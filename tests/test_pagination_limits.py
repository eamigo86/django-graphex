# -*- coding: utf-8 -*-
"""Effective max page size enforcement across the three paginators.

Covers "LimitOffsetGraphqlPagination", "PageGraphqlPagination" and
"CursorGraphqlPagination" ceiling behavior when a maximum is configured,
omitted, or exceeded by the caller.
"""

from django.test import TestCase

from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)


class ResolvePageSizeTest(TestCase):
    """Unit tests for the shared "_resolve_page_size" resolver.

    Covers requested, default, and max-size combinations, including the
    unbounded and negative-value edge cases.
    """

    def setUp(self) -> None:
        """Build a bare "LimitOffsetGraphqlPagination" to call the resolver on.

        Any paginator subclass works since "_resolve_page_size" is shared.
        """
        self.p = LimitOffsetGraphqlPagination()

    def test_max_is_fallback_when_no_default_and_omitted(self) -> None:
        """Assert an omitted size with no default falls back to the max.

        If this fails, requests with no explicit size and no configured
        default stop being capped by the maximum (the pinned fix).
        """
        # requested omitted, no default -> falls back to the max (the fix).
        self.assertEqual(self.p._resolve_page_size(None, None, 100), 100)

    def test_explicit_value_clamped_to_max(self) -> None:
        """Assert an explicit size above the max is clamped down to the max.

        If this fails, a client-requested oversized page size bypasses the
        configured ceiling.
        """
        self.assertEqual(self.p._resolve_page_size(500, 25, 100), 100)

    def test_default_used_when_omitted(self) -> None:
        """Assert the configured default is used when the caller omits a size.

        If this fails, an omitted size does not fall back to the configured
        default and instead falls straight to the max or errors.
        """
        self.assertEqual(self.p._resolve_page_size(None, 25, 100), 25)

    def test_unbounded_when_nothing_configured(self) -> None:
        """Assert the resolver returns None when no size, default, or max is set.

        If this fails, the paginator stops being unbounded by default and
        instead applies an unexpected implicit limit.
        """
        self.assertIsNone(self.p._resolve_page_size(None, None, None))

    def test_requested_under_max_is_kept(self) -> None:
        """Assert a requested size under the max is kept as-is.

        If this fails, a valid, in-range requested size gets overridden by
        the default or the max instead of being honored.
        """
        self.assertEqual(self.p._resolve_page_size(10, 25, 100), 10)

    def test_negative_raises(self) -> None:
        """Assert a negative requested size raises a ValueError.

        If this fails, a negative page size is silently accepted instead of
        being rejected by the resolver.

        Raises:
            ValueError: Expected from "_resolve_page_size" and asserted via
                assertRaises.
        """
        with self.assertRaises(ValueError):
            self.p._resolve_page_size(-5, None, 100)


class LimitOffsetCeilingTest(TestCase):
    """Exercise the effective max-limit ceiling on "LimitOffsetGraphqlPagination".

    Covers omitted, explicit, and unconfigured "max_limit" scenarios.
    """

    def test_omitted_limit_falls_back_to_max(self) -> None:
        """Assert an omitted "limit" with no default caps results at the max.

        If this fails, an omitted limit with a configured max returns every
        row instead of capping at "max_limit".
        """
        # No default, max=5: an omitted `limit` must cap at 5, not return all.
        p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=5)
        qs = list(range(50))
        self.assertEqual(len(p.paginate_queryset(qs)), 5)

    def test_explicit_limit_clamped_to_max(self) -> None:
        """Assert an explicit "limit" above the max is clamped down to the max.

        If this fails, a caller-supplied oversized limit bypasses the
        configured ceiling.
        """
        p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=5)
        self.assertEqual(len(p.paginate_queryset(list(range(50)), limit=40)), 5)

    def test_unbounded_when_nothing_configured(self) -> None:
        """Assert pagination returns every row when no default or max is set.

        If this fails, the paginator applies an unexpected implicit limit
        even though neither "default_limit" nor "max_limit" is configured.
        """
        p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
        qs = list(range(50))
        self.assertEqual(len(p.paginate_queryset(qs)), 50)  # unchanged: returns all


class PageCeilingTest(TestCase):
    """Exercise the effective max-page-size ceiling on "PageGraphqlPagination".

    Covers a client-requested oversized page size and an omitted one.
    """

    def test_client_page_size_clamped_to_max(self) -> None:
        """Assert a client-requested page size above the max is clamped down.

        If this fails, a caller-supplied oversized page_size bypasses the
        configured "max_page_size" ceiling.
        """
        p = PageGraphqlPagination(
            page_size=None, page_size_query_param="page_size", max_page_size=5
        )
        result = p.paginate_queryset(list(range(50)), page=1, page_size=40)
        self.assertEqual(len(result), 5)

    def test_omitted_page_size_falls_back_to_max(self) -> None:
        """Assert an omitted page size with no default caps results at the max.

        If this fails, an omitted page size with a configured max returns
        every row instead of capping at "max_page_size".
        """
        p = PageGraphqlPagination(
            page_size=None, page_size_query_param="page_size", max_page_size=5
        )
        self.assertEqual(len(p.paginate_queryset(list(range(50)), page=1)), 5)


class CursorMaxTest(TestCase):
    """Exercise the per-instance max page size on "CursorGraphqlPagination".

    Covers the configured maximum, its clamping behavior, and the default
    floor used when nothing is configured.
    """

    def test_cursor_has_per_instance_max(self) -> None:
        """Assert a per-instance "max_page_size" is stored and reflected in "to_dict".

        If this fails, the configured maximum stops being exposed via the
        instance attribute or the settings snapshot.
        """
        p = CursorGraphqlPagination(max_page_size=7)
        self.assertEqual(p.max_page_size, 7)
        self.assertEqual(p.to_dict()["max_page_size"], 7)

    def test_cursor_clamps_first_to_max(self) -> None:
        """Assert "_page_size" clamps a requested "first" above the max down to it.

        If this fails, a caller-supplied oversized "first" bypasses the
        configured "max_page_size" ceiling.
        """
        p = CursorGraphqlPagination(max_page_size=7)
        self.assertEqual(p._page_size(first=100), 7)

    def test_cursor_floor_when_nothing_configured(self) -> None:
        """Assert "_page_size" falls back to the module default when unconfigured.

        If this fails, cursor pagination with no page_size or max_page_size
        stops falling back to DEFAULT_CURSOR_PAGE_SIZE.
        """
        p = CursorGraphqlPagination(page_size=None, max_page_size=None)
        self.assertEqual(p._page_size(), 20)  # DEFAULT_CURSOR_PAGE_SIZE
