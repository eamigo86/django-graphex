"""Public HTTP contract for nullable page-number pagination."""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest
from django.db.models import QuerySet
from django.test import RequestFactory
from graphql import GraphQLError

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import PageGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Author, Post

R = Registry()


class PagePost(DjangoObjectType):
    """Expose posts in the isolated page-number schema.

    This output type is shared by root and nested list results.
    """

    class Meta:
        """Bind the post model and isolated registry.

        The registry prevents cross-schema output collisions.
        """

        model = Post
        registry = R


class PagePosts(DjangoListObjectType):
    """Use two-row pages for both root and nested post lists.

    The partial final page distinguishes existing negative-page behavior.
    """

    class Meta:
        """Bind posts and their page-number pagination.

        Ordering by ID makes row assertions deterministic.
        """

        model = Post
        registry = R
        pagination = PageGraphqlPagination(
            page_size=2, page_size_query_param="pageSize", ordering="id"
        )


class PageAuthor(DjangoObjectType):
    """Expose an author's generated nested posts field.

    The relation is populated by the schema compiler.
    """

    class Meta:
        """Bind the author model and isolated registry.

        The nested posts field reuses the registered post list policy.
        """

        model = Author
        registry = R


class PageAuthors(DjangoListObjectType):
    """Expose the parent list containing nested posts.

    The nested query checks both optimized and materialized resolution.
    """

    class Meta:
        """Bind the author model and isolated registry.

        No page-number policy is applied to the parent list.
        """

        model = Author
        registry = R


class PageQuery(ObjectType):
    """Expose the ORM root and generated nested-list entry points.

    Both use the same PagePosts paginator through the public view.
    """

    posts = DjangoListObjectField(PagePosts)
    authors = DjangoListObjectField(PageAuthors)


SCHEMA = DjangoGraphQLSchema(query=PageQuery, registries=isolated_pair(R))


def _post(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one JSON request through the public GraphQL view.

    Args:
        query: GraphQL operation to execute.
        variables: Optional operation variables.

    Returns:
        The decoded HTTP JSON response.
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


def _query(scope: str, argument: str, *, variable: bool = False) -> str:
    """Build equivalent root or nested public list operations.

    Args:
        scope: Root ORM list or nested materialized list.
        argument: Optional argument text for the results field.
        variable: Whether the operation declares a nullable page variable.

    Returns:
        A GraphQL operation selecting rows and totalCount.
    """
    prefix = "query($page: Int)" if variable else "query"
    results = f"results({argument})" if argument else "results"
    posts = f"posts {{ totalCount {results} {{ id title }} }}"
    selection = posts if scope == "root" else f"authors {{ results {{ {posts} }} }}"
    return f"{prefix} {{ {selection} }}"


def _page(body: dict[str, Any], scope: str) -> dict[str, Any]:
    """Extract the selected post-list container from an HTTP response.

    Args:
        body: Decoded GraphQL response.
        scope: Root ORM list or nested materialized list.

    Returns:
        The post-list container with rows and totalCount.
    """
    data = body["data"]
    return data["posts"] if scope == "root" else data["authors"]["results"][0]["posts"]


@pytest.fixture
def page_rows(db: Any) -> list[Post]:
    """Create five deterministically ordered posts under one author.

    Args:
        db: Pytest database fixture.

    Returns:
        The posts in insertion order.
    """
    author = Author.objects.create(name="page-parent")
    return [Post.objects.create(author=author, title=f"Page {i}") for i in range(1, 6)]


@pytest.mark.parametrize("scope", ["root", "nested"])
@pytest.mark.parametrize("kind", ["literal", "variable"])
def test_explicit_null_page_matches_omission_http(
    page_rows: list[Post], scope: str, kind: str
) -> None:
    """Explicit null selects the same first rows and count as omitted page.

    Args:
        page_rows: Five ordered database posts.
        scope: ORM root or materialized nested list.
        kind: Literal null or nullable variable set to null.
    """
    omitted = _post(_query(scope, 'ordering: "id"'))
    assert "errors" not in omitted, omitted
    if kind == "literal":
        actual = _post(_query(scope, 'page: null, ordering: "id"'))
    else:
        actual = _post(
            _query(scope, 'page: $page, ordering: "id"', variable=True),
            {"page": None},
        )
    assert "errors" not in actual, actual
    expected = _page(omitted, scope)
    assert expected["totalCount"] == 5
    assert [row["id"] for row in expected["results"]] == [
        str(post.pk) for post in page_rows[:2]
    ]
    assert _page(actual, scope) == expected


@pytest.mark.parametrize("scope", ["root", "nested"])
def test_existing_page_boundaries_http(page_rows: list[Post], scope: str) -> None:
    """Pin positive, zero, and pre-existing negative-page behavior.

    Args:
        page_rows: Five ordered database posts.
        scope: ORM root or materialized nested list.
    """
    expected = [str(row.pk) for row in page_rows]
    for page, indexes in [
        (1, [0, 1]),
        (2, [2, 3]),
        (4, []),
        (-1, [3, 4]),
        (-2, [1, 2]),
    ]:
        body = _post(_query(scope, f'page: {page}, ordering: "id"'))
        assert "errors" not in body, body
        selected = _page(body, scope)
        assert selected["totalCount"] == 5
        assert [row["id"] for row in selected["results"]] == [
            expected[i] for i in indexes
        ]
        if page < 0:
            print(f"BASELINE_NEGATIVE {scope} {page}: {selected}")

    zero = _post(_query(scope, 'page: 0, ordering: "id"'))
    assert zero["errors"][0]["message"] == (
        "Page value for PageGraphqlPagination must be a non-zero value"
    )


@pytest.mark.parametrize("scope", ["root", "nested"])
def test_omitted_nullable_variable_keeps_default_http(
    page_rows: list[Post], scope: str
) -> None:
    """Omitting a nullable variable still uses the SDL's first-page default.

    Args:
        page_rows: Five ordered database posts.
        scope: ORM root or materialized nested list.
    """
    omitted = _post(_query(scope, 'ordering: "id"'))
    variable_omitted = _post(
        _query(scope, 'page: $page, ordering: "id"', variable=True), {}
    )
    assert "errors" not in variable_omitted, variable_omitted
    assert _page(variable_omitted, scope) == _page(omitted, scope)
    assert [row["id"] for row in _page(variable_omitted, scope)["results"]] == [
        str(post.pk) for post in page_rows[:2]
    ]


def test_nested_null_page_reaches_materialized_list_without_optimizer(
    page_rows: list[Post], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public nested request exercises in-memory pagination, not only ORM.

    Args:
        page_rows: Five ordered database posts.
        monkeypatch: Temporary method wrapper recording collection kinds.
    """
    original = PageGraphqlPagination.paginate_queryset
    collection_kinds: list[bool] = []

    def record_collection(
        paginator: PageGraphqlPagination, qs: Any, **kwargs: Any
    ) -> Any:
        """Record whether each paginated collection is a QuerySet.

        Args:
            paginator: Active paginator instance.
            qs: Input collection passed by the resolver.
            **kwargs: GraphQL pagination arguments.

        Returns:
            The original paginator result.
        """
        collection_kinds.append(isinstance(qs, QuerySet))
        return original(paginator, qs, **kwargs)

    monkeypatch.setattr(PageGraphqlPagination, "paginate_queryset", record_collection)
    with mock.patch.object(graphql_api_settings, "OPTIMIZE_QUERYSET", False):
        body = _post(_query("nested", 'page: null, ordering: "id"'))
    assert "errors" not in body, body
    assert _page(body, "nested")["totalCount"] == len(page_rows)
    assert False in collection_kinds


def test_direct_page_null_normalizes_both_paths(page_rows: list[Post]) -> None:
    """The regular paginator and prefetch precheck share the null default.

    Args:
        page_rows: Five ordered database posts.
    """
    paginator = PageGraphqlPagination(page_size=2)
    expected = page_rows[:2]
    assert list(paginator.paginate_queryset(page_rows)) == expected
    assert list(paginator.paginate_queryset(page_rows, page=None)) == expected
    assert paginator.prefetch_window_slice(page=None) == (
        paginator.prefetch_window_slice()
    )
    with pytest.raises(GraphQLError, match="non-zero value"):
        paginator.paginate_queryset(page_rows, page=0)
