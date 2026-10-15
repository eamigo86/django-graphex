"""Execute the playground's django-graphex 3.1 security contract in isolation."""

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLAYGROUND = Path(__file__).resolve().parents[1] / "examples" / "playground"


def test_cursor_pagination_readme_matches_playground_settings() -> None:
    """Keep the documented cursor default and cap aligned with this app.

    The schema omits a local cursor size, so its paginator inherits the
    Playground settings rather than the unconfigured library defaults.

    """
    settings_tree = ast.parse((PLAYGROUND / "config/settings.py").read_text())
    assignment = next(
        node
        for node in settings_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "DJANGO_GRAPHEX"
            for target in node.targets
        )
    )
    assert isinstance(assignment.value, ast.Dict)
    configured = {
        ast.literal_eval(key): ast.literal_eval(value)
        for key, value in zip(assignment.value.keys, assignment.value.values)
        if isinstance(key, ast.Constant)
        and key.value in {"DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE"}
    }
    assert configured == {"DEFAULT_PAGE_SIZE": 10, "MAX_PAGE_SIZE": 100}

    schema_tree = ast.parse((PLAYGROUND / "blog/schema.py").read_text())
    comment_list = next(
        node
        for node in schema_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "CommentListType"
    )
    meta = next(
        node
        for node in comment_list.body
        if isinstance(node, ast.ClassDef) and node.name == "Meta"
    )
    pagination = next(
        node.value
        for node in meta.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "pagination"
            for target in node.targets
        )
    )
    assert isinstance(pagination, ast.Call)
    assert isinstance(pagination.func, ast.Name)
    assert pagination.func.id == "CursorGraphqlPagination"
    assert {keyword.arg for keyword in pagination.keywords} == {"ordering"}

    row = next(
        line
        for line in (PLAYGROUND / "README.md").read_text().splitlines()
        if line.startswith("| `CursorGraphqlPagination` |")
    )
    documented_default = re.search(r"DEFAULT_PAGE_SIZE\s*=\s*(\d+)", row)
    documented_maximum = re.search(r"MAX_PAGE_SIZE\s*=\s*(\d+)", row)
    assert documented_default is not None, row
    assert documented_maximum is not None, row
    assert int(documented_default.group(1)) == configured["DEFAULT_PAGE_SIZE"]
    assert int(documented_maximum.group(1)) == configured["MAX_PAGE_SIZE"]
    assert "remains unset" not in row


def test_playground_310_auth_and_cache_contract_is_executable() -> None:
    """Run the real example schema/views without polluting the root registry.

    The subprocess isolates Django settings and global GraphQL type registries.
    """
    if importlib.util.find_spec("daphne") is None:
        pytest.skip("the runnable playground requires the subscriptions extra")

    env = os.environ.copy()
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.pop("PYTEST_ADDOPTS", None)
    selected = [
        "tests/test_schema_and_client.py::test_auth_user_surface_is_read_only_and_minimal",
        "tests/test_schema_and_client.py::test_secure_endpoint_rejects_anonymous_user_reads",
        "tests/test_schema_and_client.py::test_public_registration_hashes_password_without_granting_privileges",
        "tests/test_shipped_defaults.py::test_response_cache_starts_disabled_with_global_invalidation",
        "tests/test_shipped_defaults.py::test_default_query_cache_hook_rejects_cookie_dependent_requests",
    ]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *selected,
            "-q",
            "--no-cov",
            "--no-migrations",
        ],
        cwd=PLAYGROUND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
