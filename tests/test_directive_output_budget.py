"""Per-request aggregate budget for directive-produced text, and directive cost."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
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
    request = SimpleNamespace()
    for _ in range(3):
        info = SimpleNamespace(variable_values=shared, root_value={}, context=request)
        _charge(info, 8, "replace")  # type: ignore[arg-type]
    info = SimpleNamespace(variable_values=shared, root_value={}, context=request)
    _charge(info, 8, "replace")  # type: ignore[arg-type]
    with pytest.raises(GraphQLError):
        _charge(info, 8, "replace")  # type: ignore[arg-type]


def _seen_variables(info: Any) -> str:
    """Resolve to the names of the variables the resolver can see.

    Args:
        info: The GraphQL resolve info.

    Returns:
        The sorted variable names joined by commas.
    """
    values = getattr(info.variable_values, "coerced", info.variable_values)
    return ",".join(sorted(values))


_RESOLVED = GraphQLSchema(
    query=GraphQLObjectType(
        "Query",
        {
            "text": GraphQLField(
                GraphQLString,
                args={"v": GraphQLArgument(GraphQLList(GraphQLInt))},
                resolve=lambda *_args, **_kw: "abc",
            ),
            "keys": GraphQLField(
                GraphQLString,
                args={"x": GraphQLArgument(GraphQLInt)},
                resolve=lambda _root, info, x=None: _seen_variables(info),
            ),
        },
    ),
    directives=[*specified_directives, *all_directives],
)


def _run_resolved(query: str, variables: dict[str, Any] | None = None) -> Any:
    """Execute against resolver-backed fields with no root value.

    Args:
        query: The GraphQL document.
        variables: Request variables.

    Returns:
        The execution result.
    """
    return graphql_sync(
        _RESOLVED,
        query,
        variable_values=variables,
        middleware=[GraphQLDirectiveMiddleware()],
    )


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 100})
def test_client_variable_cannot_seed_the_counter() -> None:
    """A client variable named like the old internal key must not shift the budget.

    Each alias grows the text by 12 characters, so ten aliases exceed 100 even
    when the client declares a variable carrying a hugely negative counter.
    """
    name = "__graphex_directive_output__"
    body = " ".join(
        f'a{i}: text(v: ${name}) @replace(old: "", new: "WXYZ")' for i in range(10)
    )
    result = _run_resolved(
        "query($%s: [Int]) { %s }" % (name, body), {name: [None, -(10**9)]}
    )
    assert result.errors
    assert "MAX_DIRECTIVE_OUTPUT_TOTAL" in result.errors[0].message


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 1000})
def test_resolvers_only_see_declared_variables() -> None:
    """The budget leaves no extra entry in the variable values.

    The resolver must see exactly the variables the request declared.
    """
    result = _run_resolved(
        'query($x: Int) { a: text @replace(old: "", new: "WXYZ") keys(x: $x) }',
        {"x": 1},
    )
    assert not result.errors
    assert result.data["keys"] == "x"


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 100})
def test_dict_context_budget_is_per_execution() -> None:
    """A context that cannot take attributes still gets a fresh budget per run.

    Repeated executions sharing one dict context do not accumulate.
    """
    body = " ".join(f'a{i}: text @replace(old: "", new: "WXYZ")' for i in range(5))
    context: dict[str, Any] = {}
    for _ in range(3):
        result = graphql_sync(
            _RESOLVED,
            "{ %s }" % body,
            context_value=context,
            middleware=[GraphQLDirectiveMiddleware()],
        )
        assert not result.errors


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 1000})
def test_execution_table_stays_bounded() -> None:
    """Executions without a request budget cannot grow memory.

    The module table drops its least recently used entries past a fixed size.
    """
    from types import SimpleNamespace

    from django_graphex import middleware
    from django_graphex._execution_state import EXECUTION_TABLE_SIZE

    for _ in range(EXECUTION_TABLE_SIZE + 20):
        info = SimpleNamespace(variable_values={}, root_value=None, context=None)
        middleware._charge(info, 1, "replace")  # type: ignore[arg-type]
    assert len(middleware._EXECUTIONS) <= EXECUTION_TABLE_SIZE


def _concurrent(contexts: list[Any], count: int = 30) -> list[int]:
    """Run async executions concurrently and count each one's produced fields.

    Args:
        contexts: One context value per concurrent execution.
        count: Aliases per execution.

    Returns:
        The number of non-null fields of every execution.
    """
    import asyncio
    import random

    from graphql import graphql

    rng = random.Random(7)

    async def slow(_root: Any, _info: Any) -> str:
        """Yield to the loop so executions interleave.

        Args:
            _root: Unused root value.
            _info: Unused resolve info.

        Returns:
            A short text.
        """
        await asyncio.sleep(rng.random() * 0.01)
        return "x"

    schema = GraphQLSchema(
        query=GraphQLObjectType("Q", {"a": GraphQLField(GraphQLString, resolve=slow)}),
        directives=[*specified_directives, *all_directives],
    )
    body = " ".join(f"f{i}: a @center(width: 100)" for i in range(count))

    async def go() -> list[Any]:
        """Gather every execution.

        Returns:
            The execution results.
        """
        return list(
            await asyncio.gather(
                *[
                    graphql(
                        schema,
                        "{ %s }" % body,
                        context_value=c,
                        middleware=[GraphQLDirectiveMiddleware()],
                    )
                    for c in contexts
                ]
            )
        )

    return [
        sum(v is not None for v in (r.data or {}).values()) for r in asyncio.run(go())
    ]


class _Ctx:
    """A plain attribute-capable context.

    It stands in for any request-like object that can carry attributes.
    """


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 400})
@pytest.mark.parametrize("kind", ["object", "dict", "none"])
def test_many_concurrent_executions_keep_their_own_counters(kind: str) -> None:
    """More than 64 concurrent executions never reset each other's counter.

    Every execution adds 99 characters per field, so the budget of 400 allows 4
    fields; none may get more, however many run at once.

    Args:
        kind: The context type shared by (object, dict) or absent (none).
    """
    shared: Any = {"object": _Ctx(), "dict": {}, "none": None}[kind]
    produced = _concurrent([shared] * 150)
    assert produced and max(produced) <= 4


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 400})
def test_a_mock_context_cannot_disable_the_budget() -> None:
    """A context whose __getattr__ invents values still gets a real budget.

    The budget is read from the instance dictionary, never through getattr.
    """
    from unittest.mock import MagicMock

    assert max(_concurrent([MagicMock()])) <= 4


def _post_batch(items: int, aliases: int, budget: int) -> list[dict[str, Any]]:
    """POST a batch of identical expanding queries to the GraphQL view.

    Args:
        items: Number of batch items.
        aliases: Aliased expanding fields per item.
        budget: MAX_DIRECTIVE_OUTPUT_TOTAL for the request.

    Returns:
        The decoded JSON answer.
    """
    import json
    from types import ModuleType, SimpleNamespace

    from django.test import Client
    from django.urls import path

    from django_graphex.views import GraphQLView

    schema = SimpleNamespace(
        graphql_schema=GraphQLSchema(
            query=GraphQLObjectType(
                "Q", {"a": GraphQLField(GraphQLString, resolve=lambda *_: "x")}
            ),
            directives=[*specified_directives, *all_directives],
        )
    )
    urls = ModuleType("budget_urls")
    urls.urlpatterns = [path("g/", GraphQLView.as_view(schema=schema, batch=True))]  # type: ignore[attr-defined]
    body = "{ %s }" % " ".join(f"f{i}: a @center(width: 100)" for i in range(aliases))
    settings_override = {
        "MAX_DIRECTIVE_OUTPUT_TOTAL": budget,
        "MAX_BATCH_SIZE": 20,
        "MIDDLEWARE": ["django_graphex.middleware.GraphQLDirectiveMiddleware"],
    }
    with override_settings(DJANGO_GRAPHEX=settings_override, ROOT_URLCONF=urls):
        response = Client().post(
            "/g/",
            data=json.dumps([{"query": body}] * items),
            content_type="application/json",
        )
    return json.loads(response.content)  # type: ignore[no-any-return]


def test_batch_items_share_one_request_budget() -> None:
    """Ten items of one batch together may add only the request budget.

    Each field adds 99 characters, so a budget of 1000 allows ten fields in
    total across the whole batch, not ten per item.
    """
    answer = _post_batch(items=10, aliases=20, budget=1000)
    produced = sum(
        v is not None for item in answer for v in (item.get("data") or {}).values()
    )
    assert 0 < produced <= 11
    assert any(item.get("errors") for item in answer)


def test_a_single_request_item_is_unchanged() -> None:
    """A batch of one behaves as before: its own budget.

    The request budget of a single item equals the former per-execution one.
    """
    answer = _post_batch(items=1, aliases=20, budget=1000)
    produced = sum(v is not None for v in (answer[0].get("data") or {}).values())
    assert 0 < produced <= 11


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 10})
def test_subscription_events_restart_even_with_a_request_budget() -> None:
    """A subscription event ignores the request budget and has its own.

    Events of a long-lived request context would otherwise accumulate.
    """
    from types import SimpleNamespace

    from graphql import OperationType

    from django_graphex._execution_state import RequestBudget, bind_request_budget
    from django_graphex.middleware import _charge

    request = SimpleNamespace()
    bind_request_budget(request, request)
    assert isinstance(vars(request)["_graphex_request_budget"], RequestBudget)
    subscription = SimpleNamespace(operation=OperationType.SUBSCRIPTION)
    shared: dict[str, Any] = {}
    for _ in range(3):
        info = SimpleNamespace(
            variable_values=shared,
            root_value={},
            context=request,
            operation=subscription,
        )
        _charge(info, 8, "replace")  # type: ignore[arg-type]
    assert vars(request)["_graphex_request_budget"].used == 0
