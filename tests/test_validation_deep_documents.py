"""Deep acyclic documents must never overflow the Python stack in validation.

The depth and cost walkers run on untrusted documents before execution. Both
used to recurse once per fragment link and per inline nesting level, so a
~38 KB chain of 1000 fragments raised RecursionError (HTTP 500).
"""

import json
import logging
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import RequestFactory, override_settings
from graphql import (
    GraphQLField,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)

from django_graphex.cost import CostLimitValidationRule, analyze_cost
from django_graphex.validation import DepthLimitValidationRule, run_validation
from django_graphex.views import DEFAULT_VALIDATION_RULES, GraphQLView


def _schema() -> GraphQLSchema:
    """Build a self-referential Node schema with scalar and list fields.

    Returns:
        schema: Schema whose query root exposes "root" of type Node.
    """
    node = GraphQLObjectType(
        "Node",
        lambda: {
            "name": GraphQLField(GraphQLString, resolve=lambda *_: "n"),
            "child": GraphQLField(node, resolve=lambda *_: {}),
            "siblings": GraphQLField(GraphQLList(node), resolve=lambda *_: []),
        },
    )
    query = GraphQLObjectType(
        "Query", {"root": GraphQLField(node, resolve=lambda *_: {})}
    )
    return GraphQLSchema(query=query, types=[node])


def _flat_chain(n: int) -> str:
    """Return n fragments linked by spreads that add no object nesting.

    Args:
        n: Number of fragments in the chain.

    Returns:
        query: The document text.
    """
    parts = ["{ root { ...F0 } }"]
    for i in range(n):
        body = f"...F{i + 1}" if i + 1 < n else "name"
        parts.append(f"fragment F{i} on Node {{ {body} }}")
    return "\n".join(parts)


def _nested_chain(n: int) -> str:
    """Return n fragments where each one adds an object nesting level.

    Args:
        n: Number of fragments in the chain.

    Returns:
        query: The document text.
    """
    parts = ["{ root { ...F0 } }"]
    for i in range(n):
        body = f"...F{i + 1}" if i + 1 < n else "name"
        parts.append(f"fragment F{i} on Node {{ child {{ {body} }} }}")
    return "\n".join(parts)


def _inline(n: int) -> str:
    """Return n levels of inline object nesting.

    Args:
        n: Number of nested "child" selections.

    Returns:
        query: The document text.
    """
    return "{ root { " + "child { " * n + "name" + " }" * n + " } }"


def _inline_fragments(n: int) -> str:
    """Return n levels of nested inline fragments (no object nesting).

    Args:
        n: Number of nested inline fragments.

    Returns:
        query: The document text.
    """
    return "{ root { " + "... on Node { " * n + "name" + " }" * n + " } }"


def _parse_deep(query: str) -> Any:
    """Parse a document the default-stack parser cannot, to feed the rules.

    The parser recurses per nesting level, so it gets extra stack here while
    the code under test runs with the normal limit.

    Args:
        query: The document text.

    Returns:
        document: The parsed document.
    """
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(limit * 20)
    try:
        return parse(query)
    finally:
        sys.setrecursionlimit(limit)


def _post(query: str) -> tuple[int, dict[str, Any]]:
    """Execute one real HTTP request against the Node schema.

    Args:
        query: The document text.

    Returns:
        result: The status code and decoded JSON body.
    """
    request = RequestFactory().post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )
    response = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema()))(
        request
    )
    return response.status_code, json.loads(response.content)


def _codes(body: dict[str, Any]) -> set[str]:
    """Collect the extension codes of every error in a response body.

    Args:
        body: Decoded JSON response.

    Returns:
        codes: The set of "extensions.code" values.
    """
    return {(e.get("extensions") or {}).get("code") for e in body.get("errors", [])}


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 10})
@pytest.mark.parametrize(
    "query", [_nested_chain(1500), _inline(400)], ids=["fragments", "inline"]
)
def test_deep_acyclic_document_is_a_depth_error_over_http(query: str) -> None:
    """A deep acyclic document is refused with the depth error, not a 500.

    Args:
        query: The deep document under test.
    """
    status, body = _post(query)

    assert status == 400
    assert "QUERY_TOO_DEEP" in _codes(body)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 10})
def test_long_flat_fragment_chain_is_not_a_depth_violation() -> None:
    """Spreads add no nesting, so a 1500-fragment chain stays within the limit.

    The walker must traverse the whole chain without recursion.
    """
    errors = validate(_schema(), parse(_flat_chain(1500)), [DepthLimitValidationRule])

    assert errors == []


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 10})
def test_deeply_nested_inline_fragments_are_not_a_depth_violation() -> None:
    """Inline fragments add no nesting level however deeply they are stacked.

    The document is parsed with extra stack; the rule runs with the default.
    """
    errors = validate(
        _schema(), _parse_deep(_inline_fragments(400)), [DepthLimitValidationRule]
    )

    assert errors == []


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 100000})
def test_depth_limit_far_above_the_ceiling_is_capped_without_recursion() -> None:
    """A huge configured limit is capped by the structural ceiling.

    The walker reaches the ceiling through a 1500-fragment chain without
    recursing and reports a single depth error.
    """
    errors = validate(_schema(), parse(_nested_chain(1500)), [DepthLimitValidationRule])

    assert [e.extensions["code"] for e in errors] == ["QUERY_TOO_DEEP"]
    assert "maximum nesting depth of 200" in errors[0].message


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 10**9})
@pytest.mark.parametrize(
    "query",
    [_flat_chain(1500), _nested_chain(1500), _inline(400)],
    ids=["flat", "nested", "inline"],
)
def test_cost_analysis_handles_deep_acyclic_documents(query: str) -> None:
    """Cost estimation, validation rule and the public helper never recurse.

    Args:
        query: The deep document under test.
    """
    document = _parse_deep(query)

    assert analyze_cost(_schema(), document).total >= 1
    assert validate(_schema(), document, [CostLimitValidationRule]) == []


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 5})
def test_cost_limit_still_applies_to_deep_chains() -> None:
    """A deep chain over budget yields the cost error, not a stack overflow.

    The budget is exceeded by the first few levels of the chain.
    """
    errors = validate(_schema(), parse(_nested_chain(1500)), [CostLimitValidationRule])

    assert [e.extensions["code"] for e in errors] == ["QUERY_TOO_COMPLEX"]


@pytest.mark.parametrize(
    "query", [_flat_chain(1500), _inline(400)], ids=["fragments", "inline"]
)
def test_document_beyond_the_library_stack_is_a_client_error_without_limits(
    query: str,
) -> None:
    """With no depth/cost limit set, the parser/validator stack limit is a 400.

    graphql-core's parser and its NoFragmentCycles rule recurse per level, so
    these documents cannot be processed at all; that is the client's error.

    Args:
        query: The document beyond the library stack.
    """
    status, body = _post(query)

    assert status == 400
    assert _codes(body) == {"QUERY_TOO_DEEP"}


def test_moderately_long_fragment_chain_executes_without_limits() -> None:
    """A chain the library stack can handle still gets a normal response.

    The guard must not change the outcome of documents that fit the stack.
    """
    status, body = _post(_flat_chain(200))

    assert status == 200
    assert body["data"] == {"root": {"name": "n"}}


def _buggy_rule(*_args: Any) -> list[Any]:
    """Fail like a buggy custom validation rule.

    Args:
        *_args: Ignored.

    Raises:
        ValueError: Always.
    """
    raise ValueError("custom rule bug")


def test_run_validation_only_converts_stack_exhaustion() -> None:
    """Other validation failures are not swallowed as depth errors.

    Resolver and user-code errors must keep surfacing as server errors.
    """

    with pytest.raises(ValueError, match="custom rule bug"):
        run_validation(_buggy_rule)
    assert run_validation(lambda *a: (a[0],), "ok") == ["ok"]


@pytest.mark.parametrize(
    "settings_dict", [{}, {"MAX_QUERY_DEPTH": 100000}], ids=["unset", "above-ceiling"]
)
def test_fragment_nested_document_hits_the_structural_ceiling(
    settings_dict: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Fragments cannot nest deeper than the ceiling inline documents obey.

    Each fragment is shallow, so parsing succeeds; the depth rule's hard
    ceiling must answer 400 even with no (or a larger) MAX_QUERY_DEPTH, and
    nothing may reach the internal-error log.

    Args:
        settings_dict: The DJANGO_GRAPHEX override under test.
        caplog: Pytest log capture.
    """
    caplog.set_level(logging.DEBUG)
    with override_settings(DJANGO_GRAPHEX=settings_dict):
        status, body = _post(_nested_chain(300))

    assert status == 400
    assert _codes(body) == {"QUERY_TOO_DEEP"}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@override_settings(DJANGO_GRAPHEX={})
def test_documents_under_the_structural_ceiling_are_untouched() -> None:
    """A 100-level fragment chain still gets a normal response without limits.

    Documents under the ceiling must behave exactly as before.
    """
    status, body = _post(_nested_chain(100))

    assert status == 200
    assert "errors" not in body


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 5})
def test_configured_limit_below_the_ceiling_still_wins() -> None:
    """The ceiling never loosens a stricter configured limit.

    The configured limit is the one named in the error.
    """
    errors = validate(_schema(), parse(_nested_chain(50)), [DepthLimitValidationRule])

    assert [e.message for e in errors] == [
        "Query exceeds the maximum nesting depth of 5 for 'query'."
    ]


@override_settings(DJANGO_GRAPHEX={})
def test_default_rules_used_by_subscription_transports_enforce_the_ceiling() -> None:
    """The shared rule tuple (HTTP, WS and SSE) carries the ceiling.

    All three surfaces validate with this tuple.
    """
    errors = validate(
        _schema(), parse(_nested_chain(300)), list(DEFAULT_VALIDATION_RULES)
    )

    assert [e.extensions["code"] for e in errors] == ["QUERY_TOO_DEEP"]
