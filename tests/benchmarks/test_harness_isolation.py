"""Regression tests for rollback-only benchmark requests."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"


def test_profile_witness_is_child_observed_and_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attest the loaded backend only for named-profile child processes.

    Args:
        monkeypatch: Fixture selecting or removing the profile mode.
    """
    from benchmarks import harness

    schema = SimpleNamespace(__file__=BENCHMARKS / "libs/graphex/bench_schema.py")
    monkeypatch.delenv("BENCH_PROFILE", raising=False)
    assert harness._profile_witness(schema) is None
    monkeypatch.setenv("BENCH_PROFILE", "core33")
    witness = harness._profile_witness(schema)
    assert witness["schema_path"] == str(schema.__file__)
    assert witness["backend_path"] == str(REPO_ROOT / "django_graphex/__init__.py")
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert witness["source_version"] == project["project"]["version"]
    assert (
        witness["tree"]
        == subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=REPO_ROOT, text=True
        ).strip()
    )
    assert len(witness["constraints_sha256"]) == 64


def test_profile_witness_reads_future_source_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read the measured checkout version rather than a historical constant.

    Args:
        tmp_path: Synthetic future checkout with its own profile files.
        monkeypatch: Fixture redirecting the child witness to that checkout.
    """
    from benchmarks import harness

    bench = tmp_path / "benchmarks"
    profile = bench / "comparison_profiles/core33"
    (profile / "constraints").mkdir(parents=True)
    (profile / "manifest.json").write_text("{}")
    (profile / "constraints/graphex.txt").write_text("graphql-core==3.3.0\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "4.0.0"\n')
    monkeypatch.setattr(harness, "BASE_DIR", bench)
    monkeypatch.setattr(harness.subprocess, "check_output", lambda *_a, **_k: "a" * 40)
    monkeypatch.setenv("BENCH_PROFILE", "core33")
    schema = SimpleNamespace(__file__=bench / "libs/graphex/bench_schema.py")

    assert harness._profile_witness(schema)["source_version"] == "4.0.0"


@pytest.mark.parametrize("named_profile", [False, True])
def test_harness_provenance_changes_only_for_named_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, named_profile: bool
) -> None:
    """Keep historical provenance while labeling selected profile output.

    Args:
        tmp_path: Disposable diagnostic output directory.
        monkeypatch: Fixture replacing workload operations with no-op controls.
        named_profile: Whether the named comparison witness is active.
    """
    import json

    from benchmarks import harness

    schema = SimpleNamespace(OPERATIONS={}, LIB_VERSIONS={"django-graphex": "3.1.0"})
    witness = {
        "commit": "a" * 40,
        "tree": "b" * 40,
        "source_version": "4.0.0",
        "constraints_sha256": "c" * 64,
    }
    monkeypatch.setattr(harness, "_import_schema", lambda: (schema, 1.0, [1.0] * 5))
    monkeypatch.setattr(harness, "_surface", lambda *_: {})
    monkeypatch.setattr(
        harness, "_profile_witness", lambda *_: witness if named_profile else None
    )
    monkeypatch.setenv("BENCH_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("BENCH_OUTPUT_FD", raising=False)
    harness.main()
    result = json.loads((tmp_path / "graphex.json").read_text())
    if named_profile:
        assert result["provenance"] == {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "constraints_sha256": "c" * 64,
        }
        assert result["versions"]["django-graphex"] == "4.0.0"
    else:
        assert "tree" not in result["provenance"]
        assert result["versions"]["django-graphex"] == "3.1.0"


def test_named_profile_rejects_output_descriptor_for_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse a descriptor that does not name the declared output directory.

    Args:
        tmp_path: Disposable owned and decoy output directories.
        monkeypatch: Fixture replacing workload operations and environment.
    """
    from benchmarks import harness

    declared = tmp_path / "declared"
    held = tmp_path / "held"
    declared.mkdir()
    held.mkdir()
    descriptor = os.open(held, os.O_RDONLY | os.O_DIRECTORY)
    schema = SimpleNamespace(OPERATIONS={}, LIB_VERSIONS={})
    monkeypatch.setattr(harness, "_import_schema", lambda: (schema, 1.0, [1.0] * 5))
    monkeypatch.setattr(harness, "_surface", lambda *_: {})
    monkeypatch.setattr(
        harness,
        "_profile_witness",
        lambda *_: {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "source_version": "3.1.1",
            "constraints_sha256": "c" * 64,
        },
    )
    monkeypatch.setenv("BENCH_OUTPUT_DIR", str(declared))
    monkeypatch.setenv("BENCH_OUTPUT_FD", str(descriptor))
    monkeypatch.setenv("BENCH_PREFIX", "")
    try:
        with pytest.raises(ValueError, match="descriptor"):
            harness.main()
    finally:
        os.close(descriptor)
    assert list(declared.iterdir()) == []
    assert list(held.iterdir()) == []


def test_named_profile_writes_through_held_output_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write named output through the held directory, not its pathname.

    Args:
        tmp_path: Disposable diagnostic directory.
        monkeypatch: Fixture replacing workload operations and path writes.

    Raises:
        AssertionError: If the harness writes through the output pathname.
    """
    from benchmarks import harness

    output = tmp_path / "owned"
    output.mkdir()
    descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    schema = SimpleNamespace(OPERATIONS={}, LIB_VERSIONS={})
    monkeypatch.setattr(harness, "_import_schema", lambda: (schema, 1.0, [1.0] * 5))
    monkeypatch.setattr(harness, "_surface", lambda *_: {})
    monkeypatch.setattr(
        harness,
        "_profile_witness",
        lambda *_: {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "source_version": "3.1.1",
            "constraints_sha256": "c" * 64,
        },
    )
    monkeypatch.setenv("BENCH_OUTPUT_DIR", str(output))
    monkeypatch.setenv("BENCH_OUTPUT_FD", str(descriptor))
    monkeypatch.setenv("BENCH_PREFIX", "")
    original_open = Path.open

    def forbid_path_write(path: Path, *args: object, **kwargs: object) -> object:
        """Reject pathname output while permitting unrelated file reads.

        Args:
            path: File path requested by the harness.
            *args: Positional arguments for the original opener.
            **kwargs: Keyword arguments for the original opener.

        Returns:
            The original opener's stream for another path.

        Raises:
            AssertionError: If the harness writes through the output pathname.
        """
        if path == output / "graphex.json":
            raise AssertionError("named output used its pathname")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbid_path_write)
    try:
        harness.main()
    finally:
        os.close(descriptor)
    assert (output / "graphex.json").is_file()


def test_named_profile_descriptor_rejects_ambient_filename_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep an ambient prefix from changing the held-directory filename.

    Args:
        tmp_path: Disposable diagnostic directory.
        monkeypatch: Fixture replacing workload operations and environment.
    """
    from benchmarks import harness

    output = tmp_path / "owned"
    output.mkdir()
    descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    schema = SimpleNamespace(OPERATIONS={}, LIB_VERSIONS={})
    monkeypatch.setattr(harness, "_import_schema", lambda: (schema, 1.0, [1.0] * 5))
    monkeypatch.setattr(harness, "_surface", lambda *_: {})
    monkeypatch.setattr(
        harness,
        "_profile_witness",
        lambda *_: {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "source_version": "3.1.1",
            "constraints_sha256": "c" * 64,
        },
    )
    monkeypatch.setenv("BENCH_OUTPUT_DIR", str(output))
    monkeypatch.setenv("BENCH_OUTPUT_FD", str(descriptor))
    monkeypatch.setattr(harness, "BENCH_PREFIX", "../escape")
    try:
        with pytest.raises(ValueError, match="prefix"):
            harness.main()
    finally:
        os.close(descriptor)
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("library", ["../escape", "/tmp/escape"])
def test_named_profile_descriptor_rejects_unsafe_library_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, library: str
) -> None:
    """Reject traversal-bearing library names before held-directory writes.

    Args:
        tmp_path: Disposable diagnostic directory.
        monkeypatch: Fixture replacing workload operations and library name.
        library: Traversal-bearing or absolute library value.
    """
    from benchmarks import harness

    output = tmp_path / "owned"
    output.mkdir()
    descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    schema = SimpleNamespace(OPERATIONS={}, LIB_VERSIONS={})
    monkeypatch.setattr(harness, "_import_schema", lambda: (schema, 1.0, [1.0] * 5))
    monkeypatch.setattr(harness, "_surface", lambda *_: {})
    monkeypatch.setattr(
        harness,
        "_profile_witness",
        lambda *_: {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "source_version": "3.1.1",
            "constraints_sha256": "c" * 64,
        },
    )
    monkeypatch.setattr(harness, "BENCH_LIB", library)
    monkeypatch.setenv("BENCH_OUTPUT_DIR", str(output))
    monkeypatch.setenv("BENCH_OUTPUT_FD", str(descriptor))
    try:
        with pytest.raises(ValueError, match="library"):
            harness.main()
    finally:
        os.close(descriptor)
    assert list(output.iterdir()) == []


def test_named_profile_descriptor_stays_on_renamed_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the write on the held inode if its visible path is replaced.

    Args:
        tmp_path: Disposable original and replacement directories.
        monkeypatch: Fixture replacing workload operations and path lookup.
    """
    from benchmarks import harness

    output = tmp_path / "owned"
    moved = tmp_path / "moved"
    output.mkdir()
    descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    schema = SimpleNamespace(OPERATIONS={}, LIB_VERSIONS={})
    monkeypatch.setattr(harness, "_import_schema", lambda: (schema, 1.0, [1.0] * 5))
    monkeypatch.setattr(harness, "_surface", lambda *_: {})
    monkeypatch.setattr(
        harness,
        "_profile_witness",
        lambda *_: {
            "commit": "a" * 40,
            "tree": "b" * 40,
            "source_version": "3.1.1",
            "constraints_sha256": "c" * 64,
        },
    )
    monkeypatch.setenv("BENCH_OUTPUT_DIR", str(output))
    monkeypatch.setenv("BENCH_OUTPUT_FD", str(descriptor))
    monkeypatch.setattr(harness, "BENCH_PREFIX", "")
    real_stat = os.stat
    real_fstat = os.fstat
    descriptor_checked = False

    def notice_descriptor(fd: int) -> os.stat_result:
        nonlocal descriptor_checked
        if fd == descriptor:
            descriptor_checked = True
        return real_fstat(fd)

    def replace_after_lookup(path: object, **kwargs: object) -> os.stat_result:
        result = real_stat(path, **kwargs)
        if (
            descriptor_checked
            and path == output
            and kwargs.get("follow_symlinks") is False
        ):
            output.rename(moved)
            output.mkdir()
        return result

    monkeypatch.setattr(harness.os, "fstat", notice_descriptor)
    monkeypatch.setattr(harness.os, "stat", replace_after_lookup)
    try:
        harness.main()
    finally:
        os.close(descriptor)
    assert (moved / "graphex.json").is_file()
    assert list(output.iterdir()) == []


def test_all_117_operation_requests_roll_back_rows_and_sqlite_sequence(
    tmp_path: Path,
) -> None:
    """Keep rows and the primary-key sequence stable across all requests.

    Args:
        tmp_path: Temporary location for the isolated SQLite database.
    """
    script = r"""
import django
django.setup()

from django.core.management import call_command
call_command("migrate", run_syncdb=True, verbosity=0)

from benchapp.models import Author, Category, Comment, Post
from harness import _isolated_post

author = Author.objects.create(name="A", email="a@example.com")
category = Category.objects.create(name="C")
post = Post.objects.create(author=author, category=category, title="P")

def insert_comment(_client, _operation):
    comment = Comment.objects.create(post=post, author_name="Bench", text="T")
    return {"id": comment.pk}

import harness
harness._post = insert_comment

before = Comment.objects.count()
first = _isolated_post(object(), {}, timed=True, count_queries=True)
response, elapsed_ms, sql_queries = first
assert response == {"id": 1}
assert elapsed_ms is not None and elapsed_ms >= 0
assert sql_queries == 1, sql_queries
for _ in range(116):
    response, _, _ = _isolated_post(object(), {})
    assert response == {"id": 1}
assert Comment.objects.count() == before

persisted = Comment.objects.create(post=post, author_name="After", text="T")
assert persisted.pk == 1, persisted.pk
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(BENCHMARKS),
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "BENCH_LIB": "ariadne",
        "BENCH_DATABASE": str(tmp_path / "bench.sqlite3"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BENCHMARKS,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_graphex_mutation_sql_contract_counts_request_internal_queries(
    tmp_path: Path,
) -> None:
    """Count the four GraphEx mutation statements inside the request only.

    Args:
        tmp_path: Temporary location for the isolated SQLite database.
    """
    script = r"""
import django
django.setup()

from django.core.management import call_command
call_command("migrate", run_syncdb=True, verbosity=0)

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext

from benchapp.models import Author, Category, Comment, Post
from harness import _post
from libs.graphex.bench_schema import OPERATIONS
from run_publish import EXPECTED_SQL

author = Author.objects.create(name="A", email="a@example.com")
category = Category.objects.create(name="C")
Post.objects.create(pk=5000, author=author, category=category, title="P")

with transaction.atomic():
    with CaptureQueriesContext(connection) as captured:
        response = _post(Client(), OPERATIONS["create_comment"])
    transaction.set_rollback(True)

statements = [query["sql"].split()[0] for query in captured.captured_queries]
assert statements == ["SAVEPOINT", "INSERT", "PRAGMA", "RELEASE"], statements
actual = len(captured.captured_queries)
expected = EXPECTED_SQL["graphex"]["create_comment"]
assert actual == expected, (actual, expected)
assert response["data"]["commentCreate"]["ok"] is True
assert Comment.objects.count() == 0
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(BENCHMARKS),
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "BENCH_LIB": "graphex",
        "BENCH_DATABASE": str(tmp_path / "bench.sqlite3"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BENCHMARKS,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
