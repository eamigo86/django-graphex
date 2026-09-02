"""Configuration contracts for the opt-in PostgreSQL integration job."""

from __future__ import annotations

from pathlib import Path

import pytest

import tests.conftest as suite_config

ROOT = Path(__file__).parents[1]


def test_sqlite_remains_the_default_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ordinary local and matrix runs keep the in-memory SQLite database.

    This test protects the corresponding regression contract.

    Args:
        monkeypatch: Pytest fixture used to isolate process state.
    """
    monkeypatch.delenv("GDX_TEST_DATABASE", raising=False)
    assert suite_config._database_settings() == {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }


def test_postgres_database_reads_standard_service_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CI service can configure Django without a separate settings module.

    This test protects the corresponding regression contract.

    Args:
        monkeypatch: Pytest fixture used to isolate process state.
    """
    values = {
        "GDX_TEST_DATABASE": "postgres",
        "POSTGRES_DB": "graphex_ci",
        "POSTGRES_USER": "graphex",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_HOST": "database",
        "POSTGRES_PORT": "5544",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    assert suite_config._database_settings() == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "graphex_ci",
        "USER": "graphex",
        "PASSWORD": "secret",
        "HOST": "database",
        "PORT": "5544",
    }


def test_unknown_database_selector_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must not silently fall back to SQLite and fake integration success.

    This test protects the corresponding regression contract.

    Args:
        monkeypatch: Pytest fixture used to isolate process state.
    """
    monkeypatch.setenv("GDX_TEST_DATABASE", "postgress")
    with pytest.raises(RuntimeError, match="GDX_TEST_DATABASE"):
        suite_config._database_settings()


def test_workflow_runs_the_real_postgresql_contract() -> None:
    """CI provisions PostgreSQL 17 and runs only its backend-specific contract.

    This test protects the corresponding regression contract.
    """
    workflow = (ROOT / ".github/workflows/cicd.yaml").read_text()
    job = workflow.split("  postgresql:\n", 1)[1].split("\n  get-version:", 1)[0]
    assert "postgres:17" in job
    assert "python-version: '3.12'" in job
    assert "GDX_TEST_DATABASE: postgres" in job
    assert "uv run pytest --no-migrations" in job
    assert "tests/integration/test_postgresql_transactions.py --no-cov" in job
    assert "django.VERSION[:2] == (6, 0)" in job


def test_postgresql_gate_blocks_publish_and_is_documented() -> None:
    """The real-database gate is reproducible and release-blocking.

    This test protects the corresponding regression contract.
    """
    workflow = (ROOT / ".github/workflows/cicd.yaml").read_text()
    publish = workflow.split("  publish:\n", 1)[1].split("\n  create-release:", 1)[0]
    dependencies = (ROOT / "pyproject.toml").read_text()
    contributing = (ROOT / "docs/contributing.md").read_text()

    assert "postgresql" in "\n".join(publish.splitlines()[:3])
    assert '"psycopg[binary]>=3.2,<4"' in dependencies
    assert "GDX_TEST_DATABASE=postgres" in contributing
    assert "POSTGRES_DB" in contributing
    assert 'connection.vendor == "postgresql"' in contributing
