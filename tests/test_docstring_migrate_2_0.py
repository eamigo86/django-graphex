"""Contract tests for the migration codemod docstring cleanup.

The checks keep the executable migration behavior unchanged as documentation
evolves.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "migrate_2_0.py"
EXPECTED_OWNERS = frozenset(
    {
        "<module>",
        "Finding",
        "RunResult",
        "_base_is_graphene",
        "_dict_entries",
        "_dict_value",
        "_flag_mutation_args",
        "_fold_settings_namespace",
        "_is_graphene_attr",
        "_module_assignment",
        "_module_imports_graphene",
        "_native_imported_names",
        "_rename_only",
        "_repoint_middleware_paths",
        "analyze_source",
        "format_report",
        "main",
        "rewrite_source",
        "run",
    }
)
EXPECTED_EXECUTABLE_DIGEST = (
    "f43052306314be19c96b9b016bdc0586cefc4fac731a17189b9a19018ae05964"
)


def _docstring_owners(tree: ast.Module) -> frozenset[str]:
    owners = {"<module>"} if ast.get_docstring(tree, clean=False) is not None else set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: list[str] = []

        def _visit_owner(
            self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ) -> None:
            qualified_name = ".".join((*self.parents, node.name))
            if ast.get_docstring(node, clean=False) is not None:
                owners.add(qualified_name)
            self.parents.append(node.name)
            self.generic_visit(node)
            self.parents.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._visit_owner(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_owner(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_owner(node)

    Visitor().visit(tree)
    return frozenset(owners)


def _executable_digest(tree: ast.Module) -> str:
    class Normalizer(ast.NodeTransformer):
        @staticmethod
        def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                return body[1:]
            return body

        def visit_Module(self, node: ast.Module) -> ast.Module:
            self.generic_visit(node)
            node.body = self._without_docstring(node.body)
            return node

        def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
            self.generic_visit(node)
            node.body = self._without_docstring(node.body)
            return node

        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
            self.generic_visit(node)
            node.body = self._without_docstring(node.body)
            return node

        def visit_AsyncFunctionDef(
            self, node: ast.AsyncFunctionDef
        ) -> ast.AsyncFunctionDef:
            self.generic_visit(node)
            node.body = self._without_docstring(node.body)
            return node

    def canonical(value: object) -> object:
        if isinstance(value, ast.AST):
            return (
                type(value).__name__,
                tuple((name, canonical(item)) for name, item in ast.iter_fields(value)),
            )
        if isinstance(value, list):
            return tuple(canonical(item) for item in value)
        return value

    normalized = Normalizer().visit(tree)
    payload = repr(canonical(normalized))
    return hashlib.sha256(payload.encode()).hexdigest()


def test_migration_codemod_docstrings_are_complete_and_runtime_neutral() -> None:
    """Require exact owners, strict content, and unchanged executable AST.

    The executable digest ignores docstrings only.
    """
    tree = ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))
    assert _docstring_owners(tree) == EXPECTED_OWNERS
    assert _executable_digest(tree) == EXPECTED_EXECUTABLE_DIGEST

    violations = check_file(
        TARGET,
        strict_public=True,
        strict_content=True,
    )
    details = "\n".join(
        f"{TARGET}:{item.lineno}: {item.code} {item.message}" for item in violations
    )
    assert not violations, details
