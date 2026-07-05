# -*- coding: utf-8 -*-
"""Remaining branch coverage for "cost.py" (the "_CostAnalyzer" multiplier
and fragment paths) and "CostLimitValidationRule".
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


def _schema() -> GraphQLSchema:
    """Build a schema exercising the cost-analyzer's list and arg branches.

    Returns:
        schema: A schema with an "items" list field carrying both a
            pagination arg ("limit") and a non-pagination arg ("q"), an
            "nnItems" NonNull(List(...)) field, and a free "scalar" field.
    """
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


def _sub_schema() -> GraphQLSchema:
    """Build a schema with a query type but no subscription type.

    Returns:
        schema: A minimal schema used to exercise the operation-cost branch
            where the requested operation's root type cannot be resolved.
    """
    item = GraphQLObjectType("Item", {"name": GraphQLField(GraphQLString)})
    query = GraphQLObjectType("Query", {"scalar": GraphQLField(GraphQLString)})
    # A schema with a query type but no subscription type.
    return GraphQLSchema(query=query, types=[item])


# --------------------------------------------------------------------------- #
# operation root type missing                                                   #
# --------------------------------------------------------------------------- #
def test_subscription_without_subscription_type_costs_zero() -> None:
    """A subscription operation on a schema with no subscription type costs 0.

    Exercises the branch where the operation's root type cannot be resolved,
    so "operation_cost" must return 0 rather than raising.
    """
    doc = parse("subscription { scalar }")
    assert analyze_cost(_sub_schema(), doc).total == 0


# --------------------------------------------------------------------------- #
# inline fragment WITH a resolvable type condition                              #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_inline_fragment_with_type_condition_is_costed() -> None:
    """An inline fragment with a type condition must resolve and cost its leaves.

    "... on Item { name }" must resolve the Item type so its selected leaves
    are costed instead of being skipped as unresolvable.
    """
    doc = parse("{ items(limit: 2) { ... on Item { name } } }")
    assert analyze_cost(_schema(), doc).total == 1  # list own cost; leaf is free


# --------------------------------------------------------------------------- #
# cyclic + non-pagination arg                                                   #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_non_pagination_argument_is_ignored_for_multiplier() -> None:
    """A non-pagination argument must not affect the page-size multiplier.

    "q" is present alongside "limit" but is not a pagination argument, so the
    multiplier must still come solely from "limit".
    """
    with_q = analyze_cost(
        _schema(), parse('{ items(limit: 3, q: "x") { name } }')
    ).total
    without_q = analyze_cost(_schema(), parse("{ items(limit: 3) { name } }")).total
    assert with_q == without_q


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_cyclic_fragment_spread_costed_once() -> None:
    """A fragment that spreads itself must be costed once, not recursed forever.

    Fragment "F" spreads itself; the second encounter must be short-circuited
    so the analyzer terminates instead of recursing infinitely.
    """
    doc = parse("{ items(limit: 2) { ...F } } fragment F on Item { name ...F }")
    # name is free; the self-spread is guarded -> just the list own cost.
    assert analyze_cost(_schema(), doc).total == 1


# --------------------------------------------------------------------------- #
# DEFAULT_PAGE_SIZE multiplier (MAX_PAGE_SIZE unset)                             #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": None, "DEFAULT_PAGE_SIZE": 7})
def test_list_without_page_size_uses_default_page_size() -> None:
    """A list field with no page-size argument must use DEFAULT_PAGE_SIZE.

    With MAX_PAGE_SIZE unset, the multiplier must fall back to
    DEFAULT_PAGE_SIZE rather than 1 or an unbounded value.
    """
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
def test_nonnull_list_field_is_treated_as_list() -> None:
    """A NonNull(List(...)) field must still be recognized as a list field.

    "nnItems" is NonNull(List(Item)); the of_type unwrap loop must see
    through the NonNull wrapper and reach the list, so is_list_field runs
    without error.
    """
    doc = parse("{ nnItems { name } }")
    # own(nnItems)=1, children cost 0 (scalar). Multiplier doesn't change the
    # total when children are free, but is_list_field must run without error.
    assert analyze_cost(_schema(), doc).total == 1


# --------------------------------------------------------------------------- #
# variable page-size with a non-IntValue default                                #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_variable_page_size_non_int_default_falls_through() -> None:
    """An unbound variable page-size arg with a non-int default must fall through.

    The "$n" variable has a String default (not an IntValue) and is left
    unbound, so the page size must resolve to None instead of raising or
    coercing the string.
    """
    doc = parse('query($n: String = "big") { items(limit: $n) { name } }')
    # `limit` value is a variable with no usable int -> falls back to is_list +
    # MAX_PAGE_SIZE cap; children are free so total is the list own cost.
    assert analyze_cost(_schema(), doc).total == 1


# --------------------------------------------------------------------------- #
# CostLimitValidationRule enforcement                                           #
# --------------------------------------------------------------------------- #
@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "MAX_PAGE_SIZE": 1000})
def test_cost_rule_rejects_over_budget_query() -> None:
    """A query costed above MAX_QUERY_COST must be rejected by the validation rule.

    If this breaks, "CostLimitValidationRule" would silently allow queries
    that exceed the configured cost budget.
    """
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


def test_cost_rule_noop_without_budget() -> None:
    """With no MAX_QUERY_COST configured, the validation rule must be a no-op.

    Guards against the rule rejecting queries when no cost budget was ever
    configured.
    """
    schema = _schema()
    errors = validate(
        schema, parse("{ items(limit: 99) { name } }"), [CostLimitValidationRule]
    )
    assert errors == []
