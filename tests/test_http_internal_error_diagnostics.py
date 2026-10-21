"""Production HTTP diagnostics for unexpected GraphQL execution failures."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import DatabaseError
from django.test import RequestFactory, override_settings
from graphql import GraphQLError, GraphQLNonNull, GraphQLString

from django_graphex import views as views_module
from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.security import format_graphql_error
from django_graphex.views import AuthenticatedGraphQLView, BaseGraphQLView, GraphQLView


def _raise_failure(root: Any, info: Any) -> str:
    """Raise the request-local failure so one schema exercises every view."""
    raise info.context.test_failure


class _Query(ObjectType):
    """Expose a nullable field and a healthy sibling for response-shape checks."""

    failure = field(GraphQLString, resolver=_raise_failure)
    required_failure = field(GraphQLNonNull(GraphQLString), resolver=_raise_failure)
    healthy = field(GraphQLString, resolver=lambda root, info: "healthy")


_SCHEMA = DjangoGraphQLSchema(query=_Query)


def _post(view_class: type[BaseGraphQLView], failure: Exception, query: str) -> Any:
    """Execute an actual HTTP request with a request-local resolver failure."""
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": query}),
        content_type="application/json",
        HTTP_X_PRIVATE_HEADER="request-secret",
    )
    request.test_failure = failure
    request.user = SimpleNamespace(is_authenticated=True, pk=7, is_active=True)
    return view_class.as_view(schema=_SCHEMA)(request)


@pytest.mark.parametrize(
    "view_class", (BaseGraphQLView, GraphQLView, AuthenticatedGraphQLView)
)
@pytest.mark.parametrize(
    ("failure", "code", "message"),
    (
        (
            DatabaseError("private_table confidential-sql"),
            "DATA_ACCESS_ERROR",
            "Unable to complete the data operation.",
        ),
        (
            ValueError("private-business-detail"),
            "INTERNAL_SERVER_ERROR",
            "An internal error occurred.",
        ),
    ),
)
@override_settings(DEBUG=False)
def test_internal_failures_have_safe_http_diagnostics_and_correlated_logs(
    view_class: type[BaseGraphQLView],
    failure: Exception,
    code: str,
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retain GraphQL shape while logging the private exception by opaque ID.

    Args:
        view_class: Built-in HTTP view under test.
        failure: Exception raised by the resolver.
        code: Expected public category.
        message: Expected public message.
        caplog: Captured internal log records.
    """
    query = "query { healthy\n  failure }"
    with caplog.at_level(logging.ERROR, logger="django_graphex.internal_errors"):
        response = _post(view_class, failure, query)
    payload = json.loads(response.content)
    assert response.status_code == 200
    assert payload["data"] == {"healthy": "healthy", "failure": None}
    error = payload["errors"][0]
    assert error["message"] == message
    assert error["path"] == ["failure"]
    assert error["locations"] == [{"line": 2, "column": 3}]
    assert error["extensions"]["code"] == code
    error_id = error["extensions"]["errorId"]
    assert re.fullmatch(r"[0-9a-f]{32}", error_id)
    public = response.content.decode()
    assert "private" not in public
    assert "request-secret" not in public
    records = [record for record in caplog.records if error_id in record.getMessage()]
    assert len(records) == 1
    assert records[0].name == "django_graphex.internal_errors"
    assert code in records[0].getMessage()
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is failure
    assert "request-secret" not in records[0].getMessage()


@override_settings(DEBUG=False)
def test_ids_are_unique_and_wrapped_internal_extensions_are_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Never trust an internal wrapper's message or extension mapping.

    Args:
        caplog: Captured internal log records.
    """
    failure = GraphQLError(
        "wrapped private detail",
        extensions={"code": "PUBLIC_IMPOSTOR", "secret": "private-extension"},
        original_error=DatabaseError("private-db-error"),
    )
    with caplog.at_level(logging.ERROR, logger="django_graphex.internal_errors"):
        responses = [_post(BaseGraphQLView, failure, "{ failure }") for _ in range(2)]
    errors = [json.loads(response.content)["errors"][0] for response in responses]
    assert all(
        error["message"] == "Unable to complete the data operation." for error in errors
    )
    assert all(error["extensions"]["code"] == "DATA_ACCESS_ERROR" for error in errors)
    assert all(set(error["extensions"]) == {"code", "errorId"} for error in errors)
    ids = [error["extensions"]["errorId"] for error in errors]
    assert ids[0] != ids[1]
    assert all(
        sum(error_id in record.getMessage() for record in caplog.records) == 1
        for error_id in ids
    )


@override_settings(DEBUG=False)
def test_public_errors_validation_and_http_parse_errors_keep_their_contract() -> None:
    """Keep explicit GraphQLError and native errors out of internal handling.

    The validation and HTTP parser paths retain their existing statuses.
    """
    deliberate = GraphQLError("Public action required", extensions={"code": "ACTION"})
    response = _post(BaseGraphQLView, deliberate, "{ failure }")
    error = json.loads(response.content)["errors"][0]
    assert error["message"] == "Public action required"
    assert error["extensions"] == {"code": "ACTION"}
    invalid = _post(BaseGraphQLView, ValueError("unused"), "{ missingField }")
    invalid_error = json.loads(invalid.content)["errors"][0]
    assert invalid.status_code == 400
    assert "Cannot query field" in invalid_error["message"]
    assert "errorId" not in invalid_error.get("extensions", {})
    malformed = RequestFactory().post(
        "/graphql/", "not json", content_type="application/json"
    )
    parsed = BaseGraphQLView.as_view(schema=_SCHEMA)(malformed)
    assert parsed.status_code == 400
    assert "errorId" not in json.loads(parsed.content)["errors"][0].get(
        "extensions", {}
    )


@override_settings(DEBUG=True)
def test_debug_and_shared_transport_formatter_keep_existing_diagnostics() -> None:
    """Keep development and non-HTTP formatting unchanged.

    Neither path opts into production HTTP classification.
    """
    failure = GraphQLError(
        "private-debug-detail",
        extensions={"code": "DEBUG_CODE", "private": "debug-extension"},
        original_error=ValueError("private-underlying"),
    )
    response = _post(GraphQLView, failure, "{ failure }")
    error = json.loads(response.content)["errors"][0]
    assert error["message"] == "private-debug-detail"
    assert error["extensions"] == {"code": "DEBUG_CODE", "private": "debug-extension"}
    assert format_graphql_error(failure) == failure.formatted


@override_settings(DEBUG=False)
def test_shared_formatter_is_unchanged_in_production() -> None:
    """Leave the shared formatter unchanged in production.

    Subscription callers still own their existing formatting behavior.
    """
    failure = GraphQLError(
        "transport-private-detail", original_error=ValueError("transport-root")
    )
    assert format_graphql_error(failure) == failure.formatted


@pytest.mark.parametrize(
    "view_class",
    (BaseGraphQLView, GraphQLView, AuthenticatedGraphQLView),
)
@override_settings(DEBUG=False)
def test_nonnull_error_keeps_null_data_and_safe_message_in_every_view(
    view_class: type[BaseGraphQLView],
) -> None:
    """Keep null execution data while aligning each view's HTTP status.

    Args:
        view_class: Built-in HTTP view under test.
    """
    response = _post(view_class, ValueError("private"), "{ requiredFailure }")
    payload = json.loads(response.content)
    assert response.status_code == 200
    assert "data" in payload and payload["data"] is None
    assert payload["errors"][0]["path"] == ["requiredFailure"]
    assert payload["errors"][0]["message"] == "An internal error occurred."


@override_settings(DEBUG=False)
def test_logger_failure_cannot_change_safe_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the safe result if an application-supplied handler raises.

    Args:
        monkeypatch: Scoped patch for the internal logger.
    """

    def fail_log(*args: Any, **kwargs: Any) -> None:
        """Simulate a broken logging handler."""
        raise RuntimeError("logger is unavailable")

    monkeypatch.setattr(views_module._error_logger, "error", fail_log)
    response = _post(BaseGraphQLView, ValueError("private"), "{ failure }")
    error = json.loads(response.content)["errors"][0]
    assert response.status_code == 200
    assert error["message"] == "An internal error occurred."
    assert set(error["extensions"]) == {"code", "errorId"}


@override_settings(DEBUG=False)
def test_custom_view_formatter_remains_an_explicit_override() -> None:
    """Preserve an application's deliberate formatting override.

    The default HTTP policy cannot silently rewrite that override.
    """

    class CustomView(BaseGraphQLView):
        """Use an application-selected public formatting contract."""

        def format_error(self, error: Any, request: Any = None) -> dict[str, Any]:
            """Return the application's fixed public error shape."""
            return {"message": "Custom error", "extensions": {"code": "CUSTOM"}}

    response = _post(CustomView, ValueError("private"), "{ failure }")
    assert json.loads(response.content)["errors"] == [
        {"message": "Custom error", "extensions": {"code": "CUSTOM"}}
    ]


def test_production_error_documentation_example_matches_the_wire_contract() -> None:
    """Keep the published JSON example parseable and category-safe.

    The mutation guides must link to the same HTTP policy.
    """
    root = Path(__file__).resolve().parents[1]
    guide = (root / "docs/usage/views.md").read_text(encoding="utf-8")
    section = guide.split("### Production execution errors\n", 1)[1]
    example = json.loads(section.split("```json\n", 1)[1].split("\n```", 1)[0])
    error = example["errors"][0]
    assert error["message"] == "Unable to complete the data operation."
    assert error["extensions"]["code"] == "DATA_ACCESS_ERROR"
    assert re.fullmatch(r"[0-9a-f]{32}", error["extensions"]["errorId"])
    assert error["path"] == ["failure"]
    for related in ("docs/usage/mutations.md", "docs/api/mutations.md"):
        text = (root / related).read_text(encoding="utf-8")
        assert "views.md#production-execution-errors" in text
