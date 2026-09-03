"""Contract tests for the graphene benchmark docstring cleanup.

The checks keep the benchmark executable unchanged while documentation evolves.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "benchmarks" / "libs" / "graphene" / "bench_schema.py"
EXPECTED_OWNERS = frozenset(
    {
        "<module>",
        "AuthorType",
        "AuthorType.Meta",
        "CommentType",
        "CommentType.Meta",
        "CreateComment",
        "CreateComment.Arguments",
        "CreateComment.mutate",
        "Mutation",
        "PostType",
        "PostType.Meta",
        "Query",
        "Query.resolve_post",
    }
)
EXPECTED_EXECUTABLE_DIGEST = (
    "246c116a2baf7847fa58445c43796944c87cf8d3227e32d5a87e836cfec9204f"
)


def _load_checker() -> ModuleType:
    script = ROOT / "scripts" / "check_docstrings.py"
    spec = importlib.util.spec_from_file_location("check_docstrings", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            node.returns = None
            node.type_comment = None
            return node

        def visit_AsyncFunctionDef(
            self, node: ast.AsyncFunctionDef
        ) -> ast.AsyncFunctionDef:
            self.generic_visit(node)
            node.body = self._without_docstring(node.body)
            node.returns = None
            node.type_comment = None
            return node

        def visit_arg(self, node: ast.arg) -> ast.arg:
            self.generic_visit(node)
            node.annotation = None
            node.type_comment = None
            return node

        def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AnnAssign:
            self.generic_visit(node)
            node.annotation = None
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


def test_graphene_benchmark_docstrings_are_complete_and_runtime_neutral() -> None:
    """Require exact owners, strict content, and unchanged executable AST.

    Normalization ignores docstrings and mandatory annotations only.
    """
    tree = ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))
    assert _docstring_owners(tree) == EXPECTED_OWNERS
    assert _executable_digest(tree) == EXPECTED_EXECUTABLE_DIGEST

    checker = _load_checker()
    violations = [
        (violation.lineno, violation.code)
        for violation in checker.check_file(
            TARGET,
            strict_public=True,
            strict_content=True,
        )
    ]
    assert violations == []
