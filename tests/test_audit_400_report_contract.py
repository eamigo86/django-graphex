"""Keep the 4.0.0 audit report complete and bounded to verified claims."""

from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/audit-4.0.0.md"
GROUPS = (
    ("C", 3),
    ("A", 13),
    ("SD", 6),
    ("M-S", 6),
    ("M-D", 10),
    ("M-F", 7),
    ("M-H", 4),
    ("M-O", 2),
    ("M-U", 6),
    ("M-T", 1),
    ("L-C", 13),
    ("L-E", 4),
    ("L-M", 4),
    ("L-S", 4),
    ("Q", 10),
    ("P", 1),
    ("N", 6),
)
EXPECTED_IDS = tuple(
    f"{prefix}{number}" for prefix, count in GROUPS for number in range(1, count + 1)
)
EXPECTED_COUNTS = {
    "bounded-fixed": 41,
    "partial": 26,
    "contract": 9,
    "recommendation": 7,
    "negative-limited": 6,
    "decision-deferred": 11,
}


def _report() -> str:
    """Read the published audit report.

    Returns:
        The complete report text.
    """
    return REPORT.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """Select a report section without accepting matches elsewhere.

    Args:
        text: Complete Markdown document.
        heading: Exact second-level heading.

    Returns:
        Body up to the next second-level heading.
    """
    marker = f"## {heading}\n"
    assert text.count(marker) == 1
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def _dispositions(text: str) -> list[tuple[str, str, str, str, str]]:
    """Parse the primary five-column disposition table.

    Args:
        text: Complete Markdown document.

    Returns:
        Ordered ID, status, outcome, example, and evidence cells.
    """
    body = _section(text, "All 100 original claims")
    lines = [line for line in body.splitlines() if line.startswith("|")]
    assert lines[:2] == [
        "| ID | Status | Finding, outcome, and limit | Small example | Evidence |",
        "|---|---|---|---|---|",
    ]
    rows = []
    for line in lines[2:]:
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        assert len(cells) == 5
        rows.append(cells)
    return rows


def test_primary_table_preserves_exact_original_order_and_status_totals() -> None:
    """Require one disposition per original ID, not one per work-unit task.

    Work-unit counts and audit-ID counts are intentionally different.
    """
    report = _report()
    rows = _dispositions(report)
    assert tuple(row[0] for row in rows) == EXPECTED_IDS
    assert len(set(row[0] for row in rows)) == 100
    assert Counter(row[1] for row in rows) == EXPECTED_COUNTS
    assert all(row[2] and row[3] and row[4] for row in rows)
    assert all("→" in row[3] and len(row[3]) >= 25 for row in rows)
    assert all((ROOT / row[4].strip("`")).is_file() for row in rows)
    assert "41 does not mean 41 fully closed issues" in report
    assert "not a claim that all 100 issues were fixed" in report


def test_dispositions_keep_important_counterexamples_and_boundaries() -> None:
    """Keep narrowly contradicted claims separate from unproved wider ones.

    A representative counterexample must not close a broader finding.
    """
    rows = {row[0]: row for row in _dispositions(_report())}
    assert rows["SD1"][1] == "partial" and "get_queryset" in rows["SD1"][2]
    assert rows["M-D5"][1] == "contract" and "JSONString" in rows["M-D5"][2]
    assert rows["M-D4"][1] == "partial" and "1E+999999999" in rows["M-D4"][2]
    assert rows["M-U1"][1] == "partial" and "retry works" in rows["M-U1"][2]
    assert rows["L-C8"][1] == "contract" and "tail window" in rows["L-C8"][2]
    assert rows["L-C9"][1] == "partial" and "offset/page" in rows["L-C9"][2]
    assert rows["L-E3"][1] == "partial" and "SITE-B" in rows["L-E3"][2]
    assert (
        rows["Q8"][1] == "negative-limited" and "MUTATION_ERRORS_FLAG" in rows["Q8"][2]
    )
    assert (
        rows["N1"][1] == "negative-limited" and "effective permission" in rows["N1"][2]
    )
    assert (
        rows["N3"][1] == "negative-limited"
        and "MaxIntrospectionDepthRule" in rows["N3"][2]
    )
    assert rows["N4"][1] == "contract" and "process-global" in rows["N4"][2]
    assert "SSE" in rows["L-S1"][3] and "WebSocket" not in rows["L-S1"][3]
    assert "GraphQLError" in rows["M-F6"][2]
    assert "results: null" in rows["M-F6"][3] and "fallback" not in rows["M-F6"][3]
    assert "page_size=None" in rows["M-F7"][2]
    assert "pageSize:null" in rows["M-F7"][3] and "100" in rows["M-F7"][3]
    assert "MAX_BATCH_SIZE" in rows["L-C5"][2]
    assert "MAX_REQUEST_BODY_SIZE" in rows["L-C5"][2]
    assert "DOCUMENT_CACHE_MAXSIZE" in rows["L-C5"][2]
    assert "negative" in rows["L-C5"][3] and "zero" in rows["L-C5"][3]


def test_registry_and_factory_examples_state_the_actual_unit() -> None:
    """Distinguish model-registry conflicts from input-object coercions.

    The report must name the real ownership boundary for each correction.
    """
    rows = {row[0]: row for row in _dispositions(_report())}
    a4 = " ".join(rows["A4"][2:4])
    assert "same model" in a4 and "same registry" in a4
    assert "different names" in a4 and "separate registries" in a4
    a7 = " ".join(rows["A7"][2:4])
    assert "coerced input object" in a7
    assert "two aliases" in a7 and "one variable" in a7
    assert "introspection" in a7 and "factory" in a7


def test_false_positive_subclaims_keep_counterexample_and_residual() -> None:
    """Separate contradicted premises from unproved whole-claim conclusions.

    Every named subclaim needs a counterexample and a remaining limit.
    """
    section = _section(_report(), "False-positive subclaims and corrected premises")
    for original_id, allegation, counterexample in (
        ("M-D5", "raw JSON", "JSONString"),
        ("L-C8", "positive final", "tail window"),
        ("L-E3", "SITE-B", "hook ran once"),
        ("N4", "request-scoped", "process-global"),
        ("Q8", "dead", "MUTATION_ERRORS_FLAG"),
        ("Q1", "mismatch", "3.2.13"),
        ("M-U3", "never match", "not verified"),
    ):
        line = next(
            line
            for line in section.splitlines()
            if line.startswith(f"| {original_id} |")
        )
        assert allegation in line and counterexample in line
        assert "remains" in line or "unproved" in line
    assert "SD1" in section and "confirmed" in section


def test_report_discloses_original_tdd_limit_without_rewriting_history() -> None:
    """Keep the earlier RED and later unequal test bytes distinguishable.

    A narrower later same-byte cycle cannot repair the original mismatch.
    """
    limits = _section(_report(), "Verification and provenance limits")
    assert "original RED" in limits and "file absence" in limits
    assert "not identical" in limits and "helper" in limits
    assert "same-byte" in limits and "later" in limits


def test_examples_and_decision_queue_do_not_turn_boundaries_into_fixes() -> None:
    """Require concrete outcomes and explicit unresolved policy ownership.

    The examples explain behavior while the queue preserves decision gates.
    """
    report = _report()
    examples = _section(report, "Examples of corrected and unchanged behavior")
    for fragment in (
        "9007199254740993",
        "1.0",
        "1.00",
        "GraphQLError",
        "hidden destination ID",
        "ok: false",
        "cache miss",
        "cache hit",
    ):
        assert fragment in examples
    decisions = _section(report, "Decisions still required")
    for fragment in (
        "R02b",
        "R05c",
        "R09b",
        "SD1",
        "SD2",
        "SD6",
        "M-D1",
        "L-C9",
        "L-S3",
        "Q10",
    ):
        assert fragment in decisions
    limits = _section(report, "Verification and provenance limits")
    assert "seven" in limits and "DOC002" in limits
    assert "PostgreSQL" in limits and "CI" in limits
    assert "not run" in limits
    assert "ResourceWarning" in limits


def test_report_is_navigable_and_release_notes_do_not_claim_release() -> None:
    """Link the local audit outcome without claiming publication or closure.

    Both changelogs point to the same report without announcing a release.
    """
    assert "audit-4.0.0.md" in (ROOT / "zensical.yml").read_text(encoding="utf-8")
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        unreleased = text.split("## Unreleased\n", 1)[1].split("\n## ", 1)[0]
        assert "100 original audit claims" in unreleased
        assert "audit-4.0.0.md" in unreleased
        assert "not a release" in unreleased
