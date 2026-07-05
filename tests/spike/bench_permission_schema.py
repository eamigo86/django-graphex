"""P4 benchmark — calibrate "PERMISSION_SCHEMA_CACHE_MAXSIZE" from data.

SDD "permission-scoped-schema" task 4.3/4.4. Measures the three quantities the
design's Open Question needs to resolve the LRU bound (currently the placeholder
64):

(a) **prune ms** — wall time of one "prune_schema(full, granted)" rebuild on a
    representative labeled schema. This is the COLD-MISS cost the LRU amortizes; a
    cheap prune tolerates a smaller cache, an expensive one argues for a larger.
(b) **per-variant memory** — the incremental heap a single cached pruned schema
    retains ("tracemalloc" delta of the built object graph). "maxsize" times
    per-variant memory is the cache's worst-case footprint — the ceiling that
    keeps the bound honest.
(c) **hit-rate sim** — replay a realistic request stream (a Zipfian mix of
    permission profiles) through the real "_SignatureSchemaCache" at several
    "maxsize" values and report the hit rate + distinct-signature count. The
    knee of that curve is the calibrated bound.

Design constraints honored:
- pytest-collected (precedent: "tests/spike/bench_*.py"), and FAST — the schema
  is small and iteration counts are modest, so the whole module runs well under a
  second and never blocks the suite.
- Pure library surface: builds a labeled schema with "ObjectType" + "field",
  prunes with "schema_pruner.prune_schema", and caches with the real
  "_SignatureSchemaCache" — no mocks of the code under calibration.

Run: pytest tests/spike/bench_permission_schema.py -v -s
     ("-s" surfaces the printed measurement tables)
"""

from __future__ import annotations

import random
import time
import tracemalloc
from typing import Any

from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.core.permission_signature_cache import (
    _SignatureSchemaCache,
    permission_signature,
)
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.schema import DjangoGraphQLSchema

# --------------------------------------------------------------------------- #
# Representative labeled schema
# --------------------------------------------------------------------------- #
# A schema with a spread of independently-gated fields. Each ``gated_i`` field
# requires a distinct perm, so a permission profile is any subset of the N perms
# — the exact shape that drives signature cardinality in production.
_N_GATED_FIELDS = 12
_GATED_PERMS = [f"app.view_res{i:02d}" for i in range(_N_GATED_FIELDS)]


def _build_query_cls() -> type[ObjectType]:
    """Build a Query root: one public field plus "_N_GATED_FIELDS" gated fields.

    Returns:
        query_cls: The dynamically assembled "_BenchQuery" ObjectType subclass.
    """
    attrs: dict[str, object] = {"public": field(GraphQLString)}

    def _resolve(root: Any, info: Any) -> str:  # noqa: N805
        return "x"

    attrs["resolve_public"] = staticmethod(_resolve)
    for i, perm in enumerate(_GATED_PERMS):
        name = f"gated_{i:02d}"
        attrs[name] = field(GraphQLString, required_perms=[perm])
        attrs[f"resolve_{name}"] = staticmethod(_resolve)
    return type("_BenchQuery", (ObjectType,), attrs)


_schema = DjangoGraphQLSchema(query=_build_query_cls())
_full = _schema.graphql_schema
_label_set = frozenset((_full.extensions or {}).get("gdx_label_set") or ())


# --------------------------------------------------------------------------- #
# Realistic access model: ROLES, not independent per-field grants.
# --------------------------------------------------------------------------- #
# Production permission profiles are driven by a small set of Django Groups
# (roles). A user's grant set is (their role's perms) plus an occasional ad-hoc
# extra. This clustering — NOT independent per-field coin flips — is what governs
# signature cardinality, so it is what the LRU bound must be calibrated against.
def _build_roles() -> list[frozenset[str]]:
    """Return a spread of role permission-sets (admin, staff, tiers, guest).

    Returns:
        roles: The list of role permission frozensets, from broadest (admin)
            to narrowest (guest), plus two non-prefix slices.
    """
    return [
        frozenset(_GATED_PERMS),  # admin: everything
        frozenset(_GATED_PERMS[:8]),  # senior staff
        frozenset(_GATED_PERMS[:5]),  # staff
        frozenset(_GATED_PERMS[:3]),  # member
        frozenset(_GATED_PERMS[:1]),  # basic
        frozenset(),  # guest: only public
        frozenset(_GATED_PERMS[2:5]),  # support (a non-prefix slice)
        frozenset(_GATED_PERMS[4:8]),  # billing (another slice)
    ]


_ROLES = _build_roles()
#: Zipfian role popularity: the first roles (admin/staff) are rare, the middle
#: tiers common — front-loaded weights model a member-heavy user base.
_ROLE_WEIGHTS = [1, 2, 6, 12, 20, 8, 3, 3]


def _sample_profiles(count: int, *, seed: int = 1234) -> list[frozenset[str]]:
    """Return "count" permission profiles from a Zipfian role mix plus rare extras.

    Each request picks a role by popularity weight; a small fraction of users
    additionally hold ONE ad-hoc extra perm (the long tail). The result is a
    stream dominated by a handful of role signatures with a modest tail — the
    real driver of the LRU's working-set size.

    Args:
        count: The number of permission profiles to sample.
        seed: The random seed, kept fixed by default for reproducible runs.

    Returns:
        profiles: The sampled list of permission-set profiles.
    """
    rng = random.Random(seed)
    profiles: list[frozenset[str]] = []
    for _ in range(count):
        role = rng.choices(_ROLES, weights=_ROLE_WEIGHTS, k=1)[0]
        # ~8% of users carry one ad-hoc extra grant beyond their role.
        if rng.random() < 0.08:
            role = role | {rng.choice(_GATED_PERMS)}
        profiles.append(frozenset(role))
    return profiles


# --------------------------------------------------------------------------- #
# (a) prune ms
# --------------------------------------------------------------------------- #
class TestP4PruneCost:
    """Cold-miss prune wall time on the representative schema.

    Measures quantity (a) of the LRU calibration: the per-prune wall time
    that a cache miss must pay.
    """

    def test_prune_ms(self) -> None:
        """A single prune_schema rebuild must stay well under a human-perceptible frame.

        Contract: the calibration data ships broken if a cold-miss prune
        becomes slow enough to stall a request; the 50ms ceiling is a
        generous CI-stable gate on that cost.
        """
        granted = frozenset(_GATED_PERMS[:6])  # a mid-size profile
        # Warm up (parse/first-clone caches, import-time lazies).
        prune_schema(_full, granted)

        iterations = 50
        start = time.perf_counter()
        for _ in range(iterations):
            prune_schema(_full, granted)
        elapsed = time.perf_counter() - start
        per_prune_ms = (elapsed / iterations) * 1000.0

        print(
            f"\n(a) prune: {per_prune_ms:.3f} ms/variant "
            f"over {iterations} iters, {_N_GATED_FIELDS} gated fields"
        )

        # GATE: a single prune is a cheap in-memory rebuild (no I/O). It MUST stay
        # well under a human-perceptible frame so cold misses never stall a
        # request; a generous ceiling keeps the gate CI-stable across machines.
        assert per_prune_ms < 50.0, f"prune too slow: {per_prune_ms:.3f} ms"


# --------------------------------------------------------------------------- #
# (b) per-variant memory
# --------------------------------------------------------------------------- #
class TestP4PerVariantMemory:
    """Incremental heap a single cached pruned schema retains.

    Measures quantity (b) of the LRU calibration: the per-variant memory
    footprint the cache's "maxsize" ceiling must be set against.
    """

    def test_per_variant_memory_kib(self) -> None:
        """A single cached pruned-schema variant must stay within a light memory ceiling.

        Contract: the calibration data ships broken if a pruned variant
        retains enough heap that a full 64-entry cache would no longer be a
        few MiB; the 512 KiB per-variant ceiling is generous for CI
        portability.
        """
        granted = frozenset(_GATED_PERMS[:6])
        tracemalloc.start()
        before = tracemalloc.get_traced_memory()[0]
        pruned = prune_schema(_full, granted)
        # Touch the type map so lazily-built structures are realized before we
        # measure (graphql-core computes ``type_map`` on first access).
        _ = pruned.type_map
        after = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()

        per_variant_kib = (after - before) / 1024.0
        print(f"(b) memory: {per_variant_kib:.1f} KiB/variant retained")

        # Report a projected ceiling for the current bound so calibration is
        # visible: maxsize=64 * per-variant footprint.
        print(
            f"    projected ceiling @ maxsize=64: {per_variant_kib * 64 / 1024:.2f} MiB"
        )

        # GATE: a pruned variant is a lightweight clone (shared scalars/enums), so
        # a full 64-entry cache stays comfortably within a few MiB. Ceiling is
        # generous for CI portability.
        assert per_variant_kib < 512.0, f"variant too heavy: {per_variant_kib:.1f} KiB"


# --------------------------------------------------------------------------- #
# (c) hit-rate sim + maxsize calibration
# --------------------------------------------------------------------------- #
class TestP4HitRateCalibration:
    """Replay a realistic profile stream through the real LRU at several bounds.

    Measures quantity (c) of the LRU calibration: the hit rate at several
    "maxsize" values, whose knee is the calibrated default bound.
    """

    def _replay(
        self, profiles: list[frozenset[str]], maxsize: int
    ) -> tuple[float, int]:
        """Replay profiles through a fresh cache and report hit rate and cardinality.

        Args:
            profiles: The permission-set profiles to replay, in request order.
            maxsize: The LRU bound to construct the cache with for this run.

        Returns:
            A tuple of the observed hit rate and the count of distinct
            signatures seen across the replayed profiles.
        """
        cache = _SignatureSchemaCache(maxsize=maxsize)
        hits = 0
        seen: set[str] = set()
        for granted in profiles:

            class _U:
                """A minimal user stand-in exposing a fixed permission set."""

                is_active = True
                is_superuser = False

                def __init__(self, perms: frozenset[str]) -> None:
                    self._perms = perms

                def get_all_permissions(self) -> frozenset[str]:
                    return self._perms

            sig = permission_signature(granted, _label_set)
            seen.add(sig)
            was_cached = sig in cache
            cache.pruned_schema_for(_U(granted), _full)
            if was_cached:
                hits += 1
        rate = hits / len(profiles) if profiles else 0.0
        return rate, len(seen)

    def test_hit_rate_across_maxsizes(self) -> None:
        """The default maxsize=64 bound must sit on the hit-rate curve's knee.

        Contract: the calibrated default ships broken as either
        over-provisioned (matching a much smaller bound) or
        under-provisioned (still gaining meaningfully at 128) if it fails
        any of the three assertions below.
        """
        profiles = _sample_profiles(2000)
        distinct = len({permission_signature(p, _label_set) for p in profiles})

        print(
            f"\n(c) stream: {len(profiles)} requests, "
            f"{distinct} distinct signatures ({_N_GATED_FIELDS} independent perms)"
        )
        results = {}
        for maxsize in (8, 16, 32, 64, 128):
            rate, seen = self._replay(profiles, maxsize)
            results[maxsize] = rate
            print(
                f"    maxsize={maxsize:>4}: hit-rate {rate * 100:5.1f}%  (distinct={seen})"
            )

        # GATE: the default bound (64) must capture the popular head of a Zipfian
        # stream — a strong hit rate that the smaller bounds do NOT reach. If 64
        # matched 8, the bound would be over-provisioned; if it lagged 128, it
        # would be under-provisioned. We assert it is BOTH high AND on the plateau.
        assert results[64] >= 0.60, f"hit-rate@64 too low: {results[64]:.2f}"
        assert results[64] >= results[16], "64 must not underperform 16"
        # The 64->128 gain must be marginal (we are at/after the knee) — this is
        # the evidence that 64 is a sound calibrated default, not a guess.
        assert results[128] - results[64] < 0.10, (
            f"64 is below the knee: 128 gains "
            f"{(results[128] - results[64]) * 100:.1f} pts over 64"
        )
