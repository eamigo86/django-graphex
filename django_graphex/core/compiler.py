"""Native output compiler: compile_type / compile_enum / compile_schema.

Implements the thunk-based, memoize-before-recurse functional compiler over
"graphql-core". No imports from "django" or "graphene".

Key design contracts:
- camelCase via dict KEY (GraphQLField has no out_name).
- _TYPE_CACHE placeholder registered BEFORE recursion (memoize-before-recurse).
- Loop-variable capture fixed via default-arg idiom.
- Snake-closure default resolver works for both dict and object sources.
- _reset_cache() called at compile_schema entry to prevent cross-case leakage.
- GDX_SCALAR_MAP seeded into _TYPE_CACHE at compile_schema entry.
- assert_gdx_bridge(schema) called at compile_schema exit.
"""

from __future__ import annotations

from typing import Any, Sequence

from graphql import (
    GraphQLEnumType,
    GraphQLEnumValue,
    GraphQLField,
    GraphQLList,
    GraphQLNamedType,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
)

from django_graphex._strconv import to_camel_case as _to_camel_case
from django_graphex.core.bridge import GdxPayload, assert_gdx_bridge
from django_graphex.core.ir import EnumSpec, GdxMeta, TypeRef, TypeSpec
from django_graphex.core.scalars import GDX_SCALAR_MAP

# ---------------------------------------------------------------------------
# Module-level type cache
# ---------------------------------------------------------------------------

_TYPE_CACHE: dict[str, GraphQLNamedType] = {}


def _reset_cache() -> None:
    """Clear the type cache. Called at compile_schema entry."""
    _TYPE_CACHE.clear()


# ---------------------------------------------------------------------------
# camelCase conversion: single source of truth.
# ---------------------------------------------------------------------------
# ``_to_camel_case`` is the canonical ``_strconv.to_camel_case`` (aliased for the
# existing call site). It joins digit components the same way the INPUT path
# (``pydantic.alias_generators.to_camel``) does, so OUTPUT and INPUT wire names
# stay byte-identical. (A prior local regex ``_([a-z])`` left digit components
# with a stray underscore — ``phone_1`` stayed ``phone_1``.)


# ---------------------------------------------------------------------------
# TypeRef → GraphQL type (wrapping)
# ---------------------------------------------------------------------------


def _resolve_ref(ref: TypeRef) -> Any:
    """Resolve a TypeRef to a live graphql-core type.

    Looks up the named type in _TYPE_CACHE (which is seeded with scalars
    before compilation begins).
    """
    named = _TYPE_CACHE.get(ref.name)
    if named is None:
        raise ValueError(
            f"compile_schema: unknown type {ref.name!r}. "
            f"Ensure the type is included in the 'types' list passed to compile_schema."
        )

    result: Any = named

    # Apply inner wrapping first (for nested list elements)
    if ref.inner is not None:
        result = _resolve_ref(ref.inner)
        if ref.list:
            result = GraphQLList(result)
        if ref.non_null:
            result = GraphQLNonNull(result)
        return result

    if ref.list:
        result = GraphQLList(result)
    if ref.non_null:
        result = GraphQLNonNull(result)

    return result


# ---------------------------------------------------------------------------
# Field builder (thunk-friendly, loop-capture safe)
# ---------------------------------------------------------------------------


def _make_field_thunk(spec: TypeSpec) -> Any:
    """Return a thunk that builds the fields dict for a GraphQLObjectType.

    Fields are built lazily (inside the thunk) so mutual recursion is safe:
    by the time the thunk executes, all type placeholders are in _TYPE_CACHE.
    """

    def _thunk(_spec: TypeSpec = spec) -> dict[str, GraphQLField]:
        fields: dict[str, GraphQLField] = {}
        for field_spec in _spec.fields:
            # Capture loop variable via default arg to avoid aliasing
            snake_name: str = field_spec.name
            camel_name: str = _to_camel_case(snake_name)

            # Build a type-resolving lambda that captures the current ref
            # (default-arg idiom avoids loop-var capture bug)
            field_ref: TypeRef = field_spec.type

            def _make_type_thunk(_ref: TypeRef = field_ref) -> Any:
                return _resolve_ref(_ref)

            # Default snake-closure resolver: reads snake key from dict or attr
            # Captures snake_name via default arg
            if field_spec.resolver is not None:
                resolver = field_spec.resolver
            else:

                def _default_resolver(
                    root: Any,
                    _info: Any,
                    *,
                    _name: str = snake_name,
                ) -> Any:
                    if isinstance(root, dict):
                        return root.get(_name)
                    return getattr(root, _name, None)

                resolver = _default_resolver

            gql_field = GraphQLField(
                type_=_make_type_thunk(),
                resolve=resolver,
            )
            fields[camel_name] = gql_field

        return fields

    return _thunk


# ---------------------------------------------------------------------------
# compile_type
# ---------------------------------------------------------------------------


def compile_type(spec: TypeSpec) -> GraphQLObjectType:
    """Compile a "TypeSpec" into a "GraphQLObjectType".

    Memoize-before-recurse: the placeholder object type is registered in
    "_TYPE_CACHE" BEFORE its fields thunk runs, so mutual recursion A to B to
    A terminates -- when B looks up A it finds the placeholder already cached.
    A previously compiled object type for the same name is returned as-is.

    Args:
        spec: The intermediate-representation type spec to compile.

    Returns:
        obj_type: The compiled (and cached) GraphQL object type.
    """
    if spec.name in _TYPE_CACHE:
        existing = _TYPE_CACHE[spec.name]
        if isinstance(existing, GraphQLObjectType):
            return existing

    # Build GdxPayload for extensions["gdx"]
    gdx_meta = spec.gdx if spec.gdx is not None else GdxMeta()
    payload = GdxPayload(gdx_meta)

    # Construct the type with a lazy fields thunk
    obj_type = GraphQLObjectType(
        name=spec.name,
        fields=_make_field_thunk(spec),
        description=spec.description,
        extensions={"gdx": payload},
    )

    # Register BEFORE recursion (memoize-before-recurse pattern)
    _TYPE_CACHE[spec.name] = obj_type

    return obj_type


# ---------------------------------------------------------------------------
# compile_enum
# ---------------------------------------------------------------------------


def compile_enum(spec: EnumSpec) -> GraphQLEnumType:
    """Compile an "EnumSpec" into a "GraphQLEnumType".

    Each value is registered as "GraphQLEnumValue(value=raw)" so execute-time
    delivery yields the raw Python value (int or str), not a wrapped enum
    member. A previously compiled enum for the same name is returned as-is.

    Args:
        spec: The intermediate-representation enum spec to compile.

    Returns:
        enum_type: The compiled (and cached) GraphQL enum type.
    """
    if spec.name in _TYPE_CACHE:
        existing = _TYPE_CACHE[spec.name]
        if isinstance(existing, GraphQLEnumType):
            return existing

    values: dict[str, GraphQLEnumValue] = {}
    for graphql_name, raw_value in spec.values:
        description = None
        if spec.descriptions:
            description = spec.descriptions.get(graphql_name)
        values[graphql_name] = GraphQLEnumValue(
            value=raw_value,
            description=description,
        )

    enum_type = GraphQLEnumType(
        name=spec.name,
        values=values,
    )
    _TYPE_CACHE[spec.name] = enum_type
    return enum_type


# ---------------------------------------------------------------------------
# compile_schema
# ---------------------------------------------------------------------------


def compile_schema(
    types: Sequence[TypeSpec],
    enums: Sequence[EnumSpec],
    query: TypeSpec,
    *,
    mutation: TypeSpec | None = None,
) -> GraphQLSchema:
    """Compile a full "GraphQLSchema" from intermediate-representation specs.

    Steps:
    1. "_reset_cache()" -- prevent cross-case leakage.
    2. Seed "_TYPE_CACHE" from "GDX_SCALAR_MAP".
    3. Compile all enums into "_TYPE_CACHE".
    4. Compile all types into "_TYPE_CACHE" (memoize-before-recurse).
    5. Build "GraphQLSchema".
    6. "assert_gdx_bridge(schema)" -- guard every named type.

    Args:
        types: The object-type specs to compile into the schema.
        enums: The enum specs to compile into the schema.
        query: The type spec designating the root query type.
        mutation: The type spec designating the root mutation type, or None
            for a query-only schema.

    Returns:
        schema: The compiled schema with every named type carrying its "gdx"
            bridge payload.

    Raises:
        ValueError: When the query type (or a supplied mutation type) was not
            compiled or is not a "GraphQLObjectType".
    """
    # Step 1: reset
    _reset_cache()

    # Step 2: seed scalars
    for name, scalar in GDX_SCALAR_MAP.items():
        _TYPE_CACHE[name] = scalar

    # Step 3: compile enums
    for enum_spec in enums:
        compile_enum(enum_spec)

    # Step 4: compile types
    for type_spec in types:
        compile_type(type_spec)

    # Step 5: build schema
    query_type = _TYPE_CACHE.get(query.name)
    if not isinstance(query_type, GraphQLObjectType):
        raise ValueError(
            f"compile_schema: query type {query.name!r} was not compiled "
            f"or is not a GraphQLObjectType."
        )

    mutation_type = None
    if mutation is not None:
        mutation_type = _TYPE_CACHE.get(mutation.name)
        if not isinstance(mutation_type, GraphQLObjectType):
            raise ValueError(
                f"compile_schema: mutation type {mutation.name!r} was not compiled."
            )

    schema = GraphQLSchema(
        query=query_type,
        mutation=mutation_type,
    )

    # Step 6: assert bridge
    assert_gdx_bridge(schema)

    return schema
