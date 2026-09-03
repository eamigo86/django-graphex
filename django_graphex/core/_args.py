"""Native arg declaration to graphql-core "GraphQLArgument".

Provides:
- "native_arg(value, name=None)" — the native arg-declaration API: accepts a
  "GraphQLArgument", a bare graphql-core type, or a zero-arg thunk returning
  one; resolves "out_name" from the declared key.
- "to_graphql_argument(arg, name=None)" — a thin adapter used by the mutation /
  schema-compiler call sites that may receive a non-"GraphQLArgument" arg value
  (a bare graphql-core type, or a wrapper around one). It resolves the inner type
  and wraps it in a "GraphQLArgument".

Both helpers work with graphql-core types only: "_unwrap_graphql_type" returns
a graphql-core type verbatim and raises "TypeError" for anything that is not a
graphql-core "GraphQLType".
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLArgument, Undefined
from graphql.type.definition import GraphQLType

from django_graphex._strconv import to_snake_case

# ---------------------------------------------------------------------------
# Internal type unwrapper
# ---------------------------------------------------------------------------


def _unwrap_graphql_type(gtype: Any) -> Any:
    """Resolve a field/arg type to the equivalent graphql-core type.

    The expected currency is an already-built graphql-core GraphQLType (a
    scalar / object / enum / input, OR a GraphQLList / GraphQLNonNull
    wrapper around one). It is returned VERBATIM: the native field() helper
    and the native scalar singletons already produce real graphql-core types, so
    there is nothing to convert.

    Args:
        gtype: A graphql-core GraphQLType.

    Returns:
        The corresponding graphql-core type object (returned as-is).

    Raises:
        TypeError: If gtype is not a graphql-core type.
    """
    # A graphql-core type is already in the target shape.
    # Returned as-is (List/NonNull wrappers included).
    if isinstance(gtype, GraphQLType):
        return gtype

    raise TypeError(
        f"Cannot convert {gtype!r} to a graphql-core type: expected a graphql-core "
        "GraphQLType (scalar / object / enum / input or a GraphQLList / "
        "GraphQLNonNull wrapper). Declare arguments with graphql-core types "
        "(GraphQLInt, GraphQLString, GraphQLArgument, ...). See the 2.0 upgrade "
        "guide."
    )


# ---------------------------------------------------------------------------
# Collision guard: a django.db.models.Field instance where a descriptor is expected
# ---------------------------------------------------------------------------


def _guard_django_model_field(value: Any, name: str | None = None) -> None:
    """Raise a LOUD TypeError when *value* is a django.db.models.Field.

    The most likely mistake this catches: importing CharField from
    django.db.models instead of django_graphex.core and declaring it where
    a GraphQL descriptor / arg is expected. Django Field is imported LAZILY so
    the lazy-defer convention (no top-level django import) is preserved.

    This guard fires INDEPENDENTLY at two sites (design decision #4): here (the
    native_arg path, for a class Arguments body) and in core/base.py
    (the ObjectType-body descriptor-collection loop). It is intentionally NOT
    deduplicated so each entry point fails loud on its own.

    Args:
        value: The candidate arg/descriptor value.
        name: Optional declared key, included in the error for context.
    """
    from django.db.models import Field as _DjangoModelField

    if isinstance(value, _DjangoModelField):
        where = f"{name!r}: " if name is not None else ""
        raise TypeError(
            f"{where}got a django.db.models.Field ({value!r}). Did you import "
            f"CharField from django.db.models instead of django_graphex.core? Use "
            f"django_graphex.core.CharField (or Field) for GraphQL "
            f"fields."
        )


# ---------------------------------------------------------------------------
# Native arg API (S-args-8)
# ---------------------------------------------------------------------------


def native_arg(value: Any, name: str | None = None) -> GraphQLArgument:
    """Normalise a NATIVE arg declaration to a graphql-core "GraphQLArgument".

    The native arg API on the declaration path ("Mutation.args", declared
    "field(..., args={...})"). Three declaration currencies are accepted:

    - a "GraphQLArgument" — accepted VERBATIM. When "name" is given and the arg
      carries no "out_name", a copy is returned whose "out_name" is the
      snake_case form of "name" (so graphql-core maps a camelCase wire arg back to
      the snake_case Python kwarg). An arg that already has an "out_name" is
      returned unchanged.
    - a bare graphql-core "GraphQLType" (scalar / enum / input / a
      "GraphQLList" / "GraphQLNonNull" wrapper around one) — wrapped in a
      "GraphQLArgument" (with the snake_case "out_name" when "name" is given).
    - a zero-arg callable THUNK that returns one of the above — CALLED, then its
      result re-normalised through "native_arg". This is the native LAZY form
      for an input-object arg whose compiled "GraphQLInputObjectType" is not yet
      available at class-definition time (e.g. "data = lambda: GraphQLArgument(
      GraphQLNonNull(MyInput._meta.graphql_input_type))"). graphql-core validates
      an argument's type EAGERLY (unlike a field thunk), so the lazy reference must
      be deferred at the arg level and resolved here — at "Mutation.Field()" /
      field-compile time, which runs AFTER "compile_all_inputs".

    Args:
        value: A graphql-core "GraphQLArgument", a bare graphql-core type, or a
            zero-arg callable thunk returning one of those.
        name: Optional camelCase (or snake_case) declared key; drives "out_name".

    Returns:
        A "GraphQLArgument".

    Raises:
        TypeError: When "value" (or a thunk's result) is neither a
            "GraphQLArgument" nor a graphql-core type.
    """
    _guard_django_model_field(value, name)

    # Explicit unified ``Field`` branch — placed BEFORE the callable-thunk branch. A
    # ``Field`` is not callable, so ordering is not strictly required, but
    # explicit-is-clearer: in an INPUT position a ``Field`` owns its own arg
    # construction (lazy input-type resolution + NonNull/default/out_name/
    # deprecation, plus the output-only-param guard), so delegate to it. Imported
    # lazily to avoid a descriptors <-> _args import cycle.
    from django_graphex.core.descriptors import Field

    if isinstance(value, Field):
        return value.to_graphql_argument(name=name)

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
        "GraphQLArgument, type, or a thunk returning one. Declare arguments with "
        "graphql-core types (GraphQLInt, GraphQLString, GraphQLArgument, ...) — or "
        "a lazy thunk for an input-object arg. See the 2.0 upgrade guide."
    )


# ---------------------------------------------------------------------------
# Non-native arg adapter (mutation/declared-arg compile path)
# ---------------------------------------------------------------------------
# This adapter exists for the mutation / schema-compiler call sites that receive
# an arg value which is NOT already a ``GraphQLArgument`` (a bare graphql-core
# type, or a wrapper around one). A graphql-core type is converted to a
# ``GraphQLArgument`` verbatim; anything else raises ``TypeError`` (via
# ``_unwrap_graphql_type``). The NATIVE arg-declaration path (``Mutation.args`` /
# declared field ``args``) uses ``native_arg`` directly.


def to_graphql_argument(
    arg: Any,
    name: str | None = None,
) -> GraphQLArgument:
    """Adapt a non-"GraphQLArgument" arg value to a "GraphQLArgument".

    Args:
        arg: A graphql-core type (scalar / enum / input or a "GraphQLList" /
            "GraphQLNonNull" wrapper around one), a "GraphQLArgument", or a
            unified "Field" used in an INPUT position.
        name: Optional camelCase (or snake_case) field name. When provided,
            "out_name" is set to the snake_case form of "name" so that
            graphql-core maps the argument back to the correct Python kwarg (unless
            the arg already carries an "out_name" — F1: that one is preserved).

    Returns:
        A "GraphQLArgument" wrapping the resolved graphql-core type.

    Raises:
        TypeError: If "arg" (or its ".type") is not a graphql-core type.
            Declare arguments with graphql-core types.
    """
    # Explicit unified ``Field`` branch — placed BEFORE the duck ``.type`` read
    # (C1). A ``Field`` in an INPUT position (a ``field(args={...})`` /
    # ``Field(args={...})`` dict, or a mutation ``Arguments`` member) owns its own
    # arg construction: it resolves the INPUT type via ``_meta.graphql_input_type``
    # / a bare scalar and builds an EAGER ``GraphQLNonNull``. Reading its OUTPUT
    # ``.type`` here would wrap a lazy ``NativeNonNull`` that ``_unwrap_graphql_type``
    # rejects — the exact trap. Imported lazily to avoid a descriptors <-> _args
    # import cycle.
    from django_graphex.core.descriptors import Field

    if isinstance(arg, Field):
        return arg.to_graphql_argument(name=name)

    # An already-built ``GraphQLArgument`` is adapted in place, PRESERVING every
    # attribute. F1: keep a pre-set ``out_name`` (only fill it from *name* when the
    # arg carries none) and carry ``deprecation_reason`` through — the earlier
    # implementation clobbered ``out_name`` with ``to_snake_case(name)`` and dropped
    # the deprecation reason.
    if isinstance(arg, GraphQLArgument):
        out_name = arg.out_name
        if out_name is None and name is not None:
            out_name = to_snake_case(name)
        return GraphQLArgument(
            _unwrap_graphql_type(arg.type),
            default_value=arg.default_value,
            description=arg.description,
            out_name=out_name,
            deprecation_reason=arg.deprecation_reason,
        )

    # A bare graphql-core type IS the type (scalars/enums have no ``.type``). The
    # ``.type`` read covers a wrapper carrying one; fall back to the arg itself.
    inner_type = arg.type if hasattr(arg, "type") else arg
    graphql_type = _unwrap_graphql_type(inner_type)

    out_name = to_snake_case(name) if name is not None else None

    # ``Undefined`` (not None) is graphql-core's "no default" sentinel: a None
    # fallback would stamp an explicit ``= null`` default onto every bare-type
    # argument.
    default_value = getattr(arg, "default_value", Undefined)
    description = getattr(arg, "description", None)

    return GraphQLArgument(
        graphql_type,
        default_value=default_value,
        description=description,
        out_name=out_name,
    )
