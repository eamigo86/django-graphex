"""Focused contract for public ordering test docstrings."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from scripts.check_docstrings import check_file

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DOCUMENTED_OWNERS = {
    "tests/test_ordering_allowlist_serving_type.py": frozenset(
        {
            "FlatPaginatedFieldRanksByTheServingTypeTests.setUpTestData",
            "FlatPaginatedFieldRanksByTheServingTypeTests.test_narrowing_the_served_type_withdraws_the_key",
            "FlatPaginatedFieldRanksByTheServingTypeTests.test_the_relation_makes_the_key_orderable_while_it_is_published",
        }
    ),
    "tests/test_ordering_provenance.py": frozenset(
        {
            "DivergentAllowlistStampTests.setUpTestData",
            "DivergentAllowlistStampTests.test_hidden_column_is_not_orderable_when_the_node_registers_late",
            "ServerDefaultOrderingTests.setUpTestData",
            "ServerDefaultOrderingTests.test_client_ordering_on_projected_away_column_is_still_rejected",
            "ServerDefaultOrderingTests.test_client_repeating_the_default_is_still_rejected",
            "ServerDefaultOrderingTests.test_configured_default_on_projected_away_column_still_serves",
            "ServerGeneratedTiebreakTests.setUpTestData",
            "ServerGeneratedTiebreakTests.test_a_real_client_term_outside_the_allowlist_still_raises",
            "ServerGeneratedTiebreakTests.test_empty_client_ordering_falls_back_to_the_pk_without_raising",
            "SharedPaginatorInstanceTests.setUpTestData",
            "SharedPaginatorInstanceTests.test_the_exposing_container_still_allows_that_same_column",
            "SharedPaginatorInstanceTests.test_the_hiding_container_still_rejects_its_own_hidden_column",
        }
    ),
    "tests/test_publishes_column_value.py": frozenset(
        {
            "TestARelationRenderedByAnotherModelsTypeStillServesTheKey.setUpTestData",
            "TestARelationRenderedByAnotherModelsTypeStillServesTheKey.test_the_predicate_agrees_the_key_is_published",
            "TestARelationRenderedByAnotherModelsTypeStillServesTheKey.test_the_relation_hands_out_the_targets_real_key",
        }
    ),
    "tests/test_relation_scope_hatch.py": frozenset(
        {
            "BareResolveMethodIsInertTests.setUpTestData",
            "BareResolveMethodIsInertTests.test_bare_resolve_method_never_runs",
            "DeclaredListObjectFieldClosesTheSameWayTests.test_a_declared_container_is_no_longer_traversable",
            "DeclaredRelationClosesBothProjectionAxesTests.setUpTestData",
            "DeclaredRelationClosesBothProjectionAxesTests.test_the_relation_is_no_longer_traversable_by_the_filter",
            "DeclaredRelationClosesBothProjectionAxesTests.test_the_relations_column_leaves_the_ordering_allowlist",
            "DeclaredToManyHatchClosesTheFilterAxisTests.test_the_parents_own_columns_stay_orderable",
            "DeclaredToManyHatchClosesTheFilterAxisTests.test_the_relation_is_no_longer_traversable_by_the_filter",
            "DeclaredToManyHatchTests.setUpTestData",
            "DeclaredToManyHatchTests.test_declared_relation_list_runs_the_scope",
            "DeclaredToOneHatchTests.setUpTestData",
            "DeclaredToOneHatchTests.test_declared_relation_field_runs_the_scope",
        }
    ),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "tests/test_ordering_allowlist_serving_type.py": (
        "f821d20a956b49952fcfc4082b0d01b510717a49f01ee8e9972cb727c45bd87b"
    ),
    "tests/test_ordering_provenance.py": (
        "6474c3adcece11c3031f2e8970a7508e30a0f1d1112479d907a002562f7ba5d1"
    ),
    "tests/test_publishes_column_value.py": (
        "f96b662bc74db0ce20ea1269d3b891e41acb296f4fe1cf651f9b4f6a86cc9ea7"
    ),
    "tests/test_relation_scope_hatch.py": (
        "5d8d5c4f6dea8f0af61013d6a7b89f18ee0bbe800612c07da3691a3ea786cfb5"
    ),
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


def test_public_ordering_test_docstrings_are_clean_and_runtime_neutral() -> None:
    """Require strict contracts, retained owners, and unchanged executable AST.

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
