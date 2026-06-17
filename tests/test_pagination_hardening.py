# -*- coding: utf-8 -*-
"""Tests for issue #17 — pagination hardening.

Covers:
(a) page=0 raises GraphQLError explicitly (not assert — survives python -O).
(b) Tampered/garbage cursor raises GraphQLError, not HTTP 500.
(c) COUNT query is conditional: issued only for negative-page navigation.
"""

from __future__ import annotations

import base64

import pytest
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLError, graphql_sync

from django_graphex import (
    CursorGraphqlPagination,
    DjangoGraphQLSchema,
    DjangoListObjectField,
    DjangoListObjectType,
    ObjectType,
    PageGraphqlPagination,
)
from django_graphex.paginations.pagination import PageGraphqlPagination as _PGP

from .models import Author, BasicModel


# ---------------------------------------------------------------------------
# Schema helpers for (b) and (c) integration tests
# ---------------------------------------------------------------------------
class PageHardenType(DjangoListObjectType):
    class Meta:
        model = BasicModel
        pagination = PageGraphqlPagination(
            page_size=5, page_size_query_param="pageSize"
        )


class CursorHardenType(DjangoListObjectType):
    class Meta:
        model = BasicModel
        pagination = CursorGraphqlPagination(ordering="id")


class HardenQuery(ObjectType):
    page_list = DjangoListObjectField(PageHardenType)
    cursor_list = DjangoListObjectField(CursorHardenType)


harden_schema = DjangoGraphQLSchema(query=HardenQuery)


# ---------------------------------------------------------------------------
# (a) page=0 raises GraphQLError — NOT assert
# The fix must use an explicit `raise GraphQLError(...)` so that:
#   1. The raise is NOT compiled out under python -O (assert is stripped).
#   2. The exception type surfaced to callers is GraphQLError.
# ---------------------------------------------------------------------------
class TestPageZeroValidation:
    """(a) page=0 raises GraphQLError explicitly, not via assert."""

    def test_page_zero_in_memory_raises_graphql_error(self):
        """Direct call with in-memory list must raise GraphQLError."""
        p = _PGP(page_size=2, max_page_size=10)
        items = [object(), object()]
        with pytest.raises(GraphQLError):
            p.paginate_queryset(items, page=0)

    def test_page_zero_raises_not_assertion_error(self):
        """Must NOT be an AssertionError — that is stripped under python -O."""
        p = _PGP(page_size=2, max_page_size=10)
        items = [object(), object()]
        try:
            p.paginate_queryset(items, page=0)
            assert False, "Expected an exception"
        except GraphQLError:
            pass  # correct
        except AssertionError:
            pytest.fail(
                "page=0 raised AssertionError — this is stripped under python -O. "
                "Use an explicit 'raise GraphQLError(...)' instead."
            )

    def test_page_zero_message_mentions_non_zero(self):
        """Error message must help the client understand the constraint."""
        p = _PGP(page_size=2, max_page_size=10)
        with pytest.raises(GraphQLError, match="non-zero|zero|page"):
            p.paginate_queryset([object()], page=0)

    def test_page_negative_still_works(self):
        """Negative pages are valid — last-page navigation must not regress."""
        p = _PGP(page_size=1, max_page_size=10)
        result = p.paginate_queryset(["a", "b", "c"], page=-1)
        # Negative page returns some results, not raises.
        assert result is not None


# ---------------------------------------------------------------------------
# (a) db-backed queryset path — page=0 also raises
# ---------------------------------------------------------------------------
class TestPageZeroDatabasePath(TestCase):
    def setUp(self):
        for name in ("x", "y", "z"):
            Author.objects.create(name=name)

    def test_page_zero_with_queryset_raises_graphql_error(self):
        p = _PGP(page_size=2, max_page_size=10)
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), page=0)


# ---------------------------------------------------------------------------
# (b) Tampered cursor raises GraphQLError, not an unhandled 500
# The fix wraps decode_cursor calls in paginate_queryset and get_page_info
# with try/except ValueError -> GraphQLError.
# ---------------------------------------------------------------------------
class TestTamperedCursorQueryset(TestCase):
    """(b) Garbage cursor → GraphQLError, not ValueError/500."""

    def setUp(self):
        for name in ("a", "b", "c"):
            Author.objects.create(name=name)

    def _paginator(self, ordering="name"):
        return CursorGraphqlPagination(ordering=ordering, page_size=10)

    def test_garbage_cursor_paginate_queryset_raises_graphql_error(self):
        """Random base64 garbage must raise GraphQLError."""
        p = self._paginator()
        garbage = base64.urlsafe_b64encode(b"not-a-cursor").decode("ascii")
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), cursor=garbage, first=10)

    def test_non_base64_cursor_raises_graphql_error(self):
        """Non-base64 string must raise GraphQLError, not ValueError."""
        p = self._paginator()
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(
                Author.objects.all(), cursor="!!!not-base64!!!", first=10
            )

    def test_cursor_typed_field_mismatch_int_ordering(self):
        """Cursor containing non-int value on int-ordered field must raise GraphQLError.

        This covers the 'tampered cursor raises uncaught ValueError/ValidationError'
        scenario from the issue: decode_cursor returns a string; qs.filter(**{pk__gt:
        "garbage"}) raises a Django ValidationError (not a ValueError) — both must be
        caught and surfaced as GraphQLError.
        """
        # int-ordered field: Author pk (integer)
        p = CursorGraphqlPagination(ordering="id", page_size=10)
        # Encode a value that looks like a cursor but holds garbage for an int field.
        bad_value_cursor = base64.urlsafe_b64encode(b"cursor:notanint").decode("ascii")
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), cursor=bad_value_cursor, first=10)

    def test_cursor_get_page_info_garbage_cursor_raises_graphql_error(self):
        """get_page_info with garbage cursor must raise GraphQLError."""
        p = self._paginator()
        garbage = base64.urlsafe_b64encode(b"not-a-cursor").decode("ascii")
        with self.assertRaises(GraphQLError):
            p.get_page_info(Author.objects.all(), cursor=garbage, first=10)

    def test_valid_cursor_still_paginates_correctly(self):
        """A valid cursor from a real response must still paginate correctly."""
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        first_page = list(p.paginate_queryset(Author.objects.all(), first=2))
        self.assertEqual(len(first_page), 2)
        boundary = CursorGraphqlPagination.encode_cursor(first_page[-1].name)
        second_page = list(
            p.paginate_queryset(Author.objects.all(), cursor=boundary, first=10)
        )
        self.assertEqual([a.name for a in second_page], ["c"])


# ---------------------------------------------------------------------------
# (c) COUNT is conditional: only issued for negative-page navigation
# For positive pages the COUNT query must NOT be issued.
# ---------------------------------------------------------------------------
class TestConditionalCount(TestCase):
    """(c) paginate_queryset must not issue a COUNT for positive page numbers."""

    def setUp(self):
        for name in ("a", "b", "c", "d", "e"):
            Author.objects.create(name=name)

    def test_positive_page_issues_no_count_query(self):
        """page=1 must not hit the DB with a COUNT query."""
        p = _PGP(page_size=2, max_page_size=10)
        with CaptureQueriesContext(connection) as ctx:
            result = list(p.paginate_queryset(Author.objects.all(), page=1))

        sql_statements = [q["sql"] for q in ctx.captured_queries]
        count_queries = [s for s in sql_statements if "COUNT" in s.upper()]
        assert count_queries == [], (
            f"Expected no COUNT query for positive page, but got: {count_queries}"
        )
        assert len(result) == 2

    def test_negative_page_issues_count_query(self):
        """page=-1 (last-page nav) MUST issue a COUNT query — it needs total rows."""
        p = _PGP(page_size=2, max_page_size=10)
        with CaptureQueriesContext(connection) as ctx:
            result = list(p.paginate_queryset(Author.objects.all(), page=-1))

        sql_statements = [q["sql"] for q in ctx.captured_queries]
        count_queries = [s for s in sql_statements if "COUNT" in s.upper()]
        assert len(count_queries) >= 1, (
            "Expected a COUNT query for negative page navigation, but none was issued."
        )
        assert len(result) > 0

    def test_page_1_total_count_still_resolved_separately(self):
        """totalCount field is resolved by DjangoListObjectType (types.py), not by
        paginate_queryset — so making the count conditional does not break the
        totalCount response field.
        """
        # This uses the full schema so the separate qs.count() in types.py fires.
        for i in range(5):
            BasicModel.objects.create(text=f"T{i:02d}")
        result = graphql_sync(
            harden_schema.graphql_schema,
            "query { pageList { results(page: 1, pageSize: 3) { text } totalCount } }",
        )
        assert result.errors is None, result.errors
        data = result.data["pageList"]
        assert data["totalCount"] == 5
        assert len(data["results"]) == 3
