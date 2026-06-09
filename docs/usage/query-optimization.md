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
- applies a conservative **`.only()`** column projection across the
  `select_related` span (see [caveats](#only-column-projection)).

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
- prefetched branches are not narrowed (they are separate querysets).

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
| `OPTIMIZE_ONLY_FIELDS` | `True` | Additionally narrow columns with `.only()` (conservative; see the warning above). |

```python
DJANGO_GRAPHEX = {
    "OPTIMIZE_QUERYSET": True,
    "OPTIMIZE_ONLY_FIELDS": True,
}
```

## Custom resolvers

If your query type defines `resolve_<field>` that returns a **`QuerySet`**, the
optimizer adopts it as the base queryset and still applies `select_related` /
`prefetch_related` on top of it. (`.only()` is skipped for custom-resolved
querysets, since they may already shape their own columns.) Resolvers that return
anything other than a `QuerySet` are left untouched.
