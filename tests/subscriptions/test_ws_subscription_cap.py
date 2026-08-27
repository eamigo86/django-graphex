# -*- coding: utf-8 -*-
"""MAX_SUBSCRIPTIONS_PER_CONNECTION — the WS per-socket subscription cap.

A graphql-transport-ws socket multiplexes N operations, and every started
operation joins its own channel-layer group: an unbounded "_operations"
registry let ONE socket open hundreds of live subscriptions (and hundreds of
"group_add" calls) at no cost to the client. This module pins the cap that
bounds it, mirroring the HTTP view's "MAX_BATCH_SIZE" contract:

  * a subscribe at the limit is accepted, the one past it is rejected;
  * the rejection is the transport's own "error{id, payload}" frame — the
    socket and every running operation SURVIVE it;
  * an operation that completes frees its slot (an off-by-one here would turn
    the cap into a slow leak that bricks the socket);
  * "None" disables the cap entirely.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from django.test import override_settings

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402

# A Channels consumer touches the DB connection registry on every dispatched
# message; transaction=True is required (the consumer runs off the test txn).
pytestmark = pytest.mark.django_db(transaction=True)


# The node types Post's relation graph needs, and the assembled schema, are
# built ONCE process-wide by the shared module (see its docstring).
from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402


class _User:
    """A minimal authenticated user stand-in."""

    def __init__(self) -> None:
        """Report the socket as authenticated with a stable pk."""
        self.is_authenticated = True
        self.pk = 1


_SUB_QUERY = "subscription { post(action: CREATE) { id title } }"


def _notify(group: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a producer-shaped "subscription.notify" envelope (bindings.py).

    Args:
        group: The channel-layer group name the message targets.
        data: The serialized payload data to embed in the message.

    Returns:
        message: The assembled notify message dict.
    """
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": 1,
        "payload": {"action": "create", "model": "tests.post", "data": data},
    }


_FLAT_POST = {
    "id": 1,
    "title": "hello",
    "body": "",
    "views": 0,
    "author": 7,
    "category": 9,
    "tags": [3],
    "co_authors": [7, 8],
}


def _make_communicator(consumer_app: Any, layer: Any) -> WebsocketCommunicator:
    """Build a WebsocketCommunicator for the graphql-transport-ws subprotocol.

    Args:
        consumer_app: The consumer class or ASGI app to communicate with.
        layer: The channel layer attached to the connection scope.

    Returns:
        communicator: The configured WebsocketCommunicator, not yet connected.
    """
    application = (
        consumer_app.as_asgi() if hasattr(consumer_app, "as_asgi") else consumer_app
    )
    communicator = WebsocketCommunicator(
        application, "/graphql/", subprotocols=["graphql-transport-ws"]
    )
    communicator.scope["user"] = _User()
    communicator.scope["channel_layer"] = layer
    return communicator


async def _connect_and_ack(
    communicator: WebsocketCommunicator,
) -> WebsocketCommunicator:
    """Open the socket and complete the connection_init -> connection_ack handshake.

    Args:
        communicator: The communicator to connect and handshake.

    Returns:
        communicator: The same communicator, now connected and acknowledged.
    """
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=2)
    assert ack["type"] == "connection_ack"
    return communicator


def _app(layer: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a subscription WS consumer app patched to use the given layer.

    Args:
        layer: The channel layer get_channel_layer should resolve to.
        monkeypatch: The pytest fixture used to stub the channel layer.

    Returns:
        app: The consumer class built by subscription_ws_consumer.
    """
    from django_graphex.subscriptions.transports import ws

    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    return ws.subscription_ws_consumer(schema=build_native_schema())


async def _subscribe_and_wait(
    ws: Any, communicator: WebsocketCommunicator, op_id: str, *, timeout: float = 2.0
) -> str:
    """Send a subscribe for "op_id" and poll until its source joined a group.

    Waiting for the joined group is what makes the cap tests deterministic: the
    slot is only truly held once the operation task has reached its source.

    Args:
        ws: The transports.ws module (carrying the live-consumer registry).
        communicator: The communicator owning the socket.
        op_id: The operation id to subscribe.
        timeout: The maximum time in seconds to poll before failing.

    Returns:
        group: The first group name the operation's source joined.

    Raises:
        AssertionError: When the operation never starts a source in time.
    """
    await communicator.send_json_to(
        {"id": op_id, "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        consumer = ws.get_live_consumer(communicator.scope)
        if consumer is not None:
            source = consumer.started_source(op_id)
            if source is not None and source.joined_groups:
                return source.joined_groups[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"operation {op_id!r} never started a source in {timeout}s")


# ---------------------------------------------------------------------------
# The boundary: N accepted, N+1 rejected
# ---------------------------------------------------------------------------


async def test_subscribe_at_the_limit_is_accepted_and_the_next_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Nth subscribe must run and the N+1th must get an error frame.

    Contract: this test ships broken if a socket can hold more concurrent
    operations than MAX_SUBSCRIPTIONS_PER_CONNECTION allows.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)

    with override_settings(DJANGO_GRAPHEX={"MAX_SUBSCRIPTIONS_PER_CONNECTION": 2}):
        communicator = _make_communicator(app, layer)
        await _connect_and_ack(communicator)

        await _subscribe_and_wait(ws, communicator, "op1")
        await _subscribe_and_wait(ws, communicator, "op2")

        await communicator.send_json_to(
            {"id": "op3", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
        )
        rejection = await communicator.receive_json_from(timeout=2)
        assert rejection["type"] == "error"
        assert rejection["id"] == "op3"
        message = rejection["payload"][0]["message"]
        assert "MAX_SUBSCRIPTIONS_PER_CONNECTION" in message
        assert "2" in message

        consumer = ws.get_live_consumer(communicator.scope)
        assert consumer.operation_ids() == {"op1", "op2"}

        await communicator.disconnect()


async def test_socket_survives_a_rejected_subscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected subscribe must leave the socket and its streams alive.

    Contract: this test ships broken if hitting the cap closes the connection
    or kills the subscriptions the client already paid for.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)

    with override_settings(DJANGO_GRAPHEX={"MAX_SUBSCRIPTIONS_PER_CONNECTION": 1}):
        communicator = _make_communicator(app, layer)
        await _connect_and_ack(communicator)

        group = await _subscribe_and_wait(ws, communicator, "op1")

        await communicator.send_json_to(
            {"id": "op2", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
        )
        rejection = await communicator.receive_json_from(timeout=2)
        assert rejection["type"] == "error"

        # The socket still answers protocol frames...
        await communicator.send_json_to({"type": "ping"})
        assert (await communicator.receive_json_from(timeout=2))["type"] == "pong"

        # ...and the pre-existing subscription still delivers.
        await layer.group_send(group, _notify(group, _FLAT_POST))
        msg = await communicator.receive_json_from(timeout=2)
        assert msg["type"] == "next"
        assert msg["id"] == "op1"

        await communicator.disconnect()


async def test_completed_operation_frees_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completing an operation must let a new subscribe take its place.

    Contract: this test ships broken if a finished operation keeps holding its
    slot — the cap would leak downwards until the socket accepts nothing.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)

    with override_settings(DJANGO_GRAPHEX={"MAX_SUBSCRIPTIONS_PER_CONNECTION": 1}):
        communicator = _make_communicator(app, layer)
        await _connect_and_ack(communicator)

        await _subscribe_and_wait(ws, communicator, "op1")
        await communicator.send_json_to({"id": "op1", "type": "complete"})

        # The slot is free again: this subscribe must START, not be rejected.
        await _subscribe_and_wait(ws, communicator, "op2")
        consumer = ws.get_live_consumer(communicator.scope)
        assert consumer.operation_ids() == {"op2"}
        assert await communicator.receive_nothing(timeout=0.2)

        await communicator.disconnect()


async def test_none_disables_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """MAX_SUBSCRIPTIONS_PER_CONNECTION=None must accept any number of ops.

    Contract: this test ships broken if the None escape hatch stops disabling
    the guard (mirroring MAX_BATCH_SIZE=None on the HTTP side).

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)

    with override_settings(DJANGO_GRAPHEX={"MAX_SUBSCRIPTIONS_PER_CONNECTION": None}):
        communicator = _make_communicator(app, layer)
        await _connect_and_ack(communicator)

        for op_id in ("op1", "op2", "op3", "op4"):
            await _subscribe_and_wait(ws, communicator, op_id)

        consumer = ws.get_live_consumer(communicator.scope)
        assert consumer.operation_ids() == {"op1", "op2", "op3", "op4"}
        assert await communicator.receive_nothing(timeout=0.2)

        await communicator.disconnect()


def test_default_cap_ships_switched_on() -> None:
    """The shipped default must be a real number, not None.

    Contract: this test ships broken if the cap regresses to opt-in — an
    unconfigured deployment would be unbounded again.
    """
    from django_graphex.settings import graphql_api_settings

    assert graphql_api_settings.MAX_SUBSCRIPTIONS_PER_CONNECTION == 50
