"""Stable contract for the frozen bilingual 4.0.0 audit retrospective."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORTS = {
    "en": ROOT / "audit-remediation-django-graphex-4.0.0.en.md",
    "es": ROOT / "audit-remediation-django-graphex-4.0.0.es.md",
}
SNAPSHOT = "8d93483d2fd654012a544ce68365baf1964056f3"
ORIGINAL_SHA256 = "6a0ee92c2fd51ce104080bf4ac5403c24c0e00abc075882735949036d478e561"
EXPECTED_CLAIMS = (
    ("C1", "bounded-fixed"),
    ("C2", "bounded-fixed"),
    ("C3", "bounded-fixed"),
    ("A1", "partial"),
    ("A2", "partial"),
    ("A3", "bounded-fixed"),
    ("A4", "bounded-fixed"),
    ("A5", "bounded-fixed"),
    ("A6", "bounded-fixed"),
    ("A7", "bounded-fixed"),
    ("A8", "bounded-fixed"),
    ("A9", "bounded-fixed"),
    ("A10", "partial"),
    ("A11", "bounded-fixed"),
    ("A12", "bounded-fixed"),
    ("A13", "partial"),
    ("SD1", "partial"),
    ("SD2", "partial"),
    ("SD3", "bounded-fixed"),
    ("SD4", "bounded-fixed"),
    ("SD5", "bounded-fixed"),
    ("SD6", "recommendation"),
    ("M-S1", "bounded-fixed"),
    ("M-S2", "partial"),
    ("M-S3", "contract"),
    ("M-S4", "bounded-fixed"),
    ("M-S5", "bounded-fixed"),
    ("M-S6", "contract"),
    ("M-D1", "partial"),
    ("M-D2", "partial"),
    ("M-D3", "partial"),
    ("M-D4", "partial"),
    ("M-D5", "contract"),
    ("M-D6", "partial"),
    ("M-D7", "bounded-fixed"),
    ("M-D8", "bounded-fixed"),
    ("M-D9", "bounded-fixed"),
    ("M-D10", "bounded-fixed"),
    ("M-F1", "bounded-fixed"),
    ("M-F2", "bounded-fixed"),
    ("M-F3", "partial"),
    ("M-F4", "bounded-fixed"),
    ("M-F5", "bounded-fixed"),
    ("M-F6", "bounded-fixed"),
    ("M-F7", "bounded-fixed"),
    ("M-H1", "bounded-fixed"),
    ("M-H2", "bounded-fixed"),
    ("M-H3", "bounded-fixed"),
    ("M-H4", "partial"),
    ("M-O1", "bounded-fixed"),
    ("M-O2", "bounded-fixed"),
    ("M-U1", "partial"),
    ("M-U2", "partial"),
    ("M-U3", "partial"),
    ("M-U4", "contract"),
    ("M-U5", "bounded-fixed"),
    ("M-U6", "partial"),
    ("M-T1", "bounded-fixed"),
    ("L-C1", "bounded-fixed"),
    ("L-C2", "bounded-fixed"),
    ("L-C3", "bounded-fixed"),
    ("L-C4", "bounded-fixed"),
    ("L-C5", "bounded-fixed"),
    ("L-C6", "contract"),
    ("L-C7", "bounded-fixed"),
    ("L-C8", "contract"),
    ("L-C9", "bounded-fixed"),
    ("L-C10", "bounded-fixed"),
    ("L-C11", "bounded-fixed"),
    ("L-C12", "partial"),
    ("L-C13", "contract"),
    ("L-E1", "bounded-fixed"),
    ("L-E2", "bounded-fixed"),
    ("L-E3", "partial"),
    ("L-E4", "partial"),
    ("L-M1", "decision-deferred"),
    ("L-M2", "partial"),
    ("L-M3", "partial"),
    ("L-M4", "partial"),
    ("L-S1", "partial"),
    ("L-S2", "bounded-fixed"),
    ("L-S3", "bounded-fixed"),
    ("L-S4", "bounded-fixed"),
    ("Q1", "contract"),
    ("Q2", "bounded-fixed"),
    ("Q3", "bounded-fixed"),
    ("Q4", "recommendation"),
    ("Q5", "recommendation"),
    ("Q6", "recommendation"),
    ("Q7", "recommendation"),
    ("Q8", "negative-limited"),
    ("Q9", "recommendation"),
    ("Q10", "decision-deferred"),
    ("P1", "recommendation"),
    ("N1", "negative-limited"),
    ("N2", "negative-limited"),
    ("N3", "negative-limited"),
    ("N4", "contract"),
    ("N5", "negative-limited"),
    ("N6", "negative-limited"),
)
HEADING = re.compile(r"^### ([A-Z][A-Z0-9-]*) — (.+)$", re.MULTILINE)
STATUS = re.compile(r"^\*\*(?:Status|Estado):\*\* ([a-z-]+)$", re.MULTILINE)


def _chapter_sections(text: str) -> list[tuple[str, str]]:
    """Return original-claim chapters without reading external audit artifacts.

    Args:
        text: Complete report Markdown.

    Returns:
        Ordered claim identifiers and chapter bodies.
    """
    matches = list(HEADING.finditer(text))
    expected_ids = {claim_id for claim_id, _ in EXPECTED_CLAIMS}
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        if match.group(1) not in expected_ids:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result.append((match.group(1), text[match.end() : end]))
    return result


def _appendix_rows(text: str, heading: str) -> list[str]:
    """Return Markdown table rows from one named appendix.

    Args:
        text: Complete report Markdown.
        heading: Exact appendix heading in the selected language.

    Returns:
        Data rows after the table header.
    """
    start = text.index(heading) + len(heading)
    next_heading = re.search(r"^## ", text[start:], re.MULTILINE)
    section = (
        text[start : start + next_heading.start()] if next_heading else text[start:]
    )
    return [line for line in section.splitlines() if line.startswith("| `")]


@pytest.mark.parametrize("language", ["en", "es"])
def test_frozen_retrospective_has_all_original_claims(language: str) -> None:
    """Require every frozen finding, status, source anchor, and example.

    Args:
        language: Report language under test.
    """
    path = REPORTS[language]
    assert path.is_file(), f"Missing authorized {language} report: {path.name}"
    text = path.read_text(encoding="utf-8")
    assert SNAPSHOT in text
    assert ORIGINAL_SHA256 in text
    chapters = _chapter_sections(text)
    assert [claim_id for claim_id, _ in chapters] == [
        claim_id for claim_id, _ in EXPECTED_CLAIMS
    ]
    before = (
        "**Before (illustrative):**" if language == "en" else "**Antes (ilustrativo):**"
    )
    after = (
        "**After (observed/current):**"
        if language == "en"
        else "**Después (observado/actual):**"
    )
    for (claim_id, body), (_, expected_status) in zip(
        chapters, EXPECTED_CLAIMS, strict=True
    ):
        assert STATUS.search(body).group(1) == expected_status, claim_id
        assert "auditoria-django-graphex-4.0.0.md" in body, claim_id
        assert before in body and after in body, claim_id
        assert "```" in body, claim_id
        assert re.search(r"^1\. ", body, re.MULTILINE), claim_id


@pytest.mark.parametrize("language", ["en", "es"])
def test_frozen_retrospective_has_complete_evidence_appendices(language: str) -> None:
    """Require complete ancestry and changed-test inventories in both languages.

    Args:
        language: Report language under test.
    """
    text = REPORTS[language].read_text(encoding="utf-8")
    commit_heading = (
        "## Appendix A: commit chronology"
        if language == "en"
        else "## Apéndice A: cronología de commits"
    )
    test_heading = (
        "## Appendix B: changed Python test files"
        if language == "en"
        else "## Apéndice B: archivos de pruebas Python modificados"
    )
    commits = _appendix_rows(text, commit_heading)
    files = _appendix_rows(text, test_heading)
    assert len(commits) == 167
    assert len(files) == 189
    assert (
        len({re.match(r"^\| `([0-9a-f]{40})`", row).group(1) for row in commits}) == 167
    )
    assert len({re.match(r"^\| `([^`]+)`", row).group(1) for row in files}) == 189
    assert "918" in text and "1066" in text
    assert "113" in text and "76" in text


def test_language_versions_preserve_identity_and_code_examples() -> None:
    """Require matching case IDs, statuses, and fenced examples.

    The bilingual prose can differ, but frozen evidence must not.
    """
    versions = {
        language: _chapter_sections(path.read_text(encoding="utf-8"))
        for language, path in REPORTS.items()
    }
    assert [claim_id for claim_id, _ in versions["en"]] == [
        claim_id for claim_id, _ in versions["es"]
    ]
    for (_, english), (_, spanish) in zip(versions["en"], versions["es"], strict=True):
        assert STATUS.search(english).group(1) == STATUS.search(spanish).group(1)
        code = re.compile(r"```[a-zA-Z0-9]*\n([\s\S]*?)\n```")
        assert code.findall(english) == code.findall(spanish)
