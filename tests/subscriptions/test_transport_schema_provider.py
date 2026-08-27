# -*- coding: utf-8 -*-
"""P3 — Per-connection schema provider for the WS/SSE transports.

The permission-scoped-schema change makes the subscription transports resolve
their schema PER CONNECTION via an optional "schema_provider" (design D5), so a
WS or SSE connection uses the SAME pruned schema as HTTP for that user.

Contract pinned here:

  * "subscription_ws_consumer" and "subscription_sse_view" accept an optional
    "schema_provider" callable; when given it WINS and is resolved with the
    connection user ("scope['user']" for WS, "request.user" for SSE);
  * the resolved schema drives validation, so subscribing to a subscription field
    ABSENT from the provider's (pruned) schema fails at VALIDATION
    ("Cannot query field") — matching HTTP pruning;
  * BACKWARD COMPATIBLE: a plain "schema=" (no provider) still works exactly as
    before, and the example app's "schema=schema.graphql_schema" wiring is
    unchanged.

These tests deliberately drive only the VALIDATION path (a pruned schema whose
subscription field is absent, or a plain schema over a syntactically-valid but
non-existent field) so they never start a real "ChannelLayerSource" — no
channel layer is required and nothing blocks.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from graphql import GraphQLSchema

pytest.importorskip("channels")


# The node types Post's relation graph needs, and the assembled schema, are
# built ONCE process-wide by the shared module (see its docstring).
from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402


def _pruned_schema_without_subscription() -> GraphQLSchema:
    """Build a schema whose Subscription root has no "post" field.

    Simulates pruning: the type exists but the field was removed.

    Returns:
        schema: The assembled schema with a Subscription root that carries
            only an unrelated "heartbeat" field.
    """
    from graphql import GraphQLBoolean, GraphQLField, GraphQLObjectType, GraphQLSchema

    query = GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)})
    # A Subscription root with an unrelated field so the type exists but ``post``
    # is absent (subscribing to ``post`` => Cannot query field).
    subscription = GraphQLObjectType(
        "Subscription", {"heartbeat": GraphQLField(GraphQLBoolean)}
    )
    return GraphQLSchema(query=query, subscription=subscription)


class _User:
    """A minimal user stand-in exposing authentication flags and a pk."""

    def __init__(self, *, authenticated: bool = True) -> None:
        """Store the authentication flag and derive a matching pk.

        Args:
            authenticated: Whether this stand-in reports itself as
                authenticated; an unauthenticated user gets pk=None.
        """
        self.is_authenticated = authenticated
        self.pk = 1 if authenticated else None


_SUB_QUERY = "subscription { post(action: CREATE) { id } }"


def _make_request(query: str, *, user: "_User") -> Any:
    """Build a POST request carrying a subscription document and a fake user.

    Args:
        query: The GraphQL subscription document to send as the request body.
        user: The stand-in user to attach as request.user.

    Returns:
        request: The constructed Django test request.
    """
    from django.test import RequestFactory

    factory = RequestFactory()
    request = factory.post(
        "/subscriptions/sse",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    request.user = user
    return request


async def _drain(response: Any, *, max_frames: int = 3) -> str:
    """Consume up to max_frames SSE frames from a streaming response.

    Args:
        response: The streaming HTTP response to read frames from.
        max_frames: The maximum number of frames to pull before stopping.

    Returns:
        body: The concatenated decoded text of the consumed frames.
    """
    frames: list[str] = []
    aiter = response.streaming_content.__aiter__()
    import asyncio

    for _ in range(max_frames):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        frames.append(text)
        if "event: complete" in text:
            break
    aclose = getattr(aiter, "aclose", None)
    if aclose:
        await aclose()
    return "".join(frames)


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


async def test_sse_provider_resolved_with_request_user_and_pruned_omits_field() -> None:
    """The SSE view must call "schema_provider" with request.user and use its schema.

    Contract: HTTP/WS/SSE pruning parity ships broken if the SSE view either
    fails to resolve schema_provider with request.user or does not validate
    against the resulting pruned schema (the omitted "post" field must fail
    with "Cannot query field").
    """
    from django_graphex.subscriptions.transports import sse

    pruned = _pruned_schema_without_subscription()
    seen: dict[str, Any] = {}

    def provider(user: "_User") -> GraphQLSchema:
        seen["user"] = user
        return pruned

    view = sse.subscription_sse_view(schema_provider=provider)
    user = _User()
    response = await view(_make_request(_SUB_QUERY, user=user))
    assert response.status_code == 200
    assert seen["user"] is user
    body = await _drain(response)
    assert "Cannot query field" in body


async def test_sse_plain_schema_accepts_valid_subscription_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BACKWARD COMPAT: a plain schema= (no provider) must validate the "post" field.

    Contract: pre-existing SSE callers ship broken if supplying only
    "schema=" (no schema_provider) starts rejecting a legitimate
    subscription field with "Cannot query field".

    "create_source_event_stream" is stubbed to a benign ExecutionResult so
    the view never starts a real "ChannelLayerSource" (no channel layer needed).

    Args:
        monkeypatch: The pytest fixture used to stub create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import sse

    async def _stub(*a: Any, **k: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(sse, "create_source_event_stream", _stub)

    full = build_native_schema()
    view = sse.subscription_sse_view(schema=full)
    response = await view(_make_request(_SUB_QUERY, user=_User()))
    assert response.status_code == 200
    assert response["content-type"].startswith("text/event-stream")
    body = await _drain(response)
    # The known field validated: no not-found error surfaced.
    assert "Cannot query field" not in body


# ---------------------------------------------------------------------------
# WS
# ---------------------------------------------------------------------------


def _ws_consumer(
    scope: dict[str, Any],
    *,
    schema: GraphQLSchema | None = None,
    schema_provider: Any = None,
) -> Any:
    """Instantiate a WS consumer bound to schema/provider with a given scope.

    Args:
        scope: The ASGI-style connection scope to attach to the consumer.
        schema: An explicit schema to bind the consumer to, when not using a
            per-connection provider.
        schema_provider: A callable resolving the schema from the connected
            user, when not using a fixed schema.

    Returns:
        consumer: The instantiated consumer, pre-wired with fake internal
            state and a recording send_json stand-in.
    """
    from django_graphex.subscriptions.transports import ws

    kwargs: dict[str, Any] = {"init_timeout": 0.05}
    if schema is not None:
        kwargs["schema"] = schema
    if schema_provider is not None:
        kwargs["schema_provider"] = schema_provider
    consumer_cls = ws.subscription_ws_consumer(**kwargs)
    consumer = consumer_cls()
    consumer.scope = scope
    consumer._acked = True
    consumer._operations = {}
    consumer._sources = {}
    consumer._closing = False
    consumer._sent = []

    async def _fake_send_json(payload: dict[str, Any]) -> None:
        consumer._sent.append(payload)

    consumer.send_json = _fake_send_json  # type: ignore[assignment]
    return consumer


async def test_ws_provider_resolved_with_scope_user_and_pruned_errors() -> None:
    """The WS consumer must resolve schema_provider with scope["user"] and validate.

    Contract: HTTP/WS/SSE pruning parity ships broken if the WS consumer
    either fails to resolve schema_provider with scope["user"] or does not
    validate against the resulting pruned schema (the omitted "post" field
    must produce an error frame).
    """
    pruned = _pruned_schema_without_subscription()
    seen: dict[str, Any] = {}

    def provider(user: "_User") -> GraphQLSchema:
        seen["user"] = user
        return pruned

    user = _User()
    consumer = _ws_consumer({"user": user}, schema_provider=provider)
    await consumer._run_operation("1", {"query": _SUB_QUERY})

    assert seen["user"] is user
    errors = [m for m in consumer._sent if m.get("type") == "error"]
    assert errors, consumer._sent
    assert "Cannot query field" in json.dumps(errors)


def test_sse_requires_schema_or_provider() -> None:
    """Passing neither schema= nor schema_provider= must raise ValueError.

    Contract: misconfiguration ships broken (silent no-op view) if the SSE
    view accepts being built with no way to resolve a schema.
    """
    from django_graphex.subscriptions.transports import sse

    with pytest.raises(ValueError):
        sse.subscription_sse_view()


def test_ws_requires_schema_or_provider() -> None:
    """Passing neither schema= nor schema_provider= must raise ValueError.

    Contract: misconfiguration ships broken (silent no-op consumer) if the
    WS consumer factory accepts being built with no way to resolve a schema.
    """
    from django_graphex.subscriptions.transports import ws

    with pytest.raises(ValueError):
        ws.subscription_ws_consumer()


async def test_ws_provider_resolved_once_per_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The WS "schema_provider" must be resolved once per socket and cached.

    Contract: performance ships broken if a second multiplexed operation on
    the same connection re-invokes schema_provider instead of reusing the
    first resolved schema.

    Args:
        monkeypatch: The pytest fixture used to stub create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import ws

    async def _stub(*a: Any, **k: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(ws, "create_source_event_stream", _stub)

    full = build_native_schema()
    calls = {"n": 0}

    def provider(user: "_User") -> GraphQLSchema:
        calls["n"] += 1
        return full

    consumer = _ws_consumer({"user": _User()}, schema_provider=provider)
    await consumer._run_operation("1", {"query": _SUB_QUERY})
    await consumer._run_operation("2", {"query": _SUB_QUERY})
    assert calls["n"] == 1  # resolved once, cached for the connection


async def test_ws_plain_schema_validates_known_subscription_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BACKWARD COMPAT: a plain schema= WS consumer must not reject the known field.

    Contract: pre-existing WS callers ship broken if supplying only
    "schema=" (no schema_provider) starts rejecting the "post" field with a
    "Cannot query field" validation error.

    "create_source_event_stream" is stubbed so validation runs but no real
    source starts (no channel layer / no delivery-loop block).

    Args:
        monkeypatch: The pytest fixture used to stub create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import ws

    async def _stub(*a: Any, **k: Any) -> ExecutionResult:
        # A benign ExecutionResult => _run_operation sends an error frame and
        # returns WITHOUT entering the delivery loop.
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(ws, "create_source_event_stream", _stub)

    full = build_native_schema()
    consumer = _ws_consumer({"user": _User()}, schema=full)
    await consumer._run_operation("1", {"query": _SUB_QUERY})
    assert "Cannot query field" not in json.dumps(consumer._sent)
