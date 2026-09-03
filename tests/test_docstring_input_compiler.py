"""Focused contract for the input-compiler docstring cleanup."""

import ast
from pathlib import Path

INPUT_COMPILER = (
    Path(__file__).resolve().parents[1]
    / "django_graphex"
    / "core"
    / "input_compiler.py"
)
TARGET_OWNERS = frozenset(
    {
        "_default_value_for",
        "_python_type_to_gql",
        "_resolve_child_input_type",
        "_resolve_input_model_type",
        "_unwrap_list",
        "_unwrap_optional",
    }
)


def test_input_compiler_docstrings_are_backtick_free() -> None:
    """Require every assigned input-compiler docstring to use plain prose.

    The exact owner set prevents later cleanup groups from weakening this scope.
    """
    tree = ast.parse(
        INPUT_COMPILER.read_text(encoding="utf-8"), filename=str(INPUT_COMPILER)
    )
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
