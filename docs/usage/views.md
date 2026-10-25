# Views

The package ships three GraphQL views, all imported from `django_graphex.views`:

| View | Use it for |
|---|---|
| **`GraphQLView`** | The recommended view: response caching, query depth/cost validation rules and the `extensions.cost` payload. |
| **`BaseGraphQLView`** | A minimal, self-contained GraphQL view (vendored — no graphene-django dependency, no enhancements). Subclass it for a bare endpoint. |
| **`AuthenticatedGraphQLView`** | `GraphQLView` plus an endpoint-level auth gate (the library's own permission classes — no DRF). |

## Wiring the endpoint

```python
# urls.py
from django.urls import path
from django_graphex.views import GraphQLView

urlpatterns = [
    path("graphql", GraphQLView.as_view(graphiql=True)),
]
```

`GraphQLView` reads the `DJANGO_GRAPHEX["SCHEMA"]` setting by default, or pass
`schema=` explicitly. It enables the depth and cost validation rules
automatically (no-ops until `MAX_QUERY_DEPTH` / `MAX_QUERY_COST` are set — see
[Query depth & cost limits](query-limits.md)) and response caching when
`CACHE_ACTIVE` is on (see [Settings](settings.md)).

All three views validate their configuration when a view instance is
constructed. The schema must expose `graphql_schema`, and `graphiql=True`
cannot be combined with `batch=True`. Either mistake raises the same
`AssertionError` and message under ordinary and optimized (`python -O`)
Python. This applies when the instance is constructed; calling `as_view()`
alone does not promise an eager startup check. It does not imply that every
library assertion or application configuration is validated under `-O`.

### Custom execution backend

Pass `executor_class=YourBackend` to a view constructor or `as_view()` to
customize GraphQL execution. The older `execution_context_class=` spelling
remains an alias; if both are supplied, they must name the same class or view
construction raises `ImproperlyConfigured`. A class attribute may set the same
default for a view subclass. An explicit constructor or `as_view()` argument
overrides that default regardless of which alias the subclass used.

The backend class itself must match the installed GraphQL-core generation:
subclass `ExecutionContext` on 3.2, or `Executor` on 3.3. Custom 3.2 subclasses
need to be ported to the [3.3 Executor API](https://github.com/graphql-python/graphql-core/releases/tag/v3.3.0);
renaming the view keyword alone does not make them compatible. The runtime
dependency floor is now 3.3 for current source; custom backends must be ported.

On GraphQL-core 3.3, the HTTP view supplies the executor's async-iterable
predicate so a Django queryset, which implements both iterator protocols,
continues through synchronous list completion. This keeps queryset evaluation
inside the request's thread and any atomic mutation block. Results that are
async iterable but not synchronously iterable retain GraphQL-core's async
classification; this does not add general async-resolver support to the
synchronous HTTP view. Custom executor classes must accept the native 3.3
predicate argument when used with this view.

All three built-in HTTP views execute synchronously. If a resolver, middleware,
or execution backend supplies an awaitable, the view refuses it with HTTP 500
and a GraphQL JSON error rather than running it in an event loop:

```json
{
  "errors": [{
    "message": "Async execution is not supported by this HTTP view. Use synchronous resolvers and middleware."
  }]
}
```

New unstarted coroutines owned by that execution are closed without running
their bodies. Change the endpoint's resolvers and middleware to synchronous
implementations; changing a setting or awaiting the response is not a fix.
This refusal does not add async HTTP support or change the asynchronous SSE and
WebSocket subscription transports. A request that needs async execution is a
server integration error, not an ordinary client validation error.

### Production execution errors

With Django `DEBUG=False`, the default formatter on all three HTTP views
replaces **unexpected resolver exceptions** with a safe category and an opaque
`errorId`. For example, a `django.db.DatabaseError` produces:

```json
{
  "data": {"failure": null},
  "errors": [{
    "message": "Unable to complete the data operation.",
    "locations": [{"line": 1, "column": 3}],
    "path": ["failure"],
    "extensions": {
      "code": "DATA_ACCESS_ERROR",
      "errorId": "0123456789abcdef0123456789abcdef"
    }
  }]
}
```

The ID is a fresh, random 32-character hex value, not a public lookup key.
Use it to find the matching exception and traceback in the
`django_graphex.internal_errors` server logger. Restrict access to that logger:
its traceback can contain sensitive exception text. The library does not add
request bodies, variables, headers, cookies, or credentials to this log record.
If a logging handler fails, the HTTP response stays safe, but that particular
ID may have no matching log record.

Only `DatabaseError` and subclasses use `DATA_ACCESS_ERROR`; other unexpected
exceptions use `INTERNAL_SERVER_ERROR` and `An internal error occurred.`
The categories never include SQL, constraint names, exception text, or
untrusted exception extensions. If a message is intentionally safe for clients,
raise `GraphQLError` explicitly rather than a raw `ValueError`. Deliberate
`GraphQLError`, native validation and request errors, and the generated
mutation's existing generic/structured errors retain their contracts.

The classification is by phase. A custom scalar whose `parse_value` or
`parse_literal` raises `ValueError`/`TypeError` while the document is validated
or the variables are coerced is invalid client input, not an internal error:
the request gets HTTP 400 with graphql-core's validation message (for example
`Expected value of type 'MyDate'; found "garbage".` or `Variable '$v' has
invalid value ...`), without the raw exception text and without an ERROR log
record. With `DEBUG=True` the full message, cause text included, is kept. A
`ValueError` raised during execution (resolvers, output serialization) is still
masked and logged as described above. Only `ValueError`, `TypeError` and
`GraphQLError` mean invalid input: any other exception a scalar raises while
coercing (a database error, say) is a server fault and is masked and logged
too.

GraphQL `locations`, `path`, null propagation, and rollback are unchanged.
For the current JSON endpoint, a field execution error returns HTTP 200 with
`errors` and a `data` member, even when a non-null root field makes `data`
`null`. For example, a failed `{ required }` request can return
`{"data": null, "errors": [{"message": "Execution stopped.", "path": ["required"]}]}`.
Syntax, validation, and variable-coercion errors remain HTTP 400 without a
`data` member. A server fault outside field execution (for example a failing
`get_root_value` hook) is masked as above and answers HTTP 500 instead of 400.
A `query` that is not a string, or `variables` that are not a JSON object, answer
HTTP 400 (`Must provide query string.` / `Variables must be a JSON object.`)
without an ERROR log. An HTTP 200 response containing errors is not cached; a
repeated request runs again. Clients must inspect `errors`, not only status.
`DEBUG=True`, the shared subscription formatter
used by WebSocket/SSE, and subclasses that override `format_error` retain
their previous behavior; review a custom override's own production policy.

### Custom AST builders

GraphQL-core 3.3 makes parsed AST nodes immutable and requires their fields at
construction. If an extension builds inline fragments for query analysis, pass
`type_condition` and `selection_set` into `InlineFragmentNode(...)` rather
than assigning them afterward. Use a tuple for `SelectionSetNode(selections=...)`;
the built-in optimizer already reads both parsed and constructed fragments
without mutating them. When evaluating directives directly against
GraphQL-core 3.3, pass its native variable-values object rather than a plain
dict. Test the resulting schema queries with valid variables, defaults, and
invalid inputs when porting custom extensions. Published 3.1.1 still retains
the historical 3.2 requirement; this current-source migration is not a new
package release.

### Cross-site POST protection

`GraphQLView` and `AuthenticatedGraphQLView` are `csrf_exempt` (`BaseGraphQLView`
is not — mount it behind Django's own CSRF middleware, or exempt it yourself).
On all three, a POST whose content type a browser can send cross-site **without
a CORS preflight** must carry the `X-Requested-With` header or it is refused
with HTTP 403 before its body is read. That set is
`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`, and a
body-less POST with no content type at all. `application/json` and
`application/graphql` already force a preflight and are never asked for it, so
JSON clients change nothing. The SSE subscription endpoint is guarded by the
same setting. Turn it off with `REQUIRE_CSRF_HEADER=False` — see
[Security → Cross-site POST protection](security.md#cross-site-post-protection).

### Response caching and cache identity

With `CACHE_ACTIVE` on, `GraphQLView` caches eligible **HTTP 200 GraphQL data
responses without errors** (never mutations, batches, multipart,
cookie-bearing queries or a GraphiQL render). Execution errors, including
top-level `data: null`, and validation failures are returned normally but not
cached; old cached
failures are ignored so a repeated request can recover. See
[successful responses only](caching.md#successful-responses-only).
Every entry is
namespaced by a **cache identity** from `cache_key_prefix`:

| Request | Identity |
|---|---|
| Authenticated | `u<pk>` |
| Anonymous with an `Authorization` header | `t<sha256 of the header, 16 hex>` |
| Anonymous with no credential or cookies | `anon` |

Two callers with different identities never share a response entry, which is
what keeps one caller's body from being served to another. Override
`cache_key_prefix` to partition on something else (a session key, a tenant id).

Cookie-bearing queries bypass the response cache by default. Anonymous does
**not** imply public: session carts, tenants, locale and feature flags often live
in cookies and are invisible to the default key. Override `should_cache_query`
only when you either keep the stricter default or fold every contextual value
into `cache_key_prefix` / `fetch_cache_key`. Cookie-bearing mutations still
invalidate cached reads after their execution.

Invalidation uses a **version counter** instead of calling `cache.clear()`, so it
never flushes unrelated application keys. The default
`CACHE_INVALIDATION_SCOPE="global"` shares that counter across GraphQL response
identities: a mutation by one caller invalidates cached reads for all callers.
Responses remain isolated by their full identity.

`CACHE_INVALIDATION_SCOPE="identity"` opts into the narrower 3.0 policy, where
a mutation advances only the issuing caller's counter. Use it only when writes
cannot affect shared data. Under that policy, the counter is stored permanently
— it has to outlive the responses it namespaces — and a permanent key whose
name an unauthenticated caller picks is a leak, since the `Authorization` header
is unverified input that a client can vary per request.

In identity scope the counter's namespace is **bucketed for unauthenticated identities**: a
fixed number of buckets (64), never one per credential. Authenticated callers
(bounded by your user table) and the single shared `anon` partition keep their
exact namespace. The trade is deliberate:

- **Kept** — isolation. The response entry still carries the *full* identity, so
  sharing a bucket never means sharing a response.
- **Spent** — invalidation locality among unauthenticated callers. Sharing a
  counter means one caller's mutation can advance another's namespace, which
  costs a cache miss and a re-read of current data. The counter only moves
  forward, so no stale entry is ever resurrected.

A custom `cache_key_prefix` inherits this automatically: any identity it returns
for an unauthenticated request is bucketed, because the rule is about what an
unauthenticated caller can vary, not about the token shape this view emits.

!!! note "Response entries are still per-credential"

    Only the permanent counter is bucketed. Response bodies stay keyed by the
    full identity and expire on `CACHE_TIMEOUT`, so an anonymous flood of
    credentials is ordinary cache pressure your backend evicts — unless you set
    `CACHE_TIMEOUT=None`, which makes *every* cached response permanent. Don't,
    on a public endpoint.

## Endpoint-level auth: `AuthenticatedGraphQLView`

A coarse gate that requires every request to satisfy the view's
`permission_classes` — the same [permission classes](permissions.md)
(`IsAuthenticated`, `IsAdmin`, …) used at the resolver level, evaluated against
`request.user`. No DRF involved.

```python
from django_graphex.views import AuthenticatedGraphQLView
from django_graphex.permissions import IsAdmin

urlpatterns = [
    # default: must be authenticated
    path("graphql", AuthenticatedGraphQLView.as_view(graphiql=True)),
    # or require an admin for the whole endpoint
    path("admin/graphql",
         AuthenticatedGraphQLView.as_view(permission_classes=(IsAdmin,))),
]
```

A failing request gets a `403` with a JSON `errors` body before any resolver runs.

### Restricting the endpoint to a group: `API_ACCESS_GROUP`

On top of `permission_classes`, `AuthenticatedGraphQLView` honors the
`API_ACCESS_GROUP` [setting](settings.md#security). Set it to a Django auth
`Group` name to lock the **authenticated endpoint** to that group's members:

```python
DJANGO_GRAPHEX = {
    "API_ACCESS_GROUP": "api-users",  # "" (default) = gate off
}
```

Semantics:

- **Empty string (default)** — the gate is inert; behavior is exactly as without
  the setting.
- **Non-empty** — a request whose user is not a member of the named group is
  rejected with the same generic `403` (`"You do not have permission to access
  this endpoint."`) **before any GraphQL parsing or execution**. The message
  never mentions the group, so the requirement isn't leaked.
- **Active superuser bypass (invariant)** — an active superuser always passes,
  regardless of group membership. This is hardcoded, not configurable.
- **Fail-closed** — a missing or anonymous user is denied even though the default
  `permission_classes=(IsAuthenticated,)` would usually block them first; the
  gate is self-sufficient and survives `permission_classes` overrides.
- The gate applies **only** to `AuthenticatedGraphQLView`. The public
  `GraphQLView` is **not** affected.

### Permission-scoped schema: `PERMISSION_SCOPED_SCHEMA`

Beyond the coarse endpoint gate, `AuthenticatedGraphQLView` can serve **each
authenticated request a schema pruned to that caller's permissions**. Enable it
with the [`PERMISSION_SCOPED_SCHEMA`](settings.md#security) setting (default
`False` — the feature is fully inert until you turn it on):

```python
DJANGO_GRAPHEX = {
    "PERMISSION_SCOPED_SCHEMA": True,  # prune each authed request's schema
}
```

It requires a [labeled `DjangoGraphQLSchema`](security.md) — the schema stamps
each generated CRUD field (and each explicit `field(required_perms=...)`) with
the perms it needs, so the view can drop what the caller lacks.

Semantics:

- **Per-request pruning** — a field whose required perms the caller does **not**
  hold is **absent** from their schema. Selecting it fails validation with a
  native `Cannot query field "…"` — a *not-found*, never an authorization error,
  so the response never leaks that the field exists. Both **validation and
  execution** run against the pruned schema.
- **Empty pruned root ⇒ generic 403** — if pruning removes *every* field from a
  caller's `Query` root, the request gets the endpoint's existing generic `403`
  (`"You do not have permission to access this endpoint."`), raised **before**
  execution. The message is byte-identical to the `permission_classes` /
  `API_ACCESS_GROUP` denials, so an empty schema is indistinguishable from any
  other endpoint refusal.
- **Active superuser bypass (invariant)** — an active superuser always receives
  the **full** schema and **no permission signature is computed** for them.
- **Public view untouched** — the public `GraphQLView` is **never** pruned,
  regardless of the flag.
- **Read per-request** — toggling the setting between two requests takes effect
  immediately (no restart); with it `False` (default) behavior is byte-identical
  to today.
- **Revoke-safe, cached** — pruned schemas are memoized in-process by the
  caller's *permission signature* (normally `perms ∩ schema label-set`, but all
  grants when the schema has a native flat GFK fallback), in a bounded LRU
  ([`PERMISSION_SCHEMA_CACHE_MAXSIZE`](settings.md#security), default `64`). The
  signature is recomputed from the user's live permissions each request, so a
  grant or revocation is reflected on their **next** request — never a stale
  schema. Response-cache entries also fold in the signature, so a low-permission
  caller can never read a high-permission caller's cached body for the same
  query.

For subscriptions, wire the same per-connection pruning with a `schema_provider`
on the WS/SSE transports — see [Subscriptions](subscriptions.md).

!!! tip "Coarse vs fine-grained"

    `AuthenticatedGraphQLView` locks the **whole endpoint**. For per-field auth
    (public + private fields on one endpoint), prefer the finer tools:
    `permission_classes` on a `DjangoModelType`, `AuthenticatedFieldsMiddleware`,
    or `DjangoGraphQLSchema` — see [Permissions](permissions.md) and
    [Security](security.md).

## GraphiQL

With `graphiql=True`, the view serves a self-contained GraphiQL page whose assets
load from a CDN — zero wiring, but it needs internet access and an
unpkg-friendly CSP.

For **offline / strict-CSP** setups, point the view at your own Django template
with `graphiql_template`; ship your own assets and reference them with
`{% static %}`:

```python
path("graphql", GraphQLView.as_view(
    graphiql=True,
    graphiql_template="myapp/graphiql.html",   # overrides the CDN page
))
```

The template is rendered with a small context: `endpoint` (the request path) and
`subscription_path`; `request` is available via the usual context processors.

The page is served when the client prefers `text/html` over `application/json`
in its `Accept` header. Quality values are honoured, with or without whitespace
after the semicolon — `Accept: text/html; q=0.1, application/json` and
`Accept: text/html;q=0.1, application/json` both get JSON. A client can also
force JSON with a `raw` query-string parameter (or a `raw` key in the body).

## Batch endpoints

With `batch=True` the endpoint expects a **JSON list of operations**, sent as
`Content-Type: application/json`:

```python
path("graphql/batch", GraphQLView.as_view(batch=True)),
```

Any other body shape — a bare object, `application/graphql`, form-encoded or
multipart — is rejected with **HTTP 400** and the message
`Batch requests should receive a list, but received ...`. Every entry in the
list must itself be a JSON object; one that is not (a bare number, string or
nested list) is rejected with **HTTP 400** and
`Batch entries should be JSON objects, but received ...`. See
[`MAX_BATCH_SIZE`](settings.md#http-view-hardening) for the per-request
operation cap.

For a valid batch, **every entry yields exactly one response entry, in request
order**. Nothing is skipped or dropped: an entry that fails (a request error such
as a missing query or malformed `variables`, a syntax or validation error, an
unknown `operationName`, or a field execution error) gets its own error entry
and the remaining entries still run. Each entry retains its `id` and `status`.
For example, if the second entry has no query:

```json
[
  {"data": {"add": "saved"}, "id": "first", "status": 200},
  {"errors": [{"message": "Must provide query string."}], "id": "second", "status": 400},
  {"data": {"add": "saved"}, "id": "third", "status": 200}
]
```

The HTTP status of the response is the highest entry `status`: **200** when
every entry is 200, **400** as soon as one entry is a request, syntax or
validation error. A field execution error is a 200 entry with `errors` (and
`data: null` when it nulls the operation data). Clients must read each entry's
`status` and `errors` instead of relying on the HTTP status alone.

A successful mutation stays committed whatever happens to its siblings.
`ATOMIC_MUTATIONS` applies per mutation, **not to the entire batch**. When
`ATOMIC_REQUESTS` is enabled for a database, each entry also runs in its own
savepoint inside the request transaction: an entry that reports an error rolls
back only its own writes, and never marks the request transaction for rollback,
so earlier and later entries still commit. A non-batched request keeps the
request-level rollback on any error. Malformed outer bodies, a batch larger than
`MAX_BATCH_SIZE` and non-object entries are rejected before any operation runs
and keep a single request-level error object; non-400 transport errors keep
their existing envelope.

Rollback covers **every database alias** that is inside a transaction opened for
the request: each alias with `ATOMIC_REQUESTS` enabled is rolled back (or, in a
batch, its entry savepoint is), and a mutation additionally runs in
`transaction.atomic()` on the default alias when `ATOMIC_MUTATIONS` is `True`
and on any alias whose `DATABASES[alias]["ATOMIC_MUTATIONS"]` is `True`. An
alias outside any atomic block is never touched, so its writes persist, and the
global setting alone still covers only the default alias.

## Request body size

With [`MAX_REQUEST_BODY_SIZE`](settings.md#file-uploads) set, `dispatch` refuses
an oversized POST with **HTTP 413** before the body is parsed. It checks the
declared `Content-Length` first, then measures the body itself — so a client
cannot under-declare its length to slip past. The check runs before Django's
CSRF check, which would otherwise parse a multipart body for any client holding
a `csrftoken` cookie, so an oversized upload is refused unparsed.

JSON that the decoder cannot parse returns **HTTP 400**, including when the
decoder raises a recursion error. This is parser-error handling, not a promise
that every JSON document above a fixed nesting depth will be rejected; Python
versions may accept different depths.

`multipart/form-data` is measured too, but by **seeking** the request stream to
its end and back rather than by reading it. Reading it would pull a streaming
upload into memory and break every request from a client holding the endpoint's
CSRF cookie; a seek does neither. Where the stream cannot be seeked (WSGI, whose
input is already capped at `Content-Length`) a multipart POST that declares no
length at all is refused with **HTTP 411** instead. See
[How the guard reads each content type](settings.md#how-the-guard-reads-each-content-type).

The separate [`MAX_UPLOAD_SIZE`](settings.md#file-uploads) setting checks each
received multipart file **after parsing**, including unused and repeated file
parts. A file above that limit returns JSON HTTP 413 before any resolver or
GraphiQL page succeeds. This per-file check does not replace the earlier
whole-body guard or impose an ingress/memory limit.

## Subscriptions

GraphQL subscriptions are served by a dedicated view (over Channels) — see the
[Subscriptions guide](subscriptions.md).
