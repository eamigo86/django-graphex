"""Django model to Pydantic v2 schema (the native backend's model-to-rules).

Ports and modernizes the field map from "djantic" (archived, Pydantic v1) for
Pydantic v2, with total field coverage. The map is keyed by
"field.get_internal_type()" (a string) so optional Postgres/GIS field classes
are never imported; unknown internal types degrade to "str" with a warning.
"""

from __future__ import annotations

import datetime
import decimal
import enum
import functools
import ipaddress
import uuid
import warnings
from typing import Any

from django.core.files.base import File
from django.db import models
from django.utils.functional import Promise
from pydantic import Field, create_model
from pydantic_core import core_schema


class JSONScalar:
    """Marker annotation for a Django "JSONField" (and "HStoreField").

    Validates PERMISSIVELY (like "Any" -- a JSON value may be a dict, list,
    scalar, or None) so Pydantic never rejects a valid JSON payload, while
    remaining a DISTINCT, keyable type the input compiler recognises to render
    the field as the raw JSON scalar ("GdxJSON") instead of the plain "String"
    fallback that a bare "Any" annotation would produce.

    Using a dedicated marker (rather than mapping all "Any" annotations to
    "JSONString") keeps the fix scoped to the JSONField origin: a user's own
    "Any"-typed field on a custom "pydantic_model" base is unaffected.
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        """Return a permissive any core schema (accept any JSON value)."""
        return core_schema.any_schema()


class IDScalar:
    """Marker annotation for the synthetic primary key on an update input.

    GraphQL serializes every pk on OUTPUT as the "ID" scalar (a JSON string),
    and the sibling delete mutation declares "id: ID!". Typing the update
    input's "id" from the model's pk Python type instead made the two ends
    disagree: an integer pk rendered "id: Int", so echoing back the string a
    query returned raised 'Int cannot represent non-integer value'.

    This marker keeps the annotation a DISTINCT, keyable type the input
    compiler renders as "ID", and validates permissively (the resolver pops
    "id" before validation and hands it to the ORM, which coerces the wire
    string to the model's own pk type).
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        """Return a permissive any core schema (accept string or numeric ids)."""
        return core_schema.any_schema()


class FileScalar:
    """Marker annotation for a Django "FileField" (and "ImageField").

    A file column accepts TWO shapes and typing it "str" only ever admitted
    one: the storage-path string a query hands back, and the "UploadedFile"
    the multipart merge folds in from "info.context.FILES". The "str" mapping
    rejected every upload with 'Input should be a valid string', so no
    multipart write could ever be saved.

    Validation admits EXACTLY those two shapes, NOT the permissive "any" schema
    the sibling markers use: an int, list or dict would otherwise pass
    validation and blow up at "setattr"/"save()" as a raw Django exception --
    a 500 instead of a structured "errors[]" entry.

    Shaped as a wrap validator over the string schema rather than a
    "union_schema" of the two branches, because a union appends its branch tag
    to the error location ("attachment.constrained-str") and
    "translate_validation_error" keys the response envelope off that location:
    the union broke every file-field error key on the wire. Wrapping keeps the
    error at the field's own location with Pydantic's own message.

    "max_length" is read off the CLASS so the string branch keeps the column
    width constraint the "str" mapping carried; "_file_scalar" mints the
    per-width subclass. Consumers must therefore match with "issubclass",
    never identity.
    """

    #: Column width applied to the storage-path branch (None -> unconstrained).
    max_length: int | None = None

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        """Accept a File instance, else validate as a constrained storage path."""

        def validate(value: Any, next_: Any) -> Any:
            if isinstance(value, File):
                return value
            return next_(value)

        return core_schema.no_info_wrap_validator_function(
            validate,
            core_schema.str_schema(max_length=cls.max_length),
            # ``model_dump`` hands the value straight to ``setattr``; without an
            # ``any`` serializer Pydantic measures the accepted ``File`` against
            # the ``str`` branch and warns on every successful upload.
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: value, return_schema=core_schema.any_schema()
            ),
        )


@functools.lru_cache(maxsize=None)
def _file_scalar(max_length: int | None) -> type[FileScalar]:
    """Return the FileScalar subclass carrying this column width.

    Cached so the same width always yields the SAME class object, keeping the
    derived Pydantic schemas comparable and the schema cache effective.
    """
    if max_length is None:
        return FileScalar
    return type(f"FileScalar{max_length}", (FileScalar,), {"max_length": max_length})


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
)

#: internal type name -> Python type. Postgres/GIS classes are referenced only by
#: their internal-type string, never imported.
FIELD_TYPES: dict[str, Any] = {
    **{name: int for name in _INT},
    **{name: str for name in _STR},
    # A ``NullBooleanField`` reports "BooleanField" from ``get_internal_type()``,
    # so it needs no key of its own here (and could never reach one).
    "BooleanField": bool,
    "FloatField": float,
    "DecimalField": decimal.Decimal,
    "DateField": datetime.date,
    "DateTimeField": datetime.datetime,
    "TimeField": datetime.time,
    "DurationField": datetime.timedelta,
    "UUIDField": uuid.UUID,
    "BinaryField": bytes,
    "GenericIPAddressField": ipaddress.IPv4Address | ipaddress.IPv6Address,
    # JSONField -> a dedicated marker (NOT bare ``Any``) so the input compiler
    # renders it as the raw ``JSON`` scalar with structured passthrough on the
    # mutation path, instead of the plain ``String`` fallback that a bare ``Any``
    # produced (which double-encoded the value on save). See #JSONField.
    "JSONField": JSONScalar,
    "HStoreField": dict,
    # FileField/ImageField -> a dedicated marker (NOT ``str``) so the multipart
    # ``UploadedFile`` merged from ``context.FILES`` validates instead of being
    # rejected as a non-string. The wire type stays ``String``. See #FileField.
    "FileField": FileScalar,
    "ImageField": FileScalar,
}


def _scalar_type(field: models.Field) -> Any:
    """Map a non-relational field to a Python type, with an MRO fallback."""
    internal = field.get_internal_type()
    if internal in FIELD_TYPES:
        mapped = FIELD_TYPES[internal]
        # A file field's constraint rides on the marker CLASS: ``_field_def``
        # only attaches ``max_length`` to a bare ``str``, so resolving to the
        # per-width subclass here is what keeps the column width enforced.
        if mapped is FileScalar:
            return _file_scalar(getattr(field, "max_length", None))
        return mapped
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
    """Build an Enum from a field's choices (values; lazy strings coerced)."""
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
    """Return a Pydantic (annotation, FieldInfo) for a concrete model field."""
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
    """Return the model's writable scalar and relation fields.

    Many-to-many, auto-created, non-editable, non-concrete, and primary-key
    fields are excluded, leaving the fields a payload may set directly.

    Args:
        model: The Django model class to inspect.

    Returns:
        fields: The concrete, editable, non-M2M fields in model order.
    """
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
    """Return the model's forward, editable many-to-many fields.

    Non-editable relations are excluded for the same reason "writable_fields"
    excludes them: a field the model refuses to write must not be advertised as
    writable, or the input accepts a value and silently discards it.

    Args:
        model: The Django model class to inspect.

    Returns:
        fields: The forward, editable many-to-many fields declared on the model.
    """
    return [
        f
        for f in model._meta.get_fields()
        if isinstance(f, models.ManyToManyField) and f.editable
    ]


#: Memoization store for :func:`build_model_schema`.
#:
#: The derived Pydantic class is a PURE function of its cache key
#: ``(model, partial, base, frozenset(exclude))`` — it holds no per-request
#: state (``validate`` does not mutate the class), so the same key always yields
#: an interchangeable class and rebuilding it per request is wasted work.
#:
#: Unbounded by design: the key space is schema-static (each model has only a
#: handful of ``partial``/``base``/``exclude`` variants, the latter drawn from a
#: fixed set of reverse-FK child field names), so the dict saturates after warm
#: up and never grows with request volume. Do NOT feed it request-derived keys.
_SCHEMA_CACHE: dict[
    tuple[type[models.Model], bool, type | None, frozenset[str]], type
] = {}


def build_model_schema(
    model: type[models.Model],
    *,
    partial: bool = False,
    base: type | None = None,
    exclude: set[str] | None = None,
) -> type:
    """Build a Pydantic model mirroring a Django model's writable fields.

    The result is memoized in "_SCHEMA_CACHE" keyed by
    "(model, partial, base, frozenset(exclude))": identical calls return the
    SAME class object rather than rebuilding it (the class is stateless per
    "validate" call, so sharing it is safe).

    Args:
        model: The Django model class.
        partial: When True, every field is optional (update semantics).
        base: Optional user Pydantic model used as the base (for custom
            "@field_validator" or "@model_validator" rules).
        exclude: Field names to omit (e.g. a reverse FK injected at save time,
            so it isn't required in the validated payload). Any iterable is
            accepted; it is normalized to a "frozenset" for the cache key, so
            None, "set()" and "[]" all share the same slot.

    Returns:
        schema: A dynamically created Pydantic model class.
    """
    # Normalize ``exclude`` (varying iterables arrive from nested reverse-FK
    # children; ``None`` -> empty) so equivalent inputs share one cache slot.
    exclude_key = frozenset(exclude) if exclude else frozenset()
    cache_key = (model, partial, base, exclude_key)
    cached = _SCHEMA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    exclude = set(exclude_key)
    definitions: dict[str, tuple[Any, Any]] = {}
    # Update semantics (``partial=True``) require the primary key in the input so
    # the resolver can locate the row to mutate: graphene's update input exposes
    # ``id: ID!`` (added by ``construct_fields(input_for="update")``), and
    # ``DjangoModelMutation.update`` does ``data.pop("id", None)``.  The pk is
    # excluded from ``writable_fields`` (it is not editable), so add it back here
    # for the partial case only.  The create input never carries ``id``.
    if partial and "id" not in exclude:
        # The pk is annotated with the ``IDScalar`` marker, NOT the pk's own
        # Python type: graphene's contract (and this library's OUTPUT type and
        # delete mutation) is ``id: ID``, and a pk-typed input (``Int`` for an
        # ``AutoField``) rejected the very string a query hands back. The ORM
        # coerces the wire value to the real pk type at lookup time.
        # ``id`` is OPTIONAL in the validation model: the resolver pops it from the
        # payload (``data.pop("id", None)``) to locate the row BEFORE the
        # remaining data is validated, so requiring it here would fail validation
        # on the popped payload. The client still supplies it on the wire (the
        # update input exposes ``id``); a missing pk simply yields a clean
        # "not found" error in the resolver rather than a validation error.
        definitions["id"] = (
            IDScalar | None,
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
    schema = create_model(f"{model.__name__}Native", **kwargs, **definitions)  # type: ignore[call-overload]
    _SCHEMA_CACHE[cache_key] = schema
    return schema
