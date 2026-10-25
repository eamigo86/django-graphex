"""Opt-in SSE heartbeat and authenticated-account admission contracts."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import types
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from channels.layers import InMemoryChannelLayer
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings

from django_graphex.settings import DEFAULTS, GraphQLAPISettings
from django_graphex.subscriptions.transports.sse import subscription_sse_view
from tests.subscriptions._transport_schema import build_native_schema
from tests.subscriptions.test_transport_sse import _notify

pytestmark = pytest.mark.django_db


class _User:
    """Represent one stable authenticated account in SSE tests."""

    is_authenticated = True
    pk = 42


def _request() -> Any:
    """Build a valid subscription request for a stable account.

    Returns:
        A request using the test account.
    """
    request = RequestFactory().post(
        "/graphql/stream",
        data=json.dumps({"query": "subscription { post(action: CREATE) { id } }"}),
        content_type="application/json",
    )
    request.user = _User()
    return request


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={"SSE_HEARTBEAT_ENABLED": True, "SSE_HEARTBEAT_INTERVAL": 0.01}
)
async def test_idle_heartbeat_keeps_one_source_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle comment must arrive without restarting the subscription source.

    Args:
        monkeypatch: Replaces the channel layer with an isolated in-memory layer.
    """
    from django_graphex.subscriptions.transports import sse

    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    assert response.status_code == 200
    source = sse.get_started_source(response)
    assert source is not None
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    assert await asyncio.wait_for(stream.__anext__(), 0.3) == b": heartbeat\n\n"
    assert sse.get_started_source(response) is source
    assert not source.is_closed
    await stream.aclose()
    await sync_to_async(response.close)()
    assert source.is_closed


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX={"SSE_HEARTBEAT_ENABLED": False})
async def test_heartbeat_remains_off_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle default SSE response must not emit a comment periodically.

    Args:
        monkeypatch: Replaces the channel layer with an isolated in-memory layer.
    """
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(stream.__anext__(), 0.03)
    await stream.aclose()
    await sync_to_async(response.close)()


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_MAX_CONNECTIONS_PER_USER": 1,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_second_account_stream_is_rejected_before_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An atomic account cap rejects the second connection without a group join.

    Args:
        monkeypatch: Installs an in-process Redis protocol fake for contract tests.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda: layer)
    redis = _install_fake_redis(monkeypatch)
    view = subscription_sse_view(schema=build_native_schema())
    first = await view(_request())
    assert first.status_code == 200
    source = sse.get_started_source(first)
    assert source is not None
    second = await view(_request())
    assert second.status_code == 429
    assert len(redis.slots) == 1
    assert not source.is_closed
    await sync_to_async(first.close)()
    assert not redis.slots
    third = await view(_request())
    assert third.status_code == 200
    await sync_to_async(third.close)()


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_backend_failure_is_pre_stream_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable admission backend must not start a subscription source.

    Args:
        monkeypatch: Installs a backend that fails every atomic command.
    """
    from django_graphex.subscriptions.transports import sse

    redis = _install_fake_redis(monkeypatch)
    redis.fail = True
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    assert response.status_code == 503
    assert sse.get_started_source(response) is None


class _FakeRedis:
    """Model token-specific sorted-set lease operations for contract tests."""

    slots: dict[str, dict[str, float]] = {}
    fail = False
    fail_renew = False
    fail_release = False
    renew_calls = 0
    now = 1_000.0

    def eval(self, script: str, key_count: int, key: str, *args: Any) -> int:
        """Execute only the three documented lease script shapes.

        Args:
            script: Atomic Lua operation with an identifying comment.
            key_count: Number of keys sent to Redis.
            key: Stable principal key.
            *args: Token, limit, and expiry as needed by the operation.

        Returns:
            One for success and zero for a full or lost lease.
        """
        assert key_count == 1
        if self.fail:
            raise OSError("backend unavailable")
        members = self.slots.setdefault(key, {})
        if "sse-acquire" in script:
            token, limit, ttl_ms = args
            for stale in [k for k, expiry in members.items() if expiry <= self.now]:
                del members[stale]
            if len(members) >= int(limit):
                return 0
            members[str(token)] = self.now + int(ttl_ms)
            return 1
        if "sse-renew" in script:
            self.renew_calls += 1
            if self.fail_renew:
                raise OSError("secret backend address")
            token, ttl_ms = args
            if members.get(str(token), 0) <= self.now:
                return 0
            members[str(token)] = self.now + int(ttl_ms)
            return 1
        if "sse-release" in script:
            if self.fail_release:
                raise OSError("release failed")
            removed = int(members.pop(str(args[0]), None) is not None)
            if not members:
                self.slots.pop(key, None)
            return removed
        raise AssertionError("unexpected Redis script")

    def close(self) -> None:
        """Match the synchronous Redis client close method."""


def _install_fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Provide one shared Redis protocol fake to all view instances.

    Args:
        monkeypatch: The fixture controlling module imports.

    Returns:
        The shared protocol fake for assertions.
    """
    fake = _FakeRedis()
    fake.slots = {}
    package = types.ModuleType("redis")
    package.Redis = types.SimpleNamespace(from_url=lambda url, **options: fake)
    monkeypatch.setitem(sys.modules, "redis", package)
    return fake


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_MAX_CONNECTIONS_PER_USER": 5,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_sixth_stream_is_429_and_existing_five_survive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented cap counts one stable account across independent views.

    Args:
        monkeypatch: Supplies the shared Redis protocol fake.
    """
    from django_graphex.subscriptions.transports import sse

    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    redis = _install_fake_redis(monkeypatch)
    schema = build_native_schema()
    responses = [
        await subscription_sse_view(schema=schema)(_request()) for _ in range(5)
    ]
    assert [response.status_code for response in responses] == [200] * 5
    sixth = await subscription_sse_view(schema=schema)(_request())
    assert sixth.status_code == 429
    assert all(
        (source := sse.get_started_source(response)) is not None
        and not source.is_closed
        for response in responses
    )
    assert sum(map(len, redis.slots.values())) == 5
    for response in responses:
        await sync_to_async(response.close)()
    assert not redis.slots


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_anonymous_request_does_not_access_account_lease_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anonymous SSE behavior is unchanged even if Redis is unavailable.

    Args:
        monkeypatch: Installs a backend configured to fail if accessed.
    """
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    redis = _install_fake_redis(monkeypatch)
    redis.fail = True
    request = _request()
    request.user.is_authenticated = False
    response = await subscription_sse_view(schema=build_native_schema())(request)
    assert response.status_code == 200
    assert not redis.slots
    await sync_to_async(response.close)()


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_source_start_failure_releases_reserved_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No lease survives a subscribe-entry failure before response creation.

    Args:
        monkeypatch: Replaces source startup with a deterministic failure.

    Raises:
        RuntimeError: Asserted from the injected source startup.
    """
    from django_graphex.subscriptions.transports import sse

    redis = _install_fake_redis(monkeypatch)

    async def fail_start(*args: Any, **kwargs: Any) -> Any:
        """Raise before a source can be returned.

        Args:
            *args: Unused source-start arguments.
            **kwargs: Unused source-start options.

        Raises:
            RuntimeError: Always, to exercise cleanup.
        """
        raise RuntimeError("source failed")

    monkeypatch.setattr(sse, "_start_source_event_stream", fail_start)
    with pytest.raises(RuntimeError, match="source failed"):
        await subscription_sse_view(schema=build_native_schema())(_request())
    assert not redis.slots


_RENEWAL_SETTINGS = {
    "SSE_CONNECTION_LIMIT_ENABLED": True,
    "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    "SSE_HEARTBEAT_ENABLED": False,
}


def _fast_renewal(monkeypatch: pytest.MonkeyPatch, ttl_ms: int = 300) -> None:
    """Shorten the renewal cadence, retry delay, TTL and safety margin.

    Args:
        monkeypatch: Replaces the module-level timing constants.
        ttl_ms: Lease TTL sent to the backend, in milliseconds.
    """
    from django_graphex.subscriptions.transports import _sse_lease, sse

    monkeypatch.setattr(sse, "_RENEW_INTERVAL", 0.01)
    monkeypatch.setattr(sse, "_RETRY_INTERVAL", 0.01)
    monkeypatch.setattr(_sse_lease, "_TTL_MS", ttl_ms)
    monkeypatch.setattr(_sse_lease, "_SAFETY_MARGIN", 0.05)


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_RENEWAL_SETTINGS)
async def test_transient_renewal_failure_keeps_stream_open(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One failed renewal inside the lease TTL does not close the stream.

    Args:
        monkeypatch: Shortens the renewal timing.
        caplog: Captures the retry diagnostic.
    """
    from django_graphex.subscriptions.transports import sse

    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    _fast_renewal(monkeypatch)
    redis = _install_fake_redis(monkeypatch)
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    waiting = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.03)
    redis.fail_renew = True
    await asyncio.sleep(0.05)
    redis.fail_renew = False
    calls = redis.renew_calls
    await asyncio.sleep(0.05)
    assert not waiting.done()
    assert redis.renew_calls > calls
    assert "renewal failed; retrying" in caplog.text
    assert "secret backend address" not in caplog.text
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await sync_to_async(response.close)()
    assert not redis.slots
    assert sse.get_started_source(response).is_closed


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_RENEWAL_SETTINGS)
async def test_first_stream_renewal_error_is_tolerated_after_acquire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acquisition confirms the TTL, so a failing first renewal is retried.

    Args:
        monkeypatch: Shortens timing and fails one in-stream renewal.

    Raises:
        AssertionError: If the stream closes or stops renewing.
    """
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    _fast_renewal(monkeypatch)
    redis = _install_fake_redis(monkeypatch)
    real_eval = redis.eval
    renews = []

    def flaky(script: str, key_count: int, key: str, *args: Any) -> int:
        """Fail only the second renewal, the first one made by the stream.

        Args:
            script: Atomic Lua operation.
            key_count: Number of keys.
            key: Principal key.
            *args: Operation arguments.

        Returns:
            The fake backend's result.

        Raises:
            OSError: On the stream's first renewal.
        """
        if "sse-renew" in script:
            renews.append(1)
            if len(renews) == 2:
                raise OSError("secret backend address")
        return real_eval(script, key_count, key, *args)

    redis.eval = flaky  # type: ignore[method-assign]
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    waiting = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.08)
    assert len(renews) > 2
    assert not waiting.done()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await sync_to_async(response.close)()
    assert not redis.slots


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_RENEWAL_SETTINGS)
async def test_renewal_failures_until_expiry_finish_stream_without_backend_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures that outlast the safe window close the stream without leaks.

    Args:
        monkeypatch: Shortens the renewal timing.
    """
    from django_graphex.subscriptions.transports import sse

    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    _fast_renewal(monkeypatch)
    redis = _install_fake_redis(monkeypatch)
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    source = sse.get_started_source(response)
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    redis.fail_renew = True
    failure = await asyncio.wait_for(stream.__anext__(), 1)
    assert b"event: next" in failure
    assert b"SSE stream lease lost" in failure
    assert b"secret backend address" not in failure
    assert await stream.__anext__() == b"event: complete\ndata: \n\n"
    await sync_to_async(response.close)()
    assert source.is_closed
    assert redis.renew_calls >= 2
    assert not redis.slots


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_RENEWAL_SETTINGS)
async def test_successful_renewal_resets_the_failure_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures separated by a good renewal never add up to a closed stream.

    Args:
        monkeypatch: Shortens the renewal timing.
    """
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    _fast_renewal(monkeypatch, ttl_ms=200)
    redis = _install_fake_redis(monkeypatch)
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    waiting = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.03)
    for _ in range(4):
        # Each outage alone fits the window; four in a row would not.
        redis.fail_renew = True
        await asyncio.sleep(0.06)
        redis.fail_renew = False
        await asyncio.sleep(0.04)
        assert not waiting.done()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await sync_to_async(response.close)()
    assert not redis.slots


@pytest.mark.asyncio
async def test_expired_lease_cannot_be_resurrected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale token loses ownership even when its Redis member still exists.

    Args:
        monkeypatch: Installs the shared lease backend fake.
    """
    from django_graphex.subscriptions.transports._sse_lease import _acquire

    redis = _install_fake_redis(monkeypatch)
    lease = await _acquire(_User(), "redis://unused/0", 1)
    assert lease is not None
    redis.now += 45_001
    assert await lease.renew() is False
    assert sum(map(len, redis.slots.values())) == 1
    other = await _acquire(_User(), "redis://unused/0", 1)
    assert other is not None
    assert await lease.renew() is False
    await lease.close()
    assert sum(map(len, redis.slots.values())) == 1
    await other.close()
    assert not redis.slots


@pytest.mark.asyncio
async def test_cancelled_unknown_admission_cleans_its_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation waits for an in-flight atomic grant then removes it.

    Args:
        monkeypatch: Injects a blocked Redis command to hit the race.

    Raises:
        CancelledError: Asserted for the cancelled admission request.
    """
    from django_graphex.subscriptions.transports._sse_lease import _acquire

    redis = _install_fake_redis(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    original = redis.eval

    def blocked_eval(script: str, key_count: int, key: str, *args: Any) -> int:
        """Pause a grant after admission begins.

        Args:
            script: Redis script.
            key_count: Number of keys.
            key: Principal key.
            *args: Script arguments.

        Returns:
            The fake backend result.
        """
        if "sse-acquire" in script:
            entered.set()
            assert release.wait(timeout=1)
        return original(script, key_count, key, *args)

    monkeypatch.setattr(redis, "eval", blocked_eval)
    task = asyncio.create_task(_acquire(_User(), "redis://unused/0", 1))
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not redis.slots


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_HEARTBEAT_ENABLED": True,
        "SSE_HEARTBEAT_INTERVAL": 0.01,
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_event_heartbeat_and_natural_completion_share_one_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An event resets the heartbeat deadline; completion releases the lease.

    Args:
        monkeypatch: Supplies one channel layer and lease backend.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda: layer)
    redis = _install_fake_redis(monkeypatch)
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    source = sse.get_started_source(response)
    assert source is not None
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    group = source.joined_groups[0]
    await layer.group_send(group, _notify(group, {"id": 1}))
    event = await asyncio.wait_for(stream.__anext__(), 1)
    assert b'"post": {"id": "1"}' in event
    assert await asyncio.wait_for(stream.__anext__(), 0.3) == b": heartbeat\n\n"
    assert sse.get_started_source(response) is source
    await source.aclose()
    assert (
        await asyncio.wait_for(stream.__anext__(), 1) == b"event: complete\ndata: \n\n"
    )
    await sync_to_async(response.close)()
    assert not redis.slots


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_HEARTBEAT_ENABLED": False,
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_healthy_lease_renews_without_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis renewal continues while no comment or subscription event is sent.

    Args:
        monkeypatch: Shortens renewal for the bounded test.
    """
    from django_graphex.subscriptions.transports import sse

    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    monkeypatch.setattr(sse, "_RENEW_INTERVAL", 0.01)
    redis = _install_fake_redis(monkeypatch)
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    waiting = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.05)
    assert redis.renew_calls >= 2
    assert not waiting.done()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await sync_to_async(response.close)()
    assert not redis.slots


@pytest.mark.asyncio
@override_settings(
    DJANGO_GRAPHEX={
        "SSE_CONNECTION_LIMIT_ENABLED": True,
        "SSE_CONNECTION_REDIS_URL": "redis://unused/0",
    }
)
async def test_subscribe_result_releases_unused_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-stream subscribe denial consumes no long-lived account slot.

    Args:
        monkeypatch: Replaces the source entry with an execution error.
    """
    from graphql import ExecutionResult, GraphQLError

    from django_graphex.subscriptions.transports import sse

    redis = _install_fake_redis(monkeypatch)

    async def deny_start(*args: Any, **kwargs: Any) -> Any:
        """Return the normal native subscribe-denial shape.

        Args:
            *args: Unused source-start arguments.
            **kwargs: Unused source-start options.

        Returns:
            An execution result with a generic error.
        """
        return ExecutionResult(data=None, errors=[GraphQLError("Denied")])

    monkeypatch.setattr(sse, "_start_source_event_stream", deny_start)
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    assert response.status_code == 200
    assert not redis.slots
    await sync_to_async(response.close)()


@pytest.mark.asyncio
async def test_missing_persistent_account_id_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authenticated identity without a stable PK cannot take a lease.

    Args:
        monkeypatch: Supplies the optional backend without a network service.

    Raises:
        ValueError: Asserted for the missing account identity.
    """
    from django_graphex.subscriptions.transports._sse_lease import _acquire

    redis = _install_fake_redis(monkeypatch)
    user = _User()
    user.pk = None
    with pytest.raises(ValueError, match="persistent primary key"):
        await _acquire(user, "redis://unused/0", 1)
    assert not redis.slots


@pytest.mark.asyncio
async def test_failed_release_is_bounded_by_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release outage does not raise into SSE teardown; expiry frees the slot.

    Args:
        monkeypatch: Injects a release-only Redis failure.
    """
    from django_graphex.subscriptions.transports._sse_lease import _acquire

    redis = _install_fake_redis(monkeypatch)
    lease = await _acquire(_User(), "redis://unused/0", 1)
    assert lease is not None
    redis.fail_release = True
    await lease.close()
    assert await lease.renew() is False
    assert sum(map(len, redis.slots.values())) == 1
    redis.fail_release = False
    redis.now += 45_001
    replacement = await _acquire(_User(), "redis://unused/0", 1)
    assert replacement is not None
    await replacement.close()
    assert not redis.slots


@pytest.mark.asyncio
async def test_cancelled_backend_failure_still_propagates_cancellation() -> None:
    """A failing blocked worker cannot convert cancellation into an outage reply.

    Raises:
        CancelledError: Asserted after the worker has settled.
    """
    from django_graphex.subscriptions.transports._sse_lease import _run_blocking

    entered = threading.Event()
    release = threading.Event()

    def fail_after_release() -> None:
        """Fail only after the waiting caller has been cancelled.

        Raises:
            OSError: Always, after the test releases the worker.
        """
        entered.set()
        assert release.wait(timeout=1)
        raise OSError("backend failed")

    task = asyncio.create_task(_run_blocking(fail_after_release))
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_controls_ship_disabled_with_independent_values() -> None:
    """The opt-in flags remain false while their values remain available.

    This pins both enablement and value defaults separately.
    """
    settings = GraphQLAPISettings({}, DEFAULTS, ())
    assert settings.SSE_HEARTBEAT_ENABLED is False
    assert settings.SSE_HEARTBEAT_INTERVAL == 15
    assert settings.SSE_CONNECTION_LIMIT_ENABLED is False
    assert settings.SSE_MAX_CONNECTIONS_PER_USER == 5
    assert settings.SSE_CONNECTION_REDIS_URL is None


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("SSE_HEARTBEAT_ENABLED", 1),
        ("SSE_CONNECTION_LIMIT_ENABLED", "true"),
        ("SSE_HEARTBEAT_INTERVAL", 0),
        ("SSE_HEARTBEAT_INTERVAL", float("nan")),
        ("SSE_MAX_CONNECTIONS_PER_USER", False),
        ("SSE_MAX_CONNECTIONS_PER_USER", -1),
        ("SSE_CONNECTION_REDIS_URL", "http://not-redis"),
    ],
)
def test_invalid_control_settings_fail_explicitly(name: str, bad: Any) -> None:
    """Misconfigured opt-in controls must not fail after a 200 response.

    Args:
        name: The setting under test.
        bad: An invalid value for the setting.

    Raises:
        ImproperlyConfigured: Asserted for the invalid value.
    """
    settings = GraphQLAPISettings({name: bad}, DEFAULTS, ())
    with pytest.raises(ImproperlyConfigured, match=name):
        getattr(settings, name)


@pytest.mark.asyncio
async def test_streams_share_one_client_per_redis_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leases reuse one client per URL and never close the shared client.

    Args:
        monkeypatch: Installs a Redis class that counts client creation.
    """
    from django_graphex.subscriptions.transports._sse_lease import _acquire

    redis = _install_fake_redis(monkeypatch)
    created: list[str] = []
    closed: list[str] = []
    original = sys.modules["redis"].Redis.from_url
    sys.modules["redis"].Redis.from_url = lambda url, **options: (
        created.append(url) or original(url, **options)
    )
    redis.close = lambda: closed.append("closed")  # type: ignore[method-assign]
    first = await _acquire(_User(), "redis://shared/0", 3)
    second = await _acquire(_User(), "redis://shared/0", 3)
    other = await _acquire(_User(), "redis://other/0", 3)
    assert first is not None and second is not None and other is not None
    assert created == ["redis://shared/0", "redis://other/0"]
    for lease in (first, second, other):
        await lease.close()
    assert closed == []
    assert not redis.slots


@pytest.mark.asyncio
@override_settings(DJANGO_GRAPHEX=_RENEWAL_SETTINGS)
async def test_initial_renewal_retry_delay_is_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed first in-stream renewal retries after the returned delay.

    Args:
        monkeypatch: Replaces the renewal helper with a scripted one.
    """
    from django_graphex.subscriptions.transports import sse

    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    _install_fake_redis(monkeypatch)
    monkeypatch.setattr(sse, "_RENEW_INTERVAL", 1000.0)
    calls: list[float] = []

    async def scripted(lease: Any, loop: asyncio.AbstractEventLoop) -> float:
        """Ask for a quick retry after the first call only.

        Args:
            lease: Ignored.
            loop: The running loop.

        Returns:
            A short delay once, then a very long one.
        """
        calls.append(loop.time())
        return 0.01 if len(calls) == 1 else 1000.0

    monkeypatch.setattr(sse, "_renew_lease", scripted)
    response = await subscription_sse_view(schema=build_native_schema())(_request())
    stream = response.streaming_content.__aiter__()
    assert await stream.__anext__() == b":\n\n"
    waiting = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0.15)
    assert len(calls) >= 2
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await sync_to_async(response.close)()


class _Clock:
    """Model the loop clock the lease code reads."""

    def __init__(self) -> None:
        """Start at an arbitrary instant."""
        self.now = 500.0

    def time(self) -> float:
        """Return the fake instant.

        Returns:
            The current fake loop time.
        """
        return self.now


class _ClockedClient:
    """Advance a fake clock while a Redis command is in flight."""

    def __init__(self, clock: _Clock) -> None:
        """Record the clock and the arguments of every command.

        Args:
            clock: The clock to advance by the command latency.
        """
        self.clock = clock
        self.fail = False
        self.latency = 0.0
        self.calls: list[tuple[Any, ...]] = []

    def eval(self, script: str, key_count: int, *args: Any) -> int:
        """Take "latency" seconds, then fail or confirm ownership.

        Args:
            script: Lua source, ignored.
            key_count: Key count, ignored.
            *args: Key, token and TTL.

        Returns:
            One when ownership is confirmed.

        Raises:
            OSError: While "fail" is set.
        """
        self.calls.append(args)
        self.clock.now += self.latency
        if self.fail:
            raise OSError("down")
        return 1


@pytest.mark.asyncio
async def test_lease_timing_uses_the_production_constants() -> None:
    """TTL 45 s, margin 5 s -> 40 s window; retry 5 s, renew 15 s, send stamp.

    Raises:
        AssertionError: If any production timing value or stamp drifts.
    """
    from django_graphex.subscriptions.transports import sse
    from django_graphex.subscriptions.transports._sse_lease import _Lease

    clock = _Clock()
    client = _ClockedClient(clock)
    lease = _Lease(client, "key", "token")
    client.latency = 3.0
    sent_at = clock.now
    delay = await sse._renew_lease(lease, clock)  # type: ignore[arg-type]
    assert delay == 15.0
    assert client.calls[-1][-1] == 45_000
    # Stamped when the command was SENT, not when it came back.
    assert lease.renewed_at == sent_at
    assert lease.may_still_own(sent_at + 39.99)
    assert not lease.may_still_own(sent_at + 40.0)

    client.fail = True
    clock.now = sent_at + 20.0
    assert await sse._renew_lease(lease, clock) == 5.0  # type: ignore[arg-type]
    clock.now = sent_at + 40.0
    with pytest.raises(sse._LeaseLost):
        await sse._renew_lease(lease, clock)  # type: ignore[arg-type]
