# -*- coding: utf-8 -*-
"""Remaining branch coverage for ``cost.py`` (the ``_CostAnalyzer`` multiplier
and fragment paths) and ``CostLimitValidationRule``.
"""

from django.test import override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)

from django_graphex.cost import CostLimitValidationRule, analyze_cost


def _schema():
    item = GraphQLObjectType("Item", {"name": GraphQLField(GraphQLString)})
    query = GraphQLObjectType(
        "Query",
        {
            # A list field with both a pagination arg (`limit`) and a
            # non-pagination arg (`q`) -> exercises the arg-skip branch.
            "items": GraphQLField(
                GraphQLList(item),
                args={
                    "limit": GraphQLArgument(GraphQLInt),
                    "q": GraphQLArgument(GraphQLString),
                },
            ),
            # A NonNull(List(...)) field -> the of_type unwrap loop hits a list.
            "nnItems": GraphQLField(GraphQLNonNull(GraphQLList(item))),
            "scalar": GraphQLField(GraphQLString),
        },
    )
    return GraphQLSchema(query=query, types=[item])


def _sub_schema():
    item = GraphQLObjectType("Item", {"name": GraphQLField(GraphQLString)})
    query = GraphQLObjectType("Query", {"scalar": GraphQLField(GraphQLString)})
    # A schema with a query type but no subscription type.
    return GraphQLSchema(query=query, types=[item])


# --------------------------------------------------------------------------- #
# operation root type missing                                                   #
# --------------------------------------------------------------------------- #
def test_subscription_without_subscription_type_costs_zero():
    # No subscription type -> root_type is None -> operation_cost returns 0
    # (line 114).
    doc = parse("subscription { scalar }")
    assert analyze_cost(_sub_schema(), doc).total == 0


# --------------------------------------------------------------------------- #
# inline fragment WITH a resolvable type condition                              #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_inline_fragment_with_type_condition_is_costed():
    # `... on Item { name }` resolves the Item type and costs its leaves (151).
    doc = parse("{ items(limit: 2) { ... on Item { name } } }")
    assert analyze_cost(_schema(), doc).total == 1  # list own cost; leaf is free


# --------------------------------------------------------------------------- #
# cyclic + non-pagination arg                                                   #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_non_pagination_argument_is_ignored_for_multiplier():
    # `q` is present but isn't a pagination arg, so the multiplier still comes
    # from `limit` (line 206-207 skip).
    with_q = analyze_cost(
        _schema(), parse('{ items(limit: 3, q: "x") { name } }')
    ).total
    without_q = analyze_cost(_schema(), parse("{ items(limit: 3) { name } }")).total
    assert with_q == without_q


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_cyclic_fragment_spread_costed_once():
    # F spreads itself; the second encounter is short-circuited (line 161-162).
    doc = parse("{ items(limit: 2) { ...F } } fragment F on Item { name ...F }")
    # name is free; the self-spread is guarded -> just the list own cost.
    assert analyze_cost(_schema(), doc).total == 1


# --------------------------------------------------------------------------- #
# DEFAULT_PAGE_SIZE multiplier (MAX_PAGE_SIZE unset)                             #
# --------------------------------------------------------------------------- #
@override_settings(
    DJANGO_GRAPHEX={"MAX_PAGE_SIZE": None, "DEFAULT_PAGE_SIZE": 7}
)
def test_list_without_page_size_uses_default_page_size():
    # No page-size arg, MAX_PAGE_SIZE unset -> DEFAULT_PAGE_SIZE multiplier (199).
    item = GraphQLObjectType(
        "It",
        {
            "child": GraphQLField(
                GraphQLObjectType("C", {"x": GraphQLField(GraphQLString)})
            )
        },
    )
    query = GraphQLObjectType("Query", {"items": GraphQLField(GraphQLList(item))})
    schema = GraphQLSchema(query=query)
    doc = parse("{ items { child { x } } }")
    # own(items)=1 + DEFAULT_PAGE_SIZE(7) * own(child)=1 -> 1 + 7*1 = 8.
    assert analyze_cost(schema, doc).total == 8


# --------------------------------------------------------------------------- #
# NonNull(List(...)) detection                                                  #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 5})
def test_nonnull_list_field_is_treated_as_list():
    # nnItems: NonNull(List(Item)) -> the of_type loop reaches the list (228-230).
    doc = parse("{ nnItems { name } }")
    # own(nnItems)=1, children cost 0 (scalar). Multiplier doesn't change the
    # total when children are free, but is_list_field must run without error.
    assert analyze_cost(_schema(), doc).total == 1


# --------------------------------------------------------------------------- #
# variable page-size with a non-IntValue default                                #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_variable_page_size_non_int_default_falls_through():
    # The variable has a String default (not IntValue) and is unbound -> the
    # page size resolves to None (line 218-221 fall-through).
    doc = parse('query($n: String = "big") { items(limit: $n) { name } }')
    # `limit` value is a variable with no usable int -> falls back to is_list +
    # MAX_PAGE_SIZE cap; children are free so total is the list own cost.
    assert analyze_cost(_schema(), doc).total == 1


# --------------------------------------------------------------------------- #
# CostLimitValidationRule enforcement                                           #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "MAX_PAGE_SIZE": 1000})
def test_cost_rule_rejects_over_budget_query():
    # A list of objects-with-children over the tiny budget is rejected.
    inner = GraphQLObjectType("Inner", {"x": GraphQLField(GraphQLString)})
    item = GraphQLObjectType("Item", {"inner": GraphQLField(inner)})
    query = GraphQLObjectType(
        "Query",
        {
            "items": GraphQLField(
                GraphQLList(item), args={"limit": GraphQLArgument(GraphQLInt)}
            )
        },
    )
    schema = GraphQLSchema(query=query, types=[item, inner])
    errors = validate(
        schema,
        parse("{ items(limit: 50) { inner { x } } }"),
        [CostLimitValidationRule],
    )
    assert any("exceeds the maximum" in e.message for e in errors)


def test_cost_rule_noop_without_budget():
    # No MAX_QUERY_COST -> the rule does nothing.
    schema = _schema()
    errors = validate(
        schema, parse("{ items(limit: 99) { name } }"), [CostLimitValidationRule]
    )
    assert errors == []
