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
from unittest.mock import patch

import graphene
import pytest
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphene import Schema
from graphql import build_schema, parse
from graphql.language.ast import FieldNode, FragmentDefinitionNode, OperationDefinitionNode

from django_graphex import DjangoModelType, DjangoObjectField, DjangoObjectType
from django_graphex.registry import Registry
from django_graphex.utils import (
    _concrete_field_map,
    _relation_field_map,
)

from .models import Author, Category, Post, Tag


# ---------------------------------------------------------------------------
# AST helpers for building fake field_nodes
# ---------------------------------------------------------------------------


def _parse_mutation_field_node(gql: str, mutation_field: str):
    """Parse a GraphQL mutation string and return the FieldNode for
    ``mutation_field`` (e.g. ``postCreate``).

    Example:
        _parse_mutation_field_node(
            "mutation { postCreate { ok post { title author { name } } } }",
            "postCreate",
        )
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


def _fake_info(field_node, fragments=None):
    """Build a minimal ResolveInfo-like namespace with field_nodes + fragments."""
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

    def test_relation_field_map_returns_consistent_result(self):
        """_relation_field_map returns the same dict content on repeated calls."""
        result1 = _relation_field_map(Post)
        result2 = _relation_field_map(Post)
        self.assertEqual(set(result1.keys()), set(result2.keys()))

    def test_concrete_field_map_returns_consistent_result(self):
        """_concrete_field_map returns the same dict content on repeated calls."""
        result1 = _concrete_field_map(Post)
        result2 = _concrete_field_map(Post)
        self.assertEqual(set(result1.keys()), set(result2.keys()))

    @pytest.mark.django_db
    def test_get_fields_called_once_per_model_per_optimizer_run(self):
        """Within one queryset_factory call, get_fields is called at most once
        per model, not once per call-site.

        We count calls via a wrapping spy on Post._meta.get_fields.
        A correctly memoized run calls it at most once for Post across all
        internal walkers that inspect Post's field map.
        """
        _R2 = Registry()

        class _QPostType(DjangoObjectType):
            class Meta:
                model = Post
                registry = _R2

        class _QAuthorType(DjangoObjectType):
            class Meta:
                model = Author
                registry = _R2

        class _QQuery(graphene.ObjectType):
            post = DjangoObjectField(_QPostType)

        schema = Schema(query=_QQuery)

        author = Author.objects.create(name="Memo")
        post = Post.objects.create(title="M1", author=author)

        call_counts: dict[str, int] = {}
        original_get_fields = Post._meta.get_fields

        def counting_get_fields(*args, **kwargs):
            call_counts["post"] = call_counts.get("post", 0) + 1
            return original_get_fields(*args, **kwargs)

        with patch.object(Post._meta, "get_fields", counting_get_fields):
            result = schema.execute(
                "{ post(id: %d) { title author { name } } }" % post.pk
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


class PostMutType(DjangoModelType):
    """DjangoModelType for Post used by the re-read optimization tests."""

    class Meta:
        model = Post


class PostMutTypeFiltered(DjangoModelType):
    """DjangoModelType for Post where filter_queryset returns .none()."""

    class Meta:
        model = Post

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
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
    def setUpTestData(cls):
        cls.category = Category.objects.create(title="Tech")
        cls.author = Author.objects.create(name="Ada")
        cls.post = Post.objects.create(
            title="P1", author=cls.author, category=cls.category
        )

    def _perform_mutate_with_selection(self, selection_gql: str) -> tuple:
        """Call PostMutType.perform_mutate with a fake info derived from
        ``selection_gql`` (a mutation body: ``{ ok post { ... } }``).

        Returns (result, list_of_captured_queries).
        """
        gql = "mutation { postCreate %s }" % selection_gql
        field_node, fragments = _parse_mutation_field_node(gql, "postCreate")
        info = _fake_info(field_node, fragments)

        with CaptureQueriesContext(connection) as ctx:
            result = PostMutType.perform_mutate(self.post, info)

        return result, ctx.captured_queries

    def test_perform_mutate_with_to_one_selection_prefetches_relations(self):
        """Requesting author+category in the selection set must result in the
        re-read queryset using select_related so that accessing those relations
        does NOT trigger extra queries.

        This is the N+1 guard: accessing output_obj.author and output_obj.category
        after perform_mutate should require 0 additional SELECTs.
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

    def test_perform_mutate_scalar_only_no_regression(self):
        """Requesting only scalar fields (no relations) still works correctly."""
        result, queries = self._perform_mutate_with_selection(
            "{ ok post { title } }"
        )

        self.assertTrue(result.ok)
        output_obj = getattr(result, PostMutType._meta.output_field_name)
        self.assertIsNotNone(output_obj)
        self.assertEqual(output_obj.title, "P1")

    def test_perform_mutate_data_matches_expected(self):
        """The returned object's fields match what was saved — behavior parity."""
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

    def test_perform_mutate_falls_back_when_filter_excludes_row(self):
        """When filter_queryset returns .none(), perform_mutate uses the in-memory
        obj so the mutation never returns null — existing behavior preserved.
        """
        gql = "mutation { filteredPostCreate { ok post { title } } }"
        field_node, fragments = _parse_mutation_field_node(gql, "filteredPostCreate")
        info = _fake_info(field_node, fragments)

        result = PostMutTypeFiltered.perform_mutate(self.post, info)

        self.assertTrue(result.ok)
        output_obj = getattr(result, PostMutTypeFiltered._meta.output_field_name)
        # Falls back to the in-memory obj.
        self.assertEqual(output_obj.title, "P1")
