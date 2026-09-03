"""Contract tests for the release-tool docstring cleanup.

The checks preserve the executable AST while documentation evolves.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FILES = tuple(SCRIPTS / name for name in ("check_base_install.py", "codemod_phase4.py"))
EXPECTED_OWNERS = {
    "check_base_install.py": frozenset({"<module>"}),
    "codemod_phase4.py": frozenset(
        {
            "<module>",
            "_is_mutation_base",
            "_collect_mutation_class_ranges",
            "_has_import",
            "_transform_import_line",
            "transform_source",
            "process_file",
            "process_path",
            "main",
        }
    ),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "check_base_install.py": (
        "79e8db3445596e65fc607a9cd8c4ff43fa5e6b82cb3dac10b7ff12b44896322a"
    ),
    "codemod_phase4.py": (
        "790afa25070ad97746438a3d3a09ee0d42a6a4858fcd5c3d78f11d63ef2d5e75"
    ),
}


def _load_checker() -> ModuleType:
    script = SCRIPTS / "check_docstrings.py"
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
    return hashlib.sha256(repr(canonical(normalized)).encode()).hexdigest()


def test_release_tool_docstrings_are_complete_and_executable_ast_is_unchanged() -> None:
    """Require exact owners, strict contracts, and unchanged executable AST.

    The digest excludes docstrings only, so annotations remain part of the contract.
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
