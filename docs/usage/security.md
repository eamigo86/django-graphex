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
    `Meta.max_deep`, `Meta.complexity`) now live on their own page —
    [Query depth & cost limits](query-limits.md).

Wire the middlewares through `GRAPHENE['MIDDLEWARE']`:

```python
GRAPHENE = {
    "SCHEMA": "myapp.schema.schema",
    "MIDDLEWARE": [
        "django_graphex.DisableIntrospectionMiddleware",
        "django_graphex.AuthenticatedFieldsMiddleware",
        "django_graphex.GraphQLDirectiveMiddleware",
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
    "INTROSPECTION_ALLOW_SUPERUSER": True,   # default: superusers may introspect
}
```

| Setting | Default | Effect |
|---------|---------|--------|
| `ALLOW_INTROSPECTION` | `False` | When `True`, introspection is allowed for everyone. |
| `INTROSPECTION_ALLOW_SUPERUSER` | `True` | When `True`, a superuser may introspect even if `ALLOW_INTROSPECTION` is `False`. |

A blocked introspection query returns an error; a missing `context`/`user`
(non-HTTP execution) is treated as non-superuser and does not crash.

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
   for plain `graphene.Schema` setups.

```python
# plain-schema setup, without DjangoGraphQLSchema
DJANGO_GRAPHEX = {"PROTECTED_FIELDS": ["me", "allOrders", "createOrder"]}
```

## Declaring private fields: `DjangoGraphQLSchema`

The cleanest way to declare what is private is right where you build the schema.
`DjangoGraphQLSchema` is a `graphene.Schema` subclass that accepts `private_query`,
`private_mutation` and `private_subscription` (all optional, all symmetric). Each
`private_*` root is **unioned** into its operation root, so you keep public and
private fields in **separate** roots: the schema exposes the union, and the
private ones require auth. Field names are collected and attached automatically —
no settings, no naming conventions, always in sync with the schema.

```python
import graphene
from django_graphex import DjangoGraphQLSchema, all_directives

class PublicQueries(graphene.ObjectType):
    server_time = graphene.String()

class PrivateQueries(graphene.ObjectType):
    me = graphene.Field(UserType)
    all_orders = graphene.List(OrderType)

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
    class RootSubscription(blog.PublicSubscriptions, shop.PublicSubscriptions,
                           graphene.ObjectType): pass
    class RootPrivateSubscription(blog.PrivateSubscriptions, shop.PrivateSubscriptions,
                                  graphene.ObjectType): pass
    ```

!!! note "Subscriptions are symmetric"

    Subscriptions are treated exactly like queries and mutations: **only** the
    fields in `private_subscription` are protected. A `subscription` without
    `private_subscription` protects nothing. (A single full root plus a
    `private_*` marker subset of names still works, for back-compat.)

!!! warning "Add the middleware"

    If you pass `private_query`/`private_mutation`/`private_subscription` but
    `AuthenticatedFieldsMiddleware` is **not** in `GRAPHENE['MIDDLEWARE']`,
    `DjangoGraphQLSchema` emits a `RuntimeWarning` — the private fields would
    otherwise go unprotected. (The check inspects `GRAPHENE['MIDDLEWARE']`;
    middleware wired only via `schema.execute(middleware=…)` or the view is not
    detected.)

### Behavior matrix

| Middleware in `GRAPHENE['MIDDLEWARE']` | Schema declares private fields | Result |
|---|---|---|
| ✅ | ✅ | declared fields require auth |
| ✅ | ❌ | everything public |
| ❌ | ❌ | everything public |
| ❌ | ✅ | everything public **+ `RuntimeWarning`** |

## Customizing: helpers and override points

`AuthenticatedFieldsMiddleware` exposes two override points:

```python
from django_graphex import AuthenticatedFieldsMiddleware, collect_field_names

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
  field names of the given graphene `ObjectType`s (from `ObjectType._meta.fields`).
- **`DenyAllRegistry`** — a fail-closed `frozenset` whose membership test is always
  `True`. Return it from `get_protected_fields` when your schema/registry can't be
  built, so a broken schema **fails closed** (every field requires auth) instead of
  silently exposing everything:

```python
from django_graphex import DenyAllRegistry

try:
    PROTECTED = collect_field_names(PrivateQueries, PrivateMutations)
except Exception:
    PROTECTED = DenyAllRegistry()   # broken schema -> everything is private
```

## Query depth & cost limits

Two **validation rules** protect your API from over-nested or over-wide queries
(`Meta.max_deep`, `Meta.complexity`, `MAX_QUERY_DEPTH`, `MAX_QUERY_COST`,
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
{ "errors": [{ "message": "Query exceeds the maximum nesting depth of 2 for 'RentalCompany'.",
               "extensions": { "code": "QUERY_TOO_DEEP" } }] }
```

!!! note "Two error shapes"

    These are GraphQL **execution** errors (top-level `errors` with
    `extensions.code`). Mutation **business** errors are different: a
    `DjangoModelType`/`DjangoModelMutation` returns `ok: false` and a
    structured `errors` list of `{ field, messages }` (e.g.
    `{ "field": "id", "messages": ["Author with id 9 does not exist."] }`) — the
    operation itself succeeds, the payload reports the validation outcome.
