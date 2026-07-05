# -*- coding: utf-8 -*-
"""Tests for django_graphex.settings module."""

from __future__ import annotations

from django.test import TestCase, override_settings

from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.settings import graphql_api_settings


class SettingsTest(TestCase):
    """Test cases for the "graphql_api_settings" lazy settings object.

    Covers default values, override_settings-driven rebinding, and general
    accessibility of the settings instance.
    """

    def test_default_settings(self) -> None:
        """Assert every documented setting resolves to its declared default.

        If this fails, a setting's shipped default silently drifted from
        what the documentation promises.
        """
        self.assertIsNotNone(graphql_api_settings)

        # Each setting must resolve, and to its documented default value.
        expected_defaults = {
            "DEFAULT_PAGINATION_CLASS": LimitOffsetGraphqlPagination,
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
    def test_custom_settings(self) -> None:
        """Assert a custom DJANGO_GRAPHEX dict overrides take effect for every key.

        If this fails, project-level settings overrides would be ignored and
        every consumer would keep seeing library defaults.
        """
        # The setting_changed signal rebinds the global, so read via the module
        # to observe the rebuilt instance.
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertEqual(s.DEFAULT_PAGE_SIZE, 25)
        self.assertEqual(s.MAX_PAGE_SIZE, 100)
        self.assertIs(s.CACHE_ACTIVE, True)
        self.assertEqual(s.CACHE_TIMEOUT, 600)

    def test_settings_accessibility(self) -> None:
        """Assert the settings object is importable and exposes attributes.

        If this fails, consumers importing "graphql_api_settings" directly
        would get an unusable or empty object.
        """
        # Settings should be importable and accessible
        from django_graphex.settings import graphql_api_settings

        # Should be able to access settings
        self.assertIsNotNone(graphql_api_settings)

        # Should have some attributes
        attrs = dir(graphql_api_settings)
        self.assertIsInstance(attrs, list)
        self.assertGreater(len(attrs), 0)

    def test_settings_type(self) -> None:
        """Assert the settings object has a type and a string representation.

        If this fails, "graphql_api_settings" would not behave like a normal
        Python object, breaking any debugging or logging that reprs it.
        """
        # Settings should be some kind of settings object
        self.assertIsNotNone(type(graphql_api_settings))

        # Should have string representation
        str_repr = str(graphql_api_settings)
        self.assertIsInstance(str_repr, str)

    def test_optimizer_safe_mode_default_is_false(self) -> None:
        """Assert OPTIMIZER_SAFE_MODE defaults to False when not configured.

        If this fails, the optimizer would run in safe mode unexpectedly for
        projects that never opted in.
        """
        # REQ-1 / Scenario: Default value
        self.assertIs(graphql_api_settings.OPTIMIZER_SAFE_MODE, False)

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZER_SAFE_MODE": True})
    def test_optimizer_safe_mode_override_true(self) -> None:
        """Assert OPTIMIZER_SAFE_MODE can be overridden to True.

        If this fails, projects could not opt into safe mode via
        "override_settings" / DJANGO_GRAPHEX configuration.
        """
        # REQ-1 / Scenario: Override to True
        # setting_changed signal fires automatically via override_settings.
        from django_graphex import settings as settings_module

        s = settings_module.graphql_api_settings
        self.assertIs(s.OPTIMIZER_SAFE_MODE, True)
