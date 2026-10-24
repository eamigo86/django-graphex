"""Concurrency contracts for permission-scoped schema cache lookups."""

from __future__ import annotations

import threading

import pytest
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

from django_graphex.core.permission_signature_cache import _SignatureSchemaCache


class _User:
    """Supply immutable live grants to the cache without a Django database."""

    def __init__(self, grants: set[str]) -> None:
        self.grants = grants
        self.is_active = True
        self.is_superuser = False

    def get_all_permissions(self) -> set[str]:
        """Return this request's grants.

        Returns:
            A copy of the user's permission codenames.
        """
        return set(self.grants)


def _schema() -> GraphQLSchema:
    """Build one labeled schema with three distinct permission signatures.

    Returns:
        A source schema with three distinct permission labels.
    """
    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"field": GraphQLField(GraphQLString)}),
        extensions={"gdx_label_set": frozenset({"app.a", "app.b", "app.c"})},
    )


def _join_all(threads: list[threading.Thread]) -> None:
    """Await owned workers and reject any thread left alive."""
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)


def test_warm_hit_completes_before_unrelated_cold_prune_is_released() -> None:
    """Let a warm cache hit complete during an unrelated cold prune.

    The blocked build for one signature must not hold up another cached key.

    Raises:
        TimeoutError: The cold prune was not released within the allotted time.
    """
    cache = _SignatureSchemaCache()
    full = _schema()
    user_a, user_b = _User({"app.a"}), _User({"app.b"})
    cached_b = cache.pruned_schema_for(user_b, full, prune=lambda schema, _: schema)
    pruning_a = threading.Event()
    release_a = threading.Event()
    b_entered_get = threading.Event()
    b_done = threading.Event()
    errors: list[BaseException] = []
    results: list[GraphQLSchema] = []
    original_get = cache._get

    def observed_get(
        key: tuple[int, str], schema: GraphQLSchema
    ) -> GraphQLSchema | None:
        if threading.current_thread() is worker_b:
            b_entered_get.set()
        return original_get(key, schema)

    cache._get = observed_get

    def block_a(schema: GraphQLSchema, _grants: frozenset[str]) -> GraphQLSchema:
        pruning_a.set()
        if not release_a.wait(timeout=5):
            raise TimeoutError("the cold prune was not released")
        return schema

    def run_a() -> None:
        try:
            cache.pruned_schema_for(user_a, full, prune=block_a)
        except BaseException as error:
            errors.append(error)

    def run_b() -> None:
        try:
            results.append(cache.pruned_schema_for(user_b, full))
        except BaseException as error:
            errors.append(error)
        finally:
            b_done.set()

    worker_a = threading.Thread(target=run_a)
    worker_b = threading.Thread(target=run_b)
    threads = [worker_a]
    worker_a.start()
    try:
        assert pruning_a.wait(timeout=5), "cold prune A did not start"
        threads.append(worker_b)
        worker_b.start()
        assert b_entered_get.wait(timeout=5), "warm lookup B did not enter _get"
        completed_before_release = b_done.wait(timeout=2)
    finally:
        release_a.set()
        _join_all(threads)

    assert completed_before_release, "warm B waited on unrelated cold prune A"
    assert errors == []
    assert results == [cached_b]
    assert results[0] is cached_b


def test_cold_builds_remain_serial_and_same_key_is_shared() -> None:
    """Serialize cold prunes and share a build for the same key.

    Distinct signatures cannot enter their pruning callbacks together.

    Raises:
        TimeoutError: The first cold prune was not released within the allotted time.
    """
    cache = _SignatureSchemaCache()
    full = _schema()
    user_a, user_c = _User({"app.a"}), _User({"app.c"})
    entered_a = threading.Event()
    release_a = threading.Event()
    active = 0
    peak = 0
    builds: list[frozenset[str]] = []
    results: list[GraphQLSchema] = []
    errors: list[BaseException] = []
    count_lock = threading.Lock()
    pruning_c = threading.Event()

    def prune(schema: GraphQLSchema, grants: frozenset[str]) -> GraphQLSchema:
        nonlocal active, peak
        with count_lock:
            active += 1
            peak = max(peak, active)
            builds.append(grants)
        try:
            if grants == frozenset({"app.a"}):
                entered_a.set()
                if not release_a.wait(timeout=5):
                    raise TimeoutError("cold prune A was not released")
            if grants == frozenset({"app.c"}):
                pruning_c.set()
            return schema
        finally:
            with count_lock:
                active -= 1

    def run(user: _User) -> None:
        try:
            results.append(cache.pruned_schema_for(user, full, prune=prune))
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=run, args=(user_a,))
    same = threading.Thread(target=run, args=(user_a,))
    other = threading.Thread(target=run, args=(user_c,))
    threads = [first]
    first.start()
    try:
        assert entered_a.wait(timeout=5)
        for thread in (same, other):
            threads.append(thread)
            thread.start()
        cold_c_entered_before_release = pruning_c.wait(timeout=0.2)
    finally:
        release_a.set()
        _join_all(threads)

    assert errors == []
    assert not cold_c_entered_before_release
    assert peak == 1
    assert builds.count(frozenset({"app.a"})) == 1
    assert builds.count(frozenset({"app.c"})) == 1
    assert len(results) == 3
    assert all(result is full for result in results)


def test_clear_waits_for_build_then_removes_entry() -> None:
    """Make cache clearing wait for an active build.

    No completed entry should survive the ordered clear operation.

    Raises:
        TimeoutError: The build was not released within the allotted time.
    """
    cache = _SignatureSchemaCache()
    full = _schema()
    entered_build = threading.Event()
    release_build = threading.Event()
    entered_clear = threading.Event()
    clear_done = threading.Event()
    errors: list[BaseException] = []

    def prune(schema: GraphQLSchema, _grants: frozenset[str]) -> GraphQLSchema:
        entered_build.set()
        if not release_build.wait(timeout=5):
            raise TimeoutError("build was not released")
        return schema

    def build() -> None:
        try:
            cache.pruned_schema_for(_User({"app.a"}), full, prune=prune)
        except BaseException as error:
            errors.append(error)

    def clear() -> None:
        entered_clear.set()
        cache.clear()
        clear_done.set()

    builder = threading.Thread(target=build)
    clearer = threading.Thread(target=clear)
    threads = [builder]
    builder.start()
    try:
        assert entered_build.wait(timeout=5)
        threads.append(clearer)
        clearer.start()
        assert entered_clear.wait(timeout=5)
        cleared_before_release = clear_done.wait(timeout=0.2)
    finally:
        release_build.set()
        _join_all(threads)

    assert not cleared_before_release
    assert clear_done.is_set()
    assert errors == []
    assert len(cache) == 0


def test_reentrant_clear_and_failed_prune_leave_cache_recoverable() -> None:
    """Keep the cache usable after reentrant clear and failed pruning.

    A failed build must not publish an entry before a later successful retry.

    Raises:
        ValueError: Raised by the patched prune to simulate a failed build.
    """
    cache = _SignatureSchemaCache()
    full = _schema()
    user = _User({"app.a"})

    def fail(_schema: GraphQLSchema, _grants: frozenset[str]) -> GraphQLSchema:
        cache.clear()
        raise ValueError("prune failed")

    with pytest.raises(ValueError, match="prune failed"):
        cache.pruned_schema_for(user, full, prune=fail)
    assert len(cache) == 0
    assert cache.pruned_schema_for(user, full, prune=lambda schema, _: schema) is full
    assert len(cache) == 1
