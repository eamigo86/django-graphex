"""Public HTTP distinction between GraphQL execution and request errors."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from django.core.cache import caches
from django.test import RequestFactory, override_settings
from graphql import GraphQLError, GraphQLNonNull, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import BaseGraphQLView, GraphQLView


def _schema(calls: list[str]) -> DjangoGraphQLSchema:
    """Build a public schema with non-null and nullable resolver failures.

    Args:
        calls: Resolver invocation log.

    Returns:
        The schema exercised by the HTTP views.
    """

    def fail(root: Any, info: Any) -> str:
        calls.append("required")
        raise GraphQLError("Execution stopped.", extensions={"code": "EXAMPLE_FAILURE"})

    def optional_fail(root: Any, info: Any) -> str:
        calls.append("optional")
        raise GraphQLError("Optional field failed.")

    def resolve_healthy(root: Any, info: Any) -> str:
        calls.append("healthy")
        return "ready"

    class Query(ObjectType):
        required = field(GraphQLNonNull(GraphQLString), resolver=fail)
        optional = field(GraphQLString, resolver=optional_fail)
        healthy = field(GraphQLString, resolver=resolve_healthy)

    return DjangoGraphQLSchema(query=Query)


def _post(
    schema: DjangoGraphQLSchema,
    body: dict[str, Any] | list[dict[str, Any]],
    *,
    batch: bool = False,
    content_type: str = "application/json",
) -> tuple[int, Any]:
    """Send a real HTTP request through the enhanced view.

    Args:
        schema: Schema used for validation and execution.
        body: GraphQL request body.
        batch: Whether the view accepts a list of operations.
        content_type: Request encoding.

    Returns:
        The HTTP status and decoded response envelope.
    """
    request_factory = RequestFactory()
    if content_type == "application/json":
        request = request_factory.post(
            "/graphql/", data=json.dumps(body), content_type=content_type
        )
    else:
        request = request_factory.post(
            "/graphql/", data=body, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
    response = GraphQLView.as_view(schema=schema, batch=batch)(request)
    return response.status_code, json.loads(response.content)


def test_nonnull_root_execution_error_has_null_data_in_both_views() -> None:
    """A failed non-null root executes before returning its null data envelope.

    Raises:
        GraphQLError: Raised by the root resolver to fail the non-null root field.
    """
    calls: list[str] = []

    def fail(root: Any, info: Any) -> str:
        calls.append("resolver")
        raise GraphQLError("Execution stopped.", extensions={"code": "EXAMPLE_FAILURE"})

    class Query(ObjectType):
        required = field(GraphQLNonNull(GraphQLString), resolver=fail)

    schema = DjangoGraphQLSchema(query=Query)
    request_factory = RequestFactory()
    for view_class in (BaseGraphQLView, GraphQLView):
        request = request_factory.post(
            "/graphql/",
            data=json.dumps({"query": "{ required }"}),
            content_type="application/json",
        )
        response = view_class.as_view(schema=schema)(request)
        payload = json.loads(response.content)
        assert response.status_code == 200
        assert payload["data"] is None
        assert len(payload["errors"]) == 1
        assert payload["errors"][0]["message"] == "Execution stopped."
        assert payload["errors"][0]["path"] == ["required"]
        assert payload["errors"][0]["extensions"]["code"] == "EXAMPLE_FAILURE"
    assert calls == ["resolver", "resolver"]


@pytest.mark.parametrize("clean_response", [False, True])
def test_null_execution_envelope_survives_cleaning_and_production_formatting(
    clean_response: bool,
) -> None:
    """Keep the deliberate error code and null data with DEBUG disabled.

    Args:
        clean_response: Whether response cleaning is enabled.
    """
    calls: list[str] = []
    with override_settings(
        DEBUG=False,
        DJANGO_GRAPHEX={"CLEAN_RESPONSE": clean_response, "EXPOSE_QUERY_COST": True},
    ):
        status, payload = _post(_schema(calls), {"query": "{ required }"})
    assert status == 200
    assert payload["data"] is None
    assert payload["errors"][0]["path"] == ["required"]
    assert payload["errors"][0]["extensions"]["code"] == "EXAMPLE_FAILURE"
    assert "cost" not in payload.get("extensions", {})
    assert calls == ["required"]


@pytest.mark.parametrize(
    "body",
    [
        {"query": "{ required"},
        {"query": "{ unknownField }"},
        {
            "query": "query($name: String!) { __type(name: $name) { name } }",
            "variables": {"name": 1},
        },
    ],
)
def test_request_errors_stay_http_400_without_data(body: dict[str, Any]) -> None:
    """Distinguish parsing, validation, and variable-coercion failures.

    Args:
        body: Invalid public GraphQL request.
    """
    calls: list[str] = []
    status, payload = _post(_schema(calls), body)
    assert status == 400
    assert "data" not in payload
    assert payload["errors"]
    assert calls == []


def test_nullable_error_and_success_keep_existing_data_and_cost() -> None:
    """Keep HTTP 200 partial data and successful responses unchanged.

    Scenario: nullable error and success keep existing data and cost.
    """
    calls: list[str] = []
    schema = _schema(calls)
    with override_settings(DJANGO_GRAPHEX={"EXPOSE_QUERY_COST": True}):
        partial_status, partial = _post(schema, {"query": "{ healthy optional }"})
        success_status, success = _post(schema, {"query": "{ healthy }"})
    assert partial_status == success_status == 200
    assert partial["data"] == {"healthy": "ready", "optional": None}
    assert partial["errors"][0]["path"] == ["optional"]
    assert "cost" in partial["extensions"]
    assert success["data"] == {"healthy": "ready"}
    assert "errors" not in success
    assert "cost" in success["extensions"]
    assert calls == ["healthy", "optional", "healthy"]


def test_null_execution_errors_are_not_cached_or_replayed() -> None:
    """Execute each HTTP 200 error request without storing a response entry.

    Scenario: null execution errors are not cached or replayed.
    """
    calls: list[str] = []
    cache_config = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "lc3-null-execution-error",
        }
    }
    with override_settings(
        CACHES=cache_config,
        DJANGO_GRAPHEX={"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60},
    ):
        backend = caches["default"]
        with patch.object(backend, "set", wraps=backend.set) as set_mock:
            first = _post(_schema(calls), {"query": "{ required }"})
            second = _post(_schema(calls), {"query": "{ required }"})
        response_writes = [
            call
            for call in set_mock.call_args_list
            if isinstance(call.args[0], str) and call.args[0].startswith("_graphql_v2_")
        ]
    assert first[0] == second[0] == 200
    assert first[1]["data"] is second[1]["data"] is None
    assert first[1]["errors"] and second[1]["errors"]
    assert response_writes == []
    assert calls == ["required", "required"]


def test_batch_execution_error_continues_and_validation_error_remains_scoped() -> None:
    """Return one null execution entry and keep ordinary validation entries.

    Scenario: batch execution error continues and validation error remains scoped.
    """
    calls: list[str] = []
    status, payload = _post(
        _schema(calls),
        [
            {"id": "failed", "query": "{ required }"},
            {"id": "invalid", "query": "{ unknownField }"},
            {"id": "next", "query": "{ healthy }"},
        ],
        batch=True,
    )
    assert status == 400
    assert [(entry["id"], entry["status"]) for entry in payload] == [
        ("failed", 200),
        ("invalid", 400),
        ("next", 200),
    ]
    assert payload[0]["data"] is None and payload[0]["errors"]
    assert "data" not in payload[1] and payload[1]["errors"]
    assert payload[2]["data"] == {"healthy": "ready"}
    assert calls == ["required", "healthy"]


def test_multipart_form_uses_same_execution_envelope() -> None:
    """Keep ordinary multipart form handling on the common response path.

    Scenario: multipart form uses same execution envelope.
    """
    calls: list[str] = []
    status, payload = _post(
        _schema(calls), {"query": "{ required }"}, content_type="multipart/form-data"
    )
    assert status == 200
    assert payload["data"] is None and payload["errors"]
    assert calls == ["required"]
