"""Benchmark publication runner contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks import run_publish

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"


def _raw(lib: str, sample: float) -> dict:
    stats = {
        "mean_ms": sample,
        "p50_ms": sample + 1,
        "p95_ms": sample + 2,
        "min_ms": sample - 1,
        "stddev_ms": sample / 10,
        "iterations": 100,
    }
    ops = {}
    for operation, queries in run_publish.EXPECTED_SQL[lib].items():
        ops[operation] = {**stats, "sql_queries": queries}
    return {
        "lib": lib,
        "versions": run_publish.EXPECTED_VERSIONS[lib],
        "python": "3.12.11",
        "django": "6.0.6",
        "machine": {"platform": "test", "cpu_count": 1},
        "dataset": {"authors": 1000, "posts_per_author": 10, "comments_per_post": 5},
        "provenance": {"commit": "abc", "constraints_sha256": "def"},
        "schema_import_ms": sample,
        "schema_rebuild_samples_ms": [sample, sample + 1],
        "surface": run_publish.EXPECTED_SURFACE,
        "ops": ops,
    }


def _datasets() -> dict:
    datasets = {
        prefix: {
            lib: [_raw(lib, value) for value in (3.0, 1.0, 2.0)]
            for lib in run_publish.LIBRARIES
        }
        for prefix in ("", "2x_")
    }
    for run in datasets["2x_"].values():
        for artifact in run:
            artifact["dataset"]["authors"] = 2000
    return datasets


def test_aggregate_uses_medians_and_preserves_exact_invariants() -> None:
    """Aggregate timing medians without weakening stable invariants.

    This protects the canonical aggregation contract.
    """
    runs = [_raw("graphex", value) for value in (3.0, 1.0, 2.0)]
    result = run_publish._aggregate_runs("graphex", runs, authors=1000)
    assert result["schema_import_ms"] == 2.0
    assert result["ops"]["flat_list"]["p50_ms"] == 3.0
    assert result["schema_rebuild_samples_ms"] == [2.0, 3.0]
    assert result["aggregation"]["runs"] == 3


def test_library_order_rotates_between_runs() -> None:
    """Rotate the first library between consecutive repetitions.

    This keeps execution-order bias balanced across runs.
    """
    assert run_publish._rotated_libraries(0) == run_publish.LIBRARIES
    assert run_publish._rotated_libraries(1)[0] == "graphene"
    assert run_publish._rotated_libraries(2)[0] == "strawberry"


def test_aggregate_rejects_sql_or_surface_drift() -> None:
    """Reject raw runs whose SQL contract drifts.

    This prevents invalid measurements from reaching canonical artifacts.
    """
    runs = [_raw("ariadne", value) for value in (1.0, 2.0, 3.0)]
    runs[2]["ops"]["nested"]["sql_queries"] += 1
    with pytest.raises(AssertionError, match="SQL contract"):
        run_publish._aggregate_runs("ariadne", runs, authors=1000)


def test_publication_is_all_or_nothing(tmp_path: Path) -> None:
    """Leave canonical files untouched when any raw run is invalid.

    Args:
        tmp_path: Temporary directory used for isolated artifacts.
    """
    results = tmp_path / "results"
    results.mkdir()
    sentinel = results / "graphex.json"
    sentinel.write_text("old")
    datasets = _datasets()
    datasets["2x_"]["strawberry"][1]["surface"] = {}

    with pytest.raises(AssertionError, match="surface contract"):
        run_publish._publish(datasets, results)

    assert sentinel.read_text() == "old"
    assert list(results.iterdir()) == [sentinel]


def test_publication_writes_all_eight_canonical_medians(tmp_path: Path) -> None:
    """Publish one validated median artifact per library and seed.

    Args:
        tmp_path: Temporary directory used for isolated artifacts.
    """
    results = tmp_path / "results"
    run_publish._publish(_datasets(), results)
    paths = sorted(path.name for path in results.iterdir())
    assert paths == sorted(
        f"{prefix}{lib}.json" for prefix in ("", "2x_") for lib in run_publish.LIBRARIES
    )
    assert (
        json.loads((results / "graphene.json").read_text())["aggregation"]["runs"] == 3
    )


def test_run_all_writes_only_ignored_scratch_results() -> None:
    """Keep the diagnostic runner away from canonical artifacts.

    This protects tracked results from accidental single-run replacement.
    """
    script = (BENCHMARKS / "run_all.sh").read_text()
    assert 'BENCH_OUTPUT_DIR="$HERE/scratch/run_all"' in script
    assert (
        "python benchmarks/run_publish.py --authors 1000 2000 --runs 3"
        in (BENCHMARKS / "README.md").read_text()
    )
