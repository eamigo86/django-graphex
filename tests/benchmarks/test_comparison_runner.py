"""Contracts for the isolated named-profile single-run entrypoint."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks import run_comparison


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
