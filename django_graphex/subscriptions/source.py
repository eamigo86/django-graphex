"""ChannelLayerSource — the native subscription engine's group consumer.

This is the consumer half of the serialize-once data path (design section 3).
The PRODUCER ("SubscriptionBinding.broadcast" in "bindings.py") serializes a
changed instance ONCE into a SNAKE-keyed flat dict and fans it out to the
action/per-pk/indexed Channels groups via "group_send" with the envelope:

    {
        "type": "subscription.notify",
        "stream": <stream>,
        "group": <group name>,
        "pk": <primary key>,
        "payload": {"action": <action>, "model": <label>, "data": <flat dict>},
    }

"ChannelLayerSource" is a GROUP consumer (NOT a "WebsocketConsumer"): it is
async-iterator compatible ("__aiter__" / "__anext__") so the WU2
"DeliveryIterator" can wrap it directly. It joins EXACTLY the action-selected
groups, runs an async "receive()" loop, applies "split_filters" PRE-execute
(an in-memory equality drop yields NOTHING — zero downstream "execute()"), and
yields the already-serialized flat "data" dict for a matching event. The
consumer NEVER re-serializes (the serialize-once invariant): one producer-side
"serialize_instance" call feeds N subscribers.

The join set is computed by the CALLER ("drive_subscription"/a factory, WU5)
and passed in via "groups": "('create','update','delete')" for "all_actions"
else "(action,)" — this object never hardcodes all three (the #1420 bug guard).

Out-of-band close ("aclose()" / "__aexit__") "group_discard"s EVERY joined
group inside a "try/finally" so cleanup runs even on abnormal teardown (no
ghost subscribers), and releases a consumer blocked in "receive()" promptly so
"DeliveryIterator.aclose()" is never gated on the next broadcast.

This module imports neither graphene nor Django at module scope. "channels" is
imported lazily/guarded so the base package never hard-requires it.
"""

from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from .mixins import split_filters

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Sequence

__all__ = ["ChannelLayerSource"]


class ChannelLayerSource:
    """Async-iterator group consumer over a Channels channel layer.

    The consumer joins EXACTLY the caller-selected groups
    ("('create','update','delete')" for "all_actions" else "(action,)" — never
    hardcoding all three, the #1420 guard), receives from the Channels channel
    layer ("InMemoryChannelLayer" in tests, Redis in production), and applies the
    optional notification filters PRE-execute via "split_filters". Plain-equality
    keys present in the flat "data" are compared in memory; a mismatch DROPS the
    event (yields nothing).

    The receive loop yields "payload['data']" — the already-serialized flat snake
    dict — verbatim. It performs NO re-serialization and NO model instantiation
    (the serialize-once invariant). "__lookup" filters returned by "split_filters"
    as a NON-EMPTY "remaining" mapping require a single-row DB verification; that
    DB-backed narrowing is owned by the driver layer (WU5) which wires the
    "db_verify" hook to run an ".exists()" check. Until a hook is wired the source
    DROPS such events CONSERVATIVELY (never yields unverified — see the SECURITY
    note on the receive loop). The equality-only common case never issues a query.

    Attributes:
        db_verify: Optional async DB-verify hook "async (remaining, event) ->
            bool" the driver (WU5) wires to verify a NON-EMPTY "__lookup"
            "remaining" filter mapping against the database (a single-row
            ".exists()" narrowing). When "None" (the default), a non-empty
            remaining mapping DROPS the event conservatively — the source NEVER
            silently yields an unverified "__lookup"-filtered event.
    """

    __slots__ = (
        "_groups",
        "_channel_layer",
        "filters",
        "db_verify",
        "_channel",
        "_joined",
        "_closed",
        "_started",
        "_receive_task",
    )

    def __init__(
        self,
        groups: "Sequence[str]",
        channel_layer: Any,
        filters: dict[str, Any] | None = None,
        db_verify: "Callable[[dict[str, Any], dict[str, Any]], Any] | None" = None,
    ) -> None:
        """Store the join set, the channel layer, and the pre-execute filters.

        Args:
            groups: The EXACT Channels group names this source must join. The
                caller derives them from the requested action
                ("('create','update','delete')" for "all_actions" else
                "(action,)") — this class never hardcodes all three (the #1420
                guard).
            channel_layer: The Channels channel layer ("InMemoryChannelLayer" in
                tests, Redis in production) the source receives from.
            filters: Optional notification filters (Django ORM lookup -> expected
                value) applied PRE-execute via "split_filters". Defaults to an
                empty mapping (yield every event).
            db_verify: Optional async DB-verify hook for a NON-EMPTY "remaining"
                "__lookup" filter mapping. When "None", the receive loop DROPS
                such events conservatively (no silent leak).
        """
        # Copy so a caller mutating its list cannot change our join/discard set.
        self._groups: list[str] = list(groups)
        self._channel_layer = channel_layer
        self.filters: dict[str, Any] = dict(filters) if filters else {}
        # Optional async DB-verify hook for NON-EMPTY "remaining" __lookup
        # filters (WU5 wires the single-row .exists() narrowing). None => the
        # receive loop drops such events conservatively (no silent leak).
        self.db_verify = db_verify
        self._channel: str | None = None
        self._joined: list[str] = []
        self._closed = False
        self._started = False
        # The in-flight receive() task, tracked so aclose() can cancel it and
        # release a consumer parked in receive() PROMPTLY (the WU2 handoff:
        # DeliveryIterator.aclose() must not be gated on the next broadcast).
        self._receive_task: "asyncio.Future[Any] | None" = None

    # -- public read-only state --------------------------------------------
    @property
    def channel(self) -> str | None:
        """Return the per-consumer channel name allocated at "start".

        Returns:
            The channel name, or "None" before "start" (or after "aclose").
        """
        return self._channel

    @property
    def joined_groups(self) -> list[str]:
        """Return the groups actually joined so far.

        Returns:
            A copy of the joined-group list — callers cannot mutate state.
        """
        return list(self._joined)

    @property
    def is_closed(self) -> bool:
        """Return whether the source has been closed (groups discarded).

        Returns:
            "True" once "aclose" (or "__aexit__") has run, else "False".
        """
        return self._closed

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> "ChannelLayerSource":
        """Allocate a channel and "group_add" to EXACTLY the selected groups.

        Idempotent: a second call is a no-op. Joining only "self._groups"
        enforces the #1420 guard — a single-action source never touches the
        other two groups.

        Returns:
            "self" so "await source.start()" can be chained.
        """
        if self._started:
            return self
        self._channel = await self._channel_layer.new_channel()
        for group in self._groups:
            await self._channel_layer.group_add(group, self._channel)
            self._joined.append(group)
        self._started = True
        return self

    async def aclose(self) -> None:
        """Out-of-band close: "group_discard" every joined group, release receive.

        Idempotent. First the close flag is set and any in-flight "receive()"
        task is cancelled so a consumer parked in "receive()" is released
        PROMPTLY (it raises "StopAsyncIteration" rather than waiting for the
        next broadcast — the WU2 handoff requirement).

        The "group_discard" sweep is EXCEPTION-ISOLATED: EVERY joined group is
        attempted even if one discard raises (a "RedisChannelLayer" raises on
        transient errors; the "InMemoryChannelLayer" test backend never does).
        A non-isolated sweep would abort on the first raise and leak the failing
        group AND every group after it — IRRECOVERABLE because "is_closed" is
        already set, so a retry early-returns. Here each discard runs in its own
        "try" and errors are COLLECTED; state is finalized only AFTER the full
        sweep, and the first collected error is re-raised (or an
        "ExceptionGroup" for multiple) so the failure still surfaces. After
        "aclose()" returns — success or partial — no joined group remains
        un-attempted.

        Raises:
            asyncio.CancelledError: When a "group_discard" cancels THIS aclose
                task; re-raised immediately to preserve cooperative cancellation.
            BaseException: The first collected discard failure, re-raised after
                the full sweep completes.
            BaseExceptionGroup: When more than one group discard failed, grouping
                every collected error so none is lost.
        """
        if self._closed:
            return
        self._closed = True

        # Cancel a parked receive() so __anext__ unblocks immediately. The
        # __anext__ loop catches the CancelledError and raises StopAsyncIteration.
        receive_task = self._receive_task
        self._receive_task = None
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()

        channel = self._channel
        joined = self._joined
        # Best-effort: drop the channel so any parked receive cannot leak. Done
        # BEFORE the sweep so a raising discard cannot strand the channel ref.
        self._channel = None
        if channel is None:
            self._joined = []
            return

        # Attempt EVERY discard even if some raise — collect failures, continue.
        # The failing group AND every group after it must NOT leak (the ghost-
        # subscriber leak the docstring promises against under Redis).
        errors: list[BaseException] = []
        for group in joined:
            try:
                await self._channel_layer.group_discard(group, channel)
            except BaseException as exc:  # noqa: BLE001 - re-raised after sweep
                # Re-raise CancelledError immediately: swallowing a cancellation
                # of THIS aclose task would break cooperative cancellation.
                if isinstance(exc, asyncio.CancelledError):
                    self._joined = []
                    raise
                errors.append(exc)

        # Finalize state only AFTER the full sweep so a retry early-returns with
        # nothing left to discard (idempotent + recoverable).
        self._joined = []

        if errors:
            # Surface the failure AFTER the full sweep. Re-raise the single error
            # as-is; group multiple discard errors so none is lost (BaseException-
            # Group is a builtin on the project's Python floor, 3.12).
            if len(errors) == 1:
                raise errors[0]
            raise BaseExceptionGroup(
                "group_discard sweep raised for one or more groups", errors
            )

    # -- async context manager --------------------------------------------
    async def __aenter__(self) -> "ChannelLayerSource":
        """Enter the context: start (join groups) and return self."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        """Exit the context: discard every joined group (even on exception).

        Returns "False" so any exception raised inside the context body
        propagates after cleanup — the discard sweep always runs.
        """
        await self.aclose()
        return False

    # -- async iteration ---------------------------------------------------
    def __aiter__(self) -> "ChannelLayerSource":
        """Return self — this object is its own async iterator."""
        return self

    async def __anext__(self) -> dict[str, Any]:
        """Receive the next matching event and yield its flat "data" dict.

        Loops over "channel_layer.receive(channel)": a non-matching event
        ("split_filters" returns "None" for an in-memory equality mismatch)
        is DROPPED and the loop continues — a filtered event yields NOTHING and
        triggers ZERO downstream "execute()". A NON-EMPTY remaining mapping
        (unverified "__lookup" filters) is verified via "db_verify" when
        wired (drop on False) and DROPPED CONSERVATIVELY when no hook is wired —
        the source never yields an unverified "__lookup"-filtered event. A
        matching event yields the already-serialized flat "data" dict verbatim
        (no re-serialization).

        Raises:
            StopAsyncIteration: when the source has been closed out-of-band
                (including an aclose()-initiated cancel of a parked receive).
            asyncio.CancelledError: when the task running this loop is cancelled
                EXTERNALLY (not via aclose()) — re-raised for cooperative
                cancellation.
        """
        # Out-of-band close set between values -> stop on the next pull.
        if self._closed or self._channel is None:
            raise StopAsyncIteration

        while True:
            # Track the in-flight receive() so aclose() can cancel it and
            # release this coroutine promptly when blocked waiting for an event.
            receive_task = asyncio.ensure_future(
                self._channel_layer.receive(self._channel)
            )
            self._receive_task = receive_task
            try:
                message = await receive_task
            except asyncio.CancelledError:
                # Distinguish WHO cancelled the parked receive:
                #   * aclose() initiated the close (self._closed is True) -> the
                #     consumer was blocked waiting for a broadcast and the source
                #     is shutting down -> stop CLEANLY (StopAsyncIteration).
                #   * the task running this loop was cancelled EXTERNALLY (e.g.
                #     SSE/WS teardown cancelling the request task) -> the source
                #     is NOT closed -> RE-RAISE so cooperative cancellation
                #     propagates (the caller's finally: aclose() then runs).
                # Swallowing an external cancel would break teardown and leak
                # groups when the caller relies on the cancellation propagating.
                if self._closed:
                    raise StopAsyncIteration from None
                raise
            finally:
                if self._receive_task is receive_task:
                    self._receive_task = None

            # A close may have fired while we were parked in receive(); do not
            # deliver a trailing value and release the blocked consumer.
            if self._closed or self._channel is None:
                raise StopAsyncIteration

            payload = (message or {}).get("payload") or {}
            data = payload.get("data")

            # Pre-execute filtering: an in-memory equality mismatch drops the
            # event entirely (yields nothing, zero downstream execute). A non-
            # empty "remaining" mapping carries "__lookup" filters that need a
            # single-row DB verification; the in-memory equality gate (the common
            # case, empty remaining) never touches the ORM here.
            if self.filters:
                remaining = split_filters(data, self.filters)
                if remaining is None:
                    # Dropped in memory — keep waiting for the next event.
                    continue
                if remaining:
                    # SECURITY: a NON-EMPTY remaining mapping means unverified
                    # "__lookup" filters (e.g. owner__tenant_id__exact=7) that the
                    # in-memory equality gate CANNOT verify. NEVER yield such an
                    # event unverified — that is a cross-tenant data leak. If the
                    # driver (WU5) wired a db_verify hook, await it and DROP on
                    # False; if NO hook is wired, DROP CONSERVATIVELY (the safe
                    # default until WU5 wires the single-row .exists() narrowing).
                    if self.db_verify is None:
                        continue
                    verified = self.db_verify(remaining, data)
                    if isawaitable(verified):
                        verified = await verified
                    if not verified:
                        continue

            return data
