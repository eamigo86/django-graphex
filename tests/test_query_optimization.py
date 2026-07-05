# -*- coding: utf-8 -*-
"""Query optimization tests: nested select/prefetch, .only(), and N+1.

Covers the reworked "django_graphex.utils.queryset_factory" /
"recursive_params" (SPEC "specs/queryset-optimization-spec.md").
"""

from __future__ import annotations

from typing import Any

from django.db import connection, models
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import ExecutionResult, graphql_sync, parse
from graphql.language.ast import (
    FragmentDefinitionNode,
    OperationDefinitionNode,
    SelectionSetNode,
)

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.utils import (
    _collect_only_fields,
    _relation_field_map,
    recursive_params,
)

from ._schema_isolation import isolated_pair
from .models import Author, Category, Post, Tag

_RQO = Registry()


# --------------------------------------------------------------------------- #
# Helpers: parse a GraphQL string into a model-level selection set            #
# --------------------------------------------------------------------------- #
def _parse(query: str) -> tuple[SelectionSetNode, dict[str, FragmentDefinitionNode]]:
    """Return the model-level selection set and fragments for "{ wrapper { ... } }".

    Args:
        query: A GraphQL query document with a single top-level wrapper
            field whose selection set is the one under test.

    Returns:
        parsed: A tuple of the wrapper field's selection set and a mapping
            of fragment name to its definition node.
    """
    document = parse(query)
    fragments = {
        d.name.value: d
        for d in document.definitions
        if isinstance(d, FragmentDefinitionNode)
    }
    operation = next(
        d for d in document.definitions if isinstance(d, OperationDefinitionNode)
    )
    return operation.selection_set.selections[0].selection_set, fragments


def _params(
    query: str, model: type[models.Model] = Post
) -> tuple[list[str], list[str]]:
    """Parse a query and compute its select_related/prefetch_related paths.

    Args:
        query: A GraphQL query document with a single top-level wrapper
            field whose selection set drives the path computation.
        model: The Django model the selection set is walked against.

    Returns:
        paths: A tuple of the computed select_related and prefetch_related
            path lists.
    """
    selection_set, fragments = _parse(query)
    return recursive_params(
        selection_set, fragments, _relation_field_map(model), [], []
    )


# --------------------------------------------------------------------------- #
# recursive_params — select / prefetch path building                           #
# --------------------------------------------------------------------------- #
class RecursiveParamsTest(TestCase):
    """Tests for "recursive_params" building select/prefetch path lists.

    Covers forward/reverse/M2M classification, nesting, camelCase
    resolution, fragments, no-op leaves, and deduplication.
    """

    def test_forward_fk_is_select_m2m_and_reverse_are_prefetch(self) -> None:
        """Assert forward FKs become select_related, M2M/reverse become prefetch.

        If this fails, the walker would misclassify a relation kind,
        causing either a missed optimization or an incorrect query plan.
        """
        select, prefetch = _params(
            "{ p { title author { name } category { title } tags { label } } }"
        )
        self.assertEqual(set(select), {"author", "category"})
        self.assertEqual(set(prefetch), {"tags"})

    def test_nested_dotted_paths(self) -> None:
        """Assert a select-then-prefetch chain produces a dotted path.

        If this fails, nested optimizations across a forward relation
        followed by a reverse relation would not compose into a single
        "author__posts" prefetch path.
        """
        # author (select) -> posts (reverse FK, prefetch) => author__posts
        select, prefetch = _params("{ p { author { name posts { title } } } }")
        self.assertEqual(set(select), {"author"})
        self.assertEqual(set(prefetch), {"author__posts"})

    def test_camelcase_relation_is_resolved(self) -> None:
        """Assert a camelCase relation name resolves to its snake_case field.

        If this fails, a relation selected via its camelCase GraphQL name
        would not be recognized and optimized.
        """
        # coAuthors -> co_authors (M2M) => prefetch
        select, prefetch = _params("{ p { coAuthors { name } } }")
        self.assertEqual(set(prefetch), {"co_authors"})

    def test_fragment_spread_and_inline_fragment(self) -> None:
        """Assert both fragment spreads and inline fragments are walked.

        If this fails, relations selected only through a named fragment
        or an inline fragment would be missed by the optimizer.
        """
        query = """
        {
          p {
            ...Frag
            ... on Whatever { tags { label } }
          }
        }
        fragment Frag on Whatever { author { name } }
        """
        select, prefetch = _params(query)
        self.assertEqual(set(select), {"author"})
        self.assertEqual(set(prefetch), {"tags"})

    def test_scalars_and_unknown_leaves_are_noop(self) -> None:
        """Assert scalar and unknown computed leaves produce no optimization paths.

        If this fails, the walker would either crash or wrongly emit
        select/prefetch paths for fields that are not relations.
        """
        # Only scalars / unknown computed fields: nothing to optimize, no crash.
        select, prefetch = _params("{ p { title body displayName } }")
        self.assertEqual(select, [])
        self.assertEqual(prefetch, [])

    def test_deduplicates_paths(self) -> None:
        """Assert selecting the same relation twice yields one optimization path.

        If this fails, repeated selections of the same relation (for
        example, via separate top-level fields) would produce duplicate
        entries in the select/prefetch lists.
        """
        select, prefetch = _params(
            "{ p { author { name } author { bio } tags { label } tags { id } } }"
        )
        self.assertEqual(select, ["author"])
        self.assertEqual(prefetch, ["tags"])


# --------------------------------------------------------------------------- #
# _collect_only_fields — conservative column projection                         #
# --------------------------------------------------------------------------- #
class OnlyFieldsTest(TestCase):
    """Tests for "_collect_only_fields" computing a conservative .only() set.

    Covers requested-field projection, unknown-leaf full-load fallback,
    prefetch-branch exclusion, and wrapper-leaf handling.
    """

    def test_includes_pk_requested_fields_and_fk_attname(self) -> None:
        """Assert requested fields, the pk, and FK attnames all get projected.

        If this fails, a queryset built with the computed .only() set
        would be missing columns needed to resolve the requested selection.
        """
        selection_set, fragments = _parse("{ p { title author { name } } }")
        only = _collect_only_fields(Post, selection_set, fragments)
        self.assertIn("id", only)  # Post pk
        self.assertIn("title", only)
        self.assertIn("author_id", only)  # forward FK local key
        self.assertIn("author__id", only)  # related pk
        self.assertIn("author__name", only)
        self.assertNotIn("body", only)  # not requested -> deferred

    def test_unknown_leaf_loads_model_in_full(self) -> None:
        """Assert an unknown computed leaf forces the model to load in full.

        If this fails, a computed property field (not a real column) would
        cause the optimizer to under-project, deferring columns the
        property implementation actually needs.
        """
        # displayName is a property (unknown) -> Author loaded fully (incl. bio).
        selection_set, fragments = _parse("{ a { displayName } }")
        only = _collect_only_fields(Author, selection_set, fragments)
        self.assertIn("bio", only)
        self.assertIn("name", only)
        self.assertIn("id", only)

    def test_prefetch_branch_not_narrowed(self) -> None:
        """Assert the root .only() set excludes prefetch-branch column paths.

        Phase B narrows the prefetch's OWN child queryset, not the root
        queryset — this test remains TRUE. "_collect_only_fields"
        (root-only projection) must NOT emit any "tags__*" paths into the
        root .only() set; those columns belong to the child queryset that
        Phase B narrows separately via "_collect_prefetch_only_sets" /
        "_narrow_plain_prefetch".

        If this fails, the root queryset's .only() set would incorrectly
        include columns that belong to a prefetched relation's own
        queryset.
        """
        selection_set, fragments = _parse("{ p { title tags { label } } }")
        only = _collect_only_fields(Post, selection_set, fragments)
        self.assertFalse(any(o.startswith("tags__") for o in only))
        self.assertIn("title", only)

    def test_plumbing_leaves_do_not_force_full(self) -> None:
        """Assert "results"/"totalCount" wrapper leaves do not force a full load.

        If this fails, list-wrapper plumbing fields would be mistaken for
        unknown computed leaves and force the model to load every column.
        """
        # `results`/`totalCount` wrapper around model fields must stay narrowed.
        selection_set, fragments = _parse("{ w { results { title } totalCount } }")
        only = _collect_only_fields(Post, selection_set, fragments)
        self.assertIn("title", only)
        self.assertNotIn("body", only)  # still narrowed despite totalCount leaf


# --------------------------------------------------------------------------- #
# End-to-end: N+1 elimination over a real schema                               #
# --------------------------------------------------------------------------- #
class AuthorType(DjangoObjectType):
    """Object type for "Author", registered on the isolated test registry.

    Feeds the end-to-end N+1 elimination tests below.
    """

    class Meta:
        """Configuration for "AuthorType".

        Declares the backing model and the isolated test registry.
        """

        model = Author
        registry = _RQO


class CategoryType(DjangoObjectType):
    """Object type for "Category", registered on the isolated test registry.

    Feeds the end-to-end N+1 elimination tests below.
    """

    class Meta:
        """Configuration for "CategoryType".

        Declares the backing model and the isolated test registry.
        """

        model = Category
        registry = _RQO


class TagType(DjangoObjectType):
    """Object type for "Tag", registered on the isolated test registry.

    Feeds the end-to-end N+1 elimination tests below.
    """

    class Meta:
        """Configuration for "TagType".

        Declares the backing model and the isolated test registry.
        """

        model = Tag
        registry = _RQO


class PostType(DjangoObjectType):
    """Object type for "Post", registered on the isolated test registry.

    Feeds the end-to-end N+1 elimination tests below.
    """

    class Meta:
        """Configuration for "PostType".

        Declares the backing model and the isolated test registry.
        """

        model = Post
        registry = _RQO


class PostListType(DjangoListObjectType):
    """List type for "Post", registered on the isolated test registry.

    Backs the "allPosts" list field used by the N+1 elimination tests.
    """

    class Meta:
        """Configuration for "PostListType".

        Declares the backing model and the isolated test registry.
        """

        model = Post
        registry = _RQO


class Query(ObjectType):
    """Root query exposing the list and single-object "Post" fields under test.

    Used by both the list-based and single-object N+1 elimination tests.
    """

    all_posts = DjangoListObjectField(PostListType)
    post = DjangoObjectField(PostType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(_RQO))

NESTED_QUERY = """
{
  allPosts {
    results {
      title
      author { name }
      tags { results { label } totalCount }
    }
    totalCount
  }
}
"""


class NPlusOneTest(TestCase):
    """End-to-end N+1 elimination tests over a real compiled schema.

    Exercises the nested list query (author + tags) both with and without
    the query optimizer enabled.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed one author, one category, three tags, and five tagged posts.

        Five rows are enough to make a constant (row-count-independent)
        query count observable.
        """
        author = Author.objects.create(name="Ada", bio="x")
        category = Category.objects.create(title="Tech")
        tags = [Tag.objects.create(label="t%d" % i) for i in range(3)]
        for i in range(5):
            post = Post.objects.create(
                title="P%d" % i, author=author, category=category
            )
            post.tags.add(*tags)

    def _run(self) -> dict[str, Any]:
        """Execute the shared nested query and return the "allPosts" payload.

        Returns:
            data: The "allPosts" field's resolved data.
        """
        result = graphql_sync(schema.graphql_schema, NESTED_QUERY)
        assert result.errors is None, result.errors
        # force full resolution / serialization
        data = result.data["allPosts"]
        return data

    def test_constant_query_count_with_optimization(self) -> None:
        """Assert the nested query runs in a constant, row-count-independent 2 queries.

        1 posts(select_related author) + 1 prefetch tags = 2, independent
        of the number of rows. totalCount is selected after results, so
        the lazy count reuses the materialized result cache (no separate
        COUNT query).

        If this fails, the optimizer would regress into per-row N+1
        queries for the nested author/tags selection.
        """
        with self.assertNumQueries(2):
            data = self._run()
        self.assertEqual(data["totalCount"], 5)
        self.assertEqual(len(data["results"]), 5)
        self.assertEqual(data["results"][0]["author"]["name"], "Ada")
        self.assertEqual(len(data["results"][0]["tags"]["results"]), 3)
        self.assertEqual(data["results"][0]["tags"]["totalCount"], 3)

    def test_optimization_can_be_disabled(self) -> None:
        """Assert disabling OPTIMIZE_QUERYSET produces strictly more queries.

        With optimization OFF, the nested author triggers one query per
        row.

        If this fails, the OPTIMIZE_QUERYSET setting would not actually
        gate the optimizer, making it impossible to opt out.
        """
        # With optimization OFF, the nested author triggers one query per row.
        from unittest import mock

        with mock.patch.object(graphql_api_settings, "OPTIMIZE_QUERYSET", False):
            with CaptureQueriesContext(connection) as ctx_off:
                self._run()
        with CaptureQueriesContext(connection) as ctx_on:
            self._run()

        self.assertGreater(len(ctx_off.captured_queries), len(ctx_on.captured_queries))


# --------------------------------------------------------------------------- #
# Single-object retrieval (DjangoObjectField) — N+1 elimination                #
# --------------------------------------------------------------------------- #
class SingleObjectTest(TestCase):
    """N+1 elimination tests for single-object retrieval via "DjangoObjectField".

    Exercises the single-object query (author + tags) and the
    missing-object null-resolution path.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed one author, three tags, and one tagged post.

        A single tagged post is enough to exercise the retrieve path's
        nested author/tags optimization.
        """
        author = Author.objects.create(name="Grace", bio="y")
        tags = [Tag.objects.create(label="s%d" % i) for i in range(3)]
        cls.post = Post.objects.create(title="Solo", author=author)
        cls.post.tags.add(*tags)

    def _query(self, pk: int) -> ExecutionResult:
        """Execute the shared single-object query for a given primary key.

        Args:
            pk: The "Post" primary key to retrieve.

        Returns:
            result: The raw graphql-core execution result.
        """
        return graphql_sync(
            schema.graphql_schema,
            "{ post(id: %s) { title author { name } "
            "tags { results { label } totalCount } } }" % pk,
        )

    def test_constant_query_count_for_single_object(self) -> None:
        """Assert a single-object query with nested relations runs in 2 queries.

        1 (post + select_related author) + 1 (prefetch tags) = 2, no
        per-relation N+1.

        If this fails, single-object retrieval would regress into extra
        per-relation queries for its nested author/tags selection.
        """
        with self.assertNumQueries(2):
            result = self._query(self.post.pk)
            assert result.errors is None, result.errors
            data = result.data["post"]
            self.assertEqual(data["author"]["name"], "Grace")
            self.assertEqual(len(data["tags"]["results"]), 3)
            self.assertEqual(data["tags"]["totalCount"], 3)

    def test_missing_object_returns_none(self) -> None:
        """Assert retrieving a nonexistent primary key returns null, not an error.

        If this fails, a single-object query for a missing row would
        surface a GraphQL error instead of resolving to null.
        """
        result = self._query(9999999)
        self.assertIsNone(result.errors)
        self.assertIsNone(result.data["post"])
