"""Build one private named-profile seed without publishing measurements."""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import run_comparison
from .comparison_seed import SeedPlan, _check_destination, prepare_seed_plan


@dataclass(frozen=True)
class PreparedSeed:
    """Record the validated private database and retained child streams.

    The source plan is a checked observation, not future execution authority.
    """

    plan: SeedPlan
    database: Path
    sha256: str
    migration_stdout: Path
    migration_stderr: Path
    seed_stdout: Path
    seed_stderr: Path


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically install a prepared directory only if its name is still free.

    Args:
        source: Fresh private staging directory.
        destination: Checked final output path.

    Raises:
        OSError: If the target exists or the platform cannot provide no-clobber.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    old, new = os.fsencode(source), os.fsencode(destination)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        result = rename(old, new, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        result = rename(-100, old, -100, new, 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise OSError("atomic no-clobber directory rename is unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def _check_visible(path: Path, descriptor: int, *, directory: bool) -> None:
    """Reject a visible path that no longer names its held object.

    Args:
        path: Visible directory or regular-file path.
        descriptor: Descriptor acquired while that object was reserved.
        directory: Whether the expected object is a directory.

    Raises:
        ValueError: If the path is missing, linked, or replaced.
    """
    try:
        visible = path.lstat()
        held = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError("private seed path changed") from exc
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(visible.st_mode) or (visible.st_dev, visible.st_ino) != (
        held.st_dev,
        held.st_ino,
    ):
        raise ValueError("private seed path changed")


def _retained_digest() -> bytes | None:
    """Observe an absent or regular shared seed without opening it as SQLite.

    Returns:
        Digest of a regular retained database, or None when it is absent.

    Raises:
        ValueError: If the retained path is not a stable regular file.
        OSError: If an observed regular file cannot be opened or read.
    """
    path = run_comparison.BASE / "db.sqlite3"
    try:
        visible = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(visible.st_mode):
        raise ValueError("retained benchmark database is not a regular file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        held = os.fstat(stream.fileno())
        if not stat.S_ISREG(held.st_mode) or (visible.st_dev, visible.st_ino) != (
            held.st_dev,
            held.st_ino,
        ):
            raise ValueError("retained benchmark database changed")
        digest = hashlib.file_digest(stream, "sha256").digest()
        current = path.lstat()
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (
            held.st_dev,
            held.st_ino,
        ):
            raise ValueError("retained benchmark database changed")
        return digest


def _checked_plan(plan: SeedPlan, venv_root: Path, retained: bytes | None) -> None:
    """Revalidate all source and destination bindings before another step.

    Args:
        plan: Original read-only preflight result.
        venv_root: Selected named-profile environment root.
        retained: Initial absence or digest of the shared retained database.

    Raises:
        ValueError: If the plan, destination, or retained database drifted.
    """
    current = prepare_seed_plan(plan.profile, venv_root, plan.output_root, plan.authors)
    if current != plan:
        raise ValueError("private seed plan changed")
    _check_destination(plan.output_root, venv_root)
    if _retained_digest() != retained:
        raise ValueError("retained benchmark database changed")


def _private_parent(parent: Path) -> int:
    """Hold an existing owner-only external parent directory.

    Args:
        parent: Parent of the requested fresh destination.

    Returns:
        Open directory descriptor for bounded identity checks.

    Raises:
        ValueError: If the parent is linked, missing, or not owner-only.
    """
    if not parent.is_absolute() or parent != parent.resolve():
        raise ValueError("private seed parent must be an absolute unlinked path")
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _check_visible(parent, descriptor, directory=True)
        held = os.fstat(descriptor)
        if held.st_uid != os.getuid() or stat.S_IMODE(held.st_mode) & 0o077:
            raise ValueError("private seed parent must be owner-only")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _run_child(
    plan: SeedPlan, database: Path, operation: tuple[str, ...]
) -> tuple[Path, Path]:
    """Dispatch one named Django command with durable private streams.

    Args:
        plan: Revalidated named-profile selection.
        database: Exclusively created private SQLite path.
        operation: Exact migration or seed command arguments.

    Returns:
        Paths holding the child's stdout and stderr, including on failure.

    Raises:
        subprocess.CalledProcessError: If Django exits unsuccessfully.
    """
    prefix = f".{plan.output_root.name}-{operation[0]}-"
    out_fd, out_name = tempfile.mkstemp(
        prefix=prefix, suffix=".stdout", dir=database.parent
    )
    try:
        err_fd, err_name = tempfile.mkstemp(
            prefix=prefix, suffix=".stderr", dir=database.parent
        )
    except OSError:
        os.close(out_fd)
        raise
    with os.fdopen(out_fd, "wb") as stdout, os.fdopen(err_fd, "wb") as stderr:
        subprocess.run(
            [str(plan.python), "-m", "django", *operation],
            cwd=run_comparison.BASE,
            env=run_comparison._environment("graphex", database, plan.authors),
            stdout=stdout,
            stderr=stderr,
            check=True,
        )
    return Path(out_name), Path(err_name)


def create_private_seed(plan: SeedPlan, venv_root: Path) -> PreparedSeed:
    """Build and validate one new private seed from a freshly checked plan.

    Only an owner-only external parent is accepted. The database is first
    created as an exclusive random regular file there, then linked into a
    staged directory and installed at the requested name without replacement.
    Failed or uncertain attempts are retained, never automatically removed.
    The random staging directory is used only beneath an owner-only parent;
    opening it after creation is not proof of creator ownership. Visible-path
    checks bound ordinary substitutions but are not an operating system
    sandbox against an actor able to change every filesystem operation.

    Args:
        plan: Immutable result of the read-only named-profile preflight.
        venv_root: Root of the already prepared named-profile environments.

    Returns:
        Validated private database path and retained provenance streams.

    Raises:
        ValueError: If the plan, paths, source, freeze, or database drift.
        OSError: If exclusive creation or no-clobber installation fails.
        subprocess.CalledProcessError: If migration or seeding fails.
    """
    if type(plan) is not SeedPlan:
        raise ValueError("a checked SeedPlan is required")
    retained = _retained_digest()
    _checked_plan(plan, venv_root, retained)
    parent = plan.output_root.parent
    parent_fd = _private_parent(parent)
    try:
        _checked_plan(plan, venv_root, retained)
        attempt_fd, attempt_name = tempfile.mkstemp(
            prefix=f".{plan.output_root.name}-attempt-", suffix=".sqlite3", dir=parent
        )
        attempt = Path(attempt_name)
        stage: Path | None = None
        try:
            streams: list[tuple[Path, Path]] = []
            for operation in (
                ("migrate", "--run-syncdb", "--noinput"),
                ("seed_bench", "--authors", str(plan.authors)),
            ):
                _check_visible(parent, parent_fd, directory=True)
                _check_visible(attempt, attempt_fd, directory=False)
                _checked_plan(plan, venv_root, retained)
                streams.append(_run_child(plan, attempt, operation))
                _check_visible(parent, parent_fd, directory=True)
                _check_visible(attempt, attempt_fd, directory=False)
                _checked_plan(plan, venv_root, retained)
            run_comparison._check_database(attempt, plan.authors)
            _check_visible(attempt, attempt_fd, directory=False)
            _checked_plan(plan, venv_root, retained)
            _check_visible(parent, parent_fd, directory=True)
            stage = Path(
                tempfile.mkdtemp(prefix=f".{plan.output_root.name}-ready-", dir=parent)
            )
            stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                _check_visible(stage, stage_fd, directory=True)
                _check_visible(attempt, attempt_fd, directory=False)
                os.link(attempt, stage / "db.sqlite3", follow_symlinks=False)
                _check_visible(stage / "db.sqlite3", attempt_fd, directory=False)
                _checked_plan(plan, venv_root, retained)
                _check_visible(parent, parent_fd, directory=True)
                _check_visible(stage, stage_fd, directory=True)
                _rename_noreplace(stage, plan.output_root)
                _check_visible(parent, parent_fd, directory=True)
                _check_visible(plan.output_root, stage_fd, directory=True)
                _check_visible(plan.database, attempt_fd, directory=False)
            finally:
                os.close(stage_fd)
            if _retained_digest() != retained or run_comparison._git_identity() != (
                plan.commit,
                plan.tree,
            ):
                raise ValueError("protected source or retained database changed")
            with os.fdopen(os.dup(attempt_fd), "rb") as database_stream:
                database_stream.seek(0)
                digest = hashlib.file_digest(database_stream, "sha256").hexdigest()
            return PreparedSeed(
                plan=plan,
                database=plan.database,
                sha256=digest,
                migration_stdout=streams[0][0],
                migration_stderr=streams[0][1],
                seed_stdout=streams[1][0],
                seed_stderr=streams[1][1],
            )
        except Exception as exc:
            exc.add_note(f"private seed attempt retained: {attempt}")
            if stage is not None:
                exc.add_note(f"private seed staging directory retained: {stage}")
            exc.add_note(f"private seed streams retained under: {parent}")
            raise
        finally:
            os.close(attempt_fd)
    finally:
        os.close(parent_fd)
