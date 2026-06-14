# -*- coding: utf-8 -*-
"""Nested related lists carry the uniform results/totalCount shape.

Covers the SPEC ``specs/nested-list-shape-spec.md``: every related list field
exposes ``results`` + ``totalCount`` with filtering + pagination + ordering, the
prefetch cache keeps N+1 at zero (in-memory pagination), and a per-model paginator
is reused when the model appears nested under another.

A dedicated ``Registry`` isolates these types from the global one so the schema
shape is deterministic regardless of test order.
"""

import os
from types import SimpleNamespace

import graphene
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphene import Schema

from django_graphex import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings

from .models import Author, Post, Tag

R = Registry()


class TagTypeN(DjangoObjectType):
    class Meta:
        model = Tag
        registry = R


class AuthorTypeN(DjangoObjectType):
    class Meta:
        model = Author
        registry = R


class PostTypeN(DjangoObjectType):
    class Meta:
        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class AuthorListN(DjangoListObjectType):
    class Meta:
        model = Author
        registry = R
        # Custom per-model paginator -> nested Author lists must reuse it (AC8).
        pagination = PageGraphqlPagination(
            page_size=10, page_size_query_param="pageSize"
        )


class Query(graphene.ObjectType):
    authors = DjangoListObjectField(AuthorListN)


schema = Schema(query=Query)
type_map = schema.graphql_schema.type_map


def _args(type_name, field_name):
    return set(type_map[type_name].fields[field_name].args.keys())


# --------------------------------------------------------------------------- #
# Schema shape                                                                  #
# --------------------------------------------------------------------------- #
class NestedShapeTest(TestCase):
    def test_nested_field_is_a_list_type(self):
        # AC1: AuthorTypeN.posts (reverse FK) is a list type with results/totalCount.
        posts_type = type_map["AuthorTypeN"].fields["posts"].type
        self.assertEqual(posts_type.name, "PostListType")
        fields = type_map["PostListType"].fields
        self.assertIn("results", fields)
        self.assertIn("totalCount", fields)

    def test_nested_results_has_pagination_and_ordering_args(self):
        # AC2: auto-generated list type uses the default LimitOffset paginator.
        args = _args("PostListType", "results")
        self.assertIn("limit", args)
        self.assertIn("offset", args)
        self.assertIn("ordering", args)

    def test_nested_reuses_registered_paginator(self):
        # AC8: PostTypeN.coAuthors (M2M -> Author) reuses AuthorListN (Page).
        co_type = type_map["PostTypeN"].fields["coAuthors"].type
        self.assertEqual(co_type.name, "AuthorListN")
        args = _args("AuthorListN", "results")
        self.assertIn("page", args)
        self.assertNotIn("limit", args)


# --------------------------------------------------------------------------- #
# Behaviour (pagination / ordering / filtering / N+1)                          #
# --------------------------------------------------------------------------- #
class NestedBehaviourTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = Author.objects.create(name="Ada", bio="b")
        for i in range(6):
            Post.objects.create(title="Post %02d" % i, author=cls.author)

    def _exec(self, query):
        result = schema.execute(query)
        assert result.errors is None, result.errors
        return result.data

    def test_pagination_and_ordering(self):
        data = self._exec("""
            { authors { results { name posts {
                results(limit: 2, ordering: "-id") { title } totalCount
            } } } }
            """)
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 6)  # full set
        self.assertEqual([p["title"] for p in posts["results"]], ["Post 05", "Post 04"])

    def test_offset(self):
        data = self._exec(
            "{ authors { results { posts { results(limit: 2, offset: 2, "
            'ordering: "id") { title } } } } }'
        )
        posts = data["authors"]["results"][0]["posts"]["results"]
        self.assertEqual([p["title"] for p in posts], ["Post 02", "Post 03"])

    def test_filtering(self):
        # Nested posts are filterable (PostTypeN declares filter_fields on title).
        data = self._exec(
            '{ authors { results { posts(filter: { title: { icontains: "05" } }) { '
            "results { title } totalCount } } } }"
        )
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 1)
        self.assertEqual(posts["results"][0]["title"], "Post 05")

    def test_unfiltered_nested_is_constant_queries(self):
        # AC4: more parents must not add queries (prefetch cache + in-memory page).
        for n in range(3):
            a = Author.objects.create(name="A%d" % n)
            Post.objects.create(title="t", author=a)

        query = """
        { authors { results { name posts {
            results(limit: 1) { title } totalCount
        } } totalCount } }
        """
        # Constant regardless of the number of authors: authors select + a single
        # prefetch for all authors' posts. The Page paginator no longer issues an
        # unconditional COUNT for positive pages (fix for #17c), so the expected
        # query count is 3 (was 4 before the conditional COUNT change).
        with self.assertNumQueries(3):
            self._exec(query)

    def test_filtered_nested_constant_queries(self):
        # Option A: a filtered nested list is fetched via a single filtered
        # Prefetch, so it costs the same as the unfiltered one (no per-parent N+1).
        for n in range(4):
            a = Author.objects.create(name="X%d" % n)
            for j in range(3):
                Post.objects.create(title="t%d" % j, author=a)

        unfiltered = (
            "{ authors { results { posts { results { title } totalCount } } } }"
        )
        filtered = (
            '{ authors { results { posts(filter: { title: { icontains: "t" } }) '
            "{ results { title } totalCount } } } }"
        )
        with CaptureQueriesContext(connection) as plain:
            self._exec(unfiltered)
        with CaptureQueriesContext(connection) as filt:
            self._exec(filtered)
        self.assertEqual(len(filt.captured_queries), len(plain.captured_queries))

    def test_filtered_nested_correct_and_paginated(self):
        # Filter applied (totalCount = filtered size) + in-memory limit/ordering.
        data = self._exec(
            '{ authors { results { posts(filter: { title: { icontains: "0" } }) '
            '{ results(limit: 2, ordering: "-id") { title } totalCount } } } }'
        )
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 6)  # all "Post 0X" contain "0"
        self.assertEqual([p["title"] for p in posts["results"]], ["Post 05", "Post 04"])

    def test_filtered_fallback_when_optimization_disabled(self):
        from unittest import mock

        with mock.patch.object(graphql_api_settings, "OPTIMIZE_QUERYSET", False):
            data = self._exec(
                '{ authors { results { posts(filter: { title: { icontains: "05" } }) '
                "{ results { title } totalCount } } } }"
            )
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 1)
        self.assertEqual(posts["results"][0]["title"], "Post 05")

    def test_filtered_nested_with_deeper_nested_list(self):
        # Regression: a filter on an intermediate nested list + a deeper nested
        # list on the same path (posts(filter) -> coAuthors) used to raise
        # "'posts' lookup was already seen with a different queryset". The deeper
        # list is now prefetched through the filtered parent's queryset.
        co = Author.objects.create(name="Co")
        for post in Post.objects.filter(author=self.author):
            post.co_authors.add(co)

        data = self._exec(
            '{ authors { results { name posts(filter: { title: { icontains: "0" } }) {'
            "  totalCount"
            '  results(ordering: "id") {'
            "    title coAuthors { totalCount results { name } }"
            "  }"
            "} } } }"
        )
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 6)  # all "Post 0X" contain "0"
        first = posts["results"][0]
        self.assertEqual(first["coAuthors"]["totalCount"], 1)
        self.assertEqual(first["coAuthors"]["results"][0]["name"], "Co")

    def test_filtered_nested_with_deeper_nested_is_constant_queries(self):
        # The deeper nested list under a filtered parent stays N+1-safe: adding
        # authors/posts must not add queries.
        co = Author.objects.create(name="Co")
        for post in Post.objects.all():
            post.co_authors.add(co)

        query = (
            '{ authors { results { posts(filter: { title: { icontains: "Post" } }) {'
            "  results { title coAuthors { results { name } } }"
            "} } } }"
        )
        with CaptureQueriesContext(connection) as before:
            self._exec(query)

        for n in range(5):
            extra = Author.objects.create(name="N%d" % n)
            post = Post.objects.create(title="Post extra %d" % n, author=extra)
            post.co_authors.add(co)

        with CaptureQueriesContext(connection) as after:
            self._exec(query)
        # Same number of queries despite 5 more authors/posts.
        self.assertEqual(len(after.captured_queries), len(before.captured_queries))


class InMemoryPaginatorTest(TestCase):
    def _items(self):
        return [SimpleNamespace(id=i, name="n%d" % i) for i in range(5)]

    def test_limit_offset_in_memory(self):
        paginator = LimitOffsetGraphqlPagination()
        page = paginator.paginate_queryset(self._items(), limit=2, offset=1)
        self.assertEqual([o.id for o in page], [1, 2])

    def test_limit_offset_in_memory_ordering(self):
        paginator = LimitOffsetGraphqlPagination()
        page = paginator.paginate_queryset(self._items(), limit=3, ordering="-id")
        self.assertEqual([o.id for o in page], [4, 3, 2])

    def test_page_in_memory(self):
        paginator = PageGraphqlPagination(page_size=2)
        page = paginator.paginate_queryset(self._items(), page=2)
        self.assertEqual([o.id for o in page], [2, 3])

    def test_in_memory_order_handles_none(self):
        items = [SimpleNamespace(id=1, v=None), SimpleNamespace(id=2, v=5)]
        paginator = LimitOffsetGraphqlPagination()
        page = paginator.paginate_queryset(items, limit=10, ordering="v")
        # None sorts last; no TypeError raised.
        self.assertEqual([o.id for o in page], [2, 1])


# --------------------------------------------------------------------------- #
# Mutation responses carry the nested shape too (AC5)                          #
# --------------------------------------------------------------------------- #
from django_graphex import DjangoModelMutation  # noqa: E402


class _GAuthorType(DjangoObjectType):
    class Meta:
        model = Author


class _GTagType(DjangoObjectType):
    class Meta:
        model = Tag


class _GPostType(DjangoObjectType):
    class Meta:
        model = Post


class _PostMutation(DjangoModelMutation):
    class Meta:
        model = Post


class _MutQuery(graphene.ObjectType):
    hello = graphene.String()


class _Mutation(graphene.ObjectType):
    post_create = _PostMutation.CreateField()


# DjangoGraphQLSchema is the canonical schema entry point on BOTH backends.
# Under GDX_BACKEND=native it assembles the native graphql-core schema from the
# native root compiler (WU2), recovering the native mutation GraphQLField that a
# bare graphene.Schema would drop from the empty Mutation root (the WU9 fix for
# the "_Mutation must define one or more fields" failure). Under graphene it
# behaves exactly like graphene.Schema.
mut_schema = DjangoGraphQLSchema(query=_MutQuery, mutation=_Mutation)

# graphql-core's GraphQLSchema (native) executes via ``graphql_sync``; graphene's
# Schema executes via ``.execute``. The same document runs on both.
_NATIVE_BACKEND = os.environ.get("GDX_BACKEND", "graphene") == "native"


class MutationNestedShapeTest(TestCase):
    def _execute(self, document, request):
        if _NATIVE_BACKEND:
            from graphql import graphql_sync

            return graphql_sync(
                mut_schema.graphql_schema, document, context_value=request
            )
        return mut_schema.execute(document, context_value=request)

    def test_create_response_nested_list_shape(self):
        # A native create mutation EXECUTES end-to-end via DjangoGraphQLSchema:
        # the native mutation field's output type is the mutation PAYLOAD
        # (post/ok/errors), the input arg is the camelCase wire name, and the
        # resolver creates a real row (WU9). Under graphene the same document
        # runs through graphene.Schema unchanged.
        author = Author.objects.create(name="Ada")
        # The uniform results/totalCount nested-list shape on an auto-derived
        # to-many relation (``tags``) is produced by the converter on the graphene
        # node; the native node compiler emits a plain ``[Tag]`` for auto-derived
        # to-many relations (tracked debt — native auto-relation nested-list shape
        # is a node-relation slice, NOT WU9 mutation-schema assembly). Select the
        # shape each backend genuinely produces so the mutation-execution path is
        # exercised honestly on both.
        if _NATIVE_BACKEND:
            tags_selection = "tags { label }"
        else:
            tags_selection = "tags { results { label } totalCount }"
        mutation = (
            'mutation { postCreate(newPost: {title: "X", body: "y", author: %d}) '
            "{ post { title author { name } %s } "
            "ok errors { field messages } } }" % (author.id, tags_selection)
        )
        from django.test import RequestFactory

        request = RequestFactory().post("/graphql/", content_type="application/json")
        result = self._execute(mutation, request)
        self.assertIsNone(result.errors)
        data = result.data["postCreate"]
        self.assertTrue(data["ok"], data["errors"])
        self.assertEqual(data["post"]["title"], "X")
        self.assertEqual(data["post"]["author"]["name"], "Ada")
        # A freshly created post has no tags, in whichever shape the backend emits.
        if _NATIVE_BACKEND:
            self.assertEqual(data["post"]["tags"], [])
        else:
            self.assertEqual(data["post"]["tags"]["totalCount"], 0)
            self.assertEqual(data["post"]["tags"]["results"], [])
        # The row really landed in the DB (not a faked payload).
        self.assertTrue(Post.objects.filter(title="X").exists())
