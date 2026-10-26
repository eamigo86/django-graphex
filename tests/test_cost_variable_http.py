"""HTTP regressions for selected-operation cost with bound request variables."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from django.test import RequestFactory, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLString,
)
from graphql import execution as graphql_execution
from graphql import validate as graphql_validate
from graphql.language import IntValueNode
from pydantic import BaseModel, Field

from django_graphex.core import InputType
from django_graphex.core.input_compiler import compile_input_type
from django_graphex.views import GraphQLView


def _schema(resolved: list[int], limit_type: Any = GraphQLInt) -> GraphQLSchema:
    """Build a one-item list whose nested object makes limit affect cost."""
    inner = GraphQLObjectType("CostInner", {"name": GraphQLField(GraphQLString)})
    item = GraphQLObjectType("CostItem", {"child": GraphQLField(inner)})

    def resolve_items(_root: Any, _info: Any, limit: int | None = None) -> list[Any]:
        resolved.append(limit or 0)
        return [{"child": {"name": "one"}}]

    query = GraphQLObjectType(
        "CostQuery",
        {
            "items": GraphQLField(
                GraphQLList(item),
                args={"limit": GraphQLArgument(limit_type)},
                resolve=resolve_items,
            ),
            "status": GraphQLField(GraphQLString, resolve=lambda *_: "ok"),
        },
    )
    return GraphQLSchema(query=query, types=[item, inner])


def _post(
    view: Any, query: str, variables: dict[str, Any], operation: str = "Probe"
) -> tuple[int, dict[str, Any]]:
    """Execute one real HTTP request with the selected operation and variables."""
    request = RequestFactory().post(
        "/graphql/",
        data=json.dumps(
            {"query": query, "variables": variables, "operationName": operation}
        ),
        content_type="application/json",
    )
    response = view(request)
    return response.status_code, json.loads(response.content)


_VARIABLE_QUERY = "query Probe($n: Int = 5) { items(limit: $n) { child { name } } }"
_LIMITS = {"MAX_QUERY_COST": 120, "MAX_PAGE_SIZE": None, "DEFAULT_PAGE_SIZE": 100}


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_high_variable_is_rejected_before_resolver_on_validation_cache_hits() -> None:
    """Reject a real limit of 150 after document validation is cached.

    A repeated request must not bypass the bound operation cost of 151.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))

    literal_status, literal_body = _post(
        view, "query Probe { items(limit: 150) { child { name } } }", {}
    )
    assert literal_status == 400
    assert literal_body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"

    with patch("django_graphex.views.validate", wraps=graphql_validate) as validate_spy:
        for _ in range(2):
            status, body = _post(view, _VARIABLE_QUERY, {"n": 150})
            assert status == 400
            assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
            assert "151" in body["errors"][0]["message"]
        assert validate_spy.call_count == 1
    assert resolved == []


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_small_and_declared_default_variables_remain_accepted() -> None:
    """Accept both cheap supplied and declared-default variables.

    The bound check must preserve normal resolver execution.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))
    for variables in ({"n": 5}, {}):
        status, body = _post(view, _VARIABLE_QUERY, variables)
        assert status == 200
        assert body["data"]["items"][0]["child"]["name"] == "one"
    assert resolved == [5, 5]


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_high_declared_default_is_checked_when_variable_is_omitted() -> None:
    """Reject an omitted variable with a high declared default.

    Native coercion supplies the default before the bound cost check.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))
    query = "query Probe($n: Int = 150) { items(limit: $n) { child { name } } }"
    status, body = _post(view, query, {})
    assert status == 400
    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert resolved == []


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": None, "MAX_PAGE_SIZE": None})
def test_no_cost_budget_remains_a_noop() -> None:
    """Leave large variables accepted when the cost budget is disabled.

    This preserves the existing optional nature of MAX_QUERY_COST.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))
    status, body = _post(view, _VARIABLE_QUERY, {"n": 150})
    assert status == 200
    assert body["data"]["items"]
    assert resolved == [150]


@override_settings(
    DJANGO_GRAPHEX={
        "MAX_QUERY_COST": 50,
        "MAX_PAGE_SIZE": None,
        "DEFAULT_PAGE_SIZE": 100,
    }
)
def test_static_fallback_still_rejects_a_small_bound_variable() -> None:
    """Keep the earlier conservative static validation rejection.

    A cheap bound value must not relax the existing document fallback.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))
    status, body = _post(view, _VARIABLE_QUERY, {"n": 5})
    assert status == 400
    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert resolved == []


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_only_selected_operation_is_bound_checked_and_invalid_input_keeps_its_error() -> (
    None
):
    """Check only the selected operation after native variable validation.

    Invalid input and an unknown operation retain their original errors.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))
    document = (
        "query Cheap { status } "
        "query Probe($n: Int) { items(limit: $n) { child { name } } }"
    )
    cheap_status, cheap_body = _post(view, document, {"n": 150}, "Cheap")
    assert cheap_status == 200
    assert cheap_body["data"]["status"] == "ok"

    high_status, high_body = _post(view, document, {"n": 150})
    assert high_status == 400
    assert high_body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"

    invalid_status, invalid_body = _post(view, document, {"n": "invalid"})
    assert invalid_status == 400
    assert "invalid" in invalid_body["errors"][0]["message"]
    assert (
        invalid_body["errors"][0].get("extensions", {}).get("code")
        != "QUERY_TOO_COMPLEX"
    )

    unknown_status, unknown_body = _post(view, document, {"n": 150}, "Missing")
    assert unknown_status == 400
    assert "Unknown operation" in unknown_body["errors"][0]["message"]
    assert resolved == []


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_unselected_operation_still_receives_static_validation() -> None:
    """Keep static document validation for an unselected operation.

    The new selected-operation check does not weaken that prior rule.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))
    document = (
        "query Cheap { status } "
        "query Expensive { items(limit: 150) { child { name } } }"
    )
    status, body = _post(view, document, {}, "Cheap")
    assert status == 400
    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert resolved == []


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_bound_skip_directive_controls_actual_cost() -> None:
    """Exclude an expensive selection when a bound skip directive omits it.

    Disabling the directive then rejects the same over-budget selection.
    """
    resolved: list[int] = []
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=_schema(resolved)))
    query = (
        "query Probe($n: Int, $skip: Boolean!) { "
        "items(limit: $n) @skip(if: $skip) { child { name } } status }"
    )
    skipped_status, skipped_body = _post(view, query, {"n": 150, "skip": True})
    assert skipped_status == 200
    assert skipped_body["data"] == {"status": "ok"}
    high_status, high_body = _post(view, query, {"n": 150, "skip": False})
    assert high_status == 400
    assert high_body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert resolved == []


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_custom_scalar_and_executor_build_once_before_cost_refusal() -> None:
    """Run custom scalar coercion and configured executor construction once.

    The over-budget refusal must not call the resolver.
    """
    coerced: list[Any] = []
    built: list[str] = []
    resolved: list[int] = []

    def parse_value(value: Any) -> int:
        coerced.append(value)
        return int(value)

    scalar = GraphQLScalarType(
        "CostInt",
        serialize=int,
        parse_value=parse_value,
        parse_literal=lambda node, _variables=None: (
            int(node.value) if isinstance(node, IntValueNode) else None
        ),
    )

    class RecordingExecutor(graphql_execution.Executor):
        @classmethod
        def build(cls, *args: Any, **kwargs: Any) -> Any:
            built.append("built")
            return super().build(*args, **kwargs)

    view = GraphQLView.as_view(
        schema=SimpleNamespace(graphql_schema=_schema(resolved, scalar)),
        executor_class=RecordingExecutor,
    )
    status, body = _post(
        view,
        "query Probe($n: CostInt) { items(limit: $n) { child { name } } }",
        {"n": 150},
    )
    assert status == 400
    assert body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert coerced == [150]
    assert built == ["built"]
    assert resolved == []


@override_settings(DJANGO_GRAPHEX=_LIMITS)
def test_input_default_factories_are_not_recoerced_for_bound_cost() -> None:
    """Avoid recoercing hand-authored and model-derived input defaults.

    The hand-authored factory runs once; model-derived omission stays absent.
    """
    calls: list[str] = []
    resolved: list[dict[str, Any]] = []

    def hand_default() -> str:
        calls.append("hand")
        return "generated"

    def model_default() -> str:
        calls.append("model")
        return "model-generated"

    class HandInput(InputType):
        token: str = Field(default_factory=hand_default)

    class ModelInput(BaseModel):
        token: str = Field(default_factory=model_default)

    hand_type = compile_input_type(HandInput, name="CostHandFactoryInput")
    model_type = compile_input_type(ModelInput, name="CostModelFactoryInput")
    inner = GraphQLObjectType("FactoryCostInner", {"name": GraphQLField(GraphQLString)})
    item = GraphQLObjectType("FactoryCostItem", {"child": GraphQLField(inner)})

    def resolve_items(_root: Any, _info: Any, **inputs: Any) -> list[Any]:
        resolved.append(inputs)
        return [{"child": {"name": "one"}}]

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "FactoryCostQuery",
            {
                "items": GraphQLField(
                    GraphQLList(item),
                    args={
                        "limit": GraphQLArgument(GraphQLInt),
                        "hand": GraphQLArgument(hand_type),
                        "model": GraphQLArgument(model_type),
                    },
                    resolve=resolve_items,
                )
            },
        )
    )
    view = GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=schema))
    query = (
        "query Probe($n: Int, $hand: CostHandFactoryInput, "
        "$model: CostModelFactoryInput) { "
        "items(limit: $n, hand: $hand, model: $model) { child { name } } }"
    )
    assert calls == []

    high_status, high_body = _post(view, query, {"n": 150, "hand": {}, "model": {}})
    assert high_status == 400
    assert high_body["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert calls == ["hand"]
    assert resolved == []

    low_status, low_body = _post(view, query, {"n": 5, "hand": {}, "model": {}})
    assert low_status == 200
    assert low_body["data"]["items"][0]["child"]["name"] == "one"
    assert calls == ["hand", "hand"]
    assert resolved[0]["hand"] == {"token": "generated"}
    assert resolved[0]["model"] == {}
