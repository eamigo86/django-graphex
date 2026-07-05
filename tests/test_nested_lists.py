"""Nested related lists carry the uniform results/totalCount shape.

Covers the SPEC "specs/nested-list-shape-spec.md": every related list field
exposes "results" + "totalCount" with filtering + pagination + ordering, the
prefetch cache keeps N+1 at zero (in-memory pagination), and a per-model paginator
is reused when the model appears nested under another.

A dedicated "Registry" isolates these types from the global one so the schema
shape is deterministic regardless of test order.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.db import connection
from django.http import HttpRequest
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import (
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author, Post, Tag

R = Registry()


class TagTypeN(DjangoObjectType):
    """ "Tag" object type registered on the isolated nested-list "Registry".

    Used as the target of the "coAuthors" and "tags" nested M2M relations.
    """

    class Meta:
        """Bind the type to "Tag" under the isolated registry "R".

        No extra options are needed for this type.
        """

        model = Tag
        registry = R


class AuthorTypeN(DjangoObjectType):
    """ "Author" object type registered on the isolated nested-list "Registry".

    Declares the reverse-FK "posts" relation exercised by the shape tests.
    """

    class Meta:
        """Bind the type to "Author" under the isolated registry "R".

        No extra options are needed for this type.
        """

        model = Author
        registry = R


class PostTypeN(DjangoObjectType):
    """ "Post" object type with a filterable "title" field, for nested-filter tests.

    Also exposes the "coAuthors" M2M relation used by the paginator-reuse test.
    """

    class Meta:
        """Bind the type to "Post" with "title" filterable by icontains/exact.

        No other options are needed for these nested-filter tests.
        """

        model = Post
        registry = R
        filter_fields = {"title": ["icontains", "exact"]}


class AuthorListN(DjangoListObjectType):
    """ "Author" list type using a custom page-based paginator.

    Nested "Author" lists elsewhere in the schema must reuse this paginator
    (AC8) instead of falling back to the default limit/offset one.
    """

    class Meta:
        """Bind the list type to "Author" with a custom page-size paginator.

        The paginator uses page_size=10 and the "pageSize" query param name.
        """

        model = Author
        registry = R
        # Custom per-model paginator -> nested Author lists must reuse it (AC8).
        pagination = PageGraphqlPagination(
            page_size=10, page_size_query_param="pageSize"
        )


class Query(ObjectType):
    """Root query exposing the paginated "authors" list field.

    The only entry point for the schema built in this module.
    """

    authors = DjangoListObjectField(AuthorListN)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))
type_map = schema.graphql_schema.type_map


def _args(type_name: str, field_name: str) -> set[str]:
    """Collect the argument names declared on one field of a schema type.

    Args:
        type_name: The GraphQL type name to look up in the schema's type map.
        field_name: The field name on that type whose arguments are read.

    Returns:
        The set of argument names declared on the field.
    """
    return set(type_map[type_name].fields[field_name].args.keys())


# --------------------------------------------------------------------------- #
# Schema shape                                                                  #
# --------------------------------------------------------------------------- #
class NestedShapeTest(TestCase):
    """Coverage for the schema shape of nested related-list fields.

    Covers list-type resolution, its default pagination/ordering args, and
    paginator reuse across nested M2M relations.
    """

    def test_nested_field_is_a_list_type(self) -> None:
        """A reverse-FK nested field ("AuthorTypeN.posts") is a list type with results/totalCount.

        This test breaks if a nested reverse-FK field stops resolving to a
        generated list type (AC1), or if that list type drops "results" or
        "totalCount".
        """
        posts_type = type_map["AuthorTypeN"].fields["posts"].type
        self.assertEqual(posts_type.name, "PostListType")
        fields = type_map["PostListType"].fields
        self.assertIn("results", fields)
        self.assertIn("totalCount", fields)

    def test_nested_results_has_pagination_and_ordering_args(self) -> None:
        """The auto-generated nested list type's "results" field exposes limit/offset/ordering args.

        This test breaks if an auto-generated nested list type (AC2) stops
        using the default limit/offset paginator's argument set.
        """
        args = _args("PostListType", "results")
        self.assertIn("limit", args)
        self.assertIn("offset", args)
        self.assertIn("ordering", args)

    def test_nested_reuses_registered_paginator(self) -> None:
        """A nested M2M field reuses the target type's registered paginator instead of the default.

        This test breaks if "PostTypeN.coAuthors" (M2M to "Author") stops
        resolving to "AuthorListN" and its page-based paginator (AC8),
        falling back to a fresh limit/offset list type instead.
        """
        co_type = type_map["PostTypeN"].fields["coAuthors"].type
        self.assertEqual(co_type.name, "AuthorListN")
        args = _args("AuthorListN", "results")
        self.assertIn("page", args)
        self.assertNotIn("limit", args)


# --------------------------------------------------------------------------- #
# Behaviour (pagination / ordering / filtering / N+1)                          #
# --------------------------------------------------------------------------- #
class NestedBehaviourTest(TestCase):
    """Coverage for nested-list pagination, ordering, filtering, and N+1 safety.

    Also covers deeper-nested lists composed under a filtered parent list.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with six sequentially-titled posts.

        Shared as class-level fixture data by every test in this class.
        """
        cls.author = Author.objects.create(name="Ada", bio="b")
        for i in range(6):
            Post.objects.create(title="Post %02d" % i, author=cls.author)

    def _exec(self, query: str) -> dict[str, Any]:
        """Execute a GraphQL document against the module's nested-list schema.

        Args:
            query: The GraphQL query document to execute.

        Returns:
            The execution result's "data" mapping.
        """
        result = graphql_sync(schema.graphql_schema, query)
        assert result.errors is None, result.errors
        return result.data

    def test_pagination_and_ordering(self) -> None:
        """A nested list honors "limit" and descending "ordering" together.

        This test breaks if nested-list pagination and ordering stop
        composing, or if "totalCount" stops reflecting the full unfiltered set.
        """
        data = self._exec("""
            { authors { results { name posts {
                results(limit: 2, ordering: "-id") { title } totalCount
            } } } }
            """)
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 6)  # full set
        self.assertEqual([p["title"] for p in posts["results"]], ["Post 05", "Post 04"])

    def test_offset(self) -> None:
        """A nested list honors "offset" combined with "limit" and ascending "ordering".

        This test breaks if the in-memory nested-list paginator stops
        applying "offset" correctly alongside "limit".
        """
        data = self._exec(
            "{ authors { results { posts { results(limit: 2, offset: 2, "
            'ordering: "id") { title } } } } }'
        )
        posts = data["authors"]["results"][0]["posts"]["results"]
        self.assertEqual([p["title"] for p in posts], ["Post 02", "Post 03"])

    def test_filtering(self) -> None:
        """A nested list applies its declared filter and reports the filtered "totalCount".

        This test breaks if "PostTypeN"'s "filter_fields" stop being honored
        when the type is nested under "authors.posts".
        """
        # Nested posts are filterable (PostTypeN declares filter_fields on title).
        data = self._exec(
            '{ authors { results { posts(filter: { title: { icontains: "05" } }) { '
            "results { title } totalCount } } } }"
        )
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 1)
        self.assertEqual(posts["results"][0]["title"], "Post 05")

    def test_unfiltered_nested_is_constant_queries(self) -> None:
        """Adding more parent authors does not add queries for an unfiltered nested list.

        This test breaks if the prefetch cache and in-memory pagination (AC4)
        regress, reintroducing an N+1 query per parent author.
        """
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

    def test_filtered_nested_constant_queries(self) -> None:
        """A filtered nested list costs the same query count as an unfiltered one.

        This test breaks if applying a filter to a nested list starts issuing
        a separate query per parent instead of a single filtered Prefetch.
        """
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

    def test_filtered_nested_correct_and_paginated(self) -> None:
        """A filtered nested list reports the filtered "totalCount" and honors in-memory pagination.

        This test breaks if filtering and pagination stop composing on a
        nested list, or if "totalCount" starts reflecting the unfiltered set.
        """
        # Filter applied (totalCount = filtered size) + in-memory limit/ordering.
        data = self._exec(
            '{ authors { results { posts(filter: { title: { icontains: "0" } }) '
            '{ results(limit: 2, ordering: "-id") { title } totalCount } } } }'
        )
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 6)  # all "Post 0X" contain "0"
        self.assertEqual([p["title"] for p in posts["results"]], ["Post 05", "Post 04"])

    def test_filtered_fallback_when_optimization_disabled(self) -> None:
        """A filtered nested list still returns correct results with "OPTIMIZE_QUERYSET" disabled.

        This test breaks if disabling queryset optimization changes the
        observable filtering behavior of a nested list.
        """
        from unittest import mock

        with mock.patch.object(graphql_api_settings, "OPTIMIZE_QUERYSET", False):
            data = self._exec(
                '{ authors { results { posts(filter: { title: { icontains: "05" } }) '
                "{ results { title } totalCount } } } }"
            )
        posts = data["authors"]["results"][0]["posts"]
        self.assertEqual(posts["totalCount"], 1)
        self.assertEqual(posts["results"][0]["title"], "Post 05")

    def test_filtered_nested_with_deeper_nested_list(self) -> None:
        """A filter on an intermediate nested list composes with a deeper nested list on the same path.

        This is a regression test: "posts(filter) -> coAuthors" used to raise
        "'posts' lookup was already seen with a different queryset" because
        the deeper list was not prefetched through the filtered parent's
        queryset. This test breaks if that regression reappears.
        """
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

    def test_filtered_nested_with_deeper_nested_is_constant_queries(self) -> None:
        """A deeper nested list under a filtered parent stays N+1-safe as more data is added.

        This test breaks if adding more authors/posts under a filtered parent
        list increases the query count for the deeper nested "coAuthors" list.
        """
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
    """Coverage for the in-memory (non-queryset) pagination path used for prefetched lists.

    Covers limit/offset, page-based, and None-tolerant ordering.
    """

    def _items(self) -> list[SimpleNamespace]:
        """Build five throwaway namespace objects with sequential ids and names.

        Returns:
            A list of five "SimpleNamespace" objects with "id" 0..4 and a
            matching "name".
        """
        return [SimpleNamespace(id=i, name="n%d" % i) for i in range(5)]

    def test_limit_offset_in_memory(self) -> None:
        """ "LimitOffsetGraphqlPagination" slices an in-memory list by limit and offset.

        This test breaks if the in-memory limit/offset pagination stops
        matching plain Python slicing semantics.
        """
        paginator = LimitOffsetGraphqlPagination()
        page = paginator.paginate_queryset(self._items(), limit=2, offset=1)
        self.assertEqual([o.id for o in page], [1, 2])

    def test_limit_offset_in_memory_ordering(self) -> None:
        """ "LimitOffsetGraphqlPagination" applies descending ordering before slicing an in-memory list.

        This test breaks if ordering is applied after slicing instead of
        before, or if descending order stops being honored.
        """
        paginator = LimitOffsetGraphqlPagination()
        page = paginator.paginate_queryset(self._items(), limit=3, ordering="-id")
        self.assertEqual([o.id for o in page], [4, 3, 2])

    def test_page_in_memory(self) -> None:
        """ "PageGraphqlPagination" returns the requested page of an in-memory list.

        This test breaks if page-based in-memory pagination stops computing
        the correct slice for a given page number and page size.
        """
        paginator = PageGraphqlPagination(page_size=2)
        page = paginator.paginate_queryset(self._items(), page=2)
        self.assertEqual([o.id for o in page], [2, 3])

    def test_in_memory_order_handles_none(self) -> None:
        """In-memory ordering on a field with a None value sorts None last without raising.

        This test breaks if ordering by a field containing None values starts
        raising a TypeError instead of treating None as sorting last.
        """
        items = [SimpleNamespace(id=1, v=None), SimpleNamespace(id=2, v=5)]
        paginator = LimitOffsetGraphqlPagination()
        page = paginator.paginate_queryset(items, limit=10, ordering="v")
        # None sorts last; no TypeError raised.
        self.assertEqual([o.id for o in page], [2, 1])


# --------------------------------------------------------------------------- #
# Mutation responses carry the nested shape too (AC5)                          #
# --------------------------------------------------------------------------- #
from django_graphex.mutation import DjangoModelMutation  # noqa: E402

RMUT = Registry()


class _GAuthorType(DjangoObjectType):
    """ "Author" object type registered on the isolated mutation "Registry"."""

    class Meta:
        """Bind the type to "Author" under the isolated registry "RMUT"."""

        model = Author
        registry = RMUT


class _GTagType(DjangoObjectType):
    """ "Tag" object type registered on the isolated mutation "Registry"."""

    class Meta:
        """Bind the type to "Tag" under the isolated registry "RMUT"."""

        model = Tag
        registry = RMUT


class _GPostType(DjangoObjectType):
    """ "Post" object type registered on the isolated mutation "Registry"."""

    class Meta:
        """Bind the type to "Post" under the isolated registry "RMUT"."""

        model = Post
        registry = RMUT


class _PostMutation(DjangoModelMutation):
    """CRUD mutation for "Post", registered on the isolated mutation "Registry"."""

    class Meta:
        """Bind the mutation to "Post" under the isolated registry "RMUT"."""

        model = Post
        registry = RMUT


class _MutQuery(ObjectType):
    """Minimal root query required alongside the mutation root."""

    hello = field(GraphQLString)


class _Mutation(ObjectType):
    """Root mutation exposing the generated "postCreate" field."""

    post_create = _PostMutation.CreateField()


# DjangoGraphQLSchema is the canonical schema entry point. It assembles the
# native graphql-core schema from the native root compiler (WU2), recovering the
# native mutation GraphQLField from the Mutation root (the WU9 fix for the
# "_Mutation must define one or more fields" failure).
mut_schema = DjangoGraphQLSchema(
    query=_MutQuery, mutation=_Mutation, registries=isolated_pair(RMUT)
)


class MutationNestedShapeTest(TestCase):
    """Coverage confirming mutation responses carry the nested list shape too (AC5).

    Executes a real create mutation end-to-end via "DjangoGraphQLSchema".
    """

    def _execute(self, document: str, request: HttpRequest) -> Any:
        """Execute a GraphQL document against the module's mutation schema.

        Args:
            document: The GraphQL query or mutation document to execute.
            request: The Django request passed through as GraphQL "context_value".

        Returns:
            The graphql-core "ExecutionResult" for the executed document.
        """
        # The native graphql-core schema executes via ``graphql_sync``.
        return graphql_sync(mut_schema.graphql_schema, document, context_value=request)

    def test_create_response_nested_list_shape(self) -> None:
        """A native "postCreate" mutation returns the uniform results/totalCount shape for "tags".

        This test breaks if the native mutation-execution path (WU9) stops
        producing the mutation payload shape (post/ok/errors), if the
        auto-derived to-many relation "tags" stops emitting the uniform
        results/totalCount container, or if the create stops actually
        persisting a row.
        """
        # A native create mutation EXECUTES end-to-end via DjangoGraphQLSchema:
        # the native mutation field's output type is the mutation PAYLOAD
        # (post/ok/errors), the input arg is the camelCase wire name, and the
        # resolver creates a real row (WU9).
        author = Author.objects.create(name="Ada")
        # The uniform results/totalCount nested-list shape on an auto-derived
        # to-many relation (``tags``) is produced by the native node compiler,
        # which emits the ``TagListType`` (results/totalCount) container for
        # auto-derived to-many relations. The mutation-execution path is
        # therefore exercised with this selection.
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
        # A freshly created post has no tags; both backends emit the uniform
        # results/totalCount nested-list shape.
        self.assertEqual(data["post"]["tags"]["totalCount"], 0)
        self.assertEqual(data["post"]["tags"]["results"], [])
        # The row really landed in the DB (not a faked payload).
        self.assertTrue(Post.objects.filter(title="X").exists())
