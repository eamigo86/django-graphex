"""S-ROOTS-j: native ``<Model>Filterinput`` name-collision fix (#1571).

A model exposed via BOTH a nested/relation list path (``DjangoNestedListObjectField`` /
auto-derived relation list) AND a root list-object / flat-paginate path, where its
node ``DjangoObjectType`` declares a custom ``@filter_field``, used to build TWO
distinct ``GraphQLInputObjectType`` instances sharing the name
``<Model>Filterinput`` — one WITHOUT the custom filter (the nested path dropped it)
and one WITH it (the root path) — triggering graphql-core's

    TypeError: Schema must contain uniquely named types but contains multiple
    types named '<Model>Filterinput'.

Root cause: ``DjangoNestedListObjectField.__init__`` skipped
``DjangoListObjectField.__init__`` (to avoid eagerly building the arg) and never
set ``self.custom_filters``, so ``schema_compiler._filter_arg`` built the nested
filter input WITHOUT the node type's ``@filter_field`` methods. Fix (Option B):
propagate the node type's ``@filter_field`` custom filters into the nested path so
EVERY path produces ONE identical shape — the cache then dedupes and the
single-shape SDL name stays byte-identical ``<Model>Filterinput`` (#1533).
"""
from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_native_filter_input_collision_multi_path_same_model():
    """RED→GREEN: a model exposed via nested + flat-paginate filter paths with a
    custom ``@filter_field`` must assemble a native schema with NO duplicate-name
    TypeError, and BOTH filter inputs must carry the custom ``search`` filter.

    Pre-fix: the nested/relation path drops ``search`` → two distinct
    ``OrderChildFilterinput`` shapes → ``Schema must contain uniquely named
    types but contains multiple types named 'OrderChildFilterinput'``.
    """
    from graphql import GraphQLString

    from django_graphex import ObjectType
    from django_graphex.fields import (
        DjangoFilterPaginateListField,
        DjangoListObjectField,
        DjangoNestedListObjectField,
    )
    from django_graphex.filtering import filter_field
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import OrderChild, OrderParent

    # Node type with a custom @filter_field. This is the SHAPE-divergence source:
    # the custom `search` arg must appear on EVERY path that exposes OrderChild.
    class _CollChildType(DjangoObjectType):
        class Meta:
            model = OrderChild
            filter_fields = {"id": ("exact",), "text": ("icontains",)}

        @filter_field(GraphQLString, description="Full-text search")
        def search(cls, queryset, info, value):
            return queryset.filter(text__icontains=value)

    class _CollChildListType(DjangoListObjectType):
        class Meta:
            model = OrderChild
            pagination = LimitOffsetGraphqlPagination(default_limit=10)

    class _CollParentType(DjangoObjectType):
        # Explicit nested list — the path that USED to drop `search`.
        kids = DjangoNestedListObjectField(_CollChildListType, accessor="kids")

        class Meta:
            model = OrderParent
            filter_fields = {"id": ("exact",), "title": ("icontains",)}

    class _CollParentListType(DjangoListObjectType):
        class Meta:
            model = OrderParent

    compile_all_outputs()

    class _CollQuery(ObjectType):
        # Root list-object over the parent (exposes nested `kids` filter input).
        parents = DjangoListObjectField(_CollParentListType)
        # Flat-paginate over the child WITH the custom filter (the WITH-search shape).
        kids_flat = DjangoFilterPaginateListField(
            _CollChildType,
            pagination=LimitOffsetGraphqlPagination(default_limit=10),
        )

    # The deliverable: assembling the native schema MUST NOT raise the
    # duplicate-name TypeError (pre-fix it does).
    schema = DjangoGraphQLSchema(query=_CollQuery)
    type_map = schema.graphql_schema.type_map

    # Exactly one OrderChildFilterinput type by name (no collision, no dup).
    child_filter_names = [n for n in type_map if n == "OrderChildFilterinput"]
    assert child_filter_names == ["OrderChildFilterinput"], (
        "expected exactly one 'OrderChildFilterinput' in the type map; got "
        f"{child_filter_names!r}"
    )

    # The single canonical OrderChildFilterinput must carry the custom `search`
    # filter (the union/complete shape) so both paths agree.
    child_filter = type_map["OrderChildFilterinput"]
    assert "search" in child_filter.fields, (
        "OrderChildFilterinput must expose the custom @filter_field 'search' "
        f"on every path; got fields {sorted(child_filter.fields)!r}"
    )


@pytest.mark.django_db
def test_native_nested_field_carries_custom_filters():
    """Unit-level guard: ``DjangoNestedListObjectField`` must propagate the node
    type's ``@filter_field`` custom filters (it dropped them pre-fix)."""
    from graphql import GraphQLString

    from django_graphex.fields import DjangoNestedListObjectField
    from django_graphex.filtering import filter_field
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import OrderChild

    class _NestedChildType(DjangoObjectType):
        class Meta:
            model = OrderChild
            filter_fields = {"id": ("exact",), "text": ("icontains",)}

        @filter_field(GraphQLString)
        def search(cls, queryset, info, value):
            return queryset

    class _NestedChildListType(DjangoListObjectType):
        class Meta:
            model = OrderChild

    field = DjangoNestedListObjectField(_NestedChildListType, accessor="kids")

    custom_filters = getattr(field, "custom_filters", None)
    assert custom_filters, (
        "DjangoNestedListObjectField must expose the node type's @filter_field "
        f"custom filters; got {custom_filters!r}"
    )
    names = [name for name, _fn, _meta in custom_filters]
    assert "search" in names, (
        f"nested field custom_filters must include 'search'; got {names!r}"
    )


@pytest.mark.django_db
def test_native_custom_filter_search_executes_end_to_end():
    """GATE (execution): a real ``filter: { search: ... }`` custom-filter query
    over a flat-paginate field must EXECUTE and actually filter rows under native.

    This exercises three native-backend behaviors that previously broke a custom
    ``@filter_field`` end-to-end:
      1. the schema assembles (no PostFilterinput-style collision);
      2. ``to_q`` SKIPS the custom-filter key (``search``) instead of calling
         ``.items()`` on its scalar value (``'str' object has no attribute
         'items'``);
      3. ``apply_custom_filters`` reads the native DICT delivery shape so the
         custom filter actually runs (it returned everything before, because the
         dict had no ``search`` attribute).
    """
    from graphql import GraphQLString, graphql_sync

    from django_graphex import ObjectType
    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.filtering import filter_field
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import OrderChild, OrderParent

    class _ExecChildType(DjangoObjectType):
        class Meta:
            model = OrderChild
            filter_fields = {"id": ("exact",), "text": ("icontains",)}

        @filter_field(GraphQLString, description="search over text")
        def search(cls, queryset, info, value):
            return queryset.filter(text__icontains=value)

    compile_all_outputs()

    class _ExecQuery(ObjectType):
        kids_flat = DjangoFilterPaginateListField(
            _ExecChildType,
            pagination=LimitOffsetGraphqlPagination(default_limit=10),
        )

    schema = DjangoGraphQLSchema(query=_ExecQuery)

    parent = OrderParent.objects.create(title="P")
    OrderChild.objects.create(text="alpha match", order_parent=parent)
    OrderChild.objects.create(text="beta other", order_parent=parent)

    result = graphql_sync(
        schema.graphql_schema,
        '{ kidsFlat(filter: { search: "alpha" }) { id text } }',
    )

    assert result.errors is None, (
        "native custom @filter_field query raised errors (to_q .items() crash "
        f"or dict-delivery skip?): {result.errors!r}"
    )
    texts = [row["text"] for row in result.data["kidsFlat"]]
    assert texts == ["alpha match"], (
        "custom 'search' @filter_field did not actually filter under native; "
        f"got {texts!r} (it returned everything before the dict-delivery fix)"
    )


@pytest.mark.django_db
def test_native_single_filter_path_name_unchanged_byte_parity():
    """SDL byte-parity guard (#1533): a model with a SINGLE filter shape must
    STILL render its filter input as exactly ``<Model>Filterinput`` (lowercase
    'i'), with the fix NOT introducing any suffix/disambiguator for the common
    single-path case.
    """
    from graphql import print_type

    from django_graphex import ObjectType
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import OrderParent

    class _SingleParentType(DjangoObjectType):
        class Meta:
            model = OrderParent
            filter_fields = {"id": ("exact",), "title": ("icontains",)}

    class _SingleParentListType(DjangoListObjectType):
        class Meta:
            model = OrderParent

    compile_all_outputs()

    class _SingleQuery(ObjectType):
        parents = DjangoListObjectField(_SingleParentListType)

    schema = DjangoGraphQLSchema(query=_SingleQuery)
    type_map = schema.graphql_schema.type_map

    # The name must be EXACTLY 'OrderParentFilterinput' (graphene-quirk casing,
    # #1533) — no PascalCase 'FilterInput', no suffix/discriminator.
    assert "OrderParentFilterinput" in type_map, (
        "single-shape filter input must keep the byte-parity name "
        f"'OrderParentFilterinput'; type map has "
        f"{[n for n in type_map if 'Filter' in n]!r}"
    )
    sdl = print_type(type_map["OrderParentFilterinput"])
    assert sdl.startswith("input OrderParentFilterinput"), (
        f"single-shape filter input SDL header changed: {sdl.splitlines()[0]!r}"
    )
