# -*- coding: utf-8 -*-
"""WU4 — ChannelLayerSource: the native engine's group consumer.

Design paragraph 3 (serialize-once data path) + paragraph 1 (engine
layering). "ChannelLayerSource" is a GROUP consumer (NOT a WebsocketConsumer)
that:

  - joins EXACTLY the action-selected groups ("('create','update','delete')" for
    all-actions, else "(action,)" — the #1420 single-action guard: a single-action
    source must NOT join the other two groups),
  - runs an async receive loop over "channel_layer.receive(channel)",
  - applies "split_filters" PRE-execute (in-memory equality drop) so a filtered
    event yields NOTHING (zero downstream execute),
  - yields the already-serialized flat "data" dict ("payload['data']") for a
    matching event (NO re-serialize, NO model instantiation — the serialize-once
    invariant: producer-side "serialize_instance" runs once, the consumer never
    re-serializes),
  - on "aclose()" / "__aexit__" "group_discard"s EVERY joined group (no ghost
    subscribers) and releases a consumer blocked in "receive()" promptly so the
    WU2 "DeliveryIterator.aclose()" is not gated on the next broadcast.

These tests are the WU4 gate and use "InMemoryChannelLayer" (channels 4.3.2).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from pytest_django.fixtures import DjangoAssertNumQueries  # noqa: E402

from django_graphex.subscriptions.source import ChannelLayerSource  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _notify_message(
    group: str, data: dict[str, Any], *, action: str = "create", pk: int = 1
) -> dict[str, Any]:
    """Build a producer-shaped "subscription.notify" envelope (bindings.py).

    Args:
        group: The channel-layer group name the message targets.
        data: The serialized payload data to embed in the message.
        action: The CRUD action name to embed in the payload.
        pk: The primary key to embed in the envelope.

    Returns:
        message: The assembled notify message dict.
    """
    return {
        "type": "subscription.notify",
        "stream": "demo",
        "group": group,
        "pk": pk,
        "payload": {"action": action, "model": "app.Demo", "data": data},
    }


async def _receive_one(source: ChannelLayerSource, *, timeout: float = 1.0) -> Any:
    """Pull the next yielded value from "source" with a wall-clock timeout.

    Args:
        source: The source to pull the next value from.
        timeout: The maximum time in seconds to wait for a value.

    Returns:
        value: The next value yielded by the source.
    """
    return await asyncio.wait_for(source.__anext__(), timeout=timeout)


# ---------------------------------------------------------------------------
# Exact group join — incl. the #1420 single-action guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_actions_joins_exactly_three_groups() -> None:
    """ "all_actions" must join exactly the create/update/delete groups.

    Contract: this test ships broken if an all-actions source joins a
    different group set than exactly create/update/delete.
    """
    layer = InMemoryChannelLayer()
    groups = ["demo-create", "demo-update", "demo-delete"]
    source = ChannelLayerSource(groups=groups, channel_layer=layer)

    await source.start()
    try:
        assert set(source.joined_groups) == set(groups)
        assert len(source.joined_groups) == 3
        # Every joined group actually maps to this source's channel in the layer.
        for group in groups:
            assert source.channel in layer.groups.get(group, {})
    finally:
        await source.aclose()


@pytest.mark.asyncio
async def test_single_action_joins_exactly_one_group_1420_guard() -> None:
    """#1420 guard: a single-action source must join only its group, not the others.

    Contract: this test ships broken if a single-action source rejoins the
    other two action groups (the #1420 regression).

    The bug was hardcoding "('create','update','delete')" regardless of the
    requested action, so a create-only subscriber also received update/delete
    events. The join set must mirror the caller-selected action.
    """
    layer = InMemoryChannelLayer()
    source = ChannelLayerSource(groups=["demo-create"], channel_layer=layer)

    await source.start()
    try:
        assert source.joined_groups == ["demo-create"]
        assert len(source.joined_groups) == 1
        # The OTHER two groups must NOT be joined by this source.
        assert source.channel not in layer.groups.get("demo-update", {})
        assert source.channel not in layer.groups.get("demo-delete", {})
    finally:
        await source.aclose()


@pytest.mark.asyncio
async def test_context_manager_start_joins_groups() -> None:
    """ "async with" must enter/start and join the selected groups.

    Contract: this test ships broken if entering the context manager fails
    to start the source and join its configured groups.
    """
    layer = InMemoryChannelLayer()
    async with ChannelLayerSource(
        groups=["demo-create"], channel_layer=layer
    ) as source:
        assert source.joined_groups == ["demo-create"]
        assert source.channel is not None


# ---------------------------------------------------------------------------
# Receive + yield the flat already-serialized dict (serialize-once)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_to_joined_group_yields_flat_data_dict() -> None:
    """A broadcast to a joined group must yield the flat payload['data'] dict.

    Contract: this test ships broken if the yielded value is re-serialized
    or otherwise differs from the exact flat dict the producer sent.
    """
    layer = InMemoryChannelLayer()
    flat = {"id": 1, "is_active": True, "date_joined": "2026-06-14"}
    async with ChannelLayerSource(
        groups=["demo-create"], channel_layer=layer
    ) as source:
        await layer.group_send("demo-create", _notify_message("demo-create", flat))
        out = await _receive_one(source)
        # The exact already-serialized snake dict is yielded verbatim — no
        # re-serialization, no model instantiation on the consumer side.
        assert out == flat
        assert out is not None


@pytest.mark.asyncio
async def test_serialize_instance_not_called_on_consumer_yield_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consumer must never call serialize_instance — the serialize-once invariant.

    Contract: this test ships broken if the consumer re-serializes an
    instance instead of yielding the already-flat producer-serialized dict.

    The producer (binding) serializes ONCE before group_send. The source yields
    the already-flat dict, so serialize_instance must not run again on the
    consumer side regardless of how many subscribers consume the same event.

    Args:
        monkeypatch: The pytest fixture used to wrap serialize_instance with
            a call-counting spy.
    """
    from django_graphex.subscriptions import mixins

    calls = {"n": 0}
    real = mixins.serialize_instance

    def _counting(
        *args: Any, **kwargs: Any
    ) -> Any:  # pragma: no cover - must never fire here
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(mixins, "serialize_instance", _counting)

    layer = InMemoryChannelLayer()
    flat = {"id": 7, "is_active": False}
    async with ChannelLayerSource(
        groups=["demo-create"], channel_layer=layer
    ) as source:
        await layer.group_send("demo-create", _notify_message("demo-create", flat))
        out = await _receive_one(source)

    assert out == flat
    assert calls["n"] == 0


@pytest.mark.django_db
def test_assertNumQueries_zero_on_consumer_yield_path(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Yielding a flat dict for an in-memory-equality match must hit zero DB queries.

    Contract: this test ships broken if an in-memory-resolvable equality
    filter falls through to a DB query instead of resolving purely in memory.

    SYNC test driving the async receive via asyncio.run inside the assertion
    block (django_assert_num_queries calls ensure_connection() synchronously,
    which raises SynchronousOnlyOperation under asyncio_mode="auto").

    Args:
        django_assert_num_queries: The pytest-django fixture used as a
            context manager asserting an exact DB query count.
    """
    layer = InMemoryChannelLayer()
    flat = {"id": 1, "owner_id": 5}

    async def _drive() -> dict[str, Any]:
        source = ChannelLayerSource(groups=["demo-create"], channel_layer=layer)
        await source.start()
        try:
            # Equality filter resolvable fully in memory (no "__" lookup).
            source.filters = {"owner_id": 5}
            await layer.group_send("demo-create", _notify_message("demo-create", flat))
            return await asyncio.wait_for(source.__anext__(), timeout=1.0)
        finally:
            await source.aclose()

    with django_assert_num_queries(0):
        out = asyncio.run(_drive())

    assert out == flat


# ---------------------------------------------------------------------------
# Pre-execute filter DROP — non-matching event yields NOTHING
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_matching_filter_event_dropped_pre_execute() -> None:
    """An in-memory equality mismatch must drop the event before any execute.

    Contract: this test ships broken if a non-matching event is still
    yielded instead of being dropped pre-execute.

    Sending a non-matching event then a matching one must yield ONLY the matching
    payload — the rejected event produces zero downstream values.
    """
    layer = InMemoryChannelLayer()
    async with ChannelLayerSource(
        groups=["demo-create"], channel_layer=layer
    ) as source:
        source.filters = {"owner_id": 5}
        # Non-matching: owner_id 99 != 5 -> split_filters returns None -> dropped.
        await layer.group_send(
            "demo-create",
            _notify_message("demo-create", {"id": 1, "owner_id": 99}),
        )
        # Matching: owner_id 5 == 5 -> yielded.
        match = {"id": 2, "owner_id": 5}
        await layer.group_send("demo-create", _notify_message("demo-create", match))

        out = await _receive_one(source)
        assert out == match


@pytest.mark.asyncio
async def test_no_filters_yields_every_event() -> None:
    """With no filters configured, every joined-group event must be yielded as-is.

    Contract: this test ships broken if an event is dropped or reordered
    when no filter is configured on the source.
    """
    layer = InMemoryChannelLayer()
    async with ChannelLayerSource(
        groups=["demo-create"], channel_layer=layer
    ) as source:
        first = {"id": 1, "owner_id": 1}
        second = {"id": 2, "owner_id": 2}
        await layer.group_send("demo-create", _notify_message("demo-create", first))
        await layer.group_send("demo-create", _notify_message("demo-create", second))
        assert await _receive_one(source) == first
        assert await _receive_one(source) == second


# ---------------------------------------------------------------------------
# group_discard lifecycle — no ghost subscribers; blocked receive released
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_group_discards_every_joined_group() -> None:
    """aclose() must group_discard every joined group, leaving no ghost subscriber.

    Contract: this test ships broken if any joined group is left un-discarded
    after aclose().
    """
    layer = InMemoryChannelLayer()
    groups = ["demo-create", "demo-update", "demo-delete"]
    source = ChannelLayerSource(groups=groups, channel_layer=layer)
    await source.start()
    channel = source.channel

    # Confirm joined first.
    for group in groups:
        assert channel in layer.groups.get(group, {})

    await source.aclose()

    # Every joined group must be discarded.
    for group in groups:
        assert channel not in layer.groups.get(group, {})


@pytest.mark.asyncio
async def test_aexit_group_discards_every_joined_group() -> None:
    """__aexit__ must discard every joined group on context exit.

    Contract: this test ships broken if exiting the "async with" block
    leaves any joined group un-discarded.
    """
    layer = InMemoryChannelLayer()
    groups = ["demo-create", "demo-update"]
    async with ChannelLayerSource(groups=groups, channel_layer=layer) as source:
        channel = source.channel
        for group in groups:
            assert channel in layer.groups.get(group, {})

    for group in groups:
        assert channel not in layer.groups.get(group, {})


@pytest.mark.asyncio
async def test_aclose_releases_blocked_receive_promptly() -> None:
    """aclose() on a source blocked in receive() must return promptly.

    Contract: this test ships broken if aclose() relies on a downstream
    timeout to release a blocked receive instead of cancelling it directly,
    which would gate WU2's DeliveryIterator.aclose() on the next broadcast.

    A background __anext__ parks in receive() (no event ever arrives).
    aclose() must release it (raise StopAsyncIteration) ON ITS OWN. The
    promptness assertion (sub-500ms vs the 5s ceiling) proves the release is
    driven by aclose() cancelling the parked receive, NOT by the ceiling.
    """
    import time

    layer = InMemoryChannelLayer()
    source = ChannelLayerSource(groups=["demo-create"], channel_layer=layer)
    await source.start()

    pull = asyncio.ensure_future(source.__anext__())
    # Let the pull park inside receive().
    await asyncio.sleep(0.05)
    assert not pull.done()

    started = time.perf_counter()
    await source.aclose()
    with pytest.raises(StopAsyncIteration):
        # A generous ceiling that aclose() must beat by orders of magnitude; if
        # release depended on this timeout the elapsed assert below would fail.
        await asyncio.wait_for(pull, timeout=5.0)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, (
        "blocked receive was NOT released promptly by aclose() "
        f"(took {elapsed * 1000:.1f}ms — release likely came from the timeout)"
    )


@pytest.mark.asyncio
async def test_aclose_idempotent() -> None:
    """Calling aclose() twice must be safe and must discard groups only once.

    Contract: this test ships broken if a redundant second aclose() call
    raises or re-attempts the discard sweep.
    """
    layer = InMemoryChannelLayer()
    source = ChannelLayerSource(groups=["demo-create"], channel_layer=layer)
    await source.start()
    channel = source.channel

    await source.aclose()
    await source.aclose()  # must not raise

    assert channel not in layer.groups.get("demo-create", {})


@pytest.mark.asyncio
async def test_group_discard_runs_even_on_abnormal_teardown() -> None:  # noqa: DOC005
    """An exception during teardown must still discard every joined group.

    Contract: this test ships broken if an exception propagating through
    the context body leaks a joined group instead of the try/finally
    teardown discarding it regardless.

    Simulates an abnormal __aexit__ (exception propagating through the
    context body); the group_discard cleanup must still run for every joined
    group so no ghost subscriber leaks.
    """
    layer = InMemoryChannelLayer()
    groups = ["demo-create", "demo-update"]
    source = ChannelLayerSource(groups=groups, channel_layer=layer)

    with pytest.raises(ValueError):
        async with source:
            channel = source.channel
            for group in groups:
                assert channel in layer.groups.get(group, {})
            raise ValueError("boom inside the context body")

    # Despite the exception, every joined group was discarded.
    for group in groups:
        assert channel not in layer.groups.get(group, {})


# ---------------------------------------------------------------------------
# HIGH — group_discard sweep is exception-isolated (no ghost-subscriber leak)
#
# RedisChannelLayer raises on transient errors mid-sweep; InMemoryChannelLayer
# never does, so these defects stay invisible under the in-memory test backend.
# A fake layer whose group_discard raises on ONE group reproduces the Redis
# failure mode: a non-isolated sweep aborts on the first raise and leaks every
# group after it (IRRECOVERABLE because is_closed is already set).
# ---------------------------------------------------------------------------


class _FakeChannelLayer:
    """A minimal channel layer whose ``group_discard`` raises on chosen groups.

    Reproduces the production ``RedisChannelLayer`` failure mode that the
    ``InMemoryChannelLayer`` test backend masks: a transient error raised by one
    ``group_discard`` mid-sweep. Tracks membership so the test can assert which
    groups were actually discarded (none must leak past the failing one).
    """

    def __init__(self, *, raise_on: set[str]) -> None:
        """Store the set of groups whose discard should raise.

        Args:
            raise_on: The group names whose group_discard call raises
                RuntimeError instead of succeeding.
        """
        self._raise_on = set(raise_on)
        self.groups: dict[str, set[str]] = {}
        self.discard_attempts: list[str] = []
        self._counter = 0

    async def new_channel(self) -> str:
        """Allocate and return a new, uniquely numbered fake channel name.

        Returns:
            channel: A name of the form "fake.channel!N" for incrementing N.
        """
        self._counter += 1
        return f"fake.channel!{self._counter}"

    async def group_add(self, group: str, channel: str) -> None:
        """Record a (group, channel) join.

        Args:
            group: The group name being joined.
            channel: The channel name joining the group.
        """
        self.groups.setdefault(group, set()).add(channel)

    async def group_discard(self, group: str, channel: str) -> None:
        """Record the discard attempt, then either raise or actually discard.

        Args:
            group: The group name being left.
            channel: The channel name leaving the group.

        Raises:
            RuntimeError: When "group" is one of the configured raise_on
                groups, simulating a transient Redis failure.
        """
        # Record EVERY attempt so the test proves the sweep never aborts early.
        self.discard_attempts.append(group)
        if group in self._raise_on:
            raise RuntimeError(f"transient redis failure discarding {group!r}")
        self.groups.get(group, set()).discard(channel)

    async def receive(self, channel: str) -> Any:  # pragma: no cover - not exercised
        """Block forever, simulating a receive that never resolves.

        Args:
            channel: The channel name to receive on; unused.
        """
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_aclose_discard_sweep_is_exception_isolated() -> None:
    """A raising group_discard must not abort the sweep, avoiding a ghost leak.

    Contract: this test ships broken if the sweep aborts on the first
    group_discard failure instead of attempting every joined group.

    The docstring promises "every joined group is removed even if one discard
    raises". A non-isolated try/finally (guarding only "self._channel = None")
    aborts on the first raise and leaks the failing group AND every group after
    it. This test sends the raising group in the MIDDLE so a non-isolated sweep
    leaks the trailing group; an isolated sweep attempts all three and surfaces
    the error AFTER the full sweep.
    """
    groups = ["g-create", "g-update", "g-delete"]
    layer = _FakeChannelLayer(raise_on={"g-update"})
    source = ChannelLayerSource(groups=groups, channel_layer=layer)
    await source.start()
    channel = source.channel
    for group in groups:
        assert channel in layer.groups.get(group, set())

    # The error surfaces (is raised) AFTER the full sweep — not swallowed.
    with pytest.raises(RuntimeError, match="transient redis failure"):
        await source.aclose()

    # EVERY group was attempted — the sweep did not abort on the first raise.
    assert layer.discard_attempts == groups, (
        "discard sweep aborted early — groups after the failing one leaked: "
        f"attempted {layer.discard_attempts}, expected {groups}"
    )

    # The two non-raising groups (one BEFORE and one AFTER the failure) were
    # actually discarded — no ghost subscriber leaks past the failing group.
    assert channel not in layer.groups.get("g-create", set())
    assert channel not in layer.groups.get("g-delete", set())

    # Idempotent + recoverable: a retry must not re-raise and must leave no
    # joined group un-attempted (state finalized AFTER the full sweep).
    await source.aclose()
    assert source.joined_groups == []
    assert source.is_closed is True


# ---------------------------------------------------------------------------
# MEDIUM — __anext__ must NOT swallow EXTERNAL CancelledError
#
# aclose()-initiated cancellation -> StopAsyncIteration (clean stop).
# EXTERNAL cancellation (task running the loop cancelled) -> must PROPAGATE so
# cooperative cancellation works (SSE/WS teardown that cancels the task).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_cancellation_propagates() -> None:
    """Cancelling the consuming task (not via aclose) must propagate CancelledError.

    Contract: this test ships broken if an externally cancelled receive is
    silently converted to StopAsyncIteration, breaking cooperative
    cancellation for callers like SSE/WS teardown.

    A consumer parked in receive() whose task is cancelled externally (e.g.
    SSE/WS teardown cancelling the request task) must see CancelledError
    propagate — NOT be silently converted to StopAsyncIteration.
    """
    layer = InMemoryChannelLayer()
    source = ChannelLayerSource(groups=["demo-create"], channel_layer=layer)
    await source.start()

    pull = asyncio.ensure_future(source.__anext__())
    # Let the pull park inside receive().
    await asyncio.sleep(0.05)
    assert not pull.done()

    # External cancellation: cancel the task WITHOUT calling aclose().
    pull.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pull

    # The source was never closed by this external cancel.
    assert source.is_closed is False

    # Cleanup (no ghost subscribers).
    await source.aclose()


@pytest.mark.asyncio
async def test_aclose_initiated_cancel_still_stops_cleanly() -> None:
    """Regression: an aclose()-initiated cancel must still yield StopAsyncIteration.

    Contract: this test ships broken if the external-cancel propagation fix
    regresses the aclose() path into raising CancelledError instead of
    stopping cleanly.

    The external-cancel fix must NOT regress the aclose() path: when aclose()
    cancels the parked receive, the consumer must stop CLEANLY.
    """
    layer = InMemoryChannelLayer()
    source = ChannelLayerSource(groups=["demo-create"], channel_layer=layer)
    await source.start()

    pull = asyncio.ensure_future(source.__anext__())
    await asyncio.sleep(0.05)
    assert not pull.done()

    await source.aclose()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pull, timeout=5.0)


# ---------------------------------------------------------------------------
# MEDIUM/SECURITY — __lookup filters must NOT pass through UNVERIFIED
#
# split_filters returns a NON-EMPTY "remaining" mapping for __lookup filters
# (e.g. owner__tenant_id__exact=7) that need a single-row DB verification (WU5).
# Until WU5 wires the verifier, the source MUST drop conservatively — never
# silently yield an unverified __lookup-filtered event (cross-tenant leak).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_filter_without_verifier_drops_conservatively() -> None:
    """A remaining "__lookup" filter with no db_verify hook must drop the event.

    Contract: this test ships broken if an unverified lookup-filtered event
    is yielded instead of conservatively dropped (a cross-tenant data leak).

    split_filters returns a non-empty remaining mapping for a __lookup
    filter. The in-memory equality gate cannot verify it, and no DB-verify hook
    is wired, so the source must DROP CONSERVATIVELY — never yield unverified.
    A trailing fully-matched event proves the drop is per-event (not a
    permanent stop).
    """
    layer = InMemoryChannelLayer()
    async with ChannelLayerSource(
        groups=["demo-create"], channel_layer=layer
    ) as source:
        # A __lookup filter -> split_filters returns {"owner__tenant_id": 7}
        # (non-empty remaining). No db_verify hook set.
        source.filters = {"owner__tenant_id": 7}
        assert source.db_verify is None

        # This event matches on equality (no equality keys to fail) but carries
        # an UNVERIFIED __lookup filter -> must be DROPPED, not yielded.
        await layer.group_send(
            "demo-create",
            _notify_message("demo-create", {"id": 1, "owner_tenant_id": 7}),
        )

        # Send a second event that has NO filters remaining (clear the filter on
        # the source) so the loop yields something and we can prove the FIRST
        # event was dropped (its id never appears).
        async def _drain_then_clear():
            # Give the first (dropped) event a beat, then send a yieldable one.
            await asyncio.sleep(0.05)
            source.filters = {}
            await layer.group_send(
                "demo-create",
                _notify_message("demo-create", {"id": 2, "owner_tenant_id": 7}),
            )

        drainer = asyncio.ensure_future(_drain_then_clear())
        out = await _receive_one(source)
        await drainer
        # The unverified __lookup event (id 1) was DROPPED; only id 2 yielded.
        assert out == {"id": 2, "owner_tenant_id": 7}


@pytest.mark.asyncio
async def test_lookup_filter_with_verifier_true_yields_false_drops() -> None:
    """A remaining "__lookup" filter must be verified via the db_verify hook.

    Contract: this test ships broken if the source yields on a False verify
    result or drops on a True one.

    With a db_verify hook set, a remaining __lookup filter is verified by
    awaiting db_verify(remaining, event): yield on True, drop on False. This
    is the WU5 contract — the driver wires the single-row .exists() narrowing
    into the hook.
    """
    layer = InMemoryChannelLayer()

    seen: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def _verify(remaining: dict[str, Any], event: dict[str, Any]) -> bool:
        seen.append((dict(remaining), dict(event)))
        # Verify by tenant id carried in the event (stand-in for .exists()).
        return event.get("owner_tenant_id") == remaining.get("owner__tenant_id")

    async with ChannelLayerSource(
        groups=["demo-create"], channel_layer=layer
    ) as source:
        source.filters = {"owner__tenant_id": 7}
        source.db_verify = _verify

        # FALSE: tenant 99 != 7 -> verifier returns False -> dropped.
        await layer.group_send(
            "demo-create",
            _notify_message("demo-create", {"id": 1, "owner_tenant_id": 99}),
        )
        # TRUE: tenant 7 == 7 -> verifier returns True -> yielded.
        match = {"id": 2, "owner_tenant_id": 7}
        await layer.group_send("demo-create", _notify_message("demo-create", match))

        out = await _receive_one(source)
        assert out == match

    # The verifier was invoked with the remaining __lookup mapping + the event.
    assert seen, "db_verify hook was never awaited"
    assert seen[0][0] == {"owner__tenant_id": 7}


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_source_module_has_no_graphene_import() -> None:
    """The source module must never import graphene (no-graphene-import gate).

    Contract: this test ships broken if source.py gains a graphene import,
    reintroducing a dependency the native engine was built to avoid.
    """
    import pathlib

    from django_graphex.subscriptions import source as source_mod

    text = pathlib.Path(source_mod.__file__).read_text(encoding="utf-8")
    assert "import graphene" not in text
    assert "from graphene" not in text


def test_source_module_is_async_iterator() -> None:
    """ "ChannelLayerSource" must be async-iterator compatible ("__aiter__" -> self).

    Contract: this test ships broken if ChannelLayerSource stops being
    directly usable in an "async for" loop.
    """
    layer = InMemoryChannelLayer()
    source = ChannelLayerSource(groups=["demo-create"], channel_layer=layer)
    assert source.__aiter__() is source
    assert hasattr(source, "__anext__")
    assert hasattr(source, "aclose")
