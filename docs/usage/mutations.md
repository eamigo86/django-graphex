# Mutations

GraphQL mutations allow you to modify data on your server. `django-graphex` provides powerful tools to create mutations from Django models, making CRUD operations simple and consistent.

## DjangoModelMutation

The `DjangoModelMutation` is the cornerstone of mutations in `django-graphex`. It automatically generates Create, Read, Update, and Delete (CRUD) operations directly from a Django model.

### Features

- :material-auto-fix: **Automatic CRUD Operations**: Generates create, update, and delete mutations
- :material-check-circle: **Built-in Validation**: Validates all writable model fields, FK existence, uniqueness, and `unique_together` constraints
- :material-file-upload: **File Upload Support**: Handles multipart/form-data requests
- :material-link-variant: **Nested Relationships**: Supports nested field creation and updates
- :material-alert-circle: **Error Handling**: Returns structured error responses

### Basic Usage

=== "Define Your Mutation"

    ```python
    from django.contrib.auth.models import User
    from django_graphex import DjangoModelMutation

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            description = "User mutations: create, update, delete"
    ```

=== "Add to Schema"

    ```python
    import graphene
    from .mutations import UserMutation

    class Mutation(graphene.ObjectType):
        # Get all mutation fields (create, update, delete)
        user_create, user_delete, user_update = UserMutation.MutationFields()

    schema = graphene.Schema(query=Query, mutation=Mutation)
    ```

=== "Alternative Schema Setup"

    ```python
    import graphene
    from .mutations import UserMutation

    class Mutation(graphene.ObjectType):
        # Individual mutation fields
        create_user = UserMutation.CreateField()
        update_user = UserMutation.UpdateField()
        delete_user = UserMutation.DeleteField()

    schema = graphene.Schema(query=Query, mutation=Mutation)
    ```

### Configuration Options

The `DjangoModelMutation` supports several configuration options:

#### Meta Configuration

```python
from django.contrib.auth.models import User
from .models import Address, Profile

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        only_fields = ('username', 'email', 'first_name', 'last_name')
        exclude_fields = ('password',)
        input_field_name = 'user_data'  # Default: 'new_{model_name}'
        output_field_name = 'user'      # Default: '{model_name}'
        description = "Custom description for the mutation"
        # map each nested field to its related Django model
        nested_fields = {'profile': Profile, 'addresses': Address}
```

#### Field Filtering

!!! tip "Field Control"
    Use `only_fields` to include specific fields, or `exclude_fields` to exclude certain fields from mutations.

=== "Include Specific Fields"

    ```python
    from django.contrib.auth.models import User

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            only_fields = ('username', 'email', 'first_name', 'last_name')
    ```

=== "Exclude Fields"

    ```python
    from django.contrib.auth.models import User

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            exclude_fields = ('password', 'is_staff', 'is_superuser')
    ```

### Custom Arguments

You can add custom arguments to your mutations:

```python
import graphene
from django.contrib.auth.models import User
from django_graphex import DjangoModelMutation

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User

    class Arguments:
        send_email = graphene.Boolean(
            default_value=False,
            description="Send welcome email after user creation"
        )

    @classmethod
    def create(cls, root, info, **kwargs):
        send_email = kwargs.pop('send_email', False)
        response = super().create(root, info, **kwargs)
        if response.ok and send_email:
            send_welcome_email(getattr(response, cls._meta.output_field_name).email)
        return response
```

### Nested Fields Support

Handle related models with nested fields:

```python
from django.contrib.auth.models import User
from .models import Address, Profile

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        # each nested field maps to its related Django model
        nested_fields = {'profile': Profile, 'addresses': Address}
```

!!! info "Nested Fields Behavior"
    - For single objects: The created object's ID is assigned to the field
    - For lists: Objects are added to the many-to-many relationship

### File Upload Support

The mutation automatically handles file uploads when the request content type is `multipart/form-data`:

```python
from .models import Profile

# The mutation will automatically handle avatar uploads (ImageField on the model)
class ProfileMutation(DjangoModelMutation):
    class Meta:
        model = Profile
```

### Error Handling

All mutations return a consistent response structure:

```python
{
  "ok": Boolean,           # True if successful, False if errors
  "errors": [ErrorType],   # List of validation errors
  "{model_name}": Object   # The created/updated/deleted object (null if errors)
}
```

Example error response:

```json
{
  "data": {
    "createUser": {
      "ok": false,
      "errors": [
        {
          "field": "email",
          "messages": ["This field is required."]
        },
        {
          "field": "username",
          "messages": ["A user with that username already exists."]
        }
      ],
      "user": null
    }
  }
}
```

### Custom Mutation Logic

Override methods to add custom logic:

=== "Custom Save Logic"

    Override `create` / `update` and call `super()` to run logic around the save
    (there is no separate `save` hook — validation and persistence happen inside
    `create`/`update`):

    ```python
    from django.contrib.auth.models import User
    from django_graphex import DjangoModelMutation

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User

        @classmethod
        def create(cls, root, info, **kwargs):
            response = super().create(root, info, **kwargs)
            # Custom logic after a successful save
            if response.ok:
                send_welcome_email(getattr(response, cls._meta.output_field_name).email)
            return response
    ```

### Complete Example

Here's a complete example showing all features:

=== "models.py"

    ```python
    from django.db import models
    from django.contrib.auth.models import User

    class Profile(models.Model):
        user = models.OneToOneField(User, on_delete=models.CASCADE)
        bio = models.TextField(blank=True)
        avatar = models.ImageField(upload_to='avatars/', blank=True)
        birth_date = models.DateField(null=True, blank=True)

    class Address(models.Model):
        user = models.ForeignKey(User, on_delete=models.CASCADE)
        street = models.CharField(max_length=255)
        city = models.CharField(max_length=100)
        country = models.CharField(max_length=100)
    ```

=== "mutations.py"

    ```python
    import graphene
    from django.contrib.auth.models import User
    from django_graphex import DjangoModelMutation
    from .models import Address, Profile

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            exclude_fields = ('is_staff', 'is_superuser')
            nested_fields = {'profile': Profile, 'addresses': Address}

        class Arguments:
            send_welcome_email = graphene.Boolean(default_value=True)
    ```

=== "schema.py"

    ```python
    import graphene
    from .mutations import UserMutation

    class Mutation(graphene.ObjectType):
        create_user, delete_user, update_user = UserMutation.MutationFields()

    schema = graphene.Schema(query=Query, mutation=Mutation)
    ```

### How nested writes work

`nested_fields = {field_name: RelatedModel}` lets a single create/update write
related objects alongside the parent. The same engine backs both
`DjangoModelMutation` and `DjangoModelType`.

- **Atomic** — the whole operation runs in a `transaction.atomic()` block. If the
  parent *or* any child fails validation, **everything rolls back** (no orphan
  rows) and the response is `ok: false` with the errors.
- **Relation-aware** — the relation is introspected from the model:

    | Relation | Order | Behavior |
    |---|---|---|
    | Forward `ForeignKey` / `OneToOneField` | child saved **first** | its pk is set on the parent |
    | Reverse FK / reverse `OneToOne` | parent **first** | each child is linked to the parent |
    | `ManyToManyField` (either side) | parent **first** | children are saved and `.add()`-ed |

- **Upsert** — a child payload that carries its `id` **updates** that row; without
  an `id` it creates a new one. (The nested input only exposes `id` on the
  parent's *update* input, so nested **creates** stay create-only.)
- **Additive & safe** — M2M/reverse children are only added, never removed; an
  empty `[]` / `{}` payload is a no-op (the relation is left untouched).
- **Errors are prefixed** — a child error is reported as `field.subfield`
  (e.g. `addresses.zip_code`).

!!! warning "Reverse-FK nested fields"

    For a **reverse** relation (the child holds the FK to the parent), the child's
    FK back to the parent is injected automatically at save time — you do not need
    to supply it in the mutation input. Use `exclude_fields` on the child's
    `DjangoModelMutation` (or `only_fields`) to keep it out of the input:

    ```python
    class PostMutation(DjangoModelMutation):
        class Meta:
            model = Post
            only_fields = ["id", "title", "body"]   # no "author": injected from parent
    ```

### M2M write semantics: nested path vs. top-level path

The two write paths use **different M2M semantics** — this is intentional in v1.2.x and will be
unified in v1.3.0:

| Write path | M2M operation | Effect |
|---|---|---|
| **Nested** (`nested_fields`) | `.add(*children)` | **Additive** — existing links are kept; the submitted items are appended. Submitting an empty list is a no-op. |
| **Top-level native backend** | `.set(pks)` | **Replace** — existing links are removed and replaced with exactly the submitted list. Submitting an empty list clears all links. |

**Practical implication:** to *remove* M2M links via the nested path you currently cannot — use the
top-level mutation instead, or issue a separate mutation that clears and re-adds.

!!! note "Planned for v1.3.0"
    A per-field `m2m_behavior = "set" | "add"` option will let you choose the semantics on the
    nested path and align the default to `.set` (matching top-level behavior). Track the work in
    [GitHub issue #18](https://github.com/eamigo86/django-graphex/issues/18).

### Explicit-null limitation in update mutations

`update()` currently treats `None` values in the input as "not provided" and skips them. This
means you **cannot clear a nullable field or empty an M2M** by sending `null` — the field will be
left unchanged.

```graphql
# This does NOT clear the bio field in v1.2.x:
mutation {
  updateUser(newUser: { id: 1, bio: null }) {
    ok
    user { id bio }
  }
}
```

**Workaround:** use a separate mutation that explicitly assigns an empty string or removes the
M2M association via a dedicated resolver.

!!! note "Planned for v1.3.0"
    Explicit-null support requires distinguishing "omitted" from "explicitly null" at the input
    level. The planned approach is an AST-presence check so the current partial-update behavior
    is preserved for omitted fields while respecting intentional nulls. Track the work in
    [GitHub issue #18](https://github.com/eamigo86/django-graphex/issues/18).

### perform_mutate response shape

`DjangoModelMutation.perform_mutate` and `DjangoModelType.perform_mutate` intentionally differ:

| Class | Response object | Extra DB query |
|---|---|---|
| `DjangoModelType` | Re-reads via `get_queryset()` — picks up DB defaults, signals, annotations | Yes |
| `DjangoModelMutation` | Returns the **in-memory** object that was just saved | No |

If your mutation relies on a DB default or signal to set a field value and you need that value in
the response, use `DjangoModelType` instead of `DjangoModelMutation`, or override
`perform_mutate` to add an explicit `refresh_from_db()` call:

```python
class MyMutation(DjangoModelMutation):
    class Meta:
        model = MyModel

    @classmethod
    def perform_mutate(cls, obj, info):
        obj.refresh_from_db()
        return super().perform_mutate(obj, info)
```

## Traditional GraphQL Mutations

While `DjangoModelMutation` covers most use cases, you can still create traditional GraphQL mutations for custom logic:

=== "Traditional Mutation"

    ```python
    import graphene
    from django_graphex import DjangoObjectType
    from django.contrib.auth.models import User

    class UserType(DjangoObjectType):
        class Meta:
            model = User

    class CreateUser(graphene.Mutation):
        class Arguments:
            username = graphene.String(required=True)
            email = graphene.String(required=True)
            password = graphene.String(required=True)

        ok = graphene.Boolean()
        user = graphene.Field(UserType)

        def mutate(self, info, username, email, password):
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            return CreateUser(ok=True, user=user)
    ```

=== "With Error Handling"

    ```python
    from django_graphex.errors import ErrorType

    class CreateUser(graphene.Mutation):
        class Arguments:
            username = graphene.String(required=True)
            email = graphene.String(required=True)
            password = graphene.String(required=True)

        ok = graphene.Boolean()
        user = graphene.Field(UserType)
        errors = graphene.List(ErrorType)

        def mutate(self, info, username, email, password):
            # Validation
            errors = []

            if User.objects.filter(username=username).exists():
                errors.append(ErrorType(
                    field="username",
                    messages=["Username already exists"]
                ))

            if User.objects.filter(email=email).exists():
                errors.append(ErrorType(
                    field="email",
                    messages=["Email already registered"]
                ))

            if errors:
                return CreateUser(ok=False, errors=errors, user=None)

            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            return CreateUser(ok=True, user=user, errors=None)
    ```

## Best Practices

!!! tip "Mutation Best Practices"

    1. **Use DjangoModelMutation**: Drive mutations from `Meta.model` for consistency
    2. **Validate Input**: Always validate input data before processing
    3. **Handle Errors Gracefully**: Provide clear, actionable error messages
    4. **Test Thoroughly**: Write tests for all mutation scenarios
    5. **Document Fields**: Use descriptions for all mutation fields and arguments
    6. **Security First**: Implement proper authentication and authorization

### Authentication & Permissions

```python
from graphql import GraphQLError
from django.contrib.auth.models import User
from django_graphex import DjangoModelMutation

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User

    @classmethod
    def create(cls, root, info, **kwargs):
        if not info.context.user.is_authenticated:
            raise GraphQLError("Authentication required")

        if not info.context.user.has_perm('auth.add_user'):
            raise GraphQLError("Permission denied")

        return super().create(root, info, **kwargs)
```

### Custom Validation

For field-level validation beyond automatic DB checks, supply a Pydantic model
via `Meta.pydantic_model`:

```python
from pydantic import BaseModel, field_validator
from django.contrib.auth.models import User
from django_graphex import DjangoModelMutation

class UserValidation(BaseModel):
    username: str
    email: str

    @field_validator("email", check_fields=False)
    @classmethod
    def email_must_be_corporate(cls, v):
        if not v.endswith("@example.com"):
            raise ValueError("Only corporate email addresses are accepted.")
        return v

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        pydantic_model = UserValidation
```

## Testing Mutations

=== "Basic Test"

    ```python
    import pytest
    from graphene.test import Client
    from .schema import schema

    @pytest.mark.django_db
    def test_create_user_mutation():
        client = Client(schema)

        mutation = """
            mutation CreateUser($userData: UserInput!) {
                createUser(newUser: $userData) {
                    ok
                    user {
                        id
                        username
                        email
                    }
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        variables = {
            "userData": {
                "username": "testuser",
                "email": "test@example.com",
                "password": "secretpass123"
            }
        }

        result = client.execute(mutation, variables=variables)
        assert result['data']['createUser']['ok'] is True
        assert result['data']['createUser']['user']['username'] == 'testuser'
    ```

=== "Error Handling Test"

    ```python
    @pytest.mark.django_db
    def test_create_user_validation_error():
        client = Client(schema)

        mutation = """
            mutation CreateUser($userData: UserInput!) {
                createUser(newUser: $userData) {
                    ok
                    errors {
                        field
                        messages
                    }
                }
            }
        """

        # Missing required email
        variables = {
            "userData": {
                "username": "testuser",
                "password": "secretpass123"
            }
        }

        result = client.execute(mutation, variables=variables)
        assert result['data']['createUser']['ok'] is False
        assert len(result['data']['createUser']['errors']) > 0
    ```

The mutation system in `django-graphex` provides a robust foundation for handling data modifications in your GraphQL API, with built-in validation, error handling, and support for complex operations.
