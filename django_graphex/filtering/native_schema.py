"""Native (graphql-core) ``<Model>FilterInput`` builder for ``GDX_BACKEND=native``.

This is the graphql-core twin of :mod:`django_graphex.filtering.schema` (the
graphene builder). It produces the SAME nested input shape so the cross-process
SDL parity harness (WU4/WU10) can assert byte-equality:

    input <Model>Filterinput {
      <camelField>: <Model><Field>Lookups   # out_name = snake field name
      <relation>:   <Related>Filterinput     # out_name = snake relation name
      ...
    }

    input <Model><Field>Lookups {
      exact: <Scalar>          # out_name = "exact"
      icontains: String        # out_name = "icontains"
      isnull: Boolean          # out_name = "isnull"
      in: [<Scalar>]           # out_name = "in"
      range: [<Scalar>]        # out_name = "range"
    }

The cardinal footgun (see design D5 / explore risk #3):
    graphql-core uses the dict key as the WIRE key (camelCase, for SDL parity)
    and ``out_name`` as the key delivered to the resolver. ``to_q`` expects
    snake ORM keys. A field WITHOUT ``out_name`` would deliver the camelCase
    wire key to ``to_q``, which would build a WRONG / EMPTY ``Q`` with NO error.
    Therefore EVERY field carries ``out_name`` set to its snake ORM lookup key.

WU3 scope: scalar/relation lookups, ``out_name`` on every field, choices enum,
``extensions['gdx']`` invariant (D8), custom ``@filter_field`` args (typed via
the native scalar bridge).

WU4 scope (here): the recursive ``and`` / ``or`` / ``not`` combinators (added
inside the field thunk so they close over the cached self-reference — the
``_NATIVE_INPUT_CACHE`` cache-before-thunk recursion guard, D5), and the
build-time completeness assertion ``_assert_filter_type_complete`` (A6) wired
into ``build_filter_input_type`` to catch the silent empty-``.fields`` footgun
that a circular thunk would otherwise ship unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from graphql import (
    GraphQLBoolean,
    GraphQLEnumType,
    GraphQLEnumValue,
    GraphQLFloat,
    GraphQLID,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInt,
    GraphQLList,
    GraphQLScalarType,
    GraphQLString,
)

from django_graphex._strconv import to_camel_case
from django_graphex.registry import get_global_registry

from .lookups import default_lookups_for
from .schema import _normalize_filter_fields, _relation_model

if TYPE_CHECKING:
    from django_graphex.registry import Registry

__all__ = ("build_filter_input_type", "_assert_filter_type_complete")


# ---------------------------------------------------------------------------
# Django internal-type name -> graphql-core scalar singleton.
#
# Mirrors the graphene map in ``filtering/schema.py:35-65`` 1:1 but yields
# graphql-core scalars (reusing the owned native scalar singletons from
# ``native/scalars.py`` so SDL names match the output path).
# ---------------------------------------------------------------------------

def _scalar_by_internal() -> dict[str, GraphQLScalarType]:
    """Build the internal-type -> graphql-core scalar map.

    Deferred so importing this module never forces the heavy scalars module if
    the native backend is inactive.
    """
    from django_graphex.native.scalars import (
        GdxDecimal,
        GdxFilterDate,
        GdxFilterDateTime,
        GdxFilterTime,
        GdxJSONString,
        GdxUUID,
    )

    return {
        "AutoField": GraphQLID,
        "BigAutoField": GraphQLID,
        "SmallAutoField": GraphQLID,
        "IntegerField": GraphQLInt,
        "SmallIntegerField": GraphQLInt,
        "BigIntegerField": GraphQLInt,
        "PositiveIntegerField": GraphQLInt,
        "PositiveSmallIntegerField": GraphQLInt,
        "PositiveBigIntegerField": GraphQLInt,
        "CharField": GraphQLString,
        "TextField": GraphQLString,
        "EmailField": GraphQLString,
        "URLField": GraphQLString,
        "SlugField": GraphQLString,
        "FilePathField": GraphQLString,
        "FileField": GraphQLString,
        "ImageField": GraphQLString,
        "GenericIPAddressField": GraphQLString,
        "BooleanField": GraphQLBoolean,
        "NullBooleanField": GraphQLBoolean,
        "FloatField": GraphQLFloat,
        "DecimalField": GdxDecimal,
        # Date/DateTime/Time use PLAIN-named filter-input scalars (Date /
        # DateTime / Time) to match graphene's filter-input map — NOT the
        # CustomDate-named OUTPUT singletons. graphene-django is internally
        # inconsistent here (CustomDate output, Date filter); native matches
        # graphene PER-PATH for full-schema SDL parity (discovery #1509).
        "DateField": GdxFilterDate,
        "DateTimeField": GdxFilterDateTime,
        "TimeField": GdxFilterTime,
        "DurationField": GraphQLString,
        "UUIDField": GdxUUID,
        "BinaryField": GraphQLString,
        "JSONField": GdxJSONString,
    }


# ---------------------------------------------------------------------------
# extensions["gdx"] payload for native filter input types (D8 invariant).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GdxFilterInputSpec:
    """Payload stored under ``extensions["gdx"]`` on every native filter input.

    Carries the source model + the GraphQL type name so read-sites (and the
    compat bridge) can route without re-deriving them.
    """

    model: Any = None
    name: str | None = None
    is_lookups: bool = False


#: Memo of generated native input types keyed by ``(model, frozenset(filter_fields))``.
#: Separate from the graphene ``schema._INPUT_CACHE`` so the two backends never
#: cross-contaminate. The and/or/not combinators (WU4) close over the cached
#: reference registered here BEFORE the field thunk evaluates (cache-before-thunk).
_NATIVE_INPUT_CACHE: dict[tuple[Any, Any, Any], GraphQLInputObjectType] = {}


def _pk_scalar(model: type[models.Model]) -> GraphQLScalarType:
    """Return the graphql-core scalar for a model's primary key."""
    return _field_scalar(model._meta.pk)


def _field_scalar(field: models.Field) -> GraphQLScalarType:
    """Map a concrete model field to its graphql-core scalar singleton.

    Args:
        field: The Django model field.

    Returns:
        The graphql-core scalar for the field's value (String fallback for
        unknown internal types, mirroring the graphene builder).
    """
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return _pk_scalar(field.related_model)
    internal = field.get_internal_type()
    scalar = _scalar_by_internal().get(internal)
    if scalar is not None:
        return scalar
    return GraphQLString


def _choices_enum(field: models.Field, registry: Registry) -> Any:
    """Return a ``GraphQLEnumType`` for a choices field, or ``GraphQLString``.

    The native output path does not (yet) register a ``GraphQLEnumType`` for
    choices fields, so we build (and memoize) one here from the field's choices,
    naming it identically to the graphene path so the future SDL-parity gate
    holds.  When the field has no choices the caller never reaches this; for
    open-ended / unresolvable choices we fall back to ``GraphQLString``.

    Args:
        field: The Django model field carrying choices.
        registry: The registry used to memoize the enum (shared with the
            graphene path's name keying).

    Returns:
        A ``GraphQLEnumType`` for the field's choices, or ``GraphQLString``.
    """
    from django_graphex.converter import get_choices

    meta = field.model._meta
    name = to_camel_case(f"{meta.app_label}_{meta.object_name}_{field.name}_Enum")

    cached = registry.get_type_for_enum(name)
    if isinstance(cached, GraphQLEnumType):
        return cached

    choices = getattr(field, "choices", None)
    if not choices:
        return GraphQLString

    values: dict[str, GraphQLEnumValue] = {}
    for choice_name, value, _description in get_choices(choices):
        values[choice_name] = GraphQLEnumValue(value=value)
    if not values:
        return GraphQLString

    enum_type = GraphQLEnumType(name=name, values=values)
    registry.register_enum(name, enum_type)
    return enum_type


def _lookups_input_type(
    model: type[models.Model],
    field: models.Field,
    field_name: str,
    lookups: tuple[str, ...] | None,
    registry: Registry,
) -> GraphQLInputObjectType:
    """Build the ``<Model><Field>Lookups`` graphql-core input for a scalar field.

    Every lookup field carries ``out_name`` equal to its lookup name so the
    coerced dict delivers snake ORM keys to ``to_q``.

    Args:
        model: The owning model.
        field: The Django model field.
        field_name: The (possibly relation-qualified) leaf field name.
        lookups: The explicit lookup tuple, or ``None`` for the defaults.
        registry: The registry providing choices enums.

    Returns:
        A ``GraphQLInputObjectType`` for the field's lookups.
    """
    if lookups is None:
        lookups = default_lookups_for(field.get_internal_type())

    if getattr(field, "choices", None):
        scalar: Any = _choices_enum(field, registry)
    else:
        scalar = _field_scalar(field)

    name = to_camel_case(f"{model._meta.object_name}_{field_name}_Lookups")
    return _build_lookups_type(name, scalar, lookups)


def _pk_lookups_input_type(
    model: type[models.Model],
    field_name: str,
    related: type[models.Model],
    lookups: tuple[str, ...] | None,
) -> GraphQLInputObjectType:
    """Build a plain-pk lookups input for a relation declared directly.

    Args:
        model: The owning model.
        field_name: The relation field name.
        related: The related model.
        lookups: The explicit lookup tuple, or ``None`` for the defaults.

    Returns:
        A ``GraphQLInputObjectType`` for the relation's pk lookups.
    """
    if lookups is None:
        lookups = default_lookups_for(related._meta.pk.get_internal_type())
    scalar = _pk_scalar(related)
    name = to_camel_case(f"{model._meta.object_name}_{field_name}_Lookups")
    return _build_lookups_type(name, scalar, lookups)


def _build_lookups_type(
    name: str, scalar: Any, lookups: tuple[str, ...]
) -> GraphQLInputObjectType:
    """Assemble a ``<...>Lookups`` input type from a scalar and lookup names.

    Args:
        name: The GraphQL type name.
        scalar: The graphql-core scalar (or enum) for the field's value.
        lookups: The lookup names to expose.

    Returns:
        A ``GraphQLInputObjectType`` whose fields each carry ``out_name``.
    """

    def _fields() -> dict[str, GraphQLInputField]:
        out: dict[str, GraphQLInputField] = {}
        for lookup in lookups:
            if lookup == "isnull":
                out[lookup] = GraphQLInputField(GraphQLBoolean, out_name=lookup)
            elif lookup in ("in", "range"):
                out[lookup] = GraphQLInputField(GraphQLList(scalar), out_name=lookup)
            else:
                out[lookup] = GraphQLInputField(scalar, out_name=lookup)
        return out

    return GraphQLInputObjectType(
        name=name,
        fields=_fields,
        extensions={
            "gdx": GdxFilterInputSpec(name=name, is_lookups=True)
        },
    )


def build_filter_input_type(
    model: type[models.Model],
    filter_fields: Any,
    registry: Registry | None = None,
    custom_filters: list | None = None,
) -> GraphQLInputObjectType | None:
    """Build (or reuse) the native ``<Model>Filterinput`` graphql-core input type.

    Produces the same nested shape as the graphene builder (per-field
    ``<Field>Lookups`` inputs + nested relation filter inputs). Every field
    carries an ``out_name`` (snake ORM key). ``and`` / ``or`` / ``not``
    combinators are added in WU4.

    Args:
        model: The Django model the input filters.
        filter_fields: The ``Meta.filter_fields`` declaration (list or dict).
        registry: The registry providing choices enums and related types;
            defaults to the global registry.
        custom_filters: Optional list of ``(arg_name, method, metadata)``
            triples from ``@filter_field``-decorated methods. Each is added as
            a plain scalar argument to the filter input type.

    Returns:
        A ``GraphQLInputObjectType``, or ``None`` when no filterable fields were
        declared (and no custom filters provided).
    """
    if not filter_fields and not custom_filters:
        return None

    if registry is None:
        registry = get_global_registry()

    normalized = _normalize_filter_fields(filter_fields) if filter_fields else {}

    custom_key = tuple(
        (name, meta.get("graphene_type")) for name, _fn, meta in (custom_filters or [])
    )
    cache_key = (
        model,
        frozenset((path, lookups) for path, lookups in normalized.items()),
        custom_key,
    )
    cached = _NATIVE_INPUT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Split paths into this model's own leaves and per-relation sub-declarations.
    own: dict[str, tuple[str, ...] | None] = {}
    relations: dict[str, dict[str, tuple[str, ...] | None]] = {}
    relation_direct: dict[str, tuple[str, ...] | None] = {}

    for path, lookups in normalized.items():
        head, sep, tail = path.partition("__")
        related = _relation_model(model, head)
        if sep:
            if related is None:
                own[path] = lookups
            else:
                relations.setdefault(head, {})[tail] = lookups
        else:
            if related is not None:
                relation_direct[head] = lookups
            else:
                own[head] = lookups

    name = to_camel_case(f"{model._meta.object_name}_FilterInput")

    def _fields() -> dict[str, GraphQLInputField]:
        out: dict[str, GraphQLInputField] = {}

        for field_name, lookups in own.items():
            try:
                field = model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            lookups_type = _lookups_input_type(
                model, field, field_name, lookups, registry
            )
            # Wire key = camelCase; out_name = snake ORM field name (footgun).
            out[to_camel_case(field_name)] = GraphQLInputField(
                lookups_type, out_name=field_name
            )

        for head, sub_fields in relations.items():
            related = _relation_model(model, head)
            if related is None:
                continue
            nested = build_filter_input_type(related, sub_fields, registry)
            if nested is not None:
                out[to_camel_case(head)] = GraphQLInputField(nested, out_name=head)

        for head, lookups in relation_direct.items():
            related = _relation_model(model, head)
            if related is None:
                continue
            pk_lookups = _pk_lookups_input_type(model, head, related, lookups)
            out[to_camel_case(head)] = GraphQLInputField(pk_lookups, out_name=head)

        for arg_name, _fn, meta in custom_filters or []:
            gql_type = _custom_filter_gql_type(meta)
            out[to_camel_case(arg_name)] = GraphQLInputField(
                gql_type, out_name=arg_name, description=meta.get("description")
            )

        # Recursive logical combinators. They reference THIS very input type, so
        # they close over ``input_type`` — which is registered in the cache
        # BEFORE this thunk can evaluate (cache-before-thunk recursion guard,
        # D5). ``and`` / ``or`` -> ``[<Self>]``; ``not`` -> ``<Self>``. Mirrors
        # the graphene builder (``filtering/schema.py:334-336``) for SDL parity.
        # ``out_name`` carries the snake combinator key so ``to_q`` reads it.
        out["and"] = GraphQLInputField(GraphQLList(input_type), out_name="and")
        out["or"] = GraphQLInputField(GraphQLList(input_type), out_name="or")
        out["not"] = GraphQLInputField(input_type, out_name="not")

        return out

    input_type = GraphQLInputObjectType(
        name=name,
        fields=_fields,
        extensions={"gdx": GdxFilterInputSpec(model=model, name=name)},
    )
    # Register BEFORE returning (and before the field thunk above can evaluate)
    # so the and/or/not combinators close over the cached reference without
    # re-entering the builder — the cache-before-thunk recursion guard (D5).
    _NATIVE_INPUT_CACHE[cache_key] = input_type
    # A6: force thunk evaluation NOW and raise if the type resolved to empty
    # ``.fields`` (the silent circular-reference footgun — a thunk that captured
    # an incomplete type would otherwise ship an empty input type unnoticed).
    _assert_filter_type_complete(input_type)
    return input_type


def _assert_filter_type_complete(gql_input_type: GraphQLInputObjectType) -> None:
    """Force thunk evaluation and assert the input type has non-empty fields.

    The deferred-fields ``lambda`` means a filter input can be constructed and
    cached BEFORE its fields exist. If a recursive combinator (and/or/not) or a
    nested relation thunk captured an *incomplete* type — e.g. the circular
    ``Category -> parent -> Category`` case where the inner type's thunk hadn't
    populated yet — the resulting ``.fields`` could silently resolve to empty and
    the schema would ship a useless input type with NO error.

    Calling this at build time forces ``.fields`` to evaluate and raises if the
    result is empty, turning the silent footgun into a loud build-time failure.

    Args:
        gql_input_type: The native filter input type to validate.

    Raises:
        AssertionError: If the type's ``.fields`` evaluates to an empty dict.
    """
    fields = dict(gql_input_type.fields)  # forces the thunk to evaluate
    assert fields, (
        f"native filter input {gql_input_type.name!r} resolved to EMPTY .fields "
        "— a thunk likely captured an incomplete (circular) type before its "
        "fields were populated. Check the cache-before-thunk ordering."
    )


def _custom_filter_gql_type(meta: dict[str, Any]) -> Any:
    """Resolve a custom ``@filter_field`` arg's graphql-core type from metadata.

    ``@filter_field`` stores the declared graphene scalar/type under the
    ``graphene_type`` metadata key (see ``filtering/filter_field.py``). Under the
    native backend we must mirror that exact type so SDL parity with the graphene
    builder holds (a ``@filter_field(graphene.Int)`` arg renders ``Int``, not
    ``String``).

    The graphene -> graphql-core translation reuses the output-path scalar
    bridge (``native/_args.py``) so the resolved scalar is the SAME singleton the
    rest of the native compiler emits.

    Args:
        meta: The ``@filter_field`` metadata dict (carries ``graphene_type``).

    Returns:
        The graphql-core type for the argument. Falls back to ``GraphQLString``
        only when no ``graphene_type`` is present (matching graphene's default).
    """
    graphene_type = meta.get("graphene_type")
    if graphene_type is None:
        return GraphQLString

    from django_graphex.native._args import _unwrap_graphene_type

    return _unwrap_graphene_type(graphene_type)
