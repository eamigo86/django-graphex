"""Keep the changelog, the 4.1 upgrade guide and the settings page consistent."""

import re
import unicodedata
from pathlib import Path

from django_graphex.settings import DEFAULTS

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
DOCS_CHANGELOG = ROOT / "docs" / "changelog.md"
UPGRADE = ROOT / "docs" / "UPGRADE-4.1.md"
SETTINGS = ROOT / "docs" / "usage" / "settings.md"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _slug(heading: str) -> str:
    """Derive the fragment the docs builder gives a heading.

    Args:
        heading: Heading text after its hash prefix.

    Returns:
        The Markdown "toc" slug: ASCII, lowercase, word characters kept.
    """
    plain = unicodedata.normalize("NFKD", heading.replace("`", ""))
    ascii_text = plain.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", ascii_text).strip().lower())


def _section(text: str, start: str, end: str) -> str:
    """Return the text between two markers.

    Args:
        text: The document.
        start: Marker that opens the section (included).
        end: Marker that closes it (excluded).

    Returns:
        The slice from "start" up to "end".
    """
    return text[text.index(start) : text.index(end)]


def _release_section(path: Path) -> str:
    """Read the 4.1.0 release section of a changelog.

    Args:
        path: The changelog file.

    Returns:
        The text from the 4.1.0 heading to the 4.0.0 heading.
    """
    return _section(path.read_text(encoding="utf-8"), "## 4.1.0", "## 4.0.0")


def test_every_behavior_change_links_to_an_upgrade_guide_anchor() -> None:
    """Every "Behavior changes" bullet has a migration link that resolves.

    Contract: this ships broken if a bullet has no link into the upgrade guide or
    links to a heading that does not exist there.
    """
    anchors = {
        _slug(m) for m in re.findall(r"^#{2,6} (.+)$", UPGRADE.read_text("utf-8"), re.M)
    }
    behavior = _section(
        _release_section(CHANGELOG), "### Behavior changes", "### Added settings"
    )
    bullets = [line for line in behavior.splitlines() if line.startswith("- ")]
    assert bullets
    for bullet in bullets:
        fragments = [
            target.split("#", 1)[1]
            for target in LINK.findall(bullet)
            if target.startswith("docs/UPGRADE-4.1.md#")
        ]
        assert fragments, bullet
        for fragment in fragments:
            assert fragment in anchors, (fragment, bullet)


def test_relative_links_in_the_root_changelog_resolve() -> None:
    """Every relative link in "CHANGELOG.md" points at a file from the repo root.

    Contract: this ships broken if a link only works from inside "docs/".
    """
    for target in LINK.findall(CHANGELOG.read_text(encoding="utf-8")):
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        assert (ROOT / target.split("#", 1)[0]).exists(), target


def test_release_section_is_mirrored_in_the_docs_changelog() -> None:
    """The 4.1.0 section of both changelogs differs only by the docs/ link prefix.

    Contract: this ships broken if the two changelogs drift apart.
    """
    root = _release_section(CHANGELOG).replace("](docs/", "](")
    assert root == _release_section(DOCS_CHANGELOG)


def test_settings_page_defaults_block_lists_every_default() -> None:
    """Every key of "DEFAULTS" appears in the settings page defaults block.

    Contract: this ships broken if a setting is added without documenting it.
    """
    text = SETTINGS.read_text(encoding="utf-8")
    block = text.split("```python", 1)[1].split("```", 1)[0]
    missing = [key for key in DEFAULTS if f'"{key}"' not in block]
    assert not missing, missing
