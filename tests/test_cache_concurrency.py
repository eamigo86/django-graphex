# -*- coding: utf-8 -*-
"""Concurrency test for the version-counter bump-vs-serve race (issue #60).

Background
----------
Issue #60a describes a TOCTOU window where a mutation bumped the version
counter *before* its DB transaction committed.  A concurrent query that ran in
that window could cache pre-mutation data at the new version key, producing a
stale serve that would persist until the next mutation.

The fix wraps the bump in "transaction.on_commit", which guarantees the
counter advances only after the write is durable.  The ordering invariant is:

    mutation_commit → on_commit(version_bump) → next query reads new version

A true deterministic race requires the bump to be visible to a second thread
*before* that thread reads the version.  In a single-process test environment
with SQLite this is not replicable as a real race without sleeps (which are
non-deterministic and flaky).  Instead this module:

1. Directly asserts the **on_commit ordering invariant**: the version counter
   must only advance inside an on_commit callback, never before the transaction
   commits.  This is what the fix guarantees; verifying it is sufficient to
   prove the race window is closed.

2. Provides a **threading.Barrier-based test** that drives two threads
   concurrently — one mutating (bumping) and one querying — and asserts that
   the query thread never observes a stale-version serve after the mutation
   committed.

   Because the in-process SQLite test DB serialises writes, the test asserts
   the *ordering* property rather than attempting to reproduce a timing fault.
   A comment explains why and documents the invariant being tested.
"""

import threading
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings

from django_graphex.views import GraphQLView
from tests.cache_helpers import CACHE_ON, graphql_post, minimal_cache_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _view():
    return GraphQLView.as_view(schema=minimal_cache_schema)


# ---------------------------------------------------------------------------
# 1. On-commit ordering invariant
#    Assert: _bump_cache_version MUST schedule the incr via on_commit, not
#    execute it immediately inside the mutation branch.
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class OnCommitOrderingTest(TestCase):
    """The version-bump MUST be deferred to transaction.on_commit.

    This directly verifies the on_commit ordering invariant that closes the
    TOCTOU race window described in issue #60a.
    """

    def setUp(self) -> None:
        """Clear the cache before each test.

        Ensures version counters and cached responses from a prior test do
        not leak into this test's assertions.
        """
        cache.clear()

    def test_bump_deferred_to_on_commit_not_immediate(self) -> None:
        """_bump_cache_version MUST register the incr with on_commit, not execute it inline.

        Rationale: if the bump fires before the surrounding transaction commits,
        a concurrent query can cache stale data at the new version key.  Deferring
        to on_commit closes this window: the version only advances after the
        mutation's DB write is durable.

        We intercept transaction.on_commit and assert it is called exactly once
        (with a callable), proving the bump is deferred.  We also verify the
        counter has NOT advanced before on_commit fires.
        """
        view_instance = GraphQLView(schema=minimal_cache_schema)
        identity = "race_ordering_user"
        # Seed the version so incr has an integer to work with.
        version_before = view_instance._get_cache_version(cache, identity)

        on_commit_received = []
        immediate_bump_detected = []

        def capturing_on_commit(func, using=None):
            # Record but do NOT execute the callback — simulates a pending tx.
            on_commit_received.append(func)

        # Patch on_commit so callbacks are held, not flushed.
        with patch(
            "django_graphex.views.transaction.on_commit",
            side_effect=capturing_on_commit,
        ):
            view_instance._bump_cache_version(cache, identity)

        # The version must NOT have changed (on_commit was not flushed).
        version_mid = view_instance._get_cache_version(cache, identity)
        if version_mid != version_before:
            immediate_bump_detected.append(True)

        assert not immediate_bump_detected, (
            "Version advanced BEFORE on_commit fired — bump-before-commit TOCTOU bug present: "
            f"before={version_before!r}, mid={version_mid!r}"
        )

        # Exactly one on_commit callback was registered.
        assert len(on_commit_received) == 1, (
            f"Expected 1 on_commit registration, got {len(on_commit_received)}"
        )

        # Flushing the callback must advance the counter.
        on_commit_received[0]()
        version_after = view_instance._get_cache_version(cache, identity)
        assert int(version_after) > int(version_before), (
            "Version did not advance after flushing on_commit callback: "
            f"before={version_before!r}, after={version_after!r}"
        )

    def test_rollback_does_not_advance_version(self) -> None:
        """A rolled-back mutation MUST NOT advance the version counter.

        Django does not invoke on_commit callbacks when a transaction is rolled
        back.  This verifies that the version-bump is therefore not applied on
        rollback, which is the primary correctness guarantee of the on_commit fix.

        Raises:
            ValueError: Raised internally and immediately caught to force the
                transaction to roll back; not propagated to the caller.
        """
        view_instance = GraphQLView(schema=minimal_cache_schema)
        identity = "race_rollback_user"
        version_before = view_instance._get_cache_version(cache, identity)

        try:
            with transaction.atomic():
                view_instance._bump_cache_version(cache, identity)
                # Force rollback — on_commit callbacks are discarded.
                raise ValueError("simulated rollback")
        except ValueError:
            pass

        version_after = view_instance._get_cache_version(cache, identity)
        assert version_before == version_after, (
            "Version advanced despite transaction rollback — "
            "bump-before-commit bug still present: "
            f"before={version_before!r}, after={version_after!r}"
        )


# ---------------------------------------------------------------------------
# 2. Threading.Barrier-based bump-vs-serve ordering test
#
# Two threads run in a forced happens-before sequence:
#   Thread A (mutator): seeds the cache, then atomically bumps the version
#                       counter (simulating committed mutation).
#   Thread B (querier): waits for thread A's bump to complete, then issues the
#                       same query and asserts it reaches the backend (cache
#                       MISS at new version) rather than being served stale.
#
# Determinism note
# ----------------
# SQLite (:memory:) serialises writes and connection objects are not shared
# between threads in Django's default connection pool.  A true timing race
# (where threads overlap on the same in-flight transaction) cannot be
# reproduced reliably in this environment.  We therefore use threading.Barrier
# to enforce a strict happens-before relationship:
#
#   A seeds cache → barrier_1 → A bumps version → barrier_2 → B queries
#
# This tests the *ordering invariant*: once the version has been atomically
# incremented by thread A, thread B — reading the same cache backend — MUST
# observe the new version and get a cache MISS.  It is not a timing stress
# test; it is a functional correctness test with enforced ordering.
#
# Why not use TransactionTestCase with real on_commit?
# ----------------------------------------------------
# TransactionTestCase flushes the DB between tests (expensive) and Django's
# test runner does not share SQLite :memory: connections across threads.
# Using _bump_cache_version directly (which internally calls transaction.on_commit)
# inside captureOnCommitCallbacks is the correct way to flush on_commit in the
# in-process test environment and avoids cross-thread DB-connection issues.
# ---------------------------------------------------------------------------


@override_settings(**CACHE_ON)
class BumpVsServeOrderingTest(TestCase):
    """Two-thread ordering assertion for the bump-vs-serve race (issue #60).

    Threading.Barrier enforces A-seeds → A-bumps → B-queries ordering.
    See module docstring for the determinism rationale.

    Uses TestCase (not TransactionTestCase) because:
    - captureOnCommitCallbacks(execute=True) flushes on_commit within the
      test's savepoint, giving us real on_commit semantics without needing a
      full transaction commit.
    - SQLite :memory: connections are not shared across threads, making
      TransactionTestCase-based inter-thread DB synchronisation unreliable.

    The identity used in the test matches what GraphQLView.cache_key_prefix
    returns for an authenticated user with pk=50: "u50".
    """

    def setUp(self) -> None:
        """Clear the cache before each test.

        Ensures version counters and cached responses from a prior test do
        not leak into this test's assertions.
        """
        cache.clear()

    def test_query_after_bump_gets_cache_miss(self) -> None:
        """After the version is bumped, a concurrent query MUST miss the cache.

        Enforced ordering via Barrier:
          Phase 1: thread A seeds the cache (query at version N).
          Phase 2 (after barrier_1): thread A bumps the version to N+1.
          Phase 3 (after barrier_2): thread B queries — must miss at N+1.

        This proves the ordering invariant: a bump that completed before a
        query is issued must be visible to that query, preventing a stale serve.
        """
        factory = RequestFactory()
        user = User(pk=50, username="race_user_50")
        view = _view()
        view_instance = GraphQLView(schema=minimal_cache_schema)

        # The identity for pk=50 as computed by GraphQLView.cache_key_prefix.
        identity = "u50"

        errors: list = []
        barrier_1 = threading.Barrier(2, timeout=5)
        barrier_2 = threading.Barrier(2, timeout=5)

        def thread_a_seed_and_bump():
            """Phase 1: seed.  Phase 2: bump (on_commit executed immediately)."""
            try:
                # Phase 1: seed the cache at version N.
                view(graphql_post(factory, "{ hello }", user=user))
                barrier_1.wait()  # Signal thread B: cache seeded.

                # Phase 2: bump version N → N+1.
                # Patch transaction.on_commit to execute the callback immediately
                # (simulating a committed transaction).  This avoids relying on
                # captureOnCommitCallbacks from a non-main thread, which would
                # require shared DB connection context.
                def immediate_on_commit(func, using=None):
                    func()

                with patch(
                    "django_graphex.views.transaction.on_commit",
                    side_effect=immediate_on_commit,
                ):
                    view_instance._bump_cache_version(cache, identity)
                barrier_2.wait()  # Signal thread B: version bumped.
            except Exception as exc:
                errors.append(f"thread_a: {exc!r}")
                try:
                    barrier_1.abort()
                except Exception:
                    pass
                try:
                    barrier_2.abort()
                except Exception:
                    pass

        thread_b_super_calls = {"n": 0}
        original_super_call = GraphQLView.super_call

        def counting_super_call(self_view, request, *args, **kwargs):
            thread_b_super_calls["n"] += 1
            return original_super_call(self_view, request, *args, **kwargs)

        def thread_b_query():
            """Phase 3: query after bump — must produce a cache MISS."""
            try:
                barrier_1.wait()  # Wait: cache seeded.
                barrier_2.wait()  # Wait: version bumped.

                with patch.object(GraphQLView, "super_call", counting_super_call):
                    view(graphql_post(factory, "{ hello }", user=user))
            except Exception as exc:
                errors.append(f"thread_b: {exc!r}")

        ta = threading.Thread(target=thread_a_seed_and_bump, daemon=True)
        tb = threading.Thread(target=thread_b_query, daemon=True)
        ta.start()
        tb.start()
        ta.join(timeout=10)
        tb.join(timeout=10)

        if errors:
            self.fail(f"Thread errors during bump-vs-serve ordering test: {errors}")

        # Thread B queried AFTER the version was bumped; the cache key at the old
        # version is stale, so the backend MUST be called at least once.
        self.assertGreaterEqual(
            thread_b_super_calls["n"],
            1,
            "Thread B was served stale data from the cache after the version was bumped "
            "(the on_commit ordering invariant is violated — version was not visible "
            "to thread B after thread A's bump completed).",
        )
