# -*- coding: utf-8 -*-
"""The "Did you mean" strip has to hold on the subscription transports too.

The HTTP view routes every error through "BaseGraphQLView.format_error", but
the WS and SSE transports used to serialize graphql-core's raw "error.formatted"
instead. So on a deployment that exposes subscriptions with introspection
genuinely disabled, a "subscribe" frame or a direct POST to the SSE endpoint
still handed back real field and type names -- the exact schema oracle the HTTP
strip closes.

Both transports must therefore answer a misspelled field WITHOUT naming the
real one, on every frame that carries errors: the subscribe-time validation
error, the subscribe-entry failure, and the in-stream "next{errors}" frame. And
they must keep the suggestion when introspection is not actually disabled --
"ALLOW_INTROSPECTION" is False by default and inert until
"DisableIntrospectionMiddleware" is installed, so reading the setting alone
would strip hints from a schema anybody can introspect.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import RequestFactory, override_settings

pytest.importorskip("channels")

from graphql import (  # noqa: E402
    ExecutionResult,
    GraphQLBoolean,
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.security import DisableIntrospectionMiddleware  # noqa: E402

#: Installing the middleware is what makes "ALLOW_INTROSPECTION=False" real.
_INTROSPECTION_OFF = {
    "ALLOW_INTROSPECTION": False,
    "MIDDLEWARE": (DisableIntrospectionMiddleware,),
}
#: The middleware is installed but the setting hands introspection out anyway.
_INTROSPECTION_ON = {
    "ALLOW_INTROSPECTION": True,
    "MIDDLEWARE": (DisableIntrospectionMiddleware,),
}
#: The stock project: the setting is off, but nothing enforces it.
_MIDDLEWARE_MISSING = {"ALLOW_INTROSPECTION": False, "MIDDLEWARE": ()}

#: A misspelling of "Tick.id" -- graphql-core answers it with "Did you mean 'id'?".
_MISSPELLED = "subscription { onTick { idd } }"

#: An error message shaped exactly like the one graphql-core produces for a
#: failure raised after the stream started (the "next{errors}" frame).
_LEAKY_MESSAGE = "Cannot query field 'emial' on type 'Tick'. Did you mean 'email'?"


def _schema() -> GraphQLSchema:
    """Build a one-field subscription schema whose subscribe entry never runs.

    Returns:
        schema: A schema whose "onTick" subscription publishes a "Tick" with a
            single "id" field for a misspelling to suggest.
    """
    tick = GraphQLObjectType("Tick", {"id": GraphQLField(GraphQLString)})

    async def subscribe(root: Any, info: Any) -> Any:
        raise GraphQLError(_LEAKY_MESSAGE)

    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)}),
        subscription=GraphQLObjectType(
            "Subscription", {"onTick": GraphQLField(tick, subscribe=subscribe)}
        ),
    )


class _User:
    """A minimal authenticated user stand-in exposing the flags the transports read."""

    is_authenticated = True
    pk = 1


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


async def _sse_body(query: str) -> str:
    """Run the SSE view for a document and return its concatenated frames.

    Args:
        query: The GraphQL subscription document to post.

    Returns:
        body: The decoded text of every frame up to (and including) "complete".
    """
    import asyncio

    from django_graphex.subscriptions.transports import sse

    request = RequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    request.user = _User()

    response = await sse.subscription_sse_view(schema=_schema())(request)
    frames: list[str] = []
    aiter = response.streaming_content.__aiter__()
    for _ in range(3):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
        frames.append(
            chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        )
        if "event: complete" in frames[-1]:
            break
    aclose = getattr(aiter, "aclose", None)
    if aclose:
        await aclose()
    return "".join(frames)


@override_settings(DJANGO_GRAPHEX=_INTROSPECTION_OFF)
async def test_sse_strips_the_suggestion_when_introspection_is_disabled() -> None:
    """The SSE validation frame must not name the field the client misspelled.

    Contract: this ships broken if the SSE transport serializes raw
    "error.formatted", turning a subscription endpoint into a schema oracle.
    """
    body = await _sse_body(_MISSPELLED)

    assert "Cannot query field 'idd' on type 'Tick'." in body
    assert "Did you mean" not in body


@override_settings(DJANGO_GRAPHEX=_INTROSPECTION_ON)
async def test_sse_keeps_the_suggestion_when_introspection_is_allowed() -> None:
    """The hint stays when the schema is public anyway.

    Contract: a guard that fires unconditionally costs every development
    deployment its error hints.
    """
    body = await _sse_body(_MISSPELLED)

    assert "Did you mean" in body


@override_settings(DJANGO_GRAPHEX=_MIDDLEWARE_MISSING)
async def test_sse_keeps_the_suggestion_without_the_introspection_middleware() -> None:
    """The setting alone must not trigger the strip.

    Contract: "ALLOW_INTROSPECTION" is False by default and inert until the
    middleware is installed, so a stock project must keep its hints.
    """
    body = await _sse_body(_MISSPELLED)

    assert "Did you mean" in body


# ---------------------------------------------------------------------------
# WS
# ---------------------------------------------------------------------------


def _consumer() -> Any:
    """Build a WS consumer wired to record every frame it sends.

    Returns:
        consumer: An acked consumer whose "send_json" appends to "_sent".
    """
    from django_graphex.subscriptions.transports import ws

    consumer = ws.subscription_ws_consumer(schema=_schema(), init_timeout=0.05)()
    consumer.scope = {"user": _User()}
    consumer._acked = True
    consumer._operations = {}
    consumer._sources = {}
    consumer._closing = False
    consumer._sent = []

    async def send_json(payload: dict[str, Any]) -> None:
        consumer._sent.append(payload)

    consumer.send_json = send_json
    return consumer


async def _ws_frames(query: str) -> str:
    """Run one WS subscribe operation and return its frames as JSON text.

    Args:
        query: The GraphQL subscription document to subscribe with.

    Returns:
        frames: The JSON dump of every frame the consumer sent.
    """
    consumer = _consumer()
    await consumer._run_operation("op1", {"query": query})
    return json.dumps(consumer._sent)


@override_settings(DJANGO_GRAPHEX=_INTROSPECTION_OFF)
async def test_ws_strips_the_suggestion_when_introspection_is_disabled() -> None:
    """The WS validation error frame must not name the real field.

    Contract: this ships broken if the WS transport serializes raw
    "error.formatted" on the subscribe-time validation path.
    """
    frames = await _ws_frames(_MISSPELLED)

    assert "Cannot query field 'idd' on type 'Tick'." in frames
    assert "Did you mean" not in frames


@override_settings(DJANGO_GRAPHEX=_INTROSPECTION_ON)
async def test_ws_keeps_the_suggestion_when_introspection_is_allowed() -> None:
    """The hint stays on WS when the schema is public anyway.

    Contract: a guard that fires unconditionally costs every development
    deployment its error hints.
    """
    frames = await _ws_frames(_MISSPELLED)

    assert "Did you mean" in frames


@override_settings(DJANGO_GRAPHEX=_MIDDLEWARE_MISSING)
async def test_ws_keeps_the_suggestion_without_the_introspection_middleware() -> None:
    """The setting alone must not trigger the WS strip.

    Contract: "ALLOW_INTROSPECTION" is False by default and inert until the
    middleware is installed, so a stock project must keep its hints.
    """
    frames = await _ws_frames(_MISSPELLED)

    assert "Did you mean" in frames


@override_settings(DJANGO_GRAPHEX=_INTROSPECTION_OFF)
async def test_ws_strips_the_suggestion_on_a_subscribe_entry_failure() -> None:
    """The subscribe entry's own error must lose its suggestion too.

    Contract: a document that clears validation and then fails inside
    "create_source_event_stream" takes a different frame path, and this ships
    broken if that path serializes the raw error.
    """
    frames = await _ws_frames("subscription { onTick { id } }")

    assert "Did you mean" not in frames


@override_settings(DJANGO_GRAPHEX=_INTROSPECTION_OFF)
async def test_ws_strips_the_suggestion_on_an_in_stream_error_frame() -> None:
    """An error raised after the stream started must lose its suggestion.

    Contract: "next{errors}" is the third serialization site in the WS
    transport, and a strip that covers only the subscribe-time frames leaves
    the oracle open for the whole life of the subscription.
    """
    consumer = _consumer()

    await consumer._send_next(
        "op1", ExecutionResult(data=None, errors=[GraphQLError(_LEAKY_MESSAGE)])
    )

    frames = json.dumps(consumer._sent)
    assert "Cannot query field 'emial' on type 'Tick'." in frames
    assert "Did you mean" not in frames
