"""Measure projection security overhead inside the GraphEx benchmark.

docs/why.md publishes a number for the guard, and a number nobody can reproduce
is a number nobody should believe. This script wraps the shared
publishes_column_value predicate with a counting timer, then measures the same
schema-build and nested-request regions as harness.py.

    BENCH_LIB=graphex DJANGO_SETTINGS_MODULE=config.settings \\
      .venv-graphex/bin/python guard_cost.py

The reported guard total is an upper bound. The timer's two perf_counter_ns
calls are inside the measured span, so roughly 0.1 microseconds of every call
belongs to the instrument rather than to the predicate. That bias deliberately
overstates rather than understates the security cost.

Both the defining module and the pagination module binding are patched. Patching
only the definition would miss ordering-allowlist calls and report zero cost per
request.
"""

import importlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("BENCH_LIB", "graphex")

WARMUP = 15
TIMED = 100

STATE = {"calls": 0, "ns": 0}


def _reset() -> None:
    """Zero the call counter and the accumulated predicate time."""
    STATE["calls"] = 0
    STATE["ns"] = 0


def _snapshot() -> tuple[int, float]:
    """Read the counter back.

    Returns:
        Call count and accumulated predicate time in milliseconds.
    """
    return STATE["calls"], STATE["ns"] / 1e6


def main() -> None:
    """Measure schema-build and nested-request guard costs.

    The resulting JSON report is written to standard output.
    """
    import django

    django.setup()

    from django_graphex.core import output_compiler
    from django_graphex.paginations import pagination

    real = output_compiler.publishes_column_value

    def counted(node_type: Any, field: Any) -> bool:
        """Answer exactly as the real predicate does, and record the cost.

        Args:
            node_type: The compiled type the guard is asking about.
            field: The model field whose value publication is in question.

        Returns:
            Whatever the wrapped predicate returns.
        """
        started = time.perf_counter_ns()
        try:
            return real(node_type, field)
        finally:
            STATE["calls"] += 1
            STATE["ns"] += time.perf_counter_ns() - started

    output_compiler.publishes_column_value = counted
    pagination.publishes_column_value = counted

    # Region 1: the schema build, the same import harness.py times.
    _reset()
    started = time.perf_counter()
    module = importlib.import_module("libs.graphex.bench_schema")
    build_ms = (time.perf_counter() - started) * 1000.0
    build_calls, build_guard_ms = _snapshot()

    from django.test import Client

    client = Client()
    payload = json.dumps({"query": module.OPERATIONS["nested"]["query"]})

    def post() -> None:
        """POST the nested operation once, failing loudly on a non-200."""
        response = client.post(
            "/graphql/", data=payload, content_type="application/json"
        )
        assert response.status_code == 200, response.status_code

    for _ in range(WARMUP):
        post()

    # Region 2: one nested request, the ordering allowlist's live path.
    request_ms = []
    guard_ms = []
    guard_calls = set()
    for _ in range(TIMED):
        _reset()
        started = time.perf_counter()
        post()
        request_ms.append((time.perf_counter() - started) * 1000.0)
        calls, elapsed = _snapshot()
        guard_calls.add(calls)
        guard_ms.append(elapsed)

    request_p50 = statistics.median(request_ms)
    guard_p50 = statistics.median(guard_ms)
    print(
        json.dumps(
            {
                "schema_build_ms": round(build_ms, 4),
                "build_guard_calls": build_calls,
                "build_guard_ms": round(build_guard_ms, 4),
                "nested_p50_ms": round(request_p50, 4),
                "nested_stddev_ms": round(statistics.pstdev(request_ms), 4),
                "request_guard_calls": sorted(guard_calls),
                "request_guard_p50_ms": round(guard_p50, 5),
                "request_guard_share_pct": round(100.0 * guard_p50 / request_p50, 4),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
