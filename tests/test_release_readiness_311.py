"""Release preparation contracts for the unpublished 3.1.1 security patch."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _metadata(path: Path) -> dict:
    """Load a TOML document used by a release contract.

    Args:
        path: Location of the TOML document.

    Returns:
        Parsed release metadata.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _package(lock: dict, name: str) -> dict:
    """Find one package in a resolved dependency lock.

    Args:
        lock: Parsed lock contents.
        name: Distribution name to find.

    Returns:
        The matching package entry.
    """
    return next(package for package in lock["package"] if package["name"] == name)


def test_patch_metadata_and_locks_are_consistent() -> None:
    """Keep the candidate version and patched runtime in both environments.

    The GraphQL 3.3 migration is deliberately not part of this patch.
    """
    project = _metadata(ROOT / "pyproject.toml")["project"]
    root_lock = _metadata(ROOT / "uv.lock")
    playground_lock = _metadata(ROOT / "examples/playground/uv.lock")

    assert project["version"] == "3.1.1"
    assert "graphql-core>=3.2.13,<3.3" in project["dependencies"]
    assert _package(root_lock, "django-graphex")["version"] == "3.1.1"
    assert _package(playground_lock, "django-graphex")["version"] == "3.1.1"
    for lock in (root_lock, playground_lock):
        assert _package(lock, "graphql-core")["version"] == "3.2.13"
    assert _package(playground_lock, "django")["version"] == "6.0.8"


def test_dated_patch_notes_preserve_310_history() -> None:
    """Date the patch notes without falsely describing them as published.

    The historical 3.1.0 release heading and audit trail remain available.
    """
    root_notes = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    docs_notes = (ROOT / "docs/changelog.md").read_text(encoding="utf-8")

    for notes in (root_notes, docs_notes):
        assert "## 3.1.1 — 2026-10-01" in notes
        assert "## 3.1.1 — Unreleased" not in notes
        assert "Publication remains pending." in notes
    assert "docs/changelog.md#311--2026-10-01" in root_notes
    assert "## 3.1.0 — 2026-09-03" in docs_notes
    assert "### Audit traceability" in docs_notes
    for term in (
        "https://github.com/graphql-python/graphql-core/releases/tag/v3.2.12",
        "https://github.com/graphql-python/graphql-core/releases/tag/v3.2.13",
        "max_tokens",
        "OverlappingFieldsCanBeMerged",
        "GraphQLSyntaxError",
    ):
        assert term in docs_notes


def test_security_guidance_distinguishes_upstream_and_view_limits() -> None:
    """Distinguish the upstream parser budget from HTTP view configuration.

    The view does not currently configure the parser's token limit.
    """
    guidance = (ROOT / "docs/usage/security.md").read_text(encoding="utf-8")

    for term in (
        "graphql-core 3.2.13",
        "max_tokens",
        "MAX_REQUEST_BODY_SIZE",
        "does not pass max_tokens",
        "250,000",
    ):
        assert term in guidance


def test_benchmark_versions_remain_historical() -> None:
    """Keep reproducible 3.1.0 measurements separate from current patches.

    The benchmark freeze is historical evidence, not a current lock file.
    """
    versions = (ROOT / "benchmarks/versions.env").read_text(encoding="utf-8")
    constraints = (ROOT / "benchmarks/constraints.txt").read_text(encoding="utf-8")
    benchmark_guide = (ROOT / "benchmarks/README.md").read_text(encoding="utf-8")
    public_guide = (ROOT / "docs/why.md").read_text(encoding="utf-8")

    assert "DJANGO_VERSION=6.0.6" in versions
    assert "Django==6.0.6" in constraints
    assert "graphql-core==3.2.11" in constraints
    assert "3.1.0 measurement" in benchmark_guide
    assert "3.1.0 measurement" in public_guide
