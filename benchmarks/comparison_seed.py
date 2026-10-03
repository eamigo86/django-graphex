"""Check a private seed destination without creating it."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import run_comparison


@dataclass(frozen=True)
class SeedPlan:
    """Bind a fresh destination to checked source and profile observations."""

    profile: str
    library: str
    python: Path
    output_root: Path
    database: Path
    authors: int
    commit: str
    tree: str
    source_version: str
    python_version: str
    django_version: str
    graphql_core_version: str
    backend_path: Path
    manifest_sha256: str
    constraints_sha256: str
    freeze: str


def _check_destination(output_root: Path, venv_root: Path) -> None:
    """Reject a destination currently occupied, linked, or inside protected roots.

    Args:
        output_root: Proposed external directory for a future private seed.
        venv_root: Existing named-profile environment root.

    Raises:
        ValueError: If the destination is currently unsafe for later reservation.
    """
    if (
        not output_root.is_absolute()
        or output_root.exists()
        or output_root.is_symlink()
        or not output_root.parent.is_dir()
        or output_root.parent != output_root.parent.resolve()
    ):
        raise ValueError("seed destination must be a fresh absolute external path")
    destination = output_root.resolve()
    if destination.is_relative_to(
        run_comparison.ROOT.resolve()
    ) or destination.is_relative_to(venv_root.resolve()):
        raise ValueError("seed destination overlaps source or profile environments")


def prepare_seed_plan(
    profile: str, venv_root: Path, output_root: Path, authors: int
) -> SeedPlan:
    """Read and validate one named Graphex seed plan without writing anything.

    Args:
        profile: Exact selected benchmark profile.
        venv_root: Absolute root of already prepared named environments.
        output_root: Fresh external destination to reserve in a later unit.
        authors: Supported published workload cardinality.

    Returns:
        Immutable observations for the future exclusive seed creator.

    Raises:
        ValueError: If source, profile, interpreter, or destination fails preflight.
    """
    if type(authors) is not int or authors not in (1000, 2000):
        raise ValueError("seed authors must be 1000 or 2000")
    spec = run_comparison.load_profile(profile, "graphex", run_comparison.BASE)
    if spec["mode"] != "source" or not venv_root.is_absolute():
        raise ValueError("an absolute source-profile environment is required")
    _check_destination(output_root, venv_root)
    python = venv_root / f".venv-{profile}-graphex/bin/python"
    if not python.is_file():
        raise ValueError("profile interpreter is missing")
    freeze = spec["constraints"].read_text()
    sidecar = python.parent.parent / ".freeze.txt"
    if not sidecar.is_file() or sidecar.read_text() != freeze:
        raise ValueError("profile freeze sidecar differs from constraints")
    commit, tree = run_comparison._git_identity()
    if (
        run_comparison._installed_freeze(python, spec["constraints"], "graphex")
        != freeze
    ):
        raise ValueError("installed profile freeze differs from constraints")
    database = output_root / "db.sqlite3"
    runtime = run_comparison._runtime_probe(python, "graphex", database, authors)
    if any(
        runtime[key] != expected
        for key, expected in (
            ("python", spec["python"]),
            ("django", spec["packages"]["django"]),
            ("graphql-core", spec["packages"]["graphql-core"]),
            ("backend_path", str(run_comparison.ROOT / "django_graphex/__init__.py")),
        )
    ):
        raise ValueError(
            "profile runtime differs from the selected source and manifest"
        )
    source_version = tomllib.loads(
        (run_comparison.ROOT / "pyproject.toml").read_text()
    )["project"]["version"]
    if not isinstance(source_version, str) or not source_version:
        raise ValueError("source version is missing")
    _check_destination(output_root, venv_root)
    if run_comparison._git_identity() != (commit, tree):
        raise ValueError("source identity changed during seed preflight")
    manifest = run_comparison.BASE / "comparison_profiles" / profile / "manifest.json"
    return SeedPlan(
        profile=profile,
        library="graphex",
        python=python,
        output_root=output_root,
        database=database,
        authors=authors,
        commit=commit,
        tree=tree,
        source_version=source_version,
        python_version=runtime["python"],
        django_version=runtime["django"],
        graphql_core_version=runtime["graphql-core"],
        backend_path=Path(runtime["backend_path"]),
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        constraints_sha256=hashlib.sha256(spec["constraints"].read_bytes()).hexdigest(),
        freeze=freeze,
    )
