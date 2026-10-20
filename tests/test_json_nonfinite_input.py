"""Raw JSON input rejects non-finite numbers before resolver execution."""

from __future__ import annotations

import json
from math import isinf
from typing import Any

import pytest
from django.test import RequestFactory
from graphql import (
    GraphQLArgument,
    GraphQLError,
    GraphQLString,
    Undefined,
    graphql_sync,
)
from graphql.language.ast import NameNode, VariableNode

from django_graphex.core import ObjectType, field
from django_graphex.core.scalars import GdxJSON, GdxJSONString
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

_CALLS: list[Any] = []


def _resolve_echo(root: Any, info: Any, payload: Any) -> Any:
    """Record and return an input reaching the public field resolver.

    Args:
        root: Unused root value.
        info: Unused GraphQL resolver context.
        payload: Parsed raw JSON argument.

    Returns:
        The parsed argument without conversion.
    """
    _CALLS.append(payload)
    return payload


def _resolve_presence(root: Any, info: Any, **kwargs: Any) -> str:
    """Report whether the optional argument was actually supplied.

    Args:
        root: Unused root value.
        info: Unused GraphQL resolver context.
        **kwargs: Supplied GraphQL arguments.

    Returns:
        A marker for argument presence.
    """
    return "present" if "payload" in kwargs else "absent"


class _Query(ObjectType):
    """Expose a raw JSON input through the native schema compiler."""

    echo = field(
        GdxJSON,
        args={"payload": GraphQLArgument(GdxJSON)},
        resolver=_resolve_echo,
    )
    presence = field(
        GraphQLString,
        args={"payload": GraphQLArgument(GdxJSON)},
        resolver=_resolve_presence,
    )


_SCHEMA = DjangoGraphQLSchema(query=_Query)


def test_literal_overflow_rejected_before_resolver() -> None:
    """A finite-looking exponent must not become an accepted infinity."""
    _CALLS.clear()
    result = graphql_sync(_SCHEMA.graphql_schema, "{ echo(payload: 1e999) }")
    assert result.errors is not None
    assert "JSON cannot represent non-finite numbers" in result.errors[0].message
    assert _CALLS == []


def test_nested_variable_infinity_rejected_before_resolver() -> None:
    """Nested non-finite variable values must fail input coercion."""
    _CALLS.clear()
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "query($payload: JSON) { echo(payload: $payload) }",
        variable_values={"payload": {"items": [1, float("inf")]}},
    )
    assert result.errors is not None
    assert "JSON cannot represent non-finite numbers" in result.errors[0].message
    assert _CALLS == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize(
    "wrap",
    [lambda value: value, lambda value: [value], lambda value: {"nested": [value]}],
)
def test_variable_nonfinite_values_fail_before_resolver(
    value: float, wrap: Any
) -> None:
    """Direct and nested variable non-finite floats fail input coercion.

    Args:
        value: Non-finite numeric value.
        wrap: Shape builder for the raw JSON variable.
    """
    _CALLS.clear()
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "query($payload: JSON) { echo(payload: $payload) }",
        variable_values={"payload": wrap(value)},
    )
    assert result.errors is not None
    assert "JSON cannot represent non-finite numbers" in result.errors[0].message
    assert _CALLS == []


@pytest.mark.parametrize(
    "literal",
    ["1e999", "[1, 1e999]", "{nested: [1e999]}", "[1e999, 2]"],
)
def test_overflow_literal_shapes_fail_before_resolver(literal: str) -> None:
    """A parsed non-finite float cannot reach the resolver at any depth.

    Args:
        literal: Inline raw JSON literal containing an overflowing float.
    """
    _CALLS.clear()
    result = graphql_sync(_SCHEMA.graphql_schema, f"{{ echo(payload: {literal}) }}")
    assert result.errors is not None
    assert "JSON cannot represent non-finite numbers" in result.errors[0].message
    assert _CALLS == []


def test_nonfinite_default_literal_rejected() -> None:
    """An overflowing variable default is rejected during input validation."""
    _CALLS.clear()
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "query($payload: JSON = 1e999) { echo(payload: $payload) }",
        variable_values={},
    )
    assert result.errors is not None
    assert "JSON cannot represent non-finite numbers" in result.errors[0].message
    assert _CALLS == []


def test_available_variable_literal_path_rejects_nonfinite() -> None:
    """Direct literal coercion cannot bypass the raw input check."""
    node = VariableNode(name=NameNode(value="value"))
    with pytest.raises(GraphQLError, match="JSON cannot represent non-finite numbers"):
        GdxJSON.parse_literal(node, {"value": {"nested": [float("nan")]}})


def test_finite_and_string_values_keep_identity_and_wire_shape() -> None:
    """Finite numbers, falsy values, and numeric strings remain unchanged."""
    payload = {
        "items": [0, False, None, "", 1e308, "NaN", "Infinity"],
        "empty": [],
    }
    assert GdxJSON.parse_value(payload) is payload
    _CALLS.clear()
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "query($payload: JSON) { echo(payload: $payload) }",
        variable_values={"payload": payload},
    )
    assert result.errors is None
    assert json.loads(json.dumps(result.formatted, allow_nan=False)) == {
        "data": {"echo": payload}
    }
    assert _CALLS == [payload]
    assert _CALLS[0] is payload


def test_huge_finite_int_and_native_container_aliases_are_not_rewritten() -> None:
    """Input inspection neither converts integers nor copies native containers."""
    huge_int = 10**400
    shared = [huge_int, 1.25]
    payload = {"first": shared, "second": shared}
    assert GdxJSON.parse_value(huge_int) is huge_int
    assert GdxJSON.parse_value(payload) is payload
    assert payload["first"] is payload["second"]
    cycle: list[Any] = []
    cycle.append(cycle)
    assert GdxJSON.parse_value(cycle) is cycle


def test_defaults_missing_members_and_explicit_null_keep_their_contract() -> None:
    """Finite defaults, omitted object keys and list null slots persist."""
    _CALLS.clear()
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "query($value: JSON = 3.5) { echo(payload: [1, $value, null]) }",
        variable_values={},
    )
    assert result.errors is None
    assert result.data == {"echo": [1, 3.5, None]}
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "query($value: JSON) { echo(payload: {hidden: $value, list: [1, $value]}) }",
        variable_values={},
    )
    assert result.errors is None
    assert result.data == {"echo": {"list": [1, None]}}
    result = graphql_sync(
        _SCHEMA.graphql_schema,
        "query($value: JSON) { presence(payload: $value) }",
        variable_values={},
    )
    assert result.errors is None
    assert result.data == {"presence": "absent"}
    assert (
        GdxJSON.parse_literal(VariableNode(name=NameNode(value="value")), {})
        is Undefined
    )


def test_http_input_error_uses_graphql_error_wire() -> None:
    """The public HTTP view rejects non-finite input without invoking a resolver."""
    _CALLS.clear()
    request = RequestFactory().post(
        "/graphql/",
        json.dumps(
            {
                "query": "query($payload: JSON) { echo(payload: $payload) }",
                "variables": {"payload": {"bad": float("inf")}},
            }
        ),
        content_type="application/json",
    )
    response = GraphQLView.as_view(schema=_SCHEMA)(request)
    body = json.loads(response.content)
    assert body["errors"]
    assert "JSON cannot represent non-finite numbers" in body["errors"][0]["message"]
    assert _CALLS == []


def test_raw_output_and_json_string_scalar_remain_separate() -> None:
    """Input-only rejection does not alter output or JSONString coercion."""
    value = float("inf")
    assert GdxJSON.serialize(value) is value
    assert isinf(GdxJSONString.parse_value("1e999"))
