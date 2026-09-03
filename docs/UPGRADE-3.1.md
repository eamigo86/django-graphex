# Upgrade from 3.0 to 3.1

Version 3.1 is a compatibility-focused hardening release. Most applications can
upgrade without schema changes, but cached APIs should review the new global
invalidation default and custom CRUD permissions must remain synchronous.

## Upgrade checklist

1. Install `django-graphex==3.1.0` in a staging environment.
2. If response caching is enabled, keep the safe global scope unless **all**
   cached data is private to one identity.
3. Check custom `BasePermission` hooks: CRUD hooks must use `def`, while
   subscription authorization may use `async def`.
4. Run your mutation, subscription and cache integration tests.

## Changes that can affect an application

### Cache invalidation is global by default

One successful mutation now invalidates cached reads for every response
identity. Response bodies remain isolated per identity; only the version counter
is shared. The cache-key format is versioned, so 3.0 entries cannot be revived.

```python
DJANGO_GRAPHEX = {
    "CACHE_ACTIVE": True,
    "CACHE_INVALIDATION_SCOPE": "global",  # 3.1 default
}
```

Use `"identity"` only for a cache whose mutations and reads are fully private:

```python
DJANGO_GRAPHEX = {
    "CACHE_ACTIVE": True,
    "CACHE_INVALIDATION_SCOPE": "identity",  # 3.0-compatible opt-in
}
```

Unknown values raise `ImproperlyConfigured`. See
[Response caching](usage/caching.md#mutation-invalidation) for the key layout,
durable-execution rules and cookie policy.

### Cookie-dependent queries skip caching

The default `GraphQLView.should_cache_query(request)` returns `False` for a
request with cookies. This prevents two anonymous sessions from sharing a cart,
tenant or locale-dependent response. Cookie-free public queries can still share
the anonymous cache.

If you override the hook to accept cookies, include **every** varying context in
the key:

```python
class TenantGraphQLView(GraphQLView):
    def should_cache_query(self, request):
        return True

    @staticmethod
    def cache_key_prefix(request):
        return f"tenant:{request.tenant.pk}:session:{request.session.session_key}"
```

### CRUD permission hooks stay synchronous

An awaitable returned by `BasePermission.has_permission` or an action-specific
CRUD hook now fails closed with `ImproperlyConfigured` before a write begins.
Use a normal `def` method. Subscription hooks are different: their async
pipeline explicitly awaits `authorize_subscription` and `subscription_scope`.

```python
class CanEdit(BasePermission):
    def has_update_permission(self, info, model, **kwargs):
        return info.context.user.has_perm("shop.change_product")
```

## Correctness fixes

- Rejected GET mutations and validation failures no longer invalidate cache;
  execution that may have persisted data still does. Atomic rollbacks do not.
- Subscription callbacks capture a detached event snapshot at signal time.
  Repeated saves produce distinct events, and rollback produces none.
- `CLEAN_RESPONSE` uses the selected `operationName` before deciding whether an
  introspection response must preserve `null` and empty lists.
- Renamed subclasses of `MultiSelectField` compile as lists in output and CRUD
  inputs.
- Pagination argument names such as `limit` multiply query cost only when the
  GraphQL return type is actually list-shaped.

## Documentation, example and release changes

- The quickstart exposes a small, authenticated, read-only `auth.User` surface;
  registration uses `create_user()` and never accepts privilege fields.
- The playground reset removes generated migrations safely, and WebSocket
  origin defaults allow only the local development hosts.
- CI now gates release on exact tests, branch and patch coverage above 95%,
  PostgreSQL 17, docs, playground and an external wheel smoke test.
- A release is built once, checksummed and reused by PyPI and GitHub Release.
  Manual dispatch publishes only to TestPyPI; production requires a matching
  annotated version tag.
- Benchmarks validate the full 20×10×5 response, roll measured mutations back,
  support pinned offline replay and publish only validated three-run medians.

## Audit-to-documentation map

This table is the review path for the 24 audit findings. The linked page is the
canonical operational documentation; the [changelog](changelog.md#310--2026-09-02)
records the release-level summary.

| # | Change | Canonical documentation |
|---:|---|---|
| 1 | Cookie-aware anonymous cache isolation | [Caching: per-user isolation](usage/caching.md#per-user-isolation) |
| 2 | Invalidate only after potentially durable execution | [Caching: post-commit invalidation](usage/caching.md#post-commit-invalidation-toctou-safety) |
| 3 | Safe authenticated-user quickstart | [Quick Start](quickstart.md) |
| 4 | Complete pre-publication gate graph | [Contributing: release contract](contributing.md#release-contract) |
| 5 | One immutable distribution artifact | [Contributing: release contract](contributing.md#release-contract) |
| 6 | Immutable `on_commit` event snapshots | [Subscriptions: commit-time delivery](usage/subscriptions.md#commit-time-broadcast-delivery) |
| 7 | `CLEAN_RESPONSE` follows `operationName` | [Security: introspection cleaning](usage/security.md#ast-based-introspection-detection-clean_response) |
| 8 | Real `MultiSelectField` subclasses remain lists | [Types: multiselect fields](usage/types.md#multiselectfield) |
| 9 | Global invalidation with identity opt-in | [Caching: mutation invalidation](usage/caching.md#mutation-invalidation) |
| 10 | Cost multipliers require list returns | [Query cost analysis](usage/query-limits.md#query-cost-analysis) |
| 11 | Async CRUD permissions fail closed | [Permissions](usage/permissions.md#writing-a-custom-permission) |
| 12 | Wheel smoke test outside the checkout | [Contributing: release contract](contributing.md#release-contract) |
| 13 | Core transactional tests without Channels | [Contributing: test contract](contributing.md#test-contract) |
| 14 | Exact exception assertions | [Contributing: test contract](contributing.md#test-contract) |
| 15 | Branch and patch coverage above 95% | [Contributing: test contract](contributing.md#test-contract) |
| 16 | Bounded test and tox tools | [Contributing: testing standards](contributing.md#testing-standards) |
| 17 | PostgreSQL transaction release gate | [Contributing: database setup](contributing.md#database-setup) |
| 18 | Accurate generated-mutation contract | [Mutations: permissions](usage/mutations.md#permissions-are-djangomodeltype-only) |
| 19 | Recoverable playground reset | [Playground: reset](usage/examples/playground.md#resetting-the-playground) |
| 20 | Restricted WebSocket origins | [Playground: WebSocket origins](usage/examples/playground.md#websocket-origin-policy) |
| 21 | Exact 20×10×5 benchmark contract | [Why: benchmark conditions](why.md#the-conditions) |
| 22 | Rollback-isolated measurements | [Why: benchmark conditions](why.md#the-conditions) |
| 23 | Pinned offline replay | [Why: reproduce](why.md#reproduce-it-yourself) |
| 24 | Validated median publisher | [Why: reproduce](why.md#reproduce-it-yourself) |

## Next steps

- Read the full [3.1.0 changelog](changelog.md#310--2026-09-02).
- If coming from 2.x, complete the [3.0 upgrade guide](UPGRADE-3.0.md) first.
- Validate the runnable changes in the [playground](usage/examples/playground.md).
