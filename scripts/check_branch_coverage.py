"""Enforce exact pure-branch coverage from a Cobertura XML report.

The combined pytest coverage gate is separate from this branch-only check.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

DEFAULT_THRESHOLD = Decimal("95.01")


def parse_threshold(raw: str) -> Decimal:
    """Validate a branch-percentage threshold without rounding it.

    Args:
        raw: Percentage supplied by the caller.

    Returns:
        Finite percentage between zero and one hundred, inclusive.

    Raises:
        argparse.ArgumentTypeError: The percentage is malformed or outside range.
    """
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("invalid threshold") from exc
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(100):
        raise argparse.ArgumentTypeError("invalid threshold")
    return value


def branch_counts(root: ET.Element) -> tuple[int, int]:
    """Read and validate the integer branch outcomes on the coverage root.

    Args:
        root: Parsed XML document root.

    Returns:
        Covered and valid branch counts.

    Raises:
        ValueError: The document is not a valid report with usable branch counts.
    """
    if root.tag != "coverage":
        raise ValueError("expected coverage root")
    counts: list[int] = []
    for name in ("branches-covered", "branches-valid"):
        raw = root.get(name)
        if raw is None or re.fullmatch(r"[0-9]+", raw) is None:
            raise ValueError(f"invalid {name} count")
        counts.append(int(raw))
    covered, valid = counts
    if valid == 0:
        raise ValueError("branches-valid total is zero")
    if covered > valid:
        raise ValueError("branches-covered exceeds branches-valid")
    return covered, valid


def main(argv: list[str] | None = None) -> int:
    """Check the exact branch fraction and report its own percentage.

    Args:
        argv: Command arguments, or process arguments when omitted.

    Returns:
        Zero when the threshold is met; one when it is not.

    Raises:
        SystemExit: The report or command arguments are invalid.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="fresh Cobertura coverage XML")
    parser.add_argument(
        "--threshold",
        type=parse_threshold,
        default=DEFAULT_THRESHOLD,
        help="minimum pure-branch percentage (default: 95.01)",
    )
    args = parser.parse_args(argv)
    try:
        root = ET.parse(args.report).getroot()
    except OSError as exc:
        parser.error(f"cannot read report: {exc}")
    except ET.ParseError as exc:
        parser.error(f"invalid XML report: {exc}")
    try:
        covered, valid = branch_counts(root)
    except ValueError as exc:
        parser.error(str(exc))
    percent = Decimal(covered) * 100 / Decimal(valid)
    threshold = Fraction(args.threshold)
    meets_threshold = (
        covered * 100 * threshold.denominator >= threshold.numerator * valid
    )
    outcome = "PASS" if meets_threshold else "FAIL"
    print(
        f"pure branches: {covered}/{valid} = {percent:.4f}% "
        f"(required >= {args.threshold}%) — {outcome}"
    )
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
