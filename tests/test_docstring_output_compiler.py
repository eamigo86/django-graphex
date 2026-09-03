"""Focused contract for the output compiler docstring cleanup."""

import ast
from pathlib import Path

OUTPUT_COMPILER = (
    Path(__file__).resolve().parents[1]
    / "django_graphex"
    / "core"
    / "output_compiler.py"
)
TARGET_OWNERS = frozenset(
    {
        "_compile_array_field",
        "_compile_choices_enum_field",
        "_compile_generic_foreign_key",
        "_compile_range_field",
        "_get_gfk_flat_type",
        "_get_range_composite_type",
        "_gfk_flat_resolver",
        "_inner_output_type",
        "_is_array_field",
        "_is_generic_foreign_key",
        "_is_many_relation",
        "_is_range_field",
        "_is_relation_field",
        "_to_graphql_field",
    }
)


def test_output_compiler_docstrings_are_backtick_free() -> None:
    """Require the selected output compiler docstrings to use plain prose.

    The exact owner set prevents later cleanup groups from weakening this scope.
    """
    tree = ast.parse(OUTPUT_COMPILER.read_text(encoding="utf-8"))
    owners = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in TARGET_OWNERS
    }

    assert owners.keys() == TARGET_OWNERS
    offenders = {
        name: node.lineno
        for name, node in owners.items()
        if "`" in (ast.get_docstring(node, clean=False) or "")
    }
    assert not offenders, f"backticks remain in selected docstrings: {offenders}"
