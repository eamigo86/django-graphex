# Fields API Reference

This section provides detailed API documentation for GraphQL field classes in `django-graphex`.

## DjangoObjectField

A GraphQL field for querying a single Django model object by ID.

```python
class DjangoObjectField(Field)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `_type` | `DjangoObjectType` | The GraphQL type representing the Django model |
| `*args` | `Any` | Additional positional arguments passed to base Field |
| `**kwargs` | `Any` | Additional keyword arguments passed to base Field |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | The Django model class associated with this field |

### Methods

#### `object_resolver(manager, root, info, **kwargs)`

Static method that resolves a single object by its ID.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `root` (`Any`): Parent object in GraphQL resolution
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Query arguments including `id`

**Returns:** Model instance or `None` if not found

#### `wrap_resolve(parent_resolver)`

Wraps the resolver with the object resolver functionality.

**Parameters:**
- `parent_resolver` (`Callable`): Parent resolver function

**Returns:** Wrapped resolver function

### Example Usage

```python
import graphene
from django_graphex import DjangoObjectField, DjangoObjectType
from .models import User

class UserType(DjangoObjectType):
    class Meta:
        model = User

class Query(graphene.ObjectType):
    user = DjangoObjectField(UserType, description="Get a single user")

schema = graphene.Schema(query=Query)
```

### GraphQL Query

```graphql
query GetUser($id: ID!) {
  user(id: $id) {
    id
    username
    email
  }
}
```

---

## DjangoListField

A basic GraphQL field for querying a list of Django model objects.

```python
# Subclasses graphene.Field
class DjangoListField(Field)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `_type` | `DjangoObjectType` | The GraphQL type representing the Django model |
| `*args` | `Any` | Additional positional arguments |
| `**kwargs` | `Any` | Additional keyword arguments |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `type` | `Field` | Returns the GraphQL field type |

### Example Usage

```python
from django_graphex.fields import DjangoListField

class Query(graphene.ObjectType):
    users = DjangoListField(UserType)
```

!!! note "Not exported at the top level"
    `DjangoListField` is a low-level building block; import it from
    `django_graphex.fields`. For list queries prefer
    `DjangoFilterListField`, `DjangoFilterPaginateListField` or
    `DjangoListObjectField` (all exported from `django_graphex`).

---

## DjangoFilterListField

A GraphQL field for querying a filtered list of Django model objects.

```python
class DjangoFilterListField(Field)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `_type` | `DjangoObjectType` | Required | The GraphQL type |
| `fields` | `dict` | `None` | Filter field configuration |
| `extra_filter_meta` | `dict` | `None` | Additional filter metadata |
| `*args` | `Any` | - | Additional positional arguments |
| `**kwargs` | `Any` | - | Additional keyword arguments |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | The Django model class |
| `fields` | `dict` | Filter field configuration |
| `filter_backend` | `object` | Native (`Q`-based) filter backend applied to the queryset |
| `filter_type` | `InputObjectType` | Generated `<Model>FilterInput` for the `filter:` argument |

### Methods

#### `list_resolver(manager, filter_backend, root, info, **kwargs)`

Static method that resolves a filtered list of objects.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `filter_backend` (`object`): native filter backend; apply with `filter_backend.apply(qs, kwargs.get("filter"))`
- `root` (`Any`): Parent object in GraphQL resolution
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Query arguments including the `filter` value

**Returns:** Filtered QuerySet

### Example Usage

```python
from django_graphex import DjangoFilterListField

class Query(graphene.ObjectType):
    users = DjangoFilterListField(
        UserType,
        description="Filtered list of users"
    )
```

### GraphQL Query

```graphql
query GetFilteredUsers {
  users(filter: { username: { icontains: "john" }, isActive: { exact: true } }) {
    id
    username
    email
    isActive
  }
}
```

---

## DjangoFilterPaginateListField

A GraphQL field for querying a filtered and paginated list of Django model objects.

```python
class DjangoFilterPaginateListField(Field)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `_type` | `DjangoObjectType` | Required | The GraphQL type |
| `pagination` | `BaseDjangoGraphqlPagination` | Default pagination | Pagination configuration |
| `fields` | `dict` | `None` | Filter field configuration |
| `extra_filter_meta` | `dict` | `None` | Additional filter metadata |
| `*args` | `Any` | - | Additional positional arguments |
| `**kwargs` | `Any` | - | Additional keyword arguments |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | The Django model class |
| `fields` | `dict` | Filter field configuration |
| `filter_backend` | `object` | Native (`Q`-based) filter backend applied to the queryset |
| `filter_type` | `InputObjectType` | Generated `<Model>FilterInput` for the `filter:` argument |
| `pagination` | `BaseDjangoGraphqlPagination` | Pagination instance |

### Methods

#### `get_queryset(manager, root, info, **kwargs)`

Get the base queryset for this field.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `root` (`Any`): Parent object
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Query arguments

**Returns:** Base QuerySet

#### `list_resolver(manager, filter_backend, root, info, **kwargs)`

Resolve a filtered and paginated list of objects.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `filter_backend` (`object`): native filter backend; apply with `filter_backend.apply(qs, kwargs.get("filter"))`
- `root` (`Any`): Parent object
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Query arguments including the `filter` value and pagination

**Returns:** Paginated QuerySet

### Example Usage

```python
from django_graphex import (
    DjangoFilterPaginateListField,
    LimitOffsetGraphqlPagination
)

class Query(graphene.ObjectType):
    users = DjangoFilterPaginateListField(
        UserType,
        pagination=LimitOffsetGraphqlPagination(default_limit=20),
        description="Paginated and filtered list of users"
    )
```

### GraphQL Query

```graphql
query GetPaginatedUsers {
  users(
    filter: { username: { icontains: "john" }, isActive: { exact: true } },
    limit: 10,
    offset: 20
  ) {
    id
    username
    email
    isActive
  }
}
```

---

## DjangoListObjectField

A GraphQL field for Django list objects that returns both count and results.

```python
class DjangoListObjectField(Field)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `_type` | `DjangoListObjectType` | Required | The GraphQL list type |
| `fields` | `dict` | `None` | Filter field configuration |
| `extra_filter_meta` | `dict` | `None` | Additional filter metadata |
| `*args` | `Any` | - | Additional positional arguments |
| `**kwargs` | `Any` | - | Additional keyword arguments |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | The Django model class |
| `fields` | `dict` | Filter field configuration |
| `filter_backend` | `object` | Native (`Q`-based) filter backend applied to the queryset |
| `filter_type` | `InputObjectType` | Generated `<Model>FilterInput` for the `filter:` argument |

### Methods

#### `list_resolver(manager, filter_backend, root, info, **kwargs)`

Resolve a list object with count and results.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `filter_backend` (`object`): native filter backend; apply with `filter_backend.apply(qs, kwargs.get("filter"))`
- `root` (`Any`): Parent object
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Query arguments including the `filter` value

**Returns:** `DjangoListObjectBase` with count and results

### Example Usage

```python
from django_graphex import DjangoListObjectField, DjangoListObjectType

class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        pagination = LimitOffsetGraphqlPagination(default_limit=25)

class Query(graphene.ObjectType):
    all_users = DjangoListObjectField(
        UserListType,
        description="All users with count and pagination"
    )
```

### GraphQL Query

```graphql
query GetUserList {
  allUsers {
    totalCount
    results(limit: 10, offset: 0) {
      id
      username
      email
    }
  }
}
```

For `DjangoListObjectField`, filter arguments are placed on the list field itself,
while pagination and ordering arguments (`limit`, `offset`, `page`, `pageSize`,
`first`, `ordering`, cursor arguments) are placed on the `results(...)` subfield.
`totalCount` and `pageInfo` are siblings of `results`.

### Response Structure

```json
{
  "data": {
    "allUsers": {
      "totalCount": 150,
      "results": [
        {
          "id": "1",
          "username": "user1",
          "email": "user1@example.com"
        }
      ]
    }
  }
}
```

---

## Field Configuration Examples

### Basic Field Setup

```python
import graphene
from django_graphex import (
    DjangoObjectField,
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField
)

class Query(graphene.ObjectType):
    # Single object
    user = DjangoObjectField(UserType)

    # Simple filtered list
    users = DjangoFilterListField(UserType)

    # Filtered and paginated list
    users_paginated = DjangoFilterPaginateListField(UserType)

    # List object with count
    all_users = DjangoListObjectField(UserListType)
```

### Advanced Field Configuration

```python
from .paginations import CustomPagination

class Query(graphene.ObjectType):
    # Custom filtered list — `fields=` overrides the type's `filter_fields`
    staff_users = DjangoFilterListField(
        UserType,
        fields={"username": ("exact", "icontains"), "is_active": ("exact",)},
        description="Filtered list of staff users"
    )

    # Custom paginated list
    paginated_users = DjangoFilterPaginateListField(
        UserType,
        pagination=CustomPagination(default_limit=50),
        fields={"username": ("exact", "icontains"), "is_active": ("exact",)},
        description="Custom paginated user list"
    )

    # Custom resolver
    active_users = DjangoFilterListField(UserType)

    def resolve_active_users(self, info, **kwargs):
        return User.objects.filter(is_active=True)
```

### Error Handling

```python
class Query(graphene.ObjectType):
    user = DjangoObjectField(UserType)

    def resolve_user(self, info, **kwargs):
        try:
            return User.objects.get(id=kwargs.get('id'))
        except User.DoesNotExist:
            return None  # Will return null in GraphQL response
```

## Best Practices

!!! tip "Field Best Practices"

    1. **Use Appropriate Fields**: Choose the right field type for your use case
    2. **Add Descriptions**: Always provide meaningful descriptions for your fields
    3. **Configure Filtering**: Set up proper filter configurations for list fields
    4. **Handle Errors**: Implement proper error handling in custom resolvers
    5. **Optimize Queries**: Use `select_related` and `prefetch_related` for performance
    6. **Limit Results**: Always configure reasonable pagination limits

### Performance Optimization

```python
class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        pagination = LimitOffsetGraphqlPagination(default_limit=25)

    @classmethod
    def get_queryset(cls, queryset, info):
        return queryset.select_related('profile').prefetch_related('posts')

class Query(graphene.ObjectType):
    users = DjangoListObjectField(UserListType)
```

This API reference provides comprehensive documentation for all field classes in `django-graphex`, enabling developers to effectively use and customize GraphQL fields for their Django applications.
