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

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import CursorGraphqlPagination, PageGraphqlPagination
from django_graphex.paginations.pagination import PageGraphqlPagination as _PGP
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType

from .models import Author, BasicModel


# ---------------------------------------------------------------------------
# Schema helpers for (b) and (c) integration tests
# ---------------------------------------------------------------------------
class PageHardenType(DjangoListObjectType):
    """ "BasicModel" list type using a custom page-size paginator, for hardening tests.

    Backs the "pageList" root field used by the conditional-COUNT tests.
    """

    class Meta:
        """Bind the list type to "BasicModel" with a page-size 5 paginator.

        The "pageSize" query param name is used on the wire.
        """

        model = BasicModel
        pagination = PageGraphqlPagination(
            page_size=5, page_size_query_param="pageSize"
        )


class CursorHardenType(DjangoListObjectType):
    """ "BasicModel" list type using cursor-based pagination, for tampered-cursor tests.

    Backs the "cursorList" root field.
    """

    class Meta:
        """Bind the list type to "BasicModel" with cursor pagination ordered by "id".

        No other options are needed for these hardening tests.
        """

        model = BasicModel
        pagination = CursorGraphqlPagination(ordering="id")


class HardenQuery(ObjectType):
    """Root query exposing both the page-based and cursor-based hardening lists.

    The only entry point for the schema built in this module.
    """

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
    """(a) page=0 raises GraphQLError explicitly, not via assert.

    Covers the in-memory pagination path only; see "TestPageZeroDatabasePath"
    for the queryset-backed path.
    """

    def test_page_zero_in_memory_raises_graphql_error(self) -> None:
        """A direct call on an in-memory list with page=0 raises "GraphQLError".

        This test breaks if page=0 stops being rejected explicitly for
        in-memory pagination.
        """
        p = _PGP(page_size=2, max_page_size=10)
        items = [object(), object()]
        with pytest.raises(GraphQLError):
            p.paginate_queryset(items, page=0)

    def test_page_zero_raises_not_assertion_error(self) -> None:
        """page=0 raises "GraphQLError", never an "AssertionError".

        This test breaks if the page=0 guard reverts to a bare "assert",
        which is silently stripped under "python -O" and would let an
        invalid page slip through uncaught.
        """
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

    def test_page_zero_message_mentions_non_zero(self) -> None:
        """The page=0 error message mentions the page constraint, to help API clients.

        This test breaks if the error message stops referencing the
        zero/non-zero page constraint.
        """
        p = _PGP(page_size=2, max_page_size=10)
        with pytest.raises(GraphQLError, match="non-zero|zero|page"):
            p.paginate_queryset([object()], page=0)

    def test_page_negative_still_works(self) -> None:
        """Negative pages (last-page navigation) still succeed without raising.

        This test breaks if the page=0 validation accidentally starts
        rejecting negative page numbers too.
        """
        p = _PGP(page_size=1, max_page_size=10)
        result = p.paginate_queryset(["a", "b", "c"], page=-1)
        # Negative page returns some results, not raises.
        assert result is not None


# ---------------------------------------------------------------------------
# (a) db-backed queryset path — page=0 also raises
# ---------------------------------------------------------------------------
class TestPageZeroDatabasePath(TestCase):
    """(a) page=0 also raises "GraphQLError" on the real queryset-backed path.

    Complements "TestPageZeroValidation", which covers the in-memory path.
    """

    def setUp(self) -> None:
        """Create three throwaway authors for the database-path page=0 test.

        Shared as fixture data by the test in this class.
        """
        for name in ("x", "y", "z"):
            Author.objects.create(name=name)

    def test_page_zero_with_queryset_raises_graphql_error(self) -> None:
        """page=0 against a real Django queryset raises "GraphQLError".

        This test breaks if the queryset-backed pagination path stops
        sharing the same page=0 validation as the in-memory path.
        """
        p = _PGP(page_size=2, max_page_size=10)
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), page=0)


# ---------------------------------------------------------------------------
# (b) Tampered cursor raises GraphQLError, not an unhandled 500
# The fix wraps decode_cursor calls in paginate_queryset and get_page_info
# with try/except ValueError -> GraphQLError.
# ---------------------------------------------------------------------------
class TestTamperedCursorQueryset(TestCase):
    """(b) Garbage cursor causes GraphQLError, not ValueError/500.

    Covers "paginate_queryset" and "get_page_info" across several kinds of
    malformed cursors.
    """

    def setUp(self) -> None:
        """Create three throwaway authors for the tampered-cursor tests.

        Shared as fixture data by every test in this class.
        """
        for name in ("a", "b", "c"):
            Author.objects.create(name=name)

    def _paginator(self, ordering: str = "name") -> CursorGraphqlPagination:
        """Build a cursor paginator with a page size of 10, for these tests.

        Args:
            ordering: The ordering field name to construct the paginator with.

        Returns:
            A fresh "CursorGraphqlPagination" instance.
        """
        return CursorGraphqlPagination(ordering=ordering, page_size=10)

    def test_garbage_cursor_paginate_queryset_raises_graphql_error(self) -> None:
        """Random base64 garbage as a cursor raises "GraphQLError".

        This test breaks if decoding an undecodable cursor stops being
        caught and surfaced as "GraphQLError".
        """
        p = self._paginator()
        garbage = base64.urlsafe_b64encode(b"not-a-cursor").decode("ascii")
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), cursor=garbage, first=10)

    def test_non_base64_cursor_raises_graphql_error(self) -> None:
        """A non-base64 cursor string raises "GraphQLError", not a raw "ValueError".

        This test breaks if a malformed, non-base64 cursor stops being
        caught and surfaced as "GraphQLError".
        """
        p = self._paginator()
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(
                Author.objects.all(), cursor="!!!not-base64!!!", first=10
            )

    def test_cursor_typed_field_mismatch_int_ordering(self) -> None:
        """A cursor holding a non-int value for an int-ordered field raises "GraphQLError".

        This covers the "tampered cursor raises uncaught
        ValueError/ValidationError" scenario from the issue: decode_cursor
        returns a string; "qs.filter(**{pk__gt: 'garbage'})" raises a Django
        "ValidationError" (not a "ValueError") — both must be caught and
        surfaced as "GraphQLError". This test breaks if either exception type
        stops being caught.
        """
        # int-ordered field: Author pk (integer)
        p = CursorGraphqlPagination(ordering="id", page_size=10)
        # Encode a value that looks like a cursor but holds garbage for an int field.
        bad_value_cursor = base64.urlsafe_b64encode(b"cursor:notanint").decode("ascii")
        with self.assertRaises(GraphQLError):
            p.paginate_queryset(Author.objects.all(), cursor=bad_value_cursor, first=10)

    def test_cursor_get_page_info_garbage_cursor_raises_graphql_error(self) -> None:
        """ "get_page_info" with a garbage cursor raises "GraphQLError".

        This test breaks if "get_page_info" stops sharing the same
        cursor-decoding error handling as "paginate_queryset".
        """
        p = self._paginator()
        garbage = base64.urlsafe_b64encode(b"not-a-cursor").decode("ascii")
        with self.assertRaises(GraphQLError):
            p.get_page_info(Author.objects.all(), cursor=garbage, first=10)

    def test_valid_cursor_still_paginates_correctly(self) -> None:
        """A valid cursor from a real prior response still paginates correctly.

        This test breaks if the hardening around invalid cursors regresses
        the happy path for a genuinely valid, previously-issued cursor.
        """
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
    """(c) "paginate_queryset" must not issue a COUNT for positive page numbers.

    Also confirms "totalCount" still resolves correctly under this change.
    """

    def setUp(self) -> None:
        """Create five throwaway authors for the conditional-COUNT tests.

        Shared as fixture data by every test in this class.
        """
        for name in ("a", "b", "c", "d", "e"):
            Author.objects.create(name=name)

    def test_positive_page_issues_no_count_query(self) -> None:
        """page=1 does not issue a COUNT query against the database.

        This test breaks if positive-page pagination starts issuing an
        unconditional COUNT query again.
        """
        p = _PGP(page_size=2, max_page_size=10)
        with CaptureQueriesContext(connection) as ctx:
            result = list(p.paginate_queryset(Author.objects.all(), page=1))

        sql_statements = [q["sql"] for q in ctx.captured_queries]
        count_queries = [s for s in sql_statements if "COUNT" in s.upper()]
        assert count_queries == [], (
            f"Expected no COUNT query for positive page, but got: {count_queries}"
        )
        assert len(result) == 2

    def test_negative_page_issues_count_query(self) -> None:
        """page=-1 (last-page navigation) issues a COUNT query since it needs the total row count.

        This test breaks if negative-page navigation stops issuing the COUNT
        query it needs to compute the last page.
        """
        p = _PGP(page_size=2, max_page_size=10)
        with CaptureQueriesContext(connection) as ctx:
            result = list(p.paginate_queryset(Author.objects.all(), page=-1))

        sql_statements = [q["sql"] for q in ctx.captured_queries]
        count_queries = [s for s in sql_statements if "COUNT" in s.upper()]
        assert len(count_queries) >= 1, (
            "Expected a COUNT query for negative page navigation, but none was issued."
        )
        assert len(result) > 0

    def test_page_1_total_count_still_resolved_separately(self) -> None:
        """The "totalCount" GraphQL field still resolves correctly under the conditional-COUNT change.

        "totalCount" is resolved by "DjangoListObjectType" (types.py), not by
        "paginate_queryset", so making the count conditional there must not
        break the "totalCount" response field. This test breaks if that
        separation regresses.
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
