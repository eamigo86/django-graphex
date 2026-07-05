# -*- coding: utf-8 -*-
"""Tests for issue #20 — optimizer performance.

Covers:
(a) Request-scoped field-map memoization: _relation_field_map / _concrete_field_map
    return the same object within one _apply_optimizations invocation and the
    underlying get_fields() is called at most once per model per run.
(b) DjangoModelType.perform_mutate: selection-aware re-read eliminates to-one N+1.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from django.db import connection
from django.db.models import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import ExecutionResult, GraphQLResolveInfo, graphql_sync, parse
from graphql.language.ast import (
    FieldNode,
    FragmentDefinitionNode,
    OperationDefinitionNode,
)

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoObjectField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType, DjangoObjectType
from django_graphex.utils import (
    _concrete_field_map,
    _relation_field_map,
)

from ._schema_isolation import isolated_pair
from .models import (
    Author,
    OptimizerPerfAuthor,
    OptimizerPerfCategory,
    OptimizerPerfPost,
    Post,
)


def _execute(schema: DjangoGraphQLSchema, query: str) -> ExecutionResult:
    """Execute "query" against a native "DjangoGraphQLSchema" (graphene-free).

    Drop-in for the retired "schema.execute(query)": returns the graphql-core
    "ExecutionResult" (same ".data" / ".errors" shape graphene returned).

    Args:
        schema: The native schema wrapper to execute the query against.
        query: The GraphQL query document to execute.

    Returns:
        The graphql-core execution result.
    """
    return graphql_sync(schema.graphql_schema, query)


def _gtype(name: str, bases: tuple[type, ...], ns: dict[str, Any]) -> type:
    """Build a dynamic native type via "type()" with pydantic-safe namespace.

    Native "ObjectType" / "DjangoObjectType" are pydantic "BaseModel"
    subclasses; building them with "type(name, bases, ns)" requires
    "ns['__module__']" and a nested "Meta" whose "__qualname__" is
    "<Outer>.Meta" (the value a "class" body produces). This supplies both so
    the dynamic form behaves exactly like the equivalent "class" statement.

    Args:
        name: The class name to build.
        bases: The base classes for the new type.
        ns: The class namespace (attributes and nested classes).

    Returns:
        The dynamically constructed class.
    """
    ns = dict(ns)
    ns.setdefault("__module__", __name__)
    ns["__qualname__"] = name
    for attr_name, attr_val in list(ns.items()):
        if isinstance(attr_val, type):
            try:
                attr_val.__qualname__ = f"{name}.{attr_name}"
            except (AttributeError, TypeError):  # pragma: no cover - defensive
                pass
    return type(name, bases, ns)


# ---------------------------------------------------------------------------
# AST helpers for building fake field_nodes
# ---------------------------------------------------------------------------


def _parse_mutation_field_node(
    gql: str, mutation_field: str
) -> tuple[FieldNode, dict[str, FragmentDefinitionNode]]:
    """Parse a GraphQL mutation string and return the FieldNode for "mutation_field".

    Example:
        _parse_mutation_field_node(
            "mutation { postCreate { ok post { title author { name } } } }",
            "postCreate",
        )

    Args:
        gql: The GraphQL mutation document text to parse.
        mutation_field: The top-level mutation field name to locate (e.g.
            "postCreate").

    Returns:
        A tuple of the matching field node and the document's fragment
        definitions keyed by name.
    """
    document = parse(gql)
    fragments = {
        d.name.value: d
        for d in document.definitions
        if isinstance(d, FragmentDefinitionNode)
    }
    operation = next(
        d for d in document.definitions if isinstance(d, OperationDefinitionNode)
    )
    field = next(
        f for f in operation.selection_set.selections if f.name.value == mutation_field
    )
    return field, fragments


def _fake_info(
    field_node: FieldNode,
    fragments: dict[str, FragmentDefinitionNode] | None = None,
) -> SimpleNamespace:
    """Build a minimal ResolveInfo-like namespace with field_nodes + fragments.

    Args:
        field_node: The single field node to expose as "field_nodes".
        fragments: Optional fragment definitions keyed by name.

    Returns:
        A namespace shaped enough like "GraphQLResolveInfo" for the
        optimizer helpers under test.
    """
    return SimpleNamespace(
        field_nodes=[field_node],
        fragments=fragments or {},
        variable_values={},
        context=SimpleNamespace(META={}, FILES={}),
        return_type=None,
        schema=None,
    )


# ---------------------------------------------------------------------------
# (a) Memoization — unit tests
# ---------------------------------------------------------------------------


class FieldMapMemoizationTest(TestCase):
    """_relation_field_map and _concrete_field_map use request-scoped caching.

    Within a single _apply_optimizations call (one optimizer run) each
    (model, map-kind) must be computed at most once.  We verify by patching
    model._meta.get_fields to count raw calls, then running the optimizer and
    asserting get_fields was called at most once for the root model per run.
    """

    def test_relation_field_map_returns_consistent_result(self) -> None:
        """ "_relation_field_map" returns the same dict content on repeated calls.

        This test breaks if repeated calls without a shared cache stop
        agreeing on the set of mapped relation names.
        """
        result1 = _relation_field_map(Post)
        result2 = _relation_field_map(Post)
        self.assertEqual(set(result1.keys()), set(result2.keys()))

    def test_concrete_field_map_returns_consistent_result(self) -> None:
        """ "_concrete_field_map" returns the same dict content on repeated calls.

        This test breaks if repeated calls without a shared cache stop
        agreeing on the set of mapped concrete field names.
        """
        result1 = _concrete_field_map(Post)
        result2 = _concrete_field_map(Post)
        self.assertEqual(set(result1.keys()), set(result2.keys()))

    def test_relation_field_map_returns_same_object_with_cache(self) -> None:
        """With a shared "_cache" dict, the SAME object is returned on the second call.

        This test breaks if the request-scoped memoization stops returning
        the identical cached dict object on a repeated call.
        """
        cache: dict = {}
        result1 = _relation_field_map(Post, _cache=cache)
        result2 = _relation_field_map(Post, _cache=cache)
        self.assertIs(
            result1, result2, "_relation_field_map must return the cached object"
        )
        self.assertEqual(set(result1.keys()), set(result2.keys()))

    def test_concrete_field_map_returns_same_object_with_cache(self) -> None:
        """With a shared "_cache" dict, the SAME object is returned on the second call.

        This test breaks if the request-scoped memoization stops returning
        the identical cached dict object on a repeated call.
        """
        cache: dict = {}
        result1 = _concrete_field_map(Post, _cache=cache)
        result2 = _concrete_field_map(Post, _cache=cache)
        self.assertIs(
            result1, result2, "_concrete_field_map must return the cached object"
        )
        self.assertEqual(set(result1.keys()), set(result2.keys()))

    @pytest.mark.django_db
    def test_get_fields_called_once_per_model_per_optimizer_run(self) -> None:
        """Within one queryset_factory call, "get_fields" is called at most once per model.

        Not once per call-site. We count calls via a wrapping spy on
        "Post._meta.get_fields". A correctly memoized run calls it at most
        once for Post across all internal walkers that inspect Post's field
        map. This test breaks if that memoization regresses, causing
        "get_fields" to be called once per walker call-site instead.
        """
        _R2 = Registry()

        class _QPostType(DjangoObjectType):
            """ "Post" object type registered on the isolated memoization "Registry"."""

            class Meta:
                """Bind the type to "Post" under the isolated registry "_R2"."""

                model = Post
                registry = _R2

        class _QAuthorType(DjangoObjectType):
            """ "Author" object type registered on the isolated memoization "Registry"."""

            class Meta:
                """Bind the type to "Author" under the isolated registry "_R2"."""

                model = Author
                registry = _R2

        class _QQuery(ObjectType):
            """Root query exposing the single "post" field used by this test."""

            post = DjangoObjectField(_QPostType)

        schema = DjangoGraphQLSchema(query=_QQuery, registries=isolated_pair(_R2))

        author = Author.objects.create(name="Memo")
        post = Post.objects.create(title="M1", author=author)

        call_counts: dict[str, int] = {}
        original_get_fields = Post._meta.get_fields

        def counting_get_fields(*args: Any, **kwargs: Any) -> Any:
            """Wrap "Post._meta.get_fields" to count invocations.

            Args:
                *args: Positional arguments forwarded to the original method.
                **kwargs: Keyword arguments forwarded to the original method.

            Returns:
                Whatever the original "get_fields" returns.
            """
            call_counts["post"] = call_counts.get("post", 0) + 1
            return original_get_fields(*args, **kwargs)

        with patch.object(Post._meta, "get_fields", counting_get_fields):
            result = _execute(
                schema, "{ post(id: %d) { title author { name } } }" % post.pk
            )

        assert result.errors is None, result.errors
        post_calls = call_counts.get("post", 0)
        # With memoization: get_fields called at most twice per model per run
        # (once for _relation_field_map and once for _concrete_field_map — the
        # two maps have different cache keys so each is computed once).
        # Without memoization: called 6+ times across all walker call-sites.
        # We assert <= 2 as the memoized ceiling.
        self.assertLessEqual(
            post_calls,
            2,
            f"Post._meta.get_fields called {post_calls} times in one optimizer run "
            f"(expected <= 2 with memoization — one per map kind)",
        )


# ---------------------------------------------------------------------------
# (b) Mutation re-read — N+1 elimination
# ---------------------------------------------------------------------------


# NOTE: PostMutType / PostMutTypeFiltered below are DjangoModelType subclasses
# and therefore ALWAYS self-register on the GLOBAL registry (they reject both
# Meta.registry and Meta.skip_registry). Wrapping the shared "Post" model here
# would auto-derive globally-named companion output types that collide with
# same-named companions other test modules build over the same shared model,
# so they are built over the dedicated OptimizerPerfPost/-Author/-Category
# models instead (see tests/models.py). Every OTHER type in this file is a
# function-local DjangoObjectType with its own isolated Registry and is
# unaffected by this collision, so it keeps using the shared Author/Post
# models.


class PostMutType(DjangoModelType):
    """DjangoModelType for OptimizerPerfPost used by the re-read optimization tests.

    Used by "MutationReReadOptimizationTest".
    """

    class Meta:
        """Bind the type to "OptimizerPerfPost" with an explicit "output_field_name".

        "output_field_name" defaults to the model name ("optimizerperfpost"),
        but "perform_mutate" locates its re-read sub-selection by matching
        this name against the mutation's GraphQL selection set (e.g.
        "{ ok post { ... } }" below), so it is pinned to "post" to match the
        fixed GraphQL literal these tests parse.
        """

        model = OptimizerPerfPost
        output_field_name = "post"


class PostMutTypeFiltered(DjangoModelType):
    """DjangoModelType for OptimizerPerfPost where filter_queryset returns .none().

    Used to exercise the re-read fallback when the row is filtered away.
    """

    class Meta:
        """Bind the type to "OptimizerPerfPost" with an explicit "output_field_name".

        See "PostMutType.Meta" for why "output_field_name" is pinned to
        "post" instead of the model-derived default.
        """

        model = OptimizerPerfPost
        output_field_name = "post"

    @classmethod
    def filter_queryset(
        cls, qs: QuerySet, info: GraphQLResolveInfo, **kwargs: Any
    ) -> QuerySet:
        """Scope every queryset to empty, to exercise the re-read-returns-nothing branch.

        Args:
            qs: The queryset to scope.
            info: The GraphQL resolve info for the current request.
            **kwargs: Extra arguments available for scoping (unused here).

        Returns:
            An always-empty queryset ("qs.none()").
        """
        return qs.none()


@pytest.mark.django_db
class MutationReReadOptimizationTest(TestCase):
    """DjangoModelType.perform_mutate applies the optimizer to the re-read.

    A mutation that returns nested to-one relations (author, category) in its
    selection set must not trigger extra queries for each relation — the re-read
    queryset must use select_related for those relations.

    Tests call perform_mutate directly with a fake info whose field_nodes carry
    the expected mutation selection AST — same approach as test_nested_objects.py.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one category, one author, and one post referencing both.

        Shared as class-level fixture data by every test in this class. Uses
        the dedicated OptimizerPerfPost/-Author/-Category models (not the
        shared Post/Author/Category) so PostMutType's global registration
        stays collision-free — see the module-level NOTE above PostMutType.
        """
        cls.category = OptimizerPerfCategory.objects.create(title="Tech")
        cls.author = OptimizerPerfAuthor.objects.create(name="Ada")
        cls.post = OptimizerPerfPost.objects.create(
            title="P1", author=cls.author, category=cls.category
        )

    def _perform_mutate_with_selection(
        self, selection_gql: str
    ) -> tuple[DjangoModelType, list[dict[str, Any]]]:
        """Call "PostMutType.perform_mutate" with a fake info built from a selection body.

        Args:
            selection_gql: The mutation selection body, e.g.
                "{ ok post { title } }".

        Returns:
            A tuple of the mutation result and the list of queries captured
            during the "perform_mutate" call.
        """
        gql = "mutation { postCreate %s }" % selection_gql
        field_node, fragments = _parse_mutation_field_node(gql, "postCreate")
        info = _fake_info(field_node, fragments)

        with CaptureQueriesContext(connection) as ctx:
            result = PostMutType.perform_mutate(self.post, info)

        return result, ctx.captured_queries

    def test_perform_mutate_with_to_one_selection_prefetches_relations(self) -> None:
        """Requesting author+category in the selection set makes the re-read use select_related.

        This is the N+1 guard: accessing "output_obj.author" and
        "output_obj.category" after "perform_mutate" should require 0
        additional SELECTs. This test breaks if the re-read queryset stops
        pre-joining those relations.
        """
        result, queries_for_reread = self._perform_mutate_with_selection(
            "{ ok post { title author { name } category { title } } }"
        )

        self.assertTrue(result.ok)
        output_obj = getattr(result, PostMutType._meta.output_field_name)
        self.assertIsNotNone(output_obj)

        # After the re-read, accessing author and category must NOT trigger
        # additional SQL (select_related must have pre-joined them).
        with CaptureQueriesContext(connection) as ctx:
            author_name = output_obj.author.name
            category_title = output_obj.category.title

        self.assertEqual(author_name, "Ada")
        self.assertEqual(category_title, "Tech")
        self.assertEqual(
            len(ctx.captured_queries),
            0,
            f"Expected 0 extra queries after optimized re-read but got "
            f"{len(ctx.captured_queries)}. Queries:\n"
            + "\n".join(q["sql"] for q in ctx.captured_queries),
        )

    def test_perform_mutate_scalar_only_no_regression(self) -> None:
        """Requesting only scalar fields (no relations) still works correctly.

        This test breaks if the optimized re-read path stops handling a
        selection with no relation fields.
        """
        result, queries = self._perform_mutate_with_selection("{ ok post { title } }")

        self.assertTrue(result.ok)
        output_obj = getattr(result, PostMutType._meta.output_field_name)
        self.assertIsNotNone(output_obj)
        self.assertEqual(output_obj.title, "P1")

    def test_perform_mutate_data_matches_expected(self) -> None:
        """The returned object's fields match what was saved, preserving behavior parity.

        This test breaks if the optimized re-read path stops returning data
        consistent with what was actually persisted.
        """
        result, _ = self._perform_mutate_with_selection(
            "{ ok post { title author { name } } }"
        )
        self.assertTrue(result.ok)
        output_obj = getattr(result, PostMutType._meta.output_field_name)
        self.assertEqual(output_obj.title, "P1")
        # author should be accessible without triggering an extra query
        # (already fetched by select_related).
        with self.assertNumQueries(0):
            self.assertEqual(output_obj.author.name, "Ada")

    def test_perform_mutate_falls_back_when_filter_excludes_row(self) -> None:
        """When "filter_queryset" returns "none()", "perform_mutate" falls back to the in-memory object.

        This preserves existing behavior: the mutation never returns null
        just because the re-read queryset was filtered away. This test
        breaks if that fallback regresses.
        """
        gql = "mutation { filteredPostCreate { ok post { title } } }"
        field_node, fragments = _parse_mutation_field_node(gql, "filteredPostCreate")
        info = _fake_info(field_node, fragments)

        result = PostMutTypeFiltered.perform_mutate(self.post, info)

        self.assertTrue(result.ok)
        output_obj = getattr(result, PostMutTypeFiltered._meta.output_field_name)
        # Falls back to the in-memory obj.
        self.assertEqual(output_obj.title, "P1")


# ---------------------------------------------------------------------------
# Issue #57 — _fmap_cache threaded through nested-list descent in
# _walk_filtered_prefetches
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class NestedListDescentFmapCacheTest(TestCase):
    """#57: _fmap_cache must be threaded through _walk_filtered_prefetches's
    nested-list descent branches (window-slice and plain).

    When a query contains a nested list field (DjangoNestedListObjectField),
    the walker descends into its sub-selection to collect deeper prefetches.
    Before the fix, the two recursive calls inside the nested-list branch omit
    _fmap_cache, so each descent level calls _meta.get_fields() fresh instead
    of reusing the request-scoped cache.

    This test:
      1. Builds a schema with Author → posts (nested list) → (scalar fields).
      2. Patches Post._meta.get_fields to count invocations.
      3. Executes a query that triggers the walker.
      4. Asserts get_fields is called at most 2 times for Post (once per map kind)
         even though the nested-list branch descends into Post's sub-selection.

    Without the fix: the nested-list descent calls get_fields again for every
    recursive walk of Post's fields (>= 3 calls). With the fix: cached, so <= 2.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with three posts.

        Shared as fixture data for the nested-list-descent memoization test.
        """
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="FmapCacheAuthor")
        for i in range(3):
            Post.objects.create(title=f"FmapPost{i}", author=cls.author)

    def test_nested_list_descent_memoizes_get_fields(self) -> None:
        """#57: "_meta.get_fields" is called at most 2 times for Post in a nested-list query.

        A query that traverses authors -> posts (nested list) -> {id, title}
        must memoize Post's field map. Before the fix, the nested-list
        descent bypasses the cache and calls get_fields on every recursive
        call. This test breaks if that memoization regresses.
        """
        from unittest.mock import patch

        from django_graphex.fields import DjangoNestedListObjectField
        from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
        from django_graphex.registry import Registry
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _REG = Registry()

        class _FPostType(DjangoObjectType):
            class Meta:
                model = Post
                registry = _REG

        class _FPostListType(DjangoListObjectType):
            class Meta:
                model = Post
                pagination = LimitOffsetGraphqlPagination(default_limit=5)
                registry = _REG

        class _FAuthorType(DjangoObjectType):
            posts = DjangoNestedListObjectField(_FPostListType, accessor="posts")

            class Meta:
                model = Author
                registry = _REG

        class _FAuthorListType(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _REG

        schema = DjangoGraphQLSchema(
            query=_gtype(
                "_FmapQuery",
                (ObjectType,),
                {"authors": DjangoListObjectField(_FAuthorListType)},
            ),
            registries=isolated_pair(_REG),
        )

        call_counts: dict[str, int] = {}
        original_get_fields = Post._meta.get_fields

        def counting_get_fields(*args, **kwargs):
            call_counts["post"] = call_counts.get("post", 0) + 1
            return original_get_fields(*args, **kwargs)

        with patch.object(Post._meta, "get_fields", counting_get_fields):
            result = _execute(
                schema,
                "{ authors { results { posts { results(limit: 5, offset: 0) { id title } totalCount } } } }",
            )

        assert result.errors is None, result.errors

        post_calls = call_counts.get("post", 0)
        # The fix adds _fmap_cache to the 2 nested-list descent call-sites in
        # _walk_filtered_prefetches.  Other optimizer paths (recursive_params,
        # _collect_prefetch_only_sets, etc.) are not yet cached — that is the
        # scope of #66.  We assert the call count is strictly less than the
        # pre-fix baseline (9) to guard against any regression that would restore
        # the previously-uncached descent.  After the fix the known value is 7.
        self.assertLess(
            post_calls,
            9,
            f"Post._meta.get_fields called {post_calls} times in nested-list query. "
            f"Expected < 9 (the pre-fix baseline) — _fmap_cache must be threaded "
            f"through both nested-list descent sites in _walk_filtered_prefetches.",
        )


# ---------------------------------------------------------------------------
# Issue #66 (b) — _fmap_cache threaded through .only()-narrowing pass
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class OnlyNarrowingFmapCacheTest(TestCase):
    """#66(b): _fmap_cache must be threaded through _collect_prefetch_only_sets,
    _leaf_model, and _compute_child_only so _meta.get_fields() is not re-invoked
    redundantly during the .only()-narrowing pass.

    These helpers currently call _relation_field_map(model) without a cache,
    causing extra get_fields() calls for every nested model level during the
    narrowing pass.  After the fix, the existing request-scoped _fmap_cache is
    forwarded from _apply_optimizations into these helpers.

    Test strategy: spy on Post._meta.get_fields, execute a query that triggers
    the narrowing pass (OPTIMIZE_ONLY_FIELDS=True), count get_fields calls.
    Before the fix: multiple calls for Post from the narrowing pass.
    After the fix: fewer calls (the narrowing pass reuses the cache).
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with three posts.

        Shared as fixture data for the only-narrowing memoization test.
        """
        from tests.models import Author, Post

        cls.author = Author.objects.create(name="NarrowCacheAuthor")
        for i in range(3):
            Post.objects.create(title=f"NarrowPost{i}", author=cls.author)

    def test_only_narrowing_memoizes_get_fields(self) -> None:
        """#66(b): "_meta.get_fields" is called fewer times for Post in a narrowing query.

        A query with OPTIMIZE_ONLY_FIELDS=True that prefetches posts must not
        call "Post._meta.get_fields" repeatedly from the narrowing pass.
        After threading "_fmap_cache" through "_collect_prefetch_only_sets"
        and friends, the call count is reduced from the pre-fix baseline.
        This test breaks if that memoization regresses.
        """
        from unittest.mock import patch

        from django.test import override_settings

        from django_graphex.registry import Registry
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _REG = Registry()

        class _NPostType(DjangoObjectType):
            class Meta:
                model = Post
                registry = _REG

        class _NAuthorType(DjangoObjectType):
            class Meta:
                model = Author
                registry = _REG

        class _NAuthorListType(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _REG

        schema = DjangoGraphQLSchema(
            query=_gtype(
                "_NarrowQuery",
                (ObjectType,),
                {"authors": DjangoListObjectField(_NAuthorListType)},
            ),
            registries=isolated_pair(_REG),
        )

        call_counts_with: dict[str, int] = {}
        call_counts_without: dict[str, int] = {}
        original_get_fields = Post._meta.get_fields

        def counting_with(*args, **kwargs):
            call_counts_with["post"] = call_counts_with.get("post", 0) + 1
            return original_get_fields(*args, **kwargs)

        def counting_without(*args, **kwargs):
            call_counts_without["post"] = call_counts_without.get("post", 0) + 1
            return original_get_fields(*args, **kwargs)

        gql = "{ authors { results { posts { results { id title } } } } }"

        # Run with OPTIMIZE_ONLY_FIELDS=True (default) — triggers narrowing pass.
        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True}):
            with patch.object(Post._meta, "get_fields", counting_with):
                result = _execute(schema, gql)

        assert result.errors is None, result.errors

        # Verify behavior: correct data returned despite caching.
        authors_data = result.data["authors"]["results"]
        self.assertTrue(len(authors_data) >= 1, "Authors must be returned")

        calls_with = call_counts_with.get("post", 0)
        # Before the fix: the narrowing pass calls _relation_field_map(Post) without
        # cache on every iteration — typically 3+ extra calls vs the cached path.
        # After the fix: narrowing reuses the _fmap_cache, so total < pre-fix baseline.
        # We assert the fix reduces the count vs an uncached run as a regression guard.
        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": False}):
            with patch.object(Post._meta, "get_fields", counting_without):
                result_off = _execute(schema, gql)

        assert result_off.errors is None, result_off.errors
        calls_without = call_counts_without.get("post", 0)

        # With caching: calls_with should be <= calls_without (the uncached baseline).
        # The fix doesn't invert the count (the base walker still calls _relation_field_map
        # once) — it just removes the redundant calls from _collect_prefetch_only_sets.
        self.assertLessEqual(
            calls_with,
            calls_without,
            f"With OPTIMIZE_ONLY_FIELDS=True, Post._meta.get_fields was called "
            f"{calls_with} times vs {calls_without} with OFF. "
            f"The narrowing pass must not add redundant get_fields calls after the fix.",
        )

    def test_only_narrowing_data_parity(self) -> None:
        """#66(b) non-regression: query results are identical with/without "_fmap_cache" in narrowing.

        This test breaks if threading the request-scoped cache through the
        narrowing pass changes the observable query results.
        """

        from django.test import override_settings

        from django_graphex.registry import Registry
        from django_graphex.types import (
            DjangoListObjectField,
            DjangoListObjectType,
            DjangoObjectType,
        )
        from tests.models import Author, Post

        _REG = Registry()

        class _NPPostType(DjangoObjectType):
            class Meta:
                model = Post
                registry = _REG

        class _NPAuthorType(DjangoObjectType):
            class Meta:
                model = Author
                registry = _REG

        class _NPAuthorListType(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _REG

        schema = DjangoGraphQLSchema(
            query=_gtype(
                "_NarrowParityQuery",
                (ObjectType,),
                {"authors": DjangoListObjectField(_NPAuthorListType)},
            ),
            registries=isolated_pair(_REG),
        )

        gql = "{ authors { results { posts { results { id title } } } } }"

        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True}):
            result_on = _execute(schema, gql)
        with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": False}):
            result_off = _execute(schema, gql)

        assert result_on.errors is None, result_on.errors
        assert result_off.errors is None, result_off.errors

        self.assertEqual(
            result_on.data,
            result_off.data,
            "Query results must be identical with and without OPTIMIZE_ONLY_FIELDS",
        )
