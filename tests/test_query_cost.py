# -*- coding: utf-8 -*-
"""Query cost analysis (`complexity` / MAX_QUERY_COST) via CostLimitValidationRule."""

from types import SimpleNamespace

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

from django_graphex import (
    CostLimitValidationRule,
    DjangoGraphQLSchema,
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
    ObjectType,
    analyze_cost,
    field,
)
from django_graphex import cost as cost_module
from django_graphex.registry import get_global_registry
from django_graphex.views import GraphQLView
from tests.models import Author, UUIDItem


def _build_schema(company_complexity=None):
    """companies(limit) -> properties(limit) -> owner -> name (all list args)."""
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


def _cost(schema, query, variables=None):
    return analyze_cost(schema, parse(query), variable_values=variables).total


class CostEngineTest(TestCase):
    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_literal_page_size_multiplier(self):
        schema = _build_schema()
        # companies = 1 + L*(properties); properties = 1 + P*(owner=1)
        # L=10, P=20 -> properties=21 -> companies = 1 + 10*21 = 211
        q = "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 211)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_scalars_cost_zero(self):
        schema = _build_schema()
        # only scalars under the list -> 1 + 10*0 = 1
        self.assertEqual(_cost(schema, "{ companies(limit: 10) { name } }"), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 5})
    def test_page_size_capped_at_max_page_size(self):
        schema = _build_schema()
        # limits 10/20 capped to 5/5 -> properties = 1 + 5*1 = 6; companies = 1 + 5*6 = 31
        q = "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 31)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_variable_page_size_resolved(self):
        schema = _build_schema()
        q = "query($n: Int){ companies(limit: $n) { properties(limit: 2) { owner { name } } } }"
        # properties = 1 + 2*1 = 3; companies = 1 + n*3
        self.assertEqual(_cost(schema, q, variables={"n": 4}), 13)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_variable_default_used_when_unbound(self):
        schema = _build_schema()
        # unbound variable -> its declared default (3) is used
        q2 = "query($n: Int = 3){ companies(limit: $n) { properties(limit: 2) { owner { name } } } }"
        # properties = 3 -> companies = 1 + 3*3 = 10
        self.assertEqual(_cost(schema, q2), 10)

    @override_settings(
        DJANGO_GRAPHEX={"MAX_PAGE_SIZE": None, "DEFAULT_LIST_MULTIPLIER": 10}
    )
    def test_default_multiplier_when_unbounded(self):
        schema = _build_schema()
        cost_module._unbounded_warned = True  # silence the one-shot warning here
        # no limit args, no cap -> mult 10 each
        # properties = 1 + 10*1 = 11; companies = 1 + 10*11 = 111
        q = "{ companies { properties { owner { name } } } }"
        self.assertEqual(_cost(schema, q), 111)

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "MAX_PAGE_SIZE": None})
    def test_unbounded_list_warns_once(self):
        schema = _build_schema()
        cost_module._unbounded_warned = False
        with pytest.warns(RuntimeWarning, match="MAX_PAGE_SIZE is None"):
            _cost(schema, "{ companies { properties { owner { name } } } }")

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_type_complexity_overrides_default_weight(self):
        schema = _build_schema(company_complexity=5)
        # own(company)=5 -> companies = 5 + 10*0 = 5
        self.assertEqual(_cost(schema, "{ companies(limit: 10) { name } }"), 5)

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_fragment_does_not_bypass(self):
        schema = _build_schema()
        plain = "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }"
        fragged = (
            "{ companies(limit: 10) { ...C } } "
            "fragment C on Company { properties(limit: 20) { owner { name } } }"
        )
        self.assertEqual(_cost(schema, fragged), _cost(schema, plain))


class CostRuleTest(TestCase):
    def _errors(self, schema, query):
        return [
            e.message for e in validate(schema, parse(query), [CostLimitValidationRule])
        ]

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 100, "MAX_PAGE_SIZE": 1000})
    def test_rejects_over_budget(self):
        schema = _build_schema()  # cost 211 > 100
        errors = self._errors(
            schema,
            "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }",
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("exceeds the maximum of 100", errors[0])

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1000, "MAX_PAGE_SIZE": 1000})
    def test_allows_within_budget(self):
        schema = _build_schema()  # cost 211 < 1000
        self.assertEqual(
            self._errors(
                schema,
                "{ companies(limit: 10) { properties(limit: 20) { owner { name } } } }",
            ),
            [],
        )

    @override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
    def test_no_budget_is_noop(self):
        schema = _build_schema()  # MAX_QUERY_COST unset
        self.assertEqual(
            self._errors(
                schema,
                "{ companies(limit: 999) { properties(limit: 999) { owner { name } } } }",
            ),
            [],
        )


class ComplexityWiringTest(TestCase):
    def test_object_type_stores_complexity(self):
        class _AuthorType(DjangoObjectType):
            class Meta:
                model = Author
                complexity = 7

        self.assertEqual(_AuthorType._meta.complexity, 7)

    def test_list_type_stores_complexity(self):
        class _AuthorList(DjangoListObjectType):
            class Meta:
                model = Author
                complexity = 8

        self.assertEqual(_AuthorList._meta.complexity, 8)

    def test_serializer_type_forwards_complexity_to_output_type(self):
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
    def test_view_includes_cost_rule(self):
        self.assertIn(CostLimitValidationRule, GraphQLView.validation_rules)

    @override_settings(
        DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000, "SCHEMA": "tests.schema.schema"}
    )
    def test_get_query_cost_returns_payload(self):
        class _Owner(ObjectType):
            name = field(GraphQLString)

        class _Query(ObjectType):
            owner = field(_Owner)

        view = GraphQLView()
        view.schema = DjangoGraphQLSchema(query=_Query)
        cost = view.get_query_cost("{ owner { name } }", {}, None)
        self.assertEqual(cost, {"requestedCost": 1, "maxCost": None})
