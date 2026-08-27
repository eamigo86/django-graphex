"""Permission-signature cache (P2): signature + thread-safe bounded LRU.

This module turns a caller's LIVE permissions into a stable permission
signature and maintains an in-process, lazy, thread-safe, bounded LRU mapping
from signature to pruned "GraphQLSchema". The view (P2) reads it per request to
select the pruned schema a user validates and executes against.

Design (SDD "permission-scoped-schema" D3):

- "permission_signature(perms, label_set)" is the SHA-256 hexdigest of the
  newline-joined sorted "perms & label_set" — a projection onto ONLY the
  schema-relevant perms. Perms outside the label-set collapse away, so two users
  who differ only in irrelevant perms share one signature (and one pruned
  schema). The signature is NOT keyed by user id, so a permission grant/revoke is
  reflected on the caller's NEXT request (a new signature, never a stale schema).
- The cache is a module-level "_SignatureSchemaCache" (an "OrderedDict" +
  "threading.RLock"), NOT "functools.lru_cache": we need explicit "maxsize"
  eviction, a lock-guarded double-checked lazy build, and introspection for the
  P4 benchmark. Closure resolvers are unpicklable, so the cache is in-process
  only — never a Django/external cache and never keyed by user id.
- Building is lock-guarded and idempotent per signature: N concurrent
  first-requests for one cold signature build the pruned schema exactly ONCE and
  share the single instance.
- "pruned_schema_for(user, full)" fast-paths an ACTIVE superuser to the FULL
  schema WITHOUT computing a signature (they see everything, so pruning is a
  waste). Everyone else is projected, signed, and served from the LRU.

The default "maxsize" (64) is CALIBRATED by the P4 benchmark
(tests/spike/bench_permission_schema.py) and overridable via the
"PERMISSION_SCHEMA_CACHE_MAXSIZE" key of DJANGO_GRAPHEX (0 caches nothing,
None keeps the calibrated default, a negative is refused). Calibration: a
realistic role-driven request stream produces ~50 distinct permission
signatures, and 64 captures that entire working set (~97% hit rate, at/after the
curve's knee — 128 adds nothing) while a single pruned variant retains only a
few KiB, so a full 64-entry cache costs well under 1 MiB.
"""

from __future__ import annotations

import threading
import weakref
from collections import OrderedDict
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Callable

from ..settings import graphql_api_settings
from .schema_pruner import prune_schema

if TYPE_CHECKING:
    from graphql import GraphQLSchema

__all__ = ("permission_signature", "pruned_schema_for")

#: LRU bound calibrated by the P4 benchmark (~50 distinct signatures on a
#: realistic role-driven stream; 64 holds the full working set at the curve's
#: knee). Overridable via the ``PERMISSION_SCHEMA_CACHE_MAXSIZE`` setting (read
#: per eviction pass, so the bound is not frozen at import).
_DEFAULT_MAXSIZE = 64

#: The schema-extensions channel that carries the global label-set (P0).
_LABEL_SET_KEY = "gdx_label_set"

#: Type of a prune callable: ``(full, granted) -> pruned``. Injectable so tests
#: can substitute a spy; production wires ``schema_pruner.prune_schema``.
PruneFn = Callable[["GraphQLSchema", frozenset], "GraphQLSchema"]


def permission_signature(perms: frozenset[str], label_set: frozenset[str]) -> str:
    """Return the stable signature of "perms" projected onto "label_set".

    Args:
        perms: The caller's live permission codenames (from
            "get_all_permissions()").
        label_set: The schema's global label-set ("extensions[gdx_label_set]")
            — the only perms that can affect pruning.

    Returns:
        The hex SHA-256 digest of the sorted relevant perms. Perms outside
        "label_set" are ignored, so irrelevant differences collapse to the same
        signature; dropping a relevant perm yields a different signature.
    """
    relevant = frozenset(perms) & frozenset(label_set)
    return sha256("\n".join(sorted(relevant)).encode()).hexdigest()


class _SignatureSchemaCache:
    """Thread-safe bounded LRU mapping ``(full schema, signature) -> pruned``.

    A module-level singleton (:data:`_CACHE`) backs :func:`pruned_schema_for`;
    tests instantiate their own for isolation. Reads are lock-light (a fast
    pre-check); a cold key is built under the lock with a double-check so
    concurrent first-requests build exactly once.

    Entries are keyed by ``(id(full), signature)`` — NOT the signature alone —
    because two DIFFERENT ``full`` schemas can share a permission signature
    (most starkly a permission-less user, whose relevant-perm projection is
    empty for every schema, so the signature is ``sha256("")`` regardless of
    schema). Keying on the signature alone let one schema's pruned variant be
    served for an unrelated schema — a correctness bug for any deployment
    routing more than one schema through the cache. A weak reference to the
    source ``full`` is kept alongside each entry so that a recycled ``id`` (a
    fresh schema object reusing a garbage-collected schema's address) is
    detected on read and rebuilt rather than served stale.
    """

    def __init__(self, maxsize: int | None = None) -> None:
        """Initialize an empty cache with the given (or settings-derived) bound.

        Args:
            maxsize: A fixed LRU bound for this instance; when None the bound
                follows the ``PERMISSION_SCHEMA_CACHE_MAXSIZE`` setting, read
                on every eviction pass. The module singleton is built at
                import, so capturing the setting here would freeze it for the
                life of the process and make it unreachable from
                ``override_settings``.
        """
        self._maxsize = maxsize
        # Key: (id(full), signature). Value: (weakref-or-None to full, pruned).
        self._entries: OrderedDict[tuple[int, str], tuple[Any, GraphQLSchema]] = (
            OrderedDict()
        )
        self._lock = threading.RLock()

    def __len__(self) -> int:
        """Return the number of cached ((full, signature) -> schema) entries.

        Returns:
            The count of currently cached entries.
        """
        return len(self._entries)

    def __contains__(self, signature: str) -> bool:
        """Return whether any cached entry currently holds *signature*.

        Membership is by signature (ignoring the schema component of the key)
        so callers and tests can probe "is this permission signature cached?"
        without holding the schema that produced it.

        Args:
            signature: The permission signature to look for.

        Returns:
            True if some cached entry has this signature, else False.
        """
        return any(sig == signature for _schema_id, sig in self._entries)

    def clear(self) -> None:
        """Drop every cached entry (used by tests / settings reloads)."""
        with self._lock:
            self._entries.clear()

    def pruned_schema_for(
        self,
        user: Any,
        full: GraphQLSchema,
        *,
        prune: PruneFn | None = None,
    ) -> GraphQLSchema:
        """Return the pruned schema for *user* against the labeled *full* schema.

        An ACTIVE superuser bypasses to the FULL schema without a signature. Any
        other user is projected onto the schema label-set, signed, and served
        from the LRU (built lazily under the lock on a miss).

        Args:
            user: The request user (needs ``is_superuser`` / ``is_active`` and
                ``get_all_permissions()``).
            full: The labeled FULL ``GraphQLSchema``.
            prune: Optional prune callable override (defaults to
                ``schema_pruner.prune_schema``); injectable for tests.

        Returns:
            The FULL schema for an active superuser, else the cached/lazily-built
            pruned schema for the caller's permission signature.
        """
        if getattr(user, "is_active", False) and getattr(user, "is_superuser", False):
            return full

        label_set = frozenset((full.extensions or {}).get(_LABEL_SET_KEY) or ())
        granted = frozenset(user.get_all_permissions())
        signature = permission_signature(granted, label_set)
        key = (id(full), signature)

        # Fast, lock-light pre-check: a hit refreshes recency and returns.
        cached = self._get(key, full)
        if cached is not None:
            return cached

        prune_fn = prune if prune is not None else prune_schema
        with self._lock:
            # Double-check: another thread may have built it while we waited.
            cached = self._live_entry(key, full)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached
            built = prune_fn(full, granted & label_set)
            self._entries[key] = (_safe_ref(full), built)
            self._entries.move_to_end(key)
            self._evict_if_needed()
            return built

    def _get(self, key: "tuple[int, str]", full: GraphQLSchema) -> GraphQLSchema | None:
        """Return a cached schema (refreshing recency) or ``None`` on a miss.

        Args:
            key: The composite ``(id(full), signature)`` cache key.
            full: The source schema, used to detect a recycled ``id`` collision.

        Returns:
            The cached pruned schema, or None on a miss (including a recycled
            ``id`` whose weak reference no longer resolves to *full*).
        """
        with self._lock:
            cached = self._live_entry(key, full)
            if cached is not None:
                self._entries.move_to_end(key)
            return cached

    def _live_entry(
        self, key: "tuple[int, str]", full: GraphQLSchema
    ) -> GraphQLSchema | None:
        """Return the entry for *key* only if it truly belongs to *full*.

        Guards against ``id`` recycling: an entry whose stored weak reference no
        longer resolves to *full* is treated as a miss and dropped. That covers
        both a reference pointing at a different live schema and a DEAD one —
        the source was garbage-collected and a new object took its address,
        which is the shape an actual recycle takes. Only an entry stored without
        a reference at all (a schema that cannot be weakly referenced) keeps the
        pre-weakref behaviour of trusting the key.

        Args:
            key: The composite ``(id(full), signature)`` cache key.
            full: The schema the caller is requesting a pruned variant for.

        Returns:
            The cached pruned schema when the entry is live and belongs to
            *full*, else None.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        ref, pruned = entry
        source = ref() if ref is not None else None
        if ref is not None and source is not full:
            # The source is either a DIFFERENT live schema or already collected
            # (``source is None``). Both mean this ``id`` now belongs to another
            # object, so the entry is stale — and the collected case is the one
            # an id recycle actually produces.
            del self._entries[key]
            return None
        return pruned

    def _evict_if_needed(self) -> None:
        """Evict least-recently-used entries until within the current bound."""
        maxsize = self._maxsize if self._maxsize is not None else _resolve_maxsize()
        while len(self._entries) > maxsize:
            self._entries.popitem(last=False)


def _safe_ref(obj: Any) -> "weakref.ref[Any] | None":
    """Return a weak reference to *obj*, or None when it cannot be referenced.

    A weak reference lets the cache detect ``id`` recycling (a fresh schema
    reusing a garbage-collected schema's address) without pinning the schema in
    memory. Objects that do not support weak references still cache correctly —
    they simply forgo the recycling guard.

    Args:
        obj: The object to weakly reference (a source ``GraphQLSchema``).

    Returns:
        A ``weakref.ref`` to *obj*, or None if *obj* is not weak-referenceable.
    """
    try:
        return weakref.ref(obj)
    except TypeError:
        return None


def _resolve_maxsize() -> int:
    """Return the configured LRU bound (setting override or the default).

    A bound of 0 is honored as "cache nothing"; it used to be falsy here and
    silently restored the default, so turning the cache off left the 64-entry
    default running. A negative bound is refused by the settings reader.

    Returns:
        The current LRU bound.
    """
    configured = getattr(
        graphql_api_settings, "PERMISSION_SCHEMA_CACHE_MAXSIZE", _DEFAULT_MAXSIZE
    )
    return _DEFAULT_MAXSIZE if configured is None else int(configured)


#: Process-wide cache backing :func:`pruned_schema_for`.
_CACHE = _SignatureSchemaCache()


def pruned_schema_for(user: Any, full: GraphQLSchema) -> GraphQLSchema:
    """Return the per-request pruned schema for the user (module-singleton cache).

    This is the BUNDLED permission-scoped provider seam: it is the callable the
    HTTP "AuthenticatedGraphQLView" and the subscription transports (via a
    "schema_provider=lambda user: pruned_schema_for(user, full)" idiom) route
    through, and it is where the "PERMISSION_SCOPED_SCHEMA" feature flag is
    honored so ONE flag rules the feature across every transport:

    - "PERMISSION_SCOPED_SCHEMA" False (default) -> "full" is returned
      unchanged. The setting is read PER CALL (per HTTP request / per
      subscription connection), never memoized at import, so toggling it takes
      effect on the next request/connection.
    - "PERMISSION_SCOPED_SCHEMA" True -> an active superuser still receives
      "full" (no signature); everyone else is served the LRU-cached schema
      pruned to their permission signature, built lazily and thread-safely on a
      miss.

    A CUSTOM "schema_provider" callable that does NOT route through this helper
    is the caller's own code and is intentionally NOT gated here — the flag gates
    the BUNDLED helper only.

    Args:
        user: The request/connection user.
        full: The labeled FULL "GraphQLSchema".

    Returns:
        The selected "GraphQLSchema" for this caller.
    """
    # Read the flag per-call (never at import) so the bundled provider matches
    # the HTTP view's gate and a settings toggle is reflected on the next
    # request/connection.
    if not graphql_api_settings.PERMISSION_SCOPED_SCHEMA:
        return full
    return _CACHE.pruned_schema_for(user, full)
