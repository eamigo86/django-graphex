"""Keep date-part behavior tests independent of audit-runtime identity."""

from __future__ import annotations

import ast
from pathlib import Path


def test_datepart_behavior_does_not_assert_local_runtime_identity() -> None:
    """Keep supported GraphQL-core patch releases usable in date-part tests.

    The date-part suite must assert HTTP and filtering behavior instead of
    requiring an exact local overlay, checkout, working directory, or patch.
    """
    source = (Path(__file__).parent / "test_datepart_filtering.py").read_text(
        encoding="utf-8"
    )
    syntax = ast.parse(source)
    behavior_test = next(
        node
        for node in syntax.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_numeric_date_parts_have_int_sdl_and_work_over_http"
    )
    assert not any(
        isinstance(node, ast.Attribute)
        and node.attr in {"__version__", "__file__", "cwd"}
        for node in ast.walk(behavior_test)
    )
    assert not any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in {"graphql-core", "core330-overlay"}
        for node in ast.walk(behavior_test)
    )
