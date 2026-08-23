# Security

`django-graphex` ships opt-in GraphQL security middlewares and a small
schema helper to declare which fields are private — so you can block
introspection and require authentication on selected fields without rewriting
your resolvers.

- [`DisableIntrospectionMiddleware`](#disable-introspection) — block schema
  introspection in production.
- [`AuthenticatedFieldsMiddleware`](#field-level-authentication) — require an
  authenticated user on selected top-level fields.
- [`DjangoGraphQLSchema`](#declaring-private-fields-djangographqlschema) — declare
  the private fields next to the schema, with no settings duplication.

!!! tip "Looking for depth & cost limits?"

    Query-shape limiters (`DepthLimitValidationRule`, `CostLimitValidationRule`,
    `Meta.max_depth`, `Meta.complexity`) now live on their own page —
    [Query depth & cost limits](query-limits.md).

Wire the middlewares through `DJANGO_GRAPHEX['MIDDLEWARE']`:

```python
DJANGO_GRAPHEX = {
    "SCHEMA": "myapp.schema.schema",
    "MIDDLEWARE": [
        "django_graphex.security.DisableIntrospectionMiddleware",
        "django_graphex.security.AuthenticatedFieldsMiddleware",
        "django_graphex.middleware.GraphQLDirectiveMiddleware",
    ],
}
```

## Disable introspection

`DisableIntrospectionMiddleware` blocks the introspection meta-fields `__schema`
and `__type` (so tools can't dump your schema), while leaving `__typename`
untouched.

```python
DJANGO_GRAPHEX = {
    "ALLOW_INTROSPECTION": False,            # default: block introspection
    "INTROSPECTION_ALLOW_SUPERUSER": True,   # default: active superusers may introspect
}
```

| Setting | Default | Effect |
|---------|---------|--------|
| `ALLOW_INTROSPECTION` | `False` | When `True`, introspection is allowed for everyone. |
| `INTROSPECTION_ALLOW_SUPERUSER` | `True` | When `True`, an **active** superuser (`is_active` **and** `is_superuser`) may introspect even if `ALLOW_INTROSPECTION` is `False`. |

A blocked introspection query returns an error; a missing `context`/`user`
(non-HTTP execution) is treated as non-superuser and does not crash. The bypass
requires an **active** account, exactly like every other superuser check in the
library ([`IsAdmin`](permissions.md), the endpoint gate and the
[permission-scoped schema](permission-scoped-schema.md)): deactivating a
superuser revokes it immediately, even on authentication backends that do not
run Django's `user_can_authenticate` check (token / JWT).

```graphql
query { __schema { queryType { name } } }
# -> error: "GraphQL introspection is disabled."
```

## Field-level authentication

`AuthenticatedFieldsMiddleware` requires an authenticated user
(`request.user.is_authenticated`) on the schema's **private** top-level fields,
raising a `GraphQLError` otherwise. It only enforces at the top level — nested
fields are never gated — and **nothing is protected unless you declare it**, so
adding the middleware is safe.

"Top level" is read from the **resolve path** (a top-level field has no parent
path segment), never from the root value: setting `root_value` on the view, as a
class attribute or through `get_root_value()` does **not** change what is gated,
and a field is still gated when it is reached through an inline fragment. A
selection nested under another field — including one inside a list element — is
not gated even if its name matches a protected top-level field.

The chain runs on **every** transport: the HTTP view, and — since 2.1.0 — the
SSE and WebSocket subscription transports, which build the same
`DJANGO_GRAPHEX['MIDDLEWARE']` chain once per connection and apply it both to
the subscribe entry (before any `group_add`) and to each delivered event.

!!! danger "Fixed in 2.1.0"
    In 2.0.0 `DJANGO_GRAPHEX['MIDDLEWARE']` was read only by `GraphQLView`.
    Subscriptions are served *only* by the SSE / WS transports, so the middleware
    never ran for them and `private_subscription` protected nothing: an
    `AnonymousUser` could subscribe to a field reported in
    `gdx_protected_fields` and receive its events.

!!! danger "Fixed after 2.1.0"
    Up to and including 2.1.0 the middleware used "the root value is not `None`"
    as its proxy for "this is a nested field". Because `root_value` is a public,
    documented seam, a view configured with one (`GraphQLView.as_view(...,
    root_value=...)`, the class attribute, or an overridden `get_root_value()`)
    lost **all** private-field protection: every protected field resolved for
    anonymous callers. The same proxy also skipped the gate on every delivered
    subscription event, since the event payload *is* the root value there.

A blocked field returns:

```json
{
  "errors": [{
    "message": "Authentication required.",
    "path": ["me"],
    "extensions": {"code": "UNAUTHENTICATED", "status_code": 401}
  }]
}
```

The private field set is resolved from, in order:

1. the registry attached by [`DjangoGraphQLSchema`](#declaring-private-fields-djangographqlschema)
   (recommended), or
2. `DJANGO_GRAPHEX["PROTECTED_FIELDS"]` — a list of top-level field names,
   for setups that don't use `DjangoGraphQLSchema`.

```python
# plain-schema setup, without DjangoGraphQLSchema
DJANGO_GRAPHEX = {"PROTECTED_FIELDS": ["me", "allOrders", "createOrder"]}
```

## Declaring private fields: `DjangoGraphQLSchema`

The cleanest way to declare what is private is right where you build the schema.
`DjangoGraphQLSchema` accepts `private_query`,
`private_mutation` and `private_subscription` (all optional, all symmetric). Each
`private_*` root is **unioned** into its operation root, so you keep public and
private fields in **separate** roots: the schema exposes the union, and the
private ones require auth. Field names are collected and attached automatically —
no settings, no naming conventions, always in sync with the schema.

```python
from graphql import GraphQLString
from django_graphex.directives import all_directives
from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.core.descriptors import NativeList

class PublicQueries(ObjectType):
    server_time = field(GraphQLString)

class PrivateQueries(ObjectType):
    me = field(UserType)
    all_orders = field(NativeList(OrderType))

schema = DjangoGraphQLSchema(
    query=PublicQueries,                      # public-only subset
    private_query=PrivateQueries,             # private-only subset (require auth)
    mutation=PublicMutations,
    private_mutation=PrivateMutations,        # optional
    subscription=PublicSubscriptions,
    private_subscription=PrivateSubscriptions,  # optional
    directives=all_directives,
)
```

The schema's actual query root is the **union** of `PublicQueries` and
`PrivateQueries` — you don't build a combined root yourself. Field names are
matched against `info.field_name` (camelCase under the default
`auto_camelcase=True`), so `all_orders` protects `allOrders`.

!!! tip "Per-app modularity"

    Each app can expose its own `Public*` / `Private*` subsets; at the project
    level aggregate them with multiple inheritance and pass the aggregates:

    ```python
    from django_graphex.core import ObjectType

    class RootSubscription(blog.PublicSubscriptions, shop.PublicSubscriptions,
                           ObjectType): pass
    class RootPrivateSubscription(blog.PrivateSubscriptions, shop.PrivateSubscriptions,
                                  ObjectType): pass
    ```

!!! note "Subscriptions are symmetric"

    Subscriptions are treated exactly like queries and mutations: **only** the
    fields in `private_subscription` are protected. A `subscription` without
    `private_subscription` protects nothing. (A single full root plus a
    `private_*` marker subset of names still works, for back-compat.)

    Enforcement is symmetric too: the SSE and WS transports run the configured
    middleware chain, so a declared-private subscription field is denied at
    subscribe time and on every delivered event. (Before 2.1.0 it was declared
    but never enforced — see the danger note above.)

!!! warning "Add the middleware"

    If you pass `private_query`/`private_mutation`/`private_subscription` but
    `AuthenticatedFieldsMiddleware` is **not** in `DJANGO_GRAPHEX['MIDDLEWARE']`,
    `DjangoGraphQLSchema` emits a `RuntimeWarning` — the private fields would
    otherwise go unprotected. (The check inspects `DJANGO_GRAPHEX['MIDDLEWARE']`;
    middleware wired only via the view is not detected.)

### Behavior matrix

| Middleware in `DJANGO_GRAPHEX['MIDDLEWARE']` | Schema declares private fields | Result |
|---|---|---|
| ✅ | ✅ | declared fields require auth |
| ✅ | ❌ | everything public |
| ❌ | ❌ | everything public |
| ❌ | ✅ | everything public **+ `RuntimeWarning`** |

## Customizing: helpers and override points

`AuthenticatedFieldsMiddleware` exposes two override points:

```python
from django_graphex.schema import collect_field_names
from django_graphex.security import AuthenticatedFieldsMiddleware

class MyAuthMiddleware(AuthenticatedFieldsMiddleware):
    def get_protected_fields(self, info):
        # build the set however you like (here, straight from your root types)
        from myapp.schema import PrivateQueries, PrivateMutations
        return collect_field_names(PrivateQueries, PrivateMutations)

    def get_error_extensions(self, info, user):
        ext = super().get_error_extensions(info, user)  # {"code": "UNAUTHENTICATED", ...}
        # enrich, e.g. surface a JWT failure reason your auth layer recorded
        reason = getattr(getattr(info, "context", None), "auth_failure_reason", None)
        if reason:
            ext["reason"] = reason
        return ext
```

- **`collect_field_names(*object_types, camelcase=True)`** — returns the camelCased
  field names of the given `ObjectType`s (from `ObjectType._meta.fields`).
- **`DenyAllRegistry`** — a fail-closed `frozenset` whose membership test is always
  `True`. Return it from `get_protected_fields` when your schema/registry can't be
  built, so a broken schema **fails closed** (every field requires auth) instead of
  silently exposing everything:

```python
from django_graphex.schema import DenyAllRegistry

try:
    PROTECTED = collect_field_names(PrivateQueries, PrivateMutations)
except Exception:
    PROTECTED = DenyAllRegistry()   # broken schema -> everything is private
```

## HTTP view hardening

### Batch request size limit

`BaseGraphQLView` (and its subclasses) enforce a per-request operation limit when
`batch=True` is set. Requests that exceed `MAX_BATCH_SIZE` are rejected with
**HTTP 400** before any operation is executed.

See [`MAX_BATCH_SIZE`](settings.md#http-view-hardening) in the settings reference.

### Endpoint access group (`API_ACCESS_GROUP`)

`AuthenticatedGraphQLView` can lock the **authenticated endpoint** to members of a
single Django auth `Group`. Set [`API_ACCESS_GROUP`](settings.md#security) to the
group name; non-members are rejected with a generic **HTTP 403** before any GraphQL
parsing or execution, and the message never reveals the group requirement. An
**active superuser always bypasses** the gate (hardcoded), and a missing/anonymous
user is denied (fail-closed). `""` (default) disables it, and the public
`GraphQLView` is **not** affected. See
[Views → Restricting the endpoint to a group](views.md#restricting-the-endpoint-to-a-group-api_access_group).

### Permission-scoped schema (`PERMISSION_SCOPED_SCHEMA`)

With [`PERMISSION_SCOPED_SCHEMA`](settings.md#security) enabled,
`AuthenticatedGraphQLView` serves **each authenticated request a schema pruned to
the caller's permissions** — a field the caller lacks perms for is *absent* from
their schema, not merely blocked at resolve time. This closes the **existence
leak** that resolver-level authorization leaves open: a blocked resolver still
reveals that the field exists (via an authorization error on a queryable field),
whereas a pruned field reads as a native `Cannot query field` — a *not-found*
indistinguishable from a typo.

Security model:

- **No existence leak** — pruned fields are gone from validation, so denials are
  *not-found* errors, never authorization errors. Nothing in any error path
  reveals a hidden field ever existed.
- **No cross-permission cache leak** — the pruned schema, the in-process schema
  cache, and the HTTP **response cache** are all keyed by the caller's
  *permission signature* (`perms ∩ schema label-set`). Two callers with different
  relevant perms never share a pruned schema or a cached response body for the
  same query.
- **Empty root ⇒ generic 403** — a caller whose entire `Query` root is pruned
  away gets the endpoint's generic `403`, byte-identical to the
  `permission_classes` / `API_ACCESS_GROUP` denials — an empty schema is
  indistinguishable from any other refusal.
- **Superuser & public-view invariants** — an active superuser always gets the
  full schema (no signature computed); the public `GraphQLView` is never pruned.
- **Revoke-safe** — the signature is recomputed from live permissions each
  request (never keyed by user id, never persisted to an external cache), so a
  revoked grant takes effect on the caller's next request.
- **Untagged = public** — a field with no `gdx_required_perms` label survives
  every signature, so an unlabeled schema is unaffected (byte-identical to today).

Requires a labeled [`DjangoGraphQLSchema`](#declaring-private-fields-djangographqlschema).
Default `False` is fully inert. See
[Views → Permission-scoped schema](views.md#permission-scoped-schema-permission_scoped_schema)
and, for subscriptions,
[Subscriptions → Per-connection schema](subscriptions.md).

!!! tip "End-to-end guide"

    For a worked, role-by-role walkthrough of the whole permission stack —
    pruned SDL per user, the exact denial responses, `DjangoModelPermissions`,
    `API_ACCESS_GROUP` and per-action subscription pruning — see the
    [Permission-scoped schema guide](permission-scoped-schema.md).

### GraphiQL CDN Subresource Integrity

When `graphiql=True`, the built-in CDN page (`GRAPHIQL_HTML`) loads React and
GraphiQL from [unpkg.com](https://unpkg.com) with:

- **Pinned patch versions** — URLs use exact `@X.Y.Z` versions, not floating
  major tags.
- **Subresource Integrity (SRI)** — every `<script>` and `<link>` tag carries an
  `integrity="sha384-…"` attribute that the browser verifies before evaluating the
  asset. A compromised CDN or unexpected version bump cannot inject malicious
  JavaScript without the browser rejecting the asset.

The pinned versions and SRI hashes are documented inline in `views.py`.
When upgrading to a newer React or GraphiQL release, recompute the hashes:

```bash
curl -sL <url> | openssl dgst -sha384 -binary | openssl base64 -A
# Prepend "sha384-" to the output.
```

To serve assets from your own infrastructure (offline / strict-CSP setups), point
the view at a custom template:

```python
GraphQLView.as_view(schema=schema, graphiql=True, graphiql_template="myapp/graphiql.html")
```

### AST-based introspection detection (`CLEAN_RESPONSE`)

When `CLEAN_RESPONSE=True` is set, `GraphQLView` passes the response data through
`clean_dict` to remove `null` fields. Introspection responses (`__schema` / `__type`
queries) are **exempt** — applying `clean_dict` to them would corrupt the payload
because many introspection fields legitimately return `null`.

The check is AST-based: a response is treated as introspection when **all**
top-level selections are `__schema` or `__type` fields, regardless of the
query's textual format. This correctly handles compact inline queries
(`{ __schema { types { name } } }`), differently-indented or re-formatted
clients, and `__type` queries.

## Query depth & cost limits

Two **validation rules** protect your API from over-nested or over-wide queries
(`Meta.max_depth`, `Meta.complexity`, `MAX_QUERY_DEPTH`, `MAX_QUERY_COST`,
`EXPOSE_QUERY_COST`). They are documented on their own page —
[Query depth & cost limits](query-limits.md).

## Error codes

Errors the library raises during execution carry a machine-readable
`extensions.code` so clients can branch on the failure type:

| Code | Raised by | HTTP `status_code` |
|------|-----------|--------------------|
| `UNAUTHENTICATED` | `AuthenticatedFieldsMiddleware` (private field, no user) | `401` |
| `PERMISSION_DENIED` | permission classes on `DjangoModelType` | `403` |
| `INTROSPECTION_DISABLED` | `DisableIntrospectionMiddleware` | `403` |
| `QUERY_TOO_DEEP` | `DepthLimitValidationRule` | — (validation) |
| `QUERY_TOO_COMPLEX` | `CostLimitValidationRule` | — (validation) |

```json
{ "errors": [{ "message": "Query exceeds the maximum nesting depth of 2 for 'CategoryGenericType'.",
               "extensions": { "code": "QUERY_TOO_DEEP" } }] }
```

!!! note "Two error shapes"

    These are GraphQL **execution** errors (top-level `errors` with
    `extensions.code`). Mutation **business** errors are different: a
    `DjangoModelType`/`DjangoModelMutation` returns `ok: false` and a
    structured `errors` list of `{ field, messages }` (e.g.
    `{ "field": "id", "messages": ["Author with id 9 does not exist."] }`) — the
    operation itself succeeds, the payload reports the validation outcome.
