"""Executable contracts for the standalone pure-branch coverage gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_branch_coverage.py"


def _run_checker(report: Path, *options: str) -> subprocess.CompletedProcess[str]:
    """Run the actual command-line gate against one XML report.

    Args:
        report: XML report path supplied to the checker.
        options: Additional command-line options.

    Returns:
        Captured command result.
    """
    return subprocess.run(
        [sys.executable, str(CHECKER), str(report), *options],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_report(
    path: Path, *, covered: str, valid: str, rate: str = "0.9999"
) -> Path:
    """Write a minimal Cobertura root with intentionally untrusted rates.

    Args:
        path: Destination for the fixture XML.
        covered: Branches-covered attribute.
        valid: Branches-valid attribute.
        rate: Branch-rate attribute that must not control acceptance.

    Returns:
        Written report path.
    """
    path.write_text(
        '<coverage branches-covered="'
        + covered
        + '" branches-valid="'
        + valid
        + '" branch-rate="'
        + rate
        + '" />',
        encoding="utf-8",
    )
    return path


def test_exact_default_threshold_accepts_9501_of_10000(tmp_path: Path) -> None:
    """Accept the exact 95.01 percent boundary without rate rounding.

    Args:
        tmp_path: Owned fixture directory.
    """
    result = _run_checker(
        _write_report(tmp_path / "coverage.xml", covered="9501", valid="10000")
    )
    assert result.returncode == 0
    assert "9501/10000" in result.stdout
    assert "95.0100%" in result.stdout


def test_exact_default_threshold_rejects_9500_of_10000(tmp_path: Path) -> None:
    """Reject the adjacent fraction even when XML claims a high rate.

    Args:
        tmp_path: Owned fixture directory.
    """
    result = _run_checker(
        _write_report(tmp_path / "coverage.xml", covered="9500", valid="10000")
    )
    assert result.returncode == 1
    assert "9500/10000" in result.stdout
    assert "95.0000%" in result.stdout


def test_lying_rounded_rate_cannot_override_counts(tmp_path: Path) -> None:
    """Use root integer counts instead of its untrusted rate string.

    Args:
        tmp_path: Owned fixture directory.
    """
    path = _write_report(
        tmp_path / "coverage.xml", covered="9500", valid="10000", rate="1"
    )
    assert _run_checker(path).returncode == 1
    path = _write_report(path, covered="9501", valid="10000", rate="0")
    assert _run_checker(path).returncode == 0


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("", "invalid XML"),
        ("<coverage", "invalid XML"),
        ("<other branches-covered='1' branches-valid='1'/>", "coverage root"),
        ("<coverage branches-valid='1'/>", "branches-covered"),
        ("<coverage branches-covered='1'/>", "branches-valid"),
        ("<coverage branches-covered='1.0' branches-valid='2'/>", "branches-covered"),
        ("<coverage branches-covered='-1' branches-valid='2'/>", "branches-covered"),
        ("<coverage branches-covered='3' branches-valid='2'/>", "exceeds"),
        ("<coverage branches-covered='0' branches-valid='0'/>", "zero"),
        ("<coverage branches-covered='true' branches-valid='2'/>", "branches-covered"),
    ],
)
def test_invalid_reports_fail_closed(
    tmp_path: Path, content: str, expected: str
) -> None:
    """Reject absent, malformed and dishonest count metadata.

    Args:
        tmp_path: Owned fixture directory.
        content: XML body for one invalid report.
        expected: Diagnostic substring.
    """
    path = tmp_path / "coverage.xml"
    path.write_text(content, encoding="utf-8")
    result = _run_checker(path)
    assert result.returncode != 0
    assert expected in result.stderr


def test_missing_report_fails_closed(tmp_path: Path) -> None:
    """Reject an absent report without replacing it or assuming zero.

    Args:
        tmp_path: Owned fixture directory.
    """
    result = _run_checker(tmp_path / "missing.xml")
    assert result.returncode != 0
    assert "cannot read" in result.stderr


@pytest.mark.parametrize("threshold", ["NaN", "Infinity", "-1", "100.01", "abc", ""])
def test_invalid_threshold_fails_closed(tmp_path: Path, threshold: str) -> None:
    """Reject non-finite, out-of-range or malformed thresholds.

    Args:
        tmp_path: Owned fixture directory.
        threshold: Invalid percent passed through the real CLI.
    """
    path = _write_report(tmp_path / "coverage.xml", covered="1", valid="1")
    result = _run_checker(path, "--threshold", threshold)
    assert result.returncode != 0
    assert "threshold" in result.stderr.lower()


def test_explicit_valid_threshold_uses_exact_fraction(tmp_path: Path) -> None:
    """Allow a valid override without falling back to XML rate metadata.

    Args:
        tmp_path: Owned fixture directory.
    """
    path = _write_report(tmp_path / "coverage.xml", covered="1", valid="2")
    assert _run_checker(path, "--threshold", "50").returncode == 0
    assert _run_checker(path, "--threshold", "50.01").returncode == 1


def test_threshold_above_exact_boundary_cannot_round_down(tmp_path: Path) -> None:
    """Reject a threshold strictly above the covered fraction.

    Args:
        tmp_path: Owned fixture directory.
    """
    path = _write_report(tmp_path / "coverage.xml", covered="9501", valid="10000")
    result = _run_checker(path, "--threshold", "95.0100000000000000000000000001")
    assert result.returncode == 1
    assert "FAIL" in result.stdout
