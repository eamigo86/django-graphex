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

#### `get_pagination_field(type)`

Get a pagination field for the given GraphQL type.

**Parameters:**
- `type` (`ObjectType`): GraphQL type to paginate

**Returns:** `GenericPaginationField` instance

#### `to_graphql_fields()`

Convert pagination parameters to GraphQL field arguments.

**Returns:** `dict` of GraphQL field arguments

#### `to_dict()`

Convert pagination configuration to dictionary.

**Returns:** `dict` of configuration parameters

#### `paginate_queryset(qs, **kwargs)`

Paginate the given queryset with the provided parameters.

**Parameters:**
- `qs` (`QuerySet`): Django queryset to paginate
- `**kwargs`: Pagination parameters from GraphQL query

**Returns:** Paginated `QuerySet`

---

## LimitOffsetGraphqlPagination

Pagination implementation using limit and offset parameters.

```python
class LimitOffsetGraphqlPagination(BaseDjangoGraphqlPagination)
```

### Constructor

```python
LimitOffsetGraphqlPagination(
    default_limit=20,
    max_limit=None,
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

**Returns:** Sliced `QuerySet`

### Example Usage

=== "Basic Configuration"

    ```python
    from django_graphex import LimitOffsetGraphqlPagination

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
    page_size=20,
    page_size_query_param=None,
    max_page_size=None,
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

### Example Usage

=== "Basic Configuration"

    ```python
    from django_graphex import PageGraphqlPagination

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

---

## CursorGraphqlPagination

Forward **keyset** (cursor) pagination over a single ordering field. An opaque
`cursor` encodes the ordering-field value of a boundary row, and `first` controls
the page size. The list type also gains a `pageInfo` field (see below) so the
client reads `endCursor` from the response instead of building it by hand.

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
| `ordering` | `str` | `"-created"` | Single keyset field; a leading `-` selects descending order |
| `cursor_query_param` | `str` | `"cursor"` | GraphQL argument name for the (after-)cursor |
| `first_query_param` | `str` | `"first"` | GraphQL argument name for the page size |
| `page_size` | `int` | `DEFAULT_PAGE_SIZE` | Fallback page size when `first` is not provided |
| `max_page_size` | `int` | `MAX_PAGE_SIZE` | Ceiling on `first`; clamps any larger request |

### GraphQL arguments

| Argument | Type | Description |
|----------|------|-------------|
| `first` | `Int` | Number of results to return per page |
| `cursor` | `String` | Opaque cursor; returns the rows that come after it |

### Methods

#### `encode_cursor(value)` / `decode_cursor(cursor)`

Static helpers that turn an ordering-field value into an opaque cursor token and
back. To page forward, take the ordering field of the last row in `results` and
build the next cursor with `encode_cursor`.

#### `paginate_queryset(qs, **kwargs)`

Orders the queryset by `ordering`, applies the `__gt` / `__lt` keyset filter from
the decoded cursor and returns the next `first` rows. Invalid cursors raise a
`ValueError` (surfaced as a GraphQL error).

### Example Usage

```python
from django_graphex import CursorGraphqlPagination

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
    (`last`/`before`) is intentionally out of scope.

---

## Pagination Utilities

### GenericPaginationField

Internal field class used by pagination implementations.

```python
class GenericPaginationField(Field)
```

This class is used internally by pagination classes and typically doesn't need to be used directly.

### Utility Functions

#### `_get_count(qs)`

Get the count of a queryset efficiently.

**Parameters:**
- `qs` (`QuerySet`): Django queryset

**Returns:** `int` - Count of objects

#### `_nonzero_int(value, strict=False, cutoff=None)`

Validate and convert value to non-zero integer.

**Parameters:**
- `value` (`Any`): Value to convert
- `strict` (`bool`): Whether to enforce strict validation
- `cutoff` (`int`): Maximum allowed value

**Returns:** `int` or `None`

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
class Query(graphene.ObjectType):
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
