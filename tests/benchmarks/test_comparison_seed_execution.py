"""Contracts for the fresh private named-profile seed creator."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmarks import run_comparison
from benchmarks.comparison_seed import SeedPlan


def _workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authors: int = 1000
) -> tuple[SeedPlan, Path, Path]:
    """Provide a private parent and checked-plan stand-in without Django writes.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture isolating the benchmark source root.
        authors: Published workload cardinality.

    Returns:
        Checked plan, named environment root, and retained marker.
    """
    source = tmp_path / "source"
    base = source / "benchmarks"
    base.mkdir(parents=True)
    retained = base / "db.sqlite3"
    retained.write_bytes(b"retained")
    venv_root = tmp_path / "venvs"
    python = venv_root / ".venv-core33-graphex/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(run_comparison, "ROOT", source)
    monkeypatch.setattr(run_comparison, "BASE", base)
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: ("a" * 40, "b" * 40))
    output = tmp_path / f"private-{authors}"
    plan = SeedPlan(
        profile="core33",
        library="graphex",
        python=python,
        output_root=output,
        database=output / "db.sqlite3",
        authors=authors,
        commit="a" * 40,
        tree="b" * 40,
        source_version="3.1.1",
        python_version="3.12.11",
        django_version="6.0.8",
        graphql_core_version="3.3.0",
        backend_path=source / "django_graphex/__init__.py",
        manifest_sha256="c" * 64,
        constraints_sha256="d" * 64,
        freeze="django==6.0.8\ngraphql-core==3.3.0\n",
    )
    return plan, venv_root, retained


def _checks(monkeypatch: pytest.MonkeyPatch, plan: SeedPlan) -> list[tuple[str, Path]]:
    """Keep the real file reservation while replacing expensive child work.

    Args:
        monkeypatch: Fixture replacing read-only preflight and database checks.
        plan: The expected immutable preflight result.

    Returns:
        Child operations and their private database paths.
    """
    from benchmarks import comparison_seed_execution as execution

    monkeypatch.setattr(execution, "prepare_seed_plan", lambda *_: plan)
    observed: list[tuple[str, Path]] = []

    def child(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
        stdout: Any,
        stderr: Any,
    ) -> None:
        """Emulate only the reserved private SQLite file's content change.

        Raises:
            AssertionError: If a child escapes the checked source environment.
        """
        assert check is True and cwd == run_comparison.BASE
        database = Path(env["BENCH_DATABASE"])
        assert database.parent == plan.output_root.parent
        assert database != plan.database
        assert env["BENCH_AUTHORS"] == str(plan.authors)
        assert env["BENCH_PROFILE"] == "core33" and env["BENCH_LIB"] == "graphex"
        assert "UV_INDEX_URL" not in env and "BENCH_OUTPUT_DIR" not in env
        assert argv[:3] == [str(plan.python), "-m", "django"]
        operation = argv[3]
        observed.append((operation, database))
        database.write_bytes(b"migrated" if operation == "migrate" else b"seeded")
        stdout.write(f"{operation} stdout\n".encode())
        stderr.write(f"{operation} stderr\n".encode())

    monkeypatch.setattr(execution.subprocess, "run", child)

    def validate(database: Path, authors: int) -> None:
        """Require the shared validator to see the seeded reserved file."""
        assert authors == plan.authors and database.read_bytes() == b"seeded"

    monkeypatch.setattr(run_comparison, "_check_database", validate)
    return observed


@pytest.mark.parametrize("authors", (1000, 2000))
def test_creator_uses_private_named_runtime_and_shared_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authors: int
) -> None:
    """Publish only a validated private result after migrate and seed.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture isolating external child work.
        authors: One published workload size.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch, authors)
    observed = _checks(monkeypatch, plan)
    monkeypatch.setenv("BENCH_DATABASE", str(retained))
    monkeypatch.setenv("UV_INDEX_URL", "private-index.example")
    monkeypatch.setenv("BENCH_OUTPUT_DIR", str(retained.parent))
    result = execution.create_private_seed(plan, venv_root)
    assert result.plan == plan and result.database == plan.database
    assert result.database.read_bytes() == b"seeded"
    assert result.sha256 == hashlib.sha256(b"seeded").hexdigest()
    assert [name for name, _ in observed] == ["migrate", "seed_bench"]
    assert observed[0][1] == observed[1][1]
    assert result.migration_stdout.read_bytes() == b"migrate stdout\n"
    assert result.migration_stderr.read_bytes() == b"migrate stderr\n"
    assert result.seed_stdout.read_bytes() == b"seed_bench stdout\n"
    assert result.seed_stderr.read_bytes() == b"seed_bench stderr\n"
    assert retained.read_bytes() == b"retained"


def test_creator_rejects_every_forged_plan_field_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a changed or forged checked plan rather than trusting its label.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture replacing the read-only preflight.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(execution, "prepare_seed_plan", lambda *_: plan)
    for field in plan.__dataclass_fields__:
        with pytest.raises(ValueError):
            execution.create_private_seed(replace(plan, **{field: object()}), venv_root)
    assert not plan.output_root.exists() and retained.read_bytes() == b"retained"


@pytest.mark.parametrize("kind", ("file", "directory", "symlink"))
def test_creator_refuses_occupied_destination_even_if_plan_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Never overwrite occupied output or follow a destination symlink.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture replacing the read-only preflight.
        kind: Foreign target type.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(execution, "prepare_seed_plan", lambda *_: plan)
    if kind == "file":
        plan.output_root.write_bytes(b"foreign")
    elif kind == "directory":
        plan.output_root.mkdir()
        (plan.output_root / "marker").write_bytes(b"foreign")
    else:
        plan.output_root.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        execution.create_private_seed(plan, venv_root)
    assert retained.read_bytes() == b"retained"
    assert kind == "symlink" or (
        (plan.output_root / "marker").read_bytes() == b"foreign"
        if kind == "directory"
        else plan.output_root.read_bytes() == b"foreign"
    )


def test_creator_requires_owner_only_parent_before_attempt_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid child writes in a parent open to unrelated users.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture replacing the read-only preflight.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(execution, "prepare_seed_plan", lambda *_: plan)
    tmp_path.chmod(0o755)
    try:
        with pytest.raises(ValueError, match="owner-only"):
            execution.create_private_seed(plan, venv_root)
    finally:
        tmp_path.chmod(0o700)
    assert not list(tmp_path.glob(".private-1000-*"))
    assert retained.read_bytes() == b"retained"


@pytest.mark.parametrize("failed", ("migrate", "seed_bench"))
def test_creator_retains_failed_attempt_and_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: str
) -> None:
    """Keep failed private files and both child streams without cleanup.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture replacing the selected child operation.
        failed: Command to fail.

    Raises:
        AssertionError: If failed attempt files or streams are missing.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    seen = _checks(monkeypatch, plan)
    original = execution.subprocess.run

    def child(argv: list[str], **kwargs: Any) -> None:
        """Fail the selected command after writing its diagnostic streams."""
        if argv[3] == failed:
            kwargs["stdout"].write(b"failed stdout\n")
            kwargs["stderr"].write(b"failed stderr\n")
            raise subprocess.CalledProcessError(7, argv)
        original(argv, **kwargs)

    monkeypatch.setattr(execution.subprocess, "run", child)
    with pytest.raises(subprocess.CalledProcessError):
        execution.create_private_seed(plan, venv_root)
    assert [name for name, _ in seen] == ([] if failed == "migrate" else ["migrate"])
    attempts = sorted(tmp_path.glob(".private-1000-attempt-*.sqlite3"))
    assert len(attempts) == 1 and attempts[0].is_file()
    assert list(tmp_path.glob(".private-1000-*.stdout"))
    assert list(tmp_path.glob(".private-1000-*.stderr"))
    assert not plan.output_root.exists() and retained.read_bytes() == b"retained"


@pytest.mark.parametrize(
    "field,bad",
    (("commit", "f" * 40), ("freeze", "wrong"), ("graphql_core_version", "0")),
)
def test_creator_rejects_profile_drift_before_second_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, bad: str
) -> None:
    """Stop before seeding when fresh source or profile bindings drift.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture changing the fresh source binding.
        field: Bound profile or source field to change.
        bad: Replacement field value.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    seen = _checks(monkeypatch, plan)
    count = 0

    def check(*_: object) -> SeedPlan:
        """Change the returned source identity after migration."""
        nonlocal count
        count += 1
        return plan if count <= 3 else replace(plan, **{field: bad})

    monkeypatch.setattr(execution, "prepare_seed_plan", check)
    with pytest.raises(ValueError, match="plan"):
        execution.create_private_seed(plan, venv_root)
    assert [name for name, _ in seen] == ["migrate"]
    assert not plan.output_root.exists() and retained.read_bytes() == b"retained"


@pytest.mark.parametrize("replacement", ("file", "symlink"))
def test_creator_rejects_database_replacement_between_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    """Never seed a foreign regular file or symlink after migration.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture replacing a reserved database pathname.
        replacement: Foreign pathname type to install.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    seen = _checks(monkeypatch, plan)
    original = execution.subprocess.run

    def replace_database(argv: list[str], **kwargs: Any) -> None:
        """Replace the just-migrated path with a foreign regular file."""
        original(argv, **kwargs)
        if argv[3] == "migrate":
            database = Path(kwargs["env"]["BENCH_DATABASE"])
            database.rename(tmp_path / "recoverable-owned.sqlite3")
            if replacement == "file":
                database.write_bytes(b"foreign")
            else:
                (tmp_path / "foreign.sqlite3").write_bytes(b"foreign")
                database.symlink_to(tmp_path / "foreign.sqlite3")

    monkeypatch.setattr(execution.subprocess, "run", replace_database)
    with pytest.raises(ValueError, match="changed"):
        execution.create_private_seed(plan, venv_root)
    assert [name for name, _ in seen] == ["migrate"]
    assert (tmp_path / "recoverable-owned.sqlite3").read_bytes() == b"migrated"
    attempt = list(tmp_path.glob(".private-1000-attempt-*.sqlite3"))[0]
    assert attempt.read_bytes() == b"foreign"
    assert attempt.is_symlink() == (replacement == "symlink")
    assert not plan.output_root.exists() and retained.read_bytes() == b"retained"


@pytest.mark.parametrize("kind", ("directory", "file", "symlink"))
def test_creator_refuses_foreign_output_just_before_atomic_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Keep a foreign target rather than replacing it at install.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture inserting a target at the no-clobber boundary.
        kind: Foreign target form.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    _checks(monkeypatch, plan)
    original = execution._rename_noreplace

    def occupied(source: Path, destination: Path) -> None:
        """Insert a foreign target immediately before atomic install."""
        if kind == "directory":
            destination.mkdir()
        elif kind == "file":
            destination.write_bytes(b"foreign")
        else:
            destination.symlink_to(tmp_path / "missing")
        original(source, destination)

    monkeypatch.setattr(execution, "_rename_noreplace", occupied)
    with pytest.raises(FileExistsError):
        execution.create_private_seed(plan, venv_root)
    if kind == "directory":
        assert list(plan.output_root.iterdir()) == []
    elif kind == "file":
        assert plan.output_root.read_bytes() == b"foreign"
    else:
        assert plan.output_root.is_symlink()
    assert retained.read_bytes() == b"retained"


def test_creator_rejects_invalid_shared_database_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never publish a database rejected by the shared cardinality checker.

    Args:
        tmp_path: Pytest-owned private filesystem root.
        monkeypatch: Fixture replacing the database validator.
    """
    from benchmarks import comparison_seed_execution as execution

    plan, venv_root, retained = _workspace(tmp_path, monkeypatch)
    _checks(monkeypatch, plan)
    monkeypatch.setattr(
        run_comparison,
        "_check_database",
        lambda *_: (_ for _ in ()).throw(ValueError("shape")),
    )
    with pytest.raises(ValueError, match="shape"):
        execution.create_private_seed(plan, venv_root)
    assert not plan.output_root.exists() and retained.read_bytes() == b"retained"
