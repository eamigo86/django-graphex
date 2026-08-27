# -*- coding: utf-8 -*-
"""Depth and cost validation rules on the subscription transports.

The docs promise "MAX_QUERY_DEPTH" / "MAX_QUERY_COST" on every operation type,
but both transports used to call "validate" with graphql-core's default rule
set, so a subscription document was never measured. A subscription is the worst
surface to lose the guard on: its selection set is re-executed for every
delivered event, so an over-deep or over-costly document is paid for again and
again instead of once.

Both transports must therefore validate with the SAME settings-driven rule
tuple the HTTP view uses -- and must still accept a document that fits inside
the configured budgets.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import RequestFactory, override_settings

pytest.importorskip("channels")

from graphql import (  # noqa: E402
    GraphQLBoolean,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

#: Raised by the subscribe entry so a document that PASSES validation is
#: distinguishable from one the rules rejected: only a validated document ever
#: reaches the resolver, so this marker in the error frame proves the guard let
#: it through rather than silently blocking everything.
_SUBSCRIBE_REACHED = "subscribe-entry-reached"


def _schema() -> GraphQLSchema:
    """Build a self-nesting subscription schema with no channel-layer source.

    The subscribe entry raises immediately, so a document that clears
    validation never starts a real source and needs no channel layer.

    Returns:
        schema: A schema whose "onTick" subscription returns a self-nesting
            "Node", allowing arbitrarily deep (and costly) documents.
    """
    node: GraphQLObjectType = GraphQLObjectType(
        "Node",
        lambda: {
            "id": GraphQLField(GraphQLString),
            "child": GraphQLField(node),
        },
    )

    async def subscribe(root: Any, info: Any) -> Any:
        raise RuntimeError(_SUBSCRIBE_REACHED)

    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)}),
        subscription=GraphQLObjectType(
            "Subscription",
            {"onTick": GraphQLField(node, subscribe=subscribe)},
        ),
    )


class _User:
    """A minimal authenticated user stand-in exposing the flags the transports read."""

    is_authenticated = True
    pk = 1


#: Three nested object levels below the root -- over a MAX_QUERY_DEPTH of 2.
_DEEP = "subscription { onTick { child { child { id } } } }"
#: Two object levels: within a depth budget of 2, over a cost budget of 1.
_COSTLY = "subscription { onTick { child { id } } }"
#: One object level: inside every budget configured below.
_CHEAP = "subscription { onTick { id } }"


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


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
async def test_sse_enforces_max_query_depth() -> None:
    """An over-deep subscription must be rejected in-stream by the depth rule.

    Contract: this ships broken if the SSE transport validates without the
    depth rule, letting a document deeper than "MAX_QUERY_DEPTH" subscribe.
    """
    body = await _sse_body(_DEEP)

    assert "QUERY_TOO_DEEP" in body
    assert _SUBSCRIBE_REACHED not in body


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1})
async def test_sse_enforces_max_query_cost() -> None:
    """An over-budget subscription must be rejected in-stream by the cost rule.

    Contract: this ships broken if the SSE transport validates without the cost
    rule, letting a document over "MAX_QUERY_COST" subscribe.
    """
    body = await _sse_body(_COSTLY)

    assert "QUERY_TOO_COMPLEX" in body
    assert _SUBSCRIBE_REACHED not in body


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2, "MAX_QUERY_COST": 5})
async def test_sse_accepts_a_document_inside_the_budgets() -> None:
    """A subscription within both budgets must still reach the subscribe entry.

    Contract: a guard that rejects everything is not a guard -- this ships
    broken if wiring the rules into SSE blocks a compliant document.
    """
    body = await _sse_body(_CHEAP)

    assert _SUBSCRIBE_REACHED in body
    assert "QUERY_TOO_DEEP" not in body
    assert "QUERY_TOO_COMPLEX" not in body


# ---------------------------------------------------------------------------
# WS
# ---------------------------------------------------------------------------


async def _ws_frames(query: str) -> str:
    """Run one WS subscribe operation and return its frames as JSON text.

    Args:
        query: The GraphQL subscription document to subscribe with.

    Returns:
        frames: The JSON dump of every frame the consumer sent.
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
    await consumer._run_operation("op1", {"query": query})
    return json.dumps(consumer._sent)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
async def test_ws_enforces_max_query_depth() -> None:
    """An over-deep subscription must be rejected by the WS depth rule.

    Contract: this ships broken if the WS transport validates without the depth
    rule, letting a document deeper than "MAX_QUERY_DEPTH" subscribe.
    """
    frames = await _ws_frames(_DEEP)

    assert "QUERY_TOO_DEEP" in frames
    assert _SUBSCRIBE_REACHED not in frames


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1})
async def test_ws_enforces_max_query_cost() -> None:
    """An over-budget subscription must be rejected by the WS cost rule.

    Contract: this ships broken if the WS transport validates without the cost
    rule, letting a document over "MAX_QUERY_COST" subscribe.
    """
    frames = await _ws_frames(_COSTLY)

    assert "QUERY_TOO_COMPLEX" in frames
    assert _SUBSCRIBE_REACHED not in frames


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2, "MAX_QUERY_COST": 5})
async def test_ws_accepts_a_document_inside_the_budgets() -> None:
    """A subscription within both budgets must still reach the subscribe entry.

    Contract: a guard that rejects everything is not a guard -- this ships
    broken if wiring the rules into WS blocks a compliant document.
    """
    frames = await _ws_frames(_CHEAP)

    assert _SUBSCRIBE_REACHED in frames
    assert "QUERY_TOO_DEEP" not in frames
    assert "QUERY_TOO_COMPLEX" not in frames
