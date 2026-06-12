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
| `{body_hash}` | `fetch_cache_key(request)` — SHA-256 of `request.body` | Distinguishes different queries / variable sets |

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

Backends that support atomic `incr` (Redis, Memcached) use it; backends that
do not (Django's local-memory cache when the key is absent) fall back to
storing a fresh UUID.

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

## `CACHE_ACTIVE=False` (default)

When `CACHE_ACTIVE` is `False`, the `dispatch` method bypasses all caching
logic immediately and every request is executed fresh.  The setting can be
toggled per-test with `@override_settings(DJANGO_GRAPHEX={"CACHE_ACTIVE": True})`.
