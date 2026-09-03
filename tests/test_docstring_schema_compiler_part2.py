"""Focused contract for the remaining schema-compiler docstring cleanup."""

import ast
from pathlib import Path

SCHEMA_COMPILER = (
    Path(__file__).resolve().parents[1]
    / "django_graphex"
    / "core"
    / "schema_compiler.py"
)
TARGET_OWNERS = frozenset(
    {
        "_build_django_output_field",
        "_build_filter_list_field",
        "_build_list_object_field",
        "_build_plain_object_field",
        "_build_polymorphic_field",
        "_compile_wrapped_field_type",
        "_filter_arg",
        "_list_container_output_type",
        "_plain_django_output_type",
        "_polymorphic_field_type",
        "_unwrap_to_node_type",
    }
)


def test_remaining_schema_compiler_docstrings_are_backtick_free() -> None:
    """Require the remaining schema compiler docstrings to use plain prose.

    The exact owner set prevents later cleanup groups from weakening this scope.
    """
    tree = ast.parse(SCHEMA_COMPILER.read_text())
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
