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
    from django_graphex.mutation import DjangoModelMutation

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            description = "User mutations: create, update, delete"
    ```

=== "Add to Schema"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    from .mutations import UserMutation

    class Mutation(ObjectType):
        # Get all mutation fields (create, update, delete)
        user_create, user_delete, user_update = UserMutation.MutationFields()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

=== "Alternative Schema Setup"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    from .mutations import UserMutation

    class Mutation(ObjectType):
        # Individual mutation fields
        create_user = UserMutation.CreateField()
        update_user = UserMutation.UpdateField()
        delete_user = UserMutation.DeleteField()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

!!! tip "Deprecating a mutation field"
    Every mutation-field builder (`CreateField`, `UpdateField`, `DeleteField`,
    and `MutationFields`) accepts `deprecation_reason=`, wired straight into the
    compiled field so the SDL renders `@deprecated(reason: ...)`:

    ```python
    class Mutation(ObjectType):
        create_user = UserMutation.CreateField(
            deprecation_reason="Use `createUserV2` instead; will be removed in 3.0."
        )
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

### Custom Arguments with `Field`

You can add custom arguments to your mutations. Declare them in a nested
`class Arguments` with the unified `Field` descriptor — the same descriptor
used in output position — or one of the typed shortcuts (`BooleanField`,
`CharField`, `IntField`, …) for a bare scalar:

```python
from django.contrib.auth.models import User
from django_graphex.core import BooleanField
from django_graphex.mutation import DjangoModelMutation

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User

    class Arguments:
        send_email = BooleanField(
            default=False,
            description="Send welcome email after user creation",
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

### Automatic multipart uploads

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

!!! tip "FK existence check runs only on the failure path"
    A valid mutation issues a single `INSERT`/`UPDATE` — the per-FK `SELECT 1`
    existence pre-check is **not** run on the happy path. If the write raises an
    `IntegrityError` (e.g. a bad FK pk), the same diagnostics that used to run
    eagerly now run **after** the failure to attribute the exact field, so a bad
    FK still returns the identical structured `errors[]` envelope. Nested writes
    (`Meta.nested_fields`) similarly open a `transaction.atomic()` savepoint
    **only when nested child work is actually present** — a plain, parent-only
    create/update pays no savepoint overhead. Both changes are purely
    performance-oriented: the observable response shape is unchanged.

### Custom Mutation Logic

Override methods to add custom logic:

=== "Custom Save Logic"

    Override `create` / `update` and call `super()` to run logic around the save
    (there is no separate `save` hook — validation and persistence happen inside
    `create`/`update`):

    ```python
    from django.contrib.auth.models import User
    from django_graphex.mutation import DjangoModelMutation

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
    from django.contrib.auth.models import User
    from django_graphex.core import BooleanField
    from django_graphex.mutation import DjangoModelMutation
    from .models import Address, Profile

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            exclude_fields = ('is_staff', 'is_superuser')
            nested_fields = {'profile': Profile, 'addresses': Address}

        class Arguments:
            send_welcome_email = BooleanField(default=True)
    ```

=== "schema.py"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema
    from .mutations import UserMutation

    class Mutation(ObjectType):
        create_user, delete_user, update_user = UserMutation.MutationFields()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

=== "GraphQL client"

    ```graphql
    mutation CreateUser($userData: NewUser!, $sendEmail: Boolean) {
      createUser(newUser: $userData, sendWelcomeEmail: $sendEmail) {
        ok
        user {
          id
          username
          email
          profile {
            bio
            avatar
          }
          addresses {
            totalCount
            results { street city country }
          }
        }
        errors { field messages }
      }
    }
    ```

=== "Variables"

    ```json
    {
      "userData": {
        "username": "jane_doe",
        "email": "jane@example.com",
        "firstName": "Jane",
        "lastName": "Doe",
        "profile": {
          "bio": "Django + GraphQL enthusiast",
          "birthDate": "1990-06-15"
        },
        "addresses": [
          { "street": "123 Main St", "city": "Springfield", "country": "US" }
        ]
      },
      "sendEmail": true
    }
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
- **M2M pk validation** — when M2M pks are passed directly to the top-level
  mutation (not via `nested_fields`), non-existent pks are caught *before* the
  DB write and returned as a structured `ErrorType` (field name + message),
  never as an `IntegrityError` 500.
- **To-one list guard** — supplying a list to a forward `ForeignKey` /
  `OneToOneField` nested field raises a clean error if the list contains more
  than one item. A single-element list is accepted as a convenience.
- **Reverse-O2O list guard** — supplying a list of more than one item to a
  reverse `OneToOneField` nested field raises a clean error instead of hitting
  the DB UNIQUE constraint.
- **Reverse-FK ownership guard** — upsert of a reverse-FK child by pk is
  rejected if that child currently belongs to a *different* parent. This
  prevents a client from silently re-parenting (stealing) rows owned by another
  object. The error message is `"Object <pk> does not belong to this <Model>."`.

!!! warning "Reverse-FK child re-parenting"
    Attempting to assign an existing child (by pk) to a new parent via the
    nested write path will fail with a validation error if the child's FK already
    points to a different parent. To genuinely re-parent a row, issue a direct
    update mutation on the child model instead.

#### Worked examples — UPDATE + nested create and UPDATE + nested update (upsert)

=== "UPDATE + nested create"

    ```graphql
    # Add a brand-new address to an existing user (no `id` on the address payload
    # → creates a new Address row and links it to the user).
    mutation {
      updateUser(newUser: {
        id: "1"
        addresses: [
          { street: "456 Oak Ave", city: "Shelbyville", country: "US" }
        ]
      }) {
        ok
        user {
          addresses {
            results { id street city country }
            totalCount
          }
        }
        errors { field messages }
      }
    }
    ```

    The new address is **added** to the user's existing addresses (`M2M`/reverse-FK
    children use `.add()` semantics — existing links are kept). `totalCount` will
    increase by 1.

=== "UPDATE + nested update (upsert)"

    ```graphql
    # Update an existing address: include its `id` in the payload.
    # Without an id → creates; with an id → updates that row in place.
    mutation {
      updateUser(newUser: {
        id: "1"
        addresses: [
          { id: "3", street: "789 Elm St", city: "Springfield", country: "US" }
        ]
      }) {
        ok
        user {
          addresses {
            results { id street city country }
          }
        }
        errors { field messages }
      }
    }
    ```

    A child payload **with `id`** updates that existing row. A child payload
    **without `id`** creates a new one. Both can appear in the same `addresses`
    list in a single mutation call.

!!! tip "Removing M2M/reverse-FK children"
    Nested writes are **additive only** (`.add()` — existing links are kept).
    To remove links, issue a separate mutation that targets the child directly or
    override the top-level mutation. See
    [M2M write semantics](#m2m-write-semantics-nested-path-vs-top-level-path) below.

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

The two write paths use **different M2M semantics** — this is intentional and the two paths
are not yet unified:

| Write path | M2M operation | Effect |
|---|---|---|
| **Nested** (`nested_fields`) | `.add(*children)` | **Additive** — existing links are kept; the submitted items are appended. Submitting an empty list (or `null`) is a **no-op**. |
| **Top-level native backend** | `.set(pks)` | **Replace** — existing links are removed and replaced with exactly the submitted list. Submitting an empty list `[]` **or an explicit `null`** clears all links. Omitting the field entirely leaves the relation untouched. |

**Practical implication:** to *remove* M2M links via the nested path you currently cannot — use the
top-level mutation instead (send `tags: []` or `tags: null` to clear), or issue a separate mutation
that clears and re-adds.

!!! note "Not yet implemented as of v2.0"
    A per-field `m2m_behavior = "set" | "add"` option will let you choose the semantics on the
    nested path and align the default to `.set` (matching top-level behavior).

### Explicit-null semantics in update mutations

`update()` follows the GraphQL specification: **an omitted field is not the same as an explicit
`null`**. On a partial update:

| Input | Effect |
|---|---|
| Field **omitted** from the input | Value is **left unchanged** (partial-update semantics). |
| Field sent as **explicit `null`** (nullable field / FK) | Column is set to **`NULL`**. |
| Field sent as **explicit `null`** (required field) | A clean **validation error** (`ok: false`, `errors[]`) — never a 500. |
| M2M sent as `null` **or** `[]` (top-level path) | Relation is **cleared**. |
| M2M **omitted** (top-level path) | Relation is **left unchanged**. |

```graphql
# Clear the nullable ``bio`` field:
mutation {
  updateUser(newUser: { id: 1, bio: null }) {
    ok
    user { id bio }        # -> bio is now null
  }
}

# Leave ``bio`` untouched (it is simply omitted):
mutation {
  updateUser(newUser: { id: 1, firstName: "Ada" }) {
    ok
    user { id bio }        # -> bio unchanged
  }
}

# Clear an M2M (``tags: null`` is equivalent to ``tags: []``):
mutation {
  updatePost(newPost: { id: 1, tags: null }) {
    ok
    post { id }
  }
}
```

!!! warning "Nested inputs treat `null` as a no-op"
    Explicit-null semantics apply to **scalar fields, foreign keys, and the top-level
    (`ID`-list) M2M surface**. For **nested inputs** (`Meta.nested_fields`) a `null` / `[]` /
    `{}` payload is a deliberate **no-op** — the related children are left untouched, never
    deleted. Interpreting `null` as "delete every related child" would be dangerous and
    irreversible, so nested writes never clear on `null`. To remove nested children, target the
    child model directly.

### perform_mutate response shape

`DjangoModelMutation.perform_mutate` and `DjangoModelType.perform_mutate` intentionally differ in
how they produce the response object after a successful write:

| Class | Response object | Optimizer applied? | Extra DB query? |
|---|---|---|---|
| `DjangoModelType` | Re-reads via `get_queryset()` — picks up DB defaults, signals, annotations | Yes — the re-read passes through `queryset_factory` so `select_related` / `prefetch_related` / `.only()` are derived from the mutation's response selection | Yes (one re-read) |
| `DjangoModelMutation` | Returns the **in-memory** object that was just saved | No re-read, so no optimizer pass | No |

**Practical implication:** if your mutation response selects nested relations
(e.g. `user { profile { bio } }`), `DjangoModelType` will resolve them via the
re-read queryset — which the optimizer makes efficient. `DjangoModelMutation`
returns the in-memory object, so relations are resolved lazily (one per field),
unless you `refresh_from_db()` in a custom `perform_mutate`.

To avoid N+1 on `DjangoModelMutation` responses with nested relations, or when you
need DB defaults or signals to be reflected, override `perform_mutate`:

```python
class MyMutation(DjangoModelMutation):
    class Meta:
        model = MyModel

    @classmethod
    def perform_mutate(cls, obj, info):
        obj.refresh_from_db()
        return super().perform_mutate(obj, info)
```

## Mutation response: depth limits and optimizer

### `MAX_QUERY_DEPTH` and `Meta.max_depth` apply to mutations

Query depth limiting (`MAX_QUERY_DEPTH` global setting and `Meta.max_depth` per-type)
is enforced on **all** operation types — including mutation response selection sets.
The selection set validation runs before execution, so a mutation that requests
deeper nesting than the limit permits is rejected with a validation error before
any database writes occur.

```python
DJANGO_GRAPHEX = {
    "MAX_QUERY_DEPTH": 5,   # enforced on query, mutation, and subscription selection sets
}
```

The per-type attribute is `Meta.max_depth`; the global setting key is
`MAX_QUERY_DEPTH`:

```python
class UserModelType(DjangoModelType):
    class Meta:
        model = User
        max_depth = 3   # overrides the global MAX_QUERY_DEPTH for this type
```

See [Query depth & cost limits](query-limits.md) for the full reference.

## Traditional GraphQL Mutations

While `DjangoModelMutation` covers most use cases, you can still create traditional GraphQL mutations for custom logic:

=== "Traditional Mutation"

    ```python
    from django_graphex.core import BooleanField, CharField, Field, Mutation
    from django_graphex.types import DjangoObjectType
    from django.contrib.auth.models import User

    class UserType(DjangoObjectType):
        class Meta:
            model = User

    class CreateUser(Mutation):
        class Arguments:
            username = CharField(required=True)
            email = CharField(required=True)
            password = CharField(required=True)

        ok = BooleanField()
        user = Field(UserType)

        @staticmethod
        def mutate(root, info, username, email, password):
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            return CreateUser(ok=True, user=user)
    ```

=== "With Error Handling"

    ```python
    from django_graphex.core import BooleanField, CharField, Field, Mutation
    from django_graphex.errors import ErrorType
    # ErrorType is a native ObjectType (a Python class), so wrap it in the
    # lazy NativeList rather than graphql-core's GraphQLList.
    from django_graphex.core.descriptors import NativeList

    class CreateUser(Mutation):
        class Arguments:
            username = CharField(required=True)
            email = CharField(required=True)
            password = CharField(required=True)

        ok = BooleanField()
        user = Field(UserType)
        errors = Field(NativeList(ErrorType))

        @staticmethod
        def mutate(root, info, username, email, password):
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
from django_graphex.mutation import DjangoModelMutation

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

For field-level validation beyond automatic DB checks (inline `validate_<field>`
methods, object-level `validate()`, and `Meta.pydantic_model`), see the
authoritative reference:
[Model backend (Pydantic) — Custom validation](backends.md#custom-validation-inline-validate_field).

## Testing Mutations

=== "Basic Test"

    ```python
    import pytest
    from graphql import graphql_sync
    from .schema import schema   # a DjangoGraphQLSchema

    @pytest.mark.django_db
    def test_create_user_mutation():
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

        result = graphql_sync(schema.graphql_schema, mutation, variable_values=variables)
        assert result.errors is None
        assert result.data['createUser']['ok'] is True
        assert result.data['createUser']['user']['username'] == 'testuser'
    ```

=== "Error Handling Test"

    ```python
    from graphql import graphql_sync

    @pytest.mark.django_db
    def test_create_user_validation_error():
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

        result = graphql_sync(schema.graphql_schema, mutation, variable_values=variables)
        assert result.data['createUser']['ok'] is False
        assert len(result.data['createUser']['errors']) > 0
    ```

The mutation system in `django-graphex` provides a robust foundation for handling data modifications in your GraphQL API, with built-in validation, error handling, and support for complex operations.

---

## File Upload Support

### Base64FileInput

`django-graphex` ships an **opt-in** `Base64FileInput` for sending files through the GraphQL body as base64-encoded strings. Import it explicitly — it is not wired into `DjangoModelMutation` automatically.

```python
from django_graphex.uploads import Base64FileInput
from django_graphex.uploads import Base64FileInput, decode_base64_file
```

#### Shape

```graphql
input Base64FileInput {
  filename: String!           # Original filename (stored / used as the key by FileField)
  data: String!               # Base64-encoded file content
  contentType: String         # MIME type — defaults to "application/octet-stream"
}
```

#### Resolver usage

```python
from django_graphex.core import BooleanField, Field, Mutation
from django_graphex.uploads import Base64FileInput

class UploadAvatarMutation(Mutation):
    class Arguments:
        # Pass the input-object CLASS directly. Field resolves the compiled
        # GraphQLInputObjectType LAZILY at schema-build time, so there is no thunk
        # boilerplate and no `_meta.graphql_input_type` reference at class scope.
        avatar = Field(Base64FileInput, required=True)

    ok = BooleanField()

    @classmethod
    def mutate(cls, root, info, **kwargs):
        # The input object arrives as a dict (snake-cased keys); rehydrate it into a
        # Base64FileInput so .to_uploaded_file() is available.
        avatar = Base64FileInput(**kwargs["avatar"])
        # Pass max_size to override the global MAX_UPLOAD_SIZE for this field:
        uploaded = avatar.to_uploaded_file(max_size=512 * 1024)  # 512 KB cap
        profile.avatar.save(uploaded.name, uploaded, save=True)
        return cls(ok=True)
```

The `avatar` argument arrives in the resolver as a plain `dict` of the input
fields; rehydrate it with `Base64FileInput(**kwargs["avatar"])` to get a validated
instance with `.filename`, `.data`, `.content_type` attributes **and** a
`.to_uploaded_file(*, max_size=None)` method that returns a `SimpleUploadedFile`.

!!! note "How `Field` resolves the input type"
    `Base64FileInput._meta.graphql_input_type` is compiled at schema-build time.
    Listing `django_graphex` in `INSTALLED_APPS` triggers that compilation from
    `AppConfig.ready()`, so `Field(Base64FileInput, ...)` resolves the class
    to the real compiled input type when the schema mounts the field — lazily,
    never reading the attribute (which would be `None`) at class-definition time.
    The older `lambda: GraphQLArgument(GraphQLNonNull(...))` thunk still works as
    the low-level substrate.

You can also call the module-level helper directly if you hold the raw dict:

```python
from django_graphex.uploads import decode_base64_file

uploaded = decode_base64_file(
    {"filename": "report.pdf", "data": b64_string, "content_type": "application/pdf"},
    max_size=10 * 1024 * 1024,  # 10 MB override
)
```

#### GraphQL client example

```graphql
mutation UploadAvatar($file: Base64FileInput!) {
  uploadAvatar(avatar: $file) { ok }
}
```

Variables:
```json
{
  "file": {
    "filename": "photo.png",
    "contentType": "image/png",
    "data": "<base64 string>"
  }
}
```

### Settings

Add both settings to your `DJANGO_GRAPHEX` dict in `settings.py`:

```python
DJANGO_GRAPHEX = {
    # Required when Base64FileInput is used — raises ImproperlyConfigured if
    # absent and no per-field override is given.
    "MAX_UPLOAD_SIZE": 5 * 1024 * 1024,    # 5 MB per decoded file

    # Primary memory cap: the full JSON body is rejected BEFORE parsing when
    # this limit is exceeded. None = disabled (not recommended for public APIs).
    # Rule of thumb: ≥ base64_overhead × MAX_UPLOAD_SIZE × expected_files_per_request
    # (base64 encodes 3 bytes as 4 ASCII chars → overhead ≈ 4/3)
    "MAX_REQUEST_BODY_SIZE": 20 * 1024 * 1024,  # 20 MB total body
}
```

#### Per-field override

Pass `max_size` to `.to_uploaded_file()` or `decode_base64_file()` to use a tighter (or looser) cap for a specific field:

```python
avatar.to_uploaded_file(max_size=512 * 1024)         # 512 KB — tight avatar cap
document.to_uploaded_file(max_size=50 * 1024 * 1024) # 50 MB — loose document cap
```

Per-field `max_size` overrides the global `MAX_UPLOAD_SIZE` for that call only.

### Memory-safety architecture

> **Why two settings?**

The base64 payload lives inside the JSON body. By the time any field resolver sees it, the entire body is already in RAM. The guards compose as follows:

| Guard | Where it fires | What it saves |
|---|---|---|
| `MAX_REQUEST_BODY_SIZE` | `dispatch()` — BEFORE JSON parse | The entire body allocation |
| Per-field decoded-size pre-check | Inside `decode_base64_file` — BEFORE `base64.decode` | The decoded-bytes allocation |

**Peak memory** ≈ `body_size + MAX_UPLOAD_SIZE`.

For batch requests, `MAX_BATCH_SIZE` (op count) + `MAX_REQUEST_BODY_SIZE` (bytes) compose naturally: operations execute sequentially so peak decoded memory is bounded by one file's size, not the whole batch.

### Error handling

| Condition | Result |
|---|---|
| Body exceeds `MAX_REQUEST_BODY_SIZE` | HTTP 413 (before parsing) |
| Estimated decoded size > effective cap | `GraphQLError` (before decode) |
| Invalid / malformed base64 | `GraphQLError` (never HTTP 500) |
| `MAX_UPLOAD_SIZE` unset + no per-field override | `ImproperlyConfigured` at call time |

### Content validation

Magic-byte / MIME-type sniffing is **out of scope**. Use Django's `FileField` validators (e.g. `FileExtensionValidator`) or a custom model validator for content-type enforcement — that is the correct layer.

### Query cost

Input payload size is **not** accounted for in query-cost analysis (the `MAX_QUERY_COST` setting). The body-size guard (`MAX_REQUEST_BODY_SIZE`) is the canonical byte-level cap.

### Response caching

Upload mutations are not cached. The response-cache layer already skips `mutation` operations — no special configuration needed.

### Batch uploads

For batch requests:

- `MAX_REQUEST_BODY_SIZE` caps the total body of all operations combined.
- Per-field decoded-size pre-checks fire inside each operation's resolver.
- No special upload-batch rejection: rely on `MAX_BATCH_SIZE` (op count) + `MAX_REQUEST_BODY_SIZE` (bytes).

### REST side-channel alternative

For gateway-constrained environments (e.g. an API gateway with a 10 MB payload limit), the recommended alternative is a **REST side-channel**:

1. Upload the file directly to a presigned URL (S3, GCS, Azure Blob) or a separate `POST /upload/` endpoint.
2. Receive a file key or public URL in response.
3. Pass that reference as a plain `String` field in the GraphQL mutation.

This avoids base64 overhead (≈33% size increase) entirely and scales naturally with file size.
