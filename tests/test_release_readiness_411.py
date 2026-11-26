"""Contracts for the 4.1.1 release metadata, notes and upgrade section."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.1.1"
DATE = "2026-11-26"
FLOOR = "graphql-core>=3.3.1,<3.4"


def test_changelog_dates_the_release_above_4_1_0() -> None:
    """Keep the dated 4.1.1 section directly above 4.1.0.

    Both changelog copies list 4.1.1 and then 4.1.0. Later releases and an
    "Unreleased" heading may sit above 4.1.1.
    """
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        notes = (ROOT / relative).read_text(encoding="utf-8")
        headings = [line for line in notes.splitlines() if line.startswith("## ")]
        start = headings.index(f"## {VERSION} — {DATE}")
        headings = headings[start:]
        assert headings[:2] == [f"## {VERSION} — {DATE}", "## 4.1.0 — 2026-10-27"]
        section = notes.split(headings[0], maxsplit=1)[1].split(headings[1])[0]
        assert FLOOR in section
        assert "CVE-2026-119286" in section
        assert "QUERY_TOO_COMPLEX" in section
        assert "#255" in section
        assert "UPGRADE-4.1.md#upgrading-to-411" in section


def test_upgrade_guide_has_a_4_1_1_section() -> None:
    """Tell 4.1.0 users about the floor and the lower cost estimates.

    The section sits in the 4.1 guide and names both actions.
    """
    guide = (ROOT / "docs/UPGRADE-4.1.md").read_text(encoding="utf-8")
    assert "\n## Upgrading to 4.1.1\n" in guide
    section = guide.split("\n## Upgrading to 4.1.1\n", maxsplit=1)[1]
    section = section.split("\n## ", maxsplit=1)[0]
    assert "3.3.1" in section
    assert "MAX_QUERY_COST" in section
