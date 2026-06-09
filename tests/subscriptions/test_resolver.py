# -*- coding: utf-8 -*-
"""T-RESOLVER: the async subscribe generator joins/leaves groups + control msgs."""

import pytest
from channels.layers import get_channel_layer

from .helpers import run_subscribe
from .schema import UserSubscription

pytestmark = pytest.mark.asyncio


async def test_subscribe_yields_single_confirmation():
    result = await run_subscribe(
        UserSubscription,
        channel_id="chan-1",
        action="create",
        operation="subscribe",
        data=["username"],
    )
    assert result.ok is True
    assert result.error is None
    assert result.stream == "users"
    assert result.action == "create"
    assert result.operation == "subscribe"


async def test_subscribe_adds_channel_to_group_and_registers_fields():
    channel_layer = get_channel_layer()
    await run_subscribe(
        UserSubscription,
        channel_id="chan-2",
        action="update",
        operation="subscribe",
        data=["username"],
    )

    # A register control message is delivered to the connection's channel.
    register = await channel_layer.receive("chan-2")
    assert register["type"] == "subscription.register"
    assert register["group"] == "auth.user-update"
    assert register["fields"] == ["username"]

    # The channel is now a member of the group: a group_send reaches it.
    await channel_layer.group_send(
        "auth.user-update", {"type": "subscription.notify", "payload": {}}
    )
    delivered = await channel_layer.receive("chan-2")
    assert delivered["type"] == "subscription.notify"


async def test_subscribe_all_actions_joins_three_groups():
    channel_layer = get_channel_layer()
    await run_subscribe(
        UserSubscription,
        channel_id="chan-3",
        action="all_actions",
        operation="subscribe",
    )
    groups = set()
    for _ in range(3):
        message = await channel_layer.receive("chan-3")
        assert message["type"] == "subscription.register"
        groups.add(message["group"])
    assert groups == {
        "auth.user-create",
        "auth.user-update",
        "auth.user-delete",
    }


async def test_unsubscribe_discards_and_deregisters():
    channel_layer = get_channel_layer()
    await run_subscribe(
        UserSubscription,
        channel_id="chan-4",
        action="create",
        operation="subscribe",
    )
    # drop the register message
    await channel_layer.receive("chan-4")

    await run_subscribe(
        UserSubscription,
        channel_id="chan-4",
        action="create",
        operation="unsubscribe",
    )
    deregister = await channel_layer.receive("chan-4")
    assert deregister["type"] == "subscription.deregister"
    assert deregister["group"] == "auth.user-create"


async def test_subscribe_reports_error_without_channel_layer(monkeypatch):
    monkeypatch.setattr(
        "django_graphex.subscriptions.subscription.get_channel_layer",
        lambda: None,
    )
    result = await run_subscribe(
        UserSubscription,
        channel_id="chan-5",
        action="create",
        operation="subscribe",
    )
    assert result.ok is False
    assert "channel layer" in result.error.lower()
