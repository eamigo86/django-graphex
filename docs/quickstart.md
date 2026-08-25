# Quick Start

This guide will help you get started with django-graphex quickly.

## Configuration

Configure global settings for pagination in your Django settings:

```python title="settings.py"
DJANGO_GRAPHEX = {
    'DEFAULT_PAGINATION_CLASS': 'django_graphex.paginations.LimitOffsetGraphqlPagination',
    'DEFAULT_PAGE_SIZE': 20,
    'MAX_PAGE_SIZE': 50,
    'CACHE_ACTIVE': True,
    'CACHE_TIMEOUT': 300    # seconds
}
```

## Types Definition

### Basic Type

A `DjangoObjectType` maps one Django model to one GraphQL object type — the
model's fields are converted automatically (`choices` become enums, relations
become nested lists). `filter_fields` declares which ORM lookups are exposed
when this type is used as a (nested) list:

```python title="types.py"
from django.contrib.auth.models import User
from django_graphex.types import DjangoObjectType

class UserType(DjangoObjectType):
    class Meta:
        model = User
        description = "Type definition for a single user"
        filter_fields = {
            "id": ("exact", ),
            "first_name": ("icontains", "iexact"),
            "last_name": ("icontains", "iexact"),
            "username": ("icontains", "iexact"),
            "email": ("icontains", "iexact"),
            "is_staff": ("exact", ),
        }
```

### List Type with Pagination

A `DjangoListObjectType` wraps the node type in the uniform list shape —
`results` (paginated, ordered) plus `totalCount` — with pagination configured
in `Meta`:

```python title="types.py"
from django_graphex.types import DjangoListObjectType
from django_graphex.paginations import LimitOffsetGraphqlPagination

class UserListType(DjangoListObjectType):
    class Meta:
        description = "Type definition for user list"
        model = User
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25,
            ordering="-username"  # Can be string, tuple, or list
        )
```

### Model Type

A `DjangoModelType` is the all-in-one option: from a single declaration it
auto-generates the output type, the retrieve/list queries **and** the full set
of CRUD mutations (create / update / delete, with validation and integrity
checks). You mount them on your roots with `QueryFields()` /
`MutationFields()` — shown in [Schema Definition](#schema-definition) below:

```python title="types.py"
from django.contrib.auth.models import User
from django_graphex.types import DjangoModelType
from django_graphex.paginations import LimitOffsetGraphqlPagination

class UserModelType(DjangoModelType):
    """With this type definition, mutations are auto-generated"""

    class Meta:
        description = "User model type definition"
        model = User
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25,
            ordering="-username"
        )
        filter_fields = {
            "id": ("exact", ),
            "first_name": ("icontains", "iexact"),
            "last_name": ("icontains", "iexact"),
            "username": ("icontains", "iexact"),
            "email": ("icontains", "iexact"),
            "is_staff": ("exact", ),
        }
```

!!! tip "Field-type conversion"
    Django model fields map to GraphQL types automatically. For the full mapping
    — including PostgreSQL `ArrayField` (`[<inner>]`, `ArrayField(choices)` →
    `[<Enum>]`) and `*RangeField` (`{ lower, upper }`) — see the
    [field-type conversion reference and worked example](usage/types.md#field-type-conversion-reference).

## Input Types

Define input types for mutations:

```python title="inputs.py"
from django_graphex.types import DjangoInputObjectType
from django.contrib.auth.models import User

class UserInput(DjangoInputObjectType):
    class Meta:
        description = "User InputType definition for mutations"
        model = User
```

## Mutations

### Model-based Mutations

!!! tip "Recommended Approach"
    DjangoModelMutation automatically implements Create, Delete and Update functions.

```python title="mutations.py"
from django.contrib.auth.models import User
from django_graphex.mutation import DjangoModelMutation

class UserModelMutation(DjangoModelMutation):
    class Meta:
        description = "Model-based Mutation for Users"
        model = User
```

### Traditional Mutations

A hand-written mutation subclasses `django_graphex.core.Mutation`. Declare its
output payload with the typed descriptors (`BooleanField`, `CharField`, or the
general `Field`), its inputs in a nested `class Arguments` using the SAME
`CharField` / `Field` descriptors — `Field` is unified and works in both
output and input position — and implement a `mutate(root, info, ...)`
classmethod that returns an instance of the mutation:

```python title="mutations.py"
from django_graphex.core import BooleanField, CharField, Mutation


class CreateUser(Mutation):
    """Traditional mutation - implement the mutate function yourself."""

    ok = BooleanField()
    username = CharField()

    class Arguments:
        username = CharField(required=True)
        password = CharField(required=True)

    @staticmethod
    def mutate(root, info, username, password):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username=username, password=password)
        return CreateUser(ok=True, username=user.username)
```

## Schema Definition

The schema wires everything together: a `Query` root mounts the types through
field classes (each offering a different mix of filtering / pagination /
single-object lookup), a `Mutation` root mounts the mutations, and
`DjangoGraphQLSchema` compiles both into the executable GraphQL schema.

There are two ways to reach that surface. `UserListType` (a hand-declared
`DjangoListObjectType`) gives you full control over the container; `UserModelType`
(a `DjangoModelType`) generates the equivalent surface — including its own
`UserListGenericType` container — from a single declaration. The tabs below show
each on its own, but a project can use both, even over the same model:

=== "Manual types (UserType / UserListType)"

    ```python title="schema.py"
    from django_graphex.fields import DjangoObjectField, DjangoListObjectField, DjangoFilterPaginateListField, DjangoFilterListField
    from django_graphex.core import ObjectType
    from django_graphex.paginations import LimitOffsetGraphqlPagination
    from django_graphex.schema import DjangoGraphQLSchema
    from .types import UserType, UserListType
    from .mutations import CreateUser, UserModelMutation

    class Query(ObjectType):
        # Different ways to define user list queries
        users = DjangoListObjectField(UserListType, description='All Users query')
        users_paginated = DjangoFilterPaginateListField(
            UserType,
            pagination=LimitOffsetGraphqlPagination()
        )
        users_filtered = DjangoFilterListField(UserType)

        # Single user queries
        user = DjangoObjectField(UserType, description='Single User query')
        user_detail = UserListType.RetrieveField(description='User detail')

    class Mutation(ObjectType):
        # Model-based mutations
        user_create = UserModelMutation.CreateField()
        user_delete = UserModelMutation.DeleteField()
        user_update = UserModelMutation.UpdateField()

        # Traditional mutation
        create_user = CreateUser.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

=== "DjangoModelType (all-in-one)"

    ```python title="schema.py"
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    from .types import UserModelType
    from .mutations import CreateUser

    class Query(ObjectType):
        # QueryFields() returns (retrieve, list) — the list container
        # (UserListGenericType) is generated automatically.
        user_retrieve, user_list = UserModelType.QueryFields(
            description='User queries with model type'
        )

    class Mutation(ObjectType):
        # MutationFields() returns (create, delete, update)
        user_create, user_delete, user_update = UserModelType.MutationFields()

        # Traditional mutation
        create_user = CreateUser.Field()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

## Example Queries

With the schema above you can already query lists (pagination and ordering
arguments live on `results`, filters on the field itself) and single objects:

=== "List Query"

    ```graphql
    {
      users {
        results(limit: 5, offset: 0) {
          id
          username
          firstName
          lastName
        }
        totalCount
      }
    }
    ```

=== "Filtered Query"

    ```graphql
    {
      users(filter: { firstName: { icontains: "john" } }) {
        results(limit: 10) {
          id
          username
          firstName
          lastName
        }
        totalCount
      }
    }
    ```

=== "Single User"

    ```graphql
    {
      user(id: 1) {
        id
        username
        firstName
        lastName
        email
      }
    }
    ```

## Example Mutations

The model-based mutations take their input under a single `newUser` argument
(delete takes just the `id`) and return a payload with the mutated object,
`ok`, and an `errors` list of `{ field, messages }` on validation failure:

=== "Create User"

    ```graphql
    mutation {
      userCreate(newUser: {username: "test", password: "test123"}) {
        user {
          id
          username
          firstName
          lastName
        }
        ok
        errors {
          field
          messages
        }
      }
    }
    ```

=== "Update User"

    ```graphql
    mutation {
      userUpdate(newUser: {id: 1, username: "newusername"}) {
        user {
          id
          username
        }
        ok
        errors {
          field
          messages
        }
      }
    }
    ```

=== "Delete User"

    ```graphql
    mutation {
      userDelete(id: 1) {
        ok
        errors {
          field
          messages
        }
      }
    }
    ```

## Next Steps

- Try the runnable [Playground](https://github.com/eamigo86/django-graphex/tree/main/examples/playground) — a complete Django project exercising every feature end-to-end
- Learn more about [Fields](usage/fields.md)
- Explore [Pagination](usage/pagination.md) options
- Discover [Directives](directives.md) for data formatting
- Check out more [Examples & Recipes](usage/examples/blog-schema.md)
