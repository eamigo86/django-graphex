"""Check local HTML page links and fragments in a generated documentation site."""

from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PageLinks(HTMLParser):
    """Collect link destinations and declared anchors from one HTML page."""

    def __init__(self) -> None:
        """Initialize independent collections for a single parsed page."""
        super().__init__(convert_charrefs=True)
        self.anchors: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Collect HTML IDs, named anchors and hyperlink targets.

        Args:
            tag: Lowercase HTML element name.
            attrs: Parsed element attributes.
        """
        values = dict(attrs)
        if values.get("id"):
            self.anchors.add(values["id"])
        if tag == "a" and values.get("name"):
            self.anchors.add(values["name"])
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])


def _destination(
    site: Path, source: Path, href: str, base_path: str
) -> tuple[Path, str] | None:
    """Resolve a local HTML link without leaving the generated site.

    Args:
        site: Generated site root.
        source: Page containing the hyperlink.
        href: Hyperlink target.
        base_path: Deployment URL path for absolute links.

    Returns:
        Target HTML path and fragment, or None for an external or asset link.

    Raises:
        ValueError: A local hyperlink escapes the generated site.
    """
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return None
    raw_path = unquote(parsed.path)
    if raw_path.startswith("/") and base_path != "/":
        if not raw_path.startswith(base_path):
            return None
        raw_path = raw_path[len(base_path) :]
    if raw_path and Path(raw_path).suffix not in ("", ".html"):
        return None
    candidate = (
        site / raw_path.lstrip("/")
        if raw_path.startswith("/")
        else source.parent / raw_path
    )
    if not raw_path:
        candidate = source
    if candidate.suffix != ".html":
        candidate /= "index.html"
    target = candidate.resolve()
    if not target.is_relative_to(site):
        raise ValueError(f"local link escapes site: {href}")
    return target, unquote(parsed.fragment)


def check_site(site: Path, base_path: str = "/") -> list[str]:
    """Find broken local HTML destinations and fragments in generated pages.

    Args:
        site: Generated documentation root.
        base_path: Deployment URL path for absolute links.

    Returns:
        Diagnostics for missing files or fragment targets.

    Raises:
        ValueError: The site is missing or has no HTML pages.
    """
    if not site.is_dir():
        raise ValueError(f"site directory not found: {site}")
    pages = sorted(site.rglob("*.html"))
    if not pages:
        raise ValueError(f"no HTML pages in site: {site}")
    parsed: dict[Path, PageLinks] = {}
    for page in pages:
        content = PageLinks()
        content.feed(page.read_text(encoding="utf-8"))
        parsed[page.resolve()] = content
    errors: list[str] = []
    for page, content in parsed.items():
        for href in content.links:
            try:
                resolved = _destination(site, page, href, base_path)
            except ValueError as exc:
                errors.append(f"{page.relative_to(site)}: {exc}")
                continue
            if resolved is None:
                continue
            target, fragment = resolved
            if target not in parsed:
                errors.append(f"{page.relative_to(site)}: missing page for {href}")
            elif fragment and fragment not in parsed[target].anchors:
                errors.append(
                    f"{page.relative_to(site)}: missing fragment {fragment} in {href}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    """Validate a generated site and print all broken local HTML links.

    Args:
        argv: Command arguments, or process arguments when omitted.

    Returns:
        Zero for a valid site and one for missing or broken local links.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path, help="generated site directory")
    parser.add_argument(
        "--base-path", default="/", help="deployment URL path (default: /)"
    )
    args = parser.parse_args(argv)
    if not args.base_path.startswith("/") or not args.base_path.endswith("/"):
        parser.error("base path must start and end with /")
    site = args.site.resolve()
    try:
        errors = check_site(site, args.base_path)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"site anchor check failed: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f"checked {len(list(site.rglob('*.html')))} HTML pages: local links valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
