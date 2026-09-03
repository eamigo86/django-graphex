"""Focused contract for the schema pruner docstring cleanup."""

import ast
from pathlib import Path

SCHEMA_PRUNER = (
    Path(__file__).resolve().parents[1] / "django_graphex" / "core" / "schema_pruner.py"
)
TARGET_OWNERS = frozenset(
    {
        "_Pruner._clone_input",
        "_Pruner._clone_root",
        "_Pruner._field_permitted",
        "_Pruner._filter_key_survives",
        "_Pruner._forwarded_implementer_clones",
        "_Pruner._implicit_perms",
        "_Pruner._input_field_permitted",
        "_Pruner._output_survives",
        "_Pruner._rebuild_arg",
        "_Pruner._rebuild_field",
        "_Pruner._serving_clones",
        "_Pruner._surviving_actions",
        "_Pruner.run",
    }
)


class _DocstringOwnerVisitor(ast.NodeVisitor):
    """Collect class and callable owners by qualified name."""

    def __init__(self) -> None:
        self.owners: dict[str, ast.AST] = {}
        self._parents: list[str] = []

    def _visit_owner(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        qualified_name = ".".join((*self._parents, node.name))
        self.owners[qualified_name] = node
        self._parents.append(node.name)
        self.generic_visit(node)
        self._parents.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_owner(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_owner(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_owner(node)


def test_schema_pruner_docstrings_are_backtick_free() -> None:
    """Require the selected schema pruner docstrings to use plain prose.

    The exact owner set prevents unrelated docstrings from weakening this scope.
    """
    tree = ast.parse(SCHEMA_PRUNER.read_text())
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
