"""Contracts for the 4.1.1 release metadata, notes and upgrade section."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.1.1"
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
        assert packages["graphql-core"]["version"].startswith("3.3.")
        locked = tuple(int(n) for n in packages["graphql-core"]["version"].split("."))
        assert locked >= (3, 3, 1)


def test_install_snippets_name_the_current_version() -> None:
    """Reject install commands that pin an earlier release.

    Both the README and the installation page carry them.
    """
    for relative in ("README.md", "docs/installation.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f'pip install "django-graphex=={VERSION}"' in text
        assert f'uv add "django-graphex[subscriptions]=={VERSION}"' in text
        assert 'django-graphex==4.1.0"' not in text
        assert FLOOR in text


def test_changelog_dates_the_release_above_4_1_0() -> None:
    """Date the 4.1.1 section and keep it the first heading.

    Both changelog copies list 4.1.1 first and 4.1.0 directly after it, and no
    "Unreleased" heading remains.
    """
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        notes = (ROOT / relative).read_text(encoding="utf-8")
        headings = [line for line in notes.splitlines() if line.startswith("## ")]
        assert "## Unreleased" not in headings
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
