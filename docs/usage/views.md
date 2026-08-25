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
  caller's *permission signature* (`perms ∩ schema label-set`), in a bounded LRU
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

## Subscriptions

GraphQL subscriptions are served by a dedicated view (over Channels) — see the
[Subscriptions guide](subscriptions.md).
