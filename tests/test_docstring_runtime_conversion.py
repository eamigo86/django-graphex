"""Focused contract for runtime conversion docstrings."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "django_graphex"
FILES = tuple(
    RUNTIME / name
    for name in (
        "__init__.py",
        "converter.py",
        "core/_args.py",
        "core/_compat.py",
        "core/backend.py",
        "core/bridge.py",
        "core/compat.py",
        "core/compiler.py",
        "core/factory.py",
    )
)
EXPECTED_DOCUMENTED_OWNERS = {
    "__init__.py": frozenset({"_version_from_pyproject"}),
    "converter.py": frozenset(
        {
            "_DeadScalarSentinel",
            "_is_valid_name",
            "_ensure_contenttypes_converters_registered",
        }
    ),
    "core/_args.py": frozenset(
        {
            "_unwrap_graphql_type",
            "_guard_django_model_field",
        }
    ),
    "core/_compat.py": frozenset({"_adapt_self"}),
    "core/backend.py": frozenset(
        {
            "_errors_to_type",
            "PydanticBackend._output_fields",
        }
    ),
    "core/bridge.py": frozenset(
        {
            "_MetaView",
            "GdxPayload._meta",
            "GdxPayload.__repr__",
        }
    ),
    "core/compat.py": frozenset(
        {
            "_gdx_meta",
            "_gdx_graphene_type",
        }
    ),
    "core/compiler.py": frozenset(
        {
            "_resolve_ref",
            "_make_field_thunk",
        }
    ),
    "core/factory.py": frozenset(
        {
            "_make_output_type",
            "_make_list_type",
        }
    ),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "__init__.py": "1af31857302199baba853f093abf4e7f633b089683f2fec92d397aba62390641",
    "converter.py": "81fd60630762647de9bdd39c0218a306bcfb1f8474fba43557334d8ba15c921f",
    "core/_args.py": "942ccbed5c9e1870fb5c681f4dc052230dce696c78fa32692c7d03ee7a7ebc8e",
    "core/_compat.py": "5a8decefdb8d1e517328a90c7420122b94c36a8fb188756b8a0282f985d50833",
    "core/backend.py": "c0d5629ee43e93ef4a38d779617444379cca7bce5b8d3867da8fa35ba8abf262",
    "core/bridge.py": "b784e2b193bd7bd82fff6092ac2192e0293555e0864afc31f507b013c411170a",
    "core/compat.py": "39590e1e2aec286248fab408852b2b15484103618174381bc8bc2a738b50248f",
    "core/compiler.py": "6c46d40a8109a99a3a78e25ac0e61dbaf7a7ccc32624a73f9ddcd826bc00ccb5",
    "core/factory.py": "fafe35a1d1dffc03620646baeb4f37c07a26cbdfffc3a1ac9abf2119bc0965c6",
}


def _relative_name(path: Path) -> str:
    return path.relative_to(RUNTIME).as_posix()


def _docstring_owners(tree: ast.Module) -> frozenset[str]:
    owners = {"<module>"} if ast.get_docstring(tree, clean=False) is not None else set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.parents: list[str] = []

        def _visit_owner(
            self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ) -> None:
            if ast.get_docstring(node, clean=False) is not None:
                owners.add(".".join((*self.parents, node.name)))
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


def test_runtime_conversion_docstrings_are_clean_and_runtime_neutral() -> None:
    """Require strict content, retained owners, and unchanged executable AST.

    The executable digest excludes docstrings only.
    """
    violations: dict[str, list[tuple[int, str]]] = {}

    for path in FILES:
        name = _relative_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert EXPECTED_DOCUMENTED_OWNERS[name] <= _docstring_owners(tree)
        assert _executable_digest(tree) == EXPECTED_EXECUTABLE_DIGESTS[name]
        violations[name] = [
            (violation.lineno, violation.code)
            for violation in check_file(
                path,
                strict_public=True,
                strict_content=True,
            )
        ]

    assert violations == {name: [] for name in EXPECTED_DOCUMENTED_OWNERS}
