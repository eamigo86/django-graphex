# -*- coding: utf-8 -*-
"""Multi-backend cache coverage for the v1.2.x cache fixes.

The cache fixes introduced in issues #60 (version counter), #53 (cookie/multipart
skip), and #11 (cross-user isolation) were originally validated only on
LocMemCache.  This module re-runs the core cache behaviours under both
LocMemCache and DatabaseCache to catch:

  - Pickle round-trip issues (DatabaseCache serialises values via pickle;
    LocMemCache stores Python objects in-process).
  - Cross-process semantics that LocMemCache hides (DatabaseCache uses a real
    DB table accessible to any process or thread sharing the same DB).

Backends under test
-------------------
LocMemCache
    No external dependencies; values stored as Python objects in a dict.
DatabaseCache
    Uses a SQLite table (the test suite already uses SQLite :memory:) created
    with "createcachetable" in the fixture. Catches pickle-roundtrip
    regressions and cross-process-visible state.

NOTE: Redis parity would require a running Redis service in CI (no Redis
service is configured in this project's CI matrix).  Redis coverage is left
as a follow-up requiring a CI service addition.
"""

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.cache import caches
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView
from tests.cache_helpers import graphql_post, minimal_cache_schema

if TYPE_CHECKING:
    from pytest_django.plugin import DjangoDbBlocker

# ---------------------------------------------------------------------------
# Backend parametrization
#
# Each parametrize ID pairs an override_settings CACHES dict with a human
# name.  The DatabaseCache cache table name is "test_graphql_cache" — a
# different name from any production cache table, so it does not collide with
# other test fixtures.
# ---------------------------------------------------------------------------

_LOCMEM_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-locmem",
    }
}

_DB_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "test_graphql_cache",
    }
}

# (cache_settings_dict, backend_label)
_BACKEND_PARAMS = [
    pytest.param(_LOCMEM_CACHES, id="locmem"),
    pytest.param(_DB_CACHES, id="db"),
]


# ---------------------------------------------------------------------------
# DatabaseCache table fixture
#
# createcachetable is idempotent (uses CREATE TABLE IF NOT EXISTS internally),
# so it is safe to call at test-module scope.  Calling it once per module
# rather than once per test keeps the suite fast.
#
# The table is created inside the Django test DB (SQLite :memory: as
# configured in conftest.pytest_configure).  Django's test runner wraps each
# TestCase in a transaction so the table is always clean between tests.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def ensure_db_cache_table(
    django_db_setup: None, django_db_blocker: "DjangoDbBlocker"
) -> None:
    """Create the DatabaseCache table once per test module.

    "django_db_setup" and "django_db_blocker" are pytest-django fixtures that
    ensure the test database exists before this fixture attempts DDL.

    Args:
        django_db_setup: The pytest-django fixture that provisions the test
            database; depended on only for ordering, its yielded value is
            unused.
        django_db_blocker: The pytest-django blocker used to unblock database
            access outside of a test body.

    The table name "test_graphql_cache" matches
    "_DB_CACHES["default"]["LOCATION"]" above. createcachetable is idempotent
    so re-running is safe.
    """
    with django_db_blocker.unblock():
        call_command("createcachetable", "test_graphql_cache", verbosity=0)


# ---------------------------------------------------------------------------
# Helper — build a fresh cache backend instance for the given settings
# ---------------------------------------------------------------------------


def _get_cache(caches_setting: dict[str, Any]) -> Any:
    """Return the "default" cache backend instance.

    Args:
        caches_setting: A CACHES override dict; unused, the cache is always
            fetched from Django's active "caches" registry by the "default"
            key.

    Returns:
        cache: The "default" cache backend currently configured in Django.
    """
    return caches["default"]


# ---------------------------------------------------------------------------
# Test class factory
#
# We use a base mixin and parametrize at the class level via pytest so that
# each backend gets its own isolated set of test results.  Django TestCase
# wraps every test in a transaction, which keeps DatabaseCache state clean
# between runs.
# ---------------------------------------------------------------------------


class _CacheBackendBehaviourBase:
    """Mixin with parametrized backend behaviours.

    Subclasses provide "caches_setting" (a CACHES dict) so the same
    behaviour assertions run against LocMemCache and DatabaseCache.
    """

    #: Subclasses must override this with a CACHES override dict.
    caches_setting: dict = {}

    def _settings(self, **extra_graphex: Any) -> dict[str, Any]:
        """Build the override_settings dict for this test's backend.

        Args:
            extra_graphex: Extra DJANGO_GRAPHEX settings that override the
                CACHE_ACTIVE/CACHE_TIMEOUT defaults.

        Returns:
            settings: A dict with "CACHES" set to this instance's
                caches_setting and "DJANGO_GRAPHEX" merged with the extras.
        """
        graphex = {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}
        graphex.update(extra_graphex)
        return {"CACHES": self.caches_setting, "DJANGO_GRAPHEX": graphex}

    # ------------------------------------------------------------------
    # 1. Per-identity isolation: user A's cache entry not served to user B
    # ------------------------------------------------------------------

    def test_per_identity_isolation(self) -> None:
        """User A's cached entry MUST NOT be served to user B.

        If this breaks, the cache key namespace is not identity-scoped and
        one user's response can leak to another user on the same backend.
        """
        settings = self._settings()
        factory = RequestFactory()
        user_a = User(pk=10, username="alice_backend")
        user_b = User(pk=11, username="bob_backend")

        with override_settings(**settings):
            caches["default"].clear()
            view = GraphQLView.as_view(schema=minimal_cache_schema)

            req_a = graphql_post(factory, "{ me }", user=user_a)
            resp_a = view(req_a)
            data_a = json.loads(resp_a.content)
            assert data_a["data"]["me"] == "alice_backend"

            req_b = graphql_post(factory, "{ me }", user=user_b)
            resp_b = view(req_b)
            data_b = json.loads(resp_b.content)
            assert data_b["data"]["me"] == "bob_backend", (
                f"User B received user A's cached response (cross-user leak on "
                f"{self.caches_setting['default']['BACKEND']})"
            )

    # ------------------------------------------------------------------
    # 2. Mutation on_commit version bump — cache invalidated after mutation
    # ------------------------------------------------------------------

    def test_mutation_invalidates_own_namespace(self) -> None:
        """After a mutation, a subsequent query from the SAME user MUST hit the backend again.

        The mutation advances the identity's version counter so the old cached
        key is no longer addressed.  We verify by checking that super_call is
        invoked a second time after the mutation.
        """
        settings = self._settings()
        factory = RequestFactory()
        user = User(pk=20, username="mutator_backend")

        with override_settings(**settings):
            caches["default"].clear()
            view = GraphQLView.as_view(schema=minimal_cache_schema)
            call_count = {"n": 0}
            original_super_call = GraphQLView.super_call

            def counting_super_call(self_view, request, *args, **kwargs):
                call_count["n"] += 1
                return original_super_call(self_view, request, *args, **kwargs)

            with patch.object(GraphQLView, "super_call", counting_super_call):
                # First query — populates cache.
                view(graphql_post(factory, "{ hello }", user=user))
                assert call_count["n"] == 1, "First query did not reach backend"

                # Mutation — bumps version counter via on_commit.
                # captureOnCommitCallbacks flushes on_commit within the test.
                with self.captureOnCommitCallbacks(execute=True):  # type: ignore[attr-defined]
                    view(
                        graphql_post(factory, "mutation { doThing { ok } }", user=user)
                    )

                # Second query — version changed, MUST re-execute.
                view(graphql_post(factory, "{ hello }", user=user))
                assert call_count["n"] >= 3, (
                    f"Second query after mutation was served from stale cache on "
                    f"{self.caches_setting['default']['BACKEND']} "
                    f"(super_call count={call_count['n']}, expected >=3)"
                )

    # ------------------------------------------------------------------
    # 3. Cookie-bearing response not cached (CSRF skip)
    # ------------------------------------------------------------------

    def test_cookie_bearing_response_not_cached(self) -> None:
        """A response that carries Set-Cookie MUST NOT be stored and replayed.

        The view stores only (body, status, content_type) so the cache hit
        reconstructs a cookie-free response.  This prevents CSRF token sharing
        across identity namespaces (issue #53b).
        """
        settings = self._settings()
        factory = RequestFactory()

        with override_settings(**settings):
            caches["default"].clear()
            view = GraphQLView.as_view(schema=minimal_cache_schema)
            call_count = {"n": 0}
            original_super_call = GraphQLView.super_call

            def counting_super_call(self_view, request, *args, **kwargs):
                call_count["n"] += 1
                return original_super_call(self_view, request, *args, **kwargs)

            req1 = graphql_post(factory, "{ hello }")
            req2 = graphql_post(factory, "{ hello }")

            with patch.object(GraphQLView, "super_call", counting_super_call):
                resp1 = view(req1)
                resp2 = view(req2)

            # Second response MUST be served from cache (backend called once).
            assert call_count["n"] == 1, (
                f"Backend was called twice — caching is not working on "
                f"{self.caches_setting['default']['BACKEND']}"
            )

            # The cached (reconstructed) response MUST NOT carry the first
            # response's Set-Cookie header verbatim.
            cookie1 = resp1.cookies.get("csrftoken")
            cookie2 = resp2.cookies.get("csrftoken")
            if cookie1 is not None and cookie2 is not None:
                assert cookie1.value != cookie2.value, (
                    "Cached response replayed first client's CSRF cookie to second client "
                    f"(backend: {self.caches_setting['default']['BACKEND']})"
                )

    # ------------------------------------------------------------------
    # 4. Cache-hit reconstruction: body and status round-trip correctly
    # ------------------------------------------------------------------

    def test_cache_hit_reconstructs_response_correctly(self) -> None:
        """A cache hit MUST return the same body and status as the original response.

        This validates the (body, status, content_type) tuple survives the
        backend's serialisation round-trip (pickle for DatabaseCache, in-process
        for LocMemCache).
        """
        settings = self._settings()
        factory = RequestFactory()

        with override_settings(**settings):
            caches["default"].clear()
            view = GraphQLView.as_view(schema=minimal_cache_schema)

            req1 = graphql_post(factory, "{ hello }")
            req2 = graphql_post(factory, "{ hello }")

            resp1 = view(req1)
            resp2 = view(req2)

            # Both must be HTTP 200.
            assert resp1.status_code == 200
            assert resp2.status_code == 200

            # Body must be identical (same query, same resolver result).
            assert resp1.content == resp2.content, (
                f"Cache hit returned different body on "
                f"{self.caches_setting['default']['BACKEND']}: "
                f"original={resp1.content!r}, hit={resp2.content!r}"
            )

            # The body must be valid JSON with the expected value.
            data = json.loads(resp2.content)
            assert data["data"]["hello"] == "world"


# ---------------------------------------------------------------------------
# Concrete test classes — one per backend
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCacheBackendLocMem(TestCase, _CacheBackendBehaviourBase):
    """Runs all cache behaviour assertions against LocMemCache.

    LocMemCache stores values as Python objects in-process, so it never
    exercises the pickle round-trip that DatabaseCache goes through.
    """

    caches_setting = _LOCMEM_CACHES


@pytest.mark.django_db(transaction=True)
class TestCacheBackendDB(TestCase, _CacheBackendBehaviourBase):
    """Runs all cache behaviour assertions against DatabaseCache.

    DatabaseCache uses a SQLite table created by the "ensure_db_cache_table"
    fixture. This backend surfaces pickle round-trip regressions and
    cross-process-visible state that LocMemCache hides.

    Note: Redis parity would require a running Redis service in CI.
    No Redis service is configured in this project's CI matrix, so Redis
    coverage is out of scope for this issue.
    """

    caches_setting = _DB_CACHES
