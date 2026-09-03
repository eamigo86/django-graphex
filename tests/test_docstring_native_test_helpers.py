"""Focused contract for native test-helper docstrings."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DOCUMENTED_OWNERS = {
    "examples/playground/tests/test_subscription_transports_e2e.py": frozenset(
        {"_sse_frames", "_fresh_channel_layer"}
    ),
    "tests/core/_sdl_parity_seed.py": frozenset(
        {"_build_native_seed_schema", "_extract_block"}
    ),
    "tests/core/test_fk_check_failure_path.py": frozenset({"_fk_existence_probes"}),
    "tests/core/test_input_compiler_lists_defaults.py": frozenset(
        {"_sdl", "_exec_arg"}
    ),
    "tests/core/test_input_compiler_nested_inputtype.py": frozenset({"_exec_outer"}),
    "tests/core/test_native_args_only.py": frozenset(
        {"_BlockGraphene", "_purge_graphene_modules", "_arg_sdl"}
    ),
    "tests/core/test_native_choices_enum.py": frozenset(
        {"_unwrap", "_canonical_enum_name"}
    ),
    "tests/core/test_native_root_graphene_free.py": frozenset(
        {"_BlockGraphene", "_purge_graphene_modules"}
    ),
    "tests/core/test_pagination_native_only.py": frozenset(
        {"_build_paginated_schema", "_normalize_results_element"}
    ),
    "tests/core/test_s8c_field_descriptor_graphene_free.py": frozenset(
        {"_build_field_kind_schema"}
    ),
    "tests/core/test_schema_lazy_fork.py": frozenset(
        {
            "_isolate_global_registries",
            "_build_schema_over_post",
            "_invalidate_relation_caches",
        }
    ),
    "tests/core/test_subscription_native_build.py": frozenset({"_BlockGraphene"}),
    "tests/core/test_window_prefetch_native.py": frozenset(
        {"_make_django_type", "_build_native_nested_schema", "_seed"}
    ),
    "tests/core/test_zero_graphene_full_exercise.py": frozenset(
        {"_run_gate_subprocess"}
    ),
    "tests/subscriptions/test_source.py": frozenset({"_FakeChannelLayer"}),
    "tests/subscriptions/urls_sse_csrf.py": frozenset({"_build_native_schema"}),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "examples/playground/tests/test_subscription_transports_e2e.py": "5b19e1296acadcad3a6a86156454993e23f6acceb5e830a9500414f090ddd1a6",
    "tests/core/_sdl_parity_seed.py": "d3d58366278297aa51a68614d254dc866a7ab80d423b006ce6538dcd5b2f186e",
    "tests/core/test_fk_check_failure_path.py": "b9c916422268b754ff3bd0055df3b8c3dd4598ab1c76ee72838dfd5db9605888",
    "tests/core/test_input_compiler_lists_defaults.py": "794d9681ad07c309834ecbafad33eb931c5c254a07e60560442e5d436fdb9c1f",
    "tests/core/test_input_compiler_nested_inputtype.py": "bf211dd67d3f4a098bf3a10fb1f1242fa6aa47b3fb8c20dd0d53dfc9f6fdb3c4",
    "tests/core/test_native_args_only.py": "bf1f0387ab51b2bc46b7032c0d341afb6d27bf0c442d363c704578f5c6406e53",
    "tests/core/test_native_choices_enum.py": "dddda67f2da51560ba4a3414b8d6a2350f6ea11bd76475fd3442a6207e0f7539",
    "tests/core/test_native_root_graphene_free.py": "2b5f97d7ee66fa29489fb08e5526e6d8ce259a3f25b494d1e9e8d1264c092b41",
    "tests/core/test_pagination_native_only.py": "a66112dc203c12fe9381bda4f48eb95730ebab611f42c45f74f227c2852604f0",
    "tests/core/test_s8c_field_descriptor_graphene_free.py": "e0d8eb9242e80f4a849c6daa9552fa16daf56df18c390288a8b673967f0af00e",
    "tests/core/test_schema_lazy_fork.py": "0e64c2e2a7b9d0e02a53b0541c5251657f5eb89123cdf89878d0d4baac796a23",
    "tests/core/test_subscription_native_build.py": "261f2ccacde516ae60b0e88b45d17d0d192f1a90ec5ae0e11cac7e8d14f39d21",
    "tests/core/test_window_prefetch_native.py": "618c857b7e9fa38294b297efba5c4ea71b3889fe08a8b9d23458944021431241",
    "tests/core/test_zero_graphene_full_exercise.py": "fa6077761e572c4d916d2ed5cfa81f935bbb9ba69c928e4c237aff09cb14ff98",
    "tests/subscriptions/test_source.py": "fa7c238b6b012f27004abf7c57457a96f8cb39470fcb14ebdf5927d4d358d964",
    "tests/subscriptions/urls_sse_csrf.py": "b29cf536ba868ed450e4d4b22d1f28e7c97ba21e319d447b78d3dae73853d872",
}


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

        visit_ClassDef = _visit_owner
        visit_FunctionDef = _visit_owner
        visit_AsyncFunctionDef = _visit_owner

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

        def _visit_owner(
            self,
            node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> ast.AST:
            self.generic_visit(node)
            node.body = self._without_docstring(node.body)
            return node

        visit_Module = _visit_owner
        visit_ClassDef = _visit_owner
        visit_FunctionDef = _visit_owner
        visit_AsyncFunctionDef = _visit_owner

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


def test_native_test_helper_docstrings_are_clean_and_runtime_neutral() -> None:
    """Require strict content, retained owners, and unchanged executable AST.

    The executable digest excludes docstrings only.
    """
    violations: dict[str, list[tuple[int, str]]] = {}

    for name, expected_owners in EXPECTED_DOCUMENTED_OWNERS.items():
        path = ROOT / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert expected_owners <= _docstring_owners(tree)
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
