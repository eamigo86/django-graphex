"""Contracts for read-only preflight of a private named-profile seed."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from benchmarks import run_comparison


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Build a source and pinned-interpreter stand-in without a database.

    Args:
        tmp_path: Disposable filesystem root.
        monkeypatch: Fixture isolating identity and runtime observations.

    Returns:
        Source and virtualenv roots for read-only tests.
    """
    root = tmp_path / "source"
    (root / "django_graphex").mkdir(parents=True)
    (root / "django_graphex/__init__.py").write_text("")
    (root / "pyproject.toml").write_text('[project]\nversion = "3.1.1"\n')
    marker = root / "retained-marker"
    marker.write_bytes(b"retained")
    venv_root = tmp_path / "venvs"
    python = venv_root / ".venv-core33-graphex/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    freeze = run_comparison.BASE / "comparison_profiles/core33/constraints/graphex.txt"
    (python.parent.parent / ".freeze.txt").write_bytes(freeze.read_bytes())
    monkeypatch.setattr(run_comparison, "ROOT", root)
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: ("a" * 40, "b" * 40))
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
    return root, venv_root


@pytest.mark.parametrize("authors", (1000, 2000))
def test_seed_plan_is_pinned_and_has_no_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authors: int
) -> None:
    """Return a complete checked plan without reserving any destination.

    Args:
        tmp_path: Disposable filesystem root.
        monkeypatch: Fixture blocking write entrypoints.
        authors: One supported workload size.

    Raises:
        AssertionError: If the plan changes an observed field or writes output.
    """
    from benchmarks import comparison_seed

    root, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / f"private-{authors}"
    observed: list[tuple[Path, int]] = []
    original_probe = run_comparison._runtime_probe

    def probe(python: Path, library: str, database: Path, count: int) -> dict[str, str]:
        """Record the intended private path used by the cheap runtime probe.

        Raises:
            AssertionError: If the probe would target a different library.
        """
        assert library == "graphex"
        observed.append((database, count))
        return original_probe(python, library, database, count)

    monkeypatch.setattr(run_comparison, "_runtime_probe", probe)

    def forbid(*_: object, **__: object) -> None:
        """Fail if preflight attempts a directory or child-process write."""
        raise AssertionError("read-only preflight attempted a write")

    monkeypatch.setattr(run_comparison.subprocess, "run", forbid)
    monkeypatch.setattr(Path, "mkdir", forbid)
    plan = comparison_seed.prepare_seed_plan("core33", venv_root, output, authors)
    freeze = (
        run_comparison.BASE / "comparison_profiles/core33/constraints/graphex.txt"
    ).read_text()
    assert (plan.profile, plan.library, plan.authors) == ("core33", "graphex", authors)
    assert plan.python == venv_root / ".venv-core33-graphex/bin/python"
    assert plan.output_root == output
    assert plan.database == output / "db.sqlite3"
    assert (plan.commit, plan.tree, plan.source_version) == (
        "a" * 40,
        "b" * 40,
        "3.1.1",
    )
    assert (plan.python_version, plan.django_version, plan.graphql_core_version) == (
        "3.12.11",
        "6.0.8",
        "3.3.0",
    )
    assert plan.backend_path == root / "django_graphex/__init__.py"
    assert plan.freeze == freeze
    assert plan.constraints_sha256 == hashlib.sha256(freeze.encode()).hexdigest()
    manifest = run_comparison.BASE / "comparison_profiles/core33/manifest.json"
    assert plan.manifest_sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert observed == [(output / "db.sqlite3", authors)]
    assert not output.exists() and not output.is_symlink()
    assert (root / "retained-marker").read_bytes() == b"retained"


@pytest.mark.parametrize("authors", (0, 999, 3000, True, "1000"))
def test_seed_plan_rejects_invalid_authors_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authors: object
) -> None:
    """Reject non-workload or boolean cardinalities without creating output.

    Args:
        tmp_path: Disposable filesystem root.
        monkeypatch: Fixture isolating runtime observations.
        authors: Invalid candidate count.
    """
    from benchmarks import comparison_seed

    _, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "private"
    with pytest.raises(ValueError):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, authors)
    assert not output.exists()


@pytest.mark.parametrize(
    "kind",
    ("file", "directory", "dangling", "source", "venv", "relative", "parent-symlink"),
)
def test_seed_plan_rejects_occupied_or_protected_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Refuse occupied, linked, nonabsolute, or protected seed paths.

    Args:
        tmp_path: Disposable filesystem root.
        monkeypatch: Fixture isolating runtime observations.
        kind: Unsafe destination form.
    """
    from benchmarks import comparison_seed

    root, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "private"
    if kind == "file":
        output.write_bytes(b"foreign")
    elif kind == "directory":
        output.mkdir()
        (output / "marker").write_bytes(b"foreign")
    elif kind == "dangling":
        output.symlink_to(tmp_path / "missing")
    elif kind == "source":
        output = root / "private"
    elif kind == "venv":
        output = venv_root / "private"
    elif kind == "relative":
        output = Path("relative-private")
    else:
        parent = tmp_path / "linked-parent"
        parent.symlink_to(root, target_is_directory=True)
        output = parent / "private"
    with pytest.raises(ValueError):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, 1000)
    if kind == "file":
        assert output.read_bytes() == b"foreign"
    if kind == "directory":
        assert (output / "marker").read_bytes() == b"foreign"
    assert (root / "retained-marker").read_bytes() == b"retained"


def test_seed_plan_rejects_wrong_profile_source_or_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed on unknown profile, dirty source, or freeze drift.

    Args:
        tmp_path: Disposable filesystem root.
        monkeypatch: Fixture injecting mismatched observations.
    """
    from benchmarks import comparison_seed

    _, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "private"
    with pytest.raises(ValueError):
        comparison_seed.prepare_seed_plan("unknown", venv_root, output, 1000)
    monkeypatch.setattr(
        run_comparison,
        "_git_identity",
        lambda: (_ for _ in ()).throw(ValueError("dirty")),
    )
    with pytest.raises(ValueError, match="dirty"):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, 1000)
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: ("a" * 40, "b" * 40))
    (venv_root / ".venv-core33-graphex/.freeze.txt").write_text("wrong\n")
    with pytest.raises(ValueError, match="freeze"):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, 1000)
    (venv_root / ".venv-core33-graphex/.freeze.txt").write_text(
        (
            run_comparison.BASE / "comparison_profiles/core33/constraints/graphex.txt"
        ).read_text()
    )
    monkeypatch.setattr(run_comparison, "_installed_freeze", lambda *_: "wrong\n")
    with pytest.raises(ValueError, match="installed profile freeze"):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, 1000)
    (venv_root / ".venv-core33-graphex/.freeze.txt").unlink()
    (venv_root / ".venv-core33-graphex/bin/python").unlink()
    with pytest.raises(ValueError, match="interpreter"):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, 1000)
    assert not output.exists()


@pytest.mark.parametrize("change", ("destination", "source"))
def test_seed_plan_rechecks_state_after_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """Reject destination or source drift observed during read-only preflight.

    Args:
        tmp_path: Disposable filesystem root.
        monkeypatch: Fixture injecting a concurrent change.
        change: State to change during the runtime probe.
    """
    from benchmarks import comparison_seed

    _, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "private"
    observed = run_comparison._runtime_probe
    if change == "source":
        identities = iter((("a" * 40, "b" * 40), ("c" * 40, "d" * 40)))
        monkeypatch.setattr(run_comparison, "_git_identity", lambda: next(identities))
    else:

        def occupied(*args: object) -> dict[str, str]:
            """Place a foreign file before the final fresh-path check."""
            output.write_bytes(b"foreign")
            return observed(*args)

        monkeypatch.setattr(run_comparison, "_runtime_probe", occupied)
    with pytest.raises(ValueError):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, 1000)
    if change == "destination":
        assert output.read_bytes() == b"foreign"


@pytest.mark.parametrize("field", ("python", "django", "graphql-core", "backend_path"))
def test_seed_plan_rejects_wrong_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """Require exact native interpreter versions and this source backend.

    Args:
        tmp_path: Disposable filesystem root.
        monkeypatch: Fixture injecting one runtime drift.
        field: Observed runtime field to change.
    """
    from benchmarks import comparison_seed

    _, venv_root = _workspace(tmp_path, monkeypatch)
    output = tmp_path / "private"
    original = run_comparison._runtime_probe

    def drift(*args: object) -> dict[str, str]:
        """Change only one observed runtime field."""
        observed = original(*args)
        observed[field] = "wrong"
        return observed

    monkeypatch.setattr(run_comparison, "_runtime_probe", drift)
    with pytest.raises(ValueError, match="runtime"):
        comparison_seed.prepare_seed_plan("core33", venv_root, output, 1000)
    assert not output.exists()
