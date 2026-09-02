# -*- coding: utf-8 -*-
"""Tests for django_graphex.settings module."""

from __future__ import annotations

from django.core.checks import WARNING
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
            "CACHE_INVALIDATION_SCOPE": "global",
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
            "CACHE_INVALIDATION_SCOPE": "identity",
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
        self.assertEqual(s.CACHE_INVALIDATION_SCOPE, "identity")

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


class UnknownSettingKeyCheckTest(TestCase):
    """Test cases for the "DJANGO_GRAPHEX" unknown-key Django system check.

    A misspelled key inside the "DJANGO_GRAPHEX" dict silently keeps the
    library default, so a typo'd security cap ("MAX_PAGE_SIZ") or flag
    ("CACHE_ACTIV") does nothing at all. The system check is the only signal
    a project gets.
    """

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZ": 10, "CACHE_ACTIV": True})
    def test_unknown_keys_are_reported_by_run_checks(self) -> None:
        """Assert misspelled DJANGO_GRAPHEX keys surface through "run_checks".

        If this fails, a typo'd cap or security flag ships to production with
        no signal whatsoever: the setting keeps its library default.
        """
        from django.core.checks import run_checks

        messages = [m for m in run_checks() if m.id.startswith("django_graphex.")]
        self.assertEqual(len(messages), 1, messages)
        message = messages[0]
        self.assertEqual(message.id, "django_graphex.W001")
        self.assertEqual(message.level, WARNING)
        self.assertIn("MAX_PAGE_SIZ", message.msg)
        self.assertIn("CACHE_ACTIV", message.msg)
        # The closest known key must be suggested, as the Meta-option idiom does.
        self.assertIn("MAX_PAGE_SIZE", message.hint or "")
        self.assertIn("CACHE_ACTIVE", message.hint or "")

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 10, "CACHE_ACTIVE": True})
    def test_known_keys_report_nothing(self) -> None:
        """Assert a correctly spelled DJANGO_GRAPHEX dict raises no message.

        If this fails, every correctly configured project would see a spurious
        warning and learn to ignore the check.
        """
        from django.core.checks import run_checks

        self.assertEqual(
            [m for m in run_checks() if m.id.startswith("django_graphex.")], []
        )
