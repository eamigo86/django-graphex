"""Keep subscription startup cancellations from leaving channel-layer groups."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.test import AsyncRequestFactory  # noqa: E402

from django_graphex.subscriptions.source import ChannelLayerSource  # noqa: E402
from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)

_QUERY = "subscription { post(action: CREATE) { id title } }"


class _User:
    """Supply the authenticated user expected by the transports."""

    is_authenticated = True
    pk = 1


class _JoinGateLayer(InMemoryChannelLayer):
    """Pause after a real backend join and before group_add returns."""

    def __init__(self) -> None:
        """Initialize finite events that control the first group join."""
        super().__init__()
        self.joined = asyncio.Event()
        self.release_join = asyncio.Event()
        self._pause_next = True

    async def group_add(self, group: str, channel: str) -> None:
        """Make the actual membership observable at the cancellation point.

        Args:
            group: The group to join.
            channel: The source-owned channel to register.
        """
        await super().group_add(group, channel)
        if self._pause_next:
            self._pause_next = False
            self.joined.set()
            await self.release_join.wait()


async def _open_websocket(layer: _JoinGateLayer) -> WebsocketCommunicator:
    """Connect and acknowledge a real ASGI subscription WebSocket.

    Args:
        layer: The isolated channel layer used by the subscriber.

    Returns:
        The connected WebSocket communicator.
    """
    from django_graphex.subscriptions.transports import ws

    app = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = WebsocketCommunicator(
        app.as_asgi(), "/graphql/", subprotocols=["graphql-transport-ws"]
    )
    communicator.scope["user"] = _User()
    communicator.scope["channel_layer"] = layer
    connected, protocol = await communicator.connect()
    assert connected and protocol == "graphql-transport-ws"
    await communicator.send_json_to({"type": "connection_init"})
    assert await communicator.receive_json_from() == {"type": "connection_ack"}
    return communicator


async def test_client_complete_during_real_join_discards_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A processed complete must not leave the startup group's member behind.

    Args:
        monkeypatch: The fixture routing the source to the gated layer.
    """
    layer = _JoinGateLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    communicator = await _open_websocket(layer)
    try:
        await communicator.send_json_to(
            {"id": "starting", "type": "subscribe", "payload": {"query": _QUERY}}
        )
        await asyncio.wait_for(layer.joined.wait(), timeout=2)
        assert layer.groups
        await communicator.send_json_to({"id": "starting", "type": "complete"})
        await communicator.send_json_to({"type": "ping"})
        assert await communicator.receive_json_from() == {"type": "pong"}
        assert not layer.groups
    finally:
        layer.release_join.set()
        await communicator.disconnect()


async def test_disconnect_during_real_join_discards_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disconnect must cancel the pending startup and remove its membership.

    Args:
        monkeypatch: The fixture routing the source to the gated layer.
    """
    layer = _JoinGateLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    communicator = await _open_websocket(layer)
    disconnected = False
    try:
        await communicator.send_json_to(
            {"id": "starting", "type": "subscribe", "payload": {"query": _QUERY}}
        )
        await asyncio.wait_for(layer.joined.wait(), timeout=2)
        assert layer.groups
        await asyncio.wait_for(communicator.disconnect(), timeout=2)
        disconnected = True
        assert not layer.groups
    finally:
        layer.release_join.set()
        if not disconnected:
            await communicator.disconnect()


async def test_sse_cancel_during_real_join_discards_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared source also cleans up when an SSE request is cancelled.

    Args:
        monkeypatch: The fixture routing the source to the gated layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = _JoinGateLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    request = AsyncRequestFactory().post(
        "/graphql/stream/",
        data=json.dumps({"query": _QUERY}),
        content_type="application/json",
    )
    request.user = _User()
    view = sse.subscription_sse_view(schema=build_native_schema())
    request_task = asyncio.create_task(view(request))
    try:
        await asyncio.wait_for(layer.joined.wait(), timeout=2)
        assert layer.groups
        request_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request_task
        assert not layer.groups
    finally:
        layer.release_join.set()
        if not request_task.done():
            request_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request_task


class _SecondJoinFailureLayer(InMemoryChannelLayer):
    """Fail once after the backend joins the second source-owned group."""

    def __init__(self) -> None:
        """Prepare the one-time failure counter."""
        super().__init__()
        self.calls = 0

    async def group_add(self, group: str, channel: str) -> None:
        """Perform the real join and fail after the second membership exists.

        Args:
            group: The group to join.
            channel: The source-owned channel to register.

        Raises:
            ValueError: Once, after the second real membership is created.
        """
        self.calls += 1
        await super().group_add(group, channel)
        if self.calls == 2:
            raise ValueError("second join failed")


async def test_failed_second_join_discards_only_its_memberships() -> None:
    """Verify partial startup removes only source-owned memberships.

    A fresh source may then join and close without affecting an existing peer.
    """
    layer = _SecondJoinFailureLayer()
    peer = await layer.new_channel()
    await InMemoryChannelLayer.group_add(layer, "create", peer)
    source = ChannelLayerSource(["create", "update", "delete"], layer)
    with pytest.raises(ValueError, match="second join failed"):
        await source.start()
    assert layer.groups == {"create": {peer: layer.groups["create"][peer]}}
    assert source.joined_groups == []
    await source.aclose()
    assert layer.groups == {"create": {peer: layer.groups["create"][peer]}}

    fresh = ChannelLayerSource(["create"], layer)
    await fresh.start()
    await fresh.start()
    assert fresh.channel in layer.groups["create"]
    await fresh.aclose()
    await fresh.aclose()
    assert layer.groups == {"create": {peer: layer.groups["create"][peer]}}


async def test_failure_before_backend_join_preserves_original_error() -> None:
    """Verify a pre-join rejection leaves no groups or masked error.

    Raises:
        AssertionError: The source violates the cleanup contract.
    """

    class FailBeforeJoin(InMemoryChannelLayer):
        """Raise before any membership is created."""

        async def group_add(self, group: str, channel: str) -> None:
            """Reject the add before touching the backend.

            Args:
                group: The attempted group.
                channel: The attempted channel.

            Raises:
                ValueError: Always.
            """
            raise ValueError("add rejected")

    layer = FailBeforeJoin()
    source = ChannelLayerSource(["create"], layer)
    with pytest.raises(ValueError, match="add rejected"):
        await source.start()
    assert not layer.groups
    await source.aclose()
    assert not layer.groups


async def test_cleanup_failure_does_not_replace_startup_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify a discard error does not replace the startup failure.

    Args:
        caplog: Captured internal warnings from startup cleanup.

    Raises:
        AssertionError: The source changes the observed failure.
    """

    class FailingLayer(InMemoryChannelLayer):
        """Reject both the attempted join and its best-effort discard."""

        async def group_add(self, group: str, channel: str) -> None:
            """Reject a group before joining it.

            Args:
                group: The attempted group.
                channel: The attempted channel.

            Raises:
                ValueError: Always.
            """
            raise ValueError("join failed")

        async def group_discard(self, group: str, channel: str) -> None:
            """Reject the cleanup attempt.

            Args:
                group: The attempted group.
                channel: The attempted channel.

            Raises:
                RuntimeError: Always.
            """
            raise RuntimeError("discard failed")

    source = ChannelLayerSource(["create"], FailingLayer())
    with caplog.at_level(logging.WARNING, logger="django_graphex.subscriptions.source"):
        with pytest.raises(ValueError, match="join failed"):
            await source.start()
    assert not source.is_closed
    assert source.joined_groups == []
    warnings = [
        record
        for record in caplog.records
        if record.name == "django_graphex.subscriptions.source"
        and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == (
        "Subscription startup group cleanup failed; continuing best-effort cleanup."
    )
    assert warnings[0].exc_info is not None
    assert warnings[0].exc_info[0] is RuntimeError


class _FailFirstJoinLayer(InMemoryChannelLayer):
    """Reject the first join, then permit a real membership."""

    def __init__(self) -> None:
        """Initialize the one-time rejection state."""
        super().__init__()
        self._reject_first = True

    async def group_add(self, group: str, channel: str) -> None:
        """Fail before one join and delegate later calls to the backend.

        Args:
            group: The source-owned group.
            channel: The source-owned channel.

        Raises:
            ValueError: Only on the first attempt.
        """
        if self._reject_first:
            self._reject_first = False
            raise ValueError("initial join rejected")
        await super().group_add(group, channel)


async def test_same_source_retry_after_failed_join_delivers_and_cleans_up() -> None:
    """Retry the same source after a one-time pre-join failure.

    The retry must deliver an actual group event and its final close must
    remove the real membership.
    """
    layer = _FailFirstJoinLayer()
    source = ChannelLayerSource(["create"], layer)
    with pytest.raises(ValueError, match="initial join rejected"):
        await source.start()
    await source.start()
    assert source.channel in layer.groups["create"]
    was_closed = source.is_closed
    await layer.group_send(
        "create", {"type": "subscription.notify", "payload": {"data": {"id": "retry"}}}
    )
    try:
        delivered = await asyncio.wait_for(source.__anext__(), timeout=2)
    except StopAsyncIteration:
        delivered = None
    await source.aclose()
    assert (was_closed, delivered, layer.groups) == (False, {"id": "retry"}, {})


async def test_explicit_close_after_failed_join_stays_closed() -> None:
    """Keep an explicitly closed source terminal after failed startup.

    A later start call must not create another backend membership.
    """
    layer = _FailFirstJoinLayer()
    source = ChannelLayerSource(["create"], layer)
    with pytest.raises(ValueError, match="initial join rejected"):
        await source.start()
    await source.aclose()
    await source.start()
    assert source.is_closed
    assert not layer.groups
