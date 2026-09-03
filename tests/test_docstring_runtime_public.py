"""Focused contract for public runtime docstrings."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "django_graphex"
FILES = tuple(RUNTIME / name for name in ("cost.py", "validation.py", "views.py"))
EXPECTED_OWNERS = {
    "cost.py": frozenset(
        {
            "<module>",
            "CostReport",
            "_settings_value",
            "_type_complexity",
            "_CostAnalyzer",
            "_CostAnalyzer.__init__",
            "_CostAnalyzer.operation_cost",
            "_CostAnalyzer._selection_set_cost",
            "_CostAnalyzer._own_cost",
            "_CostAnalyzer._list_multiplier",
            "_CostAnalyzer._page_size_argument",
            "_CostAnalyzer._is_list_field",
            "_CostAnalyzer._warn_unbounded",
            "_variable_defaults",
            "analyze_cost",
            "CostLimitValidationRule",
            "CostLimitValidationRule.enter_operation_definition",
        }
    ),
    "validation.py": frozenset(
        {
            "<module>",
            "_Constraint",
            "_type_max_depth",
            "DepthLimitValidationRule",
            "DepthLimitValidationRule.__init__",
            "DepthLimitValidationRule.enter_operation_definition",
            "DepthLimitValidationRule._walk",
            "DepthLimitValidationRule._report",
        }
    ),
    "views.py": frozenset(
        {
            "<module>",
            "csrf_header_missing",
            "HttpError",
            "HttpError.__init__",
            "get_accepted_content_types",
            "instantiate_middleware",
            "set_rollback",
            "_document_cache_maxsize",
            "_dynamic_limits_key",
            "_rules_key",
            "cached_parse",
            "cached_validate",
            "clear_document_caches",
            "BaseGraphQLView",
            "BaseGraphQLView.__init__",
            "BaseGraphQLView.get_root_value",
            "BaseGraphQLView.get_middleware",
            "BaseGraphQLView.get_context",
            "BaseGraphQLView.as_view",
            "BaseGraphQLView.csrf_header_guard",
            "BaseGraphQLView.dispatch",
            "BaseGraphQLView.get_response",
            "BaseGraphQLView.render_graphiql",
            "BaseGraphQLView.json_encode",
            "BaseGraphQLView.parse_body",
            "BaseGraphQLView._graphql_schema_for",
            "BaseGraphQLView._cache_key_signature",
            "BaseGraphQLView.execute_graphql_request",
            "BaseGraphQLView.can_display_graphiql",
            "BaseGraphQLView.request_wants_html",
            "BaseGraphQLView.get_graphql_params",
            "BaseGraphQLView.format_error",
            "BaseGraphQLView.get_content_type",
            "GraphQLView",
            "GraphQLView.get_operation_ast",
            "GraphQLView.fetch_cache_key",
            "GraphQLView.cache_key_prefix",
            "GraphQLView.should_cache_query",
            "GraphQLView._cache_version_identity",
            "GraphQLView._cache_version_namespace",
            "GraphQLView._get_cache_version",
            "GraphQLView._bump_cache_version",
            "GraphQLView.super_call",
            "GraphQLView._execute_uncached_and_invalidate",
            "GraphQLView.dispatch",
            "GraphQLView.as_view",
            "GraphQLView._is_introspection_document",
            "GraphQLView.get_response",
            "GraphQLView.get_query_cost",
            "GraphQLView.response_json_encode",
            "AuthenticatedGraphQLView",
            "AuthenticatedGraphQLView.__init__",
            "AuthenticatedGraphQLView._graphql_schema_for",
            "AuthenticatedGraphQLView._cache_key_signature",
            "AuthenticatedGraphQLView.dispatch",
            "AuthenticatedGraphQLView._forbidden_response",
            "AuthenticatedGraphQLView._passes_access_group",
        }
    ),
}
EXPECTED_EXECUTABLE_DIGESTS = {
    "cost.py": "85bbf1eee7d3135394abd4baa74694f0181ae3bf0dbac6d3b2d18fe8e072819a",
    "validation.py": "0f9c32c375155f584b6d6cd982a479b02cb06aaa2f90289de69d3758ec20e805",
    "views.py": "e7d8ce6f6eddc386282163ae5a2e0836264598d4ad87d18f5e0060e691d1197a",
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


def test_runtime_public_docstrings_are_complete_and_executable_ast_is_unchanged() -> (
    None
):
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
