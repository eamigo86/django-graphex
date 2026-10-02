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
