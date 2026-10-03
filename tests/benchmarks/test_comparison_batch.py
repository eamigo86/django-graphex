"""Stub-only contracts for a complete private rotated comparison batch."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmarks import comparison_batch, run_comparison
from benchmarks.comparison_batch import run_batch
from benchmarks.comparison_seed import SeedPlan
from benchmarks.comparison_seed_execution import PreparedSeed
from benchmarks.run_publish import (
    EXPECTED_SQL,
    EXPECTED_SURFACE,
    EXPECTED_VERSIONS,
    METRICS,
    OPERATIONS,
)


def _seed(parent: Path, authors: int) -> PreparedSeed:
    """Make a small owned file shaped like one prevalidated seed record.

    Args:
        parent: Private test directory.
        authors: Declared source cardinality.

    Returns:
        A synthetic record; no real benchmark database is created.
    """
    output = parent / f"seed-{authors}"
    output.mkdir(mode=0o700)
    database = output / "db.sqlite3"
    database.write_bytes(f"synthetic-{authors}".encode())
    plan = SeedPlan(
        profile="core33",
        library="graphex",
        python=parent.parent / "envs/.venv-core33-graphex/bin/python",
        output_root=output,
        database=database,
        authors=authors,
        commit="a" * 40,
        tree="b" * 40,
        source_version="3.1.1",
        python_version="3.12.11",
        django_version="6.0.8",
        graphql_core_version="3.3.0",
        backend_path=parent / "old/django_graphex/__init__.py",
        manifest_sha256="c" * 64,
        constraints_sha256="d" * 64,
        freeze="synthetic freeze\n",
    )
    return PreparedSeed(
        plan=plan,
        database=database,
        sha256=hashlib.sha256(database.read_bytes()).hexdigest(),
        migration_stdout=parent / "migration.stdout",
        migration_stderr=parent / "migration.stderr",
        seed_stdout=parent / "seed.stdout",
        seed_stderr=parent / "seed.stderr",
    )


def _plan(
    library: str, database: Path, authors: int, output: Path, venv_root: Path
) -> run_comparison.RunPlan:
    """Construct one synthetic current-source plan for a stubbed dispatch.

    Args:
        library: Selected whole stack.
        database: Synthetic seed path.
        authors: Synthetic seed cardinality.
        output: Unique run destination.
        venv_root: Named synthetic interpreter root.

    Returns:
        Raw-result validator-compatible current plan.
    """
    packages = run_comparison.load_profile("core33", library, run_comparison.BASE)[
        "packages"
    ]
    return run_comparison.RunPlan(
        "core33",
        library,
        venv_root / f".venv-core33-{library}/bin/python",
        database,
        output,
        authors,
        "3.12.11",
        "e" * 40,
        "f" * 40,
        "3.1.1",
        Path(f"/synthetic/{library}/backend.py"),
        "1" * 64,
        "2" * 64,
        packages,
    )


def _raw(plan: run_comparison.RunPlan, offset: int) -> dict[str, Any]:
    """Build a validator-compatible raw dictionary with distinct timings.

    Args:
        plan: Current synthetic run plan.
        offset: Timing offset for one repetition.

    Returns:
        Raw diagnostic result, not a published median.
    """
    versions = {
        name: plan.source_version if name == "django-graphex" else plan.packages[name]
        for name in EXPECTED_VERSIONS[plan.library]
    }
    return {
        "lib": plan.library,
        "versions": versions,
        "python": plan.python_version,
        "django": plan.packages["django"],
        "machine": {"platform": "synthetic", "cpu_count": 1},
        "dataset": {
            "authors": plan.authors,
            "posts_per_author": 10,
            "comments_per_post": 5,
        },
        "provenance": {
            "commit": plan.commit,
            "tree": plan.tree,
            "constraints_sha256": plan.constraints_sha256,
        },
        "schema_import_ms": offset + 10.0,
        "schema_rebuild_samples_ms": [offset + i / 10 for i in range(5)],
        "surface": EXPECTED_SURFACE,
        "ops": {
            name: {
                **{metric: offset + 1.0 for metric in METRICS},
                "iterations": 100,
                "sql_queries": EXPECTED_SQL[plan.library][name],
            }
            for name in OPERATIONS
        },
        "profile_witness": {
            "profile": plan.profile,
            "library": plan.library,
            "commit": plan.commit,
            "tree": plan.tree,
            "source_version": plan.source_version,
            "manifest_sha256": plan.manifest_sha256,
            "constraints_sha256": plan.constraints_sha256,
            "backend_path": str(plan.backend_path),
            "schema_path": str(
                run_comparison.BASE / "libs" / plan.library / "bench_schema.py"
            ),
            "python": plan.python_version,
            "django": plan.packages["django"],
            "graphql-core": plan.packages["graphql-core"],
        },
    }


def _stub_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[run_comparison.RunPlan]:
    """Install deterministic no-HTTP source, plan, and runner stubs.

    Args:
        monkeypatch: Pytest patch fixture.

    Returns:
        Plan list populated by the stubbed single-run dispatcher.
    """
    from benchmarks import comparison_batch

    monkeypatch.setattr(
        comparison_batch, "_check_seed", lambda seed, root: (seed.sha256, ())
    )
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: ("e" * 40, "f" * 40))
    monkeypatch.setattr(run_comparison, "_check_measured_context", lambda plan: None)
    monkeypatch.setattr(
        run_comparison,
        "prepare_run",
        lambda profile, library, root, db, out, authors: _plan(
            library, db, authors, out, root
        ),
    )
    seen: list[run_comparison.RunPlan] = []

    def fake_single(plan: run_comparison.RunPlan) -> Path:
        """Write only synthetic JSON under one test-owned destination.

        Args:
            plan: Stubbed current-source plan.

        Returns:
            Synthetic raw path.
        """
        seen.append(plan)
        plan.output_root.mkdir(mode=0o700)
        result = _raw(plan, (1, 9, 3)[(len(seen) - 1) // 4 % 3])
        path = plan.output_root / f"{plan.library}.json"
        path.write_text(json.dumps(result))
        return path

    monkeypatch.setattr(run_comparison, "run_single", fake_single)
    return seen


def test_batch_rotates_two_seeds_and_returns_only_eight_detached_medians(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch 24 distinct stubs, then aggregate eight complete triples.

    Args:
        tmp_path: Owned synthetic seed and output roots.
        monkeypatch: Replaces costly probes and child dispatch.
    """
    seeds_parent = tmp_path / "seeds"
    seeds_parent.mkdir(mode=0o700)
    seeds = (_seed(seeds_parent, 1000), _seed(seeds_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    result = run_batch(seeds, tmp_path / "envs", output)

    assert len(seen) == 24
    assert len({plan.output_root for plan in seen}) == 24
    assert [plan.authors for plan in seen] == [1000] * 12 + [2000] * 12
    assert [plan.library for plan in seen[:12]] == [
        "graphex",
        "graphene",
        "strawberry",
        "ariadne",
        "graphene",
        "strawberry",
        "ariadne",
        "graphex",
        "strawberry",
        "ariadne",
        "graphex",
        "graphene",
    ]
    assert [plan.library for plan in seen[12:]] == [plan.library for plan in seen[:12]]
    assert len(result.groups) == 8
    assert len(result.receipts) == 24
    assert [receipt.number for receipt in result.receipts] == list(range(1, 25))
    assert [receipt.plan for receipt in result.receipts] == seen
    assert [receipt.raw_path for receipt in result.receipts] == list(
        result.dispatch_order
    )
    assert all(
        receipt.sha256 == hashlib.sha256(receipt.raw_path.read_bytes()).hexdigest()
        for receipt in result.receipts
    )
    from benchmarks.comparison_publish import DispatchReceipt as PublishedReceipt

    assert PublishedReceipt is comparison_batch.DispatchReceipt
    assert (
        comparison_batch.BatchResult(result.groups, result.dispatch_order).receipts
        == ()
    )
    assert all(len(group.raw_paths) == 3 for group in result.groups)
    assert all(group.median["aggregation"]["runs"] == 3 for group in result.groups)
    assert all(group.median["schema_import_ms"] == 13.0 for group in result.groups)
    assert {group.seed_sha256 for group in result.groups} == {
        seed.sha256 for seed in seeds
    }
    assert all(group.source_commit == "e" * 40 for group in result.groups)
    assert all(group.seed_commit == "a" * 40 for group in result.groups)
    result.groups[0].median["ops"]["nested"]["p95_ms"] = 999.0
    assert (
        json.loads(result.groups[0].raw_paths[0].read_text())["ops"]["nested"]["p95_ms"]
        != 999.0
    )
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("invalid", ((), (1000,), (1000, 1000), (2000, 1000)))
def test_batch_rejects_wrong_seed_set_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: tuple[int, ...],
) -> None:
    """Require exactly one ordered seed per published cardinality.

    Args:
        tmp_path: Owned synthetic seed paths.
        monkeypatch: Replaces costly dispatch.
        invalid: Invalid cardinality sequence.

    Raises:
        AssertionError: If an invalid set reaches dispatch.
    """
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = tuple(_seed(seed_parent, count) for count in sorted(set(invalid)))
    if invalid == (1000, 1000):
        seeds = (seeds[0], seeds[0])
    elif invalid == (2000, 1000):
        seeds = (seeds[1], seeds[0])
    with pytest.raises(ValueError):
        run_batch(seeds, tmp_path / "envs", output)
    assert seen == []
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("kind", ("file", "directory", "symlink"))
def test_batch_refuses_occupied_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """Reject non-private or linked output parents before dispatch.

    Args:
        tmp_path: Owned output fixture parent.
        monkeypatch: Replaces costly dispatch.
        kind: Invalid parent kind.

    Raises:
        AssertionError: If a path is overwritten.
    """
    seen = _stub_dispatch(monkeypatch)
    parent = tmp_path / "runs"
    marker = tmp_path / "marker"
    marker.write_text("preserve")
    if kind == "file":
        parent.write_text("occupied")
    elif kind == "directory":
        parent.mkdir(mode=0o755)
    else:
        parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        run_batch((), tmp_path / "envs", parent)
    assert marker.read_text() == "preserve"
    assert seen == []


def test_batch_keeps_partial_raw_output_without_aggregation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed second child cannot return a falsely complete batch.

    Args:
        tmp_path: Owned synthetic output paths.
        monkeypatch: Replaces the second child with failure.

    Raises:
        AssertionError: If failure returns a batch or removes retained output.
    """
    from benchmarks import comparison_batch

    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    original = run_comparison.run_single
    aggregation_calls = []
    monkeypatch.setattr(
        comparison_batch,
        "aggregate_three",
        lambda *args: aggregation_calls.append(args),
    )

    def fail_second(plan: run_comparison.RunPlan) -> Path:
        """Preserve the first raw file, then simulate child failure.

        Args:
            plan: Selected run plan.

        Returns:
            First raw path before the second dispatch raises.

        Raises:
            RuntimeError: On the second dispatch.
        """
        if seen:
            raise RuntimeError("child failed")
        return original(plan)

    monkeypatch.setattr(run_comparison, "run_single", fail_second)
    with pytest.raises(RuntimeError, match="child failed"):
        run_batch(seeds, tmp_path / "envs", output)
    assert len(seen) == 1
    assert (seen[0].output_root / "graphex.json").is_file()
    assert aggregation_calls == []


def test_batch_rejects_seed_digest_drift_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed private seed cannot enter even a stubbed measurement.

    Args:
        tmp_path: Owned synthetic seeds.
        monkeypatch: Replaces the costly profile probes.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    seeds[0].database.write_bytes(b"drift")
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen: list[run_comparison.RunPlan] = []
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: ("e" * 40, "f" * 40))
    monkeypatch.setattr(run_comparison, "run_single", lambda plan: seen.append(plan))
    with pytest.raises(ValueError, match="digest"):
        run_batch(seeds, tmp_path / "envs", output)
    assert seen == []


def test_batch_rejects_publicly_readable_prepared_database(tmp_path: Path) -> None:
    """Do not treat a world-readable seed file as a private prepared asset.

    Args:
        tmp_path: Owned synthetic seed root.

    Raises:
        AssertionError: If the unsafe file reaches profile probing.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seed = _seed(seed_parent, 1000)
    seed.database.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        comparison_batch._check_seed(seed, tmp_path / "envs")


def test_batch_rejects_raw_mutation_after_read_before_complete_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never return a median when an earlier raw file later changes.

    Args:
        tmp_path: Owned synthetic raw-output root.
        monkeypatch: Mutates the first raw file during the second stub dispatch.

    Raises:
        AssertionError: If a complete batch is returned from drifting raw data.
    """
    seeds_parent = tmp_path / "seeds"
    seeds_parent.mkdir(mode=0o700)
    seeds = (_seed(seeds_parent, 1000), _seed(seeds_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    original = run_comparison.run_single

    def mutate_first(plan: run_comparison.RunPlan) -> Path:
        """Change the first retained result after the second one is written.

        Args:
            plan: Selected synthetic run.

        Returns:
            New synthetic result path.
        """
        result = original(plan)
        if len(seen) == 2:
            seen[0].output_root.joinpath("graphex.json").write_text("{}")
        return result

    monkeypatch.setattr(run_comparison, "run_single", mutate_first)
    with pytest.raises(ValueError, match="raw result changed"):
        run_batch(seeds, tmp_path / "envs", output)
    assert len(seen) == 24
    assert (seen[0].output_root / "graphex.json").read_text() == "{}"


def test_batch_rejects_invalid_raw_json_and_preserves_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed child JSON remains on disk but cannot enter aggregation.

    Args:
        tmp_path: Owned synthetic output root.
        monkeypatch: Writes a malformed first result.
    """
    seeds_parent = tmp_path / "seeds"
    seeds_parent.mkdir(mode=0o700)
    seeds = (_seed(seeds_parent, 1000), _seed(seeds_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    _stub_dispatch(monkeypatch)

    def broken(plan: run_comparison.RunPlan) -> Path:
        """Write one invalid diagnostic without calling the real harness.

        Args:
            plan: First synthetic run.

        Returns:
            Invalid raw path.
        """
        plan.output_root.mkdir(mode=0o700)
        path = plan.output_root / f"{plan.library}.json"
        path.write_text("not JSON")
        return path

    monkeypatch.setattr(run_comparison, "run_single", broken)
    with pytest.raises(json.JSONDecodeError):
        run_batch(seeds, tmp_path / "envs", output)
    assert (output / "seed-1000-r1-graphex/graphex.json").read_text() == "not JSON"


def _git_at(path: Path, *args: str) -> str:
    """Execute a local fixture Git command without network access.

    Args:
        path: Temporary Git checkout.
        *args: Exact command arguments.

    Returns:
        Trimmed command output.
    """
    return subprocess.check_output(["git", *args], cwd=path, text=True).strip()


def test_batch_accepts_ancestor_seed_only_with_equal_data_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind the older seed witness without relabeling it as current source.

    Args:
        tmp_path: Two owned local Git checkouts.
        monkeypatch: Points the batch source root at the fixture.

    Raises:
        AssertionError: If a changed contract or forged tree is accepted.
    """
    current = tmp_path / "current"
    current.mkdir()
    _git_at(current, "init", "-q")
    for path in (*comparison_batch.DATA_CONTRACT, "django_graphex/__init__.py"):
        target = current / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"contract: {path}\n")
    (current / "pyproject.toml").write_text('[project]\nversion = "3.1.1"\n')
    _git_at(current, "add", ".")
    _git_at(
        current,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "seed contract",
    )
    old_commit = _git_at(current, "rev-parse", "HEAD")
    old_tree = _git_at(current, "rev-parse", "HEAD^{tree}")
    old = tmp_path / "old"
    subprocess.run(
        ["git", "clone", "-q", "--no-local", str(current), str(old)],
        check=True,
        capture_output=True,
    )
    (current / "README.md").write_text("later documentation\n")
    _git_at(current, "add", "README.md")
    _git_at(
        current,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "current source",
    )
    current_identity = (
        _git_at(current, "rev-parse", "HEAD"),
        _git_at(current, "rev-parse", "HEAD^{tree}"),
    )
    monkeypatch.setattr(run_comparison, "ROOT", current)
    plan = replace(
        _seed(tmp_path, 1000).plan,
        commit=old_commit,
        tree=old_tree,
        backend_path=old / "django_graphex/__init__.py",
    )
    comparison_batch._compatible_seed_source(plan, current_identity)
    with pytest.raises(ValueError, match="recorded clean checkout"):
        comparison_batch._compatible_seed_source(
            replace(plan, tree="0" * 40), current_identity
        )
    (current / "benchmarks/benchapp/models.py").write_text("changed model contract\n")
    _git_at(current, "add", "benchmarks/benchapp/models.py")
    _git_at(
        current,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "change data contract",
    )
    changed_identity = (
        _git_at(current, "rev-parse", "HEAD"),
        _git_at(current, "rev-parse", "HEAD^{tree}"),
    )
    with pytest.raises(ValueError, match="seed data contract changed"):
        comparison_batch._compatible_seed_source(plan, changed_identity)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("profile", "other"),
        ("library", "graphene"),
        ("authors", 3000),
        ("graphql_core_version", "3.2.13"),
        ("manifest_sha256", "0" * 64),
        ("constraints_sha256", "0" * 64),
        ("freeze", "wrong freeze"),
    ),
)
def test_batch_rejects_forged_seed_plan_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    """Recheck recorded seed fields instead of trusting a forged record.

    Args:
        tmp_path: Owned synthetic seed and environment paths.
        monkeypatch: Replaces external Git and runtime probes only.
        field: SeedPlan field to falsify.
        replacement: Incompatible field value.

    Raises:
        AssertionError: If the forged plan is accepted.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seed = _seed(seed_parent, 1000)
    seed.database.chmod(0o600)
    envs = tmp_path / "envs"
    python = envs / ".venv-core33-graphex/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("synthetic")
    spec = run_comparison.load_profile("core33", "graphex", run_comparison.BASE)
    freeze = spec["constraints"].read_text()
    (python.parent.parent / ".freeze.txt").write_text(freeze)
    manifest = run_comparison.BASE / "comparison_profiles/core33/manifest.json"
    plan = replace(
        seed.plan,
        freeze=freeze,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        constraints_sha256=hashlib.sha256(spec["constraints"].read_bytes()).hexdigest(),
    )
    seed = replace(seed, plan=plan)
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: ("e" * 40, "f" * 40))
    monkeypatch.setattr(
        comparison_batch, "_compatible_seed_source", lambda plan, identity: None
    )
    monkeypatch.setattr(run_comparison, "_installed_freeze", lambda *args: freeze)
    monkeypatch.setattr(
        run_comparison,
        "_runtime_probe",
        lambda *args: {
            "python": "3.12.11",
            "django": "6.0.8",
            "graphql-core": "3.3.0",
            "backend_path": str(run_comparison.ROOT / "django_graphex/__init__.py"),
        },
    )
    monkeypatch.setattr(run_comparison, "_check_database", lambda *args: None)
    monkeypatch.setattr(
        run_comparison, "_database_identity", lambda *args: (seed.sha256, ())
    )
    assert comparison_batch._check_seed(seed, envs) == (seed.sha256, ())
    with pytest.raises(ValueError):
        comparison_batch._check_seed(
            replace(seed, plan=replace(plan, **{field: replacement})), envs
        )


def test_batch_rejects_source_drift_after_first_stub_and_retains_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-child source change stops the batch without removing output.

    Args:
        tmp_path: Owned synthetic run root.
        monkeypatch: Simulates source drift after the first child.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    source = ["e" * 40, "f" * 40]
    monkeypatch.setattr(run_comparison, "_git_identity", lambda: tuple(source))
    original = run_comparison.run_single

    def drift(plan: run_comparison.RunPlan) -> Path:
        """Change only the fake source identity after a raw result exists.

        Args:
            plan: First synthetic run plan.

        Returns:
            Retained raw result path.
        """
        path = original(plan)
        source[0] = "0" * 40
        return path

    monkeypatch.setattr(run_comparison, "run_single", drift)
    with pytest.raises(ValueError, match="source or seed changed after dispatch"):
        run_batch(seeds, tmp_path / "envs", output)
    assert len(seen) == 1
    assert (seen[0].output_root / "graphex.json").is_file()


def test_batch_rejects_seed_drift_after_first_stub_and_retains_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed seed stops the batch before another child starts.

    Args:
        tmp_path: Owned synthetic seed and output directories.
        monkeypatch: Changes a seed file after the first raw result.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    original = run_comparison.run_single
    monkeypatch.setattr(
        comparison_batch,
        "_check_seed",
        lambda seed, root: (hashlib.sha256(seed.database.read_bytes()).hexdigest(), ()),
    )

    def change_seed(plan: run_comparison.RunPlan) -> Path:
        """Write one raw stub and then change its private input.

        Args:
            plan: Selected synthetic run.

        Returns:
            Retained first raw path.
        """
        path = original(plan)
        seeds[0].database.write_bytes(b"changed after first run")
        return path

    monkeypatch.setattr(run_comparison, "run_single", change_seed)
    with pytest.raises(ValueError, match="source or seed changed after dispatch"):
        run_batch(seeds, tmp_path / "envs", output)
    assert len(seen) == 1
    assert (seen[0].output_root / "graphex.json").is_file()


def test_batch_preflights_all_raw_destinations_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An occupied later destination cannot cause an earlier partial run.

    Args:
        tmp_path: Owned synthetic result and marker paths.
        monkeypatch: Replaces costly child execution.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    marker = output / "seed-2000-r3-graphene"
    marker.write_text("foreign result")
    seen = _stub_dispatch(monkeypatch)
    with pytest.raises(ValueError, match="occupied"):
        run_batch(seeds, tmp_path / "envs", output)
    assert seen == []
    assert marker.read_text() == "foreign result"


def test_batch_rejects_a_forged_current_run_plan_before_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not dispatch a plan selecting another named interpreter.

    Args:
        tmp_path: Owned synthetic run and seed paths.
        monkeypatch: Forges a preflight return without running a child.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    original = run_comparison.prepare_run
    monkeypatch.setattr(
        run_comparison,
        "prepare_run",
        lambda *args: replace(original(*args), python=Path("/foreign/python")),
    )
    with pytest.raises(ValueError, match="run plan differs"):
        run_batch(seeds, tmp_path / "envs", output)
    assert seen == []


def test_batch_rejects_cross_library_machine_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not compare internally valid triples measured on different hosts.

    Args:
        tmp_path: Owned synthetic raw-result directory.
        monkeypatch: Changes every Ariadne result to a second synthetic host.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    seen = _stub_dispatch(monkeypatch)
    original = run_comparison.run_single

    def mixed_host(plan: run_comparison.RunPlan) -> Path:
        """Change one library's synthetic machine without invalidating its triple.

        Args:
            plan: Selected synthetic run plan.

        Returns:
            Retained raw result path.
        """
        path = original(plan)
        if plan.library == "ariadne":
            raw = json.loads(path.read_text())
            raw["machine"]["cpu_count"] = 2
            path.write_text(json.dumps(raw))
        return path

    monkeypatch.setattr(run_comparison, "run_single", mixed_host)
    with pytest.raises(ValueError, match="machine differs across batch"):
        run_batch(seeds, tmp_path / "envs", output)
    assert len(seen) == 4
    assert len(tuple(output.iterdir())) == 4


@pytest.mark.parametrize("invalid", ("surface", "sql", "witness"))
def test_batch_rejects_child_contract_drift_without_aggregation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    """Use the shared validator on each actual raw-shaped stub output.

    Args:
        tmp_path: Owned synthetic run root.
        monkeypatch: Corrupts one raw-shaped result field.
        invalid: Selected malformed contract field.
    """
    seed_parent = tmp_path / "seeds"
    seed_parent.mkdir(mode=0o700)
    seeds = (_seed(seed_parent, 1000), _seed(seed_parent, 2000))
    output = tmp_path / "runs"
    output.mkdir(mode=0o700)
    _stub_dispatch(monkeypatch)
    aggregated: list[object] = []
    monkeypatch.setattr(
        comparison_batch, "aggregate_three", lambda *args: aggregated.append(args)
    )

    def wrong_result(plan: run_comparison.RunPlan) -> Path:
        """Write one invalid but parseable synthetic raw result.

        Args:
            plan: First selected current-source profile.

        Returns:
            Retained invalid raw path.
        """
        plan.output_root.mkdir(mode=0o700)
        raw = _raw(plan, 1)
        if invalid == "surface":
            raw["surface"] = {}
        elif invalid == "sql":
            raw["ops"]["nested"]["sql_queries"] += 1
        else:
            raw["profile_witness"]["tree"] = "wrong"
        path = plan.output_root / f"{plan.library}.json"
        path.write_text(json.dumps(raw))
        return path

    monkeypatch.setattr(run_comparison, "run_single", wrong_result)
    with pytest.raises(ValueError):
        run_batch(seeds, tmp_path / "envs", output)
    assert (output / "seed-1000-r1-graphex/graphex.json").is_file()
    assert aggregated == []
