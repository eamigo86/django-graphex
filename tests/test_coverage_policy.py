"""Contracts for the repository-wide coverage gates."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_root_and_patch_coverage_are_strictly_above_95_percent() -> None:  # noqa: DOC002
    """The suite and changed-line gates both enforce the agreed 95.01% floor."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--cov-fail-under=95.01" in addopts

    workflow = (ROOT / ".github/workflows/cicd.yaml").read_text()
    assert "diff-cover>=10.5.1,<11" in workflow
    assert "--fail-under=95.01" in workflow
    coverage_job = workflow.split("  coverage:\n", 1)[1].split("\n  get-version:", 1)[0]
    assert "fetch-depth: 0" in coverage_job
