# -*- coding: utf-8 -*-
"""DjangoModelType ↔ subscriptions integration (define once -> query/mutation/subscription)."""

from types import SimpleNamespace

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.core.exceptions import ImproperlyConfigured

from django_graphex import DjangoModelType, IsAuthenticated
from django_graphex.subscriptions import (
    GraphqlAPIDemultiplexer,
    Subscription,
    SubscriptionField,
)
from tests.models import HookModel

from .helpers import run_subscribe


class HookModelType(DjangoModelType):
    class Meta:
        model = HookModel
        stream = "hooks"
        serialize_data = True


class NoStreamType(DjangoModelType):
    class Meta:
        model = HookModel  # no stream -> subscriptions off


class HookDemultiplexer(GraphqlAPIDemultiplexer):
    # Iterable (set) form: the stream is derived from each type's Meta.stream.
    subscriptions = {HookModelType}


def test_subscription_type_built_from_meta():
    sub = HookModelType.subscription_type()
    assert issubclass(sub, Subscription)
    assert sub._meta.stream == "hooks"
    assert sub._meta.model is HookModel
    assert sub._meta.serialize_data is True
    # Cached: the same generated class is reused.
    assert HookModelType.subscription_type() is sub


def test_subscription_field_returns_field():
    assert isinstance(HookModelType.SubscriptionField(), SubscriptionField)


def test_missing_stream_raises():
    with pytest.raises(ImproperlyConfigured):
        NoStreamType.subscription_type()


def test_demultiplexer_accepts_iterable_and_derives_stream():
    resolved = HookDemultiplexer()._resolved_subscriptions()
    assert set(resolved) == {"hooks"}
    assert resolved["hooks"] is HookModelType.subscription_type()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_generated_subscription_delivers():
    communicator = WebsocketCommunicator(HookDemultiplexer.as_asgi(), "/ws/")
    connected, _ = await communicator.connect()
    assert connected
    handshake = await communicator.receive_json_from()

    await run_subscribe(
        HookModelType.subscription_type(),
        channel_id=handshake["channel_id"],
        action="create",
        operation="subscribe",
    )

    await database_sync_to_async(HookModel.objects.create)(text="hi")

    frame = await communicator.receive_json_from()
    assert frame["stream"] == "hooks"
    assert frame["payload"]["action"] == "create"
    assert frame["payload"]["data"]["text"] == "hi"

    await communicator.disconnect()


def _info(user):
    return SimpleNamespace(context=SimpleNamespace(user=user))


class _GatedType(DjangoModelType):
    permission_classes = [IsAuthenticated]

    class Meta:
        model = HookModel
        stream = "gated"


class _ScopedType(DjangoModelType):
    class Meta:
        model = HookModel
        stream = "scoped"

    @classmethod
    def subscription_scope(cls, info, **kwargs):
        # Server-forced scope: only deliver rows whose text == "keep".
        return {"text": "keep"}


class _ScopedDemux(GraphqlAPIDemultiplexer):
    subscriptions = {_ScopedType}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_permission_gate_blocks_unauthorized_subscribe():
    """authorize(info, 'subscribe') runs at registration via permission_classes."""
    sub = _GatedType.subscription_type()

    denied = await run_subscribe(
        sub,
        info=_info(SimpleNamespace(is_authenticated=False)),
        channel_id="c1",
        action="create",
        operation="subscribe",
    )
    assert denied.ok is False and denied.error

    allowed = await run_subscribe(
        sub,
        info=_info(SimpleNamespace(is_authenticated=True)),
        channel_id="c1",
        action="create",
        operation="subscribe",
    )
    assert allowed.ok is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_subscription_scope_is_enforced_at_delivery():
    """A server-forced subscription_scope drops non-matching notifications."""
    communicator = WebsocketCommunicator(_ScopedDemux.as_asgi(), "/ws/")
    connected, _ = await communicator.connect()
    assert connected
    handshake = await communicator.receive_json_from()

    await run_subscribe(
        _ScopedType.subscription_type(),
        info=_info(SimpleNamespace(is_authenticated=True)),
        channel_id=handshake["channel_id"],
        action="create",
        operation="subscribe",
        # A conflicting client filter must NOT widen the forced scope: the
        # server's {text: "keep"} wins, so "drop" is still dropped below.
        filters={"text": "drop"},
    )

    # Out of scope -> dropped (decided in memory against the payload).
    await database_sync_to_async(HookModel.objects.create)(text="drop")
    assert await communicator.receive_nothing(timeout=0.3) is True

    # In scope -> delivered.
    await database_sync_to_async(HookModel.objects.create)(text="keep")
    frame = await communicator.receive_json_from()
    assert frame["payload"]["data"]["text"] == "keep"

    await communicator.disconnect()
