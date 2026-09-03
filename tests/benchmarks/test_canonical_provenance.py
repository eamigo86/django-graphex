"""Contracts for tracked canonical benchmark provenance."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks import run_publish

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"
RESULTS = BENCHMARKS / "results"
DELIVERY_BASE = "4d595f1c4822d37a520a188892a943caa744f2ea"


def _copy_canonical(tmp_path: Path) -> tuple[Path, Path]:
    results = tmp_path / "results"
    shutil.copytree(RESULTS, results)
    constraints = tmp_path / "constraints.txt"
    shutil.copy2(BENCHMARKS / "constraints.txt", constraints)
    return results, constraints


def _rewrite_all(results: Path, field: str, value: str) -> None:
    for path in results.glob("*.json"):
        artifact = json.loads(path.read_text())
        artifact["provenance"][field] = value
        path.write_text(json.dumps(artifact))


def test_tracked_canonical_results_pass_the_full_contract() -> None:
    """Accept all eight tracked artifacts under the current contract.

    This exercises real full-history ancestry in the repository checkout.
    """
    run_publish.validate_canonical_results()


def test_validator_resolves_only_the_public_delivery_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve only the public coordinate available from the remote history.

    Args:
        monkeypatch: Pytest helper used to record subprocess calls.
    """
    calls = []

    def _successful_git(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_publish.subprocess, "run", _successful_git)
    run_publish.validate_canonical_results()

    assert calls == [
        ["git", "cat-file", "-e", f"{DELIVERY_BASE}^{{commit}}"],
        ["git", "merge-base", "--is-ancestor", DELIVERY_BASE, "HEAD"],
    ]
    measured = json.loads((RESULTS / "graphex.json").read_text())["provenance"]
    assert measured["commit"] not in repr(calls)
    assert measured["measurement_tree"] not in repr(calls)


@pytest.mark.parametrize(
    ("failed_check", "message"),
    ((0, "does not exist"), (1, "is not an ancestor of HEAD")),
)
def test_canonical_results_require_reachable_delivery_ancestry(
    monkeypatch: pytest.MonkeyPatch, failed_check: int, message: str
) -> None:
    """Reject an unavailable or unrelated public delivery base.

    Args:
        monkeypatch: Pytest helper used to replace Git commands.
        failed_check: Zero-based Git check that must fail.
        message: Expected explanation for the failure.
    """
    calls = []

    def _selective_git(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=int(len(calls) - 1 == failed_check))

    monkeypatch.setattr(run_publish.subprocess, "run", _selective_git)
    with pytest.raises(AssertionError, match=message):
        run_publish.validate_canonical_results()


@pytest.mark.parametrize(
    "field", ("commit", "measurement_tree", "constraints_sha256", "delivery_base_commit")
)
def test_canonical_results_reject_provenance_drift(tmp_path: Path, field: str) -> None:
    """Reject one artifact whose provenance differs from its peers.

    Args:
        tmp_path: Isolated canonical artifact directory.
        field: Provenance field to make inconsistent.
    """
    results, constraints = _copy_canonical(tmp_path)
    path = results / "graphex.json"
    artifact = json.loads(path.read_text())
    artifact["provenance"][field] = "0" * len(artifact["provenance"][field])
    path.write_text(json.dumps(artifact))

    with pytest.raises(AssertionError, match="one provenance"):
        run_publish.validate_canonical_results(results, constraints_path=constraints)


@pytest.mark.parametrize(
    "field", ("commit", "measurement_tree", "constraints_sha256", "delivery_base_commit")
)
def test_canonical_results_require_full_lowercase_shas(
    tmp_path: Path, field: str
) -> None:
    """Reject abbreviated or otherwise malformed provenance coordinates.

    Args:
        tmp_path: Isolated canonical artifact directory.
        field: Provenance field to abbreviate.
    """
    results, constraints = _copy_canonical(tmp_path)
    _rewrite_all(results, field, "abc123")

    with pytest.raises(AssertionError, match=rf"{field} must be a full"):
        run_publish.validate_canonical_results(results, constraints_path=constraints)


def test_canonical_results_match_constraints_and_public_delivery_base(
    tmp_path: Path,
) -> None:
    """Bind provenance to the tracked freeze and approved delivery base.

    Args:
        tmp_path: Isolated canonical artifact directories.
    """
    results, constraints = _copy_canonical(tmp_path)
    _rewrite_all(results, "constraints_sha256", "0" * 64)
    with pytest.raises(AssertionError, match="constraints digest"):
        run_publish.validate_canonical_results(results, constraints_path=constraints)

    results, constraints = _copy_canonical(tmp_path / "delivery")
    _rewrite_all(results, "delivery_base_commit", "a" * 40)
    with pytest.raises(AssertionError, match="public delivery base"):
        run_publish.validate_canonical_results(results, constraints_path=constraints)


@pytest.mark.parametrize("drift", ("surface", "sql", "cardinality", "aggregation"))
def test_canonical_results_reject_current_contract_drift(
    tmp_path: Path, drift: str
) -> None:
    """Apply surface, SQL, cardinality and aggregation checks to medians.

    Args:
        tmp_path: Isolated canonical artifact directory.
        drift: Current artifact contract dimension to corrupt.
    """
    results, constraints = _copy_canonical(tmp_path)
    path = results / "graphex.json"
    artifact = json.loads(path.read_text())
    if drift == "surface":
        artifact["surface"] = {}
    elif drift == "sql":
        artifact["ops"]["nested"]["sql_queries"] += 1
    elif drift == "cardinality":
        artifact["dataset"]["comments_per_post"] = 4
    else:
        artifact["aggregation"]["runs"] = 1
    path.write_text(json.dumps(artifact))

    with pytest.raises(AssertionError, match="contract|aggregation"):
        run_publish.validate_canonical_results(results, constraints_path=constraints)


def test_canonical_results_require_exactly_eight_artifacts(tmp_path: Path) -> None:
    """Reject incomplete canonical result sets.

    Args:
        tmp_path: Isolated canonical artifact directory.
    """
    results, constraints = _copy_canonical(tmp_path)
    (results / "ariadne.json").unlink()

    with pytest.raises(AssertionError, match="exactly eight"):
        run_publish.validate_canonical_results(results, constraints_path=constraints)


@pytest.mark.parametrize(
    ("job", "next_job"),
    (
        ("test", "base-install"),
        ("base-install", "lint-and-security"),
        ("coverage", "postgresql"),
    ),
)
def test_suite_checkouts_provide_full_history_for_ancestry_check(
    job: str, next_job: str
) -> None:
    """Require full Git history wherever the benchmark tests execute.

    The canonical validator must be able to prove delivery-base ancestry.

    Args:
        job: Workflow job that executes the benchmark contracts.
        next_job: Following job used to bound the workflow slice.
    """
    workflow = (REPO_ROOT / ".github/workflows/cicd.yaml").read_text()
    suite_job = workflow.split(f"  {job}:\n", 1)[1].split(
        f"\n  {next_job}:", 1
    )[0]
    assert "fetch-depth: 0" in suite_job
