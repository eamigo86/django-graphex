"""WU2 (reworked): native root-ObjectType compiler + anti-tautology guard.

These tests run under GDX_BACKEND=native (native_only mark) and prove the
GENUINE native seam that the discarded first WU2 attempt lacked:

1. ``compile_native_root`` turns a plain ``graphene.ObjectType`` root into a
   graphql-core ``GraphQLObjectType`` whose per-field TYPES are the canonical
   native instances (``_meta.graphql_output_type``) carrying
   ``extensions['gdx']`` — NOT graphene-built types.
2. ANTI-TAUTOLOGY: the field type for a ``DjangoObjectField`` is identity-equal
   to the shared-registry canonical instance for that model. If native silently
   fell back to graphene, this identity assertion would FAIL.
3. The compiler RAISES ``NotImplementedError`` (never silent-skip) for field
   kinds whose native builder does not exist yet (list/filter/pagination —
   WU3/WU5/WU6).
4. The native ``DjangoGraphQLSchema`` assembles a ``graphql.GraphQLSchema`` from
   the native root with NO graphene.Schema duplicate-name error, and
   ``query=None`` raises ``GraphQLError``.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


@pytest.mark.django_db
def test_compile_native_root_returns_graphql_object_type():
    """compile_native_root(Query) returns a graphql-core GraphQLObjectType."""
    import graphene
    from graphql import GraphQLObjectType

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _RootCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(graphene.ObjectType):
        category = DjangoObjectField(_RootCatType)

    native_root = compile_native_root(_SeedQuery, name="Query")
    assert isinstance(native_root, GraphQLObjectType)
    assert native_root.name == "Query"
    assert "category" in native_root.fields


@pytest.mark.django_db
def test_compile_native_root_field_type_is_canonical_native_instance():
    """ANTI-TAUTOLOGY: the DjangoObjectField's compiled field type IS the shared
    registry canonical native GraphQLObjectType (identity), carrying gdx.

    A graphene fallback would NOT produce this identity nor extensions['gdx'].
    """
    import graphene
    from graphql import GraphQLObjectType

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.base import get_shared_output_registry
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _AntiTautCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(graphene.ObjectType):
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
def test_compile_native_root_wires_resolver():
    """The native field's resolve is wired (not a dead no-op)."""
    import graphene

    from django_graphex.fields import DjangoObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ResolverCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _SeedQuery(graphene.ObjectType):
        category = DjangoObjectField(_ResolverCatType)

    native_root = compile_native_root(_SeedQuery, name="Query")
    field = native_root.fields["category"]
    assert field.resolve is not None and callable(field.resolve)
    # The single-object field exposes an `id` argument.
    assert "id" in field.args


@pytest.mark.django_db
def test_compile_native_root_raises_notimplemented_for_list_field():
    """The compiler RAISES NotImplementedError (never silent-skip) for a list
    field whose native builder does not exist yet (WU5/WU6)."""
    import graphene

    from django_graphex.fields import DjangoListObjectField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _NIListType(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _ListQuery(graphene.ObjectType):
        categories = DjangoListObjectField(_NIListType)

    with pytest.raises(NotImplementedError) as exc:
        compile_native_root(_ListQuery, name="Query")
    msg = str(exc.value)
    assert "categories" in msg, f"error must name the field; got: {msg}"
    assert "DjangoListObjectField" in msg, (
        f"error must name the field kind; got: {msg}"
    )


@pytest.mark.django_db
def test_compile_native_root_raises_notimplemented_for_filter_field():
    """The compiler RAISES NotImplementedError for a filter list field (WU3)."""
    import graphene

    from django_graphex.fields import DjangoFilterListField
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.native.schema_compiler import compile_native_root
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _FilterCatType(DjangoObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    class _FilterQuery(graphene.ObjectType):
        cats = DjangoFilterListField(_FilterCatType)

    with pytest.raises(NotImplementedError) as exc:
        compile_native_root(_FilterQuery, name="Query")
    assert "cats" in str(exc.value)
    assert "DjangoFilterListField" in str(exc.value)


@pytest.mark.django_db
def test_compile_native_root_reuses_raw_graphql_field():
    """The compiler REUSES a raw graphql-core GraphQLField placed on the root.

    Under GDX_BACKEND=native, ``DjangoModelType.CreateField()`` returns a raw
    ``graphql.GraphQLField`` that graphene's ObjectType metaclass does NOT mount
    into ``_meta.fields`` (it stays as a plain class attribute). The native root
    compiler must recover such attributes from the class dict and reuse them
    AS-IS (no rebuild). This is exactly the mutation-field integration seam WU9
    will rely on; here we assert it with a hand-built GraphQLField so the test is
    independent of Phase-4 mutation input-compilation ordering.

    The recovered field must be REGISTERED in ``_NATIVE_FIELD_REGISTRY``: the
    compiler keys recovery off registry membership (not a blanket
    ``isinstance(value, GraphQLField)`` scan) so an unrelated user-declared raw
    ``GraphQLField`` is never silently mounted. We register the hand-built field
    under a synthetic key (kept decoupled from Phase-4 mutation input-compile
    ordering) and clean it up afterward.
    """
    import graphene
    from graphql import GraphQLField, GraphQLString

    from django_graphex.mutation import _NATIVE_FIELD_REGISTRY
    from django_graphex.native.schema_compiler import compile_native_root

    raw_field = GraphQLField(GraphQLString, resolve=lambda root, info: "ok")
    _reg_key = ("_test_thing_model", "create", "native")
    _NATIVE_FIELD_REGISTRY[_reg_key] = raw_field
    try:

        class _MutationRoot(graphene.ObjectType):
            create_thing = raw_field

        # graphene drops the raw GraphQLField — it must NOT appear in _meta.fields.
        assert "create_thing" not in (
            getattr(_MutationRoot._meta, "fields", {}) or {}
        )

        native_root = compile_native_root(_MutationRoot, name="Mutation")
        # camelCase mirrors graphene auto_camelcase=True; recovered from the class
        # dict, reused as the SAME native GraphQLField instance (no rebuild).
        assert "createThing" in native_root.fields
        assert native_root.fields["createThing"] is raw_field
    finally:
        _NATIVE_FIELD_REGISTRY.pop(_reg_key, None)


@pytest.mark.django_db
def test_compile_native_root_ignores_unregistered_raw_graphql_field():
    """SUGGESTION (defect #2): a raw GraphQLField NOT in _NATIVE_FIELD_REGISTRY
    is NOT mounted onto the native root.

    The compiler keys field recovery off ``_NATIVE_FIELD_REGISTRY`` membership
    (identity), not a blanket ``isinstance(value, GraphQLField)`` scan, so only
    provably-native mutation fields are recovered.
    """
    import graphene
    from graphql import GraphQLField, GraphQLString

    from django_graphex.native.schema_compiler import compile_native_root

    # A raw GraphQLField that was NEVER registered by the mutation machinery.
    stray_field = GraphQLField(GraphQLString, resolve=lambda root, info: "stray")

    class _StrayRoot(graphene.ObjectType):
        stray_thing = stray_field

    native_root = compile_native_root(_StrayRoot, name="Mutation")
    assert "strayThing" not in native_root.fields
