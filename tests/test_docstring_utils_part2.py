"""Protect the remaining utils docstring remediation slice."""

import ast
from pathlib import Path

UTILS_PATH = Path(__file__).parents[1] / "django_graphex" / "utils.py"
TARGET_FUNCTIONS = frozenset(
    {
        "_apply_optimizations",
        "_build_generic_prefetch",
        "_build_member_queryset",
        "_collect_annotated_fields",
        "_collect_gfk_union_buckets",
        "_collect_prefetch_only_sets",
        "_content_type_or_none",
        "_detect_promotions",
        "_merge_filtered_prefetches",
        "_narrow_plain_prefetch",
        "_resolve_results_paginator",
        "_walk_annotated_fields",
        "_walk_filtered_prefetches",
        "_walk_window_params",
    }
)


def test_remaining_utils_docstring_slice_contains_no_backticks() -> None:
    """Require plain-text docstrings for the exact remaining utils slice.

    The named AST owners keep this cleanup boundary explicit.
    """
    tree = ast.parse(UTILS_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    missing = TARGET_FUNCTIONS - functions.keys()
    assert not missing, f"Missing targeted functions: {sorted(missing)}"

    docstrings = {
        name: ast.get_docstring(functions[name], clean=False)
        for name in TARGET_FUNCTIONS
    }
    undocumented = sorted(
        name for name, docstring in docstrings.items() if docstring is None
    )
    assert not undocumented, f"Missing targeted docstrings: {undocumented}"

    offenders = sorted(
        name for name, docstring in docstrings.items() if "`" in (docstring or "")
    )
    assert not offenders, f"Backticks remain in targeted docstrings: {offenders}"
