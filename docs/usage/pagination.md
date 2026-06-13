# Pagination

Pagination is essential for managing large datasets in GraphQL APIs. `django-graphex` provides several pagination strategies to efficiently handle query results and improve performance.

## Pagination Types

`django-graphex` offers three pagination implementations:

- :material-format-list-numbered: **LimitOffsetGraphqlPagination**: Traditional limit/offset pagination
- :material-book-open-page-variant: **PageGraphqlPagination**: Page-number based pagination
- :material-cursor-default: **CursorGraphqlPagination**: Forward keyset (cursor) pagination with `pageInfo`

## LimitOffsetGraphqlPagination

The most common pagination method, using `limit` and `offset` parameters to control result sets.

### Features

- :material-speedometer: **Simple & Fast**: Easy to understand and implement
- :material-sort: **Flexible Ordering**: Supports custom ordering with Django syntax
- :material-tune: **Configurable Limits**: Set default and maximum page sizes
- :material-database: **Database Efficient**: Works well with Django QuerySets

### Basic Usage

=== "Define Pagination"

    ```python
    from django_graphex.paginations import LimitOffsetGraphqlPagination

    # Basic configuration
    pagination = LimitOffsetGraphqlPagination(
        default_limit=25,    # Default number of items per page
        max_limit=100,       # Maximum allowed limit
        ordering="-id"       # Default ordering
    )
    ```

=== "Use with DjangoListObjectType"

    ```python
    from django_graphex import DjangoListObjectType
    from .models import User

    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            pagination = LimitOffsetGraphqlPagination(
                default_limit=25,
                max_limit=100,
                ordering="-date_joined"
            )
    ```

=== "Use with Fields"

    ```python
    from django_graphex import DjangoFilterPaginateListField
    from .types import UserType

    class Query(graphene.ObjectType):
        users = DjangoFilterPaginateListField(
            UserType,
            pagination=LimitOffsetGraphqlPagination(default_limit=10)
        )
    ```

### Configuration Options

```python
LimitOffsetGraphqlPagination(
    default_limit=20,                    # Default items per page
    max_limit=100,                      # Maximum allowed limit
    ordering="-created_at",             # Default ordering field(s)
    limit_query_param="limit",          # GraphQL argument name for limit
    offset_query_param="offset",        # GraphQL argument name for offset
    ordering_param="ordering"           # GraphQL argument name for ordering
)
```

### Query Examples

!!! note "Argument placement"
    Pagination and ordering arguments (`limit`, `offset`, `ordering`) live on the
    `results` subfield. Filter arguments live on the list field. `totalCount` is a
    sibling of `results`.

=== "Basic Query"

    ```graphql
    query GetUsers {
      users {
        results {
          id
          username
          email
        }
        totalCount
      }
    }
    ```

=== "With Pagination"

    ```graphql
    query GetUsersWithPagination {
      users {
        results(limit: 10, offset: 20) {
          id
          username
          email
        }
        totalCount
      }
    }
    ```

=== "With Ordering"

    ```graphql
    query GetUsersOrdered {
      users {
        results(limit: 10, ordering: "username,-date_joined") {
          id
          username
          email
          dateJoined
        }
        totalCount
      }
    }
    ```

### Ordering Validation (Security)

!!! warning "Ordering is validated against concrete model fields"

    Both `LimitOffsetGraphqlPagination` and `PageGraphqlPagination` validate every
    client-supplied `ordering` term **before** calling `qs.order_by()`.

    **Why this matters:**

    - An invalid field name would cause Django to raise `FieldError`, which leaks
      the full model field list (including sensitive columns like `password`,
      `is_superuser`) in `errors[].message` — a CWE-209 information disclosure.
    - Relation-spanning lookups (`posts__title`, `author__name`) force Django to
      follow join chains, which can exhaust database resources (DoS).

    **Allowlist rule:** each ordering term's root (the part before `__`) must match
    one of the model's **concrete attnames** (`model._meta.concrete_fields`).
    Leading `-`/`+` direction prefixes are stripped before comparison.

    **Rejected examples:**

    ```graphql
    # Non-existent field → GraphQLError: "Invalid ordering field: 'nonexistent'"
    { users { results(ordering: "nonexistent") { id } } }

    # Relation-spanning → GraphQLError: "Invalid ordering field: ..."
    { users { results(ordering: "posts__title") { id } } }
    ```

    **Accepted examples (concrete attnames of the model):**

    ```graphql
    # Single ascending
    { users { results(ordering: "username") { id } } }

    # Descending
    { users { results(ordering: "-date_joined") { id } } }

    # Multi-field comma list
    { users { results(ordering: "last_name,-date_joined") { id } } }
    ```

    If you need to allow ordering by additional (non-default) fields, ensure those
    columns are concrete attnames on the model. You cannot order by reverse-FK names
    (e.g. `posts`) or by relation paths (`posts__title`) — use a database index and
    annotate the queryset instead if you need computed sort keys.

### Response Structure

```json
{
  "data": {
    "users": {
      "totalCount": 150,
      "results": [
        {
          "id": "1",
          "username": "john_doe",
          "email": "john@example.com"
        },
        {
          "id": "2",
          "username": "jane_smith",
          "email": "jane@example.com"
        }
      ]
    }
  }
}
```

## PageGraphqlPagination

Page-number based pagination, similar to Django's built-in pagination.

### Features

- :material-book-multiple: **Page-Based**: Navigate by page numbers
- :material-resize: **Dynamic Page Size**: Optional client-controlled page sizes
- :material-calculator: **Automatic Calculation**: Handles page calculations automatically
- :material-navigation: **User Friendly**: Intuitive for frontend pagination controls

### Basic Usage

=== "Define Pagination"

    ```python
    from django_graphex.paginations import PageGraphqlPagination

    pagination = PageGraphqlPagination(
        page_size=25,                    # Items per page
        page_size_query_param="pageSize", # Allow client to control page size
        max_page_size=100,               # Maximum page size
        ordering="-created_at"           # Default ordering
    )
    ```

=== "Use with Types"

    ```python
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            pagination = PageGraphqlPagination(
                page_size=20,
                page_size_query_param="pageSize",
                max_page_size=100
            )
    ```

### Configuration Options

```python
PageGraphqlPagination(
    page_size=25,                       # Default page size
    page_size_query_param="pageSize",   # Enable dynamic page sizing
    max_page_size=100,                  # Maximum allowed page size
    ordering="-id",                     # Default ordering
    ordering_param="ordering"           # Ordering parameter name
)
```

!!! tip "`page_size_query_param` semantics"

    - **Non-`None` string** (e.g. `"pageSize"`) — adds a `pageSize` argument to
      the `results(...)` subfield. Clients can request any size up to
      `max_page_size`; values above the cap are silently clamped to `max_page_size`.
    - **`None`** (the default) — page size is **fixed** at `page_size`; clients
      cannot change it. The `pageSize` argument is not added to the schema.

    This is **asymmetric** with `LimitOffsetGraphqlPagination.limit_query_param`,
    which is always `"limit"` and is always present in the schema — it cannot be
    disabled by setting it to `None`.

### Query Examples

=== "Basic Page Query"

    ```graphql
    query GetUsersPage {
      users {
        results(page: 1) {
          id
          username
          email
        }
        totalCount
      }
    }
    ```

=== "With Dynamic Page Size"

    ```graphql
    query GetUsersWithPageSize {
      users {
        results(page: 2, pageSize: 15) {
          id
          username
          email
        }
        totalCount
      }
    }
    ```

=== "Navigation Example"

    ```graphql
    query GetUsersForPagination {
      users {
        results(page: 3, pageSize: 20, ordering: "username") {
          id
          username
          email
          dateJoined
        }
        totalCount
        # Calculate pagination info on frontend:
        # totalPages = Math.ceil(totalCount / pageSize)
        # hasNextPage = page < totalPages
        # hasPreviousPage = page > 1
      }
    }
    ```

## CursorGraphqlPagination

Forward **keyset** (cursor) pagination over a single ordering field. Instead of
an `offset` (which gets slow on large tables and skips/repeats rows when data
changes), each page is fetched relative to the ordering value of the previous
page's last row — so it stays fast and stable. The list type also exposes a
`pageInfo` field, so the client just echoes `endCursor` to get the next page.

### Features

- :material-flash: Constant-time paging regardless of how deep you are (no large `OFFSET`).
- :material-shield-check: Stable under inserts/deletes between pages.
- :material-information: `pageInfo` with `endCursor` / `hasNextPage` / `hasPreviousPage` / `startCursor`.

### Basic Usage

```python
import graphene
from django_graphex import (
    DjangoListObjectType,
    DjangoListObjectField,
    CursorGraphqlPagination,
)
from .models import Event


class EventListType(DjangoListObjectType):
    class Meta:
        model = Event
        description = "Event list with cursor pagination"
        pagination = CursorGraphqlPagination(ordering="id")  # use "-id" for newest-first


class Query(graphene.ObjectType):
    events = DjangoListObjectField(EventListType)
```

### Query Examples

Paginate forward with variables — write `first`/`cursor` once and pass them to
both `results` and `pageInfo`:

```graphql
query Events($first: Int!, $cursor: String) {
  events {
    results(first: $first, cursor: $cursor) {
      id
      name
    }
    totalCount
    pageInfo(first: $first, cursor: $cursor) {
      startCursor
      endCursor
      hasNextPage
      hasPreviousPage
    }
  }
}
```

=== "Page 1"

    ```json
    { "first": 3 }
    ```

    ```json
    {
      "data": {
        "events": {
          "results": [
            { "id": "1", "name": "Item 00" },
            { "id": "2", "name": "Item 01" },
            { "id": "3", "name": "Item 02" }
          ],
          "totalCount": 12,
          "pageInfo": {
            "startCursor": "Y3Vyc29yOjE=",
            "endCursor": "Y3Vyc29yOjM=",
            "hasNextPage": true,
            "hasPreviousPage": false
          }
        }
      }
    }
    ```

=== "Page 2 (echo endCursor)"

    ```json
    { "first": 3, "cursor": "Y3Vyc29yOjM=" }
    ```

    ```json
    {
      "data": {
        "events": {
          "results": [
            { "id": "4", "name": "Item 03" },
            { "id": "5", "name": "Item 04" },
            { "id": "6", "name": "Item 05" }
          ],
          "pageInfo": {
            "startCursor": "Y3Vyc29yOjQ=",
            "endCursor": "Y3Vyc29yOjY=",
            "hasNextPage": true,
            "hasPreviousPage": true
          }
        }
      }
    }
    ```

!!! tip "How to navigate"
    - **Next page:** send the previous `pageInfo.endCursor` as `cursor`.
    - **Stop:** when `pageInfo.hasNextPage` is `false`.
    - `hasPreviousPage` is exact (there really is a row before the current page),
      so it is `false` on the first page even if a stray cursor is supplied.

!!! note "Scope"
    Cursor pagination is **forward-only** (`first` + `cursor`); backward
    pagination (`last`/`before`) is intentionally not provided. `ordering` must be
    a single field (a leading `-` selects descending order) — order by a stable,
    indexed field such as the primary key.

## Advanced Pagination Usage

### Multiple Ordering Fields

`LimitOffsetGraphqlPagination` and `PageGraphqlPagination` both support multiple
ordering fields. `CursorGraphqlPagination` is single-field by design: keyset
pagination requires a stable, well-defined ordering over one field (typically
the primary key). Multi-field cursors are not supported.

=== "String Format"

    ```graphql
    query {
      users {
        results(ordering: "last_name,first_name,-date_joined") {
          firstName
          lastName
          dateJoined
        }
        totalCount
      }
    }
    ```

=== "Django QuerySet Equivalent"

    ```python
    # This GraphQL query is equivalent to:
    User.objects.order_by('last_name', 'first_name', '-date_joined')
    ```

### Combining with Filtering

Pagination works seamlessly with filtering:

=== "Filtered Pagination"

    ```python
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            pagination = LimitOffsetGraphqlPagination(default_limit=25)
            filter_fields = {
                'username': ('icontains', 'exact'),
                'email': ('icontains', 'exact'),
                'is_active': ('exact',),
            }
    ```

=== "Query with Filters"

    ```graphql
    query GetActiveUsers {
      users(filter: { isActive: { exact: true }, username: { icontains: "john" } }) {
        results(limit: 10, ordering: "username") {
          id
          username
          email
          isActive
        }
        totalCount
      }
    }
    ```

### Custom Pagination Classes

Create custom pagination for specific needs:

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
    ```

=== "Custom Page Pagination"

    ```python
    from django_graphex.paginations import PageGraphqlPagination

    class LargeDatasetPagination(PageGraphqlPagination):
        def __init__(self, **kwargs):
            super().__init__(
                page_size=100,
                page_size_query_param=None,  # Fixed page size
                max_page_size=100,
                ordering="-id",
                **kwargs
            )
    ```

## Related settings

Pagination behavior is governed by three global settings under `DJANGO_GRAPHEX`.
They serve as library-wide defaults; **instance arguments always take precedence**:

| Setting | Default | Description |
|---------|---------|-------------|
| `DEFAULT_PAGINATION_CLASS` | `"django_graphex.paginations.LimitOffsetGraphqlPagination"` | Paginator class used when no `Meta.pagination` is set on a type. |
| `DEFAULT_PAGE_SIZE` | `None` | Default page/limit size. `None` means unbounded (all rows). |
| `MAX_PAGE_SIZE` | `None` | Maximum page/limit size the client may request. `None` means no cap. |

**Precedence:** instance arg (e.g. `LimitOffsetGraphqlPagination(default_limit=25)`) > `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE`.

!!! warning "Global defaults are read at import time"

    `DEFAULT_PAGE_SIZE` and `MAX_PAGE_SIZE` are read as **default parameter values**
    when the pagination class is instantiated — typically at module import time when
    your schema is first evaluated. This means changing them via Django's
    `override_settings` at test time (or at runtime) does **not** affect already-
    imported paginator instances. To configure them reliably, set them in your
    actual `settings.py` before any schema module is imported, or pass the desired
    values directly to the paginator constructor.

```python
# settings.py
DJANGO_GRAPHEX = {
    "DEFAULT_PAGINATION_CLASS": "django_graphex.paginations.LimitOffsetGraphqlPagination",
    "DEFAULT_PAGE_SIZE": 20,
    "MAX_PAGE_SIZE": 100,
}
```

## Robustness & Error Handling

### Invalid Page Numbers

`PageGraphqlPagination` rejects `page=0` with a `GraphQLError` regardless of
Python's optimisation level. Before v1.2.1 the check was an `assert` statement
which is compiled out under `python -O` / `PYTHONOPTIMIZE=1`, causing page=0 to
silently compute a negative offset. The validation is now an explicit raise so
it always fires.

- **`page=0`**: raises `GraphQLError("Page value for PageGraphqlPagination must be a non-zero value")`.
- **`page < 0`**: valid — returns the last page (offset relative to the total count).
- **`page > 0`**: valid — standard page navigation.

### Tampered or Malformed Cursors

`CursorGraphqlPagination` decodes opaque cursor strings from clients. If a
cursor is corrupted, hand-crafted, or contains a value incompatible with the
ordering field's type, the paginator raises `GraphQLError("Invalid cursor")`
instead of propagating an unhandled `ValueError` or Django `ValidationError`.

The guard covers two failure points:

1. **Malformed base64 / wrong prefix** — `decode_cursor` raises `ValueError`.
2. **Type mismatch** — the decoded value cannot be coerced by `qs.filter()` (e.g.
   a string cursor passed to an `IntegerField` raises a Django `ValidationError`).

Both are caught and re-raised as `GraphQLError`, so clients always see a clean
error response (HTTP 200, `errors[]`) rather than an HTTP 500.

!!! example "Tampered cursor response"
    ```json
    {
      "data": { "events": null },
      "errors": [{ "message": "Invalid cursor" }]
    }
    ```

### COUNT Query Behaviour

`PageGraphqlPagination` only issues a `COUNT` query when it is actually needed:

| `page` value | COUNT issued? | Reason |
|---|---|---|
| `page > 0` | No | Offset is `page_size * (page - 1)` — no row count needed |
| `page < 0` | Yes | Last-page navigation: offset = `total - page_size * abs(page)` |

`totalCount` on the list wrapper is still resolved independently by
`DjangoListObjectType` and always reflects the filtered queryset count. This
change only affects the internal COUNT inside `paginate_queryset`.

## Performance Considerations

### Database Query Optimization

!!! tip "Conditional COUNT"
    As of v1.2.1, `PageGraphqlPagination` skips the COUNT query for positive
    page numbers. Only last-page navigation (`page < 0`) still issues a COUNT.
    On large tables this reduces the per-request query count for the common
    forward-pagination case.

=== "Efficient Ordering"

    ```python
    # ✅ Good: Use indexed fields for ordering
    pagination = LimitOffsetGraphqlPagination(
        ordering="-id"  # Primary key is indexed
    )

    # ⚠️  Less efficient: Non-indexed field
    pagination = LimitOffsetGraphqlPagination(
        ordering="full_name"  # May not be indexed
    )
    ```

=== "Select Related"

    ```python
    # Optimize with select_related for foreign keys via Meta.queryset
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            pagination = LimitOffsetGraphqlPagination(default_limit=25)
            queryset = User.objects.select_related('profile')
    ```

### Large Offset Performance

!!! info "Offset Limitations"
    Large offsets (e.g., `offset=10000`) can be slow. Consider cursor-based pagination for very large datasets.

## Frontend Integration

### React Example with Apollo Client

=== "Limit/Offset Pagination"

    ```javascript
    import { gql, useQuery } from '@apollo/client';

    const GET_USERS = gql`
      query GetUsers($limit: Int!, $offset: Int!) {
        users {
          results(limit: $limit, offset: $offset) {
            id
            username
            email
          }
          totalCount
        }
      }
    `;

    function UserList() {
      const [page, setPage] = useState(0);
      const limit = 10;
      const offset = page * limit;

      const { loading, error, data } = useQuery(GET_USERS, {
        variables: { limit, offset }
      });

      const totalPages = data ? Math.ceil(data.users.totalCount / limit) : 0;

      return (
        <div>
          {data?.users.results.map(user => (
            <div key={user.id}>{user.username}</div>
          ))}

          <Pagination
            currentPage={page}
            totalPages={totalPages}
            onPageChange={setPage}
          />
        </div>
      );
    }
    ```

=== "Page-Based Pagination"

    ```javascript
    const GET_USERS_BY_PAGE = gql`
      query GetUsers($page: Int!, $pageSize: Int) {
        users {
          results(page: $page, pageSize: $pageSize) {
            id
            username
            email
          }
          totalCount
        }
      }
    `;

    function UserList() {
      const [currentPage, setCurrentPage] = useState(1);
      const pageSize = 15;

      const { loading, error, data } = useQuery(GET_USERS_BY_PAGE, {
        variables: { page: currentPage, pageSize }
      });

      const totalPages = data ? Math.ceil(data.users.totalCount / pageSize) : 0;

      return (
        <div>
          {data?.users.results.map(user => (
            <div key={user.id}>{user.username}</div>
          ))}

          <div>
            <button
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage(currentPage - 1)}
            >
              Previous
            </button>

            <span>Page {currentPage} of {totalPages}</span>

            <button
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage(currentPage + 1)}
            >
              Next
            </button>
          </div>
        </div>
      );
    }
    ```

## Best Practices

!!! tip "Pagination Best Practices"

    1. **Set Reasonable Defaults**: Use sensible default page sizes (10-50 items)
    2. **Limit Maximum Size**: Prevent excessive data transfer with max limits
    3. **Use Indexed Fields**: Order by indexed fields for better performance
    4. **Cache Counts**: Cache total counts for frequently accessed datasets
    5. **Consider Cursor Pagination**: For real-time data or very large datasets
    6. **Frontend State Management**: Maintain pagination state in your frontend

### Security Considerations

```python
# Limit maximum page sizes to prevent abuse
pagination = LimitOffsetGraphqlPagination(
    default_limit=25,
    max_limit=100,  # Prevent users from requesting thousands of records
    ordering="-id"
)
```

### Testing Pagination

=== "Test Pagination Logic"

    ```python
    import pytest
    from graphene.test import Client
    from .schema import schema

    @pytest.mark.django_db
    def test_users_pagination():
        # Create test users
        for i in range(50):
            User.objects.create_user(
                username=f'user{i}',
                email=f'user{i}@example.com'
            )

        client = Client(schema)
        query = """
            query GetUsers($limit: Int!, $offset: Int!) {
                users {
                    results(limit: $limit, offset: $offset) {
                        id
                        username
                    }
                    totalCount
                }
            }
        """

        result = client.execute(query, variables={'limit': 10, 'offset': 20})

        assert len(result['data']['users']['results']) == 10
        assert result['data']['users']['totalCount'] == 50
    ```

=== "Test Ordering"

    ```python
    @pytest.mark.django_db
    def test_users_ordering():
        User.objects.create_user(username='charlie', email='c@example.com')
        User.objects.create_user(username='alice', email='a@example.com')
        User.objects.create_user(username='bob', email='b@example.com')

        client = Client(schema)
        query = """
            query GetUsers($ordering: String!) {
                users {
                    results(ordering: $ordering, limit: 10) {
                        username
                    }
                }
            }
        """

        result = client.execute(query, variables={'ordering': 'username'})
        usernames = [user['username'] for user in result['data']['users']['results']]

        assert usernames == ['alice', 'bob', 'charlie']
    ```

The pagination system in `django-graphex` provides flexible, efficient ways to handle large datasets while maintaining good performance and user experience.
