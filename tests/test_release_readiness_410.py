"""Contracts for the 4.1.0 release metadata, notes and upgrade guide."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.1.0"


def test_changelog_declares_the_compatibility_policy() -> None:
    """State the policy and list behavior changes first.

    Both changelog copies carry the dated 4.1.0 section header.
    """
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        notes = (ROOT / relative).read_text(encoding="utf-8")
        heading = f"## {VERSION} — 2026-10-27\n"
        assert notes.count(heading) == 1
        section = notes.split(heading, maxsplit=1)[1].split("\n## 4.0.0", maxsplit=1)[0]
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
