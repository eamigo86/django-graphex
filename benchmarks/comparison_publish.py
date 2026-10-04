"""Stage and atomically install one portable core33 comparison bundle."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from . import run_comparison
from .comparison_batch import (
    LIBRARIES,
    BatchGroup,
    BatchResult,
    DispatchReceipt,
    _digest_regular,
    _read_raw,
)
from .comparison_seed_execution import _rename_noreplace
from .comparison_statistics import aggregate_three

SCHEMA = "django-graphex.core33.comparison.v1"
AUTHOR_COUNTS = (1000, 2000)
GROUP_KEYS = tuple(
    (authors, library) for authors in AUTHOR_COUNTS for library in LIBRARIES
)
ROTATIONS = (
    LIBRARIES,
    LIBRARIES[1:] + LIBRARIES[:1],
    LIBRARIES[2:] + LIBRARIES[:2],
)
FILENAMES = {
    (authors, library): f"{'2x_' if authors == 2000 else ''}{library}.json"
    for authors, library in GROUP_KEYS
}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PORTABLE_TEXT = re.compile(r"[A-Za-z0-9_.+-]{1,120}\Z")
SERIES_NAME = re.compile(r"core33(?:-[A-Za-z0-9][A-Za-z0-9._-]{0,119})?\Z")


def _hex(value: object, pattern: re.Pattern[str]) -> bool:
    """Check one full lowercase hexadecimal identity.

    Args:
        value: Candidate identity.
        pattern: Exact-width compiled hexadecimal pattern.

    Returns:
        Whether the identity has the required width and case.
    """
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _public_machine(value: object) -> dict[str, str | int]:
    """Keep only nonidentifying platform and CPU facts.

    Args:
        value: Raw machine witness.

    Returns:
        Narrow portable machine projection.

    Raises:
        ValueError: If a public field could contain a path or identifier.
    """
    if not isinstance(value, dict):
        raise ValueError("raw machine witness is missing")
    platform = value.get("platform")
    cpu_count = value.get("cpu_count")
    if (
        not isinstance(platform, str)
        or PORTABLE_TEXT.fullmatch(platform) is None
        or type(cpu_count) is not int
        or not 1 <= cpu_count <= 1024
    ):
        raise ValueError("machine facts are not portable")
    return {"platform": platform, "cpu_count": cpu_count}


def _portable_versions(value: object) -> dict[str, str]:
    """Reject path-like or identifying text from selected stack versions.

    Args:
        value: Shared-validated whole-stack version dictionary.

    Returns:
        Independent public version dictionary.

    Raises:
        ValueError: If a version is not compact portable text.
    """
    if not isinstance(value, dict) or not value:
        raise ValueError("whole-stack versions are missing")
    if any(
        not isinstance(name, str)
        or PORTABLE_TEXT.fullmatch(name) is None
        or not isinstance(version, str)
        or PORTABLE_TEXT.fullmatch(version) is None
        for name, version in value.items()
    ):
        raise ValueError("whole-stack versions are not portable")
    return dict(value)


def _check_target(results_root: Path, series: str = "core33") -> Path:
    """Require an external results parent and one absent core33 series name.

    Args:
        results_root: Existing result directory; never created here.
        series: Single portable child name; defaults to the historical target.

    Returns:
        Still-absent selected destination.

    Raises:
        ValueError: If the parent is linked, relative, or occupied.
    """
    if type(series) is not str or SERIES_NAME.fullmatch(series) is None:
        raise ValueError("core33 series needs one safe child name")
    if (
        not results_root.is_absolute()
        or results_root != results_root.resolve()
        or results_root.is_symlink()
        or not results_root.is_dir()
        or results_root.name != "results"
    ):
        raise ValueError("an existing unlinked absolute results parent is required")
    target = results_root / series
    try:
        target.lstat()
    except FileNotFoundError:
        return target
    raise ValueError("core33 publication target is already occupied")


def _read_receipts(
    batch: BatchResult, receipts: Sequence[DispatchReceipt]
) -> dict[tuple[int, str], list[tuple[DispatchReceipt, dict[str, Any]]]]:
    """Validate the complete ordered private raw batch before any public write.

    Args:
        batch: Detached unpublished result from the original batch.
        receipts: Exactly one typed receipt per raw dispatch in execution order.

    Returns:
        Eight groups of verified receipt and raw pairs.

    Raises:
        ValueError: If order, bytes, source, stack, machine, or shape drifts.
    """
    if (
        type(batch) is not BatchResult
        or len(batch.dispatch_order) != 24
        or len(receipts) != 24
    ):
        raise ValueError("publisher requires exactly 24 completed raw dispatches")
    if batch.receipts and tuple(receipts) != batch.receipts:
        raise ValueError("explicit receipts differ from the live batch")
    groups: dict[tuple[int, str], list[tuple[DispatchReceipt, dict[str, Any]]]] = {
        key: [] for key in GROUP_KEYS
    }
    source: tuple[str, str, str, str, str, str] | None = None
    profiles: dict[str, tuple[Path, Path, str, tuple[tuple[str, str], ...]]] = {}
    databases: dict[int, Path] = {}
    machine: dict[str, Any] | None = None
    used_paths: set[Path] = set()
    schema_base: Path | None = None
    for number, receipt in enumerate(receipts, 1):
        if (
            type(receipt) is not DispatchReceipt
            or type(receipt.plan) is not run_comparison.RunPlan
        ):
            raise ValueError("dispatch receipt or plan has an unexpected type")
        plan = receipt.plan
        if receipt.schema_base is not None and (
            not isinstance(receipt.schema_base, Path)
            or not receipt.schema_base.is_absolute()
            or receipt.schema_base.name != "benchmarks"
        ):
            raise ValueError("receipt schema context is malformed")
        if number == 1:
            schema_base = receipt.schema_base
        elif receipt.schema_base != schema_base:
            raise ValueError("receipts use mixed schema checkouts")
        authors = AUTHOR_COUNTS[(number - 1) // 12]
        repetition = ((number - 1) % 12) // 4
        library = ROTATIONS[repetition][(number - 1) % 4]
        if (
            type(receipt.number) is not int
            or receipt.number != number
            or type(plan.authors) is not int
            or (plan.authors, plan.library, plan.profile)
            != (authors, library, "core33")
            or receipt.raw_path != batch.dispatch_order[number - 1]
            or receipt.raw_path in used_paths
            or receipt.raw_path != plan.output_root / f"{library}.json"
            or plan.output_root.name != f"seed-{authors}-r{repetition + 1}-{library}"
            or not receipt.raw_path.is_absolute()
            or not _hex(receipt.sha256, HEX64)
        ):
            raise ValueError("receipt order, profile, path, or digest is invalid")
        used_paths.add(receipt.raw_path)
        current_source = (
            plan.commit,
            plan.tree,
            plan.source_version,
            plan.manifest_sha256,
            plan.python_version,
            plan.packages.get("django", ""),
        )
        if (
            not _hex(plan.commit, HEX40)
            or not _hex(plan.tree, HEX40)
            or not _hex(plan.manifest_sha256, HEX64)
            or not _hex(plan.constraints_sha256, HEX64)
            or PORTABLE_TEXT.fullmatch(plan.source_version) is None
            or PORTABLE_TEXT.fullmatch(plan.python_version) is None
        ):
            raise ValueError("measurement source identity is malformed")
        if source is None:
            source = current_source
        elif current_source != source:
            raise ValueError("measurement source or common runtime differs")
        profile = (
            plan.python,
            plan.backend_path,
            plan.constraints_sha256,
            tuple(sorted(plan.packages.items())),
        )
        previous_profile = profiles.setdefault(library, profile)
        if profile != previous_profile:
            raise ValueError("one library has mixed runtime or freeze")
        previous_database = databases.setdefault(authors, plan.database)
        if previous_database != plan.database:
            raise ValueError("one seed size has mixed databases")
        raw, digest = _read_raw(receipt.raw_path, plan, receipt.schema_base)
        if digest != receipt.sha256:
            raise ValueError("raw bytes differ from dispatch receipt")
        if machine is None:
            machine = raw["machine"]
        elif raw["machine"] != machine:
            raise ValueError("machine differs across libraries or seeds")
        groups[(authors, library)].append((receipt, raw))
    return groups


def _artifacts(
    batch: BatchResult,
    groups: dict[tuple[int, str], list[tuple[DispatchReceipt, dict[str, Any]]]],
) -> dict[str, bytes]:
    """Recompute all medians and project only public allowlisted fields.

    Args:
        batch: Recorded detached batch result.
        groups: Shared-validated receipt and raw triples.

    Returns:
        Exactly eight ready-to-write portable JSON byte strings.

    Raises:
        ValueError: If group identities, medians, or public fields differ.
    """
    if len(batch.groups) != 8:
        raise ValueError("publisher requires exactly eight median groups")
    seed_sources: dict[int, tuple[str, str, str]] = {}
    artifacts = {}
    for key, group in zip(GROUP_KEYS, batch.groups, strict=True):
        if type(group) is not BatchGroup or (group.authors, group.library) != key:
            raise ValueError("median group is missing, duplicated, or reordered")
        triple = groups[key]
        if len(triple) != 3:
            raise ValueError("median group lacks three raw runs")
        receipts = [receipt for receipt, _ in triple]
        first_plan = receipts[0].plan
        if (
            group.raw_paths != tuple(receipt.raw_path for receipt in receipts)
            or any(
                replace(receipt.plan, output_root=first_plan.output_root) != first_plan
                for receipt in receipts
            )
            or (group.source_commit, group.source_tree)
            != (first_plan.commit, first_plan.tree)
            or not _hex(group.seed_commit, HEX40)
            or not _hex(group.seed_tree, HEX40)
            or not _hex(group.seed_sha256, HEX64)
        ):
            raise ValueError("median group provenance or raw mapping differs")
        seed = (group.seed_commit, group.seed_tree, group.seed_sha256)
        previous_seed = seed_sources.setdefault(group.authors, seed)
        if seed != previous_seed:
            raise ValueError("one seed size has mixed source or bytes")
        if any(receipt.schema_base != receipts[0].schema_base for receipt in receipts):
            raise ValueError("median group has mixed schema checkout context")
        computed = aggregate_three(
            first_plan, [raw for _, raw in triple], receipts[0].schema_base
        )
        if group.median != computed:
            raise ValueError("recorded median differs from raw result math")
        machine = _public_machine(computed["machine"])
        versions = _portable_versions(computed["versions"])
        payload = {
            "schema": SCHEMA,
            "profile": "core33",
            "library": group.library,
            "dataset": deepcopy(computed["dataset"]),
            "whole_stack": {
                "versions": versions,
                "python": first_plan.python_version,
                "django": first_plan.packages["django"],
            },
            "machine": machine,
            "surface": deepcopy(computed["surface"]),
            "operations": deepcopy(computed["ops"]),
            "schema_import_ms": computed["schema_import_ms"],
            "schema_rebuild_diagnostic_ms": deepcopy(
                computed["schema_rebuild_samples_ms"]
            ),
            "aggregation": deepcopy(computed["aggregation"]),
            "measurement_source": {
                "commit": first_plan.commit,
                "tree": first_plan.tree,
                "version": first_plan.source_version,
                "manifest_sha256": first_plan.manifest_sha256,
                "constraints_sha256": first_plan.constraints_sha256,
            },
            "seed_source": {
                "commit": group.seed_commit,
                "tree": group.seed_tree,
                "sha256": group.seed_sha256,
            },
            "raw_sha256": [receipt.sha256 for receipt in receipts],
        }
        artifacts[FILENAMES[key]] = (
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        ).encode()
    return artifacts


def _check_stage(stage: Path, expected: dict[str, bytes]) -> None:
    """Reopen each staged regular file and verify every exact public byte.

    Args:
        stage: Unique private directory on the target filesystem.
        expected: Already validated eight-file public projection.

    Raises:
        ValueError: If stage contents or a file's identity changed.
    """
    if set(os.listdir(stage)) != set(expected):
        raise ValueError("staged bundle is incomplete or contains extra files")
    for name, data in expected.items():
        path = stage / name
        visible = path.lstat()
        if not stat.S_ISREG(visible.st_mode) or visible.st_nlink != 1:
            raise ValueError("staged artifact is not a single-linked regular file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            held = os.fstat(stream.fileno())
            observed = stream.read()
        if (
            (visible.st_dev, visible.st_ino) != (held.st_dev, held.st_ino)
            or observed != data
            or json.loads(observed) != json.loads(data)
            or (path.lstat().st_dev, path.lstat().st_ino) != (held.st_dev, held.st_ino)
        ):
            raise ValueError("staged artifact bytes or identity changed")


def _check_stage_identity(stage: Path, descriptor: int) -> None:
    """Reject a stage name that no longer identifies its held directory.

    Args:
        stage: Visible staging name.
        descriptor: Open descriptor acquired immediately after creation.

    Raises:
        ValueError: If the staging directory was replaced or linked.
    """
    try:
        visible = stage.lstat()
        held = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError("staged bundle changed") from exc
    if not stat.S_ISDIR(visible.st_mode) or (visible.st_dev, visible.st_ino) != (
        held.st_dev,
        held.st_ino,
    ):
        raise ValueError("staged bundle changed")


def publish_core33(
    batch: BatchResult,
    receipts: Sequence[DispatchReceipt],
    results_root: Path,
    series: str = "core33",
) -> Path:
    """Atomically install eight portable core33 medians from retained raw bytes.

    This does not run a child, open a seed database, or change historical JSON.
    A failed or uncertain stage remains for recovery; it is never automatically
    removed. Path checks bound ordinary drift, not a same-user filesystem
    sandbox or an attestation of every loaded byte. The first acquired descriptor
    checks continuity from acquisition; it does not prove creator ownership.
    An empty foreign directory substituted before acquisition can receive the
    exclusive writes and be installed. Callers need a trusted results parent
    without concurrent path substitution.

    Args:
        batch: Complete unpublished batch with eight recorded median groups.
        receipts: Twenty-four numbered raw-path, plan, and byte-digest records.
        results_root: Existing results directory for a new core33 child.
        series: Fresh single-directory series name; defaults to core33.

    Returns:
        Newly installed core33 directory containing exactly eight files.

    Raises:
        ValueError: If provenance, raw bytes, medians, portability, or target fails.
        OSError: If staging or atomic no-clobber installation fails.
    """
    target = _check_target(results_root, series)
    groups = _read_receipts(batch, receipts)
    artifacts = _artifacts(batch, groups)
    stage = Path(tempfile.mkdtemp(prefix=".core33-stage-", dir=results_root))
    descriptor = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _check_stage_identity(stage, descriptor)
        for name, data in artifacts.items():
            with (stage / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        _check_stage(stage, artifacts)
        if any(
            _digest_regular(receipt.raw_path) != receipt.sha256 for receipt in receipts
        ):
            raise ValueError(f"raw bytes changed; staged bundle retained at {stage}")
        _check_stage_identity(stage, descriptor)
        _check_stage(stage, artifacts)
        _check_target(results_root, series)
        _rename_noreplace(stage, target)
    finally:
        os.close(descriptor)
    return target
