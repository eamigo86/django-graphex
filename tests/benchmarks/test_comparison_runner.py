"""Contracts for the isolated named-profile single-run entrypoint."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks import run_comparison
from benchmarks.run_publish import (
    EXPECTED_SQL,
    EXPECTED_SURFACE,
    EXPECTED_VERSIONS,
    OPERATIONS,
)


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create disposable profile inputs without installing dependencies.

    Args:
        tmp_path: Temporary root supplied by pytest.
        monkeypatch: Fixture used to replace external observations.

    Returns:
        Benchmark directory and disposable virtualenv root.
    """
    root = tmp_path / "source"
    bench = root / "benchmarks"
    bench.mkdir(parents=True)
    original = Path(__file__).resolve().parents[2] / "benchmarks"
    shutil.copytree(original / "comparison_profiles", bench / "comparison_profiles")
    (root / "django_graphex").mkdir()
    (root / "django_graphex/__init__.py").write_text("")
    (root / "pyproject.toml").write_text('[project]\nversion = "3.1.1"\n')
    venv_root = tmp_path / "venvs"
    python = venv_root / ".venv-core33-graphex/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    freeze = bench / "comparison_profiles/core33/constraints/graphex.txt"
    (python.parent.parent / ".freeze.txt").write_bytes(freeze.read_bytes())
    database = tmp_path / "seed.sqlite3"
    database.touch()
    monkeypatch.setattr(run_comparison, "ROOT", root)
    monkeypatch.setattr(run_comparison, "BASE", bench)
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: ("a" * 40, "b" * 40))
    monkeypatch.setattr(run_comparison, "_check_database", lambda *_: None)
    monkeypatch.setattr(
        run_comparison, "_installed_freeze", lambda *_: freeze.read_text()
    )
    monkeypatch.setattr(
        run_comparison,
        "_runtime_probe",
        lambda *_: {
            "python": "3.12.11",
            "django": "6.0.8",
            "graphql-core": "3.3.0",
            "backend_path": str(root / "django_graphex/__init__.py"),
        },
    )
    return bench, venv_root


def test_preflight_rejects_invalid_requests_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject unknown selectors and occupied or repository-owned outputs.

    Args:
        tmp_path: Disposable profile workspace.
        monkeypatch: Fixture used to isolate external observations.
    """
    bench, venv_root = _workspace(tmp_path, monkeypatch)
    database = tmp_path / "seed.sqlite3"
    output = tmp_path / "new-result"
    dangling = tmp_path / "dangling-output"
    dangling.symlink_to(tmp_path / "absent")
    for profile, library, destination in (
        ("unknown", "graphex", output),
        ("core33", "unknown", output),
        ("core33", "graphex", bench / "results"),
        ("core33", "graphex", dangling),
    ):
        with pytest.raises(ValueError):
            run_comparison.prepare_run(
                profile, library, venv_root, database, destination, 1000
            )
    assert not output.exists()


def test_preflight_rejects_wrong_source_and_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require the active interpreter to import this clean source and freeze.

    Args:
        tmp_path: Disposable profile workspace.
        monkeypatch: Fixture used to isolate external observations.
    """
    bench, venv_root = _workspace(tmp_path, monkeypatch)
    database = tmp_path / "seed.sqlite3"
    output = tmp_path / "new-result"
    monkeypatch.setattr(
        run_comparison,
        "_runtime_probe",
        lambda *_: {
            "python": "3.12.11",
            "django": "6.0.8",
            "graphql-core": "3.3.0",
            "backend_path": "/wrong/source.py",
        },
    )
    with pytest.raises(ValueError, match="source"):
        run_comparison.prepare_run(
            "core33", "graphex", venv_root, database, output, 1000
        )
    assert not output.exists()
    (venv_root / ".venv-core33-graphex/.freeze.txt").write_text("wrong\n")
    with pytest.raises(ValueError, match="freeze"):
        run_comparison.prepare_run(
            "core33", "graphex", venv_root, database, output, 1000
        )


def test_preflight_rejects_runtime_drift_and_dirty_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse a mismatched runtime or an uncommitted source identity.

    Args:
        tmp_path: Disposable profile workspace.
        monkeypatch: Fixture used to isolate external observations.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    database = tmp_path / "seed.sqlite3"
    output = tmp_path / "new-result"
    monkeypatch.setattr(
        run_comparison,
        "_runtime_probe",
        lambda *_: {
            "python": "3.14.0",
            "django": "6.0.8",
            "graphql-core": "3.3.0",
            "backend_path": str(run_comparison.ROOT / "django_graphex/__init__.py"),
        },
    )
    with pytest.raises(ValueError, match="runtime"):
        run_comparison.prepare_run(
            "core33", "graphex", venv_root, database, output, 1000
        )
    monkeypatch.setattr(
        run_comparison,
        "_git_identity",
        lambda: (_ for _ in ()).throw(ValueError("dirty")),
    )
    with pytest.raises(ValueError, match="dirty"):
        run_comparison.prepare_run(
            "core33", "graphex", venv_root, database, output, 1000
        )
    assert not output.exists()


def test_preflight_reports_source_and_freeze_without_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report the checked source, profile, and selected freeze without effects.

    Args:
        tmp_path: Disposable profile workspace.
        monkeypatch: Fixture used to isolate external observations.
        capsys: Fixture capturing the diagnostic output.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "new-result"
    run_comparison.main(
        [
            "--profile",
            "core33",
            "--library",
            "graphex",
            "--venv-root",
            str(venv_root),
            "--database",
            str(tmp_path / "seed.sqlite3"),
            "--output-root",
            str(output),
            "--authors",
            "1000",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["commit"] == "a" * 40
    assert report["tree"] == "b" * 40
    assert report["source_version"] == "3.1.1"
    assert report["backend_path"] == str(
        run_comparison.ROOT / "django_graphex/__init__.py"
    )
    assert report["packages"]["graphql-core"] == "3.3.0"
    assert len(report["constraints_sha256"]) == 64
    assert not output.exists()


def test_seed_preflight_reads_without_resetting(tmp_path: Path) -> None:
    """Require the fixed workload post and retain the original database bytes.

    Args:
        tmp_path: Disposable database location.
    """
    database = tmp_path / "seed.sqlite3"
    with sqlite3.connect(database) as connection:
        for table in ("author", "post", "comment"):
            connection.execute(f"CREATE TABLE benchapp_{table} (id INTEGER)")
        connection.execute("INSERT INTO benchapp_author VALUES (1)")
        connection.executemany(
            "INSERT INTO benchapp_post VALUES (?)",
            [(5000,)] + [(i,) for i in range(1, 10)],
        )
        connection.executemany(
            "INSERT INTO benchapp_comment VALUES (?)", [(i,) for i in range(1, 51)]
        )
    before = database.read_bytes()
    run_comparison._check_database(database, 1)
    assert database.read_bytes() == before
    with pytest.raises(ValueError, match="seed"):
        run_comparison._check_database(database, 2)


def test_direct_cli_uses_its_sibling_profile_validator(tmp_path: Path) -> None:
    """Keep direct invocation independent of an ambient benchmark package.

    Args:
        tmp_path: Disposable decoy import directory.
    """
    decoy = tmp_path / "benchmarks"
    decoy.mkdir()
    (decoy / "__init__.py").touch()
    (decoy / "profile_bootstrap.py").write_text(
        'raise RuntimeError("decoy imported")\n'
    )
    environment = {"PATH": os.defpath, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(Path(run_comparison.__file__)), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--profile" in result.stdout


def _measured_result(plan: run_comparison.RunPlan) -> dict[str, object]:
    """Build a complete synthetic child result for validator controls.

    Args:
        plan: Prepared synthetic profile selection.

    Returns:
        Five-operation result bearing the expected child witness.
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
        "machine": {"platform": "test", "cpu_count": 1},
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
        "schema_import_ms": 1.0,
        "schema_rebuild_samples_ms": [1.0] * 5,
        "surface": EXPECTED_SURFACE,
        "ops": {
            name: {
                "sql_queries": EXPECTED_SQL[plan.library][name],
                "iterations": 100,
                "mean_ms": 1.0,
                "p50_ms": 1.0,
                "p95_ms": 1.0,
                "min_ms": 1.0,
                "stddev_ms": 0.0,
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


def test_result_validator_accepts_dynamic_source_version_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate a future source version without creating a diagnostic file.

    Args:
        tmp_path: Disposable profile and future checkout paths.
        monkeypatch: Fixture replacing external preflight observations.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    (run_comparison.ROOT / "pyproject.toml").write_text(
        '[project]\nversion = "4.0.0"\n'
    )
    output = tmp_path / "run"
    plan = run_comparison.prepare_run(
        "core33", "graphex", venv_root, tmp_path / "seed.sqlite3", output, 1000
    )
    run_comparison.validate_result(plan, _measured_result(plan))
    assert plan.source_version == "4.0.0"
    assert not output.exists()


@pytest.mark.parametrize("library", ["graphex", "graphene", "strawberry", "ariadne"])
def test_result_validator_accepts_each_disclosed_whole_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, library: str
) -> None:
    """Keep each peer's compatible GraphQL-core and package pins distinct.

    Args:
        tmp_path: Disposable synthetic preflight workspace.
        monkeypatch: Fixture replacing external preflight observations.
        library: Selected whole-stack profile entry.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    prepared = run_comparison.prepare_run(
        "core33",
        "graphex",
        venv_root,
        tmp_path / "seed.sqlite3",
        tmp_path / "run",
        1000,
    )
    manifest = json.loads(
        (run_comparison.BASE / "comparison_profiles/core33/manifest.json").read_text()
    )
    plan = replace(
        prepared, library=library, packages=manifest["libraries"][library]["packages"]
    )
    run_comparison.validate_result(plan, _measured_result(plan))
    assert not plan.output_root.exists()


@pytest.mark.parametrize(
    "field", ["commit", "tree", "source_version", "backend_path", "constraints_sha256"]
)
def test_result_validator_rejects_forged_child_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Reject five independently forged measured identity fields.

    Args:
        tmp_path: Disposable profile and output paths.
        monkeypatch: Fixture replacing external preflight observations.
        field: Witness value changed after preflight.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "run"
    plan = run_comparison.prepare_run(
        "core33", "graphex", venv_root, tmp_path / "seed.sqlite3", output, 1000
    )
    result = _measured_result(plan)
    result["profile_witness"][field] = "forged"
    with pytest.raises(ValueError, match="witness"):
        run_comparison.validate_result(plan, result)
    assert not output.exists()


@pytest.mark.parametrize(
    "field", ["versions", "provenance", "surface", "sql", "rebuilds"]
)
def test_result_validator_rejects_workload_or_stack_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Reject mismatched stack, schema, SQL, or rebuild output read-only.

    Args:
        tmp_path: Disposable profile and output paths.
        monkeypatch: Fixture replacing external preflight observations.
        field: Result contract element changed after measurement.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "run"
    plan = run_comparison.prepare_run(
        "core33", "graphex", venv_root, tmp_path / "seed.sqlite3", output, 1000
    )
    result = _measured_result(plan)
    if field == "versions":
        result["versions"]["django"] = "0"
    elif field == "provenance":
        result["provenance"]["constraints_sha256"] = "0" * 64
    elif field == "surface":
        result["surface"] = {}
    elif field == "sql":
        result["ops"]["nested"]["sql_queries"] = 0
    else:
        result["schema_rebuild_samples_ms"] = []
    with pytest.raises(ValueError):
        run_comparison.validate_result(plan, result)
    assert not output.exists()


@pytest.mark.parametrize("field", ["missing_import", "nonnumeric_rebuild"])
def test_result_validator_rejects_incomplete_schema_timings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Reject an incomplete schema diagnostic before later publication.

    Args:
        tmp_path: Disposable synthetic preflight workspace.
        monkeypatch: Fixture replacing external preflight observations.
        field: Invalid schema timing to test.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    plan = run_comparison.prepare_run(
        "core33",
        "graphex",
        venv_root,
        tmp_path / "seed.sqlite3",
        tmp_path / "run",
        1000,
    )
    result = _measured_result(plan)
    if field == "missing_import":
        del result["schema_import_ms"]
    else:
        result["schema_rebuild_samples_ms"] = ["bad"] * 5
    with pytest.raises(ValueError, match="schema"):
        run_comparison.validate_result(plan, result)


@pytest.mark.parametrize(
    "metric", ["mean_ms", "p50_ms", "p95_ms", "min_ms", "stddev_ms"]
)
@pytest.mark.parametrize(
    "value",
    [float("inf"), json.loads("1e999"), True, False],
    ids=["infinity", "json-overflow", "true", "false"],
)
def test_result_validator_rejects_invalid_operation_timings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metric: str, value: object
) -> None:
    """Reject non-finite and boolean operation timings from a child result.

    Args:
        tmp_path: Disposable synthetic preflight workspace.
        monkeypatch: Fixture replacing external preflight observations.
        metric: Operation timing field to corrupt.
        value: Invalid measured value.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    plan = run_comparison.prepare_run(
        "core33",
        "graphex",
        venv_root,
        tmp_path / "seed.sqlite3",
        tmp_path / "run",
        1000,
    )
    result = _measured_result(plan)
    result["ops"]["flat_list"][metric] = value
    with pytest.raises(ValueError, match="timing"):
        run_comparison.validate_result(plan, result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_import_ms", True),
        ("schema_import_ms", False),
        ("schema_rebuild_samples_ms", True),
        ("schema_rebuild_samples_ms", False),
        ("sql_queries", True),
    ],
)
def test_result_validator_rejects_boolean_schema_timings_and_sql_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: bool
) -> None:
    """Reject JSON booleans where measured numbers or SQL counts are required.

    Args:
        tmp_path: Disposable synthetic preflight workspace.
        monkeypatch: Fixture replacing external preflight observations.
        field: Schema timing or SQL count field to corrupt.
        value: JSON-compatible boolean supplied by the child.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    plan = run_comparison.prepare_run(
        "core33",
        "graphex",
        venv_root,
        tmp_path / "seed.sqlite3",
        tmp_path / "run",
        1000,
    )
    result = _measured_result(plan)
    if field == "schema_rebuild_samples_ms":
        result[field] = [value] * 5
    elif field == "sql_queries":
        result["ops"]["flat_list"][field] = value
    else:
        result[field] = value
    with pytest.raises(ValueError):
        run_comparison.validate_result(plan, result)


def test_result_validator_accepts_finite_integer_and_float_timings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve valid integer and floating-point timing values.

    Args:
        tmp_path: Disposable synthetic preflight workspace.
        monkeypatch: Fixture replacing external preflight observations.
    """
    _, venv_root = _workspace(tmp_path, monkeypatch)
    plan = run_comparison.prepare_run(
        "core33",
        "graphex",
        venv_root,
        tmp_path / "seed.sqlite3",
        tmp_path / "run",
        1000,
    )
    result = _measured_result(plan)
    result["ops"]["flat_list"]["mean_ms"] = 1
    result["ops"]["flat_list"]["p50_ms"] = 0.5
    result["schema_import_ms"] = 2
    result["schema_rebuild_samples_ms"] = [0, 1, 0.5, 1.0, 2]
    run_comparison.validate_result(plan, result)
