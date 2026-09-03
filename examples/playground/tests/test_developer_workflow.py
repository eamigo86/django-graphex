"""Regression tests for the playground's copied developer workflow."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PLAYGROUND = Path(__file__).resolve().parents[1]


def test_reset_removes_ignored_migrations_and_bytecode(tmp_path: Path) -> None:
    """Assert reset recovers a checkout containing a stale migration chain.

    Args:
        tmp_path: Isolated directory where the copied playground is exercised.
    """
    project = tmp_path / "playground"
    migrations = project / "blog" / "migrations"
    cache = migrations / "__pycache__"
    cache.mkdir(parents=True)
    shutil.copy2(PLAYGROUND / "Makefile", project / "Makefile")
    (project / "db.sqlite3").write_text("stale", encoding="utf-8")
    (migrations / "__init__.py").write_text("", encoding="utf-8")
    (migrations / "0002_orphan.py").write_text(
        "dependencies = [('blog', '0001_missing')]\n", encoding="utf-8"
    )
    (cache / "0002_orphan.pyc").write_bytes(b"stale")

    fake_bin = project / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}

    subprocess.run(
        ["make", "reset"], cwd=project, env=env, check=True, capture_output=True
    )

    assert not (project / "db.sqlite3").exists()
    assert (migrations / "__init__.py").exists()
    assert not list(migrations.glob("0*.py"))
    assert not cache.exists()


def test_every_documented_pytest_command_disables_migrations() -> None:
    """Assert direct test commands avoid ignored local migration artifacts.

    This pins the copied workflow to pytest-django's migration-free mode.
    """
    sources = [PLAYGROUND / "README.md", PLAYGROUND / "pytest.ini"]
    sources.extend(sorted((PLAYGROUND / "tests").glob("*.py")))
    commands = [
        (path, line)
        for path in sources
        if path != Path(__file__)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "python -m pytest" in line
    ]
    assert commands
    missing = [
        (path.name, line.strip())
        for path, line in commands
        if "--no-migrations" not in line
    ]
    assert not missing, missing
