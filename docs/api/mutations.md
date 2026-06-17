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
| `nested_fields` | `dict` | `{}` | Nested field configuration |

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
are written after and linked to it. Any validation failure rolls the whole
transaction back. See [How nested writes work](../usage/mutations.md#how-nested-writes-work).

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
    from django_graphex import DjangoModelMutation
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
    from graphql import GraphQLArgument, GraphQLBoolean

    class UserMutation(DjangoModelMutation):
        class Meta:
            model = User

        class Arguments:
            send_email = GraphQLArgument(
                GraphQLBoolean,
                default_value=False,
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
    from django_graphex import DjangoGraphQLSchema, ObjectType

    class Mutation(ObjectType):
        create_user = UserMutation.CreateField()
        update_user = UserMutation.UpdateField()
        delete_user = UserMutation.DeleteField()

    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
    ```

=== "All Fields at Once"

    ```python
    from django_graphex import DjangoGraphQLSchema, ObjectType

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

## SerializerMutationOptions

Configuration options class for `DjangoModelMutation`.

```python
class SerializerMutationOptions(BaseOptions)
```

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `fields` | `dict` | GraphQL fields for the mutation |
| `input_fields` | `dict` | Input fields configuration |
| `interfaces` | `tuple` | GraphQL interfaces |
| `model` | `Model` | Django model class |
| `pydantic_model` | `BaseModel` | Pydantic model used for validation |
| `action` | `str` | Mutation action type |
| `arguments` | `dict` | GraphQL arguments |
| `output` | `ObjectType` | Output type |
| `resolver` | `Callable` | Resolver function |
| `nested_fields` | `dict` | Nested field configuration |

## Advanced Usage

### File Upload Support

The mutation automatically handles file uploads when the request content type is `multipart/form-data`:

```python
class ProfileMutation(DjangoModelMutation):
    class Meta:
        model = Profile  # model has an ImageField

# The mutation will automatically handle file uploads
```

```graphql
mutation UpdateProfile($profileData: ProfileInput!) {
  updateProfile(newProfile: $profileData) {
    ok
    profile {
      id
      avatar  # File upload handled automatically
      bio
    }
    errors {
      field
      messages
    }
  }
}
```

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
from graphql import GraphQLList, GraphQLNonNull, GraphQLString
from django_graphex import field
from django_graphex.native.base import ObjectType

class ErrorType(ObjectType):
    field = field(GraphQLNonNull(GraphQLString))                  # String!
    messages = field(
        GraphQLNonNull(GraphQLList(GraphQLNonNull(GraphQLString)))  # [String!]!
    )
```

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
