"""Focused contract for converter-adjacent test helper docstrings."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CONTRACTS = {
    "tests/test_converter.py": (
        37,
        "f5c70e9a4e8888bb61c605b7f873ccdd554d423c18353e089dd0eed7bc617164",
        "907c000bbe7f3b36c18db1b56a6058baedeff25c8d7908b800095c9d28a96580",
    ),
    "tests/test_converter_branches.py": (
        39,
        "1444870d03aa4a19a9413328a76ed2345dfeb9f292d43cca5003018bc2b3e63b",
        "a01b0fd068cd57596e1891d9459597e62d82726993a653c6f2260f8b3e1dd53a",
    ),
    "tests/test_converter_internals.py": (
        20,
        "9868677c9cb960b050ef429bdcd8f0bf04675b8440b1df0363c088267c9001aa",
        "cd3b184b8fa084c0853e835a4bd2bbfd2948fc044961d746ed0a39781c018b79",
    ),
    "tests/test_explicit_null_and_json_input.py": (
        45,
        "7d364c5da4001c412d11bdd33bc93b08752f7154b6d80aa3975830e9a231e690",
        "ae6b181d6c0e9ee6163c54c79ec56487193c86a3cc55f40f4c0d7e133921a60d",
    ),
    "tests/test_optimizer_phase_d.py": (
        86,
        "d06ec6b9d032b675c16eb08bb878105cb7202b5a84bea11f09f3301cca7bd404",
        "2c2f9476e0498c8dc7624b5eacccb7121468d5eddf43b8f9d95eef7c4af95c91",
    ),
    "tests/test_release_artifact_scripts.py": (
        10,
        "b20ee542699f9bb6fe7e2f7162e9d7e0312060d86e85edc5dc255dae4d096062",
        "8377edda872e1f37d5139d0f1de061512d2f392519add7a04b05a6f7d8775d6e",
    ),
    "tests/test_schema_pruner.py": (
        33,
        "31f98cbaeb64edda7dd0d3959b2b34d2149ebafe8374ad7b5bf026dc9818c97e",
        "347eb6d8ec9ba4e4339c657afa631bb22850ca2b8d655fd7240ab7c98a0209ea",
    ),
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

        def generic_visit(self, node: ast.AST) -> None:
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                super().generic_visit(node)
                return
            qualified_name = ".".join((*self.parents, node.name))
            if ast.get_docstring(node, clean=False) is not None:
                owners.add(qualified_name)
            self.parents.append(node.name)
            super().generic_visit(node)
            self.parents.pop()

    Visitor().visit(tree)
    return frozenset(owners)


def _owner_digest(owners: frozenset[str]) -> str:
    return hashlib.sha256("\n".join(sorted(owners)).encode()).hexdigest()


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

        def generic_visit(self, node: ast.AST) -> ast.AST:
            normalized = super().generic_visit(node)
            if isinstance(
                normalized,
                (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                normalized.body = self._without_docstring(normalized.body)
            return normalized

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


def test_converter_helper_docstrings_are_complete_and_ast_is_unchanged() -> None:
    """Require exact owners, strict contracts, and unchanged executable AST.

    Owner counts and digests make additions, removals, and renames fail closed. The
    executable digest excludes docstrings only, so annotations remain protected.
    """
    checker = _load_checker()
    violations: dict[str, list[tuple[int, str]]] = {}

    for relative_path, expected in EXPECTED_CONTRACTS.items():
        path = ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        owners = _docstring_owners(tree)
        expected_owner_count, expected_owner_digest, expected_ast_digest = expected
        assert len(owners) == expected_owner_count
        assert _owner_digest(owners) == expected_owner_digest
        assert _executable_digest(tree) == expected_ast_digest
        violations[relative_path] = [
            (violation.lineno, violation.code)
            for violation in checker.check_file(
                path,
                strict_public=True,
                strict_content=True,
            )
        ]

    assert violations == {relative_path: [] for relative_path in EXPECTED_CONTRACTS}
