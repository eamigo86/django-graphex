"""Tests for the django_graphex.apps.DjangoGraphexConfig AppConfig.

TDD RED phase: tests written before the module exists.
Run with: .venv/bin/python -m pytest tests/core/test_apps.py -x -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper


def test_app_config_exists() -> None:
    """Assert that DjangoGraphexConfig is importable from apps.py.

    If this fails, the app registration entry point is missing or broken,
    so Django cannot discover django_graphex as an installed app.
    """
    from django_graphex.apps import DjangoGraphexConfig

    assert DjangoGraphexConfig is not None


def test_app_config_name() -> None:
    """Assert that DjangoGraphexConfig.name equals "django_graphex".

    If this fails, Django's app registry resolves the wrong label for the
    app, breaking migrations, admin, and settings lookups tied to that name.
    """
    from django_graphex.apps import DjangoGraphexConfig

    assert DjangoGraphexConfig.name == "django_graphex"


def test_app_config_ready_calls_compile_all_inputs() -> None:
    """Assert that AppConfig.ready() triggers compile_all_inputs() exactly once.

    If this fails, InputType subclasses never get compiled on app startup,
    leaving the GraphQL schema without input types when the app boots.
    """
    from unittest.mock import patch

    from django_graphex.apps import DjangoGraphexConfig

    config = DjangoGraphexConfig.__new__(DjangoGraphexConfig)
    # AppConfig needs app_name and app_module
    config.name = "django_graphex"

    with patch("django_graphex.core.base.compile_all_inputs") as mock_compile:
        config.ready()
        mock_compile.assert_called_once()


def test_app_config_ready_sets_graphql_input_type(settings: SettingsWrapper) -> None:
    """Assert that after ready(), InputType subclasses get graphql_input_type set.

    If this fails, InputType subclasses defined before app startup are left
    without a compiled GraphQLInputObjectType, so the schema build would fail
    or silently omit those input types.

    Args:
        settings: The pytest-django fixture giving access to Django settings;
            unused directly but required to ensure Django settings are
            configured before the test runs.
    """
    from graphql import GraphQLInputObjectType

    from django_graphex.apps import DjangoGraphexConfig
    from django_graphex.core.base import InputType

    # Create a fresh InputType subclass
    class ReadyTestInput(InputType):
        """Input type fixture used to verify ready() compiles it."""

        value: str

    # Simulate ready() call
    config = DjangoGraphexConfig.__new__(DjangoGraphexConfig)
    config.name = "django_graphex"
    config.ready()

    assert ReadyTestInput._meta.graphql_input_type is not None
    assert isinstance(ReadyTestInput._meta.graphql_input_type, GraphQLInputObjectType)
