# Nested Lists

Every related **list** field — a `ManyToManyField`, a reverse `ForeignKey`, a
reverse M2M, or a `GenericRelation` — is exposed with the **same shape** as a
root list: a `DjangoListObjectType` with `results` + `totalCount`, supporting
**filtering**, **pagination** and **ordering**. This also applies to nested lists
returned in **mutation responses**.

```graphql
{
  authors {
    results {
      name
      posts {                                  # reverse FK -> list type
        results(limit: 10, offset: 0, ordering: "-id") {
          title
        }
        totalCount
      }
    }
    totalCount
  }
}
```

As at the root, **pagination and ordering arguments live on `results`**, while
**filter arguments live on the nested field** itself:

```graphql
{
  authors {
    results {
      posts(filter: { title: { icontains: "graphql" } }) {   # filter on the field
        results(limit: 5, ordering: "title") { title }   # paginate/order on results
        totalCount
      }
    }
  }
}
```

## Worked example (2 models)

`Author (1) ─→ (N) Post`:

```python
# models.py
class Author(models.Model):
    name = models.CharField(max_length=100)

class Post(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, related_name="posts", on_delete=models.CASCADE)
```

```python
# schema.py
import graphene
from django_graphex import (
    DjangoListObjectField, DjangoListObjectType, DjangoObjectType,
    LimitOffsetGraphqlPagination,
)

class PostType(DjangoObjectType):
    class Meta:
        model = Post
        filter_fields = {"title": ["icontains"]}     # enables the nested filter

class AuthorType(DjangoObjectType):
    class Meta:
        model = Author

class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author
        pagination = LimitOffsetGraphqlPagination(default_limit=50)

class Query(graphene.ObjectType):
    authors = DjangoListObjectField(AuthorListType)
```

Nested list, **paginated + ordered + filtered** (`posts` was a plain `[Post]`
before; now it is a list type):

```graphql
{
  authors {
    results {
      name
      posts(filter: { title: { icontains: "Post 0" } }) {   # filter on the field
        results(limit: 2, ordering: "-id") {     # paginate/order on results
          title
        }
        totalCount
      }
    }
    totalCount
  }
}
```

```json
{
  "authors": {
    "results": [
      {
        "name": "Author 0",
        "posts": {
          "results": [{ "title": "Author 0 Post 3" }, { "title": "Author 0 Post 2" }],
          "totalCount": 4
        }
      }
    ],
    "totalCount": 5
  }
}
```

!!! success "N+1 eliminated — even with the nested filter"
    With **5 authors** (4 posts each), the query above runs **3 database queries
    total**, *independent of the number of authors*:

    1. `SELECT … FROM author …` (the paginated authors)
    2. `SELECT … FROM post WHERE title ILIKE '%Post 0%' AND author_id IN (…)`
       — **one filtered `Prefetch`** for every author's posts
    3. `SELECT COUNT(*) … FROM author` (the root `totalCount`)

    Without the optimizer the nested `posts` would run **one query per author**
    (N+1). The filter is pushed into a single `Prefetch`, and `limit` / `offset` /
    `ordering` are applied in memory over that cache — so adding authors never adds
    queries. See [Query Optimization](query-optimization.md).

!!! note "Deeper lists under a filtered nested list"

    A nested list **under** a filtered one (e.g. a filtered `posts` whose own
    `comments` are also selected) is prefetched **through** the filtered parent's
    queryset, so it stays N+1-safe and never raises
    `'X' lookup was already seen with a different queryset`.

## Which list type / paginator is used

The nested field reuses the related model's **registered** `DjangoListObjectType`
when there is one — so its `pagination` and `filter_fields` are honored even when
the model appears nested under a different model:

```python
from django.contrib.auth.models import User

class UserListType(DjangoModelType):
    class Meta:
        model = User
        pagination = PageGraphqlPagination(page_size=25)   # User's list paginator
        filter_fields = {"username": ("exact", "icontains"), "is_active": ("exact",)}


class GroupType(DjangoObjectType):
    class Meta:
        model = Group
# Group.users (M2M -> User) nested list reuses UserListType: it paginates with
# PageGraphqlPagination and filters with the declared filter_fields.
```

When a model has **no** registered list type, one is **auto-generated** using the
default paginator (`DJANGO_GRAPHEX["DEFAULT_PAGINATION_CLASS"]`, or
`LimitOffsetGraphqlPagination` when unset) and the node type's `filter_fields`.

## Performance (N+1)

Nested lists are designed to keep the [query optimizer](query-optimization.md)'s
N+1 elimination intact — **even when filtered**:

- An **unfiltered** nested list is read from the parent query's
  `prefetch_related` cache and **paginated/ordered in memory** — so a list of *P*
  parents costs **one** prefetch query for the whole level (not one per parent).
- A **filtered** nested list is fetched with a single **filtered `Prefetch`**
  (`Prefetch(lookup, queryset=<filtered queryset>)`) for **all** parents — also
  **one** query for the whole level, with pagination/ordering applied in memory
  over that cache. `totalCount` is the filtered set size.

So a query like `authors { results { posts(filter: { title: { icontains: "x" } }) { results(limit: 5) { … } totalCount } } }`
runs a **constant** number of queries regardless of how many authors are
returned.

!!! note "Fallback"
    The per-parent database query is used only when the relation was **not**
    prefetched — e.g. with `DJANGO_GRAPHEX["OPTIMIZE_QUERYSET"] = False`.
    Pagination of a filtered nested list still loads its filtered set into memory
    (no per-parent SQL `LIMIT`); for very large filtered sets that is the
    trade-off of the in-memory approach.

!!! note "Always-on, uniform shape"
    This shape is applied to **all** related list fields (and mutation outputs);
    there is no flag. Clients read nested lists exactly like root lists:
    `field { results { … } totalCount }`.

## Per-field optimize hook

For cases where you need to customize the child queryset for a specific nested
list field — for example to add a `select_related`, a custom annotation, or a
default ordering — declare an **`optimize_<snake_field>`** static method on the
**parent** graphene type:

```python
class AuthorType(DjangoObjectType):
    class Meta:
        model = Author

    # Customize the queryset used to prefetch Author.posts.
    # Called once per query — NOT once per parent row.
    @staticmethod
    def optimize_posts(queryset, info, **kwargs):
        """Add select_related and a default ordering to the posts prefetch."""
        filter_value = kwargs.get("filter_value")   # filter input or None
        is_window = kwargs.get("is_window", False)  # True when DB-side windowed

        # Compose freely on top of the optimizer-built queryset.
        return queryset.select_related("category").order_by("-views", "id")
```

**Rules**

- The method name is `optimize_` + the **snake_case** form of the **GraphQL field
  name** (e.g. `blogPosts` → `optimize_blog_posts`).
- It is declared on the **parent** type (the type that owns the nested field),
  **not** on the child type.
- It MUST return a `QuerySet`.  Returning anything else emits a WARNING and the
  optimizer-built queryset is used unchanged.
- Keyword arguments passed to the hook:
  - `filter_value` — the filter input for this field, or `None`.
  - `is_window` — `True` when the DB-side window-slice path is taken (i.e.
    `OPTIMIZE_NESTED_PAGINATION=True` and the field is windowed); `False` on all
    plain prefetch paths, including the fallback after a window opt-out.
- When **no** `optimize_<field>` method is declared the optimizer behaves
  byte-identically to the pre-hook baseline — purely additive, zero overhead.

**Safe-mode interaction**

If `OPTIMIZER_SAFE_MODE=True` (default `False`) and the hook raises an
exception, the **entire resolve** degrades to the un-optimized base queryset
(same boundary as all other optimizer errors) and a WARNING is logged.  With the
default `False` setting the exception propagates normally.

**What NOT to use it for**

- Root queryset customization — use `resolve_<field>` on the root type instead.
- Hooks on `DjangoFilterListField` or `DjangoFilterPaginateListField` — not
  supported; only `DjangoNestedListObjectField` has this hook.
- Per-field `SAFE_MODE` isolation — field-level try/except is a separate,
  currently unspecified feature.

**Full example**

```python
from django.db.models import Prefetch
from django_graphex import DjangoObjectType, DjangoListObjectType, DjangoListObjectField
from django_graphex.fields import DjangoNestedListObjectField

class PostListType(DjangoListObjectType):
    class Meta:
        model = Post
        pagination = LimitOffsetGraphqlPagination(default_limit=10)

class AuthorType(DjangoObjectType):
    posts = DjangoNestedListObjectField(PostListType, accessor="posts")

    class Meta:
        model = Author

    @staticmethod
    def optimize_posts(queryset, info, **kwargs):
        # Add select_related so Post.category is fetched in the same query.
        return queryset.select_related("category")

class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author

class Query(graphene.ObjectType):
    authors = DjangoListObjectField(AuthorListType)
```

With `optimize_posts` declared, a query requesting `posts { results { title category { name } } }` will
join the `category` table in the prefetch query instead of issuing one extra
query per post — **without** disabling the global N+1 optimizer.
