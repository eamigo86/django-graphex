"""Focused contract for the core directive docstring cleanup."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
DIRECTIVES = ROOT / "django_graphex" / "directives"
FILES = tuple(DIRECTIVES / name for name in ("date.py", "list.py", "numbers.py"))
EXPECTED_OWNERS = {
    "date.py": frozenset(
        {
            "<module>",
            "DateGraphQLDirective",
            "DateGraphQLDirective.get_args",
            "DateGraphQLDirective.resolve",
            "_combine_date_time",
            "_format_dt",
            "_format_relativedelta",
            "_format_time_ago",
            "_parse",
            "str_in_dict_keys",
        }
    ),
    "list.py": frozenset(
        {
            "<module>",
            "SampleGraphQLDirective",
            "SampleGraphQLDirective.get_args",
            "SampleGraphQLDirective.resolve",
            "ShuffleGraphQLDirective",
            "ShuffleGraphQLDirective.resolve",
            "UniqueGraphQLDirective",
            "UniqueGraphQLDirective.resolve",
        }
    ),
    "numbers.py": frozenset(
        {
            "<module>",
            "AbsGraphQLDirective",
            "AbsGraphQLDirective.resolve",
            "CeilGraphQLDirective",
            "CeilGraphQLDirective.resolve",
            "FloorGraphQLDirective",
            "FloorGraphQLDirective.resolve",
            "RoundGraphQLDirective",
            "RoundGraphQLDirective.get_args",
            "RoundGraphQLDirective.resolve",
            "_coerce",
            "_to_float",
            "_wants_string",
        }
    ),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "date.py": "d357a8f90d3f7ab6b49e62a21dd6df6d0430b34d31ef210735a7bd5bd92b33c9",
    "list.py": "745e28cdfb079355435233e22eab8ae69c0f799189f0b65e9ad9e822963b4e4b",
    "numbers.py": "1e9c3a697763b4814d254841d4a50e7df847b7e0806aea3e249b1a745bb6e744",
}


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


def test_core_directive_docstrings_are_complete_and_runtime_neutral() -> None:
    """Require exact owners, full contracts, and unchanged executable AST.

    Normalization ignores docstrings and mandatory annotations only.
    """
    checker = _load_checker()
    violations: dict[str, list[tuple[int, str]]] = {}

    for path in FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _docstring_owners(tree) == EXPECTED_OWNERS[path.name]
        assert _executable_digest(tree) == EXPECTED_EXECUTABLE_DIGESTS[path.name]
        violations[path.name] = [
            (violation.lineno, violation.code)
            for violation in checker.check_file(
                path,
                strict_public=True,
                strict_content=True,
            )
        ]

    assert violations == {path.name: [] for path in FILES}
