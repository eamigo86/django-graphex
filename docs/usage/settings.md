# Settings

All configuration lives under a single `DJANGO_GRAPHEX` dict in your
Django settings. Every key is optional — unset keys fall back to the defaults
below.

```python
# settings.py
DJANGO_GRAPHEX = {
    # --- Schema & middleware ----------------------------------------------- #
    # (merged in from the legacy GRAPHENE namespace in 2.0)
    "SCHEMA": None,                  # dotted path to your schema, or pass schema= to the view
    "SCHEMA_OUTPUT": "schema.json",  # default output file for the graphql_schema command
    "SCHEMA_INDENT": 2,              # JSON indent for graphql_schema output
    "MIDDLEWARE": (),                # GraphQL execution middleware (dotted paths or objects)
    "SUBSCRIPTION_PATH": None,       # WebSocket subscription endpoint exposed to GraphiQL
    "ATOMIC_MUTATIONS": False,       # wrap each mutation in transaction.atomic()
    "MAX_VALIDATION_ERRORS": None,   # cap validation errors returned (None = no cap)
    "SUBSCRIPTION_CONNECTION_INIT_TIMEOUT": 3.0,  # graphql-transport-ws connection_init wait (s)
    "SSE_HEARTBEAT_ENABLED": False,  # optional idle SSE comments
    "SSE_HEARTBEAT_INTERVAL": 15,  # seconds when enabled
    "SSE_CONNECTION_LIMIT_ENABLED": False,  # optional shared account cap
    "SSE_MAX_CONNECTIONS_PER_USER": 5,  # when enabled
    "SSE_CONNECTION_REDIS_URL": None,  # shared Redis URL when cap enabled

    # --- Pagination -------------------------------------------------------- #
    "DEFAULT_PAGINATION_CLASS": "django_graphex.paginations.LimitOffsetGraphqlPagination",
    "DEFAULT_PAGE_SIZE": 100,
    "MAX_PAGE_SIZE": None,

    # --- Response cache ---------------------------------------------------- #
    "CACHE_ACTIVE": False,
    "CACHE_TIMEOUT": 300,
    "CACHE_INVALIDATION_SCOPE": "global",
    "CLEAN_RESPONSE": False,

    # --- Document cache (parse + validate) ---------------------------------- #
    "DOCUMENT_CACHE_MAXSIZE": 128,  # bounds the parse + per-schema validation LRUs (0 disables both)

    # --- Queryset optimization (N+1) --------------------------------------- #
    "OPTIMIZE_QUERYSET": True,
    "OPTIMIZE_ONLY_FIELDS": True,
    "OPTIMIZE_NESTED_PAGINATION": True,
    "OPTIMIZER_SAFE_MODE": False,
    "OPTIMIZER_WORK_BUDGET": 2000,  # per-execution optimizer expansion cap per walker (None disables)
    "OPTIMIZE_ANNOTATED_FIELDS": True,

    # --- Subscriptions ----------------------------------------------------- #
    "SUBSCRIPTION_PAYLOAD_MODE": "id_only",
    "MAX_SUBSCRIPTIONS_PER_CONNECTION": 50,  # concurrent operations per WS socket (None = unlimited)

    # --- HTTP / view hardening --------------------------------------------- #
    "MAX_BATCH_SIZE": 10,            # max operations per batch request (None = unlimited)
    "REQUIRE_CSRF_HEADER": True,     # demand X-Requested-With on CORS-simple POSTs

    # --- Security ---------------------------------------------------------- #
    "ALLOW_INTROSPECTION": False,
    "INTROSPECTION_ALLOW_SUPERUSER": True,
    "PROTECTED_FIELDS": (),
    "API_ACCESS_GROUP": "",             # restrict AuthenticatedGraphQLView to this auth Group ("" = off)
    "PERMISSION_SCOPED_SCHEMA": False,  # prune each authed request's schema to the caller's perms (off = inert)
    "PERMISSION_SCHEMA_CACHE_MAXSIZE": 64,  # LRU bound for the per-signature pruned-schema cache

    # --- Query depth & cost ------------------------------------------------ #
    "MAX_QUERY_DEPTH": None,
    "MAX_QUERY_COST": None,
    "EXPOSE_QUERY_COST": False,
    "DEFAULT_LIST_MULTIPLIER": 10,
    "COST_PAGINATION_ARGS": ("limit", "page_size", "first", "last"),
    "COST_DIRECTIVE": 0,                # cost per custom directive use (0 = free)

    # --- Filtering --------------------------------------------------------- #
    "COMMON_FILTER_LOOKUPS": ("exact", "in", "isnull"),

    # --- String directive output ------------------------------------------ #
    "MAX_REPLACE_OUTPUT_LENGTH": 1_000_000,  # Unicode characters per @replace result; None = uncapped
    "MAX_DIRECTIVE_OUTPUT_TOTAL": 10_000_000,  # characters directives may add per HTTP request (batch items share it); None = unlimited

    # --- File uploads (opt-in — Base64FileInput) --------------------------- #
    "MAX_UPLOAD_SIZE": None,        # Required when Base64FileInput is used
    "MAX_REQUEST_BODY_SIZE": None,  # Body-size guard (primary memory cap)
}
```

## Schema & middleware

These keys configure the schema the view serves and the GraphQL execution
pipeline. In v1.x they lived in the separate `GRAPHENE` dict; in 2.0 they are
part of `DJANGO_GRAPHEX` like everything else.

| Setting | Default | Description |
|---|---|---|
| `SCHEMA` | `None` | Dotted path (or the object) of the schema `GraphQLView` uses **when you don't pass `schema=` to `.as_view()`**. `None` = you must pass `schema=` explicitly. Accepts an import string. |
| `SCHEMA_OUTPUT` | `"schema.json"` | Default output file for the [`graphql_schema`](#exporting-the-schema) management command. A `.json` path writes introspection JSON; a `.graphql` / `.gql` path writes SDL. Override per-run with `--out`. |
| `SCHEMA_INDENT` | `2` | JSON indentation used by the [`graphql_schema`](#exporting-the-schema) command. Override per-run with `--indent`. Ignored for SDL output. |
| `MIDDLEWARE` | `()` | GraphQL **execution** middleware chain — dotted paths or callables/objects. The bundled security middlewares plug in here, e.g. `"django_graphex.security.DisableIntrospectionMiddleware"` and `"…AuthenticatedFieldsMiddleware"`, plus `"django_graphex.middleware.GraphQLDirectiveMiddleware"` if you use directives. Accepts import strings. Used as the view's default when `middleware=` isn't passed. |
| `SUBSCRIPTION_PATH` | `None` | Path of the WebSocket subscription endpoint advertised to GraphiQL / the bundled client. `None` = default routing. See [Subscriptions](subscriptions.md). |
| `ATOMIC_MUTATIONS` | `False` | Wrap each mutation in `transaction.atomic()`. GraphQL execution errors and the established mutation error flag roll back writes in that operation. Structured `ok: false` data is not itself an execution error; an earlier successful sibling root field is not retroactively rolled back. `True` wraps the default database; set `DATABASES[alias]["ATOMIC_MUTATIONS"] = True` to cover another alias. Errors also roll back every alias with `ATOMIC_REQUESTS`. |
| `MAX_VALIDATION_ERRORS` | `None` | Cap the number of GraphQL validation errors returned in a single response (also honored by the WS/SSE subscription transports). `None` = no cap. |
| `SUBSCRIPTION_CONNECTION_INIT_TIMEOUT` | `3.0` | Seconds the `graphql-transport-ws` server waits for the first `connection_init` after the socket opens before closing with code **4408** (`connectionInitWaitTimeout`). The transport factory may override it. |

When Django enables `ATOMIC_REQUESTS` on a database alias, GraphQL
execution errors and the mutation error flag mark that alias's request
transaction for rollback, for every alias that has the option. Without either
transaction setting, a write made before a later GraphQL execution error may
already be durable. Rolled-back atomic writes do not advance the GraphQL
response-cache version; durable non-atomic writes still invalidate cached
responses.

### Per-database atomic mutations

`ATOMIC_MUTATIONS = True` wraps each mutation in `transaction.atomic()` on the
default database. Another alias opts in with its own key in `DATABASES`:

```python
DATABASES = {
    "default": {...},
    "analytics": {..., "ATOMIC_MUTATIONS": True},
}
```

`DATABASES["default"]["ATOMIC_MUTATIONS"] = True` has the same effect as the
global setting for the default alias. Each opted-in alias gets its own atomic
block, so a GraphQL execution error rolls back the writes on every one of
them. Django has no two-phase commit: the blocks commit independently, so a
failure while committing one alias cannot undo another that already committed.
Models routed by a database router to an alias without this option are not
wrapped.

## Pagination

| Setting | Default | Description |
|---|---|---|
| `DEFAULT_PAGINATION_CLASS` | `LimitOffsetGraphqlPagination` | Dotted path (or class) of the paginator applied to list fields that don't set their own. Set to `None` to disable default pagination (list fields then return a plain list). See [Pagination](pagination.md). |
| `DEFAULT_PAGE_SIZE` | `100` | Size inherited by LimitOffset, Page, and Cursor paginators when their size constructor argument is omitted. Set a different positive value before importing the pagination classes to change the startup default. Explicit `None` retains each paginator's legacy behavior; it is not a universal “return all” option. |
| `MAX_PAGE_SIZE` | `None` | Hard ceiling on the effective page size, applied **even when no page-size argument is sent**. `None` = no ceiling. |

## Response cache

| Setting | Default | Description |
|---|---|---|
| `CACHE_ACTIVE` | `False` | Enable successful HTTP 200, error-free GraphQL response caching in `GraphQLView`; failed responses are neither stored nor reused. |
| `CACHE_TIMEOUT` | `300` | Cache TTL in seconds. |
| `CACHE_INVALIDATION_SCOPE` | `"global"` | Mutation invalidation policy. `"global"` advances one shared GraphQL version so every identity sees shared writes; `"identity"` preserves the narrower 3.0 per-identity policy. Any other value raises `ImproperlyConfigured`. |
| `CLEAN_RESPONSE` | `False` | For `GraphQLView`, remove `null`, empty strings, and empty containers recursively while retaining numeric zero and `false`. Selected introspection operations are exempt — see [response cleaning](security.md#ast-based-introspection-detection-clean_response). |

### Security: per-user cache isolation

When `CACHE_ACTIVE` is `True`, `GraphQLView` partitions cached responses by request identity so that one user's cached response is never served to a different user.

**Identity partitioning rules:**

- **Authenticated requests** — partitioned by `request.user.pk`.  Each user has an independent cache namespace.
- **Token-authenticated requests** (e.g. `Authorization: Bearer …` with no resolved `request.user`) — partitioned by a short hash of the `Authorization` header.
- **Anonymous requests without cookies** — share a single `"anon"` partition.
- **Requests with cookies** — bypass response caching by default. Anonymous does not mean context-free: carts, sessions, tenants, locale and feature flags can all be cookie-dependent.

**Mutation invalidation:**

A mutation advances a GraphQL version counter instead of calling
`cache.clear()`. `CACHE_INVALIDATION_SCOPE="global"` is the safe default: user
A's mutation invalidates cached reads belonging to user B and anonymous/token
identities as well. The response key still carries the full identity, so bodies
remain isolated.

`CACHE_INVALIDATION_SCOPE="identity"` restores the 3.0 behavior in which only
the issuing identity (or unauthenticated bucket) advances. Choose it only for
fully identity-private data; shared writes can otherwise leave other callers'
cached reads stale. Neither mode affects non-GraphQL cache entries.

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

The `fetch_cache_key` staticmethod hashes tagged, length-framed request-body
and GET query, variables, and operation-name components into a 64-character
SHA-256 digest. It remains separately overridable; the two hooks are composed
in `dispatch`. The new default digest produces cold misses for existing cached
responses, which expire normally. An override must preserve component
boundaries if it handles GET requests itself.

`GraphQLView.should_cache_query(request)` is the eligibility hook. Its default
returns `False` for every cookie-bearing query. An override may be stricter; if
it opts contextual requests back in, the identity or body key must include every
session, tenant, locale or cookie value that can affect the response.

## Document cache (parse + validate)

| Setting | Default | Description |
|---|---|---|
| `DOCUMENT_CACHE_MAXSIZE` | `128` | In-process bound (per LRU) for two independent document caches in the view layer. `0` disables **both** caches; `None` leaves them unbounded. A negative integer raises `ImproperlyConfigured` when this setting is read. |
| `DOCUMENT_CACHE_MAX_QUERY_LENGTH` | `65536` | Bound on what both document caches retain. A document longer than this many characters, or whose parsed AST has more than an eighth of this many tokens, is parsed and validated on every request but never cached; each cache also retains at most this many AST tokens in total, evicting least recently used entries first. `0` caches no document; `None` removes every one of these bounds. A negative integer raises `ImproperlyConfigured` when this setting is read. |

graphql-core re-parses and re-revalidates the identical query document on every
request; real APIs replay a small, stable set of documents (a handful of
persisted queries from your frontend), so both steps are memoizable:

- **Parse cache** — global, keyed on the raw query string. The parsed
  `DocumentNode` (AST) is immutable and schema-independent, so a single cached
  document is safely **shared across every request and every schema**.
- **Validation cache** — per-schema. Verdicts are stored in a
  `WeakKeyDictionary` keyed by the `GraphQLSchema` **object itself**, with an
  inner LRU (also bounded by `DOCUMENT_CACHE_MAXSIZE`) inside each schema's
  sub-cache. This means a permission-pruned schema (see
  [`PERMISSION_SCOPED_SCHEMA`](#security)) **never** shares a validation
  verdict with another schema — a query invalid against a pruned schema can
  never read a full schema's cached "valid" result. Because the cache is keyed
  by object identity, a garbage-collected schema's sub-cache is dropped
  automatically instead of risking an `id()`-reuse collision with an unrelated
  schema instance. The key also folds in the runtime query-limit settings
  (`MAX_QUERY_DEPTH`, `MAX_QUERY_COST`, and the cost-analysis page-size
  settings), so tightening a limit at runtime invalidates previously cached
  "valid" verdicts immediately — the cache never serves a stale verdict across
  a limit change.

A parsed AST is many times larger than its query text (up to about 270x for a
dense document such as `{ a a a ... }`), so entry count and text length alone do
not bound memory. `DOCUMENT_CACHE_MAX_QUERY_LENGTH` therefore also bounds the
AST itself, measured in tokens: a document is retained only when it is at most
that many characters long **and** its AST has at most an eighth of that many
tokens (8,192 by default), and each cache evicts least recently used entries
once it retains more than that many tokens in total (65,536 by default). A
retained AST measured about 320-550 bytes per token, so the default worst case
is about 40 MB of ASTs per worker for the parse cache, and the same again for
each schema's validation sub-cache when its cached verdicts carry errors
(errors reference the AST nodes they blame), on top of at most
`DOCUMENT_CACHE_MAXSIZE` x 65,536 characters of query text in the parse cache
(the validation cache keys on a digest of the text instead). Persisted-query-sized
documents stay cached; very large or token-dense documents, which a client sends
once, are simply processed without being retained. Setting
either bound to `None` removes that guarantee.

Raise `DOCUMENT_CACHE_MAXSIZE` if your application legitimately replays more
than 128 distinct documents per schema; set it to `0` to disable both caches
entirely (e.g. while debugging a parse/validation-related issue). `None` means
unbounded, as it does for every other limit in this namespace — only safe when
the set of documents your clients send is finite, since nothing is ever evicted.

## Queryset optimization (N+1)

| Setting | Default | Description |
|---|---|---|
| `OPTIMIZE_QUERYSET` | `True` | Auto-apply `select_related` / `prefetch_related` derived from the query selection. See [Query Optimization](query-optimization.md). |
| `OPTIMIZE_ONLY_FIELDS` | `True` | Also narrow columns with `.only()` across the `select_related` span **and** inside each `Prefetch` child queryset. Set `False` if resolvers/properties read non-selected columns. |
| `OPTIMIZE_NESTED_PAGINATION` | `True` | DB-side `ROW_NUMBER()` window slicing for reverse-FK nested paginated lists (`LimitOffset` / `Page`). `False` = in-memory order+slice fallback. See [Nested Lists](nested-lists.md#performance-n1). |
| `OPTIMIZER_SAFE_MODE` | `False` | When `True`, any exception in the optimization block degrades to the un-optimized queryset and logs a `WARNING` (instead of a 500). Default fail-loud. See [Query Optimization](query-optimization.md). |
| `OPTIMIZER_WORK_BUDGET` | `2000` | Per-operation-execution cap on the selection contexts each optimizer walker expands. Fragments reached through distinct relation paths describe exponentially many lookups; past the cap the root field is resolved without the optimizer plan (same data, more queries). `None` disables the cap; `0` or a negative value raises `ImproperlyConfigured`. See [Query Optimization](query-optimization.md#optimizer_work_budget-work-cap). |
| `OPTIMIZE_ANNOTATED_FIELDS` | `True` | Inject `AnnotatedField` DB annotations only when the field is selected. Runtime kill-switch for annotation injection. See [Fields → AnnotatedField](fields.md#annotatedfield). |

## Subscriptions

| Setting | Default | Description |
|---|---|---|
| `SUBSCRIPTION_PAYLOAD_MODE` | `"id_only"` | When `"id_only"`, change notifications carry only `{"id": <pk>}`; `"full"` serializes the full instance through the subscription's backend. Per-subscription override: `Meta.payload_mode`. See [Subscriptions](subscriptions.md). |
| `MAX_SUBSCRIPTIONS_PER_CONNECTION` | `50` | Maximum number of concurrent operations on **one WebSocket**. A rejected operation does not close the socket. This is not an account-wide cap; see [Subscriptions → Per-connection subscription cap](subscriptions.md#per-connection-subscription-cap). |
| `SSE_HEARTBEAT_ENABLED` | `False` | Opt in to idle SSE comment frames. Does not change subscription events or require Redis. |
| `SSE_HEARTBEAT_INTERVAL` | `15` | Positive finite number of seconds between idle comments while the heartbeat is enabled. |
| `SSE_CONNECTION_LIMIT_ENABLED` | `False` | Opt in to a shared Redis-backed concurrent SSE stream cap for authenticated accounts only. |
| `SSE_MAX_CONNECTIONS_PER_USER` | `5` | Positive integer account cap when enabled. A full account receives HTTP 429 before source startup. |
| `SSE_CONNECTION_REDIS_URL` | `None` | `redis://` or `rediss://` URL of the shared admission backend. Required when the account cap is enabled; unavailable admission returns HTTP 503. See [SSE connection controls](subscriptions.md#sse-connection-controls) for cleanup, expiry, and failover limits. |

## HTTP / view hardening

| Setting | Default | Description |
|---|---|---|
| `MAX_BATCH_SIZE` | `10` | Maximum number of operations allowed in a single [batch request](https://www.apollographql.com/blog/apollo-client/performance/batching-client-graphql-queries/). Requests exceeding this limit receive **HTTP 400**. `0` allows no batch operations; `None` removes the cap (use only with independent rate limiting). A negative integer raises `ImproperlyConfigured` when this setting is read. |
| `REQUIRE_CSRF_HEADER` | `True` | Demand the **`X-Requested-With`** header on a POST whose content type a browser can send cross-site with **no CORS preflight** — `application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`, or no content type at all. The endpoint is `csrf_exempt`, so without it a cross-site `<form>` submit executes under the victim's session cookie; the header is not CORS-safelisted, so demanding it forces the preflight a forged request cannot pass. The value is never inspected. **This changes behaviour for existing form-encoded and multipart clients**, which must add the header or get **HTTP 403** before the body is read. `application/json` and `application/graphql` already force a preflight and are never asked for it. Set to `False` only if a client cannot add the header **and** the endpoint is protected another way. See [Security → Cross-site POST protection](security.md#cross-site-post-protection). |

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
| `ALLOW_INTROSPECTION` | `False` | With `DisableIntrospectionMiddleware` installed in GraphQL `MIDDLEWARE`, control `__schema` / `__type` introspection. The default `MIDDLEWARE=()` means `False` alone does not block it. See [Security](security.md#disable-introspection). |
| `INTROSPECTION_ALLOW_SUPERUSER` | `True` | With that middleware installed and `ALLOW_INTROSPECTION=False`, let **active** superusers (`is_active` **and** `is_superuser`) bypass the block; a deactivated superuser is blocked. |
| `PROTECTED_FIELDS` | `()` | Top-level field names requiring auth via `AuthenticatedFieldsMiddleware` (when not using `DjangoGraphQLSchema`). See [Security](security.md). |
| `API_ACCESS_GROUP` | `""` | Restrict the **authenticated endpoint** (`AuthenticatedGraphQLView`) to members of this Django auth `Group` (by name). `""` disables the gate. Non-members get a generic `403` before any GraphQL parsing/execution; an **active superuser always bypasses** it. The public `GraphQLView` is **not** affected. See [Views → Endpoint-level auth](views.md#endpoint-level-auth-authenticatedgraphqlview) and the [permission guide](permission-scoped-schema.md#layer-2-the-endpoint-gate-api_access_group) (with curl examples). |
| `PERMISSION_SCOPED_SCHEMA` | `False` | Serve each **authenticated** request (`AuthenticatedGraphQLView`) a schema pruned to the caller's permissions: a field whose required perms the user lacks is **absent**, so selecting it reads as `Cannot query field` (a not-found, never an authz leak). Read **per-request**. An **active superuser** always gets the full schema (no signature computed); a non-superuser whose pruned `Query` root is **empty** gets the endpoint's generic `403`. The public `GraphQLView` is **never** pruned. **Subscriptions:** the **same** flag also gates the bundled `pruned_schema_for` helper used by the SSE/WS transports' `schema_provider` (read **per connection**), so a subscription connection wired to it serves the full schema when off and the pruned one when on — see [Subscriptions → Per-connection schema](subscriptions.md#per-connection-schema-permission-scoped-subscriptions). A **custom** provider callable that does not route through `pruned_schema_for` is not gated. Requires a labeled `DjangoGraphQLSchema`. `False` (default) is byte-identical to today. For a worked, role-by-role walkthrough (pruned SDL per user, exact denial responses), see the [permission guide](permission-scoped-schema.md). |
| `PERMISSION_SCHEMA_CACHE_MAXSIZE` | `64` | In-process **LRU** bound for the `PERMISSION_SCOPED_SCHEMA` cache. Entries are keyed by the caller's permission **signature** (`perms ∩ schema label-set`), never by user id, so users with the same relevant perms share one pruned schema; least-recently-used entries evict past this cap. `0` caches nothing (every request prunes); `None` keeps the default `64`; a **negative** value raises `ImproperlyConfigured`. Read on every eviction pass, so `override_settings` reaches it. |

## Query depth & cost

| Setting | Default | Description |
|---|---|---|
| `MAX_QUERY_DEPTH` | `None` | Global max nested-object depth (`DepthLimitValidationRule`). `None` is the **only** way to disable the global limit; per-type `Meta.max_depth` still applies. `0` or a negative value raises `ImproperlyConfigured` — it used to switch the guard off silently. |
| `MAX_QUERY_COST` | `None` | Reject queries whose estimated cost exceeds this (`CostLimitValidationRule`). `None` is the **only** way to disable the budget; `0` or a negative value raises `ImproperlyConfigured`. |
| `EXPOSE_QUERY_COST` | `False` | Add `extensions.cost` (`requestedCost` / `maxCost`) to responses. Combine with `MAX_QUERY_COST=None` for a non-blocking observation mode. |
| `DEFAULT_LIST_MULTIPLIER` | `10` | Cost multiplier for a list field whose page size is unknown (no literal/variable value and no `MAX_PAGE_SIZE` cap). |
| `COST_PAGINATION_ARGS` | `("limit", "page_size", "first", "last")` | Argument names treated as a real list field's page size when costing a field, compared in snake_case form (`page_size` matches `pageSize`). |
| `COST_DIRECTIVE` | `0` | Cost added for every custom directive use (`@replace`, `@center`, ...) on a field, multiplied by the enclosing lists like any other field cost, so aliases x directives is visible to `MAX_QUERY_COST`. `0` keeps directives free (existing totals unchanged); it must be a non-negative integer, anything else raises `ImproperlyConfigured` when the setting is read. A directive runs once on the whole value of its field, so one on a scalar list field is costed once; only the enclosing object lists multiply it. `@skip` and `@include` are never charged. A value such as `1` or `2` is a reasonable starting point; try it with `EXPOSE_QUERY_COST` first. |

See [Query Optimization](query-optimization.md) and [Security](security.md) for the depth/cost guides.

## Filtering

| Setting | Default | Description |
|---|---|---|
| `COMMON_FILTER_LOOKUPS` | `("exact", "in", "isnull")` | The **common base** lookup set every field receives when `Meta.filter_fields` declares it in **list form**. Text fields additionally get `icontains` / `istartswith`, and ordered (number/date/datetime) fields `gt` / `gte` / `lt` / `lte` / `range`. Dict-form declarations are explicit and ignore this. See [Filtering](filtering.md). |

## String directive output

This setting applies to `@replace` on ordinary string fields by default; it
does **not** require `Base64FileInput` or any upload feature.

| Setting | Default | Description |
|---|---|---|
| `MAX_REPLACE_OUTPUT_LENGTH` | `1_000_000` | Maximum **Unicode characters** in each `@replace` result, not encoded bytes; the request-wide budget is `MAX_DIRECTIVE_OUTPUT_TOTAL`. The exact Python replacement length (including empty-substring insertions and `count`) is checked **before** replacement allocation; results above the cap produce a GraphQL field error with normal null propagation. A result at the cap is allowed. Must be a positive integer; `None` restores the former uncapped behavior, which is unsafe without another output limit. |
| `MAX_DIRECTIVE_OUTPUT_TOTAL` | `10_000_000` | Per-**request** budget, in Unicode characters, for text that directives **add**. Every custom directive is charged the amount by which its result is longer than its input, summed over all fields, aliases, rows and chained directives of the execution (all items of a batch share the budget of their HTTP request; a subscription event is its own execution; an execution the GraphQL view did not start, or whose context cannot carry the counter -- `None`, `__slots__` -- is counted per execution). Once the budget is spent, each further directive use is a GraphQL field error naming this setting and produces no text; a single field can overshoot by at most its own per-field cap. Normal requests are unaffected; directives that do not lengthen the text (`@uppercase`, `@truncate`, ...) are free. Must be a positive integer; `None` removes the budget. It complements `MAX_REPLACE_OUTPUT_LENGTH`, which still bounds each `@replace` result. |

## File uploads

These settings cover received multipart files and `Base64FileInput`, the opt-in
input type for files encoded inside the GraphQL body. See
[Mutations → File Upload Support](mutations.md#file-upload-support).

| Setting | Default | Description |
|---|---|---|
| `MAX_UPLOAD_SIZE` | `None` | Maximum size (bytes) of **each received multipart file**, including unused or unmapped parts and repeated parts under one name. A file at the limit passes; a larger file returns JSON HTTP 413 before resolver execution. `None` leaves multipart files without this per-file cap. The same setting caps decoded `Base64FileInput` data (a file of exactly the limit passes on both transports) and is **required** for that input unless a per-call `max_size` override is supplied; without either, Base64 decoding raises `ImproperlyConfigured`. The override affects only that Base64 call, not multipart files. Example: `5 * 1024 * 1024` (5 MB). |
| `MAX_REQUEST_BODY_SIZE` | `None` | Maximum total HTTP request **body length** (bytes), checked in `BaseGraphQLView.dispatch` **before** JSON parsing. This is the primary memory-safety cap: the entire base64 string is already in the HTTP body before any resolver runs, so rejecting here prevents full-body allocation above the threshold. The per-field decoded-size pre-check in `decode_base64_file` is a secondary guard that saves the decode allocation for payloads that slip past (e.g. when this setting is unset). Requests that exceed the limit receive **HTTP 413**; a `multipart/form-data` POST that declares no `Content-Length` receives **HTTP 411** on a server whose request stream cannot be measured (WSGI), because it is then the one body whose size is unknowable. `0` allows no body bytes; `None` disables the guard (not recommended for public-facing endpoints). A negative integer raises `ImproperlyConfigured` when this setting is read. Example: `20 * 1024 * 1024` (20 MB). See [How the guard reads each content type](#how-the-guard-reads-each-content-type) below. |

When `CACHE_ACTIVE=True`, `GraphQLView` applies the same configured POST body
limit **before** operation parsing or parse, validation, and response-cache
access. A request exceeding the cap still receives HTTP 413, even if an
identical query was cached earlier. This is an ordering fix, not a new limit:
`None` still disables the body cap, and it does not bound retained cache bytes
or request reception by an ASGI server.

### How the guard reads each content type

The guard runs in two stages. Stage 1 rejects a declared `Content-Length` above
the cap without reading anything. Stage 2 then measures the real body, because
`Content-Length` is a client-supplied claim and stage 1 on its own would take it
at face value.

Stage 2 measures every content type — but it measures `multipart/form-data`
differently, because reading a multipart body would break the request (the CSRF
check has already drained the stream) and pull a streamed upload into RAM.
Instead it **seeks** `request._stream` to the end and straight back: nothing is
allocated, the parser still receives an untouched stream, and multipart keeps
streaming to disk under
[`FILE_UPLOAD_MAX_MEMORY_SIZE`](https://docs.djangoproject.com/en/stable/ref/settings/#file-upload-max-memory-size).
This is the same measurement Django's own `HttpRequest.body` performs on a
seekable stream, done one level up so the answer can be a 413 rather than a 400.

Whether that seek is available depends on the server, and so does what an absent
`Content-Length` means:

- **ASGI** hands the view a `SpooledTemporaryFile` — the handler already spooled
  the whole body with no `Content-Length` cap — which is seekable. The real size
  is always known, so an under-declared *or* absent length is answered with
  **HTTP 413** when the body exceeds the cap.
- **WSGI** hands the view a `LimitedStream` capped at `Content-Length`, which is
  not seekable and does not need to be: an under-declared length truncates the
  body it is lying about instead of smuggling it through. An **absent** length is
  the one case that cap cannot express (Django turns it into a limit of zero), so
  a chunked multipart POST is refused with **HTTP 411 Length Required** whenever
  `MAX_REQUEST_BODY_SIZE` is set.

The practical consequences:

| Body | Bounded by | `DATA_UPLOAD_MAX_MEMORY_SIZE` applies? |
|---|---|---|
| `application/json` (including base64 uploads) | `MAX_REQUEST_BODY_SIZE`, measured by reading | **Yes** — the body must be in memory to be parsed |
| `application/graphql`, `application/x-www-form-urlencoded` | `MAX_REQUEST_BODY_SIZE`, measured by reading | Yes, same reason |
| `multipart/form-data` | `MAX_REQUEST_BODY_SIZE` vs the **measured** body where the stream is seekable (ASGI); vs the `Content-Length` Django already capped the stream at otherwise (WSGI), with **411** when none is declared | **File parts, no** — they stream to disk. **Non-file parts, yes** — Django sums every non-file part (your `query` and `variables` parts included) against that limit |

#### What this cannot do under ASGI

Be blunt about the boundary: **no view-level setting can stop a multipart body
from being received under ASGI, and this one does not.** Django's ASGI handler
runs `read_body` before the view exists, spooling every chunk the server hands it
into a rolling temporary file with no `CONTENT_LENGTH` cap — unlike WSGI, where
`WSGIRequest` wraps the input in a `LimitedStream` capped at `CONTENT_LENGTH`.
By the time `MAX_REQUEST_BODY_SIZE` is consulted, the bytes are already on your
disk.

What `MAX_REQUEST_BODY_SIZE` gives you under ASGI is a refusal to **process**:
413 once the body — declared honestly, under-declared, or not declared at all —
is measured above the cap. What actually bounds **reception** is your ASGI
server's own request limit
(uvicorn/hypercorn/daphne behind a reverse proxy — set it there) plus
[`FILE_UPLOAD_MAX_MEMORY_SIZE`](https://docs.djangoproject.com/en/stable/ref/settings/#file-upload-max-memory-size),
which only decides when the spool moves from RAM to disk. If you serve GraphQL
uploads over ASGI on a public endpoint, configure that server-level limit; this
setting is not a substitute for it.

So for larger **base64** uploads you must raise **both** `MAX_REQUEST_BODY_SIZE`
and Django's
[`DATA_UPLOAD_MAX_MEMORY_SIZE`](https://docs.djangoproject.com/en/stable/ref/settings/#data-upload-max-memory-size)
(default 2.5 MB) — the full base64 body counts toward that limit, and a 5 MB file
needs roughly 6.7 MB of it.

A **multipart** upload can usually leave `DATA_UPLOAD_MAX_MEMORY_SIZE` alone,
but the reason is narrower than "it does not apply". Django enforces that limit
on every **non-file** part of a multipart body — it sums their sizes and raises
`RequestDataTooBig` past the cap. What escapes it is the **file** parts: those
stream to disk under WSGI and are spooled by the handler under ASGI, and their
bytes are governed by
[`FILE_UPLOAD_MAX_MEMORY_SIZE`](https://docs.djangoproject.com/en/stable/ref/settings/#file-upload-max-memory-size)
instead. So the file itself does not count, and the parts that ride alongside it
do. This library's multipart contract has exactly two of those: a **`query`**
part carrying the document and an optional **`variables`** part carrying its
variables as JSON — there is no `operations` / `map` envelope, and posting one
is answered with `400 Must provide query string`. See
[Mutations → Automatic multipart uploads](mutations.md#automatic-multipart-uploads).
Raise the limit if `variables` grows large — a bulk write whose variables carry
thousands of rows is the shape that reaches it.

A multipart upload does still need `MAX_REQUEST_BODY_SIZE` set above the
whole multipart body — **on both servers**. Under WSGI a declared
`Content-Length` over the cap is refused with 413 before the view runs; under
ASGI the spooled body is measured and refused the same way. Size that setting
against the file plus its multipart envelope, not against the JSON overhead
alone.

When `MAX_UPLOAD_SIZE` is configured, the view also checks **each file part**
after Django parses the multipart body and before a resolver or GraphiQL page
can succeed. This is not an ingress or upload-memory limit: the server and
Django have already received and parsed the parts. An unmatched part is still
size-checked, even though mutation input mapping later ignores it. The
whole-body cap above remains independent and can reject earlier.

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

## Exporting the schema

The `graphql_schema` management command exports your schema to a file (or
stdout). It mirrors graphene-django's command of the **same name**, so it is a
drop-in for projects migrating off graphene-django — built entirely on
graphql-core, with no graphene import.

```bash
# Write introspection JSON to DJANGO_GRAPHEX["SCHEMA_OUTPUT"] (default schema.json)
python manage.py graphql_schema

# Override the output path
python manage.py graphql_schema --out build/schema.json

# Write SDL instead — selected by the .graphql / .gql extension
python manage.py graphql_schema --out schema.graphql

# Print to stdout (handy for piping into codegen tools)
python manage.py graphql_schema --out -

# Override the JSON indent (ignored for SDL)
python manage.py graphql_schema --indent 4

# Export a specific schema instead of DJANGO_GRAPHEX["SCHEMA"]
python manage.py graphql_schema --schema myapp.schema.schema
```

| Option | Alias | Description |
|---|---|---|
| `--out <path>` | `-o` | Output file path; overrides `SCHEMA_OUTPUT`. Use `-` for stdout. A `.graphql` / `.gql` extension writes SDL instead of introspection JSON. |
| `--indent <int>` | `-i` | JSON indentation; overrides `SCHEMA_INDENT` (default `2`). Ignored for SDL output. |
| `--schema <dotted.path>` | | Dotted path to the schema (a `DjangoGraphQLSchema`) to export; overrides `SCHEMA`. |

**JSON vs SDL.** The output format is chosen by the file extension: `.json` (or
stdout, or any non-SDL extension) writes **introspection JSON**, while
`.graphql` / `.gql` writes **SDL** (via graphql-core `print_schema`). The
introspection JSON is wrapped as `{"data": <introspection>}` — the same shape
graphene-django produced — so existing client codegen keeps working unchanged.

When neither `DJANGO_GRAPHEX["SCHEMA"]` is set nor `--schema` is passed, the
command raises a `CommandError` with an actionable message.

!!! note "Migration path"

    `SCHEMA_OUTPUT` and `SCHEMA_INDENT` are the same keys graphene-django read
    under its `GRAPHENE` namespace. In django-graphex they live inside
    `DJANGO_GRAPHEX`, and `graphql_schema` consumes them the same way.

## How settings are read

`DJANGO_GRAPHEX` is read through a small self-contained reader (no DRF
dependency). Changes are picked up automatically in tests via Django's
`setting_changed` signal, so `@override_settings(DJANGO_GRAPHEX={...})`
works as expected. Reading a setting name that does not exist raises
`AttributeError` to catch typos early.

`MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE`, `DOCUMENT_CACHE_MAXSIZE`, and
`DOCUMENT_CACHE_MAX_QUERY_LENGTH` reject negative integers with `ImproperlyConfigured` when each setting is read, not
at Django startup. The error names the setting, rejected value, minimum of
zero, and remedy. Their existing `0`, `None`, positive, and default behaviors
are unchanged; this is not a general setting-type validator. The newer limits
`DOCUMENT_CACHE_MAX_QUERY_LENGTH`, `OPTIMIZER_WORK_BUDGET` and
`MAX_DIRECTIVE_OUTPUT_TOTAL` additionally require an integer or `None`: a string
such as `"65536"` or a boolean raises `ImproperlyConfigured` when read.

## Typos in the `DJANGO_GRAPHEX` dict

A key the library does not know is **ignored**: the setting it was meant to
configure silently keeps its default. A misspelled cap or security flag
therefore does nothing at all — `"MAX_PAGE_SIZ": 10` leaves `MAX_PAGE_SIZE` at
`None` (no cap), and `"CACHE_ACTIV": True` leaves the response cache off.

django-graphex registers a Django system check (`django_graphex.W001`,
`Tags.compatibility`) that compares your keys against the known settings and
suggests the closest match, so `manage.py check` catches it:

```console
$ python manage.py check
WARNINGS:
?: (django_graphex.W001) Unknown DJANGO_GRAPHEX setting(s) ['CACHE_ACTIV', 'MAX_PAGE_SIZ'].
  They are IGNORED, so the setting they were meant to configure keeps its default.
	HINT: 'CACHE_ACTIV' -> did you mean 'CACHE_ACTIVE'? 'MAX_PAGE_SIZ' -> did you mean 'MAX_PAGE_SIZE'?
```

It is a warning, never an exception, so it cannot break an app that starts
today. Silence it — after checking the key really is meant for something else —
with `SILENCED_SYSTEM_CHECKS = ["django_graphex.W001"]`.
