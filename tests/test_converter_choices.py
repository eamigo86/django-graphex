# -*- coding: utf-8 -*-
"""Tests that the converter normalizes every Django "choices" declaration form.

On the CI floor (Django 4.x) "field.choices" is NOT pre-normalized, so these
exercise the converter's own normalization directly.
"""

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from django_graphex.converter import (
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


def _callable_choices() -> list[tuple[str, str]]:
    """Return a static choices list, used to test the callable-choices form.

    Returns:
        pairs: Two (value, label) pairs mimicking a Django callable
            "choices" argument.
    """
    return [("a", "A"), ("b", "B")]


_TUPLES = [("c", "C"), ("d", "D")]
_DICT = {"x": "X", "y": "Y"}
_GROUPED = [("Group", [("e", "E"), ("f", "F")])]


def _values(choices: Any) -> set[Any]:
    """Extract the set of choice values from any supported choices form.

    Args:
        choices: Django field choices in any supported form (see
            "get_choices").

    Returns:
        values: The distinct leaf choice values, discarding names/descriptions.
    """
    return {value for _name, value, _desc in get_choices(choices)}


def test_get_choices_handles_textchoices() -> None:
    """get_choices must extract values from a TextChoices class and its .choices form.

    Ships broken if either the enumeration class itself or its
    pre-normalized ".choices" tuple form stops yielding matching values.
    """
    assert _values(_Status) == {"draft", "pub"}
    assert _values(_Status.choices) == {"draft", "pub"}  # already normalized form


def test_get_choices_handles_integerchoices() -> None:
    """get_choices must extract integer values from an IntegerChoices class.

    Ships broken if integer-valued enumerations stop normalizing correctly.
    """
    assert _values(_Priority) == {1, 2}


def test_get_choices_handles_mapping() -> None:
    """get_choices must extract values from a plain dict choices form.

    Ships broken if dict-based "choices" declarations stop normalizing.
    """
    assert _values(_DICT) == {"x", "y"}


def test_get_choices_handles_callable() -> None:
    """get_choices must extract values from a callable choices form.

    Ships broken if a callable "choices" argument stops being invoked and
    normalized correctly.
    """
    assert _values(_callable_choices) == {"a", "b"}


def test_get_choices_handles_tuples_and_groups() -> None:
    """get_choices must extract values from flat tuples and grouped choices.

    Ships broken if grouped choices (nested category -> sub-choices) stop
    recursing correctly.
    """
    assert _values(_TUPLES) == {"c", "d"}
    assert _values(_GROUPED) == {"e", "f"}  # grouped recursion still works


def test_convert_field_with_choices_builds_enum_for_each_form() -> None:
    """Every modern Django choices form must build a valid GraphQL enum.

    Ships broken if any choices declaration form (TextChoices, IntegerChoices,
    mapping, callable, tuples) raises during enum construction or produces an
    enum whose members do not match the declared choices.
    """
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
    from graphql import GraphQLEnumType

    from django_graphex.converter import build_choices_enum_type

    registry = get_global_registry()
    for label, (field, expected_members) in forms.items():
        field.name = f"field_{label}"
        field.model = BasicModel  # the converter reads field.model._meta for the name
        # Each modern form converts without raising (it raised ValueError /
        # TypeError before the normalization fix) and yields an enum whose members
        # match the declared choices. S-enum-2 (OUTPUT) + S-input-5 (INPUT) retired
        # graphene on the choices converter path — on native it returns the
        # dead-scalar sentinel for both paths and the enum is built by the native
        # canonical builder ``build_choices_enum_type`` (a graphql-core
        # ``GraphQLEnumType``).
        enum = build_choices_enum_type(field, registry)
        assert isinstance(enum, GraphQLEnumType), label
        assert set(enum.values.keys()) == expected_members, label


# --------------------------------------------------------------------------- #
# Enum-member NAMING (Option 1 cascade): value -> label (msgid) -> A_<value>   #
# --------------------------------------------------------------------------- #
def _names(choices: Any) -> list[str]:
    """Extract the ordered list of generated enum-member names for choices.

    Args:
        choices: Django field choices in any supported form (see
            "get_choices").

    Returns:
        names: The generated GraphQL enum member name for each leaf choice,
            in declaration order.
    """
    return [name for name, _value, _desc in get_choices(choices)]


def test_naming_uses_value_when_valid() -> None:
    """A value that is already a valid GraphQL name must be used verbatim.

    Ships broken if simple alphabetic values stop being uppercased directly
    instead of going through the label/prefix fallback cascade.
    """
    assert _names((("draft", "Draft"), ("published", "Published"))) == [
        "DRAFT",
        "PUBLISHED",
    ]


def test_naming_falls_back_to_label_for_numeric_values() -> None:
    """A numeric-looking value must fall back to its label instead of a bare digit name.

    Ships broken if the motivating case ("1", "Male") starts producing an
    invalid GraphQL enum name like "A_1" instead of "MALE".
    """
    assert _names((("1", "Male"), ("2", "Female"))) == ["MALE", "FEMALE"]


def test_naming_resolves_lazy_label_to_source_msgid() -> None:
    """A lazy/translatable label must resolve to its source string (msgid).

    Ships broken if the generated enum name changes depending on the active
    locale instead of staying pinned to the untranslated msgid.
    """
    from django.utils.translation import gettext_lazy as _
    from django.utils.translation import override

    # A lazy/translatable label resolves to its SOURCE string (msgid), so the
    # enum name is stable regardless of the active locale.
    with override("es"):
        assert _names((("1", _("Male")), ("2", _("Female")))) == ["MALE", "FEMALE"]


def test_naming_integerchoices_use_member_labels() -> None:
    """IntegerChoices values must fall back to their member labels for naming.

    Ships broken if integer values (1, 2), which are invalid GraphQL names,
    stop falling back to their declared labels ("LOW", "HIGH").
    """
    assert _names(_Priority) == ["LOW", "HIGH"]


def test_naming_last_resort_prefix_when_label_unusable() -> None:
    """A numeric value with an unusable label must fall back to an A_-prefixed name.

    Ships broken if a numeric value paired with an empty or whitespace-only
    label stops producing the "A_<value>" last-resort name.
    """
    assert _names((("1", ""), ("2", "   "))) == ["A_1", "A_2"]


def test_naming_rejects_colliding_names() -> None:
    """Two choices generating one member name must fail before enum creation.

    Raises:
        ImproperlyConfigured: Both labels normalize to the same member name.
    """
    with pytest.raises(ImproperlyConfigured, match="A_B"):
        _names((("1", "A B"), ("2", "A_B")))


def test_naming_blank_value_becomes_empty() -> None:
    """A blank "no selection" choice must name to EMPTY, not an A_-prefixed name.

    Ships broken if a blank value, or a label with no alphanumeric
    characters, stops resolving to the "EMPTY" sentinel name.
    """
    assert _names((("", " "), ("a", "A"))) == ["EMPTY", "A"]
    # Dashes-only label has no alphanumerics -> still EMPTY.
    assert _names(((" ", "---------"),)) == ["EMPTY"]


def test_naming_blank_value_prefers_useful_label() -> None:
    """A blank value with a meaningful label must name after the label.

    Ships broken if a blank value stops preferring a usable label over the
    "EMPTY" sentinel when one is available.
    """
    assert _names((("", "Unknown"),)) == ["UNKNOWN"]


# --------------------------------------------------------------------------- #
# Cross-GROUP name collisions (repeated labels such as "Other" / "Unknown")    #
# --------------------------------------------------------------------------- #
#: Two option groups repeating the label "Other" for two distinct stored values.
_GROUPED_COLLIDING = [("Sports", [(1, "Other")]), ("Arts", [(2, "Other")])]


def _enum_for(choices: Any, field_name: str) -> Any:
    """Build the native choices enum for a throwaway field carrying choices.

    Args:
        choices: Django field choices in any supported form.
        field_name: The field name, which keys the canonical enum name.

    Returns:
        enum: The "GraphQLEnumType" built for those choices.
    """
    from django_graphex.converter import build_choices_enum_type
    from django_graphex.registry import Registry

    field = models.IntegerField(choices=choices)
    field.name = field_name
    field.model = BasicModel  # the converter reads field.model._meta for the name
    return build_choices_enum_type(field, Registry())


def test_naming_rejects_colliding_names_across_groups() -> None:
    """Repeated labels in separate option groups must be rejected.

    Raises:
        ImproperlyConfigured: Both groups generate the same member name.
    """
    with pytest.raises(ImproperlyConfigured, match="OTHER"):
        _names(_GROUPED_COLLIDING)


def test_grouped_colliding_labels_reject_enum_creation() -> None:
    """A grouped member collision must fail before any value can be published.

    Raises:
        ImproperlyConfigured: Both groups generate the same member name.
    """
    with pytest.raises(ImproperlyConfigured, match="OTHER"):
        _enum_for(_GROUPED_COLLIDING, "grouped_colliding")


def test_grouped_unique_labels_keep_every_value_in_the_enum() -> None:
    """Unambiguous grouped members still round-trip every stored value.

    The collision rule does not reject a grouped declaration merely because
    its groups contain numeric raw values.
    """
    enum = _enum_for(
        [("Sports", [(1, "Other Sports")]), ("Arts", [(2, "Other Arts")])],
        "grouped_unique",
    )
    for stored in (1, 2):
        name = enum.serialize(stored)
        assert enum.parse_value(name) == stored


def test_grouped_non_colliding_enum_sdl_is_unchanged() -> None:
    """Grouped choices without a collision must keep their plain, unsuffixed SDL.

    Ships broken if the cross-group de-duplication starts suffixing (or
    re-naming) members that never collided, silently rewriting published SDL.
    """
    from graphql import print_type

    enum = _enum_for(
        [("Group A", [(1, "Low")]), ("Group B", [(2, "High")])],
        "grouped_plain",
    )

    assert print_type(enum) == (
        "enum testsBasicmodelGroupedPlainEnum {\n"
        '  """Low"""\n'
        "  LOW\n"
        "\n"
        '  """High"""\n'
        "  HIGH\n"
        "}"
    )


def test_double_underscore_choice_value_never_generates_reserved_member() -> None:
    """A value starting with "__" falls through the cascade to a valid name.

    Scenario: a reserved-looking choice value.
    """
    from django_graphex.converter import choice_enum_name

    assert choice_enum_name("__x", "Hidden") == "HIDDEN"
    assert not choice_enum_name("__x", "__x").startswith("__")
