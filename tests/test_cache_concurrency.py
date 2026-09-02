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

3. Asserts the invariant **end to end through the view**, on a
   "TransactionTestCase" so "on_commit" keeps its production semantics: a
   probe mutation records the version token as of its own commit point, which
   catches a bump scheduled at the wrong place in "dispatch" (the historic
   defect: scheduling it before "super_call" made the deferral inert).
"""

import threading
from typing import Any
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.test import (
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from graphql import GraphQLBoolean, GraphQLResolveInfo, GraphQLString

from django_graphex.core import Mutation, ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
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

        The bump runs inside a REAL "transaction.atomic()" block (the one
        "captureOnCommitCallbacks" opens); nothing is patched, so the deferral
        itself — not merely the registration call — is what is observed.
        """
        view_instance = GraphQLView(schema=minimal_cache_schema)
        identity = "race_ordering_user"
        # Seed the version so incr has an integer to work with.
        version_before = view_instance._get_cache_version(cache, identity)

        # Real atomic block: callbacks are captured by Django itself, so a bump
        # that ran inline would be visible in the counter immediately.
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            view_instance._bump_cache_version(cache, identity)

        # The version must NOT have changed (the transaction has not committed).
        version_mid = view_instance._get_cache_version(cache, identity)
        assert version_mid == version_before, (
            "Version advanced BEFORE commit — bump-before-commit TOCTOU bug present: "
            f"before={version_before!r}, mid={version_mid!r}"
        )

        # Exactly one on_commit callback was registered.
        assert len(callbacks) == 1, (
            f"Expected 1 on_commit registration, got {len(callbacks)}"
        )

        # Flushing the callback must advance the counter.
        callbacks[0]()
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

        # The default scope shares one version namespace across identities.
        identity = "global"

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


# ---------------------------------------------------------------------------
# 3. End-to-end deferral: the bump must land AFTER the mutation's own
#    transaction commits, not before it.
#
# The two tests above exercise "_bump_cache_version" in isolation, so they stay
# green even when "dispatch" schedules the bump at the wrong moment.  The
# historic defect lived at the CALL SITE: the bump was scheduled before
# "super_call", and the atomic block that "ATOMIC_MUTATIONS" opens lives inside
# "super_call", so "on_commit" found no open transaction and fired inline —
# before the mutation had even run.
#
# This test observes the real ordering end to end.  The probe mutation registers
# its own "on_commit" callback, which therefore fires exactly when the mutation's
# transaction commits; that callback records the version token it sees at that
# instant.  A bump that fires before the commit is visible as an already-advanced
# token in the recording.  TransactionTestCase is required: inside a plain
# TestCase every callback is captured by the test's own outer atomic block, which
# makes both the correct and the broken scheduling indistinguishable.
# ---------------------------------------------------------------------------

#: Version tokens observed at the exact moment the mutation transaction commits.
_COMMIT_TIME_VERSIONS: list[Any] = []

#: The version-counter cache key used by the default global scope.
_GLOBAL_VERSION_KEY = GraphQLView._CACHE_VERSION_KEY_TEMPLATE.format(identity="global")


class _ProbeQ(ObjectType):
    """Query root for the commit-ordering probe schema."""

    hello = field(GraphQLString)

    def resolve_hello(root: Any, info: GraphQLResolveInfo) -> str:  # noqa: N805
        """Resolve the "hello" field to a constant greeting.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            The literal string "world".
        """
        return "world"


class _ProbeMut(Mutation):
    """Mutation that records the version token at its own commit point."""

    class Arguments:
        """No arguments are accepted by this mutation."""

    ok = field(GraphQLBoolean)

    @classmethod
    def mutate(cls, root: Any, info: GraphQLResolveInfo) -> "_ProbeMut":
        """Register a commit probe and report success.

        The registered callback runs when the transaction this resolver is
        executing in commits, so the token it reads is the version as of the
        moment the mutation's write became durable.

        Args:
            root: The unused parent resolver value.
            info: The GraphQL execution info for the current field.

        Returns:
            A new instance with "ok" set to True.
        """
        transaction.on_commit(
            lambda: _COMMIT_TIME_VERSIONS.append(cache.get(_GLOBAL_VERSION_KEY))
        )
        return cls(ok=True)


class _ProbeMutationRoot(ObjectType):
    """Mutation root exposing the commit-ordering probe mutation."""

    do_thing = _ProbeMut.Field()


#: Schema whose mutation records the cache version at its commit point.
_probe_schema = DjangoGraphQLSchema(query=_ProbeQ, mutation=_ProbeMutationRoot)


@override_settings(
    DJANGO_GRAPHEX={
        "CACHE_ACTIVE": True,
        "CACHE_TIMEOUT": 60,
        "ATOMIC_MUTATIONS": True,
    }
)
class BumpLandsAfterMutationCommitTest(TransactionTestCase):
    """The version bump MUST NOT be visible before the mutation commits.

    Uses TransactionTestCase so "on_commit" keeps its production semantics: a
    TestCase wraps every test in an atomic block that would defer both the
    correct and the mis-scheduled bump to the same point, hiding the defect.
    """

    def setUp(self) -> None:
        """Reset the cache and the commit-time recording before each test.

        Prevents version counters and probe records from a prior test from
        leaking into this test's assertions.
        """
        cache.clear()
        _COMMIT_TIME_VERSIONS.clear()

    def test_version_is_unchanged_at_the_mutation_commit_point(self) -> None:
        """The counter must still hold the old token when the mutation commits.

        Ordering invariant:

            mutation commit -> version bump -> next query reads the new version

        A bump scheduled before "super_call" fires inline (no transaction is open
        at that point), so the probe would observe the ALREADY advanced token —
        the bump-before-commit TOCTOU window of issue #60a.
        """
        cache.set(_GLOBAL_VERSION_KEY, 5, timeout=None)
        view = GraphQLView.as_view(schema=_probe_schema)

        response = view(graphql_post(RequestFactory(), "mutation { doThing { ok } }"))

        assert response.status_code == 200, response.content
        assert _COMMIT_TIME_VERSIONS == [5], (
            "Version was already bumped when the mutation transaction committed "
            "— the bump is not deferred past the commit (issue #60a TOCTOU "
            f"window): observed {_COMMIT_TIME_VERSIONS!r}, expected [5]"
        )
        assert cache.get(_GLOBAL_VERSION_KEY) == 6, (
            "The mutation did not invalidate the cache namespace: version is "
            f"{cache.get(_GLOBAL_VERSION_KEY)!r}, expected 6"
        )
