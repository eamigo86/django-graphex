# -*- coding: utf-8 -*-
"""Malformed-but-decodable bodies must be CLIENT errors on both transports.

Two surfaces assume a mapping the moment JSON decoding succeeds:

  * SSE — "_read_request_body" calls "body.get(...)" on whatever
    "json.loads" returned. A JSON body that is a list, a bare string or
    "null" decodes fine and then raises "AttributeError", so the endpoint
    answers 500 for a shape the HTTP view already classifies as a 400
    ("views.py": "The received data is not a valid JSON query."). SSE was the
    ONE surface in the library answering 500 for it. A deeply nested body is
    the same class of defect through a different door: "json.loads" raises
    "RecursionError", which the decode guard did not catch.
  * WS — "_on_subscribe" forwarded a non-mapping "payload" straight into
    "_run_operation", where "payload.get('query')" raised inside the operation
    task. The task's exception was logged and DROPPED: no "error" frame, no
    "complete" frame, nothing on the wire. A protocol violation that produces
    NO response is worse than one that errors, because the client cannot tell
    it apart from a slow server and waits forever.

Both rejections must leave the surface usable: the SSE endpoint keeps serving
well-formed requests, and the WS socket keeps its other operations running.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import pytest
from django.test import RequestFactory

pytest.importorskip("channels")

from graphql import (  # noqa: E402
    GraphQLBoolean,
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.subscriptions.transports.sse import (  # noqa: E402
    subscription_sse_view,
)

_SUB_QUERY = "subscription { onTick { id } }"

#: A JSON array/string/null all decode cleanly and then fail the mapping
#: assumption — the exact shapes the HTTP view answers 400 for.
_NON_OBJECT_BODIES = ("[1, 2, 3]", '"x"', "null", "42", "true")

#: Deep enough to blow the interpreter's recursion limit inside "json.loads".
_DEEPLY_NESTED_BODY = "[" * 10_000 + "]" * 10_000


class _User:
    """A minimal authenticated user stand-in exposing the flags both transports read."""

    is_authenticated = True
    pk = 1


def _denying_schema() -> GraphQLSchema:
    """Build a one-field subscription schema whose subscribe entry always denies.

    Denying keeps a well-formed request short (no channel layer needed) while
    still proving it travelled the whole parse/validate/subscribe path.

    Returns:
        A schema with a single "onTick" subscription field.
    """

    async def subscribe(root: Any, info: Any) -> Any:
        raise GraphQLError("denied")

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


async def _post_json(body: str) -> Any:
    """POST a raw JSON body at the SSE view and return its response.

    Args:
        body: The raw request body to send as "application/json".

    Returns:
        The view's HTTP response.
    """
    request = RequestFactory().post(
        "/subscriptions/sse", data=body, content_type="application/json"
    )
    request.user = _User()
    return await subscription_sse_view(schema=_denying_schema())(request)


def _consumer() -> Any:
    """Build an acked WS consumer that records every frame it sends.

    Returns:
        A consumer whose "send_json" appends to "_sent" and whose "close"
        records the code rather than touching a socket.
    """
    from django_graphex.subscriptions.transports import ws

    consumer = ws.subscription_ws_consumer(
        schema=_denying_schema(), init_timeout=0.05
    )()
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


async def _drain(consumer: Any, op_id: str) -> None:
    """Await the operation task a subscribe may have spawned, swallowing its error.

    The pre-fix behaviour spawns a task that dies inside "_run_operation"; the
    fixed behaviour spawns nothing. Draining covers both so the assertions
    observe the frames actually sent either way.

    Args:
        consumer: The consumer whose operation registry to drain.
        op_id: The operation id the subscribe used.
    """
    task = consumer._operations.get(op_id)
    if task is not None:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await task


@pytest.mark.parametrize("body", _NON_OBJECT_BODIES)
async def test_a_non_object_json_body_is_a_client_error(body: str) -> None:
    """Answer a decodable non-object JSON body with 400, not 500.

    Contract: the HTTP view already refuses this exact shape with 400 and a
    named message. Without the guard "body.get(...)" raises "AttributeError"
    and SSE becomes the one endpoint in the library that answers 500 for a
    body the rest of it calls a client error.

    Args:
        body: The raw non-object JSON body under test.
    """
    response = await _post_json(body)

    assert response.status_code == 400
    assert "not a valid JSON query" in response.content.decode()


async def test_a_deeply_nested_json_body_is_a_client_error() -> None:
    """Answer a body that blows the decoder's recursion limit with 400, not 500.

    Contract: "json.loads" raises "RecursionError", which is not a subclass of
    "ValueError" — so the decode guard let it escape the view and Django
    turned a hostile-but-cheap body into a 500.
    """
    response = await _post_json(_DEEPLY_NESTED_BODY)

    assert response.status_code == 400


async def test_a_well_formed_request_still_streams() -> None:
    """Keep serving a well-formed subscription request.

    Contract: the guard must reject a shape, not tighten the endpoint — a
    normal JSON subscription POST still gets its 200 "text/event-stream".
    """
    response = await _post_json(json.dumps({"query": _SUB_QUERY}))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")


async def test_a_non_object_ws_subscribe_payload_is_answered() -> None:
    """Answer a non-mapping "subscribe" payload with an error frame.

    Contract: without the guard "payload.get('query')" raises inside the
    operation task, the exception is logged and dropped, and the client gets
    NOTHING back — indistinguishable from a slow server, so it waits forever.
    """
    consumer = _consumer()

    await consumer._on_subscribe({"id": "op1", "payload": [1, 2, 3]})
    await _drain(consumer, "op1")

    assert len(consumer._sent) == 1, "the client got no frame at all"
    frame = consumer._sent[0]
    assert frame["type"] == "error"
    assert frame["id"] == "op1"
    assert "object" in json.dumps(frame["payload"])


async def test_a_rejected_ws_payload_leaves_the_socket_alive() -> None:
    """Keep the socket and its later operations working after the rejection.

    Contract: a malformed payload is one operation's problem. The socket must
    not close, and the next well-formed subscribe must travel the whole
    parse/validate/subscribe path (here: to the schema's deny).
    """
    consumer = _consumer()

    await consumer._on_subscribe({"id": "bad", "payload": "not-an-object"})
    await _drain(consumer, "bad")
    await consumer._on_subscribe({"id": "good", "payload": {"query": _SUB_QUERY}})
    await _drain(consumer, "good")

    assert consumer._closed_with == []
    assert [frame["id"] for frame in consumer._sent] == ["bad", "good"]
    assert "denied" in json.dumps(consumer._sent[1]["payload"])
