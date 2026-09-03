"""Regression tests for rollback-only benchmark requests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"


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
