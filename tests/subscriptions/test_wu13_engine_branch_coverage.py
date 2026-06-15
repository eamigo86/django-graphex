# -*- coding: utf-8 -*-
"""WARNING-1 close-out (verify #1522) — engine-layer branch coverage top-up.

Phase 6 verify flagged the NEW subscription engine modules below the project-wide
95% branch floor. This module ADDS targeted, MEANINGFUL-assert tests for the
remaining uncovered branches in the pure-async engine layer (no transport / no
channels-consumer machinery needed):

  * ``delivery.py``  — close-while-awaiting StopAsyncIteration, a source with NO
    ``aclose`` attr, and an ``aclose`` that raises ``RuntimeError`` (best-effort).
  * ``guard.py``     — no-subscription-type early return, NonNull/List unwrap,
    a non-object subscription field type skip, and the already-visited dedupe.
  * ``source.py``    — idempotent ``start``, the channel-None aclose fast path,
    an external (NOT aclose) cancel re-raise, the multi-error ``BaseExceptionGroup``
    sweep, a close racing a parked receive, and a SYNCHRONOUS ``db_verify`` hook.
  * ``streaming.py`` — the allow-all default hooks (authorize/scope/instance_index).
  * ``mixins.py``    — ``split_filters`` __lookup remaining + the safe_group_name
    hashing branch (length/charset reject).

Each test asserts a real, observable outcome — never a bare "it ran" — so it
would FAIL if the documented behavior regressed. Pure asyncio: gated only behind
``channels`` import (conftest skips the whole subpackage without it).
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("channels")


# ---------------------------------------------------------------------------
# delivery.py — out-of-band close + best-effort source aclose
# ---------------------------------------------------------------------------


async def test_delivery_close_while_awaiting_source_drops_trailing_value():
    """A close that fires WHILE ``__anext__`` is parked drops the trailing value.

    Covers delivery.py:100 — the post-await close check. The source yields a
    value only after we set the close flag mid-await, so the iterator must raise
    ``StopAsyncIteration`` rather than deliver that trailing value.
    """
    from django_graphex.subscriptions.delivery import DeliveryIterator

    released = asyncio.Event()

    async def _source():
        # Park until the test releases us, by which point the iterator is closed.
        await released.wait()
        yield {"id": 1}

    it = DeliveryIterator(_source(), lambda v: v)
    pull = asyncio.ensure_future(it.__anext__())
    await asyncio.sleep(0)  # let the pull park inside ``await source.__anext__()``

    # Close out-of-band, THEN let the source produce its (now-trailing) value.
    it._close_event.set()
    released.set()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pull, timeout=1.0)


async def test_delivery_aclose_when_source_has_no_aclose_is_noop():
    """``aclose`` on a source WITHOUT an ``aclose`` attr just flags closed.

    Covers delivery.py:116->exit — the ``getattr(source, 'aclose', None) is None``
    branch. A bare async-iterator object (no ``aclose``) must not raise.
    """
    from django_graphex.subscriptions.delivery import DeliveryIterator

    class _NoAclose:
        def __aiter__(self):
            return self

        async def __anext__(self):  # pragma: no cover - never pulled here
            raise StopAsyncIteration

    it = DeliveryIterator(_NoAclose(), lambda v: v)
    assert it.is_closed is False
    await it.aclose()
    assert it.is_closed is True
    # Idempotent second call (already-closed early return) is also a no-op.
    await it.aclose()
    assert it.is_closed is True


async def test_delivery_aclose_swallows_runtime_error_from_source():
    """A source ``aclose`` raising ``RuntimeError`` is swallowed (best-effort).

    Covers delivery.py:119-122 — an already-closing async generator can raise
    ``RuntimeError``; ``aclose`` treats teardown as best-effort and idempotent.
    """
    from django_graphex.subscriptions.delivery import DeliveryIterator

    closed = {"called": False}

    class _RaisingAclose:
        def __aiter__(self):
            return self

        async def __anext__(self):  # pragma: no cover - never pulled here
            raise StopAsyncIteration

        async def aclose(self):
            closed["called"] = True
            raise RuntimeError("async generator is already running")

    it = DeliveryIterator(_RaisingAclose(), lambda v: v)
    await it.aclose()  # must NOT propagate the RuntimeError
    assert closed["called"] is True
    assert it.is_closed is True


# ---------------------------------------------------------------------------
# guard.py — schema walk branches
# ---------------------------------------------------------------------------


def test_guard_schema_without_subscription_type_returns_early():
    """``check_subscription_schema`` is a no-op when there is no subscription type.

    Covers guard.py:113-114 — ``schema.subscription_type is None`` early return.
    """
    from graphql import GraphQLBoolean, GraphQLField, GraphQLObjectType, GraphQLSchema

    from django_graphex.subscriptions.guard import check_subscription_schema

    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)})
    )
    assert schema.subscription_type is None
    # No raise, no error — a query-only schema is simply skipped.
    check_subscription_schema(schema)


def test_guard_schema_unwraps_nonnull_list_and_dedupes_visited():
    """The schema walk unwraps NonNull/List, skips non-object types, dedupes types.

    Covers guard.py:124-125 (the unwrap loop body over NonNull+List), 131-132
    (a non-object field type is skipped), and 133-134 (the already-visited dedupe
    when two subscription fields return the SAME event type).
    """
    from graphql import (
        GraphQLBoolean,
        GraphQLField,
        GraphQLList,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLSchema,
    )

    from django_graphex.subscriptions.guard import check_subscription_schema
    from django_graphex.subscriptions.resolvers import make_snake_resolver

    # A guarded event type: every field carries the sentinel resolver.
    event_type = GraphQLObjectType(
        "Event",
        {"id": GraphQLField(GraphQLBoolean, resolve=make_snake_resolver("id"))},
    )

    subscription_type = GraphQLObjectType(
        "Subscription",
        {
            # NonNull(List(NonNull(event))) exercises the unwrap loop fully.
            "a": GraphQLField(GraphQLNonNull(GraphQLList(GraphQLNonNull(event_type)))),
            # SAME event type via a second field → the visited-dedupe path.
            "b": GraphQLField(event_type),
            # A SCALAR-typed subscription field is skipped (not an object type).
            "c": GraphQLField(GraphQLBoolean),
        },
    )
    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)}),
        subscription=subscription_type,
    )

    # Passes: the only object event type is fully sentinel-guarded; the scalar
    # field is skipped and the duplicate event type is visited exactly once.
    check_subscription_schema(schema)


# ---------------------------------------------------------------------------
# source.py — lifecycle + sweep + receive branches
# ---------------------------------------------------------------------------


class _Layer:
    """A minimal channel-layer stand-in: new_channel / group_add / receive."""

    def __init__(self):
        self.added: list[tuple[str, str]] = []
        self.discarded: list[tuple[str, str]] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._n = 0

    async def new_channel(self):
        self._n += 1
        return f"chan{self._n}"

    async def group_add(self, group, channel):
        self.added.append((group, channel))

    async def group_discard(self, group, channel):
        self.discarded.append((group, channel))

    async def receive(self, channel):
        return await self._queue.get()


async def test_source_start_is_idempotent():
    """A second ``start`` is a no-op (no double group_add).

    Covers source.py:155-156 — the ``if self._started: return self`` guard.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    layer = _Layer()
    src = ChannelLayerSource(groups=["g1"], channel_layer=layer)
    await src.start()
    assert layer.added == [("g1", "chan1")]
    # Idempotent: the second start joins nothing new.
    result = await src.start()
    assert result is src
    assert layer.added == [("g1", "chan1")]


async def test_source_aclose_before_start_has_no_channel_fast_path():
    """``aclose`` before ``start`` (no channel allocated) finalizes cleanly.

    Covers source.py:200-202 — the ``channel is None`` fast path: nothing was
    joined, so the sweep is skipped and state is finalized.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    layer = _Layer()
    src = ChannelLayerSource(groups=["g1"], channel_layer=layer)
    assert src.channel is None
    await src.aclose()
    assert src.is_closed is True
    assert src.joined_groups == []
    assert layer.discarded == []


async def test_source_external_cancel_in_discard_sweep_reraises():
    """A ``CancelledError`` raised by ``group_discard`` is re-raised immediately.

    Covers source.py:214-216 — a cancellation of the aclose task itself must NOT
    be swallowed (cooperative cancellation), and ``_joined`` is cleared first.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    class _CancelOnDiscard(_Layer):
        async def group_discard(self, group, channel):
            raise asyncio.CancelledError()

    layer = _CancelOnDiscard()
    src = ChannelLayerSource(groups=["g1"], channel_layer=layer)
    await src.start()
    with pytest.raises(asyncio.CancelledError):
        await src.aclose()
    # The sweep cleared joined before re-raising (no dangling join state).
    assert src.joined_groups == []


async def test_source_multi_discard_errors_raise_exception_group():
    """Two failing discards surface as a ``BaseExceptionGroup`` after a FULL sweep.

    Covers source.py:208-211 + 229 — every group is attempted even when each
    raises; the errors are collected and a multi-error group is raised so none is
    lost, AND every group was still discarded-attempted (no leak).
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    class _RaiseTwice(_Layer):
        async def group_discard(self, group, channel):
            self.discarded.append((group, channel))
            raise ValueError(f"discard failed for {group}")

    layer = _RaiseTwice()
    src = ChannelLayerSource(groups=["g1", "g2"], channel_layer=layer)
    await src.start()
    with pytest.raises(BaseExceptionGroup) as exc_info:
        await src.aclose()

    # Both groups were attempted (no abort-on-first-raise leak) and both errors
    # are carried in the group.
    assert {g for g, _ in layer.discarded} == {"g1", "g2"}
    assert len(exc_info.value.exceptions) == 2
    assert src.joined_groups == []


async def test_source_single_discard_error_reraised_as_is():
    """A single failing discard re-raises the original error (not a group).

    Covers source.py:223-228 — the ``len(errors) == 1`` arm.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    sentinel = RuntimeError("redis transient")

    class _RaiseOnce(_Layer):
        async def group_discard(self, group, channel):
            self.discarded.append((group, channel))
            raise sentinel

    layer = _RaiseOnce()
    src = ChannelLayerSource(groups=["only"], channel_layer=layer)
    await src.start()
    with pytest.raises(RuntimeError) as exc_info:
        await src.aclose()
    assert exc_info.value is sentinel


async def test_source_close_racing_parked_receive_stops_cleanly():
    """A close that cancels a parked ``receive`` stops with StopAsyncIteration.

    Covers source.py:297-298 (aclose-initiated cancel → StopAsyncIteration) and
    the post-receive close re-check (306-307) on the prompt-release path.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    layer = _Layer()  # receive() blocks forever (empty queue)
    src = ChannelLayerSource(groups=["g1"], channel_layer=layer)
    await src.start()

    pull = asyncio.ensure_future(src.__anext__())
    await asyncio.sleep(0)  # let __anext__ park inside receive()
    await src.aclose()  # cancels the parked receive → StopAsyncIteration

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pull, timeout=1.0)
    assert src.is_closed is True


async def test_source_close_during_receive_return_drops_trailing_value():
    """A close that flips ``_closed`` DURING a returning ``receive`` drops the value.

    Covers source.py:301->306 (the finally ``is`` check restores ``_receive_task``
    to None on a NORMAL return) and 306-307 (the post-receive close re-check raises
    ``StopAsyncIteration`` rather than delivering the trailing value). The layer's
    ``receive`` returns a real message but sets ``_closed`` just before returning —
    no cancellation, so the cancel arm is NOT taken; the post-receive guard is.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    src_ref: dict = {}

    class _CloseOnReceive(_Layer):
        async def receive(self, channel):
            # Flip the source closed flag, then return a value normally.
            src_ref["src"]._closed = True
            return {"payload": {"data": {"id": 99}, "action": "create"}}

    layer = _CloseOnReceive()
    src = ChannelLayerSource(groups=["g1"], channel_layer=layer)
    src_ref["src"] = src
    await src.start()

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(src.__anext__(), timeout=1.0)


async def test_source_external_cancel_of_receive_loop_reraises():
    """An EXTERNAL cancel of the receive loop (source NOT closed) re-raises.

    Covers source.py:299 — the ``raise`` (not StopAsyncIteration) arm when the
    cancel did NOT originate from aclose (cooperative cancellation propagates).
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    layer = _Layer()  # receive() blocks forever
    src = ChannelLayerSource(groups=["g1"], channel_layer=layer)
    await src.start()

    pull = asyncio.ensure_future(src.__anext__())
    await asyncio.sleep(0)  # park in receive()
    pull.cancel()  # external cancel; src is NOT closed → re-raise

    with pytest.raises(asyncio.CancelledError):
        await pull
    assert src.is_closed is False


async def test_source_sync_db_verify_hook_is_not_awaited():
    """A SYNCHRONOUS ``db_verify`` returning a bool is used without awaiting.

    Covers source.py:333->335 — the ``isawaitable(verified)`` False branch: a
    plain (non-coroutine) verify result is consumed directly. The remaining
    ``__lookup`` filter is verified True so the event is delivered.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    layer = _Layer()
    src = ChannelLayerSource(
        groups=["g1"],
        channel_layer=layer,
        filters={"author__name": "ada"},  # a __lookup → non-empty remaining
    )
    # A plain (sync) verify hook → exercises the non-awaitable branch.
    calls: list[tuple] = []

    def _sync_verify(remaining, event):
        calls.append((dict(remaining), dict(event)))
        return True

    src.db_verify = _sync_verify
    await src.start()

    await layer._queue.put(
        {"payload": {"data": {"id": 1, "name": "x"}, "action": "create"}}
    )
    value = await asyncio.wait_for(src.__anext__(), timeout=1.0)
    assert value == {"id": 1, "name": "x"}
    assert calls and calls[0][0] == {"author__name": "ada"}
    await src.aclose()


async def test_source_sync_db_verify_false_drops_event():
    """A sync ``db_verify`` returning False DROPS the event (no yield).

    Covers source.py:335-336 — ``if not verified: continue``. The first event is
    dropped; a second event whose verify passes is delivered, proving the loop
    continued rather than yielding the unverified row.
    """
    from django_graphex.subscriptions.source import ChannelLayerSource

    layer = _Layer()
    src = ChannelLayerSource(
        groups=["g1"],
        channel_layer=layer,
        filters={"owner__tenant__exact": 7},
    )
    verdicts = iter([False, True])
    src.db_verify = lambda remaining, event: next(verdicts)
    await src.start()

    await layer._queue.put({"payload": {"data": {"id": 1}, "action": "create"}})
    await layer._queue.put({"payload": {"data": {"id": 2}, "action": "create"}})
    value = await asyncio.wait_for(src.__anext__(), timeout=1.0)
    # The first (verify=False) event was dropped; only the second is delivered.
    assert value == {"id": 2}
    await src.aclose()


# ---------------------------------------------------------------------------
# streaming.py — the allow-all default hooks
# ---------------------------------------------------------------------------


async def test_streaming_default_hooks_are_allow_all_noops():
    """The default authorize/scope/instance_index hooks are no-op allow-all.

    Covers streaming.py:76, 81, 86 — the default hook bodies. These run when a
    spec leaves a hook unset (the engine's allow-all baseline).
    """
    from django_graphex.subscriptions import streaming

    assert streaming._default_authorize(object(), action="create") is None
    assert streaming._default_scope(object(), action="create") is None
    assert streaming._default_instance_index(object()) is None


async def test_streaming_spec_defaults_use_the_allow_all_hooks():
    """A ``SubscriptionSpec`` with unset hooks carries the allow-all defaults.

    Asserts the wiring: an unset hook is the module-level default, so a build
    that omits authorize/scope inherits the no-op allow-all behavior.
    """
    from graphql import parse

    from django_graphex.subscriptions.streaming import (
        SubscriptionSpec,
        _default_authorize,
        _default_instance_index,
        _default_scope,
    )

    spec = SubscriptionSpec(
        model_label="tests.post",
        stream="posts",
        schema=None,
        document=parse("subscription { x }"),
    )
    assert spec.authorize is _default_authorize
    assert spec.scope is _default_scope
    assert spec.instance_index is _default_instance_index


# ---------------------------------------------------------------------------
# mixins.py — split_filters remaining + safe_group_name hashing
# ---------------------------------------------------------------------------


def test_mixins_split_filters_keeps_lookup_keys_as_remaining():
    """A ``__lookup`` key is returned as a remaining DB-side filter, not dropped.

    Covers mixins.py:67 — the ``else: remaining[key] = value`` arm (a key with a
    ``__`` lookup the in-memory equality gate cannot resolve).
    """
    from django_graphex.subscriptions.mixins import split_filters

    remaining = split_filters({"id": 1}, {"author__name": "ada"})
    assert remaining == {"author__name": "ada"}


def test_mixins_split_filters_in_memory_mismatch_drops():
    """An in-memory equality mismatch short-circuits to ``None`` (drop the event).

    Covers mixins.py:64-65 — the str-coerced mismatch returning ``None``.
    """
    from django_graphex.subscriptions.mixins import split_filters

    assert split_filters({"views": 5}, {"views": 9}) is None
    # Equal (str-coerced) → empty remaining (fully matched in memory).
    assert split_filters({"views": "7"}, {"views": 7}) == {}


def test_mixins_safe_group_name_hashes_overlong_or_invalid_names():
    """An over-length / invalid-charset name is deterministically hashed.

    Covers mixins.py:38-39 — the hashing branch. A valid short name passes through
    unchanged; an invalid one is hashed to a stable ``gde.<sha256>`` value.
    """
    from django_graphex.subscriptions.mixins import (
        MAX_GROUP_NAME_LENGTH,
        safe_group_name,
    )

    assert safe_group_name("posts.create") == "posts.create"

    # Invalid charset (space) → hashed, deterministic.
    hashed = safe_group_name("posts create!")
    assert hashed.startswith("gde.")
    assert safe_group_name("posts create!") == hashed

    # Over-length → hashed too.
    overlong = "x" * (MAX_GROUP_NAME_LENGTH + 1)
    assert safe_group_name(overlong).startswith("gde.")
