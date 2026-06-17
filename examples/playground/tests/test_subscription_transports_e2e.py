"""End-to-end round-trip tests for the playground's subscription transports.

These are the real thing: they drive the SAME WebSocket consumer
(``config.asgi`` / ``blog.consumers.AppWSConsumer``) and the SAME SSE view
(``config/urls.py`` / ``subscription_sse_view``) the playground serves, against
the live ``blog.schema``. A subscriber opens a subscription, the test triggers
the corresponding change through the ORM (a genuine ``Post`` save fires Django's
``post_save`` signal, which the subscription engine broadcasts), and the test
asserts the change is delivered as a ``next`` frame.

Why a real ORM save (not a hand-rolled ``group_send``): it exercises the full
producer path — ``post_save`` → ``SubscriptionBinding.broadcast`` →
serialize-once → ``group_send`` — exactly as ``postCreate`` does in the live
playground. The binding is wired the moment ``blog.schema`` is imported (its
``PostSubscription.Field()`` mount calls ``get_binding()``), so importing the
schema is all the setup the producer side needs.

Run from this directory::

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("channels")

# A Channels consumer touches the DB connection registry on every dispatched
# message, and the producer-side broadcast fires from a real transaction commit,
# so these need DB access with a real (committable) transaction.
pytestmark = pytest.mark.django_db(transaction=True)


_POST_SUB_QUERY = (
    "subscription { postSubscription(action: ALL_ACTIONS) "
    "{ id title status } }"
)


@pytest.fixture(autouse=True)
def _fresh_channel_layer():
    """Reset the in-memory channel layer between tests (no group leakage).

    The playground configures a single ``InMemoryChannelLayer`` (a process-wide
    singleton returned by ``channels.layers.get_channel_layer()``). BOTH the
    subscribe side (the consumer / SSE source) and the produce side
    (``SubscriptionBinding.broadcast`` via ``post_save``) resolve their layer
    through that same call, so they already share one layer — no patching needed.
    We just clear its groups/queues before each test so a prior test's
    subscriber cannot receive this test's broadcast and vice-versa.
    """
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    # InMemoryChannelLayer keeps per-group channel sets + per-channel queues.
    if hasattr(layer, "groups"):
        layer.groups.clear()
    if hasattr(layer, "receive_buffer"):
        layer.receive_buffer.clear()
    yield layer


async def _await_started_group(ws_module, communicator, op_id, *, timeout=3.0):
    """Poll until operation *op_id*'s source has joined a Channels group.

    The WS module records each connected consumer keyed by scope identity; this
    polls the live consumer's per-operation registry until the source is started
    and has joined at least one group (so a subsequent broadcast cannot race the
    subscribe).
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        consumer = ws_module.get_live_consumer(communicator.scope)
        if consumer is not None:
            source = consumer.started_source(op_id)
            if source is not None and source.joined_groups:
                return source.joined_groups[0]
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"operation {op_id!r} never joined a group within {timeout}s"
    )


# --------------------------------------------------------------------------- #
# WebSocket transport (graphql-transport-ws)                                   #
# --------------------------------------------------------------------------- #


async def test_ws_subscription_delivers_post_create(author):
    """WS round-trip: subscribe → create a Post via the ORM → receive a ``next``.

    Drives the playground's own ``AppWSConsumer`` (the consumer mounted in
    ``config/asgi.py``) over the graphql-transport-ws subprotocol.
    """
    from blog.consumers import AppWSConsumer
    from blog.models import Post
    from channels.testing import WebsocketCommunicator

    communicator = WebsocketCommunicator(
        AppWSConsumer.as_asgi(),
        "/ws/graphql/",
        subprotocols=["graphql-transport-ws"],
    )

    connected, subprotocol = await communicator.connect()
    assert connected, "the WS handshake must succeed"
    assert subprotocol == "graphql-transport-ws"

    # connection_init → connection_ack.
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=3)
    assert ack["type"] == "connection_ack"

    # Subscribe to postSubscription.
    await communicator.send_json_to(
        {"id": "p1", "type": "subscribe", "payload": {"query": _POST_SUB_QUERY}}
    )

    # Wait for the subscribe task to actually join its Channels group before
    # producing, so the broadcast cannot race ahead of the subscriber.
    from django_graphex.subscriptions.transports import ws as ws_module

    await _await_started_group(ws_module, communicator, "p1", timeout=3.0)

    from channels.db import database_sync_to_async

    @database_sync_to_async
    def _create_post():
        # A real ORM create → post_save → on_commit → broadcast. Outside an
        # atomic() block (transaction=True), on_commit runs immediately.
        return Post.objects.create(
            title="Live update",
            author=author,
            status=Post.Status.PUBLISHED,
        )

    await _create_post()

    msg = await communicator.receive_json_from(timeout=3.0)
    assert msg["type"] == "next"
    assert msg["id"] == "p1"
    data = msg["payload"]["data"]["postSubscription"]
    assert data["title"] == "Live update"
    assert data["status"] == "PUBLISHED"
    assert msg["payload"].get("errors") in (None, [])

    await communicator.disconnect()


async def test_ws_handshake_then_ping_pong():
    """Smoke: the playground consumer completes the handshake and answers ping."""
    from blog.consumers import AppWSConsumer
    from channels.testing import WebsocketCommunicator

    communicator = WebsocketCommunicator(
        AppWSConsumer.as_asgi(),
        "/ws/graphql/",
        subprotocols=["graphql-transport-ws"],
    )

    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=3)
    assert ack["type"] == "connection_ack"

    await communicator.send_json_to({"type": "ping"})
    pong = await communicator.receive_json_from(timeout=3)
    assert pong["type"] == "pong"

    await communicator.disconnect()


# --------------------------------------------------------------------------- #
# SSE transport (graphql-sse / text/event-stream)                             #
# --------------------------------------------------------------------------- #


async def test_sse_subscription_delivers_post_create(author):
    """SSE round-trip: open the stream → create a Post → receive an ``event: next``.

    Drives the playground's own SSE view, built exactly as ``config/urls.py``
    builds it: ``subscription_sse_view(schema=schema.graphql_schema)``.
    """
    from blog.models import Post
    from blog.schema import schema
    from django.test import RequestFactory

    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=schema.graphql_schema)

    factory = RequestFactory()
    request = factory.post(
        "/graphql/stream",
        data=json.dumps({"query": _POST_SUB_QUERY}),
        content_type="application/json",
    )
    # Public subscription: an anonymous user is allowed.
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()

    response = await view(request)
    assert response.status_code == 200
    assert response["content-type"].startswith("text/event-stream")

    # The subscribe joined a group; create a Post → broadcast → next frame.
    started = sse.get_started_source(response)
    assert started is not None, "the SSE subscribe must start a live source"
    assert started.joined_groups, "the SSE subscribe must join a Channels group"

    from channels.db import database_sync_to_async

    @database_sync_to_async
    def _create_post():
        return Post.objects.create(
            title="SSE live update",
            author=author,
            status=Post.Status.PUBLISHED,
        )

    await _create_post()

    aiter = response.streaming_content.__aiter__()
    first = await asyncio.wait_for(aiter.__anext__(), timeout=3.0)
    first = first.decode() if isinstance(first, (bytes, bytearray)) else first
    assert first.startswith("event: next\n"), f"unexpected first frame: {first!r}"

    payload_line = [ln for ln in first.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(payload_line[len("data: ") :])
    data = payload["data"]["postSubscription"]
    assert data["title"] == "SSE live update"
    assert data["status"] == "PUBLISHED"
    assert payload.get("errors") in (None, [])

    # Teardown: close the source so the generator's finally runs group_discard.
    await started.aclose()
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()
