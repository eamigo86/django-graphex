"""Ambiguous generated choice members must fail before schema publication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test.utils import isolate_apps

from django_graphex.converter import build_choices_enum_type, get_choices
from django_graphex.core import ObjectType, field
from django_graphex.filtering.native_schema import _choices_enum
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoInputObjectType, DjangoObjectType


def _callable_ambiguous_choices() -> list[tuple[int, str]]:
    """Return an ambiguous modern callable choices declaration.

    Returns:
        Two choices that generate the same member name.
    """
    return [(1, "Alpha"), (2, "Alpha")]


@pytest.mark.parametrize(
    ("choices", "member"),
    [
        ([(1, "Alpha"), (2, "Alpha")], "ALPHA"),
        ([(2, "Alpha"), (1, "Alpha")], "ALPHA"),
        ([("Sports", [(1, "Other")]), ("Arts", [(2, "Other")])], "OTHER"),
        ({1: "Alpha", 2: "Alpha"}, "ALPHA"),
        (_callable_ambiguous_choices, "ALPHA"),
        ([("draft-one", "First"), ("draft one", "Second")], "DRAFT_ONE"),
    ],
)
def test_ambiguous_members_reject_all_supported_choices_forms(
    choices: Any | Callable[[], Any], member: str
) -> None:
    """Reject collisions from order, groups, mappings, callables and values.

    Args:
        choices: A supported declaration with ambiguous generated members.
        member: The colliding generated member name.

    Raises:
        ImproperlyConfigured: The declaration produces duplicate member names.
    """
    with pytest.raises(ImproperlyConfigured, match=member):
        list(get_choices(choices))


@isolate_apps()
def test_ambiguous_members_reject_public_schema_without_cache_pollution() -> None:
    """Refuse a public schema, then allow a corrected field in its registry.

    Raises:
        ImproperlyConfigured: The initial public output has ambiguous members.
    """

    class Item(models.Model):
        status = models.IntegerField(choices=[(1, "Alpha"), (2, "Alpha")])

        class Meta:
            app_label = "member_collision"

    type_registry = Registry()

    class ItemType(DjangoObjectType):
        class Meta:
            model = Item
            registry = type_registry

    class Query(ObjectType):
        item = field(ItemType, resolver=lambda *_: Item(status=1))

    with pytest.raises(ImproperlyConfigured, match="ALPHA"):
        DjangoGraphQLSchema(query=Query)

    status = Item._meta.get_field("status")
    status.choices = [(1, "Alpha"), (2, "Beta")]
    corrected = build_choices_enum_type(status, type_registry)
    assert corrected is not None
    assert list(corrected.values) == ["ALPHA", "BETA"]
    assert corrected.parse_value("ALPHA") == 1
    assert corrected.serialize(2) == "BETA"


@isolate_apps()
def test_ambiguous_members_reject_generated_input_and_filter() -> None:
    """Reject duplicate members before generated input or filter publication.

    Raises:
        ImproperlyConfigured: The generated enum would have duplicate members.
    """

    class Item(models.Model):
        status = models.IntegerField(choices=[(1, "Alpha"), (2, "Alpha")])

        class Meta:
            app_label = "member_input_collision"

    type_registry = Registry()

    with pytest.raises(ImproperlyConfigured, match="ALPHA"):

        class ItemInput(DjangoInputObjectType):
            class Meta:
                model = Item
                registry = type_registry
                input_for = "create"

    status = Item._meta.get_field("status")
    with pytest.raises(ImproperlyConfigured, match="ALPHA"):
        _choices_enum(status, type_registry)
    assert (
        type_registry.get_type_for_enum("__native__memberInputCollisionItemStatusEnum")
        is None
    )
