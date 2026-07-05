# -*- coding: utf-8 -*-
"""FIX 4 — subscription-less (fully-pruned) schema parity across transports.

A per-connection "schema_provider" may return a schema whose Subscription root
is None — the case of a user whose subscription fields were ALL pruned away.
graphql-core's "create_source_event_stream" / "subscribe" then raises a vague
"Schema is not configured to execute subscription operation." that leaks the
server's schema shape. Both transports must instead short-circuit BEFORE reaching
graphql-core with a GENERIC denial (mirroring the HTTP view's generic-403
philosophy): SSE emits an in-stream "next{errors}" frame then "complete"; WS
emits an "error{id, payload}" frame for the subscribe id. The message must leak
nothing about which field/type is missing.

These drive ONLY the pre-subscribe path (validation succeeds against a
subscription root that exists as a type but is resolved to None at the
transport boundary), so no real "ChannelLayerSource" starts — no channel layer
is needed and nothing blocks.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("channels")

from graphql import GraphQLSchema  # noqa: E402


def _subscriptionless_schema() -> GraphQLSchema:
    """Build a schema with no subscription root ("subscription_type is None").

    Simulates a fully-pruned user: every subscription field was removed, so the
    per-user schema has no Subscription type at all.

    Returns:
        schema: A minimal Query-only schema with subscription left unset.
    """
    from graphql import (
        GraphQLBoolean,
        GraphQLField,
        GraphQLObjectType,
        GraphQLSchema,
    )

    query = GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)})
    return GraphQLSchema(query=query)  # subscription=None


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


# A syntactically-valid subscription document. Against a subscription-less schema
# the transport must deny generically BEFORE graphql-core's vague error surfaces.
_SUB_QUERY = "subscription { anything { id } }"


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


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
    import asyncio

    frames: list[str] = []
    aiter = response.streaming_content.__aiter__()
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


async def test_sse_subscriptionless_schema_denies_generically_not_leaky() -> None:
    """A subscription-less schema provider must trigger a generic in-stream denial.

    Contract: schema-shape leakage ships broken if the SSE view surfaces
    graphql-core's raw "Schema is not configured to execute subscription
    operation." message instead of a generic next{errors} frame followed by
    complete, with no source ever started.
    """
    from django_graphex.subscriptions.transports import sse

    def provider(user: "_User") -> GraphQLSchema:
        return _subscriptionless_schema()

    view = sse.subscription_sse_view(schema_provider=provider)
    response = await view(_make_request(_SUB_QUERY, user=_User()))

    # Committed as a 200 stream (a subscribe denial is delivered IN-STREAM).
    assert response.status_code == 200
    assert response["content-type"].startswith("text/event-stream")

    # No live source was started for a subscription-less schema.
    assert sse.get_started_source(response) is None

    body = await _drain(response)
    # A generic denial frame is delivered, then complete.
    assert "event: next" in body
    assert "event: complete" in body
    # The vague graphql-core message must NOT leak.
    assert "not configured to execute subscription" not in body
    # And it carries an errors payload (a denial, not an empty next).
    assert "errors" in body


async def test_sse_subscriptionless_schema_does_not_raise() -> None:
    """The subscription-less path must be handled cleanly with no unhandled exception.

    Contract: this test ships broken if building the SSE response for a
    subscription-less schema raises instead of yielding an in-stream denial.
    """
    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(
        schema_provider=lambda user: _subscriptionless_schema()
    )
    # Building the response must not raise (the denial is in-stream, not a crash).
    response = await view(_make_request(_SUB_QUERY, user=_User()))
    assert response.status_code == 200


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


async def test_ws_subscriptionless_schema_sends_generic_error_frame() -> None:
    """A subscription-less WS schema provider must send a generic error frame.

    Contract: schema-shape leakage ships broken if the consumer emits
    graphql-core's raw "Schema is not configured to execute subscription
    operation." message instead of a generic error{id, payload} frame, or if
    it starts a source for the denied operation id.
    """
    consumer = _ws_consumer(
        {"user": _User()},
        schema_provider=lambda user: _subscriptionless_schema(),
    )
    await consumer._run_operation("op1", {"query": _SUB_QUERY})

    errors = [m for m in consumer._sent if m.get("type") == "error"]
    assert errors, consumer._sent
    assert errors[0]["id"] == "op1"
    dumped = json.dumps(errors)
    # The vague graphql-core message must NOT leak.
    assert "not configured to execute subscription" not in dumped
    # No source was ever started for a subscription-less schema.
    assert consumer.started_source("op1") is None
    # No terminal next/complete for a denial (an error frame is the only reply).
    assert not [m for m in consumer._sent if m.get("type") == "next"]
