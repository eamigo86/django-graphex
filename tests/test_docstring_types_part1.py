"""Focused contract for the first docstring cleanup slice in types.py."""

import ast
from pathlib import Path

TYPES_MODULE = Path(__file__).parents[1] / "django_graphex" / "types.py"
TARGET_FUNCTIONS = (
    "_yank_fields",
    "_compile_declared_list_fields",
    "_model_field_names",
    "_is_declared_class_attr",
    "_compile_declared_fields",
    "_compile_gfk_union_output_fields",
    "_compile_relation_list_fields",
    "_compile_reverse_o2o_fields",
    "_make_output_thunk_for",
    "_make_list_fields_thunk_for",
    "_check_unknown_options",
    "_schema_scoped_registry",
    "_resolve_polymorphic_type",
)


def test_first_types_docstring_slice_contains_no_backticks() -> None:
    """Require every assigned function docstring to contain no backticks.

    The explicit owner list keeps this contract independent from later cleanup
    slices in the same module.
    """
    tree = ast.parse(TYPES_MODULE.read_text(), filename=str(TYPES_MODULE))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for name in TARGET_FUNCTIONS:
        assert name in functions, f"missing assigned function: {name}"
        docstring = ast.get_docstring(functions[name], clean=False)
        assert docstring is not None, f"missing docstring: {name}"
        assert "`" not in docstring, f"backtick remains in docstring: {name}"
