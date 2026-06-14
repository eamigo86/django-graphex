"""WU2 (reworked): native DjangoGraphQLSchema assembly + query=None guard.

Under GDX_BACKEND=native, ``DjangoGraphQLSchema`` builds a graphql-core
``GraphQLSchema`` from the native root compiler (NO graphene.Schema for the
graphql_schema, NO duplicate-name error). ``query=None`` raises ``GraphQLError``.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


@pytest.mark.django_db
def test_native_schema_query_type_is_canonical_native_instance():
    """ANTI-TAUTOLOGY (schema level): the assembled native schema's query field
    type for the DjangoObjectField IS the canonical native instance with gdx."""
    import graphene
    from graphql import GraphQLObjectType, GraphQLSchema

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.base import get_shared_output_registry
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _AssemblyCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(graphene.ObjectType):
        category = DjangoObjectField(_AssemblyCatType)

    schema = DjangoGraphQLSchema(query=_SeedQuery)
    graphql_schema = schema.graphql_schema
    assert isinstance(graphql_schema, GraphQLSchema)

    query_type = graphql_schema.query_type
    assert isinstance(query_type, GraphQLObjectType)

    field_type = query_type.fields["category"].type
    canonical = get_shared_output_registry().get_compiled(Category)
    assert field_type is canonical, (
        "ANTI-TAUTOLOGY FAILURE: assembled query field type is not the native "
        "canonical instance — native fell back to graphene."
    )
    assert "gdx" in (field_type.extensions or {})


@pytest.mark.django_db
def test_native_schema_no_duplicate_type_name():
    """The native schema assembles without a duplicate-name TypeError."""
    import graphene

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _NoDupCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(graphene.ObjectType):
        category = DjangoObjectField(_NoDupCatType)

    # Must not raise "Schema must contain uniquely named types ...".
    schema = DjangoGraphQLSchema(query=_SeedQuery)
    type_map = schema.graphql_schema.type_map
    # The canonical Category type appears exactly once (by name).
    cat_names = [n for n in type_map if n == "_NoDupCatType"]
    assert cat_names == ["_NoDupCatType"]


@pytest.mark.django_db
def test_native_single_object_query_executes_returns_real_data():
    """GATE (resolver smoke): a native single-object query EXECUTES end-to-end.

    Builds the seed native schema, seeds a real DB row, runs ``graphql_sync``
    selecting the single-object field + a scalar subfield, and asserts REAL
    DATA is returned (not None, no errors).

    This is the execution smoke the WU2 gate lacked: the prior gate only
    asserted ``field.resolve is callable`` and never EXECUTED a query, so it
    missed that the native single-object resolver was DEAD — under native,
    ``info.parent_type`` is the WU2-compiled root ``GraphQLObjectType`` which
    carried NO ``extensions['gdx']`` and NO ``graphene_type`` alias, so
    ``utils._get_custom_resolver`` crashed with
    ``'GraphQLObjectType' object has no attribute 'graphene_type'`` →
    ``data:{'category': None}, errors:[GraphQLError(...)]``.

    Against the dead resolver this test FAILS (None + GraphQLError); after the
    fix (root carries ``extensions['gdx']`` with the source graphene class +
    ``_get_custom_resolver`` reads it via the bridge) it PASSES with real data.
    """
    import graphene
    from graphql import graphql_sync

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ExecCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ExecQuery(graphene.ObjectType):
        category = DjangoObjectField(_ExecCatType)

    schema = DjangoGraphQLSchema(query=_ExecQuery)

    row = Category.objects.create(title="Hello")

    result = graphql_sync(
        schema.graphql_schema,
        "query Q($id: ID!) { category(id: $id) { id title } }",
        variable_values={"id": str(row.pk)},
    )

    assert result.errors is None, (
        "native single-object query raised errors (dead resolver?): "
        f"{result.errors!r}"
    )
    assert result.data == {"category": {"id": str(row.pk), "title": "Hello"}}, (
        "native single-object query did not return the seeded row: "
        f"{result.data!r}"
    )


@pytest.mark.django_db
def test_native_root_type_carries_gdx_with_source_graphene_class():
    """The compiled native root carries ``extensions['gdx']`` (D8 invariant)
    whose GdxMeta exposes the SOURCE graphene root class, so dual-backend
    read-sites can recover ``resolve_<field>`` methods under native."""
    import graphene

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.compat import _gdx_graphene_type
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _GdxCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _GdxQuery(graphene.ObjectType):
        category = DjangoObjectField(_GdxCatType)

    schema = DjangoGraphQLSchema(query=_GdxQuery)
    query_type = schema.graphql_schema.query_type

    # D8: the root carries extensions['gdx'].
    assert "gdx" in (query_type.extensions or {})
    # The bridge recovers the SOURCE graphene root class (so _get_custom_resolver
    # finds resolve_<field> methods declared on the user's root).
    assert _gdx_graphene_type(query_type) is _GdxQuery


@pytest.mark.django_db
def test_native_schema_query_none_raises_graphql_error():
    """DjangoGraphQLSchema(query=None) raises GraphQLError under native."""
    from graphql import GraphQLError

    from django_graphex.schema import DjangoGraphQLSchema

    with pytest.raises(GraphQLError):
        DjangoGraphQLSchema(query=None)


@pytest.mark.django_db
def test_native_schema_build_failure_raises_not_silent_fallback():
    """A native root with an unbuildable field kind RAISES (no silent graphene
    fallback). This is the guard the discarded WU2 attempt lacked.

    WU6a added native builders for the list/filter/pagination kinds, so we
    temporarily re-register ``DjangoListObjectField`` in ``_DEFERRED_FIELD_KINDS``
    to assert the propagation path (NotImplementedError surfaces through
    ``DjangoGraphQLSchema`` rather than being swallowed by a graphene fallback)
    is STILL intact for any kind that does not yet have a builder.
    """
    import graphene

    from django_graphex.fields import DjangoListObjectField
    from django_graphex.native import schema_compiler
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _RaiseListType(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ListQuery(graphene.ObjectType):
        categories = DjangoListObjectField(_RaiseListType)

    # Temporarily mark DjangoListObjectField as deferred so the compiler raises
    # NotImplementedError, proving the loud-propagation path is still in place.
    schema_compiler._DEFERRED_FIELD_KINDS["DjangoListObjectField"] = "TEST-deferred"
    try:
        # NotImplementedError from the root compiler must propagate (loud), NOT
        # be swallowed by a try/except returning a graphene schema.
        with pytest.raises(NotImplementedError):
            DjangoGraphQLSchema(query=_ListQuery)
    finally:
        schema_compiler._DEFERRED_FIELD_KINDS.pop("DjangoListObjectField", None)
