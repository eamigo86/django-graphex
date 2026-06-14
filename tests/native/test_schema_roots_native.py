"""WU7 — native schema roots: plain-ObjectType dispatch, _merge_root collision,
collect_field_names, protected-fields-via-extensions.

Under GDX_BACKEND=native:
- A ``graphene.Field(PlainObjectType)`` (plain ``graphene.ObjectType``, NOT a
  DjangoObjectType, NOT a scalar) compiles to a native ``GraphQLObjectType``
  on-the-fly (Slice A), carries ``extensions['gdx']``, is single-instance
  (two references share one instance), and RESOLVES end-to-end.
- ``_merge_root`` field-unions public + private into a native-friendly merged
  root and RAISES ``ValueError`` on a public/private field-name collision
  (the inverse-MRO security hazard graphene silently shadows).
- ``collect_field_names`` reads native ``.fields`` (camelCase keys already).
- Protected fields are stored on ``GraphQLSchema.extensions['gdx_protected_fields']``
  and read by ``security.AuthenticatedFieldsMiddleware.get_protected_fields``.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


# --------------------------------------------------------------------------- #
# Slice A — plain graphene.ObjectType field dispatch in compile_native_root    #
# --------------------------------------------------------------------------- #
def test_plain_objecttype_field_compiles_native_and_resolves():
    """A ``graphene.Field(PlainObjectType)`` compiles to a native
    ``GraphQLObjectType`` and resolves end-to-end (no GDX_SCALAR_MAP KeyError)."""
    import graphene
    from graphql import GraphQLObjectType, graphql_sync

    from django_graphex.native.schema_compiler import compile_native_root

    class _Nested(graphene.ObjectType):
        me = graphene.String()

        def resolve_me(root, info):
            return "nested-me"

    class _Q(graphene.ObjectType):
        nested = graphene.Field(_Nested)
        plain_scalar = graphene.String()

        def resolve_nested(root, info):
            return _Nested()

        def resolve_plain_scalar(root, info):
            return "scalar-val"

    native_root = compile_native_root(_Q, name="Query")
    assert isinstance(native_root, GraphQLObjectType)

    nested_field_type = native_root.fields["nested"].type
    assert isinstance(nested_field_type, GraphQLObjectType)
    # D8 invariant: native object type carries extensions['gdx'].
    assert "gdx" in (nested_field_type.extensions or {})

    from graphql import GraphQLSchema

    schema = GraphQLSchema(query=native_root)
    result = graphql_sync(schema, "{ nested { me } plainScalar }")
    assert result.errors is None, result.errors
    assert result.data == {"nested": {"me": "nested-me"}, "plainScalar": "scalar-val"}


def test_plain_objecttype_single_instance_when_referenced_twice():
    """Two ``graphene.Field`` references to the SAME plain ObjectType compile to
    ONE native instance (identity-stable, no duplicate-name TypeError)."""
    import graphene
    from graphql import GraphQLSchema

    from django_graphex.native.schema_compiler import compile_native_root

    class _Shared(graphene.ObjectType):
        v = graphene.String()

    class _Q(graphene.ObjectType):
        a = graphene.Field(_Shared)
        b = graphene.Field(_Shared)

    native_root = compile_native_root(_Q, name="Query")
    type_a = native_root.fields["a"].type
    type_b = native_root.fields["b"].type
    assert type_a is type_b, "plain-ObjectType references must share ONE native instance"

    # No duplicate-name error when assembled into a schema.
    GraphQLSchema(query=native_root)


def test_plain_objecttype_recurses_nested_plain_types():
    """A plain ObjectType referencing ANOTHER plain ObjectType compiles
    recursively without falling into _build_scalar_field."""
    import graphene
    from graphql import GraphQLObjectType, GraphQLSchema, graphql_sync

    from django_graphex.native.schema_compiler import compile_native_root

    class _Leaf(graphene.ObjectType):
        leaf_val = graphene.String()

        def resolve_leaf_val(root, info):
            return "leaf"

    class _Branch(graphene.ObjectType):
        leaf = graphene.Field(_Leaf)

        def resolve_leaf(root, info):
            return _Leaf()

    class _Q(graphene.ObjectType):
        branch = graphene.Field(_Branch)

        def resolve_branch(root, info):
            return _Branch()

    native_root = compile_native_root(_Q, name="Query")
    branch_type = native_root.fields["branch"].type
    assert isinstance(branch_type, GraphQLObjectType)
    leaf_type = branch_type.fields["leaf"].type
    assert isinstance(leaf_type, GraphQLObjectType)

    schema = GraphQLSchema(query=native_root)
    result = graphql_sync(schema, "{ branch { leaf { leafVal } } }")
    assert result.errors is None, result.errors
    assert result.data == {"branch": {"leaf": {"leafVal": "leaf"}}}


# --------------------------------------------------------------------------- #
# C12 — native _merge_root field-union + collision RAISES ValueError           #
# --------------------------------------------------------------------------- #
def test_merge_root_collision_raises_value_error():
    """_merge_root RAISES ValueError when public and private declare a field of
    the SAME name (inverse-MRO security hazard — graphene silently shadows)."""
    import graphene

    from django_graphex.schema import DjangoGraphQLSchema

    class _Pub(graphene.ObjectType):
        foo = graphene.String()

    class _Priv(graphene.ObjectType):
        foo = graphene.String()  # COLLISION with public foo

    with pytest.raises(ValueError) as exc:
        DjangoGraphQLSchema._merge_root("Query", _Pub, _Priv)
    assert "foo" in str(exc.value), (
        "ValueError must name the colliding field 'foo'"
    )


def test_merge_root_disjoint_union_succeeds():
    """_merge_root field-unions disjoint public + private without error."""
    import graphene

    from django_graphex.schema import DjangoGraphQLSchema

    class _Pub(graphene.ObjectType):
        pub_only = graphene.String()

    class _Priv(graphene.ObjectType):
        priv_only = graphene.String()

    merged = DjangoGraphQLSchema._merge_root("Query", _Pub, _Priv)
    # native merge returns a GraphQLObjectType field-union; both fields present.
    from graphql import GraphQLObjectType

    assert isinstance(merged, GraphQLObjectType)
    assert {"pubOnly", "privOnly"} <= set(merged.fields)


def test_merge_root_subset_short_circuit_returns_public():
    """When private fields are a SUBSET of public (full-root + marker idiom),
    _merge_root short-circuits to the public root unchanged."""
    import graphene

    from django_graphex.schema import DjangoGraphQLSchema

    class _Full(graphene.ObjectType):
        a = graphene.String()
        b = graphene.String()

    class _Marker(graphene.ObjectType):
        a = graphene.String()  # subset of _Full

    merged = DjangoGraphQLSchema._merge_root("Query", _Full, _Marker)
    # Subset short-circuit: public root returned unchanged (still graphene class).
    assert merged is _Full


# --------------------------------------------------------------------------- #
# C13 — collect_field_names reads native .fields                                #
# --------------------------------------------------------------------------- #
def test_collect_field_names_reads_native_fields():
    """collect_field_names reads native GraphQLObjectType.fields (camelCase keys,
    no double to_camel_case)."""
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.schema import collect_field_names

    native_type = GraphQLObjectType(
        name="N",
        fields={
            "fooBar": GraphQLField(GraphQLString),
            "baz": GraphQLField(GraphQLString),
        },
    )
    names = collect_field_names(native_type)
    assert names == frozenset({"fooBar", "baz"})


def test_collect_field_names_graphene_fallback_still_works():
    """collect_field_names still reads graphene _meta.fields for graphene types."""
    import graphene

    from django_graphex.schema import collect_field_names

    class _G(graphene.ObjectType):
        my_field = graphene.String()

    assert collect_field_names(_G) == frozenset({"myField"})


# --------------------------------------------------------------------------- #
# C14 — protected fields via GraphQLSchema.extensions                           #
# --------------------------------------------------------------------------- #
def test_protected_fields_stored_in_schema_extensions():
    """Under native, protected fields live on
    ``schema.graphql_schema.extensions['gdx_protected_fields']``."""
    import warnings

    import graphene

    from django_graphex.schema import DjangoGraphQLSchema

    class _Pub(graphene.ObjectType):
        pub = graphene.String()

    class _Priv(graphene.ObjectType):
        secret = graphene.String()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        schema = DjangoGraphQLSchema(query=_Pub, private_query=_Priv)

    extensions = schema.graphql_schema.extensions or {}
    assert "gdx_protected_fields" in extensions
    assert "secret" in extensions["gdx_protected_fields"]
    assert "pub" not in extensions["gdx_protected_fields"]


def test_get_protected_fields_reads_extensions_first():
    """security.AuthenticatedFieldsMiddleware.get_protected_fields reads
    schema.extensions['gdx_protected_fields'] FIRST."""
    import types

    from graphql import GraphQLSchema

    from django_graphex.security import AuthenticatedFieldsMiddleware

    mw = AuthenticatedFieldsMiddleware()
    # Build a bare schema carrying the extensions marker.
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    q = GraphQLObjectType("Query", {"x": GraphQLField(GraphQLString)})
    schema = GraphQLSchema(
        query=q, extensions={"gdx_protected_fields": frozenset({"secret"})}
    )
    fake_info = types.SimpleNamespace(schema=schema)
    assert mw.get_protected_fields(fake_info) == frozenset({"secret"})


def test_get_protected_fields_legacy_attribute_fallback():
    """get_protected_fields falls back to the legacy _gde_protected_fields
    attribute when extensions has no gdx_protected_fields (dual-backend)."""
    import types

    from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

    from django_graphex.security import AuthenticatedFieldsMiddleware

    mw = AuthenticatedFieldsMiddleware()
    q = GraphQLObjectType("Query", {"x": GraphQLField(GraphQLString)})
    schema = GraphQLSchema(query=q)
    schema._gde_protected_fields = frozenset({"legacy_secret"})
    fake_info = types.SimpleNamespace(schema=schema)
    assert mw.get_protected_fields(fake_info) == frozenset({"legacy_secret"})
