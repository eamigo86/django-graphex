# -*- coding: utf-8 -*-
"""T-CONSUMER: handshake and the register / notify / deregister handlers."""

import pytest
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator

from .schema import AppDemultiplexer

# Channels' dispatch() calls close_old_connections() on every message, which
# touches the DB connection, so communicator tests need DB access enabled.
pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def test_connect_emits_handshake_frame():
    communicator = WebsocketCommunicator(AppDemultiplexer.as_asgi(), "/ws/")
    connected, _ = await communicator.connect()
    assert connected

    handshake = await communicator.receive_json_from()
    assert handshake["connect"] == "success"
    assert isinstance(handshake["channel_id"], str)
    assert handshake["channel_id"]

    await communicator.disconnect()


async def test_register_then_group_membership_and_projection():
    communicator = WebsocketCommunicator(AppDemultiplexer.as_asgi(), "/ws/")
    await communicator.connect()
    handshake = await communicator.receive_json_from()
    channel = handshake["channel_id"]
    channel_layer = get_channel_layer()

    await channel_layer.group_add("auth.user-update", channel)
    await channel_layer.send(
        channel,
        {
            "type": "subscription.register",
            "group": "auth.user-update",
            "fields": ["username"],
        },
    )
    await channel_layer.group_send(
        "auth.user-update",
        {
            "type": "subscription.notify",
            "stream": "users",
            "group": "auth.user-update",
            "payload": {
                "action": "update",
                "model": "auth.user",
                "data": {"id": 1, "username": "neo", "email": "neo@example.com"},
            },
        },
    )
    frame = await communicator.receive_json_from()
    assert frame == {
        "stream": "users",
        "payload": {
            "action": "update",
            "model": "auth.user",
            "data": {"username": "neo"},
        },
    }

    # After deregister the projection bookkeeping is dropped (full payload again).
    await channel_layer.send(
        channel, {"type": "subscription.deregister", "group": "auth.user-update"}
    )
    await channel_layer.group_send(
        "auth.user-update",
        {
            "type": "subscription.notify",
            "stream": "users",
            "group": "auth.user-update",
            "payload": {
                "action": "update",
                "model": "auth.user",
                "data": {"id": 1, "username": "neo", "email": "neo@example.com"},
            },
        },
    )
    frame = await communicator.receive_json_from()
    assert frame["payload"]["data"] == {
        "id": 1,
        "username": "neo",
        "email": "neo@example.com",
    }

    await communicator.disconnect()
