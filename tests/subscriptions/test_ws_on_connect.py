"""Real-ASGI tests for optional WebSocket initialization authentication."""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from asgiref.sync import sync_to_async

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import AnonymousUser  # noqa: E402

from django_graphex.subscriptions.transports import ws  # noqa: E402
from tests.subscriptions._transport_schema import (  # noqa: E402
    build_auth_gated_schema,
    build_native_schema,
)

pytestmark = pytest.mark.django_db(transaction=True)

_QUERY = "subscription { post(action: CREATE) { id } }"


def _communicator(consumer: type, *, user: Any = None) -> WebsocketCommunicator:
    """Build a negotiated communicator with an optional previous scope user.

    Args:
        consumer: The Channels consumer class to run.
        user: Existing session identity, when supplied.

    Returns:
        A real-ASGI WebSocket communicator.
    """
    communicator = WebsocketCommunicator(
        consumer.as_asgi(), "/graphql/", subprotocols=["graphql-transport-ws"]
    )
    if user is not None:
        communicator.scope["user"] = user
    return communicator


async def _connect(communicator: WebsocketCommunicator) -> None:
    """Assert that the WebSocket handshake succeeds.

    Args:
        communicator: The client to connect.
    """
    connected, protocol = await communicator.connect()
    assert connected
    assert protocol == "graphql-transport-ws"


async def _wait_for(event: asyncio.Event) -> None:
    """Bound a callback's deterministic synchronization barrier.

    Args:
        event: The event expected to become set.
    """
    await asyncio.wait_for(event.wait(), timeout=2)


async def test_default_ignores_nonmapping_init_payloads() -> None:
    """Keep existing no-hook initialization behavior.

    A list payload remains ignored when no callback is configured.
    """
    consumer = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = _communicator(consumer)
    await _connect(communicator)
    try:
        await communicator.send_json_to(
            {"type": "connection_init", "payload": ["legacy"]}
        )
        assert await communicator.receive_json_from(timeout=2) == {
            "type": "connection_ack"
        }
    finally:
        await communicator.disconnect()


@pytest.mark.parametrize(
    ("include_payload", "payload"),
    [(False, None), (True, None), (True, {"token": "opaque"})],
    ids=["absent", "null", "object"],
)
async def test_hook_receives_normalized_payload_and_blocks_ack(
    include_payload: bool,
    payload: Any,
) -> None:
    """Await the hook before acknowledging while preserving the offered payload.

    Args:
        include_payload: Whether the frame explicitly carries a payload key.
        payload: The offered initialization payload or null.
    """
    entered = asyncio.Event()
    release = asyncio.Event()
    seen: list[tuple[Any, Any]] = []
    user = await sync_to_async(get_user_model().objects.create_user)(
        username=f"init-{include_payload}-{payload is None}"
    )

    async def authenticate(scope: Any, candidate: Any) -> Any:
        """Hold authentication at an explicit barrier and return a real user.

        Args:
            scope: The socket's Channels scope.
            candidate: The normalized initialization payload.

        Returns:
            The user authorized for this socket.
        """
        seen.append((scope, candidate))
        entered.set()
        await release.wait()
        return user

    consumer = ws.subscription_ws_consumer(
        schema=build_native_schema(), on_connect=authenticate
    )
    communicator = _communicator(consumer)
    await _connect(communicator)
    frame: dict[str, Any] = {"type": "connection_init"}
    if include_payload:
        frame["payload"] = payload
    await communicator.send_json_to(frame)
    try:
        await _wait_for(entered)
        assert seen == [(communicator.scope, payload or {})]
        assert await communicator.receive_nothing(timeout=0.05)
        release.set()
        assert await communicator.receive_json_from(timeout=2) == {
            "type": "connection_ack"
        }
        assert communicator.scope["user"] == user
    finally:
        release.set()
        await communicator.disconnect()


async def test_hook_identity_replaces_session_for_provider_and_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the callback's real user for schema pruning and subscribe gates.

    Args:
        monkeypatch: The fixture routing subscriptions to an isolated layer.
    """
    previous = await sync_to_async(get_user_model().objects.create_user)(
        username="previous-session"
    )
    current = await sync_to_async(get_user_model().objects.create_user)(
        username="current-token"
    )
    seen: list[Any] = []
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    async def authenticate(scope: Any, payload: Any) -> Any:
        """Authorize the replacement user, not the session user.

        Args:
            scope: The Channels connection scope.
            payload: The caller's initialization payload.

        Returns:
            The real authenticated replacement user.
        """
        assert scope["user"] == previous
        assert payload == {"token": "valid"}
        return current

    def provider(user: Any) -> Any:
        """Record the identity used to resolve the subscription schema.

        Args:
            user: The socket's effective user.

        Returns:
            The auth-gated native schema.
        """
        seen.append(user)
        return build_auth_gated_schema()

    consumer = ws.subscription_ws_consumer(
        schema_provider=provider, on_connect=authenticate
    )
    communicator = _communicator(consumer, user=previous)
    communicator.scope["channel_layer"] = layer
    await _connect(communicator)
    try:
        await communicator.send_json_to(
            {"type": "connection_init", "payload": {"token": "valid"}}
        )
        assert await communicator.receive_json_from(timeout=2) == {
            "type": "connection_ack"
        }
        assert communicator.scope["user"] == current
        await communicator.send_json_to(
            {"type": "subscribe", "id": "op", "payload": {"query": _QUERY}}
        )
        for _ in range(100):
            if seen and any(layer.groups.values()):
                break
            await asyncio.sleep(0.01)
        assert seen == [current]
        assert any(layer.groups.values())
    finally:
        await communicator.disconnect()


@pytest.mark.parametrize("result", [None, AnonymousUser(), Exception("SECRET")])
async def test_hook_denial_has_no_session_fallback_or_secret_output(
    result: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Reject missing, anonymous, or failing callback results generically.

    Args:
        result: The callback result or exception to raise.
        caplog: The captured server logs checked for secret disclosure.
    """
    previous = await sync_to_async(get_user_model().objects.create_user)(
        username=f"denied-{type(result).__name__}"
    )
    provider_calls: list[Any] = []

    async def authenticate(scope: Any, payload: Any) -> Any:
        """Return or raise the requested denial case.

        Args:
            scope: The Channels connection scope.
            payload: The caller's initialization payload.

        Returns:
            The configured result, if it is not an exception.

        Raises:
            Exception: The configured credential error.
        """
        assert scope["user"] == previous
        assert payload == {"token": "TOP-SECRET"}
        if isinstance(result, Exception):
            raise result
        return result

    def provider(user: Any) -> Any:
        """Fail the test if schema work begins after a denial.

        Args:
            user: The candidate user.

        Returns:
            The native schema.
        """
        provider_calls.append(user)
        return build_native_schema()

    consumer = ws.subscription_ws_consumer(
        schema_provider=provider, on_connect=authenticate
    )
    communicator = _communicator(consumer, user=previous)
    await _connect(communicator)
    with caplog.at_level(logging.DEBUG):
        await communicator.send_json_to(
            {"type": "connection_init", "payload": {"token": "TOP-SECRET"}}
        )
        assert await communicator.receive_output(timeout=2) == {
            "type": "websocket.close",
            "code": 4403,
        }
    assert not provider_calls
    assert communicator.scope["user"] == previous
    assert "TOP-SECRET" not in caplog.text
    assert "SECRET" not in caplog.text
    await communicator.send_input({"type": "websocket.disconnect", "code": 4403})
    await communicator.wait(timeout=2)


async def test_hook_rejects_nonmapping_payload_without_invocation() -> None:
    """Close malformed configured payloads before invoking the callback.

    No credential work should start for a protocol-invalid payload.
    """
    called = False

    async def authenticate(scope: Any, payload: Any) -> Any:
        """Expose an unexpected invocation.

        Args:
            scope: The Channels connection scope.
            payload: The malformed payload.

        Returns:
            No user, because this must never run.
        """
        nonlocal called
        called = True
        return None

    consumer = ws.subscription_ws_consumer(
        schema=build_native_schema(), on_connect=authenticate
    )
    communicator = _communicator(consumer)
    await _connect(communicator)
    await communicator.send_json_to({"type": "connection_init", "payload": ["bad"]})
    assert await communicator.receive_output(timeout=2) == {
        "type": "websocket.close",
        "code": 4400,
    }
    assert not called
    await communicator.send_input({"type": "websocket.disconnect", "code": 4400})
    await communicator.wait(timeout=2)


@pytest.mark.parametrize(
    "next_frame, code", [("subscribe", 4401), ("connection_init", 4429)]
)
async def test_pending_hook_retains_protocol_errors(next_frame: str, code: int) -> None:
    """Do not reinterpret pre-ACK subscription or duplicate init as auth.

    Args:
        next_frame: The second protocol message type.
        code: The native close code expected for that message.
    """
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def authenticate(scope: Any, payload: Any) -> Any:
        """Wait until protocol handling cancels the owned callback.

        Args:
            scope: The Channels connection scope.
            payload: The initialization payload.

        Returns:
            No user; protocol handling cancels before completion.

        Raises:
            asyncio.CancelledError: Propagates task cancellation.
        """
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    consumer = ws.subscription_ws_consumer(
        schema=build_native_schema(), on_connect=authenticate
    )
    communicator = _communicator(consumer)
    await _connect(communicator)
    await communicator.send_json_to({"type": "connection_init"})
    await _wait_for(entered)
    frame: dict[str, Any] = {"type": next_frame}
    if next_frame == "subscribe":
        frame.update({"id": "op", "payload": {"query": _QUERY}})
    await communicator.send_json_to(frame)
    assert await communicator.receive_output(timeout=2) == {
        "type": "websocket.close",
        "code": code,
    }
    await _wait_for(cancelled)
    await communicator.send_input({"type": "websocket.disconnect", "code": code})
    await communicator.wait(timeout=2)


async def test_pending_hook_times_out_and_cancels_without_late_ack() -> None:
    """Keep the watchdog active while authentication is pending.

    The deadline must cancel the owned callback before any acknowledgement.
    """
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def authenticate(scope: Any, payload: Any) -> Any:
        """Remain pending until timeout cancels the callback.

        Args:
            scope: The Channels connection scope.
            payload: The initialization payload.

        Returns:
            No user, because the deadline cancels this task.

        Raises:
            asyncio.CancelledError: Propagates deadline cancellation.
        """
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    consumer = ws.subscription_ws_consumer(
        schema=build_native_schema(), on_connect=authenticate, init_timeout=0.05
    )
    communicator = _communicator(consumer)
    await _connect(communicator)
    await communicator.send_json_to({"type": "connection_init"})
    await _wait_for(entered)
    assert await communicator.receive_output(timeout=2) == {
        "type": "websocket.close",
        "code": 4408,
    }
    await _wait_for(cancelled)
    assert await communicator.receive_nothing(timeout=0.05)
    await communicator.send_input({"type": "websocket.disconnect", "code": 4408})
    await communicator.wait(timeout=2)


async def test_disconnect_cancels_pending_hook() -> None:
    """Own the callback task and cancel it on transport disconnect.

    A disconnected socket must not leave credential work running.
    """
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def authenticate(scope: Any, payload: Any) -> Any:
        """Signal that a disconnect cancelled callback work.

        Args:
            scope: The Channels connection scope.
            payload: The initialization payload.

        Returns:
            No user, because disconnect cancels this task.

        Raises:
            asyncio.CancelledError: Propagates disconnect cancellation.
        """
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    consumer = ws.subscription_ws_consumer(
        schema=build_native_schema(), on_connect=authenticate
    )
    communicator = _communicator(consumer)
    await _connect(communicator)
    await communicator.send_json_to({"type": "connection_init"})
    await _wait_for(entered)
    await communicator.disconnect()
    await _wait_for(cancelled)
    assert ws.get_live_consumer(communicator.scope) is None


async def test_late_callback_result_cannot_replace_identity_or_ack() -> None:
    """Ignore a callback that suppresses cancellation after the init deadline.

    A late successful result cannot overwrite the previous scope user.
    """
    previous = await sync_to_async(get_user_model().objects.create_user)(
        username="late-previous"
    )
    late_user = await sync_to_async(get_user_model().objects.create_user)(
        username="late-token"
    )
    entered = asyncio.Event()
    returned = asyncio.Event()

    async def authenticate(scope: Any, payload: Any) -> Any:
        """Return a user even after deadline cancellation.

        Args:
            scope: The Channels connection scope.
            payload: The initialization payload.

        Returns:
            The late authenticated user.
        """
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            returned.set()
            return late_user

    consumer = ws.subscription_ws_consumer(
        schema=build_native_schema(), on_connect=authenticate, init_timeout=0.05
    )
    communicator = _communicator(consumer, user=previous)
    await _connect(communicator)
    await communicator.send_json_to({"type": "connection_init"})
    await _wait_for(entered)
    assert await communicator.receive_output(timeout=2) == {
        "type": "websocket.close",
        "code": 4408,
    }
    await _wait_for(returned)
    assert await communicator.receive_nothing(timeout=0.05)
    assert communicator.scope["user"] == previous
    await communicator.send_input({"type": "websocket.disconnect", "code": 4408})
    await communicator.wait(timeout=2)


def test_documented_on_connect_callback_is_typed_and_explained() -> None:
    """Keep the public authentication example ready to adapt safely.

    Inspect the example without importing its illustrative project services.
    """
    documentation = (
        Path(__file__).resolve().parents[2] / "docs/usage/subscriptions.md"
    ).read_text(encoding="utf-8")
    section = documentation.split("#### Optional connection authentication", 1)[1]
    example = section.split("```python\n", 1)[1].split("\n```", 1)[0]
    module = ast.parse(example)
    callback = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "authenticate_socket"
    )
    assert [argument.arg for argument in callback.args.args] == ["scope", "payload"]
    for argument in callback.args.args:
        assert argument.annotation is not None, argument.arg
        assert ast.unparse(argument.annotation) == "Mapping[str, Any]"
    assert callback.returns is not None
    assert ast.unparse(callback.returns) == "AbstractBaseUser | None"
    imported = {
        (node.module, alias.name)
        for node in module.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert {
        ("collections.abc", "Mapping"),
        ("typing", "Any"),
        ("django.contrib.auth.base_user", "AbstractBaseUser"),
    } <= imported
    description = ast.get_docstring(callback)
    assert description is not None
    assert "Args:\n    scope:" in description
    assert "\n    payload:" in description
    assert "Returns:\n" in description
    assert "`" not in description
    assert not any(
        name in description for name in ("Mapping", "AbstractBaseUser", "Any")
    )
