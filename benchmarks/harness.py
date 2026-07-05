"""Benchmark harness — runs INSIDE a per-library virtualenv.

Invocation (done by run_all.sh, but you can run it manually):

    BENCH_LIB=graphex .venv-graphex/bin/python harness.py

What it measures, per library:

  1. schema_import_ms — wall time to import ``libs/<lib>/bench_schema.py``
     (i.e. build the GraphQL schema). Captured once, around the import.
  2. Per operation (flat_list, nested, single, filtered, create_comment):
       * warmup: 15 untimed iterations
       * timed: 100 iterations (time.perf_counter, milliseconds)
       * stats: mean / p50 / p95 / min / stddev
       * sql_queries: ONE extra instrumented iteration with
         CaptureQueriesContext (excluded from timings) recording the SQL count
       * validate(): run on the FIRST response — a benchmark that returns the
         wrong shape is INVALID, so we abort loudly on AssertionError.

``create_comment`` is run LAST (it mutates the DB). All requests go through
``django.test.Client`` POSTing to ``/graphql/`` — no network, fully deterministic.

Output: results/<lib>.json.
"""

import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

BENCH_LIB = os.environ.setdefault("BENCH_LIB", "graphex")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

WARMUP = 15
TIMED = 100

# Operations that mutate the DB must run last.
MUTATING = {"create_comment"}


def _import_schema():
    """Import the active library's bench_schema, timing the import (schema build).

    ``django.setup()`` must have already run: importing bench_schema pulls in the
    Django models, which requires the app registry to be populated. The timed
    region is JUST the schema-building import, not Django bootstrap.
    """
    import importlib

    t0 = time.perf_counter()
    module = importlib.import_module(f"libs.{BENCH_LIB}.bench_schema")
    schema_import_ms = (time.perf_counter() - t0) * 1000.0
    return module, schema_import_ms


def _post(client, op):
    payload = {"query": op["query"]}
    if op.get("variables") is not None:
        payload["variables"] = op["variables"]
    resp = client.post(
        "/graphql/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200, (
        f"HTTP {resp.status_code}: {resp.content[:500]!r}"
    )
    return json.loads(resp.content)


def _stats(samples_ms):
    samples = sorted(samples_ms)
    n = len(samples)
    return {
        "mean_ms": round(statistics.mean(samples), 4),
        "p50_ms": round(statistics.median(samples), 4),
        "p95_ms": round(samples[min(n - 1, int(round(0.95 * (n - 1))))], 4),
        "min_ms": round(samples[0], 4),
        "stddev_ms": round(statistics.pstdev(samples), 4),
        "iterations": n,
    }


def main():
    # 1) Django bootstrap first (populate the app registry). Not timed.
    import django

    django.setup()

    # 2) Time the schema import (schema build) — the region we actually measure.
    schema_module, schema_import_ms = _import_schema()

    from django.db import connection
    from django.test import Client
    from django.test.utils import CaptureQueriesContext

    operations = schema_module.OPERATIONS
    lib_versions = schema_module.LIB_VERSIONS

    client = Client()

    # Order: all read ops first (any order), mutating ops last.
    read_ops = [name for name in operations if name not in MUTATING]
    mutating_ops = [name for name in operations if name in MUTATING]
    ordered = read_ops + mutating_ops

    results = {}
    for name in ordered:
        op = operations[name]

        # First response: validate shape (abort loudly on wrong data).
        first = _post(client, op)
        try:
            op["validate"](first)
        except AssertionError as exc:
            sys.stderr.write(
                f"\nVALIDATION FAILED for op '{name}' ({BENCH_LIB}): {exc}\n"
                f"Response: {json.dumps(first)[:1000]}\n"
            )
            raise

        # SQL query count: one extra instrumented iteration (excluded from timings).
        with CaptureQueriesContext(connection) as ctx:
            _post(client, op)
        sql_queries = len(ctx.captured_queries)

        # Warmup (untimed).
        for _ in range(WARMUP):
            _post(client, op)

        # Timed iterations.
        samples_ms = []
        for _ in range(TIMED):
            t0 = time.perf_counter()
            _post(client, op)
            samples_ms.append((time.perf_counter() - t0) * 1000.0)

        stats = _stats(samples_ms)
        stats["sql_queries"] = sql_queries
        results[name] = stats

    output = {
        "lib": BENCH_LIB,
        "versions": lib_versions,
        "python": platform.python_version(),
        "django": django.__version__,
        "machine": {
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "schema_import_ms": round(schema_import_ms, 4),
        "ops": results,
    }

    out_dir = BASE_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{BENCH_LIB}.json"
    out_path.write_text(json.dumps(output, indent=2))
    sys.stdout.write(json.dumps(output, indent=2) + "\n")
    sys.stdout.write(f"\nWrote {out_path}\n")


if __name__ == "__main__":
    main()
