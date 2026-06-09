# -*- coding: utf-8 -*-
"""Remaining branch coverage for ``paginations/pagination.py``.

Covers the in-memory (prefetch-cache) paginate paths for limit/offset, page and
cursor paginators, the page-size-None early return, the comma-ordering single
branches, cursor decode validation, and the cursor ``get_page_info`` /
``get_page_info_field`` resolver paths (both empty and populated windows).
"""

from types import SimpleNamespace

import pytest
from django.test import TestCase

from django_graphex.base_types import DjangoListObjectBase
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from tests.models import Author


def _items(*values):
    return [SimpleNamespace(name=v) for v in values]


# --------------------------------------------------------------------------- #
# In-memory (non-queryset) paginate paths                                       #
# --------------------------------------------------------------------------- #
def test_limit_offset_inmemory_orders_and_slices():
    p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10)
    out = p.paginate_queryset(_items("c", "a", "b"), ordering="name")
    assert [o.name for o in out] == ["a", "b"]


def test_limit_offset_inmemory_no_order():
    p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10)
    out = p.paginate_queryset(_items("x", "y", "z"))
    assert [o.name for o in out] == ["x", "y"]


def test_limit_offset_unbounded_returns_input():
    # No default and no max -> _resolve_page_size returns None -> qs returned.
    p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
    data = _items("a", "b")
    assert p.paginate_queryset(data) is data


def test_page_inmemory_orders_and_slices():
    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    out = p.paginate_queryset(_items("c", "a", "b"), page=1, ordering="name")
    assert [o.name for o in out] == ["a", "b"]


def test_page_inmemory_no_order():
    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    out = p.paginate_queryset(_items("x", "y", "z"), page=1)
    assert [o.name for o in out] == ["x", "y"]


def test_page_size_none_returns_none():
    # No page_size, no max, no client param -> page_size resolves to None ->
    # the resolver returns None (lines 436-443).
    p = PageGraphqlPagination(page_size=None, max_page_size=None)
    assert p.paginate_queryset(_items("a", "b"), page=1) is None


def test_page_zero_raises():
    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    with pytest.raises((AssertionError, ValueError)):
        p.paginate_queryset(_items("a", "b"), page=0)


def test_page_size_query_param_in_fields():
    p = PageGraphqlPagination(page_size=5, page_size_query_param="pageSize")
    assert "pageSize" in p.to_graphql_fields()


# --------------------------------------------------------------------------- #
# Cursor: decode validation + in-memory paginate / page info                    #
# --------------------------------------------------------------------------- #
def test_cursor_decode_rejects_bad_prefix():
    import base64

    bad = base64.urlsafe_b64encode(b"notcursor:1").decode("ascii")
    with pytest.raises(ValueError):
        CursorGraphqlPagination.decode_cursor(bad)


def test_cursor_decode_rejects_garbage():
    with pytest.raises(ValueError):
        CursorGraphqlPagination.decode_cursor("!!!not-base64!!!")


def test_cursor_inmemory_paginate_with_cursor():
    p = CursorGraphqlPagination(ordering="name", page_size=10)
    items = _items("a", "b", "c", "d")
    token = CursorGraphqlPagination.encode_cursor("b")
    out = p.paginate_queryset(items, first=10, cursor=token)
    assert [o.name for o in out] == ["c", "d"]


def test_cursor_inmemory_start_not_found_returns_from_zero():
    p = CursorGraphqlPagination(ordering="name", page_size=10)
    items = _items("a", "b")
    # A cursor not present -> _inmemory_cursor_start returns 0.
    token = CursorGraphqlPagination.encode_cursor("zzz")
    out = p.paginate_queryset(items, first=10, cursor=token)
    assert [o.name for o in out] == ["a", "b"]


def test_cursor_inmemory_page_info_populated_window():
    p = CursorGraphqlPagination(ordering="name", page_size=2)
    items = _items("a", "b", "c", "d")
    info = p.get_page_info(items, first=2)
    assert info["has_next_page"] is True
    assert info["has_previous_page"] is False
    assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("a")
    assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor("b")


def test_cursor_inmemory_page_info_empty_window():
    p = CursorGraphqlPagination(ordering="name", page_size=2)
    info = p.get_page_info([], first=2)
    assert info == {
        "has_next_page": False,
        "has_previous_page": False,
        "start_cursor": None,
        "end_cursor": None,
    }


def test_cursor_page_info_field_resolver_non_list_root_returns_none():
    p = CursorGraphqlPagination(ordering="name")
    field = p.get_page_info_field(None)
    assert field.resolver("not-a-base", None) is None


# --------------------------------------------------------------------------- #
# Cursor get_page_info over a real queryset                                     #
# --------------------------------------------------------------------------- #
class CursorPageInfoDbTest(TestCase):
    def setUp(self):
        for name in ("a", "b", "c", "d"):
            Author.objects.create(name=name)

    def test_page_info_queryset_first_page(self):
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        info = p.get_page_info(Author.objects.all(), first=2)
        assert info["has_next_page"] is True
        assert info["has_previous_page"] is False
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("a")

    def test_page_info_queryset_after_cursor_has_previous(self):
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("b")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info["has_previous_page"] is True
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("c")

    def test_page_info_queryset_empty_result(self):
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        # A cursor past the last row -> no rows -> the empty branch.
        token = CursorGraphqlPagination.encode_cursor("z")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info["start_cursor"] is None
        assert info["end_cursor"] is None

    def test_page_info_field_resolver_with_list_base(self):
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        field = p.get_page_info_field(None)
        base = DjangoListObjectBase(
            results=Author.objects.all(), count=4, results_field_name="results"
        )
        info = field.resolver(base, None, first=2)
        assert info["has_next_page"] is True
