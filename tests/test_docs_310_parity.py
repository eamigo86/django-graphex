"""Contracts mapping every 3.1 audit finding to canonical documentation."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("finding", "page", "terms"),
    [
        (1, "usage/caching.md", ("should_cache_query", "request.COOKIES")),
        (2, "usage/caching.md", ("HTTP 405", "validation", "does **not** advance")),
        (
            3,
            "quickstart.md",
            ("AuthenticatedGraphQLView", "create_user", "only_fields"),
        ),
        (
            4,
            "contributing.md",
            ("complete validation graph", "TestPyPI", "refs/tags/v*"),
        ),
        (5, "contributing.md", ("immutable artifact", "SHA256SUMS", "never rebuild")),
        (6, "usage/subscriptions.md", ("Signal-time snapshots", "not coalesced")),
        (7, "usage/security.md", ("operationName", "CLEAN_RESPONSE")),
        (8, "usage/types.md", ("MultiSelectField", "subclass", "list")),
        (9, "usage/caching.md", ("CACHE_INVALIDATION_SCOPE", '"global"', '"identity"')),
        (10, "usage/query-limits.md", ("singular", "real GraphQL lists", "limit")),
        (
            11,
            "usage/permissions.md",
            ("awaitable", "ImproperlyConfigured", "subscription"),
        ),
        (12, "contributing.md", ("outside the checkout", "site-packages", "py.typed")),
        (13, "contributing.md", ("without Channels", "transaction")),
        (14, "contributing.md", ("exact exception", "match=")),
        (15, "contributing.md", ("--no-cov", "95.01", "diff-cover")),
        (16, "contributing.md", ("bounded", "tox", "dependency-groups.dev")),
        (17, "contributing.md", ("PostgreSQL 17", "GDX_TEST_DATABASE=postgres")),
        (
            18,
            "usage/mutations.md",
            (
                "permission_classes",
                "ImproperlyConfigured",
                "create, update, and delete",
            ),
        ),
        (
            19,
            "usage/examples/playground.md",
            ("0*.py", "__init__.py", "--no-migrations"),
        ),
        (
            20,
            "usage/examples/playground.md",
            ("ALLOWED_HOSTS", "evil.example", "localhost"),
        ),
        (21, "why.md", ("20 authors", "10 posts", "5 comments")),
        (22, "why.md", ("rollback", "sequence", "BEGIN/ROLLBACK")),
        (23, "why.md", ("BENCH_OFFLINE=1", "constraints.txt", "constraints_sha256")),
        (24, "why.md", ("run_publish.py", "--runs 3", "median")),
    ],
)
def test_each_310_audit_finding_has_canonical_documentation(
    finding: int, page: str, terms: tuple[str, ...]
) -> None:
    """Require each numbered finding in its release guide and canonical page.

    Args:
        finding: The audit finding identifier from 1 through 24.
        page: The canonical documentation page relative to the docs directory.
        terms: The required contract terms expected on that page.
    """
    release_guide = (ROOT / "docs" / "UPGRADE-3.1.md").read_text()
    assert f"| {finding} |" in release_guide

    content = (ROOT / "docs" / page).read_text()
    for term in terms:
        assert term in content, f"finding #{finding}: {term!r} missing from docs/{page}"


def test_310_release_guide_and_changelog_are_published_in_navigation() -> None:
    """Require navigation entries for the 3.1 guide and changelog.

    The changelog must also expose the release heading and audit traceability.
    """
    nav = (ROOT / "zensical.yml").read_text()
    assert "Upgrade Guide (3.0 → 3.1): UPGRADE-3.1.md" in nav
    assert "Changelog: changelog.md" in nav

    changelog = (ROOT / "docs" / "changelog.md").read_text()
    assert "## 3.1.0 —" in changelog
    assert "### Audit traceability" in changelog


def test_310_release_guide_local_links_resolve() -> None:
    """Require every local guide link to target a published documentation file.

    Fragment-only validation remains the documentation builder's responsibility.
    """
    guide = (ROOT / "docs" / "UPGRADE-3.1.md").read_text()
    targets = re.findall(r"\[[^]]+]\(([^)]+)\)", guide)

    for target in targets:
        if "://" in target or target.startswith("#"):
            continue
        path = target.partition("#")[0]
        assert (ROOT / "docs" / path).is_file(), target
