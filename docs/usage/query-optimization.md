# Query Optimization (N+1)

`django-graphex` inspects the **incoming GraphQL selection** and builds an
optimized Django queryset for the list resolvers, so nested relations do not
trigger the classic **N+1 query problem**. This happens automatically in
`DjangoListObjectField`, `DjangoFilterPaginateListField`, `DjangoFilterListField`
and `DjangoModelType.QueryFields()`, and for **single-object** lookups
(`DjangoObjectField` and `DjangoModelType` retrieve / `RetrieveField`) — all
routed through `django_graphex.utils.queryset_factory`.

## Optimization surface at a glance

This page is the **hub** for every query-optimization feature — each is
demonstrated below with models + types + a GraphQL query, and links to its
dedicated reference page for the deep detail:

- **`select_related` / `prefetch_related`** derived from the selection
  (+ prefetch-crossing `select_related` drop) — [below](#example), this page.
- **`.only()` column projection** (root span + inside each `Prefetch` child) —
  [below](#only-column-projection), this page.
- **DB-side nested pagination** (`ROW_NUMBER()` window slicing + filter-aware
  `totalCount`) — [below](#db-side-nested-pagination-window-slicing); full decline
  list in [Nested Lists → Performance (N+1)](nested-lists.md#performance-n1).
- **`AnnotatedField`** (selection-driven `.alias()` / `.annotate()`) —
  [below](#selection-driven-annotations-annotatedfield); full reference in
  [Fields → AnnotatedField](fields.md#annotatedfield).
- **Per-field `optimize_<field>` hook** —
  [below](#per-field-optimize-hook); full reference in
  [Nested Lists → Per-field optimize hook](nested-lists.md#per-field-optimize-hook).
- **Typed `GenericForeignKey` unions** (per-content-type `GenericPrefetch`
  narrowing) — [below](#typed-genericforeignkey-unions-per-content-type-narrowing);
  full type-side declaration in
  [Types → DjangoUnionType](types.md#djangouniontype-typed-genericforeignkey-targets).

All of it is governed by the [`OPTIMIZE_*` settings](#settings) and the global
[`OPTIMIZER_SAFE_MODE`](#optimizer_safe_mode-fail-safe-degrade) fail-safe.

## What it does

For the fields requested in the query, the optimizer:

- adds **`select_related`** for forward `ForeignKey` / `OneToOneField` (and
  reverse one-to-one) — including **nested** dotted paths (`a__b__c`);
- adds **`prefetch_related`** for `ManyToManyField` and reverse relations
  (also nested, e.g. `author__posts`);
- adds **`prefetch_related`** for a `GenericForeignKey` (resolved in a second
  query on `field.name`; the parent's content-type-id and object-id columns are
  kept), and for a `GenericRelation` reverse side — which **is**
  `.only()`-narrowed, keeping its content-type / object-id attnames;
- applies a conservative **`.only()`** column projection both **across the
  `select_related` span** and **inside each `Prefetch` child queryset**
  (see [caveats](#only-column-projection)).

It is transparent to the `DjangoListObjectType` wrapper (`results` / `totalCount`
/ `pageInfo`), to **fragments** and to **inline fragments**, and matches both
`camelCase` and `snake_case` field names.

## Example

```python
# models.py
class Author(models.Model):
    name = models.CharField(max_length=100)

class Tag(models.Model):
    label = models.CharField(max_length=50)

class Post(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    author = models.ForeignKey(Author, related_name="posts", on_delete=models.CASCADE)
    tags = models.ManyToManyField(Tag, related_name="posts")
```

```python
# schema.py
import graphene
from django_graphex import DjangoListObjectField, DjangoListObjectType, DjangoObjectType


class AuthorType(DjangoObjectType):
    class Meta:
        model = Author

class TagType(DjangoObjectType):
    class Meta:
        model = Tag

class PostType(DjangoObjectType):
    class Meta:
        model = Post

class PostListType(DjangoListObjectType):
    class Meta:
        model = Post

class Query(graphene.ObjectType):
    all_posts = DjangoListObjectField(PostListType)
```

A nested query:

```graphql
{
  allPosts {
    results {
      title
      author { name }   # ForeignKey  -> select_related("author")
      tags { label }    # ManyToMany   -> prefetch_related("tags")
    }
    totalCount
  }
}
```

runs a **constant** number of database queries no matter how many posts are
returned:

1. `SELECT ... FROM post JOIN author ...` (rows + author joined, `select_related`)
2. `SELECT ... FROM tag ...` (one extra query for the `prefetch_related`)
3. `SELECT COUNT(*) ...` (from the list field's `totalCount`)

Without optimization the same query would run **1 + N** (one author query per
post) **+ N** (one tag query per post). This is verified in the test-suite with
`assertNumQueries`.

## Single objects

The same optimization applies to single-object queries. For:

```graphql
{
  post(id: 1) {
    title
    author { name }   # select_related("author")
    tags { label }    # prefetch_related("tags")
  }
}
```

the lookup runs **1 query** (the row with its forward relations joined in) **+ 1
per prefetched relation**, instead of one query per nested relation.

## `.only()` column projection

When `OPTIMIZE_ONLY_FIELDS` is enabled (default), the optimizer also restricts the
selected columns with `.only()`, loading just the fields the query asks for. To
stay correct it is **conservative**:

- it always keeps the primary key (for every model in the `select_related` span),
  forward `ForeignKey` columns and the model's `Meta.ordering` columns;
- a model that selects a **computed / property / custom-named** field is loaded in
  **full** (not narrowed), so that property keeps working;
- narrowing also applies **inside each `Prefetch` child queryset**: the child
  gets its own `.only()` keeping the reverse-FK back column, the child's
  `Meta.ordering` columns, its pk and any `GenericRelation` ct/fk attnames; a
  small set of forward-FK heads is added back to the child `select_related` so
  the narrowing does not re-introduce an N+1. A child whose sub-selection hits a
  computed / property leaf is full-loaded (bare-string prefetch, no `.only()`).

!!! warning "Models with properties / custom resolvers"
    `.only()` defers the columns you did not request. If a model **property**,
    `__str__`, a signal or a custom resolver reads a column that is *not* part of
    the GraphQL selection, accessing it will trigger one extra query per row (a
    new N+1) or surface incomplete data. The full-model safety valve covers the
    common case (a selected computed field), but if your models read non-selected
    columns out of band, disable it:

    ```python
    DJANGO_GRAPHEX = {
        "OPTIMIZE_ONLY_FIELDS": False,
    }
    ```

## Settings

Configure in `settings.py` under `DJANGO_GRAPHEX`:

| Setting | Default | Description |
|---------|---------|-------------|
| `OPTIMIZE_QUERYSET` | `True` | Apply nested `select_related` / `prefetch_related` derived from the query. Set to `False` to return the plain queryset (escape hatch). |
| `OPTIMIZE_ONLY_FIELDS` | `True` | Additionally narrow columns with `.only()` across the `select_related` span **and** inside each `Prefetch` child queryset (conservative; see the warning above). |
| `OPTIMIZE_NESTED_PAGINATION` | `True` | DB-side `ROW_NUMBER()` window slicing for reverse-FK nested paginated lists (`LimitOffset`/`Page`). `False` = in-memory order+slice fallback. See [DB-side nested pagination](#db-side-nested-pagination-window-slicing) (this page) and [Nested Lists](nested-lists.md#performance-n1). |
| `OPTIMIZER_SAFE_MODE` | `False` | When `True`, any exception in the optimization block degrades to the un-optimized queryset and logs a `WARNING` (instead of a 500). Default fail-loud. See [`OPTIMIZER_SAFE_MODE`](#optimizer_safe_mode-fail-safe-degrade) below. |
| `OPTIMIZE_ANNOTATED_FIELDS` | `True` | Inject `AnnotatedField` DB annotations only when the field is selected. Runtime kill-switch for annotation injection. See [Fields → AnnotatedField](fields.md#annotatedfield). |

```python
DJANGO_GRAPHEX = {
    "OPTIMIZE_QUERYSET": True,
    "OPTIMIZE_ONLY_FIELDS": True,
    "OPTIMIZE_NESTED_PAGINATION": True,
    "OPTIMIZER_SAFE_MODE": False,
    "OPTIMIZE_ANNOTATED_FIELDS": True,
}
```

## `OPTIMIZER_SAFE_MODE` (fail-safe degrade)

By default (`OPTIMIZER_SAFE_MODE = False`) the optimizer **fails loud**: if
building the optimized queryset raises, the exception propagates and you get a
500 — so you find the bug.

Setting it to `True` wraps the **whole** optimization in a `try/except`: on *any*
exception the entire resolve degrades to the **un-optimized base queryset** and a
`WARNING` is logged (`django_graphex.utils`) instead of surfacing the error. The
boundary is **coarse** — it degrades the whole resolve, not a single field — so a
raising per-field `optimize_<field>` hook is caught here too. It does **not**
cover a malformed `AnnotatedField` expression that raises `FieldError` at
SQL-eval time (that happens outside the build boundary; annotation injection has
its own narrower guard that skips just the annotation).

```python
DJANGO_GRAPHEX = {
    "OPTIMIZER_SAFE_MODE": True,
}
```

## DB-side nested pagination (window slicing)

When a reverse-FK nested list is **paginated** (with a `LimitOffset` or `Page`
paginator), the optimizer slices each parent's page **in the database** instead
of loading every child and slicing in memory. It does this inside the **single**
`Prefetch` it already builds for that level — so the query count stays constant
as the number of parents grows.

Using the same `Author (1) ─→ (N) Post` models from above, with a paginator and
a nested filter:

```python
# models.py
class Post(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, related_name="posts", on_delete=models.CASCADE)

    class Meta:
        ordering = ("-id",)

# schema.py
from django_graphex import (
    DjangoListObjectField, DjangoListObjectType, DjangoObjectType,
    LimitOffsetGraphqlPagination,
)

class PostType(DjangoObjectType):
    class Meta:
        model = Post
        filter_fields = {"title": ["icontains"]}     # enables the nested filter

class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        pagination = LimitOffsetGraphqlPagination(default_limit=10, ordering="-id")

class AuthorType(DjangoObjectType):
    class Meta:
        model = Author

class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author

class Query(graphene.ObjectType):
    authors = DjangoListObjectField(AuthorListType)
```

Filter on the field, paginate/order on `results`:

```graphql
{
  authors {
    results {
      name
      posts(filter: { title: { icontains: "x" } }) {   # filter on the field
        results(limit: 2, ordering: "-id") { title }    # paginate/order on results
        totalCount
      }
    }
    totalCount
  }
}
```

**What it optimizes:** the **one** `Prefetch` covering every author's posts adds
two window functions and filters to the page window, so it fetches only each
author's requested **page rows** DB-side (not all-then-slice-in-memory):

```python
_gqx_rn    = Window(RowNumber(), partition_by=[F("author_id")], order_by=...)
_gqx_total = Window(Count("*"),  partition_by=[F("author_id")])
# ...then .filter(_gqx_rn__gt=offset, _gqx_rn__lte=offset + limit)
```

`totalCount` is the **per-partition filtered `COUNT(*)`** read off `_gqx_total`,
so it reflects the nested filter without an extra query. Adding authors never
adds queries — the level stays at a **constant** query count.

Controlled by [`OPTIMIZE_NESTED_PAGINATION`](#settings) (default `True`). When a
relation is not windowable, the same single `Prefetch` is reused and the page is
ordered + sliced **in memory** instead — see
[Nested Lists → Performance (N+1)](nested-lists.md#performance-n1) for the full
decline list (cursor paginator, M2M, relation-aggregate child, non-concrete
ordering, full-load sub-selection, `.distinct()`, `OPTIMIZE_QUERYSET=False`).

## Per-field optimize hook

To customize the child queryset for a **specific** nested list field — add a
`select_related`, a custom annotation, a default ordering — declare an
**`optimize_<snake_field>`** static method on the **parent** graphene type:

```python
from django_graphex.fields import DjangoNestedListObjectField

class AuthorType(DjangoObjectType):
    posts = DjangoNestedListObjectField(PostListType, accessor="posts")

    class Meta:
        model = Author

    @staticmethod
    def optimize_posts(queryset, info, **kwargs):
        # kwargs: filter_value (filter input or None), is_window (True on the
        # DB-side windowed path). Compose on the optimizer-built child queryset.
        return queryset.select_related("category")
```

!!! warning "`select_related(<fk>)` in a hook needs the client to select that relation"
    The optimizer applies its `.only()` column narrowing to the child queryset
    **after** the hook runs. If the client does **not** also select `category`,
    `category_id` is deferred and `select_related("category")` raises a Django
    `FieldError`. So a bare `select_related(<fk>)` in a hook is only safe when the
    relation is part of the selection — otherwise compose with an ordering (e.g.
    `queryset.order_by("-id", "title")`) instead. The example playground uses the
    ordering form for exactly this reason (`AuthorType.optimize_posts` in
    `blog/schema.py`).

- The method name is `optimize_` + the **snake_case** GraphQL field name
  (`blogPosts` → `optimize_blog_posts`), declared on the **parent** type.
- It is called **once per query** (not once per parent) and **must return a
  `QuerySet`** — anything else emits a `WARNING` and the built queryset is used
  unchanged.
- `kwargs` are `filter_value` (the filter input or `None`) and `is_window`
  (`True` only on the DB-side windowed path).
- A raising hook is caught by [`OPTIMIZER_SAFE_MODE`](#optimizer_safe_mode-fail-safe-degrade)
  when it is `True` (whole resolve degrades); with the default `False` it
  propagates. Only `DjangoNestedListObjectField` supports the hook.

See [Nested Lists → Per-field optimize hook](nested-lists.md#per-field-optimize-hook)
for the full rules, the safe-mode interaction and a complete example.

## Typed GenericForeignKey unions (per-content-type narrowing)

A `GenericForeignKey` exposed as a [`DjangoUnionType`](types.md#djangouniontype-typed-genericforeignkey-targets)
(member types in `Meta.gfk_types`, owner opting in via `Meta.gfk_unions`) lets
clients select per-member fields with **inline fragments**:

```graphql
{
  attachments {
    results {
      caption
      target {
        __typename
        ... on AccountType { balance }
        ... on InvoiceType { amount }
      }
    }
  }
}
```

**What it optimizes:** on **Django 5.0+** with `OPTIMIZE_ONLY_FIELDS` on, the
optimizer routes the union GFK through a `GenericPrefetch` that builds **one
`.only()`-narrowed queryset per content type** — the `Account` queryset fetches
`balance`, the `Invoice` queryset fetches `amount` — batched across all parents
(no N+1). On **Django < 5.0** it degrades gracefully to a single bare full-load
`Prefetch` (it never imports `GenericPrefetch` and never narrows columns).

!!! note "Inline-fragment type-condition guard"
    This routing relies on a correctness guard: the optimizer never descends
    into an inline fragment whose `type_condition` names a *different* concrete
    type than the one being walked, so `... on InvoiceType { amount }` is never
    mis-attributed against the `Account` relation map (which would yield wrong
    `.only()` columns and a Django `FieldError`). See the
    [1.2.0 changelog](../changelog.md#120).

The type-side declaration order is **load-bearing** (members → union → owner
LAST). See [Types → DjangoUnionType](types.md#djangouniontype-typed-genericforeignkey-targets)
and [Types → per-content-type narrowing](types.md#per-content-type-column-narrowing-django-50)
for the full declaration and the proxy-model de-dup behavior.

## Selection-driven annotations (`AnnotatedField`)

An `AnnotatedField` is a declarative GraphQL field backed by a Django ORM
annotation that the optimizer injects **only when the field is selected** in the
incoming query (and only when `OPTIMIZE_ANNOTATED_FIELDS` is `True`, the default).
Unselected annotated fields add no SQL. A built-in resolver reads the annotation
off the row, so no `resolve_<field>` is needed.

A forward-FK relation that the optimizer placed in `select_related` is
**auto-promoted** to `prefetch_related` when its child sub-selection contains an
`AnnotatedField` — DB annotations cannot be pushed through a SQL `JOIN`, so the
child annotation rides on the promoted `Prefetch`'s queryset instead.

Declare it on the type and let the selection drive it (`Author (1) ─→ (N) Post`):

```python
# schema.py
import graphene
from django.db.models import Count
from django_graphex import (
    AnnotatedField, DjangoListObjectField, DjangoListObjectType, DjangoObjectType,
)

class AuthorType(DjangoObjectType):
    # Injected ONLY when `postCount` is selected; the built-in resolver reads it
    # off the row, so no resolve_post_count is needed.
    post_count = AnnotatedField(graphene.Int, Count("posts"))

    class Meta:
        model = Author

class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author

class Query(graphene.ObjectType):
    authors = DjangoListObjectField(AuthorListType)
```

```graphql
{
  authors {
    results {
      name
      postCount        # selected -> optimizer adds .annotate(_gqx_ann_post_count=Count("posts"))
    }
  }
}
```

**What it optimizes:** when `postCount` is in the selection the optimizer adds
the `Count("posts")` annotation (one aggregate, no extra round-trip per author);
when it is **not** selected, no annotation and **no extra SQL** are emitted. The
`expression` may also be a zero-arg callable (`lambda: Count("posts")`) for fresh
per-request construction, and `aliases=` applies `.alias()` before `.annotate()`.

See [Fields → AnnotatedField](fields.md#annotatedfield) for the full signature,
arguments table and the forward-FK promotion note.

## @skip and @include directives

The optimizer honors `@skip` and `@include` on every selection node — fields,
inline fragments, and fragment spreads. A selection that is excluded is **not
added to `select_related` / `prefetch_related`** and its columns are **not
included in `.only()`**. This prevents over-fetching related rows that the client
will never use.

```graphql
query GetPosts($loadAuthor: Boolean!) {
  posts {
    results {
      title
      # When $loadAuthor is false the optimizer skips the author join entirely
      author @include(if: $loadAuthor) {
        name
      }
      # tags are also skipped when @skip(if: true)
      tags @skip(if: true) {
        label
      }
    }
  }
}
```

In this query, when `$loadAuthor` is `false` the `author` FK is not added to
`select_related` and `author_id` is not included in the `.only()` projection.
When `tags` has `@skip(if: true)` the `tags` M2M is not added to
`prefetch_related`.

!!! note "Variable-driven directives"

    The optimizer runs at execution time when all variables are already bound, so
    `@skip(if: $flag)` and `@include(if: $show)` are always resolved exactly.

!!! note "Output-formatting directives do not affect fetch planning"

    Custom application-level directives such as `@date` and `@number` are
    *output-formatting* directives: they transform the resolved value of an
    already-fetched field. They have **no effect** on the optimizer's
    select/prefetch/only planning.

## Custom resolvers

If your query type defines `resolve_<field>` that returns a **`QuerySet`**, the
optimizer adopts it as the base queryset and still applies `select_related` /
`prefetch_related` on top of it. (`.only()` is skipped for custom-resolved
querysets, since they may already shape their own columns.) Resolvers that return
anything other than a `QuerySet` are left untouched.

## Optimized mutation re-read

`DjangoModelType.perform_mutate` re-reads the saved object from the database
so the mutation response reflects the freshest DB state (annotations, default
values, etc.).  Starting in **v1.2.1**, this re-read is **selection-aware**:
the optimizer inspects the mutation's selection set, locates the sub-field node
for `Meta.output_field_name` (e.g. `post` inside `{ ok post { … } }`), and
applies `select_related` for every to-one relation (`ForeignKey`,
`OneToOneField`) that appears in that sub-selection.

This eliminates N+1 queries on mutation responses that nest related objects:

```graphql
mutation CreatePost($input: NewPostInput!) {
  postCreate(newPost: $input) {
    ok
    post {
      title
      author { name }     # joined via select_related — no extra query
      category { title }  # joined via select_related — no extra query
    }
  }
}
```

No code changes are required; the optimization is applied automatically
whenever `DjangoModelType.perform_mutate` is called.  If the selection set
cannot be parsed (e.g. a custom `info` stub without field nodes), the method
falls back to the plain unoptimized re-read so existing behaviour is
preserved.
