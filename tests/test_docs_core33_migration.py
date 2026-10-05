"""Executable documentation contracts for the core33 migration."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERIES = "core33-4.0.0-bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e"
RESULTS = ROOT / "benchmarks/results" / SERIES
LIBRARIES = ("graphex", "graphene", "strawberry", "ariadne")
OPERATIONS = ("flat_list", "nested", "single", "filtered", "create_comment")


def _load_result(library: str, authors: int) -> dict:
    """Load one committed portable result.

    Args:
        library: Library represented by the artifact.
        authors: Seed size represented by the artifact.

    Returns:
        Parsed portable result.
    """
    prefix = "2x_" if authors == 2000 else ""
    return json.loads((RESULTS / f"{prefix}{library}.json").read_text(encoding="utf-8"))


def test_comparison_intro_names_all_four_retained_series() -> None:
    """Count the current series and each retained historical comparison.

    The introduction must not omit the pre-fragment 4.0.0 result series.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    intro = page.split("## How it compares", maxsplit=1)[1].split(
        "## Current core33 comparison", maxsplit=1
    )[0]
    for label in (
        "four distinct benchmark series",
        SERIES,
        "core33-4.0.0-01f82ab94c86a5f35918dec4ba51deee02a58ac9",
        "3.1.1-source core33",
        "original 3.1.0",
    ):
        assert label in intro


def test_current_comparison_table_is_derived_from_eight_artifacts() -> None:
    """Keep every published latency and SQL cell bound to committed data.

    The table is checked against the portable result files, not a duplicate
    set of expected numeric constants in this test.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- core33-results:start -->\n(.*?)\n<!-- core33-results:end -->",
        page,
        re.DOTALL,
    )
    assert match is not None

    rows = [
        "| Authors | Library | Flat list | Nested | Single | Filtered | Create comment |",
        "| :-- | :-- | --: | --: | --: | --: | --: |",
    ]
    for authors in (1000, 2000):
        for library in LIBRARIES:
            result = _load_result(library, authors)
            assert result["dataset"] == {
                "authors": authors,
                "posts_per_author": 10,
                "comments_per_post": 5,
            }
            cells = [
                f"{result['operations'][operation]['p50_ms']:.4f} ms / "
                f"{result['operations'][operation]['sql_queries']} SQL"
                for operation in OPERATIONS
            ]
            rows.append(f"| {authors:,} | {library} | " + " | ".join(cells) + " |")
    assert match.group(1).strip() == "\n".join(rows)


def test_current_results_guidance_distinguishes_provenance_and_statistics() -> None:
    """Distinguish the new whole-stack comparison from historical releases.

    The measured source and prepared seed have distinct repository witnesses.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    current = page.split("## Current core33 comparison", maxsplit=1)[1].split(
        "### Historical core33 3.1.1-source comparison", maxsplit=1
    )[0]
    current = " ".join(current.replace("**", "").split())
    result = _load_result("graphex", 1000)
    for token in (
        result["measurement_source"]["commit"],
        result["measurement_source"]["tree"],
        result["seed_source"]["commit"],
        "Python 3.12.11",
        "Django 6.0.8",
        "graphql-core 3.3.0",
        "graphql-core 3.2.13",
        "per-run p95",
        "not a pooled 300-sample percentile",
        "schema rebuild",
        "Raw SHA-256",
        "prepared 4.0.0 source",
    ):
        assert token in current
    assert f"benchmarks/results/{SERIES}/" in current
    assert "826d5bae87ed7bbe705cf309d46a16d3ad3cdf33" in current
    assert "bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e" in current
    assert "Historical core33 4.0.0 pre-fragment comparison" in page
    assert "benchmarks/run_publish_core33.py" in current


def test_current_public_summary_uses_new_artifact_values() -> None:
    """Keep the current public summary aligned with the new measured series.

    The expected ratios come from the committed portable result fields.
    """
    ratios = []
    for authors in (1000, 2000):
        graphex = _load_result("graphex", authors)
        ariadne = _load_result("ariadne", authors)
        graphex_ms = graphex["operations"]["create_comment"]["p50_ms"]
        ariadne_ms = ariadne["operations"]["create_comment"]["p50_ms"]
        ratios.append(graphex_ms / ariadne_ms)
    for path in (ROOT / "README.md", ROOT / "docs/why.md"):
        text = path.read_text(encoding="utf-8")
        assert SERIES in text
        for ratio in ratios:
            assert f"{ratio:.2f}×" in text
    for path in (ROOT / "CHANGELOG.md", ROOT / "docs/changelog.md"):
        current = path.read_text(encoding="utf-8").split("## 3.1.1", 1)[0]
        assert SERIES in current
        assert "4.0.0 source" in current
        assert _load_result("graphex", 1000)["measurement_source"]["commit"] in current
        for ratio in ratios:
            assert f"{ratio:.2f}×" in current


def test_current_stack_versions_match_committed_results() -> None:
    """Bind the documented version split to the artifact metadata.

    Both seed sizes must carry the same selected whole-stack versions.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- core33-stacks:start -->\n(.*?)\n<!-- core33-stacks:end -->",
        page,
        re.DOTALL,
    )
    assert match is not None
    rows = ["| Library | Selected whole-stack versions |", "| :-- | :-- |"]
    for library in LIBRARIES:
        versions = _load_result(library, 1000)["whole_stack"]["versions"]
        assert versions == _load_result(library, 2000)["whole_stack"]["versions"]
        cells = ", ".join(
            f"{name} {version}" for name, version in sorted(versions.items())
        )
        rows.append(f"| {library} | {cells} |")
    assert match.group(1).strip() == "\n".join(rows)


def test_upgrade_guide_and_changelogs_cover_the_actual_migration() -> None:
    """Expose implemented breaking changes without declaring a release.

    Version requirements remain accurate before and after publication.
    """
    guide = (ROOT / "docs/UPGRADE-4.0.md").read_text(encoding="utf-8")
    nav = (ROOT / "zensical.yml").read_text(encoding="utf-8")
    assert "UPGRADE-4.0.md" in nav
    heading = guide.splitlines()[0].removeprefix("# ")
    assert f"- {heading}: UPGRADE-4.0.md" in nav
    assert "## Version requirements" in guide
    for token in (
        "graphql-core>=3.3.0,<3.4",
        "Executor",
        "ExecutionContext",
        "immutable AST",
        "alias",
        "subscription",
        "queryset",
        "coercion",
        "cost",
        "4.0.0",
    ):
        assert token in guide
    for path in (ROOT / "CHANGELOG.md", ROOT / "docs/changelog.md"):
        notes = path.read_text(encoding="utf-8").split(
            "## 3.1.1 — 2026-10-01", maxsplit=1
        )[0]
        for token in ("immutable AST", "Executor", "subscription", "alias", "core33"):
            assert token in notes


def test_playground_banner_targets_400_checkout() -> None:
    """Avoid presenting the example as a v3.1-only application.

    Existing security and example guidance remains valid for this checkout.
    """
    page = (ROOT / "examples/playground/README.md").read_text(encoding="utf-8")
    banner = page.split("A small, runnable", maxsplit=1)[0]
    assert "Targets django-graphex v3.1" not in banner
    assert "4.0.0 checkout" in banner.lower()
    assert "graphql-core 3.3" in banner
    assert "--no-migrations --no-cov" in page
