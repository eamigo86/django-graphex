# -*- coding: utf-8 -*-
"""DRF-style inline validate_<field>() / validate() on the native backend."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.db import models
from django.test import TestCase
from pydantic import BaseModel, field_validator

from django_graphex.core.validators import build_validator_model
from django_graphex.mutation import DjangoModelMutation
from django_graphex.types import DjangoModelType
from tests.models import DummyModel


class Widget(DummyModel):
    """A minimal model exercising per-field and object-level inline validators.

    Provides "name", "slug", and "price" fields for the validate_name/validate
    scenarios covered in this module.
    """

    name = models.CharField(max_length=50)
    slug = models.CharField(max_length=50, blank=True, default="")
    price = models.IntegerField(default=0)


def _info() -> SimpleNamespace:
    """Build a bare GraphQL resolve-info stand-in for direct mutation calls.

    Returns:
        info: A namespace with the "context.META"/"context.FILES" shape the
            mutation resolvers read from.
    """
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(
    host: type[DjangoModelType] | type[DjangoModelMutation], data: dict[str, Any]
) -> Any:
    """Invoke "create" on a type or mutation host with the given input payload.

    Args:
        host: The DjangoModelType or DjangoModelMutation class to call create on.
        data: The input field's payload, keyed by the host's input field name.

    Returns:
        result: The mutation result returned by "host.create".
    """
    return host.create(None, _info(), **{host._meta.input_field_name: data})


class WidgetType(DjangoModelType):
    """A "DjangoModelType" for "Widget" with per-field and cross-field inline validators.

    Exercises "validate_name" (per-field) and "validate" (object-level) inline
    validator hooks.
    """

    class Meta:
        """Bind "WidgetType" to the "Widget" model.

        No other options are set; this is the plain single-model configuration.
        """

        model = Widget

    # per-field: reject all-caps, and transform (strip) a valid value
    def validate_name(self, value: str) -> str:
        """Reject all-caps names and strip surrounding whitespace otherwise.

        Args:
            value: The raw "name" field value submitted by the caller.

        Returns:
            value: The stripped name.

        Raises:
            ValueError: If the name is entirely upper case.
        """
        if value.isupper():
            raise ValueError("name must not be all caps")
        return value.strip()

    # object-level cross-field rule
    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Reject expensive widgets whose name does not start with "premium".

        Args:
            data: The full validated input payload for the mutation.

        Returns:
            data: The input payload unchanged.

        Raises:
            ValueError: If price exceeds 100 and name does not start with
                "premium".
        """
        if data.get("price", 0) > 100 and not data.get("name", "").startswith(
            "premium"
        ):
            raise ValueError("expensive widgets must be named premium*")
        return data


class WidgetMutation(DjangoModelMutation):
    """A "DjangoModelMutation" for "Widget" carrying the same name validator.

    Proves the inline "validate_name" hook also works on the plain mutation
    host, not just "DjangoModelType".
    """

    class Meta:
        """Bind "WidgetMutation" to the "Widget" model.

        No other options are set; this is the plain single-model configuration.
        """

        model = Widget

    def validate_name(self, value: str) -> str:
        """Reject all-caps names on the mutation write path.

        Args:
            value: The raw "name" field value submitted by the caller.

        Returns:
            value: The name unchanged.

        Raises:
            ValueError: If the name is entirely upper case.
        """
        if value.isupper():
            raise ValueError("name must not be all caps")
        return value


class PerFieldTest(TestCase):
    """Per-field "validate_name" behavior on both "DjangoModelType" and mutations.

    Covers rejection, transformation, and reuse on a plain mutation host.
    """

    def test_rejects_invalid(self) -> None:
        """An all-caps name must be rejected with a field-scoped error on "name".

        If this breaks, "validate_name" would silently accept invalid names.
        """
        result = _create(WidgetType, {"name": "LOUD"})
        self.assertFalse(result.ok)
        self.assertIn("name", {e.field for e in result.errors})

    def test_transforms_valid(self) -> None:
        """A valid name must pass through "validate_name" and be persisted stripped.

        Guards the transform side of the hook, not just the rejection side.
        """
        result = _create(WidgetType, {"name": "  spaced  "})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Widget.objects.get().name, "spaced")

    def test_works_on_mutation_too(self) -> None:
        """The same inline "validate_name" rule must also apply on a plain mutation host.

        Proves the inline validator hook is not specific to "DjangoModelType".
        """
        result = _create(WidgetMutation, {"name": "LOUD"})
        self.assertFalse(result.ok)
        self.assertIn("name", {e.field for e in result.errors})


class ObjectLevelTest(TestCase):
    """Object-level "validate" cross-field behavior on "DjangoModelType".

    Covers both the rejection and the passing case for the cross-field rule.
    """

    def test_cross_field_rejection_is_non_field_error(self) -> None:
        """An expensive, non-premium-named widget must fail as a non-field error.

        If this breaks, cross-field rules could not surface a non_field_errors
        rejection.
        """
        result = _create(WidgetType, {"name": "cheapish", "price": 200})
        self.assertFalse(result.ok)
        self.assertIn("non_field_errors", {e.field for e in result.errors})

    def test_cross_field_pass(self) -> None:
        """An expensive widget named with the "premium" prefix must pass validation.

        Confirms the object-level rule does not reject valid combinations.
        """
        result = _create(WidgetType, {"name": "premium-x", "price": 200})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))


class _SlugRules(BaseModel):
    """A standalone pydantic model contributing a "slug" field validator.

    Used to prove inline "validate_*" hooks compose with an external
    "pydantic_model".
    """

    @field_validator("slug", check_fields=False)
    @classmethod
    def no_spaces(cls, value: str) -> str:
        """Reject a slug containing spaces.

        Args:
            value: The raw "slug" field value submitted by the caller.

        Returns:
            value: The slug unchanged.

        Raises:
            ValueError: If the slug contains a space character.
        """
        if value and " " in value:
            raise ValueError("slug must not contain spaces")
        return value


class ComposeWidgetType(DjangoModelType):
    """A "DjangoModelType" composing an inline validator with an external "pydantic_model".

    Combines the inline "validate_name" hook with "_SlugRules" via the
    "pydantic_model" Meta option.
    """

    class Meta:
        """Bind "ComposeWidgetType" to "Widget" and compose in "_SlugRules".

        The "pydantic_model" option layers the external slug validator on top
        of the inline "validate_name" hook.
        """

        model = Widget
        pydantic_model = _SlugRules  # composes with the inline validate_name

    def validate_name(self, value: str) -> str:
        """Reject all-caps names alongside the composed "_SlugRules" slug check.

        Args:
            value: The raw "name" field value submitted by the caller.

        Returns:
            value: The name unchanged.

        Raises:
            ValueError: If the name is entirely upper case.
        """
        if value.isupper():
            raise ValueError("name must not be all caps")
        return value


class ComposeTest(TestCase):
    """Composition of an inline validator with an external "pydantic_model".

    Covers both the inline and the composed validator firing independently.
    """

    def test_inline_and_pydantic_model_both_run(self) -> None:
        """Both the inline "validate_name" and the composed "_SlugRules" validator must fire.

        If this breaks, composing an inline validator with an external
        "pydantic_model" would silently drop one of the two rule sets.
        """
        # inline validate_name fires
        bad_name = _create(ComposeWidgetType, {"name": "LOUD", "slug": "ok"})
        self.assertFalse(bad_name.ok)
        self.assertIn("name", {e.field for e in bad_name.errors})
        # pydantic_model slug validator fires
        bad_slug = _create(ComposeWidgetType, {"name": "fine", "slug": "has space"})
        self.assertFalse(bad_slug.ok)
        self.assertIn("slug", {e.field for e in bad_slug.errors})


class UnknownFieldTest(TestCase):
    """Warning behavior when an inline validator names a nonexistent field.

    Covers the single scenario of a "validate_<field>" typo.
    """

    def test_validate_unknown_field_warns(self) -> None:
        """A "validate_<field>" naming an unknown field must emit a UserWarning.

        Guards against a typo'd validator name failing silently instead of
        warning the developer.
        """
        with pytest.warns(UserWarning, match="does not match any writable field"):

            class _Bad(DjangoModelType):
                class Meta:
                    model = Widget

                def validate_nonexistent(self, value):  # no such field
                    return value


class HelperPassthroughTest(TestCase):
    """Passthrough behavior of "build_validator_model" with no inline validators.

    Covers both a non-None base model and a None base model.
    """

    def test_no_inline_validators_returns_pydantic_model_unchanged(self) -> None:
        """With no "validate_*" methods, the helper must return the base model as-is.

        Also covers the "None" base case, which must return None rather than
        raising or fabricating a model.
        """
        sentinel = _SlugRules
        # a host with no validate_* methods -> helper returns the base unchanged
        self.assertIs(
            build_validator_model(ObjectLevelTest, Widget, sentinel), sentinel
        )
        self.assertIsNone(build_validator_model(ObjectLevelTest, Widget, None))
