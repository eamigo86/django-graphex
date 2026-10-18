"""Regression tests for destination scopes on automatic FK and reverse-FK reads."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import Field, ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Category, Post

_REGISTRY = Registry()


class ScopeAuthorType(DjangoObjectType):
    """Author rows visible to the current request.

    Its hook narrows automatic FK targets and root rows alike.
    """

    class Meta:
        """Bind the author model to the isolated schema registry.

        The reverse posts field is intentionally automatic.
        """

        model = Author
        registry = _REGISTRY
        only_fields = ("id", "name", "posts")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Restrict authors to the request's selected name.

        Args:
            queryset: Candidate author rows.
            info: Resolve information with the request context.

        Returns:
            Authors visible to the current request.
        """
        return queryset.filter(name=info.context.allowed_author)


class ScopeCategoryType(DjangoObjectType):
    """Category rows visible to the current request.

    The nullable Post category FK exercises hidden-target null resolution.
    """

    class Meta:
        """Bind the nullable FK target to the isolated registry.

        Only the title is needed for the output visibility witness.
        """

        model = Category
        registry = _REGISTRY
        only_fields = ("id", "title")

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Restrict categories to the request's selected title.

        Args:
            queryset: Candidate category rows.
            info: Resolve information with the request context.

        Returns:
            Categories visible to the current request.
        """
        return queryset.filter(title=info.context.allowed_category)


class ScopePostType(DjangoObjectType):
    """Post rows whose title marks them as public.

    Its hook is exercised by root and automatic reverse-FK output reads.
    """

    class Meta:
        """Expose FK fields and the title used by the visibility hook.

        Both forward relations are automatically compiled from Post.
        """

        model = Post
        registry = _REGISTRY
        only_fields = ("id", "title", "author", "category")
        filter_fields = {"title": ("icontains",)}

    @classmethod
    def get_queryset(cls, queryset: Any, info: Any) -> Any:
        """Restrict post rows before nested counts and pagination.

        Args:
            queryset: Candidate post rows.
            info: Resolve information for the current request.

        Returns:
            Public post rows.
        """
        return queryset.filter(title__startswith="pub")


class ScopeQuery(ObjectType):
    """Expose parents and children through ordinary public root fields.

    These fields provide the public query surface for the regression probes.
    """

    authors = DjangoFilterListField(ScopeAuthorType)
    posts = DjangoFilterListField(ScopePostType)
    raw_post = Field(ScopePostType)

    def resolve_raw_post(self, info: Any) -> Post:
        """Return a cached parent directly, bypassing root queryset planning.

        Args:
            info: Resolve information selecting the requested fixture row.

        Returns:
            The post selected by the request context.
        """
        return Post.objects.select_related("author", "category").get(
            title=info.context.requested_title
        )


_SCHEMA = DjangoGraphQLSchema(query=ScopeQuery, registries=isolated_pair(_REGISTRY))

_DEFAULT_REGISTRY = Registry()


class DefaultAuthorType(DjangoObjectType):
    """Author output type retaining the default no-op queryset hook.

    It is the query-plan control for automatic reverse-FK reads.
    """

    class Meta:
        """Bind authors to the isolated default-hook schema.

        The posts relation remains automatically compiled.
        """

        model = Author
        registry = _DEFAULT_REGISTRY
        only_fields = ("id", "name", "posts")


class DefaultPostType(DjangoObjectType):
    """Post output type retaining the default no-op queryset hook.

    It is the query-plan control for automatic forward-FK reads.
    """

    class Meta:
        """Expose the forward FK without adding a visibility filter.

        A default hook must not alter the optimized read plan.
        """

        model = Post
        registry = _DEFAULT_REGISTRY
        only_fields = ("id", "title", "author")


class DefaultQuery(ObjectType):
    """Expose rows for the no-op hook query-plan control.

    Its roots mirror the restrictive schema without destination filtering.
    """

    posts = DjangoFilterListField(DefaultPostType)
    authors = DjangoFilterListField(DefaultAuthorType)


_DEFAULT_SCHEMA = DjangoGraphQLSchema(
    query=DefaultQuery, registries=isolated_pair(_DEFAULT_REGISTRY)
)


@pytest.mark.django_db
@pytest.mark.parametrize("optimize", [True, False])
def test_automatic_fk_visibility_matches_destination_scope(optimize: bool) -> None:
    """A hidden FK is null, including a cached target, without hiding its parent.

    Args:
        optimize: Whether the normal queryset optimizer is enabled.
    """
    visible = Author.objects.create(name="visible")
    hidden = Author.objects.create(name="hidden")
    allowed = Category.objects.create(title="allowed")
    denied = Category.objects.create(title="denied")
    Post.objects.create(title="pub-visible", author=visible, category=allowed)
    Post.objects.create(title="pub-hidden", author=hidden, category=denied)
    Post.objects.create(title="pub-null", author=visible, category=None)

    query = "{ posts { title author { name } category { title } } }"
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        for author in ("visible", "hidden"):
            result = graphql_sync(
                _SCHEMA.graphql_schema,
                query,
                context_value=SimpleNamespace(
                    allowed_author=author, allowed_category="allowed"
                ),
            )
            assert result.errors is None, [str(error) for error in result.errors or ()]
            assert result.data is not None
            by_title = {row["title"]: row for row in result.data["posts"]}
            assert sorted(by_title) == ["pub-hidden", "pub-null", "pub-visible"]
            assert by_title["pub-visible"]["author"] == (
                {"name": "visible"} if author == "visible" else None
            )
            assert by_title["pub-hidden"]["author"] == (
                {"name": "hidden"} if author == "hidden" else None
            )
            assert by_title["pub-hidden"]["category"] is None
            assert by_title["pub-null"]["category"] is None
            assert by_title["pub-visible"]["category"] == {"title": "allowed"}


@pytest.mark.django_db
@pytest.mark.parametrize("optimize", [True, False])
def test_automatic_reverse_fk_filters_before_count_and_page(optimize: bool) -> None:
    """The nested container counts and pages only the destination's visible rows.

    Args:
        optimize: Whether the normal queryset optimizer is enabled.
    """
    author = Author.objects.create(name="visible")
    for title in ("pub-one", "secret", "pub-two"):
        Post.objects.create(title=title, author=author)
    query = "{ authors { name posts { totalCount results { title } } } }"

    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        result = graphql_sync(
            _SCHEMA.graphql_schema,
            query,
            context_value=SimpleNamespace(
                allowed_author="visible", allowed_category="allowed"
            ),
        )

    assert result.errors is None, [str(error) for error in result.errors or ()]
    assert result.data is not None
    posts = result.data["authors"][0]["posts"]
    assert posts["totalCount"] == 2
    assert {item["title"] for item in posts["results"]} == {"pub-one", "pub-two"}


@pytest.mark.django_db
def test_scoped_fk_prefetch_is_batched_and_aliases_share_visibility() -> None:
    """Ten parents do not trigger ten authorization queries for one FK target.

    Aliases and an inline fragment share the same request-scoped visibility.
    """
    visible = Author.objects.create(name="visible")
    hidden = Author.objects.create(name="hidden")
    for index in range(10):
        Post.objects.create(
            title=f"pub-{index:02d}",
            author=visible if index % 2 == 0 else hidden,
        )
    query = """{
      posts {
        title
        firstAuthor: author { name }
        ... on ScopePostType { secondAuthor: author { name } }
      }
    }"""
    with CaptureQueriesContext(connection) as captured:
        result = graphql_sync(
            _SCHEMA.graphql_schema,
            query,
            context_value=SimpleNamespace(
                allowed_author="visible", allowed_category="allowed"
            ),
        )
    assert result.errors is None, [str(error) for error in result.errors or ()]
    assert result.data is not None
    assert len(result.data["posts"]) == 10
    for row in result.data["posts"]:
        expected = {"name": "visible"} if int(row["title"][-2:]) % 2 == 0 else None
        assert row["firstAuthor"] == expected
        assert row["secondAuthor"] == expected
    assert len(captured) <= 3


@pytest.mark.django_db
def test_reverse_fk_window_pages_visible_rows_only() -> None:
    """A hidden leading child cannot shorten the first visible page.

    The page and total count derive from the filtered child queryset.
    """
    author = Author.objects.create(name="visible")
    for title in ("secret", "pub-one", "pub-two"):
        Post.objects.create(title=title, author=author)
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "{ authors { posts { totalCount results(limit: 1) { title } } } }",
        context_value=SimpleNamespace(
            allowed_author="visible", allowed_category="allowed"
        ),
    )
    assert result.errors is None, [str(error) for error in result.errors or ()]
    assert result.data is not None
    posts = result.data["authors"][0]["posts"]
    assert posts["totalCount"] == 2
    assert len(posts["results"]) == 1
    assert posts["results"][0]["title"].startswith("pub")


@pytest.mark.django_db
def test_cached_fk_fallback_applies_destination_scope() -> None:
    """A caller-populated select-related cache cannot authorize a hidden FK.

    The custom root bypasses queryset_factory, exercising the automatic FK
    resolver's fallback when no scoped prefetch was planned.
    """
    visible = Author.objects.create(name="visible")
    hidden = Author.objects.create(name="hidden")
    for title, author in (("pub-visible", visible), ("pub-hidden", hidden)):
        Post.objects.create(title=title, author=author)
    query = "{ rawPost { title author { name } category { title } } }"
    for title, allowed, expected in (
        ("pub-visible", "visible", {"name": "visible"}),
        ("pub-hidden", "visible", None),
        ("pub-hidden", "hidden", {"name": "hidden"}),
    ):
        result = graphql_sync(
            _SCHEMA.graphql_schema,
            query,
            context_value=SimpleNamespace(
                requested_title=title,
                allowed_author=allowed,
                allowed_category="allowed",
            ),
        )
        assert result.errors is None, [str(error) for error in result.errors or ()]
        assert result.data is not None
        assert result.data["rawPost"]["author"] == expected
        assert result.data["rawPost"]["category"] is None


@pytest.mark.django_db
def test_scoped_reverse_fk_plain_prefetch_ignores_unscoped_cache() -> None:
    """The non-window optimized path stores only scoped reverse-FK rows.

    Disabling nested window pagination leaves the general optimizer enabled.
    """
    for index in range(4):
        author = Author.objects.create(name="visible", bio=f"author-{index}")
        for title in ("secret", "pub-one", "pub-two"):
            Post.objects.create(title=f"{title}-{index}", author=author)
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": False}):
        with CaptureQueriesContext(connection) as captured:
            result = graphql_sync(
                _SCHEMA.graphql_schema,
                "{ authors { posts { totalCount results { title } } } }",
                context_value=SimpleNamespace(
                    allowed_author="visible", allowed_category="allowed"
                ),
            )
    assert result.errors is None, [str(error) for error in result.errors or ()]
    assert result.data is not None
    assert len(result.data["authors"]) == 4
    assert all(row["posts"]["totalCount"] == 2 for row in result.data["authors"])
    assert all(
        all(post["title"].startswith("pub") for post in row["posts"]["results"])
        for row in result.data["authors"]
    )
    assert len(captured) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("optimize", [True, False])
def test_scoped_and_default_fk_query_costs_are_explicit(optimize: bool) -> None:
    """Compare scoped and no-op FK query plans in each optimizer mode.

    Args:
        optimize: Whether selection-driven queryset optimization is enabled.
    """
    visible = Author.objects.create(name="visible")
    hidden = Author.objects.create(name="hidden")
    for index in range(10):
        Post.objects.create(
            title=f"pub-{index}", author=visible if index % 2 == 0 else hidden
        )

    query = "{ posts { title author { name } } }"
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        with CaptureQueriesContext(connection) as default_queries:
            default_result = graphql_sync(_DEFAULT_SCHEMA.graphql_schema, query)
        with CaptureQueriesContext(connection) as scoped_queries:
            scoped_result = graphql_sync(
                _SCHEMA.graphql_schema,
                query,
                context_value=SimpleNamespace(
                    allowed_author="visible", allowed_category="allowed"
                ),
            )

    assert default_result.errors is None
    assert scoped_result.errors is None
    assert default_result.data is not None
    assert scoped_result.data is not None
    assert all(row["author"] is not None for row in default_result.data["posts"])
    assert sum(row["author"] is None for row in scoped_result.data["posts"]) == 5
    assert len(default_queries) == (1 if optimize else 11)
    assert len(scoped_queries) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("optimize", [True, False])
def test_reverse_fk_query_costs_are_explicit(optimize: bool) -> None:
    """Measure reverse-FK scoping against the no-op hook in each mode.

    Args:
        optimize: Whether selection-driven queryset optimization is enabled.
    """
    for index in range(10):
        author = Author.objects.create(name="visible", bio=f"author-{index}")
        for title in ("pub-one", "secret", "pub-two"):
            Post.objects.create(title=f"{title}-{index}", author=author)

    query = "{ authors { posts { totalCount results { title } } } }"
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": optimize}):
        with CaptureQueriesContext(connection) as default_queries:
            default_result = graphql_sync(_DEFAULT_SCHEMA.graphql_schema, query)
        with CaptureQueriesContext(connection) as scoped_queries:
            scoped_result = graphql_sync(
                _SCHEMA.graphql_schema,
                query,
                context_value=SimpleNamespace(
                    allowed_author="visible", allowed_category="allowed"
                ),
            )

    assert default_result.errors is None
    assert scoped_result.errors is None
    assert default_result.data is not None
    assert scoped_result.data is not None
    assert len(default_result.data["authors"]) == 10
    assert len(scoped_result.data["authors"]) == 10
    assert all(
        row["posts"]["totalCount"] == 3 for row in default_result.data["authors"]
    )
    assert all(row["posts"]["totalCount"] == 2 for row in scoped_result.data["authors"])
    assert len(default_queries) == (2 if optimize else 11)
    assert len(scoped_queries) == (2 if optimize else 11)
