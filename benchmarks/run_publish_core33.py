"""Explicitly run or replay the named core33 comparison publication."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks import comparison_batch, comparison_publish, run_comparison
from benchmarks.comparison_batch import BatchGroup, BatchResult, DispatchReceipt
from benchmarks.comparison_seed import _check_destination, prepare_seed_plan
from benchmarks.comparison_seed_execution import (
    _check_visible,
    _private_parent,
    create_private_seed,
)

MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
PLAN_PATHS = frozenset({"python", "database", "output_root", "backend_path"})
PRIVATE_EVIDENCE = ("events.jsonl", "raw-manifest.json", "batch-result.json")
OTHER_EVENTS = frozenset(
    {
        "output_parent_created",
        "batch_call_start",
        "measuring_child_success",
        "batch_call_success",
        "final_verified",
    }
)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Refuse ambiguous duplicate JSON object keys.

    Args:
        pairs: Parsed key and value pairs in one JSON object.

    Returns:
        Dictionary with unique keys.

    Raises:
        ValueError: If a key occurs more than once.
    """
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate evidence key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    """Refuse non-finite JSON spellings before any replay step.

    Args:
        value: Invalid JSON numeric token.

    Raises:
        ValueError: Always; non-finite metrics cannot be published.
    """
    raise ValueError(f"non-finite evidence token: {value}")


def _decode_json(data: bytes) -> Any:
    """Parse strict UTF-8 JSON without duplicate keys or non-finite numbers.

    Args:
        data: Bounded held regular-file bytes.

    Returns:
        Parsed JSON value.

    Raises:
        ValueError: If the JSON is ambiguous or invalid.
    """
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_constant=_invalid_constant,
    )


def _read_evidence(path: Path) -> bytes:
    """Read one bounded regular evidence file without following a link or FIFO.

    Args:
        path: Explicit external evidence path.

    Returns:
        Held bytes after visible identity remains stable.

    Raises:
        ValueError: If path, type, size, or identity is unsafe.
    """
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("replay evidence needs an absolute unambiguous path")
    visible = path.lstat()
    if not stat.S_ISREG(visible.st_mode) or visible.st_size > MAX_EVIDENCE_BYTES:
        raise ValueError("replay evidence must be a bounded regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        held = os.fstat(stream.fileno())
        if not stat.S_ISREG(held.st_mode) or (visible.st_dev, visible.st_ino) != (
            held.st_dev,
            held.st_ino,
        ):
            raise ValueError("replay evidence changed during acquisition")
        data = stream.read(MAX_EVIDENCE_BYTES + 1)
        after = path.lstat()
        if len(data) > MAX_EVIDENCE_BYTES or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) != (held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns):
            raise ValueError("replay evidence changed during reading")
    return data


def _path(value: object) -> Path:
    """Require one absolute, unreduced witness path without probing it.

    Args:
        value: Serialized path.

    Returns:
        Typed path for existing shared validation.

    Raises:
        ValueError: If the path is relative or contains parent traversal.
    """
    if type(value) is not str or not value or "\x00" in value:
        raise ValueError("evidence path is malformed")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence path is not absolute and unambiguous")
    return path


def _schema_base(value: object) -> Path:
    """Require an explicit absolute benchmark directory witness.

    Args:
        value: Recorded schema checkout directory.

    Returns:
        Validated lexical benchmark directory path.

    Raises:
        ValueError: If the context is missing or malformed.
    """
    base = _path(value)
    if base.name != "benchmarks":
        raise ValueError("schema context is not a benchmark directory")
    return base


def _plan(value: object) -> run_comparison.RunPlan:
    """Restore one exact RunPlan shape without a current runtime probe.

    Args:
        value: Journal plan object.

    Returns:
        Typed plan for the existing publisher validator.

    Raises:
        ValueError: If fields, types, or paths are malformed.
    """
    names = {field.name for field in fields(run_comparison.RunPlan)}
    if type(value) is not dict or set(value) != names:
        raise ValueError("journal RunPlan fields differ from the contract")
    typed = dict(value)
    for name in PLAN_PATHS:
        typed[name] = _path(typed[name])
    if type(typed["authors"]) is not int or typed["authors"] not in (1000, 2000):
        raise ValueError("journal author count is invalid")
    if (
        any(
            type(typed[name]) is not str or not typed[name]
            for name in names - PLAN_PATHS - {"authors", "packages"}
        )
        or type(typed["packages"]) is not dict
        or not typed["packages"]
        or any(
            type(key) is not str or type(item) is not str
            for key, item in typed["packages"].items()
        )
    ):
        raise ValueError("journal RunPlan values are malformed")
    return run_comparison.RunPlan(**typed)


def _group(value: object) -> BatchGroup:
    """Restore one recorded median group without trusting its arithmetic.

    Args:
        value: Serialized group object.

    Returns:
        Typed group for publisher recomputation.

    Raises:
        ValueError: If group shape, paths, or primitive types differ.
    """
    names = {field.name for field in fields(BatchGroup)}
    if type(value) is not dict or set(value) != names:
        raise ValueError("recorded median group fields differ")
    typed = dict(value)
    paths = typed["raw_paths"]
    if type(paths) is not list or len(paths) != 3:
        raise ValueError("recorded median group needs three raw paths")
    typed["raw_paths"] = tuple(_path(path) for path in paths)
    if (
        type(typed["authors"]) is not int
        or type(typed["median"]) is not dict
        or any(
            type(typed[name]) is not str
            for name in names - {"authors", "median", "raw_paths"}
        )
    ):
        raise ValueError("recorded median group values are malformed")
    return BatchGroup(**typed)


def _receipt(value: object) -> DispatchReceipt:
    """Restore one optional serialized live receipt.

    Args:
        value: Receipt object embedded in a newer batch record.

    Returns:
        Typed receipt for exact cross-file comparison.

    Raises:
        ValueError: If receipt shape or primitive types differ.
    """
    names = {"number", "plan", "raw_path", "sha256"}
    if type(value) is not dict or set(value) not in (names, names | {"schema_base"}):
        raise ValueError("embedded receipt fields differ")
    if type(value["number"]) is not int or type(value["sha256"]) is not str:
        raise ValueError("embedded receipt values are malformed")
    return DispatchReceipt(
        value["number"],
        _plan(value["plan"]),
        _path(value["raw_path"]),
        value["sha256"],
        _schema_base(value["schema_base"])
        if value.get("schema_base") is not None
        else None,
    )


def _child_schema_base(event: dict[str, Any], plan: run_comparison.RunPlan) -> Path:
    """Corroborate an old measuring-child invocation against its dispatch plan.

    Args:
        event: Retained actual child-start journal record.
        plan: Immediately preceding exact dispatch plan.

    Returns:
        Original benchmark directory from the recorded child cwd.

    Raises:
        ValueError: If argv, environment or cwd contradicts the plan.
    """
    base = _schema_base(event.get("cwd"))
    argv = event.get("argv")
    environment = event.get("env")
    expected = {
        "PYTHONPATH": f"{base.parent}:{base}",
        "BENCH_LIB": plan.library,
        "BENCH_DATABASE": str(plan.database),
        "BENCH_AUTHORS": str(plan.authors),
        "BENCH_PROFILE": plan.profile,
        "BENCH_OUTPUT_DIR": str(plan.output_root),
    }
    if (
        type(argv) is not list
        or argv != [str(plan.python), str(base / "harness.py")]
        or type(environment) is not dict
        or any(environment.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("recorded measuring child context differs from plan")
    return base


def load_replay(
    events: Path, manifest: Path, batch_result: Path
) -> tuple[BatchResult, tuple[DispatchReceipt, ...]]:
    """Reconstruct exact typed evidence without probing live source or runtime.

    The existing publisher subsequently rehashes all 24 raws and recomputes
    all eight medians before any public stage is created.

    Args:
        events: Retained JSONL dispatch journal.
        manifest: Retained ordered raw path and digest manifest.
        batch_result: Retained eight-group unpublished batch result.

    Returns:
        Legacy-compatible batch and exact ordered explicit receipts.

    Raises:
        ValueError: If event, manifest, or batch witnesses are incomplete or drifted.
    """
    lines = _read_evidence(events).splitlines()
    if not lines or len(lines) > 256:
        raise ValueError("dispatch journal has an invalid record count")
    starts: dict[int, run_comparison.RunPlan] = {}
    successes: dict[int, tuple[Path, str]] = {}
    contexts: dict[int, Path] = {}
    preflight_source: tuple[str, str] | None = None
    for line in lines:
        event = _decode_json(line)
        if type(event) is not dict or type(event.get("kind")) is not str:
            raise ValueError("dispatch journal event is malformed")
        kind = event["kind"]
        if kind in OTHER_EVENTS:
            continue
        if kind == "preflight":
            source = (event.get("source_commit"), event.get("source_tree"))
            if preflight_source is not None or any(
                type(item) is not str for item in source
            ):
                raise ValueError("recorded preflight source is missing or duplicated")
            preflight_source = source
            continue
        if kind in {"schema_context", "measuring_child_start"}:
            number = event.get("number")
            if (
                type(number) is not int
                or number not in starts
                or number in successes
                or number in contexts
            ):
                raise ValueError("recorded schema context is missing or duplicated")
            plan = starts[number]
            if kind == "measuring_child_start":
                base = _child_schema_base(event, plan)
            else:
                if set(event) != {
                    "kind",
                    "number",
                    "schema_base",
                    "commit",
                    "tree",
                } or (event["commit"], event["tree"]) != (
                    plan.commit,
                    plan.tree,
                ):
                    raise ValueError("explicit schema context differs from plan")
                base = _schema_base(event["schema_base"])
            contexts[number] = base
            continue
        if kind not in {"dispatch_start", "dispatch_success"}:
            raise ValueError("dispatch journal contains an unknown event")
        allowed = {"kind", "number", "utc", "monotonic_ns"}
        required = {"kind", "number"}
        if kind == "dispatch_start":
            allowed.add("plan")
            required.add("plan")
        else:
            allowed.update({"raw_path", "raw_sha256"})
            required.update({"raw_path", "raw_sha256"})
        if not required <= set(event) or not set(event) <= allowed:
            raise ValueError("dispatch journal fields differ")
        number = event["number"]
        if type(number) is not int or not 1 <= number <= 24:
            raise ValueError("dispatch number is invalid")
        if kind == "dispatch_start":
            if number != len(starts) + 1:
                raise ValueError(
                    "dispatch starts are missing, duplicated, or reordered"
                )
            starts[number] = _plan(event["plan"])
        else:
            if (
                number not in starts
                or number not in contexts
                or number != len(successes) + 1
            ):
                raise ValueError(
                    "dispatch success is missing, duplicated, or reordered"
                )
            if type(event["raw_sha256"]) is not str:
                raise ValueError("dispatch digest is malformed")
            successes[number] = (_path(event["raw_path"]), event["raw_sha256"])
    if len(starts) != 24 or len(successes) != 24 or len(contexts) != 24:
        raise ValueError("dispatch journal is incomplete")
    if preflight_source is not None and any(
        (plan.commit, plan.tree) != preflight_source for plan in starts.values()
    ):
        raise ValueError("recorded preflight source differs from dispatch plans")
    if len(set(contexts.values())) != 1:
        raise ValueError("recorded dispatches use mixed schema checkouts")
    receipts = tuple(
        DispatchReceipt(number, starts[number], *successes[number], contexts[number])
        for number in range(1, 25)
    )
    raw_manifest = _decode_json(_read_evidence(manifest))
    if type(raw_manifest) is not list or len(raw_manifest) != 24:
        raise ValueError("raw manifest needs exactly 24 records")
    for number, row in enumerate(raw_manifest, 1):
        if (
            type(row) is not dict
            or set(row) != {"number", "path", "sha256"}
            or type(row["number"]) is not int
            or type(row["sha256"]) is not str
            or (row["number"], _path(row["path"]), row["sha256"])
            != (number, receipts[number - 1].raw_path, receipts[number - 1].sha256)
        ):
            raise ValueError("raw manifest differs from the dispatch journal")
    recorded = _decode_json(_read_evidence(batch_result))
    if type(recorded) is not dict or set(recorded) not in (
        {"groups", "dispatch_order"},
        {"groups", "dispatch_order", "receipts"},
    ):
        raise ValueError("batch result fields differ")
    if (
        type(recorded["groups"]) is not list
        or len(recorded["groups"]) != 8
        or type(recorded["dispatch_order"]) is not list
        or len(recorded["dispatch_order"]) != 24
    ):
        raise ValueError("batch result cardinality differs")
    groups = tuple(_group(value) for value in recorded["groups"])
    order = tuple(_path(value) for value in recorded["dispatch_order"])
    if order != tuple(receipt.raw_path for receipt in receipts):
        raise ValueError("batch raw order differs from the journal")
    embedded: tuple[DispatchReceipt, ...] = ()
    if "receipts" in recorded:
        value = recorded["receipts"]
        if type(value) is not list or len(value) != 24:
            raise ValueError("embedded receipts are incomplete")
        embedded = tuple(
            replace(_receipt(item), schema_base=contexts[number])
            if type(item) is dict and "schema_base" not in item
            else _receipt(item)
            for number, item in enumerate(value, 1)
        )
        if embedded != receipts:
            raise ValueError("embedded receipts differ from the journal")
    return BatchResult(groups, order, embedded), receipts


def _private_root(path: Path, venv_root: Path) -> None:
    """Require an existing owner-only external parent before live work.

    Args:
        path: Caller-selected private directory.
        venv_root: Existing named interpreter directory.

    Raises:
        ValueError: If the directory overlaps checkout or environments.
    """
    if not venv_root.is_absolute() or not venv_root.is_dir():
        raise ValueError("an absolute named environment root is required")
    descriptor = _private_parent(path)
    os.close(descriptor)
    if path.is_relative_to(run_comparison.ROOT.resolve()) or path.is_relative_to(
        venv_root.resolve()
    ):
        raise ValueError("private parent overlaps source or environments")


def _write_evidence(parent: Path, batch: BatchResult) -> None:
    """Retain replayable complete-batch records without overwriting private files.

    These are generated after all dispatches pass, not a live timestamped event
    stream. Failures leave partial private records for manual inspection.

    Args:
        parent: Existing owner-only raw output parent.
        batch: Validated complete batch with 24 live receipts.

    Raises:
        ValueError: If the batch lacks complete live receipts.
        OSError: If an evidence name is occupied or a write fails.
    """
    if len(batch.receipts) != 24:
        raise ValueError("complete live receipts are required before publication")
    events = []
    manifest = []
    for receipt in batch.receipts:
        if receipt.schema_base is None:
            raise ValueError("complete live receipts need checked schema context")
        events.extend(
            (
                {
                    "kind": "dispatch_start",
                    "number": receipt.number,
                    "plan": asdict(receipt.plan),
                },
                {
                    "kind": "schema_context",
                    "number": receipt.number,
                    "schema_base": receipt.schema_base,
                    "commit": receipt.plan.commit,
                    "tree": receipt.plan.tree,
                },
                {
                    "kind": "dispatch_success",
                    "number": receipt.number,
                    "raw_path": receipt.raw_path,
                    "raw_sha256": receipt.sha256,
                },
            )
        )
        manifest.append(
            {
                "number": receipt.number,
                "path": receipt.raw_path,
                "sha256": receipt.sha256,
            }
        )
    recorded = {
        "groups": [asdict(group) for group in batch.groups],
        "dispatch_order": batch.dispatch_order,
        "receipts": [asdict(receipt) for receipt in batch.receipts],
    }

    def encode(value: object) -> bytes:
        """Encode one private record with explicit path conversion.

        Args:
            value: Typed evidence structure.

        Returns:
            Finite UTF-8 JSON bytes.
        """
        return (
            json.dumps(
                value,
                default=lambda item: (
                    str(item) if isinstance(item, Path) else _reject_type(item)
                ),
                allow_nan=False,
                sort_keys=True,
            )
            + "\n"
        ).encode()

    payloads = (
        b"".join(encode(event) for event in events),
        encode(manifest),
        encode(recorded),
    )
    descriptor = _private_parent(parent)
    try:
        for name, data in zip(PRIVATE_EVIDENCE, payloads, strict=True):
            _check_visible(parent, descriptor, directory=True)
            file_descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=descriptor,
            )
            with os.fdopen(file_descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reject_type(value: object) -> None:
    """Reject unexpected serialized objects rather than silently stringify them.

    Args:
        value: Unsupported JSON payload value.

    Raises:
        TypeError: Always, to preserve an exact evidence schema.
    """
    raise TypeError(f"unsupported evidence value: {type(value).__name__}")


def run_publication(
    profile: str,
    authors: tuple[int, int],
    runs: int,
    venv_root: Path,
    seed_parent: Path,
    output_parent: Path,
    results_root: Path,
) -> Path:
    """Create fresh named seeds, measure once, retain receipts, then publish.

    This costly mode never resets an existing database or result. A failure
    retains all partial private state without automatic cleanup.

    Args:
        profile: Exact named profile.
        authors: Fixed two published workload sizes in order.
        runs: Fixed number of rotated repetitions.
        venv_root: Existing selected four-stack interpreter directory.
        seed_parent: Existing owner-only external seed destination parent.
        output_parent: Existing empty owner-only external raw output parent.
        results_root: Existing trusted public results parent.

    Returns:
        Newly installed complete eight-artifact directory.

    Raises:
        ValueError: If options, paths, source, runtime, or results differ.
        OSError: If exclusive private/public creation fails.
    """
    if (
        profile != "core33"
        or authors != (1000, 2000)
        or type(runs) is not int
        or runs != 3
    ):
        raise ValueError("run requires core33, authors 1000 2000, and three runs")
    comparison_publish._check_target(results_root)
    _private_root(seed_parent, venv_root)
    _private_root(output_parent, venv_root)
    if (
        seed_parent == output_parent
        or seed_parent.is_relative_to(output_parent)
        or output_parent.is_relative_to(seed_parent)
        or results_root.is_relative_to(seed_parent)
        or results_root.is_relative_to(output_parent)
        or seed_parent.is_relative_to(results_root)
        or output_parent.is_relative_to(results_root)
        or any(output_parent.iterdir())
    ):
        raise ValueError("private destinations must be distinct and output empty")
    destinations = tuple(seed_parent / f"seed-{count}" for count in authors)
    for destination in destinations:
        _check_destination(destination, venv_root)
    for name in PRIVATE_EVIDENCE:
        if (output_parent / name).exists() or (output_parent / name).is_symlink():
            raise ValueError("private evidence destination is occupied")
    plans = tuple(
        prepare_seed_plan(profile, venv_root, destination, count)
        for destination, count in zip(destinations, authors, strict=True)
    )
    seeds = tuple(create_private_seed(plan, venv_root) for plan in plans)
    batch = comparison_batch.run_batch(seeds, venv_root, output_parent)
    _write_evidence(output_parent, batch)
    return comparison_publish.publish_core33(batch, batch.receipts, results_root)


def replay_publication(
    profile: str, events: Path, manifest: Path, batch_result: Path, results_root: Path
) -> Path:
    """Publish from explicit retained records without current runtime probes.

    Args:
        profile: Exact named profile.
        events: Retained dispatch journal.
        manifest: Retained raw path and digest manifest.
        batch_result: Retained unpublished eight-group record.
        results_root: Existing trusted results parent with absent core33 child.

    Returns:
        Newly installed complete eight-artifact directory.

    Raises:
        ValueError: If options, records, raw results, or medians differ.
        OSError: If atomic no-clobber installation fails.
    """
    if profile != "core33":
        raise ValueError("replay requires the core33 profile")
    comparison_publish._check_target(results_root)
    batch, receipts = load_replay(events, manifest, batch_result)
    return comparison_publish.publish_core33(batch, receipts, results_root)


def make_parser() -> argparse.ArgumentParser:
    """Build explicit mutually exclusive run and replay subcommands.

    Returns:
        Parser with no implicit measurement or legacy fallback.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run", help="create new seeds and run 24 costly measurements"
    )
    run.add_argument("--profile", required=True, choices=("core33",))
    run.add_argument("--authors", type=int, nargs=2, required=True)
    run.add_argument("--runs", type=int, required=True)
    run.add_argument("--venv-root", type=Path, required=True)
    run.add_argument("--seed-parent", type=Path, required=True)
    run.add_argument("--output-parent", type=Path, required=True)
    run.add_argument("--results-root", type=Path, required=True)
    replay = commands.add_parser(
        "replay", help="validate retained evidence without measuring"
    )
    replay.add_argument("--profile", required=True, choices=("core33",))
    replay.add_argument("--events", type=Path, required=True)
    replay.add_argument("--raw-manifest", type=Path, required=True)
    replay.add_argument("--batch-result", type=Path, required=True)
    replay.add_argument("--results-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run only the selected explicit named-profile mode.

    Args:
        argv: Optional command tokens; defaults to process arguments.

    Raises:
        ValueError: If selected records or destinations fail their contracts.
    """
    args = make_parser().parse_args(argv)
    if args.command == "run":
        target = run_publication(
            args.profile,
            tuple(args.authors),
            args.runs,
            args.venv_root,
            args.seed_parent,
            args.output_parent,
            args.results_root,
        )
    else:
        target = replay_publication(
            args.profile,
            args.events,
            args.raw_manifest,
            args.batch_result,
            args.results_root,
        )
    print(target)


if __name__ == "__main__":
    main()
