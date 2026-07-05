# -*- coding: utf-8 -*-
"""Internals of the settings reader: import-string resolution and error paths."""

from __future__ import annotations

import pytest
from django.test import override_settings

from django_graphex import settings as settings_module
from django_graphex.settings import (
    DEFAULTS,
    IMPORT_STRINGS,
    GraphQLAPISettings,
    _perform_import,
)


def test_perform_import_none_passthrough() -> None:
    """Assert "_perform_import" passes None through unchanged.

    If this fails, settings left at their unset default would be wrongly
    coerced instead of staying None.
    """
    assert _perform_import(None, "X") is None


def test_perform_import_resolves_dotted_string() -> None:
    """Assert a dotted import path string resolves to the real class.

    If this fails, DEFAULT_PAGINATION_CLASS and similar import-string
    settings would keep their raw string value instead of the imported
    object.
    """
    cls = _perform_import(
        "django_graphex.paginations.LimitOffsetGraphqlPagination",
        "DEFAULT_PAGINATION_CLASS",
    )
    from django_graphex.paginations import LimitOffsetGraphqlPagination

    assert cls is LimitOffsetGraphqlPagination


def test_perform_import_resolves_list_of_strings() -> None:
    """Assert each string in a list is import-resolved, non-strings untouched.

    If this fails, a mixed list setting would either fail to resolve its
    dotted-path entries or would mangle its non-string entries.
    """
    out = _perform_import(
        ["django_graphex.paginations.PageGraphqlPagination", 5],
        "SOME_LIST",
    )
    from django_graphex.paginations import PageGraphqlPagination

    assert out[0] is PageGraphqlPagination
    assert out[1] == 5  # non-string entries pass through untouched


def test_perform_import_passthrough_non_string() -> None:
    """Assert a non-string, non-list value passes through unchanged.

    If this fails, settings values that are already objects (not import
    paths) would be mangled by the import-string resolver.
    """
    sentinel = object()
    assert _perform_import(sentinel, "X") is sentinel


def test_invalid_setting_name_raises_attribute_error() -> None:
    """Assert reading an unknown setting name raises "AttributeError".

    If this fails, typos in setting names would silently return None
    (or some other unhelpful value) instead of failing loudly.

    Raises:
        AttributeError: Not raised by the test itself; asserted via
            "pytest.raises" around the unknown attribute access.
    """
    s = GraphQLAPISettings(None, DEFAULTS, IMPORT_STRINGS)
    with pytest.raises(AttributeError, match="Invalid DJANGO_GRAPHEX setting"):
        _ = s.NOT_A_REAL_SETTING


def test_user_setting_overrides_default() -> None:
    """Assert a user-supplied setting overrides the default and gets memoized.

    If this fails, either user overrides would be ignored in favor of
    defaults, or the "__getattr__" caching behavior would recompute the
    value on every access instead of memoizing it on the instance.
    """
    s = GraphQLAPISettings({"MAX_PAGE_SIZE": 42}, DEFAULTS, IMPORT_STRINGS)
    # Not memoized before the first read: __getattr__ has not run yet.
    assert "MAX_PAGE_SIZE" not in s.__dict__
    assert s.MAX_PAGE_SIZE == 42
    # __getattr__ caches via setattr, so the value now lives in the instance dict
    # and a second read bypasses __getattr__ entirely.
    assert s.__dict__["MAX_PAGE_SIZE"] == 42
    assert s.MAX_PAGE_SIZE == 42


@override_settings(
    DJANGO_GRAPHEX={
        "DEFAULT_PAGINATION_CLASS": (
            "django_graphex.paginations.LimitOffsetGraphqlPagination"
        )
    }
)
def test_reload_resolves_import_string_setting() -> None:
    """Assert an override_settings-driven reload re-resolves import strings.

    If this fails, the setting_changed signal handler would rebuild the
    settings object without applying import-string resolution, leaving
    DEFAULT_PAGINATION_CLASS as a raw string after an override.
    """
    # The setting_changed signal rebuilds the global; read via the module so the
    # rebound instance (not a stale import) is observed.
    from django_graphex.paginations import LimitOffsetGraphqlPagination

    assert settings_module.graphql_api_settings.DEFAULT_PAGINATION_CLASS is (
        LimitOffsetGraphqlPagination
    )
