# Fields

django-graphex provides several field types for building GraphQL schemas with
enhanced functionality. Start with the typed scalar descriptors for simple
custom fields and arguments, then move to the Django mounting field classes
below for Django-model-backed queries.

## Typed scalar descriptors

For a plain scalar field or argument, the capitalized shortcuts are the
quickest idiom — one shortcut per scalar, usable in **both** an output
position (an `ObjectType` body) and an input position (a `Mutation`'s
`class Arguments` body, or a `Field(args=...)` mapping).

In an `ObjectType`, arguments belong on the field descriptor itself, via
`Field(args=...)`:

```python
from django_graphex.core import ObjectType, Field, CharField, IntField
from graphql import GraphQLString

class Query(ObjectType):
    greeting = Field(
        GraphQLString,
        description="a greeting",
        args={"name": CharField(default="world"), "loud": IntField(default=0)},
    )

    def resolve_greeting(self, info, **kwargs):
        return f"hello {kwargs['name']}" + ("!" if kwargs["loud"] else "")
```

```graphql
{ greeting(name: "ada", loud: 1) }   # -> "hello ada!"
```

In a `Mutation`, the same shortcuts go in a `class Arguments` body:

```python
from django_graphex.core import BooleanField, CharField, IntField, Mutation

class Shout(Mutation):
    class Arguments:
        name = CharField(default="world")
        loud = IntField(default=0)

    ok = BooleanField()
    message = CharField()

    @classmethod
    def mutate(cls, root, info, **kwargs):
        text = f"hello {kwargs['name']}" + ("!" if kwargs["loud"] else "")
        return cls(ok=True, message=text)
```

!!! warning "`class Arguments` only works inside a `Mutation`"
    A `class Arguments` block nested in a plain `ObjectType` is **silently
    ignored** — the field compiles with no arguments at all, and the resolver
    then fails with `KeyError` on the argument it expected. Use
    `Field(args=...)` for query arguments.

| Shortcut | GraphQL type |
|----------|--------------|
| `CharField` | `String` |
| `IntField` | `Int` |
| `FloatField` | `Float` |
| `BooleanField` | `Boolean` |
| `IDField` | `ID` |
| `DateField` | `CustomDate` |
| `DateTimeField` | `CustomDateTime` |
| `TimeField` | `CustomTime` |
| `DecimalField` | `Decimal` |
| `UUIDField` | `UUID` |
| `JSONField` | `JSON` (or `JSONString` with `as_str=True`) |

Each shortcut accepts `source=`, `required=`, `default=`, `description=`,
`name=`, `resolver=` and `deprecation_reason=` — the same kwargs the unified
`Field` below accepts, minus `args=` (only `Field` itself takes `args=`).
`default=` only makes sense in an argument position; setting it on an output
field raises a `TypeError` at schema-build time.

See the [full descriptor API reference](../api/fields.md#field-descriptors)
for every signature, including `JSONField(as_str=True)`.

## The unified `Field`

`Field` is the one descriptor behind every shortcut above. Reach for it
directly when you need a type the shortcuts don't cover (a `DjangoObjectType`
reference, an enum, a `GraphQLList` / `GraphQLNonNull` wrapper) or when you
need `args=`, `resolver=`, or `source=`:

```python
from django_graphex.core import ObjectType, Field, CharField, IntField
from graphql import GraphQLString

class Query(ObjectType):
    # source=: resolves by reading `user_email` off the root
    email = Field(GraphQLString, source="user_email")

    # args=: an explicit {name: arg} mapping, each value itself a descriptor
    greet = Field(
        GraphQLString,
        description="Greet someone by name",
        args={"name": CharField(required=True), "count": IntField(default=1)},
    )

    def resolve_greet(self, info, **kwargs):
        return kwargs["name"] * kwargs["count"]
```

```graphql
{ greet(name: "hi", count: 2) }
```

`Field` works in both positions, and the parameters that make sense differ by
position:

| Parameter | Position | Meaning |
|-----------|----------|---------|
| `type` | both | The field's type — a graphql-core type, a `DjangoObjectType` reference (output), or an `InputType` reference (input). |
| `required` | both | Wraps the type in non-null (`T!`). |
| `description` | both | Field / argument description. |
| `name` | both | Explicit wire name (skips camelCase on output — in *every* output position, root or nested; drives `out_name` on input). |
| `deprecation_reason` | both | Marks the field / argument `@deprecated(reason: ...)`. |
| `source` | output only | Resolve by reading an attribute off the root. |
| `resolver` | output only | Field-level resolver (wins over the parent resolver). |
| `args` | output only | Explicit `{name: arg}` mapping for the field's arguments. |
| `default` | input only | The GraphQL default value; omit to leave the argument with no default. |

Setting an output-only parameter (`resolver=`, `source=`, `args=`) on a
`Field` used inside a `class Arguments` body raises a `TypeError` naming the
offending kwarg. Setting `default=` on a `Field` used in an `ObjectType` body
raises a `TypeError` at output compile time. There is no separate
`InputField` — the same `Field` (and the same typed shortcuts) work on both
sides.

`name=` is the escape hatch for an attribute name that collides with a Python
keyword. It is honoured wherever the field is declared — on a root, on a
mutation payload, and on any nested `ObjectType`:

```python
class Booking(ObjectType):
    date_ = field(GdxDate, name="date")   # renders `date`, not `date_`
```

## Django mounting fields

The field classes below wire a `DjangoObjectType` / `DjangoListObjectType`
into a `Query`, from simplest to most capable: `DjangoObjectField` for a
single object, then list fields with progressively more built-in filtering
and pagination.

## DjangoObjectField

Used for single object queries with automatic ID filtering.

```python
from django_graphex.fields import DjangoObjectField
from django_graphex.core import ObjectType
from .types import UserType

class Query(ObjectType):
    user = DjangoObjectField(UserType, description='Single User query')
```

**Features:**
- Automatic ID-based filtering
- No need to define custom resolve function
- Built-in error handling for non-existent objects

**Usage in GraphQL:**
```graphql
{
  user(id: 1) {
    id
    username
    firstName
  }
}
```

Every mounting field class below accepts `deprecation_reason=`, which renders
as `@deprecated(reason: ...)` on the compiled field:

```python
class Query(ObjectType):
    user = DjangoObjectField(
        UserType,
        deprecation_reason="Use `activeUser` instead.",
    )
```

```graphql
type Query {
  user(id: ID!): UserType @deprecated(reason: "Use `activeUser` instead.")
}
```

## DjangoFilterListField

Provides filtering capabilities for list queries without pagination.

```python
from django_graphex.fields import DjangoFilterListField
from django_graphex.core import ObjectType
from .types import UserType

class Query(ObjectType):
    users = DjangoFilterListField(UserType)
```

**Features:**
- Built on Django's ORM lookups + `Q` objects (no django-filter)
- Multiple filter types (exact, contains, etc.)
- No pagination (returns all matching results)

**Usage in GraphQL:**
```graphql
{
  users(filter: { firstName: { icontains: "john" } }) {
    id
    username
    firstName
    lastName
  }
}
```

## DjangoFilterPaginateListField

Combines filtering and pagination for list queries.

```python
from django_graphex.fields import DjangoFilterPaginateListField
from django_graphex.core import ObjectType
from django_graphex.paginations import LimitOffsetGraphqlPagination
from .types import UserType

class Query(ObjectType):
    users = DjangoFilterPaginateListField(
        UserType,
        pagination=LimitOffsetGraphqlPagination(default_limit=20)
    )
```

**Features:**
- All filtering capabilities of DjangoFilterListField
- Built-in pagination support
- Configurable pagination class

**Usage in GraphQL:**
```graphql
{
  users(filter: { firstName: { icontains: "john" } }, limit: 10, offset: 0) {
    id
    username
    firstName
  }
}
```

!!! note "Flat list"
    `DjangoFilterPaginateListField` returns a flat list, so both the filter
    arguments and the pagination/ordering arguments (`limit`, `offset`,
    `ordering`) live directly on the list field. There is no `results` /
    `totalCount` wrapper — for that, use `DjangoListObjectField`.

!!! warning "Mounted on a type: one relation must scope the list"
    Mounted on a `DjangoObjectType` (rather than on `Query`), the field scopes
    its rows to the parent row through the relation that points back at the
    parent. That works only while **exactly one** relation does: a child with
    `created_by` *and* `updated_by` foreign keys to the same parent — or a
    foreign key alongside a many-to-many — is ambiguous, and the library now
    refuses it with `ImproperlyConfigured` naming both relations rather than
    guessing. It used to apply *all* of them at once, which is a conjunction:
    the list silently resolved to `[]` for every parent that was not on both
    sides of every row.

    For an ambiguous child, mount the nested list through its **relation
    accessor** instead — the auto-generated nested list field, or an explicit
    `DjangoNestedListObjectField(ArticleListType, accessor="created_articles")`.
    Reading the accessor names the relation outright, so nothing has to be
    inferred.

## DjangoListObjectField

!!! tip "Recommended for Queries"
    This is the most flexible approach for list queries with built-in support for filtering and pagination.

```python
from django_graphex.fields import DjangoListObjectField
from django_graphex.core import ObjectType
from .types import UserListType

class Query(ObjectType):
    users = DjangoListObjectField(UserListType, description='All Users query')
```

**Features:**
- Works with DjangoListObjectType
- Inherits pagination configuration from the type
- Filtering via the type's `filter_fields` (built on Django ORM lookups + `Q`)
- Built-in caching support

**Usage in GraphQL:**

Filter arguments live on the list field; pagination and ordering arguments
(`limit`, `offset`, `ordering`) live on the `results` subfield. `totalCount` is
a sibling of `results`.

```graphql
{
  users(filter: { isActive: { exact: true } }) {
    results(limit: 10, offset: 0, ordering: "-id") {
      id
      username
      firstName
    }
    totalCount
  }
}
```

### Custom filtering logic

There are no `FilterSet` classes. Declarative lookups come from the type's
`Meta.filter_fields` and are queried through the nested `filter:` argument. For
bespoke rules (e.g. a free-text search across several columns), override
`get_queryset` / `filter_queryset` on a `DjangoModelType`:

```python
from django.db.models import Q
from django_graphex.types import DjangoModelType
from django.contrib.auth.models import User

class UserType(DjangoModelType):
    class Meta:
        model = User
        filter_fields = {"username": ("icontains",), "email": ("icontains",)}

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        term = info.context.GET.get("q") if hasattr(info.context, "GET") else None
        if term:
            qs = qs.filter(
                Q(first_name__icontains=term) | Q(last_name__icontains=term)
            )
        return qs
```

See [Permissions & hooks](permissions.md) and the [Filtering guide](filtering.md).

## AnnotatedField

A field backed by a Django ORM annotation that is injected into the
queryset **only when the field is selected** in the GraphQL query. A built-in
default resolver reads the annotated value off the row, so no `resolve_<field>`
is needed — and when the field is not selected, no annotation (and no extra SQL)
is added at all.

`AnnotatedField` is public — import it directly:

```python
from django_graphex.fields import AnnotatedField
```

**Signature:**

```python
AnnotatedField(type_, expression, aliases=None, annotation_name=None, **kwargs)
```

**Example** — a per-author post count, computed in the database:

```python
from graphql import GraphQLInt
from django.db.models import Count
from django_graphex.fields import AnnotatedField
from django_graphex.types import DjangoObjectType

class AuthorType(DjangoObjectType):
    # Backed by a DB annotation, injected ONLY when `postCount` is selected.
    post_count = AnnotatedField(GraphQLInt, Count("posts"))

    class Meta:
        model = Author
```

**Usage in GraphQL:**

```graphql
{
  authors {
    results {
      id
      name
      postCount
    }
  }
}
```

When `postCount` is selected, the optimizer adds the `Count("posts")`
annotation to the queryset. When it is **not** selected, the annotation is never
injected and the query is unchanged.

**Arguments:**

| Argument | Meaning |
|----------|---------|
| `type_` | The graphql-core output type (e.g. `GraphQLInt`). |
| `expression` | A Django `Expression` instance **or** a zero-arg callable returning one. The callable is invoked lazily at injection time, per request — useful for constructing a fresh expression on each resolve. |
| `aliases` | Optional `dict[str, Expression \| callable]` applied via `.alias()` **before** `.annotate()` (for intermediate expressions the annotation depends on). |
| `annotation_name` | Overrides the auto-derived annotation key. Defaults to `_gqx_ann_<snake_field>`. Set it when the auto key would collide with a model attname. |

```python
# expression may also be a zero-arg callable for fresh construction per request:
post_count = AnnotatedField(GraphQLInt, lambda: Count("posts"))
```

!!! note "Selection-driven and gated by a setting"
    Injection runs as `qs.alias(**aliases).annotate(**{annotation_name: expression})`
    and only fires when the field appears in the client selection set **and**
    `OPTIMIZE_ANNOTATED_FIELDS` is `True` (the default). Set it to `False` to
    disable `AnnotatedField` injection entirely. The default resolver returns
    `None` when the annotation was not injected (field not selected).

!!! tip "Annotations across a forward FK"
    Child `AnnotatedField`s on a nested type are injected on that child's
    `Prefetch` queryset. A forward-FK relation whose child selects an
    `AnnotatedField` is auto-promoted from `select_related` to
    `prefetch_related`, because DB annotations cannot be pushed through a SQL
    `JOIN`. See
    [Query Optimization → Selection-driven annotations](query-optimization.md#selection-driven-annotations-annotatedfield)
    for a worked example.

## Custom resolvers

`DjangoObjectField`, `DjangoFilterListField`, `DjangoFilterPaginateListField` and
`DjangoListObjectField` accept a custom `resolver=`. When given, it is used
instead of the built-in resolver — but it still receives the library's plumbing as
its **leading positional arguments**, so you can reuse filtering/pagination and
only change the base queryset:

- single object: `resolver(manager, root, info, **kwargs)`
- lists: `resolver(manager, filter_backend, root, info, **kwargs)`

```python
def active_users(manager, root, info, **kwargs):
    # custom base queryset; manager is the model's default manager
    return manager.filter(is_active=True).get(pk=kwargs["id"])

field = DjangoObjectField(UserType, resolver=active_users)
```

This is also what powers `DjangoModelType.RetrieveField()` / `ListField()`
(which inject `cls.retrieve` / `cls.list`), so a `DjangoModelType.Meta.queryset`
is honored by its list/retrieve.

## Field Comparison

| Feature | DjangoObjectField | DjangoFilterListField | DjangoFilterPaginateListField | DjangoListObjectField |
|---------|------------------|----------------------|------------------------------|----------------------|
| Single Objects | ✅ | ❌ | ❌ | ❌ |
| List Objects | ❌ | ✅ | ✅ | ✅ |
| Filtering | ID only | ✅ | ✅ | ✅ |
| Pagination | ❌ | ❌ | ✅ | ✅ |
| Custom queryset hooks | ❌ | ✅ | ✅ | ✅ |
| Type Integration | Basic | Basic | Basic | Full |
| Caching | ❌ | ❌ | ❌ | ✅ |

## DjangoNestedListObjectField

`DjangoNestedListObjectField` is the field class used automatically when the
optimizer wires a reverse-FK or M2M relation. You can also declare it
explicitly on a parent `DjangoObjectType` to expose a nested list with custom
accessor, filter, or pagination behavior.

`DjangoNestedListObjectField` is part of the public API — import it directly:

```python
from django_graphex.fields import DjangoNestedListObjectField
```

**Signature:**

```python
DjangoNestedListObjectField(list_type, accessor=None, fields=None, **kwargs)
```

| Argument | Meaning |
|----------|---------|
| `list_type` | A `DjangoListObjectType` subclass describing the nested list's shape, pagination, and filter options. |
| `accessor` | The parent attribute name for the relation (defaults to the field name on the parent type). |
| `fields` | Override filter configuration. Defaults to `list_type._meta.filter_fields`. Pass `None` to inherit from the type; pass `{}` or an empty dict to disable filtering on this field. |
| `**kwargs` | Forwarded to the underlying `Field`. |

**Example** — expose a per-author paginated list of posts:

```python
from django_graphex.fields import DjangoNestedListObjectField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.types import DjangoObjectType, DjangoListObjectType
from .models import Author, Post

class PostType(DjangoObjectType):
    class Meta:
        model = Post
        filter_fields = {"title": ["icontains"]}

class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        pagination = LimitOffsetGraphqlPagination(default_limit=10, ordering="-id")
        filter_fields = {"title": ["icontains"]}

class AuthorType(DjangoObjectType):
    posts = DjangoNestedListObjectField(PostListType)

    class Meta:
        model = Author
```

**Usage in GraphQL:**

```graphql
{
  author(id: 1) {
    name
    posts(filter: { title: { icontains: "graphql" } }) {
      results(limit: 5, ordering: "-id") {
        id
        title
      }
      totalCount
    }
  }
}
```

The optimizer automatically uses `prefetch_related` (with DB-side window slicing
when `OPTIMIZE_NESTED_PAGINATION` is `True`). No additional `select_related` or
`prefetch_related` calls are needed — declaring the field is enough.

See [Query Optimization → DB-side nested pagination](query-optimization.md#db-side-nested-pagination-window-slicing) and [Nested Lists](nested-lists.md) for the full reference.

## Best Practices

### 1. Use DjangoListObjectField for Lists

`DjangoListObjectField` pairs with `DjangoListObjectType` to give you
pagination, filtering, and `totalCount` out of the box — without writing a
resolver. `DjangoFilterPaginateListField` returns a flat list with no wrapper
shape, which limits client-side pagination controls.

```python
from django_graphex.core import ObjectType

# ✅ Recommended
class Query(ObjectType):
    users = DjangoListObjectField(UserListType, description='All users')

# ❌ Less flexible — no totalCount, no results wrapper
class Query(ObjectType):
    users = DjangoFilterPaginateListField(UserType)
```

### 2. Define Filter Fields in Types

Declaring `filter_fields` on the type (rather than the field) makes the filter
available everywhere the type is used — list fields, nested lists, and
`RetrieveField` — without repeating the configuration.

```python
class UserType(DjangoObjectType):
    class Meta:
        model = User
        filter_fields = {
            "username": ("exact", "icontains"),
            "email": ("exact", "icontains"),
            "is_active": ("exact",),
        }
```

### 3. Use Descriptive Names

Descriptive names make the schema self-documenting and reduce the need for
separate API docs. Include intent in the name (`active_users` > `users`) and
always add a `description=`.

```python
from django_graphex.core import ObjectType

class Query(ObjectType):
    # ✅ Clear and descriptive
    active_users = DjangoListObjectField(
        UserListType,
        description='List of active users with pagination'
    )

    user_by_id = DjangoObjectField(
        UserType,
        description='Get a single user by ID'
    )
```

### 4. Combine with Permissions

Keep permissions out of the schema layer — put them in a `resolver=` or
`filter_queryset` hook so the rule is enforced regardless of which field
triggers the query. This also keeps the field declaration clean and
independently testable.

Pass a custom `resolver=` that reuses the library's plumbing (it receives
`manager, filter_backend, root, info, **kwargs` for list fields) and only changes
the base queryset; `filter_backend.apply(qs, kwargs.get("filter"))` applies the
nested `filter:` argument:

```python
from django_graphex.fields import DjangoListObjectField
from django_graphex.core import ObjectType
from django_graphex.base_types import DjangoListObjectBase
from graphql import GraphQLError

def staff_only_users(manager, filter_backend, root, info, **kwargs):
    if not info.context.user.is_staff:
        raise GraphQLError("Staff access required")
    qs = manager.get_queryset()
    qs = filter_backend.apply(qs, kwargs.get("filter"))
    return DjangoListObjectBase(count=qs.count(), results=qs)

class Query(ObjectType):
    users = DjangoListObjectField(UserListType, resolver=staff_only_users)
```
