"""Focused contract for runtime settings, permission cache, and fields."""

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "django_graphex" / "settings.py": (
        "1c30defa589640baa7096f8b04975f5bb0f589bca51392b1d1ee16de2085dc7f"
    ),
    ROOT / "django_graphex" / "core" / "permission_signature_cache.py": (
        "8e574fd53dae26d456ede7f4e966d52878533a2afbe209f55c816648dc0b22ce"
    ),
    ROOT / "django_graphex" / "core" / "fields.py": (
        "c5207e000213a3cc7bcb814ddd1ddf5e9290feedeebe4d89813a90ec8dbc8e57"
    ),
    ROOT / "django_graphex" / "fields.py": (
        "1c5feb944166412d59f74a8d105eb37621a720cbfe0773c2a1eb527acd7be72c"
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


def test_runtime_internal_docstrings_are_clean_and_runtime_neutral() -> None:
    """Require both strict contracts and an unchanged executable AST.

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
