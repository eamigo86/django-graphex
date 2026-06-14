"""Tests for django_graphex/apps.py AppConfig.

TDD RED phase: tests written before the module exists.
Run with: .venv/bin/python -m pytest tests/native/test_apps.py -x -v
"""
from __future__ import annotations

import pytest


@pytest.mark.native_only
def test_app_config_exists():
    """DjangoGraphexConfig AppConfig should be importable from apps.py."""
    from django_graphex.apps import DjangoGraphexConfig
    assert DjangoGraphexConfig is not None


@pytest.mark.native_only
def test_app_config_name():
    """AppConfig.name must be 'django_graphex'."""
    from django_graphex.apps import DjangoGraphexConfig
    assert DjangoGraphexConfig.name == "django_graphex"


@pytest.mark.native_only
def test_app_config_ready_calls_compile_all_inputs():
    """AppConfig.ready() triggers compile_all_inputs()."""
    from unittest.mock import patch, MagicMock
    from django_graphex.apps import DjangoGraphexConfig
    from django.apps import AppConfig

    config = DjangoGraphexConfig.__new__(DjangoGraphexConfig)
    # AppConfig needs app_name and app_module
    config.name = "django_graphex"

    with patch("django_graphex.native.base.compile_all_inputs") as mock_compile:
        config.ready()
        mock_compile.assert_called_once()


@pytest.mark.native_only
def test_app_config_ready_sets_graphql_input_type(settings):
    """After ready(), InputType subclasses have graphql_input_type set."""
    from graphql import GraphQLInputObjectType
    from django_graphex.native.base import InputType, _gdx_input_registry
    from django_graphex.apps import DjangoGraphexConfig

    # Create a fresh InputType subclass
    class ReadyTestInput(InputType):
        """Test input after ready."""
        value: str

    # Simulate ready() call
    config = DjangoGraphexConfig.__new__(DjangoGraphexConfig)
    config.name = "django_graphex"
    config.ready()

    assert ReadyTestInput._meta.graphql_input_type is not None
    assert isinstance(ReadyTestInput._meta.graphql_input_type, GraphQLInputObjectType)
