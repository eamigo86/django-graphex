"""Pure profile-aware statistics for three validated diagnostic runs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any, Sequence

from benchmarks import run_comparison
from benchmarks.run_publish import METRICS, OPERATIONS


def aggregate_three(
    plan: run_comparison.RunPlan,
    runs: Sequence[dict[str, Any]],
    schema_base: Path | None = None,
) -> dict[str, Any]:
    """Return detached per-statistic medians for one exact named profile.

    Schema rebuild values are medians at each diagnostic position, not a raw
    rebuild series. The per-run p95 median is not a pooled 300-sample p95.
    Input results remain owned by the caller for separate raw preservation.

    Args:
        plan: Prepared source, seed, and whole-stack profile identity.
        runs: Exactly three raw results from independent dispatches.
        schema_base: Explicit recorded benchmark directory for replay.

    Returns:
        A detached result containing explicit aggregation metadata.

    Raises:
        ValueError: If count, validation, host, or raw-result identity differs.
    """
    if len(runs) != 3:
        raise ValueError("exactly three raw results are required")
    for run in runs:
        if "aggregation" in run:
            raise ValueError("only raw results may be aggregated")
        if schema_base is None:
            run_comparison.validate_result(plan, run)
        else:
            run_comparison.validate_result(plan, run, schema_base)
    if any(run["machine"] != runs[0]["machine"] for run in runs[1:]):
        raise ValueError("measured machine differs between runs")
    expected_stats = {*METRICS, "iterations", "sql_queries"}
    if any(
        set(run["ops"][name]) != expected_stats for run in runs for name in OPERATIONS
    ):
        raise ValueError("measured operation fields differ from the raw contract")

    result = deepcopy(runs[0])
    result["schema_import_ms"] = median(run["schema_import_ms"] for run in runs)
    result["schema_rebuild_samples_ms"] = [
        median(run["schema_rebuild_samples_ms"][index] for run in runs)
        for index in range(5)
    ]
    for name in OPERATIONS:
        for metric in METRICS:
            result["ops"][name][metric] = median(
                run["ops"][name][metric] for run in runs
            )
    result["aggregation"] = {
        "runs": 3,
        "method": "per-statistic median of three validated raw runs",
        "ops": "median of each per-run statistic; per-run p95 is not pooled p95",
        "schema_rebuild_samples_ms": (
            "per-position median of five diagnostic rebuild samples; "
            "not a raw run series"
        ),
    }
    return result
