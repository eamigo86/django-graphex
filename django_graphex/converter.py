"""Django field to GraphQL type converters."""

from __future__ import annotations

import os
import re
import warnings
from collections import OrderedDict
from collections.abc import Callable, Mapping
from functools import singledispatch
from typing import TYPE_CHECKING, Any, Iterator

from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRel,
    GenericRelation,
)
from django.db import models
from django.db.models import Choices, JSONField
from django.utils.encoding import force_str
from django.utils.functional import Promise
from django.utils.translation import override as translation_override
from graphql.pyutils import register_description

from ._strconv import to_camel_case
from .base_types import (
    Binary,
    CustomDate,
    CustomDateTime,
    CustomTime,
    GenericForeignKeyInputType,
    GenericForeignKeyType,
)
from .fields import (
    ArrayField,
    DjangoListField,
    DjangoNestedListObjectField,
    HStoreField,
    RangeField,
)
from .utils import get_model_fields, get_related_model, is_required, to_const

# Allow Django's lazy ``gettext_lazy``/``verbose_name``/``help_text`` proxies to
# be used as GraphQL descriptions (graphql-core only accepts ``str`` otherwise).
# graphene-django did this on import; we now do it ourselves.
# See https://github.com/graphql-python/graphql-core-next/issues/58.
register_description(Promise)

if TYPE_CHECKING:
    from django.db.models import Field as DjangoField
    from django.db.models import Model

    from .registry import Registry


#: True when ``GDX_BACKEND=native`` is set in the process environment. Read ONCE
#: at import (the canonical pattern used by ``paginations/pagination.py``).
_NATIVE_BACKEND: bool = os.environ.get("GDX_BACKEND", "graphene") == "native"


class _GrapheneConstructs:
    """Lazy holder for the graphene descriptor classes the converter builds.

    S8e (graphene-removal): the converter no longer imports graphene at the
    MODULE top level — that ``from graphene import (...)`` blocked the graphene
    uninstall (S8i). The graphene constructs are STILL genuinely consumed,
    though:

    * ``Enum`` — ``convert_django_field_with_choices`` returns a graphene
      ``Enum`` instance and carries the choices->enum registry side-effect (the
      native-default converter test contract asserts ``isinstance(out, Enum)``).
    * ``Dynamic`` / ``Field`` / ``ID`` — the FK / O2O / M2M / reverse / GFK
      relation closures; the native output thunk consumes the ``Dynamic``
      descriptor, and the converter tests assert ``isinstance(out, Dynamic)``
      plus ``out.type.of_type.of_type is ID`` on native.
    * ``List`` / ``NonNull`` — the ArrayField / RangeField list wrappers and the
      Boolean-NonNull create branch.
    * ``String`` / ``Int`` / ``Float`` / ``Boolean`` / ``UUID`` / ``JSONString``
      — the SCALAR descriptors, DEAD on the native OUTPUT path (built only on
      the graphene path via ``_scalar_or_dead``), so their import is deferred to
      the moment the graphene scalar is actually built.

    So the constructs stay graphene; only the uninstall-blocking TOP-LEVEL
    import moves here, resolved LAZILY on first use and cached. Each construct is
    exposed as an attribute so call sites read ``_g().Enum`` / ``_g().Dynamic``
    etc., one-for-one with the old direct names.
    """

    __slots__ = (
        "ID",
        "UUID",
        "Boolean",
        "Dynamic",
        "Enum",
        "Field",
        "Float",
        "Int",
        "List",
        "NonNull",
        "String",
        "JSONString",
    )

    def __init__(self) -> None:
        """Import the graphene constructs once and pin them as attributes."""
        from graphene import (  # noqa: PLC0415
            ID,
            UUID,
            Boolean,
            Dynamic,
            Enum,
            Field,
            Float,
            Int,
            List,
            NonNull,
            String,
        )
        from graphene.types.json import JSONString  # noqa: PLC0415

        self.ID = ID
        self.UUID = UUID
        self.Boolean = Boolean
        self.Dynamic = Dynamic
        self.Enum = Enum
        self.Field = Field
        self.Float = Float
        self.Int = Int
        self.List = List
        self.NonNull = NonNull
        self.String = String
        self.JSONString = JSONString


#: Process-wide cache for the lazily imported graphene constructs.
_GRAPHENE_CONSTRUCTS: _GrapheneConstructs | None = None


def _g() -> _GrapheneConstructs:
    """Return the lazily imported, cached graphene constructs namespace.

    The first call imports graphene (still installed until S8i) and caches the
    construct classes; subsequent calls reuse the cache. This keeps every
    descriptor the converter builds byte-identical while removing the
    uninstall-blocking top-level ``import graphene``.
    """
    global _GRAPHENE_CONSTRUCTS
    if _GRAPHENE_CONSTRUCTS is None:
        _GRAPHENE_CONSTRUCTS = _GrapheneConstructs()
    return _GRAPHENE_CONSTRUCTS


class _DeadScalarSentinel:
    """Marker returned by SCALAR converters under ``GDX_BACKEND=native``.

    The native OUTPUT compiler (``native/output_compiler.compile_output_fields``)
    reads ``model._meta`` DIRECTLY and maps each Django scalar field to a native
    scalar (DateField->GdxDate, BinaryField->GraphQLString, CharField->
    GraphQLString, …). It NEVER reads the graphene scalar DESCRIPTORS that the
    converter builds into ``_meta.fields`` (``Binary(...)`` / ``CustomDate(...)`` /
    ``String(...)`` / …) — so those descriptors are DEAD on native (verified
    empirically: the entire converter ``_meta.fields`` output is unread on the
    native output path, see #1552 and S-ROOTS-d).

    To avoid BUILDING the dead graphene scalar descriptors on native (and so let
    the now-unused graphene scalar classes retire once graphene is uninstalled in
    S8), each SCALAR ``convert_django_field`` dispatcher returns this sentinel
    when ``_NATIVE_BACKEND`` is True. ``construct_fields`` then OMITS the field
    from the produced dict — a PER-FIELD-TYPE skip (#1552): GFK, the relation
    ``Dynamic`` descriptors, and the nested-list (``_nested_list_object_field``)
    descriptors are NOT scalars and so are KEPT, never returning this sentinel.

    The graphene path (``GDX_BACKEND`` unset) is UNCHANGED — the dispatchers build
    the real graphene scalar descriptors exactly as before.
    """

    __slots__ = ()


#: Singleton sentinel instance (identity-comparable in ``construct_fields``).
_DEAD_SCALAR = _DeadScalarSentinel()


def _scalar_or_dead(build: "Callable[[], Any]") -> Any:
    """Return the built graphene scalar descriptor, or the dead-scalar sentinel.

    On native the descriptor is dead (see ``_DeadScalarSentinel``) so we return
    the sentinel WITHOUT building (or even importing) the graphene scalar — the
    native output compiler derives the field from ``model._meta`` directly. On
    graphene we build the descriptor normally.

    Args:
        build: a zero-arg callable that builds the graphene scalar descriptor.

    Returns:
        The dead-scalar sentinel on native, otherwise the built descriptor.
    """
    if _NATIVE_BACKEND:
        return _DEAD_SCALAR
    return build()


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
    """Pick a readable GraphQL enum-member name for a ``(value, label)`` choice.

    Cascade (so numeric/opaque values don't surface as ``A_1``):

    1. the **value** if it is non-blank and yields a valid GraphQL name (e.g.
       ``"draft"`` -> ``DRAFT``);
    2. otherwise the **label**, resolved as its *source* string with translations
       deactivated -- so a lazy ``_("Male")`` becomes ``MALE`` deterministically,
       independent of the active locale;
    3. a **blank** value (empty or whitespace) with no usable label -> ``EMPTY``
       (the "no selection" choice);
    4. otherwise ``A_<value>`` as a last resort.

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


def get_choices(choices: Any) -> Iterator[tuple[str, Any, Any]]:
    """Extract choices from Django field choices recursively.

    Args:
        choices: Django field choices in any supported form (an iterable of
            pairs, a mapping, a callable, or an enumeration type), possibly
            nested for grouped choices.

    Yields:
        Tuples of (name, value, description) for each leaf choice.
    """
    choices = _normalize_choices(choices)
    converted_names = []
    for value, help_text in choices:
        if isinstance(help_text, (tuple, list)):
            yield from get_choices(help_text)
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
    choices = getattr(field, "choices", None)
    if choices:
        meta = field.model._meta

        # Key enums by (app_label, object_name, field_name) so two models that
        # share a class name across different Django apps — and carry the same
        # choices-field name — never collide in the registry.  This mirrors the
        # (model_class, for_input) keying used for object/input types.
        name = f"{meta.app_label}_{meta.object_name}_{field.name}_Enum"
        if input_flag:
            name = f"{name}_{input_flag}"
        name = to_camel_case(name)

        enum = registry.get_type_for_enum(name)
        if not enum:
            choices = list(get_choices(choices))
            named_choices = [(c[0], c[1]) for c in choices]
            named_choices_descriptions = {c[0]: c[2] for c in choices}

            class EnumWithDescriptionsType:
                @property
                def description(self) -> Any:
                    """Return the description for the current enum member."""
                    return named_choices_descriptions[self.name]

            enum = _g().Enum(
                name, list(named_choices), type=EnumWithDescriptionsType
            )
            registry.register_enum(name, enum)

        # Detect django-multiselectfield's MultiSelectField via isinstance when the
        # package is installed (covers subclasses); fall back to a name check only
        # when the import fails so the converter works without the optional dep.
        try:
            from multiselectfield import MultiSelectField as _MSField  # noqa: PLC0415

            _is_multiselect = isinstance(field, _MSField)  # pragma: no cover
        except ImportError:
            # multiselectfield not installed — fall back to a class-name check.
            _is_multiselect = type(field).__name__ == "MultiSelectField"

        if _is_multiselect:
            return DjangoListField(
                enum,
                description=field.help_text or field.verbose_name,
                required=is_required(field) and input_flag == "create",
            )
        return enum(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    return convert_django_field(field, registry, input_flag, nested_field)


def choices_enum_name(
    field: DjangoField, input_flag: str | None = None
) -> str:
    """Return the CANONICAL GraphQL enum name for a choices field.

    Keyed by ``(app_label, object_name, field_name)`` so two models that share a
    class name across different Django apps — and carry the same choices-field
    name — never collide in the registry (mirrors the ``(model_class,
    for_input)`` keying used for object/input types). When ``input_flag`` is set
    the name is suffixed so an input-only enum never clobbers the output slot.

    This is the SINGLE source of truth for the choices-enum name shared by the
    graphene converter, the native OUTPUT compiler and the native filter-input
    builder, so all three resolve the SAME registry slot for one ``(model,
    field)``.

    Args:
        field: the Django model field carrying choices.
        input_flag: input action key, or ``None`` for an output field.

    Returns:
        The canonical camelCase enum name.
    """
    meta = field.model._meta
    name = f"{meta.app_label}_{meta.object_name}_{field.name}_Enum"
    if input_flag:
        name = f"{name}_{input_flag}"
    return to_camel_case(name)


#: Prefix for the NATIVE choices-enum registry slot. The legacy graphene
#: converter (``convert_django_field_with_choices``) registers a graphene
#: ``Enum`` under the BARE canonical name; storing the native graphql-core
#: ``GraphQLEnumType`` under a distinct, native-namespaced key keeps the two
#: from poisoning each other while still giving the native OUTPUT and
#: FILTER-INPUT paths ONE shared slot to converge on (S-enum-1). The whole
#: graphene branch — and this dual-slot dance — disappears with the converter's
#: graphene enum in S-del-backend-11.
_NATIVE_ENUM_SLOT_PREFIX = "__native__"


def build_choices_enum_type(
    field: DjangoField,
    registry: Registry,
    input_flag: str | None = None,
) -> Any:
    """Build (or fetch the cached) graphql-core ``GraphQLEnumType`` for a choices field.

    GRAPHENE-FREE canonical builder. Reuses :func:`get_choices` (the 4-tier
    ``choice_enum_name`` cascade) for the value names + per-choice descriptions,
    and compiles via ``native.compiler.compile_enum`` so the native OUTPUT and
    FILTER-INPUT paths share ONE instance per ``(model, field)``:

    * ``GraphQLEnumValue.value`` carries the RAW python value, so resolution
      returns the stored value (mirrors graphene's ``EnumWithDescriptionsType``).
    * ``GraphQLEnumValue.description`` carries the per-choice label so the SDL
      keeps the descriptions graphene emits (oracle req #7).

    Sharing slot: the enum is memoized in the registry under a NATIVE-namespaced
    key (:data:`_NATIVE_ENUM_SLOT_PREFIX` + :func:`choices_enum_name`). The
    legacy graphene converter registers a graphene ``Enum`` under the BARE
    canonical name; the namespaced key keeps the graphql-core enum from being
    clobbered by — or returned in place of — that graphene object, while the
    OUTPUT and FILTER-INPUT paths both converge on this one native slot. The
    GraphQLEnumType STILL carries the bare canonical NAME for SDL parity; only
    the registry KEY is namespaced.

    Args:
        field: the Django model field carrying choices.
        registry: the registry whose enum slot is shared across native paths.
        input_flag: input action key, or ``None`` for an output field.

    Returns:
        A ``GraphQLEnumType`` for the field's choices, or ``None`` when the
        field has no usable choices.
    """
    from graphql import GraphQLEnumType  # noqa: PLC0415

    from .native.compiler import compile_enum  # noqa: PLC0415
    from .native.ir import EnumSpec  # noqa: PLC0415

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
                    field, (models.fields.related.ForeignObjectRel, GenericForeignKey)
                )
            ):
                continue

            converted = convert_django_field_with_choices(
                field, registry, input_flag, nested_field
            )
            # PER-FIELD-TYPE native skip (#1552 / S-ROOTS-d): a SCALAR converter
            # returns the dead-scalar sentinel under GDX_BACKEND=native because
            # the native output compiler derives the scalar from model._meta
            # directly and never reads this descriptor. OMIT it so the dead
            # graphene scalar descriptor is not even built. GFK / relation /
            # nested-list converters never return the sentinel, so they are KEPT.
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
    return _scalar_or_dead(
        lambda: _g().String(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    # INPUT (create / update): keep the graphene ``ID`` descriptor — the native
    # input compiler still consumes it. Retired in S-input-5.
    if input_flag:
        return _g().ID(
            description=field.help_text or "Django object unique identification field",
            required=input_flag == "update",
        )
    # OUTPUT (``input_flag is None``): the native output compiler renders the PK
    # as ``id: ID!`` directly from ``model._meta`` (AutoField -> GraphQLID +
    # ``GraphQLNonNull`` for the primary key, see
    # ``output_compiler._to_graphql_field``); this graphene ``ID`` descriptor is
    # DEAD and only pins graphene on the output path. Return the dead-scalar
    # sentinel under ``GDX_BACKEND=native`` so ``construct_fields`` omits it and
    # the graphene import never fires for the PK on output (S-rel-2). The
    # graphene path (``GDX_BACKEND`` unset) is UNCHANGED.
    return _scalar_or_dead(
        lambda: _g().ID(
            description=field.help_text
            or "Django object unique identification field",
            required=not field.null,
        )
    )


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
    return _scalar_or_dead(
        lambda: _g().UUID(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    return _scalar_or_dead(
        lambda: _g().Int(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    if _NATIVE_BACKEND:
        return _DEAD_SCALAR
    g = _g()
    required = is_required(field) and input_flag == "create"
    if required:
        return g.NonNull(g.Boolean, description=field.help_text or field.verbose_name)
    return g.Boolean(description=field.help_text)


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
    return _scalar_or_dead(
        lambda: _g().Boolean(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    return _scalar_or_dead(
        lambda: Binary(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    return _scalar_or_dead(
        lambda: _g().Float(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    return _scalar_or_dead(
        lambda: CustomDate(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    return _scalar_or_dead(
        lambda: CustomDateTime(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    return _scalar_or_dead(
        lambda: CustomTime(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
        A GraphQL Dynamic field that resolves lazily to the related type, or a
        graphene-free ``NativeRelationField`` marker on the native OUTPUT path.
    """
    model = field.related_model

    # Native OUTPUT path (``input_flag is None``): a reverse OneToOne is compiled
    # DIRECTLY from ``model._meta`` by ``types._compile_reverse_o2o_fields`` (it
    # walks ``OneToOneRel`` reverse relations and resolves via the per-type
    # registry) — this descriptor is NEVER read on output. Emit a graphene-free
    # ``NativeRelationField`` presence/ordering marker (never ``None`` — the
    # silent-drop trap) so the field stays in ``_meta.fields`` with the SAME
    # ``creation_counter`` for SDL field ORDER. INPUT stays graphene until
    # S-input-5. (S-rel-2.)
    if _NATIVE_BACKEND and input_flag is None:
        from .native.descriptors import NativeRelationField  # noqa: PLC0415

        return NativeRelationField(related_model=model)

    def dynamic_type() -> Any:
        """Resolve the related GraphQL type lazily."""
        if input_flag and not nested_field:
            return _g().ID()
        _type = registry.get_type_for_model(model, for_input=input_flag)
        if not _type:
            return
        return _g().Field(
            _type, required=is_required(field) and input_flag == "create"
        )

    return _g().Dynamic(dynamic_type)


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
        A GraphQL Dynamic field that resolves lazily to the related list, or a
        graphene-free ``NativeRelationField`` marker on the native OUTPUT path.
    """
    model = get_related_model(field)

    # Native OUTPUT path (``input_flag is None``): the forward-M2M to-MANY field
    # is compiled DIRECTLY from ``model._meta`` by
    # ``types._compile_relation_list_fields`` (which reuses the related node's
    # ``<Model>ListType`` results/totalCount CONTAINER via
    # ``_nested_list_object_field`` and emits the final field via
    # ``schema_compiler._build_list_object_field``) — it NEVER reads this
    # descriptor. The graphene ``Dynamic`` below is therefore dead and only pins
    # graphene; emit a graphene-free ``NativeRelationField`` presence/ordering
    # marker instead so the field stays in ``_meta.fields`` (the silent-drop
    # guard, never ``None`` / ``_DEAD_SCALAR``) with the SAME ``creation_counter``
    # for SDL field ORDER. The INPUT path keeps graphene until S-input-5. (S-rel-3.)
    if _NATIVE_BACKEND and input_flag is None:
        from .native.descriptors import NativeRelationField  # noqa: PLC0415

        return NativeRelationField(related_model=model)

    def dynamic_type() -> Any:
        """Resolve the related GraphQL list field lazily."""
        if input_flag and not nested_field:
            return DjangoListField(
                _g().ID,
                required=is_required(field) and input_flag == "create",
                description=field.help_text or field.verbose_name,
            )
        if input_flag and nested_field:
            _type = registry.get_type_for_model(model, for_input=input_flag)
            if not _type:
                return
            return DjangoListField(_type)
        # Output: uniform results/totalCount nested list (M2M accessor = field.name).
        return _nested_list_object_field(field, model, registry, accessor=field.name)

    return _g().Dynamic(dynamic_type)


@convert_django_field.register(GenericRel)
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
        A GraphQL Dynamic field that resolves lazily to the related list, or a
        graphene-free ``NativeRelationField`` marker on the native OUTPUT path
        (reverse FK / reverse M2M only — the reverse ``GenericRel`` arm stays on
        graphene until S-rel-4).
    """
    model = field.related_model

    # Native OUTPUT path (``input_flag is None``): a reverse-FK (``ManyToOneRel``)
    # / reverse-M2M (``ManyToManyRel``) to-MANY field is compiled DIRECTLY from
    # ``model._meta`` by ``types._compile_relation_list_fields`` (reusing the
    # related node's ``<Model>ListType`` results/totalCount CONTAINER) — it NEVER
    # reads this descriptor. The graphene ``Dynamic`` below is dead and only pins
    # graphene; emit a graphene-free ``NativeRelationField`` presence/ordering
    # marker instead (the silent-drop guard, never ``None`` / ``_DEAD_SCALAR``)
    # carrying the SAME ``creation_counter`` for SDL field ORDER. The INPUT path
    # keeps graphene until S-input-5.
    #
    # SCOPE GUARD: this converter ALSO handles the reverse ``GenericRel`` (the
    # reverse side of a ``GenericRelation``). The GenericRelation list retires in
    # S-rel-4, NOT here, so a ``GenericRel`` is EXCLUDED from the native-marker
    # branch and keeps emitting the graphene ``Dynamic``. (S-rel-3.)
    if _NATIVE_BACKEND and input_flag is None and not isinstance(field, GenericRel):
        from .native.descriptors import NativeRelationField  # noqa: PLC0415

        return NativeRelationField(related_model=model)

    def dynamic_type() -> Any:
        """Resolve the related GraphQL list field lazily."""
        if input_flag and not nested_field:
            return DjangoListField(_g().ID)
        if input_flag and nested_field:
            _type = registry.get_type_for_model(model, for_input=input_flag)
            if not _type:
                return
            return DjangoListField(_type)
        # Output: uniform results/totalCount nested list (reverse accessor).
        try:
            accessor = field.get_accessor_name()
        except Exception:  # noqa: BLE001 - fall back to the relation name
            accessor = field.name
        return _nested_list_object_field(field, model, registry, accessor=accessor)

    return _g().Dynamic(dynamic_type)


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
        A GraphQL Dynamic field that resolves lazily to the related type, or a
        graphene-free ``NativeRelationField`` marker on the native OUTPUT path.
    """
    model = get_related_model(field)

    # Native OUTPUT path (``input_flag is None``): the to-ONE FK / forward-O2O
    # field is compiled DIRECTLY from ``model._meta`` by
    # ``output_compiler._to_graphql_field`` (the to-ONE arm) — it NEVER reads
    # this descriptor. The graphene ``Dynamic`` below is therefore dead and only
    # pins graphene; emit a graphene-free ``NativeRelationField`` presence/
    # ordering marker instead so the field stays in ``_meta.fields`` (the
    # silent-drop guard, never ``None`` / ``_DEAD_SCALAR`` — cf. test_issue52
    # self-ref O2O) with the SAME ``creation_counter`` for SDL field ORDER. The
    # INPUT path keeps graphene until S-input-5. (S-rel-2.)
    if _NATIVE_BACKEND and input_flag is None:
        from .native.descriptors import NativeRelationField  # noqa: PLC0415

        return NativeRelationField(related_model=model)

    def dynamic_type() -> Any:
        """Resolve the related GraphQL type lazily."""
        # Skip the MTI auto-generated parent_link OneToOneField (Django sets
        # ``remote_field.parent_link = True`` on these).  The old issubclass()
        # guard also matched genuine self-referential O2O (spouse = O2O('self'))
        # because issubclass(X, X) is always True — silently dropping the field
        # from both output and input types.  Checking parent_link instead is
        # precise: it is True only for Django-generated MTI links.
        if getattr(getattr(field, "remote_field", None), "parent_link", False):
            return
        if input_flag and not nested_field:
            return _g().ID(
                description=field.help_text or field.verbose_name,
                required=is_required(field) and input_flag == "create",
            )

        _type = registry.get_type_for_model(model, for_input=input_flag)
        if not _type:
            return

        return _g().Field(
            _type,
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )

    return _g().Dynamic(dynamic_type)


@convert_django_field.register(GenericForeignKey)
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
        A GraphQL Dynamic field that resolves lazily to the generic type.
    """

    def dynamic_type() -> Any:
        """Resolve the generic foreign-key GraphQL type lazily."""
        key = f"{field.name}_{field.model.__name__.lower()}"
        if input_flag is not None:
            key = f"{key}_{input_flag}"

        key = to_camel_case(key)
        model = field.model
        ct_field = None
        fk_field = None
        required = False
        for f in get_model_fields(model):
            if f[0] == field.ct_field:
                ct_field = f[1]
            elif f[0] == field.fk_field:
                fk_field = f[1]
            if fk_field is not None and ct_field is not None:
                break

        if ct_field is not None and fk_field is not None:
            required = (is_required(ct_field) and is_required(fk_field)) or required

        if input_flag:
            return GenericForeignKeyInputType(
                description="Input Type for a GenericForeignKey field",
                required=required and input_flag == "create",
            )

        # Track 2: when the owning DjangoObjectType declares a companion union
        # for THIS GFK via ``Meta.gfk_unions``, emit a typed Union field instead
        # of the flat GenericForeignKeyType. Members come ONLY from the union's
        # explicit ``Meta.gfk_types`` -- the ContentType table is never queried.
        union_cls = registry.get_gfk_union(model, field.name)
        if union_cls is not None:
            return _g().Field(
                union_cls,
                description="Typed union for a GenericForeignKey field",
                required=required and input_flag == "create",
            )

        # The owner declared gfk_unions for this FK but the union is not
        # registered (mis-ordered declaration: the owner's Meta was evaluated
        # before the union was registered). Warn and fall back to the flat type
        # so a mis-ordered declaration is observable, not a silent regression.
        owner = registry.get_type_for_model(model)
        owner_gfk_unions = getattr(getattr(owner, "_meta", None), "gfk_unions", None)
        if owner_gfk_unions and field.name in owner_gfk_unions:
            warnings.warn(
                "{owner}: Meta.gfk_unions declares a union for GFK "
                "{fk!r} but that union is not registered; falling back to "
                "GenericForeignKeyType. Declare member ObjectTypes, then the "
                "DjangoUnionType, then the owning type's Meta.gfk_unions "
                "(in that order).".format(
                    owner=getattr(owner, "__name__", model.__name__),
                    fk=field.name,
                ),
                stacklevel=2,
            )

        _type = registry.get_type_for_enum(key)
        if not _type:
            _type = GenericForeignKeyType

        return _g().Field(
            _type,
            description="Type for a GenericForeignKey field",
            required=required and input_flag == "create",
        )

    return _g().Dynamic(dynamic_type)


@convert_django_field.register(GenericRelation)
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
        A GraphQL Dynamic field that resolves lazily to the related list.
    """
    model = field.related_model

    def dynamic_type() -> Any:
        """Resolve the related GraphQL list field lazily."""
        if input_flag:
            return
        # Output: uniform results/totalCount nested list (GenericRelation name).
        return _nested_list_object_field(field, model, registry, accessor=field.name)

    return _g().Dynamic(dynamic_type)


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
    g = _g()
    base_type = convert_django_field(field.base_field)
    if not isinstance(base_type, (g.List, g.NonNull)):
        base_type = type(base_type)
    return g.List(
        base_type,
        description=field.help_text or field.verbose_name,
        required=is_required(field) and input_flag == "create",
    )


@convert_django_field.register(HStoreField)
@convert_django_field.register(JSONField)
def convert_postgres_field_to_string(
    field: DjangoField,
    registry: Registry | None = None,
    input_flag: str | None = None,
    nested_field: bool = False,
) -> Any:
    """Convert PostgreSQL HStore and JSON fields to the GraphQL JSONString type.

    Args:
        field: the Django HStore or JSON field to convert.
        registry: the type registry used during conversion.
        input_flag: input action key, or None for an output field.
        nested_field: whether the field is being converted as nested.

    Returns:
        A GraphQL JSONString field for the Django field.
    """
    return _scalar_or_dead(
        lambda: _g().JSONString(
            description=field.help_text or field.verbose_name,
            required=is_required(field) and input_flag == "create",
        )
    )


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
    g = _g()
    inner_type = convert_django_field(field.base_field)
    if not isinstance(inner_type, (g.List, g.NonNull)):
        inner_type = type(inner_type)
    return g.List(
        inner_type,
        description=field.help_text or field.verbose_name,
        required=is_required(field) and input_flag == "create",
    )
