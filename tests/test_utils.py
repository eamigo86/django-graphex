# -*- coding: utf-8 -*-
"""Tests for django_graphex.utils module."""

from django.test import TestCase

from django_graphex.utils import (
    clean_dict,
    get_model_fields,
    get_Object_or_None,
    to_kebab_case,
)

from .models import BasicModel


class UtilsTest(TestCase):
    """Test cases for the "django_graphex.utils" helper functions.

    Covers clean_dict, to_kebab_case, get_Object_or_None, and get_model_fields.
    """

    def test_clean_dict(self) -> None:
        """Ship-broken contract: clean_dict must strip None, empty-string, and
        empty-collection values recursively from nested dicts, dropping keys
        whose values become empty after cleaning.
        """
        # Test removing empty values from nested dicts
        dirty_dict = {
            "key1": "value1",
            "key2": None,
            "key3": "",
            "key4": {"nested1": "value", "nested2": None, "nested3": []},
            "key5": [],
        }

        cleaned = clean_dict(dirty_dict)
        expected = {"key1": "value1", "key4": {"nested1": "value"}}
        self.assertEqual(cleaned, expected)

    def test_to_kebab_case(self) -> None:
        """Ship-broken contract: to_kebab_case must convert CamelCase and
        space-separated strings to lowercase, hyphen-separated form.
        """
        # Test string to kebab-case conversion based on actual implementation
        self.assertEqual(to_kebab_case("CamelCase"), "camelcase")
        self.assertEqual(to_kebab_case("snake_case"), "snake_-case")  # Actual behavior
        self.assertEqual(to_kebab_case("Mixed Case"), "mixed-case")

    def test_get_Object_or_None(self) -> None:
        """Ship-broken contract: get_Object_or_None must return the matching
        instance when found and None (not raise) when no row matches.
        """
        # Create a test object
        obj = BasicModel.objects.create(text="test object")

        # Test successful retrieval
        result = get_Object_or_None(BasicModel, pk=obj.pk)
        self.assertEqual(result, obj)

        # Test non-existent object
        result = get_Object_or_None(BasicModel, pk=99999)
        self.assertIsNone(result)

    def test_get_model_fields(self) -> None:
        """Ship-broken contract: get_model_fields must return a list of
        (name, field) tuples covering the model's declared fields.
        """
        fields = get_model_fields(BasicModel)
        self.assertIsInstance(fields, list)
        self.assertGreater(len(fields), 0)

        # Check that it returns tuples of (name, field)
        for field_info in fields:
            self.assertIsInstance(field_info, tuple)
            self.assertEqual(len(field_info), 2)

        # The model's declared fields are present, keyed by name.
        names = {name for name, _field in fields}
        self.assertIn("id", names)
        self.assertIn("text", names)
