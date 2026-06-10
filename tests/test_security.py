# -*- coding: utf-8 -*-
"""Tests for the security middlewares and DjangoGraphQLSchema."""

import types
import warnings

import graphene
from django.test import override_settings

from django_graphex import (
    AuthenticatedFieldsMiddleware,
    DenyAllRegistry,
    DisableIntrospectionMiddleware,
    DjangoGraphQLSchema,
    collect_field_names,
    security,
)


# --------------------------------------------------------------------------- #
# Self-contained schema: public + private query/mutation roots, a subscription #
# --------------------------------------------------------------------------- #
class _Nested(graphene.ObjectType):
    me = graphene.String()  # same name as a protected top-level field

    def resolve_me(root, info):
        return "nested-me"


class _PublicQuery(graphene.ObjectType):
    public_field = graphene.String()
    public_nested = graphene.Field(_Nested)

    def resolve_public_field(root, info):
        return "pub"

    def resolve_public_nested(root, info):
        return _Nested()


class _PrivateQuery(graphene.ObjectType):
    me = graphene.String()

    def resolve_me(root, info):
        return "me"


class _RootQuery(_PublicQuery, _PrivateQuery, graphene.ObjectType):
    pass


class _CreateThing(graphene.Mutation):
    ok = graphene.Boolean()

    def mutate(root, info):
        return _CreateThing(ok=True)


class _PrivateMutation(graphene.ObjectType):
    create_thing = _CreateThing.Field()


class _RootMutation(_PrivateMutation, graphene.ObjectType):
    pass


class _Subscription(graphene.ObjectType):
    on_event = graphene.String()


with warnings.catch_warnings():  # middleware not in GRAPHENE config during tests
    warnings.simplefilter("ignore", RuntimeWarning)
    _schema = DjangoGraphQLSchema(
        query=_RootQuery,
        private_query=_PrivateQuery,
        mutation=_RootMutation,
        private_mutation=_PrivateMutation,
        subscription=_Subscription,
        private_subscription=_Subscription,  # protect every subscription
    )


def _ctx(user):
    return types.SimpleNamespace(user=user)


_anon = types.SimpleNamespace(is_authenticated=False, is_superuser=False)
_authed = types.SimpleNamespace(is_authenticated=True, is_superuser=False)
_superuser = types.SimpleNamespace(is_authenticated=True, is_superuser=True)


def _run(query, middleware, user=_anon, context="__default__"):
    ctx = _ctx(user) if context == "__default__" else context
    return _schema.execute(query, middleware=middleware, context=ctx)


# -- AC1 / AC2: introspection ------------------------------------------------ #
def test_introspection_blocked_by_default():
    mw = [DisableIntrospectionMiddleware()]
    res = _run("{ __schema { queryType { name } } }", mw)
    assert res.errors and "introspection is disabled" in str(res.errors[0])
    assert res.errors[0].extensions.get("code") == "INTROSPECTION_DISABLED"

    res_type = _run('{ __type(name: "Query") { name } }', mw)
    assert res_type.errors

    # a normal field still resolves
    ok = _run("{ publicField }", mw)
    assert ok.errors is None and ok.data["publicField"] == "pub"


def test_introspection_allowed_by_setting(monkeypatch):
    monkeypatch.setattr(security.graphql_api_settings, "ALLOW_INTROSPECTION", True)
    res = _run(
        "{ __schema { queryType { name } } }", [DisableIntrospectionMiddleware()]
    )
    assert res.errors is None
    assert res.data["__schema"]["queryType"]["name"]


def test_superuser_can_introspect():
    res = _run(
        "{ __schema { queryType { name } } }",
        [DisableIntrospectionMiddleware()],
        user=_superuser,
    )
    assert res.errors is None


def test_superuser_blocked_when_bypass_off(monkeypatch):
    monkeypatch.setattr(
        security.graphql_api_settings, "INTROSPECTION_ALLOW_SUPERUSER", False
    )
    res = _run(
        "{ __schema { queryType { name } } }",
        [DisableIntrospectionMiddleware()],
        user=_superuser,
    )
    assert res.errors


def test_introspection_without_context_does_not_crash():
    res = _run(
        "{ __schema { queryType { name } } }",
        [DisableIntrospectionMiddleware()],
        context=None,
    )
    # Blocked (treated as non-superuser), not an AttributeError crash.
    assert res.errors and "introspection is disabled" in str(res.errors[0])


# -- AC3: field-level auth --------------------------------------------------- #
def test_private_field_requires_auth():
    res = _run("{ me }", [AuthenticatedFieldsMiddleware()], user=_anon)
    assert res.errors and "Authentication required" in str(res.errors[0])
    assert res.errors[0].extensions.get("code") == "UNAUTHENTICATED"


def test_private_field_allows_authenticated():
    res = _run("{ me }", [AuthenticatedFieldsMiddleware()], user=_authed)
    assert res.errors is None and res.data["me"] == "me"


def test_public_field_never_gated():
    res = _run("{ publicField }", [AuthenticatedFieldsMiddleware()], user=_anon)
    assert res.errors is None and res.data["publicField"] == "pub"


def test_nested_field_not_gated():
    # `publicNested` is public; its child is named `me` (a protected top-level
    # name) but nested fields (root is not None) are never gated.
    res = _run("{ publicNested { me } }", [AuthenticatedFieldsMiddleware()], user=_anon)
    assert res.errors is None and res.data["publicNested"]["me"] == "nested-me"


def test_private_mutation_requires_auth():
    mw = [AuthenticatedFieldsMiddleware()]
    res = _run("mutation { createThing { ok } }", mw, user=_anon)
    assert res.errors
    ok = _run("mutation { createThing { ok } }", mw, user=_authed)
    assert ok.errors is None and ok.data["createThing"]["ok"] is True


# -- AC4: subscriptions (symmetric with query/mutation) ---------------------- #
def test_private_subscription_protects_listed_fields():
    assert "onEvent" in _schema.graphql_schema._gde_protected_fields


def test_subscriptions_not_protected_without_private_subscription():
    # A `subscription` alone protects nothing — only `private_subscription` does.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(
            query=_RootQuery, private_query=_PrivateQuery, subscription=_Subscription
        )
    assert "onEvent" not in s.graphql_schema._gde_protected_fields


def test_private_subscription_subset():
    class _SubTwo(graphene.ObjectType):
        on_a = graphene.String()
        on_b = graphene.String()

    class _PrivateSub(graphene.ObjectType):
        on_a = graphene.String()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(
            query=_RootQuery, subscription=_SubTwo, private_subscription=_PrivateSub
        )
    reg = s.graphql_schema._gde_protected_fields
    assert "onA" in reg and "onB" not in reg


def test_disjoint_public_private_subscription_roots_are_unioned():
    """Public-only + disjoint private-only roots -> the schema exposes the union."""

    class _PubSub(graphene.ObjectType):
        public_event = graphene.String()

    class _PrivSub(graphene.ObjectType):
        secret_event = graphene.String()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(
            query=_RootQuery, subscription=_PubSub, private_subscription=_PrivSub
        )
    sub = s.graphql_schema.subscription_type
    # Both fields exist even though they live in two disjoint roots.
    assert {"publicEvent", "secretEvent"} <= set(sub.fields)
    reg = s.graphql_schema._gde_protected_fields
    assert "secretEvent" in reg and "publicEvent" not in reg


def test_disjoint_public_private_query_roots_are_unioned():
    """The same union behavior applies to the query root."""

    class _PubQ(graphene.ObjectType):
        pub_only = graphene.String()

    class _PrivQ(graphene.ObjectType):
        priv_only = graphene.String()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(query=_PubQ, private_query=_PrivQ)
    q = s.graphql_schema.query_type
    assert {"pubOnly", "privOnly"} <= set(q.fields)
    reg = s.graphql_schema._gde_protected_fields
    assert "privOnly" in reg and "pubOnly" not in reg


def test_plain_schema_fallback_uses_protected_fields_only(monkeypatch):
    plain = graphene.Schema(query=_RootQuery)
    mw = AuthenticatedFieldsMiddleware()
    fake_info = types.SimpleNamespace(schema=plain.graphql_schema)

    # No settings -> nothing protected (no auto-subscription magic).
    assert mw.get_protected_fields(fake_info) == set()

    monkeypatch.setattr(
        security.graphql_api_settings, "PROTECTED_FIELDS", ("me", "onEvent")
    )
    assert mw.get_protected_fields(fake_info) == {"me", "onEvent"}


# -- AC5: warning + property read ------------------------------------------- #
def test_warning_when_middleware_absent():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        DjangoGraphQLSchema(query=_RootQuery, private_query=_PrivateQuery)
    assert any(issubclass(w.category, RuntimeWarning) for w in caught)


def test_no_warning_when_middleware_configured():
    graphene_conf = {
        "SCHEMA": "tests.schema.schema",
        "MIDDLEWARE": ["django_graphex.AuthenticatedFieldsMiddleware"],
    }
    with override_settings(GRAPHENE=graphene_conf):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            DjangoGraphQLSchema(query=_RootQuery, private_query=_PrivateQuery)
    assert not any(issubclass(w.category, RuntimeWarning) for w in caught)


# -- AC6: helpers + imports -------------------------------------------------- #
def test_collect_field_names():
    assert collect_field_names(_PrivateQuery) == frozenset({"me"})
    assert collect_field_names(None) == frozenset()


def test_deny_all_registry():
    registry = DenyAllRegistry()
    assert "anything" in registry and "another" in registry


def test_imports():
    import django_graphex as g

    for name in (
        "DisableIntrospectionMiddleware",
        "AuthenticatedFieldsMiddleware",
        "DjangoGraphQLSchema",
        "collect_field_names",
        "DenyAllRegistry",
    ):
        assert hasattr(g, name)
