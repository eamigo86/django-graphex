"""WU2 (reworked): native root-ObjectType compiler + anti-tautology guard.

These tests prove the
GENUINE native seam that the discarded first WU2 attempt lacked:

1. "compile_native_root" turns a plain "graphene.ObjectType" root into a
   graphql-core "GraphQLObjectType" whose per-field TYPES are the canonical
   native instances ("_meta.graphql_output_type") carrying
   "extensions['gdx']" — NOT graphene-built types.
2. ANTI-TAUTOLOGY: the field type for a "DjangoObjectField" is identity-equal
   to the shared-registry canonical instance for that model. If native silently
   fell back to graphene, this identity assertion would FAIL.
3. The compiler RAISES "NotImplementedError" (never silent-skip) for field
   kinds whose native builder does not exist yet (list/filter/pagination —
   WU3/WU5/WU6).
4. The native "DjangoGraphQLSchema" assembles a "graphql.GraphQLSchema" from
   the native root with NO graphene.Schema duplicate-name error, and
   "query=None" raises "GraphQLError".
"""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_compile_native_root_returns_graphql_object_type() -> None:
    """Assert that "compile_native_root(Query)" returns a graphql-core GraphQLObjectType.

    If this fails, compiling a native root type would not produce a
    usable query root for schema assembly.
    """
    from graphql import GraphQLObjectType

    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.fields import DjangoObjectField
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _RootCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(_NativeRoot):
        category = DjangoObjectField(_RootCatType)

    native_root = compile_native_root(_SeedQuery, name="Query")
    assert isinstance(native_root, GraphQLObjectType)
    assert native_root.name == "Query"
    assert "category" in native_root.fields


@pytest.mark.django_db
def test_compile_native_root_field_type_is_canonical_native_instance() -> None:
    """Assert the ANTI-TAUTOLOGY invariant: field type identity is the canonical native instance.

    The "DjangoObjectField"'s compiled field type IS the shared registry
    canonical native GraphQLObjectType (identity), carrying gdx. A
    graphene fallback would NOT produce this identity nor
    extensions["gdx"].

    If this fails, the compiler could be silently falling back to a
    graphene-built type instead of the canonical native instance.
    """
    from graphql import GraphQLObjectType

    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.base import get_shared_output_registry
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.fields import DjangoObjectField
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _AntiTautCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(_NativeRoot):
        category = DjangoObjectField(_AntiTautCatType)

    native_root = compile_native_root(_SeedQuery, name="Query")

    field = native_root.fields["category"]
    field_type = field.type
    assert isinstance(field_type, GraphQLObjectType), (
        f"expected GraphQLObjectType, got {type(field_type).__name__}"
    )
    # Identity: the field type is the canonical shared-registry instance.
    canonical = get_shared_output_registry().get_compiled(Category)
    assert field_type is canonical, (
        "ANTI-TAUTOLOGY FAILURE: native field type is NOT the canonical native "
        "instance — native silently fell back to graphene."
    )
    # gdx bridge: only native-built types carry this.
    assert "gdx" in (field_type.extensions or {}), (
        "ANTI-TAUTOLOGY FAILURE: field type lacks extensions['gdx'] — not native."
    )


@pytest.mark.django_db
def test_compile_native_root_wires_resolver() -> None:
    """Assert that the native field's resolve is wired, not a dead no-op.

    If this fails, querying a compiled root field would return nothing
    useful because no real resolver (or "id" argument) was attached.
    """
    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.fields import DjangoObjectField
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ResolverCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(_NativeRoot):
        category = DjangoObjectField(_ResolverCatType)

    native_root = compile_native_root(_SeedQuery, name="Query")
    field = native_root.fields["category"]
    assert field.resolve is not None and callable(field.resolve)
    # The single-object field exposes an `id` argument.
    assert "id" in field.args


@pytest.mark.django_db
def test_compile_native_root_builds_list_object_field() -> None:
    """Assert that the compiler builds a DjangoListObjectField into a native field.

    WU6a: the compiled field's type is the canonical WU1b list-container
    (identity, gdx-bridged). Previously this asserted NotImplementedError;
    WU6a added the builder.

    If this fails, a list-object field on the query root would either
    raise NotImplementedError or resolve to a non-canonical type.
    """
    from graphql import GraphQLObjectType

    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _NIListType(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ListQuery(_NativeRoot):
        categories = DjangoListObjectField(_NIListType)

    native_root = compile_native_root(_ListQuery, name="Query")
    field = native_root.fields["categories"]
    # Output type is the canonical WU1b list container (identity-stable, gdx).
    assert field.type is _NIListType._meta.graphql_output_type
    assert isinstance(field.type, GraphQLObjectType)
    assert "gdx" in (field.type.extensions or {})
    # The field resolver is wired (not a dead no-op).
    assert callable(field.resolve)


@pytest.mark.django_db
def test_compile_native_root_builds_filter_list_field() -> None:
    """Assert that the compiler builds a DjangoFilterListField into a native list field.

    WU6a: the compiled field carries the native filter input arg.
    Previously this asserted NotImplementedError; WU6a added the builder.

    If this fails, a filter-list field on the query root would either
    raise NotImplementedError or be missing its native filter argument.
    """
    from graphql import GraphQLInputObjectType, GraphQLList

    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.fields import DjangoFilterListField
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _FilterCatType(DjangoObjectType):
        class Meta:
            model = Category
            filter_fields = ["title"]

    compile_all_outputs()

    class _FilterQuery(_NativeRoot):
        cats = DjangoFilterListField(_FilterCatType)

    native_root = compile_native_root(_FilterQuery, name="Query")
    field = native_root.fields["cats"]
    assert isinstance(field.type, GraphQLList)
    # Filter arg is a native graphql-core input type.
    assert "filter" in field.args
    assert isinstance(field.args["filter"].type, GraphQLInputObjectType)
    assert callable(field.resolve)


@pytest.mark.django_db
def test_compile_native_root_reuses_raw_graphql_field() -> None:
    """Assert that the compiler reuses a raw graphql-core GraphQLField placed on the root.

    It does so via the REAL registration path, not a manual
    "_NATIVE_FIELD_REGISTRY" poke. "DjangoModelType.CreateField()" returns
    a raw "graphql.GraphQLField" that the native "ObjectType" metaclass
    does NOT mount into "_meta.fields" (it stays as a plain class
    attribute). The builder SELF-REGISTERS that field in
    "_NATIVE_FIELD_REGISTRY[(model, op, 'native')]", and the native root
    compiler recovers such attributes from the class dict (gated on
    registry membership) and reuses them AS-IS (no rebuild).

    v2.0: the root is a NATIVE "django_graphex.ObjectType" (the
    graphene-root compile capability was removed, decision #1603).

    If this fails, a raw mutation field mounted on the query/mutation
    root would be rebuilt (or dropped) instead of reused as the exact
    same registered GraphQLField instance.
    """
    from django_graphex.core import ObjectType as _NativeRoot
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.core.schema_compiler import compile_native_root
    from django_graphex.mutation import _NATIVE_FIELD_REGISTRY
    from django_graphex.types import DjangoModelType, DjangoObjectType

    # Use a model dedicated to this test so its input/output registry entries are
    # not polluted by sibling DjangoModelType/DjangoInputObjectType definitions
    # for the same model elsewhere in the process-wide global registry.
    from tests.models import HookModel

    class _RawHookNode(DjangoObjectType):
        class Meta:
            model = HookModel

    class _RawHookType(DjangoModelType):
        class Meta:
            model = HookModel

    compile_all_outputs()

    # The REAL registration path: CreateField() builds AND self-registers the
    # native GraphQLField — no manual _NATIVE_FIELD_REGISTRY injection.
    create_field = _RawHookType.CreateField()
    assert _NATIVE_FIELD_REGISTRY[(HookModel, "create", "native")] is create_field

    class _MutationRoot(_NativeRoot):
        create_hook = create_field

    native_root = compile_native_root(_MutationRoot, name="Mutation")
    # camelCase mirrors auto_camelcase=True; recovered from the class dict, reused
    # as the SAME native GraphQLField instance (no rebuild).
    assert "createHook" in native_root.fields
    assert native_root.fields["createHook"] is create_field


# NOTE: the former ``test_compile_native_root_ignores_unregistered_raw_graphql_field``
# was DELETED in v2.0 (S8i). It asserted that a raw ``GraphQLField`` class attribute
# NOT in ``_NATIVE_FIELD_REGISTRY`` was NOT mounted — a guard specific to the
# graphene-root recovery path (graphene's metaclass DROPPED raw ``GraphQLField``
# attributes, so the registry-membership gate decided which dropped fields to
# recover). The graphene-root compile capability was removed (decision #1603); on a
# native ``ObjectType`` root a raw ``GraphQLField`` declared in the class body is a
# legitimate declared field and IS mounted, so the old assertion no longer applies.
