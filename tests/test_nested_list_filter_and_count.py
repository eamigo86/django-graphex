# -*- coding: utf-8 -*-
"""Nested lists must honor "@filter_field" filters and "optimize_<field>" hooks.

Two defects are pinned here, both on "DjangoNestedListObjectField":

* The nested "<Model>FilterInput" PUBLISHES the "@filter_field" custom filters
  (the input type is shared with the top-level list), but no nested path ever
  ran them: "build_prefetch", "build_window_prefetch", its count subquery, and
  the resolver's own filtered/count branches all called "filter_backend.apply"
  alone. A filter argument the schema advertises was silently ignored.
* The empty-window-page count rebuilt the child queryset WITHOUT the
  "optimize_<field>" hook that WAS applied to the window queryset, so
  "totalCount" jumped on the last/overshoot page (and leaked the unscoped row
  count when the hook does row scoping).

Every reachable nested path gets its own test because each is what a user would
report: the plain prefetch, the window prefetch, the window empty-page count
(both the parent-annotation and the per-parent fallback), and the resolver path
taken when "OPTIMIZE_QUERYSET" is off.
"""

from __future__ import annotations

from typing import Any

from django.test import TestCase, override_settings
from graphql import GraphQLString, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.filtering import filter_field
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Comment, Post

R = Registry()


class NestedFilterCommentType(DjangoObjectType):
    """Grandchild row type, used to reach a nested list two levels down.

    Declares a "@filter_field" so the deepest level can assert the custom
    filter fires there too.
    """

    class Meta:
        """Bind the type to "Comment" with a filterable "body".

        The lookups exist so the nested field mounts a filter argument at all.
        """

        model = Comment
        registry = R
        filter_fields = {"body": ("exact", "icontains")}

    @filter_field(GraphQLString)
    def search(
        cls: type[NestedFilterCommentType], queryset: Any, info: Any, value: str
    ) -> Any:
        """Filter comments whose body contains "value".

        Args:
            cls: The object type class that owns the filter.
            queryset: The queryset being filtered.
            info: The GraphQL resolve info for the current request.
            value: The substring supplied by the caller.

        Returns:
            The queryset narrowed to matching bodies.
        """
        return queryset.filter(body__icontains=value)


class NestedFilterPostType(DjangoObjectType):
    """Child row type carrying both a custom filter and a grandchild hook.

    "optimize_comments" is what the empty-window-page count must honor on the
    deep-nested path.
    """

    class Meta:
        """Bind the type to "Post" with a filterable "title".

        The lookups exist so the nested field mounts a filter argument at all.
        """

        model = Post
        registry = R
        filter_fields = {"title": ("exact", "icontains")}

    @filter_field(GraphQLString)
    def search(
        cls: type[NestedFilterPostType], queryset: Any, info: Any, value: str
    ) -> Any:
        """Filter posts whose title contains "value".

        Args:
            cls: The object type class that owns the filter.
            queryset: The queryset being filtered.
            info: The GraphQL resolve info for the current request.
            value: The substring supplied by the caller.

        Returns:
            The queryset narrowed to matching titles.
        """
        return queryset.filter(title__icontains=value)

    @staticmethod
    def optimize_comments(qs: Any, info: Any, **kwargs: Any) -> Any:
        """Hide draft comments from every "comments" nested list.

        Args:
            qs: The optimizer-built child queryset.
            info: The GraphQL resolve info for the current request.
            **kwargs: The "filter_value" / "is_window" contract keywords.

        Returns:
            The queryset without the draft rows.
        """
        return qs.exclude(body__startswith="draft")


class NestedFilterAuthorType(DjangoObjectType):
    """Parent row type mounting the "posts" nested list.

    "optimize_posts" is the hook the empty-window-page count must honor on the
    top-level path.
    """

    class Meta:
        """Bind the type to "Author".

        No filter configuration: the parent is never the filtered side here.
        """

        model = Author
        registry = R

    @staticmethod
    def optimize_posts(qs: Any, info: Any, **kwargs: Any) -> Any:
        """Hide draft posts from every "posts" nested list.

        Args:
            qs: The optimizer-built child queryset.
            info: The GraphQL resolve info for the current request.
            **kwargs: The "filter_value" / "is_window" contract keywords.

        Returns:
            The queryset without the draft rows.
        """
        return qs.exclude(title__startswith="draft")


class NestedFilterAuthorList(DjangoListObjectType):
    """Root list container for "NestedFilterAuthorType".

    Every nested case in this module hangs off this single root list.
    """

    class Meta:
        """Bind the list type to "Author".

        The default paginator is enough; the pages are driven per query.
        """

        model = Author
        registry = R


class _Query(ObjectType):
    """Root query exposing the author list the nested cases hang off."""

    authors = DjangoListObjectField(NestedFilterAuthorList)


_schema = DjangoGraphQLSchema(query=_Query, registries=isolated_pair(R))


def _run(query: str) -> Any:
    """Execute "query" against the module schema and return its data.

    Args:
        query: The GraphQL document to execute.

    Returns:
        The "data" mapping of the execution result.

    Raises:
        AssertionError: When the execution reported errors.
    """
    result = graphql_sync(_schema.graphql_schema, query)
    assert result.errors is None, result.errors
    return result.data


def _seed_posts() -> Author:
    """Create one author owning an "alpha" and a "beta" post.

    Returns:
        The author both posts belong to.
    """
    author = Author.objects.create(name="Ada")
    Post.objects.create(title="alpha", author=author)
    Post.objects.create(title="beta", author=author)
    return author


class NestedCustomFilterTest(TestCase):
    """The nested "filter" argument must run "@filter_field" methods.

    One test per nested path, because each is a separate call site that could
    regress on its own.
    """

    def test_plain_prefetch_path(self) -> None:
        """An unpaginated nested list applies the custom filter.

        This test breaks if "build_prefetch" stops running the "@filter_field"
        methods the nested filter input advertises.
        """
        _seed_posts()

        data = _run(
            '{ authors { results { posts(filter: {search: "alp"}) '
            "{ results { title } totalCount } } } }"
        )

        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["results"], [{"title": "alpha"}])
        self.assertEqual(posts["totalCount"], 1)

    def test_window_prefetch_path(self) -> None:
        """A window-sliced nested list applies the custom filter.

        This test breaks if "build_window_prefetch" stops running the
        "@filter_field" methods before the window expressions.
        """
        _seed_posts()

        data = _run(
            '{ authors { results { posts(filter: {search: "alp"}) '
            "{ results(limit: 5) { title } totalCount } } } }"
        )

        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["results"], [{"title": "alpha"}])
        self.assertEqual(posts["totalCount"], 1)

    def test_window_empty_page_count(self) -> None:
        """An overshooting window page counts only the custom-filtered rows.

        This test breaks if the parent count annotation built by
        "build_window_prefetch" stops running the "@filter_field" methods.
        """
        _seed_posts()

        data = _run(
            '{ authors { results { posts(filter: {search: "alp"}) '
            "{ results(offset: 50, limit: 2) { title } totalCount } } } }"
        )

        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["results"], [])
        self.assertEqual(posts["totalCount"], 1)

    @override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": False})
    def test_resolver_path_without_optimizer(self) -> None:
        """With the optimizer off, the resolver itself applies the custom filter.

        This test breaks if "DjangoNestedListObjectField.list_resolver" stops
        running the "@filter_field" methods on its own filtered branch.
        """
        _seed_posts()

        data = _run(
            '{ authors { results { posts(filter: {search: "alp"}) '
            "{ results { title } totalCount } } } }"
        )

        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["results"], [{"title": "alpha"}])
        self.assertEqual(posts["totalCount"], 1)

    def test_deep_nested_custom_filter(self) -> None:
        """A grandchild nested list applies its own custom filter too.

        This test breaks if the re-rooted deep prefetch stops running the
        "@filter_field" methods declared on the grandchild type.
        """
        author = Author.objects.create(name="Ada")
        post = Post.objects.create(title="alpha", author=author)
        Comment.objects.create(post=post, body="hello")
        Comment.objects.create(post=post, body="goodbye")

        data = _run(
            "{ authors { results { posts { results { "
            'comments(filter: {search: "hell"}) { results { body } totalCount } '
            "} } } } }"
        )

        comments = data["authors"]["results"][0]["posts"]["results"][0]["comments"]
        self.assertEqual(comments["results"], [{"body": "hello"}])
        self.assertEqual(comments["totalCount"], 1)


class NestedWindowCountHookTest(TestCase):
    """The empty-window-page count must honor the "optimize_<field>" hook.

    "totalCount" has to stay stable across pages: a UI computing the page count
    from the last page must see the same total the first page reported.
    """

    def test_total_count_is_stable_across_pages(self) -> None:
        """The overshoot page reports the same hook-scoped total as page one.

        This test breaks if the parent count annotation built by
        "build_window_prefetch" stops applying the "optimize_<field>" hook.
        """
        author = Author.objects.create(name="Ada")
        for index in range(3):
            Post.objects.create(title=f"pub{index}", author=author)
        for index in range(4):
            Post.objects.create(title=f"draft{index}", author=author)

        totals = [
            _run(
                "{ authors { results { posts "
                "{ results(offset: %d, limit: 2) { title } totalCount } } } }" % offset
            )["authors"]["results"][0]["posts"]["totalCount"]
            for offset in (0, 2, 50)
        ]

        self.assertEqual(totals, [3, 3, 3])

    def test_deep_nested_total_count_is_stable_across_pages(self) -> None:
        """A grandchild list keeps the hook-scoped total on the overshoot page.

        The deep-nested prefetch is re-rooted into the parent queryset, so the
        parent count annotation never lands and the resolver falls back to a
        per-parent count. This test breaks if that fallback stops applying the
        "optimize_<field>" hook.
        """
        author = Author.objects.create(name="Ada")
        post = Post.objects.create(title="pub", author=author)
        for index in range(3):
            Comment.objects.create(post=post, body=f"pub{index}")
        for index in range(4):
            Comment.objects.create(post=post, body=f"draft{index}")

        totals = [
            _run(
                "{ authors { results { posts { results { comments "
                "{ results(offset: %d, limit: 2) { body } totalCount } } } } } }"
                % offset
            )["authors"]["results"][0]["posts"]["results"][0]["comments"]["totalCount"]
            for offset in (0, 50)
        ]

        self.assertEqual(totals, [3, 3])
