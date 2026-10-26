"""Real-ASGI negotiation tests for the subscription WebSocket transport."""

from __future__ import annotations

import logging
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.testing import WebsocketCommunicator  # noqa: E402

from django_graphex.subscriptions.transports import ws  # noqa: E402
from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)

_REJECTION_MESSAGE = (
    "WebSocket connection rejected: client must offer the "
    "'graphql-transport-ws' subprotocol."
)


@pytest.mark.parametrize(
    ("offered", "remove_scope_key"),
    [
        ([], False),
        ([], True),
        (["graphql-ws"], False),
        (["graphql-transport-ws-extra", "graphql-ws"], False),
    ],
    ids=["empty", "missing", "legacy-only", "non-exact-only"],
)
async def test_unoffered_subprotocol_is_rejected_before_accept(
    offered: list[str],
    remove_scope_key: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reject an unoffered protocol without registering or starting work.

    Args:
        offered: The protocols offered by the client.
        remove_scope_key: Whether to remove the optional scope key entirely.
        caplog: The captured server-side diagnostic log.
    """
    accepted: list[str | None] = []
    watchdog_started: list[bool] = []
    disconnected: list[int] = []
    base = ws.subscription_ws_consumer(schema=build_native_schema())

    class ObservedConsumer(base):
        """Observe handshake side effects while running the real ASGI path."""

        async def accept(
            self,
            subprotocol: str | None = None,
            headers: Any = None,
        ) -> None:
            """Record and forward a socket acceptance.

            Args:
                subprotocol: The protocol selected by the consumer.
                headers: Optional acceptance headers.
            """
            accepted.append(subprotocol)
            await super().accept(subprotocol=subprotocol, headers=headers)

        async def _init_watchdog(self, timeout: float) -> None:
            """Record and forward watchdog execution.

            Args:
                timeout: The configured initialization deadline.
            """
            watchdog_started.append(True)
            await super()._init_watchdog(timeout)

        async def disconnect(self, code: int) -> None:
            """Record and forward lifecycle cleanup.

            Args:
                code: The disconnect status from the ASGI server.
            """
            disconnected.append(code)
            await super().disconnect(code)

    communicator = WebsocketCommunicator(
        ObservedConsumer.as_asgi(), "/graphql/", subprotocols=offered
    )
    if remove_scope_key:
        communicator.scope.pop("subprotocols")

    with caplog.at_level(logging.WARNING, logger=ws.__name__):
        connected, close_code = await communicator.connect()

    try:
        assert not connected
        assert close_code == 4406
        assert not accepted
        assert not watchdog_started
        assert ws.get_live_consumer(communicator.scope) is None
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == ws.__name__
        ] == [_REJECTION_MESSAGE]
    finally:
        await communicator.send_input({"type": "websocket.disconnect", "code": 1006})
        await communicator.wait(timeout=2)

    assert disconnected == [1006]
    assert ws.get_live_consumer(communicator.scope) is None


@pytest.mark.parametrize(
    "offered",
    [
        ["graphql-transport-ws"],
        ["graphql-ws", "graphql-transport-ws"],
        ["graphql-transport-ws", "graphql-ws"],
    ],
    ids=["only", "second", "first"],
)
async def test_required_subprotocol_is_accepted_among_alternatives(
    offered: list[str],
) -> None:
    """Negotiate the exact supported protocol in any offer position.

    Args:
        offered: The client's candidate subprotocols.
    """
    consumer = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = WebsocketCommunicator(
        consumer.as_asgi(), "/graphql/", subprotocols=offered
    )
    connected, subprotocol = await communicator.connect()
    try:
        assert connected
        assert subprotocol == "graphql-transport-ws"
        assert ws.get_live_consumer(communicator.scope) is not None
        await communicator.send_json_to({"type": "connection_init"})
        assert await communicator.receive_json_from(timeout=2) == {
            "type": "connection_ack"
        }
    finally:
        await communicator.disconnect()

    assert ws.get_live_consumer(communicator.scope) is None
