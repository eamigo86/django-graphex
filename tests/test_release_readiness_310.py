"""Release metadata contract for django-graphex 3.1.0."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
VERSION = "3.1.0"
RELEASE_HEADING = "## 3.1.0 — 2026-09-02"


def _release_notes() -> str:
    changelog = (ROOT / "docs" / "changelog.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(RELEASE_HEADING)}\n(?P<body>.*?)(?=^## )",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"Missing release heading: {RELEASE_HEADING}"
    return match.group("body")


def test_project_metadata_is_ready_for_310() -> None:
    """The build backend must derive the release version from pyproject.toml.

    This test protects the corresponding regression contract.
    """
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == VERSION


def test_lock_metadata_matches_project_version() -> None:
    """The editable root package entry cannot drift from release metadata.

    This test protects the corresponding regression contract.
    """
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    root_package = next(
        package
        for package in lock["package"]
        if package["name"] == "django-graphex"
        and package.get("source") == {"editable": "."}
    )
    assert root_package["version"] == VERSION


def test_changelog_publishes_upgrade_guide() -> None:
    """The release must surface the verified 2.x-to-3.0 upgrade guide.

    This test protects the corresponding regression contract.
    """
    notes = _release_notes()
    assert "[2.x → 3.0 upgrade guide](UPGRADE-3.0.md)" in notes
    assert notes.count("#146") == 1
    requirements = "Google-style|type hints|backticks|--strict-public|--strict-content"
    assert all(requirement in notes for requirement in requirements.split("|"))


@pytest.mark.parametrize("finding", range(1, 25))
def test_changelog_traces_every_audit_finding(finding: int) -> None:
    """All 24 audit findings need an explicit release-note disposition.

    This test protects the corresponding regression contract.

    Args:
        finding: The numbered audit finding identifier.
    """
    notes = _release_notes()
    assert re.search(rf"^\| {finding} \|", notes, flags=re.MULTILINE)


@pytest.mark.parametrize(
    "area",
    (
        "cache",
        "subscriptions",
        "documentation",
        "test suite",
        "PostgreSQL",
        "immutable artifact",
        "benchmarks",
    ),
)
def test_changelog_covers_each_release_area(area: str) -> None:
    """The summary must let maintainers scan every remediated subsystem.

    This test protects the corresponding regression contract.

    Args:
        area: The release area expected in the changelog.
    """
    assert area.casefold() in _release_notes().casefold()
