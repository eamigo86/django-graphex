# -*- coding: utf-8 -*-
"""Tests — ordering parameters accept camelCase (GraphQL-consistency).

Client-supplied ordering VALUES historically only accepted snake_case model
attnames: "ordering: "created_at"" worked, but "ordering: "createdAt"" (the
spelling every field NAME uses on the wire) errored on the DB path and silently
degraded on the in-memory (prefetch-cache) path.

This change normalizes every client ordering term with "to_snake_case" at one
canonical point (preserving the "-"/"+" direction prefix) so:

  * "ordering: "createdAt"" behaves EXACTLY like "ordering: "created_at"" on
    BOTH the DB path and the in-memory path (parity), including the
    window-prefetch optimization (which must NOT decline for camelCase);
  * snake_case keeps working unchanged;
  * an invalid camelCase field ("nonexistentField" -> "nonexistent_field")
    still raises the same "GraphQLError";
  * relation-spanning rejection is unchanged;
  * "CursorGraphqlPagination" (server-configured ordering) is unaffected.

The test model attnames used here:
  * "Post.author" is an FK whose ATTNAME is "author_id"; the camelCase wire
    spelling is "authorId" -> "to_snake_case" -> "author_id" (a real
    concrete attname). This gives a genuine multi-underscore round-trip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLError

if TYPE_CHECKING:
    from django_graphex.fields import DjangoNestedListObjectField

from django_graphex.paginations.pagination import (
    LimitOffsetGraphqlPagination as _LOF,
)
from django_graphex.paginations.pagination import (
    PageGraphqlPagination as _PGP,
)
from django_graphex.paginations.pagination import (
    _inmemory_order,
    _validate_ordering_terms,
)

from .models import Author, Post


def _lo(default_limit: int = 50, max_limit: int = 50, ordering: str = "") -> _LOF:
    """Build a "LimitOffsetGraphqlPagination" with concise keyword defaults.

    Args:
        default_limit: The paginator's default page limit.
        max_limit: The paginator's maximum allowed limit.
        ordering: The server-configured default ordering string.

    Returns:
        paginator: The constructed limit/offset paginator instance.
    """
    return _LOF(default_limit=default_limit, max_limit=max_limit, ordering=ordering)


def _pg(page_size: int = 50, max_page_size: int = 50, ordering: str = "") -> _PGP:
    """Build a "PageGraphqlPagination" with concise keyword defaults.

    Args:
        page_size: The paginator's default page size.
        max_page_size: The paginator's maximum allowed page size.
        ordering: The server-configured default ordering string.

    Returns:
        paginator: The constructed page paginator instance.
    """
    return _PGP(page_size=page_size, max_page_size=max_page_size, ordering=ordering)


# ---------------------------------------------------------------------------
# _validate_ordering_terms — camelCase is normalized, then validated
# ---------------------------------------------------------------------------


class TestValidateOrderingCamelCase(TestCase):
    """The validator must accept camelCase spellings of concrete attnames.

    Covers accepted camelCase forms and terms that must still be rejected.
    """

    def test_camelcase_attname_accepted(self) -> None:
        """Assert "authorId" normalizes to "author_id" and passes the allowlist.

        If this fails, camelCase ordering terms are rejected even though the
        normalized snake_case attname is a valid, concrete model field.
        """
        _validate_ordering_terms(Post, "authorId")  # must not raise

    def test_camelcase_desc_prefix_accepted(self) -> None:
        """Assert a leading "-" is preserved while the term is normalized.

        If this fails, the descending-order prefix is lost or breaks
        normalization for a camelCase ordering term.
        """
        _validate_ordering_terms(Post, "-authorId")  # must not raise

    def test_camelcase_list_accepted(self) -> None:
        """Assert a list of camelCase terms is normalized and validated per-item.

        If this fails, only the string form of ordering is normalized and
        the list form regresses to rejecting valid camelCase terms.
        """
        _validate_ordering_terms(Post, ["authorId", "-id"])  # must not raise

    def test_invalid_camelcase_still_rejected(self) -> None:
        """Assert "nonexistentField" still raises after normalizing to snake_case.

        If this fails, normalization masks an invalid field name instead of
        still rejecting it as "nonexistent_field".

        Raises:
            GraphQLError: Expected from "_validate_ordering_terms" and
                asserted via pytest.raises.
        """
        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Post, "nonexistentField")

    def test_camelcase_relation_spanning_still_rejected(self) -> None:
        """Assert a camelCase relation-spanning term is still rejected.

        If this fails, normalizing camelCase before validation accidentally
        allows relation-spanning ordering that should stay disallowed.

        Raises:
            GraphQLError: Expected from "_validate_ordering_terms" and
                asserted via pytest.raises.
        """
        with pytest.raises(GraphQLError):
            _validate_ordering_terms(Post, "authorId__name")


# ---------------------------------------------------------------------------
# DB path — LimitOffset + Page paginators order correctly by camelCase
# ---------------------------------------------------------------------------


class TestDbPathCamelCaseOrdering(TestCase):
    """camelCase ordering must sort DB rows identically to snake_case.

    Covers "LimitOffsetGraphqlPagination" and "PageGraphqlPagination" in
    both ascending and descending directions.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed two authors and four posts interleaved by author.

        Interleaving makes ordering by "author_id" observable rather than
        accidentally matching insertion order.
        """
        cls.a1 = Author.objects.create(name="alice")
        cls.a2 = Author.objects.create(name="bob")
        # Interleave authors so ordering by author_id is observable.
        Post.objects.create(title="p1", author=cls.a2)
        Post.objects.create(title="p2", author=cls.a1)
        Post.objects.create(title="p3", author=cls.a2)
        Post.objects.create(title="p4", author=cls.a1)

    def _ids(self, result: list[Post]) -> list[int]:
        """Extract the "author_id" attname from each post in order.

        Args:
            result: The ordered posts to read author ids from.

        Returns:
            ids: The "author_id" values in the same order as "result".
        """
        return [p.author_id for p in result]

    def test_limitoffset_camelcase_asc_matches_snake(self) -> None:
        """Assert ascending camelCase ordering matches ascending snake_case ordering.

        If this fails, "ordering="authorId"" and "ordering="author_id""
        diverge on the limit/offset DB path.
        """
        camel = list(_lo().paginate_queryset(Post.objects.all(), ordering="authorId"))
        snake = list(_lo().paginate_queryset(Post.objects.all(), ordering="author_id"))
        assert self._ids(camel) == self._ids(snake)
        assert self._ids(camel) == sorted(self._ids(camel))

    def test_limitoffset_camelcase_desc_matches_snake(self) -> None:
        """Assert descending camelCase ordering matches descending snake_case ordering.

        If this fails, the "-authorId" direction prefix is lost or mismatches
        "-author_id" on the limit/offset DB path.
        """
        camel = list(_lo().paginate_queryset(Post.objects.all(), ordering="-authorId"))
        snake = list(_lo().paginate_queryset(Post.objects.all(), ordering="-author_id"))
        assert self._ids(camel) == self._ids(snake)
        assert self._ids(camel) == sorted(self._ids(camel), reverse=True)

    def test_page_camelcase_asc_matches_snake(self) -> None:
        """Assert ascending camelCase ordering matches snake_case on page pagination.

        If this fails, "PageGraphqlPagination" diverges between "authorId"
        and "author_id" ordering.
        """
        camel = list(
            _pg().paginate_queryset(Post.objects.all(), page=1, ordering="authorId")
        )
        snake = list(
            _pg().paginate_queryset(Post.objects.all(), page=1, ordering="author_id")
        )
        assert self._ids(camel) == self._ids(snake)
        assert self._ids(camel) == sorted(self._ids(camel))

    def test_page_camelcase_desc_matches_snake(self) -> None:
        """Assert descending camelCase ordering matches snake_case on page pagination.

        If this fails, "PageGraphqlPagination" diverges between "-authorId"
        and "-author_id" ordering.
        """
        camel = list(
            _pg().paginate_queryset(Post.objects.all(), page=1, ordering="-authorId")
        )
        snake = list(
            _pg().paginate_queryset(Post.objects.all(), page=1, ordering="-author_id")
        )
        assert self._ids(camel) == self._ids(snake)


# ---------------------------------------------------------------------------
# In-memory path — camelCase parity with snake AND with the DB path
# ---------------------------------------------------------------------------


class TestInMemoryPathCamelCaseParity(TestCase):
    """The in-memory (prefetch-cache list) path must NOT silently degrade.

    Before normalization, "_inmemory_order" did "getattr(obj, "authorId")"
    which is missing on the model instance -> every key is None -> ordering
    is a no-op (silent degrade). After normalization the in-memory result
    must equal both the snake in-memory result AND the DB-path result.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed two authors and four posts interleaved by author.

        Interleaving makes ordering by "author_id" observable rather than
        accidentally matching insertion order.
        """
        cls.a1 = Author.objects.create(name="alice")
        cls.a2 = Author.objects.create(name="bob")
        Post.objects.create(title="p1", author=cls.a2)
        Post.objects.create(title="p2", author=cls.a1)
        Post.objects.create(title="p3", author=cls.a2)
        Post.objects.create(title="p4", author=cls.a1)

    def _ids(self, result: list[Post]) -> list[int]:
        """Extract the "author_id" attname from each post in order.

        Args:
            result: The ordered posts to read author ids from.

        Returns:
            ids: The "author_id" values in the same order as "result".
        """
        return [p.author_id for p in result]

    def test_inmemory_camelcase_matches_snake(self) -> None:
        """Assert in-memory camelCase ordering matches in-memory snake_case ordering.

        If this fails, "_inmemory_order" degrades silently for a camelCase
        term instead of normalizing it to the equivalent snake_case attname.
        """
        items = list(Post.objects.all())
        camel = _inmemory_order(items, "authorId")
        snake = _inmemory_order(items, "author_id")
        assert self._ids(camel) == self._ids(snake)
        assert self._ids(camel) == sorted(self._ids(camel))

    def test_inmemory_camelcase_desc_matches_snake(self) -> None:
        """Assert descending in-memory camelCase ordering matches snake_case.

        If this fails, the "-authorId" direction prefix is lost or mismatches
        "-author_id" on the in-memory path.
        """
        items = list(Post.objects.all())
        camel = _inmemory_order(items, "-authorId")
        snake = _inmemory_order(items, "-author_id")
        assert self._ids(camel) == self._ids(snake)
        assert self._ids(camel) == sorted(self._ids(camel), reverse=True)

    def test_inmemory_camelcase_matches_db_path(self) -> None:
        """Assert in-memory ordering equals DB-path ordering for the same input.

        If this fails, the in-memory (prefetch-cache) camelCase ordering
        diverges from what the DB path would produce for identical data.
        """
        items = list(Post.objects.all())
        inmem = self._ids(_inmemory_order(items, "authorId"))
        db = self._ids(
            list(_lo().paginate_queryset(Post.objects.all(), ordering="authorId"))
        )
        assert inmem == db

    def test_limitoffset_inmemory_list_camelcase_matches_db(self) -> None:
        """Assert "paginate_queryset" over a plain list matches its DB-path result.

        If this fails, "paginate_queryset" applied to a prefetch-cache list
        (rather than a queryset) diverges from the DB path for camelCase
        ordering.
        """
        items = list(Post.objects.all())
        inmem = self._ids(_lo().paginate_queryset(items, ordering="authorId"))
        db = self._ids(
            list(_lo().paginate_queryset(Post.objects.all(), ordering="authorId"))
        )
        assert inmem == db


# ---------------------------------------------------------------------------
# Window-prefetch optimization must NOT decline for camelCase
# ---------------------------------------------------------------------------


class TestWindowPrefetchCamelCase(TestCase):
    """build_window_prefetch must still optimize a camelCase ordering term.

    Covers both the opt-in decision (does it return a Prefetch at all) and
    the emitted SQL (does it still use the window-function strategy).
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed one author and five posts to exercise window prefetching.

        Five rows are enough to make a window-sliced prefetch observable
        against the full unsliced related set.
        """
        cls.author = Author.objects.create(name="wc")
        for i in range(5):
            Post.objects.create(title=f"p{i}", author=cls.author)

    def _inst(self) -> DjangoNestedListObjectField:
        """Build the nested list field instance shared by this class's tests.

        Returns:
            field: A "DjangoNestedListObjectField" for "Author.posts",
                built via the shared test helper.
        """
        from tests.test_optimizer_phase_c import _make_test_nested_field

        return _make_test_nested_field()

    @staticmethod
    def _row_type(inst: DjangoNestedListObjectField) -> Any:
        """Return the compiled row type the window pre-check reads its allowlist from.

        Args:
            inst: The nested list field under test.

        Returns:
            The compiled row "GraphQLObjectType" for the nested list.
        """
        from tests.test_optimizer_phase_c import _row_gql_type

        return _row_gql_type(inst)

    def test_window_prefetch_optimizes_camelcase_term(self) -> None:
        """Assert a camelCase ordering term does not make the window opt decline.

        If this fails, "build_window_prefetch" would fall back to
        unoptimized prefetching whenever the ordering term is spelled in
        camelCase instead of snake_case.
        """
        from django.db.models import Prefetch

        inst = self._inst()
        related_field = Author._meta.get_field("posts")

        result = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 3, ["authorId"]),
            related_field=related_field,
            sub_selection=None,
            fragments={},
            child_gql_type=self._row_type(inst),
        )
        assert result is not None, (
            "window-prefetch must optimize a camelCase ordering term, not decline"
        )
        assert isinstance(result, Prefetch)

    def test_window_prefetch_camelcase_sql_uses_row_number(self) -> None:
        """Assert the camelCase window queryset still emits ROW_NUMBER() SQL.

        If this fails, the window-function optimization strategy would be
        silently bypassed for camelCase ordering terms even though a
        Prefetch object is still returned.
        """
        inst = self._inst()
        related_field = Author._meta.get_field("posts")
        pf = inst.build_window_prefetch(
            lookup="posts",
            filter_value=None,
            slice_tuple=(0, 3, ["authorId"]),
            related_field=related_field,
            sub_selection=None,
            fragments={},
            child_gql_type=self._row_type(inst),
        )
        assert pf is not None
        with CaptureQueriesContext(connection) as ctx:
            list(pf.queryset)
        sql = " ".join(q["sql"] for q in ctx.captured_queries).upper()
        assert "ROW_NUMBER()" in sql


# ---------------------------------------------------------------------------
# CursorGraphqlPagination is unaffected (server-configured ordering)
# ---------------------------------------------------------------------------


class TestCursorPaginationUnaffected(TestCase):
    """Cursor pagination ordering is server-configured; nothing changed here.

    Sanity-checks that cursor pagination's snake_case-only ordering
    configuration is untouched by the camelCase normalization work.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed four authors named "a0".."a3" for cursor pagination tests.

        Four rows give the paginator enough rows to slice a two-item page.
        """
        for i in range(4):
            Author.objects.create(name=f"a{i}")

    def test_cursor_ordering_field_snake_config_unchanged(self) -> None:
        """Assert a snake_case server-configured ordering field is unchanged.

        If this fails, the camelCase normalization work would have
        regressed cursor pagination's existing snake_case ordering
        configuration parsing.
        """
        from django_graphex.paginations.pagination import CursorGraphqlPagination

        p = CursorGraphqlPagination(ordering="name")
        term, field, descending = p._ordering_field()
        assert term == "name"
        assert field == "name"
        assert descending is False

    def test_cursor_paginate_by_name_unchanged(self) -> None:
        """Assert cursor pagination still paginates correctly by "name".

        If this fails, cursor pagination's actual query behavior would
        have regressed alongside the camelCase ordering normalization work.
        """
        from django_graphex.paginations.pagination import CursorGraphqlPagination

        p = CursorGraphqlPagination(ordering="name", page_size=2, max_page_size=2)
        rows = list(p.paginate_queryset(Author.objects.all(), first=2))
        assert [a.name for a in rows] == ["a0", "a1"]
