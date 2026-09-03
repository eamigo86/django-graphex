"""Protect the first targeted utils docstring remediation slice."""

import ast
from pathlib import Path

UTILS_PATH = Path(__file__).parents[1] / "django_graphex" / "utils.py"
TARGET_FUNCTIONS = frozenset(
    {
        "_apply_field_hook",
        "_apply_plain_hook",
        "_collect_only_fields",
        "_collect_only_fields_is_full_load",
        "_compute_child_only",
        "_concrete_field_map",
        "_generic_foreign_key_type",
        "_generic_rel_type",
        "_generic_relation_type",
        "_get_field_optimize_hook",
        "_gfk_field_types",
        "_gql_source_class",
        "_inline_fragment_applies",
        "_inner_object_type",
        "_leaf_model",
        "_relation_field_map",
        "_resolve_fragment_target",
    }
)


def test_first_utils_docstring_slice_contains_no_backticks() -> None:
    """Require plain-text docstrings for the exact first utils slice.

    The named AST owners keep this cleanup boundary explicit.
    """
    tree = ast.parse(UTILS_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
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
