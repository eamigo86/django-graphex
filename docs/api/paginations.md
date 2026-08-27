# Paginations API Reference

This section provides detailed API documentation for pagination classes in `django-graphex`.

## BaseDjangoGraphqlPagination

Abstract base class for all Django GraphQL pagination implementations.

```python
class BaseDjangoGraphqlPagination(object)
```

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `__name__` | `str` | Pagination class identifier |

### Abstract Methods

These methods must be implemented by subclasses:

#### `to_graphql_fields(*, native=True)`

Convert pagination parameters to graphql-core field arguments — the arguments
the paginator adds to the `results(...)` subfield.

**Parameters:**
- `native` (`bool`): accepted for signature compatibility and ignored; the
  build path is native-only

**Returns:** `dict` of `graphql.GraphQLArgument`

#### `to_dict()`

Convert pagination configuration to dictionary.

**Returns:** `dict` of configuration parameters

#### `paginate_queryset(qs, **kwargs)`

Paginate the given queryset with the provided parameters.

**Parameters:**
- `qs` (`QuerySet`): Django queryset to paginate
- `**kwargs`: Pagination parameters from GraphQL query

**Returns:** Paginated `QuerySet`

### Optional Hooks

These have a working base implementation; override only when the paginator
exposes page metadata.

#### `get_native_page_info_field(node_type)`

Return the native (graphql-core) `pageInfo` field this paginator exposes
alongside `results`, or `None` when it exposes no metadata. The base
implementation returns `None`; `CursorGraphqlPagination` overrides it to expose
its `CursorPageInfo` field. The list-type compiler calls this hook while
building the list container, so a custom paginator adds its own `pageInfo`
purely by overriding it.

**Parameters:**
- `node_type` (`GraphQLObjectType`): the compiled element (node) type the list
  paginates

**Returns:** `graphql.GraphQLField`, or `None`

#### `get_page_info_field(type)`

Legacy sibling of the hook above, kept for signature compatibility. It always
returns `None` on the native build path — override
`get_native_page_info_field` instead.

**Parameters:**
- `type` (`ObjectType`): the GraphQL list type the field belongs to

**Returns:** `None`

---

## LimitOffsetGraphqlPagination

Pagination implementation using limit and offset parameters.

```python
class LimitOffsetGraphqlPagination(BaseDjangoGraphqlPagination)
```

### Constructor

```python
LimitOffsetGraphqlPagination(
    default_limit=None,   # from DJANGO_GRAPHEX["DEFAULT_PAGE_SIZE"]
    max_limit=None,       # from DJANGO_GRAPHEX["MAX_PAGE_SIZE"]
    ordering="",
    limit_query_param="limit",
    offset_query_param="offset",
    ordering_param="ordering"
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `default_limit` | `int` | `DEFAULT_PAGE_SIZE` | Default number of items per page |
| `max_limit` | `int` | `MAX_PAGE_SIZE` | Maximum allowable limit |
| `ordering` | `str` | `""` | Default ordering field(s) |
| `limit_query_param` | `str` | `"limit"` | GraphQL argument name for limit |
| `offset_query_param` | `str` | `"offset"` | GraphQL argument name for offset |
| `ordering_param` | `str` | `"ordering"` | GraphQL argument name for ordering |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `__name__` | `str` | `"LimitOffsetPaginator"` |
| `default_limit` | `int` | Default items per page |
| `max_limit` | `int` | Maximum allowed limit |
| `ordering` | `str` | Default ordering value |
| `limit_query_param` | `str` | Limit parameter name |
| `offset_query_param` | `str` | Offset parameter name |
| `ordering_param` | `str` | Ordering parameter name |

### Methods

#### `to_dict()`

Convert limit/offset pagination configuration to dictionary.

**Returns:**
```python
{
    "limit_query_param": str,
    "default_limit": int,
    "max_limit": int,
    "offset_query_param": str,
    "ordering_param": str,
    "ordering": str,
}
```

#### `to_graphql_fields()`

Convert limit/offset parameters to GraphQL field arguments.

**Returns:**
```python
{
    "limit": Int(default_value=default_limit),
    "offset": Int(),
    "ordering": String(),
}
```

#### `paginate_queryset(qs, **kwargs)`

Paginate queryset using limit and offset parameters.

**Parameters:**
- `qs` (`QuerySet`): Django queryset to paginate
- `**kwargs`: Query parameters including `limit`, `offset`, and `ordering`

**Returns:** Sliced `QuerySet`. When neither `default_limit` nor `max_limit` is
configured the paginator is unbounded and returns the whole set — still
**ordered** by `ordering`, which is applied and validated independently of the
page-size resolution.

**Raises:**
- `GraphQLError` — negative `offset` (`"Invalid offset: {offset}. Offset must be a non-negative integer."`).
- `GraphQLError` — zero or negative `limit` (`"Invalid limit: {limit}. Limit must be a positive integer."`).
  A `limit` above `max_limit` is not an error — it is silently clamped (see
  [Configuration Examples](#the-maximum-is-an-effective-ceiling)).

### Example Usage

=== "Basic Configuration"

    ```python
    from django_graphex.paginations import LimitOffsetGraphqlPagination

    pagination = LimitOffsetGraphqlPagination(
        default_limit=20,
        max_limit=100,
        ordering="-created_at"
    )
    ```

=== "Custom Parameters"

    ```python
    pagination = LimitOffsetGraphqlPagination(
        default_limit=50,
        max_limit=200,
        ordering="name",
        limit_query_param="size",
        offset_query_param="start"
    )
    ```

=== "With DjangoListObjectType"

    ```python
    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            pagination = LimitOffsetGraphqlPagination(
                default_limit=10,
                max_limit=50,
                ordering="-published_at"
            )
    ```

### GraphQL Query

When used through a `DjangoListObjectType`/`DjangoListObjectField`, pagination and
ordering arguments are placed on the `results(...)` subfield, and the count field
is `totalCount`:

```graphql
query GetPosts($limit: Int, $offset: Int, $ordering: String) {
  posts {
    results(limit: $limit, offset: $offset, ordering: $ordering) {
      id
      title
      createdAt
    }
    totalCount
  }
}
```

### Variables

```json
{
  "limit": 10,
  "offset": 20,
  "ordering": "title,-created_at"
}
```

---

## PageGraphqlPagination

Pagination implementation using page number and page size parameters.

```python
class PageGraphqlPagination(BaseDjangoGraphqlPagination)
```

### Constructor

```python
PageGraphqlPagination(
    page_size=None,            # from DJANGO_GRAPHEX["DEFAULT_PAGE_SIZE"]
    page_size_query_param=None,
    max_page_size=None,        # from DJANGO_GRAPHEX["MAX_PAGE_SIZE"]
    ordering="",
    ordering_param="ordering"
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page_size` | `int` | `DEFAULT_PAGE_SIZE` | Items per page |
| `page_size_query_param` | `str` | `None` | Enable client-controlled page size |
| `max_page_size` | `int` | `MAX_PAGE_SIZE` | Maximum page size limit |
| `ordering` | `str` | `""` | Default ordering field(s) |
| `ordering_param` | `str` | `"ordering"` | GraphQL argument name for ordering |

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `__name__` | `str` | `"PagePaginator"` |
| `page_query_param` | `str` | `"page"` (fixed) |
| `page_size` | `int` | Default page size |
| `page_size_query_param` | `str` | Page size parameter name |
| `max_page_size` | `int` | Maximum allowed page size |
| `ordering` | `str` | Default ordering value |
| `ordering_param` | `str` | Ordering parameter name |

### Methods

#### `to_dict()`

Convert page pagination configuration to dictionary.

**Returns:**
```python
{
    "page_size_query_param": str,
    "page_size": int,
    "page_query_param": str,
    "max_page_size": int,
    "ordering_param": str,
    "ordering": str,
}
```

#### `to_graphql_fields()`

Convert page pagination parameters to GraphQL field arguments.

**Returns:**
```python
{
    "page": Int(default_value=1),
    "ordering": String(),
    # Optional: "pageSize": Int() if page_size_query_param is set
}
```

#### `paginate_queryset(qs, **kwargs)`

Paginate queryset using page number and page size parameters.

**Parameters:**
- `qs` (`QuerySet`): Django queryset to paginate
- `**kwargs`: Query parameters including `page`, `pageSize` (optional), and `ordering`

**Returns:** Paginated `QuerySet`

**Raises:**
- `GraphQLError("Page value for PageGraphqlPagination must be a non-zero value")` — `page=0`.
- `GraphQLError` — zero or negative `pageSize` (`"Invalid page size: {value}. Page size must be a positive integer."`).
  A `pageSize` above `max_page_size` is silently clamped, not an error.

### Example Usage

=== "Basic Configuration"

    ```python
    from django_graphex.paginations import PageGraphqlPagination

    pagination = PageGraphqlPagination(
        page_size=25,
        ordering="-created_at"
    )
    ```

=== "With Dynamic Page Size"

    ```python
    pagination = PageGraphqlPagination(
        page_size=20,
        page_size_query_param="pageSize",
        max_page_size=100,
        ordering="title"
    )
    ```

=== "With DjangoListObjectType"

    ```python
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            pagination = PageGraphqlPagination(
                page_size=30,
                page_size_query_param="size",
                max_page_size=100
            )
    ```

### GraphQL Query

=== "Fixed Page Size"

    ```graphql
    query GetUsers($page: Int, $ordering: String) {
      users {
        results(page: $page, ordering: $ordering) {
          id
          username
          email
        }
        totalCount
      }
    }
    ```

=== "Dynamic Page Size"

    ```graphql
    query GetUsers($page: Int, $pageSize: Int, $ordering: String) {
      users {
        results(page: $page, pageSize: $pageSize, ordering: $ordering) {
          id
          username
          email
        }
        totalCount
      }
    }
    ```

### Variables

```json
{
  "page": 2,
  "pageSize": 15,
  "ordering": "username"
}
```

### Backward Pagination

A negative `page` navigates from the end of the list in true list order:

| `page` | Rows returned |
|---|---|
| `-1` | The **last** `page_size` rows (equivalent to Python's `list[-page_size:]`) |
| `-2` | The `page_size`-row window immediately before the last page |
| Large negative (overshoot past the start) | Clamps to the **first** `page_size` rows |
| `0` | `GraphQLError` — invalid for both forward and backward navigation |

```graphql
{ users { results(page: -1) { id } } }  # last page_size rows, natural order
```

Cost: a negative `page` issues one `COUNT` query (needed to compute
`offset = total + page_size * page`) and opts out of the window-prefetch
optimization, since that optimization requires the offset up front. Positive
pages never issue a `COUNT` — see [COUNT Query Behaviour](../usage/pagination.md#count-query-behaviour).

`LimitOffsetGraphqlPagination` has no backward mode (a negative `offset`
raises `GraphQLError`) and `CursorGraphqlPagination` is forward-only; inverting
its `ordering` returns the same rows reversed, not a windowed "last page".

---

## CursorGraphqlPagination

Forward **keyset** (cursor) pagination over a single ordering field. An opaque
`cursor` encodes a **composite** boundary — the ordering-field value AND the
primary key of the boundary row, with the pk used as an `ORDER BY` tiebreak so
rows sharing the same ordering value are never skipped or duplicated across
pages. `first` controls the page size. The list type also gains a `pageInfo`
field (see below) so the client reads `endCursor` from the response instead of
building it by hand.

!!! warning "Cursors are opaque — never construct one client-side"

    Treat a cursor as an implementation detail returned by the server. A
    tampered or malformed cursor (corrupted base64, wrong internal prefix, or a
    value that cannot be coerced to the ordering field's type) is caught
    internally and raised as `GraphQLError("Invalid cursor")` rather than
    propagating a raw `ValueError` or Django `ValidationError`.

```python
class CursorGraphqlPagination(BaseDjangoGraphqlPagination)
```

### Constructor

```python
CursorGraphqlPagination(
    ordering="-created",
    cursor_query_param="cursor",
    first_query_param="first",
    page_size=None,       # defaults to DJANGO_GRAPHEX["DEFAULT_PAGE_SIZE"]
    max_page_size=None,   # defaults to DJANGO_GRAPHEX["MAX_PAGE_SIZE"]
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ordering` | `str` | `"-created"` | Single keyset field; a leading `-` selects descending order. `""` falls back to `"id"`; a comma-separated value silently uses only its **first** term |
| `cursor_query_param` | `str` | `"cursor"` | GraphQL argument name for the (after-)cursor |
| `first_query_param` | `str` | `"first"` | GraphQL argument name for the page size |
| `page_size` | `int` | `DEFAULT_PAGE_SIZE` | Fallback page size when `first` is not provided |
| `max_page_size` | `int` | `MAX_PAGE_SIZE` | Ceiling on `first`; silently clamps any larger request |

!!! info "Page-size fallback chain — never unbounded"

    The effective page size resolves as `first` (client) → `page_size` →
    `max_page_size`, clamped at `max_page_size`. When all three are unset, the
    module constant `DEFAULT_CURSOR_PAGE_SIZE` (= `20`) applies — cursor
    pagination **never** returns an unbounded result set.

!!! note "No `ordering` argument"

    Unlike `LimitOffsetGraphqlPagination` and `PageGraphqlPagination`, cursor
    pagination adds **no client `ordering` argument** to the schema — the keyset
    field is configured server-side only, via the constructor.

### GraphQL arguments

| Argument | Type | Description |
|----------|------|-------------|
| `first` | `Int` | Number of results to return per page |
| `cursor` | `String` | Opaque cursor; returns the rows that come after it |

`first` and `cursor` are the forward keyset parameters: `first` controls the
page size, `cursor` carries the opaque boundary token. `first` can be renamed
per list via `CursorGraphqlPagination(first_query_param="limit")`, which
exposes `results(limit: Int, cursor: String)` instead.

### Methods

#### `encode_cursor(value, pk=None)` / `decode_cursor(cursor)`

Static helpers that turn an ordering-field value (and, for the composite form,
the boundary row's primary key) into an opaque cursor token and back.
`decode_cursor` returns only the ordering value; use `decode_cursor_parts` to
recover both the value and the pk. To page forward, take the ordering field
and pk of the last row in `results` and build the next cursor with
`encode_cursor`.

#### `paginate_queryset(qs, **kwargs)`

Orders the queryset by `ordering` with the primary key appended as a
deterministic tiebreak, applies the compound `(field, pk) > (value, pk)` /
`(field, pk) < (value, pk)` keyset filter from the decoded cursor, and returns
the next `first` rows. Invalid or tampered cursors (malformed base64, bad
prefix, or type-coercion failure) are caught internally and raised as a
`GraphQLError("Invalid cursor")` — the raw exception never propagates.

**Raises:**
- `GraphQLError("Invalid cursor")` — malformed/tampered `cursor`.
- `GraphQLError` — zero or negative `first` (`"Invalid first: {value}. First must be a positive integer."`).
  A `first` above `max_page_size` is silently clamped, not an error.

### Example Usage

```python
from django_graphex.paginations import CursorGraphqlPagination

class EventListType(DjangoListObjectType):
    class Meta:
        model = Event
        pagination = CursorGraphqlPagination(ordering="-id")
```

```graphql
query {
  events {
    results(first: 20, cursor: "Y3Vyc29yOjQy") { id name }
    totalCount
  }
}
```

### `pageInfo` (CursorPageInfo)

A cursor-paginated `DjangoListObjectType` exposes a `pageInfo` field — this is
**opt-in**: `LimitOffsetGraphqlPagination` and `PageGraphqlPagination` types do
not get one. `pageInfo` carries the **same arguments** as `results` (`first`,
`cursor`), so pass them the same values (with variables they are written once).

```graphql
type CursorPageInfo {
  hasNextPage: Boolean!       # a row exists after the last row of the page
  hasPreviousPage: Boolean!   # a row exists before the first row of the page (exact)
  startCursor: String         # cursor of the first row (null if the page is empty)
  endCursor: String           # cursor of the last row (null if the page is empty)
}
```

Forward paging driven by `endCursor` (no manual cursor construction):

```graphql
query Events($first: Int!, $cursor: String) {
  events {
    results(first: $first, cursor: $cursor) { id name }
    totalCount
    pageInfo(first: $first, cursor: $cursor) {
      endCursor
      hasNextPage
      hasPreviousPage
    }
  }
}
```

- First page: `{ "first": 20 }` (omit `cursor`). Read `pageInfo.endCursor`.
- Next page: `{ "first": 20, "cursor": <previous endCursor> }`.
- Stop when `pageInfo.hasNextPage` is `false`.

!!! note "Same arguments on `results` and `pageInfo`"
    Because the canonical design puts pagination arguments on the `results`
    subfield, `pageInfo` takes the same `first`/`cursor` arguments and must be
    given the same values so both describe the same page. Backward pagination
    (`last`/`before`) is intentionally out of scope: each page is a single
    compound `(field, pk)` boundary filter, and true backward/multi-field
    paging requires additional lexicographic `WHERE` chains. That work is
    **not scheduled** — `CursorGraphqlPagination` is `first` + `cursor` only,
    and `__init__` takes no `last` / `before` parameter. See the
    [design rationale](../usage/pagination.md#cursorgraphqlpagination).
    `PageGraphqlPagination` supports backward navigation
    today — see its
    [Backward pagination](../usage/pagination.md#backward-pagination) section.

---

## Pagination Utilities

### NativePaginationField

Internal field descriptor used by the list-type compiler, defined in
`django_graphex.paginations.utils` (not part of the public export surface).

```python
@dataclass
class NativePaginationField:
    type: Any            # the element (node) type the list paginates
    paginator: Any = None
```

A plain dataclass carrying `(type, paginator)`; its `wrap_resolve` wraps the
`results` resolver so the paginator slices the page. Built for you when a list
type declares `Meta.pagination` — it typically doesn't need to be used
directly.

---

## Configuration Examples

### Settings Integration

```python
# settings.py
DJANGO_GRAPHEX = {
    'DEFAULT_PAGE_SIZE': 25,
    'MAX_PAGE_SIZE': 100,
    'DEFAULT_PAGINATION_CLASS': 'django_graphex.paginations.LimitOffsetGraphqlPagination'
}
```

!!! tip "`MAX_PAGE_SIZE` also bounds query cost"

    `MAX_PAGE_SIZE` caps how many items a list can return, and
    [query cost analysis](../usage/query-limits.md#query-cost-analysis) reuses it as
    the per-list multiplier ceiling. Setting it makes cost estimates accurate and
    closes the `limit: $var` bypass — recommended when `MAX_QUERY_COST` is on.

#### The maximum is an effective ceiling

The per-paginator maximum (`max_limit` / `max_page_size`, defaulting to
`MAX_PAGE_SIZE`) is applied **even when the client omits the page-size argument**.
The effective page size is resolved as `requested → default → maximum`, then
clamped at the maximum:

| `default` | `max` | client sends | rows returned |
|---|---|---|---|
| – | – | – | **all** (unbounded — no pagination configured) |
| – | `100` | – | `100` (falls back to the max) |
| `25` | `100` | – | `25` |
| `25` | `100` | `500` | `100` (clamped) |

So a list can never exceed its maximum, even unpaginated. With **no** default and
**no** maximum (the out-of-the-box defaults), behavior is unchanged — the full
queryset is returned. Set `MAX_PAGE_SIZE` (or a per-type `max_limit` /
`max_page_size`) to bound it.

Clamping is **silent**: a request above the maximum does not raise an error —
the effective size is `min(requested, max)`, matching the convention of Django
REST Framework's paginators.

### Custom Pagination Classes

=== "Custom Limit/Offset"

    ```python
    from django_graphex.paginations import LimitOffsetGraphqlPagination

    class CustomPagination(LimitOffsetGraphqlPagination):
        def __init__(self, **kwargs):
            super().__init__(
                default_limit=50,
                max_limit=200,
                ordering="-updated_at",
                **kwargs
            )

    class PostListType(DjangoListObjectType):
        class Meta:
            model = Post
            pagination = CustomPagination()
    ```

=== "Custom Page Pagination"

    ```python
    from django_graphex.paginations import PageGraphqlPagination

    class LargeDatasetPagination(PageGraphqlPagination):
        def __init__(self, **kwargs):
            super().__init__(
                page_size=100,
                page_size_query_param=None,  # Fixed size
                max_page_size=100,
                ordering="-id",
                **kwargs
            )
    ```

### Multiple Pagination Strategies

```python
from django_graphex.core import ObjectType

class Query(ObjectType):
    # Limit/Offset pagination
    posts_limit_offset = DjangoFilterPaginateListField(
        PostType,
        pagination=LimitOffsetGraphqlPagination(default_limit=20)
    )

    # Page-based pagination
    posts_page = DjangoFilterPaginateListField(
        PostType,
        pagination=PageGraphqlPagination(page_size=15)
    )
```

## Performance Considerations

### Database Query Optimization

```python
class OptimizedPagination(LimitOffsetGraphqlPagination):
    def paginate_queryset(self, qs, **kwargs):
        # Add select_related for better performance
        if hasattr(qs.model, 'author'):
            qs = qs.select_related('author')

        return super().paginate_queryset(qs, **kwargs)
```

### Count Query Optimization

For large datasets, consider caching count queries:

```python
from django.core.cache import cache

class CachedCountPagination(LimitOffsetGraphqlPagination):
    def paginate_queryset(self, qs, **kwargs):
        # Cache count queries for better performance
        cache_key = f"count_{qs.model._meta.label_lower}"
        count = cache.get(cache_key)

        if count is None:
            count = qs.count()
            cache.set(cache_key, count, 300)  # 5 minutes

        return super().paginate_queryset(qs, **kwargs)
```

## Error Handling

### Invalid Page Values

```python
class SafePagePagination(PageGraphqlPagination):
    def paginate_queryset(self, qs, **kwargs):
        try:
            return super().paginate_queryset(qs, **kwargs)
        except ValueError as e:
            # Handle invalid page numbers gracefully
            kwargs['page'] = 1
            return super().paginate_queryset(qs, **kwargs)
```

### Limit Enforcement

```python
class StrictLimitPagination(LimitOffsetGraphqlPagination):
    def paginate_queryset(self, qs, **kwargs):
        limit = kwargs.get(self.limit_query_param)
        if limit and limit > self.max_limit:
            raise ValueError(f"Limit cannot exceed {self.max_limit}")

        return super().paginate_queryset(qs, **kwargs)
```

## Best Practices

!!! tip "Pagination Best Practices"

    1. **Set Reasonable Defaults**: Use sensible default page sizes (10-50 items)
    2. **Enforce Maximum Limits**: Prevent abuse with max_limit settings
    3. **Use Indexed Ordering**: Order by indexed fields for better performance
    4. **Cache Counts**: Cache total counts for frequently accessed data
    5. **Handle Edge Cases**: Gracefully handle invalid page numbers and limits
    6. **Consider Data Size**: Use appropriate pagination strategy for your data volume
    7. **Test Performance**: Monitor query performance with large datasets

### Security Considerations

```python
class SecurePagination(LimitOffsetGraphqlPagination):
    def __init__(self, **kwargs):
        # Enforce security limits
        super().__init__(
            max_limit=100,  # Prevent excessive requests
            default_limit=20,
            **kwargs
        )
```

### Frontend Integration

```javascript
// React example for limit/offset pagination
const [pagination, setPagination] = useState({
  limit: 10,
  offset: 0
});

const { data } = useQuery(GET_POSTS, {
  variables: pagination
});

const nextPage = () => setPagination(prev => ({
  ...prev,
  offset: prev.offset + prev.limit
}));
```

This comprehensive API reference covers all pagination classes and utilities in `django-graphex`, providing developers with the tools needed to implement efficient, scalable pagination for their GraphQL APIs.
