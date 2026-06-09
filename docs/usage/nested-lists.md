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
