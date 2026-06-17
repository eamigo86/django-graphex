# -*- coding: utf-8 -*-
"""Tests that the converter normalizes every Django ``choices`` declaration form.

On the CI floor (Django 4.x) ``field.choices`` is NOT pre-normalized, so these
exercise the converter's own normalization directly.
"""

import graphene
from django.db import models

from django_graphex.converter import (
    convert_django_field_with_choices,
    get_choices,
)
from django_graphex.registry import get_global_registry

from .models import BasicModel


class _Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "pub", "Published"


class _Priority(models.IntegerChoices):
    LOW = 1, "Low"
    HIGH = 2, "High"


def _callable_choices():
    return [("a", "A"), ("b", "B")]


_TUPLES = [("c", "C"), ("d", "D")]
_DICT = {"x": "X", "y": "Y"}
_GROUPED = [("Group", [("e", "E"), ("f", "F")])]


def _values(choices):
    return {value for _name, value, _desc in get_choices(choices)}


def test_get_choices_handles_textchoices():
    assert _values(_Status) == {"draft", "pub"}
    assert _values(_Status.choices) == {"draft", "pub"}  # already normalized form


def test_get_choices_handles_integerchoices():
    assert _values(_Priority) == {1, 2}


def test_get_choices_handles_mapping():
    assert _values(_DICT) == {"x", "y"}


def test_get_choices_handles_callable():
    assert _values(_callable_choices) == {"a", "b"}


def test_get_choices_handles_tuples_and_groups():
    assert _values(_TUPLES) == {"c", "d"}
    assert _values(_GROUPED) == {"e", "f"}  # grouped recursion still works


def test_convert_field_with_choices_builds_enum_for_each_form():
    forms = {
        "textchoices": (
            models.CharField(choices=_Status, max_length=10),
            {"DRAFT", "PUB"},
        ),
        "intchoices": (models.IntegerField(choices=_Priority), {"LOW", "HIGH"}),
        "mapping": (models.CharField(choices=_DICT, max_length=10), {"X", "Y"}),
        "callable": (
            models.CharField(choices=_callable_choices, max_length=10),
            {"A", "B"},
        ),
        "tuples": (models.CharField(choices=_TUPLES, max_length=10), {"C", "D"}),
    }
    registry = get_global_registry()
    for label, (field, expected_members) in forms.items():
        field.name = f"field_{label}"
        field.model = BasicModel  # the converter reads field.model._meta for the name
        # Each modern form converts without raising (it raised ValueError /
        # TypeError before the normalization fix) and yields an Enum field whose
        # members match the declared choices. S-enum-2 retired graphene on the
        # OUTPUT choices path (it returns the dead-scalar sentinel — the native
        # compiler renders the enum from ``model._meta``), so the enum-building is
        # exercised via the INPUT path (``input_flag="create"``), which is
        # unchanged until S-input-5.
        converted = convert_django_field_with_choices(
            field, registry, input_flag="create"
        )
        assert isinstance(converted, graphene.Enum), label
        assert set(converted._meta.enum.__members__) == expected_members, label


# --------------------------------------------------------------------------- #
# Enum-member NAMING (Option 1 cascade): value -> label (msgid) -> A_<value>   #
# --------------------------------------------------------------------------- #
def _names(choices):
    return [name for name, _value, _desc in get_choices(choices)]


def test_naming_uses_value_when_valid():
    # A value that is already a valid GraphQL name is used verbatim.
    assert _names((("draft", "Draft"), ("published", "Published"))) == [
        "DRAFT",
        "PUBLISHED",
    ]


def test_naming_falls_back_to_label_for_numeric_values():
    # The motivating case: ("1", "Male") must NOT become A_1.
    assert _names((("1", "Male"), ("2", "Female"))) == ["MALE", "FEMALE"]


def test_naming_resolves_lazy_label_to_source_msgid():
    from django.utils.translation import gettext_lazy as _
    from django.utils.translation import override

    # A lazy/translatable label resolves to its SOURCE string (msgid), so the
    # enum name is stable regardless of the active locale.
    with override("es"):
        assert _names((("1", _("Male")), ("2", _("Female")))) == ["MALE", "FEMALE"]


def test_naming_integerchoices_use_member_labels():
    # IntegerChoices values (1, 2) are invalid names -> fall back to labels.
    assert _names(_Priority) == ["LOW", "HIGH"]


def test_naming_last_resort_prefix_when_label_unusable():
    # Numeric value AND an empty/whitespace label -> A_<value> last resort.
    assert _names((("1", ""), ("2", "   "))) == ["A_1", "A_2"]


def test_naming_dedupes_colliding_names():
    names = _names((("1", "A B"), ("2", "A_B")))
    assert names[0] == "A_B"
    assert names[1] != names[0]  # de-duplicated with a suffix


def test_naming_blank_value_becomes_empty():
    # A blank "no selection" choice ("", " ") -> EMPTY, not A_.
    assert _names((("", " "), ("a", "A"))) == ["EMPTY", "A"]
    # Dashes-only label has no alphanumerics -> still EMPTY.
    assert _names(((" ", "---------"),)) == ["EMPTY"]


def test_naming_blank_value_prefers_useful_label():
    # A blank value with a meaningful label uses the label.
    assert _names((("", "Unknown"),)) == ["UNKNOWN"]
