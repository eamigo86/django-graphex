# -*- coding: utf-8 -*-
"""WU2 — COND-A lightweight delivery iterator.

The Phase 6 COND-A decision (design §4, GO-gate #1516): instead of
graphql-core's stock ``subscribe()`` -> ``MapAsyncIterator`` delivery (which
does, per yielded value, 2x ``ensure_future`` + ``asyncio.wait`` + per-value
``Task.cancel`` -> ~47 us/value), django-graphex OWNS a lightweight
``async for v in source: yield await map(v)`` wrapper (~0.19 us/value, ~250x)
that is structurally distinct from ``MapAsyncIterator`` AND supports
OUT-OF-BAND CLOSE so a caller (``complete{id}`` / disconnect) can stop
iteration IMMEDIATELY without waiting on ``asyncio.wait``.

This module is transport-agnostic: ``delivery.py`` imports neither channels,
Django, nor graphene. It is pure asyncio.

These tests are the WU2 gate:
  - ORDERED delivery + completion propagation (StopAsyncIteration)
  - OUT-OF-BAND CLOSE: mid-stream aclose() -> next __anext__ raises PROMPTLY
    (does NOT hang waiting for the next source value) + underlying source
    aclose()d
  - STRUCTURAL ASSERT: our delivery obj is NOT a MapAsyncIterator (the design's
    load-bearing guard)
  - PERF sanity: per-value overhead materially below MapAsyncIterator (generous
    bound, robust to noise)
  - Map fn errors propagate (not swallowed)
  - assertNumQueries(0) across N values (dict source never touches the ORM)
"""
from __future__ import annotations

import asyncio
import inspect
import statistics
import time
from typing import Any, AsyncGenerator, AsyncIterator, Callable

import pytest

# REAL graphql-core delivery class — the one stock subscribe() returns and the
# one our wrapper must NOT be. Re-exported at the top level as
# graphql.MapAsyncIterator and defined at
# graphql/execution/map_async_iterator.py.
from graphql.execution.map_async_iterator import MapAsyncIterator

# ---------------------------------------------------------------------------
# Helpers: in-memory async sources (no DB, no channels, no execute() variance)
# ---------------------------------------------------------------------------


async def _list_source(values: list) -> AsyncGenerator[Any, None]:
    """Yield each value from *values* in order. Records nothing extra."""
    for value in values:
        yield value


class _RecordingSource:
    """An async generator-like source that records whether ``aclose`` ran.

    Used to prove that closing the delivery iterator also closes the underlying
    source (the design's "aclose()s the underlying source if it has aclose"
    requirement).
    """

    def __init__(self, values: list) -> None:
        self._values = list(values)
        self._index = 0
        self.aclosed = False
        # An asyncio.Event a producer would set to release a blocked receive.
        self._gate: asyncio.Event | None = None

    def __aiter__(self) -> "_RecordingSource":
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._values):
            raise StopAsyncIteration
        value = self._values[self._index]
        self._index += 1
        return value

    async def aclose(self) -> None:
        self.aclosed = True


class _BlockingSource:
    """A source whose next value never arrives until a producer sets the gate.

    Models a real Channels group consumer blocked in ``receive()`` waiting for
    the next broadcast. The out-of-band close test uses this to prove that
    ``aclose()`` stops iteration PROMPTLY instead of hanging on the pending
    ``__anext__``.
    """

    def __init__(self, warmup: list) -> None:
        self._warmup = list(warmup)
        self._index = 0
        self.aclosed = False
        self._gate = asyncio.Event()  # never set in the close test

    def __aiter__(self) -> "_BlockingSource":
        return self

    async def __anext__(self) -> Any:
        if self._index < len(self._warmup):
            value = self._warmup[self._index]
            self._index += 1
            return value
        # No more warmup values: block forever (until a producer sets the gate).
        await self._gate.wait()
        raise StopAsyncIteration  # pragma: no cover - gate never set in tests

    async def aclose(self) -> None:
        self.aclosed = True
        self._gate.set()  # unblock any pending wait so the task can finish


async def _identity(value: Any) -> Any:
    return value


async def _double(value: int) -> int:
    return value * 2


# ---------------------------------------------------------------------------
# ORDERED delivery + completion
# ---------------------------------------------------------------------------


async def test_values_delivered_in_order():
    """N source values -> N mapped outputs, in order."""
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2, 3, 4, 5]), _double)
    out = [value async for value in delivery]
    assert out == [2, 4, 6, 8, 10]


async def test_completion_propagated():
    """An exhausted source -> the delivery iterator raises StopAsyncIteration."""
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1]), _identity)
    assert await delivery.__anext__() == 1
    with pytest.raises(StopAsyncIteration):
        await delivery.__anext__()


async def test_aiter_returns_self():
    """``__aiter__`` returns the iterator itself (async-for compatible)."""
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2]), _identity)
    assert delivery.__aiter__() is delivery


async def test_map_fn_may_be_plain_callable():
    """A non-coroutine map fn is also supported (result awaited only if awaitable)."""
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2, 3]), lambda v: v + 100)
    out = [value async for value in delivery]
    assert out == [101, 102, 103]


# ---------------------------------------------------------------------------
# OUT-OF-BAND CLOSE — prompt cancellation, underlying source closed
# ---------------------------------------------------------------------------


async def test_out_of_band_close_mid_stream_prompt():
    """Mid-stream aclose() -> next __anext__ raises StopAsyncIteration PROMPTLY.

    The underlying source is also aclose()d. This is the COND-A requirement: a
    caller can stop iteration IMMEDIATELY without waiting on asyncio.wait or the
    next source value.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    source = _RecordingSource([10, 20, 30, 40])
    delivery = make_delivery_iterator(source, _identity)

    seen = []
    async for value in delivery:
        seen.append(value)
        if len(seen) == 2:
            await delivery.aclose()  # out-of-band close mid-stream
            break

    assert seen == [10, 20]
    # A fresh __anext__ after close must raise StopAsyncIteration immediately.
    with pytest.raises(StopAsyncIteration):
        await delivery.__anext__()
    # The underlying source was closed too.
    assert source.aclosed is True


async def test_close_does_not_hang_on_blocked_source():
    """aclose() on a source blocked in receive() returns PROMPTLY (no hang).

    Models a real Channels consumer blocked waiting for the next broadcast.
    We start a pending __anext__ in a background task, then aclose() the
    delivery iterator; the consumer task must finish promptly (cancelled or
    StopAsyncIteration) within a tight timeout — proving the close is
    out-of-band and not gated on the next source value.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    source = _BlockingSource(warmup=[1])
    delivery = make_delivery_iterator(source, _identity)

    # Drain the single warmup value so the next __anext__ blocks.
    assert await delivery.__anext__() == 1

    pending = asyncio.ensure_future(delivery.__anext__())
    await asyncio.sleep(0)  # let the task reach the blocked receive

    # Out-of-band close while a receive is pending.
    await delivery.aclose()

    # The pending __anext__ must resolve promptly (not hang).
    try:
        await asyncio.wait_for(pending, timeout=1.0)
    except (StopAsyncIteration, asyncio.CancelledError):
        pass
    except asyncio.TimeoutError:  # pragma: no cover - failure path
        pytest.fail("aclose() did not promptly cancel the pending __anext__")

    assert source.aclosed is True


async def test_aclose_idempotent():
    """Calling aclose() twice is safe and does not raise."""
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    source = _RecordingSource([1, 2, 3])
    delivery = make_delivery_iterator(source, _identity)
    await delivery.aclose()
    await delivery.aclose()  # second call is a no-op
    assert source.aclosed is True


async def test_close_event_handle_exposed():
    """The delivery iterator exposes a close handle (asyncio.Event-like).

    A caller (complete{id} / disconnect) can signal close out-of-band either via
    ``aclose()`` (the coroutine) or by setting the close handle directly.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2, 3]), _identity)
    # Either an aclose coroutine or a settable close event must exist.
    assert hasattr(delivery, "aclose")
    assert hasattr(delivery, "is_closed")
    assert delivery.is_closed is False


# ---------------------------------------------------------------------------
# STRUCTURAL ASSERT — the design's load-bearing COND-A guard
# ---------------------------------------------------------------------------


async def test_delivery_is_not_map_async_iterator():
    """Our delivery object MUST NOT be a graphql-core MapAsyncIterator.

    This is the structural guard from design §4: the COND-A win depends on
    NOT routing through MapAsyncIterator. If a refactor accidentally returned a
    MapAsyncIterator, the ~47 us/value overhead would silently return.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2, 3]), _identity)
    assert isinstance(delivery, MapAsyncIterator) is False

    # And prove the guard discriminates: a real MapAsyncIterator IS one.
    stock = MapAsyncIterator(_list_source([1, 2, 3]), lambda v: v)
    assert isinstance(stock, MapAsyncIterator) is True


def test_delivery_module_has_no_map_async_iterator_import():
    """Static guard: ``delivery.py`` must not import MapAsyncIterator.

    Reading the source text catches an accidental re-introduction even if the
    runtime structural assert above were somehow bypassed.
    """
    from django_graphex.subscriptions import delivery

    source = inspect.getsource(delivery)
    assert "MapAsyncIterator" not in source
    assert "map_async_iterator" not in source


def test_delivery_module_has_no_graphene_or_channels_import():
    """Transport-agnostic: ``delivery.py`` imports neither graphene nor channels."""
    from django_graphex.subscriptions import delivery

    source = inspect.getsource(delivery)
    assert "import graphene" not in source
    assert "from graphene" not in source
    assert "import channels" not in source
    assert "from channels" not in source
    assert "import django" not in source
    assert "from django" not in source


def test_delivery_module_dunder_all():
    """``__all__`` must export the delivery factory and class."""
    from django_graphex.subscriptions import delivery

    assert hasattr(delivery, "__all__")
    assert "make_delivery_iterator" in delivery.__all__
    assert "DeliveryIterator" in delivery.__all__


# ---------------------------------------------------------------------------
# Map fn errors propagate (do not swallow silently)
# ---------------------------------------------------------------------------


async def test_map_fn_error_propagates():
    """An exception raised inside the map fn propagates to the consumer."""
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    class _Boom(Exception):
        pass

    async def _explode(_value: Any) -> Any:
        raise _Boom("map fn failed")

    delivery = make_delivery_iterator(_list_source([1, 2, 3]), _explode)
    with pytest.raises(_Boom, match="map fn failed"):
        await delivery.__anext__()


async def test_source_error_propagates():
    """An exception raised by the underlying source propagates."""
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    class _SourceBoom(Exception):
        pass

    async def _bad_source() -> AsyncGenerator[Any, None]:
        yield 1
        raise _SourceBoom("source failed")

    delivery = make_delivery_iterator(_bad_source(), _identity)
    assert await delivery.__anext__() == 1
    with pytest.raises(_SourceBoom, match="source failed"):
        await delivery.__anext__()


# ---------------------------------------------------------------------------
# assertNumQueries(0) — the dict source path never touches the ORM
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assertNumQueries_zero_per_value(django_assert_num_queries):
    """Delivering N in-memory dict values hits ZERO DB queries total.

    The serialize-once invariant: the flat dicts are pre-serialized, so delivery
    must never re-instantiate models or hit the ORM.

    This test is intentionally SYNC: ``django_assert_num_queries`` calls
    ``ensure_connection()`` synchronously, which raises ``SynchronousOnlyOperation``
    if a loop is already running (the asyncio_mode="auto" case). We drive the
    async delivery via ``asyncio.run`` INSIDE the sync assertion block so the
    query-count guard wraps the full async consumption.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    payloads = [{"id": i, "is_active": True} for i in range(10)]

    async def _drive() -> list:
        delivery = make_delivery_iterator(_list_source(payloads), _identity)
        return [value async for value in delivery]

    with django_assert_num_queries(0):
        out = asyncio.run(_drive())

    assert out == payloads
    assert len(out) == 10


# ---------------------------------------------------------------------------
# PERF sanity — lightweight per-value overhead materially below MapAsyncIterator
# ---------------------------------------------------------------------------


async def _consume_all(delivery: AsyncIterator) -> int:
    count = 0
    async for _value in delivery:
        count += 1
    return count


def _median_per_value_us(make: Callable[[], AsyncIterator], n: int, runs: int = 5) -> float:
    """Median wall-clock per-value microseconds over *runs* timed loops."""

    async def _one() -> float:
        delivery = make()
        start = time.perf_counter()
        count = await _consume_all(delivery)
        elapsed = time.perf_counter() - start
        assert count == n
        return (elapsed / n) * 1_000_000

    # Warmup (discarded).
    asyncio.run(_one())
    asyncio.run(_one())
    times = [asyncio.run(_one()) for _ in range(runs)]
    return statistics.median(times)


def test_perf_lightweight_materially_below_stock():
    """Sanity perf bound: lightweight per-value << stock MapAsyncIterator.

    Conservative, noise-robust bound: the lightweight wrapper's median per-value
    time must be BOTH (a) below an absolute 5 us/value ceiling AND (b) below
    one tenth of stock MapAsyncIterator's per-value time. The GO-gate spike
    measured ~0.19 us (light) vs ~47 us (stock) — ~250x — so a 10x bound has
    enormous headroom and will not flake on a busy CI box.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    n = 2000

    def _make_light() -> AsyncIterator:
        return make_delivery_iterator(_list_source(list(range(n))), lambda v: v)

    def _make_stock() -> AsyncIterator:
        return MapAsyncIterator(_list_source(list(range(n))), lambda v: v)

    light_us = _median_per_value_us(_make_light, n)
    stock_us = _median_per_value_us(_make_stock, n)

    assert light_us < 5.0, (
        f"lightweight per-value {light_us:.3f} us exceeds the 5 us ceiling "
        f"(COND-A budget)"
    )
    assert light_us < stock_us / 10.0, (
        f"lightweight ({light_us:.3f} us) is not materially below stock "
        f"({stock_us:.3f} us): expected light < stock/10"
    )
