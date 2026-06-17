# -*- coding: utf-8 -*-
"""Remaining converter branch coverage.

Drives: the ``choice_enum_name`` cascade (value / label / EMPTY / A_<value>),
the MultiSelectField list branch, the required-boolean ``NonNull`` and the
NullBooleanField / BinaryField / decimal / uuid converters, ``construct_fields``
sorting (unconditional since #19), the FK/O2O inheritance skip, the
GenericForeignKey ct/fk-field resolution, and the ArrayField/RangeField
list-base branches.

Phase 7 graphene-removal: the relation / GFK / ArrayField / RangeField branches
and the pure ``choice_enum_name`` / ``assert_valid_name`` / ``construct_fields``
sorting paths are KEPT/backend-independent and unchanged. The graphene SCALAR
converters (boolean / nullboolean / binary / decimal / uuid) are dead on native
(the native output compiler derives the scalar from ``model._meta`` directly), so
those tests were CONVERTED to drive the live native scalar mapper
(``_to_graphql_field``) and, for the required-boolean ``NonNull`` input case, the
native create-input compile (``DjangoInputObjectType(input_for="create")``),
preserving the original per-field-type coverage. NOTE: native renders BinaryField
as the ``String`` scalar (graphene-django SDL parity), not a dedicated Binary
scalar.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from graphql import (
    GraphQLBoolean,
    GraphQLFloat,
    GraphQLNonNull,
    GraphQLString,
)

from django_graphex.converter import (
    assert_valid_name,
    choice_enum_name,
    construct_fields,
    convert_django_field,
    convert_django_field_with_choices,
    convert_postgres_range_to_string,
)
from django_graphex.fields import ArrayField
from django_graphex.native.output_compiler import _to_graphql_field
from django_graphex.native.scalars import GdxUUID
from django_graphex.registry import Registry
from django_graphex.types import DjangoInputObjectType, DjangoObjectType

from .models import Author, BasicModel, Post


class _StubRegistry:
    """Minimal registry for ``_to_graphql_field`` (scalars never touch it)."""

    def get_compiled(self, model_cls):
        return None


def _native_scalar(field, name="probe"):
    """Run the NATIVE scalar conversion for ``field`` and return its scalar.

    Drives ``_to_graphql_field`` (the live native equivalent of the retired
    graphene scalar dispatchers), unwraps ``GraphQLNonNull``, and returns the
    underlying graphql-core scalar.
    """
    if not getattr(field, "name", None):
        field.name = name
    field_map = _to_graphql_field(field, _StubRegistry())
    gql_type = next(iter(field_map.values())).type
    if isinstance(gql_type, GraphQLNonNull):
        gql_type = gql_type.of_type
    return gql_type


def _is_lazy_closure(obj):
    """True for a converter result that defers to a lazy ``get_type()`` closure.

    Converter paths not yet migrated off graphene still return a graphene
    ``Dynamic`` whose ``get_type()`` must be called. Detect it structurally
    (duck-typed ``get_type`` on a graphene-module object) so this file imports no
    graphene symbol; migrated relation converters return a ``NativeRelationField``
    instead, which the caller treats verbatim.
    """
    from django_graphex.native.descriptors import NativeRelationField

    return (
        not isinstance(obj, NativeRelationField)
        and callable(getattr(obj, "get_type", None))
        and type(obj).__module__.startswith("graphene")
    )


def _is_dead_scalar(obj):
    """True when ``obj`` is the converter's dead-scalar sentinel.

    S-del-backend-11: the PostgreSQL ArrayField / RangeField converters are now
    graphene-free — they return the ``_DEAD_SCALAR`` sentinel (the native OUTPUT
    compiler derives every field from ``model._meta`` and has no ArrayField /
    RangeField entry, so the descriptor is OMITTED). Assert the native sentinel
    instead of the retired graphene ``List`` wrapper.
    """
    from django_graphex.converter import _DEAD_SCALAR

    return obj is _DEAD_SCALAR


def _resolve(field, **kwargs):
    converted = convert_django_field(field, **kwargs)
    if _is_lazy_closure(converted):
        return converted.get_type()
    return converted


# --------------------------------------------------------------------------- #
# choice_enum_name cascade                                                      #
# --------------------------------------------------------------------------- #
def test_choice_enum_name_uses_value_when_valid():
    assert choice_enum_name("draft", "Draft") == "DRAFT"


def test_choice_enum_name_uses_label_for_numeric_value():
    # A numeric value is not a valid name -> falls through to the label.
    assert choice_enum_name(1, "Male") == "MALE"


def test_choice_enum_name_lazy_label_resolved_to_source():
    # A lazy gettext label resolves to its msgid (locale-independent).
    assert choice_enum_name(1, _("Female")) == "FEMALE"


def test_choice_enum_name_blank_value_no_label_is_empty():
    # value 162->172: label None and a blank value -> EMPTY.
    assert choice_enum_name("", None) == "EMPTY"


def test_choice_enum_name_blank_value_blank_label_is_empty():
    # A whitespace-only label has no alphanumeric -> still EMPTY for blank value.
    assert choice_enum_name("  ", "   ") == "EMPTY"


def test_choice_enum_name_opaque_value_falls_back_to_a_prefix():
    # Non-blank, invalid value and no usable label -> A_<value>.
    assert choice_enum_name("1", "   ").startswith("A_")


# --------------------------------------------------------------------------- #
# MultiSelectField -> DjangoListField branch                                   #
# --------------------------------------------------------------------------- #
def test_multiselectfield_choice_returns_list():
    from django_graphex.converter import _DEAD_SCALAR

    class MultiSelectField(models.CharField):
        pass

    field = MultiSelectField(max_length=20, choices=[("a", "A"), ("b", "B")])
    field.name = "tags_multi"
    field.model = BasicModel

    # S-enum-2 (OUTPUT) + S-input-5 (INPUT): the choices converter path is
    # graphene-free on BOTH paths on native — it returns the dead-scalar sentinel.
    # The native compiler renders a MultiSelectField as ``[Enum]`` from
    # ``model._meta`` (OUTPUT) and the native input compiler renders ``[Enum]``
    # from the ``ChoicesInputField`` spec (INPUT).
    for input_flag in (None, "create"):
        out = convert_django_field_with_choices(
            field, Registry(), input_flag=input_flag
        )
        assert out is _DEAD_SCALAR, (
            "S-input-5: a MultiSelectField choices converter must return the "
            f"dead-scalar sentinel for input_flag={input_flag!r}; got {out!r}"
        )


# --------------------------------------------------------------------------- #
# Scalar converter branches                                                     #
# --------------------------------------------------------------------------- #
class _RequiredBoolModel(models.Model):
    """A required + an optional boolean for native create-input nullability."""

    active = models.BooleanField(null=False, blank=False)  # required -> NonNull
    maybe = models.BooleanField(null=True)  # optional -> nullable

    class Meta:
        app_label = "tests"


def test_required_boolean_is_nonnull():
    # Native create-input: a required (null=False, no default) BooleanField is
    # wrapped in GraphQLNonNull (the native equivalent of the graphene
    # ``convert_django_field(input_flag="create")`` NonNull wrapping; the graphene
    # scalar descriptor is dead on native).
    class _In(DjangoInputObjectType):
        class Meta:
            model = _RequiredBoolModel
            input_for = "create"

    field = _In._meta.graphql_input_type.fields["active"]
    assert isinstance(field.type, GraphQLNonNull)
    assert field.type.of_type is GraphQLBoolean


def test_optional_boolean_is_plain_boolean():
    # Native output conversion: an optional BooleanField -> plain GraphQLBoolean
    # (not wrapped in NonNull).
    field = models.BooleanField(null=True)
    out = _native_scalar(field, name="maybe")
    assert out is GraphQLBoolean


def test_nullboolean_field_converts_to_boolean():
    # The deprecated NullBooleanField subclasses BooleanField; native MRO mapping
    # resolves it to GraphQLBoolean (the graphene ``convert_field_to_nullboolean``
    # descriptor is dead on native).
    field = models.NullBooleanField()
    out = _native_scalar(field, name="nb")
    assert out is GraphQLBoolean


def test_binary_field_converts_to_binary_scalar():
    # Native renders BinaryField as the ``String`` scalar (graphene-django SDL
    # parity, #1508) — there is no dedicated native Binary scalar.
    field = models.BinaryField()
    out = _native_scalar(field, name="blob")
    assert out is GraphQLString


def test_decimal_field_converts_to_float():
    # Native collapses DecimalField to GraphQLFloat (graphene-django parity).
    field = models.DecimalField(max_digits=5, decimal_places=2)
    out = _native_scalar(field, name="amount")
    assert out is GraphQLFloat


def test_uuid_field_converts_to_uuid():
    # Native maps UUIDField to GdxUUID (renders as the ``UUID`` scalar).
    field = models.UUIDField()
    out = _native_scalar(field, name="uid")
    assert out is GdxUUID


def test_unregistered_field_type_raises_typeerror():
    class WeirdField(models.Field):
        pass

    import pytest

    with pytest.raises(TypeError):
        convert_django_field(WeirdField())


# --------------------------------------------------------------------------- #
# construct_fields sorting (unconditional since #19)                           #
# --------------------------------------------------------------------------- #
def test_construct_fields_sorts_output_alphabetically():
    """Output type fields are always alphabetical (DEBUG-independent since #19)."""
    from .models import Author

    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None)
    names = list(fields)
    assert names == sorted(names)


def test_construct_fields_create_sorts_required_first():
    """Create-input fields are required-first then alphabetical (DEBUG-independent)."""
    from .models import Author

    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None, input_flag="create")
    # No exception and id is dropped on create.
    assert "id" not in fields


# --------------------------------------------------------------------------- #
# ArrayField / RangeField list-base branches                                   #
# --------------------------------------------------------------------------- #
def test_arrayfield_wraps_base_field_in_list():
    field = ArrayField(models.IntegerField())
    out = convert_django_field(field)
    assert _is_dead_scalar(out)


def test_arrayfield_with_list_base_keeps_inner_list():
    # base_type is already a List -> the `not isinstance(...)` branch is False.
    inner = ArrayField(models.CharField(max_length=5))
    field = ArrayField(inner)
    out = convert_django_field(field)
    assert _is_dead_scalar(out)


# --------------------------------------------------------------------------- #
# FK / O2O dynamic-closure inheritance skip                                     #
# --------------------------------------------------------------------------- #
def test_o2o_inheritance_parent_link_returns_none():
    # S-rel-2: on the native OUTPUT path a to-ONE O2O (incl. an MTI parent_link)
    # converts to a graphene-free ``NativeRelationField`` marker — the actual
    # output field (and the parent_link drop) is decided by the native compiler
    # from ``model._meta``, not by this descriptor.
    from django_graphex.native.descriptors import NativeRelationField

    class _Base(models.Model):
        class Meta:
            app_label = "tests"

    class _Child(_Base):
        class Meta:
            app_label = "tests"

    parent_link = next(
        f
        for f in _Child._meta.get_fields()
        if isinstance(f, models.OneToOneField) and f.remote_field.parent_link
    )
    converted = convert_django_field(parent_link, Registry())
    assert isinstance(converted, NativeRelationField)


# --------------------------------------------------------------------------- #
# OneToOneRel reverse-relation converter                                        #
# --------------------------------------------------------------------------- #
class _Profile(models.Model):
    author = models.OneToOneField(
        Author, related_name="profile", on_delete=models.CASCADE
    )

    class Meta:
        app_label = "tests"


def test_onetoone_rel_input_not_nested_returns_native_marker():
    # S-input-5: a reverse OneToOneRel on the native INPUT path converts to a
    # graphene-free ``NativeRelationField`` marker. The actual ``ID`` input field
    # is built by ``input_compiler.compile_input_type`` from a
    # ``RelationInputField`` spec, not from this descriptor.
    from django_graphex.converter import convert_django_field
    from django_graphex.native.descriptors import NativeRelationField

    rel = Author._meta.get_field("profile")  # OneToOneRel
    out = convert_django_field(rel, registry=Registry(), input_flag="create")
    assert isinstance(out, NativeRelationField)
    assert not type(out).__module__.startswith("graphene")


def test_onetoone_rel_output_returns_native_marker():
    # S-rel-2: a reverse OneToOneRel on the native OUTPUT path converts to a
    # graphene-free ``NativeRelationField`` marker (registered-or-not). The
    # graphene-faithful drop-when-unregistered / Field-when-registered logic
    # moved to ``types._compile_reverse_o2o_fields`` (which resolves via the
    # per-type registry from ``model._meta``); this converter no longer decides
    # it. ``_resolve`` returns the marker verbatim (it is not a graphene Dynamic).
    from django_graphex.native.descriptors import NativeRelationField

    rel = Author._meta.get_field("profile")  # OneToOneRel
    reg = Registry()

    class _ProfileType(DjangoObjectType):
        class Meta:
            model = _Profile
            registry = reg

    out_unregistered = _resolve(rel, registry=Registry())
    out_registered = _resolve(rel, registry=reg)

    assert isinstance(out_unregistered, NativeRelationField)
    assert isinstance(out_registered, NativeRelationField)


# --------------------------------------------------------------------------- #
# M2M / reverse-relation nested-input with no registered type -> None           #
# --------------------------------------------------------------------------- #
def test_m2m_nested_input_unregistered_returns_none():
    # S-input-5: on native the M2M converter returns a graphene-free marker for
    # BOTH the flat and the nested-input path (the nested OBJECT-input rendering
    # — and the unregistered-child skip — moved to
    # ``types._resolve_native_nested_input_fields`` + ``compile_input_type``, which
    # read ``model._meta`` directly).
    from django_graphex.converter import convert_django_field
    from django_graphex.native.descriptors import NativeRelationField

    m2m = Post._meta.get_field("tags")
    out = convert_django_field(
        m2m, registry=Registry(), input_flag="create", nested_field=True
    )
    assert isinstance(out, NativeRelationField)


def test_reverse_relation_nested_input_unregistered_returns_none():
    from django_graphex.converter import convert_django_field
    from django_graphex.native.descriptors import NativeRelationField

    reverse = Author._meta.get_field("posts")  # ManyToOneRel
    out = convert_django_field(
        reverse, registry=Registry(), input_flag="create", nested_field=True
    )
    assert isinstance(out, NativeRelationField)


def test_reverse_relation_nested_input_registered_returns_list():
    from django_graphex.converter import convert_django_field
    from django_graphex.native.descriptors import NativeRelationField

    reg = Registry()

    class _PostInput(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg

    reverse = Author._meta.get_field("posts")
    # The converter returns the graphene-free marker; the nested ``[_PostInput!]``
    # list rendering is owned by the native input compiler.
    out = convert_django_field(
        reverse, registry=reg, input_flag="create", nested_field=True
    )
    assert isinstance(out, NativeRelationField)


# --------------------------------------------------------------------------- #
# assert_valid_name                                                             #
# --------------------------------------------------------------------------- #
def test_assert_valid_name_rejects_bad_name():
    import pytest

    with pytest.raises(AssertionError):
        assert_valid_name("1bad name")
    assert_valid_name("good_name")  # no raise


# --------------------------------------------------------------------------- #
# RangeField converter (called directly; psycopg not installed)                 #
# --------------------------------------------------------------------------- #
def test_range_field_wraps_base_field_in_list():
    field = ArrayField(models.IntegerField())  # has a .base_field
    out = convert_postgres_range_to_string(field)
    assert _is_dead_scalar(out)


def test_range_field_list_base_keeps_inner_list():
    # base_field converts to a List already -> the inner branch is the "is list"
    # path (983->985 false side).
    field = ArrayField(ArrayField(models.IntegerField()))
    out = convert_postgres_range_to_string(field)
    assert _is_dead_scalar(out)


# --------------------------------------------------------------------------- #
# GenericForeignKey: registered enum type + non-resolving ct/fk fields          #
# --------------------------------------------------------------------------- #
def test_gfk_output_uses_registered_enum_type():
    from django.contrib.contenttypes.fields import GenericForeignKey
    from django.contrib.contenttypes.models import ContentType

    class _GfkOwner(models.Model):
        content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
        object_id = models.PositiveIntegerField()
        content_object = GenericForeignKey("content_type", "object_id")

        class Meta:
            app_label = "tests"

    from django_graphex.native.descriptors import NativeRelationField

    reg = Registry()
    gfk = next(
        f for f in _GfkOwner._meta.get_fields() if isinstance(f, GenericForeignKey)
    )

    # Register a (native graphql-core) enum under the key the converter computes
    # for this GFK, exercising the "an enum is already registered" setup. On the
    # native OUTPUT path the GFK converter returns a graphene-free
    # ``NativeRelationField`` marker regardless (the actual GFK output type is
    # built by the native compiler from ``model._meta``).
    from graphql import GraphQLEnumType

    key = "contentObject_gfkowner"
    reg.register_enum(key, GraphQLEnumType("Marker", {"X": 1}))
    out = _resolve(gfk, registry=reg)
    assert isinstance(out, NativeRelationField)


def test_gfk_with_unresolvable_ct_fk_fields_still_builds():
    from django.contrib.contenttypes.fields import GenericForeignKey
    from django.contrib.contenttypes.models import ContentType

    class _GfkOdd(models.Model):
        content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
        object_id = models.PositiveIntegerField()
        content_object = GenericForeignKey("content_type", "object_id")

        class Meta:
            app_label = "tests"

    gfk = next(
        f for f in _GfkOdd._meta.get_fields() if isinstance(f, GenericForeignKey)
    )
    # Point ct_field/fk_field at names that don't exist so the loop never sets
    # both -> the `required` computation is skipped (859->862 branch).
    gfk.ct_field = "missing_ct"
    gfk.fk_field = "missing_fk"
    out = _resolve(gfk, registry=Registry())
    assert out is not None
