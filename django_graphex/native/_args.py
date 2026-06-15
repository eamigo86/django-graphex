"""Graphene Argument → graphql-core GraphQLArgument converter.

Provides ``graphene_arg_to_graphql_argument(arg, name=None) -> GraphQLArgument``.

Design:
- Unwraps graphene's ``NonNull`` / ``List`` wrappers recursively to produce
  the equivalent ``GraphQLNonNull`` / ``GraphQLList`` structure.
- Resolves leaf scalar types via ``GDX_SCALAR_MAP`` (keyed by graphene
  ``_meta.name``).
- Preserves ``default_value`` and ``description`` from the graphene Argument.
- Accepts an optional ``name`` kwarg (the dict key / camelCase field name).
  When provided, ``out_name`` is set to the snake_case form of that name.

Graphene import policy:
- This module READS graphene ``Argument`` objects to convert them, so a
  runtime import of graphene is required when the converter is called.
- The module itself has NO top-level ``import graphene`` — graphene is imported
  lazily inside ``_unwrap_graphene_type`` so the module can be imported cleanly
  even when graphene is absent (import-time safety).

Zero graphene symbols in the output path (``GraphQLArgument`` is graphql-core).
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLArgument, GraphQLList, GraphQLNonNull, GraphQLScalarType
from graphql.type.definition import GraphQLType

from django_graphex._strconv import to_snake_case
from django_graphex.native.scalars import GDX_SCALAR_MAP


# ---------------------------------------------------------------------------
# Internal type unwrapper
# ---------------------------------------------------------------------------

def _unwrap_graphene_type(gtype: Any) -> Any:
    """Resolve a field/arg ``type`` to the equivalent graphql-core type.

    Two currencies reach here:

    - **Native** (S-ROOTS-a) — an already-built graphql-core ``GraphQLType``
      (a scalar / object / enum / input, OR a ``GraphQLList`` / ``GraphQLNonNull``
      wrapper around one). It is returned VERBATIM: the native ``field()`` helper
      and the native scalar singletons already produce real graphql-core types,
      so there is nothing to convert. This is the path the native descriptor
      currency uses; it carries no graphene dependency.
    - **Graphene** (transitional fallback, graphene still installed) — a graphene
      ``NonNull`` / ``List`` wrapper, or a leaf scalar/enum class with
      ``_meta.name`` resolved via ``GDX_SCALAR_MAP``.

    Args:
        gtype: A graphql-core ``GraphQLType`` (native), OR a graphene type —
            either a wrapper (``NonNull``/``List``) or a scalar/enum/object
            class (anything with ``_meta.name``).

    Returns:
        The corresponding graphql-core type object.

    Raises:
        KeyError: If the leaf graphene type name is not found in ``GDX_SCALAR_MAP``.
        TypeError: If ``gtype`` is neither a graphql-core type nor a recognised
            graphene type.
    """
    # Native currency: a graphql-core type is already in the target shape.
    # Returned as-is (List/NonNull wrappers included) — no graphene import on
    # this path, so it stays valid after graphene is uninstalled.
    if isinstance(gtype, GraphQLType):
        return gtype

    # Graphene fallback — lazy import keeps the module graphene-free at import
    # time (and lets the native path above run with graphene uninstalled).
    from graphene.types.structures import List as GList, NonNull as GNonNull

    if isinstance(gtype, GNonNull):
        return GraphQLNonNull(_unwrap_graphene_type(gtype.of_type))

    if isinstance(gtype, GList):
        return GraphQLList(_unwrap_graphene_type(gtype.of_type))

    # Leaf node — must be a graphene scalar / type class with _meta.name
    try:
        name = gtype._meta.name
    except AttributeError as exc:
        raise TypeError(
            f"Cannot convert graphene type {gtype!r} to a graphql-core type: "
            "expected NonNull, List, or a scalar/type class with ._meta.name"
        ) from exc

    if name not in GDX_SCALAR_MAP:
        raise KeyError(
            f"Scalar {name!r} is not in GDX_SCALAR_MAP. "
            "Add a custom scalar mapping or extend GDX_SCALAR_MAP."
        )
    return GDX_SCALAR_MAP[name]


# ---------------------------------------------------------------------------
# Public converter
# ---------------------------------------------------------------------------

def graphene_arg_to_graphql_argument(
    arg: Any,
    name: str | None = None,
) -> GraphQLArgument:
    """Convert a graphene ``Argument`` to a graphql-core ``GraphQLArgument``.

    Args:
        arg: A ``graphene.Argument`` instance.
        name: Optional camelCase (or snake_case) field name.  When provided,
            ``out_name`` is set to the snake_case form of *name* so that
            graphql-core maps the argument back to the correct Python kwarg.

    Returns:
        A ``GraphQLArgument`` whose ``.type`` mirrors the graphene type
        hierarchy (``GraphQLNonNull`` / ``GraphQLList`` wrappers around the
        leaf ``GraphQLScalarType``).

    Example::

        import graphene
        arg = graphene.Argument(graphene.String, required=True)
        garg = graphene_arg_to_graphql_argument(arg, name="firstName")
        # garg.type   → GraphQLNonNull(GraphQLString)
        # garg.out_name → "first_name"
    """
    graphql_type = _unwrap_graphene_type(arg.type)

    out_name: str | None = None
    if name is not None:
        out_name = to_snake_case(name)

    # Retrieve optional attrs; graphene.Argument may carry these.
    default_value = getattr(arg, "default_value", None)
    description = getattr(arg, "description", None)

    return GraphQLArgument(
        graphql_type,
        default_value=default_value,
        description=description,
        out_name=out_name,
    )
