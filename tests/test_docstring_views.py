"""Focused contract for the views docstring cleanup."""

import ast
from pathlib import Path

VIEWS = Path(__file__).resolve().parents[1] / "django_graphex" / "views.py"
TARGET_OWNERS = frozenset(
    {
        "AuthenticatedGraphQLView._cache_key_signature",
        "AuthenticatedGraphQLView._forbidden_response",
        "AuthenticatedGraphQLView._graphql_schema_for",
        "AuthenticatedGraphQLView._passes_access_group",
        "BaseGraphQLView._cache_key_signature",
        "BaseGraphQLView._graphql_schema_for",
        "GraphQLView._bump_cache_version",
        "GraphQLView._cache_version_identity",
        "GraphQLView._cache_version_namespace",
        "GraphQLView._execute_uncached_and_invalidate",
        "GraphQLView._get_cache_version",
        "_document_cache_maxsize",
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


def test_views_docstrings_are_backtick_free() -> None:
    """Require the selected views docstrings to use plain prose.

    The exact owner set prevents unrelated docstrings from weakening this scope.
    """
    tree = ast.parse(VIEWS.read_text(encoding="utf-8"))
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
