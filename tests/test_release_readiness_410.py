"""Contracts for the 4.1.0 release metadata, notes and upgrade guide."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.1.0"


def _toml(path: Path) -> dict:
    """Read a TOML document.

    Args:
        path: Project or lock path to parse.

    Returns:
        Parsed TOML document.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_version_agrees_with_both_local_locks() -> None:
    """Keep the package and both editable lock entries on one version.

    The release does not resolve third-party dependencies anew.
    """
    project = _toml(ROOT / "pyproject.toml")["project"]
    assert project["version"] == VERSION
    for path, source in (
        (ROOT / "uv.lock", "."),
        (ROOT / "examples/playground/uv.lock", "../../"),
    ):
        package = next(
            p for p in _toml(path)["package"] if p["name"] == "django-graphex"
        )
        assert package["version"] == VERSION
        assert package["source"] == {"editable": source}


def test_install_snippets_name_the_current_version() -> None:
    """Reject install commands that pin the previous release.

    Both the README and the installation page carry them.
    """
    for relative in ("README.md", "docs/installation.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f'pip install "django-graphex=={VERSION}"' in text
        assert f'uv add "django-graphex[subscriptions]=={VERSION}"' in text
        assert "django-graphex==4.0.0" not in text


def test_changelog_declares_the_compatibility_policy() -> None:
    """State the policy and list behavior changes first.

    Both changelog copies carry the same 4.1.0 section header.
    """
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        notes = (ROOT / relative).read_text(encoding="utf-8")
        section = notes.split(f"## {VERSION} — Unreleased", maxsplit=1)[1].split(
            "\n## 4.0.0", maxsplit=1
        )[0]
        assert "### Compatibility policy" in section
        assert "### Behavior changes" in section
        assert "UPGRADE-4.1.md" in section
        assert section.index("### Compatibility policy") < section.index(
            "### Behavior changes"
        )


def test_upgrade_guides_are_split_by_release() -> None:
    """Keep the 3.x to 4.0 guide separate from the 4.0 to 4.1 guide.

    The navigation lists the newer guide first.
    """
    old = (ROOT / "docs/UPGRADE-4.0.md").read_text(encoding="utf-8")
    new = (ROOT / "docs/UPGRADE-4.1.md").read_text(encoding="utf-8")
    assert old.startswith("# Upgrading to django-graphex 4.0\n")
    assert new.startswith("# Upgrading to django-graphex 4.1\n")
    assert "4.0 → 4.1" in new or "4.0 to 4.1" in new
    nav = (ROOT / "zensical.yml").read_text(encoding="utf-8")
    assert nav.index("UPGRADE-4.1.md") < nav.index("UPGRADE-4.0.md")
