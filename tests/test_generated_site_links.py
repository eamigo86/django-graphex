"""Contracts for the generated documentation site's local links."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_site_anchors.py"


def _check(site: Path) -> subprocess.CompletedProcess[str]:
    """Run the real site checker against an isolated generated-site fixture.

    Args:
        site: Directory containing generated HTML pages.

    Returns:
        Completed checker process with captured streams.
    """
    return subprocess.run(
        [sys.executable, str(CHECKER), str(site)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_site_checker_resolves_local_pages_and_fragments(tmp_path: Path) -> None:
    """Accept only links whose generated destination and target exist.

    Args:
        tmp_path: Isolated generated-site directory.

    Raises:
        AssertionError: The checker rejects valid local links.
    """
    (tmp_path / "index.html").write_text(
        '<a href="guide/#topic">Guide</a><a href="https://example.com/#remote">'
        'Remote</a><a href="#__skip">Skip</a><h1 id="__skip">Home</h1>'
    )
    guide = tmp_path / "guide"
    guide.mkdir()
    (guide / "index.html").write_text('<h2 id="topic">Topic</h2>')
    result = _check(tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("missing/#topic", "missing"),
        ("guide/#absent", "absent"),
        ("#__skip", "__skip"),
    ],
)
def test_site_checker_rejects_broken_local_links(
    tmp_path: Path, link: str, expected: str
) -> None:
    """Reject missing destinations and fragments, including the 404 skip target.

    Args:
        tmp_path: Isolated generated-site directory.
        link: Broken local hyperlink.
        expected: Diagnostic fragment.

    Raises:
        AssertionError: The checker accepts a broken hyperlink.
    """
    (tmp_path / "404.html").write_text(f'<a href="{link}">Broken</a>')
    if link.startswith("guide/"):
        guide = tmp_path / "guide"
        guide.mkdir()
        (guide / "index.html").write_text('<h2 id="topic">Topic</h2>')
    result = _check(tmp_path)
    assert result.returncode != 0
    assert expected in result.stderr


def test_ci_checks_pure_branches_and_generated_site() -> None:
    """Require both new gates without replacing the existing coverage gates.

    Raises:
        AssertionError: CI lacks a required independent gate.
    """
    workflow = (ROOT / ".github" / "workflows" / "cicd.yaml").read_text()
    coverage = workflow.split("  coverage:\n", 1)[1].split("\n  get-version:", 1)[0]
    assert (
        "uv run python scripts/check_branch_coverage.py coverage.xml --threshold 95.01"
        in coverage
    )
    assert "diff-cover>=10.5.1,<11" in coverage
    assert "uv run pytest" in coverage
    docs = workflow.split("  docs-build:\n", 1)[1].split("\n  playground:", 1)[0]
    assert "uv run python scripts/check_site_anchors.py site" in docs
    assert "--base-path /django-graphex/" in docs
    assert docs.index("zensical build --clean") < docs.index(
        "check_site_anchors.py site"
    )


def test_404_template_provides_the_theme_skip_target() -> None:
    """Require the custom theme page to retain the shared skip-link anchor.

    Raises:
        AssertionError: The override or configured target is absent.
    """
    config = (ROOT / "zensical.yml").read_text()
    assert "custom_dir: docs/overrides" in config
    template = (ROOT / "docs" / "overrides" / "404.html").read_text()
    assert '{% extends "main.html" %}' in template
    assert 'id="__skip"' in template
