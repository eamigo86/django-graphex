"""Optional Redis-backed, token-owned SSE connection leases.

One sorted set per authenticated account holds opaque lease tokens scored by
expiry according to Redis server time. Each Lua operation is atomic at the
shared Redis instance; a failed or expired renewal never recreates a token.
This is a bounded availability control, not a consensus guarantee across
Redis failover or network partitions.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_TTL_MS = 45_000
_RENEW_INTERVAL = 15.0
# After a failed renewal the stream retries sooner than a full interval, and
# gives up this long before the lease could expire on the Redis side.
_RETRY_INTERVAL = 5.0
_SAFETY_MARGIN = 5.0
_REDIS_TIMEOUT_SECONDS = 2.0
# Pooled connections live as long as the process; ping idle ones so a
# connection dropped by a proxy or NAT is replaced instead of failing a command.
_HEALTH_CHECK_SECONDS = 30

_ACQUIRE = """-- sse-acquire
local time = redis.call('TIME')
local now = time[1] * 1000 + math.floor(time[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]) * 2)
return 1
"""

_RENEW = """-- sse-renew
local time = redis.call('TIME')
local now = time[1] * 1000 + math.floor(time[2] / 1000)
local expiry = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not expiry or tonumber(expiry) <= now then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) * 2)
return 1
"""

_RELEASE = """-- sse-release
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


async def _run_blocking(operation: Any) -> Any:
    """Finish a synchronous Redis operation even if the caller is cancelled.

    Args:
        operation: A zero-argument blocking operation.

    Returns:
        The operation result.

    Raises:
        BaseException: Propagates operation errors or caller cancellation after
            the operation has settled, so its ownership state is knowable.
    """
    task = asyncio.create_task(asyncio.to_thread(operation))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            # A second cancellation must not cancel the worker while Redis can
            # still commit its command. Keep waiting until ownership is known.
            cancelled = True
        except Exception:  # noqa: BLE001 - cancellation remains authoritative
            if cancelled:
                raise asyncio.CancelledError from None
            raise
        else:
            if cancelled:
                raise asyncio.CancelledError
            return result


def _principal_key(user: Any) -> str:
    """Derive a stable, non-session Redis key from a Django account identity.

    Args:
        user: An authenticated user with a persistent primary key.

    Returns:
        A namespaced digest shared by every worker for the same account.

    Raises:
        ValueError: If the account has no persistent primary key.
    """
    pk = getattr(user, "pk", None)
    if pk is None:
        raise ValueError("An authenticated SSE account needs a persistent primary key.")
    meta = getattr(user, "_meta", None)
    label = (
        meta.label_lower
        if meta is not None
        else f"{type(user).__module__}.{type(user).__qualname__}"
    )
    digest = hashlib.sha256(f"{label}:{pk}".encode()).hexdigest()
    return f"django-graphex:sse:account:{digest}"


class _Lease:
    """Own one token until the stream ends or the lease is lost.

    The Redis client is shared per URL and is never closed by a lease.
    """

    def __init__(self, client: Any, key: str, token: str) -> None:
        """Record ownership and synchronize cross-loop response-close callbacks.

        Args:
            client: The optional synchronous Redis client.
            key: Stable account key.
            token: Unique opaque lease token.
        """
        # Loop time of the last confirmed renewal, kept by the running stream.
        self.renewed_at: float | None = None
        self._client = client
        self._key = key
        self._token = token
        self._lock = threading.Lock()
        self._closed = False

    def _renew_blocking(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            return bool(self._client.eval(_RENEW, 1, self._key, self._token, _TTL_MS))

    async def renew(self) -> bool:
        """Renew only the still-live token, without resurrecting expired slots.

        Returns:
            Whether the original token still owned an unexpired slot.

        Raises:
            Exception: When the Redis backend cannot confirm ownership.
        """
        return bool(await _run_blocking(self._renew_blocking))

    def may_still_own(self, now: float) -> bool:
        """Tell whether the last confirmed renewal still leaves a safe margin.

        Args:
            now: Current time on the same clock as "renewed_at".

        Returns:
            True while the lease cannot have expired yet, assuming the backend
            applied the last confirmed TTL; used to tolerate transient renewal
            errors without risking a stream that no longer owns its slot.
            False when no renewal was ever confirmed.
        """
        if self.renewed_at is None:
            return False
        return now < self.renewed_at + _TTL_MS / 1000 - _SAFETY_MARGIN

    def _close_blocking(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._client.eval(_RELEASE, 1, self._key, self._token)
            except Exception:  # noqa: BLE001 - the TTL is the final safety net
                logger.warning("Could not release an SSE lease; waiting for expiry.")

    async def close(self) -> None:
        """Release this token idempotently, including from response.close()."""
        await _run_blocking(self._close_blocking)


_clients: dict[str, tuple[Any, Any]] = {}
_clients_lock = threading.Lock()


def _shared_client(redis_cls: Any, url: str) -> Any:
    """Return the process-wide Redis client for a URL, creating it once.

    A client owns a thread-safe connection pool, so every stream of this
    process reuses it instead of opening one connection per stream.

    Args:
        redis_cls: The Redis client class from the optional dependency.
        url: Operator-configured Redis URL.

    Returns:
        The shared client for this class and URL.
    """
    with _clients_lock:
        cached = _clients.get(url)
        if cached is None or cached[0] is not redis_cls:
            client = redis_cls.from_url(
                url,
                socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
                socket_timeout=_REDIS_TIMEOUT_SECONDS,
                socket_keepalive=True,
                health_check_interval=_HEALTH_CHECK_SECONDS,
            )
            cached = _clients[url] = (redis_cls, client)
        return cached[1]


async def _acquire(user: Any, url: str, limit: int) -> _Lease | None:
    """Atomically admit a principal or report that its shared limit is full.

    Args:
        user: The authenticated Django account.
        url: Operator-configured Redis URL.
        limit: Maximum live SSE streams for the account.

    Returns:
        An owned lease, or None when the account is at its limit.

    Raises:
        Exception: When admission cannot be confirmed. Any possibly acquired
            token is released before the exception is propagated.
    """
    from redis import Redis  # optional; never imported by a base installation

    key = _principal_key(user)
    client = _shared_client(Redis, url)
    for attempt in (1, 2):
        token = uuid4().hex
        try:
            admitted = await _run_blocking(
                lambda: client.eval(_ACQUIRE, 1, key, token, limit, _TTL_MS)
            )
            break
        except BaseException as exc:
            # The network may fail AFTER Redis admits the token, or the request
            # may be cancelled during the handshake. Never leave an unknown
            # grant live.
            try:
                await _run_blocking(lambda: client.eval(_RELEASE, 1, key, token))
            except Exception:  # noqa: BLE001 - TTL expires an unknown grant
                logger.warning("Could not confirm SSE admission cleanup; TTL applies.")
            # A pooled connection may have gone stale: retry once with a fresh
            # token. Cancellation and the second failure propagate.
            if attempt == 2 or not isinstance(exc, Exception):
                raise
    if not admitted:
        return None
    return _Lease(client, key, token)
