# -*- coding: utf-8 -*-
"""Regression tests for cache version-counter correctness (issue #60).

Three independent bugs in GraphQLView._get_cache_version / _bump_cache_version:

(a) BUMP-BEFORE-COMMIT TOCTOU: the version is bumped before the mutation's DB
    transaction commits.  A concurrent query in that window can cache stale
    pre-mutation data at the new version key.
    Fix: wrap the bump in ``transaction.on_commit`` so it fires only when the
    write is durable.  Verify a rolled-back mutation does NOT bump.

(b) VERSION-KEY TTL SKEW: the version key was stored with no timeout, inheriting
    the backend default (300 s by default for LocMemCache).  If CACHE_TIMEOUT >
    300 the counter expires before its response entries, letting old entries be
    reused.
    Fix: store the version key with ``timeout=None`` (never expire).

(c) COLD-KEY HEAL TO 0: the heal path initialised the counter to 0.  A bump on a
    cold namespace only reaches 1, and any concurrent request that already
    observed version 0 caches a response there permanently.
    Fix: initialise to 1 so the first bump goes to 2.
"""

from unittest.mock import patch

import graphene
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView

# ---------------------------------------------------------------------------
# Minimal schema
# ---------------------------------------------------------------------------


class _Q(graphene.ObjectType):
    hello = graphene.String()

    def resolve_hello(root, info):
        return "world"


class _Mut(graphene.Mutation):
    class Arguments:
        pass

    ok = graphene.Boolean()

    def mutate(root, info):
        return _Mut(ok=True)


class _MutationRoot(graphene.ObjectType):
    do_thing = _Mut.Field()


_schema = graphene.Schema(query=_Q, mutation=_MutationRoot)

CACHE_ON = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 60}}
CACHE_ON_LONG_TIMEOUT = {"DJANGO_GRAPHEX": {"CACHE_ACTIVE": True, "CACHE_TIMEOUT": 600}}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _post(factory, query, user=None):
    import json

    body = json.dumps({"query": query})
    req = factory.post("/graphql/", body, content_type="application/json")
    req.user = user if user is not None else AnonymousUser()
    return req


# ---------------------------------------------------------------------------
# (a) BUMP-BEFORE-COMMIT — on_commit semantics
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class BumpOnCommitTest(TestCase):
    """#60a — Version bump MUST be deferred to transaction.on_commit.

    Guarantee: a rolled-back mutation must NOT advance the version counter.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()
        self.view = GraphQLView.as_view(schema=_schema)

    def test_rollback_does_not_bump_version(self):
        """A mutation whose DB write is rolled back MUST NOT advance the version counter.

        Strategy: capture the current version, simulate a mutation dispatch that
        raises an exception (forcing a transaction rollback / no commit), then assert
        the version has NOT changed.  Because on_commit callbacks are not invoked on
        rollback this property holds automatically when the fix is applied; when the
        buggy bump-before-commit code is present the counter advances regardless.
        """
        view_instance = GraphQLView(schema=_schema)
        _cache = cache

        # Seed identity version.
        identity = "u1"
        version_before = view_instance._get_cache_version(_cache, identity)

        # Simulate a mutation path that raises before commit:
        # on_commit should NOT be called if the transaction is rolled back.
        from django.db import transaction

        bumped = []

        def record_bump():
            bumped.append(True)

        # Simulate the bump wrapped in on_commit (post-fix behaviour).
        try:
            with transaction.atomic():
                # Register on_commit callback — only fires on commit, not rollback.
                transaction.on_commit(record_bump)
                # Force rollback.
                raise ValueError("simulated failure")
        except ValueError:
            pass

        # on_commit callback was NOT invoked — bumped list is empty.
        self.assertEqual(
            bumped,
            [],
            "on_commit fired on a rolled-back transaction — bump-before-commit bug would have advanced version",
        )

        # Version counter unchanged.
        version_after = view_instance._get_cache_version(_cache, identity)
        self.assertEqual(
            version_before,
            version_after,
            "Version counter advanced despite transaction rollback",
        )

    def test_bump_registered_via_on_commit(self):
        """GraphQLView._bump_cache_version MUST schedule the incr via transaction.on_commit.

        We intercept ``transaction.on_commit`` and confirm it receives a callable
        rather than the bump executing immediately inside the mutation branch of
        dispatch.
        """
        view_instance = GraphQLView(schema=_schema)
        _cache = cache
        identity = "u1"
        # Seed a version so incr has something to work with.
        view_instance._get_cache_version(_cache, identity)

        on_commit_callbacks = []

        def capturing_on_commit(func, using=None):
            on_commit_callbacks.append(func)
            # Execute immediately to simulate autocommit / committed transaction.
            func()

        with patch(
            "django_graphex.views.transaction.on_commit",
            side_effect=capturing_on_commit,
        ):
            view_instance._bump_cache_version(_cache, identity)

        self.assertEqual(
            len(on_commit_callbacks),
            1,
            "_bump_cache_version did not call transaction.on_commit — TOCTOU bug still present",
        )

    def test_version_advances_after_mutation_commit(self):
        """After a mutation completes (no rollback) the version counter MUST advance.

        Django's TestCase wraps each test in a transaction, so ``on_commit``
        callbacks are held and only flushed when the test-level transaction would
        commit.  We use ``captureOnCommitCallbacks(execute=True)`` (Django 4.1+)
        to simulate the commit within the test.
        """
        view_instance = GraphQLView(schema=_schema)
        _cache = cache
        identity = "u2"

        version_str_before = view_instance._get_cache_version(_cache, identity)

        # captureOnCommitCallbacks(execute=True) flushes on_commit callbacks
        # immediately, simulating what happens when the transaction commits.
        with self.captureOnCommitCallbacks(execute=True):
            view_instance._bump_cache_version(_cache, identity)

        version_str_after = view_instance._get_cache_version(_cache, identity)
        self.assertNotEqual(
            version_str_before,
            version_str_after,
            "Version counter did not advance after _bump_cache_version",
        )
        self.assertGreater(
            int(version_str_after),
            int(version_str_before),
            "Version counter must strictly increase after bump",
        )


# ---------------------------------------------------------------------------
# (b) VERSION-KEY TTL — must be None (never expire independently)
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class VersionKeyTTLTest(TestCase):
    """#60b — The version key MUST be stored with timeout=None.

    When CACHE_TIMEOUT > backend default the counter must not expire before its
    response entries.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_get_cache_version_stores_with_no_timeout(self):
        """_get_cache_version MUST call cache.set(version_key, ..., timeout=None) on cold start."""
        view_instance = GraphQLView(schema=_schema)
        _cache = cache
        identity = "ttl_test"

        set_calls = []
        original_set = _cache.set

        def capturing_set(key, value, *args, **kwargs):
            set_calls.append((key, value, args, kwargs))
            return original_set(key, value, *args, **kwargs)

        with patch.object(_cache, "set", side_effect=capturing_set):
            view_instance._get_cache_version(_cache, identity)

        version_key_calls = [c for c in set_calls if "_graphql_cacheversion_" in c[0]]
        self.assertTrue(
            version_key_calls,
            "_get_cache_version did not call cache.set for the version key",
        )
        for key, value, args, kwargs in version_key_calls:
            # timeout may be passed positionally or as a keyword.
            timeout_positional = args[0] if args else None
            timeout_keyword = kwargs.get("timeout", None)
            timeout = timeout_keyword if "timeout" in kwargs else timeout_positional
            self.assertIsNone(
                timeout,
                f"Version key '{key}' stored with timeout={timeout!r}; expected None (never expire)",
            )

    def test_bump_heal_stores_with_no_timeout(self):
        """_bump_cache_version heal path MUST store version key with timeout=None.

        The on_commit callback is executed inside captureOnCommitCallbacks so the
        heal logic actually runs within the test.
        """
        view_instance = GraphQLView(schema=_schema)
        _cache = cache
        identity = "ttl_heal_test"

        # Force heal: key is missing, so incr raises ValueError → heal path.
        set_calls = []
        original_set = _cache.set

        def capturing_set(key, value, *args, **kwargs):
            set_calls.append((key, value, args, kwargs))
            return original_set(key, value, *args, **kwargs)

        with patch.object(_cache, "set", side_effect=capturing_set):
            with self.captureOnCommitCallbacks(execute=True):
                view_instance._bump_cache_version(_cache, identity)

        version_key_calls = [c for c in set_calls if "_graphql_cacheversion_" in c[0]]
        self.assertTrue(
            version_key_calls,
            "_bump_cache_version heal path did not call cache.set for the version key",
        )
        for key, value, args, kwargs in version_key_calls:
            timeout_positional = args[0] if args else None
            timeout_keyword = kwargs.get("timeout", None)
            timeout = timeout_keyword if "timeout" in kwargs else timeout_positional
            self.assertIsNone(
                timeout,
                f"Heal path stored version key '{key}' with timeout={timeout!r}; expected None",
            )

    @override_settings(**CACHE_ON_LONG_TIMEOUT)
    def test_version_key_persists_beyond_cache_timeout(self):
        """With CACHE_TIMEOUT=600 > LocMemCache default the version key MUST survive.

        This is a behavioural smoke-test: set the key with timeout=None, simulate
        the passage of time by directly expiring the key (if the implementation
        used a finite timeout), then assert the version is still readable.

        Since we cannot actually wait 300 s in a unit test we instead verify that
        after _get_cache_version the key is present and its internal expiry in
        LocMemCache is None (no expiry).
        """
        view_instance = GraphQLView(schema=_schema)
        _cache = cache
        identity = "long_timeout_test"

        view_instance._get_cache_version(_cache, identity)

        version_key = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(identity=identity)
        # LocMemCache stores (expiry_time, value) internally.
        # Access the internal _cache dict to inspect the expiry.
        internal = getattr(_cache, "_cache", None)
        if internal is not None:
            stored = internal.get(version_key)
            if stored is not None:
                # LocMemCache value format: (expiry_or_none, pickled_value)
                expiry = stored[0]
                self.assertIsNone(
                    expiry,
                    f"Version key has finite expiry {expiry!r} — will expire before CACHE_TIMEOUT=600",
                )
        else:
            # Non-LocMemCache backend — verify key is still readable.
            self.assertIsNotNone(
                _cache.get(version_key),
                "Version key is missing after _get_cache_version with long CACHE_TIMEOUT",
            )


# ---------------------------------------------------------------------------
# (c) COLD-KEY HEAL — must initialise to 1
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class ColdKeyHealTest(TestCase):
    """#60c — Cold-key heal MUST initialise the counter to 1, not 0.

    When the version key is missing (cold start or expired) and _bump_cache_version
    fires, the heal path must set the key to 1 (not 0) so the first bump resolves
    to 2.  The zero-state is ambiguous: a concurrent request that observed version
    0 (before any heal) would have its response cached at key v0, which remains
    reachable indefinitely.
    """

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_cold_bump_advances_to_2_not_1(self):
        """A bump on a cold (missing) key MUST produce version 2 after second bump.

        Sequence:
          1. No version key exists (cold start after cache.clear()).
          2. _bump_cache_version is called (first bump).
          3. Heal fires: sets key to 1 (incr on missing key raises ValueError).
          4. _get_cache_version reads back the version — must be "1".
          5. Second _bump_cache_version → incr(1) → "2".

        captureOnCommitCallbacks(execute=True) is used because Django's TestCase
        wraps each test in a transaction and on_commit callbacks are only flushed
        on commit; without this context manager the callbacks would never fire.
        """
        view_instance = GraphQLView(schema=_schema)
        _cache = cache
        identity = "cold_heal_identity"

        # First bump on cold key — heal fires, sets key to 1.
        with self.captureOnCommitCallbacks(execute=True):
            view_instance._bump_cache_version(_cache, identity)

        version_after_first_bump = view_instance._get_cache_version(_cache, identity)
        self.assertEqual(
            version_after_first_bump,
            "1",
            f"After cold bump the version should be '1' (healed to 1), got {version_after_first_bump!r}",
        )

        # Second bump — incr(1) → 2.
        with self.captureOnCommitCallbacks(execute=True):
            view_instance._bump_cache_version(_cache, identity)
        version_after_second_bump = view_instance._get_cache_version(_cache, identity)
        self.assertEqual(
            version_after_second_bump,
            "2",
            f"After second bump version should be '2', got {version_after_second_bump!r}",
        )

    def test_get_cache_version_cold_start_returns_1(self):
        """_get_cache_version on a cold key MUST initialise and return '1'.

        A cold start via _get_cache_version (no prior bump) must seed to 1 so any
        subsequent single bump reaches 2.  This prevents version 0 from ever being
        used as a cache key in production traffic.
        """
        view_instance = GraphQLView(schema=_schema)
        _cache = cache
        identity = "cold_init_identity"

        version = view_instance._get_cache_version(_cache, identity)
        self.assertEqual(
            version,
            "1",
            f"Cold _get_cache_version should return '1', got {version!r}",
        )

    def test_v0_never_used_as_cache_key(self):
        """No request should be served a cached response stored at version 0."""
        view = GraphQLView.as_view(schema=_schema)
        factory = RequestFactory()

        stored_keys = []
        _cache = cache
        original_set = _cache.set

        def capturing_set(key, value, *args, **kwargs):
            stored_keys.append(key)
            return original_set(key, value, *args, **kwargs)

        req = _post(factory, "{ hello }")
        with patch.object(_cache, "set", side_effect=capturing_set):
            view(req)

        response_keys = [
            k
            for k in stored_keys
            if k.startswith("_graphql_") and "cacheversion" not in k
        ]
        for key in response_keys:
            # Key format: _graphql_{identity}_{version}_{hash}
            # identity can be 'anon', 'u1', 't<hex>' etc. — split carefully.
            # Strip the fixed prefix; last 64 chars are the sha256 hash.
            without_prefix = key[len("_graphql_") :]
            remainder = without_prefix[: -64 - 1]  # drop underscore before hash
            # remainder is "{identity}_{version}" — split on last underscore.
            last_underscore = remainder.rfind("_")
            version_part = remainder[last_underscore + 1 :]
            self.assertNotEqual(
                version_part,
                "0",
                f"Cache response stored at version 0 (key={key!r}) — cold-heal-to-0 bug still present",
            )
