# -*- coding: utf-8 -*-
"""Tests for django_graphex.settings module."""

from django.test import TestCase, override_settings

from django_graphex.settings import graphql_api_settings


class SettingsTest(TestCase):
    """Test cases for settings module."""

    def test_default_settings(self):
        """Default settings resolve to their declared default values."""
        self.assertIsNotNone(graphql_api_settings)

        # Each setting must resolve, and to its documented default value.
        expected_defaults = {
            "DEFAULT_PAGINATION_CLASS": None,
            "DEFAULT_PAGE_SIZE": None,
            "MAX_PAGE_SIZE": None,
            "CACHE_ACTIVE": False,
            "CACHE_TIMEOUT": 300,
        }
        for setting_name, expected in expected_defaults.items():
            self.assertTrue(hasattr(graphql_api_settings, setting_name), setting_name)
            self.assertEqual(
                getattr(graphql_api_settings, setting_name), expected, setting_name
            )

    @override_settings(
        DJANGO_GRAPHEX={
            "DEFAULT_PAGE_SIZE": 25,
            "MAX_PAGE_SIZE": 100,
            "CACHE_ACTIVE": True,
            "CACHE_TIMEOUT": 600,
        }
    )
    def test_custom_settings(self):
        """Custom DJANGO_GRAPHEX overrides take effect for every key."""
        # The setting_changed signal rebinds the global, so read via the module
        # to observe the rebuilt instance.
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertEqual(s.DEFAULT_PAGE_SIZE, 25)
        self.assertEqual(s.MAX_PAGE_SIZE, 100)
        self.assertIs(s.CACHE_ACTIVE, True)
        self.assertEqual(s.CACHE_TIMEOUT, 600)

    def test_settings_accessibility(self):
        """Test that settings are accessible."""
        # Settings should be importable and accessible
        from django_graphex.settings import graphql_api_settings

        # Should be able to access settings
        self.assertIsNotNone(graphql_api_settings)

        # Should have some attributes
        attrs = dir(graphql_api_settings)
        self.assertIsInstance(attrs, list)
        self.assertGreater(len(attrs), 0)

    def test_settings_type(self):
        """Test settings object type."""
        # Settings should be some kind of settings object
        self.assertIsNotNone(type(graphql_api_settings))

        # Should have string representation
        str_repr = str(graphql_api_settings)
        self.assertIsInstance(str_repr, str)
