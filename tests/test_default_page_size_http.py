"""Public HTTP regression for the library's bounded default page size."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest
from django.test import RequestFactory

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoNestedListObjectField
from django_graphex.paginations import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Author, Post

R = Registry()


class DefaultSizePost(DjangoObjectType):
    """Expose post IDs in the default-size HTTP schema.

    The three list styles share this output model.
    """

    class Meta:
        """Bind posts to the isolated test registry.

        This avoids collisions with unrelated test schemas.
        """

        model = Post
        registry = R


class DefaultSizePosts(DjangoListObjectType):
    """Use automatic global limit/offset pagination.

    No local size is supplied for the default-inheritance test.
    """

    class Meta:
        """Leave pagination absent so the global default is selected.

        This covers the automatic list-type path.
        """

        model = Post
        registry = R


class DefaultSizePagePosts(DjangoListObjectType):
    """Use page pagination without a local size.

    The inherited size is tested through HTTP results.
    """

    class Meta:
        """Bind an omitted-size page paginator to posts.

        A client page-size argument is enabled for override coverage.
        """

        model = Post
        registry = R
        pagination = PageGraphqlPagination(
            ordering="id", page_size_query_param="pageSize"
        )


class DefaultSizeCursorPosts(DjangoListObjectType):
    """Use cursor pagination without a local size.

    The test follows the returned keyset cursor to the next page.
    """

    class Meta:
        """Bind an omitted-size cursor paginator to posts.

        ID ordering makes continuation assertions deterministic.
        """

        model = Post
        registry = R
        pagination = CursorGraphqlPagination(ordering="id")


class DefaultSizeAuthor(DjangoObjectType):
    """Expose an author's nested posts through the default paginator.

    This exercises the prefetched relation path.
    """

    posts = DjangoNestedListObjectField(DefaultSizePosts, accessor="posts")

    class Meta:
        """Bind authors to the isolated test registry.

        The nested field uses the same registry as the post list.
        """

        model = Author
        registry = R


class DefaultSizeAuthors(DjangoListObjectType):
    """Expose the parent author for nested pagination.

    Only the child's 105-row boundary matters for this control.
    """

    class Meta:
        """Bind the author list without a local paginator.

        It inherits the same global default as other list types.
        """

        model = Author
        registry = R


class DefaultSizeQuery(ObjectType):
    """Expose the three default-size public list fields.

    A parent field also provides the nested list path.
    """

    default_posts = DjangoListObjectField(DefaultSizePosts)
    page_posts = DjangoListObjectField(DefaultSizePagePosts)
    cursor_posts = DjangoListObjectField(DefaultSizeCursorPosts)
    authors = DjangoListObjectField(DefaultSizeAuthors)


SCHEMA = DjangoGraphQLSchema(query=DefaultSizeQuery, registries=isolated_pair(R))


def _post(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a JSON GraphQL operation through the public HTTP view.

    Args:
        query: GraphQL query text.
        variables: Optional GraphQL variables.

    Returns:
        The decoded HTTP response body.
    """
    response = GraphQLView.as_view(schema=SCHEMA)(
        RequestFactory().post(
            "/graphql/",
            json.dumps({"query": query, "variables": variables or {}}),
            content_type="application/json",
            HTTP_X_CSRF_TOKEN="test",
        )
    )
    assert response.status_code == 200
    return json.loads(response.content)


@pytest.fixture
def ordered_posts(db: Any) -> list[Post]:
    """Create 105 posts, making a 100-row boundary observable.

    Args:
        db: Pytest database fixture.

    Returns:
        The posts in deterministic ID order.
    """
    author = Author.objects.create(name="default-page-size-parent")
    return [
        Post.objects.create(author=author, title=f"Default {index:03d}")
        for index in range(105)
    ]


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    """Extract GraphQL IDs from a result list.

    Args:
        rows: Selected GraphQL result objects.

    Returns:
        IDs in their response order.
    """
    return [row["id"] for row in rows]


def test_omitted_size_uses_library_default_across_public_paginators(
    ordered_posts: list[Post],
) -> None:
    """Each omitted-size list returns 100 of 105 rows and can fetch the rest.

    Args:
        ordered_posts: The deterministically ordered database posts.
    """
    first = _post(
        '{ defaultPosts { totalCount results(ordering: "id") { id } } '
        'pagePosts { totalCount results(ordering: "id") { id } } '
        "cursorPosts { totalCount results { id } "
        "pageInfo { endCursor hasNextPage } } }"
    )
    assert "errors" not in first, first
    expected = [str(post.pk) for post in ordered_posts]
    for field in ("defaultPosts", "pagePosts", "cursorPosts"):
        container = first["data"][field]
        assert container["totalCount"] == 105
        assert container["results"] is not None
        assert _ids(container["results"]) == expected[:100]
    assert graphql_api_settings.DEFAULT_PAGE_SIZE == 100

    offset = _post(
        '{ defaultPosts { totalCount results(offset: 100, ordering: "id") { id } } '
        'pagePosts { totalCount results(page: 2, ordering: "id") { id } } }'
    )
    assert "errors" not in offset, offset
    assert _ids(offset["data"]["defaultPosts"]["results"]) == expected[100:]
    assert _ids(offset["data"]["pagePosts"]["results"]) == expected[100:]

    cursor_info = first["data"]["cursorPosts"]["pageInfo"]
    assert cursor_info["hasNextPage"] is True
    assert cursor_info["endCursor"]
    continued = _post(
        "query($cursor: String!) { cursorPosts { totalCount "
        "results(cursor: $cursor) { id } "
        "pageInfo(cursor: $cursor) { hasNextPage } } }",
        {"cursor": cursor_info["endCursor"]},
    )
    assert "errors" not in continued, continued
    assert _ids(continued["data"]["cursorPosts"]["results"]) == expected[100:]
    assert continued["data"]["cursorPosts"]["pageInfo"]["hasNextPage"] is False


def test_default_is_not_a_maximum_http(ordered_posts: list[Post]) -> None:
    """An explicit supported request for 103 rows exceeds the 100-row default.

    Args:
        ordered_posts: The 105 database posts selected by this query.
    """
    body = _post(
        '{ defaultPosts { results(limit: 103, ordering: "id") { id } } '
        'pagePosts { results(pageSize: 103, ordering: "id") { id } } '
        "cursorPosts { results(first: 103) { id } } }"
    )
    assert "errors" not in body, body
    expected = [str(post.pk) for post in ordered_posts[:103]]
    for field in ("defaultPosts", "pagePosts", "cursorPosts"):
        assert _ids(body["data"][field]["results"]) == expected
    assert graphql_api_settings.MAX_PAGE_SIZE is None


def test_nested_omitted_size_uses_library_default_http(
    ordered_posts: list[Post],
) -> None:
    """Nested default pagination also returns 100 rows and then five.

    Args:
        ordered_posts: The 105 posts belonging to the queried parent.
    """
    first = _post(
        '{ authors { results { posts { totalCount results(ordering: "id") { id } } } } }'
    )
    assert "errors" not in first, first
    nested = first["data"]["authors"]["results"][0]["posts"]
    expected = [str(post.pk) for post in ordered_posts]
    assert nested["totalCount"] == 105
    assert _ids(nested["results"]) == expected[:100]
    second = _post(
        '{ authors { results { posts { results(offset: 100, ordering: "id") { id } } } } }'
    )
    assert "errors" not in second, second
    nested_second = second["data"]["authors"]["results"][0]["posts"]
    assert _ids(nested_second["results"]) == expected[100:]


def test_explicit_none_preserves_each_legacy_paginator_policy() -> None:
    """Preserve each paginator's explicit-None legacy policy.

    Offset returns all rows, Page returns None, and Cursor falls back to 20.
    """
    rows = list(range(105))
    assert (
        LimitOffsetGraphqlPagination(
            default_limit=None, max_limit=None
        ).paginate_queryset(rows)
        == rows
    )
    assert (
        PageGraphqlPagination(page_size=None, max_page_size=None).paginate_queryset(
            rows
        )
        is None
    )
    cursor = CursorGraphqlPagination(ordering="id", page_size=None, max_page_size=None)
    assert cursor._page_size() == 20


def test_startup_global_override_and_local_size_take_precedence() -> None:
    """Inherit global 20/100 at startup while explicit local 7 wins.

    A fresh interpreter avoids constructor defaults captured in this process.
    """
    script = """
import json
from django.conf import settings
settings.configure(DJANGO_GRAPHEX={"DEFAULT_PAGE_SIZE": 20, "MAX_PAGE_SIZE": 100})
from django_graphex.paginations import (LimitOffsetGraphqlPagination,
                                        PageGraphqlPagination, CursorGraphqlPagination)
offset = LimitOffsetGraphqlPagination()
page = PageGraphqlPagination()
cursor = CursorGraphqlPagination()
print(json.dumps({"defaults": [offset.default_limit, page.page_size, cursor.page_size],
                  "maximums": [offset.max_limit, page.max_page_size, cursor.max_page_size],
                  "local": [LimitOffsetGraphqlPagination(default_limit=7).default_limit,
                            PageGraphqlPagination(page_size=7).page_size,
                            CursorGraphqlPagination(page_size=7).page_size],
                  "max_only": LimitOffsetGraphqlPagination(default_limit=None,
                                                             max_limit=100).paginate_queryset(list(range(105))).__len__()}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    values = json.loads(result.stdout)
    assert values == {
        "defaults": [20, 20, 20],
        "maximums": [100, 100, 100],
        "local": [7, 7, 7],
        "max_only": 100,
    }
