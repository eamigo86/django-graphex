"""Malformed request shapes are clean 400s; server faults answer HTTP 500."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import RequestFactory, override_settings
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

from django_graphex.views import BaseGraphQLView, GraphQLView

_QUERY = GraphQLObjectType(
    "Query", {"a": GraphQLField(GraphQLString, resolve=lambda *args, **kw: "ok")}
)
_SCHEMA = SimpleNamespace(graphql_schema=GraphQLSchema(query=_QUERY))
_VIEWS = (BaseGraphQLView, GraphQLView)


def _request(method: str, body: Any = None, **extra: Any) -> Any:
    """Build one GraphQL request.

    Args:
        method: The HTTP method.
        body: A JSON-serializable body, or None for no body.
        **extra: Extra keyword arguments for the request factory.

    Returns:
        The request.
    """
    factory = RequestFactory()
    if body is None:
        request = getattr(factory, method)("/graphql/", **extra)
    else:
        request = getattr(factory, method)(
            "/graphql/", json.dumps(body), content_type="application/json", **extra
        )
    request.user = SimpleNamespace(is_authenticated=False, pk=None, is_active=False)
    return request


_BAD_SHAPES = (
    ({"query": 123}, "Must provide query string."),
    ({"query": ["{ a }"]}, "Must provide query string."),
    ({"query": {"a": 1}}, "Must provide query string."),
    ({"query": "{ a }", "variables": "[1]"}, "Variables must be a JSON object."),
    ({"query": "{ a }", "variables": [1]}, "Variables must be a JSON object."),
    ({"query": "{ a }", "variables": 5}, "Variables must be a JSON object."),
)


@pytest.mark.parametrize("view_class", _VIEWS)
@pytest.mark.parametrize(("body", "message"), _BAD_SHAPES)
@override_settings(DEBUG=False)
def test_malformed_post_is_a_clean_400(
    view_class: type[BaseGraphQLView],
    body: dict[str, Any],
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A JSON body of the wrong shape answers 400 and writes no ERROR log.

    Args:
        view_class: The view under test.
        body: The malformed request body.
        message: The expected client message.
        caplog: The log capture fixture.
    """
    caplog.set_level(logging.DEBUG)
    response = view_class.as_view(schema=_SCHEMA)(_request("post", body))

    assert response.status_code == 400
    assert message in response.content.decode()
    assert "errorId" not in response.content.decode()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("view_class", _VIEWS)
@override_settings(DEBUG=False)
def test_non_object_variables_in_get_and_form_are_clean_400s(
    view_class: type[BaseGraphQLView], caplog: pytest.LogCaptureFixture
) -> None:
    """A query-string or form "variables" that decodes to a list answers 400.

    Args:
        view_class: The view under test.
        caplog: The log capture fixture.
    """
    caplog.set_level(logging.DEBUG)
    view = view_class.as_view(schema=_SCHEMA)
    get = _request("get", None, data={"query": "{ a }", "variables": "[1]"})
    form = _request(
        "post",
        None,
        data={"query": "{ a }", "variables": "[1]"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert view(get).status_code == 400
    assert view(form).status_code == 400
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("view_class", _VIEWS)
@override_settings(DEBUG=False)
def test_malformed_batch_item_answers_400_for_that_item_only(
    view_class: type[BaseGraphQLView], caplog: pytest.LogCaptureFixture
) -> None:
    """A batch item with a non-string query fails alone, with no ERROR log.

    Args:
        view_class: The view under test.
        caplog: The log capture fixture.
    """
    caplog.set_level(logging.DEBUG)
    body = [{"query": 123}, {"query": "{ a }"}]
    response = view_class.as_view(schema=_SCHEMA, batch=True)(_request("post", body))
    first, second = json.loads(response.content)

    assert first["status"] == 400
    assert "Must provide query string." in json.dumps(first)
    assert second["data"] == {"a": "ok"}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("view_class", _VIEWS)
def test_valid_requests_are_unchanged(view_class: type[BaseGraphQLView]) -> None:
    """Absent, empty and object variables keep working.

    Args:
        view_class: The view under test.
    """
    view = view_class.as_view(schema=_SCHEMA)
    for variables in (None, {}, "", '{"x": 1}'):
        body: dict[str, Any] = {"query": "{ a }"}
        if variables is not None:
            body["variables"] = variables
        response = view(_request("post", body))
        assert response.status_code == 200, variables


@pytest.mark.parametrize("view_class", _VIEWS)
def test_client_errors_and_field_errors_keep_their_status(
    view_class: type[BaseGraphQLView],
) -> None:
    """Syntax errors stay 400 and a field error stays inside an HTTP 200.

    Args:
        view_class: The view under test.
    """
    view = view_class.as_view(schema=_SCHEMA)

    assert view(_request("post", {"query": "{ a "})).status_code == 400
    assert view(_request("post", {"query": "{ nope }"})).status_code == 400
    assert view(_request("post", {"query": "{ a }"})).status_code == 200
