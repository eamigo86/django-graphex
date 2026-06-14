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

from django_graphex._strconv import to_snake_case
from django_graphex.native.scalars import GDX_SCALAR_MAP


# ---------------------------------------------------------------------------
# Internal type unwrapper
# ---------------------------------------------------------------------------

def _unwrap_graphene_type(gtype: Any) -> Any:
    """Recursively unwrap a graphene type to the equivalent graphql-core type.

    Handles:
    - ``graphene.types.structures.NonNull`` → ``GraphQLNonNull(inner)``
    - ``graphene.types.structures.List`` → ``GraphQLList(inner)``
    - Leaf scalar class (has ``_meta.name``) → looked up in ``GDX_SCALAR_MAP``

    Args:
        gtype: A graphene type — either a wrapper (``NonNull``/``List``) or a
            scalar/enum/object class (anything with ``_meta.name``).

    Returns:
        The corresponding graphql-core type object.

    Raises:
        KeyError: If the leaf type name is not found in ``GDX_SCALAR_MAP``.
        TypeError: If ``gtype`` is not a recognised graphene type.
    """
    # Lazy graphene import — safe when graphene is installed (called only
    # during conversion); the MODULE itself has no top-level graphene import.
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
