# -*- coding: utf-8 -*-
"""Plain-pk native filtering (the replacement for the old plain-ID filter).

``id: { exact }`` / ``id: { in }`` filter a model by its own primary key, and a
relation declared directly (e.g. ``author: { exact }``) filters by the related
pk -- for both integer and UUID primary keys.
"""

from graphql import graphql_sync

from django_graphex import (
    DjangoGraphQLSchema,
    DjangoListObjectField,
    DjangoListObjectType,
    ObjectType,
)
from django_graphex.registry import Registry

from ._schema_isolation import isolated_pair
from .models import Author, Post, UUIDItem, UUIDThing

R = Registry()


class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        registry = R
        filter_fields = {"id": ("exact", "in"), "author": ("exact", "in")}


class UUIDThingListType(DjangoListObjectType):
    class Meta:
        model = UUIDThing
        registry = R
        filter_fields = {"id": ("exact", "in")}


class UUIDItemListType(DjangoListObjectType):
    class Meta:
        model = UUIDItem
        registry = R
        filter_fields = {"thing": ("exact", "in")}


class Query(ObjectType):
    posts = DjangoListObjectField(PostListType)
    things = DjangoListObjectField(UUIDThingListType)
    items = DjangoListObjectField(UUIDItemListType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))


def _exec(query):
    result = graphql_sync(schema.graphql_schema, query)
    assert result.errors is None, result.errors
    return result.data


# -- the generated `filter` argument exposes an input type, not a flat `id` --- #
def test_filter_argument_shape():
    args = schema.graphql_schema.query_type.fields["posts"].args
    assert "filter" in args
    # No flat per-field arguments anymore.
    assert "id" not in args
    assert "author" not in args


# -- filter by own integer id via exact / in --------------------------------- #
def test_filter_by_id_exact(db):
    a = Author.objects.create(name="A")
    p1 = Post.objects.create(title="p1", author=a)
    Post.objects.create(title="p2", author=a)

    data = _exec(
        "{ posts(filter: { id: { exact: %d } }) { results { title } } }" % p1.pk
    )
    titles = [r["title"] for r in data["posts"]["results"]]
    assert titles == ["p1"]


def test_filter_by_id_in(db):
    a = Author.objects.create(name="A")
    p1 = Post.objects.create(title="p1", author=a)
    p2 = Post.objects.create(title="p2", author=a)
    Post.objects.create(title="p3", author=a)

    data = _exec(
        "{ posts(filter: { id: { in: [%d, %d] } }) { results { title } } }"
        % (p1.pk, p2.pk)
    )
    titles = sorted(r["title"] for r in data["posts"]["results"])
    assert titles == ["p1", "p2"]


# -- filter by a related (integer) author id --------------------------------- #
def test_filter_by_related_integer_id(db):
    a1 = Author.objects.create(name="A1")
    a2 = Author.objects.create(name="A2")
    Post.objects.create(title="p1", author=a1)
    Post.objects.create(title="p2", author=a2)

    data = _exec(
        "{ posts(filter: { author: { exact: %d } }) { results { title } } }" % a1.pk
    )
    titles = [r["title"] for r in data["posts"]["results"]]
    assert titles == ["p1"]


# -- filter a UUID-pk model by its own id ------------------------------------ #
def test_filter_by_uuid_primary_key(db):
    t1 = UUIDThing.objects.create(name="t1")
    UUIDThing.objects.create(name="t2")

    data = _exec(
        '{ things(filter: { id: { exact: "%s" } }) { results { name } } }' % t1.id
    )
    names = [r["name"] for r in data["things"]["results"]]
    assert names == ["t1"]


# -- filter by a related UUID id --------------------------------------------- #
def test_filter_by_related_uuid_id(db):
    t1 = UUIDThing.objects.create(name="t1")
    t2 = UUIDThing.objects.create(name="t2")
    UUIDItem.objects.create(label="i1", thing=t1)
    UUIDItem.objects.create(label="i2", thing=t2)

    data = _exec(
        '{ items(filter: { thing: { exact: "%s" } }) { results { label } } }' % t1.id
    )
    labels = [r["label"] for r in data["items"]["results"]]
    assert labels == ["i1"]


# -- an empty filter is a no-op ---------------------------------------------- #
def test_empty_filter_returns_full_queryset(db):
    a = Author.objects.create(name="A")
    Post.objects.create(title="p1", author=a)
    Post.objects.create(title="p2", author=a)

    data = _exec("{ posts(filter: {}) { results { title } totalCount } }")
    assert data["posts"]["totalCount"] == 2
