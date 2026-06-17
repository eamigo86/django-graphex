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

```python title="types.py"
from django.contrib.auth.models import User
from django_graphex import DjangoObjectType

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

```python title="types.py"
from django_graphex import DjangoListObjectType
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

```python title="types.py"
from django.contrib.auth.models import User
from django_graphex import DjangoModelType

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

## Input Types

Define input types for mutations:

```python title="inputs.py"
from django_graphex import DjangoInputObjectType
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
from django_graphex import DjangoModelMutation

class UserModelMutation(DjangoModelMutation):
    class Meta:
        description = "Model-based Mutation for Users"
        model = User
```

### Traditional Mutations

A hand-written mutation subclasses `django_graphex.Mutation`. Declare its output
payload with `field()` (graphql-core scalars/types), its inputs in a nested
`class args` using `GraphQLArgument`, and implement a `mutate(root, info, ...)`
classmethod that returns an instance of the mutation:

```python title="mutations.py"
from graphql import GraphQLArgument, GraphQLBoolean, GraphQLNonNull, GraphQLString

from django_graphex import Mutation, field


class CreateUser(Mutation):
    """Traditional mutation - implement the mutate function yourself."""

    ok = field(GraphQLBoolean)
    username = field(GraphQLString)

    class args:
        username = GraphQLArgument(GraphQLNonNull(GraphQLString))
        password = GraphQLArgument(GraphQLNonNull(GraphQLString))

    @staticmethod
    def mutate(root, info, username, password):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username=username, password=password)
        return CreateUser(ok=True, username=user.username)
```

## Schema Definition

```python title="schema.py"
from django_graphex import (
    DjangoObjectField,
    DjangoListObjectField,
    DjangoFilterPaginateListField,
    DjangoFilterListField,
    DjangoGraphQLSchema,
    LimitOffsetGraphqlPagination,
    ObjectType,
)
from .types import UserType, UserListType, UserModelType
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

    # Using DjangoModelType
    user_retrieve, user_list = UserModelType.QueryFields(
        description='User queries with model type'
    )

class Mutation(ObjectType):
    # Model-based mutations
    user_create = UserModelMutation.CreateField()
    user_delete = UserModelMutation.DeleteField()
    user_update = UserModelMutation.UpdateField()

    # Using DjangoModelType
    user_create_alt, user_delete_alt, user_update_alt = UserModelType.MutationFields()

    # Traditional mutation
    create_user = CreateUser.Field()

schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
```

## Example Queries

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
