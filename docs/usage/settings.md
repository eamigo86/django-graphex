# Settings

All configuration lives under a single `DJANGO_GRAPHEX` dict in your
Django settings. Every key is optional — unset keys fall back to the defaults
below.

```python
# settings.py
DJANGO_GRAPHEX = {
    # --- Pagination -------------------------------------------------------- #
    "DEFAULT_PAGINATION_CLASS": "django_graphex.paginations.LimitOffsetGraphqlPagination",
    "DEFAULT_PAGE_SIZE": None,
    "MAX_PAGE_SIZE": None,

    # --- Response cache ---------------------------------------------------- #
    "CACHE_ACTIVE": False,
    "CACHE_TIMEOUT": 300,
    "CLEAN_RESPONSE": False,

    # --- Queryset optimization (N+1) --------------------------------------- #
    "OPTIMIZE_QUERYSET": True,
    "OPTIMIZE_ONLY_FIELDS": True,
    "OPTIMIZE_NESTED_PAGINATION": True,
    "OPTIMIZER_SAFE_MODE": False,
    "OPTIMIZE_ANNOTATED_FIELDS": True,

    # --- Subscriptions ----------------------------------------------------- #
    "SUBSCRIPTION_SERIALIZE_DATA": False,
    "SUBSCRIPTIONS_CHANNEL_GUARD": True,    # needs shared cache in multi-worker

    # --- Security ---------------------------------------------------------- #
    "ALLOW_INTROSPECTION": False,
    "INTROSPECTION_ALLOW_SUPERUSER": True,
    "PROTECTED_FIELDS": (),

    # --- Query depth & cost ------------------------------------------------ #
    "MAX_QUERY_DEPTH": None,
    "MAX_QUERY_COST": None,
    "EXPOSE_QUERY_COST": False,
    "DEFAULT_LIST_MULTIPLIER": 10,
    "COST_PAGINATION_ARGS": ("limit", "page_size", "first", "last"),

    # --- Filtering --------------------------------------------------------- #
    "COMMON_FILTER_LOOKUPS": ("exact", "in", "isnull"),

    # --- File uploads (opt-in — Base64FileInput) --------------------------- #
    "MAX_UPLOAD_SIZE": None,        # Required when Base64FileInput is used
    "MAX_REQUEST_BODY_SIZE": None,  # Body-size guard (primary memory cap)
}
```

## Pagination

| Setting | Default | Description |
|---|---|---|
| `DEFAULT_PAGINATION_CLASS` | `LimitOffsetGraphqlPagination` | Dotted path (or class) of the paginator applied to list fields that don't set their own. Set to `None` to disable default pagination (list fields then return a plain list). See [Pagination](pagination.md). |
| `DEFAULT_PAGE_SIZE` | `None` | Page size used when the client omits it. `None` = unbounded unless a paginator default applies. |
| `MAX_PAGE_SIZE` | `None` | Hard ceiling on the effective page size, applied **even when no page-size argument is sent**. `None` = no ceiling. |

## Response cache

| Setting | Default | Description |
|---|---|---|
| `CACHE_ACTIVE` | `False` | Enable response caching in `GraphQLView`. |
| `CACHE_TIMEOUT` | `300` | Cache TTL in seconds. |
| `CLEAN_RESPONSE` | `False` | Strip `null` values from the response payload. Introspection responses are exempt — see [AST-based introspection detection](security.md#ast-based-introspection-detection-clean_response). |

### Security: per-user cache isolation

When `CACHE_ACTIVE` is `True`, `GraphQLView` partitions cached responses by request identity so that one user's cached response is never served to a different user.

**Identity partitioning rules:**

- **Authenticated requests** — partitioned by `request.user.pk`.  Each user has an independent cache namespace.
- **Token-authenticated requests** (e.g. `Authorization: Bearer …` with no resolved `request.user`) — partitioned by a short hash of the `Authorization` header.
- **Anonymous requests** — all share a single `"anon"` partition.  Anonymous responses contain no private data so sharing is safe.

**Mutation invalidation (scoped, not global):**

A mutation advances a per-user version counter in the cache instead of calling `cache.clear()`.  This means:

- The issuing user's cached reads are invalidated (subsequent reads see fresh data).
- Other users' cached entries are **not** affected.
- Non-GraphQL cache entries (e.g. keys set by application code) are **not** affected.

**Customising the identity key:**

Subclass `GraphQLView` and override the `cache_key_prefix` staticmethod to use a different identity source (e.g. a tenant ID or a session key):

```python
from django_graphex.views import GraphQLView

class MyView(GraphQLView):
    @staticmethod
    def cache_key_prefix(request):
        # Partition by tenant, then fall back to per-user within each tenant.
        tenant = getattr(request, "tenant_id", "default")
        user_pk = getattr(getattr(request, "user", None), "pk", "anon")
        return f"{tenant}_{user_pk}"
```

The `fetch_cache_key` staticmethod (which hashes the request body) remains separately overridable; the two are composed in `dispatch` so overriding either one does not break the other.

## Queryset optimization (N+1)

| Setting | Default | Description |
|---|---|---|
| `OPTIMIZE_QUERYSET` | `True` | Auto-apply `select_related` / `prefetch_related` derived from the query selection. See [Query Optimization](query-optimization.md). |
| `OPTIMIZE_ONLY_FIELDS` | `True` | Also narrow columns with `.only()` across the `select_related` span **and** inside each `Prefetch` child queryset. Set `False` if resolvers/properties read non-selected columns. |
| `OPTIMIZE_NESTED_PAGINATION` | `True` | DB-side `ROW_NUMBER()` window slicing for reverse-FK nested paginated lists (`LimitOffset` / `Page`). `False` = in-memory order+slice fallback. See [Nested Lists](nested-lists.md#performance-n1). |
| `OPTIMIZER_SAFE_MODE` | `False` | When `True`, any exception in the optimization block degrades to the un-optimized queryset and logs a `WARNING` (instead of a 500). Default fail-loud. See [Query Optimization](query-optimization.md). |
| `OPTIMIZE_ANNOTATED_FIELDS` | `True` | Inject `AnnotatedField` DB annotations only when the field is selected. Runtime kill-switch for annotation injection. See [Fields → AnnotatedField](fields.md#annotatedfield). |

## Subscriptions

| Setting | Default | Description |
|---|---|---|
| `SUBSCRIPTION_SERIALIZE_DATA` | `False` | When `False`, change notifications carry only `{"id": <pk>}`; `True` serializes the full instance through the subscription's backend. Per-subscription override: `Meta.serialize_data`. See [Subscriptions](subscriptions.md). |
| `SUBSCRIPTIONS_CHANNEL_GUARD` | `True` | When `True`, the channel ownership guard is active: the HTTP subscribe mutation verifies that `channel_id` was registered by the current session before joining any group. The guard reads from Django's `"default"` cache. **Multi-worker deployments must configure a shared cache backend (Redis / Memcached) for this to work correctly across processes.** With the default `LocMemCache` the guard works only when the WebSocket connect and HTTP subscribe land on the **same** worker. Set `False` to bypass the guard entirely — the failure mode with the guard on but no shared cache is a loud rejection (`ok: False`), never a silent data leak. See [Subscriptions → Security](subscriptions.md#channel-ownership-guard-fail-closed). |

## HTTP / view hardening

| Setting | Default | Description |
|---|---|---|
| `MAX_BATCH_SIZE` | `10` | Maximum number of operations allowed in a single [batch request](https://www.apollographql.com/blog/apollo-client/performance/batching-client-graphql-queries/). Requests exceeding this limit receive **HTTP 400**. Set to `None` to allow batches of any length (disables the guard — use only when all clients are trusted and independent rate limiting is in place). |

### Choosing a `MAX_BATCH_SIZE` value

The default of **10** is a pragmatic cap that covers legitimate use-cases (dashboard
pages that batch 3–8 queries) while preventing request-amplification attacks that can
send hundreds of operations in a single HTTP request.

If your application legitimately needs larger batches, raise the limit explicitly:

```python
DJANGO_GRAPHEX = {
    "MAX_BATCH_SIZE": 50,  # or None to disable entirely
}
```

To restore pre-v1.2.1 behavior (no limit, any-length batch accepted):

```python
DJANGO_GRAPHEX = {
    "MAX_BATCH_SIZE": None,
}
```

!!! warning
    Setting `MAX_BATCH_SIZE=None` removes the DoS protection. Ensure your API
    gateway or reverse proxy enforces request-body size limits before doing this
    on a public-facing endpoint.

## Security

| Setting | Default | Description |
|---|---|---|
| `ALLOW_INTROSPECTION` | `False` | Allow `__schema` / `__type` introspection (`DisableIntrospectionMiddleware`). |
| `INTROSPECTION_ALLOW_SUPERUSER` | `True` | Let superusers bypass the introspection block. |
| `PROTECTED_FIELDS` | `()` | Top-level field names requiring auth via `AuthenticatedFieldsMiddleware` (when not using `DjangoGraphQLSchema`). See [Security](security.md). |

## Query depth & cost

| Setting | Default | Description |
|---|---|---|
| `MAX_QUERY_DEPTH` | `None` | Global max nested-object depth (`DepthLimitValidationRule`). `None` disables the global limit; per-type `Meta.max_deep` still applies. |
| `MAX_QUERY_COST` | `None` | Reject queries whose estimated cost exceeds this (`CostLimitValidationRule`). `None` disables the budget. |
| `EXPOSE_QUERY_COST` | `False` | Add `extensions.cost` (`requestedCost` / `maxCost`) to responses. Combine with `MAX_QUERY_COST=None` for a non-blocking observation mode. |
| `DEFAULT_LIST_MULTIPLIER` | `10` | Cost multiplier for a list field whose page size is unknown (no literal/variable value and no `MAX_PAGE_SIZE` cap). |
| `COST_PAGINATION_ARGS` | `("limit", "page_size", "first", "last")` | Argument names treated as a list's page size when costing a field. |

See [Query Optimization](query-optimization.md) and [Security](security.md) for the depth/cost guides.

## Filtering

| Setting | Default | Description |
|---|---|---|
| `COMMON_FILTER_LOOKUPS` | `("exact", "in", "isnull")` | The **common base** lookup set every field receives when `Meta.filter_fields` declares it in **list form**. Text fields additionally get `icontains` / `istartswith`, and ordered (number/date/datetime) fields `gt` / `gte` / `lt` / `lte` / `range`. Dict-form declarations are explicit and ignore this. See [Filtering](filtering.md). |

## File uploads

These settings apply to `Base64FileInput` — an opt-in input type for sending files as base64 strings inside the GraphQL body. See [Mutations → File Upload Support](mutations.md#file-upload-support).

| Setting | Default | Description |
|---|---|---|
| `MAX_UPLOAD_SIZE` | `None` | Maximum **decoded** size (bytes) of a single `Base64FileInput` field. **Required** when `Base64FileInput` is used — raises `ImproperlyConfigured` at call time when absent and no per-field `max_size` override is given. A per-field `max_size` kwarg on `.to_uploaded_file()` or `decode_base64_file()` overrides this global cap for that specific call. Example: `5 * 1024 * 1024` (5 MB). |
| `MAX_REQUEST_BODY_SIZE` | `None` | Maximum total HTTP request **body length** (bytes), checked in `BaseGraphQLView.dispatch` **before** JSON parsing. This is the primary memory-safety cap: the entire base64 string is already in the HTTP body before any resolver runs, so rejecting here prevents full-body allocation above the threshold. The per-field decoded-size pre-check in `decode_base64_file` is a secondary guard that saves the decode allocation for payloads that slip past (e.g. when this setting is unset). Requests that exceed the limit receive **HTTP 413**. `None` = disabled (not recommended for public-facing endpoints). Example: `20 * 1024 * 1024` (20 MB). **Note:** for larger base64 uploads you must raise **both** this setting and Django's [`DATA_UPLOAD_MAX_MEMORY_SIZE`](https://docs.djangoproject.com/en/stable/ref/settings/#data-upload-max-memory-size) (default 2.5 MB), since the full base64 body counts toward that limit. |

### Choosing values

A 5 MB file uploaded as base64 occupies roughly 6.7 MB in the JSON body (base64 overhead ≈ 4/3). A safe rule of thumb:

```
MAX_REQUEST_BODY_SIZE ≥ ceil(MAX_UPLOAD_SIZE × 4/3) × max_files_per_request + json_overhead
```

For a single-file upload with a 5 MB cap and 100 KB of JSON overhead:
```python
MAX_UPLOAD_SIZE = 5 * 1024 * 1024          # 5 MB decoded
MAX_REQUEST_BODY_SIZE = 20 * 1024 * 1024   # 20 MB body (comfortable margin)
```

## How settings are read

`DJANGO_GRAPHEX` is read through a small self-contained reader (no DRF
dependency). Changes are picked up automatically in tests via Django's
`setting_changed` signal, so `@override_settings(DJANGO_GRAPHEX={...})`
works as expected. An unknown key raises `AttributeError` to catch typos early.
