# -*- coding: utf-8 -*-
"""Tests for issue #18 — write-path consistency (non-breaking subset).

Covers:
(a) delete() uses _meta.pk.attname so custom-PK models return the right id.
(b) _unwrap_enums uses isinstance(value, enum.Enum) — no substring match.
(c) perform_mutate behavioural pin (DjangoModelMutation returns in-memory obj).
"""

from __future__ import annotations

import enum
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import TestCase

from django_graphex.mutation import DjangoModelMutation
from django_graphex.nested import NestedFieldsMixin
from django_graphex.types import DjangoModelType

from .models import CustomPKProduct

# ---------------------------------------------------------------------------
# Helper: minimal GraphQL resolve info stub
# ---------------------------------------------------------------------------


def _info() -> SimpleNamespace:
    """Build a minimal GraphQL resolve-info stub for mutation calls.

    Returns:
        info: A namespace exposing "context.META" and "context.FILES" as
            empty dicts, enough for the mutation code paths under test.
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


# ---------------------------------------------------------------------------
# Mutations for the tests
# ---------------------------------------------------------------------------


class CustomPKProductMutation(DjangoModelMutation):
    """Mutation for a model whose PK is "slug" (not "id").

    Exercises the delete()-pk fix against a non-default primary key field.
    """

    class Meta:
        """Wires the mutation to "CustomPKProduct".

        Looks the target instance up by "slug" instead of the default "id".
        """

        model = CustomPKProduct
        lookup_field = "slug"


class CustomPKProductType(DjangoModelType):
    """DjangoModelType for a model whose PK is "slug" (not "id").

    Exercises the delete()-pk fix against a non-default primary key field.
    """

    class Meta:
        """Wires the type to the "CustomPKProduct" model.

        Registered with the default registry (no explicit "registry" set).
        """

        model = CustomPKProduct


# ---------------------------------------------------------------------------
# (a) delete() pk fix — custom PK model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class CustomPKDeleteTest(TestCase):
    """delete() must restore the correct pk attribute on the deleted object.

    Covers both "DjangoModelMutation.delete" and "DjangoModelType.delete" for
    a model whose primary key is a non-default field ("slug").
    """

    def test_delete_returns_correct_pk_for_custom_pk_model(self) -> None:
        """Ship-broken contract: after delete, the returned object must carry
        the original pk value under the real PK attname ("slug"), not under
        "id".
        """
        CustomPKProduct.objects.create(slug="widget-42", title="Widget 42")

        result = CustomPKProductMutation.delete(None, _info(), **{"id": "widget-42"})

        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        returned_obj = getattr(result, result._meta.output_field_name)
        # The real PK attribute is ``slug``; it must hold the original pk value.
        self.assertEqual(returned_obj.slug, "widget-42")
        # id must NOT be set to the pk string on the custom-pk model
        # (the default auto-id is absent; Django leaves it as None after delete).

    def test_delete_not_found_returns_errors(self) -> None:
        """Ship-broken contract: deleting a missing object must return
        errors on the result, not raise an exception.
        """
        result = CustomPKProductMutation.delete(
            None, _info(), **{"id": "does-not-exist"}
        )
        self.assertFalse(result.ok)
        self.assertTrue(result.errors)

    def test_types_delete_returns_correct_pk_for_custom_pk_model(self) -> None:
        """Ship-broken contract: "DjangoModelType.delete" must also restore
        the pk value under the real PK attname ("slug"), matching the
        mutation-side behavior.
        """
        CustomPKProduct.objects.create(slug="gadget-99", title="Gadget 99")

        result = CustomPKProductType.delete(None, _info(), **{"id": "gadget-99"})

        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        returned_obj = getattr(result, result._meta.output_field_name)
        self.assertEqual(returned_obj.slug, "gadget-99")


# ---------------------------------------------------------------------------
# (b) _unwrap_enums — isinstance instead of substring match
# ---------------------------------------------------------------------------


class UnwrapEnumsTest(TestCase):
    """ "_unwrap_enums" must use isinstance(value, enum.Enum), not a substring match.

    Covers real enum members (both the historical graphene-style enum shape
    and plain Python enums), a look-alike class that must NOT be unwrapped,
    and ordinary non-enum values passing through unchanged.
    """

    def _unwrap(self, item: dict[str, Any]) -> dict[str, Any]:
        """Run "NestedFieldsMixin._unwrap_enums" over a copy of the given mapping.

        Args:
            item: The mapping whose enum-valued entries should be unwrapped.

        Returns:
            unwrapped: A new mapping with enum members replaced by their
                raw "value", and other entries left untouched.
        """
        return NestedFieldsMixin._unwrap_enums(dict(item))

    def test_string_valued_enum_member_is_unwrapped(self) -> None:
        """Ship-broken contract: a string-valued enum.Enum member must be
        unwrapped to its raw value.

        Historically this exercised a graphene.Enum.from_enum(...) member;
        that construction simply returns the underlying enum.Enum (its
        members ARE plain enum.Enum instances with the original .value), so
        the native equivalent is a string-valued enum.Enum declared directly.
        The behavioral contract is unchanged: _unwrap_enums keys off
        isinstance(value, enum.Enum) and must yield the raw "active" value.
        """
        Status = enum.Enum("Status", {"ACTIVE": "active", "INACTIVE": "inactive"})

        item = {"status": Status.ACTIVE}
        result = self._unwrap(item)
        # The value should be unwrapped to the raw value
        self.assertEqual(result["status"], "active")

    def test_plain_python_enum_value_is_unwrapped(self) -> None:
        """Ship-broken contract: a plain Python enum.Enum member must also be
        unwrapped to its raw value.
        """

        class Color(enum.Enum):
            """Minimal enum used only to exercise the unwrap-a-plain-enum path."""

            RED = 1
            BLUE = 2

        item = {"color": Color.RED}
        result = self._unwrap(item)
        self.assertEqual(result["color"], 1)

    def test_class_named_myenumthing_is_not_unwrapped(self) -> None:
        """Ship-broken contract: a class whose name merely contains "Enum" but
        is not an actual enum.Enum must NOT be unwrapped.

        This pins the bug fix: a substring check on the class name would
        wrongly unwrap this value; only isinstance(value, enum.Enum) may.
        """

        class MyEnumThing:
            """Not an enum — just a class with "Enum" in its name."""

            def __init__(self, val: Any) -> None:
                """Store the given value on the instance.

                Args:
                    val: The value to keep on "self.value".
                """
                self.value = val

        not_an_enum = MyEnumThing(42)
        item = {"thing": not_an_enum}
        result = self._unwrap(item)
        # The object must be returned as-is, not replaced by its .value
        self.assertIs(result["thing"], not_an_enum)

    def test_plain_string_value_is_not_unwrapped(self) -> None:
        """Ship-broken contract: ordinary non-enum values must pass through
        "_unwrap_enums" completely unchanged.
        """
        item = {"name": "Alice", "count": 3}
        result = self._unwrap(item)
        self.assertEqual(result, {"name": "Alice", "count": 3})


# ---------------------------------------------------------------------------
# (c) perform_mutate pin — DjangoModelMutation returns the in-memory object
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class PerformMutatePinTest(TestCase):
    """DjangoModelMutation.perform_mutate returns the obj passed in (no re-read).

    This documents the CURRENT (intentional) behavior: unlike DjangoModelType,
    DjangoModelMutation does NOT re-query the DB. Pinned as a regression guard
    so any future change to align them is explicit and reviewed.
    """

    def test_perform_mutate_returns_same_object(self) -> None:
        """Ship-broken contract: the returned payload object must be exactly
        the same instance passed in, not a re-queried copy.
        """
        from .models import Author

        class AuthorMutation(DjangoModelMutation):
            """Bare mutation stub, used only to exercise perform_mutate directly."""

            class Meta:
                model = Author

        author = Author(name="In-Memory Name")
        author.pk = 999  # simulate a saved instance without a real DB hit

        result = AuthorMutation.perform_mutate(author, _info())

        self.assertTrue(result.ok)
        returned = getattr(result, result._meta.output_field_name)
        self.assertIs(returned, author)
        # In-memory attribute is preserved (no DB re-read that might override)
        self.assertEqual(returned.name, "In-Memory Name")
