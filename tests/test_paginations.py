# -*- coding: utf-8 -*-
"""Validation tests for the three pagination strategies.

Pagination ships in "django_graphex.paginations" and is used through
"DjangoListObjectType(Meta.pagination=...)" + "DjangoListObjectField"; the
pagination arguments live on the "results" subfield.

These tests pin down each strategy:

* "LimitOffsetGraphqlPagination" — limit/offset slicing + ordering.
* "PageGraphqlPagination" — page/page_size paging + ordering.
* "CursorGraphqlPagination" — forward keyset cursor paging + "pageInfo".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType

from .models import BasicModel

if TYPE_CHECKING:
    from pytest import MonkeyPatch


# --------------------------------------------------------------------------- #
# Schema                                                                        #
# --------------------------------------------------------------------------- #
class LimitOffsetType(DjangoListObjectType):
    """List type backed by "BasicModel" using limit/offset pagination.

    Feeds the limit/offset validation tests below.
    """

    class Meta:
        """Configuration for "LimitOffsetType".

        Declares the backing model and a limit/offset pagination strategy
        with a default_limit of 5.
        """

        model = BasicModel
        pagination = LimitOffsetGraphqlPagination(default_limit=5)


class PageType(DjangoListObjectType):
    """List type backed by "BasicModel" using page/page_size pagination.

    Feeds the page-based validation tests below.
    """

    class Meta:
        """Configuration for "PageType".

        Declares the backing model and a page-based pagination strategy
        with a page_size of 5 exposed as the "pageSize" argument.
        """

        model = BasicModel
        pagination = PageGraphqlPagination(
            page_size=5, page_size_query_param="pageSize"
        )


class CursorType(DjangoListObjectType):
    """List type backed by "BasicModel" using forward keyset cursor pagination.

    Feeds the cursor pagination and pageInfo validation tests below.
    """

    class Meta:
        """Configuration for "CursorType".

        Declares the backing model and a cursor pagination strategy
        ordered by ascending "id".
        """

        model = BasicModel
        pagination = CursorGraphqlPagination(ordering="id")


class Query(ObjectType):
    """Root query exposing one field per pagination strategy under test.

    Each field wraps the same "BasicModel" data through a different
    pagination strategy so the strategies can be compared directly.
    """

    # Canonical mechanism (documented): pagination args live on `results`.
    limit_offset = DjangoListObjectField(LimitOffsetType)
    page = DjangoListObjectField(PageType)
    cursor = DjangoListObjectField(CursorType)


schema = DjangoGraphQLSchema(query=Query)

# 12 deterministic rows: ids 1..12 map to text "M00".."M11" (insertion order).
ROWS = 12


def _texts(results: list[dict[str, Any]]) -> list[str]:
    """Extract the "text" value from each result row, in order.

    Args:
        results: The list of result rows returned by a query.

    Returns:
        texts: The "text" field values in the same order as "results".
    """
    return [row["text"] for row in results]


def _exec(query: str) -> dict[str, Any]:
    """Execute a query against the shared schema and return its data.

    Args:
        query: The GraphQL query document text.

    Returns:
        data: The execution result's data payload.
    """
    result = graphql_sync(schema.graphql_schema, query)
    assert result.errors is None, result.errors
    return result.data


class _Base(TestCase):
    """Shared fixture base seeding 12 deterministic "BasicModel" rows."""

    def setUp(self) -> None:
        """Create 12 rows with texts "M00".."M11" in insertion order."""
        for i in range(ROWS):
            BasicModel.objects.create(text="M%02d" % i)


# --------------------------------------------------------------------------- #
# LimitOffsetGraphqlPagination — WORKS                                          #
# --------------------------------------------------------------------------- #
class LimitOffsetClassTest(_Base):
    """Tests for "LimitOffsetGraphqlPagination" slicing and ordering.

    Covers explicit limit/offset, the default_limit fallback, an
    offset-only slice near the end, and descending ordering.
    """

    def test_limit_and_offset(self) -> None:
        """Assert an explicit limit/offset pair slices the expected window.

        If this fails, limit/offset pagination would return the wrong
        rows or the wrong total count for an explicit slice request.
        """
        data = _exec(
            "query { limitOffset { results(limit: 3, offset: 2) { text } totalCount } }"
        )["limitOffset"]
        self.assertEqual(data["totalCount"], ROWS)
        self.assertEqual(_texts(data["results"]), ["M02", "M03", "M04"])

    def test_default_limit_applied(self) -> None:
        """Assert omitting limit/offset falls back to the configured default_limit.

        If this fails, a query with no explicit limit would return every
        row instead of respecting the type's configured default_limit=5.
        """
        data = _exec("query { limitOffset { results { text } totalCount } }")[
            "limitOffset"
        ]
        # default_limit=5
        self.assertEqual(len(data["results"]), 5)
        self.assertEqual(_texts(data["results"]), ["M00", "M01", "M02", "M03", "M04"])

    def test_offset_only(self) -> None:
        """Assert an offset past the midpoint returns only the remaining rows.

        If this fails, offset-based slicing would over- or under-return
        rows near the end of the result set.
        """
        data = _exec(
            "query { limitOffset { results(limit: 4, offset: 10) { text } } }"
        )["limitOffset"]
        self.assertEqual(_texts(data["results"]), ["M10", "M11"])

    def test_ordering_descending(self) -> None:
        """Assert a descending ordering argument reverses the row order.

        If this fails, the "ordering" argument would be ignored or
        misapplied on the limit/offset pagination path.
        """
        data = _exec(
            'query { limitOffset { results(limit: 3, ordering: "-id") { text } } }'
        )["limitOffset"]
        self.assertEqual(_texts(data["results"]), ["M11", "M10", "M09"])


# --------------------------------------------------------------------------- #
# PageGraphqlPagination — WORKS                                                 #
# --------------------------------------------------------------------------- #
class PageClassTest(_Base):
    """Tests for "PageGraphqlPagination" page/page_size slicing and ordering.

    Covers the default first page, an explicit page and size, the last
    partial page, and descending ordering.
    """

    def test_first_page_default(self) -> None:
        """Assert the default page (1) with the configured page_size returns rows.

        If this fails, omitting the page argument would not default to
        page 1 with the type's configured page_size=5.
        """
        data = _exec("query { page { results { text } totalCount } }")["page"]
        self.assertEqual(data["totalCount"], ROWS)
        # page_size=5, page 1
        self.assertEqual(_texts(data["results"]), ["M00", "M01", "M02", "M03", "M04"])

    def test_specific_page_and_size(self) -> None:
        """Assert an explicit page and pageSize slice the expected window.

        If this fails, page-based pagination would compute the wrong
        offset for a non-default page number and page size.
        """
        data = _exec(
            "query { page { results(page: 2, pageSize: 4) { text } totalCount } }"
        )["page"]
        self.assertEqual(_texts(data["results"]), ["M04", "M05", "M06", "M07"])

    def test_last_partial_page(self) -> None:
        """Assert the final, partially-filled page returns only its remaining rows.

        If this fails, requesting a page past full pages would either
        error or return the wrong (over/under counted) remainder.
        """
        data = _exec("query { page { results(page: 3, pageSize: 5) { text } } }")[
            "page"
        ]
        self.assertEqual(_texts(data["results"]), ["M10", "M11"])

    def test_ordering(self) -> None:
        """Assert a descending ordering argument reverses the paged row order.

        If this fails, the "ordering" argument would be ignored or
        misapplied on the page-based pagination path.
        """
        data = _exec(
            'query { page { results(page: 1, pageSize: 3, ordering: "-id") { text } } }'
        )["page"]
        self.assertEqual(_texts(data["results"]), ["M11", "M10", "M09"])


# --------------------------------------------------------------------------- #
# CursorGraphqlPagination — WORKS (forward keyset cursor)                        #
# --------------------------------------------------------------------------- #
class CursorClassTest(_Base):
    """Tests for "CursorGraphqlPagination" forward keyset cursor paging.

    Covers the first page, forward paging via a cursor, the last partial
    page, invalid cursors, and the encode/decode round-trip.
    """

    def test_first_page(self) -> None:
        """Assert the first page (no cursor) returns rows in ascending id order.

        If this fails, cursor pagination's default ordering or its first
        page's row selection would be wrong.
        """
        data = _exec("query { cursor { results(first: 5) { text } totalCount } }")[
            "cursor"
        ]
        self.assertEqual(data["totalCount"], ROWS)
        # CursorType orders by ascending id -> M00..M04
        self.assertEqual(_texts(data["results"]), ["M00", "M01", "M02", "M03", "M04"])

    def test_forward_paging_with_cursor(self) -> None:
        """Assert paging forward with an encoded cursor continues without overlap.

        If this fails, a cursor derived from the last row of one page
        would either overlap with or skip rows relative to the next page.
        """
        first = _exec("query { cursor { results(first: 5) { id text } } }")["cursor"][
            "results"
        ]
        boundary_id = first[-1]["id"]
        token = CursorGraphqlPagination.encode_cursor(boundary_id)

        nxt = _exec(
            'query { cursor { results(first: 5, cursor: "%s") { text } } }' % token
        )["cursor"]["results"]
        # No overlap with the first page; continues in order.
        self.assertEqual(_texts(nxt), ["M05", "M06", "M07", "M08", "M09"])

    def test_last_partial_page(self) -> None:
        """Assert a cursor near the end returns only the remaining partial page.

        If this fails, requesting more rows than remain past a cursor
        would either error or over-return rows.

        The boundary cursor is derived from the ACTUAL id of the 9th row (M08)
        rather than a hardcoded "encode_cursor(9)": the auto-increment id of
        the first seeded row is not guaranteed to be 1 (a committed row in an
        earlier transactional test advances the sqlite sequence), so an
        absolute id would point at the wrong boundary under some run orders.
        """
        # The 9th row (M08) is the boundary; page past it -> only M09..M11 remain.
        ninth_id = _exec("query { cursor { results(first: 9) { id } } }")["cursor"][
            "results"
        ][-1]["id"]
        token = CursorGraphqlPagination.encode_cursor(ninth_id)
        data = _exec(
            'query { cursor { results(first: 5, cursor: "%s") { text } } }' % token
        )["cursor"]
        self.assertEqual(_texts(data["results"]), ["M09", "M10", "M11"])

    def test_invalid_cursor_errors(self) -> None:
        """Assert a malformed cursor string produces a GraphQL error.

        If this fails, an invalid cursor token would be silently accepted
        (or crash unhandled) instead of surfacing a clean GraphQL error.
        """
        result = graphql_sync(
            schema.graphql_schema,
            'query { cursor { results(cursor: "not-a-valid-cursor") { text } } }',
        )
        self.assertIsNotNone(result.errors)

    def test_encode_decode_roundtrip(self) -> None:
        """Assert encoding then decoding a cursor value round-trips to its string form.

        If this fails, the cursor encoding scheme would not be
        symmetric, corrupting pagination state across requests.
        """
        self.assertEqual(
            CursorGraphqlPagination.decode_cursor(
                CursorGraphqlPagination.encode_cursor(42)
            ),
            "42",
        )


# --------------------------------------------------------------------------- #
# CursorGraphqlPagination — pageInfo                                            #
# --------------------------------------------------------------------------- #
class CursorPageInfoTest(_Base):
    """Tests for the "pageInfo" field exposed by cursor pagination.

    Covers field presence/absence across strategies, endCursor-driven
    paging, hasNextPage/hasPreviousPage, and the empty-page edge case.
    """

    def _cursor(self, value: int) -> str:
        """Encode an id value into the pagination's opaque cursor string.

        Args:
            value: The row id to encode as a cursor.

        Returns:
            cursor: The encoded cursor token.
        """
        return CursorGraphqlPagination.encode_cursor(value)

    def _nth_row_id(self, n: int) -> int:
        """Return the actual id of the nth (1-indexed) seeded row.

        The first seeded row's auto-increment id is not guaranteed to be 1 — a
        committed row in an earlier transactional test advances the sqlite
        sequence — so cursor boundaries are derived from real ids instead of
        assuming ids run 1..12.

        Args:
            n: The 1-indexed row position in ascending id order.

        Returns:
            id: The primary key of the nth row.
        """
        return _exec("query { cursor { results(first: %d) { id } } }" % n)["cursor"][
            "results"
        ][-1]["id"]

    def test_cursor_exposes_pageinfo(self) -> None:
        """Assert the cursor list type declares a "pageInfo" field.

        If this fails, clients using cursor pagination would have no way
        to query hasNextPage/hasPreviousPage/cursors metadata.
        """
        # AC1: the cursor list type has a `pageInfo` field.
        fields = schema.graphql_schema.type_map["CursorType"].fields
        self.assertIn("pageInfo", fields)

    def test_limitoffset_and_page_have_no_pageinfo(self) -> None:
        """Assert limit/offset and page list types do not expose "pageInfo".

        If this fails, non-cursor pagination strategies would advertise
        a "pageInfo" field they cannot meaningfully compute.
        """
        # AC1: LimitOffset / Page list types do NOT expose `pageInfo`.
        for type_name in ("LimitOffsetType", "PageType"):
            fields = schema.graphql_schema.type_map[type_name].fields
            self.assertNotIn("pageInfo", fields)

    def test_pageinfo_endcursor_drives_next_page(self) -> None:
        """Assert page N's endCursor drives a contiguous, non-overlapping page N+1.

        If this fails, chaining requests via the reported "endCursor"
        would either skip or repeat rows across pages.
        """
        # AC2: endCursor of page N -> contiguous page N+1, no overlap.
        page1 = _exec(
            "query { cursor { results(first: 5) { text } pageInfo(first: 5) "
            "{ endCursor } } }"
        )["cursor"]
        self.assertEqual(_texts(page1["results"]), ["M00", "M01", "M02", "M03", "M04"])
        end = page1["pageInfo"]["endCursor"]

        page2 = _exec(
            'query { cursor { results(first: 5, cursor: "%s") { text } } }' % end
        )["cursor"]
        self.assertEqual(_texts(page2["results"]), ["M05", "M06", "M07", "M08", "M09"])

    def test_hasnextpage_true_then_false(self) -> None:
        """Assert hasNextPage is true mid-stream and false on the final page.

        If this fails, clients could not reliably detect the end of a
        cursor-paginated stream.
        """
        # AC3: true on a non-final page, false on the last one.
        first = _exec("query { cursor { pageInfo(first: 5) { hasNextPage } } }")[
            "cursor"
        ]["pageInfo"]
        self.assertTrue(first["hasNextPage"])

        last = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") { hasNextPage } } }'
            % self._cursor(self._nth_row_id(10))
        )["cursor"]["pageInfo"]
        self.assertFalse(last["hasNextPage"])

    def test_haspreviouspage(self) -> None:
        """Assert hasPreviousPage is false at the start and true once paged forward.

        If this fails, clients could not reliably detect whether they
        are at the beginning of a cursor-paginated stream, including the
        spurious-cursor-at-position-zero edge case.
        """
        # AC4: false on the first page (even with a spurious cursor), true later.
        first = _exec("query { cursor { pageInfo(first: 5) { hasPreviousPage } } }")[
            "cursor"
        ]["pageInfo"]
        self.assertFalse(first["hasPreviousPage"])

        spurious = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") { hasPreviousPage } } }'
            % self._cursor(0)
        )["cursor"]["pageInfo"]
        self.assertFalse(spurious["hasPreviousPage"])

        later = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") { hasPreviousPage } } }'
            % self._cursor(self._nth_row_id(5))
        )["cursor"]["pageInfo"]
        self.assertTrue(later["hasPreviousPage"])

    def test_pageinfo_empty_page(self) -> None:
        """Assert an empty page (cursor past the end) yields null cursors.

        If this fails, paging past the end of the result set would
        return stale or non-null cursor values instead of nulls with
        hasNextPage false.
        """
        # AC5: an empty page yields null cursors and hasNextPage false.
        info = _exec(
            'query { cursor { pageInfo(first: 5, cursor: "%s") '
            "{ hasNextPage hasPreviousPage startCursor endCursor } } }"
            % self._cursor(9999)
        )["cursor"]["pageInfo"]
        self.assertEqual(
            info,
            {
                "hasNextPage": False,
                "hasPreviousPage": False,
                "startCursor": None,
                "endCursor": None,
            },
        )


def test_filter_paginate_list_field_without_pagination_does_not_raise(
    monkeypatch: MonkeyPatch,
) -> None:
    """Assert a None DEFAULT_PAGINATION_CLASS with no explicit pagination is safe.

    With DEFAULT_PAGINATION_CLASS=None and no "pagination" Meta option,
    the field must not call None() — it simply ends up with no
    pagination.

    Args:
        monkeypatch: Used to patch DEFAULT_PAGINATION_CLASS directly on
            the settings instance "django_graphex.fields" already imported,
            since "override_settings" would rebind a new global this
            module-level reference never observes.
    """
    import django_graphex.fields as fields_mod
    from django_graphex.fields import DjangoFilterPaginateListField

    from .schema import UserType

    # The field reads the settings instance imported into django_graphex.fields.
    # override_settings rebinds a *new* global that this reference never sees, so
    # patch DEFAULT_PAGINATION_CLASS directly on the instance the field uses.
    monkeypatch.setattr(
        fields_mod.graphql_api_settings,
        "DEFAULT_PAGINATION_CLASS",
        None,
        raising=False,
    )
    field = DjangoFilterPaginateListField(UserType)
    assert getattr(field, "pagination", None) is None
