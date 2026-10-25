"""Exercise permission-scoped subscription providers with real cold Django users."""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, override_settings
from graphql import ExecutionResult

from django_graphex.core.permission_signature_cache import pruned_schema_for
from tests.subscriptions.test_transport_real_user_resolution import (
    _communicator,
    _session_cookie,
)
from tests.subscriptions.test_transport_schema_provider_gate import (
    _SUB_QUERY,
    _full_labeled_schema,
    _ws_consumer,
)

pytest.importorskip("channels")
pytestmark = pytest.mark.django_db(transaction=True)


async def _real_user(*, may_view_post: bool) -> Any:
    """Return a persisted user without warming its permission cache.

    Args:
        may_view_post: Whether to grant the Post model's read permission.

    Returns:
        A fresh Django user instance whose permissions have not been read.
    """

    def _create() -> Any:
        user = get_user_model().objects.create_user(
            username=f"cold-provider-{int(may_view_post)}", password="unused"
        )
        if may_view_post:
            permission = Permission.objects.get(
                codename="view_post", content_type__app_label="tests"
            )
            user.user_permissions.add(permission)
        return get_user_model().objects.get(pk=user.pk)

    return await sync_to_async(_create, thread_sensitive=True)()


async def _sse_body(response: Any) -> str:
    """Read bounded subscription response frames.

    Args:
        response: The SSE response to inspect.

    Returns:
        The collected frame text.
    """
    frames: list[str] = []
    iterator = response.streaming_content.__aiter__()
    for _ in range(3):
        try:
            frame = await asyncio.wait_for(iterator.__anext__(), timeout=1)
        except StopAsyncIteration:
            break
        frames.append(frame.decode() if isinstance(frame, bytes) else frame)
        if "event: complete" in frames[-1]:
            break
    await iterator.aclose()
    return "".join(frames)


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True})
@pytest.mark.parametrize("may_view_post", [False, True])
async def test_sse_provider_resolves_cold_real_user_permissions(
    may_view_post: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SSE must prune from real permissions without ORM work on its event loop.

    Args:
        may_view_post: Whether the subscription is permitted.
        monkeypatch: The fixture replacing subscription startup with a bounded result.
    """
    from django_graphex.subscriptions.transports import sse

    async def _start(*args: Any, **kwargs: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(sse, "create_source_event_stream", _start)
    user = await _real_user(may_view_post=may_view_post)
    request = RequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps({"query": _SUB_QUERY}),
        content_type="application/json",
    )
    request.user = user
    view = sse.subscription_sse_view(
        schema_provider=lambda connection_user: pruned_schema_for(
            connection_user, _full_labeled_schema()
        )
    )
    response = await view(request)
    assert response.status_code == 200
    body = await _sse_body(response)
    assert ("Cannot query field 'post'" in body) is not may_view_post
    assert "You cannot call this from an async context" not in body


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True})
@pytest.mark.parametrize("may_view_post", [False, True])
async def test_ws_provider_resolves_cold_real_user_permissions(
    may_view_post: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WS must prune from real permissions without ORM work on its event loop.

    Args:
        may_view_post: Whether the subscription is permitted.
        monkeypatch: The fixture replacing subscription startup with a bounded result.
    """
    from django_graphex.subscriptions.transports import ws

    async def _start(*args: Any, **kwargs: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(ws, "create_source_event_stream", _start)
    user = await _real_user(may_view_post=may_view_post)
    consumer = _ws_consumer(
        {"user": user},
        schema_provider=lambda connection_user: pruned_schema_for(
            connection_user, _full_labeled_schema()
        ),
    )
    await consumer._run_operation("cold", {"query": _SUB_QUERY})
    frames = json.dumps(consumer._sent)
    assert ("Cannot query field 'post'" in frames) is not may_view_post
    assert "You cannot call this from an async context" not in frames


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True})
async def test_ws_real_auth_handshake_prunes_cold_permissions() -> None:
    """A real authenticated socket validates against cold user grants.

    The request crosses Channels' actual authentication handshake before the
    provider reads the Django user's permissions.
    """
    from django_graphex.subscriptions.transports.ws import subscription_ws_consumer

    user = await _real_user(may_view_post=False)
    cookie = await sync_to_async(_session_cookie, thread_sensitive=True)(user)
    app = subscription_ws_consumer(
        schema_provider=lambda connection_user: pruned_schema_for(
            connection_user, _full_labeled_schema()
        )
    )
    communicator = _communicator(app, session_cookie=cookie)
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "connection_init"})
    assert (await communicator.receive_json_from(timeout=2))["type"] == "connection_ack"
    await communicator.send_json_to(
        {"id": "cold", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    response = await communicator.receive_json_from(timeout=2)
    assert response["type"] == "error"
    assert "Cannot query field 'post'" in json.dumps(response["payload"])
    await communicator.disconnect()


async def test_sync_providers_preserve_context_and_error_paths() -> None:
    """Thread adaptation preserves context variables and transport errors.

    SSE keeps a provider exception before stream startup; WebSocket frames it
    for the affected operation.

    Raises:
        ValueError: The intentionally failing SSE provider raises this inside
            a captured exception assertion.
    """
    from django_graphex.subscriptions.transports import sse

    context_value: ContextVar[str] = ContextVar("provider-context")
    token = context_value.set("request-scope")
    seen: list[str] = []

    def provider(user: Any) -> Any:
        """Read request context from the synchronous provider thread.

        Args:
            user: The connection's user.

        Returns:
            A schema whose requested field is absent.
        """
        seen.append(context_value.get())
        return _full_labeled_schema()

    try:
        request = RequestFactory().post(
            "/subscriptions/sse",
            data=json.dumps({"query": _SUB_QUERY}),
            content_type="application/json",
        )
        request.user = None
        await sse.subscription_sse_view(schema_provider=provider)(request)
        consumer = _ws_consumer({"user": None}, schema_provider=provider)
        await consumer._run_operation("context", {"query": _SUB_QUERY})
        assert seen == ["request-scope", "request-scope"]

        def broken_provider(user: Any) -> Any:
            """Raise the existing provider error without replacing its type.

            Args:
                user: The connection's user.

            Raises:
                ValueError: Always, to exercise transport error behavior.
            """
            raise ValueError("provider failure")

        with pytest.raises(ValueError, match="provider failure"):
            await sse.subscription_sse_view(schema_provider=broken_provider)(request)
        consumer = _ws_consumer({"user": None}, schema_provider=broken_provider)
        await consumer._run_operation_framed("failure", {"query": _SUB_QUERY})
        assert "provider failure" not in json.dumps(consumer._sent)
        assert "INTERNAL_SERVER_ERROR" in json.dumps(consumer._sent)
    finally:
        context_value.reset(token)


async def test_ws_concurrent_operations_resolve_provider_once() -> None:
    """Concurrent operations on one socket share its first schema.

    The second operation must not invoke the provider again while the first
    awaits the thread-sensitive worker.
    """
    schema = _full_labeled_schema()
    calls = 0

    def provider(user: Any) -> Any:
        """Record a synchronous provider invocation.

        Args:
            user: The socket user.

        Returns:
            The schema for this socket.
        """
        nonlocal calls
        calls += 1
        return schema

    consumer = _ws_consumer({"user": None}, schema_provider=provider)
    first, second = await asyncio.gather(
        consumer._resolve_schema(), consumer._resolve_schema()
    )
    assert first is schema and second is schema
    assert calls == 1
