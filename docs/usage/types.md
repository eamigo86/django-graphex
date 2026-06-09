# Types

django-graphex provides enhanced type classes built on top of graphene's basic functionality.

!!! note "Model `choices` → GraphQL enum"

    A model field with `choices` is converted to a GraphQL enum automatically.
    Every declaration form is supported, including the Django 5.0 forms — an
    enumeration type (`TextChoices` / `IntegerChoices`), a mapping, or a callable —
    on all supported Django versions (the converter normalizes them). See
    [`choices` → GraphQL enums](#choices-graphql-enums) for how member names are
    derived.

## DjangoObjectType

The base node type: it maps a Django model to a GraphQL object type. Declare a
model and the library converts its fields (including `choices` → enums and
relations → nested list types). It is the building block every other type and
field resolves to.

```python
from django_graphex import DjangoObjectType
from django.contrib.auth.models import User

class UserType(DjangoObjectType):
    class Meta:
        description = "Type definition for a single user"
        model = User
        # Optional: restrict / shape the exposed fields.
        only_fields = ("id", "username", "email", "is_active")
        # Enables `filter:` when this type is used as a (nested) list.
        filter_fields = {"username": ("exact", "icontains")}
```

Use it directly with [`DjangoObjectField`](fields.md#djangoobjectfield) to fetch a
single object by id, as the node of a [`DjangoListObjectType`](#djangolistobjecttype),
or as the output of a [mutation](mutations.md). Relations on the model are exposed
as nested lists with the uniform `results` / `totalCount` shape — see
[Nested lists](nested-lists.md).

!!! tip "Per-request queryset"
    Override `get_queryset(cls, queryset, info)` to scope what a type returns
    (e.g. only the current user's rows). See
    [Custom queryset](#custom-queryset-per-request-filtering).

## DjangoListObjectType

!!! tip "Recommended for Types"
    Extends DjangoObjectType with built-in pagination and filtering support.

```python
from django_graphex import DjangoListObjectType
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django.contrib.auth.models import User

class UserListType(DjangoListObjectType):
    class Meta:
        description = "Type definition for user list"
        model = User
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25,
            ordering="-date_joined"
        )
        filter_fields = {
            "username": ("exact", "icontains"),
            "email": ("exact", "icontains"),
            "is_active": ("exact",),
        }
```

### Features

- **Built-in Pagination**: Automatic pagination with configurable settings
- **Filtering**: Built on Django's ORM lookups + `Q` objects (no django-filter)
- **Ordering**: Custom ordering options
- **Caching**: Optional query result caching
- **Custom Queryset**: Override default queryset behavior

### Configuration Options

```python
class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        description = "User list with advanced features"

        # Pagination
        pagination = LimitOffsetGraphqlPagination(
            default_limit=20,
            max_limit=100,
            ordering=("-date_joined", "username")
        )

        # Filtering
        filter_fields = {
            "username": ("exact", "icontains", "istartswith"),
            "email": ("exact", "icontains"),
            "date_joined": ("exact", "gte", "lte"),
            "is_active": ("exact",),
            "groups": ("exact",),
        }

        # Custom queryset
        queryset = User.objects.select_related('profile')

        # Field restrictions
        fields = ("id", "username", "email", "first_name", "last_name")
        exclude = ("password",)
```

### Helper Methods

```python
class Query(graphene.ObjectType):
    # Get both list and retrieve fields
    users = UserListType.ListField(description="List all users")
    user = UserListType.RetrieveField(description="Get single user")
```

## DjangoInputObjectType

Creates input types for mutations based on Django models.

```python
from django_graphex import DjangoInputObjectType
from django.contrib.auth.models import User

class UserInput(DjangoInputObjectType):
    class Meta:
        description = "User input for mutations"
        model = User
        fields = ("username", "email", "first_name", "last_name")
        # or exclude specific fields
        # exclude = ("password", "date_joined", "last_login")
```

### Advanced Configuration

```python
import graphene
from django_graphex import DjangoInputObjectType

class UserCreateInput(DjangoInputObjectType):
    """Input for creating new users"""

    # Add custom fields
    confirm_password = graphene.String(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "password")
        description = "Input type for user creation"

class UserUpdateInput(DjangoInputObjectType):
    """Input for updating existing users"""

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")
        description = "Input type for user updates"
```

### Usage in Mutations

```python
class CreateUserMutation(graphene.Mutation):
    class Arguments:
        input = UserCreateInput(required=True)

    user = graphene.Field(UserType)
    success = graphene.Boolean()

    def mutate(self, info, input):
        # Access input fields
        username = input.username
        email = input.email
        # ... mutation logic
```

## DjangoModelType

!!! tip "Recommended for Quick Setup"
    Automatically generates types, queries, and mutations from a Django model.
    All writable model fields are covered, `choices` become enums, FK fields
    accept a pk, and M2M fields accept a list of pks. Partial updates and DB
    integrity checks (FK existence, uniqueness, `unique_together`) are handled
    automatically.

```python
from django.contrib.auth.models import User
from django_graphex import DjangoModelType
from django_graphex.paginations import LimitOffsetGraphqlPagination

class UserModelType(DjangoModelType):
    class Meta:
        description = "User model type with auto-generated operations"
        model = User
        pagination = LimitOffsetGraphqlPagination(
            default_limit=25,
            ordering="-date_joined"
        )
        filter_fields = {
            "username": ("exact", "icontains"),
            "email": ("exact", "icontains"),
            "is_active": ("exact",),
        }
```

!!! note "Custom base queryset"

    Pass a `Meta.queryset` to scope every retrieve/list to a base queryset
    (e.g. `queryset = User.objects.filter(is_active=True)`). It is honored by the
    generated `RetrieveField()` / `ListField()`.

### Custom queryset & per-request filtering

For anything beyond a static `Meta.queryset`, override two hooks. `info.context`
is the request:

```python
from django.db.models import Count, F

class PropertyManagerType(DjangoModelType):
    class Meta:
        model = PropertyManager

    @classmethod
    def get_queryset(cls, manager, info, **kwargs):
        # custom base queryset for retrieve/list (and mutation responses)
        return PropertyManager.objects.select_related("user").annotate(
            email=F("user__email"),
            lease_count=Count("leases"),
        )

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        # per-request scoping; default returns `qs` unchanged
        user = info.context.user
        if user.is_superuser:
            return qs
        return qs.filter(company=user.company)
```

- `get_queryset(cls, manager, info, **kwargs)` supplies the base queryset and
  applies `filter_queryset`; the default uses `Meta.queryset` (else the model
  manager).
- `filter_queryset(cls, qs, info, **kwargs)` is the scoping hook; the default is a
  no-op.

!!! note "Mutation responses"

    `create` / `update` re-read the mutated object through `get_queryset` so
    annotated/related fields resolve in the response (one extra query). If
    `filter_queryset` would exclude it, the response falls back to the saved
    object — a mutation never returns `null` for what it just wrote.

### Custom output fields

To expose a field that isn't a plain model column (a model `@property`, an
annotated value, a computed URL…), declare it **directly on the
`DjangoModelType`**.
It is added to the generated output type, so it shows up in **both**
`RetrieveField()` and `ListField()` — no separate `DjangoObjectType` required:

```python
import graphene

class PropertyManagerType(DjangoModelType):
    # Plain graphene fields, resolved from the instance (here from the
    # annotations added in get_queryset above, and a model property).
    lease_count = graphene.Int(source="lease_count")
    email = graphene.String(source="email")
    logo_url = graphene.String(source="logo_url")   # a model @property

    class Meta:
        model = PropertyManager
```

- The field is resolved like any graphene field: `source="x"` reads
  `getattr(instance, "x")`, or add a `resolve_<name>` method for custom logic.
- It appears in the detail **and** the list, because the list reuses the same
  item type.

#### `resolve_<field>` methods

A custom field can also be backed by a **`resolve_<field>` method** declared on
the `DjangoModelType` — not just `source=`. The resolver is forwarded onto the
generated output type, so it runs for both the retrieve and the list. This lets a
custom field return another GraphQL type with arbitrary logic:

```python
import graphene
from django_graphex import DjangoModelType
from myapp.types import PersonType
from myapp.models import Company

class CompanyType(DjangoModelType):
    # A computed object field, resolved by the method below.
    owner = graphene.Field(PersonType)

    class Meta:
        model = Company

    def resolve_owner(self, info):
        # `self` is the Company instance being serialized; return any object
        # PersonType can resolve (here, the primary contact).
        return self.contacts.filter(is_primary=True).first()
```

- The method name must be `resolve_<field>` where `<field>` is the
  attribute name of a custom field declared on the class. It receives
  `(self, info)`, with `self` bound to the model instance and `info.context`
  the request.
- The most-derived `resolve_<field>` wins, so a subclass can override an
  inherited resolver by redeclaring the method.
- A `resolve_<x>` without a matching custom field is ignored (it is not forwarded
  to the output type).

Custom fields are **inherited** like normal class attributes, so shared fields
can live on an abstract base and a subclass may override one by redeclaring it:

```python
class TimestampedType(DjangoModelType):
    age = graphene.String(source="age_display")   # shared by subclasses

    class Meta:
        abstract = True

class InvoiceType(TimestampedType):
    total = graphene.Int(source="total_cents")     # adds its own

    class Meta:
        model = Invoice        # gets `age` + `total`
```

!!! warning "Don't mix with a hand-written `DjangoObjectType`"

    These two ways are mutually exclusive per model. If a `DjangoObjectType` is
    already registered for the model, the `DjangoModelType` reuses it and fields
    declared here are **ignored with a warning** — put them on that
    `DjangoObjectType` instead.

### Auto-generated Query Fields

```python
class Query(graphene.ObjectType):
    # Generate both retrieve and list queries automatically
    user_retrieve, user_list = UserModelType.QueryFields(
        description='User queries',
        deprecation_reason='Optional deprecation message'
    )

    # Or define them separately
    user_detail = UserModelType.RetrieveField(
        description='Get single user by ID'
    )
    user_list_custom = UserModelType.ListField(
        description='List users with filtering and pagination'
    )
```

### Auto-generated Mutation Fields

```python
class Mutation(graphene.ObjectType):
    # Generate all CRUD mutations
    user_create, user_delete, user_update = UserModelType.MutationFields(
        description='User CRUD operations'
    )

    # Or define them separately
    create_user = UserModelType.CreateField(description='Create new user')
    delete_user = UserModelType.DeleteField(description='Delete user')
    update_user = UserModelType.UpdateField(description='Update user')
```

### Custom validation with Pydantic

To add field-level validation beyond the automatic DB checks, supply a Pydantic
model via `Meta.pydantic_model`. Validators use the standard
`@field_validator` decorator with `check_fields=False` so the model can be kept
slim:

```python
from pydantic import BaseModel, field_validator
from django.contrib.auth.models import User
from django_graphex import DjangoModelType

class UserValidation(BaseModel):
    username: str
    email: str

    @field_validator("email", check_fields=False)
    @classmethod
    def email_must_be_corporate(cls, v):
        if not v.endswith("@example.com"):
            raise ValueError("Only corporate email addresses are accepted.")
        return v

class UserModelType(DjangoModelType):
    class Meta:
        model = User
        pydantic_model = UserValidation
```

### Validation errors

When a create/update fails validation, the mutation returns `ok: false` and an
`errors` list of `{ field, messages }`:

```json
{ "ok": false, "errors": [{ "field": "email", "messages": ["Enter a valid email."] }] }
```

- Errors from **nested** writes (`Meta.nested_fields`) are reported with the
  nested field name as a prefix — `field: "addresses.zip_code"` — including
  nested list children.
- `non_field_errors` is surfaced with an empty `field` (or just the nested model
  name).

## Limiting query shape: `max_deep` & `complexity`

Every type above accepts two optional `Meta` options that protect your API from
abusive queries. They are enforced **before execution** by the validation rules
the library's `GraphQLView` enables by default. See
[Query depth & cost limits](query-limits.md) for the full reference; the
mini-examples below are the gist.

**`max_deep`** — caps how many nested object levels may be selected below a field
returning this type (scalars don't count):

```python
class RentalCompanyType(DjangoModelType):
    class Meta:
        model = RentalCompany
        max_deep = 2          # company -> properties -> units OK; one level deeper is rejected
```

```graphql
rentalCompany {
  properties {        # level 1 ✅
    units {           # level 2 ✅
      tenant { name } # level 3 ❌ "Query exceeds the maximum nesting depth of 2 ..."
    }
  }
}
```

**`complexity`** — the cost weight of a field returning this type, used by cost
analysis (`MAX_QUERY_COST`). Make expensive types cost more so a single page of
them eats more of the budget:

```python
class ReportType(DjangoObjectType):
    class Meta:
        model = Report
        complexity = 50       # one report is worth 50; default object weight is 1
```

Both work on `DjangoObjectType`, `DjangoListObjectType` and `DjangoModelType`
(forwarded to its generated output type). A global depth cap (`MAX_QUERY_DEPTH`)
and cost budget (`MAX_QUERY_COST`) are configured in settings — see
[Query depth & cost limits](query-limits.md).

## `choices` → GraphQL enums

Any model field with `choices` becomes a GraphQL **enum** automatically — on
every type above (`DjangoObjectType`, `DjangoListObjectType`, `DjangoModelType`).
The interesting part is how each enum **member name** is chosen, because GraphQL
enum names must be valid identifiers (letters, digits, underscores; not starting
with a digit) and should stay readable and stable across locales.

For each `(value, label)` choice the name is picked by this cascade:

1. **The value**, if it is already a valid GraphQL name — e.g. a Django
   `TextChoices` value `"draft"` becomes `DRAFT`.
2. **Otherwise the label**, resolved as its *source* msgid with translations
   **off**, so the schema is the same in every locale. This is why numeric values
   with human labels surface readably:

    ```python
    GENDER_CHOICES = (("1", _("Male")), ("2", _("Female")))
    # -> enum members MALE / FEMALE   (NOT A_1 / A_2, and locale-independent)
    ```

3. **Otherwise `A_<value>`** as a last resort — e.g. a numeric value whose label
   is empty or also non-identifier-safe yields `A_1`, `A_2`, …

```python
from django.db import models
from django.utils.translation import gettext_lazy as _

class Profile(models.Model):
    # value -> member name
    status = models.CharField(                  # "draft" -> DRAFT (from the value)
        max_length=20,
        choices=(("draft", "Draft"), ("published", "Published")),
    )
    gender = models.CharField(                   # "1"/"2" -> MALE/FEMALE (from the label)
        max_length=1,
        choices=(("1", _("Male")), ("2", _("Female"))),
    )
```

The enum member's *description* carries the original label, so the
human-readable text is never lost.

## Type Comparison

| Feature | DjangoListObjectType | DjangoInputObjectType | DjangoModelType |
|---------|---------------------|----------------------|---------------------|
| **Purpose** | List queries with pagination | Input for mutations | Complete CRUD operations |
| **Pagination** | ✅ Built-in | ❌ N/A | ✅ Built-in |
| **Filtering** | ✅ Built-in | ❌ N/A | ✅ Built-in |
| **Auto Queries** | Manual setup | ❌ N/A | ✅ Auto-generated |
| **Auto Mutations** | ❌ No | ❌ N/A | ✅ Auto-generated |
| **Auto-derived Schema** | ❌ No | ❌ No | ✅ Full (from model) |
| **Customization** | High | High | Medium |
| **Setup Complexity** | Medium | Low | Low |

## Best Practices

### 1. Choose the Right Type

```python
# ✅ For list queries with custom logic
class UserListType(DjangoListObjectType):
    class Meta:
        model = User

# ✅ For input validation
class UserInput(DjangoInputObjectType):
    class Meta:
        model = User
        fields = ("username", "email")

# ✅ For rapid prototyping
class UserModelType(DjangoModelType):
    class Meta:
        model = User
```

### 2. Use Descriptive Names

```python
# ✅ Clear naming
class UserListType(DjangoListObjectType): pass
class CreateUserInput(DjangoInputObjectType): pass
class UserCRUDType(DjangoModelType): pass

# ❌ Confusing naming
class UserType(DjangoListObjectType): pass  # Is it single or list?
class UserInput(DjangoModelType): pass  # Not an input type
```

### 3. Optimize Performance

```python
class UserListType(DjangoListObjectType):
    class Meta:
        model = User
        # Optimize database queries
        queryset = User.objects.select_related('profile').prefetch_related('groups')

        # Limit exposed fields
        fields = ("id", "username", "email", "first_name", "last_name")

        # Enable caching for expensive queries
        # (Configure in settings)
```

### 4. Combine Types Strategically

```python
# Use DjangoModelType for basic CRUD
class UserModelType(DjangoModelType):
    class Meta:
        model = User

# Use DjangoListObjectType for complex list logic
class UserAnalyticsType(DjangoListObjectType):
    total_posts = graphene.Int()

    class Meta:
        model = User

    def resolve_total_posts(self, info):
        return self.posts.count()

# Use DjangoInputObjectType for complex input validation
class UserRegistrationInput(DjangoInputObjectType):
    confirm_password = graphene.String(required=True)
    terms_accepted = graphene.Boolean(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password")
```
