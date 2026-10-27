"""Keep five current-behavior limitations explicit in the usage guides."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def section(relative: str, heading: str) -> str:
    """Read one guide section without accepting a claim elsewhere in the file.

    Args:
        relative: Guide path relative to the repository root.
        heading: Exact Markdown heading introducing the contract.

    Returns:
        The heading's body up to the next heading of equal or higher level.
    """
    text = (ROOT / relative).read_text(encoding="utf-8")
    marker = f"{heading}\n"
    assert text.count(marker) == 1
    body = text.split(marker, 1)[1]
    level = len(heading) - len(heading.lstrip("#"))
    for line in body.splitlines():
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            body = body.split(f"\n{line}", 1)[0]
            break
    return body


def test_subscription_guide_separates_signals_from_manual_broadcast() -> None:
    """Keep bulk writes and manual sends outside automatic signal semantics.

    A manual broadcast publishes the current state immediately rather than
    inheriting the automatic signal handler's commit callback.
    """
    body = section(
        "docs/usage/subscriptions.md", "### Automatic and manual write paths"
    )
    for operation in ("bulk_create", "bulk_update", "QuerySet.update", "M2M.add"):
        assert operation in body
    assert "post_save" in body and "post_delete" in body
    assert "Subscription.get_binding().broadcast(action, instance)" in body
    assert "immediately" in body and "outermost commit" in body
    assert "fresh instance" in body
    assert "Subscription.broadcast(" not in body
    assert "on_commit(lambda" not in body


def test_date_guide_states_naive_timezone_assumption_without_changing_scalar() -> None:
    """Keep directive interpretation distinct from native DateTime coercion.

    The directive makes naive values aware while the scalar's input parser
    preserves them, including when Django timezone support is disabled.
    """
    body = section("docs/directives.md", "### Naive dates and timezone")
    assert "@date" in body and "TIME_ZONE" in body and "USE_TZ=False" in body
    assert "active Django timezone" in body
    assert "native DateTime scalar" in body and "preserves naive" in body
    assert "date(2026, 1, 10)" in body and "00:00" in body


def test_cache_guide_explains_csrf_cookie_round_trip_and_privacy() -> None:
    """Distinguish cookie-setting misses from cookie-free cache hits.

    A miss issues the CSRF cookie, and the next cookie-bearing browser request
    bypasses; a hit returns before the decorated dispatch and can stay eligible.
    """
    body = section("docs/usage/caching.md", "### Browser cookie round trip")
    assert "populate or hit" not in body
    assert body.count("A cache hit") == 1
    assert body.index("cache miss") < body.index("ensure_csrf_cookie")
    assert body.index("csrftoken") < body.index("If the browser returns that cookie")
    assert body.index("If the browser returns that cookie") < body.index("A cache hit")
    assert body.index("A cache hit") < body.index("before")
    assert body.index("before") < body.index("does not") < body.index("Set-Cookie")
    assert body.index("A cache hit") < body.index("cookie-free")
    assert body.index("cookie-free") < body.index("remain eligible")
    assert "first request" in body and "without cookies" in body
    assert "ensure_csrf_cookie" in body and "csrftoken" in body
    assert "second request" in body and "bypasses" in body
    assert "any cookie" in body and "privacy" in body
    assert "fully partition" in body
    assert "disable CSRF" not in body


def test_cache_guide_limits_csrf_cookie_claim_to_decorated_misses() -> None:
    """Name the decorated base view without promising a cookie on every response.

    Scenario: cache guide limits csrf cookie claim to decorated misses.
    """
    body = section("docs/usage/caching.md", "## CSRF cookies and cached responses")
    introduction = body.split("### Browser cookie round trip", 1)[0]
    assert "BaseGraphQLView.dispatch" in introduction
    assert "on every response" not in introduction
    assert "cache miss" in introduction and "cookie-free" in introduction
    assert "Server response-cache eligibility is distinct" in body
    assert "rfc9111.html#section-7.3" in body
    assert "rfc9111.html#section-4.1" in body
    assert "does not claim that a particular browser reuses" in body


def test_mutation_guide_distinguishes_input_semantics_from_sql_updates() -> None:
    """Separate partial-input assignment from SQL and concurrency guarantees.

    An omitted field can still appear in a full-row UPDATE after a stale
    instance is loaded, so the guide must state the practical overwrite risk.
    """
    body = section(
        "docs/usage/mutations.md", "### Partial input is not a concurrency guarantee"
    )
    assert "supplied fields" in body and "full save" in body
    assert "UPDATE" in body and "omitted field" in body
    assert "stale instance" in body and "overwrite" in body
    assert "update_fields" in body and "auto_now" in body
    assert "custom save" in body and "derived fields" in body


def test_pagination_guide_states_automatic_nullable_order_boundary() -> None:
    """Document offset/page parity without promising arbitrary ORM rewrites.

    Scenario: pagination guide states automatic nullable order boundary.
    """
    body = section(
        "docs/usage/pagination.md", "### Null ordering across paginator types"
    )
    assert "CursorGraphqlPagination" in body
    assert "NULL last ascending" in body and "NULL first descending" in body
    assert "LimitOffsetGraphqlPagination" in body and "PageGraphqlPagination" in body
    assert "nested SQL" in body and "materialized model lists" in body
    assert "category_id" in body and "Previously, a SQLite queryset" in body
    assert 'F("category_id").asc(nulls_first=True)' in body
    assert 'F("category_id").desc(nulls_last=True)' in body
    assert "does not rewrite custom expressions" in body
    assert "blanket cross-backend parity" in body
    assert "queryset ordering inherits the" not in body


def test_both_changelogs_scope_these_clarifications_to_documentation() -> None:
    """Scope both release notes to the documentation-only clarification.

    Neither changelog may present these already-existing runtime contracts
    as a newly fixed implementation behavior.
    """
    for relative in ("CHANGELOG.md", "docs/changelog.md"):
        body = section(relative, "## 4.1.0 — 2026-10-27")
        assert (
            "Document current subscription, timezone, cache-cookie, partial-update"
            in body
        )
        assert "pagination boundaries without changing runtime behavior" in body
