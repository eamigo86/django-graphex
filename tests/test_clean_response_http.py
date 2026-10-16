"""HTTP response-cleaning contract for meaningful falsy GraphQL values."""

from __future__ import annotations

import json
from typing import Any

from django.test import RequestFactory, override_settings
from graphql import (
    GraphQLBoolean,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLString,
)

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

_CHILD = GraphQLObjectType(
    "CleanResponseChild",
    {
        "count": GraphQLField(GraphQLInt),
        "enabled": GraphQLField(GraphQLBoolean),
        "blank": GraphQLField(GraphQLString),
    },
)


class _Query(ObjectType):
    """Expose falsy scalar and container responses through the real HTTP view."""

    count = field(GraphQLInt, resolver=lambda root, info: 0)
    enabled = field(GraphQLBoolean, resolver=lambda root, info: False)
    negative = field(GraphQLInt, resolver=lambda root, info: -2)
    zero_text = field(GraphQLString, resolver=lambda root, info: "0")
    blank = field(GraphQLString, resolver=lambda root, info: "")
    missing = field(GraphQLString, resolver=lambda root, info: None)
    values = field(GraphQLList(GraphQLInt), resolver=lambda root, info: [None, 0, 2])
    children = field(
        GraphQLList(_CHILD),
        resolver=lambda root, info: [
            {"count": 0, "enabled": False, "blank": ""},
            {"count": None, "enabled": None, "blank": ""},
        ],
    )
    empty = field(GraphQLList(GraphQLInt), resolver=lambda root, info: [])


_SCHEMA = DjangoGraphQLSchema(query=_Query)
_FIELDS = "count enabled negative zeroText blank missing values children { count enabled blank } empty"


def _post(query: str, operation_name: str | None = None) -> dict[str, Any]:
    """Execute a JSON POST through GraphQLView and return its decoded payload.

    Args:
        query: The GraphQL document to execute.
        operation_name: Selected operation in a multi-operation document.

    Returns:
        The decoded HTTP JSON response.
    """
    body: dict[str, Any] = {"query": query}
    if operation_name is not None:
        body["operationName"] = operation_name
    request = RequestFactory().post(
        "/graphql/", json.dumps(body), content_type="application/json"
    )
    response = GraphQLView.as_view(schema=_SCHEMA)(request)
    assert response.status_code == 200
    return json.loads(response.content)


@override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
def test_clean_response_keeps_zero_false_and_nonempty_values() -> None:
    """Retain zero and false at root, list, and nested levels.

    Retained array elements keep their original relative order.
    """
    payload = _post("{ " + _FIELDS + " }")
    assert payload["data"] == {
        "count": 0,
        "enabled": False,
        "negative": -2,
        "zeroText": "0",
        "values": [0, 2],
        "children": [{"count": 0, "enabled": False}],
    }


@override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": False})
def test_disabled_cleaning_leaves_the_full_payload_unchanged() -> None:
    """Preserve the full response when cleaning is disabled.

    Null, blank, and empty-container values remain in their original positions.
    """
    payload = _post("{ " + _FIELDS + " }")
    assert payload["data"] == {
        "count": 0,
        "enabled": False,
        "negative": -2,
        "zeroText": "0",
        "blank": "",
        "missing": None,
        "values": [None, 0, 2],
        "children": [
            {"count": 0, "enabled": False, "blank": ""},
            {"count": None, "enabled": None, "blank": ""},
        ],
        "empty": [],
    }


@override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
def test_selected_operation_controls_introspection_cleaning() -> None:
    """Follow the selected operation when deciding whether to clean.

    Introspection keeps null and empty-list fields; the normal operation is cleaned.
    """
    query = (
        'query Intro { __type(name: "_Query") { name description interfaces { name } } } '
        "query Normal { count enabled missing }"
    )
    intro = _post(query, "Intro")
    assert intro["data"]["__type"]["description"] is None
    assert intro["data"]["__type"]["interfaces"] == []
    normal = _post(query, "Normal")
    assert normal["data"] == {"count": 0, "enabled": False}
