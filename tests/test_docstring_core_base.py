"""Focused contract for the core base docstring cleanup."""

import ast
from pathlib import Path

CORE_BASE = Path(__file__).resolve().parents[1] / "django_graphex" / "core" / "base.py"
TARGET_OWNERS = frozenset(
    {
        "InputType.__init_subclass__",
        "ObjectType.__init_subclass__",
        "ObjectType.__init_subclass_with_meta__",
        "_GdxGetItemMixin",
        "_GdxInputMeta",
        "_GdxInputOptions",
        "_GdxOutputEntry",
        "_collect_descriptor_fields",
        "_django_model_field_type",
        "_forking_build",
        "_guard_django_model_field_on_body",
        "_ignored_types_with_django_field",
        "_mount_descriptor_fields",
        "_props",
        "_trim_docstring",
    }
)


class _DocstringOwnerVisitor(ast.NodeVisitor):
    """Collect class and callable owners by qualified name."""

    def __init__(self) -> None:
        self.owners: dict[str, ast.AST] = {}
        self._parents: list[str] = []

    def _visit_owner(self, node: ast.ClassDef | ast.FunctionDef) -> None:
        qualified_name = ".".join((*self._parents, node.name))
        self.owners[qualified_name] = node
        self._parents.append(node.name)
        self.generic_visit(node)
        self._parents.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_owner(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_owner(node)


def test_core_base_docstrings_are_backtick_free() -> None:
    """Require the selected core base docstrings to use plain prose.

    The exact owner set prevents later cleanup groups from weakening this scope.
    """
    tree = ast.parse(CORE_BASE.read_text())
    visitor = _DocstringOwnerVisitor()
    visitor.visit(tree)
    owners = {
        name: node for name, node in visitor.owners.items() if name in TARGET_OWNERS
    }

    assert owners.keys() == TARGET_OWNERS
    offenders = {
        name: node.lineno
        for name, node in owners.items()
        if "`" in (ast.get_docstring(node, clean=False) or "")
    }
    assert not offenders, f"backticks remain in selected docstrings: {offenders}"
