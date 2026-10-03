"""Contracts for staging new named-profile comparison artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmarks import comparison_publish, run_comparison
from benchmarks.comparison_batch import LIBRARIES, BatchGroup, BatchResult
from benchmarks.comparison_publish import DispatchReceipt, publish_core33
from benchmarks.comparison_statistics import aggregate_three
from benchmarks.run_publish import (
    EXPECTED_SQL,
    EXPECTED_SURFACE,
    EXPECTED_VERSIONS,
    OPERATIONS,
)

ROTATIONS = (LIBRARIES, LIBRARIES[1:] + LIBRARIES[:1], LIBRARIES[2:] + LIBRARIES[:2])
PUBLIC_NAMES = {
    f"{prefix}{library}.json" for prefix in ("", "2x_") for library in LIBRARIES
}


def _raw(plan: run_comparison.RunPlan, offset: float) -> dict[str, Any]:
    """Build one validator-compatible synthetic diagnostic.

    Args:
        plan: Receipt plan containing private path markers.
        offset: Distinct synthetic timing offset.

    Returns:
        Raw result with a checked profile witness.
    """
    return {
        "lib": plan.library,
        "versions": {
            name: plan.source_version
            if name == "django-graphex"
            else plan.packages[name]
            for name in EXPECTED_VERSIONS[plan.library]
        },
        "python": plan.python_version,
        "django": plan.packages["django"],
        "machine": {"platform": "synthetic-host", "cpu_count": 4},
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
        "schema_import_ms": offset + 10,
        "schema_rebuild_samples_ms": [offset + index / 10 for index in range(5)],
        "surface": EXPECTED_SURFACE,
        "ops": {
            name: {
                "mean_ms": offset + 1,
                "p50_ms": offset + 0.8,
                "p95_ms": offset + 2,
                "min_ms": offset + 0.5,
                "stddev_ms": offset / 10,
                "iterations": 100,
                "sql_queries": EXPECTED_SQL[plan.library][name],
            }
            for name in OPERATIONS
        },
        "profile_witness": {
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
        },
    }


def _fixture(tmp_path: Path) -> tuple[BatchResult, tuple[DispatchReceipt, ...], Path]:
    """Make 24 distinct raw files and eight independently aggregated groups.

    Args:
        tmp_path: Private test-owned directory.

    Returns:
        Batch, ordered receipts, and existing publication parent.
    """
    rows: dict[tuple[int, str], list[tuple[run_comparison.RunPlan, Path, dict]]] = {
        (authors, library): [] for authors in (1000, 2000) for library in LIBRARIES
    }
    receipts: list[DispatchReceipt] = []
    for authors in (1000, 2000):
        for repetition, rotation in enumerate(ROTATIONS, 1):
            for library in rotation:
                directory = (
                    tmp_path / "private-raw" / f"seed-{authors}-r{repetition}-{library}"
                )
                directory.mkdir(parents=True)
                packages = run_comparison.load_profile(
                    "core33", library, run_comparison.BASE
                )["packages"]
                plan = run_comparison.RunPlan(
                    "core33",
                    library,
                    Path(f"/private/synthetic/{library}/bin/python"),
                    Path(f"/private/synthetic/seed-{authors}.sqlite3"),
                    directory,
                    authors,
                    "3.12.11",
                    "a" * 40,
                    "b" * 40,
                    "3.1.1",
                    Path(f"/private/hidden/{library}/backend.py"),
                    "c" * 64,
                    f"{LIBRARIES.index(library) + 3}" * 64,
                    packages,
                )
                raw = _raw(plan, (10.0, 1.0, 4.0)[repetition - 1])
                path = directory / f"{library}.json"
                data = (json.dumps(raw, sort_keys=True) + "\n").encode()
                path.write_bytes(data)
                receipts.append(
                    DispatchReceipt(
                        len(receipts) + 1, plan, path, hashlib.sha256(data).hexdigest()
                    )
                )
                rows[(authors, library)].append((plan, path, raw))
    groups = []
    for authors in (1000, 2000):
        for library in LIBRARIES:
            selected = rows[(authors, library)]
            groups.append(
                BatchGroup(
                    authors,
                    library,
                    ("e" if authors == 1000 else "f") * 64,
                    "1" * 40,
                    "2" * 40,
                    "a" * 40,
                    "b" * 40,
                    tuple(path for _, path, _ in selected),
                    aggregate_three(selected[0][0], [raw for _, _, raw in selected]),
                )
            )
    parent = tmp_path / "results"
    parent.mkdir()
    batch = BatchResult(tuple(groups), tuple(item.raw_path for item in receipts))
    return batch, tuple(receipts), parent


def test_publisher_installs_exact_portable_eight_file_bundle(tmp_path: Path) -> None:
    """Project medians without exposing local witness paths or old artifacts.

    Args:
        tmp_path: Private fixture directory.
    """
    batch, receipts, parent = _fixture(tmp_path)
    legacy = parent / "graphex.json"
    legacy.write_bytes(b"historical sentinel")
    target = publish_core33(batch, receipts, parent)
    assert target == parent / "core33"
    assert {path.name for path in target.iterdir()} == PUBLIC_NAMES
    assert legacy.read_bytes() == b"historical sentinel"
    for name in PUBLIC_NAMES:
        artifact = json.loads((target / name).read_text())
        assert set(artifact) == {
            "schema",
            "profile",
            "library",
            "dataset",
            "whole_stack",
            "machine",
            "surface",
            "operations",
            "schema_import_ms",
            "schema_rebuild_diagnostic_ms",
            "aggregation",
            "measurement_source",
            "seed_source",
            "raw_sha256",
        }
        assert artifact["schema"] == "django-graphex.core33.comparison.v1"
        assert artifact["profile"] == "core33"
        assert artifact["measurement_source"]["version"] == "3.1.1"
        assert artifact["aggregation"]["runs"] == 3
        assert len(artifact["raw_sha256"]) == 3
        assert artifact["operations"]["nested"]["p95_ms"] == 6.0
        assert artifact["schema_rebuild_diagnostic_ms"][0] == 4.0
        content = (target / name).read_text()
        for private in (
            str(tmp_path),
            "/private/",
            "backend_path",
            "schema_path",
            "database",
        ):
            assert private not in content


@pytest.mark.parametrize(
    "case",
    (
        "missing",
        "duplicate_number",
        "wrong_order",
        "wrong_batch_order",
        "wrong_group_paths",
        "wrong_median",
        "wrong_seed",
        "wrong_source",
        "wrong_freeze",
        "wrong_version",
        "wrong_machine",
        "wrong_surface",
        "wrong_sql",
        "nonfinite",
        "bad_digest",
        "changed_raw",
    ),
)
def test_publisher_rejects_drift_before_staging(tmp_path: Path, case: str) -> None:
    """Refuse incomplete or drifted inputs without a public or stage name.

    Args:
        tmp_path: Private fixture directory.
        case: One incompatible receipt or raw-result mutation.
    """
    batch, original, parent = _fixture(tmp_path)
    receipts = list(original)
    if case == "missing":
        receipts.pop()
    elif case == "duplicate_number":
        receipts[1] = replace(receipts[1], number=1)
    elif case == "wrong_order":
        receipts[0], receipts[1] = receipts[1], receipts[0]
    elif case == "wrong_batch_order":
        batch = replace(batch, dispatch_order=batch.dispatch_order[::-1])
    elif case == "wrong_group_paths":
        batch = replace(
            batch,
            groups=(
                replace(batch.groups[0], raw_paths=batch.groups[1].raw_paths),
                *batch.groups[1:],
            ),
        )
    elif case == "wrong_median":
        bad = json.loads(json.dumps(batch.groups[0].median))
        bad["ops"]["nested"]["p95_ms"] += 1
        batch = replace(
            batch, groups=(replace(batch.groups[0], median=bad), *batch.groups[1:])
        )
    elif case == "wrong_seed":
        batch = replace(
            batch,
            groups=(replace(batch.groups[0], seed_sha256="0" * 64), *batch.groups[1:]),
        )
    elif case in {"wrong_source", "wrong_freeze"}:
        field = "commit" if case == "wrong_source" else "constraints_sha256"
        changed = replace(
            receipts[0].plan, **{field: "0" * (40 if field == "commit" else 64)}
        )
        receipts[0] = replace(receipts[0], plan=changed)
    elif case == "bad_digest":
        receipts[0] = replace(receipts[0], sha256="0" * 64)
    else:
        path = receipts[0].raw_path
        raw = json.loads(path.read_text())
        if case == "changed_raw":
            raw["schema_import_ms"] += 1
            path.write_text(json.dumps(raw) + "\n")
        else:
            if case == "wrong_version":
                raw["versions"]["graphql-core"] = "999"
            elif case == "wrong_machine":
                raw["machine"]["platform"] = "/private/host-secret"
            elif case == "wrong_surface":
                raw["surface"]["Author"].append("privateField")
            elif case == "wrong_sql":
                raw["ops"]["nested"]["sql_queries"] += 1
            elif case == "nonfinite":
                raw["ops"]["nested"]["mean_ms"] = float("nan")
            data = (json.dumps(raw) + "\n").encode()
            path.write_bytes(data)
            receipts[0] = replace(receipts[0], sha256=hashlib.sha256(data).hexdigest())
    with pytest.raises((ValueError, OSError)):
        publish_core33(batch, tuple(receipts), parent)
    assert not (parent / "core33").exists()
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("occupied", ("directory", "file", "symlink", "dangling"))
def test_publisher_preserves_occupied_target(tmp_path: Path, occupied: str) -> None:
    """Never replace a foreign target or remove its sentinel.

    Args:
        tmp_path: Private fixture directory.
        occupied: Foreign target shape.
    """
    batch, receipts, parent = _fixture(tmp_path)
    target = parent / "core33"
    sentinel = tmp_path / "foreign-sentinel"
    sentinel.write_bytes(b"foreign")
    if occupied == "directory":
        target.mkdir()
        (target / "sentinel").write_bytes(b"foreign")
    elif occupied == "file":
        target.write_bytes(b"foreign")
    else:
        target.symlink_to(sentinel if occupied == "symlink" else tmp_path / "missing")
    with pytest.raises((ValueError, OSError)):
        publish_core33(batch, receipts, parent)
    assert sentinel.read_bytes() == b"foreign"
    assert (
        target.is_symlink() if occupied in ("symlink", "dangling") else target.exists()
    )
    assert not list(parent.glob(".core33-stage-*"))


def test_publisher_retains_stage_after_atomic_install_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep a recoverable stage instead of a partial public bundle.

    Args:
        tmp_path: Private fixture directory.
        monkeypatch: Atomic-install failure injector.

    Raises:
        AssertionError: If the failed install loses the recoverable stage.
    """
    batch, receipts, parent = _fixture(tmp_path)

    def refuse_install(source: Path, destination: Path) -> None:
        """Simulate an atomic no-clobber refusal.

        Args:
            source: Unmodified staged directory.
            destination: Unmodified public target.

        Raises:
            OSError: Always, without changing either path.
        """
        raise OSError("simulated no-clobber refusal")

    monkeypatch.setattr(comparison_publish, "_rename_noreplace", refuse_install)
    with pytest.raises(OSError, match="simulated no-clobber refusal"):
        publish_core33(batch, receipts, parent)
    assert not (parent / "core33").exists()
    stages = list(parent.glob(".core33-stage-*"))
    assert len(stages) == 1
    assert {item.name for item in stages[0].iterdir()} == PUBLIC_NAMES


def test_publisher_rejects_nonregular_raw_without_public_write(tmp_path: Path) -> None:
    """Reject a foreign symlink replacing a receipt-bound raw file.

    Args:
        tmp_path: Private fixture directory.
    """
    batch, receipts, parent = _fixture(tmp_path)
    first = receipts[0].raw_path
    data = first.read_bytes()
    first.unlink()
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(data)
    first.symlink_to(foreign)
    with pytest.raises((ValueError, OSError)):
        publish_core33(batch, receipts, parent)
    assert foreign.read_bytes() == data
    assert not (parent / "core33").exists()


def test_publisher_rejects_stage_replacement_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not install a foreign directory substituted after stage validation.

    Args:
        tmp_path: Private fixture directory.
        monkeypatch: One-shot substitution at the final raw-byte check.
    """
    batch, receipts, parent = _fixture(tmp_path)
    original_digest = comparison_publish._digest_regular
    substituted = False

    def replace_stage(path: Path) -> str:
        """Substitute a foreign stage once, without changing the raw result.

        Args:
            path: Raw path being checked again.

        Returns:
            Original raw digest.
        """
        nonlocal substituted
        if not substituted:
            substituted = True
            stage = next(parent.glob(".core33-stage-*"))
            stage.rename(parent / "original-stage")
            stage.mkdir()
            (stage / "foreign-sentinel").write_bytes(b"foreign")
        return original_digest(path)

    monkeypatch.setattr(comparison_publish, "_digest_regular", replace_stage)
    with pytest.raises(ValueError, match="staged bundle changed"):
        publish_core33(batch, receipts, parent)
    assert not (parent / "core33").exists()
    assert (parent / "original-stage").is_dir()
    assert (
        next(parent.glob(".core33-stage-*")) / "foreign-sentinel"
    ).read_bytes() == b"foreign"


def test_publisher_documents_preacquisition_directory_limit() -> None:
    """Keep the first-acquisition ownership boundary explicit for callers.

    This assertion prevents a future guide or API simplification from claiming
    that an acquired stage descriptor proves creation ownership.
    """
    guide = " ".join((run_comparison.BASE / "README.md").read_text().split())
    api_doc = " ".join((publish_core33.__doc__ or "").split())
    assert "before the first staging descriptor is acquired" in guide
    assert "foreign directory can receive all eight exclusive files" in guide
    assert "first acquired descriptor" in api_doc
    assert "does not prove creator ownership" in api_doc


def test_publisher_rejects_explicit_receipts_that_contradict_live_batch(
    tmp_path: Path,
) -> None:
    """Do not publish when a newer batch embeds different live receipts.

    Args:
        tmp_path: Private synthetic raw and public fixture roots.

    Raises:
        AssertionError: If contradictory receipt witnesses stage an artifact.
    """
    batch, receipts, parent = _fixture(tmp_path)
    live = replace(batch, receipts=receipts)
    wrong = (replace(receipts[0], sha256="0" * 64), *receipts[1:])
    with pytest.raises(ValueError, match="explicit receipts differ"):
        publish_core33(live, wrong, parent)
    assert not (parent / "core33").exists()
    assert not list(parent.glob(".core33-stage-*"))
