"""Bounded rejection of cyclic fragment graphs before cost and depth expansion."""

from __future__ import annotations

import json

import pytest
from django.test import RequestFactory, override_settings
from graphql import GraphQLError, parse, validate
from graphql.validation import specified_rules

from django_graphex._fragment_cycles import find_fragment_cycle
from django_graphex.cost import CostLimitValidationRule, _CostAnalyzer, analyze_cost
from django_graphex.validation import DepthLimitValidationRule
from django_graphex.views import GraphQLView
from tests.test_fragment_fanout import _schema
from tests.test_views import test_schema


def _cyclic_fanout(levels: int) -> str:
    """Build a small branching fragment graph with one closing edge.

    Args:
        levels: Number of branching fragment definitions.

    Returns:
        GraphQL document containing a reachable fragment cycle.
    """
    fragments = "\n".join(
        f"fragment F{i} on Node {{ child {{ ...F{i + 1} }} child {{ ...F{i + 1} }} }}"
        for i in range(levels)
    )
    return (
        "{ root { ...F0 } }\n"
        f"{fragments}\nfragment F{levels} on Node {{ name child {{ ...F0 }} }}"
    )


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 100, "MAX_QUERY_COST": 10**9})
def test_cyclic_fanout_is_rejected_before_expensive_walks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compact cyclic graph must not expand by its number of spread paths.

    Count actual cost and depth walker entries rather than relying on timing.
    """
    counts = {"cost": 0, "depth": 0}
    original_cost = _CostAnalyzer._selection_set_cost
    original_depth = DepthLimitValidationRule._walk

    def count_cost(self: _CostAnalyzer, *args: object) -> int:
        counts["cost"] += 1
        return original_cost(self, *args)

    def count_depth(self: DepthLimitValidationRule, *args: object) -> None:
        counts["depth"] += 1
        original_depth(self, *args)

    monkeypatch.setattr(_CostAnalyzer, "_selection_set_cost", count_cost)
    monkeypatch.setattr(DepthLimitValidationRule, "_walk", count_depth)
    document = parse(_cyclic_fanout(8))
    schema = _schema()

    with pytest.raises(GraphQLError, match="[Cc]yclic fragment"):
        analyze_cost(schema, document)
    errors = validate(
        schema,
        document,
        [*specified_rules, DepthLimitValidationRule, CostLimitValidationRule],
    )

    assert any("within itself" in error.message for error in errors)
    assert counts["cost"] <= 10
    assert counts["depth"] <= 10


def test_disconnected_fragment_cycle_rejects_direct_cost_analysis() -> None:
    """Structural cycles are invalid even when the selected operation omits them.

    This prevents public cost analysis from returning a misleading report.
    """
    document = parse(
        "{ root { name } } fragment A on Node { ...B } fragment B on Node { ...A }"
    )

    with pytest.raises(GraphQLError, match="[Cc]yclic fragment"):
        analyze_cost(_schema(), document)


def test_acyclic_spreads_and_missing_targets_do_not_trigger_cycle_check() -> None:
    """Only references among defined fragments form graph edges.

    A missing target remains the responsibility of normal GraphQL validation.
    """
    document = parse(
        "{ root { ...A } } fragment A on Node { ...B ...B ...Missing } "
        "fragment B on Node { ... on Node { name } }"
    )

    assert find_fragment_cycle(document) is None
    assert analyze_cost(_schema(), document).total == 1


def test_dense_multi_entry_cycle_is_detected() -> None:
    """Multiple inbound paths must not obscure a downstream cycle.

    The graph reduction processes distinct edges, not expanded spread paths.
    """
    document = parse(
        "{ root { ...A ...B } } "
        "fragment A on Node { ...C ...D } "
        "fragment B on Node { ...C ...D } "
        "fragment C on Node { ...D } "
        "fragment D on Node { ...C }"
    )

    assert find_fragment_cycle(document) is not None
    with pytest.raises(GraphQLError, match="Cyclic fragment reference"):
        analyze_cost(_schema(), document)


def test_long_fragment_chain_uses_iterative_cycle_check() -> None:
    """A long shallow graph must not overflow Python's recursion limit.

    Both an acyclic chain and its one-edge cyclic variant are inspected.
    """
    chain = "\n".join(f"fragment F{i} on Node {{ ...F{i + 1} }}" for i in range(1100))
    acyclic = parse(
        f"{{ root {{ name }} }}\n{chain}\nfragment F1100 on Node {{ name }}"
    )
    cyclic = parse(
        f"{{ root {{ name }} }}\n{chain}\nfragment F1100 on Node {{ ...F0 }}"
    )

    assert find_fragment_cycle(acyclic) is None
    assert find_fragment_cycle(cyclic) is not None


def test_default_view_rejects_cycle_without_running_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default endpoint returns validation errors before resolver execution.

    Cost reporting must not turn the cyclic document into a raw server error.
    """
    schema = test_schema.graphql_schema
    assert schema.query_type is not None
    hello = schema.query_type.fields["hello"]
    called = 0

    def resolve_hello(*_args: object, **_kwargs: object) -> str:
        nonlocal called
        called += 1
        return "unexpected"

    monkeypatch.setattr(hello, "resolve", resolve_hello)
    root_type = schema.query_type.name
    query = f"{{ hello ...F }} fragment F on {root_type} {{ ...F }}"
    request = RequestFactory().post(
        "/graphql/", {"query": query}, content_type="application/json"
    )
    response = GraphQLView.as_view(schema=test_schema)(request)
    body = json.loads(response.content)

    assert response.status_code == 400
    assert any("within itself" in error["message"] for error in body["errors"])
    assert called == 0
