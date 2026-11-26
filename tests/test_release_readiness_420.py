"""Contracts for the 4.2.0 release metadata, notes and upgrade section."""

import tomllib
from pathlib import Path

from tests._repo_only import requires_repo_paths

ROOT = Path(__file__).resolve().parents[1]
VERSION = "4.2.0"
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

    The README, the installation page and the 4.1 guide carry them.
    """
    for relative in ("README.md", "docs/installation.md", "docs/UPGRADE-4.1.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f'pip install "django-graphex=={VERSION}"' in text
        assert 'django-graphex==4.1.1"' not in text
        assert FLOOR in text or relative == "docs/UPGRADE-4.1.md"
    for relative in ("README.md", "docs/installation.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f'uv add "django-graphex[subscriptions]=={VERSION}"' in text


def test_changelog_dates_the_release_above_4_1_1() -> None:
    """Date the 4.2.0 section and keep 4.1.1 directly below it.

    Both changelog copies list 4.2.0 and then 4.1.1, and the Added entry links
    to the upgrade note. An "Unreleased" heading may sit above 4.2.0.
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
        assert "UPGRADE-4.1.md#upgrading-to-420" in section


def test_upgrade_guide_has_a_4_2_0_section() -> None:
    """Tell 4.1 users what the GraphiQL subscriptions change loads.

    The section sits after 4.1.1 in the 4.1 guide and names the extra script,
    the WebSocket, CSP and the offline template hook.
    """
    guide = (ROOT / "docs/UPGRADE-4.1.md").read_text(encoding="utf-8")
    assert "\n## Upgrading to 4.2.0\n" in guide
    assert guide.index("\n## Upgrading to 4.1.1\n") < guide.index(
        "\n## Upgrading to 4.2.0\n"
    )
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
