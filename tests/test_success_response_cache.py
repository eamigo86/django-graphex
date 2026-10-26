"""HTTP response-cache eligibility for successful GraphQL responses."""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from django.core.cache import caches
from django.db.backends.base.base import BaseDatabaseWrapper
from django.http import HttpRequest, HttpResponse
from django.test import Client, override_settings
from django.urls import clear_url_caches, path
from graphql import (
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLResolveInfo,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.views import GraphQLView

_calls = {"fragile": 0, "healthy": 0, "view": 0}


def _fragile(root: Any, info: GraphQLResolveInfo) -> str:
    """Fail once and then recover on later execution.

    Args:
        root: The unused parent value.
        info: The unused GraphQL execution context.

    Returns:
        The recovered field value.

    Raises:
        GraphQLError: On the first resolver call.
    """
    _calls["fragile"] += 1
    if _calls["fragile"] == 1:
        raise GraphQLError("temporary downstream unavailable")
    return "recovered"


def _healthy(root: Any, info: GraphQLResolveInfo) -> str:
    """Return a stable value while counting actual executions.

    Args:
        root: The unused parent value.
        info: The unused GraphQL execution context.

    Returns:
        The stable field value.
    """
    _calls["healthy"] += 1
    return "ready"


class _TrackingView(GraphQLView):
    """Count actual base-view executions without replacing HTTP behavior."""

    def super_call(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        """Dispatch through the real base view and count the execution.

        Args:
            request: The incoming HTTP request.
            *args: Positional arguments forwarded to the base view.
            **kwargs: Keyword arguments forwarded to the base view.

        Returns:
            The base view's HTTP response.
        """
        _calls["view"] += 1
        return super().super_call(request, *args, **kwargs)


_SCHEMA = SimpleNamespace(
    graphql_schema=GraphQLSchema(
        query=GraphQLObjectType(
            "SuccessCacheQuery",
            {
                "fragile": GraphQLField(GraphQLString, resolve=_fragile),
                "healthy": GraphQLField(GraphQLString, resolve=_healthy),
            },
        )
    )
)
urlpatterns = [path("graphql/", _TrackingView.as_view(schema=_SCHEMA))]


@pytest.fixture(autouse=True)
def _isolated_cache(request: pytest.FixtureRequest) -> Iterator[None]:
    """Use a unique no-database response cache for each HTTP witness.

    Args:
        request: The current pytest case, used only for its cache namespace.

    Yields:
        Control while the isolated cache and no-database guard are active.
    """
    _calls.update(fragile=0, healthy=0, view=0)
    with (
        override_settings(
            ROOT_URLCONF=__name__,
            DEBUG=False,
            CACHES={
                "default": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                    "LOCATION": f"success-cache-{request.node.name}",
                }
            },
            DJANGO_GRAPHEX={
                "CACHE_ACTIVE": True,
                "CACHE_TIMEOUT": 60,
                "CLEAN_RESPONSE": False,
            },
        ),
        patch.object(
            BaseDatabaseWrapper,
            "ensure_connection",
            side_effect=AssertionError("unexpected database connection"),
        ),
    ):
        clear_url_caches()
        yield
        clear_url_caches()


def _post(query: str, *, cookie: bool = False) -> HttpResponse:
    """Send a real JSON POST with a fresh client and optional cookie.

    Args:
        query: The GraphQL query document.
        cookie: Whether to attach contextual request cookie state.

    Returns:
        The HTTP response from the real GraphQL URL route.
    """
    client = Client()
    if cookie:
        client.cookies["tenant"] = "private-context"
    return client.post(
        "/graphql/", data=json.dumps({"query": query}), content_type="application/json"
    )


def _response_writes(mock: Any) -> int:
    """Count only response-entry writes, excluding version-counter writes.

    Args:
        mock: The wrapped cache set mock.

    Returns:
        The number of owned response-cache entry writes.
    """
    return sum(
        isinstance(call.args[0], str) and call.args[0].startswith("_graphql_v2_")
        for call in mock.call_args_list
    )


def _post_with_cache_key(query: str) -> tuple[HttpResponse, str]:
    """Execute once and capture the actual owned response-cache key.

    Args:
        query: The GraphQL document submitted to the real view.

    Returns:
        The HTTP response and its exact response-cache key.
    """
    backend = caches["default"]
    with patch.object(backend, "get", wraps=backend.get) as get_mock:
        response = _post(query)
    keys = [
        call.args[0]
        for call in get_mock.call_args_list
        if isinstance(call.args[0], str) and call.args[0].startswith("_graphql_v2_")
    ]
    assert len(keys) == 1
    return response, keys[0]


def test_partial_execution_error_recovers_then_success_hits() -> None:
    """Rerun a partial HTTP 200 error, then cache only its recovery.

    A healthy third request must hit rather than run resolvers again.
    """
    backend = caches["default"]
    with patch.object(backend, "set", wraps=backend.set) as set_mock:
        first = _post("{ healthy fragile }")
        assert first.status_code == 200
        assert json.loads(first.content)["data"] == {
            "healthy": "ready",
            "fragile": None,
        }
        assert json.loads(first.content)["errors"]
        assert _response_writes(set_mock) == 0

        second = _post("{ healthy fragile }")
        assert second.status_code == 200
        assert json.loads(second.content) == {
            "data": {"healthy": "ready", "fragile": "recovered"}
        }
        assert _response_writes(set_mock) == 1

        third = _post("{ healthy fragile }")
        assert third.content == second.content
        assert _response_writes(set_mock) == 1

    assert _calls == {"fragile": 2, "healthy": 2, "view": 2}


def test_validation_error_is_not_stored_or_reused() -> None:
    """Execute repeated real HTTP 400 validation failures afresh.

    Neither failure may write an owned response-cache entry.
    """
    backend = caches["default"]
    with patch.object(backend, "set", wraps=backend.set) as set_mock:
        first = _post("{ missingField }")
        second = _post("{ missingField }")
        assert _response_writes(set_mock) == 0
    assert first.status_code == second.status_code == 400
    assert json.loads(first.content) == json.loads(second.content)
    assert json.loads(first.content)["errors"]
    assert _calls == {"fragile": 0, "healthy": 0, "view": 2}


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (b'{"data":{"healthy":"stale"},"errors":[{"message":"old"}]}', 200),
        (b'{"errors":[{"message":"old"}]}', 400),
        (b'{"data":{"healthy":"stale"}}', 503),
        (b"", 200),
    ],
)
def test_legacy_failed_entry_is_ignored_and_replaced(body: bytes, status: int) -> None:
    """Reject an old failed or malformed entry at its exact live cache key.

    Args:
        body: The previously stored GraphQL response body.
        status: The previously stored HTTP status.
    """
    first, key = _post_with_cache_key("{ healthy }")
    assert first.status_code == 200
    backend = caches["default"]
    backend.set(key, (body, status, "application/json"), timeout=60)

    second = _post("{ healthy }")
    third = _post("{ healthy }")
    assert second.status_code == third.status_code == 200
    assert json.loads(second.content) == {"data": {"healthy": "ready"}}
    assert third.content == second.content
    assert _calls == {"fragile": 0, "healthy": 2, "view": 2}


def test_malformed_legacy_entry_is_ignored() -> None:
    """Treat a stored non-tuple entry as a miss, not an HTTP response.

    The next successful execution must replace only its owned cache key.
    """
    first, key = _post_with_cache_key("{ healthy }")
    assert first.status_code == 200
    backend = caches["default"]
    backend.set(key, {"unexpected": "legacy shape"}, timeout=60)

    second = _post("{ healthy }")
    third = _post("{ healthy }")
    assert second.status_code == third.status_code == 200
    assert json.loads(second.content) == {"data": {"healthy": "ready"}}
    assert third.content == second.content
    assert _calls == {"fragile": 0, "healthy": 2, "view": 2}


def test_disabled_cache_executes_without_response_cache_io() -> None:
    """Keep the CACHE_ACTIVE=False control entirely uncached.

    Two identical requests must execute and skip all cache backend calls.
    """
    backend = caches["default"]
    with (
        override_settings(DJANGO_GRAPHEX={"CACHE_ACTIVE": False}),
        patch.object(backend, "get", wraps=backend.get) as get_mock,
        patch.object(backend, "set", wraps=backend.set) as set_mock,
    ):
        first = _post("{ healthy }")
        second = _post("{ healthy }")
    assert first.status_code == second.status_code == 200
    assert get_mock.call_count == set_mock.call_count == 0
    assert _calls == {"fragile": 0, "healthy": 2, "view": 2}


def test_cookie_bearing_queries_bypass_response_cache() -> None:
    """Preserve the contextual-cookie bypass for otherwise healthy queries.

    Both requests must execute without writing a shared response entry.
    """
    backend = caches["default"]
    with patch.object(backend, "set", wraps=backend.set) as set_mock:
        first = _post("{ healthy }", cookie=True)
        second = _post("{ healthy }", cookie=True)
    assert first.status_code == second.status_code == 200
    assert json.loads(first.content) == json.loads(second.content)
    assert _response_writes(set_mock) == 0
    assert _calls == {"fragile": 0, "healthy": 2, "view": 2}
