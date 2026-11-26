"""Skip tests whose inputs live in the repository but not in the sdist.

The sdist allowlist in pyproject.toml does not ship directories such as
.github, benchmarks, examples, docs-overrides or integration. A test that reads
one of them declares it with requires_repo_paths and skips, with a clear reason,
when the input is truly absent. A repository checkout has every path, so
nothing is skipped there; tests/test_sdist_includes_test_inputs.py enforces
this contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def requires_repo_paths(*relative_paths: str) -> pytest.MarkDecorator:
    """Build a skip marker for tests that read repository-only inputs.

    Args:
        *relative_paths: Paths relative to the repository root, such as
            ".github/workflows/cicd.yaml". Each must exist for the test to run.

    Returns:
        A skipif marker for use as a decorator or as a module-level pytestmark.
    """
    missing = [path for path in relative_paths if not (ROOT / path).exists()]
    return pytest.mark.skipif(
        bool(missing),
        reason=f"repo-only input not shipped in the sdist: {', '.join(missing)}",
    )
