"""Preflight a named profile and optionally dispatch one diagnostic run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from .profile_bootstrap import load_profile
    from .run_publish import (
        EXPECTED_SQL,
        EXPECTED_SURFACE,
        EXPECTED_VERSIONS,
        METRICS,
        OPERATIONS,
    )
else:
    from profile_bootstrap import load_profile
    from run_publish import (
        EXPECTED_SQL,
        EXPECTED_SURFACE,
        EXPECTED_VERSIONS,
        METRICS,
        OPERATIONS,
    )

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent


@dataclass(frozen=True)
class RunPlan:
    """Hold validated single-run inputs before any output is created.

    The immutable plan binds a selected runtime to a committed source identity.
    """

    profile: str
    library: str
    python: Path
    database: Path
    output_root: Path
    authors: int
    python_version: str
    commit: str
    tree: str
    source_version: str
    backend_path: Path
    manifest_sha256: str
    constraints_sha256: str
    packages: dict[str, str]


def _git_identity() -> tuple[str, str]:
    """Require a clean checkout and return the exact committed source identity.

    Returns:
        Commit and tree hashes for the clean benchmark checkout.

    Raises:
        ValueError: If this is a different or modified checkout.
    """

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT.resolve():
        raise ValueError("benchmark source is not this Git checkout")
    changes = git("status", "--porcelain", "--untracked-files=normal").splitlines()
    if any(change != "?? .codegraph/" for change in changes):
        raise ValueError("benchmark source checkout must be clean")
    return git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")


def _environment(library: str, database: Path, authors: int) -> dict[str, str]:
    """Build a minimal process environment without ambient package credentials.

    Args:
        library: Selected benchmark adapter.
        database: Prepared SQLite database.
        authors: Seeded author count.

    Returns:
        Explicit environment shared by probes and the measured subprocess.
    """
    return {
        "PATH": os.defpath,
        "HOME": tempfile.gettempdir(),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": f"{ROOT}:{BASE}",
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "BENCH_LIB": library,
        "BENCH_DATABASE": str(database),
        "BENCH_AUTHORS": str(authors),
        "BENCH_PROFILE": "core33",
    }


def _installed_freeze(python: Path, constraints: Path, library: str) -> str:
    """Observe the selected interpreter's installed distributions.

    Args:
        python: Profile virtualenv interpreter.
        constraints: Exact selected freeze file.
        library: Selected benchmark adapter.

    Returns:
        Validated deterministic installed freeze.
    """
    return subprocess.check_output(
        [str(python), str(BASE / "verify_freeze.py"), str(constraints), library],
        cwd=BASE,
        env=_environment(library, Path(tempfile.gettempdir()), 1000),
        text=True,
    )


def _runtime_probe(
    python: Path, library: str, database: Path, authors: int
) -> dict[str, str]:
    """Observe runtime versions and the package imported by the real interpreter.

    Args:
        python: Profile virtualenv interpreter.
        library: Selected benchmark adapter.
        database: Prepared SQLite database.
        authors: Seeded author count.

    Returns:
        Runtime versions and the resolved backend import path.
    """
    backend = {
        "graphex": "django_graphex",
        "graphene": "graphene_django",
        "strawberry": "strawberry_django",
        "ariadne": "ariadne",
    }[library]
    code = (
        "import django, graphql, importlib, json, platform; "
        "from pathlib import Path; "
        f"backend = importlib.import_module({backend!r}); "
        "print(json.dumps({'python': platform.python_version(), 'django': django.__version__, "
        "'graphql-core': graphql.version, "
        "'backend_path': str(Path(backend.__file__).resolve())}))"
    )
    output = subprocess.check_output(
        [str(python), "-c", code],
        cwd=BASE,
        env=_environment(library, database, authors),
        text=True,
    )
    return json.loads(output)


def _check_database(database: Path, authors: int) -> None:
    """Require the prepared shared seed without resetting or modifying it.

    Args:
        database: Existing SQLite seed.
        authors: Expected author count.

    Raises:
        ValueError: If seed cardinalities or fixed operation IDs differ.
    """
    try:
        with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
            counts = tuple(
                connection.execute(f"SELECT COUNT(*) FROM benchapp_{table}").fetchone()[
                    0
                ]
                for table in ("author", "post", "comment")
            )
            fixed_post = connection.execute(
                "SELECT 1 FROM benchapp_post WHERE id=5000"
            ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("prepared benchmark database is invalid") from exc
    if counts != (authors, authors * 10, authors * 50) or fixed_post is None:
        raise ValueError("prepared benchmark seed does not match the workload")


def prepare_run(
    profile: str,
    library: str,
    venv_root: Path,
    database: Path,
    output_root: Path,
    authors: int,
) -> RunPlan:
    """Validate every input before creating an output or running a workload.

    Args:
        profile: Explicit named comparison profile.
        library: One selected library.
        venv_root: Root containing the previously bootstrapped profile venvs.
        database: Existing seeded SQLite database, never reset here.
        output_root: New external diagnostic directory.
        authors: Exact prepared seed cardinality.

    Returns:
        Immutable validated run plan.

    Raises:
        ValueError: If source, destination, freeze, runtime, or seed is unsafe.
    """
    spec = load_profile(profile, library, BASE)
    if authors < 1 or not database.is_absolute() or not database.is_file():
        raise ValueError("an existing absolute seeded database is required")
    if (
        not output_root.is_absolute()
        or output_root.exists()
        or output_root.is_symlink()
        or not output_root.parent.is_dir()
    ):
        raise ValueError("output must be a fresh absolute directory")
    destination = output_root.resolve()
    if destination.is_relative_to(ROOT.resolve()) or destination.is_relative_to(
        venv_root.resolve()
    ):
        raise ValueError("output must not occupy source or profile assets")
    if not venv_root.is_absolute():
        raise ValueError("virtualenv root must be absolute")
    python = venv_root / f".venv-{profile}-{library}/bin/python"
    if not python.is_file():
        raise ValueError("profile interpreter is missing")
    freeze = spec["constraints"].read_text()
    sidecar = python.parent.parent / ".freeze.txt"
    if not sidecar.is_file() or sidecar.read_text() != freeze:
        raise ValueError("profile freeze sidecar differs from manifest constraints")
    commit, tree = _git_identity()
    _check_database(database, authors)
    if _installed_freeze(python, spec["constraints"], library) != freeze:
        raise ValueError("installed profile freeze differs from constraints")
    runtime = _runtime_probe(python, library, database, authors)
    if any(
        runtime[key] != expected
        for key, expected in (
            ("python", spec["python"]),
            ("django", spec["packages"]["django"]),
            ("graphql-core", spec["packages"]["graphql-core"]),
        )
    ):
        raise ValueError("profile runtime differs from the selected manifest")
    backend_path = Path(runtime["backend_path"])
    if library == "graphex":
        if backend_path != ROOT / "django_graphex/__init__.py":
            raise ValueError("Graphex interpreter imports the wrong source checkout")
    elif not backend_path.is_relative_to(python.parent.parent):
        raise ValueError("peer interpreter imports a backend outside its profile")
    source_version = str(
        tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    )
    manifest = BASE / "comparison_profiles" / profile / "manifest.json"
    return RunPlan(
        profile,
        library,
        python,
        database,
        output_root,
        authors,
        spec["python"],
        commit,
        tree,
        source_version,
        backend_path,
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
        hashlib.sha256(spec["constraints"].read_bytes()).hexdigest(),
        spec["packages"],
    )


def _valid_timing(value: object) -> bool:
    """Identify finite, nonnegative timing values without accepting booleans.

    Args:
        value: Measured millisecond value from the child result.

    Returns:
        Whether the value is a finite integer or float at least zero.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def validate_result(plan: RunPlan, result: dict[str, Any]) -> None:
    """Require the child output to match the checked whole-stack contract.

    Args:
        plan: Preflight-validated source and runtime selection.
        result: Raw output from the measuring child.

    Raises:
        ValueError: If identity, schema, workload, or SQL differs.
    """
    expected_witness = {
        "profile": plan.profile,
        "library": plan.library,
        "commit": plan.commit,
        "tree": plan.tree,
        "source_version": plan.source_version,
        "manifest_sha256": plan.manifest_sha256,
        "constraints_sha256": plan.constraints_sha256,
        "backend_path": str(plan.backend_path),
        "schema_path": str(BASE / "libs" / plan.library / "bench_schema.py"),
        "python": plan.python_version,
        "django": plan.packages["django"],
        "graphql-core": plan.packages["graphql-core"],
    }
    if result.get("profile_witness") != expected_witness:
        raise ValueError("measured profile witness differs from preflight")
    expected_versions = {
        name: plan.source_version if name == "django-graphex" else plan.packages[name]
        for name in EXPECTED_VERSIONS[plan.library]
    }
    expected_provenance = {
        "commit": plan.commit,
        "tree": plan.tree,
        "constraints_sha256": plan.constraints_sha256,
    }
    if (
        result.get("versions") != expected_versions
        or result.get("provenance") != expected_provenance
    ):
        raise ValueError("measured dependency provenance differs from profile")
    if result.get("lib") != plan.library or result.get("python") != plan.python_version:
        raise ValueError("measured library or Python differs from profile")
    if result.get("django") != plan.packages["django"] or result.get("dataset") != {
        "authors": plan.authors,
        "posts_per_author": 10,
        "comments_per_post": 5,
    }:
        raise ValueError("measured Django or seed differs from profile")
    if result.get("surface") != EXPECTED_SURFACE:
        raise ValueError("measured schema surface differs from contract")
    operations = result.get("ops")
    if not isinstance(operations, dict) or set(operations) != set(OPERATIONS):
        raise ValueError("measured operation set differs from contract")
    for name, sql_queries in EXPECTED_SQL[plan.library].items():
        stats = operations[name]
        if (
            not isinstance(stats, dict)
            or isinstance(stats.get("sql_queries"), bool)
            or stats.get("sql_queries") != sql_queries
            or stats.get("iterations") != 100
        ):
            raise ValueError(f"measured SQL or iterations differ for {name}")
        if not all(_valid_timing(stats.get(metric)) for metric in METRICS):
            raise ValueError(f"measured timing fields differ for {name}")
    builds = result.get("schema_rebuild_samples_ms")
    imported = result.get("schema_import_ms")
    if not _valid_timing(imported):
        raise ValueError("measured schema import differs from contract")
    if (
        not isinstance(builds, list)
        or len(builds) != 5
        or not all(_valid_timing(sample) for sample in builds)
    ):
        raise ValueError("measured schema rebuild count differs from contract")


def _database_identity(database: Path) -> tuple[str, tuple[tuple[str, int], ...]]:
    """Read seed bytes and persistent SQLite allocation sequence.

    Args:
        database: Prepared SQLite seed file.

    Returns:
        Database digest and ordered sequence values.
    """
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        sequence = tuple(
            connection.execute("SELECT name, seq FROM sqlite_sequence ORDER BY name")
        )
    return hashlib.sha256(database.read_bytes()).hexdigest(), sequence


def _check_measured_context(plan: RunPlan) -> None:
    """Recheck source, selected stack, and seed after the child exits.

    Args:
        plan: Identity attested before the measured subprocess.

    Raises:
        ValueError: If source, profile, runtime, or seed has drifted.
    """
    if (
        _git_identity() != (plan.commit, plan.tree)
        or str(
            tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
        )
        != plan.source_version
    ):
        raise ValueError("source changed during measurement")
    spec = load_profile(plan.profile, plan.library, BASE)
    manifest = BASE / "comparison_profiles" / plan.profile / "manifest.json"
    freeze = spec["constraints"].read_text()
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != plan.manifest_sha256:
        raise ValueError("profile manifest changed during measurement")
    if (
        hashlib.sha256(spec["constraints"].read_bytes()).hexdigest()
        != plan.constraints_sha256
        or (plan.python.parent.parent / ".freeze.txt").read_text() != freeze
        or _installed_freeze(plan.python, spec["constraints"], plan.library) != freeze
    ):
        raise ValueError("profile freeze changed during measurement")
    runtime = _runtime_probe(plan.python, plan.library, plan.database, plan.authors)
    if runtime != {
        "python": plan.python_version,
        "django": plan.packages["django"],
        "graphql-core": plan.packages["graphql-core"],
        "backend_path": str(plan.backend_path),
    }:
        raise ValueError("profile runtime changed during measurement")
    _check_database(plan.database, plan.authors)


def run_single(plan: RunPlan) -> Path:
    """Measure once into a disposable output using the selected interpreter.

    Failed attempts retain their output because pathname observations cannot
    establish creation ownership for safe automatic deletion.

    Args:
        plan: Read-only preflight selection.

    Returns:
        Verified diagnostic JSON path.

    Raises:
        ValueError: If source, seed, or measured result differs from preflight.
        FileExistsError: If the destination was claimed after preflight.
        subprocess.CalledProcessError: If the measuring child fails.
    """
    if (
        prepare_run(
            plan.profile,
            plan.library,
            plan.python.parents[2],
            plan.database,
            plan.output_root,
            plan.authors,
        )
        != plan
    ):
        raise ValueError("profile changed after preflight")
    before = _database_identity(plan.database)
    destination = plan.output_root
    parent_fd = os.open(
        destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    output_fd: int | None = None
    observed: os.stat_result | None = None
    filename = f"{plan.library}.json"

    def unchanged() -> bool:
        """Check that the visible name still identifies the observed directory.

        Returns:
            Whether acquisition and the visible name match the observed inode.
        """
        if output_fd is None or observed is None:
            return False
        held = os.fstat(output_fd)
        try:
            named = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            return False
        identity = (observed.st_dev, observed.st_ino)
        return stat.S_ISDIR(named.st_mode) and (
            (held.st_dev, held.st_ino) == identity
            and (named.st_dev, named.st_ino) == identity
        )

    try:
        os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
        observed = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
        output_fd = os.open(
            destination.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        if not unchanged():
            raise ValueError("output directory changed before measurement")
        environment = _environment(plan.library, plan.database, plan.authors)
        environment.update(
            BENCH_OUTPUT_DIR=str(destination),
            BENCH_OUTPUT_FD=str(output_fd),
            BENCH_PREFIX="",
        )
        subprocess.run(
            [str(plan.python), str(BASE / "harness.py")],
            cwd=BASE,
            env=environment,
            pass_fds=(output_fd,),
            capture_output=True,
            text=True,
            check=True,
        )
        _check_measured_context(plan)
        if _database_identity(plan.database) != before:
            raise ValueError("measurement changed seed or SQLite sequence")
        if not unchanged():
            raise ValueError("output directory changed during measurement")
        if os.listdir(output_fd) != [filename]:
            raise ValueError("measuring child created unexpected output files")
        file_info = os.stat(filename, dir_fd=output_fd, follow_symlinks=False)
        if not stat.S_ISREG(file_info.st_mode) or file_info.st_nlink != 1:
            raise ValueError("measuring child created a non-regular output")
        file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=output_fd)
        with os.fdopen(file_fd) as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (file_info.st_dev, file_info.st_ino):
                raise ValueError("output file changed before validation")
            validate_result(plan, json.load(stream))
        current_file = os.stat(filename, dir_fd=output_fd, follow_symlinks=False)
        if (
            current_file.st_dev,
            current_file.st_ino,
            current_file.st_size,
            current_file.st_mtime_ns,
        ) != (
            file_info.st_dev,
            file_info.st_ino,
            file_info.st_size,
            file_info.st_mtime_ns,
        ):
            raise ValueError("output file changed during validation")
        if not unchanged():
            raise ValueError("output directory changed during result validation")
        return destination / filename
    finally:
        if output_fd is not None:
            os.close(output_fd)
        os.close(parent_fd)


def main(argv: list[str] | None = None) -> None:
    """Report preflight identity or explicitly run one unpublished diagnostic.

    Args:
        argv: Optional CLI arguments; defaults to the process arguments.

    Raises:
        ValueError: If selected source, interpreter, seed, or output is unsafe.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("--venv-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--authors", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    plan = prepare_run(
        args.profile,
        args.library,
        args.venv_root,
        args.database,
        args.output_root,
        args.authors,
    )
    report = {
        "profile": plan.profile,
        "library": plan.library,
        "python": str(plan.python),
        "python_version": plan.python_version,
        "database": str(plan.database),
        "output_root": str(plan.output_root),
        "commit": plan.commit,
        "tree": plan.tree,
        "source_version": plan.source_version,
        "backend_path": str(plan.backend_path),
        "manifest_sha256": plan.manifest_sha256,
        "constraints_sha256": plan.constraints_sha256,
        "packages": plan.packages,
    }
    if args.execute:
        report["result"] = str(run_single(plan))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
