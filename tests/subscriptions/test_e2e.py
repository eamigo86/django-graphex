# -*- coding: utf-8 -*-
"""T-E2E / T-CONCURRENCY: open WS -> subscribe -> save/delete -> assert frame."""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from .helpers import run_subscribe
from .schema import AppDemultiplexer, UserSubscription

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def _connect():
    communicator = WebsocketCommunicator(AppDemultiplexer.as_asgi(), "/ws/")
    connected, _ = await communicator.connect()
    assert connected
    handshake = await communicator.receive_json_from()
    return communicator, handshake["channel_id"]


@database_sync_to_async
def _create_user(model, **kwargs):
    return model.objects.create(**kwargs)


@database_sync_to_async
def _save(instance):
    instance.save()


@database_sync_to_async
def _delete(instance):
    instance.delete()


async def test_subscribe_update_by_id_delivers_frame(django_user_model):
    communicator, channel = await _connect()
    user = await _create_user(
        django_user_model, username="trinity", email="t@example.com"
    )

    await run_subscribe(
        UserSubscription,
        channel_id=channel,
        action="update",
        operation="subscribe",
        id=user.pk,
        data=["username"],
    )

    user.username = "trinity2"
    await _save(user)

    frame = await communicator.receive_json_from()
    assert frame["stream"] == "users"
    assert frame["payload"]["action"] == "update"
    assert frame["payload"]["model"] == "auth.user"
    assert frame["payload"]["data"] == {"username": "trinity2"}

    await communicator.disconnect()


async def test_create_action_delivers_only_on_create(django_user_model):
    communicator, channel = await _connect()
    await run_subscribe(
        UserSubscription,
        channel_id=channel,
        action="create",
        operation="subscribe",
    )

    await _create_user(django_user_model, username="morpheus")
    frame = await communicator.receive_json_from()
    assert frame["payload"]["action"] == "create"
    assert frame["payload"]["data"]["username"] == "morpheus"

    await communicator.disconnect()


async def test_delete_action_delivers_on_delete(django_user_model):
    communicator, channel = await _connect()
    user = await _create_user(django_user_model, username="smith")
    await run_subscribe(
        UserSubscription,
        channel_id=channel,
        action="delete",
        operation="subscribe",
        id=user.pk,
    )

    await _delete(user)
    frame = await communicator.receive_json_from()
    assert frame["payload"]["action"] == "delete"

    await communicator.disconnect()


async def test_unsubscribe_stops_delivery(django_user_model):
    communicator, channel = await _connect()
    user = await _create_user(django_user_model, username="cypher")
    await run_subscribe(
        UserSubscription,
        channel_id=channel,
        action="update",
        operation="subscribe",
        id=user.pk,
    )
    await run_subscribe(
        UserSubscription,
        channel_id=channel,
        action="update",
        operation="unsubscribe",
        id=user.pk,
    )

    user.username = "cypher2"
    await _save(user)

    assert await communicator.receive_nothing(timeout=0.3) is True
    await communicator.disconnect()


async def test_filter_delivers_only_matching_instances(django_user_model):
    """AC1/AC3: an equality ``filters`` only delivers matching changes."""
    communicator, channel = await _connect()
    await run_subscribe(
        UserSubscription,
        channel_id=channel,
        action="create",
        operation="subscribe",
        filters={"username": "neo"},
    )

    # Non-matching create -> dropped (decided in memory, no delivery).
    await _create_user(django_user_model, username="smith")
    assert await communicator.receive_nothing(timeout=0.3) is True

    # Matching create -> delivered.
    await _create_user(django_user_model, username="neo")
    frame = await communicator.receive_json_from()
    assert frame["payload"]["data"]["username"] == "neo"

    await communicator.disconnect()


async def test_filter_lookup_falls_back_to_db(django_user_model):
    """AC2: a lookup filter (``__icontains``) is honored via the DB fallback."""
    communicator, channel = await _connect()
    await run_subscribe(
        UserSubscription,
        channel_id=channel,
        action="create",
        operation="subscribe",
        filters={"username__icontains": "or"},
    )

    await _create_user(django_user_model, username="neo")
    assert await communicator.receive_nothing(timeout=0.3) is True

    await _create_user(django_user_model, username="morpheus")
    frame = await communicator.receive_json_from()
    assert frame["payload"]["data"]["username"] == "morpheus"

    await communicator.disconnect()


async def test_filters_are_per_connection(django_user_model):
    """AC4: same group, different filters -> each connection gets only its own."""
    comm_a, chan_a = await _connect()
    comm_b, chan_b = await _connect()

    await run_subscribe(
        UserSubscription,
        channel_id=chan_a,
        action="create",
        operation="subscribe",
        filters={"username": "neo"},
    )
    await run_subscribe(
        UserSubscription,
        channel_id=chan_b,
        action="create",
        operation="subscribe",
        filters={"username": "trinity"},
    )

    await _create_user(django_user_model, username="neo")

    frame_a = await comm_a.receive_json_from()
    assert frame_a["payload"]["data"]["username"] == "neo"
    assert await comm_b.receive_nothing(timeout=0.3) is True

    await comm_a.disconnect()
    await comm_b.disconnect()


async def test_two_connections_get_their_own_projection(django_user_model):
    """AC8: same group, different ``data`` -> independent per-connection output."""
    comm_a, chan_a = await _connect()
    comm_b, chan_b = await _connect()

    # Both subscribe to *all* updates (the shared "auth.user-update" group) but
    # request different field projections.
    await run_subscribe(
        UserSubscription,
        channel_id=chan_a,
        action="update",
        operation="subscribe",
        data=["username"],
    )
    await run_subscribe(
        UserSubscription,
        channel_id=chan_b,
        action="update",
        operation="subscribe",
        data=["email"],
    )

    user = await _create_user(
        django_user_model, username="oracle", email="oracle@example.com"
    )
    user.username = "oracle2"
    await _save(user)

    frame_a = await comm_a.receive_json_from()
    frame_b = await comm_b.receive_json_from()

    assert frame_a["payload"]["data"] == {"username": "oracle2"}
    assert frame_b["payload"]["data"] == {"email": "oracle@example.com"}

    await comm_a.disconnect()
    await comm_b.disconnect()
