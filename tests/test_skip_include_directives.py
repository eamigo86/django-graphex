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
from typing import Any

from django.db import models
from django.test import TestCase, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLError,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)
from graphql.language.ast import (
    FragmentDefinitionNode,
    OperationDefinitionNode,
    SelectionSetNode,
)

from django_graphex._directives_eval import is_selection_skipped
from django_graphex.core import ObjectType, field
from django_graphex.cost import CostLimitValidationRule, analyze_cost
from django_graphex.utils import (
    _collect_only_fields,
    _collect_only_fields_is_full_load,
    _relation_field_map,
    recursive_params,
)
from django_graphex.validation import DepthLimitValidationRule

from ._schema_isolation import isolated_pair
from .models import Post

# --------------------------------------------------------------------------- #
# Schema helpers                                                                 #
# --------------------------------------------------------------------------- #


def _build_cost_schema() -> GraphQLSchema:
    """Build a companies(limit) -> properties(limit) -> owner -> name schema.

    Returns:
        schema: The assembled graphql-core schema.
    """
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


def _build_depth_schema() -> GraphQLSchema:
    """Build a self-referencing "Node" schema with max_depth=2 for depth tests.

    Returns:
        schema: The assembled graphql-core schema.
    """
    node = GraphQLObjectType(
        "Node",
        lambda: {
            "name": GraphQLField(GraphQLString),
            "child": GraphQLField(node),
        },
    )
    node.graphene_type = SimpleNamespace(_meta=SimpleNamespace(max_depth=2))
    query = GraphQLObjectType("Query", {"root": GraphQLField(node)})
    return GraphQLSchema(query=query, types=[node])


def _cost(
    schema: GraphQLSchema, query_str: str, variables: dict[str, Any] | None = None
) -> int:
    """Compute the total estimated cost of a query against a schema.

    Args:
        schema: The graphql-core schema to cost the query against.
        query_str: The GraphQL query document text.
        variables: Bound variable values used to resolve "@skip"/"@include"
            conditions and variabled limits.

    Returns:
        total: The total estimated query cost.
    """
    return analyze_cost(schema, parse(query_str), variable_values=variables).total


def _depth_errors(schema: GraphQLSchema, query_str: str) -> list[GraphQLError]:
    """Run the depth-limit validation rule and collect its errors.

    Args:
        schema: The graphql-core schema to validate against.
        query_str: The GraphQL query document text.

    Returns:
        errors: The validation errors produced by
            "DepthLimitValidationRule" (empty when within the depth limit).
    """
    return validate(schema, parse(query_str), [DepthLimitValidationRule])


# --------------------------------------------------------------------------- #
# Helpers: parse a GraphQL string for the optimizer walker tests               #
# --------------------------------------------------------------------------- #
def _parse_optimizer(
    query_str: str,
) -> tuple[SelectionSetNode, dict[str, FragmentDefinitionNode]]:
    """Return the model-level selection set and fragments for "{ wrapper { ... } }".

    Args:
        query_str: A GraphQL query document with a single top-level
            wrapper field whose selection set is the one under test.

    Returns:
        parsed: A tuple of the wrapper field's selection set and a mapping
            of fragment name to its definition node.
    """
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


def _params(
    query_str: str, model: type[models.Model] = Post
) -> tuple[list[str], list[str]]:
    """Parse a query and compute its select_related/prefetch_related paths.

    Args:
        query_str: A GraphQL query document with a single top-level
            wrapper field whose selection set drives the path computation.
        model: The Django model the selection set is walked against.

    Returns:
        paths: A tuple of the computed select_related and prefetch_related
            path lists.
    """
    selection_set, fragments = _parse_optimizer(query_str)
    return recursive_params(
        selection_set, fragments, _relation_field_map(model), [], []
    )


def _only(query_str: str, model: type[models.Model] = Post) -> list[str]:
    """Parse a query and compute its conservative .only() column set.

    Args:
        query_str: A GraphQL query document with a single top-level
            wrapper field whose selection set drives the projection.
        model: The Django model the selection set is walked against.

    Returns:
        only: The computed list of column paths to pass to .only().
    """
    selection_set, fragments = _parse_optimizer(query_str)
    return _collect_only_fields(model, selection_set, fragments)


# ============================================================================ #
# COST: @skip/@include on FieldNode                                              #
# ============================================================================ #


class CostSkipIncludeFieldTest(TestCase):
    """@skip / @include on plain fields affect cost calculation.

    Covers literal true/false on both directives, plus a nested child
    field case.
    """

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_skip_if_true_excludes_field_from_cost(self) -> None:
        """Assert "@skip(if: true)" on a field zeroes its contribution to cost.

        If this fails, the cost estimator would count a field the
        directive marks as skipped, over-reporting the query's true cost.
        """
        schema = _build_cost_schema()
        # companies @skip(if:true) → cost should be 0
        q = "{ companies(limit: 10) @skip(if: true) { properties(limit: 5) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_skip_if_false_includes_field_in_cost(self) -> None:
        """Assert "@skip(if: false)" leaves a field's normal cost contribution intact.

        If this fails, a "@skip" directive resolving to false would still
        exclude the field from cost estimation.
        """
        schema = _build_cost_schema()
        # @skip(if:false) → field is selected → normal cost
        q = "{ companies(limit: 10) @skip(if: false) { properties(limit: 5) { owner { name } } } }"
        cost = _cost(schema, q)
        self.assertGreater(cost, 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_include_if_false_excludes_field_from_cost(self) -> None:
        """Assert "@include(if: false)" on a field zeroes its contribution to cost.

        If this fails, the cost estimator would count a field the
        directive marks as excluded, over-reporting the query's true cost.
        """
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) @include(if: false) { properties(limit: 5) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_include_if_true_includes_field_in_cost(self) -> None:
        """Assert "@include(if: true)" leaves a field's normal cost contribution intact.

        If this fails, an "@include" directive resolving to true would
        still exclude the field from cost estimation.
        """
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) @include(if: true) { properties(limit: 5) { owner { name } } } }"
        cost = _cost(schema, q)
        self.assertGreater(cost, 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_nested_skip_on_child_reduces_cost(self) -> None:
        """@skip on a child field reduces but does not zero the parent.

        If this fails, skipping a nested child field would either fail
        to reduce the parent's cost or would incorrectly zero out the
        parent field too.
        """
        schema = _build_cost_schema()
        # companies(10) is counted; its properties child is @skip(if:true) → 0 children cost
        # companies own = 1, children = 0 → total = 1
        q = "{ companies(limit: 10) { properties(limit: 5) @skip(if: true) { owner { name } } } }"
        cost = _cost(schema, q)
        # properties skipped → companies = 1 (own) + 10*0 (no children)
        self.assertEqual(cost, 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_nested_include_false_on_child_reduces_cost(self) -> None:
        """Assert "@include(if: false)" on a child field reduces the parent's cost.

        If this fails, excluding a nested child field via "@include"
        would fail to reduce the parent's estimated cost.
        """
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) { properties(limit: 5) @include(if: false) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 1)


# ============================================================================ #
# COST: @skip/@include on InlineFragmentNode                                     #
# ============================================================================ #


class CostSkipIncludeInlineFragmentTest(TestCase):
    """@skip / @include on inline fragments affect cost calculation.

    Covers literal true/false on both directives applied to an inline
    fragment.
    """

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_inline_fragment_skip_if_true_excluded(self) -> None:
        """Assert an inline fragment with "@skip(if: true)" contributes zero cost.

        If this fails, the cost estimator would still walk into a
        skipped inline fragment's selections.
        """
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
    def test_inline_fragment_include_if_false_excluded(self) -> None:
        """Assert an inline fragment with "@include(if: false)" contributes zero cost.

        If this fails, the cost estimator would still walk into an
        excluded inline fragment's selections.
        """
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
    def test_inline_fragment_skip_if_false_included(self) -> None:
        """Assert an inline fragment with "@skip(if: false)" keeps its cost contribution.

        If this fails, an inline fragment whose "@skip" resolves to
        false would still be excluded from cost estimation.
        """
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
    """@skip / @include on named fragment spreads affect cost calculation.

    Covers literal true/false on both directives applied to a named
    fragment spread.
    """

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_fragment_spread_skip_if_true_excluded(self) -> None:
        """Assert a fragment spread with "@skip(if: true)" contributes zero cost.

        If this fails, the cost estimator would still walk into a
        skipped named fragment's selections.
        """
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
    def test_fragment_spread_include_if_false_excluded(self) -> None:
        """Assert a fragment spread with "@include(if: false)" contributes zero cost.

        If this fails, the cost estimator would still walk into an
        excluded named fragment's selections.
        """
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
    def test_fragment_spread_skip_if_false_included(self) -> None:
        """Assert a fragment spread with "@skip(if: false)" keeps its cost contribution.

        If this fails, a named fragment spread whose "@skip" resolves to
        false would still be excluded from cost estimation.
        """
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
    """Cost estimation is conservative for @skip/@include driven by variables.

    Covers both directives unbound, bound true, and bound false, plus
    the validation-time cost rule.
    """

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_variable_skip_unresolved_at_validation_is_conservative(self) -> None:
        """During validation (no bound variables), @skip(if: $flag) keeps the field (safe).

        If this fails, an unbound "@skip" variable would either raise or
        optimistically exclude the field, instead of conservatively
        counting it.
        """
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
    def test_variable_include_unresolved_is_conservative(self) -> None:
        """Assert an unbound "@include" variable conservatively counts the field.

        If this fails, an unbound "@include" variable would either raise
        or pessimistically exclude the field, instead of conservatively
        counting it.
        """
        schema = _build_cost_schema()
        q = "{ companies(limit: 10) @include(if: $show) { properties(limit: 5) { owner { name } } } }"
        # Unbound $show → conservative → field counted
        self.assertGreater(_cost(schema, q, variables={}), 0)
        # show=false → field excluded
        self.assertEqual(_cost(schema, q, variables={"show": False}), 0)
        # show=true → field included
        self.assertGreater(_cost(schema, q, variables={"show": True}), 0)

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "MAX_PAGE_SIZE": 1000})
    def test_cost_rule_at_validation_time_conservative_for_variable_directive(
        self,
    ) -> None:
        """The CostLimitValidationRule sees {} variables and must not skip, so it reports over-budget.

        If this fails, the validation-time cost rule would optimistically
        skip a variable-gated field instead of conservatively counting
        it, silently allowing an over-budget query through.
        """
        schema = _build_cost_schema()
        # companies(limit:10){properties(limit:5){owner{name}}} costs > 1
        q = "{ companies(limit: 10) @skip(if: $flag) { properties(limit: 5) { owner { name } } } }"
        errors = validate(schema, parse(q), [CostLimitValidationRule])
        # Conservative: field counted → rule fires (cost > 1)
        self.assertTrue(
            len(errors) > 0, "Expected cost-limit error for conservative variable skip"
        )


# ============================================================================ #
# DEPTH: @skip/@include on FieldNode                                             #
# ============================================================================ #


class DepthSkipIncludeFieldTest(TestCase):
    """@skip / @include on plain fields affect depth-limit validation.

    Covers literal true/false on both directives applied to a deeply
    nested field.
    """

    def test_skip_if_true_on_nested_field_passes_depth_limit(self) -> None:
        """A deeply-nested field with @skip(if:true) must not trigger depth limit.

        If this fails, the depth-limit rule would still count a skipped
        field's nesting depth, rejecting a query that should pass.
        """
        schema = _build_depth_schema()
        # Without @skip, this query (depth 3) would exceed max_depth=2 → error
        q = "{ root { child { child { child @skip(if: true) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")

    def test_include_if_false_on_nested_field_passes_depth_limit(self) -> None:
        """Assert "@include(if: false)" on a deep field avoids a depth-limit violation.

        If this fails, the depth-limit rule would still count an
        excluded field's nesting depth, rejecting a query that should
        pass.
        """
        schema = _build_depth_schema()
        q = "{ root { child { child { child @include(if: false) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertEqual(len(errors), 0, f"Expected no depth errors but got: {errors}")

    def test_skip_if_false_still_triggers_depth_limit(self) -> None:
        """Assert "@skip(if: false)" on a deep field still triggers the depth limit.

        If this fails, a "@skip" directive resolving to false would
        incorrectly exempt the field's nesting depth from the limit.
        """
        schema = _build_depth_schema()
        q = "{ root { child { child { child @skip(if: false) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertGreater(
            len(errors), 0, "Expected depth limit error for @skip(if:false)"
        )

    def test_include_if_true_still_triggers_depth_limit(self) -> None:
        """Assert "@include(if: true)" on a deep field still triggers the depth limit.

        If this fails, an "@include" directive resolving to true would
        incorrectly exempt the field's nesting depth from the limit.
        """
        schema = _build_depth_schema()
        q = "{ root { child { child { child @include(if: true) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertGreater(
            len(errors), 0, "Expected depth limit error for @include(if:true)"
        )


# ============================================================================ #
# DEPTH: @skip/@include on InlineFragmentNode                                    #
# ============================================================================ #


class DepthSkipIncludeInlineFragmentTest(TestCase):
    """@skip / @include on inline fragments affect depth-limit validation.

    Covers literal true/false on both directives applied to a deeply
    nested inline fragment.
    """

    def test_inline_fragment_skip_if_true_avoids_depth_violation(self) -> None:
        """Assert a skipped inline fragment does not count toward the depth limit.

        If this fails, the depth-limit rule would still descend into a
        skipped inline fragment's selections.
        """
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

    def test_inline_fragment_include_if_false_avoids_depth_violation(self) -> None:
        """Assert an excluded inline fragment does not count toward the depth limit.

        If this fails, the depth-limit rule would still descend into an
        excluded inline fragment's selections.
        """
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
    """@skip / @include on named fragment spreads affect depth-limit validation.

    Covers literal true/false on both directives applied to a deeply
    nested named fragment spread.
    """

    def test_fragment_spread_skip_if_true_avoids_depth_violation(self) -> None:
        """Assert a skipped fragment spread does not count toward the depth limit.

        If this fails, the depth-limit rule would still descend into a
        skipped named fragment's selections.
        """
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

    def test_fragment_spread_include_if_false_avoids_depth_violation(self) -> None:
        """Assert an excluded fragment spread does not count toward the depth limit.

        If this fails, the depth-limit rule would still descend into an
        excluded named fragment's selections.
        """
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
    """Depth-limit validation is conservative for @skip/@include driven by variables.

    Covers the unbound-variable case at validation time.
    """

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
    def test_variable_skip_at_validation_time_is_conservative(self) -> None:
        """DepthLimitValidationRule treats "@skip(if: $flag)" conservatively (counts it).

        If this fails, an unbound "@skip" variable would optimistically
        exempt the field's nesting depth from the limit instead of
        conservatively counting it.
        """
        schema = _build_depth_schema()
        # depth 3 > max 2 → should still error when $flag is unbound
        q = "{ root { child { child { child @skip(if: $flag) { name } } } } }"
        errors = _depth_errors(schema, q)
        self.assertGreater(
            len(errors), 0, "Expected depth-limit error for conservative variable skip"
        )


# ============================================================================ #
# OPTIMIZER: recursive_params — @skip/@include affects select/prefetch building #
# ============================================================================ #


class OptimizerRecursiveParamsSkipTest(TestCase):
    """@skip/@include on fields in the optimizer walker.

    Covers forward-FK select_related and M2M prefetch_related paths
    under both directives.
    """

    def test_skip_if_true_on_relation_not_added_to_select(self) -> None:
        """Assert a "@skip(if: true)" forward FK is not added to select_related.

        If this fails, the optimizer would still select_related a
        relation whose only selection is skipped.
        """
        # author is a FK → normally added to select_related
        # @skip(if:true) → should NOT be added
        select, prefetch = _params("{ p { author @skip(if: true) { name } } }")
        self.assertNotIn("author", select)

    def test_include_if_false_on_relation_not_added_to_select(self) -> None:
        """Assert an "@include(if: false)" forward FK is not added to select_related.

        If this fails, the optimizer would still select_related a
        relation whose only selection is excluded.
        """
        select, prefetch = _params("{ p { author @include(if: false) { name } } }")
        self.assertNotIn("author", select)

    def test_skip_if_false_on_relation_is_added_to_select(self) -> None:
        """Assert a "@skip(if: false)" forward FK is still added to select_related.

        If this fails, a "@skip" directive resolving to false would
        incorrectly suppress the relation's optimization.
        """
        select, prefetch = _params("{ p { author @skip(if: false) { name } } }")
        self.assertIn("author", select)

    def test_include_if_true_on_relation_is_added_to_select(self) -> None:
        """Assert an "@include(if: true)" forward FK is still added to select_related.

        If this fails, an "@include" directive resolving to true would
        incorrectly suppress the relation's optimization.
        """
        select, prefetch = _params("{ p { author @include(if: true) { name } } }")
        self.assertIn("author", select)

    def test_skip_if_true_on_m2m_relation_not_added_to_prefetch(self) -> None:
        """Assert a "@skip(if: true)" M2M relation is not added to prefetch_related.

        If this fails, the optimizer would still prefetch_related a
        many-to-many relation whose only selection is skipped.
        """
        select, prefetch = _params("{ p { tags @skip(if: true) { label } } }")
        self.assertNotIn("tags", prefetch)

    def test_include_if_false_on_m2m_relation_not_added_to_prefetch(self) -> None:
        """Assert an "@include(if: false)" M2M relation is not added to prefetch_related.

        If this fails, the optimizer would still prefetch_related a
        many-to-many relation whose only selection is excluded.
        """
        select, prefetch = _params("{ p { tags @include(if: false) { label } } }")
        self.assertNotIn("tags", prefetch)

    def test_skip_if_false_on_m2m_is_added_to_prefetch(self) -> None:
        """Assert a "@skip(if: false)" M2M relation is still added to prefetch_related.

        If this fails, a "@skip" directive resolving to false would
        incorrectly suppress the many-to-many relation's optimization.
        """
        select, prefetch = _params("{ p { tags @skip(if: false) { label } } }")
        self.assertIn("tags", prefetch)


class OptimizerRecursiveParamsFragmentSkipTest(TestCase):
    """@skip/@include on fragment spreads and inline fragments.

    Covers both directives on named fragment spreads and inline
    fragments, for the optimizer's select_related path.
    """

    def test_fragment_spread_skip_if_true_relation_excluded(self) -> None:
        """Assert a skipped fragment spread's relation is excluded from select.

        If this fails, the optimizer would still select_related a
        relation reachable only through a skipped named fragment.
        """
        q = """
        { p { ...AuthorFrag @skip(if: true) } }
        fragment AuthorFrag on Post { author { name } }
        """
        select, prefetch = _params(q)
        self.assertNotIn("author", select)

    def test_fragment_spread_include_if_false_relation_excluded(self) -> None:
        """Assert an excluded fragment spread's relation is excluded from select.

        If this fails, the optimizer would still select_related a
        relation reachable only through an excluded named fragment.
        """
        q = """
        { p { ...AuthorFrag @include(if: false) } }
        fragment AuthorFrag on Post { author { name } }
        """
        select, prefetch = _params(q)
        self.assertNotIn("author", select)

    def test_fragment_spread_skip_if_false_relation_included(self) -> None:
        """Assert a fragment spread with "@skip(if: false)" still optimizes its relation.

        If this fails, a "@skip" directive resolving to false on a
        fragment spread would incorrectly suppress the relation's
        optimization.
        """
        q = """
        { p { ...AuthorFrag @skip(if: false) } }
        fragment AuthorFrag on Post { author { name } }
        """
        select, prefetch = _params(q)
        self.assertIn("author", select)

    def test_inline_fragment_skip_if_true_relation_excluded(self) -> None:
        """Assert a skipped inline fragment's relation is excluded from select.

        If this fails, the optimizer would still select_related a
        relation reachable only through a skipped inline fragment.
        """
        select, prefetch = _params(
            "{ p { ... on Post @skip(if: true) { author { name } } } }"
        )
        self.assertNotIn("author", select)

    def test_inline_fragment_include_if_false_relation_excluded(self) -> None:
        """Assert an excluded inline fragment's relation is excluded from select.

        If this fails, the optimizer would still select_related a
        relation reachable only through an excluded inline fragment.
        """
        select, prefetch = _params(
            "{ p { ... on Post @include(if: false) { author { name } } } }"
        )
        self.assertNotIn("author", select)

    def test_inline_fragment_skip_if_false_relation_included(self) -> None:
        """Assert an inline fragment with "@skip(if: false)" still optimizes its relation.

        If this fails, a "@skip" directive resolving to false on an
        inline fragment would incorrectly suppress the relation's
        optimization.
        """
        select, prefetch = _params(
            "{ p { ... on Post @skip(if: false) { author { name } } } }"
        )
        self.assertIn("author", select)


# ============================================================================ #
# OPTIMIZER: _collect_only_fields — @skip/@include affects .only() set          #
# ============================================================================ #


class OptimizerOnlyFieldsSkipTest(TestCase):
    """Skipped fields must not appear in the .only() projection.

    Covers plain fields, FK attnames, and fragment-scoped fields under
    both directives.
    """

    def test_skip_if_true_field_not_in_only(self) -> None:
        """Assert a field with "@skip(if: true)" is excluded from the .only() set.

        If this fails, the column projection would include a column the
        query never actually selects, wasting a needless load.
        """
        only = _only("{ p { title @skip(if: true) author { name } } }")
        self.assertNotIn("title", only)

    def test_include_if_false_field_not_in_only(self) -> None:
        """Assert a field with "@include(if: false)" is excluded from the .only() set.

        If this fails, the column projection would include a column the
        query never actually selects, wasting a needless load.
        """
        only = _only("{ p { title @include(if: false) author { name } } }")
        self.assertNotIn("title", only)

    def test_skip_if_false_field_in_only(self) -> None:
        """Assert a field with "@skip(if: false)" is still projected into .only().

        If this fails, a "@skip" directive resolving to false would
        incorrectly exclude a column the query actually needs.
        """
        only = _only("{ p { title @skip(if: false) } }")
        self.assertIn("title", only)

    def test_include_if_true_field_in_only(self) -> None:
        """Assert a field with "@include(if: true)" is still projected into .only().

        If this fails, an "@include" directive resolving to true would
        incorrectly exclude a column the query actually needs.
        """
        only = _only("{ p { title @include(if: true) } }")
        self.assertIn("title", only)

    def test_skip_fk_relation_removes_attname_from_only(self) -> None:
        """Skipped FK field means author_id should not appear in only set.

        If this fails, skipping a forward FK relation would still
        project its local attname column, wasting a needless load.
        """
        only = _only("{ p { author @skip(if: true) { name } title } }")
        self.assertNotIn("author_id", only)

    def test_include_false_fk_relation_removes_attname_from_only(self) -> None:
        """Assert an excluded FK relation's attname is dropped from .only().

        If this fails, excluding a forward FK relation would still
        project its local attname column, wasting a needless load.
        """
        only = _only("{ p { author @include(if: false) { name } title } }")
        self.assertNotIn("author_id", only)

    def test_fragment_spread_skip_if_true_field_excluded_from_only(self) -> None:
        """Assert a skipped fragment spread's field is excluded from .only().

        If this fails, the column collector would still project a
        column reachable only through a skipped named fragment.
        """
        q = """
        { p { ...TitleFrag @skip(if: true) } }
        fragment TitleFrag on Post { title }
        """
        only = _only(q)
        self.assertNotIn("title", only)

    def test_inline_fragment_include_if_false_field_excluded_from_only(self) -> None:
        """Assert an excluded inline fragment's field is excluded from .only().

        If this fails, the column collector would still project a
        column reachable only through an excluded inline fragment.
        """
        only = _only("{ p { ... on Post @include(if: false) { title } } }")
        self.assertNotIn("title", only)


# ============================================================================ #
# OPTIMIZER: _collect_only_fields_is_full_load / _collect_only_fields symmetry  #
# on @skip/@include with BOUND variables. The two walkers MUST make identical  #
# skip decisions (see the invariant comment on both function definitions in   #
# utils.py) — a divergence here would let one walker narrow ".only()" while  #
# the other still treats the same unknown leaf as forcing a full-load.        #
# ============================================================================ #


class OptimizerFullLoadDetectorVariableSkipSymmetryTest(TestCase):
    """'_collect_only_fields_is_full_load' and '_collect_only_fields' must
    agree on @skip/@include decisions once bound "variable_values" are threaded.
    """

    def test_skipped_unknown_leaf_via_bound_variable_is_consistent(self) -> None:
        """An unknown leaf gated by '@skip(if: $flag)' with 'flag=True' bound
        must be excluded by BOTH walkers: the full-load detector must return
        "False" (no full-load) and the column collector must not narrow the
        leaf in.

        Mutation: dropping the "variable_values" threading (or the
        "is_selection_skipped" check) from "_collect_only_fields_is_full_load"
        would make it ignore the bound variable and flip to full-load=True,
        diverging from "_collect_only_fields" -> RED.
        """
        query = "query ($flag: Boolean!) { p { title someProp @skip(if: $flag) } }"
        selection_set, fragments = _parse_optimizer(query)
        variables = {"flag": True}

        is_full = _collect_only_fields_is_full_load(
            Post, selection_set, fragments, variable_values=variables
        )
        only = _collect_only_fields(
            Post, selection_set, fragments, variable_values=variables
        )

        self.assertFalse(
            is_full,
            "The unknown leaf 'someProp' is @skip(if: true)-gated by a bound "
            "variable and must NOT flip full-load.",
        )
        self.assertNotIn("some_prop", only)
        self.assertNotIn("someProp", only)

    def test_included_unknown_leaf_via_bound_variable_is_consistent(self) -> None:
        """An unknown leaf gated by '@include(if: $flag)' with 'flag=False'
        bound must be excluded by BOTH walkers (symmetric to the @skip case).
        """
        query = "query ($flag: Boolean!) { p { title someProp @include(if: $flag) } }"
        selection_set, fragments = _parse_optimizer(query)
        variables = {"flag": False}

        is_full = _collect_only_fields_is_full_load(
            Post, selection_set, fragments, variable_values=variables
        )
        only = _collect_only_fields(
            Post, selection_set, fragments, variable_values=variables
        )

        self.assertFalse(is_full)
        self.assertNotIn("some_prop", only)
        self.assertNotIn("someProp", only)


# ============================================================================ #
# OPTIMIZER: _walk_filtered_prefetches — @skip/@include suppresses filtered DB  #
# query.  Issue #12 partial gap: nested filtered list with @skip(if:true) must  #
# NOT build or execute its Prefetch object.                                      #
#                                                                                #
# Query-count baseline (no directive): 3 queries                                 #
#   1. SELECT … FROM tests_author (list)                                         #
#   2. SELECT COUNT(*) … FROM tests_author (totalCount)                          #
#   3. SELECT … FROM tests_post WHERE title=… AND author_id IN (…) (filtered pf) #
# With @skip(if:true) / @include(if:false) on the posts field: query 3 MUST NOT #
# execute → expected count == 2.                                                  #
# ============================================================================ #


class OptimizerFilteredPrefetchSkipTest(TestCase):
    """@skip/@include on a nested filtered list suppresses the filtered-prefetch query.

    Covers both directives against the query-count baseline described above.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed a category, two authors, and one post per author.

        Two authors with separate posts let the filtered prefetch query
        be observed independent of the outer author list.
        """
        from tests.models import Author, Category, Post

        cls.cat = Category.objects.create(title="SkipFiltCat")
        cls.author1 = Author.objects.create(name="SkipFiltAuthor1")
        cls.author2 = Author.objects.create(name="SkipFiltAuthor2")
        Post.objects.create(title="SkipFiltPost", author=cls.author1, category=cls.cat)
        Post.objects.create(title="SkipFiltPost", author=cls.author2, category=cls.cat)

    def _schema(self):
        """Return the filtered-nested-list schema (reuses phase-e helper).

        Native build: model types subclass the native "DjangoObjectType" /
        "DjangoListObjectType" and the query root is a native "ObjectType"
        assembled with "DjangoGraphQLSchema". A per-instance "Registry" keeps
        these throwaway types out of the global registry.
        """
        from django_graphex.core import ObjectType
        from django_graphex.fields import (
            DjangoListObjectField,
            DjangoNestedListObjectField,
        )
        from django_graphex.registry import Registry
        from django_graphex.schema import DjangoGraphQLSchema
        from django_graphex.types import DjangoListObjectType, DjangoObjectType
        from tests.models import Author, Post

        _reg = Registry()

        class _SkipFiltPostListType(DjangoListObjectType):
            class Meta:
                model = Post
                filter_fields = {"title": ["exact"]}
                registry = _reg

        class _SkipFiltAuthorType(DjangoObjectType):
            posts = DjangoNestedListObjectField(_SkipFiltPostListType, accessor="posts")

            class Meta:
                model = Author
                registry = _reg

        class _SkipFiltAuthorListType(DjangoListObjectType):
            class Meta:
                model = Author
                registry = _reg

        class _SkipFiltQuery(ObjectType):
            authors = DjangoListObjectField(_SkipFiltAuthorListType)

        return DjangoGraphQLSchema(query=_SkipFiltQuery, registries=isolated_pair(_reg))

    def _exec(self, schema, query, variables=None):
        from graphql import graphql_sync

        result = graphql_sync(schema.graphql_schema, query, variable_values=variables)
        assert result.errors is None, result.errors
        return result.data

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_skip_if_true_suppresses_filtered_prefetch_query(self) -> None:
        """@skip(if:true) on a nested filtered list must NOT issue the filtered-prefetch query.

        Without the directive the query count is 2 (authors list + filtered-prefetch);
        the outer totalCount is selected after results so its lazy count reuses the
        materialized cache (no separate COUNT query). With @skip(if:true) it must be
        1 — the filtered-prefetch DB query is suppressed, leaving only the authors list.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        schema = self._schema()
        query = """
        {
          authors {
            results {
              posts(filter: {title: {exact: "SkipFiltPost"}}) @skip(if: true) {
                results { id title }
                totalCount
              }
            }
            totalCount
          }
        }
        """
        with CaptureQueriesContext(connection) as ctx:
            self._exec(schema, query)

        self.assertEqual(
            len(ctx.captured_queries),
            1,
            f"Expected 1 query (authors list; totalCount reuses cache), got "
            f"{len(ctx.captured_queries)}. "
            f"Filtered-prefetch query was not suppressed by @skip(if:true).\n"
            f"Queries: {[q['sql'] for q in ctx.captured_queries]}",
        )

    @override_settings(
        DJANGO_GRAPHEX={
            "OPTIMIZE_NESTED_PAGINATION": False,
            "OPTIMIZE_ONLY_FIELDS": False,
        }
    )
    def test_include_if_false_suppresses_filtered_prefetch_query(self) -> None:
        """@include(if:false) on a nested filtered list suppresses the filtered-prefetch query.

        If this fails, excluding a nested filtered list via "@include"
        would still issue its dedicated DB query, wasting a needless
        round-trip.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        schema = self._schema()
        query = """
        {
          authors {
            results {
              posts(filter: {title: {exact: "SkipFiltPost"}}) @include(if: false) {
                results { id title }
                totalCount
              }
            }
            totalCount
          }
        }
        """
        with CaptureQueriesContext(connection) as ctx:
            self._exec(schema, query)

        self.assertEqual(
            len(ctx.captured_queries),
            1,
            f"Expected 1 query (authors list; totalCount reuses cache), got "
            f"{len(ctx.captured_queries)}. "
            f"Filtered-prefetch query was not suppressed by @include(if:false).\n"
            f"Queries: {[q['sql'] for q in ctx.captured_queries]}",
        )


# ============================================================================ #
# Audit rank 18: @skip/@include are evaluated PER SELECTION (GraphQL spec).     #
# is_selection_skipped inspects ONLY the directives on the node it is given —   #
# a parent @skip(if:true) does NOT make the child node's OWN evaluation return  #
# True. (Transitive exclusion happens because the caller stops descending into  #
# a skipped subtree, NOT because the child inherits the parent's directive.)    #
# ============================================================================ #
class SkipIncludePerSelectionSemanticsTest(TestCase):
    """@skip/@include are per-selection: a node is judged only by its own directives.

    Covers a skipped parent with a clean child, and a clean parent with a
    skipped child.
    """

    @staticmethod
    def _selections(query_str):
        """Return the parent FieldNode and its first child FieldNode for
        '{ root @skip(if:true) { child } }'-shaped queries."""
        from graphql import parse
        from graphql.language.ast import OperationDefinitionNode

        document = parse(query_str)
        operation = next(
            d for d in document.definitions if isinstance(d, OperationDefinitionNode)
        )
        parent = operation.selection_set.selections[0]
        child = parent.selection_set.selections[0]
        return parent, child

    def test_parent_skip_does_not_cascade_to_child_own_evaluation(self) -> None:
        """A child with NO directives evaluates to NOT-skipped even when its
        parent carries @skip(if:true). The parent itself IS skipped."""
        parent, child = self._selections("{ root @skip(if: true) { child } }")
        # Parent's own directive: skipped.
        self.assertTrue(is_selection_skipped(parent, {}))
        # Child has no directives of its own -> NOT skipped, regardless of parent.
        self.assertFalse(is_selection_skipped(child, {}))

    def test_parent_include_false_does_not_cascade_to_child(self) -> None:
        """A parent @include(if:false) is excluded but the child node, evaluated
        on its own, is not (it has no directive)."""
        parent, child = self._selections("{ root @include(if: false) { child } }")
        self.assertTrue(is_selection_skipped(parent, {}))
        self.assertFalse(is_selection_skipped(child, {}))

    def test_child_with_own_skip_is_skipped_independently(self) -> None:
        """When the CHILD carries its own @skip(if:true), it is skipped — the
        evaluation is on the child's own directive, not the (clean) parent's."""
        parent, child = self._selections("{ root { child @skip(if: true) } }")
        # Parent has no directive -> not skipped.
        self.assertFalse(is_selection_skipped(parent, {}))
        # Child's own @skip(if:true) -> skipped.
        self.assertTrue(is_selection_skipped(child, {}))


# ============================================================================ #
# ITEM 2 (a)(b): END-TO-END DATA-ABSENCE through a compiled DjangoGraphQLSchema.#
# The existing coverage above proves cost/depth/optimizer walkers honor the     #
# directives (query counts), but none asserts the RESPONSE DATA map OMITS a      #
# skipped / included-out field (absent, not None). These execute variable-driven #
# and literal @skip/@include through a real native schema and inspect the data.  #
# ============================================================================ #
class _DirectiveDataQuery(ObjectType):
    """Two scalar root fields so @skip/@include data-absence is directly assertable."""

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    field_a = field(GraphQLString)
    field_b = field(GraphQLString)

    def resolve_field_a(self, info):
        return "A-value"

    def resolve_field_b(self, info):
        return "B-value"


def _directive_data_schema():
    """A compiled native 'DjangoGraphQLSchema' over '_DirectiveDataQuery'."""
    from django_graphex.schema import DjangoGraphQLSchema

    return DjangoGraphQLSchema(query=_DirectiveDataQuery)


class SkipIncludeExecutionDataAbsenceTest(TestCase):
    """@skip/@include remove a field from the RESPONSE DATA (absent, not None).

    Covers both variable-driven and literal boolean conditions.
    """

    def _exec(self, query, variables=None):
        from graphql import graphql_sync

        schema = _directive_data_schema()
        result = graphql_sync(schema.graphql_schema, query, variable_values=variables)
        assert result.errors is None, result.errors
        return result.data

    # -- (a) variable-driven @skip / @include ------------------------------- #
    def test_variable_skip_true_include_false_omit_both_fields(self) -> None:
        """Assert s=true makes fieldA absent (not None) and i=false makes fieldB absent.

        If this fails, a skipped or excluded field would be serialized
        as a null value instead of being omitted from the response data
        map entirely.
        """
        query = """
        query ($s: Boolean!, $i: Boolean!) {
          fieldA @skip(if: $s)
          fieldB @include(if: $i)
        }
        """
        data = self._exec(query, {"s": True, "i": False})
        # ABSENT from the map — the key must not be present at all.
        self.assertNotIn("fieldA", data)
        self.assertNotIn("fieldB", data)

    def test_variable_skip_false_include_true_keeps_both_fields(self) -> None:
        """Assert flipped variables keep both fields present with their resolved values.

        If this fails, the variable-driven directive path would
        incorrectly omit fields that should be included.
        """
        query = """
        query ($s: Boolean!, $i: Boolean!) {
          fieldA @skip(if: $s)
          fieldB @include(if: $i)
        }
        """
        data = self._exec(query, {"s": False, "i": True})
        self.assertEqual(data["fieldA"], "A-value")
        self.assertEqual(data["fieldB"], "B-value")

    # -- (b) literal @skip(if: true) / @include(if: false) ------------------ #
    def test_literal_skip_true_include_false_omit_both_fields(self) -> None:
        """Assert literal "@skip(if: true)"/"@include(if: false)" omit both fields.

        If this fails, a literal (non-variable) skipped or excluded
        field would be serialized as a null value instead of being
        omitted from the response data map entirely.
        """
        query = """
        {
          fieldA @skip(if: true)
          fieldB @include(if: false)
        }
        """
        data = self._exec(query)
        self.assertNotIn("fieldA", data)
        self.assertNotIn("fieldB", data)

    def test_literal_skip_false_include_true_keeps_both_fields(self) -> None:
        """Assert literal "@skip(if: false)"/"@include(if: true)" keep both fields present.

        If this fails, the literal (non-variable) directive path would
        incorrectly omit fields that should be included.
        """
        query = """
        {
          fieldA @skip(if: false)
          fieldB @include(if: true)
        }
        """
        data = self._exec(query)
        self.assertEqual(data["fieldA"], "A-value")
        self.assertEqual(data["fieldB"], "B-value")


# ============================================================================ #
# ITEM 2 (c): @deprecated END-TO-END through a compiled DjangoGraphQLSchema.     #
# A deprecated field (via a descriptor) is hidden/shown by introspection's       #
# includeDeprecated flag and carries the reason; the SDL contains @deprecated.   #
# ============================================================================ #
class DeprecatedFieldIntrospectionTest(TestCase):
    """@deprecated: introspection hides/shows the field and carries the reason.

    Covers the printed SDL, the default (hides) introspection behavior,
    and the includeDeprecated=true (shows) behavior.
    """

    @staticmethod
    def _schema():
        from django_graphex.schema import DjangoGraphQLSchema

        # Named "Query" so the compiled root type is literally "Query" and the
        # introspection '__type(name: "Query")' lookups below resolve.
        class Query(ObjectType):
            __test__ = False

            current = field(GraphQLString)
            legacy = field(GraphQLString, deprecation_reason="use current")

            def resolve_current(self, info):
                return "now"

            def resolve_legacy(self, info):
                return "old"

        return DjangoGraphQLSchema(query=Query)

    def test_sdl_contains_deprecated_directive(self) -> None:
        """Assert the printed SDL carries "@deprecated(reason: ...)" on the field.

        If this fails, a field's "deprecation_reason" would not surface
        as the standard GraphQL "@deprecated" directive in the printed
        schema.
        """
        from graphql import print_schema

        sdl = print_schema(self._schema().graphql_schema)
        assert '@deprecated(reason: "use current")' in sdl

    def test_introspection_hides_deprecated_field_by_default(self) -> None:
        """Assert "fields" (no includeDeprecated) omits the deprecated field.

        If this fails, introspection would leak deprecated fields into
        clients that did not opt into seeing them.
        """
        from graphql import graphql_sync

        query = """
        { __type(name: "Query") { fields { name } } }
        """
        result = graphql_sync(self._schema().graphql_schema, query)
        assert result.errors is None, result.errors
        names = {f["name"] for f in result.data["__type"]["fields"]}
        self.assertIn("current", names)
        self.assertNotIn("legacy", names)

    def test_introspection_shows_deprecated_field_with_reason(self) -> None:
        """Assert "fields(includeDeprecated: true)" surfaces it with reason and flag.

        If this fails, opting into "includeDeprecated" would not
        actually surface the deprecated field, or would surface it
        without its "isDeprecated"/"deprecationReason" metadata.
        """
        from graphql import graphql_sync

        query = """
        {
          __type(name: "Query") {
            fields(includeDeprecated: true) {
              name
              isDeprecated
              deprecationReason
            }
          }
        }
        """
        result = graphql_sync(self._schema().graphql_schema, query)
        assert result.errors is None, result.errors
        legacy = next(
            f for f in result.data["__type"]["fields"] if f["name"] == "legacy"
        )
        self.assertTrue(legacy["isDeprecated"])
        self.assertEqual(legacy["deprecationReason"], "use current")
