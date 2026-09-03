"""Focused contract for benchmark harness docstrings."""

from pathlib import Path

from scripts.check_docstrings import check_file

BENCHMARKS_ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
OWNED_FILES = (
    BENCHMARKS_ROOT / "contract.py",
    BENCHMARKS_ROOT / "guard_cost.py",
    BENCHMARKS_ROOT / "harness.py",
    BENCHMARKS_ROOT / "run_publish.py",
    BENCHMARKS_ROOT / "verify_freeze.py",
)


def test_benchmark_harness_satisfies_strict_docstring_contract() -> None:
    """Require every owned module to satisfy both strict modes.

    The contract covers each module's public API and all docstring content.
    """
    violations = [
        (path, violation)
        for path in OWNED_FILES
        for violation in check_file(
            path,
            strict_public=True,
            strict_content=True,
        )
    ]

    details = "\n".join(
        f"{path}:{violation.lineno}: {violation.code} {violation.message}"
        for path, violation in violations
    )
    assert not violations, details
