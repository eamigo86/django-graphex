# Query Optimization (N+1)

`django-graphex` inspects the **incoming GraphQL selection** and builds an
optimized Django queryset for the list resolvers, so nested relations do not
trigger the classic **N+1 query problem**. This happens automatically in
`DjangoListObjectField`, `DjangoFilterPaginateListField`, `DjangoFilterListField`
and `DjangoModelType.QueryFields()`, and for **single-object** lookups
(`DjangoObjectField` and `DjangoModelType` retrieve / `RetrieveField`) — all
routed through `django_graphex.utils.queryset_factory`.

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
| `OPTIMIZE_NESTED_PAGINATION` | `True` | DB-side `ROW_NUMBER()` window slicing for reverse-FK nested paginated lists (`LimitOffset`/`Page`). `False` = in-memory order+slice fallback. See [Nested Lists](nested-lists.md#performance-n1). |
| `OPTIMIZER_SAFE_MODE` | `False` | When `True`, any exception in the optimization block degrades to the un-optimized queryset and logs a `WARNING` (instead of a 500). Default fail-loud. |
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

See [Fields → AnnotatedField](fields.md#annotatedfield).

## Custom resolvers

If your query type defines `resolve_<field>` that returns a **`QuerySet`**, the
optimizer adopts it as the base queryset and still applies `select_related` /
`prefetch_related` on top of it. (`.only()` is skipped for custom-resolved
querysets, since they may already shape their own columns.) Resolvers that return
anything other than a `QuerySet` are left untouched.
