"""Django field to GraphQL type converters."""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable, Mapping
from functools import singledispatch
from typing import TYPE_CHECKING, Any, Iterator

from django.db import models
from django.db.models import Choices, JSONField
from django.utils.encoding import force_str
from django.utils.functional import Promise
from django.utils.translation import override as translation_override
from graphql.pyutils import register_description

from ._strconv import to_camel_case
from .fields import (
    ArrayField,
    DjangoNestedListObjectField,
    HStoreField,
    RangeField,
)
from .utils import (
    _generic_foreign_key_type,
    get_model_fields,
    get_related_model,
    is_required,
    to_const,
)

# Allow Django's lazy ``gettext_lazy``/``verbose_name``/``help_text`` proxies to
# be used as GraphQL descriptions (graphql-core only accepts ``str`` otherwise).
# Registered at import so lazy proxies survive description rendering.
# See https://github.com/graphql-python/graphql-core-next/issues/58.
register_description(Promise)

if TYPE_CHECKING:
    from django.db.models import Field as DjangoField
    from django.db.models import Model

    from .registry import Registry


class _DeadScalarSentinel:
    """Marker returned by SCALAR converters (the native OUTPUT/INPUT path).

    The native OUTPUT compiler (``native/output_compiler.compile_output_fields``)
    reads ``model._meta`` DIRECTLY and maps each Django scalar field to a native
    scalar (DateField->GdxDate, BinaryField->GraphQLString, CharField->
    GraphQLString, …). It NEVER reads a per-field DESCRIPTOR from the converter —
    so building one would be DEAD work. Each SCALAR ``convert_django_field``
    dispatcher therefore returns this sentinel, and ``construct_fields`` OMITS the
    field from the produced dict — a PER-FIELD-TYPE skip (#1552): GFK, the relation
    markers, and the nested-list (``_nested_list_object_field``) descriptors are
    NOT scalars and so are KEPT, never returning this sentinel.

    Scalars unconditionally return this sentinel — no per-field descriptor is
    built for them.
    """

    __slots__ = ()


#: Singleton sentinel instance (identity-comparable in ``construct_fields``).
_DEAD_SCALAR = _DeadScalarSentinel()


def _nested_list_object_field(
    field: DjangoField,
    model: type[Model],
    registry: Registry | None,
    accessor: str,
) -> DjangoNestedListObjectField | None:
    """Build the uniform "results"/"totalCount" field for a related list.

    Reuse the model's registered "DjangoListObjectType" (so its pagination and
    filter config are honored) or auto-generate one. Return None (field skipped)
    when the related model has no registered node type, matching the previous
    gating.

    Args:
        field: the Django relation field being converted.
        model: the related Django model class.
        registry: the type registry, or None when no registry is available.
        accessor: the parent attribute name for the related set.

    Returns:
        The nested list object field, or None when no node type is registered.
    """
    if registry is None or registry.get_type_for_model(model) is None:
        return None

    from .types import get_or_create_list_object_type

    list_type = get_or_create_list_object_type(model, registry)
    description = getattr(field, "help_text", None) or getattr(
        field, "verbose_name", None
    )
    return DjangoNestedListObjectField(
        list_type, accessor=accessor, description=description or None
    )


NAME_PATTERN = r"^[_a-zA-Z][_a-zA-Z0-9]*$"
COMPILED_NAME_PATTERN = re.compile(NAME_PATTERN)


def assert_valid_name(name: str) -> None:
    """Assert that the provided name is valid for GraphQL.

    Args:
        name: the candidate name to validate.

    Raises:
        AssertionError: if "name" does not match the GraphQL name pattern.
    """
    assert COMPILED_NAME_PATTERN.match(name), (
        f'Names must match /{NAME_PATTERN}/ but "{name}" does not.'
    )


def _is_valid_name(name: str) -> bool:
    """Return whether ``name`` is a usable, non-empty GraphQL enum name."""
    return bool(name) and bool(COMPILED_NAME_PATTERN.match(name))


def convert_choice_name(name: Any) -> str:
    """Convert a Django choice value to a valid GraphQL enum name.

    Args:
        name: the raw choice value to convert.

    Returns:
        A GraphQL-safe enum name, prefixed when otherwise invalid.
    """
    const = to_const(force_str(name))
    return const if _is_valid_name(const) else f"A_{const}"


def choice_enum_name(value: Any, label: Any) -> str:
    """Pick a readable GraphQL enum-member name for a (value, label) choice.

    Cascade (so numeric/opaque values don't surface as "A_1"):

    1. the value if it is non-blank and yields a valid GraphQL name (e.g.
       "draft" -> "DRAFT");
    2. otherwise the label, resolved as its source string with translations
       deactivated -- so a lazy '_("Male")' becomes "MALE" deterministically,
       independent of the active locale;
    3. a blank value (empty or whitespace) with no usable label -> "EMPTY"
       (the "no selection" choice);
    4. otherwise "A_<value>" as a last resort.

    Args:
        value: the stored choice value.
        label: the human-readable choice label (may be a lazy string).

    Returns:
        A GraphQL-safe enum-member name.
    """
    value_str = force_str(value)
    value_is_blank = not value_str.strip()
    from_value = to_const(value_str)
    if not value_is_blank and _is_valid_name(from_value):
        return from_value
    if label is not None:
        # Resolve the label to its source msgid (not the active translation) so
        # the schema's enum names are stable across locales.
        with translation_override(None):
            from_label = to_const(force_str(label))
        # Require at least one alphanumeric char so a junk label (e.g. all
        # whitespace -> "_") doesn't win over the EMPTY / A_<value> fallback.
        if _is_valid_name(from_label) and any(ch.isalnum() for ch in from_label):
            return from_label
    # A blank value ("" / whitespace) is the "no selection" choice -> EMPTY.
    if value_is_blank:
        return "EMPTY"
    return f"A_{from_value}"


def _normalize_choices(choices: Any) -> Any:
    """Normalize Django field choices to an iterable of pairs.

    Django 5.0 lets "choices" be a mapping, a callable, or an enumeration type
    passed directly, and normalizes "field.choices" to a list of 2-tuples. On
    Django 4.x there is no such normalization, so handle those forms here too:
    an enumeration type uses its "choices", a callable is called, and a mapping
    is expanded to its items. A plain iterable of pairs passes through.

    Args:
        choices: The raw choices in any supported declaration form.

    Returns:
        An iterable of (value, label) pairs.
    """
    # A Choices subclass (TextChoices / IntegerChoices) is itself callable, so it
    # must be handled before the callable branch.
    if isinstance(choices, type) and issubclass(choices, Choices):
        choices = choices.choices
    if isinstance(choices, Callable):
        choices = choices()
    if isinstance(choices, Mapping):
        choices = choices.items()
    return choices


def get_choices(
    choices: Any, converted_names: list[str] | None = None
) -> Iterator[tuple[str, Any, Any]]:
    """Extract choices from Django field choices recursively.

    The de-duplication state is threaded through the recursion so a label
    repeated across two option groups ("Other", "None", "Unknown" are routine)
    gets the same numeric suffix a repeated label inside ONE group would get,
    instead of collapsing into a single enum member bound to the last value.
    Names that do not collide are never suffixed, so existing SDL is untouched.

    Args:
        choices: Django field choices in any supported form (an iterable of
            pairs, a mapping, a callable, or an enumeration type), possibly
            nested for grouped choices.
        converted_names: Names already emitted by an enclosing call, or None to
            start a fresh de-duplication scope. Internal to the recursion.

    Yields:
        Tuples of (name, value, description) for each leaf choice.
    """
    choices = _normalize_choices(choices)
    if converted_names is None:
        converted_names = []
    for value, help_text in choices:
        if isinstance(help_text, (tuple, list)):
            yield from get_choices(help_text, converted_names)
        else:
            name = choice_enum_name(value, help_text)
            while name in converted_names:
                name += f"_{len(converted_names)!s}"
            converted_names.append(name)
            description = help_text
            yield name, value, description


def convert_django_field_with_choices(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django field with choices to a GraphQL enum or list field.

    Args:
        field: the Django model field to convert.
        registry: the type registry used to look up and store enums.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        The GraphQL field for the choices, or the plain converted field when
        the source field has no choices.
    """
    # Belt-and-braces: ensure the contenttypes converters are registered before
    # any dispatch (AppConfig.ready already does this, but direct callers and
    # the test suite may reach here first).
    _ensure_contenttypes_converters_registered()
    choices = getattr(field, "choices", None)
    if choices:
        # The choices field is rendered as a ``GraphQLEnumType`` built from
        # ``model._meta`` (``build_choices_enum_type``, S-enum-1) — on OUTPUT by
        # ``output_compiler._compile_choices_enum_field`` and on INPUT by
        # ``input_compiler.compile_input_type`` (the shared canonical enum). No
        # converter descriptor is read on either path, so return the dead-scalar
        # sentinel and let ``construct_fields`` OMIT it — like the PK
        # (``convert_field_to_id``) and the relation markers (S-rel-2/3/4).
        return _DEAD_SCALAR
    return convert_django_field(field, registry, input_flag, nested_field)


def choices_enum_name(field: DjangoField, input_flag: str | None = None) -> str:
    """Return the CANONICAL GraphQL enum name for a choices field.

    Keyed by (app_label, object_name, field_name) so two models that share a
    class name across different Django apps — and carry the same choices-field
    name — never collide in the registry (mirrors the (model_class, for_input)
    keying used for object/input types). When "input_flag" is set the name is
    suffixed so an input-only enum never clobbers the output slot.

    This is the SINGLE source of truth for the choices-enum name shared by the
    converter, the native OUTPUT compiler and the native filter-input builder, so
    all three resolve the SAME registry slot for one (model, field) pair.

    Args:
        field: the Django model field carrying choices.
        input_flag: input action key, or None for an output field.

    Returns:
        The canonical camelCase enum name.
    """
    meta = field.model._meta
    name = f"{meta.app_label}_{meta.object_name}_{field.name}_Enum"
    if input_flag:
        name = f"{name}_{input_flag}"
    return to_camel_case(name)


#: Prefix for the NATIVE choices-enum registry slot. The native graphql-core
#: ``GraphQLEnumType`` is stored under a distinct, native-namespaced key so the
#: native OUTPUT and FILTER-INPUT paths share ONE slot to converge on
#: (S-enum-1) without colliding with any other registry entry keyed by the bare
#: canonical name.
_NATIVE_ENUM_SLOT_PREFIX = "__native__"


def build_choices_enum_type(
    field: DjangoField,
    registry: Registry,
    input_flag: str | None = None,
) -> Any:
    """Build (or fetch the cached) graphql-core "GraphQLEnumType" for a choices field.

    Canonical builder. Reuses "get_choices" (the 4-tier "choice_enum_name"
    cascade) for the value names + per-choice descriptions, and compiles via
    "core.compiler.compile_enum" so the native OUTPUT and FILTER-INPUT paths
    share ONE instance per (model, field) pair:

    * "GraphQLEnumValue.value" carries the RAW python value, so resolution
      returns the stored value.
    * "GraphQLEnumValue.description" carries the per-choice label so the SDL
      keeps per-choice descriptions (oracle req #7).

    Sharing slot: the enum is memoized in the registry under a NATIVE-namespaced
    key ("_NATIVE_ENUM_SLOT_PREFIX" + "choices_enum_name"). The namespaced key
    keeps the graphql-core enum from being clobbered by — or returned in place
    of — any other registry entry under the bare canonical name, while the
    OUTPUT and FILTER-INPUT paths both converge on this one native slot. The
    GraphQLEnumType STILL carries the bare canonical NAME for SDL parity; only
    the registry KEY is namespaced.

    Args:
        field: the Django model field carrying choices.
        registry: the registry whose enum slot is shared across native paths.
        input_flag: input action key, or None for an output field.

    Returns:
        A "GraphQLEnumType" for the field's choices, or None when the field has
        no usable choices.
    """
    from graphql import GraphQLEnumType  # noqa: PLC0415

    from .core.compiler import compile_enum  # noqa: PLC0415
    from .core.ir import EnumSpec  # noqa: PLC0415

    name = choices_enum_name(field, input_flag)
    slot_key = f"{_NATIVE_ENUM_SLOT_PREFIX}{name}"

    cached = registry.get_type_for_enum(slot_key)
    if isinstance(cached, GraphQLEnumType):
        return cached

    choices = getattr(field, "choices", None)
    if not choices:
        return None

    values: list[tuple[str, Any]] = []
    descriptions: dict[str, str] = {}
    for choice_name, value, description in get_choices(choices):
        values.append((choice_name, value))
        if description is not None:
            descriptions[choice_name] = force_str(description)
    if not values:
        return None

    enum_type = compile_enum(
        EnumSpec(
            name=name,
            values=tuple(values),
            descriptions=descriptions or None,
        )
    )
    registry.register_enum(slot_key, enum_type)
    return enum_type


def construct_fields(
    model: type[Model],
    registry: Registry,
    only_fields: Any,
    include_fields: Any,
    exclude_fields: Any,
    input_flag: str | None = None,
    nested_fields: tuple[str, ...] = (),
) -> OrderedDict[str, Any]:
    """Construct GraphQL fields from Django model fields.

    Args:
        model: the Django model class to build fields from.
        registry: the type registry used during conversion.
        only_fields: field names to include exclusively, or a falsy value.
        include_fields: field names to force-include regardless of filters.
        exclude_fields: field names to exclude from the result.
        input_flag: input action key, or None for an output type.
        nested_fields: names of fields to treat as nested.

    Returns:
        An ordered mapping of field name to converted GraphQL field.
    """
    _ensure_contenttypes_converters_registered()
    _generic_foreign_key = _generic_foreign_key_type()
    _model_fields = get_model_fields(model)

    # Sort unconditionally so dev and prod SDLs are identical (issue #19).
    # Previously gated on settings.DEBUG, which caused field-order skew between
    # environments and broke SDL snapshot tests in production.
    if input_flag == "create":
        _model_fields = sorted(
            _model_fields, key=lambda f: (not is_required(f[1]), f[0])
        )
    elif not input_flag:
        _model_fields = sorted(_model_fields, key=lambda f: f[0])

    fields = OrderedDict()

    if input_flag == "delete":
        converted = convert_django_field_with_choices(
            dict(_model_fields)["id"], registry
        )
        fields["id"] = converted
    else:
        for name, field in _model_fields:
            if input_flag == "create" and name == "id":
                continue
            is_included = include_fields and name in include_fields
            nested_field = name in nested_fields
            is_not_in_only = only_fields and name not in only_fields
            is_excluded = exclude_fields and name in exclude_fields
            # A trailing "+" means related_query_name is disabled (no back ref):
            # https://docs.djangoproject.com/en/stable/ref/models/fields/#django.db.models.ForeignKey.related_query_name
            is_no_backref = str(name).endswith("+")
            if not is_included and (is_not_in_only or is_excluded or is_no_backref):
                # We skip this field if we specify only_fields and is not
                # in there. Or when we exclude this field in exclude_fields.
                # Or when there is no back reference.
                continue
            if (
                input_flag
                and not field.editable
                and not isinstance(
                    field,
                    (models.fields.related.ForeignObjectRel, _generic_foreign_key),
                )
            ):
                continue

            converted = convert_django_field_with_choices(
                field, registry, input_flag, nested_field
            )
            # PER-FIELD-TYPE native skip (#1552 / S-ROOTS-d): a SCALAR converter
            # returns the dead-scalar sentinel because the native output compiler
            # derives the scalar from model._meta directly and never reads this
            # descriptor. OMIT it so the dead scalar descriptor is not even built.
            # GFK / relation / nested-list converters never return the sentinel,
            # so they are KEPT.
            if converted is _DEAD_SCALAR:
                continue
            fields[name] = converted
    return fields


@singledispatch
def convert_django_field(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django field to a GraphQL field type using singledispatch.

    Args:
        field: the Django model field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        The GraphQL field corresponding to the Django field.

    Raises:
        TypeError: if there is no registered converter for the field type.
    """
    raise TypeError(
        f"Don't know how to convert the Django field {field} ({field.__class__})"
    )


@convert_django_field.register(models.CharField)
@convert_django_field.register(models.TextField)
@convert_django_field.register(models.EmailField)
@convert_django_field.register(models.SlugField)
@convert_django_field.register(models.URLField)
@convert_django_field.register(models.GenericIPAddressField)
@convert_django_field.register(models.FileField)
def convert_field_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert Django string fields to the GraphQL String type.

    Args:
        field: the Django string field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL String field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.AutoField)
def convert_field_to_id(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django AutoField to the GraphQL ID type.

    Args:
        field: the Django auto field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL ID field for the Django field.
    """
    # INPUT (create / update): the native PK input surface is built by
    # ``input_compiler.compile_input_type`` from the generated Pydantic model
    # (``id: Int`` on update; omitted on create). OUTPUT (``input_flag is None``):
    # the native output compiler renders the PK as ``id: ID!`` directly from
    # ``model._meta`` (AutoField -> GraphQLID + ``GraphQLNonNull`` for the primary
    # key, see ``output_compiler._to_graphql_field``). Neither path reads a
    # converter descriptor, so return the dead-scalar sentinel and let
    # ``construct_fields`` omit it (S-rel-2 / S-input-5).
    return _DEAD_SCALAR


@convert_django_field.register(models.UUIDField)
def convert_field_to_uuid(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django UUIDField to the GraphQL UUID type.

    Args:
        field: the Django UUID field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL UUID field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.PositiveIntegerField)
@convert_django_field.register(models.PositiveSmallIntegerField)
@convert_django_field.register(models.SmallIntegerField)
@convert_django_field.register(models.BigIntegerField)
@convert_django_field.register(models.IntegerField)
def convert_field_to_int(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert Django integer fields to the GraphQL Int type.

    Args:
        field: the Django integer field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL Int field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.BooleanField)
def convert_field_to_boolean(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django BooleanField to the GraphQL Boolean type.

    Args:
        field: the Django boolean field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL Boolean field, non-null when required on create.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.NullBooleanField)
def convert_field_to_nullboolean(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django NullBooleanField to the GraphQL Boolean type.

    Args:
        field: the Django nullable boolean field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL Boolean field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.BinaryField)
def convert_binary_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django BinaryField to the custom Binary scalar type.

    Args:
        field: the Django binary field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL Binary field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.DecimalField)
@convert_django_field.register(models.FloatField)
@convert_django_field.register(models.DurationField)
def convert_field_to_float(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert Django decimal, float, and duration fields to GraphQL Float.

    Args:
        field: the Django decimal, float, or duration field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL Float field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.DateField)
def convert_date_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django DateField to the custom CustomDate scalar type.

    Args:
        field: the Django date field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL CustomDate field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.DateTimeField)
def convert_datetime_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django DateTimeField to the custom CustomDateTime scalar type.

    Args:
        field: the Django datetime field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL CustomDateTime field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.TimeField)
def convert_time_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django TimeField to the custom CustomTime scalar type.

    Args:
        field: the Django time field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL CustomTime field for the Django field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(models.OneToOneRel)
def convert_onetoone_field_to_djangomodel(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django OneToOneRel field to a GraphQL field.

    Args:
        field: the Django one-to-one relation field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A "NativeRelationField" presence/ordering marker.
    """
    model = field.related_model

    # A reverse OneToOne is compiled DIRECTLY from ``model._meta`` — on OUTPUT by
    # ``types._compile_reverse_o2o_fields`` (it walks ``OneToOneRel`` reverse
    # relations and resolves via the per-type registry); on INPUT by
    # ``types._resolve_native_relation_input_fields`` ->
    # ``input_compiler.compile_input_type`` (a reverse-O2O becomes a single
    # ``ID``). Neither path reads a converter descriptor: it flows into
    # ``_meta.fields`` only as a PRESENCE/ORDERING marker. Emit a
    # ``NativeRelationField`` (never ``None`` — the silent-drop trap) so the field
    # stays in ``_meta.fields`` with the SAME ``creation_counter`` for SDL field
    # ORDER. (S-rel-2 OUTPUT; S-input-5 INPUT.)
    from .core.descriptors import NativeRelationField  # noqa: PLC0415

    return NativeRelationField(related_model=model)


@convert_django_field.register(models.ManyToManyField)
def convert_field_to_list_or_connection(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django ManyToManyField to a GraphQL list or connection field.

    Args:
        field: the Django many-to-many field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A "NativeRelationField" presence/ordering marker.
    """
    model = get_related_model(field)

    # The forward-M2M to-MANY field is compiled DIRECTLY from ``model._meta`` — on
    # OUTPUT by ``types._compile_relation_list_fields`` (which reuses the related
    # node's ``<Model>ListType`` results/totalCount CONTAINER via
    # ``_nested_list_object_field`` and emits the final field via
    # ``schema_compiler._build_list_object_field``); on INPUT by
    # ``types._resolve_native_relation_input_fields`` ->
    # ``input_compiler.compile_input_type`` (M2M -> ``[ID!]``). Neither path reads
    # a converter descriptor: it flows into ``_meta.fields`` only as a
    # PRESENCE/ORDERING marker. Emit a ``NativeRelationField`` (the
    # silent-drop guard, never ``None`` / ``_DEAD_SCALAR``) carrying the SAME
    # ``creation_counter`` for SDL field ORDER. (S-rel-3 OUTPUT; S-input-5 INPUT.)
    from .core.descriptors import NativeRelationField  # noqa: PLC0415

    return NativeRelationField(related_model=model)


@convert_django_field.register(models.ManyToManyRel)
@convert_django_field.register(models.ManyToOneRel)
def convert_many_rel_to_djangomodel(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert Django many-to-many relation fields to GraphQL list fields.

    Args:
        field: the Django reverse many relation field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A "NativeRelationField" presence/ordering marker
        (reverse FK / reverse M2M / reverse "GenericRel").
    """
    model = field.related_model

    # A reverse-FK (``ManyToOneRel``) / reverse-M2M (``ManyToManyRel``) to-MANY
    # field is compiled DIRECTLY from ``model._meta`` — on OUTPUT by
    # ``types._compile_relation_list_fields`` (reusing the related node's
    # ``<Model>ListType`` results/totalCount CONTAINER); on INPUT by
    # ``types._resolve_native_relation_input_fields`` ->
    # ``input_compiler.compile_input_type`` (reverse to-many -> ``[ID!]``, reverse
    # O2O -> ``ID``). Neither path reads a converter descriptor: it flows into
    # ``_meta.fields`` only as a PRESENCE/ORDERING marker. Emit a
    # ``NativeRelationField`` (the silent-drop guard, never ``None`` /
    # ``_DEAD_SCALAR``) carrying the SAME ``creation_counter`` for SDL field ORDER.
    # This converter ALSO handles the reverse ``GenericRel`` (the reverse side of a
    # ``GenericRelation`` declared with ``related_query_name``), which is NOT
    # rendered by the native output compiler at all
    # (``output_compiler._is_many_relation`` is False for ``GenericRel``).
    # (S-rel-3/4 OUTPUT; S-input-5 INPUT.)
    from .core.descriptors import NativeRelationField  # noqa: PLC0415

    return NativeRelationField(related_model=model)


@convert_django_field.register(models.OneToOneField)
@convert_django_field.register(models.ForeignKey)
def convert_field_to_djangomodel(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django ForeignKey or OneToOneField to a GraphQL field.

    Args:
        field: the Django foreign-key or one-to-one field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A "NativeRelationField" presence/ordering marker.
    """
    model = get_related_model(field)

    # The to-ONE FK / forward-O2O field is compiled DIRECTLY from ``model._meta``
    # — on OUTPUT by ``output_compiler._to_graphql_field`` (the to-ONE arm); on
    # INPUT by ``types._resolve_native_relation_input_fields`` ->
    # ``input_compiler.compile_input_type`` (FK / forward-O2O -> single ``ID``,
    # ``ID!`` when required on create). Neither path reads a converter descriptor:
    # it flows into ``_meta.fields`` only as a PRESENCE/ORDERING marker. Emit a
    # ``NativeRelationField`` so the field stays in ``_meta.fields``
    # (the silent-drop guard, never ``None`` / ``_DEAD_SCALAR`` — cf. test_issue52
    # self-ref O2O) with the SAME ``creation_counter`` for SDL field ORDER.
    # (S-rel-2 OUTPUT; S-input-5 INPUT.)
    from .core.descriptors import NativeRelationField  # noqa: PLC0415

    return NativeRelationField(related_model=model)


def convert_generic_foreign_key_to_object(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django GenericForeignKey to a GraphQL object type.

    Args:
        field: the Django generic foreign-key field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A "NativeRelationField" presence/ordering marker.
    """
    model = field.model

    # The FLAT GenericForeignKey field is compiled DIRECTLY from ``model._meta`` —
    # on OUTPUT by ``output_compiler._compile_generic_foreign_key`` (the flat
    # ``GenericForeignKeyType`` with appLabel / id / modelName); the INPUT GFK
    # surface is built by the native input compiler from ``model._meta`` too. The
    # Track-2 typed GFK-UNION OUTPUT path is ALSO native: the union injector
    # ``types._compile_gfk_union_output_fields`` reads ``model._meta`` +
    # ``registry.get_gfk_union`` DIRECTLY and last-wins-overrides the flat field.
    # No converter descriptor is read on any path — flat OUTPUT, union OUTPUT, or
    # INPUT — so emit a ``NativeRelationField`` presence/ordering
    # marker (the silent-drop guard, never ``None`` / ``_DEAD_SCALAR``) with the
    # SAME ``creation_counter`` for SDL field ORDER. The flat type, union Field,
    # and mis-order WARNING are emitted by the native union injector.
    # (S-rel-4 / S-input-5.)
    from .core.descriptors import NativeRelationField  # noqa: PLC0415

    return NativeRelationField(related_model=model)


def convert_generic_relation_to_object_list(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a Django GenericRelation to a GraphQL list field.

    Args:
        field: the Django generic relation field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL Dynamic field that resolves lazily to the related list, or a
        "NativeRelationField" marker on the native OUTPUT path.
    """
    model = field.related_model

    # OUTPUT (``input_flag is None``): a forward ``GenericRelation`` to-MANY field
    # is compiled DIRECTLY from ``model._meta`` by
    # ``types._compile_relation_list_fields`` (``output_compiler._is_many_relation``
    # matches ``GenericRelation``, reusing the related node's ``<Model>ListType``
    # results/totalCount CONTAINER) — it NEVER reads a converter descriptor. Emit a
    # ``NativeRelationField`` presence/ordering marker so the field
    # stays in ``_meta.fields`` (the silent-drop guard, never ``None``) with the
    # SAME ``creation_counter`` for SDL field ORDER. The INPUT path produces NO
    # field (``GenericRelation`` has no input) — return the dead-scalar sentinel so
    # ``construct_fields`` OMITS it. (S-rel-4.)
    if input_flag is None:
        from .core.descriptors import NativeRelationField  # noqa: PLC0415

        return NativeRelationField(related_model=model)
    return _DEAD_SCALAR


# The ``django.contrib.contenttypes.fields`` module imports the ``ContentType``
# MODEL at its top, so registering the GFK / GenericRel / GenericRelation
# converters at MODULE LOAD (the natural ``@convert_django_field.register(...)``
# decorator) would touch the model registry during app-population and raise
# ``AppRegistryNotReady`` whenever ``django_graphex`` is in ``INSTALLED_APPS``.
# Those three converters are therefore defined as plain functions above and
# registered LAZILY once the app registry is ready: ``AppConfig.ready`` calls
# this, and the conversion entry points call it too as a belt-and-braces guard.
# ``functools.singledispatch.register`` is idempotent, so repeated calls are
# safe and cheap.
_CONTENTTYPES_CONVERTERS_REGISTERED = False


def _ensure_contenttypes_converters_registered() -> None:
    """Register the contenttypes field converters on first use (lazy import).

    Importing ``django.contrib.contenttypes.fields`` is deferred until after the
    app registry is ready so that importing ``django_graphex`` never loads the
    ``ContentType`` model prematurely. The registration is performed once and the
    result memoized in a module flag.
    """
    global _CONTENTTYPES_CONVERTERS_REGISTERED
    if _CONTENTTYPES_CONVERTERS_REGISTERED:
        return
    from django.contrib.contenttypes.fields import (  # noqa: PLC0415
        GenericForeignKey,
        GenericRel,
        GenericRelation,
    )

    # ``GenericRel`` (the reverse side of a ``GenericRelation``) shares the
    # reverse-many converter with ``ManyToManyRel`` / ``ManyToOneRel``.
    convert_django_field.register(GenericRel, convert_many_rel_to_djangomodel)
    convert_django_field.register(
        GenericForeignKey, convert_generic_foreign_key_to_object
    )
    convert_django_field.register(
        GenericRelation, convert_generic_relation_to_object_list
    )
    _CONTENTTYPES_CONVERTERS_REGISTERED = True


@convert_django_field.register(ArrayField)
def convert_postgres_array_to_list(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a PostgreSQL ArrayField to the GraphQL List type.

    Args:
        field: the Django array field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL List field wrapping the converted base field type.
    """
    # S-del-backend-11: the native OUTPUT compiler derives every field from
    # ``model._meta`` directly and has NO ArrayField entry — no converter
    # descriptor is read. Return the dead-scalar sentinel so ``construct_fields``
    # OMITS it (SDL-neutral — ArrayField is already absent from native output SDL).
    return _DEAD_SCALAR


@convert_django_field.register(HStoreField)
@convert_django_field.register(JSONField)
def convert_postgres_field_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """HStore / JSON field converter descriptor — DEAD on the native path.

    S-del-backend-11: the native OUTPUT compiler derives the scalar for
    HStore/JSON fields directly from "model._meta" — "output_compiler" maps
    "models.JSONField" to the raw "JSON" scalar ("GdxJSON") by default, so
    structured objects/lists pass through as-is on the wire. The
    string-encoded "JSONString" wire is an opt-in escape hatch via the
    "JSONField(n=True)" descriptor flag, not the default mapping. The native
    INPUT compiler and the filter-input map follow the same default
    ("filtering.native_schema"). No converter descriptor is read, so this
    returns the dead-scalar sentinel to keep "construct_fields" SDL-neutral.

    Args:
        field: the Django HStore or JSON field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        The "_DEAD_SCALAR" sentinel so "construct_fields" OMITS the field.
    """
    return _DEAD_SCALAR


@convert_django_field.register(RangeField)
def convert_postgres_range_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert a PostgreSQL RangeField to the GraphQL List type.

    Args:
        field: the Django range field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL List field wrapping the converted inner field type.
    """
    # S-del-backend-11: the native OUTPUT compiler derives every field from
    # ``model._meta`` directly and has NO RangeField entry — no converter
    # descriptor is read. Return the dead-scalar sentinel so ``construct_fields``
    # OMITS it (SDL-neutral — RangeField is already absent from native output SDL).
    return _DEAD_SCALAR
