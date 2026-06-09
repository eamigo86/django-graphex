# -*- coding: utf-8 -*-
"""Edge branches of ``cost.py`` and ``validation.py`` not hit by the main suites.

Covers: invalid ``complexity`` / ``max_deep`` coercion, the no-operation /
non-query root cases, inline-fragment (no type condition) and missing-fragment
guards, the multi-operation ``operation_name`` selection, and the variable
page-size error paths.
"""

from types import SimpleNamespace

from django.test import override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
)

from django_graphex.cost import (
    CostReport,
    _type_complexity,
    analyze_cost,
)
from django_graphex.validation import _type_max_deep


# --------------------------------------------------------------------------- #
# Shared schema: one list field with a `limit` page-size arg.                  #
# --------------------------------------------------------------------------- #
def _schema(complexity=None):
    item = GraphQLObjectType("Item", {"name": GraphQLField(GraphQLString)})
    if complexity is not None:
        item.graphene_type = SimpleNamespace(
            _meta=SimpleNamespace(complexity=complexity)
        )
    query = GraphQLObjectType(
        "Query",
        {
            "items": GraphQLField(
                GraphQLList(item), args={"limit": GraphQLArgument(GraphQLInt)}
            ),
            "scalar": GraphQLField(GraphQLString),
        },
    )
    return GraphQLSchema(query=query, types=[item])


# --------------------------------------------------------------------------- #
# _type_complexity / _type_max_deep coercion guards                            #
# --------------------------------------------------------------------------- #
def test_type_complexity_invalid_value_is_none():
    bad = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(complexity="x"))
    )
    assert _type_complexity(bad) is None


def test_type_complexity_negative_is_none():
    neg = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(complexity=-3))
    )
    assert _type_complexity(neg) is None


def test_type_complexity_absent_is_none():
    assert _type_complexity(SimpleNamespace()) is None


def test_type_max_deep_invalid_value_is_none():
    bad = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(max_deep="nope"))
    )
    assert _type_max_deep(bad) is None


def test_type_max_deep_negative_is_none():
    neg = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(max_deep=-1))
    )
    assert _type_max_deep(neg) is None


# --------------------------------------------------------------------------- #
# analyze_cost: no operation / unknown field / introspection                   #
# --------------------------------------------------------------------------- #
def test_analyze_cost_no_operation_returns_zero():
    # A document with only a fragment (no operation) costs 0.
    doc = parse("fragment F on Item { name }")
    report = analyze_cost(_schema(), doc)
    assert isinstance(report, CostReport)
    assert report.total == 0


def test_analyze_cost_operation_name_selects_named_operation():
    doc = parse("query A { scalar } query B { items(limit: 3) { name } }")
    a = analyze_cost(_schema(), doc, operation_name="A").total
    b = analyze_cost(_schema(), doc, operation_name="B").total
    assert a == 0  # only a scalar
    assert b >= 1  # a list field with children


def test_analyze_cost_unknown_operation_name_returns_zero():
    doc = parse("query A { scalar }")
    assert analyze_cost(_schema(), doc, operation_name="Missing").total == 0


def test_analyze_cost_introspection_field_is_free():
    doc = parse("{ __typename }")
    assert analyze_cost(_schema(), doc).total == 0


def test_analyze_cost_unknown_field_skipped():
    # A field that is not on the type is ignored (no crash, no cost).
    doc = parse("{ notARealField }")
    assert analyze_cost(_schema(), doc).total == 0


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_inline_fragment_without_type_condition():
    # `... { name }` (no `on Type`) keeps the parent type, adds no nesting.
    doc = parse("{ items(limit: 2) { ... { name } } }")
    # name is a scalar leaf (cost 0) so total is just the list's own cost (1).
    assert analyze_cost(_schema(), doc).total == 1


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_missing_fragment_is_skipped():
    # A spread referencing an undefined fragment is ignored.
    doc = parse("{ items(limit: 2) { ...Ghost } }")
    assert analyze_cost(_schema(), doc).total == 1


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_variable_non_integer_value_falls_through():
    # A bound variable that can't be int()-ed -> page size treated as unset.
    doc = parse("query($n: Int) { items(limit: $n) { name } }")
    total = analyze_cost(_schema(), doc, variable_values={"n": "not-an-int"}).total
    # falls back to MAX_PAGE_SIZE multiplier but children are scalar (0) -> own=1
    assert total == 1


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_complexity_applied():
    doc = parse("{ items(limit: 2) { name } }")
    base = analyze_cost(_schema(), doc).total
    weighted = analyze_cost(_schema(complexity=9), doc).total
    assert weighted == 9  # the declared own cost replaces the default 1
    assert base == 1
