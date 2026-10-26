"""Executable documentation contracts for the core33 migration."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERIES = "core33-4.1.0-f9f4eae81954959ab71e4a9037d5ba06486d6a8e"
PREVIOUS_SERIES = "core33-4.1.0-460efb9b7c29b097f2939c05e79514f2fda3242c"
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


def test_comparison_intro_names_all_six_retained_series() -> None:
    """Count the current series and each retained historical comparison.

    The introduction must not omit either earlier 4.0.0 result series.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    intro = page.split("## How it compares", maxsplit=1)[1].split(
        "## Current core33 comparison", maxsplit=1
    )[0]
    for label in (
        "six distinct benchmark series",
        SERIES,
        PREVIOUS_SERIES,
        "core33-4.0.0-bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e",
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


def test_current_write_mean_table_uses_run_mean_medians() -> None:
    """Bind the write mean comparison to the separate run-mean statistic.

    The published table must not substitute the p50 statistic for a mean.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- core33-write-mean:start -->\n(.*?)\n<!-- core33-write-mean:end -->",
        page,
        re.DOTALL,
    )
    assert match is not None
    rows = [
        "| Comments | GraphEx mean | Ariadne mean | GraphEx less mean time |",
        "| :-- | --: | --: | --: |",
    ]
    for authors in (1000, 2000):
        graphex = _load_result("graphex", authors)["operations"]["create_comment"]
        ariadne = _load_result("ariadne", authors)["operations"]["create_comment"]
        reduction = 100 * (1 - graphex["mean_ms"] / ariadne["mean_ms"])
        rows.append(
            f"| {authors * 50:,} | {graphex['mean_ms']:.4f} ms | "
            f"{ariadne['mean_ms']:.4f} ms | {reduction:.2f}% |"
        )
    assert match.group(1).strip() == "\n".join(rows)


def test_current_results_guidance_distinguishes_provenance_and_statistics() -> None:
    """Distinguish the new whole-stack comparison from historical releases.

    The measured source and prepared seed have distinct repository witnesses.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    current = page.split("## Current core33 comparison", maxsplit=1)[1].split(
        "### Historical core33 4.1.0 comparison", maxsplit=1
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
        "4.1.0 source",
    ):
        assert token in current
    assert f"benchmarks/results/{SERIES}/" in current
    assert PREVIOUS_SERIES not in current
    assert PREVIOUS_SERIES in page.split("### Historical core33 4.1.0 comparison", 1)[1]
    assert "Historical core33 4.0.0 comparison" in page
    assert "Historical core33 4.0.0 pre-fragment comparison" in page
    assert "benchmarks/run_publish_core33.py" in current


def test_current_public_summary_uses_new_artifact_values() -> None:
    """Keep the current public summary aligned with the new measured series.

    The expected ratios come from the committed portable result fields.
    """
    mean_reductions = []
    mean_pairs = []
    p50_ratios = []
    for authors in (1000, 2000):
        graphex = _load_result("graphex", authors)
        ariadne = _load_result("ariadne", authors)
        graphex_op = graphex["operations"]["create_comment"]
        ariadne_op = ariadne["operations"]["create_comment"]
        mean_pairs.append((graphex_op["mean_ms"], ariadne_op["mean_ms"]))
        mean_reductions.append(
            100 * (1 - graphex_op["mean_ms"] / ariadne_op["mean_ms"])
        )
        p50_ratios.append(graphex_op["p50_ms"] / ariadne_op["p50_ms"])
    for path in (ROOT / "README.md", ROOT / "docs/why.md"):
        text = " ".join(path.read_text(encoding="utf-8").split())
        assert SERIES in text
        for reduction in mean_reductions:
            assert f"{reduction:.2f}% less mean time" in text
        for graphex_mean, ariadne_mean in mean_pairs:
            assert f"{graphex_mean:.4f} vs {ariadne_mean:.4f} ms" in text
        for ratio in p50_ratios:
            assert f"{ratio:.2f}×" in text
        assert "local SQLite" in text
        assert "not a paired historical comparison" in text
        assert "mean of three run means" not in text
    for path in (ROOT / "CHANGELOG.md", ROOT / "docs/changelog.md"):
        current = path.read_text(encoding="utf-8").split("## 3.1.1", 1)[0]
        assert SERIES in current
        assert "4.1.0 source" in current
        assert _load_result("graphex", 1000)["measurement_source"]["commit"] in current
        for reduction in mean_reductions:
            assert f"{reduction:.2f}% less mean time" in current
        for ratio in p50_ratios:
            assert f"{ratio:.2f}×" in current
        assert "local SQLite" in current


def test_current_batch_ranking_is_scoped_to_both_statistics() -> None:
    """Require the local-only ranking to match both published statistics.

    This assertion does not generalize the ranking beyond the selected batch.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    current = page.split("## Current core33 comparison", 1)[1].split(
        "### Historical core33 4.1.0 comparison", 1
    )[0]
    current = " ".join(current.split())
    for authors in (1000, 2000):
        results = {library: _load_result(library, authors) for library in LIBRARIES}
        for operation in OPERATIONS:
            for statistic in ("mean_ms", "p50_ms"):
                graphex = results["graphex"]["operations"][operation][statistic]
                assert all(
                    graphex < results[library]["operations"][operation][statistic]
                    for library in LIBRARIES
                    if library != "graphex"
                )
    assert (
        "lowest observed mean and p50 in all ten operation/seed combinations" in current
    )
    assert "only in this local batch" in current


def test_current_cold_import_table_is_derived_from_eight_artifacts() -> None:
    """Keep the current cold-import medians bound to the committed data.

    The historical claim that graphex and graphene-django import in about the
    same time must not be repeated for the current series.
    """
    page = (ROOT / "docs/why.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- core33-cold-import:start -->\n(.*?)\n<!-- core33-cold-import:end -->",
        page,
        re.DOTALL,
    )
    assert match is not None
    rows = [
        "| Library | 1,000-author seed | 2,000-author seed |",
        "| :-- | --: | --: |",
    ]
    for library in LIBRARIES:
        cells = [
            f"{_load_result(library, authors)['schema_import_ms']:.2f} ms"
            for authors in (1000, 2000)
        ]
        rows.append(f"| {library} | {cells[0]} | {cells[1]} |")
    assert match.group(1).strip() == "\n".join(rows)


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


def test_playground_banner_targets_current_checkout() -> None:
    """Avoid presenting the example as a v3.1-only application.

    Existing security and example guidance remains valid for this checkout.
    """
    page = (ROOT / "examples/playground/README.md").read_text(encoding="utf-8")
    banner = page.split("A small, runnable", maxsplit=1)[0]
    assert "Targets django-graphex v3.1" not in banner
    assert "4.1.0 checkout" in banner.lower()
    assert "graphql-core 3.3" in banner
    # The playground has no coverage plugin, so --no-cov is an unknown flag
    # there; the documented commands must be the ones that actually run.
    assert "uv run --group test pytest -q --no-migrations" in page
    assert "DJANGO_SETTINGS_MODULE=config.settings python -m pytest" in page
    assert "--no-migrations --no-cov" not in page
