# Mutations API Reference

This section provides detailed API documentation for mutation classes in `django-graphex`.

## DjangoModelMutation

The primary mutation class that provides automatic CRUD operations driven directly by a Django model.

```python
class DjangoModelMutation(ObjectType)
```

### Meta Configuration

Configure mutations through a nested `Meta` class:

```python
class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        description = "User CRUD operations"
```

### Meta Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `model` | `Model` | Required | Django model class |
| `pydantic_model` | `BaseModel` | Auto-generated | Pydantic model for custom validation; auto-generated from `model` when omitted |
| `only_fields` | `tuple/list` | `()` | Include only specified fields |
| `exclude_fields` | `tuple/list` | `()` | Exclude specified fields |
| `include_fields` | `tuple/list` | `()` | Additional fields to include |
| `input_field_name` | `str` | `'new_{model}'` | Name of input argument |
| `output_field_name` | `str` | `'{model}'` | Name of output field |
| `description` | `str` | Auto-generated | Mutation description |
| `nested_fields` | `dict` | `()` | Nested field configuration — a `{field_name: Model}` mapping. The empty default means no nested writes. |
| `model_operations` | `tuple` | `("create", "update", "delete")` | Which CRUD operations to generate; any subset of `("create", "update", "delete")`. Calling the `*Field()` builder for an excluded operation raises `AttributeError`. |
| `registry` | `Registry` | Global registry | Type registry the mutation's output node and input type resolve against. A custom registry scopes the whole mutation subgraph to one schema's own pair, so a forked `DjangoGraphQLSchema` re-forks the payload's output node into its own namespace instead of reaching the process-global node. |

### Fields

Every `DjangoModelMutation` includes these standard fields:

| Field | Type | Description |
|-------|------|-------------|
| `ok` | `Boolean` | Success indicator |
| `errors` | `List[ErrorType]` | Validation errors |
| `{model_name}` | `ObjectType` | The created/updated/deleted object |

### Class Methods

#### `__init_subclass_with_meta__(**kwargs)` (classmethod)

Initialize the mutation subclass with meta configuration.

**Parameters:**
- `model` (`Model`): Required Django model class
- `pydantic_model` (`BaseModel`): Optional Pydantic model for custom validation
- `only_fields` (`tuple`): Fields to include
- `exclude_fields` (`tuple`): Fields to exclude
- `include_fields` (`tuple`): Additional fields
- `input_field_name` (`str`): Input argument name
- `output_field_name` (`str`): Output field name
- `description` (`str`): Mutation description
- `nested_fields` (`dict`): Nested field configuration
- `model_operations` (`tuple`): CRUD operations to generate
- `registry` (`Registry`): Type registry the output node and input type resolve against

#### `get_errors(errors)` (classmethod)

Create error response with provided errors.

**Parameters:**
- `errors` (`list`): List of error objects

**Returns:** Mutation instance with errors

#### `perform_mutate(obj, info)` (classmethod)

Create successful mutation response.

**Parameters:**
- `obj` (`Model`): The model instance
- `info` (`ResolveInfo`): GraphQL resolve info

**Returns:** Mutation instance with success response

#### `save_with_nested(root, info, data, instance=None, serializer_kwargs=None)` (classmethod)

Validate and persist the parent plus any `Meta.nested_fields` children
**atomically** (provided by `NestedFieldsMixin`). Forward FK/O2O children are
written before the parent and their pk injected; reverse FK/O2O and M2M children
are written after and linked to it. A reverse child (FK **or** O2O) supplied by
pk is rejected when it currently belongs to a different parent. Any validation
failure rolls the whole transaction back.
See [How nested writes work](../usage/mutations.md#how-nested-writes-work).

**Parameters:**
- `root` (`Any`): Root object
- `info` (`ResolveInfo`): GraphQL resolve info
- `data` (`dict`): Input data (nested entries are popped from it)
- `instance` (`Model | None`): Existing instance for an update, else `None`
- `serializer_kwargs` (`dict | None`): Reserved (unused by the native backend)

**Returns:** `(ok: bool, obj_or_errors)` — the saved object, or a list of `ErrorType`

### CRUD Operations

#### `create(root, info, **kwargs)` (classmethod)

Create a new object using the provided data.

**Parameters:**
- `root` (`Any`): Root object
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Mutation arguments including input data

**Returns:** Mutation response with created object or errors

#### `update(root, info, **kwargs)` (classmethod)

Update an existing object with provided data.

**Parameters:**
- `root` (`Any`): Root object
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Mutation arguments including input data

**Returns:** Mutation response with updated object or errors

#### `delete(root, info, **kwargs)` (classmethod)

Delete an object by its ID.

**Parameters:**
- `root` (`Any`): Root object
- `info` (`ResolveInfo`): GraphQL resolve info
- `**kwargs`: Mutation arguments including object ID

**Returns:** Mutation response with deleted object or errors

!!! note "Customizing persistence"

    There is no separate `save` hook. To run logic around create/update, override
    `create` / `update` and call `super()`; to change how the parent and its
    nested children are validated and written, override `save_with_nested`.

### Field Generation Methods

#### `CreateField(*args, **kwargs)` (classmethod)

Create a GraphQL field for create mutations.

**Returns:** `Field` instance configured for create operations

#### `UpdateField(*args, **kwargs)` (classmethod)

Create a GraphQL field for update mutations.

**Returns:** `Field` instance configured for update operations

#### `DeleteField(*args, **kwargs)` (classmethod)

Create a GraphQL field for delete mutations.

**Returns:** `Field` instance configured for delete operations

#### `MutationFields(*args, **kwargs)` (classmethod)

Get all mutation fields (create, delete, update).

**Returns:** Tuple of `(create_field, delete_field, update_field)`

### Example Usage

=== "Basic Mutation"

    ```python
    from django_graphex.mutation import DjangoModelMutation
    from .models import User

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            description = "User CRUD operations"
    ```

=== "With Field Control"

    ```python
    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            exclude_fields = ('password', 'is_staff', 'is_superuser')
            input_field_name = 'user_data'
            output_field_name = 'user'
    ```

=== "With Nested Fields"

    ```python
    from .models import Address, Profile

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            # each nested field maps to its related Django model
            nested_fields = {
                'profile': Profile,
                'addresses': Address,
            }
    ```

=== "Custom Arguments"

    ```python
    from django_graphex.core import BooleanField

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User

        class Arguments:
            send_email = BooleanField(
                default=False,
                description="Send welcome email",
            )

        @classmethod
        def create(cls, root, info, **kwargs):
            send_email = kwargs.pop('send_email', False)
            response = super().create(root, info, **kwargs)
            if response.ok and send_email:
                send_welcome_email(getattr(response, cls._meta.output_field_name).email)
            return response
    ```

=== "Custom Validation"

    ```python
    from pydantic import BaseModel, field_validator

    class UserValidation(BaseModel):
        @field_validator("email", check_fields=False)
        @classmethod
        def corporate_only(cls, value):
            if value and not value.endswith("@example.com"):
                raise ValueError("Only corporate email addresses are accepted.")
            return value

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User
            # supply a Pydantic model with extra validators; the derived
            # model fields extend it
            pydantic_model = UserValidation
    ```

### Schema Integration

=== "Individual Fields"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema

    class Mutation(ObjectType):
        create_user = UserMutation.CreateField()
        update_user = UserMutation.UpdateField()
        delete_user = UserMutation.DeleteField()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

=== "All Fields at Once"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema

    class Mutation(ObjectType):
        create_user, delete_user, update_user = UserMutation.MutationFields()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

### GraphQL Operations

#### Create Mutation

```graphql
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
```

#### Update Mutation

```graphql
mutation UpdateUser($userData: UserInput!) {
  updateUser(newUser: $userData) {
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
```

#### Delete Mutation

```graphql
mutation DeleteUser($id: ID!) {
  deleteUser(id: $id) {
    ok
    user {
      id
      username
    }
    errors {
      field
      messages
    }
  }
}
```

### Response Structure

#### Success Response

```json
{
  "data": {
    "createUser": {
      "ok": true,
      "user": {
        "id": "1",
        "username": "john_doe",
        "email": "john@example.com"
      },
      "errors": null
    }
  }
}
```

#### Error Response

```json
{
  "data": {
    "createUser": {
      "ok": false,
      "user": null,
      "errors": [
        {
          "field": "username",
          "messages": ["This field is required."]
        },
        {
          "field": "email",
          "messages": ["Enter a valid email address."]
        }
      ]
    }
  }
}
```

!!! note "Internal options container"

    `DjangoModelMutation._meta` is a `NativeObjectTypeOptions` instance
    (`django_graphex.core.base.NativeObjectTypeOptions`). It is an internal
    detail — the public API is the `Meta` class options documented above.

## Advanced Usage

### File Upload Support

When the request content type is `multipart/form-data`, every entry in
`request.FILES` is merged into the input payload under its own form-field name,
so a part named after a `FileField` / `ImageField` **on the mutation's own
model** is saved to that field on create and on update:

```python
class ProfileMutation(DjangoModelMutation):
    class Meta:
        model = Profile  # model has an ImageField named "avatar"

# A multipart part named "avatar" lands on Profile.avatar.
```

```graphql
mutation UpdateProfile($profileData: ProfileInput!) {
  updateProfile(newProfile: $profileData) {
    ok
    profile {
      id
      avatar  # reads back as the storage path (String)
      bio
    }
    errors {
      field
      messages
    }
  }
}
```

The GraphQL input field stays `String`: the file travels in the multipart body,
never in the GraphQL variables. That field also accepts a plain storage path
string, and rejects any other shape with a structured error.

!!! warning "Top-level fields only"

    The merge is keyed by the bare form-field name, so a file field on a child
    declared in `Meta.nested_fields` cannot be addressed — and naming a part
    after the relation itself overwrites the nested payload and raises an
    uncaught `ValueError` (an HTTP 500). For nested uploads, use the base64
    input described in [Mutations](../usage/mutations.md#file-upload-support).

### Authentication & Authorization

```python
from graphql import GraphQLError

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User

    @classmethod
    def create(cls, root, info, **kwargs):
        user = info.context.user
        if not user.is_authenticated:
            raise GraphQLError("Authentication required")

        if not user.has_perm('auth.add_user'):
            raise GraphQLError("Permission denied")

        return super().create(root, info, **kwargs)
```

### Custom Error Handling

```python
from django.core.exceptions import ValidationError
from django_graphex.errors import ErrorType

class UserMutation(DjangoModelMutation):
    class Meta:
        model = User

    @classmethod
    def create(cls, root, info, **kwargs):
        try:
            return super().create(root, info, **kwargs)
        except ValidationError as e:
            return cls.get_errors([
                ErrorType(field=field, messages=messages)
                for field, messages in e.message_dict.items()
            ])
```

## Error Types

### ErrorType

Standard error type used in mutation responses.

```python
from django_graphex.errors import ErrorType
```

`ErrorType` is a native `ObjectType` (graphene-free) with two fields:

| Field | GraphQL type | Description |
|-------|-------------|-------------|
| `field` | `String!` | The name of the field that failed validation |
| `messages` | `[String!]!` | One or more error messages for that field |

## Best Practices

!!! tip "Mutation Best Practices"

    1. **Leverage Pydantic Validation**: Use `Meta.pydantic_model` to add custom validators
    2. **Handle Permissions**: Always check authentication and authorization
    3. **Validate Input**: Rely on the auto-generated or custom Pydantic model for robust input handling
    4. **Return Meaningful Errors**: Provide clear, actionable error messages
    5. **Test Thoroughly**: Test all CRUD operations and edge cases
    6. **Document Operations**: Provide clear descriptions for mutations
    7. **Handle Files**: Use proper file upload handling for media fields

### Security Considerations

```python
class UserMutation(DjangoModelMutation):
    class Meta:
        model = User
        # Don't expose sensitive operations
        exclude_fields = ('is_superuser', 'user_permissions', 'groups')

    @classmethod
    def create(cls, root, info, **kwargs):
        if not info.context.user.has_perm('auth.add_user'):
            raise GraphQLError("Permission denied")
        return super().create(root, info, **kwargs)
```

This comprehensive API reference covers the mutation system in `django-graphex`, providing developers with the tools needed to create robust, validated GraphQL mutations for their Django applications.
