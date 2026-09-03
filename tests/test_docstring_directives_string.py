"""Focused contract for string-directive docstrings."""

from pathlib import Path

from scripts.check_docstrings import check_file

STRING_DIRECTIVES = (
    Path(__file__).resolve().parents[1] / "django_graphex" / "directives" / "string.py"
)


def test_string_directives_satisfy_strict_docstring_contract() -> None:
    """Require the complete string-directive module to satisfy both strict modes.

    The file-wide contract covers its public API and every docstring's content.
    """
    violations = check_file(
        STRING_DIRECTIVES,
        strict_public=True,
        strict_content=True,
    )

    details = "\n".join(
        f"{STRING_DIRECTIVES}:{item.lineno}: {item.code} {item.message}"
        for item in violations
    )
    assert not violations, details
