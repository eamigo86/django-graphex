"""Public and iterator-level diagnostics for best-effort subscription close."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from channels.layers import InMemoryChannelLayer

from django_graphex.subscriptions.delivery import DeliveryIterator
from django_graphex.subscriptions.transports import ws
from tests.subscriptions._transport_schema import build_native_schema
from tests.subscriptions.test_transport_ws import (
    _SUB_QUERY,
    _await_operation_gone,
    _await_started_group,
    _connect_and_ack,
    _consumer_for,
    _make_communicator,
)


@pytest.mark.django_db(transaction=True)
async def test_client_complete_logs_suppressed_delivery_runtimeerror(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A real failing group discard is diagnosed without changing WS frames.

    Args:
        monkeypatch: Isolates the channel layer used by the subscription.
        caplog: Captures the delivery logger's server-side diagnostic.

    Raises:
        RuntimeError: The injected group discard failure.
    """
    failure = RuntimeError("injected group_discard failure")
    attempts: list[tuple[str, str]] = []

    class _FailingDiscardLayer(InMemoryChannelLayer):
        """Raise the same error from the one joined group's discard."""

        async def group_discard(self, group: str, channel: str) -> None:
            """Record one discard attempt before raising the original error.

            Args:
                group: The joined subscription group.
                channel: The channel being removed from the group.

            Raises:
                RuntimeError: The injected close failure.
            """
            attempts.append((group, channel))
            raise failure

    layer = _FailingDiscardLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    app = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)
    try:
        await communicator.send_json_to(
            {
                "id": "cancelled-op",
                "type": "subscribe",
                "payload": {"query": _SUB_QUERY},
            }
        )
        group = await _await_started_group(ws, communicator, "cancelled-op")
        consumer = _consumer_for(ws, communicator)

        with caplog.at_level(
            logging.WARNING, logger="django_graphex.subscriptions.delivery"
        ):
            await communicator.send_json_to({"id": "cancelled-op", "type": "complete"})
            await _await_operation_gone(ws, communicator, "cancelled-op")

        assert len(attempts) == 1
        assert attempts[0][0] == group
        assert attempts[0][1]
        assert "cancelled-op" not in consumer.operation_ids()
        assert await communicator.receive_nothing(timeout=0.1)
        await communicator.send_json_to({"type": "ping"})
        assert await communicator.receive_json_from(timeout=2) == {"type": "pong"}

        warnings = [
            record
            for record in caplog.records
            if record.name == "django_graphex.subscriptions.delivery"
            and record.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert warnings[0].exc_info is not None
        assert warnings[0].exc_info[1] is failure
        assert "close" in warnings[0].getMessage().lower()
        assert not any(
            "failed before it could stream" in record.getMessage()
            for record in caplog.records
        )
    finally:
        await communicator.disconnect()


async def test_delivery_close_runtimeerror_warns_once_and_stays_idempotent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A benign close race also warns once without escaping to the caller.

    Args:
        caplog: Captures the warning and its original exception information.

    Raises:
        StopAsyncIteration: The test source never emits events.
        RuntimeError: The injected close race raised by the source.
    """
    failure = RuntimeError("async generator is already running")

    class _RaisingCloseSource:
        """An async source whose close represents an already-closing race."""

        attempts = 0

        def __aiter__(self) -> _RaisingCloseSource:
            """Return this async source for iterator wrapping.

            Returns:
                The same source instance.
            """
            return self

        async def __anext__(self) -> Any:
            """Stop if a consumer unexpectedly requests an event.

            Raises:
                StopAsyncIteration: This test source does not emit events.
            """
            raise StopAsyncIteration

        async def aclose(self) -> None:
            """Raise the original close race.

            Raises:
                RuntimeError: The original close race.
            """
            self.attempts += 1
            raise failure

    source = _RaisingCloseSource()
    delivery = DeliveryIterator(source, lambda value: value)
    with caplog.at_level(
        logging.WARNING, logger="django_graphex.subscriptions.delivery"
    ):
        await delivery.aclose()
        await delivery.aclose()

    warnings = [
        record
        for record in caplog.records
        if record.name == "django_graphex.subscriptions.delivery"
        and record.levelno == logging.WARNING
    ]
    assert source.attempts == 1
    assert delivery.is_closed
    assert len(warnings) == 1
    assert warnings[0].exc_info is not None
    assert warnings[0].exc_info[1] is failure


@pytest.mark.django_db(transaction=True)
async def test_client_complete_valueerror_keeps_existing_error_frame(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-RuntimeError cleanup failure still uses the WS error path.

    Args:
        monkeypatch: Isolates the channel layer used by the subscription.
        caplog: Captures existing transport errors and new delivery warnings.

    Raises:
        ValueError: The injected group discard failure.
    """
    failure = ValueError("injected group_discard failure")

    class _FailingDiscardLayer(InMemoryChannelLayer):
        """Raise a non-suppressed cleanup error from the joined group."""

        async def group_discard(self, group: str, channel: str) -> None:
            """Raise the original non-RuntimeError failure.

            Args:
                group: The joined subscription group.
                channel: The channel being removed from the group.

            Raises:
                ValueError: The injected cleanup failure.
            """
            raise failure

    layer = _FailingDiscardLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    app = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)
    try:
        await communicator.send_json_to(
            {"id": "failed-op", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
        )
        await _await_started_group(ws, communicator, "failed-op")
        with caplog.at_level(logging.WARNING):
            await communicator.send_json_to({"id": "failed-op", "type": "complete"})
            await _await_operation_gone(ws, communicator, "failed-op")
        frame = await communicator.receive_json_from(timeout=2)
        assert frame["type"] == "error"
        assert frame["id"] == "failed-op"
        assert str(failure) not in json.dumps(frame["payload"])
        assert frame["payload"][0]["extensions"]["code"] == "INTERNAL_SERVER_ERROR"
        assert not any(
            record.name == "django_graphex.subscriptions.delivery"
            and record.levelno == logging.WARNING
            for record in caplog.records
        )
        await communicator.send_json_to({"type": "ping"})
        assert await communicator.receive_json_from(timeout=2) == {"type": "pong"}
    finally:
        await communicator.disconnect()
