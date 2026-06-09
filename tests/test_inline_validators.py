# -*- coding: utf-8 -*-
"""DRF-style inline validate_<field>() / validate() on the native backend."""

from types import SimpleNamespace

import pytest
from django.db import models
from django.test import TestCase
from pydantic import BaseModel, field_validator

from django_graphex import DjangoModelMutation, DjangoModelType
from django_graphex.native.validators import build_validator_model
from tests.models import DummyModel


class Widget(DummyModel):
    name = models.CharField(max_length=50)
    slug = models.CharField(max_length=50, blank=True, default="")
    price = models.IntegerField(default=0)


def _info():
    return SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))


def _create(host, data):
    return host.create(None, _info(), **{host._meta.input_field_name: data})


class WidgetType(DjangoModelType):
    class Meta:
        model = Widget

    # per-field: reject all-caps, and transform (strip) a valid value
    def validate_name(self, value):
        if value.isupper():
            raise ValueError("name must not be all caps")
        return value.strip()

    # object-level cross-field rule
    def validate(self, data):
        if data.get("price", 0) > 100 and not data.get("name", "").startswith(
            "premium"
        ):
            raise ValueError("expensive widgets must be named premium*")
        return data


class WidgetMutation(DjangoModelMutation):
    class Meta:
        model = Widget

    def validate_name(self, value):
        if value.isupper():
            raise ValueError("name must not be all caps")
        return value


class PerFieldTest(TestCase):
    def test_rejects_invalid(self):
        result = _create(WidgetType, {"name": "LOUD"})
        self.assertFalse(result.ok)
        self.assertIn("name", {e.field for e in result.errors})

    def test_transforms_valid(self):
        result = _create(WidgetType, {"name": "  spaced  "})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))
        self.assertEqual(Widget.objects.get().name, "spaced")

    def test_works_on_mutation_too(self):
        result = _create(WidgetMutation, {"name": "LOUD"})
        self.assertFalse(result.ok)
        self.assertIn("name", {e.field for e in result.errors})


class ObjectLevelTest(TestCase):
    def test_cross_field_rejection_is_non_field_error(self):
        result = _create(WidgetType, {"name": "cheapish", "price": 200})
        self.assertFalse(result.ok)
        self.assertIn("non_field_errors", {e.field for e in result.errors})

    def test_cross_field_pass(self):
        result = _create(WidgetType, {"name": "premium-x", "price": 200})
        self.assertTrue(result.ok, msg=getattr(result, "errors", None))


class _SlugRules(BaseModel):
    @field_validator("slug", check_fields=False)
    @classmethod
    def no_spaces(cls, value):
        if value and " " in value:
            raise ValueError("slug must not contain spaces")
        return value


class ComposeWidgetType(DjangoModelType):
    class Meta:
        model = Widget
        pydantic_model = _SlugRules  # composes with the inline validate_name

    def validate_name(self, value):
        if value.isupper():
            raise ValueError("name must not be all caps")
        return value


class ComposeTest(TestCase):
    def test_inline_and_pydantic_model_both_run(self):
        # inline validate_name fires
        bad_name = _create(ComposeWidgetType, {"name": "LOUD", "slug": "ok"})
        self.assertFalse(bad_name.ok)
        self.assertIn("name", {e.field for e in bad_name.errors})
        # pydantic_model slug validator fires
        bad_slug = _create(ComposeWidgetType, {"name": "fine", "slug": "has space"})
        self.assertFalse(bad_slug.ok)
        self.assertIn("slug", {e.field for e in bad_slug.errors})


class UnknownFieldTest(TestCase):
    def test_validate_unknown_field_warns(self):
        with pytest.warns(UserWarning, match="does not match any writable field"):

            class _Bad(DjangoModelType):
                class Meta:
                    model = Widget

                def validate_nonexistent(self, value):  # no such field
                    return value


class HelperPassthroughTest(TestCase):
    def test_no_inline_validators_returns_pydantic_model_unchanged(self):
        sentinel = _SlugRules
        # a host with no validate_* methods -> helper returns the base unchanged
        self.assertIs(
            build_validator_model(ObjectLevelTest, Widget, sentinel), sentinel
        )
        self.assertIsNone(build_validator_model(ObjectLevelTest, Widget, None))
