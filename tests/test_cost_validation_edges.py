# -*- coding: utf-8 -*-
"""Edge branches of "cost.py" and "validation.py" not hit by the main suites.

Covers: invalid "complexity" / "max_depth" coercion, the no-operation /
non-query root cases, inline-fragment (no type condition) and missing-fragment
guards, the multi-operation "operation_name" selection, and the variable
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
from django_graphex.validation import _type_max_depth


# --------------------------------------------------------------------------- #
# Shared schema: one list field with a `limit` page-size arg.                  #
# --------------------------------------------------------------------------- #
def _schema(complexity: int | None = None) -> GraphQLSchema:
    """Build a minimal schema with one "items" list field and a scalar field.

    Args:
        complexity: When given, attaches a "graphene_type._meta.complexity"
            marker to the "Item" type so cost analysis picks up an explicit
            per-node cost instead of the default.

    Returns:
        schema: The constructed GraphQLSchema with "items(limit: Int)" and
            "scalar" query fields.
    """
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
# _type_complexity / _type_max_depth coercion guards                            #
# --------------------------------------------------------------------------- #
def test_type_complexity_invalid_value_is_none() -> None:
    """A non-numeric "complexity" marker must coerce to None, not raise.

    If this breaks, a badly configured "complexity" meta value could crash
    cost analysis instead of being safely ignored.
    """
    bad = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(complexity="x"))
    )
    assert _type_complexity(bad) is None


def test_type_complexity_negative_is_none() -> None:
    """A negative "complexity" marker must coerce to None, not be honored.

    If this breaks, a negative complexity value could reduce or invert the
    computed query cost instead of being rejected as invalid.
    """
    neg = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(complexity=-3))
    )
    assert _type_complexity(neg) is None


def test_type_complexity_absent_is_none() -> None:
    """A type with no "graphene_type"/"_meta" at all must yield None.

    If this breaks, cost analysis would crash on types that never declared a
    complexity marker.
    """
    assert _type_complexity(SimpleNamespace()) is None


def test_type_max_depth_invalid_value_is_none() -> None:
    """A non-numeric "max_depth" marker must coerce to None, not raise.

    If this breaks, a badly configured "max_depth" meta value could crash
    depth validation instead of being safely ignored.
    """
    bad = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(max_depth="nope"))
    )
    assert _type_max_depth(bad) is None


def test_type_max_depth_negative_is_none() -> None:
    """A negative "max_depth" marker must coerce to None, not be honored.

    If this breaks, a negative depth limit could be applied instead of being
    rejected as invalid configuration.
    """
    neg = SimpleNamespace(
        graphene_type=SimpleNamespace(_meta=SimpleNamespace(max_depth=-1))
    )
    assert _type_max_depth(neg) is None


# --------------------------------------------------------------------------- #
# analyze_cost: no operation / unknown field / introspection                   #
# --------------------------------------------------------------------------- #
def test_analyze_cost_no_operation_returns_zero() -> None:
    """A document with only a fragment (no operation) must cost 0.

    If this breaks, "analyze_cost" could crash or mis-total a document that
    has no operation to walk.
    """
    # A document with only a fragment (no operation) costs 0.
    doc = parse("fragment F on Item { name }")
    report = analyze_cost(_schema(), doc)
    assert isinstance(report, CostReport)
    assert report.total == 0


def test_analyze_cost_operation_name_selects_named_operation() -> None:
    """ "operation_name" must select the matching operation out of a multi-operation document.

    If this breaks, a request naming one operation could be costed against a
    different operation in the same document.
    """
    doc = parse("query A { scalar } query B { items(limit: 3) { name } }")
    a = analyze_cost(_schema(), doc, operation_name="A").total
    b = analyze_cost(_schema(), doc, operation_name="B").total
    assert a == 0  # only a scalar
    assert b >= 1  # a list field with children


def test_analyze_cost_unknown_operation_name_returns_zero() -> None:
    """An "operation_name" that matches no operation in the document must cost 0.

    If this breaks, a typo in the requested operation name could crash cost
    analysis instead of yielding a safe zero total.
    """
    doc = parse("query A { scalar }")
    assert analyze_cost(_schema(), doc, operation_name="Missing").total == 0


def test_analyze_cost_introspection_field_is_free() -> None:
    """The "__typename" introspection field must contribute zero cost.

    If this breaks, introspection queries could be rejected by cost limits
    meant only for real data-fetching fields.
    """
    doc = parse("{ __typename }")
    assert analyze_cost(_schema(), doc).total == 0


def test_analyze_cost_unknown_field_skipped() -> None:
    """A field absent from the schema type must be skipped without cost or crash.

    If this breaks, a malformed query could crash cost analysis instead of
    being safely ignored (validation handles rejecting it elsewhere).
    """
    # A field that is not on the type is ignored (no crash, no cost).
    doc = parse("{ notARealField }")
    assert analyze_cost(_schema(), doc).total == 0


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_inline_fragment_without_type_condition() -> None:
    """An inline fragment without a type condition must keep the parent type and add no nesting.

    If this breaks, an untyped inline fragment could be skipped entirely or
    double-count its parent field's cost.
    """
    # `... { name }` (no `on Type`) keeps the parent type, adds no nesting.
    doc = parse("{ items(limit: 2) { ... { name } } }")
    # name is a scalar leaf (cost 0) so total is just the list's own cost (1).
    assert analyze_cost(_schema(), doc).total == 1


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_missing_fragment_is_skipped() -> None:
    """A fragment spread referencing an undefined fragment must be skipped without crashing.

    If this breaks, a query referencing a missing fragment could crash cost
    analysis instead of ignoring the dangling spread.
    """
    # A spread referencing an undefined fragment is ignored.
    doc = parse("{ items(limit: 2) { ...Ghost } }")
    assert analyze_cost(_schema(), doc).total == 1


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_variable_non_integer_value_falls_through() -> None:
    """A bound variable that cannot be coerced to int must fall back to treating the page size as unset.

    If this breaks, a non-integer "limit" variable could crash cost analysis
    instead of falling back to the default page-size multiplier.
    """
    # A bound variable that can't be int()-ed -> page size treated as unset.
    doc = parse("query($n: Int) { items(limit: $n) { name } }")
    total = analyze_cost(_schema(), doc, variable_values={"n": "not-an-int"}).total
    # falls back to MAX_PAGE_SIZE multiplier but children are scalar (0) -> own=1
    assert total == 1


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": 1000})
def test_analyze_cost_complexity_applied() -> None:
    """A type's declared "complexity" marker must replace the default per-node cost.

    If this breaks, an explicit complexity override on a type would be
    ignored in favor of the flat default cost.
    """
    doc = parse("{ items(limit: 2) { name } }")
    base = analyze_cost(_schema(), doc).total
    weighted = analyze_cost(_schema(complexity=9), doc).total
    assert weighted == 9  # the declared own cost replaces the default 1
    assert base == 1
