# Types

django-graphex provides enhanced type classes built directly on graphql-core.

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
from django_graphex.types import DjangoObjectType
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

### Custom per-field filter arguments — `@filter_field`

*Added in v1.3.0.* Use the `@filter_field` decorator to expose a **custom
GraphQL filter argument** directly on the type, co-located with its logic:

```python
from graphql import GraphQLString
from django.db.models import Q
from django_graphex.filtering import filter_field
from django_graphex.types import DjangoObjectType

class PostType(DjangoObjectType):
    class Meta:
        model = Post
        filter_fields = {"title": ("exact", "icontains")}

    @filter_field(GraphQLString, description="Full-text search")
    def search(cls, queryset, info, value):
        return queryset.filter(
            Q(title__icontains=value) | Q(body__icontains=value)
        )
```

See [Filtering — `@filter_field`](filtering.md#custom-per-field-filters-filter_field)
for the full reference including type override, composition order, and reserved
argument names.

### Custom queryset (per-request filtering)

Override `get_queryset(cls, queryset, info)` to scope what a type exposes on a
per-request basis — for example, to restrict rows to the current user's data:

```python
class ArticleType(DjangoObjectType):
    class Meta:
        model = Article
        filter_fields = {"title": ("icontains",)}

    @classmethod
    def get_queryset(cls, queryset, info):
        # Only expose articles owned by the requesting user.
        return queryset.filter(owner=info.context.user)
```

The hook is called by all four top-level field types **before** the query
optimizer runs, so `select_related` / `prefetch_related` are applied on top of
the already-narrowed queryset — the same interplay described for
`DjangoModelType.Meta.queryset` in the [optimizer docs](query-optimization.md):

| Field type | `get_queryset` applied? |
|---|---|
| [`DjangoObjectField`](fields.md#djangoobjectfield) | ✅ yes |
| [`DjangoFilterListField`](fields.md#djangofilterlistfield) | ✅ yes |
| [`DjangoFilterPaginateListField`](fields.md#djangofilterpaginatelistfield) | ✅ yes |
| [`DjangoListObjectField`](fields.md#djangolistobjectfield) (`results` + `totalCount`) | ✅ yes |

Both `results` **and** `totalCount` reflect the hook — the hook is applied
before the `COUNT` query is issued.

The hook applies **wherever the field is mounted**, root or nested: a
`DjangoFilterListField` you mount by hand on a parent type (e.g.
`created_posts = DjangoFilterListField(PostType)` on `AuthorType`) scopes its
rows even when it is reached through the parent's relation, not only at the top
level.

!!! warning "The hook must return a `QuerySet`"
    Returning anything else (most often a missing `return`, so `None`) raises
    `TypeError`.  The request is denied rather than served with the scope
    silently skipped.

!!! note "Cost of scoping a hand-mounted relation field"
    A `DjangoFilterListField` mounted on a parent type normally reads the rows
    straight out of the parent's prefetch cache.  When the child type declares a
    `get_queryset` scope, that scope has to be applied to the relation, which
    issues one query per parent instead.  Types that declare no scope keep the
    cache and the single query.

!!! note "Remaining boundary: auto-expanded nested-relation fields"
    Relation fields that django-graphex **auto-expands** to a nested list
    (e.g. a `ForeignKey` reverse relation exposed as
    `allAuthors { results { posts { results { title } } } }`, resolved by
    `DjangoNestedListObjectField`) use the parent's prefetch cache and do
    **not** call the child type's `get_queryset`.  This is intentional: wiring
    the hook there would require rebuilding the prefetch queryset inside the
    resolver, which conflicts with the window-pagination and prefetch
    optimizations.  If you need per-relation row scoping there, either mount the
    relation explicitly as a `DjangoFilterListField` (which does apply the hook)
    or add a `resolve_<relation>` method on the parent type.

!!! note "DjangoModelType uses a different hook"
    `DjangoModelType` has its own queryset-scoping API (`get_queryset` +
    `filter_queryset`) with a different signature (`manager, info, **kwargs`).
    That hook is called earlier, at the CRUD-method level, and is unaffected by
    this change.  Do not mix the two APIs.

### Meta options are validated { #meta-options-validated }

Since v1.2.2 (#65), unknown or mistyped `Meta` options raise
`ImproperlyConfigured` at server startup instead of being silently ignored.
For example, a typo like `filter_Filed` (capital F) is caught immediately.

The full set of recognised options for `DjangoObjectType.Meta` is:

| Option | Description |
|--------|-------------|
| `model` | Django model class (required) |
| `registry` | Type registry instance |
| `skip_registry` | Skip automatic registration |
| `only_fields` | Include only the listed model fields |
| `exclude_fields` | Exclude the listed model fields |
| `include_fields` | Additional fields to include |
| `filter_fields` | Field filtering configuration |
| `interfaces` | GraphQL interfaces to implement |
| `max_depth` | Max nested-object depth below this type |
| `complexity` | Cost weight for query cost analysis |
| `description` | Type description exposed in the schema |

Any key not in this table is rejected at startup. Review your `DjangoObjectType`
and `DjangoListObjectType` subclasses for typos before upgrading from pre-1.2.2.

### Model inheritance { #model-inheritance }

**Abstract base** — Django copies the parent's columns onto the child, so they
appear on the child's type exactly once. Nothing special to do.

**Multi-table inheritance** — the parent keeps its own table and the child
holds a parent link. A type over the child picks up everything it inherits: the
parent's columns render alongside the child's own, and the parent's reverse
relations render as their usual `<Model>ListType` containers.

```python
class Place(models.Model):
    name = models.CharField(max_length=100)

class Review(models.Model):
    place = models.ForeignKey(Place, related_name="reviews", on_delete=models.CASCADE)

class Restaurant(Place):                 # multi-table inheritance
    serves_pizza = models.BooleanField(default=False)
```

```graphql
type RestaurantType {
  id: ID!                   # inherited from Place
  name: String              # inherited from Place
  servesPizza: Boolean
  reviews: ReviewListType   # inherited from Place
}
```

Before this, an inherited reverse relation had no compiled counterpart and the
whole schema build failed with `RestaurantType fields cannot be resolved`, while
the inherited columns — the primary key among them — were absent from the type.

The implicit parent link (`placePtr`) is deliberately not exposed: the child
already carries every inherited column, so the link would only offer a redundant
hop back to a copy of the same row.

## DjangoListObjectType

!!! tip "Recommended for Types"
    Extends DjangoObjectType with built-in pagination and filtering support.

```python
from django_graphex.types import DjangoListObjectType
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

A `DjangoListObjectType` concentrates all of its list behavior in `Meta`: the
paginator (with its default/max page size and ordering), the `filter_fields`
lookups exposed on the `filter:` argument, a custom base `queryset`, and the
usual field restrictions. The example below shows every common option in one
place:

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
        only_fields = ("id", "username", "email", "first_name", "last_name")
        exclude_fields = ("password",)
```

### Helper Methods

To mount a `DjangoListObjectType` on your `Query`, wrap it in a
[`DjangoListObjectField`](fields.md#djangolistobjectfield) — that produces the
paginated `results` / `totalCount` field with the declared filters. The type
also provides a `RetrieveField()` classmethod that builds a single-object
lookup (by `id`) from the same node type:

```python
from django_graphex.fields import DjangoListObjectField
from django_graphex.core import ObjectType

class Query(ObjectType):
    # Preferred: use DjangoListObjectField directly
    users = DjangoListObjectField(UserListType, description="List all users")
    # Or use the RetrieveField shorthand for a single object
    user = UserListType.RetrieveField(description="Get single user")
```

!!! warning "`ListField()` belongs to `DjangoModelType`, not `DjangoListObjectType`"

    `UserListType.ListField()` raises `AttributeError` — `ListField` is a
    classmethod on `DjangoModelType`, not on `DjangoListObjectType`. Use
    `DjangoListObjectField(UserListType)` instead.

## Declaring fields: the descriptor API

When a model doesn't already provide a field — a computed value, a hand-written
mutation payload, a custom argument — declare it with a **capitalized field
descriptor** imported from `django_graphex.core`. This is the primary idiom for
custom (non-model) fields:

```python
from django_graphex.core import CharField, IntField, Field, ObjectType

class UserType(ObjectType):
    full_name  = CharField(description="First + last")   # -> String
    post_count = IntField(required=True)                 # -> Int!
    email      = CharField(source="user_email")          # reads root.user_email

    def resolve_full_name(self, info):
        return f"{self.first_name} {self.last_name}"
```

Every descriptor compiles to the **exact same** graphql-core type as the
low-level `field()` substrate it wraps — the SDL is byte-identical. The
descriptors just give you a Django-model-field-style surface (`source=`,
`required=`, typed shortcuts) with real import-time names your IDE can resolve.

### Scalar shortcuts { #output-scalar-shortcuts }

Each shortcut binds one GraphQL scalar. There are **11** of them, and every one
is **position-agnostic** — the same shortcut works in an `ObjectType` body
(output) *and* in a `class Arguments` body (input). Use them anywhere you'd
hand-write `Field(<scalar>)`:

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

!!! note "The `Custom*` date/time scalar names"
    The output/argument date/time scalars render as `CustomDate` /
    `CustomDateTime` / `CustomTime`, matching the v1 (graphene-django) SDL for
    drop-in schema parity. The plain `Date` / `DateTime` / `Time` names are
    reserved for the **filter-lookup** scalars — see
    [Accepted date/time input formats](#accepted-datetime-input-formats).

Every shortcut accepts the same keyword surface (the same one the unified
`Field` accepts):

| Keyword | Effect |
|---------|--------|
| `required=True` | Wrap the type in non-null (`T!`). |
| `source="attr"` | **Output only.** Resolve by reading `attr` off the root object (or calling it if it's a method). |
| `default=value` | **Input only.** GraphQL default for the argument (an explicit `default=None` declares a real `null` default). |
| `description="..."` | Field / argument description in the SDL. |
| `name="wireName"` | Explicit wire name (skips the automatic camelCase pass). |
| `resolver=fn` | **Output only.** Field-level resolver (wins over the parent resolver). |
| `deprecation_reason="..."` | Marks the field / argument `@deprecated(reason: ...)`. |

Setting an output-only keyword (`source=` / `resolver=`) on a field used in an
argument position raises a clear `TypeError`; setting the input-only `default=`
in an output position raises a `TypeError` at output compile.

For a type with no named shortcut (a `DjangoObjectType` reference, a
`GraphQLList`/`GraphQLNonNull` wrapper, a custom scalar), use the general
`Field` descriptor — it takes any type positionally and offers the same surface:

```python
from graphql import GraphQLList, GraphQLString
from django_graphex.core import Field

class Query(ObjectType):
    me   = Field(UserType)                       # a DjangoObjectType reference
    tags = Field(GraphQLList(GraphQLString))     # list via the graphql-core wrapper
    slug = Field(GraphQLString, required=True)   # -> String!
```

### Custom fields with resolvers { #custom-fields-with-resolvers }

Descriptors work the same on a **`DjangoObjectType`**: declare the field on the
class body and it is merged with the model-derived fields. When `source=` isn't
enough, back the field with a **`resolve_<name>` method** — the contract is:

- The method name is `resolve_` + the **snake_case attribute name** of a field
  declared on the class (`full_name` → `resolve_full_name`).
- It is called as `resolve_<name>(self, info, **args)`: `self` is the object
  being serialized (the model instance on a `DjangoObjectType`), `info.context`
  is the request, and the field's declared arguments arrive as keyword arguments.
- Precedence: an explicit `resolver=` callable on the descriptor wins over the
  method; `source=` is the no-logic shortcut (it reads the named attribute off
  the instance, calling it if it's a method).

```python
from django.contrib.auth.models import User
from graphql import GraphQLArgument, GraphQLInt, GraphQLString
from django_graphex.core import CharField, Field
from django_graphex.types import DjangoObjectType

class UserType(DjangoObjectType):
    # source= shortcut — reads (or calls) `get_short_name` on the instance.
    initials = CharField(source="get_short_name")

    # Computed field backed by the resolve_full_name method below.
    full_name = CharField(description="First + last name")

    # A field with its own GraphQL arguments; the resolver reads them as kwargs.
    greeting = Field(
        GraphQLString,
        args={"width": GraphQLArgument(GraphQLInt)},
    )

    class Meta:
        model = User
        only_fields = ("id", "username", "first_name", "last_name")

    def resolve_full_name(self, info):
        return f"{self.first_name} {self.last_name}".strip()

    def resolve_greeting(self, info, width=None):
        text = f"Hello, {self.username}!"
        return text.center(width) if width else text
```

```graphql
{ user(id: 1) { fullName initials greeting(width: 30) } }
```

Argument dict keys are used **verbatim** as the wire names (declare a multi-word
argument in camelCase, e.g. `args={"maxWidth": ...}`); each argument reaches the
resolver as its **snake_case** keyword (`max_width`). The same contract applies
on a plain `ObjectType` root (see the `Query` examples above) and on a
[`DjangoModelType`](#resolve_field-methods), where the resolver is forwarded to
the generated output type.

### Arguments use the same descriptors { #the-unified-argument-idiom }

There is **one** `Field` for both positions. Arguments on a hand-written
`Mutation` (or inside `Field(args={...})`) are declared with the very same
`Field` / scalar shortcuts you use in an `ObjectType` body — the direction comes
from the **declaration site**, never from the descriptor. `Field` accepts
**either** a `DjangoInputObjectType` / `InputType` CLASS (resolved lazily to its
compiled input type) **or** a bare graphql-core scalar, so one descriptor covers
both cases:

```python
from django_graphex.core import CharField, Field, Mutation

class CreateUser(Mutation):
    class Arguments:
        new_user = Field(UserCreateInput, required=True)  # an input-object CLASS
        note     = CharField()                            # a bare String arg

    user = Field(UserType)
    ...
```

`Field(SomeInput, required=True)` replaces the older
`lambda: GraphQLArgument(GraphQLNonNull(SomeInput._meta.graphql_input_type))`
thunk — same lazy timing, one readable line. In an argument position, a scalar
shortcut accepts `required=`, `default=`, `description=`, `name=`, and
`deprecation_reason=`; the output-only `source=` / `resolver=` / `args=` raise a
clear `TypeError` if set there.

!!! note "No more `*InputField` twins (2.0)"
    In v1 the 12 typed shortcuts each had an `*InputField` sibling
    (`CharInputField`, `IntInputField`, …) and a separate `InputField`
    descriptor for arguments. **Those are gone.** The single `Field` and the 11
    surviving scalar shortcuts (`CharField`, `IntField`, `JSONField`, … —
    `GenericJSONField` was folded into `JSONField(as_str=...)`) work in **both**
    positions. Replace every `InputField(X, ...)` with `Field(X, ...)` and every
    `CharInputField()` with `CharField()`.

!!! warning "Don't import field classes from `django.db.models`"
    `django.db.models` also exports `CharField`, `IntegerField`, and friends. If
    you accidentally import a **model** field class and declare it where a GraphQL
    descriptor is expected, django-graphex raises a loud `TypeError` instead of
    silently mis-compiling:

    ```text
    'name': got a django.db.models.Field (<django.db.models.CharField>). Did you
    import CharField from django.db.models instead of django_graphex.core? Use
    django_graphex.core.CharField (or Field) for GraphQL fields.
    ```

    The guard fires on both the type-body path and the mutation-argument path.
    The fix is always the same: import from `django_graphex.core`.

!!! note "`field()` is the low-level substrate"
    The capitalized descriptors are sugar over `field()`, which stays public and
    unchanged. Reach for `field()` directly only when you want the raw
    graphql-core-typed primitive with no Django-style surface:

    ```python
    from graphql import GraphQLString
    from django_graphex.core import field

    server_time = field(GraphQLString, description="ISO timestamp")
    ```

    `field()` takes `description=`, `args=`, `resolver=`, `name=`, and
    `required_perms=` — but **not** `source=` or `required=` (those live on the
    descriptors). Prefer `CharField(...)` / `Field(...)` in new code.

## DjangoInputObjectType

Creates input types for mutations based on Django models.

```python
from django_graphex.types import DjangoInputObjectType
from django.contrib.auth.models import User

class UserInput(DjangoInputObjectType):
    class Meta:
        description = "User input for mutations"
        model = User
        only_fields = ("username", "email", "first_name", "last_name")
        # or exclude specific fields
        # exclude_fields = ("password", "date_joined", "last_login")
```

### Advanced Configuration

A `DjangoInputObjectType` derives its input fields from the model. Shape them
with `only_fields` / `exclude_fields` and a `description`:

```python
from django_graphex.types import DjangoInputObjectType

class UserCreateInput(DjangoInputObjectType):
    """Input for creating new users"""

    class Meta:
        model = User
        only_fields = ("username", "email", "first_name", "last_name", "password")
        description = "Input type for user creation"

class UserUpdateInput(DjangoInputObjectType):
    """Input for updating existing users"""

    class Meta:
        model = User
        only_fields = ("email", "first_name", "last_name")
        description = "Input type for user updates"
```

!!! note "Input bodies are model-derived"
    A `DjangoInputObjectType` compiles its input fields from the model — custom
    descriptors declared on the class body are **not** added to the input type.
    For a bespoke input field that isn't backed by a model column, declare a
    hand-written `Mutation` and pass the extra argument with `Field` / a scalar
    shortcut (e.g. `CharField`) in its `class Arguments` (see
    [the descriptor API](#declaring-fields-the-descriptor-api) and
    [Mutations](mutations.md#custom-arguments-with-field)). Custom
    **output** fields — with `source=` or a `resolve_<name>` method — belong on
    the object types instead: see
    [Custom fields with resolvers](#custom-fields-with-resolvers).

### Usage in Mutations

A `DjangoInputObjectType` is most often wired through a
[`DjangoModelMutation`](mutations.md), which consumes it automatically. For a
hand-written `Mutation`, pass the input-type **class** to `Field` — it
resolves the compiled input type lazily at schema-build time, so you reference
the class directly with no thunk boilerplate:

```python
from django_graphex.core import BooleanField, Field, Mutation

class CreateUserMutation(Mutation):
    class Arguments:
        new_user = Field(UserCreateInput, required=True)

    user = Field(UserType)
    success = BooleanField()

    @classmethod
    def mutate(cls, root, info, **kwargs):
        # The input object arrives as a dict of the declared fields.
        new_user = kwargs["new_user"]
        username = new_user["username"]
        email = new_user["email"]
        # ... mutation logic
        return cls(user=..., success=True)
```

`Field(UserCreateInput, required=True)` compiles to exactly the same
`GraphQLArgument(GraphQLNonNull(...))` the older lambda thunk produced. The thunk
form still works as a low-level substrate — see
[Declaring fields: the descriptor API](#declaring-fields-the-descriptor-api).

!!! tip "Prefer `DjangoModelMutation` for model inputs"
    For ordinary create/update/delete against a model, use
    [`DjangoModelMutation`](mutations.md) — it builds the input type, validates,
    and persists for you. Hand-written `Mutation` classes are for bespoke logic.

## DjangoModelType

!!! tip "Recommended for Quick Setup"
    Automatically generates types, queries, and mutations from a Django model.
    All writable model fields are covered, `choices` become enums, FK fields
    accept a pk, and M2M fields accept a list of pks. Partial updates and DB
    integrity checks (FK existence, uniqueness, `unique_together`) are handled
    automatically.

    Setting `Meta.stream` also auto-generates a subscription via
    `SubscriptionField()`. This requires the `[subscriptions]` extra
    (`pip install "django-graphex[subscriptions]"`). See
    [Subscriptions](subscriptions.md#from-a-djangomodeltype-one-definition).

```python
from django.contrib.auth.models import User
from django_graphex.types import DjangoModelType
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

    The declared queryset is a **template**: it is evaluated once, at class
    definition, and every request runs a fresh clone of it. It never
    accumulates a result cache, so it cannot serve stale rows — regardless of
    the [`OPTIMIZE_QUERYSET`](query-optimization.md) setting.

!!! tip "Optimizer and `Meta.queryset` interplay"

    The query optimizer applies `select_related` / `prefetch_related` / `.only()`
    **on top of** the `Meta.queryset` (or the value returned by `get_queryset`).
    A manual `prefetch_related` for a relation the optimizer also derives is
    *replaced* by the derived version — this is intentional and typically reduces
    queries further; manual prefetches of other relations are kept as they are.
    (The replacement is what keeps the two from colliding: Django rejects two
    lookups on the same path, so the query used to fail outright.) If you rely on
    specific prefetch options (e.g. a custom `Prefetch` queryset), use a
    `per-field optimize_<field>` hook on the parent type instead of embedding them
    in `Meta.queryset`. See [Query Optimization](query-optimization.md).

### Custom queryset & per-request filtering

For anything beyond a static `Meta.queryset`, override two hooks. `info.context`
is the request:

```python
from django.db.models import Count, F
from myapp.models import Author

class AuthorType(DjangoModelType):
    class Meta:
        model = Author

    @classmethod
    def get_queryset(cls, manager, info, **kwargs):
        # custom base queryset for retrieve/list (and mutation responses)
        return Author.objects.select_related("user").annotate(
            email=F("user__email"),
            post_count=Count("posts"),
        )

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        # per-request scoping; default returns `qs` unchanged
        user = info.context.user
        if user.is_superuser:
            return qs
        return qs.filter(user=user)
```

- `get_queryset(cls, manager, info, **kwargs)` supplies the base queryset and
  applies `filter_queryset`; the default uses `Meta.queryset` (else the model
  manager).
- `filter_queryset(cls, qs, info, **kwargs)` is the scoping hook; the default is a
  no-op. It scopes **every** CRUD operation: `update` and `delete` resolve the
  row they are about to write through it too, and a row outside the scope is
  reported as not found instead of being written.

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
from django_graphex.core import CharField, IntField

class AuthorType(DjangoModelType):
    # Typed descriptors, resolved from the instance (here from the annotations
    # added in get_queryset above, and a model property). `source=` reads the
    # named attribute off the instance.
    post_count = IntField(source="post_count")
    email = CharField(source="email")
    avatar_url = CharField(source="avatar_url")   # a model @property

    class Meta:
        model = Author
```

- The field is resolved like any descriptor: `source="x"` reads
  `getattr(instance, "x")`, or add a `resolve_<name>` method for custom logic.
- It appears in the detail **and** the list, because the list reuses the same
  item type.

#### `resolve_<field>` methods

A custom field can also be backed by a **`resolve_<field>` method** declared on
the `DjangoModelType` — not just `source=`. The resolver is forwarded onto the
generated output type, so it runs for both the retrieve and the list. This lets a
custom field return another GraphQL type with arbitrary logic:

```python
from django_graphex.core import Field
from django_graphex.types import DjangoModelType
from myapp.types import CommentType
from myapp.models import Post

class PostType(DjangoModelType):
    # A computed object field, resolved by the method below.
    featured_comment = Field(CommentType)

    class Meta:
        model = Post

    def resolve_featured_comment(self, info):
        # `self` is the Post instance being serialized; return any object
        # CommentType can resolve (here, the first approved comment).
        return self.comments.filter(is_approved=True).first()
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
from django_graphex.core import CharField, IntField

class TimestampedType(DjangoModelType):
    age = CharField(source="age_display")   # shared by subclasses

    class Meta:
        abstract = True

class InvoiceType(TimestampedType):
    total = IntField(source="total_cents")     # adds its own

    class Meta:
        model = Invoice        # gets `age` + `total`
```

!!! warning "Don't mix with a hand-written `DjangoObjectType`"

    These two ways are mutually exclusive per model. If a `DjangoObjectType` is
    already registered for the model, the `DjangoModelType` reuses it and fields
    declared here are **ignored with a warning** — put them on that
    `DjangoObjectType` instead.

    The same applies to the projection, but it **fails the build** rather than
    warning: `only_fields` / `include_fields` / `exclude_fields` declared on a
    `DjangoModelType` whose output type comes from the registry raise
    `ImproperlyConfigured` at class definition, naming the option, the model and
    the registered type. A silent no-op there would leave a column you excluded
    for security reasons queryable.

### Auto-generated Query Fields

A `DjangoModelType` builds its read operations for you: `RetrieveField()`
returns a single-object lookup (by `id`, routed through the type's
`get_queryset` / `filter_queryset` hooks) and `ListField()` returns the
paginated + filtered list with the uniform `results` / `totalCount` shape.
`QueryFields()` is the shorthand that returns both at once. The GraphQL field
names come from the attribute names you assign them to (`user_retrieve` →
`userRetrieve`):

```python
from django_graphex.core import ObjectType

class Query(ObjectType):
    # Generate both retrieve and list queries automatically
    user_retrieve, user_list = UserModelType.QueryFields(
        description='User queries'
    )

    # Or define them separately
    user_detail = UserModelType.RetrieveField(
        description='Get single user by ID'
    )
    user_list_custom = UserModelType.ListField(
        description='List users with filtering and pagination'
    )
```

!!! info "Generated type names"
    A `DjangoModelType` mints its types into a `Generic` name-space that no
    hand-written type claims: the node is `<Model>GenericType`, the mutation
    inputs are `<Model>CreateGenericType` / `<Model>UpdateGenericType`, and the
    list container `ListField()` returns is **`<Model>ListGenericType`**.

    That last name changed: the container used to be called `<Model>ListType`,
    which is exactly the name this guide gives your own
    `DjangoListObjectType`. Declaring both over one model therefore put two
    different types with one name into a single schema and the build failed
    with *"Schema must contain uniquely named types"*. Update any client
    document that spells the container out (an inline fragment, a
    `__typename` assertion); field names and shapes are unchanged.

### Auto-generated Mutation Fields

The write side is generated the same way: `CreateField()`, `DeleteField()` and
`UpdateField()` each return a complete mutation — input type derived from the
model, validation and DB integrity checks included — whose payload carries the
mutated object plus `ok` / `errors`. `MutationFields()` is the shorthand that
returns all three in **create, delete, update** order:

```python
from django_graphex.core import ObjectType

class Mutation(ObjectType):
    # Generate all CRUD mutations
    user_create, user_delete, user_update = UserModelType.MutationFields(
        description='User CRUD operations'
    )

    # Or define them separately
    create_user = UserModelType.CreateField(description='Create new user')
    delete_user = UserModelType.DeleteField(description='Delete user')
    update_user = UserModelType.UpdateField(description='Update user')
```

### Custom mutation arguments — `class Arguments`

The generated mutations accept extra arguments beyond the auto-derived input
object. Declare a `class Arguments` on the `DjangoModelType` — its members are
added to **every** generated mutation (`create` / `update` / `delete`)
alongside `new_<model>`, using the same
[argument descriptors](#declaring-fields-the-descriptor-api) as a hand-written
`Mutation` (a raw `GraphQLArgument` also works):

```python
from django_graphex.core import BooleanField
from django_graphex.types import DjangoModelType

class UserModelType(DjangoModelType):
    class Arguments:
        dry_run = BooleanField(description="Validate only; do not save")

    class Meta:
        model = User
```

```graphql
mutation {
  userCreate(newUser: { username: "ada" }, dryRun: true) { ok }
}
```

The extra argument reaches the resolver as a snake_case kwarg — consume it by
overriding the operation classmethod and delegating to `super()`:

```python
    @classmethod
    def create(cls, root, info, dry_run=False, **kwargs):
        if dry_run:
            return cls(ok=True)
        return super().create(root, info, **kwargs)
```

### Custom validation

For field-level validation beyond the automatic DB checks, see
[Model backend (Pydantic)](backends.md) — the authoritative reference for
inline `validate_<field>()` validators and `Meta.pydantic_model`. All
validation patterns are documented there in one place.

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

## `DjangoUnionType` — typed GenericForeignKey targets

`DjangoUnionType` is the base for a GraphQL `Union` whose members are concrete
`DjangoObjectType`s. Its primary use is to expose a Django
`GenericForeignKey` (GFK) as a **typed** union instead of the flat
`GenericForeignKeyType` scalar — so a client can select concrete fields per
member with inline fragments (`... on AccountType { balance }`).

Members are **explicitly enumerated** via `Meta.types`; the library never
inspects the `django_content_type` table to discover them.

### Required declaration order

The declaration order is **load-bearing** (no lazy string forward-references in
this release):

1. Declare the **member** `DjangoObjectType`s first.
2. Declare the `DjangoUnionType` with `Meta.types = (MemberAType, MemberBType)`.
3. Declare the **owner** `DjangoObjectType` LAST, naming its GFK union via
   `Meta.unions = {"<gfk_field_name>": TheUnion}`.

!!! warning "`gfk_unions` was renamed to `unions` (2.0)"
    The Meta key is now `unions`. Declaring the old `gfk_unions` key raises
    `django.core.exceptions.ImproperlyConfigured` at server startup — rename it.

```python
from django_graphex.types import DjangoObjectType, DjangoUnionType

# 1. Members first.
class AccountType(DjangoObjectType):
    class Meta:
        model = Account

class InvoiceType(DjangoObjectType):
    class Meta:
        model = Invoice

# 2. The union, enumerating members explicitly.
class CommentTargetUnion(DjangoUnionType):
    class Meta:
        types = (AccountType, InvoiceType)

# 3. The GFK owner LAST, mapping the GFK field name -> the union.
class CommentType(DjangoObjectType):
    class Meta:
        model = Comment              # has `target = GenericForeignKey(...)`
        unions = {"target": CommentTargetUnion}
```

Querying it:

```graphql
{
  comments {
    target {
      __typename
      ... on AccountType { balance }
      ... on InvoiceType { amount }
    }
  }
}
```

If the union is declared **after** the owner (mis-ordered), the converter emits
a `WARNING` and falls back to the flat `GenericForeignKeyType` — the schema
still builds, but the field is not a union.

### `resolve_type` is mandatory (and provided)

`DjangoUnionType.resolve_type(instance, info)` maps a plain Django row to its
registered `DjangoObjectType` via `registry.get_type_for_model(type(instance))`.
It **raises** a descriptive `TypeError` if a row's model has no registered type
(rather than returning `None`, which would surface GraphQL's opaque
"Abstract type must resolve to an Object type"). You do not override it.

### Per-content-type column narrowing (Django 5.0+)

!!! tip "Optimizer hub"
    For how this fits the rest of the N+1 optimizer (with the inline-fragment
    query), see
    [Query Optimization → Typed GenericForeignKey unions](query-optimization.md#typed-genericforeignkey-unions-per-content-type-narrowing).

When `OPTIMIZE_ONLY_FIELDS` is on **and** Django is **5.0 or newer**, the
optimizer routes the union GFK through a
[`GenericPrefetch`](https://docs.djangoproject.com/en/stable/ref/contrib/contenttypes/#django.contrib.contenttypes.prefetch.GenericPrefetch),
building **one narrowed queryset per content type** — each `.only()`-restricted
to exactly the columns that member's inline fragment selected (e.g. the
`Account` queryset fetches `balance`, the `Invoice` queryset fetches `amount`).
This batches all parents into one query per content type (no N+1).

- **Django < 5.0**: the optimizer **degrades** gracefully to a single bare,
  full-load `Prefetch` — it never imports `GenericPrefetch`, never narrows
  columns, and is never slower than the pre-union behaviour.
- **Per-content-type uniqueness**: each distinct content type gets exactly one
  queryset. Two members backed by the **same** concrete table (e.g. proxy
  models) are collapsed into one queryset whose `.only()` columns are the union
  of both members' selections. Divergent per-row narrowing on a single shared
  table is out of scope; that bucket safely degrades to full-load.

## `DjangoInterfaceType` — shared fields across types

`DjangoInterfaceType` is the base for a GraphQL `Interface` that declares fields
shared by several `DjangoObjectType` implementors (typically backed by a shared
abstract Django base model). It is **schema-level field sharing only** — it
introduces no new queryset/fetch path; each implementor's own model drives its
column narrowing.

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

Implementors declare membership with the `Meta.interfaces`
kwarg. Like `DjangoUnionType`, `DjangoInterfaceType` provides a mandatory
`resolve_type` that maps each row to its concrete implementor.

## Limiting query shape: `max_depth` & `complexity`

Every type above accepts two optional `Meta` options that protect your API from
abusive queries. They are enforced **before execution** by the validation rules
the library's `GraphQLView` enables by default. See
[Query depth & cost limits](query-limits.md) for the full reference; the
mini-examples below are the gist.

**`max_depth`** — caps how many nested object levels may be selected below a field
returning this type (scalars don't count):

```python
class CategoryType(DjangoModelType):
    class Meta:
        model = Category
        max_depth = 2          # category -> posts -> comments OK; one level deeper is rejected
```

```graphql
category {
  posts {                # level 1 ✅
    comments {           # level 2 ✅
      author { username }  # level 3 ❌ "Query exceeds the maximum nesting depth of 2 ..."
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

## Field type conversion reference

How Django model fields map to GraphQL **output** types:

| Django field | GraphQL output |
|---|---|
| `CharField` / `TextField` / `SlugField` / … | `String` |
| `IntegerField` / `AutoField` / `BigIntegerField` | `Int` |
| `FloatField` / `DecimalField` | `Float` |
| `BooleanField` | `Boolean` |
| `DateField` / `DateTimeField` / `TimeField` | `CustomDate` / `CustomDateTime` / `CustomTime` (see [input formats](#accepted-datetime-input-formats)) |
| any field with `choices` | a generated `Enum` (see above) |
| `ForeignKey` / `OneToOneField` | the related object type |
| reverse FK / `ManyToManyField` | a `<Model>ListType` container (`results` + `totalCount`) |
| `ArrayField(inner)` | `[<inner>]` — nested arrays as `[[<inner>]]`; a `choices` base as `[<Enum>]` |
| `*RangeField` (Integer/BigInteger/Decimal/Date/DateTime) | a `{ lower, upper }` composite typed by the bound scalar |
| `JSONField` | the `JSON` scalar — **raw** structured JSON on the wire (see [below](#jsonfield-json)) |
| `GenericForeignKey` | a typed union when declared in `Meta.unions`, otherwise a flat `GenericForeignKeyType` |
| `FileField` / `ImageField` | `String` — the storage name on output; on input, a storage path **or** the file a multipart part carries (see [Mutations › Automatic multipart uploads](mutations.md#automatic-multipart-uploads)) |
| `HStoreField`, GIS geometry | a permissive scalar (no native modeling — see [Backends](backends.md)) |

Worked example — `ArrayField` (incl. a `choices` base) and a range field:

```python
from django.contrib.postgres.fields import ArrayField, IntegerRangeField
from django.db import models

class Article(models.Model):
    tags = ArrayField(models.CharField(max_length=50))          # -> tags: [String]
    grid = ArrayField(ArrayField(models.IntegerField()))        # -> grid: [[Int]]
    statuses = ArrayField(                                      # -> statuses: [ArticleStatusesEnum]
        models.CharField(max_length=10, choices=(("draft", "Draft"), ("pub", "Published"))),
    )
    span = IntegerRangeField()                                  # -> span: { lower: Int, upper: Int }
```

```graphql
{ articles { tags grid statuses span { lower upper } } }
```

### Accepted date/time input formats { #accepted-datetime-input-formats }

`DateField` / `DateTimeField` / `TimeField` (both the model-derived output
fields and the `DateField()` / `DateTimeField()` / `TimeField()` shortcuts)
parse input with Python's `datetime.fromisoformat`, and serialize output with
`.isoformat()`. What that means in practice:

| Input on the wire | Result |
|---|---|
| `"2024-01-15T10:30:00Z"` | Accepted — the trailing `Z` is honored (UTC). |
| `"2024-01-15T10:30:00+05:00"` | Accepted — the **offset is preserved** (no conversion). |
| `"2024-01-15T10:30:00"` | Accepted — **naive passthrough**; the library does not call `make_aware`. |
| `"2024-01-15 10:30:00"` | Accepted — a **space** separator works in place of `T`. |
| `"2024-01-15"` (into a `DateTime`) | Accepted — a bare date becomes **midnight** (`00:00:00`). |
| `1700000000` (a numeric timestamp) | **Rejected** — the scalar only parses ISO-8601 *strings*, never numbers. |

Output is always `.isoformat()`, so an aware datetime renders with an explicit
offset (`2024-01-15T10:30:00+00:00`) — **never** the shorthand `Z`.

!!! note "Why `CustomDate` / `CustomDateTime` / `CustomTime`?"
    The output/argument scalars use these `Custom*` names for **SDL parity with
    v1** (graphene-django), so a v2 schema is a drop-in match. The plain `Date` /
    `DateTime` / `Time` names are **not** free — they belong to the
    filter-lookup scalars (the `exact` / `gte` / … values inside a
    `<Model><Field>Lookups` input). Keeping the two families distinct is what
    lets both render in one schema without a name clash.

!!! warning "`USE_TZ` interactions on the write path"
    Because parsing is a plain `fromisoformat` (no `make_aware`), what you send
    interacts with Django's timezone handling on save:

    - **`USE_TZ = True`, naive input** (`"2024-01-15T10:30:00"`): Django emits its
      own `RuntimeWarning` ("received a naive datetime … while time zone support
      is active") and interprets the value in your `TIME_ZONE`. A naive
      `10:30:00` under `TIME_ZONE = "America/New_York"` is stored (and re-read) as
      the aware `2024-01-15T15:30:00+00:00` — so the value the client reads back
      differs from the naive string it sent. Send an **offset-qualified** string
      (or `Z`) to avoid the ambiguity.
    - **`USE_TZ = False`, aware input** (`"…+05:00"`) on **SQLite**: Django raises
      a top-level error — *"SQLite backend does not support timezone-aware
      datetimes when USE_TZ is False."* — surfaced as a `GraphQLError`. Send a
      naive string when `USE_TZ` is off.

### `JSONField` → `JSON` { #jsonfield-json }

A model `JSONField` is exposed as the **`JSON`** scalar in every direction. `JSON`
carries **raw** structured JSON on the wire: objects, lists, and scalars pass
through as-is, with no string-encoding step and no client-side `JSON.parse`.

| Direction | GraphQL type | Behavior |
|---|---|---|
| Query output | `JSON` | The stored value is sent structurally — a client selecting `specs` gets a real object `{ "ram": 16 }`, not a string. |
| Mutation input | `JSON` | A real `dict` / `list` (or scalar) reaches the model field. Inline object/list **literals** in the query document are accepted, and so are **variables**. |
| Filters | `JSON` | `filter_fields = {"specs": ("exact",)}` compiles the lookup input with a `JSON` value. |

```python
from django.db import models

class Product(models.Model):
    name = models.CharField(max_length=100)
    specs = models.JSONField(null=True, blank=True)
```

```graphql
# Inline object literal — accepted (no variables required):
mutation {
  productCreate(newProduct: { name: "Laptop", specs: { ram: 16, tags: ["a", "b"] } }) {
    product {
      specs      # -> { "ram": 16, "tags": ["a", "b"] }  (a real object; no parsing)
    }
    ok
  }
}
```

```graphql
# Variables work too:
mutation CreateProduct($specs: JSON) {
  productCreate(newProduct: { name: "Laptop", specs: $specs }) {
    product { specs }
    ok
  }
}
# variables: { "specs": { "ram": 16 } }
```

Omitting `specs` leaves the column untouched; passing `specs: null` writes SQL
`NULL` — the usual omit-vs-null semantics, unchanged.

!!! tip "Custom JSON fields: the `JSONField()` descriptor and `as_str=`"

    For a hand-declared (non-model) field, the
    [`JSONField()` shortcut](#output-scalar-shortcuts) covers **both** JSON
    styles through one `as_str` flag. `JSONField()` (the default) binds the raw
    `JSON` scalar — structured objects/lists on the wire, exactly like a model
    `JSONField`. `JSONField(as_str=True)` is the **escape hatch**: it binds the
    string-encoded `JSONString` scalar, whose wire value is a JSON-**encoded
    string** the server decodes with `json.loads` on input and encodes with
    `json.dumps` on output.

    ```python
    from django_graphex.core import JSONField, ObjectType

    class Query(ObjectType):
        config     = JSONField()              # -> JSON:       { "theme": "dark" }
        raw_config = JSONField(as_str=True)   # -> JSONString: "{\"theme\": \"dark\"}"

        def resolve_config(self, info):
            return {"theme": "dark"}   # sent as a JSON object

        def resolve_raw_config(self, info):
            return {"theme": "dark"}   # serialized to a JSON string
    ```

    A `JSONString` value is always **valid JSON on the wire**: a resolver
    returning text that already parses as JSON (`'{"theme": "dark"}'`) is sent
    verbatim, while any other Python value — including a plain string such as
    `"dark"` — is `json.dumps`-encoded (`"\"dark\""`), so every value the field
    emits round-trips back through the same scalar on input.

    **Which one do I use?** Reach for the default `JSONField()` (raw `JSON`)
    unless a client specifically expects a JSON **string** — e.g. it stores the
    value verbatim, or you need wire parity with a legacy graphene-django schema
    that used `JSONString`. In that case use `JSONField(as_str=True)`.

    The scalar singletons themselves are importable for use with `Field` /
    `field()` / `GraphQLArgument`:

    ```python
    from django_graphex.core import GdxJSON, GdxJSONString
    ```

!!! note "Inline literals are accepted"

    The raw `JSON` scalar parses an **object or list literal written inline** in
    the query document (`echo(data: { a: [1, 2] })` reaches the resolver as a
    real `dict`) — the literal parser recurses through nested objects, lists, and
    variable references. You do **not** need to route structured values through
    variables (though variables work identically):

    ```graphql
    query Echo($d: JSON) { echo(data: $d) }
    # variables: { "d": { "a": [1, 2] } }
    ```

    A variable used **inside** an object literal that the request leaves unset
    simply **drops its key** — `echo(data: { a: $unset, b: 1 })` reaches the
    resolver as `{"b": 1}` (the same rule graphql-core applies to input-object
    fields), not as an error.

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
        only_fields = ("username", "email")

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

        # Limit exposed fields (use only_fields / exclude_fields, not fields / exclude)
        only_fields = ("id", "username", "email", "first_name", "last_name")

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
    total_posts = IntField()          # a custom, computed output field

    class Meta:
        model = User

    def resolve_total_posts(self, info):
        return self.posts.count()

# Use DjangoInputObjectType for model-derived input; shape it with only_fields.
# For a bespoke, non-model input argument, use a hand-written Mutation with a
# Field / CharField argument instead (input bodies are model-derived).
class UserRegistrationInput(DjangoInputObjectType):
    class Meta:
        model = User
        only_fields = ("username", "email", "password")
```

These examples assume the descriptor imports at the top of the module:

```python
from django_graphex.core import IntField
```
