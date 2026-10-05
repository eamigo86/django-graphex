"""Contracts for the 4.0.0 migration release and historical provenance."""

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.0.0"
DATE = "2026-10-05"


def _project(path: Path) -> dict:
    """Read project metadata from a TOML document.

    Args:
        path: Project or lock path to parse.

    Returns:
        Parsed TOML document.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _local_graphex(lock: dict) -> dict:
    """Find the editable local library in a lock.

    Args:
        lock: Parsed uv lock document.

    Returns:
        The local django-graphex package entry.
    """
    return next(
        package for package in lock["package"] if package["name"] == "django-graphex"
    )


def test_prepared_version_agrees_with_both_local_locks() -> None:
    """Keep the package and both editable lock entries on one version.

    The release preparation does not resolve third-party dependencies anew.
    """
    project = _project(ROOT / "pyproject.toml")["project"]
    assert project["version"] == VERSION
    assert "graphql-core>=3.3.0,<3.4" in project["dependencies"]
    for path, source in (
        (ROOT / "uv.lock", "."),
        (ROOT / "examples/playground/uv.lock", "../../"),
    ):
        package = _local_graphex(_project(path))
        assert package["version"] == VERSION
        assert package["source"] == {"editable": source}


def test_400_notes_are_dated_and_describe_version_requirements() -> None:
    """Keep dated migration notes independent of publication status.

    The two earlier dated release sections remain intact below the new notes.
    """
    for path in (ROOT / "CHANGELOG.md", ROOT / "docs/changelog.md"):
        notes = path.read_text(encoding="utf-8")
        after_unreleased = notes.split("## Unreleased", maxsplit=1)[1]
        first_release_heading = next(
            line for line in after_unreleased.splitlines() if line.startswith("## ")
        )
        assert first_release_heading == f"## {VERSION} — {DATE}"
        current = notes.split(f"## {VERSION} — {DATE}", maxsplit=1)[1].split(
            "## 3.1.1 — 2026-10-01", maxsplit=1
        )[0]
        for term in (
            "4.0.0 requires",
            "graphql-core>=3.3.0,<3.4",
            "Executor",
            "immutable AST",
            "source stream",
            "queryset",
            "coercion",
            "cost",
            "core33",
            "3.1.1",
        ):
            assert term in current
        assert "## 3.1.0 — 2026-09-03" in notes or path.name == "CHANGELOG.md"


def test_release_guidance_names_versioned_install_and_migration() -> None:
    """Explain the version boundary and an explicit upgrade path.

    Dependency requirements do not assert that a distribution was published.
    """
    guide = (ROOT / "docs/UPGRADE-4.0.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    playground = (ROOT / "examples/playground/README.md").read_text(encoding="utf-8")
    benchmark = (ROOT / "benchmarks/README.md").read_text(encoding="utf-8")
    assert "# Upgrading to django-graphex 4.0" in guide
    assert "## Version requirements" in guide
    for text in (guide, readme):
        assert "graphql-core>=3.3.0,<3.4" in text
        assert "graphql-core>=3.2.13,<3.3" in text
        assert 'pip install "django-graphex==4.0.0"' in text
    assert "4.0.0 checkout" in playground
    assert "graphql-core 3.3" in playground
    assert "not yet used by the website" not in benchmark
    assert "docs/why.md#current-core33-comparison" in benchmark


@pytest.mark.parametrize(
    "relative_path",
    (
        "README.md",
        "docs/UPGRADE-4.0.md",
        "CHANGELOG.md",
        "docs/changelog.md",
        "examples/playground/README.md",
        "docs/installation.md",
        "docs/usage/subscriptions.md",
        "docs/why.md",
    ),
)
def test_current_release_copy_does_not_expire_after_publication(
    relative_path: str,
) -> None:
    """Reject obsolete current status without rewriting measurement history.

    Args:
        relative_path: Public documentation carrying current version guidance.
    """
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    if relative_path in ("CHANGELOG.md", "docs/changelog.md"):
        text = text.split("## 3.1.1 — 2026-10-01", maxsplit=1)[0]
    elif relative_path == "docs/why.md":
        text = text.split("## Current core33 comparison", maxsplit=1)[1].split(
            "### Historical core33 3.1.1-source comparison", maxsplit=1
        )[0]
    text = " ".join(text.replace("**", "").split()).lower()
    for obsolete in (
        "release prepared",
        "prepared checkout",
        "prepared 4.0.0 checkout",
        "prepared 4.0.0 source checkout",
        "preparing for graphql-core 3.3",
        "no 4.0.0 package release is claimed",
        "has not been published",
        "not yet published",
    ):
        assert obsolete not in text
    assert re.search(r"4\.0\.0 (?:distribution |is )?not published", text) is None


def test_measured_core33_bundle_retains_original_311_source() -> None:
    """Never relabel prior measurements as the prepared package release.

    The portable result records its measured checkout, not this metadata bump.
    """
    for path in sorted((ROOT / "benchmarks/results/core33").glob("*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        assert result["measurement_source"]["version"] == "3.1.1"
        assert result["measurement_source"]["commit"] == (
            "350ae84256fdad1b1a98a6e0bef8d0f63609257f"
        )
