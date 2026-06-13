# Filtering

Filtering lets clients request subsets of a list based on field values, related
objects and **logical composition** (`and` / `or` / `not`). It is built on
Django's own ORM lookups and `Q` objects — **no `django-filter` dependency**.

## Overview

- **Opt-in per type** via `Meta.filter_fields`.
- A single nested **`filter:`** argument of a generated `<Model>FilterInput` type.
- **Per-field lookups** (`exact`, `icontains`, `in`, `range`, `isnull`, …).
- **Relation descent** (`author: { name: { … } }`), to-many auto-`distinct()`.
- **Logical operators**: `and`, `or`, `not` (arbitrarily nested).
- `choices` fields filter through their generated **Enum**.

!!! warning "Different from the previous library"

    The old flat arguments (`username: "x"`, `username_Icontains: "x"`),
    `Meta.filterset_class` and `GraphqlIDFilter` are **gone**. Filtering now
    goes through the single nested `filter:` argument. See the
    [migration guide](../migration.md).

## Declaring filterable fields

`Meta.filter_fields` accepts the same two forms as before:

=== "List form (default lookups)"

    ```python
    from django_graphex import DjangoListObjectType

    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            # each field gets the type-derived default lookup set
            filter_fields = ["username", "email", "is_active"]
    ```

=== "Dict form (explicit lookups)"

    ```python
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            filter_fields = {
                "username": ("exact", "icontains"),
                "email": ("exact", "icontains"),
                "is_active": ("exact",),
                "date_joined": ("exact", "gt", "gte", "lt", "lte", "range"),
            }
    ```

=== "Dict form (mixed — None for defaults)"

    A dict value of `None` is equivalent to the list form: the field is included
    with the type-derived **default lookup set**.  This lets you mix explicit
    lookup tuples with default-lookup fields in a single declaration:

    ```python
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            filter_fields = {
                "username": None,          # default lookups (exact, in, isnull, icontains, …)
                "email": ("exact",),       # explicit — only `exact`
                "is_active": None,         # default lookups
            }
    ```

The **default lookup set** (used by the list form) is configurable with the
`COMMON_FILTER_LOOKUPS` setting and is type-aware:

| Field kind | Default lookups |
|---|---|
| any | `exact`, `in`, `isnull` |
| text | + `icontains`, `istartswith` |
| number / date / datetime | + `gt`, `gte`, `lt`, `lte`, `range` |

## Querying with `filter:`

Each declared field becomes a nested object of its lookups:

```graphql
query {
  users(filter: {
    username: { icontains: "john" }
    isActive: { exact: true }
    dateJoined: { gte: "2023-01-01" }
  }) {
    results { id username email }
    totalCount
  }
}
```

Multiple keys in the same object are **AND-ed** together.

### Lookup types

| Lookup | Input shape | Meaning |
|---|---|---|
| `exact` | `field: { exact: v }` | equals |
| `icontains` / `istartswith` | `{ icontains: "ab" }` | case-insensitive contains / starts-with |
| `gt` / `gte` / `lt` / `lte` | `{ gte: 10 }` | ordered comparisons |
| `in` | `{ in: [1, 2, 3] }` | membership (a **list**) |
| `range` | `{ range: [10, 20] }` | between (a **two-element list**) |
| `isnull` | `{ isnull: true }` | IS (NOT) NULL |

Only the lookups you declared in `filter_fields` are exposed on each field.

## Logical operators: `and` / `or` / `not`

Every `<Model>FilterInput` carries `and: [..]`, `or: [..]` and `not: {..}`,
referencing itself — so they nest arbitrarily:

```graphql
query {
  articles(filter: {
    status: { exact: PUBLISHED }
    or: [
      { views: { lt: 20 } }
      { views: { gte: 100 } }
    ]
    not: { title: { icontains: "draft" } }
  }) {
    results { title views }
  }
}
```

- `and: [a, b]` → `a AND b`
- `or: [a, b]` → `a OR b`
- `not: a` → `NOT a`
- sibling keys in the same node are AND-ed with the operators.

## Filtering across relations

Declare a `__` path in `filter_fields`; it becomes a **nested** filter input for
the related model, which recurses (and supports its own `and`/`or`/`not`):

=== "Declare"

    ```python
    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            filter_fields = {
                "title": ("icontains", "exact"),
                "author__name": ("icontains", "exact"),
                "author__profile__location": ("icontains",),
                "category__name": ("exact",),
            }
    ```

=== "Query"

    ```graphql
    {
      posts(filter: {
        title: { icontains: "django" }
        author: { name: { icontains: "ada" } }
        category: { name: { exact: "Tech" } }
      }) {
        results { title author { name } }
      }
    }
    ```

A filter that traverses a **to-many** relation (reverse FK / M2M) automatically
applies `.distinct()` so join fan-out doesn't duplicate rows.

## Filtering by id / pk (incl. `UUIDField`)

Declare the `id` field — or a relation field **directly** (not a `__` path) — with
scalar lookups, and it filters on the primary key. This replaces the old
`GraphqlIDFilter` and works for integer **and** UUID pks:

=== "Declare"

    ```python
    class OrderListType(DjangoListObjectType):
        class Meta:
            model = Order
            filter_fields = {
                "id": ("exact", "in"),        # the order's own pk
                "customer": ("exact", "in"),  # by related pk (FK column)
            }
    ```

=== "Query"

    ```graphql
    {
      orders(filter: {
        customer: { exact: 5 }          # plain integer pk
        id: { in: ["9b2e...", "7c1d..."] }   # or UUID pks
      }) {
        results { id }
      }
    }
    ```

## `choices` fields filter via their Enum

A model field with `choices` is exposed in the filter input through the same
GraphQL **Enum** as the output type:

```graphql
{ articles(filter: { status: { in: [PUBLISHED, DRAFT] } }) { results { title } } }
```

## Custom filtering logic

There are no custom `FilterSet` classes anymore. For bespoke rules, override the
queryset hooks on a `DjangoModelType` (they also scope the generated query/list):

```python
from django.db.models import Q
from django_graphex import DjangoModelType

class UserType(DjangoModelType):
    class Meta:
        model = User
        filter_fields = {"username": ("icontains",)}

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        # e.g. a free-text "search" across several columns
        term = info.context.GET.get("q") if hasattr(info.context, "GET") else None
        if term:
            qs = qs.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term))
        return qs
```

See [Permissions & hooks](permissions.md) for `get_queryset` / `filter_queryset`.

## Combining with pagination & ordering

Filtering composes with the list field's pagination/ordering, which live on the
`results(...)` subfield:

```graphql
{
  users(filter: { isActive: { exact: true }, username: { icontains: "jo" } }) {
    results(limit: 10, offset: 20, ordering: "-date_joined") {
      username email dateJoined
    }
    totalCount
  }
}
```

## Field-level filtering

`DjangoFilterListField` / `DjangoFilterPaginateListField` expose the same `filter:`
argument; declare the filterable fields on the underlying type (or pass `fields=`):

```python
import graphene
from django_graphex import DjangoFilterListField, DjangoFilterPaginateListField
from django_graphex.paginations import PageGraphqlPagination

class Query(graphene.ObjectType):
    users = DjangoFilterListField(UserType)
    paged_users = DjangoFilterPaginateListField(
        UserType, pagination=PageGraphqlPagination(page_size=20)
    )
```

## Best practices

!!! tip

    1. Index frequently-filtered columns (`db_index=True`).
    2. Only declare fields you want to expose — `filter_fields` is the allow-list.
    3. Combine with `get_queryset` (`select_related` / `prefetch_related`) to keep
       relation filters efficient.
    4. Use `get_queryset` / `filter_queryset` for free-text search and any
       server-forced scoping.
