# -*- coding: utf-8 -*-
""" "deprecation_reason=" on the Django mounting builders (ITEM 1).

The descriptor layer ("field()" / "Field" / the scalar shortcuts) already
accepts "deprecation_reason=" and renders "@deprecated(reason: ...)" in the
compiled SDL (see "tests/core/test_field_unification.py" - F2). This module
extends the SAME guarantee to the Django mounting builders:

- "DjangoObjectField" / "DjangoListObjectField" / "DjangoFilterListField" /
  "DjangoFilterPaginateListField" ("django_graphex.fields");
- "DjangoListObjectType.RetrieveField";
- "DjangoModelType.RetrieveField" / "QueryFields";
- "DjangoModelType.CreateField" / "DeleteField" / "UpdateField" /
  "MutationFields";
- "DjangoModelMutation.CreateField" / "DeleteField" / "UpdateField" /
  "MutationFields".

Before the fix each builder silently swallowed "deprecation_reason" into a
generic "**kwargs"/"args" sink and then EITHER lost it OR crashed at schema
build with the misleading "TypeError: Cannot convert 'old' to a graphql-core
type" from "core/_args.py". After the fix the kwarg is forwarded onto the
compiled "GraphQLField" so the SDL renders "@deprecated(reason: ...)" and
introspection reports the field deprecated with the reason.

Isolation: every Django type is built against a per-module "Registry" (the
"DjangoObjectType" / "DjangoListObjectType" / "DjangoModelMutation" paths
accept "registry="). "DjangoModelType" self-registers on the GLOBAL registry
and takes no "registry=" kwarg, so its subclasses are defined at FUNCTION scope
over distinct models to avoid duplicate-registration collisions.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from graphql import (
    GraphQLSchema,
    GraphQLString,
    get_introspection_query,
    graphql_sync,
    print_schema,
)

from django_graphex.core import ObjectType, field
from django_graphex.core.schema_compiler import compile_native_root
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoObjectField,
)
from django_graphex.mutation import DjangoModelMutation
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)
from tests.models import Category, DeprecationListModel

_REG = Registry()


class _UserType(DjangoObjectType):
    class Meta:
        model = User
        registry = _REG


class _UserListType(DjangoListObjectType):
    class Meta:
        model = User
        registry = _REG
        pagination = LimitOffsetGraphqlPagination()


class _UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        registry = _REG


def _sdl_for_query(root_cls: type) -> str:
    """Compile a native Query root and return its printed SDL.

    Args:
        root_cls: The native ObjectType-derived class to compile as the
            schema's Query root.

    Returns:
        sdl: The printed SDL text for the resulting single-query schema.
    """
    root = compile_native_root(root_cls, name="Query")
    return print_schema(GraphQLSchema(query=root))


# ---------------------------------------------------------------------------
# 1. django_graphex.fields.* mounting builders
# ---------------------------------------------------------------------------


def test_django_object_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoObjectField(_type, deprecation_reason=...)" renders "@deprecated".

    If this fails, a deprecated "DjangoObjectField" would silently drop the
    reason instead of surfacing "@deprecated(reason: ...)" in the SDL.
    """

    class _Root(ObjectType):
        user = DjangoObjectField(_UserType, deprecation_reason="use node")

    sdl = _sdl_for_query(_Root)
    assert '@deprecated(reason: "use node")' in sdl


def test_django_list_object_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoListObjectField(_type, deprecation_reason=...)" renders "@deprecated".

    If this fails, a deprecated "DjangoListObjectField" would silently drop
    the reason instead of surfacing "@deprecated(reason: ...)" in the SDL.
    """

    class _Root(ObjectType):
        users = DjangoListObjectField(_UserListType, deprecation_reason="use conn")

    sdl = _sdl_for_query(_Root)
    assert '@deprecated(reason: "use conn")' in sdl


def test_django_filter_list_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoFilterListField(_type, deprecation_reason=...)" renders "@deprecated".

    If this fails, a deprecated "DjangoFilterListField" would silently drop
    the reason instead of surfacing "@deprecated(reason: ...)" in the SDL.
    """

    class _Root(ObjectType):
        users = DjangoFilterListField(_UserType, deprecation_reason="gone soon")

    sdl = _sdl_for_query(_Root)
    assert '@deprecated(reason: "gone soon")' in sdl


def test_django_filter_paginate_list_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoFilterPaginateListField(_type, deprecation_reason=...)" renders it.

    If this fails, a deprecated "DjangoFilterPaginateListField" would
    silently drop the reason instead of surfacing "@deprecated(reason: ...)"
    in the SDL.
    """

    class _Root(ObjectType):
        users = DjangoFilterPaginateListField(
            _UserType, deprecation_reason="stale list"
        )

    sdl = _sdl_for_query(_Root)
    assert '@deprecated(reason: "stale list")' in sdl


# ---------------------------------------------------------------------------
# 2. RetrieveField / QueryFields builders on the type classes
# ---------------------------------------------------------------------------


def test_list_object_type_retrieve_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoListObjectType.RetrieveField(deprecation_reason=...)" renders it.

    If this fails, a deprecated retrieve field built via
    "DjangoListObjectType.RetrieveField" would silently drop the reason
    instead of surfacing "@deprecated(reason: ...)" in the SDL.
    """

    class _Root(ObjectType):
        user = _UserListType.RetrieveField(deprecation_reason="use node")

    sdl = _sdl_for_query(_Root)
    assert '@deprecated(reason: "use node")' in sdl


def test_model_type_retrieve_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoModelType.RetrieveField(deprecation_reason=...)" renders it.

    If this fails, a deprecated retrieve field built via
    "DjangoModelType.RetrieveField" would silently drop the reason instead
    of surfacing "@deprecated(reason: ...)" in the SDL.
    """

    class _CategoryModelType(DjangoModelType):
        class Meta:
            model = Category

    class _Root(ObjectType):
        category = _CategoryModelType.RetrieveField(deprecation_reason="use node")

    sdl = _sdl_for_query(_Root)
    assert '@deprecated(reason: "use node")' in sdl


def test_model_type_query_fields_deprecation_reason_in_sdl() -> None:
    """ "DjangoModelType.QueryFields(deprecation_reason=...)" deprecates both fields.

    Registration hygiene: a paginated "DjangoModelType" mints an auto-derived
    "<Model>ListType" container on the PROCESS-WIDE output registry (never reset
    between test modules), and "DjangoModelType" rejects "Meta.registry" so it
    cannot be scoped locally. Using "ScalarKindsModel" here collided under some
    shuffled run orders: it is the target of a reverse FK ("Author.scalar_kinds"),
    so a sibling module that force-resolves "Author"'s reverse relation caches a
    differently-shaped "ScalarKindsModelListType" globally, and the two clashed
    at assembly ("multiple types named 'ScalarKindsModelListType'"). This test
    uses the dedicated, relation-free "DeprecationListModel" instead: nothing
    else in the suite references it or builds a list container for it, so its
    generated "DeprecationListModelListType" name is globally unique and the
    assertion is order-independent.

    If this fails, the retrieve and/or list field produced by
    "DjangoModelType.QueryFields" would silently drop the deprecation reason
    instead of surfacing "@deprecated(reason: ...)" on both fields in the SDL.
    """

    class _DeprecationListModelType(DjangoModelType):
        class Meta:
            model = DeprecationListModel
            pagination = LimitOffsetGraphqlPagination()

    _retrieve, _list = _DeprecationListModelType.QueryFields(
        deprecation_reason="deprecated q"
    )

    class _Root(ObjectType):
        thing = _retrieve
        things = _list

    sdl = _sdl_for_query(_Root)
    # Both the retrieve and the list field carry the reason.
    assert sdl.count('@deprecated(reason: "deprecated q")') == 2


# ---------------------------------------------------------------------------
# 3. Mutation builders — DjangoModelType.*Field
# ---------------------------------------------------------------------------


def test_model_type_create_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoModelType.CreateField(deprecation_reason=...)" renders "@deprecated".

    If this fails, a deprecated create mutation field built via
    "DjangoModelType.CreateField" would silently drop the reason instead of
    surfacing "@deprecated(reason: ...)" in the SDL.
    """

    class _CategoryMutType(DjangoModelType):
        class Meta:
            model = Category

    class _Root(ObjectType):
        hello = field(GraphQLString)

    class _Mut(ObjectType):
        category_create = _CategoryMutType.CreateField(
            deprecation_reason="use v2 create"
        )

    query = compile_native_root(_Root, name="Query")
    mutation = compile_native_root(_Mut, name="Mutation")
    sdl = print_schema(GraphQLSchema(query=query, mutation=mutation))
    assert '@deprecated(reason: "use v2 create")' in sdl


# ---------------------------------------------------------------------------
# 4. Mutation builders — DjangoModelMutation.*Field
# ---------------------------------------------------------------------------


def test_model_mutation_create_field_deprecation_reason_in_sdl() -> None:
    """ "DjangoModelMutation.CreateField(deprecation_reason=...)" renders it.

    If this fails, a deprecated create mutation field built via
    "DjangoModelMutation.CreateField" would silently drop the reason instead
    of surfacing "@deprecated(reason: ...)" in the SDL.
    """

    class _Root(ObjectType):
        hello = field(GraphQLString)

    class _Mut(ObjectType):
        user_create = _UserMutation.CreateField(deprecation_reason="use v2 create")

    query = compile_native_root(_Root, name="Query")
    mutation = compile_native_root(_Mut, name="Mutation")
    sdl = print_schema(GraphQLSchema(query=query, mutation=mutation))
    assert '@deprecated(reason: "use v2 create")' in sdl


# ---------------------------------------------------------------------------
# 5. Introspection-level assert (one representative builder)
# ---------------------------------------------------------------------------


def test_django_object_field_reported_deprecated_via_introspection() -> None:
    """A deprecated "DjangoObjectField" is reported deprecated by introspection.

    Uses a full "DjangoGraphQLSchema" plus a live introspection query
    ("includeDeprecated: true") to prove the compiled runtime schema - not just
    the printed SDL - carries "isDeprecated" / "deprecationReason".

    If this fails, the compiled runtime schema would stop reporting a
    deprecated field's "isDeprecated"/"deprecationReason" to introspection
    clients, even if the printed SDL still shows "@deprecated".
    """

    # Named ``Query`` so the compiled root type is literally ``Query`` (the schema
    # builder derives the type name from the class ``__name__``), letting the
    # ``__type(name: "Query")`` lookup below resolve.
    class Query(ObjectType):
        user = DjangoObjectField(_UserType, deprecation_reason="use node instead")

    schema = DjangoGraphQLSchema(query=Query)
    # Sanity: the standard introspection query resolves without errors.
    result = graphql_sync(schema.graphql_schema, get_introspection_query())
    assert result.errors is None

    # Default ``fields`` (no includeDeprecated) OMITS the deprecated field...
    hidden_query = """
    query { __type(name: "Query") { fields { name } } }
    """
    hidden = graphql_sync(schema.graphql_schema, hidden_query)
    assert hidden.errors is None
    default_names = {f["name"] for f in hidden.data["__type"]["fields"]}
    assert "user" not in default_names

    # ...but an explicit includeDeprecated:true query surfaces it with the reason.
    dep_query = """
    query {
      __type(name: "Query") {
        fields(includeDeprecated: true) {
          name
          isDeprecated
          deprecationReason
        }
      }
    }
    """
    dep_result = graphql_sync(schema.graphql_schema, dep_query)
    assert dep_result.errors is None
    user_field = next(
        f for f in dep_result.data["__type"]["fields"] if f["name"] == "user"
    )
    assert user_field["isDeprecated"] is True
    assert user_field["deprecationReason"] == "use node instead"
