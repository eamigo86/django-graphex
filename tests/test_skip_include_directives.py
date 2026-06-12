# -*- coding: utf-8 -*-
"""Tests for @skip/@include directive handling in cost analysis, depth limiting,
and query optimizer.

Issue: #12 — @skip/@include directives must be honored by cost analysis, depth
limit, and the query optimizer walkers.

Scenarios covered:
  - @skip(if: true)  → field/subtree excluded from cost, depth, optimizer paths
  - @skip(if: false) → field/subtree INCLUDED
  - @include(if: true)  → field/subtree INCLUDED
  - @include(if: false) → field/subtree excluded
  - @skip(if: $var) unresolved at validation time → CONSERVATIVE (counted)
  - @skip(if: $var) bound to false → INCLUDED
  - @skip(if: $var) bound to true → excluded (reporting path with bound vars)
  - Directives on FieldNode, InlineFragmentNode, FragmentSpreadNode
  - Cost reporting path (analyze_cost) with bound variable_values
  - Depth rule
  - recursive_params / _collect_only_fields (optimizer walkers)
"""

from __future__ import annotations

from types import SimpleNamespace

import graphene
import pytest
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)
from graphql.language.ast import FragmentDefinitionNode, OperationDefinitionNode

from django_graphex import (
    CostLimitValidationRule,
    DepthLimitValidationRule,
    DjangoListObjectType,
    DjangoObjectType,
)
from django_graphex.cost import analyze_cost
from django_graphex.utils import _collect_only_fields, _relation_field_map, recursive_params

from .models import Author, Post


# --------------------------------------------------------------------------- #
# Schema helpers                                                                 #
# --------------------------------------------------------------------------- #

def _build_cost_schema():
    """companies(limit) -> properties(limit) -> owner -> name."""
    owner = GraphQLObjectType("Owner", {"name": GraphQLField(GraphQLString)})
    prop = GraphQLObjectType("Property", {"owner": GraphQLField(owner)})
    company = GraphQLObjectType(
        "Company",
        {
            "name": GraphQLField(GraphQLString),
            "properties": GraphQLField(
                GraphQLList(prop), args={"limit": GraphQLArgument(GraphQLInt)}
            ),
        },
    )
    query = GraphQLObjectType(
        "Query",
        {
            "companies": GraphQLField(
                GraphQLList(company), args={"limit": GraphQLArgument(GraphQLInt)}
            ),
        },
    )
    return GraphQLSchema(query=query, types=[company, prop, owner])


def _build_depth_schema():
    node = GraphQLObjectType(
        "Node",
        lambda: {
            "name": GraphQLField(GraphQLString),
            "child": GraphQLField(node),
        },
    )
    node.graphene_type = SimpleNamespace(_meta=SimpleNamespace(max_deep=2))
    query = GraphQLObjectType("Query", {"root": GraphQLField(node)})
    return GraphQLSchema(query=query, types=[node])


def _cost(schema, query_str, variables=None):
    return analyze_cost(schema, parse(query_str), variable_values=variables).total


def _depth_errors(schema, query_str):
    return validate(schema, parse(query_str), [DepthLimitValidationRule])


# --------------------------------------------------------------------------- #
# Helpers: parse a GraphQL string for the optimizer walker tests               #
# --------------------------------------------------------------------------- #
def _parse_optimizer(query_str):
    document = parse(query_str)
    fragments = {
        d.name.value: d
        for d in document.definitions
        if isinstance(d, FragmentDefinitionNode)
    }
    operation = next(
        d for d in document.definitions if isinstance(d, OperationDefinitionNode)
    )
    return operation.selection_set.selections[0].selection_set, fragments


def _params(query_str, model=Post):
    selection_set, fragments = _parse_optimizer(query_str)
    return recursive_params(
        selection_set, fragments, _relation_field_map(model), [], []
    )


def _only(query_str, model=Post):
    selection_set, fragments = _parse_optimizer(query_str)
    return _collect_only_fields(model, selection_set, fragments)


# ============================================================================ #
# COST: @skip/@include on FieldNode                                              #
# ============================================================================ #

class CostSkipIncludeFieldTest(TestCase):
    """@skip / @include on plain fields affect cost calculation."""

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_skip_if_true_excludes_field_from_cost(self):
        schema = _build_cost_schema()
        # companies @skip(if:true) → cost should be 0
        q = "{ companies(limit: 10) @skip(if: true) { properties(limit: 5) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_skip_if_false_includes_field_in_cost(self):
        schema = _build_cost_schema()
        # @skip(if:false) → field is selected → normal cost
        q = "{ companies(limit: 10) @skip(if: false) { properties(limit: 5) { owner { name } } } }"
        cost = _cost(schema, q)
        self.assertGreater(cost, 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_include_if_false_excludes_field_from_cost(self):
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) @include(if: false) { properties(limit: 5) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_include_if_true_includes_field_in_cost(self):
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) @include(if: true) { properties(limit: 5) { owner { name } } } }"
        cost = _cost(schema, q)
        self.assertGreater(cost, 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_nested_skip_on_child_reduces_cost(self):
        """@skip on a child field reduces but does not zero the parent."""
        schema = _build_cost_schema()
        # companies(10) is counted; its properties child is @skip(if:true) → 0 children cost
        # companies own = 1, children = 0 → total = 1
        q = "{ companies(limit: 10) { properties(limit: 5) @skip(if: true) { owner { name } } } }"
        cost = _cost(schema, q)
        # properties skipped → companies = 1 (own) + 10*0 (no children)
        self.assertEqual(cost, 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_nested_include_false_on_child_reduces_cost(self):
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) { properties(limit: 5) @include(if: false) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 1)


# ============================================================================ #
# COST: @skip/@include on InlineFragmentNode                                     #
# ============================================================================ #

class CostSkipIncludeInlineFragmentTest(TestCase):
    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_inline_fragment_skip_if_true_excluded(self):
        schema = _build_cost_schema()
        q = """
        {
          companies(limit: 10) {
            ... on Company @skip(if: true) {
              properties(limit: 5) { owner { name } }
            }
          }
        }
        """
        # The inline fragment is skipped → no properties cost → companies = 1
        self.assertEqual(_cost(schema, q), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_inline_fragment_include_if_false_excluded(self):
        schema = _build_cost_schema()
        q = """
        {
          companies(limit: 10) {
            ... on Company @include(if: false) {
              properties(limit: 5) { owner { name } }
            }
          }
        }
        """
        self.assertEqual(_cost(schema, q), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_inline_fragment_skip_if_false_included(self):
        schema = _build_cost_schema()
        q = """
        {
          companies(limit: 10) {
            ... on Company @skip(if: false) {
              properties(limit: 5) { owner { name } }
            }
          }
        }
        """
        cost = _cost(schema, q)
        self.assertGreater(cost, 1)


# ============================================================================ #
# COST: @skip/@include on FragmentSpreadNode                                     #
# ============================================================================ #

class CostSkipIncludeFragmentSpreadTest(TestCase):
    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_fragment_spread_skip_if_true_excluded(self):
        schema = _build_cost_schema()
        q = """
        {
          companies(limit: 10) {
            ...PropsFragment @skip(if: true)
          }
        }
        fragment PropsFragment on Company {
          properties(limit: 5) { owner { name } }
        }
        """
        # Fragment spread is skipped → companies = 1 (own) + 10*0
        self.assertEqual(_cost(schema, q), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_fragment_spread_include_if_false_excluded(self):
        schema = _build_cost_schema()
        q = """
        {
          companies(limit: 10) {
            ...PropsFragment @include(if: false)
          }
        }
        fragment PropsFragment on Company {
          properties(limit: 5) { owner { name } }
        }
        """
        self.assertEqual(_cost(schema, q), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_fragment_spread_skip_if_false_included(self):
        schema = _build_cost_schema()
        q = """
        {
          companies(limit: 10) {
            ...PropsFragment @skip(if: false)
          }
        }
        fragment PropsFragment on Company {
          properties(limit: 5) { owner { name } }
        }
        """
        cost = _cost(schema, q)
        self.assertGreater(cost, 1)


# ============================================================================ #
# COST: variable-driven directives — conservative fallback                       #
# ============================================================================ #

class CostVariableDirectiveTest(TestCase):
    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_variable_skip_unresolved_at_validation_is_conservative(self):
        """During validation (no bound variables), @skip(if: $flag) → keep (safe)."""
        schema = _build_cost_schema()
        # CostLimitValidationRule uses {} for variable_values → conservative
        q = "{ companies(limit: 10) @skip(if: $flag) { properties(limit: 5) { owner { name } } } }"
        cost_no_vars = _cost(schema, q, variables={})
        cost_with_false = _cost(schema, q, variables={"flag": False})
        # Both should include the field (flag=False means NOT skipped; unbound = conservative)
        self.assertGreater(cost_no_vars, 0)
        self.assertGreater(cost_with_false, 0)
        # With flag=true (SKIP): field is excluded
        cost_with_true = _cost(schema, q, variables={"flag": True})
        self.assertEqual(cost_with_true, 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_variable_include_unresolved_is_conservative(self):
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) @include(if: $show) { properties(limit: 5) { owner { name } } } }"
        # Unbound $show → conservative → field counted
        self.assertGreater(_cost(schema, q, variables={}), 0)
        # show=false → field excluded
        self.assertEqual(_cost(schema, q, variables={"show": False}), 0)
        # show=true → field included
        self.assertGreater(_cost(schema, q, variables={"show": True}), 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "MAX_PAGE_SIZE": 1000})
    def test_cost_rule_at_validation_time_conservative_for_variable_directive(self):
        """The CostLimitValidationRule sees {} variables → must NOT skip → reports over-budget."""
        schema = _build_cost_schema()
        # companies(limit:10){properties(limit:5){owner{name}}} costs > 1
        q = "{ companies(limit: 10) @skip(if: $flag) { properties(limit: 5) { owner { name } } } }"
        errors = validate(schema, parse(q), [CostLimitValidationRule])
        # Conservative: field counted → rule fires (cost > 1)
        self.assertTrue(len(errors) > 0, "Expected cost-limit error for conservative variable skip")


# ============================================================================ #
# DEPTH: @skip/@include on FieldNode                                             #
# ============================================================================ #

class DepthSkipIncludeFieldTest(TestCase):
    def test_skip_if_true_on_nested_field_passes_depth_limit(self):
        """A deeply-nested field with @skip(if:true) must not trigger depth limit."""
        schema = _build_depth_schema()
        # Without @skip, this query (depth 3) would exceed max_deep=2 → error
        q = "{ root { child { child { child @skip(if: true) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")

    def test_include_if_false_on_nested_field_passes_depth_limit(self):
        schema = _build_depth_schema()
        q = "{ root { child { child { child @include(if: false) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")

    def test_skip_if_false_still_triggers_depth_limit(self):
        schema = _build_depth_schema()
        q = "{ root { child { child { child @skip(if: false) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertGreater(len(errors), 0, "Expected depth limit error for @skip(if:false)")

    def test_include_if_true_still_triggers_depth_limit(self):
        schema = _build_depth_schema()
        q = "{ root { child { child { child @include(if: true) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertGreater(len(errors), 0, "Expected depth limit error for @include(if:true)")


# ============================================================================ #
# DEPTH: @skip/@include on InlineFragmentNode                                    #
# ============================================================================ #

class DepthSkipIncludeInlineFragmentTest(TestCase):
    def test_inline_fragment_skip_if_true_avoids_depth_violation(self):
        schema = _build_depth_schema()
        # Without @skip, inline frag adds deep nesting → depth error
        q = """
        {
          root {
            child {
              child {
                ... on Node @skip(if: true) {
                  child { name }
                }
              }
            }
          }
        }
        """
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")

    def test_inline_fragment_include_if_false_avoids_depth_violation(self):
        schema = _build_depth_schema()
        q = """
        {
          root {
            child {
              child {
                ... on Node @include(if: false) {
                  child { name }
                }
              }
            }
          }
        }
        """
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")


# ============================================================================ #
# DEPTH: @skip/@include on FragmentSpreadNode                                    #
# ============================================================================ #

class DepthSkipIncludeFragmentSpreadTest(TestCase):
    def test_fragment_spread_skip_if_true_avoids_depth_violation(self):
        schema = _build_depth_schema()
        q = """
        {
          root {
            child {
              child {
                ...DeepFrag @skip(if: true)
              }
            }
          }
        }
        fragment DeepFrag on Node {
          child { name }
        }
        """
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")

    def test_fragment_spread_include_if_false_avoids_depth_violation(self):
        schema = _build_depth_schema()
        q = """
        {
          root {
            child {
              child {
                ...DeepFrag @include(if: false)
              }
            }
          }
        }
        fragment DeepFrag on Node {
          child { name }
        }
        """
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")


# ============================================================================ #
# DEPTH: variable-driven conservative fallback                                   #
# ============================================================================ #

class DepthVariableDirectiveTest(TestCase):
    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
    def test_variable_skip_at_validation_time_is_conservative(self):
        """DepthLimitValidationRule must treat @skip(if: $flag) conservatively (count it)."""
        schema = _build_depth_schema()
        # depth 3 > max 2 → should still error when $flag is unbound
        q = "{ root { child { child { child @skip(if: $flag) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertGreater(len(errors), 0, "Expected depth-limit error for conservative variable skip")


# ============================================================================ #
# OPTIMIZER: recursive_params — @skip/@include affects select/prefetch building #
# ============================================================================ #

class OptimizerRecursiveParamsSkipTest(TestCase):
    """@skip/@include on fields in the optimizer walker."""

    def test_skip_if_true_on_relation_not_added_to_select(self):
        # author is a FK → normally added to select_related
        # @skip(if:true) → should NOT be added
        select, prefetch = _params("{ p { author @skip(if: true) { name } } }")
        self.assertNotIn("author", select)

    def test_include_if_false_on_relation_not_added_to_select(self):
        select, prefetch = _params("{ p { author @include(if: false) { name } } }")
        self.assertNotIn("author", select)

    def test_skip_if_false_on_relation_is_added_to_select(self):
        select, prefetch = _params("{ p { author @skip(if: false) { name } } }")
        self.assertIn("author", select)

    def test_include_if_true_on_relation_is_added_to_select(self):
        select, prefetch = _params("{ p { author @include(if: true) { name } } }")
        self.assertIn("author", select)

    def test_skip_if_true_on_m2m_relation_not_added_to_prefetch(self):
        select, prefetch = _params("{ p { tags @skip(if: true) { label } } }")
        self.assertNotIn("tags", prefetch)

    def test_include_if_false_on_m2m_relation_not_added_to_prefetch(self):
        select, prefetch = _params("{ p { tags @include(if: false) { label } } }")
        self.assertNotIn("tags", prefetch)

    def test_skip_if_false_on_m2m_is_added_to_prefetch(self):
        select, prefetch = _params("{ p { tags @skip(if: false) { label } } }")
        self.assertIn("tags", prefetch)


class OptimizerRecursiveParamsFragmentSkipTest(TestCase):
    """@skip/@include on fragment spreads and inline fragments."""

    def test_fragment_spread_skip_if_true_relation_excluded(self):
        q = """
        { p { ...AuthorFrag @skip(if: true) } }
        fragment AuthorFrag on Post { author { name } }
        """
        select, prefetch = _params(q)
        self.assertNotIn("author", select)

    def test_fragment_spread_include_if_false_relation_excluded(self):
        q = """
        { p { ...AuthorFrag @include(if: false) } }
        fragment AuthorFrag on Post { author { name } }
        """
        select, prefetch = _params(q)
        self.assertNotIn("author", select)

    def test_fragment_spread_skip_if_false_relation_included(self):
        q = """
        { p { ...AuthorFrag @skip(if: false) } }
        fragment AuthorFrag on Post { author { name } }
        """
        select, prefetch = _params(q)
        self.assertIn("author", select)

    def test_inline_fragment_skip_if_true_relation_excluded(self):
        select, prefetch = _params(
            "{ p { ... on Post @skip(if: true) { author { name } } } }"
        )
        self.assertNotIn("author", select)

    def test_inline_fragment_include_if_false_relation_excluded(self):
        select, prefetch = _params(
            "{ p { ... on Post @include(if: false) { author { name } } } }"
        )
        self.assertNotIn("author", select)

    def test_inline_fragment_skip_if_false_relation_included(self):
        select, prefetch = _params(
            "{ p { ... on Post @skip(if: false) { author { name } } } }"
        )
        self.assertIn("author", select)


# ============================================================================ #
# OPTIMIZER: _collect_only_fields — @skip/@include affects .only() set          #
# ============================================================================ #

class OptimizerOnlyFieldsSkipTest(TestCase):
    """Skipped fields must not appear in the .only() projection."""

    def test_skip_if_true_field_not_in_only(self):
        only = _only("{ p { title @skip(if: true) author { name } } }")
        self.assertNotIn("title", only)

    def test_include_if_false_field_not_in_only(self):
        only = _only("{ p { title @include(if: false) author { name } } }")
        self.assertNotIn("title", only)

    def test_skip_if_false_field_in_only(self):
        only = _only("{ p { title @skip(if: false) } }")
        self.assertIn("title", only)

    def test_include_if_true_field_in_only(self):
        only = _only("{ p { title @include(if: true) } }")
        self.assertIn("title", only)

    def test_skip_fk_relation_removes_attname_from_only(self):
        """Skipped FK field means author_id should not appear in only set."""
        only = _only("{ p { author @skip(if: true) { name } title } }")
        self.assertNotIn("author_id", only)

    def test_include_false_fk_relation_removes_attname_from_only(self):
        only = _only("{ p { author @include(if: false) { name } title } }")
        self.assertNotIn("author_id", only)

    def test_fragment_spread_skip_if_true_field_excluded_from_only(self):
        q = """
        { p { ...TitleFrag @skip(if: true) } }
        fragment TitleFrag on Post { title }
        """
        only = _only(q)
        self.assertNotIn("title", only)

    def test_inline_fragment_include_if_false_field_excluded_from_only(self):
        only = _only(
            "{ p { ... on Post @include(if: false) { title } } }"
        )
        self.assertNotIn("title", only)
