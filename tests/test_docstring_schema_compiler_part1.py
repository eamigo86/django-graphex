"""Focused contract for the first schema-compiler docstring cleanup."""

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
        "_NativeDjangoFieldView",
        "_build_object_field",
        "_build_scalar_field",
        "_collect_dropped_native_fields",
        "_collect_root_attrs",
        "_compile_plain_object_fields",
        "_compile_plain_object_type",
        "_get_unbound_function",
        "_guard_output_default",
        "_is_forked_pair",
        "_is_plain_object_type",
        "_is_subscription_field",
        "_label_model_field",
        "_maybe_refork_mutation_field",
        "_native_field_declared_django_type",
        "_rendered_field_name",
        "_resolver_for",
        "_stamp_required_perms",
    }
)


def test_first_schema_compiler_docstrings_are_backtick_free() -> None:
    """Require the selected schema compiler docstrings to use plain prose.

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
