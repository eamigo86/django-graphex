# Types API Reference

This section provides detailed API documentation for GraphQL type classes in `django-graphex`.

## Field descriptors

Capitalized field descriptors for declaring custom (non-model) fields and
mutation arguments. All are imported from `django_graphex.core`. See
[Declaring fields: the descriptor API](../usage/types.md#declaring-fields-the-descriptor-api)
for the usage guide.

### `Field` (both positions)

```python
Field(type, *, source=None, required=False, default=_UNSET, description=None,
      name=None, resolver=None, args=None, deprecation_reason=None)
```

**One** descriptor for **both** positions — an `ObjectType` / `Mutation` payload
body (output) and a `class Arguments` body or `Field(args={...})` /
`field(args={...})` mapping (input). Direction comes from the declaration site,
never from the descriptor. `type` takes:

- **Output:** any graphql-core output type, a `DjangoObjectType` reference
  (resolved lazily), or a `NativeList` / `NativeNonNull` wrapper.
- **Input:** a `DjangoInputObjectType` / `InputType` **CLASS** (resolved lazily
  to its compiled input type) or a bare graphql-core scalar.

| Keyword | Effect |
|---------|--------|
| `source="attr"` | **Output only.** Resolve by reading `attr` off the root (or calling it if callable). |
| `required=True` | Wrap the type in non-null (`T!`) — lazy on output, eager on input. |
| `default=value` | **Input only.** GraphQL argument default; omit it (the `_UNSET` sentinel) to leave the argument with no default, or pass `default=None` for a real `null` default. |
| `description` | Field / argument description. |
| `name` | Explicit wire name (skips camelCase). |
| `resolver` | **Output only.** Field-level resolver (wins over the parent). |
| `args` | **Output only.** Explicit `{name: arg}` mapping (each value may be a `Field`). |
| `deprecation_reason` | Renders `@deprecated(reason: ...)` on the field / argument. |

Wrong-position keywords fail loud: an output-only `source=` / `resolver=` /
`args=` set on a field used in an argument position raises a clear `TypeError`;
the input-only `default=` set in an output position raises a `TypeError` at
output compile.

### Scalar shortcuts

There are **11** shortcuts, each binding one scalar and each **position-agnostic**
(usable in an `ObjectType` body *and* a `class Arguments` body). Each returns a
`Field`. Signature:
`(*, source=None, required=False, default=_UNSET, description=None, name=None, resolver=None, deprecation_reason=None)`
(`JSONField` additionally takes `as_str=False`).

| Shortcut | GraphQL type |
|----------|--------------|
| `IDField` | `ID` |
| `IntField` | `Int` |
| `FloatField` | `Float` |
| `BooleanField` | `Boolean` |
| `CharField` | `String` |
| `DateField` | `CustomDate` |
| `DateTimeField` | `CustomDateTime` |
| `TimeField` | `CustomTime` |
| `DecimalField` | `Decimal` |
| `UUIDField` | `UUID` |
| `JSONField` | `JSON` (or `JSONString` with `as_str=True`) |

The 12 former `*InputField` twins (`CharInputField`, `IntInputField`, …) and the
standalone `InputField` descriptor are **removed** in 2.0 — the single `Field`
and these shortcuts cover both positions.

!!! note "Date/time scalars and JSON"
    The date/time shortcuts render as `CustomDate` / `CustomDateTime` /
    `CustomTime` (v1 SDL parity; the plain `Date` / `DateTime` / `Time` names
    belong to the filter-lookup scalars). `JSONField()` binds the raw `JSON`
    scalar (structured JSON on the wire); `JSONField(as_str=True)` binds the
    string-encoded `JSONString` escape hatch. See
    [Accepted date/time input formats](../usage/types.md#accepted-datetime-input-formats)
    and [`JSONField` → `JSON`](../usage/types.md#jsonfield-json).

!!! warning "Import from `django_graphex.core`, not `django.db.models`"
    `django.db.models` also exports `CharField`, `IntegerField`, etc. Declaring a
    **model** field where a descriptor is expected raises a loud `TypeError`
    naming the likely import mistake — on both the type-body and mutation-argument
    paths. Always import descriptors from `django_graphex.core`.

!!! note "`field()` is the low-level substrate"
    The descriptors are sugar over the public `field(type, *, description=None,
    args=None, resolver=None, name=None, required_perms=None)` helper, which stays
    public and unchanged. `field()` has no `source=` / `required=` (those live on
    the descriptors); use it for the raw graphql-core-typed primitive.

## DjangoObjectType

Enhanced Django model GraphQL type with filtering and pagination support.

```python
class DjangoObjectType(ObjectType)
```

### Meta Configuration

The `DjangoObjectType` is configured through a nested `Meta` class:

```python
class UserType(DjangoObjectType):
    class Meta:
        model = User
        only_fields = ('id', 'username', 'email')
        filter_fields = {'username': ('exact', 'icontains')}
```

### Meta Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `model` | `Model` | Required | Django model class |
| `registry` | `Registry` | Global registry | Type registry instance |
| `skip_registry` | `bool` | `False` | Skip automatic type registration |
| `only_fields` | `tuple/list` | `()` | Include only specified fields |
| `exclude_fields` | `tuple/list` | `()` | Exclude specified fields |
| `include_fields` | `tuple/list` | `()` | Additional fields to include |
| `filter_fields` | `dict` | `None` | Field filtering configuration |
| `interfaces` | `tuple` | `()` | GraphQL interfaces to implement |
| `description` | `str` | `None` | GraphQL description for this type; defaults to the class docstring when omitted |
| `unions` | `dict` | `None` | Mapping of `GenericForeignKey` field name → `DjangoUnionType` subclass; enables typed GFK targets instead of `GenericForeignKeyType`. Renamed from `gfk_unions` in 2.0 — the old key raises `ImproperlyConfigured`. |
| `max_depth` | `int` | `None` | Max nested-object depth below this type (see [Query depth limiting](../usage/query-limits.md#query-depth-limiting)) |
| `complexity` | `int` | `None` | Cost weight of a field returning this type (see [Query cost analysis](../usage/query-limits.md#query-cost-analysis)) |

!!! warning "Unknown Meta options raise ImproperlyConfigured"
    Any key not in the table above is rejected at server startup with
    `django.core.exceptions.ImproperlyConfigured`. A previously silent typo
    (e.g. `filter_Filed`) now surfaces immediately. See also
    [Meta options are validated](../usage/types.md#meta-options-validated).

### Methods

#### `resolve_id(info)`

Resolve the ID field for the object.

**Returns:** Primary key value of the model instance

#### `is_type_of(root, info)` (classmethod)

Check if the root object is of this type.

**Parameters:**
- `root` (`Any`): Object to check
- `info` (`ResolveInfo`): GraphQL resolve info

**Returns:** `bool` - True if object matches this type

#### `get_queryset(queryset, info)` (classmethod)

Override to customize the queryset used for this type.

**Parameters:**
- `queryset` (`QuerySet`): Base queryset
- `info` (`ResolveInfo`): GraphQL resolve info

**Returns:** Modified `QuerySet`

#### `get_node(info, id)` (classmethod)

Get a single node by ID.

**Parameters:**
- `info` (`ResolveInfo`): GraphQL resolve info
- `id` (`Any`): Object identifier

**Returns:** Model instance or `None`

### Example Usage

=== "Basic Type"

    ```python
    from django_graphex.types import DjangoObjectType
    from .models import User

    class UserType(DjangoObjectType):
        class Meta:
            model = User
            description = "User account type"
    ```

=== "With Filtering"

    ```python
    class UserType(DjangoObjectType):
        class Meta:
            model = User
            filter_fields = {
                'username': ('exact', 'icontains'),
                'email': ('exact', 'icontains'),
                'is_active': ('exact',),
                'date_joined': ('gte', 'lte'),
            }
    ```

=== "Field Control"

    ```python
    class UserType(DjangoObjectType):
        class Meta:
            model = User
            only_fields = ('id', 'username', 'email', 'first_name', 'last_name')
            # Alternative: exclude_fields = ('password', 'user_permissions')
    ```

=== "Custom Queryset"

    ```python
    class UserType(DjangoObjectType):
        class Meta:
            model = User

        @classmethod
        def get_queryset(cls, queryset, info):
            return queryset.select_related('profile').prefetch_related('posts')
    ```

---

## DjangoInputObjectType

Django model GraphQL input type for mutations and arguments.

```python
class DjangoInputObjectType(InputType)  # InputType = django_graphex.core
```

### Meta Configuration

Configure input types through the `Meta` class:

```python
class UserInput(DjangoInputObjectType):
    class Meta:
        model = User
        input_for = 'create'
        only_fields = ('username', 'email', 'first_name', 'last_name')
```

### Meta Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `model` | `Model` | Required | Django model class |
| `registry` | `Registry` | Global registry | Type registry instance |
| `skip_registry` | `bool` | `False` | Skip automatic registration |
| `only_fields` | `tuple/list` | `()` | Include only specified fields |
| `exclude_fields` | `tuple/list` | `()` | Exclude specified fields |
| `filter_fields` | `dict` | `None` | Field filtering configuration |
| `input_for` | `str` | `'create'` | Input purpose: 'create', 'update', or 'delete' |
| `nested_fields` | `tuple/dict` | `()` | Nested field configuration |
| `container` | `type` | Auto-generated | Container class for the input type |

### Methods

#### `get_type()` (classmethod)

Get the type when the unmounted type is mounted.

**Returns:** The input type class

### Example Usage

=== "Create Input"

    ```python
    from django_graphex.types import DjangoInputObjectType

    class UserCreateInput(DjangoInputObjectType):
        class Meta:
            model = User
            input_for = 'create'
            only_fields = ('username', 'email', 'first_name', 'last_name', 'password')
    ```

=== "Update Input"

    ```python
    class UserUpdateInput(DjangoInputObjectType):
        class Meta:
            model = User
            input_for = 'update'
            exclude_fields = ('password', 'date_joined')
    ```

=== "With Nested Fields"

    ```python
    class UserInput(DjangoInputObjectType):
        class Meta:
            model = User
            input_for = 'create'
            # field names to expand as nested input objects
            nested_fields = ('profile', 'addresses')
    ```

---

## DjangoListObjectType

GraphQL type for paginated lists of Django objects with count and results.

```python
class DjangoListObjectType(ObjectType)
```

### Meta Configuration

Configure list types with pagination and filtering:

```python
class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        pagination = LimitOffsetGraphqlPagination(default_limit=25)
```

### Meta Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `model` | `Model` | Required | Django model class |
| `registry` | `Registry` | Global registry | Type registry instance |
| `only_fields` | `tuple/list` | `()` | Include only specified fields |
| `exclude_fields` | `tuple/list` | `()` | Exclude specified fields |
| `include_fields` | `tuple/list` | `()` | Additional fields to include |
| `queryset` | `QuerySet` | `None` | Base queryset for the list |
| `description` | `str` | Auto-generated | Type description |
| `results_field_name` | `str` | `'results'` | Name of results field |
| `pagination` | `BaseDjangoGraphqlPagination` | `None` | Pagination configuration |
| `filter_fields` | `dict` | `None` | Field filtering configuration |
| `max_depth` | `int` | `None` | Max nested-object depth below this list type (see [Query depth limiting](../usage/query-limits.md#query-depth-limiting)) |
| `complexity` | `int` | `None` | Cost weight of a field returning this list type (see [Query cost analysis](../usage/query-limits.md#query-cost-analysis)) |

### Generated Fields

A `DjangoListObjectType` automatically generates these fields:

| Field | Type | Description |
|-------|------|-------------|
| `totalCount` | `Int` | Total number of objects |
| `results` | `List[ObjectType]` | Paginated list of objects |

Pagination and ordering arguments (`limit`, `offset`, `page`, `pageSize`, `first`,
`ordering`, cursor arguments) are placed on the `results(...)` subfield. `totalCount`
(and `pageInfo`, for cursor pagination) are siblings of `results`. Filter arguments
are placed on the list field itself.

### Methods

#### `RetrieveField(**kwargs)` (classmethod)

Create a field for retrieving a single object from this list type.

**Parameters:**
- `**kwargs`: Additional field arguments

**Returns:** `DjangoObjectField` instance

#### `BaseType()` (classmethod)

Return the base `DjangoObjectType` wrapped by this list type.

**Returns:** The base object type class

### Example Usage

=== "Basic List Type"

    ```python
    from django_graphex.paginations import LimitOffsetGraphqlPagination
    from django_graphex.types import DjangoListObjectType

    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            description = "Paginated list of users"
            pagination = LimitOffsetGraphqlPagination(default_limit=20)
    ```

=== "With Custom Pagination"

    ```python
    from django_graphex.paginations import PageGraphqlPagination

    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            pagination = PageGraphqlPagination(
                page_size=15,
                page_size_query_param='pageSize'
            )
            filter_fields = {
                'title': ('icontains',),
                'status': ('exact',),
                'author__username': ('icontains',),
            }
    ```

=== "Scoping via a custom resolver"

    ```python
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.core import ObjectType

    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            pagination = LimitOffsetGraphqlPagination(default_limit=25)

    class Query(ObjectType):
        active_users = DjangoListObjectField(UserListType)

        def resolve_active_users(self, info, **kwargs):
            # A `resolve_<field>` returning a QuerySet is honored by
            # `queryset_factory`, scoping the list's base queryset.
            return User.objects.filter(is_active=True).select_related('profile')
    ```

=== "Schema Integration"

    ```python
    from django_graphex.fields import DjangoListObjectField
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema

    class Query(ObjectType):
        # Preferred: DjangoListObjectField takes the list type directly
        all_users = DjangoListObjectField(UserListType)

        # RetrieveField() shorthand is available on DjangoListObjectType
        user = UserListType.RetrieveField()

    schema = DjangoGraphQLSchema(query=Query)
    ```

    !!! warning "`ListField()` is not available on `DjangoListObjectType`"
        `UserListType.ListField()` raises `AttributeError` — `ListField` is a
        classmethod on `DjangoModelType`, not on `DjangoListObjectType`. Use
        `DjangoListObjectField(UserListType)` instead.

### GraphQL Response Structure

```json
{
  "data": {
    "allUsers": {
      "totalCount": 150,
      "results": [
        {
          "id": "1",
          "username": "john_doe",
          "email": "john@example.com"
        },
        {
          "id": "2",
          "username": "jane_smith",
          "email": "jane@example.com"
        }
      ]
    }
  }
}
```

---

## DjangoModelType

GraphQL type with automatic CRUD operations driven directly by a Django model.

```python
class DjangoModelType(ObjectType)
```

### Meta Configuration

Configure model types with automatic CRUD operations:

```python
class UserType(DjangoModelType):
    class Meta:
        model = User
        pagination = LimitOffsetGraphqlPagination(default_limit=25)
```

### Meta Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `model` | `Model` | Required | Django model class |
| `pydantic_model` | `BaseModel` | Auto-generated | Pydantic model for custom validation; auto-generated from `model` when omitted |
| `queryset` | `QuerySet` | `None` | Base queryset for retrieve and list operations; honored by `get_queryset` |
| `pagination` | `BaseDjangoGraphqlPagination` | `None` | Pagination configuration |
| `only_fields` | `tuple/list` | `()` | Include only specified fields |
| `include_fields` | `tuple/list` | `()` | Additional fields to include |
| `exclude_fields` | `tuple/list` | `()` | Exclude specified fields |
| `input_field_name` | `str` | `new_{model_name}` | Name of the mutation input argument |
| `output_field_name` | `str` | `{model_name}` | Name of the mutation output field |
| `results_field_name` | `str` | `'results'` | Name of the results field |
| `nested_fields` | `tuple/dict` | `()` | Nested field configuration |
| `filter_fields` | `dict` | `None` | Field filtering configuration |
| `description` | `str` | Auto-generated | Type description |
| `stream` | `str` | `None` | Subscription stream name; required to expose a subscription field |
| `payload_mode` | `str` | `None` | Force `"full"` or `"id_only"` subscription payloads; `None` inherits the global setting |
| `subscription_index_fields` | `tuple/list` | `None` | Model field names used to route notifications to value-scoped subscriber groups |
| `max_depth` | `int` | `None` | Max nested-object depth below the generated output type (see [Query depth limiting](../usage/query-limits.md#query-depth-limiting)) |
| `complexity` | `int` | `None` | Cost weight of the generated output type (see [Query cost analysis](../usage/query-limits.md#query-cost-analysis)) |

### Generated Methods

#### `QueryFields(**kwargs)` (classmethod)

Generate both single object and list query fields.

**Returns:** Tuple of (`single_field`, `list_field`)

#### `ListField(**kwargs)` (classmethod)

Create a list field for this model type.

**Returns:** `DjangoListObjectField` instance

#### `RetrieveField(**kwargs)` (classmethod)

Create a retrieve field for single objects.

**Returns:** `DjangoObjectField` instance

#### `MutationFields(**kwargs)` (classmethod)

Generate the create, delete and update mutation fields.

**Returns:** Tuple of (`create_field`, `delete_field`, `update_field`)

#### `CreateField(**kwargs)` / `DeleteField(**kwargs)` / `UpdateField(**kwargs)` (classmethod)

Create the individual mutation fields wired to the `create`, `delete` and
`update` resolvers respectively.

**Returns:** `Field` instance

### Override Hooks

`DjangoModelType` exposes hooks you can override on your subclass to scope
querysets and enforce authorization across all CRUD operations:

#### `get_queryset(manager, info, **kwargs)` (classmethod)

Return the base queryset for retrieve, list and mutation responses. The default
uses `Meta.queryset` (falling back to the model's default manager) and applies
`filter_queryset`. Override to add `select_related`/`annotate`, etc.

#### `filter_queryset(qs, info, **kwargs)` (classmethod)

Per-request scoping hook. The default returns `qs` unchanged.

#### `authorize(info, action, **kwargs)` (classmethod)

Authorization hook called by every CRUD method before it runs. The default
delegates to `check_permissions` using the configured `permission_classes`,
raising `GraphQLError` when denied. Override to customize.

#### `permission_classes` (class attribute)

Tuple of permission classes checked per action. Empty (the default) means no
checks. See `django_graphex.permissions`.

### Example Usage

=== "Basic Model Type"

    ```python
    from django_graphex.types import DjangoModelType
    from .models import User

    class UserType(DjangoModelType):
        class Meta:
            model = User
            description = "User type"
    ```

=== "With Pagination and Filtering"

    ```python
    class UserType(DjangoModelType):
        class Meta:
            model = User
            pagination = LimitOffsetGraphqlPagination(default_limit=30)
            filter_fields = {
                'username': ('exact', 'icontains'),
                'email': ('exact', 'icontains'),
                'is_active': ('exact',),
            }
    ```

=== "Schema Integration"

    ```python
    from django_graphex.core import ObjectType
    from django_graphex.schema import DjangoGraphQLSchema

    class Query(ObjectType):
        # Generate both fields automatically
        user, users = UserType.QueryFields()

        # Or create individual fields
        user_list = UserType.ListField()
        single_user = UserType.RetrieveField()

    schema = DjangoGraphQLSchema(query=Query)
    ```

---

## Type Registration

All types are automatically registered in a global registry for reuse and relationship resolution.

### Registry Operations

```python
from django_graphex.registry import get_global_registry

# Get the global registry
registry = get_global_registry()

# Check if a type is registered
user_type = registry.get_type_for_model(User)

# Register a type manually
registry.register(CustomUserType)
```

### Custom Registry

`Registry` is part of the public API and can be imported directly from
`django_graphex`:

```python
from django_graphex.registry import Registry

# Create custom registry
custom_registry = Registry()

class UserType(DjangoObjectType):
    class Meta:
        model = User
        registry = custom_registry
```

## Advanced Usage

### Custom Field Resolvers

```python
from django_graphex.core import CharField, IntField

class UserType(DjangoObjectType):
    full_name = CharField()
    post_count = IntField()

    class Meta:
        model = User

    def resolve_full_name(self, info):
        return f"{self.first_name} {self.last_name}"

    def resolve_post_count(self, info):
        return self.posts.count()
```

### Dynamic Field Generation

```python
class UserType(DjangoObjectType):
    class Meta:
        model = User

    @classmethod
    def __init_subclass_with_meta__(cls, **options):
        # Add dynamic fields before calling super
        from django_graphex.core import CharField
        cls.custom_field = CharField()
        super().__init_subclass_with_meta__(**options)
```

### Performance Optimization

```python
class UserType(DjangoObjectType):
    class Meta:
        model = User
        filter_fields = {
            'username': ('exact', 'icontains'),
            'email': ('exact',),
        }

    @classmethod
    def get_queryset(cls, queryset, info):
        # Optimize queries with select_related and prefetch_related
        return queryset.select_related(
            'profile'
        ).prefetch_related(
            'posts',
            'posts__comments'
        )
```

## Error Handling

### Type Validation

```python
class UserType(DjangoObjectType):
    class Meta:
        model = User

    @classmethod
    def is_type_of(cls, root, info):
        # Custom type checking logic
        if hasattr(root, 'user_type'):
            return root.user_type == 'standard'
        return super().is_type_of(root, info)
```

### Field Resolution Errors

```python
from django_graphex.core import CharField

class UserType(DjangoObjectType):
    avatar_url = CharField()

    class Meta:
        model = User

    def resolve_avatar_url(self, info):
        try:
            if self.profile and self.profile.avatar:
                return self.profile.avatar.url
            return None
        except AttributeError:
            return None
```

## Best Practices

!!! tip "Type Best Practices"

    1. **Use Descriptive Names**: Choose clear, descriptive type names
    2. **Control Field Exposure**: Use `only_fields` or `exclude_fields` appropriately
    3. **Optimize Queries**: Implement `get_queryset` for performance optimization
    4. **Handle Null Values**: Always handle potential null values in resolvers
    5. **Document Types**: Provide meaningful descriptions for types and fields
    6. **Separate Concerns**: Use different input types for different operations

### Security Considerations

```python
class UserType(DjangoObjectType):
    class Meta:
        model = User
        # Don't expose sensitive fields
        exclude_fields = (
            'password', 'user_permissions',
            'groups', 'is_superuser'
        )

    @classmethod
    def get_queryset(cls, queryset, info):
        # Apply security filters
        if not info.context.user.is_staff:
            return queryset.filter(is_active=True)
        return queryset
```

!!! tip "The projection reaches subscriptions too"
    `only_fields` / `exclude_fields` on a `DjangoModelType` (or directly on a
    `Subscription`) also gate the generated subscription: an excluded column is
    absent from the event type, from the broadcast payload, and from the set a
    client `filters` key may root on. Since client filters run as ORM lookups at
    delivery time, that projection is the supported way to keep a sensitive
    column off the subscription surface — see
    [Subscriptions › Filter key validation](../usage/subscriptions.md#filter-key-validation).

    A client filter may only use `exact`, `iexact`, `in` or `isnull` (a bare
    field name means `exact`), so a **declared** column can be tested for
    equality but not walked with `startswith` / `gt` / `icontains`. The
    projection is still what keeps it off the surface entirely.

    (Fixed in 2.0.1: 2.0.0 silently dropped the option on the subscription path,
    so the excluded column stayed both serialized and filterable.)

---

## DjangoUnionType

GraphQL Union over explicitly enumerated `DjangoObjectType` members.

```python
class DjangoUnionType(ObjectType)  # ObjectType = django_graphex.core
```

### Meta Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `types` | `tuple[DjangoObjectType, ...]` | Required (≥ 1) | Member types of the union. Members are enumerated explicitly — the `django_content_type` table is never queried to discover them. |

### Declaration Order (load-bearing)

1. Declare all **member** `DjangoObjectType`s first.
2. Declare the `DjangoUnionType` with `Meta.types`.
3. Declare the **owner** `DjangoObjectType` LAST, referencing the union via `Meta.unions` (renamed from `gfk_unions` in 2.0; the old key raises `ImproperlyConfigured`).

A mis-ordered declaration logs a `WARNING` and falls back to `GenericForeignKeyType` — the schema still builds.

### Methods

#### `resolve_type(instance, info)` (classmethod)

Maps a Django model instance to its registered `DjangoObjectType` via the
global registry. **Raises** a descriptive `TypeError` if no type is registered
for the instance's model (rather than returning `None`, which would surface an
opaque GraphQL error).

You do not override this method.

### Example Usage

```python
from django_graphex.types import DjangoObjectType, DjangoUnionType

class AccountType(DjangoObjectType):
    class Meta:
        model = Account

class InvoiceType(DjangoObjectType):
    class Meta:
        model = Invoice

class CommentTargetUnion(DjangoUnionType):
    class Meta:
        types = (AccountType, InvoiceType)

class CommentType(DjangoObjectType):
    class Meta:
        model = Comment              # has `target = GenericForeignKey(...)`
        unions = {"target": CommentTargetUnion}
```

See [Types — DjangoUnionType](../usage/types.md#djangouniontype-typed-genericforeignkey-targets) for the full usage guide including optimizer behavior.

---

## DjangoInterfaceType

GraphQL Interface for shared field declarations across multiple
`DjangoObjectType` implementors.

```python
class DjangoInterfaceType(ObjectType)  # ObjectType = django_graphex.core
```

### Meta Options

No additional Meta options beyond the GraphQL interface basics.
Implementors declare membership via the `Meta.interfaces` kwarg.

### Methods

#### `resolve_type(instance, info)` (classmethod)

Maps a Django model instance to its registered concrete `DjangoObjectType` implementor
via the global registry. **Raises** `TypeError` if the instance's model has no
registered type.

You do not override this method.

### Example Usage

```python
from django_graphex.core import CharField
from django_graphex.types import DjangoInterfaceType, DjangoObjectType

class ProductInterface(DjangoInterfaceType):
    name = CharField()

    class Meta:
        pass

class BookType(DjangoObjectType):
    class Meta:
        model = Book
        interfaces = (ProductInterface,)

class MagazineType(DjangoObjectType):
    class Meta:
        model = Magazine
        interfaces = (ProductInterface,)
```

See [Types — DjangoInterfaceType](../usage/types.md#djangointerfacetype-shared-fields-across-types) for the full usage guide.

---

This comprehensive API reference covers all type classes in `django-graphex`, providing developers with the knowledge needed to effectively create and customize GraphQL types for their Django applications.
