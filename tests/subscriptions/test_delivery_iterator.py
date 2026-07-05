# -*- coding: utf-8 -*-
"""WU2 — COND-A lightweight delivery iterator.

The Phase 6 COND-A decision (design paragraph 4, GO-gate #1516): instead of
graphql-core's stock "subscribe()" -> "MapAsyncIterator" delivery (which
does, per yielded value, 2x "ensure_future" + "asyncio.wait" + per-value
"Task.cancel" -> ~47 us/value), django-graphex OWNS a lightweight
"async for v in source: yield await map(v)" wrapper (~0.19 us/value, ~250x)
that is structurally distinct from "MapAsyncIterator" AND supports
OUT-OF-BAND CLOSE so a caller (complete{id} / disconnect) can stop
iteration IMMEDIATELY without waiting on asyncio.wait.

This module is transport-agnostic: "delivery.py" imports neither channels,
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
from pytest_django.fixtures import DjangoAssertNumQueries

# ---------------------------------------------------------------------------
# Helpers: in-memory async sources (no DB, no channels, no execute() variance)
# ---------------------------------------------------------------------------


async def _list_source(values: list[Any]) -> AsyncGenerator[Any, None]:
    """Yield each value from "values" in order. Records nothing extra."""
    for value in values:
        yield value


class _RecordingSource:
    """An async generator-like source that records whether "aclose" ran.

    Used to prove that closing the delivery iterator also closes the underlying
    source (the design's "aclose()s the underlying source if it has aclose"
    requirement).
    """

    def __init__(self, values: list[Any]) -> None:
        """Store a copy of the values to yield and reset the close flag.

        Args:
            values: The values this source will yield, in order.
        """
        self._values = list(values)
        self._index = 0
        self.aclosed = False
        # An asyncio.Event a producer would set to release a blocked receive.
        self._gate: asyncio.Event | None = None

    def __aiter__(self) -> "_RecordingSource":
        """Return self, satisfying the async iterator protocol.

        Returns:
            self: This source instance.
        """
        return self

    async def __anext__(self) -> Any:
        """Return the next stored value, or stop iteration when exhausted.

        Returns:
            value: The next value in the stored sequence.

        Raises:
            StopAsyncIteration: When every stored value has been yielded.
        """
        if self._index >= len(self._values):
            raise StopAsyncIteration
        value = self._values[self._index]
        self._index += 1
        return value

    async def aclose(self) -> None:
        """Record that this source was closed."""
        self.aclosed = True


class _BlockingSource:
    """A source whose next value never arrives until a producer sets the gate.

    Models a real Channels group consumer blocked in "receive()" waiting for
    the next broadcast. The out-of-band close test uses this to prove that
    "aclose()" stops iteration PROMPTLY instead of hanging on the pending
    "__anext__".
    """

    def __init__(self, warmup: list[Any]) -> None:
        """Store the warmup values and initialize the never-set close gate.

        Args:
            warmup: The values to yield before the source starts blocking.
        """
        self._warmup = list(warmup)
        self._index = 0
        self.aclosed = False
        self._gate = asyncio.Event()  # never set in the close test

    def __aiter__(self) -> "_BlockingSource":
        """Return self, satisfying the async iterator protocol.

        Returns:
            self: This source instance.
        """
        return self

    async def __anext__(self) -> Any:
        """Return the next warmup value, then block forever awaiting the gate.

        Returns:
            value: The next warmup value, while any remain.

        Raises:
            StopAsyncIteration: Only reached if the gate is ever set, which
                the close test does not do (aclose() unblocks the wait via
                cancellation instead).
        """
        if self._index < len(self._warmup):
            value = self._warmup[self._index]
            self._index += 1
            return value
        # No more warmup values: block forever (until a producer sets the gate).
        await self._gate.wait()
        raise StopAsyncIteration  # pragma: no cover - gate never set in tests

    async def aclose(self) -> None:
        """Record the close and release any pending wait on the gate."""
        self.aclosed = True
        self._gate.set()  # unblock any pending wait so the task can finish


async def _identity(value: Any) -> Any:
    """Return the value unchanged."""
    return value


async def _double(value: int) -> int:
    """Return twice the given integer value."""
    return value * 2


# ---------------------------------------------------------------------------
# ORDERED delivery + completion
# ---------------------------------------------------------------------------


async def test_values_delivered_in_order() -> None:
    """N source values must produce N mapped outputs in the same order.

    Contract: this test ships broken if the delivery iterator reorders,
    drops, or duplicates values from the source.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2, 3, 4, 5]), _double)
    out = [value async for value in delivery]
    assert out == [2, 4, 6, 8, 10]


async def test_completion_propagated() -> None:
    """An exhausted source must make the delivery iterator raise StopAsyncIteration.

    Contract: this test ships broken if the iterator hangs or raises a
    different exception once the source is exhausted.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1]), _identity)
    assert await delivery.__anext__() == 1
    with pytest.raises(StopAsyncIteration):
        await delivery.__anext__()


async def test_aiter_returns_self() -> None:
    """ "__aiter__" must return the iterator itself (async-for compatible).

    Contract: this test ships broken if the delivery iterator is not
    directly usable in an "async for" loop.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2]), _identity)
    assert delivery.__aiter__() is delivery


async def test_map_fn_may_be_plain_callable() -> None:
    """A non-coroutine map fn must also be supported.

    Contract: this test ships broken if the delivery iterator requires the
    map function to be a coroutine, since the result is only awaited when
    it is itself awaitable.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2, 3]), lambda v: v + 100)
    out = [value async for value in delivery]
    assert out == [101, 102, 103]


# ---------------------------------------------------------------------------
# OUT-OF-BAND CLOSE — prompt cancellation, underlying source closed
# ---------------------------------------------------------------------------


async def test_out_of_band_close_mid_stream_prompt() -> None:
    """Mid-stream aclose() must make the next __anext__ raise StopAsyncIteration promptly.

    Contract: this test ships broken if closing mid-stream does not
    immediately stop iteration, or if the underlying source is left open.

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


async def test_close_does_not_hang_on_blocked_source() -> None:
    """aclose() on a source blocked in receive() must return promptly, without hanging.

    Contract: this test ships broken if closing while a receive is pending
    hangs instead of resolving within a tight timeout.

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


async def test_aclose_idempotent() -> None:
    """Calling aclose() twice must be safe and must not raise.

    Contract: this test ships broken if a redundant second aclose() call
    (e.g. from overlapping cleanup paths) raises instead of no-op'ing.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    source = _RecordingSource([1, 2, 3])
    delivery = make_delivery_iterator(source, _identity)
    await delivery.aclose()
    await delivery.aclose()  # second call is a no-op
    assert source.aclosed is True


async def test_close_event_handle_exposed() -> None:
    """The delivery iterator must expose a close handle (asyncio.Event-like).

    Contract: this test ships broken if callers lose the ability to signal
    close out-of-band via either "aclose()" or a settable close handle.

    A caller (complete{id} / disconnect) can signal close out-of-band either via
    "aclose()" (the coroutine) or by setting the close handle directly.
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


async def test_delivery_is_not_map_async_iterator() -> None:
    """The delivery object must not be a graphql-core MapAsyncIterator.

    Contract: this is the structural guard from design paragraph 4 — the
    COND-A win ships broken if a refactor accidentally routes delivery
    through MapAsyncIterator, silently reintroducing the ~47 us/value cost.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    delivery = make_delivery_iterator(_list_source([1, 2, 3]), _identity)
    assert isinstance(delivery, MapAsyncIterator) is False

    # And prove the guard discriminates: a real MapAsyncIterator IS one.
    stock = MapAsyncIterator(_list_source([1, 2, 3]), lambda v: v)
    assert isinstance(stock, MapAsyncIterator) is True


def test_delivery_module_has_no_map_async_iterator_import() -> None:
    """Static guard: "delivery.py" must not import MapAsyncIterator.

    Contract: this test ships broken if the module gains a MapAsyncIterator
    import, catching an accidental re-introduction even if the runtime
    structural assert above were somehow bypassed.
    """
    from django_graphex.subscriptions import delivery

    source = inspect.getsource(delivery)
    assert "MapAsyncIterator" not in source
    assert "map_async_iterator" not in source


def test_delivery_module_has_no_graphene_or_channels_import() -> None:
    """Transport-agnostic guard: "delivery.py" must import neither graphene nor channels.

    Contract: this test ships broken if the module gains a graphene,
    channels, or Django dependency, breaking its pure-asyncio contract.
    """
    from django_graphex.subscriptions import delivery

    source = inspect.getsource(delivery)
    assert "import graphene" not in source
    assert "from graphene" not in source
    assert "import channels" not in source
    assert "from channels" not in source
    assert "import django" not in source
    assert "from django" not in source


def test_delivery_module_dunder_all() -> None:
    """The "delivery" module's __all__ must export the factory and class.

    Contract: this test ships broken if make_delivery_iterator or
    DeliveryIterator stops being re-exported through __all__.
    """
    from django_graphex.subscriptions import delivery

    assert hasattr(delivery, "__all__")
    assert "make_delivery_iterator" in delivery.__all__
    assert "DeliveryIterator" in delivery.__all__


# ---------------------------------------------------------------------------
# Map fn errors propagate (do not swallow silently)
# ---------------------------------------------------------------------------


async def test_map_fn_error_propagates() -> None:  # noqa: DOC005
    """An exception raised inside the map fn must propagate to the consumer.

    Contract: this test ships broken if a map-function error is swallowed
    instead of surfacing to the caller consuming the delivery iterator.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    class _Boom(Exception):
        """A sentinel exception raised by the failing map function under test."""

    async def _explode(_value: Any) -> Any:
        raise _Boom("map fn failed")

    delivery = make_delivery_iterator(_list_source([1, 2, 3]), _explode)
    with pytest.raises(_Boom, match="map fn failed"):
        await delivery.__anext__()


async def test_source_error_propagates() -> None:  # noqa: DOC005
    """An exception raised by the underlying source must propagate.

    Contract: this test ships broken if a source-side error is swallowed
    instead of surfacing to the delivery iterator's consumer.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    class _SourceBoom(Exception):
        """A sentinel exception raised by the failing source under test."""

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
def test_assertNumQueries_zero_per_value(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Delivering N in-memory dict values must hit zero DB queries total.

    Contract: the serialize-once invariant ships broken if delivery
    re-instantiates models or hits the ORM instead of streaming the
    pre-serialized flat dicts as-is.

    This test is intentionally SYNC: "django_assert_num_queries" calls
    "ensure_connection()" synchronously, which raises SynchronousOnlyOperation
    if a loop is already running (the asyncio_mode="auto" case). We drive the
    async delivery via "asyncio.run" INSIDE the sync assertion block so the
    query-count guard wraps the full async consumption.

    Args:
        django_assert_num_queries: The pytest-django fixture used as a
            context manager asserting an exact DB query count.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    payloads = [{"id": i, "is_active": True} for i in range(10)]

    async def _drive() -> list[dict[str, Any]]:
        delivery = make_delivery_iterator(_list_source(payloads), _identity)
        return [value async for value in delivery]

    with django_assert_num_queries(0):
        out = asyncio.run(_drive())

    assert out == payloads
    assert len(out) == 10


# ---------------------------------------------------------------------------
# PERF sanity — lightweight per-value overhead materially below MapAsyncIterator
# ---------------------------------------------------------------------------


async def _consume_all(delivery: AsyncIterator[Any]) -> int:
    """Drain an async iterator fully and count how many values it yielded.

    Args:
        delivery: The async iterator to drain.

    Returns:
        count: The number of values yielded before exhaustion.
    """
    count = 0
    async for _value in delivery:
        count += 1
    return count


def _median_per_value_us(
    make: Callable[[], AsyncIterator[Any]], n: int, runs: int = 5
) -> float:
    """Compute the median wall-clock per-value microseconds over "runs" timed loops.

    Args:
        make: A factory building a fresh async iterator to benchmark.
        n: The number of values the built iterator is expected to yield.
        runs: The number of timed runs to take the median over, after two
            discarded warmup runs.

    Returns:
        median_us: The median per-value time in microseconds.
    """

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


def test_perf_lightweight_materially_below_stock() -> None:
    """The lightweight per-value cost must stay materially below stock MapAsyncIterator.

    Contract: this test ships broken if the lightweight wrapper's median
    per-value time exceeds either the absolute 5 us/value ceiling or one
    tenth of stock MapAsyncIterator's per-value time.

    Conservative, noise-robust bound: the lightweight wrapper's median per-value
    time must be BOTH (a) below an absolute 5 us/value ceiling AND (b) below
    one tenth of stock MapAsyncIterator's per-value time. The GO-gate spike
    measured ~0.19 us (light) vs ~47 us (stock) — ~250x — so a 10x bound has
    enormous headroom and will not flake on a busy CI box.
    """
    from django_graphex.subscriptions.delivery import make_delivery_iterator

    n = 2000

    def _make_light() -> AsyncIterator[Any]:
        return make_delivery_iterator(_list_source(list(range(n))), lambda v: v)

    def _make_stock() -> AsyncIterator[Any]:
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
