"""Minimum-zero validation for the three configurable operational bounds."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_graphex.settings import DEFAULTS, GraphQLAPISettings, graphql_api_settings

LIMIT_NAMES = (
    "MAX_BATCH_SIZE",
    "MAX_REQUEST_BODY_SIZE",
    "DOCUMENT_CACHE_MAXSIZE",
)


@pytest.mark.parametrize(
    ("name", "remedy"),
    [
        ("MAX_BATCH_SIZE", "None"),
        ("MAX_REQUEST_BODY_SIZE", "None"),
        ("DOCUMENT_CACHE_MAXSIZE", "None"),
    ],
)
def test_negative_integer_limit_fails_on_public_setting_read(
    name: str, remedy: str
) -> None:
    """Reject a negative integer where a configured limit is read.

    Args:
        name: The setting read through the public settings object.
        remedy: The documented alternative named in the configuration error.
    """
    with override_settings(DJANGO_GRAPHEX={name: -1}):
        with pytest.raises(ImproperlyConfigured) as exc_info:
            getattr(graphql_api_settings, name)

    message = str(exc_info.value)
    assert f"DJANGO_GRAPHEX['{name}'] = -1" in message
    assert "minimum of 0" in message
    assert remedy in message


@pytest.mark.parametrize("name", LIMIT_NAMES)
@pytest.mark.parametrize("value", [0, None, 3])
def test_approved_boundary_values_are_retained(name: str, value: int | None) -> None:
    """Keep zero, an unset limit, and a positive limit unchanged.

    Args:
        name: Setting read through the public singleton.
        value: Approved boundary value to preserve.
    """
    with override_settings(DJANGO_GRAPHEX={name: value}):
        assert getattr(graphql_api_settings, name) is value


@pytest.mark.parametrize("name", LIMIT_NAMES)
def test_default_is_unchanged(name: str) -> None:
    """Keep each declared default when the namespace is empty.

    Args:
        name: Setting whose declared default is read.
    """
    with override_settings(DJANGO_GRAPHEX={}):
        assert getattr(graphql_api_settings, name) == DEFAULTS[name]


@pytest.mark.parametrize("name", LIMIT_NAMES)
@pytest.mark.parametrize("value", [False, True, -0.5, "-1"])
def test_existing_nonnegative_bool_and_noninteger_policy_is_unchanged(
    name: str, value: bool | float | str
) -> None:
    """Leave the existing validator's boolean and noninteger handling intact.

    Args:
        name: Setting read through the public singleton.
        value: Previously accepted value outside negative integers.
    """
    with override_settings(DJANGO_GRAPHEX={name: value}):
        assert getattr(graphql_api_settings, name) is value


@pytest.mark.parametrize("name", LIMIT_NAMES)
def test_negative_limit_is_validated_lazily(name: str) -> None:
    """Raise on the first setting read rather than at reader construction.

    Args:
        name: Setting with a negative integer override.
    """
    reader = GraphQLAPISettings(user_settings={name: -2})
    assert name not in reader.__dict__
    with pytest.raises(ImproperlyConfigured, match="minimum of 0"):
        getattr(reader, name)
    assert name not in reader.__dict__
