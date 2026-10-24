"""Public JSON-list variable omission contract through the native schema compiler."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import RequestFactory
from graphql import (
    GraphQLArgument,
    GraphQLInt,
    GraphQLList,
    GraphQLString,
    Undefined,
    graphql_sync,
)
from graphql.language.ast import NameNode, VariableNode

from django_graphex.core import ObjectType, field
from django_graphex.core.scalars import GdxJSON, GdxJSONString
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView


def _resolve_payload(root: Any, info: Any, payload: Any) -> Any:
    """Return the parsed input without altering its JSON shape.

    Args:
        root: Unused root value.
        info: Unused GraphQL resolver context.
        payload: Parsed GraphQL argument.

    Returns:
        The parsed argument unchanged.
    """
    return payload


def _resolve_presence(root: Any, info: Any, **kwargs: Any) -> str:
    """Expose whether GraphQL supplied the optional argument.

    Args:
        root: Unused root value.
        info: Unused GraphQL resolver context.
        **kwargs: GraphQL arguments supplied to the field.

    Returns:
        Whether the payload argument is present.
    """
    return "present" if "payload" in kwargs else "absent"


class _Query(ObjectType):
    """Expose a raw JSON argument unchanged through a compiled field."""

    echo = field(
        GdxJSON,
        args={"payload": GraphQLArgument(GdxJSON)},
        resolver=_resolve_payload,
    )
    typed = field(
        GraphQLList(GraphQLInt),
        args={"payload": GraphQLArgument(GraphQLList(GraphQLInt))},
        resolver=_resolve_payload,
    )
    presence = field(
        GraphQLString,
        args={"payload": GraphQLArgument(GdxJSON)},
        resolver=_resolve_presence,
    )


_SCHEMA = DjangoGraphQLSchema(query=_Query)


def _execute_wire(
    query: str, variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute through the public compiler and strict JSON wire encoding.

    Args:
        query: GraphQL document to execute.
        variables: Supplied GraphQL variables, if any.

    Returns:
        Decoded GraphQL wire response.
    """
    result = graphql_sync(_SCHEMA.graphql_schema, query, variable_values=variables)
    assert result.errors is None
    return json.loads(json.dumps(result.formatted, allow_nan=False))


def test_omitted_variable_keeps_null_slot_on_json_wire() -> None:
    """An absent variable in an inline JSON list retains a null wire slot.

    Scenario: omitted variable keeps null slot on json wire.
    """
    assert _SCHEMA.graphql_schema.query_type.fields["echo"].type is GdxJSON
    assert _execute_wire(
        "query($value: JSON) { echo(payload: [1, $value, 3]) }",
        {},
    ) == {"data": {"echo": [1, None, 3]}}


def test_nested_lists_preserve_slots_while_object_keys_stay_omitted() -> None:
    """Missing variables become list nulls but never materialize object keys.

    Scenario: nested lists preserve slots while object keys stay omitted.
    """
    assert _execute_wire(
        "query($value: JSON) { echo(payload: "
        "{items: [0, [$value, 2], {hidden: $value, kept: false}], "
        "hidden: $value, tail: []}) }",
        {},
    ) == {
        "data": {
            "echo": {
                "items": [0, [None, 2], {"kept": False}],
                "tail": [],
            }
        }
    }


@pytest.mark.parametrize("value", [0, False, "", [], {}, [4], {"x": 1}])
def test_supplied_json_variable_values_keep_their_shape(value: Any) -> None:
    """Defined falsy and structured values remain defined, not missing.

    Args:
        value: Value supplied by the parametrized case.
    """
    assert _execute_wire(
        "query($value: JSON) { echo(payload: [1, $value, 3]) }",
        {"value": value},
    ) == {"data": {"echo": [1, value, 3]}}


def test_defaulted_and_explicit_null_variables_remain_distinct() -> None:
    """A default is used, while explicit null retains a null slot.

    Scenario: defaulted and explicit null variables remain distinct.
    """
    query = "query($value: JSON = 7) { echo(payload: [1, $value, 3]) }"
    assert _execute_wire(query, {}) == {"data": {"echo": [1, 7, 3]}}
    assert _execute_wire(query, {"value": None}) == {"data": {"echo": [1, None, 3]}}
    assert _execute_wire("{ echo(payload: [1, null, 3]) }") == {
        "data": {"echo": [1, None, 3]}
    }


def test_ordinary_typed_list_and_direct_missing_argument_stay_unchanged() -> None:
    """Typed-list null slots and absent top-level arguments retain their behavior.

    Scenario: ordinary typed list and direct missing argument stay unchanged.
    """
    assert _execute_wire(
        "query($value: Int) { typed(payload: [1, $value, 3]) }",
        {},
    ) == {"data": {"typed": [1, None, 3]}}
    assert _execute_wire(
        "query($value: JSON) { presence(payload: $value) }",
        {},
    ) == {"data": {"presence": "absent"}}
    assert (
        GdxJSON.parse_literal(VariableNode(name=NameNode(value="value")), {})
        is Undefined
    )


def test_http_view_emits_json_null_without_undefined_sentinel() -> None:
    """The public HTTP view encodes the missing list member as strict JSON.

    Scenario: http view emits json null without undefined sentinel.
    """
    query = "query($value: JSON) { echo(payload: [1, $value, 3]) }"
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": query, "variables": {}}),
        content_type="application/json",
    )
    response = GraphQLView.as_view(schema=_SCHEMA)(request)
    assert response.status_code == 200
    assert json.loads(response.content) == {"data": {"echo": [1, None, 3]}}


def test_json_string_scalar_is_not_reinterpreted() -> None:
    """The separate JSONString scalar keeps its prior string-decoding contract.

    Scenario: json string scalar is not reinterpreted.
    """
    assert GdxJSONString.parse_value('"plain"') == "plain"
    assert GdxJSONString.parse_value('{"x": 1}') == {"x": 1}
