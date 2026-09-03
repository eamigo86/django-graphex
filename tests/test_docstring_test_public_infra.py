"""Focused docstring contract for public infrastructure tests.

The digest preserves every non-docstring AST field.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "tests" / "test_gate_coverage_isolation.py": (
        "ba888a18f757a978e77b151f4b41e4ee9c2a38889a3b31851c0f976f1e70c689"
    ),
    ROOT / "tests" / "test_middleware.py": (
        "c810d7f1ba8e4561f792efe3371bb62e97b309790aba7837221f2e25342bbe33"
    ),
    ROOT / "tests" / "test_migration_2_0_codemod.py": (
        "453b2be2444f8274d571d1cd6b645cbf196ee39f04332366d42790b2bd1b0b98"
    ),
}


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


def test_public_infrastructure_docstrings_are_clean_and_ast_neutral() -> None:
    """Require strict contracts and an unchanged non-docstring AST.

    The digest ignores docstrings only.
    """
    violations: dict[str, list[tuple[int, str]]] = {}

    for path, expected_digest in FILES.items():
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _executable_digest(tree) == expected_digest
        violations[relative] = [
            (violation.lineno, violation.code)
            for violation in check_file(
                path,
                strict_public=True,
                strict_content=True,
            )
        ]

    assert violations == {path.relative_to(ROOT).as_posix(): [] for path in FILES}
