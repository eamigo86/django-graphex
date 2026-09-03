# Quick Start

This guide will help you get started with django-graphex quickly.

## Configuration

Configure global settings for pagination in your Django settings:

```python title="settings.py"
DJANGO_GRAPHEX = {
    'DEFAULT_PAGINATION_CLASS': 'django_graphex.paginations.LimitOffsetGraphqlPagination',
    'DEFAULT_PAGE_SIZE': 20,
    'MAX_PAGE_SIZE': 50,
    # Keep response caching off until every context dependency is in the key.
    'CACHE_ACTIVE': False,
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
from django.contrib.auth import get_user_model
from django_graphex.types import DjangoObjectType

User = get_user_model()

class UserType(DjangoObjectType):
    class Meta:
        model = User
        description = "Type definition for a single user"
        # Security boundary: password and privilege fields do not enter the SDL.
        only_fields = ("id", "username", "first_name", "last_name")
        filter_fields = {
            "id": ("exact", ),
            "first_name": ("icontains", "iexact"),
            "last_name": ("icontains", "iexact"),
            "username": ("icontains", "iexact"),
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

### Why this is not a `DjangoModelType`

`DjangoModelType` is useful for ordinary application models, but Django's
account model is not an ordinary CRUD resource. A generated input can publish
privilege flags and generic persistence does not call `set_password()`. Keep
this surface read-only and add the purpose-built registration mutation below.

!!! tip "Field-type conversion"
    Django model fields map to GraphQL types automatically. For the full mapping
    — including PostgreSQL `ArrayField` (`[<inner>]`, `ArrayField(choices)` →
    `[<Enum>]`) and `*RangeField` (`{ lower, upper }`) — see the
    [field-type conversion reference and worked example](usage/types.md#field-type-conversion-reference).

## Mutations

A hand-written mutation subclasses `django_graphex.core.Mutation`. Declare its
output payload with the typed descriptors (`BooleanField`, `CharField`, or the
general `Field`), its inputs in a nested `class Arguments` using the SAME
`CharField` / `Field` descriptors — `Field` is unified and works in both
output and input position — and implement a `mutate(root, info, ...)`
classmethod that returns an instance of the mutation:

```python title="mutations.py"
from django.contrib.auth import get_user_model
from django_graphex.core import BooleanField, CharField, Field, Mutation
from .types import UserType


class CreateUser(Mutation):
    """Traditional mutation - implement the mutate function yourself."""

    ok = BooleanField()
    user = Field(UserType)

    class Arguments:
        username = CharField(required=True)
        password = CharField(required=True)

    @classmethod
    def mutate(cls, root, info, username, password):
        user = get_user_model().objects.create_user(
            username=username,
            password=password,
        )
        return cls(ok=True, user=user)
```

## Schema Definition

The schema mounts only the four-field read projection and the registration
mutation. The endpoint itself rejects anonymous requests before parsing GraphQL:

```python title="schema.py"
from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField, DjangoObjectField
from django_graphex.schema import DjangoGraphQLSchema
from .types import UserListType, UserType
from .mutations import CreateUser

class Query(ObjectType):
    user = DjangoObjectField(UserType, description="Single user")
    users = DjangoListObjectField(UserListType, description="All users")

class Mutation(ObjectType):
    register_user = CreateUser.Field()

schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
```

```python title="urls.py"
from django.urls import path
from django_graphex.views import AuthenticatedGraphQLView
from .schema import schema

urlpatterns = [
    path("graphql/", AuthenticatedGraphQLView.as_view(schema=schema, graphiql=True)),
]
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
      }
    }
    ```

## Example Mutations

Registration accepts only a username and password. `create_user()` hashes the
password and leaves `is_staff` / `is_superuser` false:

```graphql
mutation {
  registerUser(username: "test", password: "test123") {
    ok
    user { id username firstName lastName }
  }
}
```

## Next Steps

- Try the runnable [Playground](https://github.com/eamigo86/django-graphex/tree/main/examples/playground) — a complete Django project exercising every feature end-to-end
- Learn more about [Fields](usage/fields.md)
- Explore [Pagination](usage/pagination.md) options
- Discover [Directives](directives.md) for data formatting
- Check out more [Examples & Recipes](usage/examples/blog-schema.md)
