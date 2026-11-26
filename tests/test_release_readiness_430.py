"""Contracts for the 4.3.0 release metadata, notes and upgrade guide."""

import tomllib
from pathlib import Path

from tests._repo_only import requires_repo_paths

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.3.0"
DATE = "2026-11-26"
FLOOR = "graphql-core>=3.3.1,<3.4"


def _toml(path: Path) -> dict:
    """Read a TOML document.

    Args:
        path: Project or lock path to parse.

    Returns:
        Parsed TOML document.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


@requires_repo_paths("examples/playground/uv.lock")
def test_version_agrees_with_both_local_locks() -> None:
    """Keep the package and both editable lock entries on one version.

    The graphql-core floor and the locked 3.3.x release are checked too.
    """
    project = _toml(ROOT / "pyproject.toml")["project"]
    assert project["version"] == VERSION
    assert FLOOR in project["dependencies"]
    for path, source in (
        (ROOT / "uv.lock", "."),
        (ROOT / "examples/playground/uv.lock", "../../"),
    ):
        packages = {p["name"]: p for p in _toml(path)["package"]}
        assert packages["django-graphex"]["version"] == VERSION
        assert packages["django-graphex"]["source"] == {"editable": source}
        locked = tuple(int(n) for n in packages["graphql-core"]["version"].split("."))
        assert locked[:2] == (3, 3)
        assert locked >= (3, 3, 1)


def test_install_snippets_name_the_current_version() -> None:
    """Reject install commands that pin an earlier release.

    The README, the installation page and the 4.3 guide carry them.
    """
    for relative in ("README.md", "docs/installation.md", "docs/UPGRADE-4.3.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f'pip install "django-graphex=={VERSION}"' in text
        assert 'django-graphex==4.2.0"' not in text
        assert FLOOR in text
    for relative in ("README.md", "docs/installation.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f'uv add "django-graphex[subscriptions]=={VERSION}"' in text
        assert 'django-graphex[subscriptions]==4.2.0"' not in text


def test_changelog_dates_the_release_above_4_2_0() -> None:
    """Date the 4.3.0 section and keep 4.2.0 directly below it.

    Both changelog copies list 4.3.0 and then 4.2.0, and the section names the
    new error code and links to the upgrade note.
    """
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        notes = (ROOT / relative).read_text(encoding="utf-8")
        headings = [line for line in notes.splitlines() if line.startswith("## ")]
        assert headings[:2] == [f"## {VERSION} — {DATE}", "## 4.2.0 — 2026-11-26"]
        section = notes.split(headings[0], maxsplit=1)[1].split(headings[1])[0]
        assert "OPERATION_NOT_SUPPORTED" in section
        assert "UPGRADE-4.3.md#upgrading-to-430" in section


def test_upgrade_guide_has_a_4_3_0_section() -> None:
    """Tell 4.2 users what the SSE error body and the filter check change.

    The section lives in its own 4.3 guide and names the new error code, the
    content type switch and the transport.
    """
    guide = (ROOT / "docs/UPGRADE-4.3.md").read_text(encoding="utf-8")
    assert guide.startswith("# Upgrading to django-graphex 4.3\n")
    assert "\n## Upgrading to 4.3.0\n" in guide
    section = guide.split("\n## Upgrading to 4.3.0\n", maxsplit=1)[1]
    section = section.split("\n## ", maxsplit=1)[0]
    for needle in ("OPERATION_NOT_SUPPORTED", "application/json", "text/plain", "SSE"):
        assert needle in section


def test_upgrade_guides_link_in_order() -> None:
    """Link the 4.2 guide to the 4.3 guide and list the newer guide first.

    The navigation puts the 4.3 entry above the 4.2 entry.
    """
    old = (ROOT / "docs/UPGRADE-4.2.md").read_text(encoding="utf-8")
    assert "[4.3 upgrade guide](UPGRADE-4.3.md)" in old
    nav = (ROOT / "zensical.yml").read_text(encoding="utf-8")
    assert "Upgrading to django-graphex 4.3: UPGRADE-4.3.md" in nav
    assert nav.index("UPGRADE-4.3.md") < nav.index("UPGRADE-4.2.md")
