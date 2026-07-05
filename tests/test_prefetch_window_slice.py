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

from typing import Any

from django.test import TestCase

from django_graphex.paginations.pagination import (
    BaseDjangoGraphqlPagination,
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)


class TestBasePrefetchWindowSlice(TestCase):
    """Task 2.1 — BaseDjangoGraphqlPagination.prefetch_window_slice returns None.

    The abstract base has no way to compute a window slice, so it must
    always decline rather than guess.
    """

    def test_base_returns_none(self) -> None:
        """Assert the base implementation returns None for any kwargs (task 2.1).

        If this fails, the base pagination class would advertise a
        prefetch window slice it cannot actually compute, misleading
        concrete paginators that forget to override the hook.
        """

        class _ConcreteBase(BaseDjangoGraphqlPagination):
            """Minimal concrete subclass that satisfies abstract requirements."""

            def paginate_queryset(self, qs: Any, **kwargs: Any) -> Any:
                return qs

            def to_dict(self) -> dict[str, Any]:
                return {}

            def to_graphql_fields(self) -> dict[str, Any]:
                return {}

        paginator = _ConcreteBase()
        result = paginator.prefetch_window_slice(limit=5, offset=0, ordering=["id"])
        self.assertIsNone(result)


class TestLimitOffsetPrefetchWindowSlice(TestCase):
    """Tasks 2.3-2.6 — LimitOffsetGraphqlPagination.prefetch_window_slice.

    Covers the basic offset/limit computation, max_limit clamping,
    default_limit fallback, and the unbounded no-limit case.
    """

    def test_limitoffset_returns_tuple(self) -> None:
        """Assert it returns (offset, limit, ordering) for a basic call (task 2.3).

        If this fails, prefetch-window computation for offset-based
        pagination would return the wrong shape or values, breaking any
        caller relying on it to slice a queryset ahead of time.
        """
        # LimitOffsetGraphqlPagination uses default_limit / max_limit (not page_size)
        paginator = LimitOffsetGraphqlPagination(default_limit=10)
        result = paginator.prefetch_window_slice(limit=5, offset=20, ordering=["id"])
        self.assertEqual(result, (20, 5, ["id"]))

    def test_limitoffset_max_page_size_clamped(self) -> None:
        """Assert a limit greater than max_limit is clamped to max_limit (task 2.4).

        If this fails, a caller-supplied limit could exceed the
        paginator's configured cap, defeating the max page size guard.
        """
        paginator = LimitOffsetGraphqlPagination(max_limit=20)
        result = paginator.prefetch_window_slice(limit=100, offset=0, ordering=["id"])
        self.assertIsNotNone(result)
        offset, limit, ordering = result
        self.assertEqual(limit, 20, "limit must be clamped to max_limit=20")

    def test_limitoffset_default_page_size(self) -> None:
        """Assert an absent limit kwarg falls back to default_limit (task 2.5).

        If this fails, omitting the limit argument would not apply the
        paginator's configured default page size.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=10)
        result = paginator.prefetch_window_slice(offset=0, ordering=["id"])
        self.assertIsNotNone(result)
        offset, limit, ordering = result
        self.assertEqual(
            limit, 10, "default_limit must be applied when limit kwarg absent"
        )

    def test_limitoffset_unbounded_returns_none(self) -> None:
        """Assert an unbounded paginator (no default/max limit) returns None (task 2.6).

        If this fails, a paginator with no configured limit would still
        attempt to compute a bounded prefetch window instead of signaling
        that no window can be determined.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
        result = paginator.prefetch_window_slice(limit=None, offset=0, ordering=["id"])
        self.assertIsNone(result)


class TestPagePrefetchWindowSlice(TestCase):
    """Tasks 2.8-2.10 — PageGraphqlPagination.prefetch_window_slice.

    Covers a normal page offset computation, the negative/zero page
    guards, and the unbounded no-page-size case.
    """

    def test_page_returns_tuple(self) -> None:
        """Assert it returns (offset, page_size, ordering) for page=2, page_size=10.

        offset = (page - 1) * page_size = 1 * 10 = 10 (task 2.8).

        If this fails, page-based prefetch window computation would
        return the wrong offset or shape for a mid-range page.
        """
        paginator = PageGraphqlPagination(page_size=10)
        result = paginator.prefetch_window_slice(page=2, ordering=["-created"])
        self.assertEqual(result, (10, 10, ["-created"]))

    def test_page_negative_returns_none(self) -> None:
        """Assert page < 0 (count-relative) returns None (task 2.9).

        If this fails, a negative page number would be treated as a
        computable window instead of being rejected.
        """
        paginator = PageGraphqlPagination(page_size=10)
        result = paginator.prefetch_window_slice(page=-1, ordering=["id"])
        self.assertIsNone(result)

    def test_page_zero_returns_none(self) -> None:
        """Assert page=0 returns None since it yields a negative offset (C2 guard).

        offset = page_size * (0 - 1) = negative, which must not be
        returned as a valid prefetch window.

        If this fails, requesting page 0 would compute a nonsensical
        negative offset instead of being rejected.
        """
        paginator = PageGraphqlPagination(page_size=10)
        result = paginator.prefetch_window_slice(page=0, ordering=["id"])
        self.assertIsNone(result, "page=0 yields negative offset; must return None")

    def test_page_unbounded_returns_none(self) -> None:
        """Assert an unbounded paginator (page_size=None) returns None (task 2.10).

        If this fails, a paginator with no configured page size would
        still attempt to compute a bounded prefetch window.
        """
        paginator = PageGraphqlPagination(page_size=None)
        result = paginator.prefetch_window_slice(page=1, ordering=["id"])
        self.assertIsNone(result)


class TestCursorPrefetchWindowSlice(TestCase):
    """Task 2.12 — CursorGraphqlPagination.prefetch_window_slice returns None.

    Cursor pagination uses an opaque keyset, so it has no offset/limit
    window to report.
    """

    def test_cursor_returns_none(self) -> None:
        """Assert cursor pagination always returns None (opaque keyset, task 2.12).

        If this fails, cursor-based pagination would advertise a
        computable prefetch window even though its opaque, keyset-based
        cursors cannot be translated into an offset/limit slice.
        """
        paginator = CursorGraphqlPagination()
        result = paginator.prefetch_window_slice(first=5, cursor=None)
        self.assertIsNone(result)
