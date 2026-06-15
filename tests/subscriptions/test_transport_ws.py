# -*- coding: utf-8 -*-
"""WU9 — graphql-transport-ws WebSocket transport adapter (transports/ws.py).

The WS transport is the SECOND (heavier) engine validator (design §7): a Channels
``AsyncJsonWebsocketConsumer`` speaking the graphql-transport-ws protocol over a
SINGLE socket that multiplexes N operations. Both transports drive the SAME
serialize-once engine (``create_source_event_stream`` → ``ChannelLayerSource`` →
WU5 ``drive_subscription`` over the flat snake-pk dict).

Conformance scenarios covered (the WU9 gate):

  1. handshake: ``connection_init`` → ``connection_ack``.
  2. subscribe → ``next`` (a broadcast → ``next{id, payload}`` with serialize-once
     flat-pk data per WU7) → ``complete``.
  3. N operations multiplexed over ONE socket (two ids, independent streams).
  4. ``complete{id}`` from the client cancels ONLY that id's task + ``group_discard``s
     its groups (the other id keeps streaming).
  5. disconnect cancels ALL tasks + ``group_discard``s all (no ghost subscriber).
  6. ``ping`` → ``pong``.
  7. 4408 ``connection_init`` timeout.
  8. 4409 duplicate subscribe id.
  9. 4401 subscribe before ack (and/or unauthorized). Plus 4400 malformed message.

Delivery-path invariants: ``assertNumQueries(0)`` (serialize-once snake closure),
authorize-deny handled (error frame / close), ``add_done_callback`` per-task
cleanup fires on abnormal task end.

All native assertions are gated behind ``GDX_BACKEND=native`` and skipped under
graphene (the bespoke transport stays UNCHANGED until WU11).
"""
from __future__ import annotations

import asyncio
import os

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402

from tests.models import Post  # noqa: E402

_NATIVE = os.environ.get("GDX_BACKEND", "graphene") == "native"

native_only = pytest.mark.skipif(
    not _NATIVE, reason="native WS transport (GDX_BACKEND=native)"
)

# A Channels AsyncJsonWebsocketConsumer touches the DB connection registry on
# EVERY dispatched message (``aclose_old_connections`` in ``dispatch``), so every
# consumer test needs DB access — the same module-level mark the bespoke consumer
# tests use (``test_consumer.py``). ``transaction=True`` is required because the
# consumer's DB access happens in a worker thread off the test's transaction.
pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# Helpers — node types + a native subscription schema mounting a PostModelType
# SubscriptionField (mirrors test_transport_sse's module-scope registration; a
# DjangoObjectType is identity-stable, per-test registration pollutes the shared
# output registry).
# ---------------------------------------------------------------------------

if _NATIVE:
    from django_graphex.types import DjangoObjectType as _DOT

    class _TagT(_DOT):
        class Meta:
            model = __import__("tests.models", fromlist=["Tag"]).Tag

    class _CategoryT(_DOT):
        class Meta:
            model = __import__("tests.models", fromlist=["Category"]).Category

    class _AuthorT(_DOT):
        class Meta:
            model = __import__("tests.models", fromlist=["Author"]).Author

    class _PostT(_DOT):
        class Meta:
            model = Post


def _build_native_schema():
    """Assemble a native subscription schema (PostModelType.SubscriptionField)."""
    import graphene

    from django_graphex import DjangoModelType
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema

    class PostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            serialize_data = True

    class Query(graphene.ObjectType):
        ok = graphene.Boolean()

    class SubscriptionRoot(graphene.ObjectType):
        post = PostModelType.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=Query, subscription=SubscriptionRoot)
    return schema.graphql_schema


def _notify(group: str, data: dict, *, action: str = "create", pk=1) -> dict:
    """Build a producer-shaped ``subscription.notify`` envelope (bindings.py)."""
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": pk,
        "payload": {"action": action, "model": "tests.post", "data": data},
    }


class _User:
    """A minimal authenticated/anonymous user stand-in."""

    def __init__(self, *, authenticated: bool = True):
        self.is_authenticated = authenticated
        self.pk = 1 if authenticated else None


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

_SUB_QUERY = "subscription { post(action: CREATE) { id title author tags } }"


def _make_communicator(consumer_app, *, authenticated: bool = True, layer=None):
    """Build a WebsocketCommunicator for the graphql-transport-ws subprotocol.

    Mirrors how a real client connects: the subprotocol header advertises
    ``graphql-transport-ws`` and the scope carries the authenticated user (the
    auth boundary the WS consumer reads from ``self.scope['user']``).
    """
    application = (
        consumer_app.as_asgi() if hasattr(consumer_app, "as_asgi") else consumer_app
    )
    communicator = WebsocketCommunicator(
        application,
        "/graphql/",
        subprotocols=["graphql-transport-ws"],
    )
    communicator.scope["user"] = _User(authenticated=authenticated)
    if layer is not None:
        communicator.scope["channel_layer"] = layer
    return communicator


async def _connect_and_ack(communicator):
    """Open the socket and complete the connection_init → connection_ack handshake."""
    connected, _subprotocol = await communicator.connect()
    assert connected, "the WS handshake (accept) must succeed"
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=2)
    assert ack["type"] == "connection_ack"
    return communicator


def _consumer_for(ws, communicator):
    """Resolve the live consumer instance backing *communicator*.

    The WS module records each connected consumer in a registry keyed by the
    scope object identity (each communicator owns a unique ``scope`` dict), so a
    test can introspect the live per-id operation registry / started sources.
    """
    consumer = ws.get_live_consumer(communicator.scope)
    assert consumer is not None, "no live consumer registered for this socket"
    return consumer


async def _await_started_group(ws, communicator, op_id, *, timeout=2.0):
    """Poll until operation *op_id*'s source has joined a group; return the group.

    The subscribe handler starts a task that runs the engine's subscribe entry
    (joining the Channels group); this polls the live consumer's registry until
    the source is started, then returns its first joined group name.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        consumer = ws.get_live_consumer(communicator.scope)
        if consumer is not None:
            source = consumer.started_source(op_id)
            if source is not None and source.joined_groups:
                return source.joined_groups[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"operation {op_id!r} never started a source within {timeout}s")


async def _await_operation_gone(ws, communicator, op_id, *, timeout=2.0):
    """Poll until operation *op_id* is no longer in the consumer's registry."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        consumer = ws.get_live_consumer(communicator.scope)
        if consumer is None or op_id not in consumer.operation_ids():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"operation {op_id!r} still registered after {timeout}s")


# ---------------------------------------------------------------------------
# 1) handshake: connection_init → connection_ack
# ---------------------------------------------------------------------------


@native_only
async def test_handshake_connection_init_ack(monkeypatch):
    """``connection_init`` is answered with ``connection_ack`` (the auth boundary)."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    connected, subprotocol = await communicator.connect()
    assert connected
    # The accepted subprotocol must be graphql-transport-ws.
    assert subprotocol == "graphql-transport-ws"

    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=2)
    assert ack == {"type": "connection_ack"}

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 2) subscribe → next (serialize-once flat-pk data) → complete
# ---------------------------------------------------------------------------


@native_only
async def test_subscribe_next_then_complete(monkeypatch):
    """``subscribe`` → a broadcast → ``next{id, payload}`` (flat pk data) → ``complete``."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "op1", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )

    # Let the subscribe task join its group, then broadcast one event.
    group = await _await_started_group(ws, communicator, "op1", timeout=2.0)
    await layer.group_send(group, _notify(group, _FLAT_POST))

    msg = await communicator.receive_json_from(timeout=2)
    assert msg["type"] == "next"
    assert msg["id"] == "op1"
    assert msg["payload"]["data"]["post"] == {
        "id": "1",
        "title": "hello",
        "author": "7",
        "tags": ["3"],
    }
    assert msg["payload"].get("errors") in (None, [])

    # End the source naturally (out-of-band aclose) → the server emits the
    # terminal ``complete{id}`` (the graphql-transport-ws stream-ended signal).
    consumer = _consumer_for(ws, communicator)
    await consumer.started_source("op1").aclose()
    done = await communicator.receive_json_from(timeout=2)
    assert done == {"id": "op1", "type": "complete"}

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 3) N operations multiplexed over ONE socket
# ---------------------------------------------------------------------------


@native_only
async def test_multiplex_two_independent_operations(monkeypatch):
    """Two ids over ONE socket → independent streams (each id gets only its own)."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "a", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    await communicator.send_json_to(
        {"id": "b", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )

    group_a = await _await_started_group(ws, communicator, "a", timeout=2.0)
    group_b = await _await_started_group(ws, communicator, "b", timeout=2.0)
    # Both subscribe to the same model/action, so they join the same group name;
    # one broadcast must deliver a distinct ``next`` to BOTH ids.
    assert group_a == group_b
    await layer.group_send(group_a, _notify(group_a, _FLAT_POST))

    ids_seen = set()
    for _ in range(2):
        msg = await communicator.receive_json_from(timeout=2)
        assert msg["type"] == "next"
        ids_seen.add(msg["id"])
    assert ids_seen == {"a", "b"}

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 4) complete{id} from the client cancels ONLY that id (the other keeps streaming)
# ---------------------------------------------------------------------------


@native_only
async def test_client_complete_cancels_only_that_id(monkeypatch):
    """Client ``complete{id}`` cancels ONLY that id's task + discards ITS groups;
    the other id keeps streaming."""
    from django_graphex.subscriptions.transports import ws

    discards: list[tuple[str, str]] = []

    class _RecordingLayer(InMemoryChannelLayer):
        async def group_discard(self, group, channel):
            discards.append((group, channel))
            return await super().group_discard(group, channel)

    layer = _RecordingLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "keep", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    await communicator.send_json_to(
        {"id": "drop", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    await _await_started_group(ws, communicator, "keep", timeout=2.0)
    group = await _await_started_group(ws, communicator, "drop", timeout=2.0)

    # Client cancels ONLY "drop".
    await communicator.send_json_to({"id": "drop", "type": "complete"})
    # The cancelled id's task tears down → its group is discarded.
    await _await_operation_gone(ws, communicator, "drop", timeout=2.0)
    discarded_groups = {g for g, _ in discards}
    assert group in discarded_groups, "the cancelled id's group must be discarded"

    # The OTHER id ("keep") still streams: a broadcast delivers to it.
    keep_group = await _await_started_group(ws, communicator, "keep", timeout=2.0)
    await layer.group_send(keep_group, _notify(keep_group, _FLAT_POST))
    msg = await communicator.receive_json_from(timeout=2)
    assert msg["type"] == "next"
    assert msg["id"] == "keep"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 5) disconnect cancels ALL tasks + group_discards all (no ghost subscriber)
# ---------------------------------------------------------------------------


@native_only
async def test_disconnect_cancels_all_and_discards_all(monkeypatch):
    """Disconnect cancels ALL operation tasks + ``group_discard``s every joined group."""
    from django_graphex.subscriptions.transports import ws

    discards: list[tuple[str, str]] = []

    class _RecordingLayer(InMemoryChannelLayer):
        async def group_discard(self, group, channel):
            discards.append((group, channel))
            return await super().group_discard(group, channel)

    layer = _RecordingLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "x", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    await communicator.send_json_to(
        {"id": "y", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    group_x = await _await_started_group(ws, communicator, "x", timeout=2.0)
    group_y = await _await_started_group(ws, communicator, "y", timeout=2.0)
    joined = {group_x, group_y}

    await communicator.disconnect()
    # Give the disconnect teardown a moment to sweep all sources.
    await asyncio.sleep(0.05)

    discarded_groups = {g for g, _ in discards}
    assert joined <= discarded_groups, (
        f"disconnect must discard every joined group; "
        f"joined={joined} discarded={discarded_groups}"
    )


# ---------------------------------------------------------------------------
# 6) ping → pong
# ---------------------------------------------------------------------------


@native_only
async def test_ping_pong(monkeypatch):
    """A ``ping`` message is answered with ``pong``."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"type": "ping"})
    pong = await communicator.receive_json_from(timeout=2)
    assert pong["type"] == "pong"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 7) 4408 connection_init timeout
# ---------------------------------------------------------------------------


@native_only
async def test_connection_init_timeout_4408(monkeypatch):
    """No ``connection_init`` within the timeout → close code 4408."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    # A tiny init timeout so the test does not wait 3 seconds.
    app = ws.subscription_ws_consumer(schema=_build_native_schema(), init_timeout=0.1)
    communicator = _make_communicator(app, layer=layer)
    connected, _ = await communicator.connect()
    assert connected

    # Send NOTHING; wait past the init timeout — the server closes with 4408.
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4408


# ---------------------------------------------------------------------------
# 8) 4409 duplicate subscribe id
# ---------------------------------------------------------------------------


@native_only
async def test_duplicate_subscribe_id_4409(monkeypatch):
    """A second ``subscribe`` with an in-use id → close code 4409."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "dup", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    await _await_started_group(ws, communicator, "dup", timeout=2.0)
    # Re-use the same id → 4409.
    await communicator.send_json_to(
        {"id": "dup", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4409


# ---------------------------------------------------------------------------
# 9) 4401 subscribe before ack
# ---------------------------------------------------------------------------


@native_only
async def test_subscribe_before_ack_4401(monkeypatch):
    """A ``subscribe`` BEFORE ``connection_ack`` → close code 4401 (Unauthorized)."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    connected, _ = await communicator.connect()
    assert connected

    # No connection_init/ack yet — subscribing now is Unauthorized (4401).
    await communicator.send_json_to(
        {"id": "early", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4401


@native_only
async def test_too_many_init_requests_4429(monkeypatch):
    """A second ``connection_init`` → close code 4429 (Too many init requests)."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"type": "connection_init"})
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4429


@native_only
async def test_malformed_message_4400(monkeypatch):
    """A malformed (unknown-type / non-dict) message → close code 4400."""
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"type": "bogus_unknown_type"})
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4400


# ---------------------------------------------------------------------------
# server-initiated close ACTIVELY tears down a live operation (no reliance on a
# subsequent inbound websocket.disconnect). A server close (4409/4429/4400) with
# a live op MUST cancel its task AND group_discard ITS groups BY THE CLOSE — the
# close codes promise teardown (module docstring + design §7). These assert the
# teardown happens WITHOUT calling communicator.disconnect() first, and that a
# later disconnect is idempotent (no double-discard / crash).
# ---------------------------------------------------------------------------


class _RecordingLayer(InMemoryChannelLayer):
    """An ``InMemoryChannelLayer`` that records every ``group_discard`` call."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discards: list[tuple[str, str]] = []

    async def group_discard(self, group, channel):
        self.discards.append((group, channel))
        return await super().group_discard(group, channel)


@native_only
async def test_server_close_4409_tears_down_live_op(monkeypatch):
    """A 4409 dup-id close with a LIVE op cancels its task + discards ITS group.

    The teardown happens BY THE CLOSE itself — no subsequent inbound
    ``websocket.disconnect`` is delivered before the assertions. This FAILS if
    ``_close`` only sends ``websocket.close`` (the op's group would dangle).
    """
    from django_graphex.subscriptions.transports import ws

    layer = _RecordingLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "dup", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    group = await _await_started_group(ws, communicator, "dup", timeout=2.0)
    consumer = _consumer_for(ws, communicator)
    task = consumer._operations["dup"]
    source = consumer.started_source("dup")

    # Re-use the same id → server fires a 4409 close. This MUST tear the live op
    # down actively (the close path, NOT a later disconnect).
    await communicator.send_json_to(
        {"id": "dup", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4409

    # The live op's task was cancelled, its source closed, and ITS group
    # discarded — all BY THE CLOSE (no communicator.disconnect() yet).
    assert task.done(), "the live op's task must be cancelled by the server close"
    assert source.is_closed, "the live op's source must be aclose()d by the close"
    assert "dup" not in consumer.operation_ids(), "the op must leave the registry"
    discarded_groups = {g for g, _ in layer.discards}
    assert group in discarded_groups, (
        "the server close MUST group_discard the live op's group (no ghost "
        f"subscriber); discarded={discarded_groups}"
    )

    # Idempotency: a later inbound disconnect finds empty registries → it must
    # NOT double-discard the already-swept group nor crash.
    discards_before = list(layer.discards)
    await communicator.disconnect()
    await asyncio.sleep(0.05)
    assert layer.discards == discards_before, (
        "the later disconnect must be a no-op (no double-discard); "
        f"before={discards_before} after={layer.discards}"
    )


@native_only
async def test_server_close_4429_tears_down_live_op(monkeypatch):
    """A 4429 second-init close with a LIVE op cancels its task + discards its group.

    Teardown happens BY THE CLOSE (no subsequent inbound disconnect first). This
    FAILS if ``_close`` only delegates to ``self.close()``.
    """
    from django_graphex.subscriptions.transports import ws

    layer = _RecordingLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "live", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    group = await _await_started_group(ws, communicator, "live", timeout=2.0)
    consumer = _consumer_for(ws, communicator)
    task = consumer._operations["live"]
    source = consumer.started_source("live")

    # A second connection_init → server fires a 4429 close WITH the op live.
    await communicator.send_json_to({"type": "connection_init"})
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4429

    assert task.done(), "the live op's task must be cancelled by the server close"
    assert source.is_closed, "the live op's source must be aclose()d by the close"
    assert "live" not in consumer.operation_ids()
    discarded_groups = {g for g, _ in layer.discards}
    assert group in discarded_groups, (
        "the 4429 close MUST group_discard the live op's group; "
        f"discarded={discarded_groups}"
    )

    # Idempotent with a later disconnect (empty registries → no double-discard).
    discards_before = list(layer.discards)
    await communicator.disconnect()
    await asyncio.sleep(0.05)
    assert layer.discards == discards_before


@native_only
async def test_server_close_4400_midstream_tears_down_live_op(monkeypatch):
    """A 4400 malformed-message close MID-STREAM tears down a live op's group.

    A malformed frame arriving while an operation is live closes with 4400 and
    MUST group_discard the live op's group BY THE CLOSE (not a later disconnect).
    """
    from django_graphex.subscriptions.transports import ws

    layer = _RecordingLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "mid", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    group = await _await_started_group(ws, communicator, "mid", timeout=2.0)
    consumer = _consumer_for(ws, communicator)
    task = consumer._operations["mid"]
    source = consumer.started_source("mid")

    # A malformed (unknown-type) frame mid-stream → server fires a 4400 close.
    await communicator.send_json_to({"type": "bogus_unknown_type"})
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4400

    assert task.done(), "the live op's task must be cancelled by the server close"
    assert source.is_closed
    assert "mid" not in consumer.operation_ids()
    discarded_groups = {g for g, _ in layer.discards}
    assert group in discarded_groups, (
        "the 4400 close MUST group_discard the live op's group; "
        f"discarded={discarded_groups}"
    )

    discards_before = list(layer.discards)
    await communicator.disconnect()
    await asyncio.sleep(0.05)
    assert layer.discards == discards_before


# ---------------------------------------------------------------------------
# delivery-path invariant: assertNumQueries(0) over the WS stream
# ---------------------------------------------------------------------------


@native_only
async def test_ws_delivery_path_is_zero_queries(monkeypatch):
    """Delivering one event over the WS stream issues ZERO DB queries.

    The snake-closure projects the serialize-once flat pk dict in memory; the
    transport never re-serializes nor instantiates a model.
    """
    from asgiref.sync import sync_to_async
    from django.db import connection, reset_queries

    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    app = ws.subscription_ws_consumer(schema=_build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "q0", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    group = await _await_started_group(ws, communicator, "q0", timeout=2.0)

    @sync_to_async
    def _enable_query_log():
        connection.ensure_connection()
        connection.force_debug_cursor = True
        reset_queries()

    @sync_to_async
    def _query_count():
        return len(connection.queries)

    await _enable_query_log()
    await layer.group_send(group, _notify(group, _FLAT_POST))
    msg = await communicator.receive_json_from(timeout=2)
    n_queries = await _query_count()

    assert msg["type"] == "next"
    assert n_queries == 0

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# static gates: no graphene import; reads graphex_or_graphene_settings
# ---------------------------------------------------------------------------


@native_only
def test_ws_module_does_not_import_graphene():
    """``transports/ws.py`` must not import graphene (the no-graphene-import gate)."""
    import ast
    import inspect

    from django_graphex.subscriptions.transports import ws

    tree = ast.parse(inspect.getsource(ws))
    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module or "")
            for alias in node.names:
                imported_names.add(alias.name)

    assert not any(
        m == "graphene" or m.startswith("graphene.") for m in imported_modules
    )
    assert "graphene" not in imported_names
    assert "graphene_settings" not in imported_names
