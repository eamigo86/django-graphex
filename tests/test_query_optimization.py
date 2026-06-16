# -*- coding: utf-8 -*-
"""Query optimization tests: nested select/prefetch, .only(), and N+1.

Covers the reworked ``django_graphex.utils.queryset_factory`` /
``recursive_params`` (SPEC ``specs/queryset-optimization-spec.md``).
"""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync, parse
from graphql.language.ast import FragmentDefinitionNode, OperationDefinitionNode

from django_graphex import (
    DjangoGraphQLSchema,
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectField,
    DjangoObjectType,
    ObjectType,
)
from django_graphex.registry import Registry
from django_graphex.settings import graphql_api_settings
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
def _parse(query):
    """Return ``(model_selection_set, fragments)`` for a `{ wrapper { ... } }`."""
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


def _params(query, model=Post):
    selection_set, fragments = _parse(query)
    return recursive_params(
        selection_set, fragments, _relation_field_map(model), [], []
    )


# --------------------------------------------------------------------------- #
# recursive_params — select / prefetch path building                           #
# --------------------------------------------------------------------------- #
class RecursiveParamsTest(TestCase):
    def test_forward_fk_is_select_m2m_and_reverse_are_prefetch(self):
        select, prefetch = _params(
            "{ p { title author { name } category { title } tags { label } } }"
        )
        self.assertEqual(set(select), {"author", "category"})
        self.assertEqual(set(prefetch), {"tags"})

    def test_nested_dotted_paths(self):
        # author (select) -> posts (reverse FK, prefetch) => author__posts
        select, prefetch = _params("{ p { author { name posts { title } } } }")
        self.assertEqual(set(select), {"author"})
        self.assertEqual(set(prefetch), {"author__posts"})

    def test_camelcase_relation_is_resolved(self):
        # coAuthors -> co_authors (M2M) => prefetch
        select, prefetch = _params("{ p { coAuthors { name } } }")
        self.assertEqual(set(prefetch), {"co_authors"})

    def test_fragment_spread_and_inline_fragment(self):
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

    def test_scalars_and_unknown_leaves_are_noop(self):
        # Only scalars / unknown computed fields: nothing to optimize, no crash.
        select, prefetch = _params("{ p { title body displayName } }")
        self.assertEqual(select, [])
        self.assertEqual(prefetch, [])

    def test_deduplicates_paths(self):
        select, prefetch = _params(
            "{ p { author { name } author { bio } tags { label } tags { id } } }"
        )
        self.assertEqual(select, ["author"])
        self.assertEqual(prefetch, ["tags"])


# --------------------------------------------------------------------------- #
# _collect_only_fields — conservative column projection                         #
# --------------------------------------------------------------------------- #
class OnlyFieldsTest(TestCase):
    def test_includes_pk_requested_fields_and_fk_attname(self):
        selection_set, fragments = _parse("{ p { title author { name } } }")
        only = _collect_only_fields(Post, selection_set, fragments)
        self.assertIn("id", only)  # Post pk
        self.assertIn("title", only)
        self.assertIn("author_id", only)  # forward FK local key
        self.assertIn("author__id", only)  # related pk
        self.assertIn("author__name", only)
        self.assertNotIn("body", only)  # not requested -> deferred

    def test_unknown_leaf_loads_model_in_full(self):
        # displayName is a property (unknown) -> Author loaded fully (incl. bio).
        selection_set, fragments = _parse("{ a { displayName } }")
        only = _collect_only_fields(Author, selection_set, fragments)
        self.assertIn("bio", only)
        self.assertIn("name", only)
        self.assertIn("id", only)

    def test_prefetch_branch_not_narrowed(self):
        # Phase B narrows the prefetch's OWN child queryset, not the root queryset
        # — this test remains TRUE.  _collect_only_fields (root-only projection) must
        # NOT emit any "tags__*" paths into the root .only() set; those columns
        # belong to the child queryset that Phase B narrows separately via
        # _collect_prefetch_only_sets / _narrow_plain_prefetch.
        selection_set, fragments = _parse("{ p { title tags { label } } }")
        only = _collect_only_fields(Post, selection_set, fragments)
        self.assertFalse(any(o.startswith("tags__") for o in only))
        self.assertIn("title", only)

    def test_plumbing_leaves_do_not_force_full(self):
        # `results`/`totalCount` wrapper around model fields must stay narrowed.
        selection_set, fragments = _parse("{ w { results { title } totalCount } }")
        only = _collect_only_fields(Post, selection_set, fragments)
        self.assertIn("title", only)
        self.assertNotIn("body", only)  # still narrowed despite totalCount leaf


# --------------------------------------------------------------------------- #
# End-to-end: N+1 elimination over a real schema                               #
# --------------------------------------------------------------------------- #
class AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        registry = _RQO


class CategoryType(DjangoObjectType):
    class Meta:
        model = Category
        registry = _RQO


class TagType(DjangoObjectType):
    class Meta:
        model = Tag
        registry = _RQO


class PostType(DjangoObjectType):
    class Meta:
        model = Post
        registry = _RQO


class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        registry = _RQO


class Query(ObjectType):
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
    @classmethod
    def setUpTestData(cls):
        author = Author.objects.create(name="Ada", bio="x")
        category = Category.objects.create(title="Tech")
        tags = [Tag.objects.create(label="t%d" % i) for i in range(3)]
        for i in range(5):
            post = Post.objects.create(
                title="P%d" % i, author=author, category=category
            )
            post.tags.add(*tags)

    def _run(self):
        result = graphql_sync(schema.graphql_schema, NESTED_QUERY)
        assert result.errors is None, result.errors
        # force full resolution / serialization
        data = result.data["allPosts"]
        return data

    def test_constant_query_count_with_optimization(self):
        # 1 count + 1 posts(select_related author) + 1 prefetch tags = 3,
        # independent of the number of rows.
        with self.assertNumQueries(3):
            data = self._run()
        self.assertEqual(data["totalCount"], 5)
        self.assertEqual(len(data["results"]), 5)
        self.assertEqual(data["results"][0]["author"]["name"], "Ada")
        self.assertEqual(len(data["results"][0]["tags"]["results"]), 3)
        self.assertEqual(data["results"][0]["tags"]["totalCount"], 3)

    def test_optimization_can_be_disabled(
        self,
    ):
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
    @classmethod
    def setUpTestData(cls):
        author = Author.objects.create(name="Grace", bio="y")
        tags = [Tag.objects.create(label="s%d" % i) for i in range(3)]
        cls.post = Post.objects.create(title="Solo", author=author)
        cls.post.tags.add(*tags)

    def _query(self, pk):
        return graphql_sync(
            schema.graphql_schema,
            "{ post(id: %s) { title author { name } "
            "tags { results { label } totalCount } } }" % pk,
        )

    def test_constant_query_count_for_single_object(self):
        # 1 (post + select_related author) + 1 (prefetch tags) = 2, no per-relation N+1.
        with self.assertNumQueries(2):
            result = self._query(self.post.pk)
            assert result.errors is None, result.errors
            data = result.data["post"]
            self.assertEqual(data["author"]["name"], "Grace")
            self.assertEqual(len(data["tags"]["results"]), 3)
            self.assertEqual(data["tags"]["totalCount"], 3)

    def test_missing_object_returns_none(self):
        result = self._query(9999999)
        self.assertIsNone(result.errors)
        self.assertIsNone(result.data["post"])
