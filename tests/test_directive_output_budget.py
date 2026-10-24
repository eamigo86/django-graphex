"""Per-request aggregate budget for directive-produced text, and directive cost."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from graphql import (
    GraphQLField,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    parse,
    specified_directives,
)

from django_graphex.cost import analyze_cost
from django_graphex.directives import all_directives
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.settings import graphql_api_settings

_ROW = GraphQLObjectType("Row", {"name": GraphQLField(GraphQLString)})
_QUERY = GraphQLObjectType(
    "Query",
    {
        "text": GraphQLField(GraphQLString),
        "rows": GraphQLField(GraphQLList(_ROW)),
    },
)
_SCHEMA = GraphQLSchema(
    query=_QUERY, directives=[*specified_directives, *all_directives]
)
_ROOT = {"text": "abc", "rows": [{"name": "r"}] * 5}


def _execute(query: str) -> Any:
    """Execute a query with the directive middleware.

    Args:
        query: The GraphQL document.

    Returns:
        The execution result.
    """
    return graphql_sync(
        _SCHEMA,
        query,
        root_value=_ROOT,
        middleware=[GraphQLDirectiveMiddleware()],
    )


def _aliases(count: int, new: str = "WXYZ") -> str:
    """Build aliased expanding selections over the scalar field.

    Args:
        count: Number of aliases.
        new: Replacement text.

    Returns:
        The selection body.
    """
    return " ".join(f'a{i}: text @replace(old: "", new: "{new}")' for i in range(count))


def test_default_budget_is_ten_million() -> None:
    """The aggregate budget is on by default and cost per directive is opt-in.

    The settings are overridden per test and restored afterwards.
    """
    assert graphql_api_settings.MAX_DIRECTIVE_OUTPUT_TOTAL == 10_000_000
    assert graphql_api_settings.COST_DIRECTIVE == 0


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 100})
def test_budget_spans_aliases() -> None:
    """Aliases each under the per-field cap still exhaust the request budget.

    The settings are overridden per test and restored afterwards.
    """
    result = _execute("{ %s }" % _aliases(10))  # each alias grows 3 -> 15 (+12)
    data = result.data or {}
    produced = [k for k, v in data.items() if v is not None]
    assert 0 < len(produced) < 10
    assert result.errors
    assert "MAX_DIRECTIVE_OUTPUT_TOTAL" in result.errors[0].message


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 100})
def test_budget_spans_rows() -> None:
    """Rows of a list share the same request budget.

    The settings are overridden per test and restored afterwards.
    """
    q = '{ rows { name @replace(old: "", new: "%s") } }' % ("Z" * 30)
    result = _execute(q)
    assert result.errors
    assert "MAX_DIRECTIVE_OUTPUT_TOTAL" in result.errors[0].message


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 100})
def test_budget_counts_chained_directives() -> None:
    """Growth from each directive of a chain is charged.

    The settings are overridden per test and restored afterwards.
    """
    chain = '@replace(old: "", new: "WXYZWXYZ") @center(width: 40, fillchar: "-")'
    result = _execute("{ a: text %s b: text %s c: text %s }" % (chain, chain, chain))
    assert result.errors
    assert "MAX_DIRECTIVE_OUTPUT_TOTAL" in result.errors[0].message


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 100})
def test_exhausted_budget_stops_later_fields() -> None:
    """Once the budget is spent later growing fields error without producing text.

    The settings are overridden per test and restored afterwards.
    """
    result = _execute("{ %s }" % _aliases(30))
    nulls = [k for k, v in (result.data or {}).items() if v is None]
    assert len(nulls) > 15
    assert len(result.errors or []) == len(nulls)


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 100})
def test_budget_is_per_request() -> None:
    """A second request starts from zero.

    The settings are overridden per test and restored afterwards.
    """
    one = _execute("{ %s }" % _aliases(3))
    two = _execute("{ %s }" % _aliases(3))
    assert not one.errors and not two.errors


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": None})
def test_budget_none_disables() -> None:
    """None removes the aggregate budget.

    The settings are overridden per test and restored afterwards.
    """
    assert not _execute("{ %s }" % _aliases(30)).errors


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 10_000})
def test_non_growing_directives_are_free() -> None:
    """Directives that do not grow the text are never charged.

    The settings are overridden per test and restored afterwards.
    """
    q = "{ %s }" % " ".join(f"a{i}: text @uppercase" for i in range(500))
    assert not _execute(q).errors


@override_settings(
    DJANGO_GRAPHEX={
        "MAX_DIRECTIVE_OUTPUT_TOTAL": 10_000,
        "MAX_REPLACE_OUTPUT_LENGTH": 8,
    }
)
def test_per_field_cap_still_applies() -> None:
    """The per-field replace cap keeps working beside the aggregate budget.

    The settings are overridden per test and restored afterwards.
    """
    result = _execute('{ text @replace(old: "", new: "WXYZ") }')
    assert result.errors
    assert "MAX_REPLACE_OUTPUT_LENGTH" in result.errors[0].message


@pytest.mark.parametrize("value", [0, -1, True, "x"])
def test_budget_rejects_bad_values(value: Any) -> None:
    """Only a positive integer or None is accepted.

    Args:
        value: A rejected setting value.
    """
    with override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": value}):
        with pytest.raises(ImproperlyConfigured):
            graphql_api_settings.MAX_DIRECTIVE_OUTPUT_TOTAL  # noqa: B018


def _cost(query: str) -> int:
    """Estimate the cost of a query against the test schema.

    Args:
        query: The GraphQL document.

    Returns:
        The estimated cost.
    """
    return analyze_cost(_SCHEMA, parse(query)).total


def test_directive_cost_default_changes_nothing() -> None:
    """With the default COST_DIRECTIVE of 0 directives add no cost.

    The settings are overridden per test and restored afterwards.
    """
    plain = "{ rows { name } }"
    with_directive = '{ rows { name @replace(old: "a", new: "b") } }'
    assert _cost(plain) == _cost(with_directive)


@override_settings(DJANGO_GRAPHEX={"COST_DIRECTIVE": 2, "MAX_PAGE_SIZE": 10})
def test_directive_cost_counts_aliases_and_rows() -> None:
    """Each directive use costs COST_DIRECTIVE and is multiplied by the list size.

    The settings are overridden per test and restored afterwards.
    """
    base = _cost("{ rows { a: name b: name } }")
    one = _cost('{ rows { a: name @replace(old: "a", new: "b") b: name } }')
    two = _cost(
        '{ rows { a: name @replace(old: "a", new: "b") b: name @uppercase @lowercase } }'
    )
    assert one - base == 10 * 2
    assert two - base == 10 * 2 * 3
    assert _cost("{ text @uppercase }") - _cost("{ text }") == 2


@override_settings(DJANGO_GRAPHEX={"COST_DIRECTIVE": 3})
def test_skip_and_include_are_not_charged() -> None:
    """The built-in conditionals are not counted as directive uses.

    The settings are overridden per test and restored afterwards.
    """
    assert _cost("{ text @include(if: true) }") == _cost("{ text }")


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 10})
def test_budget_restarts_per_subscription_event() -> None:
    """Events share variable values but have their own root value.

    The counter therefore restarts for each event instead of accumulating over
    the lifetime of a long-lived subscription.
    """
    from types import SimpleNamespace

    from graphql import GraphQLError

    from django_graphex.middleware import _charge

    shared: dict[str, Any] = {}
    for _ in range(3):
        info = SimpleNamespace(variable_values=shared, root_value={})
        _charge(info, 8, "replace")  # type: ignore[arg-type]
    info = SimpleNamespace(variable_values=shared, root_value={})
    _charge(info, 8, "replace")  # type: ignore[arg-type]
    with pytest.raises(GraphQLError):
        _charge(info, 8, "replace")  # type: ignore[arg-type]
