"""Preserve effective server queryset order before an ascending PK tie-break."""

from __future__ import annotations

import json
import re

import pytest
from django.db import connection
from django.db.models import F
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoNestedListObjectField
from django_graphex.paginations import (
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.views import GraphQLView

from ._schema_isolation import isolated_pair
from .models import Author, Post


def _model_type(name, base, meta, **attributes):
    """Build an isolated schema type with the requested metadata.

    Args:
        name: Name used for this schema type.
        base: GraphQL type base class.
        meta: Metadata attached to the type.
        **attributes: Optional methods and fields.

    Returns:
        An isolated GraphQL type.
    """
    attributes.update(__module__=__name__, __qualname__=name)
    attributes["Meta"] = type(
        "Meta", (), dict(meta, __module__=__name__, __qualname__=f"{name}.Meta")
    )
    return type(name, (base,), attributes)


def _schema(paginator, *, root_hook=None, nested_hook=None):
    """Build root and nested list fields over the same Post rows.

    Args:
        paginator: Pagination configuration for both Post fields.
        root_hook: Optional root queryset transform.
        nested_hook: Optional nested queryset transform.

    Returns:
        An isolated GraphQL schema.
    """
    registry = Registry()
    row_attributes = {}
    if root_hook is not None:
        row_attributes["get_queryset"] = classmethod(
            lambda cls, qs, info: root_hook(qs)
        )
    _model_type(
        "ServerOrderPost",
        DjangoObjectType,
        {
            "model": Post,
            "registry": registry,
            "only_fields": ("id", "title", "views", "author"),
        },
        **row_attributes,
    )
    posts = _model_type(
        "ServerOrderPosts",
        DjangoListObjectType,
        {"model": Post, "registry": registry, "pagination": paginator},
    )
    author_attributes = {"posts": DjangoNestedListObjectField(posts, accessor="posts")}
    if nested_hook is not None:
        author_attributes["optimize_posts"] = staticmethod(
            lambda qs, info, **kwargs: nested_hook(qs)
        )
    _model_type(
        "ServerOrderAuthor",
        DjangoObjectType,
        {"model": Author, "registry": registry, "only_fields": ("id", "posts")},
        **author_attributes,
    )
    authors = _model_type(
        "ServerOrderAuthors",
        DjangoListObjectType,
        {
            "model": Author,
            "registry": registry,
            "pagination": LimitOffsetGraphqlPagination(default_limit=7),
        },
    )
    query = type(
        "ServerOrderQuery",
        (ObjectType,),
        {
            "rows": DjangoListObjectField(posts),
            "authors": DjangoListObjectField(authors),
            "__module__": __name__,
        },
    )
    return DjangoGraphQLSchema(query=query, registries=isolated_pair(registry))


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["offset", "page"])
@pytest.mark.parametrize("location", ["root", "nested"])
@pytest.mark.parametrize("server_order", ["reverse", "extra"])
def test_server_queryset_order_precedes_ascending_pk(
    kind: str, location: str, server_order: str
) -> None:
    """Use Django's effective order in public HTTP and window SQL.

    Args:
        kind: Limit/offset or page-number paginator.
        location: Root field or reverse-FK nested field.
        server_order: Reversed explicit order or extra-order precedence.
    """
    author = Author.objects.create(pk=91, name="parent")
    for pk, title, views in (
        (41, "b", 1),
        (7, "a", 1),
        (29, "b", 2),
        (13, "a", 1),
        (53, "b", 1),
        (2, "a", 2),
        (37, "b", 1),
    ):
        Post.objects.create(pk=pk, title=title, views=views, author=author)

    if server_order == "reverse":

        def hook(qs):
            """Reverse the server queryset's title ordering."""
            return qs.order_by("title").reverse()

        expected = [29, 37]
        primary = "title"
        direction = "DESC"
    else:

        def hook(qs):
            """Let legacy extra ordering override the earlier title term."""
            return qs.order_by("-title").extra(order_by=["views"])

        expected = [7, 13]
        primary = "views"
        direction = "ASC"
    paginator = (
        LimitOffsetGraphqlPagination(default_limit=2)
        if kind == "offset"
        else PageGraphqlPagination(page_size=2)
    )
    schema = _schema(
        paginator,
        root_hook=hook if location == "root" else None,
        nested_hook=hook if location == "nested" else None,
    )
    query = (
        "{ rows { results { id } } }"
        if location == "root"
        else "{ authors { results { posts { results { id } } } } }"
    )
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": query}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN="proof",
    )
    with CaptureQueriesContext(connection) as captured:
        response = GraphQLView.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert response.status_code == 200 and "errors" not in payload, payload
    rows = (
        payload["data"]["rows"]["results"]
        if location == "root"
        else (payload["data"]["authors"]["results"][0]["posts"]["results"])
    )
    assert [int(row["id"]) for row in rows] == expected
    sql = " ".join(item["sql"] for item in captured.captured_queries)
    if location == "nested":
        assert "ROW_NUMBER() OVER" in sql
    assert re.search(rf'ORDER BY .*{primary}" {direction}, .*id" ASC', sql)


@pytest.mark.django_db
def test_reversed_orm_expression_and_requested_order_stay_distinct() -> None:
    """Reverse a trusted expression, but not a later client ordering term.

    The requested term must override a hook's earlier reversed direction.
    """
    author = Author.objects.create(name="parent")
    for pk, title in ((41, "b"), (29, "b"), (7, "a")):
        Post.objects.create(pk=pk, title=title, author=author)
    original = Post.objects.order_by(F("title").asc()).reverse()
    before = str(original.query)
    paginator = LimitOffsetGraphqlPagination(default_limit=2)
    result = paginator.paginate_queryset(original)
    assert [row.pk for row in result] == [29, 41]
    assert re.search(r'ORDER BY .*title" DESC, .*id" ASC', str(result.query))
    assert str(original.query) == before

    requested = paginator.paginate_queryset(original, ordering="title")
    assert [row.pk for row in requested] == [7, 29]
    assert re.search(r'ORDER BY .*title" ASC, .*id" ASC', str(requested.query))

    reversed_desc = paginator.paginate_queryset(
        Post.objects.order_by("-title").reverse()
    )
    assert [row.pk for row in reversed_desc] == [7, 29]
    assert re.search(r'ORDER BY .*title" ASC, .*id" ASC', str(reversed_desc.query))

    random_order = paginator.paginate_queryset(Post.objects.order_by("?").reverse())
    assert random_order.query.order_by == ("?", "id")
    assert re.search(r'ORDER BY .*id" ASC', str(random_order.query))


@pytest.mark.django_db
@pytest.mark.parametrize("term", ["rank", "tests_post.views"])
def test_extra_alias_and_dotted_server_terms_remain_orm_owned(term: str) -> None:
    """Keep trusted extra-order SQL terms ahead of the internal key.

    Args:
        term: A legacy extra-select alias or dotted SQL column.
    """
    author = Author.objects.create(name="parent")
    for pk, views in ((41, 2), (7, 1), (13, 1)):
        Post.objects.create(pk=pk, title="tied", views=views, author=author)
    original = Post.objects.extra(
        select={"rank": '"tests_post"."views"'}, order_by=[term]
    )
    paginator = LimitOffsetGraphqlPagination(default_limit=2)
    result = paginator.paginate_queryset(original)
    assert [row.pk for row in result] == [7, 13]
    assert result.query.extra_order_by == [term, "id"]
    assert original.query.extra_order_by == [term]


@pytest.mark.django_db
def test_extra_alias_nested_path_falls_back_without_losing_primary_order() -> None:
    """Use plain prefetch for an extra alias that window F cannot represent.

    The plain path must still retain the legacy extra-order precedence.
    """
    author = Author.objects.create(name="parent")
    for pk, views in ((41, 2), (7, 1), (13, 1)):
        Post.objects.create(pk=pk, title="tied", views=views, author=author)

    def hook(qs):
        """Order by an extra alias unsupported by window expressions."""
        return qs.extra(select={"rank": '"tests_post"."views"'}, order_by=["rank"])

    schema = _schema(LimitOffsetGraphqlPagination(default_limit=2), nested_hook=hook)
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": "{ authors { results { posts { results { id } } } } }"}),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN="proof",
    )
    with CaptureQueriesContext(connection) as captured:
        response = GraphQLView.as_view(schema=schema)(request)
    payload = json.loads(response.content)
    assert response.status_code == 200 and "errors" not in payload, payload
    rows = payload["data"]["authors"]["results"][0]["posts"]["results"]
    assert [int(row["id"]) for row in rows] == [7, 13]
    assert "ROW_NUMBER() OVER" not in " ".join(
        item["sql"] for item in captured.captured_queries
    )
