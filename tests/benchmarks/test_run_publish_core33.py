"""Contracts for explicit named-profile run and read-only replay commands."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks import comparison_batch, comparison_publish, run_comparison
from benchmarks.comparison_batch import BatchResult
from benchmarks.run_publish_core33 import (
    _write_evidence,
    load_replay,
    make_parser,
    replay_publication,
    run_publication,
)
from tests.benchmarks.test_comparison_publish import _fixture


def test_command_requires_explicit_run_or_replay_mode() -> None:
    """Refuse an implicit measurement or legacy publisher fallback.

    Raises:
        AssertionError: If the command silently selects a costly mode.
    """
    parser = make_parser()
    with pytest.raises(SystemExit, match="2"):
        parser.parse_args([])


def _evidence(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Make complete private synthetic records with no measuring child.

    Args:
        tmp_path: Test-owned external scratch root.

    Returns:
        Events, manifest, batch and public-parent paths.
    """
    batch, receipts, results = _fixture(tmp_path)
    private = tmp_path / "evidence"
    private.mkdir(mode=0o700)
    _write_evidence(private, replace(batch, receipts=receipts))
    return (
        private / "events.jsonl",
        private / "raw-manifest.json",
        private / "batch-result.json",
        results,
    )


def test_live_private_records_replay_without_runtime_or_seed_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept exact synthetic legacy-format evidence through the real publisher.

    Args:
        tmp_path: Test-owned synthetic raw, record and public roots.
        monkeypatch: Forbids live source, seed or batch calls in replay.

    Raises:
        AssertionError: If replay invokes a live workload or loses provenance.
    """
    events, manifest, batch_path, results = _evidence(tmp_path)
    recorded = json.loads(batch_path.read_text())
    recorded.pop("receipts")
    batch_path.write_text(json.dumps(recorded))

    def forbidden(*args: object, **kwargs: object) -> None:
        """Fail on any live work in the read-only replay path.

        Args:
            *args: Unexpected live call arguments.
            **kwargs: Unexpected live call options.

        Raises:
            AssertionError: Always; replay cannot dispatch.
        """
        raise AssertionError("replay invoked a live API")

    monkeypatch.setattr(run_comparison, "prepare_run", forbidden)
    monkeypatch.setattr(run_comparison, "run_single", forbidden)
    monkeypatch.setattr(comparison_batch, "run_batch", forbidden)
    target = replay_publication("core33", events, manifest, batch_path, results)
    assert target == results / "core33"
    assert len(list(target.iterdir())) == 8
    artifact = json.loads((target / "graphex.json").read_text())
    assert artifact["measurement_source"]["version"] == "3.1.1"
    assert artifact["aggregation"]["runs"] == 3
    assert artifact["raw_sha256"] == [
        row["sha256"]
        for row in json.loads(manifest.read_text())
        if row["path"].endswith("/graphex.json") and "/seed-1000-" in row["path"]
    ]


def test_private_records_roundtrip_embedded_live_receipts(tmp_path: Path) -> None:
    """Preserve all 24 exact typed receipts in the new private record format.

    Args:
        tmp_path: Test-owned synthetic evidence root.
    """
    events, manifest, batch_path, _ = _evidence(tmp_path)
    batch, receipts = load_replay(events, manifest, batch_path)
    assert len(batch.groups) == 8
    assert len(batch.dispatch_order) == len(batch.receipts) == len(receipts) == 24
    assert batch.receipts == receipts
    assert [receipt.number for receipt in receipts] == list(range(1, 25))
    assert receipts[0].plan.source_version == "3.1.1"


@pytest.mark.parametrize(
    "case",
    (
        "missing_start",
        "duplicate_success",
        "extra_success",
        "boolean_number",
        "unknown_event_field",
        "wrong_plan_profile",
        "wrong_authors",
        "relative_raw_path",
        "wrong_manifest_sha",
        "duplicate_manifest",
        "wrong_batch_order",
        "wrong_group_key",
        "wrong_group_median",
        "wrong_seed",
        "wrong_source",
        "wrong_freeze",
        "raw_mutated",
        "nonfinite",
        "embedded_drift",
    ),
)
def test_replay_rejects_broken_cross_file_evidence_before_public_write(
    tmp_path: Path, case: str
) -> None:
    """Never treat contradictory retained records as a publishable batch.

    Args:
        tmp_path: Private synthetic evidence and destination roots.
        case: One malformed or contradictory retained witness.

    Raises:
        AssertionError: If invalid records install a public bundle.
    """
    events, manifest, batch_path, results = _evidence(tmp_path)
    event_rows = [json.loads(line) for line in events.read_text().splitlines()]
    manifest_rows = json.loads(manifest.read_text())
    batch = json.loads(batch_path.read_text())
    if case == "missing_start":
        event_rows.pop(0)
    elif case == "duplicate_success":
        event_rows.append(event_rows[1])
    elif case == "extra_success":
        event_rows.append({**event_rows[1], "number": 25})
    elif case == "boolean_number":
        event_rows[0]["number"] = True
    elif case == "unknown_event_field":
        event_rows[0]["private"] = "unsupported"
    elif case == "wrong_plan_profile":
        event_rows[0]["plan"]["profile"] = "legacy"
    elif case == "wrong_authors":
        event_rows[0]["plan"]["authors"] = 3000
    elif case == "relative_raw_path":
        event_rows[1]["raw_path"] = "relative/graphex.json"
    elif case == "wrong_manifest_sha":
        manifest_rows[0]["sha256"] = "0" * 64
    elif case == "duplicate_manifest":
        manifest_rows[1] = manifest_rows[0]
    elif case == "wrong_batch_order":
        batch["dispatch_order"].reverse()
    elif case == "wrong_group_key":
        batch["groups"][0]["library"] = "ariadne"
    elif case == "wrong_group_median":
        batch["groups"][0]["median"]["ops"]["nested"]["p95_ms"] += 1
    elif case == "wrong_seed":
        batch["groups"][0]["seed_sha256"] = "0" * 64
    elif case == "wrong_source":
        event_rows[0]["plan"]["commit"] = "0" * 40
    elif case == "wrong_freeze":
        event_rows[0]["plan"]["constraints_sha256"] = "0" * 64
    elif case == "raw_mutated":
        Path(event_rows[1]["raw_path"]).write_bytes(b"changed raw result")
    elif case == "nonfinite":
        batch["groups"][0]["median"]["ops"]["nested"]["p95_ms"] = float("nan")
    elif case == "embedded_drift":
        batch["receipts"][0]["sha256"] = "0" * 64
    events.write_text("\n".join(json.dumps(row) for row in event_rows) + "\n")
    manifest.write_text(json.dumps(manifest_rows))
    batch_path.write_text(json.dumps(batch))
    with pytest.raises((ValueError, OSError)):
        replay_publication("core33", events, manifest, batch_path, results)
    assert not (results / "core33").exists()
    assert not list(results.glob(".core33-stage-*"))


def test_replay_rejects_evidence_symlink_and_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    """Reject linked evidence and duplicate object keys before public staging.

    Args:
        tmp_path: Private evidence and destination roots.

    Raises:
        AssertionError: If ambiguous evidence reaches publication.
    """
    events, manifest, batch_path, results = _evidence(tmp_path)
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(foreign)
    with pytest.raises((ValueError, OSError)):
        replay_publication("core33", events, manifest, batch_path, results)
    assert foreign.read_bytes()
    manifest.unlink()
    manifest.write_bytes(foreign.read_bytes())
    batch_path.write_text('{"groups":[],"groups":[],"dispatch_order":[]}')
    with pytest.raises(ValueError, match="duplicate evidence key"):
        load_replay(events, manifest, batch_path)
    assert not (results / "core33").exists()


def _private_directories(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Prepare only external test-owned parent directories for run-mode stubs.

    Args:
        tmp_path: Private fixture root.

    Returns:
        Environment, seed, raw output and result parent paths.
    """
    root = tmp_path / "envs"
    root.mkdir(mode=0o700)
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    output_parent = tmp_path / "raws"
    output_parent.mkdir(mode=0o700)
    results = tmp_path / "results"
    results.mkdir()
    return root, seed_parent, output_parent, results


def test_run_mode_composes_checked_steps_and_retains_complete_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run both seed preflights before any stubbed creation or dispatch.

    Args:
        tmp_path: External test-owned roots.
        monkeypatch: Replaces costly source, seed and measurement boundaries.
    """
    from benchmarks import run_publish_core33 as command

    roots = _private_directories(tmp_path)
    seen: list[tuple[str, object]] = []

    def prepare(profile: str, root: Path, destination: Path, authors: int) -> str:
        """Record both read-only plans before any create step.

        Args:
            profile: Selected profile.
            root: Selected environment root.
            destination: Proposed fresh seed path.
            authors: Declared cardinality.

        Returns:
            Synthetic plan identity.
        """
        assert profile == "core33" and root == roots[0]
        assert destination == roots[1] / f"seed-{authors}"
        seen.append(("prepare", authors))
        return str(authors)

    def create(plan: str, root: Path) -> str:
        """Record an authorized mocked private seed creation.

        Args:
            plan: Synthetic plan identity.
            root: Selected environment root.

        Returns:
            Synthetic prepared-seed identity.
        """
        assert root == roots[0]
        seen.append(("create", plan))
        return plan

    def batch(seeds: tuple[str, str], root: Path, output: Path) -> BatchResult:
        """Record one stubbed rotated batch, without HTTP.

        Args:
            seeds: Both synthetic seed identities.
            root: Selected environment root.
            output: Selected private raw parent.

        Returns:
            Synthetic complete batch marker.
        """
        assert seeds == ("1000", "2000") and (root, output) == (roots[0], roots[2])
        seen.append(("batch", seeds))
        return BatchResult((), (), ())

    monkeypatch.setattr(command, "prepare_seed_plan", prepare)
    monkeypatch.setattr(command, "create_private_seed", create)
    monkeypatch.setattr(comparison_batch, "run_batch", batch)
    monkeypatch.setattr(
        command,
        "_write_evidence",
        lambda parent, batch: seen.append(("evidence", parent)),
    )
    monkeypatch.setattr(
        comparison_publish,
        "publish_core33",
        lambda batch, receipts, root: seen.append(("publish", root)) or root / "core33",
    )
    result = run_publication("core33", (1000, 2000), 3, *roots)
    assert result == roots[3] / "core33"
    assert seen == [
        ("prepare", 1000),
        ("prepare", 2000),
        ("create", "1000"),
        ("create", "2000"),
        ("batch", ("1000", "2000")),
        ("evidence", roots[2]),
        ("publish", roots[3]),
    ]
    assert not (roots[3] / "core33").exists()


@pytest.mark.parametrize(
    "case",
    (
        "profile",
        "authors",
        "runs",
        "occupied_target",
        "seed_name",
        "raw_parent",
        "linked_parent",
    ),
)
def test_run_rejects_bad_options_and_destinations_before_any_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Preflight malformed or occupied paths before costly or writing calls.

    Args:
        tmp_path: Private fixture root.
        monkeypatch: Detects forbidden seed planning or creation.
        case: Invalid option or destination shape.

    Raises:
        AssertionError: If any invalid case reaches seed planning.
    """
    from benchmarks import run_publish_core33 as command

    root, seeds, output, results = _private_directories(tmp_path)
    profile, authors, runs = "core33", (1000, 2000), 3
    if case == "profile":
        profile = "legacy"
    elif case == "authors":
        authors = (1000, 1000)
    elif case == "runs":
        runs = 2
    elif case == "occupied_target":
        (results / "core33").write_bytes(b"foreign")
    elif case == "seed_name":
        (seeds / "seed-1000").write_bytes(b"foreign")
    elif case == "raw_parent":
        (output / "foreign").write_bytes(b"foreign")
    elif case == "linked_parent":
        output.rmdir()
        output.symlink_to(seeds, target_is_directory=True)
    monkeypatch.setattr(
        command,
        "prepare_seed_plan",
        lambda *args: pytest.fail("planned an invalid run"),
    )
    monkeypatch.setattr(
        command,
        "create_private_seed",
        lambda *args: pytest.fail("created an invalid seed"),
    )
    with pytest.raises((ValueError, OSError)):
        run_publication(profile, authors, runs, root, seeds, output, results)
    assert not (results / "core33").is_dir()


def test_run_failure_preserves_private_partial_and_never_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leave a failed private attempt for inspection without publication.

    Args:
        tmp_path: Private fixture root.
        monkeypatch: Stubbed first seed and failing second seed.

    Raises:
        AssertionError: If failure deletes residue or calls the publisher.
    """
    from benchmarks import run_publish_core33 as command

    root, seeds, output, results = _private_directories(tmp_path)
    monkeypatch.setattr(command, "prepare_seed_plan", lambda p, r, d, a: (d, a))

    def create(plan: tuple[Path, int], _: Path) -> str:
        """Retain one first-seed marker then fail the next mocked seed.

        Args:
            plan: Synthetic destination and cardinality.
            _: Unused named environment root.

        Returns:
            First synthetic seed marker.

        Raises:
            RuntimeError: For the second seed only.
        """
        if plan[1] == 2000:
            raise RuntimeError("second seed failed")
        marker = seeds / "first-seed-sentinel"
        marker.write_bytes(b"retained")
        return str(marker)

    monkeypatch.setattr(command, "create_private_seed", create)
    monkeypatch.setattr(
        comparison_batch,
        "run_batch",
        lambda *args: pytest.fail("batch after failed seed"),
    )
    monkeypatch.setattr(
        comparison_publish,
        "publish_core33",
        lambda *args: pytest.fail("published failed seed"),
    )
    with pytest.raises(RuntimeError, match="second seed failed"):
        run_publication("core33", (1000, 2000), 3, root, seeds, output, results)
    assert (seeds / "first-seed-sentinel").read_bytes() == b"retained"
    assert not (results / "core33").exists()


def test_failed_batch_retains_raw_and_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed measured batch leaves raw residue and no public result.

    Args:
        tmp_path: Test-owned private and public fixture roots.
        monkeypatch: Stubbed seed preparation and failed batch.

    Raises:
        AssertionError: If failure invokes receipt writing or publication.
    """
    from benchmarks import run_publish_core33 as command

    root, seeds, output, results = _private_directories(tmp_path)
    monkeypatch.setattr(command, "prepare_seed_plan", lambda p, r, d, a: str(a))
    monkeypatch.setattr(command, "create_private_seed", lambda plan, root: plan)

    def fail_batch(*args: object) -> None:
        """Leave one private raw marker and fail before complete receipts.

        Args:
            *args: Unused selected seed, runtime and output values.

        Raises:
            RuntimeError: Always, after a private marker is retained.
        """
        (output / "first-raw-sentinel").write_bytes(b"retained")
        raise RuntimeError("batch failed")

    monkeypatch.setattr(comparison_batch, "run_batch", fail_batch)
    monkeypatch.setattr(
        command,
        "_write_evidence",
        lambda *args: pytest.fail("recorded incomplete batch"),
    )
    monkeypatch.setattr(
        comparison_publish,
        "publish_core33",
        lambda *args: pytest.fail("published incomplete batch"),
    )
    with pytest.raises(RuntimeError, match="batch failed"):
        run_publication("core33", (1000, 2000), 3, root, seeds, output, results)
    assert (output / "first-raw-sentinel").read_bytes() == b"retained"
    assert not (results / "core33").exists()


def test_direct_script_and_module_help_do_not_run_a_workload() -> None:
    """Both documented entry points require an explicit subcommand.

    Raises:
        AssertionError: If help imports a live workload or fails.
    """
    python = Path(__file__).resolve().parents[2] / ".venv/bin/python"
    if not python.is_file():
        python = Path("/Users/eamigo/Documents/Work/django-graphex/.venv/bin/python")
    source = Path(__file__).resolve().parents[2]
    for command in (
        [str(python), "-m", "benchmarks.run_publish_core33", "--help"],
        [str(python), str(source / "benchmarks/run_publish_core33.py"), "--help"],
    ):
        result = subprocess.run(
            command, cwd=source, text=True, capture_output=True, check=False
        )
        assert result.returncode == 0
        assert "run" in result.stdout and "replay" in result.stdout
