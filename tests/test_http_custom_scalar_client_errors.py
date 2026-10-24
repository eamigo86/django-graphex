"""Custom scalar coercion failures are client errors, not internal ones."""

from __future__ import annotations

import json
import logging
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import RequestFactory, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.views import BaseGraphQLView, GraphQLView

_SECRET = "private-internal-detail"


def _parse_date(value: Any) -> date:
    """Parse an ISO date, raising ValueError like a typical custom scalar."""
    return date.fromisoformat(value)


def _explode(root: Any, info: Any, **kwargs: Any) -> str:
    """Raise a raw ValueError during execution."""
    raise ValueError(_SECRET)


_DATE = GraphQLScalarType(
    "MyDate",
    parse_value=_parse_date,
    parse_literal=lambda node, variables=None: _parse_date(node.value),
    serialize=str,
)
_FILTER = GraphQLInputObjectType("DateFilter", {"on": GraphQLInputField(_DATE)})
_QUERY = GraphQLObjectType(
    "Query",
    {
        "d": GraphQLField(
            GraphQLString,
            args={
                "on": GraphQLArgument(_DATE),
                "many": GraphQLArgument(GraphQLList(_DATE)),
                "f": GraphQLArgument(_FILTER),
            },
            resolve=lambda root, info, **kw: "ok",
        ),
        "boom": GraphQLField(GraphQLString, resolve=_explode),
    },
)
_SCHEMA = SimpleNamespace(graphql_schema=GraphQLSchema(query=_QUERY))

_BAD_LITERAL = '{ d(on: "garbage") }'
_CASES = (
    ({"query": _BAD_LITERAL}, "Expected value of type 'MyDate'"),
    (
        {"query": "query($v: MyDate) { d(on: $v) }", "variables": {"v": "garbage"}},
        "Variable '$v' has invalid value",
    ),
    (
        {
            "query": "query($v: [MyDate]) { d(many: $v) }",
            "variables": {"v": ["2024-01-01", "garbage"]},
        },
        "Variable '$v' has invalid value",
    ),
    (
        {
            "query": "query($v: DateFilter) { d(f: $v) }",
            "variables": {"v": {"on": "garbage"}},
        },
        "Variable '$v' has invalid value",
    ),
    ({"query": '{ d(f: {on: "garbage"}) }'}, "Expected value of type 'MyDate'"),
    ({"query": '{ d(many: ["garbage"]) }'}, "Expected value of type 'MyDate'"),
)


def _post(view_class: type[BaseGraphQLView], body: dict[str, Any]) -> Any:
    """Send one JSON request through the view."""
    request = RequestFactory().post(
        "/graphql/", json.dumps(body), content_type="application/json"
    )
    request.user = SimpleNamespace(is_authenticated=False, pk=None, is_active=False)
    return view_class.as_view(schema=_SCHEMA)(request)


@pytest.mark.parametrize("view_class", (BaseGraphQLView, GraphQLView))
@pytest.mark.parametrize(("body", "prefix"), _CASES)
@override_settings(DEBUG=False)
def test_production_scalar_failure_is_a_client_error_without_error_log(
    view_class: type[BaseGraphQLView],
    body: dict[str, Any],
    prefix: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A scalar ValueError is a 400 validation error with no internals or ERROR.

    Args:
        view_class: The view under test.
        body: The request body.
        prefix: The expected message prefix.
        caplog: The log capture fixture.
    """
    caplog.set_level(logging.DEBUG, logger="django_graphex.internal_errors")
    response = _post(view_class, body)
    payload = json.loads(response.content)

    assert response.status_code == 400
    (error,) = payload["errors"]
    assert error["message"].startswith(prefix)
    assert "internal error" not in error["message"]
    assert "extensions" not in error
    assert "Invalid isoformat" not in response.content.decode()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not [r for r in caplog.records if r.exc_info]


@pytest.mark.parametrize(("body", "prefix"), _CASES[:2])
@override_settings(DEBUG=True)
def test_debug_keeps_the_scalar_detail(body: dict[str, Any], prefix: str) -> None:
    """DEBUG keeps the full graphql-core message, including the cause text.

    Args:
        body: The request body.
        prefix: The expected message prefix (unused, shared parametrization).
    """
    response = _post(GraphQLView, body)
    (error,) = json.loads(response.content)["errors"]

    assert response.status_code == 400
    assert "Invalid isoformat" in error["message"]


@pytest.mark.parametrize("view_class", (BaseGraphQLView, GraphQLView))
@override_settings(DEBUG=False)
def test_execution_time_value_error_is_still_masked_and_logged(
    view_class: type[BaseGraphQLView], caplog: pytest.LogCaptureFixture
) -> None:
    """A ValueError raised by a resolver keeps the M-S4 mask and ERROR log.

    Args:
        view_class: The view under test.
        caplog: The log capture fixture.
    """
    caplog.set_level(logging.DEBUG, logger="django_graphex.internal_errors")
    response = _post(view_class, {"query": "{ boom }"})
    (error,) = json.loads(response.content)["errors"]

    assert response.status_code == 200
    assert error["message"] == "An internal error occurred."
    assert error["extensions"]["code"] == "INTERNAL_SERVER_ERROR"
    assert _SECRET not in response.content.decode()
    assert [r for r in caplog.records if r.levelno == logging.ERROR]
