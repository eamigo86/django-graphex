# -*- coding: utf-8 -*-
"""Resolver-branch coverage for the list fields in ``fields.py``.

Drives the ``model`` properties, the NonNull unwrap in ``DjangoListField``, the
``DjangoFilterListField`` related-field (root is a model) and queryset-factory
fallbacks, the ``DjangoFilterPaginateListField`` extra-filters + pagination
branch, and the ``DjangoNestedListObjectField`` prefetch-cache / filtered /
materialize / None-root branches.
"""

import graphene
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphene import NonNull
from graphql import graphql_sync

from django_graphex import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoGraphQLSchema,
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
    LimitOffsetGraphqlPagination,
    ObjectType,
)
from django_graphex.base_types import DjangoListObjectBase
from django_graphex.fields import (
    DjangoListField,
    DjangoNestedListObjectField,
)
from django_graphex.registry import Registry

from ._schema_isolation import isolated_pair
from .models import Author, Category, Post, Tag

R = Registry()


class TagType(DjangoObjectType):
    class Meta:
        model = Tag
        registry = R


class PostType(DjangoObjectType):
    class Meta:
        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class CategoryType(DjangoObjectType):
    class Meta:
        model = Category
        registry = R

    # A nested filtered list on the related set (drives the related-field path).
    posts = DjangoFilterListField(PostType)
    # And a paginated nested list (drives extra_filters + pagination). Category
    # has a single relation to Post (`category`), so extra_filters is unambiguous.
    paginated_posts = DjangoFilterPaginateListField(
        PostType, pagination=LimitOffsetGraphqlPagination()
    )


class AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        registry = R


class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class Query(ObjectType):
    categories = DjangoFilterListField(CategoryType)
    authors = DjangoFilterPaginateListField(AuthorType)
    posts = DjangoListObjectField(PostListType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))


# --------------------------------------------------------------------------- #
# .model property exercised on each field                                       #
# --------------------------------------------------------------------------- #
def test_list_object_field_model_property():
    # DjangoListObjectField.model reads self.type._meta.model directly -> works.
    assert DjangoListObjectField(PostListType).model is Post


def test_filter_list_field_model_property():
    # `.model` unwraps the List/NonNull wrappers and reads `_meta.model`.
    assert DjangoFilterListField(CategoryType).model is Category


def test_filter_paginate_list_field_model_property():
    assert DjangoFilterPaginateListField(AuthorType).model is Author


def test_object_field_model_property():
    from django_graphex import DjangoObjectField

    assert DjangoObjectField(PostType).model is Post


def test_django_list_field_unwraps_nonnull():
    # Passing a NonNull(type) -> unwrapped before wrapping in NativeList(NativeNonNull(...)).
    # S8c: DjangoListField is off graphene; ``.type`` is the native wrapper currency
    # (NativeList / NativeNonNull) — the SAME ``[Tag!]`` shape, no graphene List.
    from django_graphex.native.descriptors import NativeList, NativeNonNull

    field = DjangoListField(NonNull(TagType))
    # The outer wrapper is NativeList(NativeNonNull(TagType)); the inner (graphene)
    # NonNull was unwrapped so it is not doubled (no [Tag!!]).
    assert isinstance(field.type, NativeList)
    assert isinstance(field.type.of_type, NativeNonNull)
    assert field.type.of_type.of_type is TagType


def test_filter_list_field_explicit_description_kept():
    # An explicit description bypasses the auto "<Model> list" default (171->174).
    field = DjangoFilterListField(CategoryType, description="Custom desc")
    assert field.description == "Custom desc"


def test_paginate_field_without_pagination_runs_resolver(db):
    # DEFAULT_PAGINATION_CLASS None + pagination None -> no paginator; the
    # resolver skips the pagination branch (355->358).
    from unittest.mock import patch

    with patch(
        "django_graphex.fields.graphql_api_settings.DEFAULT_PAGINATION_CLASS",
        None,
    ):
        field = DjangoFilterPaginateListField(PostType)
    assert getattr(field, "pagination", None) is None

    author = Author.objects.create(name="A")
    Post.objects.create(title="p1", author=author)

    class _Q(ObjectType):
        items = field

    s = DjangoGraphQLSchema(query=_Q, registries=isolated_pair(R))
    result = graphql_sync(s.graphql_schema, "{ items { title } }")
    assert result.errors is None, result.errors
    assert [p["title"] for p in result.data["items"]] == ["p1"]


class FilterListRelatedFieldTest(TestCase):
    def test_nested_filter_list_uses_related_manager(self):
        # Category -> posts (DjangoFilterListField) exercises the related-field
        # branch (root is a Django model; find_field matches the relation).
        author = Author.objects.create(name="A")
        cat = Category.objects.create(title="C")
        Post.objects.create(title="keep", author=author, category=cat)
        Post.objects.create(title="drop", author=author, category=cat)

        result = graphql_sync(schema.graphql_schema, 
            '{ categories { title posts(filter: { title: { icontains: "keep" } })'
            " { title } } }"
        )
        assert result.errors is None, result.errors
        cats = result.data["categories"]
        assert len(cats) == 1
        assert [p["title"] for p in cats[0]["posts"]] == ["keep"]

    def test_top_level_filter_list_no_root(self):
        # No root -> queryset_factory fallback path.
        Category.objects.create(title="Solo")
        result = graphql_sync(schema.graphql_schema, "{ categories { title } }")
        assert result.errors is None, result.errors
        assert {c["title"] for c in result.data["categories"]} == {"Solo"}


class FilterPaginateExtraFiltersTest(TestCase):
    def test_nested_paginate_list_applies_extra_filters_and_pagination(self):
        # Category -> paginatedPosts (DjangoFilterPaginateListField): root is a
        # model so extra_filters scope to that category, and pagination runs.
        author = Author.objects.create(name="A")
        c1 = Category.objects.create(title="C1")
        c2 = Category.objects.create(title="C2")
        Post.objects.create(title="p1", author=author, category=c1)
        Post.objects.create(title="p2", author=author, category=c1)
        Post.objects.create(title="other", author=author, category=c2)

        result = graphql_sync(schema.graphql_schema, 
            "{ categories { title paginatedPosts(limit: 5) { title } } }"
        )
        assert result.errors is None, result.errors
        rows = {
            c["title"]: [p["title"] for p in c["paginatedPosts"]]
            for c in result.data["categories"]
        }
        # Each category only sees its own posts (extra_filters scoping).
        assert sorted(rows["C1"]) == ["p1", "p2"]
        assert rows["C2"] == ["other"]


# --------------------------------------------------------------------------- #
# DjangoNestedListObjectField.list_resolver branches (direct)                   #
# --------------------------------------------------------------------------- #
class NestedListResolverTest(TestCase):
    def _field(self):
        return DjangoNestedListObjectField(PostListType, accessor="posts")

    def test_none_root_returns_empty(self):
        field = self._field()
        # output_type is the 3rd positional arg (added in #58b); nested path
        # ignores it (None is the documented sentinel for nested fields).
        out = field.list_resolver(None, field.filter_backend, None, None, None)
        assert isinstance(out, DjangoListObjectBase)
        assert out.count == 0

    def test_prefetch_cache_hit_avoids_query(self):
        author = Author.objects.create(name="A")
        Post.objects.create(title="p1", author=author)
        Post.objects.create(title="p2", author=author)

        # Prime the prefetch cache so the resolver reads it in memory.
        author = Author.objects.prefetch_related("posts").get(pk=author.pk)
        field = self._field()
        with CaptureQueriesContext(connection) as ctx:
            out = field.list_resolver(None, field.filter_backend, None, author, None)
        assert out.count == 2
        assert len(ctx.captured_queries) == 0  # served from prefetch cache

    def test_filtered_runs_db_query(self):
        author = Author.objects.create(name="A")
        Post.objects.create(title="keep", author=author)
        Post.objects.create(title="drop", author=author)

        field = DjangoNestedListObjectField(
            PostListType, accessor="posts", fields={"title": ["icontains"]}
        )
        out = field.list_resolver(
            None,
            field.filter_backend,
            None,
            author,
            None,
            filter={"title": {"icontains": "keep"}},
        )
        assert out.count == 1

    def test_unfiltered_not_prefetched_materializes(self):
        author = Author.objects.create(name="A")
        Post.objects.create(title="p1", author=author)
        # Fresh instance, no prefetch cache, no filter -> materialize branch.
        author = Author.objects.get(pk=author.pk)
        field = self._field()
        out = field.list_resolver(None, field.filter_backend, None, author, None)
        assert out.count == 1
