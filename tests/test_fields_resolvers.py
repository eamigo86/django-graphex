# -*- coding: utf-8 -*-
"""Resolver-branch coverage for the list fields in "fields.py".

Drives the "model" properties, the NonNull unwrap in "DjangoListField", the
"DjangoFilterListField" related-field (root is a model) and queryset-factory
fallbacks, the "DjangoFilterPaginateListField" extra-filters + pagination
branch, and the "DjangoNestedListObjectField" prefetch-cache / filtered /
materialize / None-root branches.
"""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.base_types import DjangoListObjectBase
from django_graphex.core import ObjectType
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListField,
    DjangoListObjectField,
    DjangoNestedListObjectField,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Category, Post, Tag

R = Registry()


class TagType(DjangoObjectType):
    """GraphQL type wrapping the "Tag" model, used for the NonNull-unwrap tests.

    Has no filters or nested fields of its own.
    """

    class Meta:
        """Meta options binding this type to "Tag" on the isolated test registry.

        No other options are set; defaults apply.
        """

        model = Tag
        registry = R


class PostType(DjangoObjectType):
    """GraphQL type wrapping the "Post" model, filterable by "title".

    Used both as a top-level type and nested under "CategoryType".
    """

    class Meta:
        """Meta options binding this type to "Post" with a "title" filter.

        Supports "icontains" and "exact" lookups on "title".
        """

        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class CategoryType(DjangoObjectType):
    """GraphQL type wrapping "Category", exposing nested filtered and paginated post lists.

    Drives the related-field and extra-filters-scoping test coverage.
    """

    class Meta:
        """Meta options binding this type to "Category" on the isolated test registry.

        No other options are set; defaults apply.
        """

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
    """GraphQL type wrapping the "Author" model, used for the paginated authors field.

    Has no filters or nested fields of its own.
    """

    class Meta:
        """Meta options binding this type to "Author" on the isolated test registry.

        No other options are set; defaults apply.
        """

        model = Author
        registry = R


class PostListType(DjangoListObjectType):
    """List-object GraphQL type wrapping "Post", filterable by "title".

    Backs the top-level "posts" field on "Query" and the direct
    "list_resolver" unit tests.
    """

    class Meta:
        """Meta options binding this list type to "Post" with a "title" filter.

        Supports "icontains" and "exact" lookups on "title".
        """

        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class Query(ObjectType):
    """Query root exposing the categories/authors/posts fields under test.

    Each field exercises a different list-field flavor (filter, paginate,
    list-object).
    """

    categories = DjangoFilterListField(CategoryType)
    authors = DjangoFilterPaginateListField(AuthorType)
    posts = DjangoListObjectField(PostListType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))


# --------------------------------------------------------------------------- #
# .model property exercised on each field                                       #
# --------------------------------------------------------------------------- #
def test_list_object_field_model_property() -> None:
    """ ""DjangoListObjectField.model"" must read the model straight off "self.type._meta.model".

    If this breaks, callers relying on ".model" to introspect a list-object
    field could get the wrong model or an exception.
    """
    # DjangoListObjectField.model reads self.type._meta.model directly -> works.
    assert DjangoListObjectField(PostListType).model is Post


def test_filter_list_field_model_property() -> None:
    """ ""DjangoFilterListField.model"" must unwrap List/NonNull wrappers before reading "_meta.model".

    If this breaks, ".model" could raise or return the wrapper type
    instead of the underlying Django model.
    """
    # `.model` unwraps the List/NonNull wrappers and reads `_meta.model`.
    assert DjangoFilterListField(CategoryType).model is Category


def test_filter_paginate_list_field_model_property() -> None:
    """ ""DjangoFilterPaginateListField.model"" must resolve to the underlying Django model.

    If this breaks, pagination-aware list fields could fail to introspect
    their bound model.
    """
    assert DjangoFilterPaginateListField(AuthorType).model is Author


def test_object_field_model_property() -> None:
    """ ""DjangoObjectField.model"" must resolve to the underlying Django model.

    If this breaks, single-object fields could fail to introspect their
    bound model.
    """
    from django_graphex.fields import DjangoObjectField

    assert DjangoObjectField(PostType).model is Post


def test_django_list_field_unwraps_nonnull() -> None:
    """ ""DjangoListField"" wrapping a NonNull type must not double-wrap the list in an extra NonNull layer.

    "DjangoListField" is off graphene; ".type" is the native wrapper
    currency ("NativeList"/"NativeNonNull") -- the same "[Tag!]" shape, no
    graphene List. "NativeNonNull" is the lazy native wrapper that can hold
    a DjangoObjectType class (the graphene NonNull replacement); the field
    must unwrap it so the outer list is not doubled. If this breaks, the
    generated schema could render "[Tag!!]" or otherwise mis-shape the
    list type.
    """
    from django_graphex.core.descriptors import NativeList, NativeNonNull

    field = DjangoListField(NativeNonNull(TagType))
    # The outer wrapper is NativeList(NativeNonNull(TagType)); the inner NonNull
    # was unwrapped so it is not doubled (no [Tag!!]).
    assert isinstance(field.type, NativeList)
    assert isinstance(field.type.of_type, NativeNonNull)
    assert field.type.of_type.of_type is TagType


def test_filter_list_field_explicit_description_kept() -> None:
    """An explicit "description" argument must bypass the auto-generated "<Model> list" default.

    If this breaks, a caller-supplied description could be silently
    overridden by the auto-generated default.
    """
    # An explicit description bypasses the auto "<Model> list" default (171->174).
    field = DjangoFilterListField(CategoryType, description="Custom desc")
    assert field.description == "Custom desc"


def test_paginate_field_without_pagination_runs_resolver(db: None) -> None:
    """With no default or explicit pagination class, the resolver must skip pagination and still return results.

    Args:
        db: The pytest-django fixture granting database access for this
            test.

    If this breaks, a field with pagination disabled entirely could crash
    the resolver instead of falling through to the unpaginated branch.
    """
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
        """Ad hoc query root exposing the pagination-disabled field under test."""

        items = field

    s = DjangoGraphQLSchema(query=_Q, registries=isolated_pair(R))
    result = graphql_sync(s.graphql_schema, "{ items { title } }")
    assert result.errors is None, result.errors
    assert [p["title"] for p in result.data["items"]] == ["p1"]


class FilterListRelatedFieldTest(TestCase):
    """Coverage of "DjangoFilterListField" root-model detection: related-field vs top-level.

    Compares the nested (related-manager) path against the top-level
    (queryset-factory) path.
    """

    def test_nested_filter_list_uses_related_manager(self) -> None:
        """A nested "posts" field under "Category" must filter through the related manager, not all posts.

        If this breaks, the related-field branch could ignore the parent
        category and leak posts from other categories, or fail to apply
        the filter at all.
        """
        # Category -> posts (DjangoFilterListField) exercises the related-field
        # branch (root is a Django model; find_field matches the relation).
        author = Author.objects.create(name="A")
        cat = Category.objects.create(title="C")
        Post.objects.create(title="keep", author=author, category=cat)
        Post.objects.create(title="drop", author=author, category=cat)

        result = graphql_sync(
            schema.graphql_schema,
            '{ categories { title posts(filter: { title: { icontains: "keep" } })'
            " { title } } }",
        )
        assert result.errors is None, result.errors
        cats = result.data["categories"]
        assert len(cats) == 1
        assert [p["title"] for p in cats[0]["posts"]] == ["keep"]

    def test_top_level_filter_list_no_root(self) -> None:
        """A top-level "categories" query (no parent root) must fall back to the queryset-factory path.

        If this breaks, top-level filter-list fields without a root value
        could crash instead of using the queryset factory fallback.
        """
        # No root -> queryset_factory fallback path.
        Category.objects.create(title="Solo")
        result = graphql_sync(schema.graphql_schema, "{ categories { title } }")
        assert result.errors is None, result.errors
        assert {c["title"] for c in result.data["categories"]} == {"Solo"}


class FilterPaginateExtraFiltersTest(TestCase):
    """Coverage of "DjangoFilterPaginateListField" extra-filters scoping plus pagination.

    Confirms each parent category only sees its own posts even when
    "limit" caps the result set.
    """

    def test_nested_paginate_list_applies_extra_filters_and_pagination(self) -> None:
        """A nested "paginatedPosts" field must scope results to its parent category and honor "limit".

        If this breaks, the extra-filters mechanism could leak posts
        across categories, or pagination could be silently skipped on the
        nested path.
        """
        # Category -> paginatedPosts (DjangoFilterPaginateListField): root is a
        # model so extra_filters scope to that category, and pagination runs.
        author = Author.objects.create(name="A")
        c1 = Category.objects.create(title="C1")
        c2 = Category.objects.create(title="C2")
        Post.objects.create(title="p1", author=author, category=c1)
        Post.objects.create(title="p2", author=author, category=c1)
        Post.objects.create(title="other", author=author, category=c2)

        result = graphql_sync(
            schema.graphql_schema,
            "{ categories { title paginatedPosts(limit: 5) { title } } }",
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
    """Direct coverage of "DjangoNestedListObjectField.list_resolver" branch selection.

    Exercises the None-root, prefetch-cache-hit, filtered, and
    materialize-from-manager branches.
    """

    def _field(self) -> DjangoNestedListObjectField:
        return DjangoNestedListObjectField(PostListType, accessor="posts")

    def test_none_root_returns_empty(self) -> None:
        """A None root must resolve to an empty "DjangoListObjectBase" instead of raising.

        If this breaks, a nested field resolved with no parent instance
        could crash instead of degrading to an empty result.
        """
        field = self._field()
        # output_type is the 3rd positional arg (added in #58b); nested path
        # ignores it (None is the documented sentinel for nested fields).
        out = field.list_resolver(None, field.filter_backend, None, None, None)
        assert isinstance(out, DjangoListObjectBase)
        assert out.count == 0

    def test_prefetch_cache_hit_avoids_query(self) -> None:
        """When the parent's relation is already prefetched, the resolver must serve it from memory, issuing zero queries.

        If this breaks, nested list resolution could silently re-query the
        database even when Django already prefetched the relation,
        defeating the point of "prefetch_related".
        """
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

    def test_filtered_runs_db_query(self) -> None:
        """A "filter" argument must force a real database query instead of using the prefetch cache.

        If this breaks, a filtered nested query could incorrectly return
        the full unfiltered prefetch-cache contents.
        """
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

    def test_unfiltered_not_prefetched_materializes(self) -> None:
        """With no prefetch cache and no filter, the resolver must materialize the relation via the manager.

        If this breaks, an unfiltered nested field on a fresh (unprefetched)
        instance could return an empty or incorrect result instead of
        falling through to the manager-materialize branch.
        """
        author = Author.objects.create(name="A")
        Post.objects.create(title="p1", author=author)
        # Fresh instance, no prefetch cache, no filter -> materialize branch.
        author = Author.objects.get(pk=author.pk)
        field = self._field()
        out = field.list_resolver(None, field.filter_backend, None, author, None)
        assert out.count == 1
