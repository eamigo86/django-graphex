"""Execute the playground's django-graphex 3.1 security contract in isolation."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLAYGROUND = Path(__file__).resolve().parents[1] / "examples" / "playground"


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
