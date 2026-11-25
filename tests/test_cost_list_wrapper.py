"""A paginated list costs its page size once, not once per wrapper level.

A DjangoListObjectType field is an object container whose "results" field is
the real GraphQL list carrying the page-size argument, so only "results"
multiplies its children (issue 255).
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from django.test import RequestFactory, override_settings
from graphql import parse

from django_graphex.core import ObjectType
from django_graphex.cost import analyze_cost
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations.pagination import (
    BaseDjangoGraphqlPagination,
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Author, Comment, Post

Paginator = Callable[[], BaseDjangoGraphqlPagination]

PAGINATORS = [
    pytest.param(lambda: CursorGraphqlPagination(ordering="id"), "first", id="cursor"),
    pytest.param(LimitOffsetGraphqlPagination, "limit", id="limit-offset"),
]


def _schema(paginator: Paginator) -> DjangoGraphQLSchema:
    """Build authors -> posts -> comments as nested paginated list wrappers.

    Args:
        paginator: Builds the paginator every list type uses.

    Returns:
        The schema.
    """
    shared = Registry()

    class CommentNode(DjangoObjectType):
        class Meta:
            model = Comment
            registry = shared

    class CommentList(DjangoListObjectType):
        class Meta:
            model = Comment
            registry = shared
            pagination = paginator()

    class PostNode(DjangoObjectType):
        class Meta:
            model = Post
            registry = shared
            only_fields = ("id", "comments")

    class PostList(DjangoListObjectType):
        class Meta:
            model = Post
            registry = shared
            pagination = paginator()

    class AuthorNode(DjangoObjectType):
        class Meta:
            model = Author
            registry = shared
            only_fields = ("id", "posts")

    class AuthorList(DjangoListObjectType):
        class Meta:
            model = Author
            registry = shared
            pagination = paginator()

    class Query(ObjectType):
        authors = DjangoListObjectField(AuthorList)

    return DjangoGraphQLSchema(query=Query, registries=isolated_pair(shared))


def _cost(schema: DjangoGraphQLSchema, query: str) -> int:
    """Estimate the cost of a query.

    Args:
        schema: The schema to cost against.
        query: The GraphQL document.

    Returns:
        The estimated total.
    """
    return analyze_cost(schema.graphql_schema, parse(query)).total


@pytest.mark.parametrize(("paginator", "arg"), PAGINATORS)
@pytest.mark.parametrize(
    ("authors", "posts", "comments"), [(10, 10, 10), (1, 10, 10), (3, 4, 5)]
)
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 100})
def test_nested_lists_scale_with_the_product_of_page_sizes(
    paginator: Paginator,
    arg: str,
    authors: int,
    posts: int,
    comments: int,
) -> None:
    """Each list level multiplies once, by its own page size.

    Every wrapper and every "results" costs 1; scalar leaves cost 0. So the
    three levels cost 2 + authors * (2 + posts * (2 + comments * 0)).

    Args:
        paginator: Builds the paginator of every list type.
        arg: The wire name of its page-size argument.
        authors: Page size of the author list.
        posts: Page size of each post list.
        comments: Page size of each comment list.
    """
    query = (
        "{ authors { results(%s: %d) { posts { results(%s: %d) {"
        " comments { results(%s: %d) { id } } } } } } }"
        % (arg, authors, arg, posts, arg, comments)
    )

    assert _cost(_schema(paginator), query) == 2 + authors * (2 + posts * 2)


@pytest.mark.parametrize(("paginator", "arg"), PAGINATORS)
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 100})
def test_page_size_changes_the_estimate(paginator: Paginator, arg: str) -> None:
    """A top-level page size of 1 costs less than one of 10.

    Args:
        paginator: Builds the paginator of every list type.
        arg: The wire name of its page-size argument.
    """
    schema = _schema(paginator)
    query = "{ authors { results(%s: %d) { posts { totalCount } } } }"

    assert _cost(schema, query % (arg, 1)) == 3
    assert _cost(schema, query % (arg, 10)) == 12


@pytest.mark.parametrize(("paginator", "arg"), PAGINATORS)
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 100})
def test_wide_and_count_only_queries(paginator: Paginator, arg: str) -> None:
    """Aliases add one list each; a wrapper read only for its count is not a list.

    Args:
        paginator: Builds the paginator of every list type.
        arg: The wire name of its page-size argument.
    """
    schema = _schema(paginator)
    wide = " ".join(f"a{i}: results({arg}: 100) {{ id }}" for i in range(500))

    assert _cost(schema, "{ authors { %s } }" % wide) == 501
    assert _cost(schema, "{ authors { totalCount } }") == 1


@pytest.mark.parametrize(("paginator", "arg"), PAGINATORS)
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 100})
def test_results_without_a_page_size_fall_back_once(
    paginator: Paginator, arg: str
) -> None:
    """A "results" with no page-size argument multiplies by MAX_PAGE_SIZE once.

    Args:
        paginator: Builds the paginator of every list type.
        arg: The wire name of its page-size argument (unused by the query).
    """
    query = "{ authors { results { posts { totalCount } } } }"

    assert _cost(_schema(paginator), query) == 2 + 100 * 1


@pytest.mark.django_db
@pytest.mark.parametrize(("paginator", "arg"), PAGINATORS)
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 100, "MAX_QUERY_COST": 1000})
def test_view_admits_a_nested_query_within_budget(
    paginator: Paginator, arg: str
) -> None:
    """A two-level nested query of about 100 rows passes a budget of 1000.

    Args:
        paginator: Builds the paginator of every list type.
        arg: The wire name of its page-size argument.
    """
    query = "{ authors { results(%s: 10) { posts { results(%s: 10) { id } } } } }" % (
        arg,
        arg,
    )
    request = RequestFactory().post(
        "/graphql/", json.dumps({"query": query}), content_type="application/json"
    )
    response = GraphQLView.as_view(schema=_schema(paginator))(request)
    body: dict[str, Any] = json.loads(response.content)

    assert response.status_code == 200, body
    assert "errors" not in body
