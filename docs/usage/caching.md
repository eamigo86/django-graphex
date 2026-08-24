# Response Caching

`GraphQLView` can cache full HTTP responses to avoid re-executing identical
queries.  Caching is off by default; enable it with a single setting:

```python
# settings.py
DJANGO_GRAPHEX = {
    "CACHE_ACTIVE": True,
    "CACHE_TIMEOUT": 300,  # seconds, default 5 min
}
```

The view uses Django's `"default"` cache backend.  Any backend Django supports
(local-memory, Redis, Memcached, database, …) works out of the box.

---

## Cache key anatomy

Each cached entry is stored under a key of the form:

```
_graphql_{identity}_{version}_{body_hash}
```

| Component | Source | Purpose |
|-----------|--------|---------|
| `_graphql_` | fixed prefix | Namespaces GraphQL entries inside a shared Django cache |
| `{identity}` | `cache_key_prefix(request)` | Isolates responses by user identity (see below) |
| `{version}` | per-identity version counter | Lets mutations invalidate a user's entries without a global flush |
| `{body_hash}` | `fetch_cache_key(request)` — SHA-256 of `request.body`; for GET requests (where the body is empty) the hash also incorporates the `query`, `variables`, and `operationName` query-string parameters | Distinguishes different queries / variable sets |

---

## Per-user isolation

Responses are **partitioned by request identity** so that one user's cached
result is never served to another user.

| Request type | Identity token | Sharing |
|---|---|---|
| Authenticated (`request.user.is_authenticated`) | `u{user.pk}` | Per-user (isolated) |
| Token-auth only (`Authorization` header, no `request.user`) | `t{sha256(header)[:16]}` | Per-token (isolated) |
| Anonymous (no credentials) | `anon` | Shared (safe — no private data) |

---

## Mutation invalidation (scoped, not global)

When a mutation is detected, the view **increments a per-identity version
counter** stored in the cache rather than calling `cache.clear()`.

This has two important properties:

1. **Only the issuing user's namespace is invalidated.**  User B's cached
   reads are unaffected when user A sends a mutation.
2. **Unrelated cache entries survive.**  Keys set by other parts of your
   application (sessions, page fragments, etc.) are not touched.

### Post-commit invalidation (TOCTOU safety)

The bump is scheduled **after the mutation has been executed**, and deferred
via `transaction.on_commit` so it only fires
**after the mutation's database write is durable**.  A concurrent query that
arrives between the start of the mutation and its commit therefore sees the
pre-mutation version key and correctly hits (or misses) pre-mutation cache
entries — it never caches pre-mutation data at the new, post-mutation version.

If the mutation's transaction is rolled back, `on_commit` is never invoked and
the version counter is **not** advanced.  Only successful mutations invalidate
the cache.

When `ATOMIC_MUTATIONS` is off (no open transaction), Django executes
`on_commit` immediately after the current statement, so behaviour is unchanged
for non-transactional deployments.

!!! note "Ordering matters"

    `ATOMIC_MUTATIONS` opens its atomic block *inside* the execution of the
    mutation, so scheduling the bump before running the mutation would find no
    open transaction and fire it immediately — advancing the counter while the
    mutation body was still running.  The bump is therefore always scheduled
    after the mutation has run.

### Version-counter key TTL

The version counter key is stored with `timeout=None` (never expires
independently).  If `CACHE_TIMEOUT` is set higher than your cache backend's
own default TTL (e.g. 600 s vs. Redis's 300 s default), the counter would
otherwise expire first, causing the version to reset and old response entries
to be reused as if they were fresh.  The permanent timeout prevents this.

### Cold-start initialisation

On a cold cache (first request or after the version key expires on a backend
that ignores `timeout=None`), the counter is initialised to `1` (not `0`).
This ensures:

- The first mutation bump reaches `2`, not `1`.
- Version `0` is never used as a live cache key, eliminating an ambiguous
  state where a concurrent request could cache a response at `v0` and that
  entry would remain permanently unreachable after the first bump.

Backends that support atomic `incr` (Redis, Memcached) use it; backends that
do not (Django's local-memory cache when the key is absent) fall back to
setting the heal value to `1` with `timeout=None`.

---

## Malformed query handling

If the request body contains syntactically invalid GraphQL, `get_operation_ast`
catches the `GraphQLSyntaxError` and returns `None`.  The request falls through
to the normal execution path, which returns HTTP 400 with a structured error
body.  The cache is not consulted or written for invalid documents.

---

## Customising the cache key

### Body hash (`fetch_cache_key`)

Override `fetch_cache_key` on a subclass to derive the body hash differently
(e.g. normalise whitespace, extract the operation name, or mix in query
variables):

```python
from django_graphex.views import GraphQLView

class MyView(GraphQLView):
    @staticmethod
    def fetch_cache_key(request):
        import hashlib, json
        data = json.loads(request.body or b"{}")
        canonical = json.dumps(
            {"query": data.get("query", ""), "variables": data.get("variables")},
            sort_keys=True,
        ).encode()
        return hashlib.sha256(canonical).hexdigest()
```

### Identity prefix (`cache_key_prefix`)

Override `cache_key_prefix` to use a different identity source (e.g. a tenant
ID, a session key, or a custom header):

```python
class MyView(GraphQLView):
    @staticmethod
    def cache_key_prefix(request):
        tenant = getattr(request, "tenant_id", "default")
        user_pk = getattr(getattr(request, "user", None), "pk", "anon")
        return f"{tenant}_{user_pk}"
```

The two overrides are composed independently in `dispatch`; overriding either
one does not break the other.

---

## Requests that bypass the cache

Not all requests are eligible for caching even when `CACHE_ACTIVE=True`.  The
following are always passed through to the underlying view uncached:

| Reason | Detail |
|--------|--------|
| **Batch requests** | A batch body is a JSON list; individual operations cannot be cached meaningfully. |
| **Multipart/form-data** | `parse_body` reads `request.POST` for this content type, consuming the WSGI stream. A subsequent read of `request.body` (needed to compute the cache key) raises `RawPostDataException`. Bypassing avoids an HTTP 500. Multipart GraphQL is used almost exclusively for file-upload mutations which are not idempotent queries. |
| **Mutations** | Mutations advance the version counter instead of being cached. |
| **GraphiQL renders** | A request the view would answer with the GraphiQL page (`graphiql=True` and the client prefers `text/html`) is never cached. The cache key is built from the request body / query-string parameters, not from content negotiation, so a cached HTML page and the JSON answer for the same query would otherwise share one slot and whoever warmed it would decide what every later client received. The GraphiQL page is a static render, so caching it buys nothing. |

---

## CSRF cookies and cached responses

The base `GraphQLView.dispatch` is decorated with `@ensure_csrf_cookie`, which
sets `Set-Cookie: csrftoken=<secret>` on every response.

To prevent one client's CSRF secret from being replayed to other clients in
the same identity namespace, the cache stores **only the response body, HTTP
status code, and content type** — not the whole `HttpResponse` object.  On a
cache hit a fresh `HttpResponse` is constructed from those stored values;
`ensure_csrf_cookie` is not re-applied (the GraphQL endpoint is `csrf_exempt`
so this has no security impact on the endpoint itself).

---

## `CACHE_ACTIVE=False` (default)

When `CACHE_ACTIVE` is `False`, the `dispatch` method bypasses all caching
logic immediately and every request is executed fresh.  The setting can be
toggled per-test with `@override_settings(DJANGO_GRAPHEX={"CACHE_ACTIVE": True})`.
