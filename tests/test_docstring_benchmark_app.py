"""Focused contract for benchmark application docstrings."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "benchmarks"
FILES = tuple(
    BENCHMARKS / relative
    for relative in (
        "benchapp/apps.py",
        "benchapp/models.py",
        "benchapp/management/commands/seed_bench.py",
        "config/settings.py",
        "config/urls.py",
    )
)
EXPECTED_OWNERS = {
    "benchapp/apps.py": frozenset({"<module>", "BenchappConfig"}),
    "benchapp/models.py": frozenset(
        {
            "<module>",
            "Author",
            "Category",
            "Category.Meta",
            "Comment",
            "Post",
            "Post.Status",
            "Tag",
        }
    ),
    "benchapp/management/commands/seed_bench.py": frozenset(
        {"<module>", "Command", "Command.add_arguments", "Command.handle"}
    ),
    "config/settings.py": frozenset({"<module>"}),
    "config/urls.py": frozenset({"<module>"}),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "benchapp/apps.py": "50e30a58f13f19574cf5f5d9176242e2d2465b77375feb3533bae857a24ca977",
    "benchapp/models.py": "2ab394a375e7bdad228e9a9d1ff6b6662667ba1e2ebef00208b03d6d2a3c5284",
    "benchapp/management/commands/seed_bench.py": "8abdd57a71434cc995278a6af6f2e86f68de6da9d2bfd7f646cfe6e35fe7ff66",
    "config/settings.py": "a695eb89984eef95d27443e21e164219ee2bdca8cb6c0fdd51930ba2de7d8f3f",
    "config/urls.py": "1a561ad5486a0cdc673535ae9c5c4113ac1b359527a1dd6935f78268d62fc81e",
}


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


def test_benchmark_app_docstrings_are_complete_and_runtime_neutral() -> None:
    """Require exact owners, strict contracts, and unchanged executable AST.

    Normalization ignores docstrings and mandatory callable annotations only.
    """
    violations: dict[str, list[tuple[int, str]]] = {}

    for path in FILES:
        relative = path.relative_to(BENCHMARKS).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _docstring_owners(tree) == EXPECTED_OWNERS[relative]
        assert _executable_digest(tree) == EXPECTED_EXECUTABLE_DIGESTS[relative]
        violations[relative] = [
            (violation.lineno, violation.code)
            for violation in check_file(
                path,
                strict_public=True,
                strict_content=True,
            )
        ]

    assert violations == {path.relative_to(BENCHMARKS).as_posix(): [] for path in FILES}
