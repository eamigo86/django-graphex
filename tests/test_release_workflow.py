"""Structural contracts for the tag-driven release workflow."""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/cicd.yaml"
MANUAL_DOCS = ROOT / ".github/workflows/docs.yml"
RELEASE_DOCS = ROOT / "docs/releasing.md"
CONTRIBUTING_DOCS = ROOT / "docs/contributing.md"
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


def test_security_patch_child_pr_runs_ci_without_widening_release_triggers() -> None:
    """Run CI for the selected child base without changing release triggers.

    Only pull-request bases expand; push and publication restrictions remain.
    """
    workflow = _workflow()
    triggers = workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
    pull_request = triggers.split("  pull_request:\n", 1)[1].split(
        "  workflow_dispatch:", 1
    )[0]
    branches = set(re.findall(r"(?m)^    - '?([^'\n]+)'?$", pull_request))

    assert {"main", "v*.*.*", "codex/v3.1.1-*"} <= branches
    assert any(fnmatchcase("codex/v3.1.1-security", branch) for branch in branches)
    assert "    - 'codex/v3.1.1-*'" not in triggers.split("  pull_request:\n", 1)[0]


def test_graphql_core_migration_branches_run_ci_without_widening_publish() -> None:
    """Admit only the migration integration and child bases to CI.

    The existing release tag and manual publication triggers stay separate.
    """
    triggers = _workflow().split("on:\n", 1)[1].split("\npermissions:", 1)[0]
    push = triggers.split("  push:\n", 1)[1].split("  pull_request:\n", 1)[0]
    pull_request = triggers.split("  pull_request:\n", 1)[1].split(
        "  workflow_dispatch:", 1
    )[0]
    push_branches, push_tags = push.split("    tags:\n", 1)
    branch_pattern = r"(?m)^    - '?([^'\n]+)'?$"
    assert set(re.findall(branch_pattern, push_branches)) == {
        "main",
        "v*.*.*",
        "codex/graphql-core-3.3",
    }
    assert set(re.findall(branch_pattern, pull_request)) == {
        "main",
        "v*.*.*",
        "codex/v3.1.1-*",
        "codex/graphql-core-3.3",
        "codex/graphql-core-3.3-*",
    }
    assert push_tags.strip() == "- 'v*.*.*'"
    assert "  workflow_dispatch:" in triggers
    for base in ("codex/graphql-core-3.3", "codex/graphql-core-3.3-t1"):
        assert any(
            fnmatchcase(base, branch)
            for branch in re.findall(branch_pattern, pull_request)
        )
    assert not any(
        fnmatchcase("codex/unrelated-feature", branch)
        for branch in re.findall(branch_pattern, pull_request)
    )


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


def test_publish_waits_for_every_release_gate() -> None:
    """Publication cannot bypass tests, packaging, docs, or example-project gates.

    This test protects the corresponding regression contract.
    """
    publish = _job("publish")
    needs_match = re.search(r"needs: \[([^]]+)]", publish)
    assert needs_match
    actual = {item.strip() for item in needs_match.group(1).split(",")}
    assert actual == {
        "test",
        "base-install",
        "lint-and-security",
        "diff-check",
        "coverage",
        "postgresql",
        "docs-build",
        "playground",
        "release-artifact",
        "get-version",
    }


def test_release_branch_has_a_cumulative_diff_check_gate() -> None:
    """Reject whitespace errors accumulated anywhere on the release branch.

    The gate compares HEAD with the shared main-branch merge base, rather than
    checking only the latest child PR, and must block publication.
    """
    command = "python3 scripts/check_docstrings.py . --strict-public --strict-content"
    diff_check = _job("diff-check")
    publish = _job("publish")
    documentation = CONTRIBUTING_DOCS.read_text(encoding="utf-8")

    assert "fetch-depth: 0" in diff_check
    assert "git merge-base origin/main HEAD" in diff_check
    assert 'git diff --check "$BASE_COMMIT"..HEAD' in diff_check
    assert "diff-check" in publish.split("needs: [", 1)[1].split("]", 1)[0]
    assert command in diff_check
    assert "RATCHET_BASE" not in diff_check
    assert "--diff-base" not in diff_check
    assert command in documentation
    requirements = "|".join(
        (
            "A. **Complete public Google style.**",
            "B. **Signature-owned types.**",
            "C. **Plain-text docstrings.**",
            "benchmarks",
            "examples/playground",
        )
    )
    assert all(item in documentation for item in requirements.split("|"))


def test_docs_are_built_before_publish_and_deployed_afterward() -> None:
    """Pages deploys the documentation artifact already validated before PyPI.

    This test protects the corresponding regression contract.
    """
    workflow = _workflow()
    docs = _job("docs-build")
    deploy = _job("deploy-docs")
    assert workflow.index("  docs-build:") < workflow.index("  publish:")
    assert "zensical build --clean" in docs
    assert "actions/upload-pages-artifact@" in docs
    assert "needs: [ publish, docs-build ]" in deploy
    assert "actions/deploy-pages@" in deploy
    assert "zensical build" not in deploy
    assert "actions/checkout@" not in deploy


def test_pages_deployment_exists_only_in_tag_release_workflow() -> None:
    """The manual docs check cannot bypass successful tagged publication.

    This test protects the corresponding regression contract.
    """
    manual = MANUAL_DOCS.read_text(encoding="utf-8")
    assert "actions/deploy-pages@" not in manual
    assert "actions/upload-pages-artifact@" not in manual
    assert "name: docs-preview" in manual


def test_manual_publish_is_testpypi_only_and_tags_are_production_only() -> None:
    """Manual runs stay in staging while only a version tag can reach PyPI.

    This test protects the corresponding regression contract.
    """
    workflow = _workflow()
    dispatch = workflow.split("  workflow_dispatch:", 1)[1].split(
        "\n\npermissions:", 1
    )[0]
    publish = _job("publish")
    assert "inputs:" not in dispatch
    assert "github.event.inputs" not in publish
    assert (
        "startsWith(github.ref, 'refs/tags/v') && 'production' || 'staging'" in publish
    )
    assert re.search(
        r"name: Publish to PyPI\n\s+if: startsWith\(github\.ref, 'refs/tags/v'\)",
        publish,
    )
    assert re.search(
        r"name: Publish to TestPyPI\n\s+if: github\.event_name == 'workflow_dispatch'",
        publish,
    )


def test_tag_version_is_rejected_before_the_artifact_build() -> None:
    """A mismatched tag fails in get-version before any releasable bytes exist.

    This test protects the corresponding regression contract.
    """
    workflow = _workflow()
    version = _job("get-version")
    publish = _job("publish")
    assert "GITHUB_REF_NAME#v" in version
    assert "does not match pyproject.toml version" in version
    assert "GITHUB_REF_NAME#v" not in publish
    assert workflow.index("Verify tag matches the package version") < workflow.index(
        "uv build"
    )


def test_codecov_upload_pins_pypi_cli_and_fails_closed() -> None:
    """Use the pinned supported acquisition route without swallowing errors.

    Exact step inputs preserve authentication and reports while rejecting
    alternate binaries, TLS bypasses, validation overrides and skipped uploads.
    """
    coverage = _job("coverage")
    marker = "    - name: Upload coverage to Codecov\n"
    assert coverage.count(marker) == 1
    upload = coverage.split(marker, maxsplit=1)[1]
    assert (
        upload.strip()
        == "\n".join(
            (
                "      uses: codecov/codecov-action@fb8b3582c8e4def4969c97caa2f19720cb33a72f # v7",
                "      with:",
                "        token: ${{ secrets.CODECOV_TOKEN }}",
                "        files: ./coverage.xml",
                "        use_pypi: true",
                "        version: v11.3.1",
                "        fail_ci_if_error: true",
                "        verbose: true",
            )
        ).strip()
    )


def test_codecov_distribution_tradeoff_and_acceptance_are_documented() -> None:
    """Explain the acquisition trust change and real hosted acceptance.

    A version pin and a green job do not prove a complete upload or signed
    standalone-binary provenance for a Python-package installation.
    """
    documents = [CONTRIBUTING_DOCS.read_text(encoding="utf-8")]
    for path in (ROOT / "CHANGELOG.md", ROOT / "docs/changelog.md"):
        documents.append(
            path.read_text(encoding="utf-8").split("## 3.1.1", maxsplit=1)[0]
        )
    for document in documents:
        for requirement in (
            "codecov-cli",
            "11.3.1",
            "PyPI",
            "HTTPS",
            "GPG/checksum",
            "fail_ci_if_error",
        ):
            assert requirement in document
    guidance = documents[0]
    for requirement in (
        "use_pypi: true",
        "version: v11.3.1",
        "fail_ci_if_error: true",
        "not equivalent",
        "transitive dependencies",
        "both Codecov project and patch checks",
        "exact commit",
    ):
        assert requirement in guidance
