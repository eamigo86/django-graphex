# Filtering

Filtering lets clients request subsets of a list based on field values, related
objects and **logical composition** (`and` / `or` / `not`). It is built on
Django's own ORM lookups and `Q` objects — **no `django-filter` dependency**.

## Overview

- **Opt-in per type** via `Meta.filter_fields`.
- A single nested **`filter:`** argument of a generated `<Model>FilterInput` type.
- **Per-field lookups** (`exact`, `icontains`, `in`, `range`, `isnull`, …).
- **Relation descent** (`author: { name: { … } }`), to-many auto-`distinct()`.
- **Logical operators**: `and`, `or`, `not` (arbitrarily nested).
- `choices` fields filter through their generated **Enum**.
- **Bounded by the type's projection** — a column whose value the serving type
  does not publish cannot be filtered, and naming it fails the build. See
  [Types › The projection is a security boundary](types.md#projection-security-boundary)
  for the rule and [the outer boundary](#projection-boundary) for this axis.

!!! warning "Different from the previous library"

    The old flat arguments (`username: "x"`, `username_Icontains: "x"`),
    `Meta.filterset_class` and `GraphqlIDFilter` are **gone**. Filtering now
    goes through the single nested `filter:` argument. See the
    [migration guide](../migration.md).

## Declaring filterable fields

`Meta.filter_fields` accepts the same two forms as before:

=== "List form (default lookups)"

    ```python
    from django_graphex.types import DjangoListObjectType

    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            # each field gets the type-derived default lookup set
            filter_fields = ["username", "email", "is_active"]
    ```

=== "Dict form (explicit lookups)"

    ```python
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            filter_fields = {
                "username": ("exact", "icontains"),
                "email": ("exact", "icontains"),
                "is_active": ("exact",),
                "date_joined": ("exact", "gt", "gte", "lt", "lte", "range"),
            }
    ```

!!! warning "Dict form: `None` values are rejected"

    `filter_fields = {"field": None}` was previously accepted as a way to
    apply the default lookup set from the dict form. This was silently
    un-Pythonic and has been **removed**: it now raises `ImproperlyConfigured`
    with a message pointing to `@filter_field`.

    Use the **list form** if you want defaults for some fields and explicit
    lookups for others:

    ```python
    # This now raises ImproperlyConfigured:
    # filter_fields = {"username": None, "email": ("exact",)}

    # After — mix list and dict forms via two declarations, or:
    filter_fields = ["username", "email"]   # all get default lookups
    # For explicit overrides on some fields, use the dict form with tuples only.
    ```

    For **custom per-field logic** (previously the only reason to use `None`),
    use the new `@filter_field` decorator instead — see the section below.

### The projection is the outer boundary { #projection-boundary }

!!! danger "A hidden column cannot be filtered — breaking change"

    `Meta.only_fields` / `Meta.exclude_fields` are a **security boundary**, not
    an output shape — [the rule is stated in full on the Types
    page](types.md#projection-security-boundary). This section is how the filter
    axis enforces it, and filtering is the sharpest of the three axes: an
    `exact` lookup answers in **one** request and `icontains` walks the value
    prefix by prefix.

    A `filter_fields` entry naming a column **the compiled type serving that
    model does not publish the value of** is a **contradiction between two
    `Meta` options**, and it raises `ImproperlyConfigured` while the schema
    builds:

    ```text
    AuthorType.Meta.filter_fields entry 'bio' names 'bio', which AuthorType
    does not publish -- Meta.only_fields / Meta.exclude_fields removed it, or a
    declared attribute publishes the name over a different value. A projection
    is a security boundary, not an output shape: a column a type hides must not
    be readable, orderable or filterable through it, and one filter request
    returns the hidden value exactly. Publish 'bio' on AuthorType, or drop the
    entry.
    ```

    **A schema that builds today can fail to build after upgrading — which is
    the point.** Until this release the entry was accepted and it *worked*:
    `filter: { bio: { exact: "…" } }` answered exactly for a column the SDL said
    did not exist, and the whole lookup set was advertised as
    `<Model>FilterInput.bio`, so the oracle was discoverable by introspection
    rather than guessed. Every schema that stops building was answering it.

    **The fix is one line, and it is a decision you have to make**: publish the
    column (add it to `only_fields`, drop it from `exclude_fields`, or force it
    back with `include_fields`), or drop the `filter_fields` entry. It is **not**
    dropped silently for you — that would repeat the defect 2.2.0 fixed, an
    option accepted and ignored.

    The rule covers every door into the filter input, because they all compile
    from the one declaration this guard checks: relation-spanning paths, a
    relation head declared on a type that hides the relation, the `and` / `or` /
    `not` combinators, nested list filters, and per-field `fields=` overrides.

    **It measures declarations that compile, not declarations.** The guard runs
    while `<Model>FilterInput` is built, and that input is built only because
    some field mounts a filtered list of the type. Declare
    `filter_fields = {"password": ("exact",)}` on a type nothing mounts that way
    and the schema builds in silence — the entry compiled to nothing and no
    client can reach it. Mount `DjangoFilterListField(UserType)` and the same
    declaration raises. So a clean build is a statement about the filter surface
    you actually serve, not a review of every `Meta` in the file: mounting a
    type later can turn a dormant declaration into a build failure, and that is
    the failure arriving exactly when the oracle would have.

#### The shapes it refuses { #filter-refusal-shapes }

The guard walks each declared path against the **compiled types the schema
being built will serve**, so a hop is measured against the type that publishes
*that* hop, never against a registry lookup for the model. Eight declarations
are refused, and only the first is the familiar one — a ninth, the lookup
spelled into the key, is the same defect as the eighth:

| Declaration | Why it is refused |
|-------------|-------------------|
| `{"bio": …}` where the node type hides `bio` | Rule 1 — the column's value is not published. A declared attribute masking `bio` behind a `resolve_bio` reads identically. |
| `{"author__bio": …}` where the **author's** type hides `bio` | The head is only traversed; the tail is measured against the type `author` resolves to. |
| `{"author": ("exact",)}` where the **author's** type hides its own key | A forward foreign key named with no tail is filtered by the target's primary key, so it is that key's value the boundary asks about. |
| `{"posts": ("exact",)}` where the **post's** type hides its own key | The same query, spelled over a reverse foreign key or a many-to-many. Those own no column on this model, so the target's key is asked of the target type directly — otherwise `posts` and `posts__id` would answer differently. |
| `{"author__name": …}` where the type declares `author` over a `resolve_author` of its own | The client reads whatever that resolver returns, while the filter joins straight past it — so the hop is a mask, exactly as a declared column served by a resolver is. This is the [scoping hatch](types.md#relation-scope-hatch); declaring it costs the relation its filter paths. |
| `{"posts__title": …}` where the type declares `posts` as a `DjangoFilterListField` | The to-MANY arm of the same hatch, refused by the same rule. The mounted list field carries a resolver by construction, so the rows the client reads are the ones it hands back while the join reaches every row behind it. |
| `{"category__name": …}` where `Category` has **no registered type** | The compiler emits no `category` field at all, so the hop fails closed. Keeping a nested filter input over a model nothing in the schema can name is a substring oracle over rows nothing can select. |
| `{"pk": …}`, or `{"id": …}` on a natural-key model | The name is not a field, so the entry compiled to **nothing** and the list was never filterable by its key. An option accepted and ignored is the defect every refusal here exists to prevent. |
| `{"name__icontains": …}` — a lookup spelled into the **key** | Lookups are declared in the entry's **value**. Spelled into the key, the whole compound lands on the model's own leaves, where no field answers to it: byte-equivalent to `pk`, and refused for the same reason. Write `{"name": ("icontains",)}`. |

Each refusal opens with the `Meta` the entry has to leave — the type whose
`Meta.filter_fields` declared it, which for a `DjangoListObjectType` that
declares none of its own is the **node type** it inherited the declaration
from — and then names the type **you have to change**, the one owning the hop
that failed rather than the one the path was declared on. A relation the
compiler dropped says so, naming the target model that needs a registered type:

```text
PostType.Meta.filter_fields entry 'category__title' traverses 'category', which
PostType does not publish as a relation -- Meta.only_fields /
Meta.exclude_fields removed it, a declared attribute publishes the name over a
resolver of its own or over a leaf, or the output compiler dropped it because
Category has no registered DjangoObjectType. […] Publish 'category' on PostType -- registering a
DjangoObjectType for Category if that is what is missing -- or drop the entry.
```

#### Two node types over one model share one input { #filter-input-union }

There is exactly one `<Model>FilterInput` per model, and every context building
it converges on the model's root declaration, so two `DjangoObjectType`s over
one model in one schema **share a single instance** — widened in place by
whichever of them asks for the most paths. The boundary is therefore measured
against the **union that will actually be served**, and against **every type
that will serve it**: a narrow type mounted beside a wide one fails the build
rather than inheriting the wide one's filters over a column it projects away.

The **body** of an `@filter_field` method stays the one deliberately open
boundary: the argument is an opaque scalar and the ORM lookup lives in your
Python, where no build-time analysis can see it. Its *name* is checked — see
[Custom per-field filters](#custom-per-field-filters-filter_field).

#### Under `PERMISSION_SCOPED_SCHEMA` the clone answers { #filter-prune-scope }

A permission-scoped schema is a **clone that publishes less**, and the filter
argument narrows with it: a relation the pruned node type no longer publishes
is dropped from the pruned `<Model>FilterInput`, and a nested input left over a
model the clone does not mount falls out of the schema entirely. This is the
same answer the ordering allowlist gives on the same clone — one schema, one
boundary, one predicate.

Which lookups the **list form** actually gives you — and which ones it does
**not** — is covered next.

## Lookup catalog — defaults vs. the full set

There are **two different lookup sets**, and mixing them up is the most common
surprise on this page:

1. The **default set** — what the list form applies automatically.
2. The **full catalog** — everything the engine supports; the extra lookups
   are available **only when you ask for them explicitly** (dict form, or
   globally via the `COMMON_FILTER_LOOKUPS` setting).

### Defaults — what the list form applies

`filter_fields = ["username", ...]` gives each field a curated, type-aware
default set — **not** the full catalog:

| Field kind | Default lookups (list form) |
|---|---|
| every field | `exact`, `in`, `isnull` |
| text (`CharField`, `TextField`, `EmailField`, `URLField`, `SlugField`, …) | + `icontains`, `istartswith` |
| ordered (integer / float / decimal, `DateField`, `DateTimeField`, `TimeField`, `DurationField`) | + `gt`, `gte`, `lt`, `lte`, `range` |

The common base (`exact`, `in`, `isnull`) comes from the
[`COMMON_FILTER_LOOKUPS` setting](settings.md); the text / ordered add-ons are
always appended on top of whatever base you configure.

### Full catalog — what you can declare explicitly

Beyond the defaults, the catalog also supports these lookups. They **never**
appear via the list form — declare them per field with the **dict form**:

| Group | Lookups | Typical fields |
|---|---|---|
| case-sensitive / position (text) | `iexact`, `contains`, `startswith`, `endswith`, `iendswith` | text fields |
| date parts | `year`, `month`, `day`, `week_day` | date / datetime fields |
| time parts | `hour`, `minute`, `second` | time / datetime fields |

```python
from django_graphex.types import DjangoListObjectType

class ArticleListType(DjangoListObjectType):
    class Meta:
        model = Article
        filter_fields = {
            # dict form: any catalog lookup, not just the defaults
            "title": ("iexact", "contains", "endswith"),
            "published_at": ("gte", "lte", "year", "month"),
        }
```

To change the **global base set** that every list-form field receives, use the
setting:

```python
DJANGO_GRAPHEX = {
    # every list-form field now also gets iexact (plus the type add-ons):
    "COMMON_FILTER_LOOKUPS": ("exact", "iexact", "in", "isnull"),
}
```

!!! warning "Declared with the list form ≠ everything is available"

    `filter_fields = ["title"]` does **not** expose `iexact`, `contains`,
    `startswith`, `endswith` or the date/time part lookups — only the
    defaults table above. If a lookup you expect is missing from the schema,
    switch that field to the **dict form** and name it explicitly.

## Querying with `filter:`

Each declared field becomes a nested object of its lookups:

```graphql
query {
  users(filter: {
    username: { icontains: "john" }
    isActive: { exact: true }
    dateJoined: { gte: "2023-01-01" }
  }) {
    results { id username email }
    totalCount
  }
}
```

Multiple keys in the same object are **AND-ed** together.

### Lookup types

| Lookup | Input shape | Meaning |
|---|---|---|
| `exact` | `field: { exact: v }` | equals |
| `icontains` / `istartswith` | `{ icontains: "ab" }` | case-insensitive contains / starts-with |
| `gt` / `gte` / `lt` / `lte` | `{ gte: 10 }` | ordered comparisons |
| `in` | `{ in: [1, 2, 3] }` | membership (a **list**) |
| `range` | `{ range: [10, 20] }` | between (a **two-element list**) |
| `isnull` | `{ isnull: true }` | IS (NOT) NULL |

Only the lookups you declared in `filter_fields` are exposed on each field.
The table shows the default-set shapes; the extra catalog lookups (`iexact`,
`contains`, date/time parts, …) follow the same pattern — see the
[lookup catalog](#lookup-catalog-defaults-vs-the-full-set).

## Logical operators: `and` / `or` / `not`

Every `<Model>FilterInput` carries `and: [..]`, `or: [..]` and `not: {..}`,
referencing itself — so they nest arbitrarily:

```graphql
query {
  articles(filter: {
    status: { exact: PUBLISHED }
    or: [
      { views: { lt: 20 } }
      { views: { gte: 100 } }
    ]
    not: { title: { icontains: "draft" } }
  }) {
    results { title views }
  }
}
```

- `and: [a, b]` → `a AND b`
- `or: [a, b]` → `a OR b`
- `not: a` → `NOT a`
- sibling keys in the same node are AND-ed with the operators.

## Filtering across relations

Declare a `__` path in `filter_fields`; it becomes a **nested** filter input for
the related model, which recurses (and supports its own `and`/`or`/`not`):

=== "Declare"

    ```python
    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            filter_fields = {
                "title": ("icontains", "exact"),
                "author__name": ("icontains", "exact"),
                "author__profile__location": ("icontains",),
                "category__name": ("exact",),
            }
    ```

=== "Query"

    ```graphql
    {
      posts(filter: {
        title: { icontains: "django" }
        author: { name: { icontains: "ada" } }
        category: { name: { exact: "Tech" } }
      }) {
        results { title author { name } }
      }
    }
    ```

A filter that traverses a **to-many** relation (reverse FK / M2M) automatically
applies `.distinct()` so join fan-out doesn't duplicate rows.

!!! info "Declaring a relation **and** a path through it"

    `{"author": ("exact",), "author__name": ("icontains",)}` declares the same
    relation twice. Both halves are kept: the nested `AuthorFilterInput` mounts
    as usual, and the plain-pk lookups move **onto** it under the related
    model's primary-key name.

    ```graphql
    { posts(filter: { author: { id: { exact: 5 }, name: { icontains: "ada" } } }) { results { title } } }
    ```

!!! info "Nested lookups are unioned with the related type's own declaration"

    When the related model has its own root `filter_fields`, a nested request
    that asks for a lookup the root does not declare **widens** the generated
    `<Related>FilterInput` instead of being dropped. Declaring
    `AuthorType.filter_fields = {"name": ("exact",)}` and
    `PostType.filter_fields = {"author__name": ("icontains",)}` yields
    `AuthorNameLookups { exact, icontains }`, so both contexts work off one
    canonical type.

!!! danger "The **related** type's projection governs the nested input"

    Each hop of a `__` path is checked against the type that publishes it, not
    against the type that declared the path. `PostType.filter_fields =
    {"author__bio": …}` is refused when **`AuthorType`** hides `bio`, and it is
    refused when `PostType` hides the `author` relation itself. Otherwise any
    third type could undo a projection by reaching the column through a join —
    and because all filter inputs for a model converge on one
    `<Model>FilterInput`, that widened shape would then serve every list
    filtering that model. See
    [The projection is the outer boundary](#projection-boundary).

## Filtering by id / pk (incl. `UUIDField`)

Declare the `id` field — or a relation field **directly** (not a `__` path) — with
scalar lookups, and it filters on the primary key. This replaces the old
`GraphqlIDFilter` and works for integer **and** UUID pks:

=== "Declare"

    ```python
    class OrderListType(DjangoListObjectType):
        class Meta:
            model = Order
            filter_fields = {
                "id": ("exact", "in"),        # the order's own pk
                "customer": ("exact", "in"),  # by related pk (FK column)
            }
    ```

=== "Query"

    ```graphql
    {
      orders(filter: {
        customer: { exact: 5 }          # plain integer pk
        id: { in: ["9b2e...", "7c1d..."] }   # or UUID pks
      }) {
        results { id }
      }
    }
    ```

!!! warning "A relation-direct entry needs the **target** type's key published"

    `"customer": ("exact",)` filters on `Order.customer_id`, whose value is the
    *customer's* primary key — so it is admitted only when the type behind
    `customer` publishes that key. A customer type declaring
    `only_fields = ("name",)` refuses this entry at build time, exactly as
    `ordering: "customer_id"` is refused at query time on the same schema. It is
    the third row of [The shapes it refuses](#filter-refusal-shapes) — the
    fourth covers the same query spelled over a reverse relation or a
    many-to-many — and the refusal names the customer's type, which is where
    the fix belongs.

## `choices` fields filter via their Enum

A model field with `choices` is exposed in the filter input through the same
GraphQL **Enum** as the output type:

```graphql
{ articles(filter: { status: { in: [PUBLISHED, DRAFT] } }) { results { title } } }
```

## Custom per-field filters — `@filter_field`

Use the `@filter_field` decorator to declare a **custom GraphQL filter argument**
directly on a `DjangoObjectType` or `DjangoModelType`. The method name becomes
the GraphQL argument name; the method body returns a queryset.

```python
from graphql import GraphQLString
from django.db.models import Q
from django_graphex.filtering import filter_field
from django_graphex.types import DjangoObjectType

class PostType(DjangoObjectType):
    class Meta:
        model = Post
        # filter_fields only for REAL model fields:
        filter_fields = {"title": ("exact", "icontains")}

    @filter_field(GraphQLString, description="Full-text search over title and body")
    def search(cls, queryset, info, value):
        return queryset.filter(
            Q(title__icontains=value) | Q(body__icontains=value)
        )
```

```graphql
query {
  posts(filter: {
    title: { icontains: "django" }   # standard lookup
    search: "tutorial"               # custom filter
  }) {
    results { id title }
  }
}
```

!!! warning "The method NAME is checked"

    A method spelled like a column the type hides compiles the very same
    `<Model>FilterInput` field that a `filter_fields` entry naming it is
    refused, so the one-line rename out of a refusal is shut. Declaring
    `def bio(...)` on a type whose `only_fields` drops `bio` fails the build:

    ```text
    Author: @filter_field method 'bio' is spelled like a column AuthorType does
    not publish, so it compiles the same <Model>FilterInput field a
    filter_fields entry naming it is refused. Rename the method, or publish
    'bio' on AuthorType.
    ```

    A method whose name is not a column on the model — `search` above — says
    nothing about what its body touches and is left alone.

!!! danger "The projection guard stops at the method BODY — this is on you"

    Everything else in this page is checked when the schema builds. A
    `@filter_field` **body** cannot be: its argument is an opaque scalar and the
    ORM lookup lives in your Python, so nothing at build time can see which
    columns it touches. The example above would happily read a `body` the type
    hides, under the perfectly innocent name `search`.

    This is a **documented boundary, deliberately left open** — refusing every
    `@filter_field` on a projected type would punish the honest majority for a
    body the compiler cannot read. When your type declares `only_fields` /
    `exclude_fields`, it is your job to keep the method body inside that same
    set. A method that filters on a hidden column reopens exactly the oracle
    [the projection boundary](#projection-boundary) closes.

### Decorator signature

```python
def filter_field(graphql_type=GraphQLString, *, description=None): ...

@filter_field(GraphQLString, description="...")
def <name>(cls, queryset, info, value):
    ...
```

| Parameter | Default | Description |
|---|---|---|
| `graphql_type` | `GraphQLString` | The graphql-core scalar or type for the GraphQL argument (`GraphQLInt`, `GraphQLString`, or a `GraphQLList` / `GraphQLNonNull` wrapper). A leftover graphene scalar raises `TypeError`. This parameter was renamed in v2.0 (see the changelog). |
| `description` | `None` | Optional GraphQL description string for the argument. |

- **`cls`** — the type class (classmethod semantics handled internally; do NOT stack `@classmethod`).
- **`queryset`** — the queryset to filter; must return a `QuerySet`.
- **`info`** — the GraphQL resolve info.
- **`value`** — the argument value from the query.

### Type override

```python
from graphql import GraphQLInt

@filter_field(GraphQLInt, description="Minimum view count")
def min_views(cls, queryset, info, value):
    return queryset.filter(views__gte=value)
```

### Composition order

At query time, the list resolvers compose the queryset in this order:

1. **`get_queryset` / `filter_queryset`** — the **base** queryset is scoped
   first (`Meta.queryset` or the default manager, then your `filter_queryset`
   override).
2. **Standard `filter_fields` lookups** — the whole nested `filter:` tree
   (fields, relations, `and` / `or` / `not`) is collapsed into **one `Q`
   object** and applied as a **single** `.filter(...)` call — one SQL `WHERE` —
   with `.distinct()` applied at most **once** (when a to-many relation was
   traversed).
3. **Custom `@filter_field` methods** — chained one by one, in declaration
   order.

The order is the same wherever the list appears. A
[nested list](nested-lists.md) mounts the *same* `<Model>FilterInput`, so it
runs the custom methods too — on its rows **and** on its `totalCount`,
whichever internal path serves the page (prefetch, DB-side window, or the
per-parent fallback).

**Why this order?** Server-forced scoping goes first so no client-supplied
filter can ever widen the visible rows. The standard lookups are
*declarative*, so the engine can merge them into a single `WHERE` clause and
decide `.distinct()` exactly once — that is why they run together as one
stage. Custom `@filter_field` methods are *opaque* Python (they may add
joins, annotations, or their own `.distinct()`), so they chain last, each
receiving the queryset the previous stage produced.

#### Worked example: all three stages in one query

```python
from django.db.models import Q
from django_graphex.filtering import filter_field
from django_graphex.types import DjangoListObjectType, DjangoObjectType


class PostType(DjangoObjectType):
    class Meta:
        model = Post
        # stage 2: standard filter_fields lookups
        filter_fields = {"title": ("icontains", "exact"), "views": ("gte", "lte")}

    @classmethod
    def get_queryset(cls, queryset, info):
        # stage 1: server-forced scoping — never client-visible as an argument
        return queryset.exclude(is_draft=True)

    @filter_field(description="Full-text search over title")
    def search(cls, queryset, info, value):
        # stage 3: custom, opaque Python — chained last
        return queryset.filter(Q(title__icontains=value))


class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
```

```graphql
query {
  posts(filter: { title: { icontains: "world" }, search: "world" }) {
    results { id title views }
    totalCount
  }
}
```

What runs, in order:

1. `get_queryset` scopes the base queryset to `queryset.exclude(is_draft=True)`
   — draft posts are invisible no matter what `filter:` the client sends. A
   `"World draft"` post with `is_draft=True` never reaches later stages, even
   though its title matches both `icontains: "world"` and `search: "world"`.
2. The standard lookup, `title: { icontains: "world" }`, is collapsed into a
   single `Q` and applied as **one** `.filter(...)` call.
3. The custom `search` argument runs last, chaining its own
   `.filter(Q(title__icontains="world"))` on the queryset stage 2 produced.

A live repro against this exact declaration confirms the composition: the
draft post is excluded regardless of `filter:`, and Django folds the chained
`.filter()` calls from stages 2 and 3 into a single SQL `WHERE` (both
conditions test the same column here only because the example reuses
`icontains` for `search`; in general the custom stage can add joins,
annotations, or its own `.distinct()` that stage 2 knows nothing about):

```sql
SELECT "post"."id", "post"."title", "post"."views" FROM "post"
WHERE (NOT ("post"."is_draft")
   AND "post"."title" LIKE '%world%' ESCAPE '\'
   AND "post"."title" LIKE '%world%' ESCAPE '\')
```

`NOT ("post"."is_draft")` is stage 1's `get_queryset` scoping; the two
`title LIKE` fragments are stages 2 and 3 respectively (they look identical
here only because the example's custom filter reuses `icontains` under the
hood — a `search` implementation doing a JOIN or annotation would show up as
its own fragment instead).

#### How the `filter:` value is split between stages

Stages 2 and 3 read the **same** `filter:` input value, partitioned by
**model introspection**: a top-level key that is a real model field or
relation (or a combinator) goes to the standard-lookup stage; any other key
is assumed to be a custom `@filter_field` argument and is left for stage 3.

Two consequences:

- **Never name a `@filter_field` after a real model field.** The partition
  looks at the *model*, not at what you declared — a custom filter named like
  a model column (e.g. `def title(...)` on a model with a `title` field) gets
  routed to the standard-lookup translator, which expects a
  `{lookup: value}` object and crashes on the scalar value. Pick a name that
  is not a model field (`search`, `title_matches`, …).
- **Custom arguments only work at the top level of `filter:`.** The
  `and` / `or` / `not` combinators translate to a single `Q`, and custom
  methods are never applied inside them — so a custom argument used inside a
  combinator raises a clear `GraphQLError` ("Unknown filter field 'search'
  inside the 'and' combinator …") instead of silently matching nothing.

Keys that are not part of the generated `<Model>FilterInput` at all never
reach the resolver — GraphQL validation rejects the query before execution.

### Reserved argument names

The following names are **reserved** for pagination and built-in arguments.
Using them as `@filter_field` method names raises `ImproperlyConfigured` at
class definition:

`limit`, `offset`, `ordering`, `page`, `page_size`, `first`, `cursor`, `filter`, `id`

```python
# This raises ImproperlyConfigured immediately at class definition:
@filter_field(GraphQLString)
def limit(cls, queryset, info, value):   # ← name conflict!
    ...
```

A `@filter_field` method must also not be named after a filter argument the
`Meta.filter_fields` declaration already compiles, nor after an `and` / `or` /
`not` combinator. Such a collision raises `ImproperlyConfigured` when the
filter input is built:

```python
class PostType(DjangoObjectType):
    class Meta:
        model = Post
        filter_fields = {"title": ("exact", "icontains")}

    @filter_field(GraphQLString)
    def title(cls, queryset, info, value):   # ← shadows the compiled `title`
        ...
```

Previously the custom filter silently replaced the generated
`PostTitleLookups` input, leaving the field unfilterable in both shapes.

### `filter_queryset` — scope the base queryset

For server-side scoping that applies on every request (not client-visible
as a GraphQL argument), override `filter_queryset` on a `DjangoModelType`:

```python
from django.db.models import Q
from django_graphex.types import DjangoModelType

class UserType(DjangoModelType):
    class Meta:
        model = User
        filter_fields = {"username": ("icontains",)}

    @classmethod
    def filter_queryset(cls, qs, info, **kwargs):
        # e.g. always scope to the current user's tenant
        return qs.filter(tenant=info.context.user.tenant)
```

The scope applies to **every** CRUD operation on the type, writes included:
`retrieve` and `list` narrow their results, and `update` and `delete` resolve
their target row through the same hook, so a row belonging to another tenant
answers exactly as a missing one (`ok: false`, `<Model> with id <pk> does not
exist.`) instead of being written.

`DjangoModelMutation` carries the **same two hooks**, with the same names and
the same signatures, so an override moves between the two hosts unchanged. It
has no read operations, so there the scope governs `update` and `delete` only.

!!! warning "`permission_classes` is `DjangoModelType`-only"
    `get_queryset` / `filter_queryset` answer *which rows exist for this
    caller*. `permission_classes` / `authorize` answer *may this caller perform
    this action* — and those live on `DjangoModelType` alone.
    `DjangoModelMutation` does **not** check them; declaring
    `permission_classes` on one has no effect. Use `DjangoModelType` when you
    need per-action authorization, or gate the mutation at the schema root.

!!! danger "Upgrade note — fixed in 2.2.0"
    2.1.0 and earlier applied this scope on the read path only: `update` and
    `delete` looked their target up on the bare model, so the snippet above
    protected reads while leaving every row in the table writable by any
    caller. Both write methods resolve through the scoped queryset from 2.2.0
    on; if you are still on 2.1.0 or earlier, upgrade.

See [Permissions & hooks](permissions.md) for `get_queryset` / `filter_queryset`.

## Combining with pagination & ordering

Filtering composes with the list field's pagination/ordering, which live on the
`results(...)` subfield:

```graphql
{
  users(filter: { isActive: { exact: true }, username: { icontains: "jo" } }) {
    results(limit: 10, offset: 20, ordering: "-date_joined") {
      username email dateJoined
    }
    totalCount
  }
}
```

!!! warning "A hidden column is not sortable either"

    The two axes are **one boundary asking one predicate**, so they cannot
    disagree: a column removed with `only_fields` / `exclude_fields` is rejected
    by `ordering` for the same reason it cannot appear in the filter input at
    all — a filter narrow enough to isolate a pair of rows, plus an `ordering`
    on the hidden column, reads the hidden value back one comparison at a time.
    The rule itself lives in
    [Types › The projection is a security boundary](types.md#projection-security-boundary);
    see [the outer boundary](#projection-boundary) for the filter half and
    [Ordering validation](pagination.md#ordering-validation-security) for the
    ordering half.

    They differ only in **when** they fire. The filter half is enforced at
    **build time** — a `filter_fields` entry naming a hidden column fails the
    schema build outright, so nothing hidden ever reaches the filter input. The
    ordering half is enforced at **query time**, because the allowlist belongs
    to the schema serving the request: under
    [`PERMISSION_SCOPED_SCHEMA`](permission-scoped-schema.md) two callers hold
    different pruned schemas over the same type, and only the one serving the
    request can say what it publishes.

    The ordering axis also carries the boundary's
    [one exception](types.md#projection-exception) — an operator-configured
    `ordering=` default on the two offset paginators. The filter axis has no
    equivalent: there is no operator-supplied filter *value*, only a declared
    surface, and a declared surface is exactly what is refused.

## Field-level filtering

Everything above configures filtering **on the type**: you declare
`Meta.filter_fields` once, mount the type with `DjangoListObjectField`, and
every query using it gets the same wrapped result (`results` / `totalCount`)
with the same filter surface.

Field-level filtering is the alternative for two situations:

- You want a **flat list** — the objects themselves (`[User!]`), with **no**
  `results` / `totalCount` wrapper.
- You want to decide which fields are filterable **per query field**, not
  once per type.

That is what `DjangoFilterListField` and `DjangoFilterPaginateListField` do.
Mounted directly on `Query`, they expose the same `filter:` argument (and, for
the paginate variant, the pagination arguments **on the field itself**). The
optional `fields=` parameter declares the filterable fields for **that one
field** — that per-field override is what makes it "field-level":

```python
from django.contrib.auth.models import User

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField, DjangoFilterPaginateListField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.types import DjangoObjectType


class UserType(DjangoObjectType):
    class Meta:
        model = User


class Query(ObjectType):
    # Flat [User] list — THIS field is filterable by username only:
    users = DjangoFilterListField(UserType, fields=["username"])

    # Flat [User!] list — filter + limit/offset args live on the field itself:
    paged_users = DjangoFilterPaginateListField(
        UserType,
        pagination=LimitOffsetGraphqlPagination(default_limit=20),
        fields=["username"],
    )
```

```graphql
query {
  users(filter: { username: { icontains: "jo" } }) {
    id
    username
  }
  pagedUsers(filter: { username: { icontains: "jo" } }, limit: 10, offset: 0) {
    id
    username
  }
}
```

Note the difference from the type-level queries earlier on this page: there is
no `results { … }` wrapper and no `totalCount` — the field returns the list
directly.

Omit `fields=` and the field falls back to the type's own
`Meta.filter_fields` declaration (no filtering at all if the type declares
none).

!!! note "One canonical filter input per model"

    All filter inputs for the same model converge on a **single**
    `<Model>FilterInput` type. If the type *also* declares
    `Meta.filter_fields` covering the paths you pass in `fields=`, the type's
    (wider) declaration wins — a per-field `fields=` cannot **narrow** it; it
    can only add paths (which then appear for every field filtering that
    model). The per-field override shines when the type itself declares no
    `filter_fields` (as above), giving each query field its own filter
    surface.

    Because a `fields=` override **widens** that shared type, it is checked
    against the node type's projection exactly like a `Meta.filter_fields`
    declaration: a `fields=` entry naming a hidden column fails the schema
    build. Widening is the second door into the same input, and it is shut too
    — see [The projection is the outer boundary](#projection-boundary).

## Best practices

!!! tip

    1. Index frequently-filtered columns (`db_index=True`).
    2. Only declare fields you want to expose — `filter_fields` is the allow-list.
    3. Combine with `get_queryset` (`select_related` / `prefetch_related`) to keep
       relation filters efficient.
    4. Use `get_queryset` / `filter_queryset` for free-text search and any
       server-forced scoping.
