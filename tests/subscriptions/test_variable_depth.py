"""Over-deep subscription variables answer the same coded error as HTTP."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLArgument,
    GraphQLField,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from tests.subscriptions._sse import sse_frames  # noqa: E402
from tests.subscriptions.test_wu13_sse_branch_coverage import (  # noqa: E402
    _json_request,
)
from tests.subscriptions.test_wu13_ws_branch_coverage import (  # noqa: E402
    _connect_and_ack,
    _make_communicator,
)

pytestmark = pytest.mark.django_db(transaction=True)

_QUERY = "subscription($v: Node) { tick(n: $v) }"
_MESSAGE = "Variables are nested too deeply to be coerced."


def _schema(subscribe_raises: bool = False) -> GraphQLSchema:
    """Build a schema with a recursive input type and a tick subscription.

    Args:
        subscribe_raises: Whether the subscribe resolver raises RecursionError.

    Returns:
        The schema.
    """
    node: GraphQLInputObjectType = GraphQLInputObjectType(
        "Node",
        lambda: {
            "all": GraphQLInputField(GraphQLList(node)),
            "leaf": GraphQLInputField(GraphQLString),
        },
    )

    async def subscribe(_root: Any, _info: Any, **_kwargs: Any) -> Any:
        if subscribe_raises:
            raise RecursionError("maximum recursion depth exceeded")

        async def events() -> Any:
            yield "ok"

        return events()

    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"a": GraphQLField(GraphQLString)}),
        subscription=GraphQLObjectType(
            "Subscription",
            {
                "tick": GraphQLField(
                    GraphQLString,
                    args={"n": GraphQLArgument(node)},
                    subscribe=subscribe,
                    resolve=lambda value, _info, **_kwargs: value,
                )
            },
        ),
    )


def _nested(depth: int) -> dict[str, Any]:
    """Nest a Node value to the given depth.

    Args:
        depth: How many "all" levels wrap the leaf.

    Returns:
        The variables mapping.
    """
    value: dict[str, Any] = {"leaf": "x"}
    for _ in range(depth):
        value = {"all": [value]}
    return {"v": value}


async def _sse_errors(
    monkeypatch: pytest.MonkeyPatch, schema: GraphQLSchema, depth: int
) -> list[dict[str, Any]]:
    """Run the subscription over SSE and return the framed errors.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        schema: The schema to serve.
        depth: Variable nesting depth.

    Returns:
        The errors of the single "next" frame.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=schema)
    response = await view(_json_request(_QUERY, variables=_nested(depth)))
    assert response.status_code == 200
    frames = [frame async for frame in sse_frames(response)]
    assert frames[-1] == b"event: complete\ndata: \n\n"
    event, data = frames[0].decode().strip().split("\n", 1)
    assert event == "event: next"
    return json.loads(data.removeprefix("data: "))["errors"]  # type: ignore[no-any-return]


async def _ws_errors(
    monkeypatch: pytest.MonkeyPatch, schema: GraphQLSchema, depth: int
) -> list[dict[str, Any]]:
    """Run the subscription over WebSocket and return the "error" frame errors.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        schema: The schema to serve.
        depth: Variable nesting depth.

    Returns:
        The payload of the "error" frame.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    communicator = _make_communicator(
        ws.subscription_ws_consumer(schema=schema), layer=layer
    )
    await _connect_and_ack(communicator)
    await communicator.send_json_to(
        {
            "id": "op",
            "type": "subscribe",
            "payload": {"query": _QUERY, "variables": _nested(depth)},
        }
    )
    frame = await communicator.receive_json_from(timeout=5)
    await communicator.disconnect()
    assert frame["type"] == "error"
    return frame["payload"]  # type: ignore[no-any-return]


@pytest.mark.parametrize("depth", (900, 3000))
@pytest.mark.parametrize("transport", ("sse", "ws"))
async def test_deep_variables_are_a_coded_client_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    depth: int,
) -> None:
    """Variables that exhaust the stack frame the HTTP error, unlogged.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
        depth: How deeply the variables are nested.
    """
    caplog.set_level(logging.DEBUG)
    run = _sse_errors if transport == "sse" else _ws_errors

    (error,) = await run(monkeypatch, _schema(), depth)

    assert error["message"] == _MESSAGE
    assert error["extensions"] == {"code": "QUERY_TOO_DEEP"}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("transport", ("sse", "ws"))
async def test_recursion_error_in_a_subscribe_resolver_is_not_a_client_error(
    monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    """A RecursionError the subscribe resolver raises is never QUERY_TOO_DEEP.

    It is a located resolver error, framed like any other resolver exception.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        transport: The transport under test.
    """
    run = _sse_errors if transport == "sse" else _ws_errors

    (error,) = await run(monkeypatch, _schema(subscribe_raises=True), 1)

    assert "QUERY_TOO_DEEP" not in json.dumps(error)
    assert error["path"] == ["tick"]


async def test_ws_over_deep_json_frame_closes_with_bad_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JSON frame that exhausts the decoder closes 4400 instead of crashing.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    communicator = _make_communicator(
        ws.subscription_ws_consumer(schema=_schema()), layer=layer
    )
    await _connect_and_ack(communicator)
    await communicator.send_to(text_data="[" * 100_000)
    closed = await communicator.receive_output(timeout=5)
    assert closed["type"] == "websocket.close"
    assert closed["code"] == 4400
