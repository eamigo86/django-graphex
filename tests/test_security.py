# -*- coding: utf-8 -*-
"""Tests for the security middlewares and DjangoGraphQLSchema."""

from __future__ import annotations

import types
import warnings
from typing import TYPE_CHECKING, Any

from django.test import override_settings
from graphql import (
    ExecutionResult,
    GraphQLBoolean,
    GraphQLError,
    GraphQLString,
    graphql_sync,
)

from django_graphex import security
from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import (
    DenyAllRegistry,
    DjangoGraphQLSchema,
    collect_field_names,
)
from django_graphex.security import (
    AuthenticatedFieldsMiddleware,
    DisableIntrospectionMiddleware,
)

if TYPE_CHECKING:
    from pytest import MonkeyPatch


# --------------------------------------------------------------------------- #
# Self-contained schema: public + private query/mutation roots, a subscription #
# --------------------------------------------------------------------------- #
class _Nested(ObjectType):
    me = field(GraphQLString)  # same name as a protected top-level field

    def resolve_me(root, info):
        return "nested-me"


class _PublicQuery(ObjectType):
    public_field = field(GraphQLString)
    public_nested = field(_Nested)

    def resolve_public_field(root, info):
        return "pub"

    def resolve_public_nested(root, info):
        return _Nested()


class _PrivateQuery(ObjectType):
    me = field(GraphQLString)

    def resolve_me(root, info):
        return "me"


class _RootQuery(_PublicQuery, _PrivateQuery, ObjectType):
    pass


class _CreateThing(Mutation):
    ok = field(GraphQLBoolean)

    def mutate(root, info):
        return _CreateThing(ok=True)


class _PrivateMutation(ObjectType):
    create_thing = _CreateThing.Field()


class _RootMutation(_PrivateMutation, ObjectType):
    pass


class _Subscription(ObjectType):
    on_event = field(GraphQLString)


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


def _ctx(user: Any) -> types.SimpleNamespace:
    """Build a minimal request-context stand-in carrying "user".

    Args:
        user: The user object (real or duck-typed) to expose as
            "context.user".

    Returns:
        context: A namespace exposing "user".
    """
    return types.SimpleNamespace(user=user)


_anon = types.SimpleNamespace(
    is_authenticated=False, is_superuser=False, is_active=False
)
_authed = types.SimpleNamespace(
    is_authenticated=True, is_superuser=False, is_active=True
)
_superuser = types.SimpleNamespace(
    is_authenticated=True, is_superuser=True, is_active=True
)
#: A superuser whose account has been deactivated (is_active=False).
_inactive_superuser = types.SimpleNamespace(
    is_authenticated=True, is_superuser=True, is_active=False
)


def _run(
    query: str,
    middleware: list[Any],
    user: Any = _anon,
    context: Any = "__default__",
) -> ExecutionResult:
    """Execute a query against the shared schema with the given middleware/user.

    Args:
        query: The GraphQL query or mutation document to execute.
        middleware: The middleware stack passed through to "graphql_sync".
        user: The user exposed as "context.user" when "context" is left at
            its sentinel default.
        context: An explicit context value to use instead of building one
            from "user"; pass None to simulate a missing context.

    Returns:
        result: The execution result returned by "graphql_sync".
    """
    ctx = _ctx(user) if context == "__default__" else context
    # Native backend: execute against the graphql-core schema directly.
    # ``DjangoGraphQLSchema`` exposes the assembled ``graphql_schema``; the
    # graphene-style security middleware (objects with a ``resolve`` method)
    # are accepted by graphql-core's MiddlewareManager unchanged.
    return graphql_sync(
        _schema.graphql_schema, query, middleware=middleware, context_value=ctx
    )


# -- AC1 / AC2: introspection ------------------------------------------------ #
def test_introspection_blocked_by_default() -> None:
    """Assert introspection queries are rejected without opting in.

    If this fails, "__schema"/"__type" queries would leak schema
    structure by default instead of requiring an explicit opt-in.
    """
    mw = [DisableIntrospectionMiddleware()]
    res = _run("{ __schema { queryType { name } } }", mw)
    assert res.errors and "introspection is disabled" in str(res.errors[0])
    assert res.errors[0].extensions.get("code") == "INTROSPECTION_DISABLED"

    res_type = _run('{ __type(name: "Query") { name } }', mw)
    assert res_type.errors

    # a normal field still resolves
    ok = _run("{ publicField }", mw)
    assert ok.errors is None and ok.data["publicField"] == "pub"


def test_introspection_allowed_by_setting(monkeypatch: MonkeyPatch) -> None:
    """Assert ALLOW_INTROSPECTION=True permits introspection queries.

    If this fails, opting into introspection via settings would not
    actually allow "__schema" queries to succeed.

    Args:
        monkeypatch: Used to set ALLOW_INTROSPECTION on the settings
            instance for the duration of the test.
    """
    monkeypatch.setattr(security.graphql_api_settings, "ALLOW_INTROSPECTION", True)
    res = _run(
        "{ __schema { queryType { name } } }", [DisableIntrospectionMiddleware()]
    )
    assert res.errors is None
    assert res.data["__schema"]["queryType"]["name"]


def test_superuser_can_introspect() -> None:
    """Assert an active superuser bypasses the introspection block by default.

    If this fails, superusers would be unable to introspect the schema
    even though the bypass is enabled by default.
    """
    res = _run(
        "{ __schema { queryType { name } } }",
        [DisableIntrospectionMiddleware()],
        user=_superuser,
    )
    assert res.errors is None


def test_deactivated_superuser_cannot_introspect() -> None:
    """Assert a DEACTIVATED superuser does not get the introspection bypass.

    Regression for the 2.1.0 defect: the bypass tested "is_superuser" only,
    so a user whose account had been deactivated kept full "__schema" access
    on any backend that does not run Django's "user_can_authenticate" check
    (token / JWT), unlike every sibling superuser check in the package.

    If this fails, deactivating a compromised or off-boarded superuser would
    not revoke its ability to dump the schema.
    """
    res = _run(
        "{ __schema { queryType { name } } }",
        [DisableIntrospectionMiddleware()],
        user=_inactive_superuser,
    )
    assert res.errors and "introspection is disabled" in str(res.errors[0])
    assert res.errors[0].extensions.get("code") == "INTROSPECTION_DISABLED"


def test_superuser_blocked_when_bypass_off(monkeypatch: MonkeyPatch) -> None:
    """Assert disabling INTROSPECTION_ALLOW_SUPERUSER blocks superusers too.

    If this fails, turning off the superuser bypass setting would not
    actually re-apply the introspection block to superusers.

    Args:
        monkeypatch: Used to set INTROSPECTION_ALLOW_SUPERUSER to False
            on the settings instance for the duration of the test.
    """
    monkeypatch.setattr(
        security.graphql_api_settings, "INTROSPECTION_ALLOW_SUPERUSER", False
    )
    res = _run(
        "{ __schema { queryType { name } } }",
        [DisableIntrospectionMiddleware()],
        user=_superuser,
    )
    assert res.errors


def test_introspection_without_context_does_not_crash() -> None:
    """Assert a missing request context still blocks introspection cleanly.

    If this fails, a None context would raise an unhandled
    AttributeError instead of being treated as a non-superuser and
    blocked normally.
    """
    res = _run(
        "{ __schema { queryType { name } } }",
        [DisableIntrospectionMiddleware()],
        context=None,
    )
    # Blocked (treated as non-superuser), not an AttributeError crash.
    assert res.errors and "introspection is disabled" in str(res.errors[0])


# -- AC3: field-level auth --------------------------------------------------- #
def test_private_field_requires_auth() -> None:
    """Assert an anonymous caller is denied a protected top-level field.

    If this fails, "AuthenticatedFieldsMiddleware" would let an
    unauthenticated caller read a field it is supposed to gate.
    """
    res = _run("{ me }", [AuthenticatedFieldsMiddleware()], user=_anon)
    assert res.errors and "Authentication required" in str(res.errors[0])
    assert res.errors[0].extensions.get("code") == "UNAUTHENTICATED"


def test_private_field_allows_authenticated() -> None:
    """Assert an authenticated caller can read a protected top-level field.

    If this fails, "AuthenticatedFieldsMiddleware" would wrongly deny an
    authenticated caller access to a field it should permit.
    """
    res = _run("{ me }", [AuthenticatedFieldsMiddleware()], user=_authed)
    assert res.errors is None and res.data["me"] == "me"


def test_public_field_never_gated() -> None:
    """Assert a public (unprotected) top-level field is never gated.

    If this fails, the middleware would incorrectly require
    authentication for a field that was never listed as protected.
    """
    res = _run("{ publicField }", [AuthenticatedFieldsMiddleware()], user=_anon)
    assert res.errors is None and res.data["publicField"] == "pub"


def test_nested_field_not_gated() -> None:
    """Assert a nested field sharing a protected field's name is not gated.

    "publicNested" is public; its child is named "me" (a protected
    top-level name) but nested fields (root is not None) are never
    gated.

    If this fails, the middleware would gate a nested field purely
    because its name coincides with a protected top-level field name.
    """
    res = _run("{ publicNested { me } }", [AuthenticatedFieldsMiddleware()], user=_anon)
    assert res.errors is None and res.data["publicNested"]["me"] == "nested-me"


def test_root_value_does_not_disable_field_auth() -> None:
    """Assert a configured "root_value" does not switch field auth off.

    Regression for the 2.1.0 defect: the middleware used "root is not None"
    as a proxy for "nested field", but "root_value" is a public, documented
    seam (a "GraphQLView" kwarg, a class attribute and an overridable
    "get_root_value"). Setting it made EVERY protected top-level field
    resolve for anonymous callers.

    If this fails, any project passing a root value loses private-field
    protection entirely on the HTTP view and on both subscription
    transports.
    """
    import json

    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from django_graphex.views import GraphQLView

    def _post(**view_kwargs: Any) -> dict[str, Any]:
        view = GraphQLView.as_view(
            schema=_schema, middleware=[AuthenticatedFieldsMiddleware()], **view_kwargs
        )
        request = RequestFactory().post(
            "/graphql",
            data=json.dumps({"query": "{ me }"}),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        return json.loads(view(request).content)

    # Control: the default view (no root value) denies the anonymous caller.
    assert _post()["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"
    # The seam must not change that.
    seamed = _post(root_value={"x": 1})
    assert seamed["errors"][0]["extensions"]["code"] == "UNAUTHENTICATED"
    assert seamed["data"] == {"me": None}


def test_top_level_is_detected_from_the_resolve_path(
    monkeypatch: MonkeyPatch,
) -> None:
    """Assert the top-level predicate reads the resolve path, not the root value.

    Exercises the four path shapes with a non-None root value in play: a
    top-level field ("me"), a nested field, a field inside a list element
    (the path carries an integer index) and a top-level field reached
    through an inline fragment.

    If this fails, the middleware either misses a genuine top-level field
    (a leak) or gates a nested one (a false denial) once a root value is
    configured.

    Args:
        monkeypatch: Used to set PROTECTED_FIELDS on the settings instance
            for the duration of the test.
    """
    from graphql import GraphQLField, GraphQLList, GraphQLObjectType, GraphQLSchema

    item = GraphQLObjectType(
        "Item", {"me": GraphQLField(GraphQLString, resolve=lambda *_: "nested-me")}
    )
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "Query",
            {
                "me": GraphQLField(GraphQLString, resolve=lambda *_: "me"),
                "nested": GraphQLField(item, resolve=lambda *_: object()),
                "items": GraphQLField(
                    GraphQLList(item), resolve=lambda *_: [object(), object()]
                ),
            },
        )
    )
    monkeypatch.setattr(security.graphql_api_settings, "PROTECTED_FIELDS", ("me",))

    def _exec(query: str) -> ExecutionResult:
        return graphql_sync(
            schema,
            query,
            middleware=[AuthenticatedFieldsMiddleware()],
            context_value=_ctx(_anon),
            root_value={"x": 1},
        )

    # Top level, plain and through an inline fragment: both gated.
    for query in ("{ me }", "{ ... on Query { me } }"):
        res = _exec(query)
        assert res.errors and "Authentication required" in str(res.errors[0]), query

    # Nested, and nested inside a list element (path = ['items', 0, 'me']).
    assert _exec("{ nested { me } }").data == {"nested": {"me": "nested-me"}}
    assert _exec("{ items { me } }").data == {
        "items": [{"me": "nested-me"}, {"me": "nested-me"}]
    }


def test_private_mutation_requires_auth() -> None:
    """Assert a protected mutation is denied to anonymous callers, allowed to authed ones.

    If this fails, "AuthenticatedFieldsMiddleware" would not extend its
    field-level gating to mutation fields.
    """
    mw = [AuthenticatedFieldsMiddleware()]
    res = _run("mutation { createThing { ok } }", mw, user=_anon)
    assert res.errors
    ok = _run("mutation { createThing { ok } }", mw, user=_authed)
    assert ok.errors is None and ok.data["createThing"]["ok"] is True


# -- AC4: subscriptions (symmetric with query/mutation) ---------------------- #
def test_private_subscription_protects_listed_fields() -> None:
    """Assert a field listed under private_subscription is marked protected.

    If this fails, "private_subscription" fields would not be recorded
    in the schema's protected-field registry.
    """
    assert "onEvent" in _schema.graphql_schema._gde_protected_fields


def test_subscriptions_not_protected_without_private_subscription() -> None:
    """Assert a plain "subscription" root protects nothing by itself.

    A "subscription" alone protects nothing — only "private_subscription"
    does.

    If this fails, declaring a subscription root would implicitly
    protect its fields even without an explicit private_subscription.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(
            query=_RootQuery, private_query=_PrivateQuery, subscription=_Subscription
        )
    assert "onEvent" not in s.graphql_schema._gde_protected_fields


def test_private_subscription_subset() -> None:
    """Assert only fields listed under private_subscription are protected.

    If this fails, listing a subset of subscription fields as private
    would either protect none of them or protect the whole subscription
    root.
    """

    class _SubTwo(ObjectType):
        on_a = field(GraphQLString)
        on_b = field(GraphQLString)

    class _PrivateSub(ObjectType):
        on_a = field(GraphQLString)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(
            query=_RootQuery, subscription=_SubTwo, private_subscription=_PrivateSub
        )
    reg = s.graphql_schema._gde_protected_fields
    assert "onA" in reg and "onB" not in reg


def test_anonymous_can_subscribe_to_public_subscription_field() -> None:
    """Audit rank 12: positive mirror of "test_private_subscription_protects_*".

    An AnonymousUser MUST be allowed onto a PUBLIC (unprotected)
    subscription field. "AuthenticatedFieldsMiddleware" gates only the
    fields named in the schema's protected set; a subscription field
    that is NOT in that set passes through unchanged regardless of the
    user — the symmetric counterpart of the private-subscription
    protection check above. Here "onB" is public (only "onA" is listed
    as "private_subscription"), so an anonymous subscribe to "onB" must
    NOT raise.

    If this fails, the middleware would wrongly gate a public
    subscription field, or the control assertion for the protected
    field would stop raising, making the positive check vacuous.

    Raises:
        GraphQLError: Expected from the control assertion on the
            protected field and asserted via pytest.raises.
    """

    class _SubTwo(ObjectType):
        on_a = field(GraphQLString)
        on_b = field(GraphQLString)

    class _PrivateSub(ObjectType):
        on_a = field(GraphQLString)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(
            query=_RootQuery, subscription=_SubTwo, private_subscription=_PrivateSub
        )

    reg = s.graphql_schema._gde_protected_fields
    # Precondition: onB is public (unprotected); onA is protected.
    assert "onB" not in reg and "onA" in reg

    mw = AuthenticatedFieldsMiddleware()
    sentinel = object()

    def _next(root, info, **kwargs):
        return sentinel

    # Top-level subscribe (root is None), anonymous user, PUBLIC field 'onB'.
    info = types.SimpleNamespace(
        field_name="onB",
        schema=s.graphql_schema,
        context=_ctx(_anon),
    )
    # Must pass straight through to the resolver — no Authentication error.
    assert mw.resolve(_next, None, info) is sentinel

    # Control: the PROTECTED field 'onA' still rejects the same anonymous user,
    # proving the positive path above is not vacuous.
    import pytest

    info_protected = types.SimpleNamespace(
        field_name="onA",
        schema=s.graphql_schema,
        context=_ctx(_anon),
    )
    with pytest.raises(GraphQLError):
        mw.resolve(_next, None, info_protected)


def test_disjoint_public_private_subscription_roots_are_unioned() -> None:
    """Public-only + disjoint private-only roots -> the schema exposes the union.

    If this fails, combining a public subscription root with a disjoint
    private subscription root would drop fields instead of exposing
    both.
    """

    class _PubSub(ObjectType):
        public_event = field(GraphQLString)

    class _PrivSub(ObjectType):
        secret_event = field(GraphQLString)

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


def test_disjoint_public_private_query_roots_are_unioned() -> None:
    """The same union behavior applies to the query root.

    If this fails, combining a public query root with a disjoint
    private query root would drop fields instead of exposing both.
    """

    class _PubQ(ObjectType):
        pub_only = field(GraphQLString)

    class _PrivQ(ObjectType):
        priv_only = field(GraphQLString)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        s = DjangoGraphQLSchema(query=_PubQ, private_query=_PrivQ)
    q = s.graphql_schema.query_type
    assert {"pubOnly", "privOnly"} <= set(q.fields)
    reg = s.graphql_schema._gde_protected_fields
    assert "privOnly" in reg and "pubOnly" not in reg


def test_plain_schema_fallback_uses_protected_fields_only(
    monkeypatch: MonkeyPatch,
) -> None:
    """Assert a bare graphql-core schema falls back to the PROTECTED_FIELDS setting.

    A bare graphql-core schema carries neither the native
    extensions['gdx_protected_fields'] marker nor the legacy
    "_gde_protected_fields" attribute, so "get_protected_fields" falls
    through to the PROTECTED_FIELDS setting (steps 1+2 miss, step 3
    hits).

    If this fails, a schema built outside "DjangoGraphQLSchema" would
    either wrongly protect nothing regardless of settings, or would
    crash instead of falling back gracefully.

    Args:
        monkeypatch: Used to set PROTECTED_FIELDS on the settings
            instance for the duration of the test.
    """
    # A bare graphql-core schema carries neither the native
    # ``extensions['gdx_protected_fields']`` marker nor the legacy
    # ``_gde_protected_fields`` attribute, so ``get_protected_fields`` falls
    # through to the ``PROTECTED_FIELDS`` setting (steps 1+2 miss, step 3 hits).
    from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

    plain = GraphQLSchema(
        query=GraphQLObjectType("Query", {"me": GraphQLField(GraphQLString)})
    )
    mw = AuthenticatedFieldsMiddleware()
    fake_info = types.SimpleNamespace(schema=plain)

    # No settings -> nothing protected (no auto-subscription magic).
    assert mw.get_protected_fields(fake_info) == set()

    monkeypatch.setattr(
        security.graphql_api_settings, "PROTECTED_FIELDS", ("me", "onEvent")
    )
    assert mw.get_protected_fields(fake_info) == {"me", "onEvent"}


# -- AC5: warning + property read ------------------------------------------- #
def test_warning_when_middleware_absent() -> None:
    """Assert building a schema with private fields but no middleware warns.

    If this fails, declaring private_query fields without configuring
    the authentication middleware would silently ship an unprotected
    schema instead of warning the developer.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        DjangoGraphQLSchema(query=_RootQuery, private_query=_PrivateQuery)
    assert any(issubclass(w.category, RuntimeWarning) for w in caught)


def test_no_warning_when_middleware_configured() -> None:
    """Assert configuring the auth middleware suppresses the missing-middleware warning.

    v2.0 reads the auth-middleware config from the single DJANGO_GRAPHEX
    namespace ONLY (the legacy GRAPHENE namespace is no longer consulted
    — see "_auth_middleware_configured"). The behavioral assertion is
    unchanged: when the middleware IS configured, no RuntimeWarning is
    emitted.

    If this fails, configuring the middleware under DJANGO_GRAPHEX would
    still trigger the "middleware absent" warning as a false positive.
    """
    # v2.0 reads the auth-middleware config from the single ``DJANGO_GRAPHEX``
    # namespace ONLY (the legacy ``GRAPHENE`` namespace is no longer consulted —
    # see ``_auth_middleware_configured``). The behavioral assertion is unchanged:
    # when the middleware IS configured, no RuntimeWarning is emitted.
    graphex_conf = {
        "SCHEMA": "tests.schema.schema",
        "MIDDLEWARE": ["django_graphex.security.AuthenticatedFieldsMiddleware"],
    }
    with override_settings(DJANGO_GRAPHEX=graphex_conf):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            DjangoGraphQLSchema(query=_RootQuery, private_query=_PrivateQuery)
    assert not any(issubclass(w.category, RuntimeWarning) for w in caught)


# -- AC6: helpers + imports -------------------------------------------------- #
def test_collect_field_names() -> None:
    """Assert "collect_field_names" lists a type's fields and handles None.

    If this fails, the helper would either miss declared field names or
    crash instead of returning an empty set for a None object type.
    """
    assert collect_field_names(_PrivateQuery) == frozenset({"me"})
    assert collect_field_names(None) == frozenset()


def test_django_graphql_schema_query_none_raises_graphql_error() -> None:
    """Assert DjangoGraphQLSchema(query=None) raises GraphQLError.

    Previously graphene silently built a schema with no query root; the
    explicit guard makes the failure loud and consistent across
    backends.

    If this fails, omitting the query root would silently build a
    broken schema instead of failing loudly at construction time.

    Raises:
        GraphQLError: Expected from "DjangoGraphQLSchema" and asserted
            via pytest.raises.
    """
    import pytest
    from graphql import GraphQLError

    with pytest.raises(GraphQLError):
        DjangoGraphQLSchema(query=None)


def test_deny_all_registry() -> None:
    """Assert "DenyAllRegistry" reports every key as contained (deny-all).

    If this fails, the deny-all registry stand-in would not behave as an
    unconditional "everything is present" container.
    """
    registry = DenyAllRegistry()
    assert "anything" in registry and "another" in registry


def test_imports() -> None:
    """Assert security/schema symbols import only from their submodules.

    v2.0 submodule-only API: these symbols import from their submodule
    (django_graphex.security / django_graphex.schema), NOT the package
    root.

    If this fails, either a symbol would be missing from its submodule,
    or it would have regressed into being re-exported at the package
    root, widening the public API surface unintentionally.
    """
    import django_graphex as g
    from django_graphex.schema import (
        DenyAllRegistry,
        DjangoGraphQLSchema,
        collect_field_names,
    )
    from django_graphex.security import (
        AuthenticatedFieldsMiddleware,
        DisableIntrospectionMiddleware,
    )

    for obj in (
        DisableIntrospectionMiddleware,
        AuthenticatedFieldsMiddleware,
        DjangoGraphQLSchema,
        collect_field_names,
        DenyAllRegistry,
    ):
        assert obj is not None

    for name in (
        "DisableIntrospectionMiddleware",
        "AuthenticatedFieldsMiddleware",
        "DjangoGraphQLSchema",
        "collect_field_names",
        "DenyAllRegistry",
    ):
        assert not hasattr(g, name), (
            f"{name} must not be re-exported at the package root"
        )
