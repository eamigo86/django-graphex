# -*- coding: utf-8 -*-
"""Internals of the settings reader: import-string resolution and error paths."""

import pytest
from django.test import override_settings

from django_graphex import settings as settings_module
from django_graphex.settings import (
    DEFAULTS,
    IMPORT_STRINGS,
    GraphQLAPISettings,
    _perform_import,
)


def test_perform_import_none_passthrough():
    assert _perform_import(None, "X") is None


def test_perform_import_resolves_dotted_string():
    cls = _perform_import(
        "django_graphex.paginations.LimitOffsetGraphqlPagination",
        "DEFAULT_PAGINATION_CLASS",
    )
    from django_graphex.paginations import LimitOffsetGraphqlPagination

    assert cls is LimitOffsetGraphqlPagination


def test_perform_import_resolves_list_of_strings():
    out = _perform_import(
        ["django_graphex.paginations.PageGraphqlPagination", 5],
        "SOME_LIST",
    )
    from django_graphex.paginations import PageGraphqlPagination

    assert out[0] is PageGraphqlPagination
    assert out[1] == 5  # non-string entries pass through untouched


def test_perform_import_passthrough_non_string():
    sentinel = object()
    assert _perform_import(sentinel, "X") is sentinel


def test_invalid_setting_name_raises_attribute_error():
    s = GraphQLAPISettings(None, DEFAULTS, IMPORT_STRINGS)
    with pytest.raises(AttributeError, match="Invalid DJANGO_GRAPHEX setting"):
        _ = s.NOT_A_REAL_SETTING


def test_user_setting_overrides_default():
    s = GraphQLAPISettings({"MAX_PAGE_SIZE": 42}, DEFAULTS, IMPORT_STRINGS)
    assert s.MAX_PAGE_SIZE == 42
    # Caching: reading again returns the memoized attribute.
    assert s.MAX_PAGE_SIZE == 42


@override_settings(
    DJANGO_GRAPHEX={
        "DEFAULT_PAGINATION_CLASS": (
            "django_graphex.paginations.LimitOffsetGraphqlPagination"
        )
    }
)
def test_reload_resolves_import_string_setting():
    # The setting_changed signal rebuilds the global; read via the module so the
    # rebound instance (not a stale import) is observed.
    from django_graphex.paginations import LimitOffsetGraphqlPagination

    assert settings_module.graphql_api_settings.DEFAULT_PAGINATION_CLASS is (
        LimitOffsetGraphqlPagination
    )
