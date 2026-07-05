# -*- coding: utf-8 -*-
"""Signature + LRU cache tests (P2): "core.permission_signature_cache".

The module derives a stable "permission signature" — a projection of a user's
live permissions onto the schema's label-set — and maintains an in-process,
lazy, thread-safe, bounded LRU mapping signature -> pruned GraphQLSchema.

Coverage:
- "permission_signature(perms, label_set)" == sha256(sorted(perms & label_set))
  hex digest; perms outside the label-set collapse to the SAME signature;
  revoking a relevant perm yields a DIFFERENT signature.
- "pruned_schema_for(user, full)":
  - active superuser -> the FULL schema, WITHOUT computing a signature
  - same signature -> the pruned schema is built ONCE (second call is a hit)
  - bounded LRU never exceeds "PERMISSION_SCHEMA_CACHE_MAXSIZE" (LRU eviction)
  - N concurrent first-requests for one signature -> one shared instance, no race
"""

from __future__ import annotations

import threading
import time
from hashlib import sha256
from typing import Any

from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

from django_graphex.core import permission_signature_cache as psc

# --------------------------------------------------------------------------- #
# Perm codenames + a tiny labeled schema whose "secret" field is perm-gated.
# --------------------------------------------------------------------------- #
_VIEW_PUB = "app.view_pub"
_VIEW_SECRET = "app.view_secret"
_LABEL_SET = frozenset({_VIEW_PUB, _VIEW_SECRET})


def _labeled(gql_field: GraphQLField, perms: frozenset[str]) -> GraphQLField:
    """Stamp a "gdx_required_perms" extension onto a field, in place.

    Args:
        gql_field: The field to annotate.
        perms: The permission codenames required to read this field.

    Returns:
        gql_field: The same field instance, for chaining at the call site.
    """
    gql_field.extensions = {
        **(gql_field.extensions or {}),
        "gdx_required_perms": perms,
    }
    return gql_field


def _full_schema() -> GraphQLSchema:
    """Build a tiny labeled schema with one public and one perm-gated field.

    Returns:
        schema: A "GraphQLSchema" whose "gdx_label_set" extension is
            "_LABEL_SET" and whose "secret" field requires "_VIEW_SECRET".
    """
    query = GraphQLObjectType(
        "Query",
        {
            "public": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_PUB})),
            "secret": _labeled(GraphQLField(GraphQLString), frozenset({_VIEW_SECRET})),
        },
    )
    return GraphQLSchema(query=query, extensions={"gdx_label_set": _LABEL_SET})


class _FakeUser:
    """Minimal duck-typed user: superuser flag + a fixed permission set."""

    def __init__(
        self,
        perms: object,
        *,
        is_superuser: bool = False,
        is_active: bool = True,
    ) -> None:
        """Store the fixed permission set and superuser/active flags.

        Args:
            perms: An iterable of permission codenames this user holds.
            is_superuser: Whether the user reports as a Django superuser.
            is_active: Whether the user reports as an active account.
        """
        self._perms = set(perms)
        self.is_superuser = is_superuser
        self.is_active = is_active

    def get_all_permissions(self) -> set[str]:
        """Return a fresh copy of this user's fixed permission set.

        Returns:
            perms: The permission codenames this fake user holds.
        """
        return set(self._perms)


# --------------------------------------------------------------------------- #
# Task 2.1 — permission_signature
# --------------------------------------------------------------------------- #
def test_signature_is_sha256_of_sorted_relevant_perms() -> None:
    """Assert the signature is the sha256 hexdigest of the sorted relevant perms.

    If this fails, the permission signature would no longer be a stable,
    reproducible hash of the granted permissions.
    """
    perms = frozenset({_VIEW_PUB, _VIEW_SECRET})
    expected = sha256("\n".join(sorted(perms)).encode()).hexdigest()
    assert psc.permission_signature(perms, _LABEL_SET) == expected


def test_irrelevant_perms_collapse_to_same_signature() -> None:
    """Assert perms outside the label-set do not change the signature.

    If this fails, unrelated permission changes on a user would needlessly
    invalidate their cached pruned schema.
    """
    base = frozenset({_VIEW_PUB})
    with_noise = frozenset({_VIEW_PUB, "other.unrelated_perm", "x.y_z"})
    assert psc.permission_signature(base, _LABEL_SET) == psc.permission_signature(
        with_noise, _LABEL_SET
    )


def test_revoking_a_relevant_perm_changes_the_signature() -> None:
    """Assert dropping a label-set perm yields a new, distinct signature.

    If this fails, revoking a permission that gates schema fields would not
    invalidate the stale cached pruned schema, leaking access.
    """
    full = frozenset({_VIEW_PUB, _VIEW_SECRET})
    revoked = frozenset({_VIEW_PUB})
    assert psc.permission_signature(full, _LABEL_SET) != psc.permission_signature(
        revoked, _LABEL_SET
    )


def test_empty_relevant_perms_signature_is_stable() -> None:
    """Assert a user with no relevant perms still gets a well-defined signature.

    If this fails, a permission-less user could not be signed and cached,
    breaking the pruning path for the least-privileged callers.
    """
    empty = psc.permission_signature(frozenset(), _LABEL_SET)
    assert empty == sha256(b"").hexdigest()


# --------------------------------------------------------------------------- #
# Task 2.2 / 2.3 — pruned_schema_for: superuser bypass, LRU hit, eviction, races
# --------------------------------------------------------------------------- #
def _fresh_cache() -> psc._SignatureSchemaCache:
    """Build a brand-new, empty signature/schema cache for test isolation.

    Returns:
        cache: A fresh "_SignatureSchemaCache" instance.
    """
    return psc._SignatureSchemaCache()


def test_superuser_gets_full_schema_without_signature() -> None:
    """Assert an active superuser receives the FULL schema and no prune runs.

    If this fails, superusers would either see a pruned schema (missing
    fields they are entitled to) or would trigger unnecessary pruning work.
    """
    full = _full_schema()
    calls: list[frozenset] = []

    def spy_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        calls.append(granted)
        return schema  # identity clone stand-in

    cache = _fresh_cache()
    root = _FakeUser([], is_superuser=True, is_active=True)
    result = cache.pruned_schema_for(root, full, prune=spy_prune)
    assert result is full
    assert calls == []  # signature/prune never computed for a superuser


def test_inactive_superuser_is_pruned_like_a_normal_user() -> None:
    """Assert an INACTIVE superuser does NOT get the full-schema bypass.

    If this fails, a deactivated superuser account would still see the
    unpruned full schema instead of being treated like any other user.
    """
    full = _full_schema()
    cache = _fresh_cache()
    built: list[frozenset] = []

    def spy_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        built.append(granted)
        return GraphQLSchema(
            query=GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)})
        )

    user = _FakeUser({_VIEW_PUB}, is_superuser=True, is_active=False)
    result = cache.pruned_schema_for(user, full, prune=spy_prune)
    assert result is not full
    assert built == [frozenset({_VIEW_PUB})]


def test_same_signature_builds_once_and_hits_cache() -> None:
    """Assert two users with identical relevant perms share ONE built schema.

    If this fails, the LRU cache would rebuild a pruned schema per user
    instead of reusing it for every user sharing the same signature.
    """
    full = _full_schema()
    cache = _fresh_cache()
    build_count = {"n": 0}

    def counting_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        build_count["n"] += 1
        return GraphQLSchema(
            query=GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)})
        )

    user_a = _FakeUser({_VIEW_PUB})
    user_b = _FakeUser({_VIEW_PUB, "other.unrelated"})  # same relevant perms
    first = cache.pruned_schema_for(user_a, full, prune=counting_prune)
    second = cache.pruned_schema_for(user_b, full, prune=counting_prune)
    assert first is second  # identical instance served from the cache
    assert build_count["n"] == 1  # built exactly once


def test_distinct_full_schemas_never_share_a_signature_entry() -> None:
    """Assert the cache is keyed by (full schema, signature), not signature alone.

    Two DIFFERENT "full" schemas can share a permission signature — most
    starkly for a permission-less user, whose relevant-perm projection is empty
    for every schema, so the signature is sha256 of the empty string regardless
    of which schema is passed. If the cache keyed on signature ONLY, the second
    schema's request would hit the FIRST schema's cached pruned variant and
    silently serve the wrong (stale) schema — a correctness bug for any
    deployment that routes more than one schema through "pruned_schema_for"
    (multi-schema or multi-tenant apps, and the subscription "schema_provider"
    seam).

    If this fails, a permission-less caller of schema B receives schema A's
    pruned schema, exposing or hiding fields that belong to a different schema.
    """
    from graphql import GraphQLInt

    # Two schemas that share the SAME empty-perms signature but differ in shape:
    # schema A has no ``secret`` field; schema B does (perm-gated).
    schema_a = GraphQLSchema(
        query=GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)}),
        extensions={"gdx_label_set": _LABEL_SET},
    )
    schema_b = _full_schema()

    cache = _fresh_cache()

    def identity_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        # Return a fresh marker schema tagged with the source schema's identity
        # so we can assert which ``full`` the cached entry was built from.
        return GraphQLSchema(
            query=GraphQLObjectType("Query", {"marker": GraphQLField(GraphQLInt)}),
            extensions={"built_from": id(schema)},
        )

    empty_user = _FakeUser(set())  # signature == sha256("") for BOTH schemas
    pruned_a = cache.pruned_schema_for(empty_user, schema_a, prune=identity_prune)
    pruned_b = cache.pruned_schema_for(empty_user, schema_b, prune=identity_prune)

    # Same empty-perms signature, but the two schemas MUST NOT collide.
    assert pruned_a is not pruned_b, (
        "distinct full schemas sharing a signature must not share a cache entry"
    )
    assert (pruned_a.extensions or {}).get("built_from") == id(schema_a)
    assert (pruned_b.extensions or {}).get("built_from") == id(schema_b)


def test_recycled_id_entry_is_dropped_and_rebuilt() -> None:
    """Assert a cache entry whose id was recycled onto another schema is rebuilt.

    A cache key embeds id(full), which the runtime may reuse for a NEW schema
    once the original is garbage-collected. The weak reference stored beside the
    entry detects this: on read, an entry whose ref no longer resolves to the
    requested schema is treated as a miss, dropped, and rebuilt for the new
    schema — never served stale.

    If this fails, a schema that happens to reuse a collected schema's address
    would receive the collected schema's pruned variant.
    """
    schema_old = _full_schema()
    schema_new = _full_schema()
    cache = _fresh_cache()

    builds: list[int] = []

    def marking_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        builds.append(id(schema))
        return GraphQLSchema(
            query=GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)}),
            extensions={"built_from": id(schema)},
        )

    # Forge the recycled-id collision: an entry keyed by schema_new's id but
    # whose stored weak reference still points at schema_old (as if schema_old
    # had been at that address first and schema_new now reuses it).
    signature = psc.permission_signature(frozenset(), _LABEL_SET)
    stale = marking_prune(schema_old, frozenset())
    cache._entries[(id(schema_new), signature)] = (psc._safe_ref(schema_old), stale)
    builds.clear()

    result = cache.pruned_schema_for(_FakeUser(set()), schema_new, prune=marking_prune)

    # The stale entry (ref -> schema_old) was detected and rebuilt for schema_new.
    assert result is not stale
    assert builds == [id(schema_new)]
    assert (result.extensions or {}).get("built_from") == id(schema_new)


def test_safe_ref_returns_none_for_non_weak_referenceable_object() -> None:
    """Assert _safe_ref degrades to None when an object cannot be weakly referenced.

    Objects without a __weakref__ slot (e.g. a __slots__ class that omits it)
    cannot be weakly referenced. Such a schema still caches correctly; it
    simply forgoes the id-recycling guard rather than raising.

    If this fails, wiring a non-weak-referenceable schema-like object would crash
    the cache instead of caching without the recycling guard.
    """

    class _NoWeakref:
        """A stand-in object that cannot be weakly referenced."""

        __slots__ = ()

    assert psc._safe_ref(_NoWeakref()) is None


def test_lru_never_exceeds_maxsize_and_evicts_least_recently_used() -> None:
    """Assert more than maxsize distinct signatures triggers bounded LRU eviction.

    If this fails, the cache would grow unbounded instead of evicting the
    least-recently-used pruned schema once it exceeds its configured size.
    """
    full = _full_schema()
    cache = psc._SignatureSchemaCache(maxsize=2)

    def uniq_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        return GraphQLSchema(
            query=GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)})
        )

    # Each distinct relevant-perm set is a distinct signature. The label-set has
    # {_VIEW_PUB, _VIEW_SECRET}; build three distinct signatures.
    cache.pruned_schema_for(_FakeUser(set()), full, prune=uniq_prune)  # sig A
    cache.pruned_schema_for(_FakeUser({_VIEW_PUB}), full, prune=uniq_prune)  # sig B
    cache.pruned_schema_for(_FakeUser({_VIEW_SECRET}), full, prune=uniq_prune)  # sig C
    assert len(cache) == 2  # never exceeds maxsize=2
    # Signature A (least recently used) was evicted; B and C remain.
    sig_a = psc.permission_signature(frozenset(), _LABEL_SET)
    assert sig_a not in cache


def test_double_checked_lock_serves_entry_built_during_the_wait() -> None:
    """A signature populated after the pre-check miss is served in-lock, not rebuilt.

    Force the lock-guarded double-check path deterministically: the lock-light
    pre-check is stubbed to always miss, so the SECOND call falls into the lock,
    finds the entry the FIRST call stored, and returns it WITHOUT a rebuild.

    If this fails, a race between the lock-light pre-check and the in-lock
    build could cause a signature to be rebuilt instead of reusing the
    entry a concurrent caller already stored.
    """
    full = _full_schema()
    cache = _fresh_cache()
    build_count = {"n": 0}

    def counting_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        build_count["n"] += 1
        return GraphQLSchema(
            query=GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)})
        )

    # Every lock-light pre-check misses, forcing the in-lock double-check path.
    # ``_get`` now takes the composite ``(id(full), signature)`` key plus the
    # source schema (used to detect an ``id``-recycling collision).
    cache._get = lambda key, full: None  # noqa: ARG005

    user = _FakeUser({_VIEW_PUB})
    first = cache.pruned_schema_for(user, full, prune=counting_prune)
    second = cache.pruned_schema_for(user, full, prune=counting_prune)
    assert first is second  # in-lock double-check returned the stored entry
    assert build_count["n"] == 1  # built once despite the forced pre-check miss


def test_concurrent_first_requests_build_one_shared_instance() -> None:
    """N threads hitting one cold signature -> exactly one build, one instance.

    A ready-barrier lines every thread up on the cold-cache doorstep, then the
    slow build widens the race window with a short sleep. The lock-guarded
    double-check must collapse this to a SINGLE build shared by all threads.

    If this fails, concurrent first-requests for a cold signature would race
    past the lock and build the pruned schema more than once.
    """
    full = _full_schema()
    cache = _fresh_cache()
    build_count = {"n": 0}
    count_lock = threading.Lock()
    ready = threading.Barrier(8)

    def slow_prune(schema: GraphQLSchema, granted: frozenset[str]) -> GraphQLSchema:
        with count_lock:
            build_count["n"] += 1
        time.sleep(0.05)  # widen the window so a race WOULD be observable
        return GraphQLSchema(
            query=GraphQLObjectType("Query", {"public": GraphQLField(GraphQLString)})
        )

    user = _FakeUser({_VIEW_PUB})
    results: list[Any] = []
    results_lock = threading.Lock()

    def worker() -> None:
        ready.wait()  # all threads start the lookup at (nearly) the same instant
        r = cache.pruned_schema_for(user, full, prune=slow_prune)
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert build_count["n"] == 1  # lock-guarded double-check: built once
    assert len(results) == 8
    assert all(r is results[0] for r in results)  # one shared instance
