"""Real HTTP regressions for bounded batch transport errors."""

from __future__ import annotations

import json
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from django.db import connection
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import path
from graphql import (
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.views import BaseGraphQLView, GraphQLView, HttpError
from tests.models import Author


class TrackingGraphQLView(GraphQLView):
    """Observe mutation-cache invalidation without replacing HTTP dispatch.

    Only the version-bump hook is instrumented; request handling stays real.
    """

    bumps: list[str] = []

    def _bump_cache_version(self, cache_backend: Any, identity: str) -> None:
        """Record each version bump and preserve the real cache operation.

        Args:
            cache_backend: Configured Django cache backend.
            identity: Cache identity whose version changes.
        """
        self.bumps.append(identity)
        super()._bump_cache_version(cache_backend, identity)


class ServerFailureView(TrackingGraphQLView):
    """Raise a non-400 transport error from one valid batch entry.

    This tests that the new partial-envelope rule does not expand to HTTP 500.
    """

    def get_response(
        self, request: Any, data: Any, show_graphiql: bool = False
    ) -> tuple[Any, int]:
        """Keep normal execution except for the selected synthetic failure.

        Args:
            request: The incoming HTTP request.
            data: The parsed batch entry.
            show_graphiql: Whether GraphiQL is rendered.

        Returns:
            The encoded GraphQL body and HTTP status.

        Raises:
            HttpError: For the selected HTTP 500 batch entry.
        """
        if data.get("id") == "server":
            raise HttpError(HttpResponse(status=500), message="Server failure.")
        return super().get_response(request, data, show_graphiql)


def _schema(calls: list[str], atomic_observations: list[bool]) -> SimpleNamespace:
    """Build a query and two mutations with observable durable writes.

    Args:
        calls: Resolver call log.
        atomic_observations: Transaction-state log.

    Returns:
        A schema wrapper accepted by the built-in HTTP views.
    """

    def add(_root: Any, _info: Any) -> str:
        """Persist one author and report the active transaction state.

        Returns:
            The mutation's GraphQL value.
        """
        calls.append("add")
        atomic_observations.append(connection.in_atomic_block)
        Author.objects.create(name="saved")
        return "saved"

    def fail(_root: Any, _info: Any) -> str:
        """Write before a deliberate resolver error for rollback coverage.

        Raises:
            GraphQLError: Always, after the write attempt.
        """
        calls.append("fail")
        Author.objects.create(name="rolled back")
        raise GraphQLError("Expected resolver failure.")

    return SimpleNamespace(
        graphql_schema=GraphQLSchema(
            query=GraphQLObjectType(
                "BatchQuery",
                {"ping": GraphQLField(GraphQLString, resolve=lambda *_: "pong")},
            ),
            mutation=GraphQLObjectType(
                "BatchMutation",
                {
                    "add": GraphQLField(GraphQLString, resolve=add),
                    "fail": GraphQLField(GraphQLString, resolve=fail),
                },
            ),
        )
    )


def _post(
    body: Any,
    *,
    view_class: type[BaseGraphQLView] = TrackingGraphQLView,
    atomic: bool = False,
    cache_active: bool = True,
    batch: bool = True,
) -> tuple[Any, list[str], list[bool], list[str]]:
    """Send one real request with isolated cache and a fresh cookie-free client.

    Args:
        body: JSON request body.
        view_class: Built-in HTTP view under test.
        atomic: Whether each mutation uses an atomic block.
        cache_active: Whether the enhanced view uses response caching.
        batch: Whether the endpoint accepts a batch body.

    Returns:
        The response, resolver calls, transaction states, and cache bumps.
    """
    calls: list[str] = []
    atomic_observations: list[bool] = []
    TrackingGraphQLView.bumps.clear()
    urlconf = ModuleType("batch_http_error_partial_urls")
    urlconf.urlpatterns = [
        path(
            "graphql/",
            view_class.as_view(schema=_schema(calls, atomic_observations), batch=batch),
        )
    ]
    settings = {
        "ATOMIC_MUTATIONS": atomic,
        "CACHE_ACTIVE": cache_active,
        "MAX_BATCH_SIZE": None,
    }
    caches = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "batch-http-error-partial",
        }
    }
    with override_settings(
        DJANGO_GRAPHEX=settings, ROOT_URLCONF=urlconf, CACHES=caches
    ):
        response = Client(raise_request_exception=False).post(
            "/graphql/", data=json.dumps(body), content_type="application/json"
        )
    return response, calls, atomic_observations, list(TrackingGraphQLView.bumps)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("atomic", [False, True])
@pytest.mark.parametrize("view_class", [BaseGraphQLView, TrackingGraphQLView])
def test_later_http_400_keeps_prior_result_and_stops_batch(
    atomic: bool, view_class: type[BaseGraphQLView]
) -> None:
    """Retain one durable write and the error, without running later entries.

    Args:
        atomic: Per-operation mutation transaction setting.
        view_class: The base or enhanced HTTP view.
    """
    response, calls, transactions, bumps = _post(
        [
            {"id": "first", "query": "mutation { add }"},
            {"id": "second"},
            {"id": "third", "query": "mutation { add }"},
        ],
        atomic=atomic,
        view_class=view_class,
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert isinstance(payload, list) and len(payload) == 2
    assert payload[0] == {"data": {"add": "saved"}, "id": "first", "status": 200}
    assert payload[1]["id"] == "second"
    assert payload[1]["status"] == 400
    assert payload[1]["errors"][0]["message"] == "Must provide query string."
    assert calls == ["add"]
    assert transactions == [atomic]
    assert list(Author.objects.values_list("name", flat=True)) == ["saved"]
    assert len(bumps) == (1 if view_class is TrackingGraphQLView else 0)


@pytest.mark.django_db(transaction=True)
def test_partial_response_does_not_depend_on_response_cache() -> None:
    """Retain prior success when the enhanced view has caching disabled.

    Cache configuration must not determine the batch response shape.
    """
    response, calls, transactions, bumps = _post(
        [{"id": "saved", "query": "mutation { add }"}, {"id": "bad"}],
        cache_active=False,
    )
    assert response.status_code == 400
    assert [entry["id"] for entry in json.loads(response.content)] == ["saved", "bad"]
    assert calls == ["add"]
    assert transactions == [False]
    assert bumps == []
    assert list(Author.objects.values_list("name", flat=True)) == ["saved"]


@pytest.mark.django_db(transaction=True)
def test_non_400_http_error_keeps_existing_request_level_envelope() -> None:
    """Do not broaden the approved HTTP 400 rule to server failures.

    A non-400 exception still reaches the request-level error handler.
    """
    response, calls, _, bumps = _post(
        [
            {"id": "first", "query": "mutation { add }"},
            {"id": "server", "query": "{ ping }"},
            {"id": "unrun", "query": "mutation { add }"},
        ],
        view_class=ServerFailureView,
    )
    assert response.status_code == 500
    assert isinstance(json.loads(response.content), dict)
    assert calls == ["add"]
    assert list(Author.objects.values_list("name", flat=True)) == ["saved"]
    assert len(bumps) == 1


@pytest.mark.django_db(transaction=True)
def test_first_http_400_has_one_error_entry_and_no_invalidation() -> None:
    """Include the failing first entry while leaving later writes untouched.

    No completed mutation means no cache-version bump is needed.
    """
    response, calls, transactions, bumps = _post(
        [{"id": "first"}, {"id": "unrun", "query": "mutation { add }"}]
    )
    assert response.status_code == 400
    assert json.loads(response.content) == [
        {
            "errors": [{"message": "Must provide query string."}],
            "id": "first",
            "status": 400,
        }
    ]
    assert calls == transactions == bumps == []
    assert not Author.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_validation_error_continues_until_later_transport_error() -> None:
    """Keep normal validation continuity and rollback the failed atomic op.

    Only the later transport failure stops the remaining batch entries.
    """
    response, calls, transactions, bumps = _post(
        [
            {"id": "one", "query": "mutation { add }"},
            {"id": "validation", "query": "{ missing }"},
            {"id": "rollback", "query": "mutation { fail }"},
            {"id": "transport"},
            {"id": "unrun", "query": "mutation { add }"},
        ],
        atomic=True,
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert isinstance(payload, list) and len(payload) == 4
    assert [entry["id"] for entry in payload] == [
        "one",
        "validation",
        "rollback",
        "transport",
    ]
    assert [entry["status"] for entry in payload] == [200, 400, 200, 400]
    assert payload[1]["errors"] and payload[2]["errors"]
    assert payload[3]["errors"][0]["message"] == "Must provide query string."
    assert calls == ["add", "fail"]
    assert transactions == [True]
    assert list(Author.objects.values_list("name", flat=True)) == ["saved"]
    assert len(bumps) == 1


@pytest.mark.django_db(transaction=True)
def test_outer_preflight_and_single_error_keep_existing_object_envelope() -> None:
    """Leave malformed outer requests and non-batch responses unchanged.

    These paths never enter the per-operation batch response loop.
    """
    for body, batch in [
        ({"query": "{ ping }"}, True),
        ([{"query": "{ ping }"}, "bad"], True),
        ({}, False),
    ]:
        response, calls, _, bumps = _post(body, batch=batch)
        assert response.status_code == 400
        assert isinstance(json.loads(response.content), dict)
        assert calls == bumps == []
    assert not Author.objects.exists()
