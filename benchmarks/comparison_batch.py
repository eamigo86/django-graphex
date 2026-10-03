"""Run one unpublished rotated batch from two existing private seeds."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import run_comparison
from .comparison_seed import SeedPlan
from .comparison_seed_execution import PreparedSeed
from .comparison_statistics import aggregate_three

LIBRARIES = ("graphex", "graphene", "strawberry", "ariadne")
DATA_CONTRACT = (
    "benchmarks/benchapp/__init__.py",
    "benchmarks/benchapp/apps.py",
    "benchmarks/benchapp/models.py",
    "benchmarks/benchapp/management/__init__.py",
    "benchmarks/benchapp/management/commands/__init__.py",
    "benchmarks/benchapp/management/commands/seed_bench.py",
    "benchmarks/config/__init__.py",
    "benchmarks/config/settings.py",
    "benchmarks/comparison_profiles/core33/manifest.json",
    "benchmarks/comparison_profiles/core33/constraints/graphex.txt",
)


@dataclass(frozen=True)
class BatchGroup:
    """Hold one validated median and its three retained raw paths.

    The seed and current-source witnesses remain distinct.
    """

    authors: int
    library: str
    seed_sha256: str
    seed_commit: str
    seed_tree: str
    source_commit: str
    source_tree: str
    raw_paths: tuple[Path, Path, Path]
    median: dict[str, Any]


@dataclass(frozen=True)
class DispatchReceipt:
    """Bind one completed dispatch to its checked plan and retained raw bytes.

    A receipt corroborates local evidence; it is not a signed attestation or
    authority to rerun a workload or trust an arbitrary path.
    """

    number: int
    plan: run_comparison.RunPlan
    raw_path: Path
    sha256: str
    schema_base: Path | None = None


@dataclass(frozen=True)
class BatchResult:
    """Return eight detached groups without publishing any artifact.

    The dispatch order lists retained raw paths in execution order. New live
    batches include 24 checked receipts; the empty default keeps older
    two-field records and constructor calls compatible for explicit replay.
    """

    groups: tuple[BatchGroup, ...]
    dispatch_order: tuple[Path, ...]
    receipts: tuple[DispatchReceipt, ...] = ()


def _git(root: Path, *args: str) -> str:
    """Read one Git fact from an explicitly selected source checkout.

    Args:
        root: Source checkout containing the selected witness.
        *args: Read-only Git operation and arguments.

    Returns:
        Command output without trailing whitespace.
    """
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _compatible_seed_source(plan: SeedPlan, current: tuple[str, str]) -> None:
    """Require the seed's older commit to have identical data-contract blobs.

    Args:
        plan: Original immutable seed witness; it is never rewritten.
        current: Current committed source identity for measurement.

    Raises:
        ValueError: If checkout, ancestry, migrations, or data blobs differ.
    """
    old_root = plan.backend_path.parents[1]
    if (
        plan.backend_path != old_root / "django_graphex/__init__.py"
        or not plan.backend_path.is_file()
        or Path(_git(old_root, "rev-parse", "--show-toplevel")).resolve()
        != old_root.resolve()
        or _git(old_root, "rev-parse", "HEAD") != plan.commit
        or _git(old_root, "rev-parse", "HEAD^{tree}") != plan.tree
        or _git(old_root, "status", "--porcelain", "--untracked-files=normal")
        not in ("", "?? .codegraph/")
    ):
        raise ValueError("seed source witness is not the recorded clean checkout")
    if (
        _git(run_comparison.ROOT, "merge-base", plan.commit, current[0]) != plan.commit
        or _git(run_comparison.ROOT, "rev-parse", f"{plan.commit}^{{tree}}")
        != plan.tree
    ):
        raise ValueError("seed source is not a verified ancestor")
    for path in DATA_CONTRACT:
        old_blob = _git(run_comparison.ROOT, "rev-parse", f"{plan.commit}:{path}")
        current_blob = _git(run_comparison.ROOT, "rev-parse", f"{current[0]}:{path}")
        if old_blob != current_blob:
            raise ValueError(f"seed data contract changed: {path}")
    migration_path = "benchmarks/benchapp/migrations"
    if any(
        _git(run_comparison.ROOT, "ls-tree", "-r", revision, "--", migration_path)
        for revision in (plan.commit, current[0])
    ) or any(
        (root / migration_path).exists() for root in (old_root, run_comparison.ROOT)
    ):
        raise ValueError("seed migration overlay differs from the clean contract")
    old_version = tomllib.loads(
        _git(run_comparison.ROOT, "show", f"{plan.commit}:pyproject.toml")
    )["project"]["version"]
    if plan.source_version != old_version:
        raise ValueError("seed source version differs from its recorded commit")


def _digest_regular(path: Path) -> str:
    """Hash one existing unlinked regular file without blocking on a FIFO.

    Args:
        path: Prepared private seed database.

    Returns:
        SHA-256 digest of the held regular file.

    Raises:
        ValueError: If its visible or held identity is not a regular file.
    """
    visible = path.lstat()
    if not stat.S_ISREG(visible.st_mode):
        raise ValueError("seed database is not a regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        held = os.fstat(stream.fileno())
        if not stat.S_ISREG(held.st_mode) or (visible.st_dev, visible.st_ino) != (
            held.st_dev,
            held.st_ino,
        ):
            raise ValueError("seed database changed during acquisition")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.lstat()
        if not stat.S_ISREG(after.st_mode) or (after.st_dev, after.st_ino) != (
            held.st_dev,
            held.st_ino,
        ):
            raise ValueError("seed database changed during hashing")
        return digest


def _check_seed(
    seed: PreparedSeed, venv_root: Path
) -> tuple[str, tuple[tuple[str, int], ...]]:
    """Recheck one old-source seed without recreating or modifying it.

    Args:
        seed: Existing private seed and original source witness.
        venv_root: Exact named-profile environment root.

    Returns:
        Database digest and allocation sequence for drift comparisons.

    Raises:
        ValueError: If its file, plan, source, profile, or runtime drifted.
    """
    if type(seed) is not PreparedSeed or type(seed.plan) is not SeedPlan:
        raise ValueError("a prepared private seed is required")
    plan = seed.plan
    if (
        plan.profile != "core33"
        or plan.library != "graphex"
        or type(plan.authors) is not int
        or plan.authors not in (1000, 2000)
        or not venv_root.is_absolute()
        or not seed.database.is_absolute()
        or seed.database != plan.database
        or seed.database != plan.output_root / "db.sqlite3"
        or plan.python != venv_root / ".venv-core33-graphex/bin/python"
        or not plan.output_root.is_dir()
        or plan.output_root.is_symlink()
    ):
        raise ValueError("prepared seed fields differ from its named profile")
    if _digest_regular(seed.database) != seed.sha256:
        raise ValueError("prepared seed digest changed")
    parent = plan.output_root.parent
    if (
        plan.output_root != plan.output_root.resolve()
        or plan.output_root.is_relative_to(run_comparison.ROOT.resolve())
        or plan.output_root.is_relative_to(venv_root.resolve())
        or parent != parent.resolve()
    ):
        raise ValueError("prepared seed is not at a private external path")
    for path, directory in (
        (parent, True),
        (plan.output_root, True),
        (seed.database, False),
    ):
        info = path.lstat()
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if (
            not expected(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise ValueError("prepared seed is not an owner-only private asset")
    current = run_comparison._git_identity()
    _compatible_seed_source(plan, current)
    spec = run_comparison.load_profile("core33", "graphex", run_comparison.BASE)
    freeze = spec["constraints"].read_text()
    manifest = run_comparison.BASE / "comparison_profiles/core33/manifest.json"
    if (
        plan.python_version != spec["python"]
        or plan.django_version != spec["packages"]["django"]
        or plan.graphql_core_version != spec["packages"]["graphql-core"]
        or plan.freeze != freeze
        or plan.manifest_sha256 != hashlib.sha256(manifest.read_bytes()).hexdigest()
        or plan.constraints_sha256
        != hashlib.sha256(spec["constraints"].read_bytes()).hexdigest()
        or (plan.python.parent.parent / ".freeze.txt").read_text() != freeze
        or run_comparison._installed_freeze(plan.python, spec["constraints"], "graphex")
        != freeze
    ):
        raise ValueError("prepared seed freeze or profile changed")
    runtime = run_comparison._runtime_probe(
        plan.python, "graphex", seed.database, plan.authors
    )
    if runtime != {
        "python": plan.python_version,
        "django": plan.django_version,
        "graphql-core": plan.graphql_core_version,
        "backend_path": str(run_comparison.ROOT / "django_graphex/__init__.py"),
    }:
        raise ValueError("prepared seed runtime changed")
    run_comparison._check_database(seed.database, plan.authors)
    identity = run_comparison._database_identity(seed.database)
    if identity[0] != seed.sha256 or _digest_regular(seed.database) != seed.sha256:
        raise ValueError("prepared seed digest or SQLite sequence changed")
    return identity


def _private_output_parent(
    parent: Path, venv_root: Path, seeds: tuple[PreparedSeed, ...]
) -> int:
    """Hold an owner-only external output parent without creating it.

    Args:
        parent: Already existing external directory for all 24 outputs.
        venv_root: Protected named-profile environment root.
        seeds: Protected prepared database records.

    Returns:
        Held directory descriptor for later visible-identity checks.

    Raises:
        ValueError: If the parent is linked, occupied, or overlaps assets.
    """
    if (
        not parent.is_absolute()
        or parent != parent.resolve()
        or parent.is_symlink()
        or not parent.is_dir()
    ):
        raise ValueError("batch output parent must be an existing absolute directory")
    if (
        parent.is_relative_to(run_comparison.ROOT.resolve())
        or parent.is_relative_to(venv_root.resolve())
        or any(
            parent.is_relative_to(seed.database.parent.parent.resolve())
            for seed in seeds
        )
    ):
        raise ValueError("batch output parent overlaps protected assets")
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _same_parent(parent, descriptor)
        held = os.fstat(descriptor)
        if held.st_uid != os.getuid() or stat.S_IMODE(held.st_mode) & 0o077:
            raise ValueError("batch output parent must be owner-only")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _same_parent(parent: Path, descriptor: int) -> None:
    """Reject a visible output parent that no longer names the held directory.

    Args:
        parent: Visible output root.
        descriptor: Previously acquired directory descriptor.

    Raises:
        ValueError: If it was replaced or linked.
    """
    visible, held = parent.lstat(), os.fstat(descriptor)
    if not stat.S_ISDIR(visible.st_mode) or (visible.st_dev, visible.st_ino) != (
        held.st_dev,
        held.st_ino,
    ):
        raise ValueError("batch output parent changed")


def _read_raw(
    path: Path, plan: run_comparison.RunPlan, schema_base: Path | None = None
) -> tuple[dict[str, Any], str]:
    """Read and revalidate one retained regular JSON result without following links.

    Args:
        path: Exact path returned by the verified single-run dispatcher.
        plan: Current-source run plan for this output.
        schema_base: Explicit recorded benchmark directory for replay.

    Returns:
        Parsed raw result and held-byte digest for later drift checks.

    Raises:
        ValueError: If file identity, shape, or provenance differs.
    """
    if path != plan.output_root / f"{plan.library}.json":
        raise ValueError("single-run returned an unexpected raw path")
    visible = path.lstat()
    if not stat.S_ISREG(visible.st_mode):
        raise ValueError("raw result is not a regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        held = os.fstat(stream.fileno())
        if not stat.S_ISREG(held.st_mode) or (visible.st_dev, visible.st_ino) != (
            held.st_dev,
            held.st_ino,
        ):
            raise ValueError("raw result changed during acquisition")
        data = stream.read()
        raw = json.loads(data)
        after = path.lstat()
        if not stat.S_ISREG(after.st_mode) or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) != (held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns):
            raise ValueError("raw result changed during validation")
    if not isinstance(raw, dict):
        raise ValueError("raw result is not a JSON object")
    run_comparison.validate_result(plan, raw, schema_base)
    return raw, hashlib.sha256(data).hexdigest()


def run_batch(
    seeds: tuple[PreparedSeed, PreparedSeed], venv_root: Path, output_parent: Path
) -> BatchResult:
    """Dispatch 24 rotated raw runs and return eight unpublished medians.

    Existing private seeds are read-only. All raw outputs and failed partial
    attempts remain at their distinct caller-owned external destinations.
    Visible-path checks bound ordinary substitutions, not a universal
    same-user filesystem sandbox or creator-ownership receipt.

    Args:
        seeds: Exactly the 1,000- and 2,000-author prepared Graphex seeds.
        venv_root: Existing root of four named-profile interpreters.
        output_parent: Existing owner-only external directory for raw runs.

    Returns:
        Detached medians, raw paths and exact receipts after all 24 runs pass.

    Raises:
        ValueError: If source, seeds, outputs, runtime, or results drift.
        OSError: If a fresh output cannot be acquired safely.
        subprocess.CalledProcessError: If a measuring child fails.
    """
    parent_fd = _private_output_parent(output_parent, venv_root, seeds)
    try:
        if len(seeds) != 2 or tuple(seed.plan.authors for seed in seeds) != (
            1000,
            2000,
        ):
            raise ValueError("batch requires ordered 1000- and 2000-author seeds")
        source = run_comparison._git_identity()
        baseline = tuple(_check_seed(seed, venv_root) for seed in seeds)
        schedule = tuple(
            (seed, repetition, LIBRARIES[(index + repetition) % 4])
            for seed in seeds
            for repetition in range(3)
            for index in range(4)
        )
        destinations = tuple(
            output_parent / f"seed-{seed.plan.authors}-r{repetition + 1}-{library}"
            for seed, repetition, library in schedule
        )
        for destination in destinations:
            try:
                destination.lstat()
            except FileNotFoundError:
                continue
            raise ValueError("batch raw output destination is occupied")
        groups: dict[
            tuple[int, str], list[tuple[run_comparison.RunPlan, Path, dict[str, Any]]]
        ] = {
            (seed.plan.authors, library): [] for seed in seeds for library in LIBRARIES
        }
        order: list[Path] = []
        receipts: list[DispatchReceipt] = []
        raw_digests: dict[Path, str] = {}
        machine_reference: dict[str, Any] | None = None
        for (seed, _repetition, library), destination in zip(schedule, destinations):
            _same_parent(output_parent, parent_fd)
            if (
                run_comparison._git_identity() != source
                or _check_seed(seed, venv_root)
                != baseline[0 if seed is seeds[0] else 1]
            ):
                raise ValueError("batch source or seed changed before dispatch")
            plan = run_comparison.prepare_run(
                "core33",
                library,
                venv_root,
                seed.database,
                destination,
                seed.plan.authors,
            )
            if (
                (plan.commit, plan.tree) != source
                or plan.profile != "core33"
                or plan.library != library
                or plan.database != seed.database
                or plan.output_root != destination
                or plan.authors != seed.plan.authors
                or plan.python != venv_root / f".venv-core33-{library}/bin/python"
            ):
                raise ValueError("batch run plan differs from selected source or stack")
            path = run_comparison.run_single(plan)
            order.append(path)
            _same_parent(output_parent, parent_fd)
            if (
                run_comparison._git_identity() != source
                or _check_seed(seed, venv_root)
                != baseline[0 if seed is seeds[0] else 1]
            ):
                raise ValueError("batch source or seed changed after dispatch")
            raw, raw_digest = _read_raw(path, plan)
            receipts.append(
                DispatchReceipt(
                    len(receipts) + 1, plan, path, raw_digest, run_comparison.BASE
                )
            )
            machine = raw.get("machine")
            if not isinstance(machine, dict) or not machine:
                raise ValueError("raw result has no machine witness")
            if machine_reference is None:
                machine_reference = machine
            elif machine != machine_reference:
                raise ValueError("machine differs across batch")
            groups[(seed.plan.authors, library)].append((plan, path, raw))
            raw_digests[path] = raw_digest
        if run_comparison._git_identity() != source or any(
            _check_seed(seed, venv_root) != before
            for seed, before in zip(seeds, baseline)
        ):
            raise ValueError("batch source or seed changed before aggregation")
        if any(_digest_regular(path) != digest for path, digest in raw_digests.items()):
            raise ValueError("raw result changed before aggregation")
        for rows in groups.values():
            run_comparison._check_measured_context(rows[0][0])
        medians: list[BatchGroup] = []
        for seed in seeds:
            for library in LIBRARIES:
                rows = groups[(seed.plan.authors, library)]
                if len(rows) != 3:
                    raise ValueError("batch has an incomplete raw group")
                first_plan = rows[0][0]
                if any(
                    replace(plan, output_root=first_plan.output_root) != first_plan
                    for plan, _, _ in rows
                ):
                    raise ValueError("batch run profiles differ within a raw group")
                median = aggregate_three(first_plan, [raw for _, _, raw in rows])
                medians.append(
                    BatchGroup(
                        authors=seed.plan.authors,
                        library=library,
                        seed_sha256=seed.sha256,
                        seed_commit=seed.plan.commit,
                        seed_tree=seed.plan.tree,
                        source_commit=source[0],
                        source_tree=source[1],
                        raw_paths=(rows[0][1], rows[1][1], rows[2][1]),
                        median=median,
                    )
                )
        _same_parent(output_parent, parent_fd)
        if run_comparison._git_identity() != source or any(
            _check_seed(seed, venv_root) != before
            for seed, before in zip(seeds, baseline)
        ):
            raise ValueError("batch source or seed changed after aggregation")
        if any(_digest_regular(path) != digest for path, digest in raw_digests.items()):
            raise ValueError("raw result changed after aggregation")
        for rows in groups.values():
            run_comparison._check_measured_context(rows[0][0])
        return BatchResult(tuple(medians), tuple(order), tuple(receipts))
    finally:
        os.close(parent_fd)
