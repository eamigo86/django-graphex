# Fields

django-graphex provides several field types for building GraphQL schemas with enhanced functionality.

## DjangoObjectField

Used for single object queries with automatic ID filtering.

```python
from django_graphex import DjangoObjectField
from .types import UserType

class Query(graphene.ObjectType):
    user = DjangoObjectField(UserType, description='Single User query')
```

**Features:**
- Automatic ID-based filtering
- No need to define custom resolve function
- Built-in error handling for non-existent objects

**Usage in GraphQL:**
```graphql
{
  user(id: 1) {
    id
    username
    firstName
  }
}
```

## DjangoFilterListField

Provides filtering capabilities for list queries without pagination.

```python
from django_graphex import DjangoFilterListField
from .types import UserType

class Query(graphene.ObjectType):
    users = DjangoFilterListField(UserType)
```

**Features:**
- Built on Django's ORM lookups + `Q` objects (no django-filter)
- Multiple filter types (exact, contains, etc.)
- No pagination (returns all matching results)

**Usage in GraphQL:**
```graphql
{
  users(filter: { firstName: { icontains: "john" } }) {
    id
    username
    firstName
    lastName
  }
}
```

## DjangoFilterPaginateListField

Combines filtering and pagination for list queries.

```python
from django_graphex import DjangoFilterPaginateListField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from .types import UserType

class Query(graphene.ObjectType):
    users = DjangoFilterPaginateListField(
        UserType,
        pagination=LimitOffsetGraphqlPagination(default_limit=20)
    )
```

**Features:**
- All filtering capabilities of DjangoFilterListField
- Built-in pagination support
- Configurable pagination class

**Usage in GraphQL:**
```graphql
{
  users(filter: { firstName: { icontains: "john" } }, limit: 10, offset: 0) {
    id
    username
    firstName
  }
}
```

!!! note "Flat list"
    `DjangoFilterPaginateListField` returns a flat list, so both the filter
    arguments and the pagination/ordering arguments (`limit`, `offset`,
    `ordering`) live directly on the list field. There is no `results` /
    `totalCount` wrapper — for that, use `DjangoListObjectField`.

## DjangoListObjectField

!!! tip "Recommended for Queries"
    This is the most flexible approach for list queries with built-in support for filtering and pagination.

```python
from django_graphex import DjangoListObjectField
from .types import UserListType

class Query(graphene.ObjectType):
    users = DjangoListObjectField(UserListType, description='All Users query')
```

**Features:**
- Works with DjangoListObjectType
- Inherits pagination configuration from the type
- Filtering via the type's `filter_fields` (built on Django ORM lookups + `Q`)
- Built-in caching support

**Usage in GraphQL:**

Filter arguments live on the list field; pagination and ordering arguments
(`limit`, `offset`, `ordering`) live on the `results` subfield. `totalCount` is
a sibling of `results`.

```graphql
{
  users(filter: { isActive: { exact: true } }) {
    results(limit: 10, offset: 0, ordering: "-id") {
      id
      username
      firstName
    }
    totalCount
  }
}
```

### Custom filtering logic

There are no `FilterSet` classes. Declarative lookups come from the type's
`Meta.filter_fields` and are queried through the nested `filter:` argument. For
bespoke rules (e.g. a free-text search across several columns), override
`get_queryset` / `filter_queryset` on a `DjangoModelType`:

```python
from django.db.models import Q
from django_graphex import DjangoModelType
from django.contrib.auth.models import User

class UserType(DjangoModelType):
    class Meta:
        model = User
        filter_fields = {"username": ("icontains",), "email": ("icontains",)}

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        term = info.context.GET.get("q") if hasattr(info.context, "GET") else None
        if term:
            qs = qs.filter(
                Q(first_name__icontains=term) | Q(last_name__icontains=term)
            )
        return qs
```

See [Permissions & hooks](permissions.md) and the [Filtering guide](filtering.md).

## Custom resolvers

`DjangoObjectField`, `DjangoFilterListField`, `DjangoFilterPaginateListField` and
`DjangoListObjectField` accept a custom `resolver=`. When given, it is used
instead of the built-in resolver — but it still receives the library's plumbing as
its **leading positional arguments**, so you can reuse filtering/pagination and
only change the base queryset:

- single object: `resolver(manager, root, info, **kwargs)`
- lists: `resolver(manager, filter_backend, root, info, **kwargs)`

```python
def active_users(manager, root, info, **kwargs):
    # custom base queryset; manager is the model's default manager
    return manager.filter(is_active=True).get(pk=kwargs["id"])

field = DjangoObjectField(UserType, resolver=active_users)
```

This is also what powers `DjangoModelType.RetrieveField()` / `ListField()`
(which inject `cls.retrieve` / `cls.list`), so a `DjangoModelType.Meta.queryset`
is honored by its list/retrieve.

## Field Comparison

| Feature | DjangoObjectField | DjangoFilterListField | DjangoFilterPaginateListField | DjangoListObjectField |
|---------|------------------|----------------------|------------------------------|----------------------|
| Single Objects | ✅ | ❌ | ❌ | ❌ |
| List Objects | ❌ | ✅ | ✅ | ✅ |
| Filtering | ID only | ✅ | ✅ | ✅ |
| Pagination | ❌ | ❌ | ✅ | ✅ |
| Custom queryset hooks | ❌ | ✅ | ✅ | ✅ |
| Type Integration | Basic | Basic | Basic | Full |
| Caching | ❌ | ❌ | ❌ | ✅ |

## Best Practices

### 1. Use DjangoListObjectField for Lists

```python
# ✅ Recommended
class Query(graphene.ObjectType):
    users = DjangoListObjectField(UserListType, description='All users')

# ❌ Less flexible
class Query(graphene.ObjectType):
    users = DjangoFilterPaginateListField(UserType)
```

### 2. Define Filter Fields in Types

```python
class UserType(DjangoObjectType):
    class Meta:
        model = User
        filter_fields = {
            "username": ("exact", "icontains"),
            "email": ("exact", "icontains"),
            "is_active": ("exact",),
        }
```

### 3. Use Descriptive Names

```python
class Query(graphene.ObjectType):
    # ✅ Clear and descriptive
    active_users = DjangoListObjectField(
        UserListType,
        description='List of active users with pagination'
    )

    user_by_id = DjangoObjectField(
        UserType,
        description='Get a single user by ID'
    )
```

### 4. Combine with Permissions

Pass a custom `resolver=` that reuses the library's plumbing (it receives
`manager, filter_backend, root, info, **kwargs` for list fields) and only changes
the base queryset; `filter_backend.apply(qs, kwargs.get("filter"))` applies the
nested `filter:` argument:

```python
from django_graphex import DjangoListObjectField
from django_graphex.base_types import DjangoListObjectBase
from graphql import GraphQLError

def staff_only_users(manager, filter_backend, root, info, **kwargs):
    if not info.context.user.is_staff:
        raise GraphQLError("Staff access required")
    qs = manager.get_queryset()
    qs = filter_backend.apply(qs, kwargs.get("filter"))
    return DjangoListObjectBase(count=qs.count(), results=qs)

class Query(graphene.ObjectType):
    users = DjangoListObjectField(UserListType, resolver=staff_only_users)
```
