# -*- coding: utf-8 -*-
"""Query cost analysis ("complexity" / MAX_QUERY_COST) via CostLimitValidationRule."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.test import TestCase, override_settings
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

from django_graphex import cost as cost_module
from django_graphex.core import ObjectType, field
from django_graphex.cost import CostLimitValidationRule, analyze_cost
from django_graphex.registry import get_global_registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoModelType, DjangoObjectType
from django_graphex.views import GraphQLView
from tests.models import Author, UUIDItem


def _build_schema(company_complexity: int | None = None) -> GraphQLSchema:
    """Build a companies -> properties -> owner -> name schema, all list args.

    Args:
        company_complexity: When given, stamped as the "Company" type's
            declared complexity via a "graphene_type" stand-in.

    Returns:
        schema: The assembled graphql-core schema.
    """
    owner = GraphQLObjectType("Owner", {"name": GraphQLField(GraphQLString)})
    prop = GraphQLObjectType(
        "Property",
        {"owner": GraphQLField(owner)},
    )
    company = GraphQLObjectType(
        "Company",
        {
            "name": GraphQLField(GraphQLString),
            "properties": GraphQLField(
                GraphQLList(prop), args={"limit": GraphQLArgument(GraphQLInt)}
            ),
        },
    )
    if company_complexity is not None:
        company.graphene_type = SimpleNamespace(
            _meta=SimpleNamespace(complexity=company_complexity)
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


def _cost(
    schema: GraphQLSchema, query: str, variables: dict[str, Any] | None = None
) -> int:
    """Compute the total estimated cost of a query against a schema.

    Args:
        schema: The graphql-core schema to cost the query against.
        query: The GraphQL query document text.
        variables: Bound variable values used to resolve variabled limits.

    Returns:
        total: The total estimated query cost.
    """
    return analyze_cost(schema, parse(query), variable_values=variables).total


class CostEngineTest(TestCase):
    """Tests for the cost-estimation engine's arithmetic and edge cases.

    Covers literal and variable page-size limits, scalar-only selections,
    fragments, and the unbounded-list warning/fallback.
    """

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_literal_page_size_multiplier(self) -> None:
        """Assert a literal page-size limit multiplies nested field cost correctly.

        If this fails, the cost estimator would miscompute the multiplier
        contributed by nested list fields with literal limit arguments.
        """
        schema = _build_schema()
        # companies = 1 + L*(properties); properties = 1 + P*(owner=1)
        # L=10, P=20 -> properties=21 -> companies = 1 + 10*21 = 211
        q = "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 211)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_scalars_cost_zero(self) -> None:
        """Assert selecting only scalar fields under a list contributes zero cost.

        If this fails, plain scalar selections would be over-counted,
        inflating the cost of scalar-only queries.
        """
        schema = _build_schema()
        # only scalars under the list -> 1 + 10*0 = 1
        self.assertEqual(_cost(schema, "{ companies(limit: 10) { name } }"), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 5})
    def test_page_size_capped_at_max_page_size(self) -> None:
        """Assert a limit above MAX_PAGE_SIZE is capped before costing.

        If this fails, a caller could request an oversized limit and have
        the cost estimator under-report the true resolved query cost.
        """
        schema = _build_schema()
        # limits 10/20 capped to 5/5 -> properties = 1 + 5*1 = 6; companies = 1 + 5*6 = 31
        q = "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 31)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_variable_page_size_resolved(self) -> None:
        """Assert a variable-bound limit argument resolves to its bound value.

        If this fails, cost estimation would ignore bound variable values
        and either fail or use an incorrect fallback for the multiplier.
        """
        schema = _build_schema()
        q = "query($n: Int){ companies(limit: $n) { properties(limit: 2) { owner { name } } } }"
        # properties = 1 + 2*1 = 3; companies = 1 + n*3
        self.assertEqual(_cost(schema, q, variables={"n": 4}), 13)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_variable_default_used_when_unbound(self) -> None:
        """Assert an unbound variable falls back to its declared default value.

        If this fails, an operation-declared variable default would be
        ignored when the variable is not supplied at execution time.
        """
        schema = _build_schema()
        # unbound variable -> its declared default (3) is used
        q2 = "query($n: Int = 3){ companies(limit: $n) { properties(limit: 2) { owner { name } } } }"
        # properties = 3 -> companies = 1 + 3*3 = 10
        self.assertEqual(_cost(schema, q2), 10)

    @override_settings(
        DJANGO_GRAPHEX={"MAX_PAGE_SIZE": None, "DEFAULT_LIST_MULTIPLIER": 10}
    )
    def test_default_multiplier_when_unbounded(self) -> None:
        """Assert an unbounded list field falls back to DEFAULT_LIST_MULTIPLIER.

        If this fails, list fields with no limit argument and no
        MAX_PAGE_SIZE cap would either raise or use the wrong fallback
        multiplier.
        """
        schema = _build_schema()
        cost_module._unbounded_warned = True  # silence the one-shot warning here
        # no limit args, no cap -> mult 10 each
        # properties = 1 + 10*1 = 11; companies = 1 + 10*11 = 111
        q = "{ companies { properties { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 111)

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "MAX_PAGE_SIZE": None})
    def test_unbounded_list_warns_once(self) -> None:
        """Assert an unbounded list field emits a one-shot "RuntimeWarning".

        If this fails, operators would get no signal that MAX_PAGE_SIZE is
        unset while list fields are being cost-estimated with a fallback
        multiplier.

        Raises:
            RuntimeWarning: Expected from the cost estimator and asserted
                via "pytest.warns".
        """
        schema = _build_schema()
        cost_module._unbounded_warned = False
        with pytest.warns(RuntimeWarning, match="MAX_PAGE_SIZE is None"):
            _cost(schema, "{ companies { properties { owner { name } } } }")

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_negative_page_size_clamped_to_zero(self) -> None:
        """Assert a negative page size never produces a negative multiplier.

        If this fails, a negative limit would multiply a subtree by a
        negative number, letting the query subtract cost from the total.
        """
        schema = _build_schema()
        q = "{ companies(limit: -1000) { properties(limit: 1) { owner { name } } } }"
        # own(companies)=1 + 0 * properties -> 1, never negative.
        self.assertEqual(_cost(schema, q), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_type_complexity_overrides_default_weight(self) -> None:
        """Assert a type's declared complexity overrides the default field weight.

        If this fails, a type author's explicit "complexity" Meta option
        would be ignored in favor of the default per-field weight.
        """
        schema = _build_schema(company_complexity=5)
        # own(company)=5 -> companies = 5 + 10*0 = 5
        self.assertEqual(_cost(schema, "{ companies(limit: 10) { name } }"), 5)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_fragment_does_not_bypass(self) -> None:
        """Assert selecting fields through a fragment costs the same as inline.

        If this fails, a query could dodge cost estimation by moving its
        expensive selections into a named fragment.
        """
        schema = _build_schema()
        plain = "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }"
        fragged = (
            "{ companies(limit: 10) { ...C } } "
            "fragment C on Company { properties(limit: 20) { owner { name } } }"
        )
        self.assertEqual(_cost(schema, fragged), _cost(schema, plain))


class CostRuleTest(TestCase):
    """Tests for "CostLimitValidationRule" enforcing MAX_QUERY_COST.

    Covers rejection over budget, acceptance within budget, and the
    no-op behavior when no budget is configured.
    """

    def _errors(self, schema: GraphQLSchema, query: str) -> list[str]:
        """Run the cost validation rule and collect its error messages.

        Args:
            schema: The graphql-core schema to validate against.
            query: The GraphQL query document text.

        Returns:
            messages: The validation error messages produced by
                "CostLimitValidationRule" (empty when the query is within
                budget or no budget is configured).
        """
        return [
            e.message for e in validate(schema, parse(query), [CostLimitValidationRule])
        ]

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 100, "MAX_PAGE_SIZE": 1000})
    def test_rejects_over_budget(self) -> None:
        """Assert a query whose cost exceeds MAX_QUERY_COST is rejected.

        If this fails, queries over the configured cost budget would be
        allowed to execute instead of being rejected at validation time.
        """
        schema = _build_schema()  # cost 211 > 100
        errors = self._errors(
            schema,
            "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("exceeds the maximum of 100", errors[0])

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1000, "MAX_PAGE_SIZE": 1000})
    def test_allows_within_budget(self) -> None:
        """Assert a query whose cost is within MAX_QUERY_COST passes validation.

        If this fails, legitimate queries under the configured cost budget
        would be wrongly rejected.
        """
        schema = _build_schema()  # cost 211 < 1000
        self.assertEqual(
            self._errors(
                schema,
                "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }",
            ),
            [],
        )

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 50, "MAX_PAGE_SIZE": 1000})
    def test_negative_limit_cannot_cancel_a_sibling_field(self) -> None:
        """Assert a negative limit cannot buy budget for an expensive sibling.

        If this fails, an aliased field with a negative page size would
        subtract cost from the operation total and let an over-budget
        sibling through the DoS gate.
        """
        schema = _build_schema()
        errors = self._errors(
            schema,
            "{ a: companies(limit: -1000) { properties(limit: 1) { owner { name } } } "
            "  b: companies(limit: 1000) { properties(limit: 1) { owner { name } } } }",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("exceeds the maximum of 50", errors[0])

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 50, "MAX_PAGE_SIZE": 1000})
    def test_variable_default_is_not_trusted_for_enforcement(self) -> None:
        """Assert a document-declared variable default cannot lower the estimate.

        If this fails, a client could declare a small default for a page-size
        variable, pass a large value at execution time, and bypass
        MAX_QUERY_COST entirely.
        """
        schema = _build_schema()
        errors = self._errors(
            schema,
            "query Q($n: Int = 1) { companies(limit: $n) "
            "{ properties(limit: 1) { owner { name } } } }",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("exceeds the maximum of 50", errors[0])

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_no_budget_is_noop(self) -> None:
        """Assert leaving MAX_QUERY_COST unset makes the validation rule a no-op.

        If this fails, cost validation would reject queries even when no
        cost budget has been configured for the project.
        """
        schema = _build_schema()  # MAX_QUERY_COST unset
        self.assertEqual(
            self._errors(
                schema,
                "{ companies(limit: 999) { properties(limit: 999) { owner { name } } } }",
            ),
            [],
        )


class ComplexityWiringTest(TestCase):
    """Tests for the "complexity" Meta option propagating across type kinds.

    Covers object types, list types, and the serializer-to-output-type
    forwarding path.
    """

    def test_object_type_stores_complexity(self) -> None:
        """Assert a "DjangoObjectType" stores its declared "complexity" Meta option.

        If this fails, an object type's explicit complexity weight would
        not be readable off "_meta.complexity".
        """

        class _ComplexityAuthorType(DjangoObjectType):
            class Meta:
                model = Author
                complexity = 7

        self.assertEqual(_ComplexityAuthorType._meta.complexity, 7)

    def test_list_type_stores_complexity(self) -> None:
        """Assert a "DjangoListObjectType" stores its declared "complexity" option.

        If this fails, a list type's explicit complexity weight would not
        be readable off "_meta.complexity".
        """

        class _AuthorList(DjangoListObjectType):
            class Meta:
                model = Author
                complexity = 8

        self.assertEqual(_AuthorList._meta.complexity, 8)

    def test_serializer_type_forwards_complexity_to_output_type(self) -> None:
        """Assert a serializer type's complexity propagates to its output type.

        If this fails, a "DjangoModelType"'s declared complexity would not
        reach the compiled output type actually used for cost estimation.
        """
        reg = get_global_registry()
        reg._types.pop((UUIDItem, None), None)
        reg._list_types.pop(UUIDItem, None)

        class _ItemType(DjangoModelType):
            class Meta:
                model = UUIDItem
                complexity = 9

        self.assertEqual(_ItemType._meta.complexity, 9)
        self.assertEqual(_ItemType._meta.output_type._meta.complexity, 9)


class CostViewWiringTest(TestCase):
    """Tests for "GraphQLView" wiring up cost validation and reporting.

    Covers both the validation-rule registration and the
    "get_query_cost" reporting helper.
    """

    def test_view_includes_cost_rule(self) -> None:
        """Assert "GraphQLView.validation_rules" includes the cost validation rule.

        If this fails, requests served through the default view would
        never have their cost enforced against MAX_QUERY_COST.
        """
        self.assertIn(CostLimitValidationRule, GraphQLView.validation_rules)

    @override_settings(
        DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000, "SCHEMA": "tests.schema.schema"}
    )
    def test_get_query_cost_returns_payload(self) -> None:
        """Assert "get_query_cost" returns a requestedCost/maxCost payload.

        If this fails, the view's public cost-reporting helper would
        return the wrong shape or values for a simple, low-cost query.
        """

        class _Owner(ObjectType):
            name = field(GraphQLString)

        class _Query(ObjectType):
            owner = field(_Owner)

        view = GraphQLView()
        view.schema = DjangoGraphQLSchema(query=_Query)
        cost = view.get_query_cost("{ owner { name } }", {}, None)
        self.assertEqual(cost, {"requestedCost": 1, "maxCost": None})
