"""Regression tests for automatic nullable-column pagination order."""

from __future__ import annotations

import json

import pytest
from django.db import connection
from django.db.models import F
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoNestedListObjectField
from django_graphex.paginations.pagination import (
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
    _automatic_null_ordering,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView

from ._schema_isolation import isolated_pair
from .models import Author, Category, Post


def _model_type(
    name: str, base: type, meta: dict[str, object], **attributes: object
) -> type:
    """Build an isolated model-backed type for the nullable-order schema.

    Args:
        name: Distinct native type name.
        base: Native GraphQL type base.
        meta: Model and registry metadata.
        **attributes: Additional declared fields or methods.

    Returns:
        The isolated model-backed type.
    """
    metadata = type(
        "Meta", (), dict(meta, __module__=__name__, __qualname__=f"{name}.Meta")
    )
    attributes.update(Meta=metadata, __module__=__name__, __qualname__=name)
    return type(name, (base,), attributes)


def _nested_schema(paginator: object) -> DjangoGraphQLSchema:
    """Expose a nullable ordering column on an actual nested GraphQL list.

    Args:
        paginator: Offset-based or page-number pagination configuration.

    Returns:
        An isolated native schema with author posts.
    """
    registry = Registry()
    _model_type(
        "NullOrderCategory",
        DjangoObjectType,
        {"model": Category, "registry": registry, "only_fields": ("id",)},
    )
    _model_type(
        "NullOrderPost",
        DjangoObjectType,
        {
            "model": Post,
            "registry": registry,
            "only_fields": ("id", "title", "category", "author"),
        },
    )
    posts = _model_type(
        "NullOrderPosts",
        DjangoListObjectType,
        {"model": Post, "registry": registry, "pagination": paginator},
    )
    _model_type(
        "NullOrderAuthor",
        DjangoObjectType,
        {
            "model": Author,
            "registry": registry,
            "only_fields": ("id", "posts"),
        },
        posts=DjangoNestedListObjectField(posts, accessor="posts"),
    )
    authors = _model_type(
        "NullOrderAuthors",
        DjangoListObjectType,
        {
            "model": Author,
            "registry": registry,
            "pagination": LimitOffsetGraphqlPagination(default_limit=2),
        },
    )
    query = type(
        "NullOrderQuery",
        (ObjectType,),
        {
            "authors": DjangoListObjectField(authors),
            "__module__": __name__,
            "__qualname__": "NullOrderQuery",
        },
    )
    return DjangoGraphQLSchema(query=query, registries=isolated_pair(registry))


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["offset", "page"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_nullable_queryset_and_materialized_pages_agree(
    kind: str, direction: str
) -> None:
    """Place nulls last ascending and first descending for both row sources.

    Args:
        kind: Offset-based or page-number pagination.
        direction: Ascending or descending nullable-column order.
    """
    author = Author.objects.create(name="author")
    low = Category.objects.create(pk=1, title="low")
    high = Category.objects.create(pk=2, title="high")
    for pk, category in ((40, None), (10, high), (30, low), (20, None)):
        Post.objects.create(pk=pk, title=f"post-{pk}", author=author, category=category)

    paginator = (
        LimitOffsetGraphqlPagination(default_limit=4, max_limit=4)
        if kind == "offset"
        else PageGraphqlPagination(page_size=4, max_page_size=4)
    )
    ordering = "category_id" if direction == "asc" else "-category_id"
    expected = [30, 10, 20, 40] if direction == "asc" else [20, 40, 10, 30]
    queryset_page = paginator.paginate_queryset(Post.objects.all(), ordering=ordering)
    list_page = paginator.paginate_queryset(
        list(Post.objects.order_by("-pk")), ordering=ordering
    )

    assert [row.pk for row in list_page] == expected
    assert [row.pk for row in queryset_page] == expected


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["offset", "page"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
@pytest.mark.parametrize("optimized", [True, False])
def test_nested_nullable_order_matches_window_and_plain_prefetch(
    kind: str, direction: str, optimized: bool
) -> None:
    """Keep nested public pages consistent across optimized and fallback paths.

    Args:
        kind: Offset-based or page-number pagination.
        direction: Ascending or descending nullable-column order.
        optimized: Whether the nested SQL window path is enabled.
    """
    author = Author.objects.create(name="parent")
    low = Category.objects.create(pk=1, title="low")
    high = Category.objects.create(pk=2, title="high")
    for pk, category in ((40, None), (10, high), (30, low), (20, None)):
        Post.objects.create(pk=pk, title=f"post-{pk}", author=author, category=category)

    order = "categoryId" if direction == "asc" else "-categoryId"
    paginator = (
        LimitOffsetGraphqlPagination(default_limit=2)
        if kind == "offset"
        else PageGraphqlPagination(page_size=2)
    )
    schema = _nested_schema(paginator)
    query = (
        "{ authors { results { posts { results"
        f'(ordering: "{order}") {{ id }}'
        " } } } }"
    )
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": query}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN="proof",
    )
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_NESTED_PAGINATION": optimized}):
        with CaptureQueriesContext(connection) as captured:
            response = GraphQLView.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert response.status_code == 200 and "errors" not in payload, payload
    rows = payload["data"]["authors"]["results"][0]["posts"]["results"]
    expected = [30, 10] if direction == "asc" else [20, 40]
    assert [int(row["id"]) for row in rows] == expected
    sql = " ".join(item["sql"] for item in captured.captured_queries)
    assert ("ROW_NUMBER() OVER" in sql) is optimized


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["offset", "page"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_explicit_orm_null_placement_remains_authoritative(
    kind: str, direction: str
) -> None:
    """Preserve caller expressions even when their null policy differs.

    Args:
        kind: Offset-based or page-number pagination.
        direction: Explicit ascending or descending expression direction.
    """
    author = Author.objects.create(name="author")
    category = Category.objects.create(title="present")
    Post.objects.create(pk=20, title="null", author=author)
    Post.objects.create(pk=10, title="present", author=author, category=category)
    expression = (
        F("category_id").asc(nulls_first=True)
        if direction == "asc"
        else F("category_id").desc(nulls_last=True)
    )
    original = Post.objects.order_by(expression)
    paginator = (
        LimitOffsetGraphqlPagination(default_limit=2)
        if kind == "offset"
        else PageGraphqlPagination(page_size=2)
    )
    result = paginator.paginate_queryset(original)
    assert result.query.order_by[0] is expression
    assert original.query.order_by == (expression,)
    assert [row.pk for row in result] == ([20, 10] if direction == "asc" else [10, 20])


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["offset", "page"])
def test_multifield_priority_and_relation_name_remain_intact(kind: str) -> None:
    """Keep secondary direction, PK ties, and relation-name ORM terms.

    Args:
        kind: Offset-based or page-number pagination.
    """
    author = Author.objects.create(name="author")
    category = Category.objects.create(title="present")
    for pk, attached, views in (
        (40, None, 1),
        (20, category, 2),
        (30, category, 2),
        (10, category, 3),
    ):
        Post.objects.create(
            pk=pk, title=f"post-{pk}", author=author, category=attached, views=views
        )
    paginator = (
        LimitOffsetGraphqlPagination(default_limit=4)
        if kind == "offset"
        else PageGraphqlPagination(page_size=4)
    )
    page = paginator.paginate_queryset(
        Post.objects.all(), ordering="category_id,-views"
    )
    assert [row.pk for row in page] == [10, 20, 30, 40]
    relation_order = paginator.paginate_queryset(Post.objects.order_by("category"))
    assert relation_order.query.order_by == ("category", "id")


def test_malformed_prefix_is_not_normalized_into_a_valid_column() -> None:
    """Leave an invalid server ordering spelling for Django to reject."""
    assert _automatic_null_ordering(Post, ["--category_id"]) == ["--category_id"]
