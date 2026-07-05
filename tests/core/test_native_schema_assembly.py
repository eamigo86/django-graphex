"""WU2 (reworked): native DjangoGraphQLSchema assembly + query=None guard.

"DjangoGraphQLSchema" builds a graphql-core
"GraphQLSchema" from the native root compiler (NO graphene.Schema for the
graphql_schema, NO duplicate-name error). "query=None" raises "GraphQLError".
"""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_native_schema_query_type_is_canonical_native_instance() -> None:
    """Assert the ANTI-TAUTOLOGY invariant at the schema-assembly level.

    The assembled native schema's query field type for the
    "DjangoObjectField" IS the canonical native instance with gdx.

    If this fails, the assembled schema could be silently referencing a
    graphene-built type instead of the canonical native instance.
    """
    from graphql import GraphQLObjectType, GraphQLSchema

    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.base import get_shared_output_registry
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoObjectField
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _AssemblyCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(_NativeRoot):
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
def test_native_schema_no_duplicate_type_name() -> None:
    """Assert that the native schema assembles without a duplicate-name TypeError.

    If this fails, assembling the native schema would raise (or silently
    duplicate) a type name that should appear exactly once in the type map.
    """
    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoObjectField
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _NoDupCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(_NativeRoot):
        category = DjangoObjectField(_NoDupCatType)

    # Must not raise "Schema must contain uniquely named types ...".
    schema = DjangoGraphQLSchema(query=_SeedQuery)
    type_map = schema.graphql_schema.type_map
    # The canonical Category type appears exactly once (by name).
    cat_names = [n for n in type_map if n == "_NoDupCatType"]
    assert cat_names == ["_NoDupCatType"]


@pytest.mark.django_db
def test_native_single_object_query_executes_returns_real_data() -> None:
    """GATE (resolver smoke): assert that a native single-object query executes end-to-end.

    Builds the seed native schema, seeds a real DB row, runs
    "graphql_sync" selecting the single-object field plus a scalar
    subfield, and asserts REAL DATA is returned (not None, no errors).

    This is the execution smoke the WU2 gate lacked: the prior gate only
    asserted "field.resolve is callable" and never EXECUTED a query, so it
    missed that the native single-object resolver was DEAD — under
    native, "info.parent_type" is the WU2-compiled root
    "GraphQLObjectType" which carried NO "extensions['gdx']" and NO
    "graphene_type" alias, so "utils._get_custom_resolver" crashed with
    "'GraphQLObjectType' object has no attribute 'graphene_type'" ->
    "data:{'category': None}, errors:[GraphQLError(...)]".

    Against the dead resolver this test FAILS (None + GraphQLError); after
    the fix (root carries "extensions['gdx']" with the source graphene
    class and "_get_custom_resolver" reads it via the bridge) it PASSES
    with real data.
    """
    from graphql import graphql_sync

    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoObjectField
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ExecCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ExecQuery(_NativeRoot):
        category = DjangoObjectField(_ExecCatType)

    schema = DjangoGraphQLSchema(query=_ExecQuery)

    row = Category.objects.create(title="Hello")

    result = graphql_sync(
        schema.graphql_schema,
        "query Q($id: ID!) { category(id: $id) { id title } }",
        variable_values={"id": str(row.pk)},
    )

    assert result.errors is None, (
        f"native single-object query raised errors (dead resolver?): {result.errors!r}"
    )
    assert result.data == {"category": {"id": str(row.pk), "title": "Hello"}}, (
        f"native single-object query did not return the seeded row: {result.data!r}"
    )


@pytest.mark.django_db
def test_native_root_type_carries_gdx_with_source_graphene_class() -> None:
    """Assert that the compiled native root carries extensions["gdx"] (D8 invariant).

    Its GdxMeta exposes the SOURCE graphene root class, so dual-backend
    read-sites can recover "resolve_<field>" methods under native.

    If this fails, dual-backend read-sites would lose the ability to
    locate user-declared resolver methods on the root class.
    """
    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.compat import _gdx_graphene_type
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoObjectField
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _GdxCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _GdxQuery(_NativeRoot):
        category = DjangoObjectField(_GdxCatType)

    schema = DjangoGraphQLSchema(query=_GdxQuery)
    query_type = schema.graphql_schema.query_type

    # D8: the root carries extensions['gdx'].
    assert "gdx" in (query_type.extensions or {})
    # The bridge recovers the SOURCE graphene root class (so _get_custom_resolver
    # finds resolve_<field> methods declared on the user's root).
    assert _gdx_graphene_type(query_type) is _GdxQuery


@pytest.mark.django_db
def test_native_schema_query_none_raises_graphql_error() -> None:
    """Assert that "DjangoGraphQLSchema(query=None)" raises GraphQLError under native.

    If this fails, omitting a query root would either crash with an
    unrelated exception or silently construct an invalid schema.
    """
    from graphql import GraphQLError

    from django_graphex.schema import DjangoGraphQLSchema

    with pytest.raises(GraphQLError):
        DjangoGraphQLSchema(query=None)


@pytest.mark.django_db
def test_native_schema_build_failure_raises_not_silent_fallback() -> None:
    """Assert that a native root with an unbuildable field kind raises, not falls back silently.

    This is the guard the discarded WU2 attempt lacked. WU6a added native
    builders for the list/filter/pagination kinds, so this test
    temporarily re-registers "DjangoListObjectField" in
    "_DEFERRED_FIELD_KINDS" to assert the propagation path
    (NotImplementedError surfaces through "DjangoGraphQLSchema" rather
    than being swallowed by a graphene fallback) is STILL intact for any
    kind that does not yet have a builder.

    If this fails, an unbuildable field kind could silently fall back to
    a graphene-built schema instead of raising loudly.
    """
    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core import schema_compiler
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _RaiseListType(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ListQuery(_NativeRoot):
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


# --------------------------------------------------------------------------- #
# types= forwarding — native DjangoGraphQLSchema must thread types= into the   #
# graphql-core GraphQLSchema exactly as graphene.Schema does (else silent drop) #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_native_schema_forwards_unreferenced_plain_object_type() -> None:
    """Assert that an unreferenced plain native ObjectType passed via types= lands in type_map.

    Against the unfixed assembly this FAILS: the native
    "GraphQLSchema(...)" call did NOT forward "types=", so the
    unreferenced type is dropped (it is not reachable from Query). After
    the fix the native type_map contains the forwarded type as a
    gdx-bearing native instance.

    S-del-backend-11: the root and forwarded type are NATIVE
    "ObjectType"s (the graphene-ROOT compile capability was removed); the
    forwarding behavior is unchanged.

    If this fails, a type referenced only via the schema's types= kwarg
    would be dropped from the compiled schema's type map.
    """
    from graphql import GraphQLObjectType, GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema

    class _UnreferencedType(ObjectType):
        secret = field(GraphQLString)

    class _TypesQuery(ObjectType):
        # Does NOT reference _UnreferencedType.
        hello = field(GraphQLString)

    compile_all_outputs()

    schema = DjangoGraphQLSchema(query=_TypesQuery, types=[_UnreferencedType])
    type_map = schema.graphql_schema.type_map

    assert "_UnreferencedType" in type_map, (
        "types= forwarding FAILED: the unreferenced type was dropped from the "
        "native schema type_map (native did not forward types= to GraphQLSchema)."
    )
    forwarded = type_map["_UnreferencedType"]
    assert isinstance(forwarded, GraphQLObjectType)
    # The forwarded entry is the canonical native (gdx-bearing) instance, NOT a
    # graphene-built type smuggled in.
    assert "gdx" in (forwarded.extensions or {}), (
        "types= forwarding produced a non-native type (no extensions['gdx']) — "
        "native fell back to graphene for the forwarded type."
    )


@pytest.mark.django_db
def test_native_schema_forwards_django_object_type_canonical_instance() -> None:
    """Assert that a DjangoObjectType passed via types= reuses its canonical native instance.

    The forwarded entry is identity-stable and lands in the type_map.

    If this fails, forwarding a DjangoObjectType via types= could recompile
    a second, distinct instance instead of reusing the canonical one.
    """
    from graphql import GraphQLObjectType, GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.core.base import get_shared_output_registry
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _TypesCatType(DjangoObjectType):
        class Meta:
            model = Category

    class _TypesQuery2(ObjectType):
        hello = field(GraphQLString)

    compile_all_outputs()

    schema = DjangoGraphQLSchema(query=_TypesQuery2, types=[_TypesCatType])
    type_map = schema.graphql_schema.type_map

    assert "_TypesCatType" in type_map
    forwarded = type_map["_TypesCatType"]
    assert isinstance(forwarded, GraphQLObjectType)
    canonical = get_shared_output_registry().get_compiled(Category)
    assert forwarded is canonical, (
        "types= forwarding did NOT reuse the canonical native instance for the "
        "DjangoObjectType — it must be identity-stable, not a recompile."
    )


@pytest.mark.django_db
def test_native_schema_types_referenced_and_listed_no_duplicate_name() -> None:
    """Assert the IDENTITY INVARIANT: a type both referenced and listed in types= is not duplicated.

    The forwarded native type for a class must be the SAME instance the
    rest of the schema uses (the canonical "_meta.graphql_output_type"),
    so listing it in "types=" while a field also references it does not
    create a second same-named type.

    If this fails, listing an already-referenced type in types= would
    raise a duplicate-name TypeError instead of being a harmless no-op.
    """
    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.fields import DjangoObjectField
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _DupCatType(DjangoObjectType):
        class Meta:
            model = Category

    class _DupQuery(_NativeRoot):
        category = DjangoObjectField(_DupCatType)  # references _DupCatType

    compile_all_outputs()

    # _DupCatType is BOTH referenced by `category` AND listed in types=. This
    # must NOT raise "Schema must contain uniquely named types ...".
    schema = DjangoGraphQLSchema(query=_DupQuery, types=[_DupCatType])
    type_map = schema.graphql_schema.type_map
    cat_names = [n for n in type_map if n == "_DupCatType"]
    assert cat_names == ["_DupCatType"], (
        f"types= referenced+listed produced a duplicate-name divergence: {cat_names!r}"
    )


@pytest.mark.django_db
def test_native_schema_forwards_scalar_type_via_types() -> None:
    """Assert that a graphql-core scalar instance passed via types= lands in the type_map.

    v2.0: the graphene-scalar-class forwarding case was dropped (decision
    #1603). The native "types=" API forwards a graphql-core
    "GraphQLNamedType" instance verbatim (case 1). Forwarding the
    canonical "GdxUUID" scalar forces the unreferenced UUID type into the
    schema/SDL.

    If this fails, forwarding a bare graphql-core scalar instance via
    types= would either drop it or replace it with a different instance.
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.scalars import GdxUUID
    from django_graphex.schema import DjangoGraphQLSchema

    class _ScalarTypesQuery(ObjectType):
        hello = field(GraphQLString)

    compile_all_outputs()

    schema = DjangoGraphQLSchema(query=_ScalarTypesQuery, types=[GdxUUID])
    type_map = schema.graphql_schema.type_map

    assert "UUID" in type_map, (
        "types= forwarding dropped the forwarded UUID scalar instance."
    )
    assert type_map["UUID"] is GdxUUID, (
        "types= forwarding did not keep the canonical native scalar instance."
    )


@pytest.mark.django_db
def test_native_schema_types_unsupported_kind_raises_not_implemented() -> None:
    """Assert that an unsupported type kind passed via types= raises NotImplementedError.

    The error names the offending type — NEVER a silent drop (honest, no
    silent SDL divergence).

    If this fails, an unsupported types= entry could be silently dropped,
    producing a schema that diverges from what the caller expected.
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema

    # A plain class that is NOT a graphql-core named type, NOT a Django output
    # type, NOT a native plain ObjectType, and has no GDX_SCALAR_MAP name — the
    # generic "unsupported kind" the forwarder must reject loudly.
    class _SomeUnsupported:
        pass

    class _UnsupportedQuery(ObjectType):
        hello = field(GraphQLString)

    compile_all_outputs()

    with pytest.raises(NotImplementedError) as exc:
        DjangoGraphQLSchema(query=_UnsupportedQuery, types=[_SomeUnsupported])
    # The error must name the offending type so the failure is honest.
    assert "_SomeUnsupported" in str(exc.value)


# --------------------------------------------------------------------------- #
# S6f — DjangoGraphQLSchema is no longer a graphene.Schema subclass            #
# (metaclass-swap block S6 closes here; the graphql_schema is built directly   #
# via the native root compiler, and the public surface is preserved without    #
# inheriting graphene.Schema).                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_s6f_schema_is_not_graphene_schema_subclass() -> None:
    """Assert that "DjangoGraphQLSchema" no longer subclasses "graphene.Schema" (S6f).

    Against the pre-S6f base this FAILS (it WAS "graphene.Schema"); after
    S6f it is a plain class that builds "graphql_schema" directly via the
    native compiler. Asserted via MRO "__module__" strings so the gate
    never imports graphene — it must hold with graphene ABSENT (v2.0).

    If this fails, the schema class would still carry a graphene base in
    its MRO, contradicting the graphene-removal milestone.
    """
    from django_graphex.schema import DjangoGraphQLSchema

    graphene_bases = [
        b.__qualname__
        for b in DjangoGraphQLSchema.__mro__
        if b.__module__.split(".")[0] == "graphene"
    ]
    assert not graphene_bases, (
        "S6f: DjangoGraphQLSchema MRO must contain no graphene base — it builds "
        f"graphql_schema directly via the native root compiler; found: {graphene_bases}."
    )


@pytest.mark.django_db
def test_s6f_public_surface_preserved_without_graphene_base() -> None:
    """Assert that the public surface callers rely on survives the graphene-base removal.

    "views.py" reads "schema.graphql_schema"; legacy readers read
    "query" / "mutation" / "subscription"; SDL tooling reads "str(schema)"
    and "schema.graphql_schema". "auto_camelcase" is exposed for parity
    readers.

    If this fails, removing the graphene base would have broken one of
    the attributes existing callers depend on.
    """
    from graphql import GraphQLSchema, GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class _S6fQuery(ObjectType):
        hello = field(GraphQLString)

    schema = DjangoGraphQLSchema(query=_S6fQuery)

    # graphql_schema is the canonical graphql-core schema (what views.py reads).
    assert isinstance(schema.graphql_schema, GraphQLSchema)
    # Legacy root readers are preserved.
    assert schema.query is _S6fQuery
    assert schema.mutation is None
    assert schema.subscription is None
    # __str__ renders SDL (graphene.Schema.__str__ parity) without a graphene base.
    sdl = str(schema)
    assert "type _S6fQuery" in sdl or "hello" in sdl
    # auto_camelcase is exposed for parity readers (graphene default True).
    assert schema.auto_camelcase is True


@pytest.mark.django_db
def test_s6f_protected_fields_attached_without_graphene_branch() -> None:
    """Assert that the protected-field registry still lands on graphql_schema, with no graphene branch.

    The native build attaches both the legacy "_gde_protected_fields"
    marker and the canonical "extensions['gdx_protected_fields']".

    If this fails, protected-field metadata would be missing from either
    the legacy marker or the canonical extensions location, breaking
    consumers of either read-site.
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class _PubQ(ObjectType):
        pub_only = field(GraphQLString)

    class _PrivQ(ObjectType):
        priv_only = field(GraphQLString)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        schema = DjangoGraphQLSchema(query=_PubQ, private_query=_PrivQ)

    gql = schema.graphql_schema
    # Legacy marker (read by older middleware via info.schema._gde_protected_fields).
    assert "privOnly" in gql._gde_protected_fields
    assert "pubOnly" not in gql._gde_protected_fields
    # Canonical native read location (C14).
    assert gql.extensions["gdx_protected_fields"] == frozenset({"privOnly"})
