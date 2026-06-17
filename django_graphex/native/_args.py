"""Native arg declaration → graphql-core GraphQLArgument (graphene-free, v2.0).

Provides:
- ``native_arg(value, name=None)`` — the v2.0 native arg-declaration API
  (decision #1603): accepts a ``GraphQLArgument``, a bare graphql-core type, or a
  zero-arg thunk returning one; resolves ``out_name`` from the declared key.
- ``graphene_arg_to_graphql_argument(arg, name=None)`` — a thin adapter used by
  the mutation / schema-compiler call sites that may receive a non-
  ``GraphQLArgument`` arg value (a bare graphql-core type, or a wrapper around
  one). It resolves the inner type and wraps it in a ``GraphQLArgument``.

S-del-backend-11: the graphene backend is deleted. Both helpers are graphene-free
— ``_unwrap_graphene_type`` returns a graphql-core type verbatim and RAISES
``TypeError`` for any leftover graphene type (the v2.0 CLEAN BREAK). The module
has ZERO graphene imports at any scope.
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLArgument
from graphql.type.definition import GraphQLType

from django_graphex._strconv import to_snake_case


# ---------------------------------------------------------------------------
# Internal type unwrapper
# ---------------------------------------------------------------------------

def _unwrap_graphene_type(gtype: Any) -> Any:
    """Resolve a field/arg ``type`` to the equivalent graphql-core type.

    S-del-backend-11: the graphene backend is deleted, so only the NATIVE currency
    reaches here — an already-built graphql-core ``GraphQLType`` (a scalar / object
    / enum / input, OR a ``GraphQLList`` / ``GraphQLNonNull`` wrapper around one).
    It is returned VERBATIM: the native ``field()`` helper and the native scalar
    singletons already produce real graphql-core types, so there is nothing to
    convert. The graphene fallback (a graphene ``NonNull`` / ``List`` wrapper or a
    leaf scalar/enum class with ``_meta.name`` resolved via ``GDX_SCALAR_MAP``) was
    removed — v2.0 declares args/fields with graphql-core types only.

    Args:
        gtype: A graphql-core ``GraphQLType`` (native currency).

    Returns:
        The corresponding graphql-core type object (returned as-is).

    Raises:
        TypeError: If ``gtype`` is not a graphql-core type (e.g. a leftover
            graphene type — the CLEAN BREAK off graphene, decision #1603).
    """
    # Native currency: a graphql-core type is already in the target shape.
    # Returned as-is (List/NonNull wrappers included).
    if isinstance(gtype, GraphQLType):
        return gtype

    raise TypeError(
        f"Cannot convert {gtype!r} to a graphql-core type: expected a graphql-core "
        "GraphQLType (scalar / object / enum / input or a GraphQLList / "
        "GraphQLNonNull wrapper). The graphene type form was removed in 2.0 "
        "(decision #1603); declare args/fields with graphql-core types. See the "
        "2.0 upgrade guide."
    )


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
# Non-native arg adapter (mutation/declared-arg compile fallback)
# ---------------------------------------------------------------------------
# S-del-backend-11: the graphene-ROOT compile capability + the graphene leaf
# branch of ``_unwrap_graphene_type`` are removed. This adapter still exists for
# the mutation / schema-compiler call sites that receive an arg value which is NOT
# already a ``GraphQLArgument`` (a bare graphql-core type, or a wrapper around
# one). A graphql-core type is converted to a ``GraphQLArgument`` verbatim; a
# leftover graphene type now raises ``TypeError`` (via ``_unwrap_graphene_type``)
# — the v2.0 CLEAN BREAK (decision #1603). The NATIVE arg-declaration path
# (``Mutation.args`` / declared field ``args``) uses ``native_arg`` directly.

def graphene_arg_to_graphql_argument(
    arg: Any,
    name: str | None = None,
) -> GraphQLArgument:
    """Adapt a non-``GraphQLArgument`` arg value to a ``GraphQLArgument``.

    Args:
        arg: A graphql-core type (scalar / enum / input or a ``GraphQLList`` /
            ``GraphQLNonNull`` wrapper around one), or a ``GraphQLArgument``.
        name: Optional camelCase (or snake_case) field name.  When provided,
            ``out_name`` is set to the snake_case form of *name* so that
            graphql-core maps the argument back to the correct Python kwarg.

    Returns:
        A ``GraphQLArgument`` wrapping the resolved graphql-core type.

    Raises:
        TypeError: If *arg* (or its ``.type``) is a leftover graphene type (the
            v2.0 CLEAN BREAK — declare args with graphql-core types).
    """
    # A ``GraphQLArgument`` carries its type on ``.type``; a bare graphql-core
    # type IS the type and (for scalars/enums) has no ``.type`` attribute. Fall
    # back to the arg itself so both forms resolve to a graphql-core type.
    inner_type = arg.type if hasattr(arg, "type") else arg
    graphql_type = _unwrap_graphene_type(inner_type)

    out_name: str | None = None
    if name is not None:
        out_name = to_snake_case(name)

    default_value = getattr(arg, "default_value", None)
    description = getattr(arg, "description", None)

    return GraphQLArgument(
        graphql_type,
        default_value=default_value,
        description=description,
        out_name=out_name,
    )
