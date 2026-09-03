"""Focused docstring contract for public filter tests."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "tests" / "test_directives.py": (
        "31273b02f1e11146ece844c45a5904dd3db1db4f6a7611e7e2dafc16d3445991"
    ),
    ROOT / "tests" / "test_filter_field.py": (
        "672a58209ad09beebb0e528786fa46bb57ec898496780bebcaf2eedcc4ca6100"
    ),
    ROOT / "tests" / "test_nested_list_filter_and_count.py": (
        "2f19857e2050938865fd46b37db6981a9ab00965ab7cc09ba7aa03ab74175c98"
    ),
    ROOT / "tests" / "test_v130_cover_gaps.py": (
        "7696b0616cb00c32e40b01f8e3cb7069fd3094b451aecb5bb5c9a969700d60ae"
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


def test_public_filter_test_docstrings_are_clean_and_runtime_neutral() -> None:
    """Require strict contracts and an unchanged executable AST.

    Normalization ignores docstrings and mandatory callable annotations only.
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
