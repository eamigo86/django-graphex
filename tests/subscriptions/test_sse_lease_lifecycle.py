"""Deterministic regressions for bounded SSE lease lifecycle ownership."""

from __future__ import annotations

import asyncio
import threading
import types
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from channels.layers import InMemoryChannelLayer
from django.test import override_settings
from graphql import ExecutionResult

from django_graphex.subscriptions.transports import sse
from django_graphex.subscriptions.transports._sse_lease import _acquire
from tests.subscriptions._transport_schema import build_native_schema
from tests.subscriptions.test_sse_controls import _install_fake_redis, _request, _User
from tests.subscriptions.test_transport_sse import _notify

pytestmark = pytest.mark.django_db
_SETTINGS = {
    "SSE_CONNECTION_LIMIT_ENABLED": True,
    "SSE_MAX_CONNECTIONS_PER_USER": 1,
    "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    "SSE_HEARTBEAT_ENABLED": False,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("expiry_phase", ["source_start", "before_body"])
@override_settings(DJANGO_GRAPHEX=_SETTINGS)
async def test_expired_initial_lease_never_delivers_application_data(
    monkeypatch: pytest.MonkeyPatch, expiry_phase: str
) -> None:
    """Reject expired startup or frame loss rather than dispatching stale data.

    Args:
        monkeypatch: Replaces the backend with a deterministic protocol fake.
        expiry_phase: Whether expiry occurs at source start or before body read.
    """
    fake = _install_fake_redis(monkeypatch)
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda: layer)
    original = sse._start_source_event_stream

    async def delayed_start(*args: Any, **kwargs: Any) -> Any:
        source = await original(*args, **kwargs)
        fake.now += 45_001
        return source

    if expiry_phase == "source_start":
        monkeypatch.setattr(sse, "_start_source_event_stream", delayed_start)
    first = await sse.subscription_sse_view(schema=build_native_schema())(_request())
    monkeypatch.setattr(sse, "_start_source_event_stream", original)
    if expiry_phase == "before_body":
        fake.now += 45_001
    second = await sse.subscription_sse_view(schema=build_native_schema())(_request())
    try:
        if expiry_phase == "source_start":
            assert first.status_code == 503
            assert second.status_code == 200
            return
        assert first.status_code == second.status_code == 200
        stream = first.streaming_content.__aiter__()
        assert await stream.__anext__() == b":\n\n"
        source = sse.get_started_source(first)
        assert source is not None
        group = source.joined_groups[0]
        await layer.group_send(group, _notify(group, {"id": 1}))
        frame = await asyncio.wait_for(stream.__anext__(), 1)
        assert b"SSE stream lease lost" in frame
        assert b'"id":1' not in frame
        await stream.aclose()
    finally:
        await sync_to_async(first.close)()
        await sync_to_async(second.close)()


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_SETTINGS)
async def test_ready_events_still_renew_overdue_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ready results cannot starve ownership maintenance for eighty seconds.

    Args:
        monkeypatch: Supplies controlled local and backend clocks.
    """
    fake = _install_fake_redis(monkeypatch)
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    clock = types.SimpleNamespace(now=1000.0)
    proxy = types.SimpleNamespace(
        **{key: getattr(asyncio, key) for key in ("create_task", "wait", "gather")}
    )
    proxy.get_running_loop = lambda: types.SimpleNamespace(time=lambda: clock.now)
    monkeypatch.setattr(sse, "asyncio", proxy)

    async def ready_delivery(*args: Any) -> Any:
        try:
            for number in range(5):
                clock.now += 16
                fake.now += 16_000
                yield ExecutionResult(data={"probe": number})
        finally:
            await args[0].aclose()

    monkeypatch.setattr(sse, "drive_subscription", ready_delivery)
    response = await sse.subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    try:
        assert await stream.__anext__() == b":\n\n"
        frames = [await asyncio.wait_for(stream.__anext__(), 1) for _ in range(5)]
        assert all(b'"probe"' in frame for frame in frames)
        assert fake.renew_calls >= 5
    finally:
        await stream.aclose()
        await sync_to_async(response.close)()


@pytest.mark.asyncio
async def test_repeated_cancellation_settles_admission_before_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two cancellations cannot leave an in-flight acquired token orphaned.

    Args:
        monkeypatch: Installs a barrier-controlled fake backend.
    """
    fake = _install_fake_redis(monkeypatch)
    entered = threading.Event()
    permit = threading.Event()
    committed = threading.Event()
    released = threading.Event()
    original = fake.eval

    def ordered_eval(script: str, key_count: int, key: str, *args: Any) -> int:
        if "sse-acquire" in script:
            entered.set()
            assert permit.wait(2)
            result = original(script, key_count, key, *args)
            committed.set()
            return result
        result = original(script, key_count, key, *args)
        if "sse-release" in script:
            released.set()
        return result

    monkeypatch.setattr(fake, "eval", ordered_eval)
    task = asyncio.create_task(_acquire(_User(), "redis://unused/0", 1))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release_before_commit = await asyncio.to_thread(released.wait, 0.3)
        permit.set()
        assert await asyncio.to_thread(committed.wait, 1)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not release_before_commit
        assert released.is_set()
        assert not fake.slots
    finally:
        permit.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_SETTINGS)
async def test_backend_error_after_start_closes_source_before_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup revalidation error cannot leave a group joined.

    Args:
        monkeypatch: Injects the backend fault after source startup.
    """
    fake = _install_fake_redis(monkeypatch)
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    sources: list[Any] = []
    original = sse._start_source_event_stream

    async def fail_after_start(*args: Any, **kwargs: Any) -> Any:
        source = await original(*args, **kwargs)
        sources.append(source)
        fake.fail_renew = True
        return source

    monkeypatch.setattr(sse, "_start_source_event_stream", fail_after_start)
    response = await sse.subscription_sse_view(schema=build_native_schema())(_request())
    assert response.status_code == 503
    assert len(sources) == 1 and sources[0].is_closed
    assert not fake.slots


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_SETTINGS)
async def test_cancelled_startup_revalidation_closes_source_and_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation during startup validation closes both owned resources.

    Args:
        monkeypatch: Supplies a lease that cancels during its ownership check.

    Raises:
        asyncio.CancelledError: Injected while checking startup ownership.
    """
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    sources: list[Any] = []
    original = sse._start_source_event_stream

    async def record_source(*args: Any, **kwargs: Any) -> Any:
        source = await original(*args, **kwargs)
        sources.append(source)
        return source

    class CancellingLease:
        closed = False

        async def renew(self) -> bool:
            raise asyncio.CancelledError

        async def close(self) -> None:
            self.closed = True

    lease = CancellingLease()

    async def acquire(*args: Any) -> CancellingLease:
        return lease

    monkeypatch.setattr(sse, "_acquire", acquire)
    monkeypatch.setattr(sse, "_start_source_event_stream", record_source)
    with pytest.raises(asyncio.CancelledError):
        await sse.subscription_sse_view(schema=build_native_schema())(_request())
    assert len(sources) == 1 and sources[0].is_closed
    assert lease.closed


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_SETTINGS)
async def test_consumer_delay_rechecks_before_next_source_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A paused consumer renews before reading again, or stops on failure.

    Args:
        monkeypatch: Advances the loop and backend clocks between frames.
    """
    fake = _install_fake_redis(monkeypatch)
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    clock = types.SimpleNamespace(now=1000.0)
    proxy = types.SimpleNamespace(
        **{key: getattr(asyncio, key) for key in ("create_task", "wait", "gather")}
    )
    proxy.get_running_loop = lambda: types.SimpleNamespace(time=lambda: clock.now)
    monkeypatch.setattr(sse, "asyncio", proxy)

    async def ready_delivery(*args: Any) -> Any:
        try:
            for number in range(3):
                yield ExecutionResult(data={"probe": number})
        finally:
            await args[0].aclose()

    monkeypatch.setattr(sse, "drive_subscription", ready_delivery)
    response = await sse.subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    try:
        assert await stream.__anext__() == b":\n\n"
        assert b'"probe": 0' in await stream.__anext__()
        before = fake.renew_calls
        clock.now += 16
        fake.now += 16_000
        assert b'"probe": 1' in await stream.__anext__()
        assert fake.renew_calls == before + 1
        clock.now += 41
        fake.now += 41_000
        fake.fail_renew = True
        frame = await stream.__anext__()
        assert b"SSE stream lease lost" in frame
        assert b'"probe": 2' not in frame
    finally:
        await stream.aclose()
        await sync_to_async(response.close)()


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_SETTINGS)
async def test_overdue_ready_result_is_withheld_on_backend_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ready result cannot pass an overdue failed ownership check.

    Args:
        monkeypatch: Makes the backend fail during the awaited source read.
    """
    fake = _install_fake_redis(monkeypatch)
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    clock = types.SimpleNamespace(now=1000.0)
    proxy = types.SimpleNamespace(
        **{key: getattr(asyncio, key) for key in ("create_task", "wait", "gather")}
    )
    proxy.get_running_loop = lambda: types.SimpleNamespace(time=lambda: clock.now)
    monkeypatch.setattr(sse, "asyncio", proxy)

    async def failing_delivery(*args: Any) -> Any:
        try:
            clock.now += 41
            fake.now += 41_000
            fake.fail_renew = True
            yield ExecutionResult(data={"probe": "must-not-deliver"})
        finally:
            await args[0].aclose()

    monkeypatch.setattr(sse, "drive_subscription", failing_delivery)
    response = await sse.subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    try:
        assert await stream.__anext__() == b":\n\n"
        frame = await stream.__anext__()
        assert b"SSE stream lease lost" in frame
        assert b"must-not-deliver" not in frame
    finally:
        await stream.aclose()
        await sync_to_async(response.close)()
