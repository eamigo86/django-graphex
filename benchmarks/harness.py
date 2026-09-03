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

  3. surface — the declared field list of Author / Post / Comment, read back
     out of the running schema by introspection. The fairness rule says all four
     libraries declare the SAME fields; recording them puts that claim in the
     artifact where a reader can diff it instead of trusting the README.

``create_comment`` is run LAST (it mutates the DB). All requests go through
``django.test.Client`` POSTing to ``/graphql/`` — no network, fully deterministic.

Output: results/<lib>.json, or results/<BENCH_PREFIX><lib>.json when
``BENCH_PREFIX`` is set (``BENCH_PREFIX=2x_`` writes the doubled-dataset
artifacts ``docs/why.md`` publishes).
"""

import json
import os
import platform
import statistics
import sys
import time
from contextlib import nullcontext
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

BENCH_LIB = os.environ.setdefault("BENCH_LIB", "graphex")
# Which SEED the run measures is the caller's business, not something this file
# can detect, so the artifact name carries it: BENCH_PREFIX=2x_ writes
# results/2x_<lib>.json, the doubled-dataset artifacts docs/why.md cites. Empty
# by default, so run_all.sh keeps writing results/<lib>.json byte-identically.
BENCH_PREFIX = os.environ.get("BENCH_PREFIX", "")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

WARMUP = 15
TIMED = 100
# Rebuilds of the schema, timed after the dependency tree is already imported.
SCHEMA_BUILDS = 5

# Operations that mutate the DB must run last.
MUTATING = {"create_comment"}


def _import_schema():
    """Import the active library's bench_schema and time it two separate ways.

    ``django.setup()`` must have already run: importing bench_schema pulls in the
    Django models, which requires the app registry to be populated.

    The FIRST import pays two costs at once — loading the library and its
    dependency tree off disk, and building the schema from the declarations —
    and only the second of those is a property of the library's compiler. They
    are wildly different sizes (strawberry spends over two orders of magnitude
    more time importing than building), so reporting the sum as "schema build"
    compares the wrong thing, and it is the import half that is cold-cache
    sensitive and therefore noisy.

    So the build is measured on its own: purge ``bench_schema`` from
    ``sys.modules`` and re-import it. The dependency tree stays cached, so the
    re-import re-executes only the module body — the declarations and the
    schema constructor. Verified fresh, not a cache hit: in all four libraries
    the rebuilt schema object, its ``GraphQLSchema``, its Author type and that
    type's fields are all new objects.
    """
    import importlib

    name = f"libs.{BENCH_LIB}.bench_schema"

    t0 = time.perf_counter()
    module = importlib.import_module(name)
    cold_import_ms = (time.perf_counter() - t0) * 1000.0

    build_samples = []
    for _ in range(SCHEMA_BUILDS):
        del sys.modules[name]
        t0 = time.perf_counter()
        module = importlib.import_module(name)
        build_samples.append(round((time.perf_counter() - t0) * 1000.0, 4))

    return module, cold_import_ms, build_samples


def _post(client, op):
    payload = {"query": op["query"]}
    if op.get("variables") is not None:
        payload["variables"] = op["variables"]
    resp = client.post(
        "/graphql/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.content[:500]!r}"
    return json.loads(resp.content)


def _isolated_post(client, op, *, timed=False, count_queries=False):
    """Execute one request in a rollback-only transaction.

    Transaction boundaries sit outside both the timer and query capture. This
    leaves the database rows and SQLite sequence unchanged after every
    validation, SQL probe, warmup and measured sample.
    """
    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext

    with transaction.atomic():
        query_context = (
            CaptureQueriesContext(connection) if count_queries else nullcontext()
        )
        with query_context as captured:
            started = time.perf_counter() if timed else None
            response = _post(client, op)
            elapsed_ms = (
                (time.perf_counter() - started) * 1000.0
                if started is not None
                else None
            )
        transaction.set_rollback(True)
    sql_queries = len(captured.captured_queries) if count_queries else None
    return response, elapsed_ms, sql_queries


_SURFACE_QUERY = """
    query {
      __schema {
        types { name fields { name } }
      }
    }
"""


def _surface(client):
    """Read the declared field list of the three benchmarked types back out.

    The fairness rule says all four libraries declare the SAME field lists, and a
    rule nobody can check is a rule nobody should believe. Introspecting the
    running schema puts the answer in the result artifact, where a reader can
    diff it across libraries instead of taking the claim on trust.

    Type names differ by library idiom (ariadne's SDL says ``Post``, the three
    class-based libraries say ``PostType``), so both spellings are accepted.

    Args:
        client: A Django test client already pointed at the mounted GraphQL view.

    Returns:
        Model name mapped to its sorted declared field names.
    """
    resp = _post(client, {"query": _SURFACE_QUERY, "variables": None})
    by_name = {t["name"]: t for t in resp["data"]["__schema"]["types"]}
    out = {}
    for model in ("Author", "Post", "Comment"):
        entry = by_name.get(f"{model}Type") or by_name.get(model)
        out[model] = sorted(f["name"] for f in (entry or {}).get("fields") or ())
    return out


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


def main() -> None:
    """Run the selected library's isolated benchmark and write its result.

    Raises:
        AssertionError: If an operation returns an invalid response.
    """
    # 1) Django bootstrap first (populate the app registry). Not timed.
    import django

    django.setup()

    # 2) Time the cold import and, separately, the schema build itself.
    schema_module, cold_import_ms, build_samples = _import_schema()

    from django.test import Client

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
        first, _, _ = _isolated_post(client, op)
        try:
            op["validate"](first)
        except AssertionError as exc:
            sys.stderr.write(
                f"\nVALIDATION FAILED for op '{name}' ({BENCH_LIB}): {exc}\n"
                f"Response: {json.dumps(first)[:1000]}\n"
            )
            raise

        # SQL query count: one extra instrumented iteration (excluded from timings).
        _, _, sql_queries = _isolated_post(client, op, count_queries=True)

        # Warmup (untimed).
        for _ in range(WARMUP):
            _isolated_post(client, op)

        # Timed iterations.
        samples_ms = []
        for _ in range(TIMED):
            _, elapsed_ms, _ = _isolated_post(client, op, timed=True)
            samples_ms.append(elapsed_ms)

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
        # The cold first import: library + dependency tree + one schema build.
        # Cold-cache sensitive, so only comparable when every library's
        # virtualenv was warmed equally beforehand (run_all.sh does that).
        "schema_import_ms": round(cold_import_ms, 4),
        # Rebuilds of the schema with the dependency tree already imported, in
        # order. A DIAGNOSTIC, deliberately not reduced to a single figure and
        # NOT a cross-library comparison: re-executing the declarations
        # perturbs each library's process state differently, so the series is
        # only meaningful read down a single column. django-graphex climbs
        # here; ariadne is flat. See benchmarks/README.md.
        "schema_rebuild_samples_ms": build_samples,
        "surface": _surface(client),
        "ops": results,
    }

    out_dir = BASE_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{BENCH_PREFIX}{BENCH_LIB}.json"
    out_path.write_text(json.dumps(output, indent=2))
    sys.stdout.write(json.dumps(output, indent=2) + "\n")
    sys.stdout.write(f"\nWrote {out_path}\n")


if __name__ == "__main__":
    main()
