# SPEC — Consolidate views: BaseGraphQLView / GraphQLView / AuthenticatedGraphQLView

Status: accepted
Branch: `views-refactor` (off `polish`)
Type: breaking (view rename) + additive (auth view, graphiql template override)

## Motivation

Today the GraphQL view lives in two files with names that don't reflect their
roles: `_view.py` holds the vendored base `GraphQLView` (the graphene-django fork)
and `views.py` holds `ExtraGraphQLView` (our enhanced view: caching, depth/cost
rules, cost exposure). Consolidate and rename for clarity, add a custom-auth view,
and make the GraphiQL page overridable for offline/CSP setups.

## Changes

### 1. Merge `_view.py` into `views.py` + rename
- `_view.GraphQLView` (the forked base) → **`BaseGraphQLView`**, moved into `views.py`.
- `views.ExtraGraphQLView` (the enhanced one) → **`GraphQLView`** (`BaseGraphQLView`
  subclass). Keeps caching + `DepthLimitValidationRule`/`CostLimitValidationRule`
  + `extensions.cost`.
- Delete `_view.py`.
- `subscriptions/views.py`: `from .._view import GraphQLView` →
  `from ..views import BaseGraphQLView`; `SubscriptionGraphQLView(BaseGraphQLView)`.
- Clean break (no alias): `ExtraGraphQLView` is removed. It is not a top-level
  export, so the break is contained to `graphene_django_extras.views`.
- Export `BaseGraphQLView`, `GraphQLView`, `AuthenticatedGraphQLView` from the
  package `__init__` (views were previously not exported; the recommended
  `GraphQLView` should be importable top-level).

### 2. `AuthenticatedGraphQLView(GraphQLView)` — custom auth, no DRF
- A view that locks the whole endpoint behind the library's own permission
  classes (`BasePermission` subclasses like `IsAuthenticated`), with **no DRF**.
- `permission_classes` class attribute (default `(IsAuthenticated,)`), overridable
  per `as_view`/subclass.
- Enforced in `dispatch`: build a minimal `info`-like object
  (`SimpleNamespace(context=request)`) and call each permission's
  `has_permission(info)` — reusing the existing resolver-level permission infra
  (they already read `info.context.user`). On failure → `HttpResponse(status=403)`
  (or 401 for unauthenticated; use 403 to match the existing permission semantics).
- No authentication backends / no throttling in this iteration (throttling is a
  separate future feature). Authentication is whatever Django middleware already
  populated on `request.user`.
- Coarse, endpoint-level gate; complements the finer-grained
  `AuthenticatedFieldsMiddleware` / `ExtraGraphQLSchema` / type `permission_classes`.

### 3. GraphiQL: keep the CDN page as default, add a template override
- Default `render_graphiql` keeps returning the self-contained **CDN** HTML
  (unchanged behavior).
- Add a `graphiql_template: str | None = None` view option (class attr +
  `as_view` kwarg). When set, `render_graphiql` renders that Django template
  (via the normal template loaders) instead of the CDN string, passing a small
  context (at least the endpoint path; `request` is available via context
  processors) so the template can wire the fetcher and reference its OWN static
  assets with `{% static %}`.
- This gives offline/CSP users a path: ship your own assets + template and point
  the view at it in `urls.py`, without the package vendoring ~1 MB of JS.

```python
# urls.py
path("graphql", GraphQLView.as_view(graphiql=True,
                                     graphiql_template="myapp/graphiql.html"))
```

## Out of scope
- Vendoring/bundling GraphiQL assets (rejected in favour of the template hook).
- Throttling / authentication backends on the auth view.

## Acceptance
- AC1: `BaseGraphQLView`, `GraphQLView`, `AuthenticatedGraphQLView` importable from
  `graphene_django_extras` and `graphene_django_extras.views`; `_view.py` gone;
  `ExtraGraphQLView` no longer exists.
- AC2: `SubscriptionGraphQLView` still works (extends `BaseGraphQLView`).
- AC3: `AuthenticatedGraphQLView` returns 403 for an unauthenticated request and
  passes it through for an authenticated one; honors a custom `permission_classes`.
- AC4: with `graphiql=True` and no template → the CDN page (unchanged); with
  `graphiql_template=...` → the custom template is rendered.
- AC5: full suite green (DRF + django-filter uninstalled), ruff + mypy clean; tests
  and `tests/urls.py` updated to the new names; docs/changelog updated.

## Commits
1. `docs: SPEC — consolidate views (Base/GraphQLView/Authenticated + graphiql template)`
2. `refactor!: merge _view into views; BaseGraphQLView + GraphQLView + AuthenticatedGraphQLView + graphiql_template`
3. `docs: views guide + migration/changelog`
