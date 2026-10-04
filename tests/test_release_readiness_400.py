"""Contracts for the prepared, unpublished 4.0.0 migration release."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.0.0"
DATE = "2026-10-04"


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


def test_400_notes_are_dated_but_explicitly_not_published() -> None:
    """Close migration notes without treating preparation as publication.

    The two earlier dated release sections remain intact below the new notes.
    """
    for path in (ROOT / "CHANGELOG.md", ROOT / "docs/changelog.md"):
        notes = path.read_text(encoding="utf-8")
        assert (
            notes.split("## Unreleased", maxsplit=1)[1]
            .lstrip()
            .startswith(f"## {VERSION} — {DATE}")
        )
        current = notes.split(f"## {VERSION} — {DATE}", maxsplit=1)[1].split(
            "## 3.1.1 — 2026-10-01", maxsplit=1
        )[0]
        for term in (
            "Release prepared, not published",
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


def test_release_guidance_names_prepared_checkout_not_published_wheel() -> None:
    """Keep the guide, root README and Playground on the prepared status.

    Ordinary package-manager installation is not proof of an unpublished wheel.
    """
    guide = (ROOT / "docs/UPGRADE-4.0.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    playground = (ROOT / "examples/playground/README.md").read_text(encoding="utf-8")
    benchmark = (ROOT / "benchmarks/README.md").read_text(encoding="utf-8")
    assert "4.0.0 release prepared" in guide
    assert "not published" in guide
    assert "4.0.0 prepared checkout" in readme
    assert "prepared 4.0.0 checkout" in playground
    assert "graphql-core 3.3" in playground
    assert "not yet used by the website" not in benchmark
    assert "docs/why.md#current-core33-comparison" in benchmark


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
