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
# Native arg API (S-args-8) — graphene-free arg declaration
# ---------------------------------------------------------------------------

def native_arg(value: Any, name: str | None = None) -> GraphQLArgument:
    """Normalise a NATIVE arg declaration to a graphql-core ``GraphQLArgument``.

    The 2.0 native arg API (decision #1603 — CLEAN BREAK off graphene). It is the
    graphene-free replacement for ``graphene_arg_to_graphql_argument`` on the
    native declaration path (``Mutation.args``, declared ``field(..., args={...})``).
    Three declaration currencies are accepted, all graphene-free:

    - a ``GraphQLArgument`` — accepted VERBATIM. When *name* is given and the arg
      carries no ``out_name``, a copy is returned whose ``out_name`` is the
      snake_case form of *name* (so graphql-core maps a camelCase wire arg back to
      the snake_case Python kwarg). An arg that already has an ``out_name`` is
      returned unchanged.
    - a bare graphql-core ``GraphQLType`` (scalar / enum / input / a
      ``GraphQLList`` / ``GraphQLNonNull`` wrapper around one) — wrapped in a
      ``GraphQLArgument`` (with the snake_case ``out_name`` when *name* is given).
    - a zero-arg callable THUNK that returns one of the above — CALLED, then its
      result re-normalised through ``native_arg``. This is the native LAZY form
      for an input-object arg whose compiled ``GraphQLInputObjectType`` is not yet
      available at class-definition time (e.g. ``data = lambda: GraphQLArgument(
      GraphQLNonNull(MyInput._meta.graphql_input_type))``). graphql-core validates
      an argument's type EAGERLY (unlike a field thunk), so the lazy reference must
      be deferred at the arg level and resolved here — at ``Mutation.Field()`` /
      field-compile time, which runs AFTER ``compile_all_inputs``.

    graphene is NEVER imported. The transitional ``graphene.Argument`` form is no
    longer accepted here (it is the v2.0 breaking change; see the S8j upgrade
    guide / codemod).

    Args:
        value: A graphql-core ``GraphQLArgument``, a bare graphql-core type, or a
            zero-arg callable thunk returning one of those.
        name: Optional camelCase (or snake_case) declared key; drives ``out_name``.

    Returns:
        A ``GraphQLArgument``.

    Raises:
        TypeError: When *value* (or a thunk's result) is neither a
            ``GraphQLArgument`` nor a graphql-core type (e.g. a leftover
            ``graphene.Argument`` — the CLEAN BREAK).
    """
    out_name: str | None = to_snake_case(name) if name is not None else None

    if isinstance(value, GraphQLArgument):
        if out_name is None or value.out_name is not None:
            return value
        # Rebuild with out_name set, preserving every other attribute.
        kwargs = value.to_kwargs()
        kwargs["out_name"] = out_name
        return GraphQLArgument(**kwargs)

    if isinstance(value, GraphQLType):
        return GraphQLArgument(value, out_name=out_name)

    # Native lazy form — a zero-arg thunk deferring an input-object arg. Resolve it
    # NOW (Field()/compile time, after compile_all_inputs) and re-normalise the
    # result so the thunk may return either a GraphQLArgument or a bare type.
    # ``isinstance(value, type)`` is excluded so a graphql-core type CLASS never
    # mis-routes here (types reach the branch above as instances).
    if callable(value) and not isinstance(value, type):
        return native_arg(value(), name=name)

    where = f"{name!r} = " if name is not None else ""
    raise TypeError(
        f"Native arg declaration {where}{value!r} is not a graphql-core "
        "GraphQLArgument, type, or a thunk returning one. The graphene.Argument "
        "form was removed in 2.0 (decision #1603); declare args with graphql-core "
        "GraphQLArgument / types (or a lazy thunk for an input-object arg). See the "
        "2.0 upgrade guide."
    )


# ---------------------------------------------------------------------------
# Transitional graphene converter (still-graphene ROOTS / legacy @filter_field)
# ---------------------------------------------------------------------------
# DEFERRED (open-Q#3): tests + fixtures still declare schema ROOTS as
# ``graphene.ObjectType`` with graphene scalar fields, and ``@filter_field`` may
# pass a graphene scalar. Those paths route through this converter and the
# graphene FALLBACK in ``_unwrap_graphene_type`` above. They are retired together
# with the graphene-root short-circuits in S-del-backend-11 once every root is
# native. The NATIVE arg-declaration path (Mutation.args / declared field args)
# no longer touches this — it uses ``native_arg`` (graphene-free).

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
    # A graphene ``Argument`` carries its scalar/enum on ``.type``; a bare mounted
    # scalar instance (e.g. ``graphene.String()`` declared directly in a legacy
    # ``Input`` class) IS the type and has no ``.type`` attribute. Fall back to the
    # arg itself so both forms convert to a graphql-core ``GraphQLArgument``.
    graphene_type = arg.type if hasattr(arg, "type") else arg
    graphql_type = _unwrap_graphene_type(graphene_type)

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
