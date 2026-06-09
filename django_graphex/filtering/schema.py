"""Build the recursive ``<Model>FilterInput`` graphene input type for a model.

Generation is driven by ``Meta.filter_fields`` (list or dict form). Each model
field declared (directly or via a ``__`` relation path) yields either a nested
``<RelatedModel>FilterInput`` or a per-field ``<Field>Lookups`` input. Logical
``and`` / ``or`` / ``not`` keys are added to every input referencing itself; as
those names are Python keywords the class is built dynamically with a string-keyed
namespace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import graphene
from django.db import models
from graphene.utils.str_converters import to_camel_case

from django_graphex.registry import get_global_registry

from .lookups import default_lookups_for

if TYPE_CHECKING:
    from django_graphex.registry import Registry

__all__ = ("build_filter_input_type",)


#: Django internal-type name -> graphene scalar class (mirrors the native map in
#: ``native/fields.py``, but yields graphene scalars instead of Python types).
_SCALAR_BY_INTERNAL: dict[str, Any] = {
    "AutoField": graphene.ID,
    "BigAutoField": graphene.ID,
    "SmallAutoField": graphene.ID,
    "IntegerField": graphene.Int,
    "SmallIntegerField": graphene.Int,
    "BigIntegerField": graphene.Int,
    "PositiveIntegerField": graphene.Int,
    "PositiveSmallIntegerField": graphene.Int,
    "PositiveBigIntegerField": graphene.Int,
    "CharField": graphene.String,
    "TextField": graphene.String,
    "EmailField": graphene.String,
    "URLField": graphene.String,
    "SlugField": graphene.String,
    "FilePathField": graphene.String,
    "FileField": graphene.String,
    "ImageField": graphene.String,
    "GenericIPAddressField": graphene.String,
    "BooleanField": graphene.Boolean,
    "NullBooleanField": graphene.Boolean,
    "FloatField": graphene.Float,
    "DecimalField": graphene.Decimal,
    "DateField": graphene.Date,
    "DateTimeField": graphene.DateTime,
    "TimeField": graphene.Time,
    "DurationField": graphene.String,
    "UUIDField": graphene.UUID,
    "BinaryField": graphene.String,
    "JSONField": graphene.types.json.JSONString,
}

#: Memo of generated input types keyed by ``(model, frozenset(filter_fields))``.
_INPUT_CACHE: dict[tuple[Any, Any], Any] = {}


def _pk_scalar(model: type[models.Model]) -> Any:
    """Return the graphene scalar for a model's primary key."""
    return _field_scalar(model._meta.pk)


def _field_scalar(field: models.Field) -> Any:
    """Map a concrete model field to its graphene scalar class.

    Args:
        field: The Django model field.

    Returns:
        The graphene scalar class for the field's value.
    """
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return _pk_scalar(field.related_model)
    internal = field.get_internal_type()
    scalar = _SCALAR_BY_INTERNAL.get(internal)
    if scalar is not None:
        return scalar
    # Unknown internal type: degrade to String (keeps the input buildable).
    return graphene.String


def _choices_enum(field: models.Field, registry: Registry) -> Any:
    """Return the registered choices Enum for a field, or ``String``.

    Reuses the enum the converter registers under
    ``f"{object_name}_{field.name}_Enum"`` (camel-cased), matching the output
    type so the same enum is shared.

    Args:
        field: The Django model field carrying choices.
        registry: The registry to look the enum up in.

    Returns:
        The registered graphene Enum, or ``graphene.String`` when absent.
    """
    name = to_camel_case(f"{field.model._meta.object_name}_{field.name}_Enum")
    enum = registry.get_type_for_enum(name)
    return enum if enum is not None else graphene.String


def _normalize_filter_fields(filter_fields: Any) -> dict[str, tuple[str, ...] | None]:
    """Normalize a ``filter_fields`` declaration to ``{path: lookups | None}``.

    Args:
        filter_fields: A list of field paths, or a ``{path: lookups}`` dict.

    Returns:
        A mapping of field path to an explicit lookup tuple, or ``None`` when
        the default lookup set should apply (list form).
    """
    result: dict[str, tuple[str, ...] | None] = {}
    if isinstance(filter_fields, dict):
        for path, lookups in filter_fields.items():
            result[path] = tuple(lookups)
    else:
        for path in filter_fields or ():
            result[path] = None
    return result


def _lookups_input_type(
    model: type[models.Model],
    field: models.Field,
    field_name: str,
    lookups: tuple[str, ...] | None,
    registry: Registry,
) -> Any:
    """Build the ``<Model><Field>Lookups`` input for a scalar field.

    Args:
        model: The owning model.
        field: The Django model field.
        field_name: The (possibly relation-qualified) leaf field name.
        lookups: The explicit lookup tuple, or ``None`` for the defaults.
        registry: The registry providing choices enums.

    Returns:
        A graphene ``InputObjectType`` subclass for the field's lookups.
    """
    if lookups is None:
        lookups = default_lookups_for(field.get_internal_type())

    if getattr(field, "choices", None):
        scalar = _choices_enum(field, registry)
    else:
        scalar = _field_scalar(field)

    namespace: dict[str, Any] = {}
    for lookup in lookups:
        if lookup == "isnull":
            namespace[lookup] = graphene.Boolean()
        elif lookup in ("in", "range"):
            namespace[lookup] = graphene.List(scalar)
        else:
            namespace[lookup] = scalar()

    name = to_camel_case(f"{model._meta.object_name}_{field_name}_Lookups")
    return type(name, (graphene.InputObjectType,), namespace)


def _pk_lookups_input_type(
    model: type[models.Model],
    field_name: str,
    related: type[models.Model],
    lookups: tuple[str, ...] | None,
) -> Any:
    """Build a plain-pk lookups input for a relation declared directly.

    A relation declared with scalar lookups (e.g. ``"author": ("exact", "in")``)
    filters on the related primary key, typed as the related pk scalar (the
    native replacement for the old plain-ID relation filter).

    Args:
        model: The owning model.
        field_name: The relation field name.
        related: The related model.
        lookups: The explicit lookup tuple, or ``None`` for the defaults.

    Returns:
        A graphene ``InputObjectType`` subclass for the relation's pk lookups.
    """
    if lookups is None:
        lookups = default_lookups_for(related._meta.pk.get_internal_type())
    scalar = _pk_scalar(related)

    namespace: dict[str, Any] = {}
    for lookup in lookups:
        if lookup == "isnull":
            namespace[lookup] = graphene.Boolean()
        elif lookup in ("in", "range"):
            namespace[lookup] = graphene.List(scalar)
        else:
            namespace[lookup] = scalar()

    name = to_camel_case(f"{model._meta.object_name}_{field_name}_Lookups")
    return type(name, (graphene.InputObjectType,), namespace)


def build_filter_input_type(
    model: type[models.Model],
    filter_fields: Any,
    registry: Registry | None = None,
) -> Any:
    """Build (or reuse) the recursive ``<Model>FilterInput`` input type.

    Args:
        model: The Django model the input filters.
        filter_fields: The ``Meta.filter_fields`` declaration (list or dict).
        registry: The registry providing choices enums and related types;
            defaults to the global registry.

    Returns:
        A graphene ``InputObjectType`` subclass, or ``None`` when no filterable
        fields were declared.
    """
    if not filter_fields:
        return None

    if registry is None:
        registry = get_global_registry()

    normalized = _normalize_filter_fields(filter_fields)
    cache_key = (
        model,
        frozenset((path, lookups) for path, lookups in normalized.items()),
    )
    cached = _INPUT_CACHE.get(cache_key)
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
                # Not a relation -> treat the whole path as a transform lookup on
                # the head field (rare); fall back to a leaf on the head.
                own[path] = lookups
            else:
                relations.setdefault(head, {})[tail] = lookups
        else:
            if related is not None:
                relation_direct[head] = lookups
            else:
                own[head] = lookups

    namespace: dict[str, Any] = {}

    for field_name, lookups in own.items():
        try:
            field = model._meta.get_field(field_name)
        except Exception:
            continue
        namespace[field_name] = _lookups_input_type(
            model, field, field_name, lookups, registry
        )()

    for head, sub_fields in relations.items():
        related = _relation_model(model, head)
        if related is None:
            continue
        nested = build_filter_input_type(related, sub_fields, registry)
        if nested is not None:
            namespace[head] = nested()

    for head, lookups in relation_direct.items():
        related = _relation_model(model, head)
        if related is None:
            continue
        namespace[head] = _pk_lookups_input_type(model, head, related, lookups)()

    name = to_camel_case(f"{model._meta.object_name}_FilterInput")
    # `and` / `or` / `not` are Python keywords -> build with a string-keyed
    # namespace so they become real input fields. They reference this very type,
    # so register the (incomplete) class in the cache first to break recursion.
    input_type = type(name, (graphene.InputObjectType,), dict(namespace))
    _INPUT_CACHE[cache_key] = input_type

    input_type._meta.fields["and"] = graphene.InputField(graphene.List(input_type))
    input_type._meta.fields["or"] = graphene.InputField(graphene.List(input_type))
    input_type._meta.fields["not"] = graphene.InputField(input_type)

    return input_type


def _relation_model(model: type[models.Model], name: str) -> type[models.Model] | None:
    """Return the related model for a relation field name, else ``None``."""
    try:
        field = model._meta.get_field(name)
    except Exception:
        return None
    if field.is_relation:
        return field.related_model
    return None
