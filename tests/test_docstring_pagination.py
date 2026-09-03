"""Focused contract for the pagination docstring cleanup."""

import ast
from pathlib import Path

PAGINATION = (
    Path(__file__).resolve().parents[1]
    / "django_graphex"
    / "paginations"
    / "pagination.py"
)
TARGET_OWNERS = frozenset(
    {
        "BaseDjangoGraphqlPagination._resolve_page_size",
        "CursorGraphqlPagination._encode_row_cursor",
        "CursorGraphqlPagination._inmemory_after_cursor",
        "CursorGraphqlPagination._inmemory_cursor_start",
        "CursorGraphqlPagination._inmemory_keyset_order",
        "CursorGraphqlPagination._keyset_predicate",
        "CursorGraphqlPagination._legacy_value_predicate",
        "CursorGraphqlPagination._order_terms",
        "_apply_ordering",
        "_coerce_like",
        "_normalize_ordering",
        "_normalize_ordering_term",
        "_split_ordering",
        "_validate_ordering_terms",
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


def test_pagination_docstrings_are_backtick_free() -> None:
    """Require the selected pagination docstrings to use plain prose.

    The exact owner set prevents unrelated docstrings from weakening this scope.
    """
    tree = ast.parse(PAGINATION.read_text())
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
