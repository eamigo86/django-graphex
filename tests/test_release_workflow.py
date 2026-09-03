"""Structural contracts for the tag-driven release workflow."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/cicd.yaml"
RELEASE_DOCS = ROOT / "docs/releasing.md"
DOCS_CONFIG = ROOT / "zensical.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        _workflow(),
    )
    assert match, f"workflow job {name!r} not found"
    return match.group(1)


def test_release_artifact_builds_and_validates_one_distribution_pair() -> None:
    """Verify one job builds and validates the distribution pair.

    The workflow must create the reusable, checksummed artifact only once.
    """
    workflow = _workflow()
    artifact = _job("release-artifact")
    assert workflow.count("uv build") == 1
    assert "needs: [ get-version ]" in artifact
    assert "find dist -maxdepth 1 -type f -name '*.whl'" in artifact
    assert "find dist -maxdepth 1 -type f -name '*.tar.gz'" in artifact
    assert "check_wheel_install.py" in artifact
    assert "release_audit.py" in artifact
    assert "SHA256SUMS" in artifact
    assert "name: python-dist" in artifact
    assert "actions/upload-artifact@" in artifact


def test_release_consumers_download_and_verify_the_same_artifact() -> None:
    """Verify every publisher reuses the checksummed artifact.

    Publishing and GitHub Release must consume the bytes from the build job.
    """
    for job_name in ("publish", "create-release"):
        job = _job(job_name)
        assert "actions/download-artifact@" in job
        assert "name: python-dist" in job
        assert "sha256sum -c SHA256SUMS" in job
        assert "uv build" not in job

    publish = _job("publish")
    assert "uv publish dist/*.whl dist/*.tar.gz" in publish
    create_release = _job("create-release")
    assert "dist/*" in create_release


def test_immutable_artifact_contract_is_published_in_the_docs() -> None:
    """Verify maintainers can discover the build-once release contract.

    The documentation navigation must expose every immutable-artifact invariant.
    """
    documentation = RELEASE_DOCS.read_text(encoding="utf-8")
    navigation = DOCS_CONFIG.read_text(encoding="utf-8")
    assert "Release process: releasing.md" in navigation
    for requirement in (
        "one wheel and one source distribution",
        "SHA256SUMS",
        "python-dist",
        "must not rebuild",
    ):
        assert requirement in documentation
