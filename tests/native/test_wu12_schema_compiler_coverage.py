"""WU12 Phase-5 carry-forward coverage — native/schema_compiler.py.

Lifts ``native/schema_compiler.py`` branch coverage to >=95% by exercising the
field-dispatch arms the existing ``tests/native/`` suite did not reach: explicit
``name=`` rendering, scalar/declared/plain-object arg conversion, the resolver
fallback, wrapped django-output targets, the paginate-list inner-non-null shape +
pagination args, the ``root is None`` short-circuit, and the subscription-field
arm (duck-typed, no channels import).

Each test asserts a real compiled shape (field type, args, resolver) — not just
line execution. All run under GDX_BACKEND=native.

Run:
  GDX_BACKEND=native .venv/bin/python -m pytest -q tests/native/test_wu12_schema_compiler_coverage.py
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import pytest
from graphql import (
    GraphQLInt,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLString,
)
from graphql.execution import default_field_resolver

pytestmark = pytest.mark.native_only


# ---------------------------------------------------------------------------
# _rendered_field_name — explicit name vs camelCase (lines 82-85)
# ---------------------------------------------------------------------------


def test_rendered_field_name_honors_explicit_name():
    """An explicit ``name=`` is returned verbatim (line 84)."""
    from django_graphex.native.schema_compiler import _rendered_field_name

    class _Field:
        name = "date"

    assert _rendered_field_name(_Field(), "date_") == "date"


def test_rendered_field_name_camelcases_when_no_explicit():
    """No explicit name -> camelCase of the snake attr name (line 85)."""
    from django_graphex.native.schema_compiler import _rendered_field_name

    class _Field:
        name = None

    assert _rendered_field_name(_Field(), "is_active") == "isActive"


# ---------------------------------------------------------------------------
# _is_subscription_field — duck-typed gate (lines 152-155)
# ---------------------------------------------------------------------------


def test_is_subscription_field_false_for_wrong_class_name():
    """A field whose class is not 'SubscriptionField' returns False (line 153)."""
    from django_graphex.native.schema_compiler import _is_subscription_field

    class NotASubField:
        type = object()

    assert _is_subscription_field(NotASubField()) is False


def test_is_subscription_field_checks_build_native_field_callable():
    """A 'SubscriptionField' whose type has _build_native_field passes (154-155)."""
    from django_graphex.native.schema_compiler import _is_subscription_field

    class _Target:
        @staticmethod
        def _build_native_field():  # pragma: no cover - identity only
            return None

    # Forge a class literally named SubscriptionField with a build-capable target.
    SubscriptionField = type("SubscriptionField", (), {"type": _Target})
    assert _is_subscription_field(SubscriptionField()) is True

    # And False when the target lacks _build_native_field (line 155 falsy arm).
    SubFieldNoBuild = type("SubscriptionField", (), {"type": object()})
    assert _is_subscription_field(SubFieldNoBuild()) is False


# ---------------------------------------------------------------------------
# _resolver_for — None source/field falls back to default (lines 249-250)
# ---------------------------------------------------------------------------


def test_resolver_for_returns_default_without_source():
    """_resolver_for(None, None) returns graphql-core default resolver (250)."""
    from django_graphex.native.schema_compiler import _resolver_for

    assert _resolver_for(None, None) is default_field_resolver
    assert _resolver_for(None, "field") is default_field_resolver


def test_resolver_for_recovers_resolve_method():
    """_resolver_for returns the source's resolve_<name> when declared."""
    from graphql import GraphQLString

    from django_graphex import ObjectType
    from django_graphex import field as native_field
    from django_graphex.native.schema_compiler import _resolver_for

    class _Src(ObjectType):
        thing = native_field(GraphQLString)

        def resolve_thing(root, info):  # noqa: N805 - native resolver
            return "ok"

    resolver = _resolver_for(_Src, "thing")
    assert resolver is not default_field_resolver
    assert callable(resolver)


# ---------------------------------------------------------------------------
# _build_scalar_field — args conversion arm (lines 217-220)
# ---------------------------------------------------------------------------


def test_build_scalar_field_converts_args():
    """A native scalar field declaring args converts them to GraphQLArgument.

    S-del-backend-11: the graphene-source fixture was replaced with the native
    ``field(GraphQLString, args={...})`` declaration (the graphene-root compile
    capability was removed; the compiler internals are native-only now).
    """
    from graphql import GraphQLArgument

    from django_graphex import field as native_field
    from django_graphex.native.schema_compiler import _build_scalar_field

    declared = native_field(
        GraphQLString, args={"name": GraphQLArgument(GraphQLString)}
    )
    gql_field = _build_scalar_field(declared, source_cls=None, field_name="greeting")
    assert gql_field.type is GraphQLString
    assert "name" in gql_field.args


# ---------------------------------------------------------------------------
# compile_declared_field — wrapped django-output target + args (421, 472)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compile_declared_field_wrapped_django_output_list():
    """A native ``field(NativeList(DjangoObjectType))`` declared field compiles to
    a list of the canonical container/node native type (wrapper preservation).

    S-del-backend-11: the graphene ``List(...)`` fixture was replaced with the
    native ``NativeList`` wrapper (the graphene-root compile capability was
    removed).
    """
    from django_graphex import ObjectType
    from django_graphex import field as native_field
    from django_graphex.native.descriptors import NativeList
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_declared_field
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _DeclCatNode(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _Holder(ObjectType):
        cats = native_field(NativeList(_DeclCatNode))

    field = _Holder._meta.fields["cats"]
    gql_field = compile_declared_field(_Holder, "cats", field)
    assert isinstance(gql_field.type, GraphQLList)
    inner = gql_field.type.of_type
    assert inner is _DeclCatNode._meta.graphql_output_type


@pytest.mark.django_db
def test_compile_declared_field_with_args():
    """A native declared field with args converts them.

    S-del-backend-11: the graphene-source fixture was replaced with the native
    ``field(GraphQLString, args={...})`` declaration.
    """
    from graphql import GraphQLArgument

    from django_graphex import ObjectType
    from django_graphex import field as native_field
    from django_graphex.native.schema_compiler import compile_declared_field

    class _Holder(ObjectType):
        echo = native_field(
            GraphQLString, args={"value": GraphQLArgument(GraphQLString)}
        )

    field = _Holder._meta.fields["echo"]
    gql_field = compile_declared_field(_Holder, "echo", field)
    assert "value" in gql_field.args


# ---------------------------------------------------------------------------
# _build_plain_object_field — args conversion arm (line 530)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_plain_object_field_with_args():
    """A native plain-ObjectType field declaring args converts them.

    S-del-backend-11: the graphene-source fixture was replaced with a native
    plain ``ObjectType`` field carrying native args.
    """
    from graphql import GraphQLArgument, GraphQLInt

    from django_graphex import ObjectType
    from django_graphex import field as native_field
    from django_graphex.native.schema_compiler import _build_plain_object_field

    class _Nested(ObjectType):
        value = native_field(GraphQLString)

    class _Holder(ObjectType):
        nested = native_field(_Nested, args={"depth": GraphQLArgument(GraphQLInt)})

    field = _Holder._meta.fields["nested"]
    gql_field = _build_plain_object_field(field, source_cls=_Holder, field_name="nested")
    assert isinstance(gql_field.type, GraphQLObjectType)
    assert "depth" in gql_field.args


# ---------------------------------------------------------------------------
# _filter_arg — no declared fields/custom -> {} ; native input None -> {} (578)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_filter_arg_empty_without_declared_fields():
    """_filter_arg returns {} when the field declares no fields/custom filters."""
    from django_graphex.native.schema_compiler import _filter_arg

    class _NoFilterField:
        fields = None
        custom_filters = None

    assert _filter_arg(_NoFilterField()) == {}


# ---------------------------------------------------------------------------
# _unwrap_to_node_type — peels graphql-core List/NonNull wrappers (line 664)
# ---------------------------------------------------------------------------


def test_unwrap_to_node_type_peels_graphql_core_wrappers():
    """A field whose .type is GraphQLList(GraphQLNonNull(node)) unwraps to node."""
    from django_graphex.native.schema_compiler import _unwrap_to_node_type

    node = GraphQLObjectType("Leaf", fields=lambda: {"x": _scalar_field()})

    class _Field:
        type = GraphQLList(GraphQLNonNull(node))

    assert _unwrap_to_node_type(_Field()) is node


def _scalar_field():
    from graphql import GraphQLField

    return GraphQLField(GraphQLString)


# ---------------------------------------------------------------------------
# _build_filter_list_field — paginate variant inner-non-null + pagination args
# (lines 698-708)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_build_filter_paginate_list_field_inner_non_null_and_args():
    """DjangoFilterPaginateListField -> [Node!] with pagination args (699, 708)."""
    from django_graphex import ObjectType as _NativeRoot
    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _PgCatType(DjangoObjectType):
        class Meta:
            model = Category
            filter_fields = ["title"]

    compile_all_outputs()

    # Pass an explicit paginator so the pagination-args branch (line 708) fires
    # regardless of the project's DEFAULT_PAGINATION_CLASS setting.
    class _PgQuery(_NativeRoot):
        cats = DjangoFilterPaginateListField(
            _PgCatType, pagination=LimitOffsetGraphqlPagination()
        )

    native_root = compile_native_root(_PgQuery, name="Query")
    field = native_root.fields["cats"]
    # [Node!]: List wrapping NonNull(node) — the paginate variant's inner non-null.
    assert isinstance(field.type, GraphQLList)
    assert isinstance(field.type.of_type, GraphQLNonNull)
    # LimitOffset pagination args are mounted directly on the field.
    assert "limit" in field.args
    assert "offset" in field.args
    assert field.args["limit"].type is GraphQLInt


# ---------------------------------------------------------------------------
# compile_native_root — root is None short-circuit (lines 736-737)
# ---------------------------------------------------------------------------


def test_compile_native_root_none_returns_none():
    """compile_native_root(None, ...) returns None (737)."""
    from django_graphex.native.schema_compiler import compile_native_root

    assert compile_native_root(None, name="Subscription") is None


# ---------------------------------------------------------------------------
# compile_native_root — subscription-field arm (line 763, 770)
# ---------------------------------------------------------------------------


def test_compile_native_root_builds_subscription_field():
    """A SubscriptionField on the root compiles via _build_native_field (763, 770).

    Duck-typed: no channels import. We forge a SubscriptionField-named field whose
    ``type`` exposes ``_build_native_field`` returning a real GraphQLField, then
    assert the native root mounts THAT exact field under the camelCased wire name.
    Using a forged root (plain ``_meta`` namespace) keeps graphene out of the way:
    the compiler only reads ``root._meta.fields`` and the duck-typed gate.
    """
    from types import SimpleNamespace

    from graphql import GraphQLField

    from django_graphex.native.schema_compiler import compile_native_root

    built = GraphQLField(GraphQLString, resolve=lambda root, info: "x")

    class _SubTarget:
        @staticmethod
        def _build_native_field():
            return built

    # A field object literally named 'SubscriptionField' whose .type is the
    # build-capable target — exactly what _is_subscription_field gates on.
    SubscriptionField = type(
        "SubscriptionField", (), {"name": None, "type": _SubTarget}
    )
    sub_field = SubscriptionField()

    # A real class (so _collect_root_attrs can walk __mro__) carrying a plain
    # _meta namespace with the forged subscription field.
    class _SubRoot:
        _meta = SimpleNamespace(fields={"on_thing": sub_field})

    native_root = compile_native_root(_SubRoot, name="Subscription")
    assert "onThing" in native_root.fields
    assert native_root.fields["onThing"] is built
