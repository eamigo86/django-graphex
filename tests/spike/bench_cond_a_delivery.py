"""COND-A PERF GO-GATE spike — Phase 6 (streaming-subscriptions), branch v2.0.0.

De-risks the design's COND-A decision to OWN the subscription delivery iterator
instead of using graphql-core's stock ``subscribe()`` path.

THE CLAIM UNDER TEST
--------------------
graphql-core's ``subscribe()`` -> ``map_source_to_response()`` wraps the source
in a ``MapAsyncIterator`` whose ``__anext__`` does, PER YIELDED VALUE (while open):

    aclose = ensure_future(self._close_event.wait())   # 1x ensure_future
    anext  = ensure_future(self.iterator.__anext__())   # 1x ensure_future
    pending = (await wait([aclose, anext], FIRST_COMPLETED))[1]   # 1x asyncio.wait
    for task in pending: task.cancel()                  # 1x Task.cancel (the close-watcher)

The design's alternative: a lightweight ``async for source_value in source:
yield map(source_value)`` wrapper with out-of-band close (asyncio.Event /
aclose()), which avoids MapAsyncIterator entirely.

GO requires the lightweight wrapper to be MATERIALLY faster than the stock
MapAsyncIterator delivery. Threshold used: >=2x throughput (the design cited
a ~4.6x swing; we report whether that holds too).

This is a SPIKE. It does NOT touch production code and is gitignored from the
default test run via ``--ignore=tests/spike``. Run explicitly:

    .venv/bin/python tests/spike/bench_cond_a_delivery.py
    # or
    .venv/bin/pytest tests/spike/bench_cond_a_delivery.py -v -s -p no:cacheprovider
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from typing import Any, AsyncGenerator, AsyncIterator, Callable, Optional

import pytest

# REAL graphql-core 3.2.11 delivery class — the one subscribe() actually returns.
# Confirmed by reading the venv source:
#   graphql/execution/subscribe.py:94  -> return MapAsyncIterator(stream, map_fn)
#   graphql/execution/map_async_iterator.py  -> the class definition
# Re-exported at top level as graphql.MapAsyncIterator.
from graphql import MapAsyncIterator

# Sanity: prior 3.11.x numbers are stale; this runtime must be >=3.12.
assert sys.version_info >= (3, 12), (
    f"COND-A INVALID on this runtime: got Python {sys.version_info}; need >=3.12."
)


# ---------------------------------------------------------------------------
# Fixtures: a source that yields N pre-built flat dict payloads (serialize-once),
# no DB, no execute() variance — so we isolate the ITERATOR overhead only.
# ---------------------------------------------------------------------------

# Pre-build payloads once at import so per-run generator construction is the only
# source-side work, identical for both paths.
def _make_payloads(n: int) -> list[dict]:
    return [{"id": i, "value": f"v{i}", "ok": True} for i in range(n)]


_PAYLOAD_CACHE: dict[int, list[dict]] = {}


def _payloads(n: int) -> list[dict]:
    if n not in _PAYLOAD_CACHE:
        _PAYLOAD_CACHE[n] = _make_payloads(n)
    return _PAYLOAD_CACHE[n]


async def _source(n: int) -> AsyncGenerator[dict, None]:
    """Async source generator: yields N pre-built dicts with no extra work."""
    for payload in _payloads(n):
        yield payload


# The "mapped work": identical and trivial in BOTH paths so we isolate the
# iterator overhead, NOT the work. A plain identity-ish dict touch.
def _trivial_map(payload: dict) -> dict:
    # Return as-is (the design's serialize-once payload is already flat).
    return payload


# ---------------------------------------------------------------------------
# The LIGHTWEIGHT wrapper (the design's approach): plain async-for delivery with
# an out-of-band asyncio.Event close. NOT a MapAsyncIterator.
# ---------------------------------------------------------------------------

class LightweightDelivery:
    """Design's bespoke transport: ``async for v in source: yield map(v)``.

    Out-of-band close via asyncio.Event so a concurrent task can stop iteration
    promptly without per-value ensure_future + asyncio.wait machinery.
    """

    __slots__ = ("_source", "_map", "_close_event")

    def __init__(self, source: AsyncIterator, map_fn: Callable[[Any], Any]) -> None:
        self._source = source.__aiter__()
        self._map = map_fn
        self._close_event = asyncio.Event()

    def __aiter__(self) -> "LightweightDelivery":
        return self

    async def __anext__(self) -> Any:
        if self._close_event.is_set():
            raise StopAsyncIteration
        # Hot path: no ensure_future, no asyncio.wait — just await the source.
        value = await self._source.__anext__()
        return self._map(value)

    async def aclose(self) -> None:
        """Out-of-band close: set the event and close the underlying source."""
        self._close_event.set()
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except RuntimeError:
                pass

    @property
    def is_closed(self) -> bool:
        return self._close_event.is_set()


# ---------------------------------------------------------------------------
# Timed consumers — wall-clock per delivery of all N values.
# ---------------------------------------------------------------------------

async def _consume_stock(n: int) -> float:
    """(a) STOCK path: graphql-core MapAsyncIterator with trivial map fn."""
    delivery = MapAsyncIterator(_source(n), _trivial_map)
    start = time.perf_counter()
    count = 0
    async for _v in delivery:
        count += 1
    elapsed = time.perf_counter() - start
    assert count == n, f"stock delivered {count}, expected {n}"
    return elapsed


async def _consume_lightweight(n: int) -> float:
    """(b) LIGHTWEIGHT path: design's plain async-for wrapper."""
    delivery = LightweightDelivery(_source(n), _trivial_map)
    start = time.perf_counter()
    count = 0
    async for _v in delivery:
        count += 1
    elapsed = time.perf_counter() - start
    assert count == n, f"lightweight delivered {count}, expected {n}"
    return elapsed


# ---------------------------------------------------------------------------
# Benchmark harness: warmup + median-of-runs, report spread.
# ---------------------------------------------------------------------------

WARMUP_RUNS = 2
TIMED_RUNS = 7  # >= 5 timed runs; odd for a clean median
N_VALUES = (100, 1000, 10_000)


def _bench_one(coro_fn: Callable[[int], Any], n: int) -> list[float]:
    """Run warmup + TIMED_RUNS, each in its own event loop, return timed seconds."""
    # Warmup (results discarded) — JIT-free Python, but warms caches/import paths.
    for _ in range(WARMUP_RUNS):
        asyncio.run(coro_fn(n))
    times: list[float] = []
    for _ in range(TIMED_RUNS):
        times.append(asyncio.run(coro_fn(n)))
    return times


def _stats(times: list[float], n: int) -> dict:
    per_value_us = [(t / n) * 1_000_000 for t in times]
    median_us = statistics.median(per_value_us)
    median_total = statistics.median(times)
    throughput = n / median_total if median_total > 0 else float("inf")
    return {
        "median_per_value_us": median_us,
        "min_per_value_us": min(per_value_us),
        "max_per_value_us": max(per_value_us),
        "stdev_per_value_us": statistics.pstdev(per_value_us),
        "throughput_vps": throughput,
    }


def run_benchmark() -> list[dict]:
    """Run the full N sweep, return a list of per-N result rows."""
    rows: list[dict] = []
    for n in N_VALUES:
        stock_times = _bench_one(_consume_stock, n)
        light_times = _bench_one(_consume_lightweight, n)
        stock = _stats(stock_times, n)
        light = _stats(light_times, n)
        # ratio = lightweight throughput / stock throughput (>1 means lightweight faster)
        ratio = light["throughput_vps"] / stock["throughput_vps"]
        rows.append(
            {
                "n": n,
                "stock": stock,
                "light": light,
                "throughput_ratio": ratio,
            }
        )
    return rows


def _print_results(rows: list[dict]) -> None:
    print(
        f"\nCOND-A delivery micro-benchmark "
        f"(Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}, "
        f"warmup={WARMUP_RUNS}, timed_runs={TIMED_RUNS})"
    )
    print(
        "  N        | stock µs/val (med [min-max] ±sd)        "
        "| light µs/val (med [min-max] ±sd)        | ratio (light tput / stock tput)"
    )
    print("  " + "-" * 120)
    for r in rows:
        s, l = r["stock"], r["light"]
        print(
            f"  {r['n']:<8} | "
            f"{s['median_per_value_us']:>7.3f} [{s['min_per_value_us']:.3f}-{s['max_per_value_us']:.3f}] "
            f"±{s['stdev_per_value_us']:.3f}    | "
            f"{l['median_per_value_us']:>7.3f} [{l['min_per_value_us']:.3f}-{l['max_per_value_us']:.3f}] "
            f"±{l['stdev_per_value_us']:.3f}    | "
            f"{r['throughput_ratio']:>5.2f}x"
        )


# ---------------------------------------------------------------------------
# (3) Structural assertion + (4) out-of-band close — functional checks.
# ---------------------------------------------------------------------------

class TestCondAStructural:
    def test_lightweight_is_not_map_async_iterator(self) -> None:
        """Structural guard: lightweight delivery is NOT a MapAsyncIterator."""
        delivery = LightweightDelivery(_source(3), _trivial_map)
        assert not isinstance(delivery, MapAsyncIterator), (
            "Lightweight delivery must NOT be a graphql-core MapAsyncIterator."
        )
        # And the stock one IS, to prove the guard discriminates.
        stock = MapAsyncIterator(_source(3), _trivial_map)
        assert isinstance(stock, MapAsyncIterator)
        print(
            "\n  [structural] isinstance(lightweight, MapAsyncIterator) = "
            f"{isinstance(delivery, MapAsyncIterator)} (expected False); "
            f"isinstance(stock, MapAsyncIterator) = {isinstance(stock, MapAsyncIterator)} (expected True)"
        )


class TestCondAOutOfBandClose:
    def test_prompt_cancellation_stops_iteration(self) -> None:
        """Out-of-band close: aclose() stops iteration promptly (next __anext__ raises)."""

        async def scenario() -> tuple[int, bool]:
            delivery = LightweightDelivery(_source(10_000), _trivial_map)
            seen = 0
            async for _v in delivery:
                seen += 1
                if seen == 3:
                    await delivery.aclose()  # out-of-band close mid-stream
                    break
            # After close, a fresh __anext__ must raise StopAsyncIteration immediately.
            stopped = False
            try:
                await delivery.__anext__()
            except StopAsyncIteration:
                stopped = True
            return seen, stopped

        seen, stopped = asyncio.run(scenario())
        assert seen == 3, f"expected to stop at 3, saw {seen}"
        assert stopped, "after aclose(), __anext__ must raise StopAsyncIteration"
        assert LightweightDelivery(_source(1), _trivial_map).is_closed is False
        print(
            f"\n  [close] consumed {seen} then aclose(); post-close __anext__ "
            f"raised StopAsyncIteration = {stopped} (prompt cancellation OK)"
        )


# ---------------------------------------------------------------------------
# (5) GO/NO-GO gate — the perf verdict.
# ---------------------------------------------------------------------------

# GO threshold: lightweight must be MATERIALLY faster. We require >=2x throughput
# at the representative N=1000 (the design's headline N). The design cited ~4.6x;
# we report whether that stronger claim holds too, but only gate on >=2x.
GO_THRESHOLD = 2.0


class TestCondAGoGate:
    def test_lightweight_materially_faster_than_stock(self) -> None:
        rows = run_benchmark()
        _print_results(rows)

        by_n = {r["n"]: r for r in rows}
        headline = by_n[1000]
        ratio_1k = headline["throughput_ratio"]

        verdict = "GO" if ratio_1k >= GO_THRESHOLD else "NO-GO"
        meets_design_claim = ratio_1k >= 4.6
        print(
            f"\n  [VERDICT] N=1000 throughput ratio (light/stock) = {ratio_1k:.2f}x "
            f"| threshold = {GO_THRESHOLD:.1f}x -> {verdict} "
            f"| meets design's ~4.6x claim: {meets_design_claim}"
        )

        assert ratio_1k >= GO_THRESHOLD, (
            f"NO-GO: lightweight throughput is only {ratio_1k:.2f}x stock at N=1000 "
            f"(threshold {GO_THRESHOLD:.1f}x). OWN-the-iterator may not be justified; "
            f"COND-A should be revisited."
        )


if __name__ == "__main__":
    # Standalone run: structural + close checks, then the perf sweep + verdict.
    print("=" * 100)
    print("COND-A PERF GO-GATE SPIKE — graphql-core MapAsyncIterator vs lightweight delivery")
    print("=" * 100)

    # Structural
    s = LightweightDelivery(_source(3), _trivial_map)
    stock = MapAsyncIterator(_source(3), _trivial_map)
    print(
        f"\n[structural] isinstance(light, MapAsyncIterator) = {isinstance(s, MapAsyncIterator)} "
        f"(expected False); isinstance(stock, MapAsyncIterator) = {isinstance(stock, MapAsyncIterator)} "
        f"(expected True)"
    )

    # Out-of-band close
    async def _close_scenario() -> tuple[int, bool]:
        delivery = LightweightDelivery(_source(10_000), _trivial_map)
        seen = 0
        async for _v in delivery:
            seen += 1
            if seen == 3:
                await delivery.aclose()
                break
        stopped = False
        try:
            await delivery.__anext__()
        except StopAsyncIteration:
            stopped = True
        return seen, stopped

    seen, stopped = asyncio.run(_close_scenario())
    print(
        f"[close] consumed {seen} then aclose(); post-close __anext__ raised "
        f"StopAsyncIteration = {stopped}"
    )

    # Perf sweep
    rows = run_benchmark()
    _print_results(rows)

    headline = {r["n"]: r for r in rows}[1000]
    ratio_1k = headline["throughput_ratio"]
    verdict = "GO" if ratio_1k >= GO_THRESHOLD else "NO-GO"
    print(
        f"\n[VERDICT] N=1000 throughput ratio (light/stock) = {ratio_1k:.2f}x "
        f"| threshold = {GO_THRESHOLD:.1f}x -> {verdict} "
        f"| meets design's ~4.6x claim: {ratio_1k >= 4.6}"
    )
    print("=" * 100)
