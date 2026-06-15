# Migration Guide

`django-graphex` is a near-complete rewrite and the successor to
`graphene-django-extras`. This guide walks you, step by step, from the old library
to the new one.

> **Coming from plain `graphene-django` instead?** `django-graphex` replaces it
> together with `django-filter` and Django REST Framework — there is no separate
> "extras" layer. The type, mutation, filtering and pagination concepts below map
> directly; you can simply skip the DRF-serializer notes.

!!! info "New name & import path"

    | | Old | New |
    |---|---|---|
    | **Install** | `pip install graphene-django-extras` | `pip install django-graphex` |
    | **Import** | `import graphene_django_extras` | `import django_graphex` |
    | **Settings dict** | `GRAPHENE_DJANGO_EXTRAS = {…}` | `DJANGO_GRAPHEX = {…}` |

    In the before/after snippets below, the **Before** code uses the old
    `graphene_django_extras` import and the **After** code uses the new
    `django_graphex` import. Repo: <https://github.com/eamigo86/django-graphex>.

## Migrating from `graphene-django-extras` to `django-graphex`

### Breaking Changes

#### 1. Python and Django Support

!!! warning "Runtime Requirements"
    django-graphex requires **Python 3.12+** (3.12, 3.13, 3.14) and **Django 5.2 (LTS) or 6.0**.
    Django 4.2, 5.0 and 5.1 are EOL and no longer supported as of v1.3.0.
    It depends on **graphene >=3.3,<4** directly (the
    `graphene-django` dependency was dropped) and **pydantic >=2,<3**.
    Each Django version is tested on the Python versions it officially supports.

#### 2. Django REST Framework removed — use `Meta.model`

!!! danger "DRF is gone"
    `djangorestframework` is no longer a dependency (not even an optional extra),
    and `Meta.serializer_class` is no longer supported. Types, mutations and
    subscriptions are now backed by `Meta.model`, validated with **Pydantic v2**.

The class was also **renamed** (no serializer anymore):

- `DjangoSerializerType` → **`DjangoModelType`**
- `DjangoSerializerMutation` → **`DjangoModelMutation`**

The old names were removed with no alias — update your imports and base classes.

Replace the serializer with the model:

```python
# Before (graphene-django-extras): DRF serializer backend
from rest_framework import serializers
from graphene_django_extras import DjangoSerializerType

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]

class UserType(DjangoSerializerType):
    class Meta:
        serializer_class = UserSerializer

# After (django-graphex): native (Pydantic) backend
from django_graphex import DjangoModelType

class UserType(DjangoModelType):
    class Meta:
        model = User
```

- **Custom validation** moves off the serializer. Either declare inline
  validators directly on the class (`validate_<field>(self, value)` and an
  object-level `validate(self, data)`), or pass a Pydantic model as
  `Meta.pydantic_model`. See [Model backend (Pydantic)](usage/backends.md).
- **Nested writes**: `Meta.nested_fields` values are now Django **model classes**
  (not DRF serializers).
- **The DRF-based `AuthenticatedGraphQLView` (a DRF `APIView`) was removed.** A new,
  DRF-free `AuthenticatedGraphQLView` exists (see view rename below) that gates the
  endpoint with the library's own permission classes.

#### 3. Views consolidated and renamed

The two view modules were merged into `django_graphex.views` and renamed:

| Before (graphene-django-extras) | Now (django-graphex) |
|---|---|
| `ExtraGraphQLView` (enhanced view) | **`GraphQLView`** |
| internal `_view.GraphQLView` (base) | **`BaseGraphQLView`** |
| — | **`AuthenticatedGraphQLView`** (new, DRF-free endpoint auth gate) |

```python
# Before
from graphene_django_extras.views import ExtraGraphQLView
path("graphql", ExtraGraphQLView.as_view(graphiql=True))

# After
from django_graphex import GraphQLView   # also top-level now
path("graphql", GraphQLView.as_view(graphiql=True))
```

`GraphQLView` also gains a `graphiql_template` option to override the default CDN
GraphiQL page for offline/CSP setups. See [Views](usage/views.md).

#### 4. Nested lists always return `results` / `totalCount`

Nested list fields now always expose the uniform `results` / `totalCount` shape
(and can be filtered, paginated and ordered). Update any query that read a nested
relation as a plain list:

```graphql
# Before (graphene-django-extras): nested relation as a plain list
{ authors { results { name posts { title } } } }

# After (django-graphex): nested relation is a full list
{ authors { results { name posts { totalCount results { title } } } } }
```

See [Nested Lists](usage/nested-lists.md) for details.

#### 5. Subscriptions now live in this package

Subscription support is shipped here again as the optional `[subscriptions]`
extra over Django Channels 4. The standalone `graphene-django-subscriptions`
package is now a deprecated shim that re-exports from here, so you can drop it.

```bash
pip install "django-graphex[subscriptions]"
```

The migration shims for the **old standalone package's API are not carried over**
(this is a fresh implementation, not a compatibility layer). In v2.0 the legacy
bespoke transport was replaced by native SSE + `graphql-transport-ws`:

- `depromise_subscription` middleware → removed; serve subscriptions with the
  native transports (`subscription_sse_view` / `subscription_ws_consumer`).
- the demultiplexer consumer + HTTP `channelId` handshake → removed; route the
  native WebSocket consumer and/or mount the SSE view instead.
- `SubscriptionBinding.consumer` alias → use `.subscription_cls`.

Subscriptions are **native-only** in v2.0 (`GDX_BACKEND=native`). See the
[Subscriptions guide](usage/subscriptions.md).

#### 6. Filtering: a single nested `filter:` argument (django-filter removed)

!!! danger "Flat filter args, `filterset_class` and `GraphqlIDFilter` are gone"
    `django-filter` is no longer a dependency. The flat per-field arguments
    (`username: "x"`, `username_Icontains: "x"`), `Meta.filterset_class`, and
    `GraphqlIDFilter` / `GraphqlIDFormField` were **removed**. Filtering now uses a
    single nested `filter:` argument with `and` / `or` / `not`.

`Meta.filter_fields` is unchanged (list or dict form) — only the **query shape**
changes:

```graphql
# Before (graphene-django-extras): flat args, implicitly AND-ed
{ users(username_Icontains: "jo", isActive: true) { results { id } } }

# After (django-graphex): one nested filter input (and now `or` / `not` too)
{ users(filter: { username: { icontains: "jo" }, isActive: { exact: true } }) {
    results { id } } }
```

- **Custom `FilterSet`s** → override `get_queryset` / `filter_queryset` on a
  `DjangoModelType` (e.g. free-text search with `Q`).
- **`GraphqlIDFilter` / UUID-pk filtering** → declare the `id` field (or a relation
  directly) with scalar lookups and query `filter: { id: { exact/in: … } }`.
- **Related filtering** (`author__name`) → nested `filter: { author: { name: { … } } }`.

See the [Filtering guide](usage/filtering.md).

#### 7. Pagination/ordering arguments moved onto `results(...)`

On a `DjangoListObjectField` / `DjangoListObjectType` the standalone pagination
and ordering arguments are **no longer on the list field**; they live on the
`results(...)` subfield, with `totalCount` (and, for cursor pagination, `pageInfo`)
as siblings. The list field itself now only takes `filter:`.

```graphql
# Before (graphene-django-extras): limit/offset/ordering on the list field
{ users(limit: 10, offset: 20, ordering: "-dateJoined") { results { id } totalCount } }

# After (django-graphex): on the results subfield; filter stays on the list field
{ users(filter: { isActive: { exact: true } }) {
    results(limit: 10, offset: 20, ordering: "-date_joined") { id }
    totalCount
} }
```

The flat `DjangoFilterPaginateListField` is the exception: it returns a plain list,
so its filter, `limit`, `offset` and `ordering` all stay on the field (no
`results`/`totalCount` wrapper). See [Fields](usage/fields.md) and
[Pagination](usage/pagination.md).

### New in django-graphex 1.0

- **Cursor pagination** (`CursorGraphqlPagination`) and a non-opaque `pageInfo`.
- **`get_queryset` / `filter_queryset` hooks** and DRF-style `permission_classes`
  on `DjangoModelType` (see [Permissions](usage/permissions.md)).
- **Native `and` / `or` / `not` filtering** on a single `filter:` argument, built
  on Django's ORM `Q` objects — no `django-filter` (see [Filtering](usage/filtering.md)).
- **Security middlewares**: `DisableIntrospectionMiddleware` and
  `AuthenticatedFieldsMiddleware`, plus `DjangoGraphQLSchema` for declaring private
  fields (see [Security](usage/security.md)).
- New directives (`@truncate`, `@slugify`, `@round`, `@abs`, `@unique`) and
  directive arguments as GraphQL variables (see [Directives](directives.md)).

### Migration Steps

1. **Update your environment** to Python 3.12+ and Django 4.2+ (graphene
   `>=3.3,<4`, pydantic `>=2,<3`).
2. **Swap the dependency** — uninstall the old package, install the new one:

   ```bash
   # uv (recommended)
   uv remove graphene-django-extras
   uv add django-graphex
   # subscriptions: uv add "django-graphex[subscriptions]"
   ```

   ```bash
   # pip
   pip uninstall graphene-django-extras
   pip install django-graphex
   # subscriptions: pip install "django-graphex[subscriptions]"
   ```

   You can also **drop** `djangorestframework`, `django-filter` and
   `graphene-django` from your requirements — none of them are dependencies
   anymore.
3. **Update imports from `graphene_django_extras` to `django_graphex`.** Every
   `import graphene_django_extras` and `from graphene_django_extras import …`
   must become `django_graphex`:

    - `from graphene_django_extras import DjangoSerializerType` →
      `from django_graphex import DjangoModelType`
    - `from graphene_django_extras import DjangoSerializerMutation` →
      `from django_graphex import DjangoModelMutation`
    - `from graphene_django_extras.views import ExtraGraphQLView` →
      `from django_graphex import GraphQLView`
    - Settings: `GRAPHENE_DJANGO_EXTRAS = {…}` → `DJANGO_GRAPHEX = {…}`

4. **Drop DRF from your types/mutations.** Replace `Meta.serializer_class` with
   `Meta.model`, and move serializer validation to inline `validate_<field>()` /
   object-level `validate()` (or `Meta.pydantic_model`). See
   [section 2](#2-django-rest-framework-removed-use-metamodel).
5. **Rename the base classes.** `DjangoSerializerType` → `DjangoModelType`,
   `DjangoSerializerMutation` → `DjangoModelMutation`; update imports and
   `nested_fields` values to **model classes**.
6. **Rename the views.** `ExtraGraphQLView` → `GraphQLView` (now top-level);
   adopt `AuthenticatedGraphQLView` if you want an endpoint-level auth gate, and
   `graphiql_template` for offline/CSP GraphiQL. See
   [section 3](#3-views-consolidated-and-renamed).
7. **Convert filtering to the nested `filter:` argument** with `and` / `or` /
   `not` (and `id: { exact / in }`); delete any `filterset_class` /
   `GraphqlIDFilter` and move custom `FilterSet` logic to
   `get_queryset` / `filter_queryset`. See
   [section 6](#6-filtering-a-single-nested-filter-argument-django-filter-removed).
8. **Update nested-list queries** to read `results` / `totalCount`
   (see [section 4](#4-nested-lists-always-return-results-totalcount)).
9. **Move pagination/ordering arguments** (`limit`/`offset`, `page`,
   `first`/`cursor`, `ordering`) onto the `results(...)` subfield; keep filter
   arguments on the list field (see
   [section 7](#7-paginationordering-arguments-moved-onto-results)).
10. **Migrate subscriptions** into this package's `[subscriptions]` extra: drop
    `graphene-django-subscriptions`, remove `depromise_subscription`, rename
    `consumers={stream: ...}` → `subscriptions={stream: Subscription}` and
    `.consumer` → `.subscription_cls`. See
    [section 5](#5-subscriptions-now-live-in-this-package).
11. **Test your GraphQL queries and mutations.**

