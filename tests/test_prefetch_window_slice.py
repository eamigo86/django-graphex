"""Unit tests for BaseDjangoGraphqlPagination.prefetch_window_slice hook.

C1 Phase 2 — RED-first per task:
  2.1  Base returns None
  2.3  LimitOffset returns tuple
  2.4  LimitOffset MAX_PAGE_SIZE clamped
  2.5  LimitOffset DEFAULT_PAGE_SIZE applied when limit kwarg absent
  2.6  LimitOffset unbounded returns None
  2.8  Page returns tuple (non-negative page)
  2.9  Page negative page returns None
  2.10 Page unbounded (page_size=None) returns None
  2.12 Cursor returns None
"""

from __future__ import annotations

from django.test import TestCase

from django_graphex.paginations.pagination import (
    BaseDjangoGraphqlPagination,
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)


class TestBasePrefetchWindowSlice(TestCase):
    """Task 2.1 — BaseDjangoGraphqlPagination.prefetch_window_slice returns None."""

    def test_base_returns_none(self):
        """Base implementation returns None for any kwargs (task 2.1)."""

        class _ConcreteBase(BaseDjangoGraphqlPagination):
            """Minimal concrete subclass that satisfies abstract requirements."""

            def paginate_queryset(self, qs, **kwargs):
                return qs

            def to_dict(self):
                return {}

            def to_graphql_fields(self):
                return {}

        paginator = _ConcreteBase()
        result = paginator.prefetch_window_slice(limit=5, offset=0, ordering=["id"])
        self.assertIsNone(result)


class TestLimitOffsetPrefetchWindowSlice(TestCase):
    """Tasks 2.3–2.6 — LimitOffsetGraphqlPagination.prefetch_window_slice."""

    def test_limitoffset_returns_tuple(self):
        """Returns (offset, limit, ordering) for a basic call (task 2.3)."""
        # LimitOffsetGraphqlPagination uses default_limit / max_limit (not page_size)
        paginator = LimitOffsetGraphqlPagination(default_limit=10)
        result = paginator.prefetch_window_slice(limit=5, offset=20, ordering=["id"])
        self.assertEqual(result, (20, 5, ["id"]))

    def test_limitoffset_max_page_size_clamped(self):
        """limit > max_limit is clamped to max_limit (task 2.4)."""
        paginator = LimitOffsetGraphqlPagination(max_limit=20)
        result = paginator.prefetch_window_slice(limit=100, offset=0, ordering=["id"])
        self.assertIsNotNone(result)
        offset, limit, ordering = result
        self.assertEqual(limit, 20, "limit must be clamped to max_limit=20")

    def test_limitoffset_default_page_size(self):
        """Absent limit kwarg falls back to default_limit (task 2.5)."""
        paginator = LimitOffsetGraphqlPagination(default_limit=10)
        result = paginator.prefetch_window_slice(offset=0, ordering=["id"])
        self.assertIsNotNone(result)
        offset, limit, ordering = result
        self.assertEqual(
            limit, 10, "default_limit must be applied when limit kwarg absent"
        )

    def test_limitoffset_unbounded_returns_none(self):
        """Unbounded paginator (default_limit=None, max_limit=None) returns None (task 2.6)."""
        paginator = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
        result = paginator.prefetch_window_slice(limit=None, offset=0, ordering=["id"])
        self.assertIsNone(result)


class TestPagePrefetchWindowSlice(TestCase):
    """Tasks 2.8–2.10 — PageGraphqlPagination.prefetch_window_slice."""

    def test_page_returns_tuple(self):
        """Returns (offset, page_size, ordering) for page=2, page_size=10 (task 2.8).

        offset = (page - 1) * page_size = 1 * 10 = 10.
        """
        paginator = PageGraphqlPagination(page_size=10)
        result = paginator.prefetch_window_slice(page=2, ordering=["-created"])
        self.assertEqual(result, (10, 10, ["-created"]))

    def test_page_negative_returns_none(self):
        """page < 0 (count-relative) returns None (task 2.9)."""
        paginator = PageGraphqlPagination(page_size=10)
        result = paginator.prefetch_window_slice(page=-1, ordering=["id"])
        self.assertIsNone(result)

    def test_page_unbounded_returns_none(self):
        """Unbounded (page_size=None) returns None (task 2.10)."""
        paginator = PageGraphqlPagination(page_size=None)
        result = paginator.prefetch_window_slice(page=1, ordering=["id"])
        self.assertIsNone(result)


class TestCursorPrefetchWindowSlice(TestCase):
    """Task 2.12 — CursorGraphqlPagination.prefetch_window_slice returns None."""

    def test_cursor_returns_none(self):
        """Cursor pagination always returns None (opaque keyset, task 2.12)."""
        paginator = CursorGraphqlPagination()
        result = paginator.prefetch_window_slice(first=5, cursor=None)
        self.assertIsNone(result)
