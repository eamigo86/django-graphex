# Views

The package ships three GraphQL views (all in `django_graphex.views`, also
exported at the top level):

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
from django_graphex import IsAdmin

urlpatterns = [
    # default: must be authenticated
    path("graphql", AuthenticatedGraphQLView.as_view(graphiql=True)),
    # or require an admin for the whole endpoint
    path("admin/graphql",
         AuthenticatedGraphQLView.as_view(permission_classes=(IsAdmin,))),
]
```

A failing request gets a `403` with a JSON `errors` body before any resolver runs.

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

## Subscriptions

GraphQL subscriptions are served by a dedicated view (over Channels) — see the
[Subscriptions guide](subscriptions.md).
