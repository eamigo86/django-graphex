# -*- coding: utf-8 -*-
"""The WS subscribe call has TWO failure exits; this pins the raising one.

"create_source_event_stream" reports a faulty subscribe resolver by RETURNING
an "ExecutionResult": "execute_subscription" wraps anything the resolver raises
in "located_error" (always a "GraphQLError"), and the caller catches
"GraphQLError" and returns it as a result. So a denying resolver never reaches
the transport's "except Exception".

One thing does: invalid non-dict variables raise a plain "TypeError" before
source construction. GraphQL-core 3.2 performed this check internally; the
transport adapter retains it for 3.3, whose Executor.build does not. A client
that sends an unparsed JSON string must receive an operation "error" frame
without closing the socket or disturbing its other operations.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("channels")

from graphql import (  # noqa: E402
    GraphQLBoolean,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)


def _schema() -> GraphQLSchema:
    """Build a one-field subscription schema with a valid subscribe entry.

    Returns:
        schema: A schema whose "onTick" subscription would stream if it were
            ever reached.
    """

    async def subscribe(root: Any, info: Any) -> Any:
        raise AssertionError("the subscribe entry must never be reached")

    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)}),
        subscription=GraphQLObjectType(
            "Subscription",
            {
                "onTick": GraphQLField(
                    GraphQLObjectType("Tick", {"id": GraphQLField(GraphQLString)}),
                    subscribe=subscribe,
                )
            },
        ),
    )


class _User:
    """A minimal authenticated user stand-in exposing the flags the consumer reads."""

    is_authenticated = True
    pk = 1


def _consumer() -> Any:
    """Build an acked WS consumer that records every frame it sends.

    Returns:
        consumer: A consumer whose "send_json" appends to "_sent" and whose
            "close" records the fact rather than touching a socket.
    """
    from django_graphex.subscriptions.transports import ws

    consumer = ws.subscription_ws_consumer(schema=_schema(), init_timeout=0.05)()
    consumer.scope = {"user": _User()}
    consumer._acked = True
    consumer._operations = {}
    consumer._sources = {}
    consumer._closing = False
    consumer._sent = []
    consumer._closed_with = []

    async def send_json(payload: dict[str, Any]) -> None:
        consumer._sent.append(payload)

    async def close(code: int | None = None) -> None:
        consumer._closed_with.append(code)

    consumer.send_json = send_json
    consumer.close = close
    return consumer


async def test_non_dict_variables_are_framed_and_leave_the_socket_alive() -> None:
    """Answer a non-dict "variables" payload with an error frame, not a close.

    Contract: the adapter must reject malformed variables before invoking the
    subscribe entry, and the consumer must frame that TypeError without killing
    other subscriptions multiplexed on the socket.
    """
    consumer = _consumer()

    await consumer._run_operation(
        "op1", {"query": "subscription { onTick { id } }", "variables": "not-a-dict"}
    )

    assert len(consumer._sent) == 1
    frame = consumer._sent[0]
    assert frame["type"] == "error"
    assert frame["id"] == "op1"
    assert "dictionary" in json.dumps(frame["payload"])
    assert consumer._closed_with == []
