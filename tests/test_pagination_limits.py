# -*- coding: utf-8 -*-
"""Effective max page size enforcement across the three paginators."""

from django.test import TestCase

from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)


class ResolvePageSizeTest(TestCase):
    """Unit tests for the shared `_resolve_page_size` resolver."""

    def setUp(self):
        self.p = LimitOffsetGraphqlPagination()

    def test_max_is_fallback_when_no_default_and_omitted(self):
        # requested omitted, no default -> falls back to the max (the fix).
        self.assertEqual(self.p._resolve_page_size(None, None, 100), 100)

    def test_explicit_value_clamped_to_max(self):
        self.assertEqual(self.p._resolve_page_size(500, 25, 100), 100)

    def test_default_used_when_omitted(self):
        self.assertEqual(self.p._resolve_page_size(None, 25, 100), 25)

    def test_unbounded_when_nothing_configured(self):
        self.assertIsNone(self.p._resolve_page_size(None, None, None))

    def test_requested_under_max_is_kept(self):
        self.assertEqual(self.p._resolve_page_size(10, 25, 100), 10)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            self.p._resolve_page_size(-5, None, 100)


class LimitOffsetCeilingTest(TestCase):
    def test_omitted_limit_falls_back_to_max(self):
        # No default, max=5: an omitted `limit` must cap at 5, not return all.
        p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=5)
        qs = list(range(50))
        self.assertEqual(len(p.paginate_queryset(qs)), 5)

    def test_explicit_limit_clamped_to_max(self):
        p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=5)
        self.assertEqual(len(p.paginate_queryset(list(range(50)), limit=40)), 5)

    def test_unbounded_when_nothing_configured(self):
        p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
        qs = list(range(50))
        self.assertEqual(len(p.paginate_queryset(qs)), 50)  # unchanged: returns all


class PageCeilingTest(TestCase):
    def test_client_page_size_clamped_to_max(self):
        p = PageGraphqlPagination(
            page_size=None, page_size_query_param="page_size", max_page_size=5
        )
        result = p.paginate_queryset(list(range(50)), page=1, page_size=40)
        self.assertEqual(len(result), 5)

    def test_omitted_page_size_falls_back_to_max(self):
        p = PageGraphqlPagination(
            page_size=None, page_size_query_param="page_size", max_page_size=5
        )
        self.assertEqual(len(p.paginate_queryset(list(range(50)), page=1)), 5)


class CursorMaxTest(TestCase):
    def test_cursor_has_per_instance_max(self):
        p = CursorGraphqlPagination(max_page_size=7)
        self.assertEqual(p.max_page_size, 7)
        self.assertEqual(p.to_dict()["max_page_size"], 7)

    def test_cursor_clamps_first_to_max(self):
        p = CursorGraphqlPagination(max_page_size=7)
        self.assertEqual(p._page_size(first=100), 7)

    def test_cursor_floor_when_nothing_configured(self):
        p = CursorGraphqlPagination(page_size=None, max_page_size=None)
        self.assertEqual(p._page_size(), 20)  # DEFAULT_CURSOR_PAGE_SIZE
