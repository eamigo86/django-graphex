"""Keep WebSocket operation IDs reusable only after source teardown."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from graphql import ExecutionResult  # noqa: E402

from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)

_QUERY = "subscription { post(action: CREATE) { id title } }"


class _User:
    """Provide the authenticated identity required by the transport."""

    is_authenticated = True
    pk = 1


class _GatedLayer(InMemoryChannelLayer):
    """Expose group-discard ordering without a clock-based assertion."""

    def __init__(self) -> None:
        """Create gates for the first group discard."""
        super().__init__()
        self.discard_entered = asyncio.Event()
        self.release_discard = asyncio.Event()

    async def group_discard(self, group: str, channel: str) -> None:
        """Pause the first group discard until the test releases it.

        Args:
            group: The joined group to leave.
            channel: The source's channel name.
        """
        self.discard_entered.set()
        await self.release_discard.wait()
        await super().group_discard(group, channel)


class _FiniteSource:
    """End a real started source when signaled by the test."""

    def __init__(self, source: Any) -> None:
        """Retain the real source and create deterministic iteration gates.

        Args:
            source: A started ChannelLayerSource with real group membership.
        """
        self.source = source
        self.ready = asyncio.Event()
        self.finish = asyncio.Event()

    def __aiter__(self) -> _FiniteSource:
        """Return this asynchronous iterator.

        Returns:
            The finite source itself.
        """
        return self

    async def __anext__(self) -> Any:
        """Wait for the end signal, then terminate the stream.

        Raises:
            StopAsyncIteration: When the test signals normal stream completion.
        """
        self.ready.set()
        await self.finish.wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        """Close the real source and discard its joined groups."""
        await self.source.aclose()


async def test_complete_waits_for_teardown_then_reuses_same_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete frame must follow teardown and permit immediate ID reuse.

    Args:
        monkeypatch: The fixture supplying a real in-memory channel layer.
    """
    from django_graphex.subscriptions.transports import ws

    layer = _GatedLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    original_start = ws._start_source_event_stream
    started: asyncio.Queue[_FiniteSource] = asyncio.Queue()
    complete_sent = asyncio.Event()

    async def controlled_start(*args: Any, **kwargs: Any) -> Any:
        """Retain a real started source while controlling its natural end.

        Args:
            args: Positional arguments for the production source starter.
            kwargs: Keyword arguments for the production source starter.

        Returns:
            A finite wrapper around the real started source.
        """
        result = await original_start(*args, **kwargs)
        if isinstance(result, ExecutionResult):
            return result
        wrapped = _FiniteSource(result)
        started.put_nowait(wrapped)
        return wrapped

    monkeypatch.setattr(ws, "_start_source_event_stream", controlled_start)
    base = ws.subscription_ws_consumer(schema=build_native_schema())

    class ObservedConsumer(base):
        """Record when the server emits its terminal operation frame."""

        async def send_json(self, content: Any, close: bool = False) -> None:
            """Forward a frame and record a server complete.

            Args:
                content: The protocol frame to send.
                close: Whether this frame closes the socket.
            """
            if content.get("type") == "complete":
                complete_sent.set()
            await super().send_json(content, close=close)

    communicator = WebsocketCommunicator(
        ObservedConsumer.as_asgi(),
        "/graphql/",
        subprotocols=["graphql-transport-ws"],
    )
    communicator.scope["user"] = _User()
    communicator.scope["channel_layer"] = layer
    connected, protocol = await communicator.connect()
    assert connected and protocol == "graphql-transport-ws"
    await communicator.send_json_to({"type": "connection_init"})
    assert await communicator.receive_json_from() == {"type": "connection_ack"}
    try:
        await communicator.send_json_to(
            {"id": "same", "type": "subscribe", "payload": {"query": _QUERY}}
        )
        first = await asyncio.wait_for(started.get(), timeout=2)
        await asyncio.wait_for(first.ready.wait(), timeout=2)
        assert first.source.joined_groups
        consumer = ws.get_live_consumer(communicator.scope)
        assert consumer is not None
        old_task = consumer._operations["same"]

        first.finish.set()
        await asyncio.wait_for(layer.discard_entered.wait(), timeout=2)
        assert not complete_sent.is_set(), "complete preceded group cleanup"
        assert "same" in consumer.operation_ids()

        layer.release_discard.set()
        assert await communicator.receive_json_from() == {
            "id": "same",
            "type": "complete",
        }
        assert not layer.groups

        await communicator.send_json_to(
            {"id": "same", "type": "subscribe", "payload": {"query": _QUERY}}
        )
        second = await asyncio.wait_for(started.get(), timeout=2)
        await asyncio.wait_for(second.ready.wait(), timeout=2)
        assert second.source.joined_groups
        new_task = consumer._operations["same"]
        assert new_task is not old_task
        consumer._operation_done("same", old_task)
        assert consumer._operations["same"] is new_task
    finally:
        layer.release_discard.set()
        await communicator.disconnect()
    assert not layer.groups


async def test_teardown_error_keeps_existing_terminal_frame_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A close failure still emits complete before its framed error.

    Args:
        monkeypatch: The fixture replacing only the started stream's close path.

    Raises:
        ValueError: Inside the test source; the transport catches and frames it.
    """
    from django_graphex.subscriptions.transports import ws
    from tests.subscriptions.test_transport_schema_provider_gate import _ws_consumer

    class FailingCloseSource:
        """Finish naturally, then fail during source cleanup."""

        def __aiter__(self) -> FailingCloseSource:
            """Return the finite asynchronous iterator.

            Returns:
                This source.
            """
            return self

        async def __anext__(self) -> Any:
            """End the stream before cleanup.

            Raises:
                StopAsyncIteration: Always, to request normal completion.
            """
            raise StopAsyncIteration

        async def aclose(self) -> None:
            """Report a backend cleanup failure.

            Raises:
                ValueError: Always, to preserve the existing frame sequence.
            """
            raise ValueError("close failed")

    async def start(*args: Any, **kwargs: Any) -> FailingCloseSource:
        """Return the finite source after normal validation.

        Args:
            args: Positional starter arguments.
            kwargs: Keyword starter arguments.

        Returns:
            A source whose cleanup fails.
        """
        return FailingCloseSource()

    monkeypatch.setattr(ws, "_start_source_event_stream", start)
    consumer = _ws_consumer({"user": _User()}, schema=build_native_schema())
    await consumer._run_operation_framed("failing", {"query": _QUERY})
    assert [frame["type"] for frame in consumer._sent] == ["complete", "error"]
    assert consumer._sent[1]["payload"] == [{"message": "close failed"}]
