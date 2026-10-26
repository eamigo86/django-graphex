"""Explicit SSE lease integration tests against an owned Redis process.

These tests are deliberately outside the default tests discovery path. Set
"DJANGO_GRAPHEX_LIVE_REDIS_SERVER" and "DJANGO_GRAPHEX_LIVE_REDIS_CLIENT_DIR"
to verified, isolated artifacts before invoking this file explicitly.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket as network_socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from channels.layers import InMemoryChannelLayer
from django.test import RequestFactory, override_settings

from django_graphex.subscriptions.transports import _sse_lease, sse
from tests.subscriptions._transport_schema import build_native_schema


class _User:
    """Give every process the same persistent account identity."""

    is_authenticated = True
    _meta = SimpleNamespace(label_lower="live_redis.account")

    def __init__(self, pk: int = 42) -> None:
        self.pk = pk


def _line(process: subprocess.Popen[bytes], timeout: float = 5.0) -> dict[str, Any]:
    """Read one child result and retain bounded stderr on failure.

    Args:
        process: Child process expected to write a result line.
        timeout: Maximum seconds to wait for the result.

    Returns:
        The decoded child result.

    Raises:
        AssertionError: If the child exits or fails to report in time.
    """

    def failure(reason: str) -> AssertionError:
        """Include available child stderr without blocking on a live child.

        Args:
            reason: Reason the result was unavailable.

        Returns:
            An assertion with bounded diagnostic output.
        """
        assert process.stderr is not None
        error_fd = process.stderr.fileno()
        os.set_blocking(error_fd, False)
        chunks = bytearray()
        while len(chunks) < 8192:
            try:
                part = os.read(error_fd, 8192 - len(chunks))
            except BlockingIOError:
                break
            if not part:
                break
            chunks.extend(part)
        return AssertionError(
            f"{reason}; child stderr (up to 8192 bytes): "
            f"{chunks.decode(errors='replace')}"
        )

    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    data = bytearray()
    fd = process.stdout.fileno()
    os.set_blocking(fd, False)
    while time.monotonic() < deadline:
        try:
            part = os.read(fd, 1)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if not part:
            raise failure(f"child exited before result: {process.poll()}")
        if part == b"\n":
            return json.loads(data)
        data.extend(part)
    raise failure("child did not report within five seconds")


def _stop_child(process: subprocess.Popen[bytes]) -> None:
    """Stop only the child process owned by this test."""
    if process.poll() is None:
        try:
            assert process.stdin is not None
            process.stdin.write(b"STOP\n")
            process.stdin.flush()
            process.wait(timeout=5)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    if process.stdin is not None:
        process.stdin.close()
    if process.stdout is not None:
        process.stdout.close()


@pytest.fixture(scope="session")
def live_redis() -> Iterator[tuple[str, str, Any, Path, subprocess.Popen[bytes]]]:
    """Start and finally stop a private, persistence-free Redis server.

    Yields:
        The Unix URL, loopback URL, client, private directory, and process.
    """
    server_name = os.environ.get("DJANGO_GRAPHEX_LIVE_REDIS_SERVER")
    client_name = os.environ.get("DJANGO_GRAPHEX_LIVE_REDIS_CLIENT_DIR")
    if not server_name or not client_name:
        pytest.fail(
            "Set both DJANGO_GRAPHEX_LIVE_REDIS_SERVER and DJANGO_GRAPHEX_LIVE_REDIS_CLIENT_DIR for this explicit suite."
        )
    server = Path(server_name).resolve(strict=True)
    client_dir = Path(client_name).resolve(strict=True)
    import redis

    assert Path(redis.__file__).resolve().is_relative_to(client_dir)
    assert redis.__version__ == "8.1.0"
    assert server.is_file() and os.access(server, os.X_OK)
    private = Path(tempfile.mkdtemp(prefix="dgx-ls1-", dir="/private/tmp"))
    private.chmod(0o700)
    assert private.stat().st_uid == os.getuid()
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    unix_socket = private / "r.sock"
    unix_url = f"unix://{unix_socket}"
    # The public setting intentionally accepts only redis:// or rediss://.
    # Reserve a fresh loopback port rather than probing an ambient service.
    with network_socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    tcp_url = f"redis://127.0.0.1:{port}/0"
    command = [
        str(server),
        "--bind",
        "127.0.0.1",
        "--port",
        str(port),
        "--unixsocket",
        str(unix_socket),
        "--unixsocketperm",
        "700",
        "--save",
        "",
        "--appendonly",
        "no",
        "--daemonize",
        "no",
        "--dir",
        str(private),
        "--logfile",
        str(private / "redis.log"),
        "--protected-mode",
        "yes",
    ]
    process = subprocess.Popen(
        command,
        cwd=private,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = redis.Redis.from_url(unix_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        deadline = time.monotonic() + 5
        while (
            not unix_socket.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert process.poll() is None, (
            process.returncode,
            (private / "redis.log").read_text(),
        )
        assert unix_socket.exists()
        assert stat.S_IMODE(unix_socket.stat().st_mode) == 0o700
        assert client.ping() is True
        assert client.info("server")["redis_version"] == "8.10.2"
        assert client.info("server")["process_id"] == process.pid
        tcp_client = redis.Redis.from_url(
            tcp_url, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            assert tcp_client.info("server")["process_id"] == process.pid
        finally:
            tcp_client.close()
        print(
            f"OWNED_REDIS_START pid={process.pid} uid={os.getuid()} "
            f"dir={private} socket={unix_socket} port={port}",
            flush=True,
        )
        yield unix_url, tcp_url, client, private, process
    finally:
        client.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        assert process.poll() is not None
        print(
            f"OWNED_REDIS_STOP pid={process.pid} exit={process.returncode} "
            f"dir={private}",
            flush=True,
        )


@pytest.fixture
def redis_case(
    live_redis: tuple[str, str, Any, Path, subprocess.Popen[bytes]],
) -> Iterator[tuple[str, str, Any, Path]]:
    """Isolate client pools and clear the newly owned database between cases.

    Args:
        live_redis: The owned session fixture.

    Yields:
        The two URLs, client, and private directory for this case.
    """
    unix_url, tcp_url, client, private, _ = live_redis

    # The server URL is constant for this session. A client cached by a previous
    # case would bypass a later case's monkeypatched from_url failure wrapper.
    def clear_case_clients() -> None:
        """Close only clients cached for the test-owned Redis endpoints."""
        with _sse_lease._clients_lock:
            cached = [_sse_lease._clients.pop(url, None) for url in (unix_url, tcp_url)]
        for entry in cached:
            if entry is not None:
                entry[1].close()

    clear_case_clients()
    client.flushdb()
    try:
        yield unix_url, tcp_url, client, private
    finally:
        clear_case_clients()


def _request(pk: int = 42) -> Any:
    """Create a valid SSE request for an authenticated principal."""
    request = RequestFactory().post(
        "/graphql/stream",
        data=json.dumps({"query": "subscription { post(action: CREATE) { id } }"}),
        content_type="application/json",
    )
    request.user = _User(pk)
    return request


_CHILD = """
import asyncio, json, os, sys
from types import SimpleNamespace
import redis
from django_graphex.subscriptions.transports._sse_lease import _acquire, _principal_key
class User:
    is_authenticated = True
    _meta = SimpleNamespace(label_lower='live_redis.account')
    pk = 42
print(json.dumps({'ready': os.getpid()}), flush=True)
assert sys.stdin.readline() == 'GO\\n'
lease = asyncio.run(_acquire(User(), os.environ['LIVE_REDIS_URL'], 5))
print(json.dumps({'pid': os.getpid(), 'admitted': lease is not None,
    'key': _principal_key(User()), 'token': lease._token if lease else None,
    'redis_origin': redis.__file__}), flush=True)
assert sys.stdin.readline() == 'STOP\\n'
if lease is not None:
    asyncio.run(lease.close())
"""


def test_real_lua_cross_process_cap(redis_case: tuple[str, str, Any, Path]) -> None:
    """Eight independent Python workers admit exactly five account leases.

    Args:
        redis_case: The freshly cleared owned Redis instance.
    """
    url, _, client, _ = redis_case
    children: list[subprocess.Popen[bytes]] = []
    try:
        for _ in range(8):
            process = subprocess.Popen(
                [sys.executable, "-B", "-c", _CHILD],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "LIVE_REDIS_URL": url},
            )
            children.append(process)
        ready = [_line(child) for child in children]
        assert len({entry["ready"] for entry in ready}) == 8
        for child in children:
            assert child.stdin is not None
            child.stdin.write(b"GO\n")
            child.stdin.flush()
        results = [_line(child) for child in children]
        assert len({entry["pid"] for entry in results}) == 8
        assert sum(entry["admitted"] for entry in results) == 5
        assert len({entry["token"] for entry in results if entry["admitted"]}) == 5
        assert all(
            re.fullmatch(r"[0-9a-f]{32}", entry["token"])
            for entry in results
            if entry["admitted"]
        )
        key = _sse_lease._principal_key(_User())
        assert {entry["key"] for entry in results} == {key}
        assert all(
            entry["redis_origin"].startswith(
                os.environ["DJANGO_GRAPHEX_LIVE_REDIS_CLIENT_DIR"]
            )
            for entry in results
        )
        assert client.zcard(key) == 5
    finally:
        for child in children:
            _stop_child(child)
    assert client.zcard(_sse_lease._principal_key(_User())) == 0


@pytest.mark.asyncio
async def test_real_lua_ownership_expiry_and_independent_accounts(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry never resurrects a token or lets an old owner delete its successor.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Shortens only this test's lease lifetime.
    """
    url, _, client, _ = redis_case
    monkeypatch.setattr(_sse_lease, "_TTL_MS", 250)
    first = await _sse_lease._acquire(_User(), url, 1)
    other = await _sse_lease._acquire(_User(43), url, 1)
    assert first is not None and other is not None
    assert first._key != other._key
    assert first._key == _sse_lease._principal_key(_User())
    assert first._key.startswith("django-graphex:sse:account:")
    assert len(first._key.rsplit(":", 1)[1]) == 64
    await asyncio.sleep(0.35)
    assert await first.renew() is False
    replacement = await _sse_lease._acquire(_User(), url, 1)
    assert replacement is not None and replacement._token != first._token
    await first.close()
    assert client.zrange(replacement._key, 0, -1) == [replacement._token.encode()]
    await replacement.close()
    await other.close()
    assert client.dbsize() == 0


@pytest.mark.asyncio
async def test_real_lua_unknown_acquire_reply_releases_committed_token(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost reply after a real Redis commit triggers token-specific cleanup.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Injects a lost reply after the real Lua command commits.

    Raises:
        AssertionError: If the committed token remains after the expected
            lost-reply error has been caught.
    """
    import redis

    url, _, client, _ = redis_case
    real_from_url = redis.Redis.from_url

    class LostReply:
        def __init__(self, real: Any) -> None:
            self.real = real

        def eval(self, script: str, *args: Any) -> Any:
            value = self.real.eval(script, *args)
            if "sse-acquire" in script:
                raise OSError("simulated lost acquire reply after actual Lua execution")
            return value

        def close(self) -> None:
            self.real.close()

    monkeypatch.setattr(
        redis.Redis,
        "from_url",
        classmethod(lambda cls, address, **kw: LostReply(real_from_url(address, **kw))),
    )
    with pytest.raises(OSError, match="simulated lost acquire reply"):
        await _sse_lease._acquire(_User(), url, 1)
    assert client.zcard(_sse_lease._principal_key(_User())) == 0


@pytest.mark.asyncio
async def test_real_lua_double_cancellation_waits_for_commit_then_releases(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated cancellation cannot race token cleanup ahead of a real commit.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Delays the reply after real Lua execution.
    """
    import redis

    url, _, client, _ = redis_case
    real_from_url = redis.Redis.from_url
    committed = threading.Event()
    return_reply = threading.Event()

    class DelayedReply:
        def __init__(self, real: Any) -> None:
            self.real = real

        def eval(self, script: str, *args: Any) -> Any:
            result = self.real.eval(script, *args)
            if "sse-acquire" in script:
                committed.set()
                assert return_reply.wait(timeout=3)
            return result

        def close(self) -> None:
            self.real.close()

    monkeypatch.setattr(
        redis.Redis,
        "from_url",
        classmethod(
            lambda cls, address, **kw: DelayedReply(real_from_url(address, **kw))
        ),
    )
    acquire = asyncio.create_task(_sse_lease._acquire(_User(), url, 1))
    try:
        committed_in_time = await asyncio.wait_for(
            asyncio.to_thread(committed.wait, 2), 3
        )
        if not committed_in_time:
            error = None
            if acquire.done() and not acquire.cancelled():
                error = repr(acquire.exception())
            assert committed_in_time, f"acquire did not commit; task exception: {error}"
        assert client.zcard(_sse_lease._principal_key(_User())) == 1
        acquire.cancel()
        acquire.cancel()
    finally:
        return_reply.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(acquire, 4)
    assert client.zcard(_sse_lease._principal_key(_User())) == 0


@pytest.mark.asyncio
async def test_real_lua_crashed_owner_expires_without_release(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process exit without cleanup leaves only a bounded short test lease.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Shortens only this test's lease lifetime.
    """
    url, _, client, _ = redis_case
    monkeypatch.setattr(_sse_lease, "_TTL_MS", 250)
    child_script = """
import asyncio, json, os
from types import SimpleNamespace
from django_graphex.subscriptions.transports import _sse_lease
class User:
    _meta = SimpleNamespace(label_lower='live_redis.account')
    pk = 42
_sse_lease._TTL_MS = 250
lease = asyncio.run(_sse_lease._acquire(User(), os.environ['LIVE_REDIS_URL'], 1))
print(json.dumps({'pid': os.getpid(), 'admitted': lease is not None}), flush=True)
os._exit(0)
"""
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", child_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "LIVE_REDIS_URL": url},
    )
    try:
        result = _line(child)
        assert result["pid"] == child.pid and result["admitted"] is True
        assert child.wait(timeout=3) == 0
        assert client.zcard(_sse_lease._principal_key(_User())) == 1
        await asyncio.sleep(0.35)
        replacement = await _sse_lease._acquire(_User(), url, 1)
        assert replacement is not None
        await replacement.close()
        assert client.dbsize() == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)
        if child.stdout is not None:
            child.stdout.close()
        if child.stderr is not None:
            child.stderr.close()


@pytest.mark.asyncio
async def test_public_sse_live_cap_and_cleanup(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine Redis sixth admission is HTTP 429 before source startup.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Supplies an isolated channel layer.
    """
    _, url, client, _ = redis_case
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    view = sse.subscription_sse_view(schema=build_native_schema())
    responses = []
    key = _sse_lease._principal_key(_User())
    with override_settings(
        DJANGO_GRAPHEX={
            "SSE_CONNECTION_LIMIT_ENABLED": True,
            "SSE_MAX_CONNECTIONS_PER_USER": 5,
            "SSE_CONNECTION_REDIS_URL": url,
        }
    ):
        try:
            responses = [await view(_request()) for _ in range(5)]
            assert [response.status_code for response in responses] == [200] * 5
            assert client.zcard(key) == 5
            denied = await view(_request())
            assert denied.status_code == 429
            assert sse.get_started_source(denied) is None
            assert client.zcard(key) == 5
            await sync_to_async(responses[0].close)()
            assert client.zcard(key) == 4
            replacement = await view(_request())
            assert replacement.status_code == 200
            responses.append(replacement)
        finally:
            for response in responses:
                await sync_to_async(response.close)()
    assert client.zcard(key) == 0


@pytest.mark.asyncio
async def test_public_sse_live_backend_unavailable_is_503_before_source(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected database on the owned coordinator fails before source startup.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Supplies an isolated channel layer.
    """
    _, tcp_url, _, _ = redis_case
    unavailable_url = tcp_url.rsplit("/", 1)[0] + "/999999"
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    with override_settings(
        DJANGO_GRAPHEX={
            "SSE_CONNECTION_LIMIT_ENABLED": True,
            "SSE_CONNECTION_REDIS_URL": unavailable_url,
        }
    ):
        response = await sse.subscription_sse_view(schema=build_native_schema())(
            _request()
        )
    assert response.status_code == 503
    assert sse.get_started_source(response) is None


@pytest.mark.asyncio
async def test_public_sse_live_source_start_failure_releases_lease(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source-start exception releases the real admitted Redis slot.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Injects a source-start error after real admission.

    Raises:
        AssertionError: If the admitted lease remains after the expected
            source-start error has been caught.
    """
    _, url, client, _ = redis_case
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )

    async def fail_source(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("test-only source startup failure")

    monkeypatch.setattr(sse, "_start_source_event_stream", fail_source)
    with override_settings(
        DJANGO_GRAPHEX={
            "SSE_CONNECTION_LIMIT_ENABLED": True,
            "SSE_CONNECTION_REDIS_URL": url,
        }
    ):
        with pytest.raises(RuntimeError, match="test-only source startup failure"):
            await sse.subscription_sse_view(schema=build_native_schema())(_request())
    assert client.zcard(_sse_lease._principal_key(_User())) == 0


@pytest.mark.asyncio
async def test_public_sse_live_normal_source_completion_releases_lease(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Natural stream completion closes its source and real Redis lease.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Supplies an isolated channel layer.
    """
    _, url, client, _ = redis_case
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    with override_settings(
        DJANGO_GRAPHEX={
            "SSE_CONNECTION_LIMIT_ENABLED": True,
            "SSE_CONNECTION_REDIS_URL": url,
        }
    ):
        response = await sse.subscription_sse_view(schema=build_native_schema())(
            _request()
        )
        assert response.status_code == 200
        source = sse.get_started_source(response)
        assert source is not None
        stream = response.streaming_content.__aiter__()
        assert await stream.__anext__() == b":\n\n"
        await source.aclose()
        assert await asyncio.wait_for(stream.__anext__(), 2) == sse._COMPLETE_FRAME
        await stream.aclose()
        await sync_to_async(response.close)()
        assert client.zcard(_sse_lease._principal_key(_User())) == 0


@pytest.mark.asyncio
async def test_public_sse_live_midstream_loss_is_generic_and_closes(
    redis_case: tuple[str, str, Any, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deleted real Redis lease yields no application payload after ownership loss.

    Args:
        redis_case: The freshly cleared owned Redis instance.
        monkeypatch: Advances only this test's renewal deadline.
    """
    _, url, client, _ = redis_case
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda: InMemoryChannelLayer()
    )
    monkeypatch.setattr(sse, "_RENEW_INTERVAL", 0.03)
    with override_settings(
        DJANGO_GRAPHEX={
            "SSE_CONNECTION_LIMIT_ENABLED": True,
            "SSE_CONNECTION_REDIS_URL": url,
        }
    ):
        response = await sse.subscription_sse_view(schema=build_native_schema())(
            _request()
        )
        assert response.status_code == 200
        source = sse.get_started_source(response)
        assert source is not None
        stream = response.streaming_content.__aiter__()
        assert await stream.__anext__() == b":\n\n"
        client.delete(_sse_lease._principal_key(_User()))
        next_frame = await asyncio.wait_for(stream.__anext__(), 2)
        assert b"SSE stream lease lost; reconnect to retry." in next_frame
        assert b'"data"' not in next_frame
        assert await stream.__anext__() == sse._COMPLETE_FRAME
        await stream.aclose()
        await sync_to_async(response.close)()
        assert source.is_closed
        assert client.dbsize() == 0
