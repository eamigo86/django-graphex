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
    import gc
    from types import SimpleNamespace

    from django_graphex import middleware
    from django_graphex._execution_state import EXECUTION_TABLE_SIZE

    for _ in range(EXECUTION_TABLE_SIZE + 20):
        info = SimpleNamespace(variable_values={}, root_value=None, context=None)
        middleware._charge(info, 1, "replace")  # type: ignore[arg-type]
    gc.collect()  # entries of finished executions leave the weak table
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


def _post_two_items(view_class: Any) -> list[dict[str, Any]]:
    """POST two identical growing items to a batch view of the given class.

    Args:
        view_class: GraphQLView or a subclass of it.

    Returns:
        The decoded JSON answer.
    """
    import json
    from types import ModuleType, SimpleNamespace

    from django.test import Client
    from django.urls import path

    schema = SimpleNamespace(
        graphql_schema=GraphQLSchema(
            query=GraphQLObjectType(
                "Q", {"text": GraphQLField(GraphQLString, resolve=lambda *_: "x")}
            ),
            directives=[*specified_directives, *all_directives],
        )
    )
    urls = ModuleType("budget_two_urls")
    urls.urlpatterns = [path("g/", view_class.as_view(schema=schema, batch=True))]  # type: ignore[attr-defined]
    settings_override = {
        "MAX_DIRECTIVE_OUTPUT_TOTAL": 100,
        "MAX_BATCH_SIZE": 20,
        "MIDDLEWARE": ["django_graphex.middleware.GraphQLDirectiveMiddleware"],
    }
    body = {"query": "{ text @center(width: 100) }"}
    with override_settings(DJANGO_GRAPHEX=settings_override, ROOT_URLCONF=urls):
        response = Client().post(
            "/g/", data=json.dumps([body, body]), content_type="application/json"
        )
    return json.loads(response.content)  # type: ignore[no-any-return]


def _dict_context_view() -> Any:
    """Build a view class whose context is a plain dict.

    Returns:
        A GraphQLView subclass with a dict get_context.
    """
    from django_graphex.views import GraphQLView

    class DictContextView(GraphQLView):
        """View handing resolvers a dict instead of the request."""

        def get_context(self, request: Any) -> Any:
            """Return a dict context.

            Args:
                request: The incoming HTTP request.

            Returns:
                A new dict holding the request.
            """
            return {"request": request}

    return DictContextView


@pytest.mark.parametrize("dict_context", [False, True])
def test_batch_shares_the_budget_for_any_mutable_context(dict_context: bool) -> None:
    """Two items growing 99 characters each cannot both fit a budget of 100.

    The default request context and a dict context both carry the counter.

    Args:
        dict_context: Whether the view hands resolvers a dict context.
    """
    from django_graphex.views import GraphQLView

    view = _dict_context_view() if dict_context else GraphQLView
    first, second = _post_two_items(view)
    assert not first.get("errors")
    assert "MAX_DIRECTIVE_OUTPUT_TOTAL" in second["errors"][0]["message"]


def test_reused_dict_context_gets_a_fresh_budget_per_request() -> None:
    """The same dict bound for a new request starts from zero again.

    Each request binds a new budget object over the reused dict.
    """
    from types import SimpleNamespace

    from django_graphex._execution_state import bind_request_budget, request_budget_of

    context: dict[str, Any] = {}
    seen = []
    for _ in range(2):
        request = SimpleNamespace()
        bind_request_budget(request, context)
        budget = request_budget_of(context)
        assert budget is request_budget_of(request)
        seen.append(budget)
    assert seen[0] is not seen[1]


def test_immutable_mapping_context_stays_per_execution() -> None:
    """A mapping that cannot take the counter is not bound.

    The execution then keeps its per-execution budget.
    """
    from types import MappingProxyType, SimpleNamespace

    from django_graphex._execution_state import bind_request_budget, request_budget_of

    context = MappingProxyType({})
    bind_request_budget(SimpleNamespace(), context)
    assert request_budget_of(context) is None


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


_FILLERS = 1100


def _serial_fillers(schema: GraphQLSchema, query: str, context: Any = None) -> None:
    """Run more complete serial executions than the fallback table holds.

    Args:
        schema: Schema the fillers run against.
        query: Query each filler runs.
        context: Context value of every filler.
    """
    for _ in range(_FILLERS):
        result = graphql_sync(
            schema,
            query,
            context_value=context,
            middleware=[GraphQLDirectiveMiddleware()],
        )
        assert not result.errors


async def _run_with_fillers(fillers: bool, context: Any) -> Any:
    """Grow 99 characters, wait, optionally run fillers, then grow 99 more.

    Args:
        fillers: Whether to run serial executions while the first waits.
        context: Context value of the waiting execution.

    Returns:
        The execution result of the waiting operation.
    """
    import asyncio

    from graphql import graphql

    started = asyncio.Event()
    release = asyncio.Event()

    async def second(*_: Any) -> str:
        started.set()
        await release.wait()
        return "x"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "Q",
            {
                "one": GraphQLField(GraphQLString, resolve=lambda *_: "x"),
                "two": GraphQLField(GraphQLString, resolve=second),
            },
        ),
        directives=[*specified_directives, *all_directives],
    )
    task = asyncio.ensure_future(
        graphql(
            schema,
            "{ one @center(width: 100) two @center(width: 100) }",
            context_value=context,
            middleware=[GraphQLDirectiveMiddleware()],
        )
    )
    await started.wait()
    if fillers:
        _serial_fillers(schema, "{ one @center(width: 100) }", context={})
    release.set()
    return await task


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 150})
@pytest.mark.parametrize("fillers", [False, True])
@pytest.mark.parametrize("context", [None, {}])
def test_live_execution_keeps_its_counter_across_many_executions(
    fillers: bool, context: Any
) -> None:
    """A running execution is not reset by other executions finishing.

    Field one adds 99 characters, then field two waits while more than the
    fallback table size of other executions run; field two's own 99 must still
    exceed the budget of 150.

    Args:
        fillers: Whether other executions run while field two waits.
        context: Context value of the waiting execution.
    """
    import asyncio

    result = asyncio.run(_run_with_fillers(fillers, context))
    assert result.data is not None
    assert result.data["one"] is not None
    assert result.data["two"] is None
    assert result.errors
    assert "MAX_DIRECTIVE_OUTPUT_TOTAL" in result.errors[0].message


@pytest.mark.parametrize("fillers", [False, True])
def test_live_execution_keeps_its_optimizer_work_across_many_executions(
    fillers: bool,
) -> None:
    """The optimizer work state of a running execution survives other runs.

    Two fields of one execution read the same state before and after more than
    the fallback table size of other executions completed.

    Args:
        fillers: Whether other executions run while field two waits.
    """
    import asyncio

    from graphql import graphql

    from django_graphex.utils import _request_work

    states: list[dict[str, Any]] = []

    async def go() -> None:
        gate = asyncio.Event()
        started = asyncio.Event()

        def one(_root: Any, info: Any) -> str:
            work = _request_work(info)
            work["used"]["walker"] = 7
            work["exhausted"] = True
            states.append(work)
            return "x"

        async def two(_root: Any, info: Any) -> str:
            started.set()
            await gate.wait()
            states.append(_request_work(info))
            return "x"

        def filler(_root: Any, info: Any) -> str:
            assert _request_work(info) == {"used": {}, "exhausted": False}
            return "x"

        def schema_of(a: Any, b: Any) -> GraphQLSchema:
            return GraphQLSchema(
                query=GraphQLObjectType(
                    "Q",
                    {
                        "one": GraphQLField(GraphQLString, resolve=a),
                        "two": GraphQLField(GraphQLString, resolve=b),
                    },
                )
            )

        task = asyncio.ensure_future(graphql(schema_of(one, two), "{ one two }"))
        await started.wait()
        if fillers:
            plain = schema_of(filler, filler)
            for _ in range(_FILLERS):
                graphql_sync(plain, "{ one }")
        gate.set()
        assert not (await task).errors

    asyncio.run(go())
    assert states[0] is states[1]
    assert states[1] == {"used": {"walker": 7}, "exhausted": True}


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 150})
def test_real_subscription_events_each_get_their_own_counter() -> None:
    """Each event of a graphql-core subscription restarts the counter.

    Events share one source executor, but each grows 99 characters under a
    budget of 150 and none of them fails.
    """
    import asyncio

    from graphql import subscribe

    async def source(*_: Any) -> Any:
        for event in range(3):
            yield f"event {event}"

    schema = GraphQLSchema(
        query=_QUERY,
        subscription=GraphQLObjectType(
            "S",
            {
                "t": GraphQLField(
                    GraphQLString, subscribe=source, resolve=lambda value, _i: value
                )
            },
        ),
        directives=[*specified_directives, *all_directives],
    )

    async def go() -> list[Any]:
        stream = subscribe(
            schema,
            parse("subscription { t @center(width: 100) }"),
            middleware=[GraphQLDirectiveMiddleware()],
        )
        return [result async for result in stream]

    results = asyncio.run(go())
    assert len(results) == 3
    assert not any(result.errors for result in results)


@override_settings(DJANGO_GRAPHEX={"MAX_DIRECTIVE_OUTPUT_TOTAL": 150})
def test_live_subscription_event_keeps_its_counter_across_other_events() -> None:
    """A subscription event still running is not reset by other streams' events.

    Event one grows 99 characters, then waits while more than the fallback table
    size of events of another subscription complete; its next 99 must exceed 150.
    """
    import asyncio

    from graphql import subscribe

    started = asyncio.Event()
    release = asyncio.Event()

    async def second(*_: Any) -> str:
        started.set()
        await release.wait()
        return "x"

    async def main_source(*_: Any) -> Any:
        yield {"n": 1}

    async def filler_source(*_: Any) -> Any:
        for index in range(_FILLERS):
            yield {"n": index}

    item = GraphQLObjectType(
        "Item",
        {
            "one": GraphQLField(GraphQLString, resolve=lambda *_: "x"),
            "two": GraphQLField(GraphQLString, resolve=second),
            "plain": GraphQLField(GraphQLString, resolve=lambda *_: "x"),
        },
    )
    schema = GraphQLSchema(
        query=_QUERY,
        subscription=GraphQLObjectType(
            "S",
            {
                "main": GraphQLField(
                    item, subscribe=main_source, resolve=lambda value, _i: value
                ),
                "filler": GraphQLField(
                    item, subscribe=filler_source, resolve=lambda value, _i: value
                ),
            },
        ),
        directives=[*specified_directives, *all_directives],
    )

    async def go() -> Any:
        middleware = [GraphQLDirectiveMiddleware()]
        main = subscribe(
            schema,
            parse(
                "subscription { main { one @center(width: 100) two @center(width: 100) } }"
            ),
            middleware=middleware,
        )
        task = asyncio.ensure_future(main.__anext__())
        await started.wait()
        async for result in subscribe(
            schema,
            parse("subscription { filler { plain @center(width: 100) } }"),
            middleware=middleware,
        ):
            assert not result.errors
        release.set()
        return await task

    result = asyncio.run(go())
    assert result.data is not None
    assert result.data["main"]["two"] is None
    assert "MAX_DIRECTIVE_OUTPUT_TOTAL" in result.errors[0].message
