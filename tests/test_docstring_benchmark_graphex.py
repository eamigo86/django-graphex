"""Focused contract for django-graphex benchmark docstrings."""

from pathlib import Path

from scripts.check_docstrings import check_file

BENCHMARK_SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "libs"
    / "graphex"
    / "bench_schema.py"
)


def test_graphex_benchmark_satisfies_strict_docstring_contract() -> None:
    """Require the complete benchmark module to satisfy both strict modes.

    The file-wide contract covers its public API and every docstring's content.
    """
    violations = check_file(
        BENCHMARK_SCHEMA,
        strict_public=True,
        strict_content=True,
    )

    details = "\n".join(
        f"{BENCHMARK_SCHEMA}:{item.lineno}: {item.code} {item.message}"
        for item in violations
    )
    assert not violations, details
