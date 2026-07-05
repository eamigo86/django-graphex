"""WU7 — native schema roots: plain-ObjectType dispatch, _merge_root collision,
collect_field_names, protected-fields-via-extensions.

Behavior:
- A "graphene.Field(PlainObjectType)" (plain "graphene.ObjectType", NOT a
  DjangoObjectType, NOT a scalar) compiles to a native "GraphQLObjectType"
  on-the-fly (Slice A), carries "extensions['gdx']", is single-instance
  (two references share one instance), and RESOLVES end-to-end.
- "_merge_root" field-unions public + private into a native-friendly merged
  root and RAISES "ValueError" on a public/private field-name collision
  (the inverse-MRO security hazard graphene silently shadows).
- "collect_field_names" reads native ".fields" (camelCase keys already).
- Protected fields are stored on "GraphQLSchema.extensions['gdx_protected_fields']"
  and read by "security.AuthenticatedFieldsMiddleware.get_protected_fields".
"""

from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# C12 — native _merge_root field-union + collision RAISES ValueError           #
# --------------------------------------------------------------------------- #
def test_merge_root_collision_raises_value_error() -> None:
    """Ships broken if "_merge_root" stops RAISING ValueError when public and
    private declare a field of the SAME name (inverse-MRO security hazard the
    merge must reject).
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class _Pub(ObjectType):
        foo = field(GraphQLString)

    class _Priv(ObjectType):
        foo = field(GraphQLString)  # COLLISION with public foo

    with pytest.raises(ValueError) as exc:
        DjangoGraphQLSchema._merge_root("Query", _Pub, _Priv)
    assert "foo" in str(exc.value), "ValueError must name the colliding field 'foo'"


def test_merge_root_disjoint_union_succeeds() -> None:
    """Ships broken if "_merge_root" stops field-unioning disjoint public and
    private roots without error.
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class _Pub(ObjectType):
        pub_only = field(GraphQLString)

    class _Priv(ObjectType):
        priv_only = field(GraphQLString)

    merged = DjangoGraphQLSchema._merge_root("Query", _Pub, _Priv)
    # native merge returns a GraphQLObjectType field-union; both fields present.
    from graphql import GraphQLObjectType

    assert isinstance(merged, GraphQLObjectType)
    assert {"pubOnly", "privOnly"} <= set(merged.fields)


def test_merge_root_subset_short_circuit_returns_public() -> None:
    """Ships broken if "_merge_root" stops short-circuiting to the public
    root unchanged when private fields are a SUBSET of public (full-root +
    marker idiom).
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class _Full(ObjectType):
        a = field(GraphQLString)
        b = field(GraphQLString)

    class _Marker(ObjectType):
        a = field(GraphQLString)  # subset of _Full

    merged = DjangoGraphQLSchema._merge_root("Query", _Full, _Marker)
    # Subset short-circuit: public root returned unchanged.
    assert merged is _Full


# --------------------------------------------------------------------------- #
# C13 — collect_field_names reads native .fields                                #
# --------------------------------------------------------------------------- #
def test_collect_field_names_reads_native_fields() -> None:
    """Ships broken if collect_field_names stops reading native
    GraphQLObjectType.fields (camelCase keys, no double to_camel_case).
    """
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


def test_collect_field_names_camelcases_meta_fields_keys() -> None:
    """Ships broken if collect_field_names stops camelCasing snake_case
    "_meta.fields" keys.

    A native "ObjectType" exposes "_meta.fields" with snake_case keys; the
    reader camelCases them to match "info.field_name" under
    "auto_camelcase=True" (the same path the legacy graphene root used).
    """
    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import collect_field_names

    class _G(ObjectType):
        my_field = field(GraphQLString)

    assert collect_field_names(_G) == frozenset({"myField"})


# --------------------------------------------------------------------------- #
# C14 — protected fields via GraphQLSchema.extensions                           #
# --------------------------------------------------------------------------- #
def test_protected_fields_stored_in_schema_extensions() -> None:
    """Ships broken if protected fields stop living on
    "schema.graphql_schema.extensions['gdx_protected_fields']" under native.
    """
    import warnings

    from graphql import GraphQLString

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class _Pub(ObjectType):
        pub = field(GraphQLString)

    class _Priv(ObjectType):
        secret = field(GraphQLString)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        schema = DjangoGraphQLSchema(query=_Pub, private_query=_Priv)

    extensions = schema.graphql_schema.extensions or {}
    assert "gdx_protected_fields" in extensions
    assert "secret" in extensions["gdx_protected_fields"]
    assert "pub" not in extensions["gdx_protected_fields"]


def test_get_protected_fields_reads_extensions_first() -> None:
    """Ships broken if
    security.AuthenticatedFieldsMiddleware.get_protected_fields stops reading
    schema.extensions['gdx_protected_fields'] FIRST.
    """
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


def test_get_protected_fields_legacy_attribute_fallback() -> None:
    """Ships broken if get_protected_fields stops falling back to the legacy
    _gde_protected_fields attribute when extensions has no
    gdx_protected_fields (dual-backend).
    """
    import types

    from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

    from django_graphex.security import AuthenticatedFieldsMiddleware

    mw = AuthenticatedFieldsMiddleware()
    q = GraphQLObjectType("Query", {"x": GraphQLField(GraphQLString)})
    schema = GraphQLSchema(query=q)
    schema._gde_protected_fields = frozenset({"legacy_secret"})
    fake_info = types.SimpleNamespace(schema=schema)
    assert mw.get_protected_fields(fake_info) == frozenset({"legacy_secret"})
