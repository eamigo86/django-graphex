"""Benchmark publication runner contract tests."""

from __future__ import annotations

import json
import re
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


def _canonical_results(prefix: str) -> dict[str, dict]:
    return {
        lib: json.loads((BENCHMARKS / "results" / f"{prefix}{lib}.json").read_text())
        for lib in run_publish.LIBRARIES
    }


def _markdown_row(document: str, label: str) -> list[str]:
    line = next(line for line in document.splitlines() if line.startswith(label))
    return [cell.strip() for cell in line.strip("|").split("|")]


def test_published_documentation_is_derived_from_canonical_artifacts() -> None:
    """Verify published documentation is derived from canonical artifacts.

    This test protects the corresponding regression contract.
    """
    why = (REPO_ROOT / "docs" / "why.md").read_text()
    readme = (BENCHMARKS / "README.md").read_text()
    one_x = _canonical_results("")
    two_x = _canonical_results("2x_")

    labels = {
        "flat_list": "| **flat_list**",
        "nested": "| **nested**",
        "single": "| **single**",
        "filtered": "| **filtered**",
        "create_comment": "| **create_comment**",
    }
    for operation, label in labels.items():
        cells = _markdown_row(why, label)[1:]
        for lib, cell in zip(run_publish.LIBRARIES, cells, strict=True):
            stats = two_x[lib]["ops"][operation]
            assert f"{stats['p50_ms']:.2f} ms" in cell
            assert re.search(rf"\b{stats['sql_queries']} SQL\b", cell)

    imports_2x = _markdown_row(why, "| **Cold import**")[1:]
    imports_1x = _markdown_row(why, "| *…at the 1,000-author seed*")[1:]
    for lib, cell_2x, cell_1x in zip(
        run_publish.LIBRARIES, imports_2x, imports_1x, strict=True
    ):
        assert f"{two_x[lib]['schema_import_ms']:.2f} ms" in cell_2x
        assert f"{one_x[lib]['schema_import_ms']:.2f} ms" in cell_1x

    graphex_version = two_x["graphex"]["versions"]["django-graphex"]
    dataset = two_x["graphex"]["dataset"]
    comments = (
        dataset["authors"]
        * dataset["posts_per_author"]
        * dataset["comments_per_post"]
    )
    assert f"django-graphex **{graphex_version}**" in why
    assert f"{comments:,} comments" in why
    assert "4 request-internal SQL statements" in readme
    assert "`scratch/<lib>.json` by default" in readme
    command = "python benchmarks/run_publish.py --authors 1000 2000 --runs 3"
    assert command in why
    assert command in readme

    # Neither public page may imply a timing gate that the publisher does not
    # implement. Both pages also distinguish measured state from delivery state.
    for document in (why, readme):
        normalized = " ".join(document.split()).replace("**", "")
        assert "latencies rise uniformly across all four libraries" not in normalized
        assert "does not reject a run because its timing is slower" in normalized
        assert "actual local commit and tree" in normalized
        assert "only the public ancestor" in normalized
        assert re.search(
            r"(?:does not .*claim|nor claim) byte, tree or semantic equivalence",
            normalized,
        )

    normalized_why = " ".join(why.split()).replace("**", "")
    cold_import_spreads = []
    for artifacts in (one_x, two_x):
        for artifact in artifacts.values():
            samples = artifact["aggregation"]["schema_import_ms"]["samples"]
            spread = (max(samples) - min(samples)) / artifact["schema_import_ms"]
            cold_import_spreads.append(spread * 100)
    assert (
        f"{min(cold_import_spreads):.0f}–{max(cold_import_spreads):.0f} %"
        in normalized_why
    )

    for lib in ("graphex", "graphene"):
        one_x_filtered = one_x[lib]["ops"]["filtered"]["p50_ms"]
        two_x_filtered = two_x[lib]["ops"]["filtered"]["p50_ms"]
        assert (
            f"{one_x_filtered:.2f} ms → {two_x_filtered:.2f} ms" in normalized_why
        )

    # Every displayed cold-import result comes directly from one of the eight
    # canonical median artifacts.
    labels = {
        "graphex": "django-graphex",
        "graphene": "graphene-django",
        "strawberry": "strawberry",
        "ariadne": "ariadne",
    }
    for lib, label in labels.items():
        row = _markdown_row(readme, f"| {label} |")
        assert row[1:] == [
            f"{one_x[lib]['schema_import_ms']:.2f} ms",
            f"{two_x[lib]['schema_import_ms']:.2f} ms",
        ]

    assert "reference implementation (django-graphex 3.1)" in readme
