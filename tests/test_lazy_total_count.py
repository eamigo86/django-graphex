# -*- coding: utf-8 -*-
"""Lazy "totalCount" — the COUNT SQL is issued only when "totalCount" is selected.

"DjangoListObjectField.list_resolver" used to call "qs.count()" unconditionally
before building the "DjangoListObjectBase" (one COUNT query + ~1.4ms per request)
even when the client never selected "totalCount". These tests pin the lazy
contract:

* No "totalCount" in the selection -> NO COUNT SQL issued.
* "totalCount" selected -> COUNT issued exactly once, value correct.
* "totalCount" selected twice / aliased -> still one COUNT (memoized supplier).
* Results consumed before "totalCount" -> the deferred "count()" still returns
  the correct value (queryset ".count()" clones, so it is safe post-iteration).
* Nested list fields (prefetched + filtered DB paths) stay correct.
* Pagination "pageInfo" paths are unaffected.
* Filtered + "totalCount" returns the correct matched value.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.base_types import DjangoListObjectBase
from django_graphex.core import ObjectType
from django_graphex.fields import (
    DjangoListObjectField,
    DjangoNestedListObjectField,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post

R = Registry()


class PostType(DjangoObjectType):
    """GraphQL object type exposing "Post" with title filtering.

    Used by "PostListType" and the ad-hoc test "Query" below to exercise the
    lazy "totalCount" contract.
    """

    class Meta:
        """Bind "PostType" to the "Post" model on the isolated test registry.

        "filter_fields" enables the "icontains"/"exact" lookups exercised by
        the filtered-count scenarios.
        """

        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class PostListType(DjangoListObjectType):
    """GraphQL list type exposing filtered, paginated "Post" collections.

    Backs the "posts" root field whose "totalCount" laziness is under test.
    """

    class Meta:
        """Bind "PostListType" to the "Post" model on the isolated test registry.

        "filter_fields" enables the "icontains"/"exact" lookups exercised by
        the filtered-count scenarios.
        """

        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class Query(ObjectType):
    """Root query exposing the "posts" list field under test.

    This is the minimal schema surface needed to drive "totalCount" laziness
    scenarios through "graphql_sync".
    """

    posts = DjangoListObjectField(PostListType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))


def _count_sql(captured: list[dict[str, str]]) -> int:
    """Return how many captured queries are COUNT statements.

    Args:
        captured: Query log entries as recorded by "CaptureQueriesContext",
            each exposing a "sql" key.

    Returns:
        count: The number of captured queries whose SQL text contains "COUNT(".
    """
    return sum(1 for q in captured if "COUNT(" in q["sql"].upper())


class LazyTotalCountTest(TestCase):
    """Scenarios 1, 2, 3 and 7: when and how often the COUNT query fires.

    Each test drives the schema through "graphql_sync" and inspects the
    captured SQL to pin exactly how many COUNT statements were issued.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed one author with six posts, one of which matches "needle".

        Shared across every test in this class via Django's transactional
        "setUpTestData" fixture.
        """
        cls.author = Author.objects.create(name="A")
        for i in range(5):
            Post.objects.create(title=f"p{i}", author=cls.author)
        Post.objects.create(title="needle", author=cls.author)

    # -- scenario 1: no totalCount -> no COUNT SQL -------------------------------
    def test_no_total_count_issues_no_count_sql(self) -> None:
        """Omitting "totalCount" from the selection must issue zero COUNT queries.

        This test breaks if list resolution starts eagerly counting the
        queryset regardless of what the client actually selected.
        """
        with CaptureQueriesContext(connection) as ctx:
            result = graphql_sync(
                schema.graphql_schema, "{ posts { results { title } } }"
            )
        assert result.errors is None, result.errors
        assert len(result.data["posts"]["results"]) == 6
        assert _count_sql(ctx.captured_queries) == 0, ctx.captured_queries

    # -- scenario 2: totalCount selected -> exactly one COUNT --------------------
    def test_total_count_selected_issues_one_count(self) -> None:
        """Selecting "totalCount" must issue exactly one COUNT query.

        This test breaks if the count supplier is invoked more than once or
        if the returned value stops matching the actual row count.
        """
        with CaptureQueriesContext(connection) as ctx:
            result = graphql_sync(
                schema.graphql_schema,
                "{ posts { totalCount results { title } } }",
            )
        assert result.errors is None, result.errors
        assert result.data["posts"]["totalCount"] == 6
        assert _count_sql(ctx.captured_queries) == 1, ctx.captured_queries

    # -- scenario 3: totalCount aliased twice -> still one COUNT (memoized) -------
    def test_total_count_aliased_twice_issues_one_count(self) -> None:
        """Selecting "totalCount" under two aliases must still issue one COUNT.

        This test breaks if the memoized count supplier stops caching and
        re-runs the COUNT query for each alias.
        """
        with CaptureQueriesContext(connection) as ctx:
            result = graphql_sync(
                schema.graphql_schema,
                "{ posts { a: totalCount b: totalCount results { title } } }",
            )
        assert result.errors is None, result.errors
        assert result.data["posts"]["a"] == 6
        assert result.data["posts"]["b"] == 6
        assert _count_sql(ctx.captured_queries) == 1, ctx.captured_queries

    # -- scenario 7: filtered + totalCount -> correct matched value --------------
    def test_filtered_total_count_value(self) -> None:
        """A filtered query's "totalCount" must reflect the matched rows only.

        This test breaks if the lazy count supplier counts the unfiltered
        base queryset instead of the filtered one.
        """
        result = graphql_sync(
            schema.graphql_schema,
            '{ posts(filter: { title: { icontains: "needle" } })'
            " { totalCount results { title } } }",
        )
        assert result.errors is None, result.errors
        assert result.data["posts"]["totalCount"] == 1
        assert [p["title"] for p in result.data["posts"]["results"]] == ["needle"]


class LazyTotalCountCloneSemanticsTest(TestCase):
    """Scenario 4: results consumed before totalCount -> count still correct.

    Django "QuerySet.count()" clones the queryset, so a deferred count issued
    after the results were iterated returns the right number (not zero, not a
    stale cache).
    """

    def test_results_before_total_count_supplier_clones(self) -> None:
        """Reading "count" after iterating "results" must still return the right total.

        This test breaks if the deferred count supplier reuses the same
        (already-consumed) queryset instead of relying on Django's
        ".count()" cloning behavior.
        """
        author = Author.objects.create(name="A")
        for i in range(3):
            Post.objects.create(title=f"p{i}", author=author)

        qs = Post.objects.all()
        base = DjangoListObjectBase(results=qs, count=lambda qs=qs: qs.count())
        # Consume the results FIRST (materialize the queryset result cache).
        materialized = list(base.results)
        assert len(materialized) == 3
        # Now read the deferred count: the supplier clones qs, so it is correct.
        assert base.count == 3


class LazyTotalCountBaseUnitTest(TestCase):
    """Direct unit coverage for the supplier / memoization on the base object.

    Exercises "DjangoListObjectBase.count" directly, bypassing GraphQL
    execution entirely.
    """

    def test_int_count_passthrough(self) -> None:
        """A plain int passed as "count" is returned unchanged.

        This test breaks if the base object stops accepting an already
        computed count and forces callers through the callable path.
        """
        base = DjangoListObjectBase(results=[], count=7)
        assert base.count == 7

    def test_callable_count_is_memoized(self) -> None:
        """A callable "count" supplier is invoked at most once, then cached.

        This test breaks if repeated reads of "count" re-invoke the
        supplier, which would defeat the purpose of lazy counting.
        """
        calls = {"n": 0}

        def supplier() -> int:
            """Return a fixed count while tracking how many times it runs."""
            calls["n"] += 1
            return 42

        base = DjangoListObjectBase(results=[], count=supplier)
        assert base.count == 42
        assert base.count == 42  # second read must NOT re-invoke the supplier
        assert calls["n"] == 1

    def test_to_dict_reads_lazy_count(self) -> None:
        """ "to_dict()" must resolve the lazy count supplier into a value.

        This test breaks if serialization bypasses the memoized "count"
        property and leaks the raw callable instead.
        """
        base = DjangoListObjectBase(results=[], count=lambda: 9)
        assert base.to_dict()["count"] == 9


class LazyTotalCountNestedTest(TestCase):
    """Scenario 5: nested list fields both ways (prefetched + filtered DB).

    Covers "DjangoNestedListObjectField.list_resolver" directly rather than
    through a full GraphQL query.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed one author with two posts, "keep" and "drop".

        Shared across every test in this class via Django's transactional
        "setUpTestData" fixture.
        """
        cls.author = Author.objects.create(name="A")
        Post.objects.create(title="keep", author=cls.author)
        Post.objects.create(title="drop", author=cls.author)

    def test_nested_prefetch_cache_count(self) -> None:
        """A prefetched nested list resolves "count" with zero extra queries.

        This test breaks if the nested resolver stops using the in-memory
        prefetch cache and issues a COUNT query against the database instead.
        """
        field = DjangoNestedListObjectField(PostListType, accessor="posts")
        author = Author.objects.prefetch_related("posts").get(pk=self.author.pk)
        with CaptureQueriesContext(connection) as ctx:
            out = field.list_resolver(None, field.filter_backend, None, author, None)
        # In-memory list: len() is cheap, eager is fine, zero extra queries.
        assert out.count == 2
        assert len(ctx.captured_queries) == 0

    def test_nested_filtered_defers_count(self) -> None:
        """A filtered nested list resolves to a "DjangoListObjectBase" with the correct count.

        This test breaks if filtering a nested list field stops routing
        through the DB-backed filter path or returns the wrong matched count.
        """
        from django_graphex.filtering.backend import resolve_filter_backend

        field = DjangoNestedListObjectField(PostListType, accessor="posts")
        author = Author.objects.get(pk=self.author.pk)
        backend = resolve_filter_backend()
        out = field.list_resolver(
            None,
            backend,
            None,
            author,
            None,
            filter={"title": {"icontains": "keep"}},
        )
        assert isinstance(out, DjangoListObjectBase)
        assert out.count == 1


class LazyTotalCountPaginationTest(TestCase):
    """Scenario 6: pagination pageInfo path stays correct with lazy count.

    Confirms that limiting "results" does not change what "totalCount"
    reports for the full matched set.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed one author with ten posts to exercise a limited page.

        Shared across every test in this class via Django's transactional
        "setUpTestData" fixture.
        """
        author = Author.objects.create(name="A")
        for i in range(10):
            Post.objects.create(title=f"p{i:02d}", author=author)

    def test_paginated_results_and_total_count(self) -> None:
        """ "totalCount" reflects all rows while "results" honors the page limit.

        This test breaks if pagination and lazy counting interfere, e.g. if
        "totalCount" starts reporting only the size of the current page.
        """
        result = graphql_sync(
            schema.graphql_schema,
            "{ posts { totalCount results(limit: 3) { title } } }",
        )
        assert result.errors is None, result.errors
        assert result.data["posts"]["totalCount"] == 10
        assert len(result.data["posts"]["results"]) == 3
