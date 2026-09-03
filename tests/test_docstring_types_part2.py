"""Focused contract for the second docstring cleanup slice in types.py."""

import ast
from pathlib import Path

TYPES_MODULE = Path(__file__).parents[1] / "django_graphex" / "types.py"
TARGET_OWNERS = (
    "_nested_input_perms",
    "_resolve_native_nested_input_fields",
    "_resolve_native_relation_input_fields",
    "_resolve_native_choices_input_fields",
    "DjangoInputObjectType.__init_subclass__",
    "DjangoModelType._build_native_mutation_field",
    "DjangoModelType._with_deprecation",
)


def test_second_types_docstring_slice_contains_no_backticks() -> None:
    """Require every assigned owner docstring to contain no backticks.

    The explicit owner list keeps this contract independent from other cleanup
    slices in the same module.
    """
    tree = ast.parse(TYPES_MODULE.read_text(), filename=str(TYPES_MODULE))
    owners: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owners[node.name] = node
        elif isinstance(node, ast.ClassDef):
            owners.update(
                {
                    f"{node.name}.{member.name}": member
                    for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            )

    for owner in TARGET_OWNERS:
        assert owner in owners, f"missing assigned owner: {owner}"
        docstring = ast.get_docstring(owners[owner], clean=False)
        assert docstring is not None, f"missing docstring: {owner}"
        assert "`" not in docstring, f"backtick remains in docstring: {owner}"
