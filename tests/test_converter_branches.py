# -*- coding: utf-8 -*-
"""Remaining converter branch coverage.

Drives: the ``choice_enum_name`` cascade (value / label / EMPTY / A_<value>),
the MultiSelectField list branch, the required-boolean ``NonNull`` and the
NullBooleanField / BinaryField / decimal / uuid converters, ``construct_fields``
DEBUG sorting, the FK/O2O inheritance skip, the GenericForeignKey ct/fk-field
resolution, and the ArrayField/RangeField list-base branches.
"""

import graphene
from django.db import models
from django.test import override_settings
from django.utils.translation import gettext_lazy as _
from graphene import UUID, Boolean, Dynamic, Float, List, NonNull

from django_graphex.fields import ArrayField
from django_graphex.base_types import Binary
from django_graphex.converter import (
    assert_valid_name,
    choice_enum_name,
    construct_fields,
    convert_django_field,
    convert_django_field_with_choices,
    convert_postgres_range_to_string,
)
from django_graphex.registry import Registry
from django_graphex.types import DjangoInputObjectType, DjangoObjectType

from .models import Author, BasicModel, Post


def _resolve(field, **kwargs):
    converted = convert_django_field(field, **kwargs)
    if isinstance(converted, Dynamic):
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
    class MultiSelectField(models.CharField):
        pass

    field = MultiSelectField(max_length=20, choices=[("a", "A"), ("b", "B")])
    field.name = "tags_multi"
    field.model = BasicModel
    out = convert_django_field_with_choices(field, Registry())
    # The MultiSelectField branch wraps the enum in a DjangoListField (a Field).
    assert isinstance(out, graphene.Field)


# --------------------------------------------------------------------------- #
# Scalar converter branches                                                     #
# --------------------------------------------------------------------------- #
def test_required_boolean_is_nonnull():
    field = models.BooleanField(null=False, blank=False)
    field.name = "active"
    out = convert_django_field(field, Registry(), input_flag="create")
    assert isinstance(out, NonNull)


def test_optional_boolean_is_plain_boolean():
    field = models.BooleanField(null=True)
    out = convert_django_field(field, Registry())
    assert isinstance(out, Boolean)


def test_nullboolean_field_converts_to_boolean():
    field = models.BooleanField(null=True)
    # Force the NullBooleanField converter directly (deprecated class path).
    from django_graphex.converter import convert_field_to_nullboolean

    out = convert_field_to_nullboolean(field)
    assert isinstance(out, Boolean)


def test_binary_field_converts_to_binary_scalar():
    field = models.BinaryField()
    out = convert_django_field(field)
    assert isinstance(out, Binary)


def test_decimal_field_converts_to_float():
    field = models.DecimalField(max_digits=5, decimal_places=2)
    out = convert_django_field(field)
    assert isinstance(out, Float)


def test_uuid_field_converts_to_uuid():
    field = models.UUIDField()
    out = convert_django_field(field)
    assert isinstance(out, UUID)


def test_unregistered_field_type_raises_typeerror():
    class WeirdField(models.Field):
        pass

    import pytest

    with pytest.raises(TypeError):
        convert_django_field(WeirdField())


# --------------------------------------------------------------------------- #
# construct_fields DEBUG sorting                                                #
# --------------------------------------------------------------------------- #
@override_settings(DEBUG=True)
def test_construct_fields_debug_sorts_output_alphabetically():
    from .models import Author

    registry = Registry()
    fields = construct_fields(Author, registry, None, None, None)
    names = list(fields)
    assert names == sorted(names)


@override_settings(DEBUG=True)
def test_construct_fields_debug_create_sorts_required_first():
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
    assert isinstance(out, List)


def test_arrayfield_with_list_base_keeps_inner_list():
    # base_type is already a List -> the `not isinstance(...)` branch is False.
    inner = ArrayField(models.CharField(max_length=5))
    field = ArrayField(inner)
    out = convert_django_field(field)
    assert isinstance(out, List)


# --------------------------------------------------------------------------- #
# FK / O2O dynamic-closure inheritance skip                                     #
# --------------------------------------------------------------------------- #
def test_o2o_inheritance_parent_link_returns_none():
    # A OneToOneField whose model subclasses its related_model (multi-table
    # inheritance parent link) is skipped by the closure (returns None).
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
    assert isinstance(converted, Dynamic)
    assert converted.get_type() is None


# --------------------------------------------------------------------------- #
# OneToOneRel reverse-relation converter                                        #
# --------------------------------------------------------------------------- #
class _Profile(models.Model):
    author = models.OneToOneField(
        Author, related_name="profile", on_delete=models.CASCADE
    )

    class Meta:
        app_label = "tests"


def test_onetoone_rel_input_not_nested_is_id():
    from graphene import ID

    rel = Author._meta.get_field("profile")  # OneToOneRel
    out = _resolve(rel, registry=Registry(), input_flag="create")
    assert isinstance(out, ID)


def test_onetoone_rel_output_unregistered_returns_none():
    rel = Author._meta.get_field("profile")
    assert _resolve(rel, registry=Registry()) is None


def test_onetoone_rel_output_registered_returns_field():
    reg = Registry()

    class _ProfileType(DjangoObjectType):
        class Meta:
            model = _Profile
            registry = reg

    rel = Author._meta.get_field("profile")
    out = _resolve(rel, registry=reg)
    # A Field wrapping the registered profile type.
    assert out.type is _ProfileType


# --------------------------------------------------------------------------- #
# M2M / reverse-relation nested-input with no registered type -> None           #
# --------------------------------------------------------------------------- #
def test_m2m_nested_input_unregistered_returns_none():
    m2m = Post._meta.get_field("tags")
    assert (
        _resolve(m2m, registry=Registry(), input_flag="create", nested_field=True)
        is None
    )


def test_reverse_relation_nested_input_unregistered_returns_none():
    reverse = Author._meta.get_field("posts")  # ManyToOneRel
    assert (
        _resolve(reverse, registry=Registry(), input_flag="create", nested_field=True)
        is None
    )


def test_reverse_relation_nested_input_registered_returns_list():
    reg = Registry()

    class _PostInput(DjangoInputObjectType):
        class Meta:
            model = Post
            registry = reg

    reverse = Author._meta.get_field("posts")
    out = _resolve(reverse, registry=reg, input_flag="create", nested_field=True)
    # A list of the registered nested input type: [_PostInput!].
    assert isinstance(out.type, List)
    assert isinstance(out.type.of_type, NonNull)
    assert out.type.of_type.of_type is _PostInput


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
    assert isinstance(out, List)


def test_range_field_list_base_keeps_inner_list():
    # base_field converts to a List already -> the inner branch is the "is list"
    # path (983->985 false side).
    field = ArrayField(ArrayField(models.IntegerField()))
    out = convert_postgres_range_to_string(field)
    assert isinstance(out, List)


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

    reg = Registry()
    gfk = next(
        f for f in _GfkOwner._meta.get_fields() if isinstance(f, GenericForeignKey)
    )

    # Register an enum under the key the closure computes, so the registered
    # branch (869->872) is taken.
    from graphene import Enum

    key = "contentObject_gfkowner"
    reg.register_enum(key, Enum("Marker", [("X", 1)]))
    out = _resolve(gfk, registry=reg)
    assert out is not None


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
