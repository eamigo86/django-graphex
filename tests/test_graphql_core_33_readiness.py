"""Contracts for the current GraphQL-core 3.3 migration floor."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
FLOOR = "graphql-core>=3.3.0,<3.4"


def _read_toml(path: Path) -> dict:
    """Read project or lock metadata.

    Args:
        path: TOML file to load.

    Returns:
        Parsed metadata.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _locked_package(lock: dict, name: str) -> dict:
    """Find a package in a dependency lock.

    Args:
        lock: Parsed lock document.
        name: Package to find.

    Returns:
        Package metadata.
    """
    return next(package for package in lock["package"] if package["name"] == name)


def test_current_graphql_floor_and_both_locks_are_consistent() -> None:
    """Require the 3.3 floor and matching locks.

    The prepared local version is distinct from the published 3.1.1 patch.
    """
    project = _read_toml(ROOT / "pyproject.toml")["project"]
    assert FLOOR in project["dependencies"]
    for path in (ROOT / "uv.lock", ROOT / "examples/playground/uv.lock"):
        lock = _read_toml(path)
        assert _locked_package(lock, "django-graphex")["version"] == project["version"]
        assert _locked_package(lock, "graphql-core")["version"].startswith("3.3.")


def test_current_guidance_distinguishes_the_floor_from_patch_history() -> None:
    """Distinguish current requirements from the published patch.

    Dated 3.1.1 notes retain their historical dependency claim.
    """
    for path in (ROOT / "README.md", ROOT / "docs/installation.md"):
        assert ">=3.3.0,<3.4" in path.read_text(encoding="utf-8")
    views = (ROOT / "docs/usage/views.md").read_text(encoding="utf-8")
    assert "Executor" in views
    assert "Custom 3.2 subclasses" in views
    assert "runtime dependency floor is now 3.3" in " ".join(views.lower().split())
    for path in (ROOT / "CHANGELOG.md", ROOT / "docs/changelog.md"):
        notes = path.read_text(encoding="utf-8")
        assert "## Unreleased" in notes
        assert FLOOR in notes.split("## 3.1.1 — 2026-10-01", maxsplit=1)[0]
        patch = notes.split("## 3.1.1 — 2026-10-01", maxsplit=1)[1]
        assert "3.2.13" in patch
