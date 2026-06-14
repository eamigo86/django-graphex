"""extensions["gdx"] bridge: GdxPayload, _MetaView, assert_gdx_bridge.

Owned once here; Phases 2-7 extend/call, never re-introduce.

No imports from ``django`` or ``graphene``.

Allowlist derivation:
    ``rg -oh '_meta\\.\\w+' django_graphex/ | sort -u``
    minus the ~11 legitimate Django ``model._meta.*`` reads:
        app_label, concrete_fields, constraints, get_field, get_fields,
        local_many_to_many, model_name, object_name, ordering, parents, pk,
        private_fields, unique_together

The gdx set (everything else) is the allowlist below.
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLObjectType, GraphQLSchema


# ---------------------------------------------------------------------------
# GDX allowlist (owned once)
# ---------------------------------------------------------------------------

_GDX_ALLOWLIST: frozenset[str] = frozenset(
    {
        # core type options
        "model",
        "name",
        "fields",
        "only_fields",
        "exclude_fields",
        "skip_registry",
        # input
        "input_for",
        "input_field_name",
        "input_fields",
        "graphql_input_type",
        # output
        "output",
        "output_type",
        "output_list_type",
        "output_field_name",
        # depth / cost
        "max_deep",
        "complexity",
        # relations
        "gfk_unions",
        "nested_fields",
        "relation_accessor",
        # subscriptions
        "stream",
        "index_fields",
        "subscription_index_fields",
        "serialize_data",
        # pagination
        "pagination",
        "results_field_name",
        "max_page_size",
        # filtering
        "filter_fields",
        # registry
        "registry",
        # other
        "arguments",
        "backend",
        "baseType",
        "connection",
        "container",
        "fields_map",
        "interfaces",
        "model_operations",
        "mutation_output",
        "node",
        "queryset",
        "types",
        # Phase 3: native output compile attrs
        "graphql_output_type",
    }
)


# ---------------------------------------------------------------------------
# _MetaView — attribute proxy over GdxMeta
# ---------------------------------------------------------------------------

class _MetaView:
    """Proxy that exposes ``GdxMeta`` fields as attributes.

    ``__getattr__`` raises ``AttributeError`` (NEVER returns ``None``) on any
    attribute not in ``_GDX_ALLOWLIST``.  This hard-fails silent depth/cost
    bugs caused by a missing attr silently returning ``None``.
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: Any) -> None:
        object.__setattr__(self, "_spec", spec)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in _GDX_ALLOWLIST:
            raise AttributeError(
                f"_MetaView: unknown gdx attr {name!r}. "
                f"If this is a new attr, add it to _GDX_ALLOWLIST in bridge.py."
            )
        spec = object.__getattribute__(self, "_spec")
        try:
            return getattr(spec, name)
        except AttributeError:
            raise AttributeError(
                f"_MetaView: GdxMeta has no attr {name!r}."
            )


# ---------------------------------------------------------------------------
# GdxPayload — placed on extensions["gdx"]
# ---------------------------------------------------------------------------

class GdxPayload:
    """Payload placed on ``GraphQLObjectType(extensions={"gdx": GdxPayload(...)})```.

    Replaces graphene's ``graphene_type`` back-reference.  Reachable from:
    - ``ValidationRule``s via ``get_named_type(...).extensions["gdx"]``
    - resolvers via ``info.parent_type / return_type``
    - the bridge assertion at schema-build time

    ``_meta`` property provides the ``graphene_type._meta`` shim so existing
    read-sites (validation.py, cost.py, utils.py) continue working in 2.0
    before Phase 7 removes the shim.
    """

    __slots__ = ("_gdx_meta",)

    def __init__(self, gdx_meta: Any) -> None:
        object.__setattr__(self, "_gdx_meta", gdx_meta)

    @property
    def _meta(self) -> _MetaView:
        """Shim: ``type.extensions['gdx']._meta.max_deep`` keeps reading."""
        return _MetaView(object.__getattribute__(self, "_gdx_meta"))

    def __repr__(self) -> str:
        return f"GdxPayload({object.__getattribute__(self, '_gdx_meta')!r})"


# ---------------------------------------------------------------------------
# assert_gdx_bridge
# ---------------------------------------------------------------------------

# Types to skip: graphql-core introspection types and built-in scalars/directives
_SKIP_PREFIXES = ("__",)
# Built-in scalar names that don't need gdx extensions
from graphql import (
    GraphQLBoolean,
    GraphQLFloat,
    GraphQLID,
    GraphQLInt,
    GraphQLString,
)
_BUILTIN_SCALAR_NAMES: frozenset[str] = frozenset(
    {t.name for t in (GraphQLString, GraphQLInt, GraphQLFloat, GraphQLBoolean, GraphQLID)}
)


def assert_gdx_bridge(schema: GraphQLSchema) -> None:
    """Assert every user-defined object/interface/input type in ``schema`` carries
    ``extensions["gdx"]``.

    Raises ``AssertionError`` identifying the first offending type if any is
    missing the bridge.  Skips:
    - introspection types (names starting with ``__``)
    - built-in scalars (String, Int, Float, Boolean, ID)
    - graphql-core scalars registered via GDX_SCALAR_MAP
    - non-object types (scalars, enums, unions — they don't need the bridge)
    """
    from graphql import GraphQLObjectType as _ObjType
    from graphql import GraphQLInterfaceType as _IFType
    from graphql import GraphQLInputObjectType as _InputType
    from graphql import GraphQLScalarType as _ScalarType
    from graphql import GraphQLEnumType as _EnumType
    from graphql import GraphQLUnionType as _UnionType

    # Only assert on object/interface/input types — scalars/enums/unions are exempt
    _assertable = (_ObjType, _IFType, _InputType)

    for type_name, gql_type in schema.type_map.items():
        # Skip introspection types
        if type_name.startswith("__"):
            continue
        # Skip scalar and enum types
        if isinstance(gql_type, (_ScalarType, _EnumType, _UnionType)):
            continue
        if not isinstance(gql_type, _assertable):
            continue
        if "gdx" not in (gql_type.extensions or {}):
            raise AssertionError(
                f"assert_gdx_bridge: type {type_name!r} is missing "
                f"extensions['gdx']. All object/interface/input types must be "
                f"compiled via compile_schema (or have GdxPayload attached)."
            )
