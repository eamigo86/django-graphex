"""Keep historical documentation links attached to their actual headings."""

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _heading_slug(heading: str) -> str:
    """Derive the simple site fragment for the historical target headings.

    Args:
        heading: Markdown heading content after its hash prefix.

    Returns:
        Fragment generated from the normalized heading text.
    """
    plain = unicodedata.normalize("NFKD", heading.replace("`", ""))
    ascii_text = plain.encode("ascii", "ignore").decode("ascii").lower()
    words = re.sub(r"[^a-z0-9\s-]", "", ascii_text)
    return re.sub(r"\s+", "-", words.strip())


def test_historical_links_match_existing_target_headings() -> None:
    """Resolve five release and cache links against their Markdown headings.

    This checks source hrefs and target headings together instead of merely
    asserting a copied literal fragment. The generated site is checked
    separately by the documentation build gate.
    """
    cases = (
        ("UPGRADE-3.1.md", "changelog", "changelog.md", "3.1.0 —"),
        ("UPGRADE-3.1.md", "3.1.0 changelog", "changelog.md", "3.1.0 —"),
        ("index.md", "3.1.0 changelog", "changelog.md", "3.1.0 —"),
        (
            "changelog.md",
            "Caching › Bucketing for unauthenticated identities",
            "usage/caching.md",
            "Bucketing for unauthenticated identities",
        ),
        (
            "usage/caching.md",
            "Bucketing for unauthenticated identities",
            "#",
            "Bucketing for unauthenticated identities",
        ),
    )
    docs = ROOT / "docs"
    for source_name, label, target_name, heading_prefix in cases:
        source = (docs / source_name).read_text(encoding="utf-8")
        target = (
            (docs / target_name).read_text(encoding="utf-8")
            if target_name != "#"
            else source
        )
        headings = re.findall(r"^#{2,6} (.+)$", target, flags=re.MULTILINE)
        matched_headings = [
            heading for heading in headings if heading.startswith(heading_prefix)
        ]
        assert len(matched_headings) == 1
        expected_fragment = _heading_slug(matched_headings[0])
        target_prefix = "" if target_name == "#" else target_name
        href = re.search(
            rf"\[{re.escape(label)}\]\({re.escape(target_prefix)}#([^)]+)\)",
            source,
        )
        assert href is not None
        assert href.group(1) == expected_fragment
