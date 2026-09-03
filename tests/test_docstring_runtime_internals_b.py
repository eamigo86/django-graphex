"""Focused contract for the second runtime-internals docstring cleanup."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _owners(names: str) -> frozenset[str]:
    return frozenset(names.split())


EXPECTED_OWNERS = {
    "django_graphex/core/mutation.py": _owners(
        "<module> Mutation Mutation.Arguments Mutation.Field Mutation.Meta "
        "Mutation._resolve_mutate _compile_args"
    ),
    "django_graphex/core/perm_labels.py": _owners(
        "<module> _codename _interface_perms implicit_label_set "
        "implicit_perms_for_type input_label_set required_perms_for"
    ),
    "django_graphex/core/polymorphic_compiler.py": _owners(
        "<module> _make_resolve_type _member_output_type _resolve_registries "
        "compile_interface_type compile_polymorphic_type compile_union_type "
        "is_interface_type is_union_type"
    ),
    "django_graphex/core/registry_compiler.py": _owners(
        "<module> BuildError NativeOutputRegistry NativeOutputRegistry.__init__ "
        "NativeOutputRegistry.get_compiled NativeOutputRegistry.iter_entries "
        "NativeOutputRegistry.register NativeOutputRegistry.set_compiled "
        "_compile_one _compile_one._make_fields_thunk _fork_output_class "
        "_forked_interfaces_thunk _reset_in_progress assert_schema_pair_isolation "
        "compile_all compile_all_outputs compile_all_outputs._class_instance "
        "compile_outputs_into fork_output_class"
    ),
    "django_graphex/core/validators.py": _owners(
        "<module> _collect _field_wrapper _object_wrapper _unwrap build_validator_model"
    ),
    "django_graphex/paginations/utils.py": _owners(
        "<module> NativePaginationField NativePaginationField.__post_init__ "
        "NativePaginationField.list_resolver NativePaginationField.wrap_resolve "
        "_get_count _paginate_list_base _positive_int"
    ),
    "django_graphex/uploads.py": _owners(
        "<module> Base64FileInput Base64FileInput.to_uploaded_file "
        "_accepted_part_names _effective_max_size _estimate_decoded_size "
        "decode_base64_file merge_uploaded_files"
    ),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "django_graphex/core/mutation.py": (
        "32af8b1df09e8a04420ae53748839bf2a84a49381f9c5f775c64ff55e85c78b9"
    ),
    "django_graphex/core/perm_labels.py": (
        "005c353fcfd1ffc0cb55955780f2934cd966c54a52dc99ce718b3d3c6802d334"
    ),
    "django_graphex/core/polymorphic_compiler.py": (
        "7e7c5c6f4e74a7a0049af7881e25af04cfeb80f9c2e9a39432b25778917298ac"
    ),
    "django_graphex/core/registry_compiler.py": (
        "d769ff6c89abef7535638377d354601fbffd64e9a067411986a96259274af874"
    ),
    "django_graphex/core/validators.py": (
        "387fa324d6ff0e43106d2104aafed6e04022cb22ae6c7fd680e10fa5d6817474"
    ),
    "django_graphex/paginations/utils.py": (
        "3bd1bc8d765f578d5f2f0f7de78c64a5d6244abc6e38bfbeadc0fd51109f56a7"
    ),
    "django_graphex/uploads.py": (
        "3396506a68afac1d4e8bf58b7d71d4cf7ba3648fede2bd07b7491d34c3a6d6ec"
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


def test_runtime_internals_b_docstrings_are_complete_and_ast_is_unchanged() -> None:
    """Require exact owners, strict contracts, and unchanged executable AST.

    The digest excludes docstrings only, so annotations remain part of the contract.
    """
    checker = _load_checker()
    violations: dict[str, list[tuple[int, str]]] = {}

    for relative_path, expected_owners in EXPECTED_OWNERS.items():
        path = ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert _docstring_owners(tree) == expected_owners
        assert _executable_digest(tree) == EXPECTED_EXECUTABLE_DIGESTS[relative_path]
        violations[relative_path] = [
            (violation.lineno, violation.code)
            for violation in checker.check_file(
                path,
                strict_public=True,
                strict_content=True,
            )
        ]

    assert violations == {relative_path: [] for relative_path in EXPECTED_OWNERS}
