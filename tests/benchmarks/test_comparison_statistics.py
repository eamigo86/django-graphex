"""Contracts for pure median aggregation of named-profile diagnostic runs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from benchmarks import run_comparison
from benchmarks.comparison_statistics import aggregate_three
from benchmarks.run_publish import (
    EXPECTED_SQL,
    EXPECTED_SURFACE,
    EXPECTED_VERSIONS,
    OPERATIONS,
)


def _plan(library: str, authors: int) -> run_comparison.RunPlan:
    """Build one synthetic identity using the committed direct profile pins.

    Args:
        library: Named comparison library.
        authors: Synthetic prepared seed size.

    Returns:
        Immutable plan for dictionary-only validation.
    """
    packages = run_comparison.load_profile("core33", library, run_comparison.BASE)[
        "packages"
    ]
    return run_comparison.RunPlan(
        profile="core33",
        library=library,
        python=Path("/synthetic/python"),
        database=Path("/synthetic/seed.sqlite3"),
        output_root=Path("/synthetic/output"),
        authors=authors,
        python_version="3.12.11",
        commit="a" * 40,
        tree="b" * 40,
        source_version="3.1.1",
        backend_path=Path(f"/synthetic/{library}/backend.py"),
        manifest_sha256="c" * 64,
        constraints_sha256="d" * 64,
        packages=packages,
    )


def _raw_run(plan: run_comparison.RunPlan, offset: int) -> dict[str, Any]:
    """Build a synthetic measured shape accepted by shared validation.

    Args:
        plan: Exact expected profile identity.
        offset: Distinct synthetic timing offset.

    Returns:
        Raw-shaped result with no aggregation metadata.
    """
    versions = {
        name: plan.source_version if name == "django-graphex" else plan.packages[name]
        for name in EXPECTED_VERSIONS[plan.library]
    }
    witness = {
        "profile": plan.profile,
        "library": plan.library,
        "commit": plan.commit,
        "tree": plan.tree,
        "source_version": plan.source_version,
        "manifest_sha256": plan.manifest_sha256,
        "constraints_sha256": plan.constraints_sha256,
        "backend_path": str(plan.backend_path),
        "schema_path": str(
            run_comparison.BASE / "libs" / plan.library / "bench_schema.py"
        ),
        "python": plan.python_version,
        "django": plan.packages["django"],
        "graphql-core": plan.packages["graphql-core"],
    }
    operations = {
        name: {
            "mean_ms": offset + 1.0,
            "p50_ms": offset + 0.8,
            "p95_ms": offset + 2.0,
            "min_ms": offset + 0.5,
            "stddev_ms": offset / 10,
            "iterations": 100,
            "sql_queries": EXPECTED_SQL[plan.library][name],
        }
        for name in OPERATIONS
    }
    return {
        "lib": plan.library,
        "versions": versions,
        "python": plan.python_version,
        "django": plan.packages["django"],
        "machine": {"platform": "synthetic", "cpu_count": 1},
        "dataset": {
            "authors": plan.authors,
            "posts_per_author": 10,
            "comments_per_post": 5,
        },
        "provenance": {
            "commit": plan.commit,
            "tree": plan.tree,
            "constraints_sha256": plan.constraints_sha256,
        },
        "schema_import_ms": offset + 10.0,
        "schema_rebuild_samples_ms": [offset + index / 10 for index in range(5)],
        "surface": deepcopy(EXPECTED_SURFACE),
        "ops": operations,
        "profile_witness": witness,
    }


@pytest.mark.parametrize("library", ("graphex", "graphene", "strawberry", "ariadne"))
@pytest.mark.parametrize("authors", (1000, 2000))
def test_three_run_median_uses_each_validated_profile_statistic(
    library: str, authors: int
) -> None:
    """Use the middle observation, not the first run or an average.

    Args:
        library: Named comparison stack.
        authors: Synthetic seed cardinality.
    """
    plan = _plan(library, authors)
    runs = [_raw_run(plan, offset) for offset in (1, 9, 3)]
    result = aggregate_three(plan, runs)

    assert result["schema_import_ms"] == 13.0
    assert result["schema_rebuild_samples_ms"] == [3.0, 3.1, 3.2, 3.3, 3.4]
    for name in OPERATIONS:
        assert result["ops"][name]["p95_ms"] == 5.0
        assert result["ops"][name]["sql_queries"] == EXPECTED_SQL[library][name]
        assert result["ops"][name]["iterations"] == 100
    assert result["aggregation"]["runs"] == 3
    assert "per-run p95" in result["aggregation"]["ops"]
    assert "per-position median" in result["aggregation"]["schema_rebuild_samples_ms"]
    assert result["profile_witness"] == runs[0]["profile_witness"]


@pytest.mark.parametrize("count", (0, 1, 2, 4))
def test_three_run_median_requires_exactly_three_raw_runs(count: int) -> None:
    """Reject incomplete or padded groups rather than publish a false median.

    Args:
        count: Number of synthetic raw results supplied.
    """
    plan = _plan("graphex", 1000)
    with pytest.raises(ValueError, match="exactly three"):
        aggregate_three(plan, [_raw_run(plan, offset) for offset in range(count)])


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("lib", "graphene"),
        ("dataset", {"authors": 2000, "posts_per_author": 10, "comments_per_post": 5}),
        ("provenance", {"commit": "other", "tree": "other"}),
        ("surface", {}),
    ),
)
def test_three_run_median_rejects_mixed_raw_identity(
    field: str, replacement: object
) -> None:
    """Apply the shared witness and workload contract to every run.

    Args:
        field: Raw result field changed in only the middle run.
        replacement: Incompatible field value.
    """
    plan = _plan("graphex", 1000)
    runs = [_raw_run(plan, offset) for offset in (1, 9, 3)]
    runs[1][field] = replacement
    with pytest.raises(ValueError):
        aggregate_three(plan, runs)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("profile", "other"),
        ("commit", "other"),
        ("tree", "other"),
        ("source_version", "4.0.0"),
        ("manifest_sha256", "other"),
        ("constraints_sha256", "other"),
        ("backend_path", "/other/backend.py"),
        ("graphql-core", "3.2.13"),
    ),
)
def test_three_run_median_rejects_mixed_profile_witness(
    field: str, replacement: str
) -> None:
    """Refuse a run from another exact profile or source snapshot.

    Args:
        field: Profile witness field changed in one run.
        replacement: Incompatible witness value.
    """
    plan = _plan("graphex", 1000)
    runs = [_raw_run(plan, offset) for offset in (1, 9, 3)]
    runs[1]["profile_witness"][field] = replacement
    with pytest.raises(ValueError):
        aggregate_three(plan, runs)


def test_three_run_median_rejects_sql_and_nonfinite_timing() -> None:
    """Keep the existing per-run SQL and finite-timing gates.

    A middle run cannot hide invalid measurements behind valid neighbors.
    """
    plan = _plan("graphex", 1000)
    runs = [_raw_run(plan, offset) for offset in (1, 9, 3)]
    runs[1]["ops"]["nested"]["sql_queries"] += 1
    with pytest.raises(ValueError):
        aggregate_three(plan, runs)
    runs[1]["ops"]["nested"]["sql_queries"] -= 1
    runs[2]["ops"]["nested"]["p95_ms"] = float("nan")
    with pytest.raises(ValueError):
        aggregate_three(plan, runs)


def test_three_run_median_rejects_machine_drift_and_aggregated_inputs() -> None:
    """Do not conflate different hosts or reaggregate a derived result.

    Only raw results from one stable machine enter this helper.
    """
    plan = _plan("graphex", 1000)
    runs = [_raw_run(plan, offset) for offset in (1, 9, 3)]
    runs[1]["machine"]["cpu_count"] = 2
    with pytest.raises(ValueError, match="machine"):
        aggregate_three(plan, runs)
    runs[1]["machine"]["cpu_count"] = 1
    runs[1]["aggregation"] = {"runs": 3}
    with pytest.raises(ValueError, match="raw"):
        aggregate_three(plan, runs)


def test_three_run_median_detaches_output_and_keeps_raw_runs() -> None:
    """Return an independent result without changing the observations.

    Callers retain all three raw results for later provenance inspection.
    """
    plan = _plan("graphex", 1000)
    runs = [_raw_run(plan, offset) for offset in (1, 9, 3)]
    original = deepcopy(runs)
    result = aggregate_three(plan, runs)
    result["profile_witness"]["commit"] = "changed"
    result["ops"]["nested"]["p95_ms"] = 999.0
    result["schema_rebuild_samples_ms"][0] = 999.0
    assert runs == original


def test_three_run_median_calls_shared_validator_for_each_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the named-runner validator rather than a weaker duplicate gate.

    Args:
        monkeypatch: Replaces the validator with a counting wrapper.
    """
    plan = _plan("graphex", 1000)
    runs = [_raw_run(plan, offset) for offset in (1, 9, 3)]
    original = run_comparison.validate_result
    seen: list[int] = []

    def counting_validator(
        checked_plan: run_comparison.RunPlan, result: dict[str, Any]
    ) -> None:
        """Count each call while preserving the real validation behavior."""
        seen.append(id(result))
        original(checked_plan, result)

    monkeypatch.setattr(run_comparison, "validate_result", counting_validator)
    aggregate_three(plan, runs)
    assert seen == [id(result) for result in runs]
