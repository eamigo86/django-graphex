"""Keep generated-mutation security tests independent of local audit paths."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "source_name",
    (
        "test_generated_integrity_error_redaction.py",
        "test_generated_delete_security.py",
    ),
)
def test_generated_security_suites_do_not_require_a_local_graphql_checkout(
    source_name: str,
) -> None:
    """Keep security assertions portable across supported GraphQL installs.

    Args:
        source_name: Generated-mutation security test module to inspect.
    """
    source = (Path(__file__).parent / source_name).read_text(encoding="utf-8")
    syntax = ast.parse(source)
    function_names = {
        node.name for node in syntax.body if isinstance(node, ast.FunctionDef)
    }
    assert "_assert_runtime_identity" not in function_names
    assert not any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and ("core330-overlay" in node.value or ".codex/visualizations" in node.value)
        for node in ast.walk(syntax)
    )


def test_contributor_testing_guidance_keeps_local_runtime_guards_external() -> None:
    """Document that supported-runtime proof must not bind shipped tests.

    The contributor guide states the portable-test rule.
    """
    guide = (Path(__file__).resolve().parents[1] / "docs/contributing.md").read_text(
        encoding="utf-8"
    )
    testing = guide.split("### Testing Standards\n", 1)[1].split("\n### ", 1)[0]
    assert "Runtime identity guards" in testing
    assert "external verification runners" in testing
    assert "shipped tests" in testing
