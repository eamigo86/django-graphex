# Fields API Reference

This section provides detailed API documentation for GraphQL field classes in `django-graphex`.

## Field descriptors

The typed scalar shortcuts and the unified `Field` they route through. All
are imported from `django_graphex.core`. See
[Fields → Typed scalar descriptors](../usage/fields.md#typed-scalar-descriptors)
for the usage guide.

### `Field`

```python
Field(type, *, source=None, required=False, default=_UNSET, description=None,
      name=None, resolver=None, args=None, deprecation_reason=None)
```

ONE descriptor, usable in **both** an OUTPUT position (an `ObjectType` /
`Mutation` payload body) and an INPUT position (a `class Arguments` body or a
`Field(args={...})` / `field(args={...})` mapping). Direction is never
declared on the descriptor — it comes from the declaration site.

| Keyword | Position | Effect |
|---------|----------|--------|
| `source="attr"` | output only | Resolve by reading `attr` off the root (or calling it if callable). Raises `TypeError` in an input position. |
| `resolver` | output only | Field-level resolver (wins over the parent). Raises `TypeError` in an input position. |
| `args` | output only | Explicit `{name: arg}` mapping (each value itself a `Field` / shortcut). Raises `TypeError` in an input position. |
| `default` | input only | The GraphQL default value; omit to leave the argument with no default (an explicit `default=None` is a real `null` default). Raises `TypeError` at output compile time. |
| `required=True` | both | Wrap the type in non-null (`T!`). |
| `description` | both | Field / argument description. |
| `name` | both | Explicit wire name (skips camelCase on output; drives `out_name` on input). |
| `deprecation_reason` | both | Renders `@deprecated(reason: ...)` on the compiled field / argument. |

### Typed scalar shortcuts

Each shortcut returns a `Field` bound to one scalar, usable in both
positions. Signature (identical for all 11):
`(*, source=None, required=False, default=_UNSET, description=None, name=None, resolver=None, deprecation_reason=None)`.

| Shortcut | GraphQL type | Shortcut | GraphQL type |
|----------|--------------|----------|--------------|
| `IDField` | `ID` | `DateField` | `CustomDate` |
| `IntField` | `Int` | `DateTimeField` | `CustomDateTime` |
| `FloatField` | `Float` | `TimeField` | `CustomTime` |
| `BooleanField` | `Boolean` | `DecimalField` | `Decimal` |
| `CharField` | `String` | `UUIDField` | `UUID` |

`JSONField` is the one bespoke shortcut — it takes an extra `as_str` flag:

```python
JSONField(*, as_str=False, source=None, required=False, default=_UNSET,
          description=None, name=None, resolver=None, deprecation_reason=None)
```

`as_str=False` (the default) binds the raw `JSON` scalar (structured
objects/lists pass through on both output and input). `as_str=True` binds
`JSONString`, the string-encoding escape hatch.

!!! note "No `InputField`"
    There is a single `Field` (and a single set of typed shortcuts) for both
    positions. `InputField` and the per-scalar `*InputField` twins do not
    exist in this API.

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
| `deprecation_reason` | `str \| None` | Optional; renders `@deprecated(reason: ...)` on the compiled field |
| `**kwargs` | `Any` | Additional keyword arguments passed to base Field |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | The Django model class associated with this field |

### Methods

#### `object_resolver(manager, output_type, root, info, **kwargs)`

Static method that resolves a single object by its ID.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `output_type` (`type`): The `DjangoObjectType` subclass for this field, forwarded to `queryset_factory` so its `get_queryset` hook is applied
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
from django_graphex.fields import DjangoObjectField
from django_graphex.core import ObjectType
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from .models import User

class UserType(DjangoObjectType):
    class Meta:
        model = User

class Query(ObjectType):
    user = DjangoObjectField(UserType, description="Get a single user")

schema = DjangoGraphQLSchema(query=Query)
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
# Subclasses the native NativeMountedField
class DjangoListField(NativeMountedField)
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
from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListField

class Query(ObjectType):
    users = DjangoListField(UserType)
```

!!! note "Not exported at the top level"
    `DjangoListField` is a low-level building block; import it from
    `django_graphex.fields`. For list queries prefer
    `DjangoFilterListField`, `DjangoFilterPaginateListField` or
    `DjangoListObjectField` (all imported from `django_graphex.fields`).

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
| `*args` | `Any` | - | Additional positional arguments |
| `deprecation_reason` | `str \| None` | `None` | Renders `@deprecated(reason: ...)` on the compiled field |
| `**kwargs` | `Any` | - | Additional keyword arguments |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | The Django model class |
| `fields` | `dict` | Filter field configuration |
| `filter_backend` | `object` | Native (`Q`-based) filter backend applied to the queryset |
| `filter_type` | `InputObjectType` | Generated `<Model>FilterInput` for the `filter:` argument |

### Methods

#### `list_resolver(manager, filter_backend, custom_filters, output_type, root, info, **kwargs)`

Static method that resolves a filtered list of objects.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `filter_backend` (`object`): native filter backend; apply with `filter_backend.apply(qs, kwargs.get("filter"))`
- `custom_filters` (`list`): list of `(arg_name, method, metadata)` triples from `@filter_field`-decorated methods on the output type
- `output_type` (`type`): the `DjangoObjectType` subclass for this field; its `get_queryset` hook is applied on both resolution paths — inside `queryset_factory` for a fresh queryset, and directly on the relation when the field is reached through a parent object
- `root` (`Any`): Parent object in GraphQL resolution
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Query arguments including the `filter` value

**Returns:** Filtered QuerySet

### Example Usage

```python
from django_graphex.fields import DjangoFilterListField
from django_graphex.core import ObjectType

class Query(ObjectType):
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
| `*args` | `Any` | - | Additional positional arguments |
| `deprecation_reason` | `str \| None` | `None` | Renders `@deprecated(reason: ...)` on the compiled field |
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
from django_graphex.fields import DjangoFilterPaginateListField
from django_graphex.core import ObjectType
from django_graphex.paginations import LimitOffsetGraphqlPagination

class Query(ObjectType):
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
| `*args` | `Any` | - | Additional positional arguments |
| `deprecation_reason` | `str \| None` | `None` | Renders `@deprecated(reason: ...)` on the compiled field |
| `**kwargs` | `Any` | - | Additional keyword arguments |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `Model` | The Django model class |
| `fields` | `dict` | Filter field configuration |
| `filter_backend` | `object` | Native (`Q`-based) filter backend applied to the queryset |
| `filter_type` | `InputObjectType` | Generated `<Model>FilterInput` for the `filter:` argument |

### Methods

#### `list_resolver(manager, filter_backend, output_type, root, info, **kwargs)`

Resolve a list object with count and results.

**Parameters:**
- `manager` (`Manager`): Django model manager
- `filter_backend` (`object`): native filter backend; apply with `filter_backend.apply(qs, kwargs.get("filter"))`
- `output_type` (`type`): the `DjangoObjectType` subclass for the list items (the `DjangoListObjectType._meta.baseType`), forwarded to `queryset_factory` so its `get_queryset` hook is applied
- `root` (`Any`): Parent object
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Query arguments including the `filter` value

**Returns:** `DjangoListObjectBase` with count and results

### Example Usage

```python
from django_graphex.fields import DjangoListObjectField
from django_graphex.core import ObjectType
from django_graphex.types import DjangoListObjectType

class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        pagination = LimitOffsetGraphqlPagination(default_limit=25)

class Query(ObjectType):
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
from django_graphex.fields import DjangoObjectField, DjangoFilterListField, DjangoFilterPaginateListField, DjangoListObjectField
from django_graphex.core import ObjectType

class Query(ObjectType):
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
from django_graphex.core import ObjectType
from .paginations import CustomPagination

class Query(ObjectType):
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
from django_graphex.core import ObjectType

class Query(ObjectType):
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

class Query(ObjectType):
    users = DjangoListObjectField(UserListType)
```

This API reference provides comprehensive documentation for all field classes in `django-graphex`, enabling developers to effectively use and customize GraphQL fields for their Django applications.
