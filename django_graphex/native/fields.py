"""Django model -> Pydantic v2 schema (the native backend's "model -> rules").

Ports and modernizes the field map from ``djantic`` (archived, Pydantic v1) for
Pydantic v2, with total field coverage. The map is keyed by
``field.get_internal_type()`` (a string) so optional Postgres/GIS field classes
are never imported; unknown internal types degrade to ``str`` with a warning.
"""

from __future__ import annotations

import datetime
import decimal
import enum
import ipaddress
import uuid
import warnings
from typing import Any

from django.db import models
from django.utils.functional import Promise
from pydantic import Field, create_model

# -- Django internal type -> Python type -------------------------------------- #
_INT = (
    "AutoField",
    "BigAutoField",
    "SmallAutoField",
    "IntegerField",
    "SmallIntegerField",
    "BigIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "PositiveBigIntegerField",
)
_STR = (
    "CharField",
    "TextField",
    "EmailField",
    "URLField",
    "SlugField",
    "FilePathField",
    "FileField",
    "ImageField",
)

#: internal type name -> Python type. Postgres/GIS classes are referenced only by
#: their internal-type string, never imported.
FIELD_TYPES: dict[str, Any] = {
    **{name: int for name in _INT},
    **{name: str for name in _STR},
    "BooleanField": bool,
    "NullBooleanField": bool,
    "FloatField": float,
    "DecimalField": decimal.Decimal,
    "DateField": datetime.date,
    "DateTimeField": datetime.datetime,
    "TimeField": datetime.time,
    "DurationField": datetime.timedelta,
    "UUIDField": uuid.UUID,
    "BinaryField": bytes,
    "GenericIPAddressField": ipaddress.IPv4Address | ipaddress.IPv6Address,
    "JSONField": Any,
    "HStoreField": dict,
}


def _scalar_type(field: models.Field) -> Any:
    """Map a non-relational field to a Python type, with an MRO fallback."""
    internal = field.get_internal_type()
    if internal in FIELD_TYPES:
        return FIELD_TYPES[internal]
    # Postgres ArrayField: type the inner item.
    if internal == "ArrayField" and getattr(field, "base_field", None) is not None:
        return list[_scalar_type(field.base_field)]  # type: ignore[misc]
    if internal.endswith("RangeField"):
        return list[Any]
    # Unknown (custom/GIS): fall back to str so the schema still builds.
    warnings.warn(
        f"No native type mapping for {internal}; defaulting to str.",
        RuntimeWarning,
        stacklevel=2,
    )
    return str


def _choices_enum(field: models.Field) -> type[enum.Enum]:
    """Build an ``Enum`` from a field's choices (values; lazy strings coerced)."""
    members: dict[str, Any] = {}
    used: set[str] = set()
    for value, _label in field.flatchoices:
        if isinstance(value, Promise):
            value = str(value)
        name = str(value).upper().replace(" ", "_") or "EMPTY"
        while name in used:
            name += "_"
        used.add(name)
        members[name] = value
    return enum.Enum(f"{field.model.__name__}_{field.name}_choices", members)


def _python_type(field: models.Field) -> Any:
    """Resolve a field's Python type (choices -> Enum, FK -> related pk type)."""
    if field.choices:
        return _choices_enum(field)
    if isinstance(field, (models.ForeignKey, models.OneToOneField)):
        return _scalar_type(field.related_model._meta.pk)
    return _scalar_type(field)


def _field_def(field: models.Field, partial: bool) -> tuple[Any, Any]:
    """Return a Pydantic ``(annotation, FieldInfo)`` for a concrete model field."""
    py_type = _python_type(field)

    constraints: dict[str, Any] = {}
    if not field.choices and py_type is str and getattr(field, "max_length", None):
        constraints["max_length"] = field.max_length
    if py_type is decimal.Decimal:
        if field.max_digits is not None:
            constraints["max_digits"] = field.max_digits
        if field.decimal_places is not None:
            constraints["decimal_places"] = field.decimal_places

    description = str(field.help_text) if field.help_text else str(field.verbose_name)

    required = (
        not field.null
        and not field.blank
        and not field.has_default()
        and not field.primary_key
    )
    if field.null:
        py_type = py_type | None
    if partial or not required:
        default: Any = None
        if field.has_default() and callable(field.default):
            return (
                py_type,
                Field(
                    default_factory=field.default,
                    description=description,
                    **constraints,
                ),
            )
        if field.has_default():
            default = field.default
        return (py_type, Field(default=default, description=description, **constraints))
    return (py_type, Field(description=description, **constraints))


def writable_fields(model: type[models.Model]) -> list[models.Field]:
    """Return the model's writable scalar/relation fields (excludes M2M, auto)."""
    fields = []
    for field in model._meta.get_fields():
        if isinstance(field, models.ManyToManyField):
            continue
        if not getattr(field, "concrete", False) or field.primary_key:
            continue
        if field.auto_created or not field.editable:
            continue
        fields.append(field)
    return fields


def m2m_fields(model: type[models.Model]) -> list[models.ManyToManyField]:
    """Return the model's (forward) many-to-many fields."""
    return [
        f for f in model._meta.get_fields() if isinstance(f, models.ManyToManyField)
    ]


def build_model_schema(
    model: type[models.Model],
    *,
    partial: bool = False,
    base: type | None = None,
    exclude: set[str] | None = None,
) -> type:
    """Build a Pydantic model mirroring a Django model's writable fields.

    Args:
        model: The Django model class.
        partial: When True, every field is optional (update semantics).
        base: Optional user Pydantic model used as the base (for custom
            ``@field_validator`` / ``@model_validator`` rules).
        exclude: Field names to omit (e.g. a reverse FK injected at save time,
            so it isn't required in the validated payload).

    Returns:
        A dynamically created Pydantic model class.
    """
    exclude = exclude or set()
    definitions: dict[str, tuple[Any, Any]] = {}
    # Update semantics (``partial=True``) require the primary key in the input so
    # the resolver can locate the row to mutate: graphene's update input exposes
    # ``id: ID!`` (added by ``construct_fields(input_for="update")``), and
    # ``DjangoModelMutation.update`` does ``data.pop("id", None)``.  The pk is
    # excluded from ``writable_fields`` (it is not editable), so add it back here
    # for the partial case only.  The create input never carries ``id``.
    if partial and "id" not in exclude:
        pk_field = model._meta.pk
        pk_py_type = _scalar_type(pk_field)
        # ``id`` is OPTIONAL in the validation model: the resolver pops it from the
        # payload (``data.pop("id", None)``) to locate the row BEFORE the
        # remaining data is validated, so requiring it here would fail validation
        # on the popped payload. The client still supplies it on the wire (the
        # update input exposes ``id``); a missing pk simply yields a clean
        # "not found" error in the resolver rather than a validation error.
        definitions["id"] = (
            pk_py_type | None,
            Field(
                default=None,
                description="Django object unique identification field",
            ),
        )
    for field in writable_fields(model):
        if field.name in exclude or field.attname in exclude:
            continue
        definitions[field.name] = _field_def(field, partial)
    # M2M: a list of pks, always optional (attached after the parent saves).
    for field in m2m_fields(model):
        if field.name in exclude:
            continue
        pk_type = _scalar_type(field.related_model._meta.pk)
        definitions[field.name] = (list[pk_type] | None, Field(default=None))  # type: ignore[valid-type]

    kwargs: dict[str, Any] = {"__module__": __name__}
    if base is not None:
        kwargs["__base__"] = base
    return create_model(f"{model.__name__}Native", **kwargs, **definitions)  # type: ignore[call-overload]
