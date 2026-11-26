"""Contracts for the 4.2.0 release metadata, notes and upgrade section."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.2.0"
DATE = "2026-11-26"
FLOOR = "graphql-core>=3.3.1,<3.4"


def test_install_snippet_in_the_4_2_guide_pins_4_2_0() -> None:
    """Keep the 4.2 guide pinned to the release it describes.

    The newer guide carries the current pin; this one stays on 4.2.0.
    """
    text = (ROOT / "docs/UPGRADE-4.2.md").read_text(encoding="utf-8")
    assert f'pip install "django-graphex=={VERSION}"' in text
    assert FLOOR in text


def test_changelog_dates_the_release_above_4_1_1() -> None:
    """Date the 4.2.0 section and keep 4.1.1 directly below it.

    Both changelog copies list 4.2.0 and then 4.1.1, and the Added entry links
    to the upgrade note. A 4.3.0 section may sit above 4.2.0.
    """
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        notes = (ROOT / relative).read_text(encoding="utf-8")
        headings = [line for line in notes.splitlines() if line.startswith("## ")]
        headings = headings[headings.index(f"## {VERSION} — {DATE}") :]
        assert headings[:2] == [f"## {VERSION} — {DATE}", "## 4.1.1 — 2026-11-26"]
        section = notes.split(headings[0], maxsplit=1)[1].split(headings[1])[0]
        assert "### Added" in section
        assert "graphql-ws" in section
        assert "SUBSCRIPTION_PATH" in section
        assert "#258" in section
        assert "UPGRADE-4.2.md#upgrading-to-420" in section


def test_upgrade_guide_has_a_4_2_0_section() -> None:
    """Tell 4.1 users what the GraphiQL subscriptions change loads.

    The section lives in its own 4.2 guide and names the extra script, the
    WebSocket, CSP and the offline template hook.
    """
    guide = (ROOT / "docs/UPGRADE-4.2.md").read_text(encoding="utf-8")
    assert guide.startswith("# Upgrading to django-graphex 4.2\n")
    assert "\n## Upgrading to 4.2.0\n" in guide
    section = guide.split("\n## Upgrading to 4.2.0\n", maxsplit=1)[1]
    section = section.split("\n## ", maxsplit=1)[0]
    for needle in (
        "graphql-ws",
        "unpkg",
        "CSP",
        "WebSocket",
        "SUBSCRIPTION_PATH",
        "/ws/graphql/",
        "graphiql_template",
    ):
        assert needle in section


def test_upgrade_guides_are_split_by_minor_release() -> None:
    """Keep the 4.2 notes out of the 4.1 guide and link the guides in order.

    The 4.1 guide pins its last patch and points to the 4.2 guide; the
    navigation lists the newer guide first.
    """
    old = (ROOT / "docs/UPGRADE-4.1.md").read_text(encoding="utf-8")
    assert "## Upgrading to 4.2.0" not in old
    assert 'pip install "django-graphex==4.1.1"' in old
    assert "[4.2 upgrade guide](UPGRADE-4.2.md)" in old
    nav = (ROOT / "zensical.yml").read_text(encoding="utf-8")
    assert "Upgrading to django-graphex 4.2: UPGRADE-4.2.md" in nav
    assert nav.index("UPGRADE-4.2.md") < nav.index("UPGRADE-4.1.md")
