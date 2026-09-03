"""Focused contract for the schema facade docstring cleanup."""

import ast
from pathlib import Path

SCHEMA_FACADE = Path(__file__).resolve().parents[1] / "django_graphex" / "schema.py"
TARGET_OWNERS = frozenset(
    {
        "DjangoGraphQLSchema.__str__",
        "DjangoGraphQLSchema._build_native_graphql_schema",
        "DjangoGraphQLSchema._build_native_graphql_schema._native_root",
        "DjangoGraphQLSchema._build_native_graphql_schema._root_name",
        "DjangoGraphQLSchema._compute_label_set",
        "DjangoGraphQLSchema._merge_root",
        "DjangoGraphQLSchema._native_types_for_forwarding",
        "_auth_middleware_configured",
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


def test_schema_facade_docstrings_are_backtick_free() -> None:
    """Require the selected schema facade docstrings to use plain prose.

    The exact owner set prevents unrelated docstrings from weakening this scope.
    """
    tree = ast.parse(SCHEMA_FACADE.read_text(encoding="utf-8"))
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
