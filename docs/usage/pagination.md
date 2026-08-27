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
    from django_graphex.types import DjangoListObjectType
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
    from django_graphex.fields import DjangoFilterPaginateListField
    from django_graphex.core import ObjectType
    from .types import UserType

    class Query(ObjectType):
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

!!! info "Requests above the maximum are silently clamped"

    A `limit` larger than `max_limit` does **not** raise an error — the effective
    limit is `min(requested, max_limit)`, the same convention Django REST
    Framework uses for its paginators. When the client **omits** the argument,
    the fallback chain is `default_limit` → `max_limit`: as long as a maximum is
    configured, the list is **never unbounded**, even without a default.

    | `default_limit` | `max_limit` | client sends | effective limit |
    |---|---|---|---|
    | `25` | `100` | `limit: 500` | `100` (silently clamped) |
    | `25` | `100` | — | `25` (default) |
    | – | `100` | — | `100` (max as last resort) |
    | – | – | — | unbounded (no pagination configured) |

    The same rule applies to `PageGraphqlPagination`: a `pageSize` above
    `max_page_size` is silently clamped, and an omitted `pageSize` resolves as
    `page_size` → `max_page_size`.

!!! info "`ordering` applies even when the list is unbounded"

    The last row of the table above is the **shipped default**: with no
    `pagination=` on the list type and no `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE`
    in your settings, the default `LimitOffsetGraphqlPagination` is unbounded and
    returns the whole set. `ordering` is **not** part of that page-size decision —
    it is applied (and validated) on every request, bounded or not. So
    `results(ordering: "username")` sorts correctly on a list that has no page
    size configured, and `results(ordering: "nonexistent")` is rejected there with
    the same `Invalid ordering field` error a bounded paginator raises.

### Query Examples

!!! note "Argument placement"
    Pagination and ordering arguments (`limit`, `offset`, `ordering`) live on the
    `results` subfield. Filter arguments live on the list field. `totalCount` is a
    sibling of `results`.

!!! tip "`totalCount` is computed lazily"
    The `COUNT` query backing `totalCount` is only issued when the client
    actually **selects** `totalCount` in the query — a request that selects only
    `results` skips the `COUNT` entirely. When the results were already
    materialized in memory (e.g. an in-memory ordered/sliced page, or a
    prefetch-cache hit), `totalCount` reuses that materialized list (`len()`)
    instead of issuing a fresh query. This is a **performance-only** change: the
    response shape is unchanged, but the number of `COUNT` queries issued for a
    given request can differ from a naive eager count.

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

!!! warning "Ordering is validated against the fields your type exposes"

    Both `LimitOffsetGraphqlPagination` and `PageGraphqlPagination` validate every
    client-supplied `ordering` term **before** calling `qs.order_by()`.

    **Why this matters:**

    - An invalid field name would cause Django to raise `FieldError`, which leaks
      the full model field list (including sensitive columns like `password`,
      `is_superuser`) in `errors[].message` — a CWE-209 information disclosure.
    - A column you hid with `only_fields` / `exclude_fields` would still be
      *sortable*. Sorting by it ranks the rows by a value the client cannot
      select — a read oracle. Combined with a filter that isolates two rows, the
      hidden value is recovered exactly, one query per bit.
    - Relation-spanning lookups (`posts__title`, `author__name`) force Django to
      follow join chains, which can exhaust database resources (DoS).

    **Allowlist rule:** each ordering term's root (the part before `__`) must match
    one of the model's **concrete attnames** (`model._meta.concrete_fields`) **that
    your type actually exposes**. Leading `-`/`+` direction prefixes are stripped
    before comparison.

    The allowlist is **read off the compiled node type that actually serves
    `results`** — the type in the SDL — not re-derived from its `Meta`, and it
    asks the same predicate the filter axis asks. So *orderable*, *filterable*
    and *selectable* are the same set by construction, whatever put a field
    there: `only_fields` / `exclude_fields` / `include_fields`, or a relation
    the compiler drops because its target is not registered. **The rule and
    everything it means are stated once, in
    [Types › The projection is a security boundary](types.md#projection-security-boundary);
    this section is only how the ordering axis enforces it.**

    Field **names** are mapped back to ORM **attnames**, which is the one thing
    the SDL cannot spell: a forward FK published as `author` is ordered by
    `author_id`, and `pk` rides along with the primary key. Whether those
    attnames are *allowed* is still the predicate's answer, not the mapping's —
    see the forward-FK note below.

    The rule is enforced on every ordering path: the queryset path, the
    prefetch-cache (in-memory) path, and the nested window-prefetch
    optimization. It is also **per schema**: two schemas built over the same list
    container class each read their own node type, so a second schema cannot
    widen the first one's ordering surface. Under
    [`PERMISSION_SCOPED_SCHEMA`](permission-scoped-schema.md) that includes the
    pruned schema a given caller was served — a column that disappears with the
    relation publishing it stops being orderable for that caller.

    **A published name is not a published value.** A declared class attribute
    wins over the model-derived field of the same name, so it can put back a
    column `only_fields` removed. It stays orderable when it carries **no**
    resolver, because the default resolver hands out the column itself:

    ```python
    class AuthorType(DjangoObjectType):
        bio = CharField()  # orderable — this serves Author.bio

        class Meta:
            model = Author
            only_fields = ("id", "name")
    ```

    Add a `resolve_bio` and the field serves whatever that method returns. The
    name is published, the column is not, and `ordering: "bio"` is rejected —
    sorting by it would rank the rows by the raw column while every response
    carries the substitute. A masked primary key takes `ordering: "pk"` down
    with it, for the same reason.

    This fails closed on purpose: a `resolve_<name>` that happens to return the
    real column loses the ordering term too. Nothing can read a resolver body at
    schema-build time, so the line is drawn at the resolver rather than inside
    it. Drop the resolver, or add a second field under a different name.

    The **same-name `source=` shortcut is the one exemption**, because the
    compiler can read it: `bio = CharField(source="bio")` compiles to a resolver
    that provably reads that very attribute, so the column stays orderable — and
    stays filterable, on the same predicate. A `source=` naming a *different*
    attribute is a mask like any other and is refused.

    **The projection gates the client argument, not your own default.** The
    `ordering=` you pass when constructing `LimitOffsetGraphqlPagination` or
    `PageGraphqlPagination` is your configuration, applied identically to every
    request, so it may name a column the type projects away:

    ```python
    class UserListType(DjangoListObjectType):
        class Meta:
            model = User
            # UserType hides "last_login"; ordering by it here is still fine.
            pagination = LimitOffsetGraphqlPagination(ordering="-last_login")
    ```

    A client that passes `ordering: "-last_login"` on that same field is still
    rejected: the check follows where the value came from, not what it says.

    **This is not a claim that the default leaks nothing.** A server-configured
    ordering ranks by exactly as much as a client term does. It is a decision
    that a deployment choice you can see and change must not become a runtime
    outage — the one exception to the rule, recorded as such in
    [Types › The one exception](types.md#projection-exception).

    !!! danger "`CursorGraphqlPagination` does **not** get this exemption"

        Ranking is where the exemption stops. A paginator that *prints the
        ordering value back* is reading the column out, not ranking by it, and
        no operator-intent argument survives that.

        A keyset cursor **is** the ordering value. `pageInfo.startCursor` and
        `endCursor` are base64 of `cursor:<ordering value>\x1f<pk>`, so
        configuring `CursorGraphqlPagination(ordering="bio")` on a type that
        hides `bio` publishes that column verbatim to anyone who base64-decodes
        the token — a direct read, not a ranking.

        `CursorGraphqlPagination` therefore enforces the allowlist on its
        configured `ordering` **regardless of provenance**, and raises
        `GraphQLError: Invalid ordering field: '<name>'` on every request until
        the configuration is corrected. Order it by a column the node type
        exposes.

    **The primary key follows the projection like any other column.** Ordering by
    `pk`, by the pk's field name, or by its attname works whenever the pk itself
    is exposed — the ordinary surrogate-`id` case, where ranking rows by an
    identifier the client already reads gives nothing away.

    A **natural** primary key (a slug, a code, an email) carries real data and can
    be projected away like any other column. When it is, `ordering: "pk"` and
    `ordering: "<slug>"` are both rejected: exempting the alias while rejecting
    the name would close nothing, since they resolve to the same column.

    Hiding the pk costs nothing else. The paginators still emit it as their own
    deterministic tiebreak — that ordering is generated, never client input, so it
    is not gated. The nested window optimization declines rather than sorting by a
    tiebreak it cannot serve, and the plain prefetch path returns the same rows.

    **A forward FK's `author_id` follows the *author's* type, not the post's.**
    It is orderable only when `PostType` publishes `author` **and** the type
    behind `author` publishes the key that FK points at:

    ```python
    class AuthorType(DjangoObjectType):
        class Meta:
            model = Author
            only_fields = ("name",)          # the key is projected away

    class PostType(DjangoObjectType):
        class Meta:
            model = Post                     # publishes "author" — but its key?

    # ordering: "author_id"  ->  Invalid ordering field: 'author_id'.
    ```

    Publishing `id` on `AuthorType` puts `author_id` back. **This rejects
    orderings that used to succeed**, and the old justification — "the id is
    already readable through `author { id }`" — was simply false in this shape:
    `author { id }` does not exist in that schema either. Ranking posts by
    `author_id` there orders them by a key nothing in the SDL hands out, which
    is the read oracle in its original form. The same predicate answers the
    filter axis, so `filter_fields = {"author": ("exact",)}` is refused on the
    very same configuration — see
    [Types › What "hidden" means](types.md#what-hidden-means).

    Declaring the relation over a `resolve_author` of your own — the
    [to-one scoping hatch](types.md#relation-scope-hatch) — refuses `author_id`
    outright, whatever the author's type publishes: what the client can read is
    then whatever that resolver returns, while `ordering` still ranks by the raw
    key on the post's own row.

    **camelCase is accepted (GraphQL-consistency).** Because every field *name* is
    exposed in **camelCase** on the wire, ordering **values** accept camelCase too:
    each term is normalized to its snake_case attname before validation and before
    `qs.order_by()`. So `ordering: "createdAt"` behaves **exactly** like
    `ordering: "created_at"` — on the DB path, the in-memory (prefetch-cache) path,
    **and** the nested window-prefetch optimization. Both spellings work; snake_case
    is unchanged. An invalid camelCase field (e.g. `nonexistentField`) still raises
    the same `GraphQLError`, and relation-spanning terms are still rejected.

    **Rejected examples:**

    ```graphql
    # Non-existent field → GraphQLError: "Invalid ordering field: 'nonexistent'"
    { users { results(ordering: "nonexistent") { id } } }

    # Column the type projects away (exclude_fields = ("password",))
    # → GraphQLError: "Invalid ordering field: 'password'"
    { users { results(ordering: "password") { id } } }

    # Relation-spanning → GraphQLError: "Invalid ordering field: ..."
    { users { results(ordering: "posts__title") { id } } }

    # FK field *name* (not attname) → GraphQLError
    # Use 'author_id' (the concrete attname) instead of 'author'
    { posts { results(ordering: "author") { id } } }
    ```

    **Accepted examples:**

    ```graphql
    # Django's native pk alias (and its negated form)
    { users { results(ordering: "pk") { id } } }
    { users { results(ordering: "-pk") { id } } }

    # Concrete attname
    { users { results(ordering: "username") { id } } }

    # Descending
    { users { results(ordering: "-date_joined") { id } } }

    # camelCase (normalized to the snake_case attname) — same as "-date_joined"
    { users { results(ordering: "-dateJoined") { id } } }

    # Multi-field comma list
    { users { results(ordering: "last_name,-date_joined") { id } } }

    # Multi-field comma list, camelCase — same as "lastName,-dateJoined"
    { users { results(ordering: "lastName,-dateJoined") { id } } }
    ```

    If you need to allow ordering by additional (non-default) fields, ensure those
    columns are concrete attnames on the model **and** are exposed by the type (not
    removed by `only_fields` / `exclude_fields`). You cannot order by reverse-FK
    names (e.g. `posts`) or by relation paths (`posts__title`) — use a database
    index and annotate the queryset instead if you need computed sort keys.

    Conversely, `exclude_fields` is now enough to make a column unsortable: there
    is no separate ordering allowlist to configure.

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

### Offset Validation

`LimitOffsetGraphqlPagination` raises a clean `GraphQLError` when the client
supplies a **negative** `offset` value (e.g. `offset: -5`). The raw Django
`ValueError("Negative indexing is not supported")` is never exposed.

```graphql
# Raises GraphQLError: "Invalid offset: -5. Offset must be a non-negative integer."
{ users { results(offset: -5, limit: 10) { id } } }
```

### Limit Validation

A `limit` of `0` or a **negative** `limit` both raise a clean `GraphQLError`
instead of returning an empty page or a nonsensical negative-length slice.
This is a separate guard from the [silent clamp](#configuration-options) that
applies when `limit` is **above** `max_limit`; here the value is invalid
outright, not just out of range.

```graphql
# Raises GraphQLError: "Invalid limit: 0. Limit must be a positive integer."
{ users { results(limit: 0) { id } } }

# Raises GraphQLError: "Invalid limit: -5. Limit must be a positive integer."
{ users { results(limit: -5) { id } } }
```

The same guard applies to `PageGraphqlPagination`'s `pageSize` argument
(`"Invalid page size: 0. Page size must be a positive integer."`) and to
`CursorGraphqlPagination`'s `first` argument (`"Invalid first: 0. First must
be a positive integer."`) — every paginator's page-size-like argument rejects
zero and negative values the same way.

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

### Backward pagination

`PageGraphqlPagination` accepts negative `page` values to navigate from the
**end** of the list, in true list order (i.e. `page=-1` returns exactly what
Python's `list[-page_size:]` would):

| `page` | Rows returned |
|---|---|
| `-1` | The **last** `page_size` rows, in natural (ascending `ordering`) order |
| `-2` | The `page_size`-row window immediately **before** the last page |
| Large negative (overshoot past the start) | Clamps to the **first** `page_size` rows |
| `0` | `GraphQLError` — page `0` is never valid, forward or backward |

```graphql
# 10-row table, page_size = 3
{ users { results(page: -1) { id } } }   # rows 8, 9, 10 (the last 3, in order)
{ users { results(page: -2) { id } } }   # rows 5, 6, 7  (the window before)
{ users { results(page: -100) { id } } } # rows 1, 2, 3  (overshoot clamps to the start)
```

!!! warning "Cost: one extra `COUNT` query, and no window-prefetch"

    A negative `page` needs the total row count to compute where the window
    starts (`offset = count + page_size * page`), so it costs **one additional
    `COUNT` query** beyond the normal `SELECT`. Positive pages never issue a
    `COUNT` (see [COUNT Query Behaviour](#count-query-behaviour) below).
    Negative pages also **opt out of the window-prefetch optimization** — the
    prefetch pre-check needs the offset up front (before any query runs), which
    a negative page cannot supply without first counting, so it falls back to
    the standard (non-window) resolution path for that request.

!!! note "`LimitOffsetGraphqlPagination` and `CursorGraphqlPagination` have no backward mode"

    - `LimitOffsetGraphqlPagination` has **no** backward navigation: a negative
      `offset` (e.g. `offset: -5`) always raises a clean `GraphQLError` — see
      [Offset Validation](#offset-validation).
    - `CursorGraphqlPagination` is **forward-only** by design (no `last`/`before`)
      — see [Why is there no backward pagination](#cursorgraphqlpagination) above.
      The closest idiom is inverting `ordering` (e.g. `"id"` → `"-id"`): this
      returns the **same set of rows in reverse order**, not a "last page" —
      there is no windowed "start from the end" behavior.

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

!!! info "The cursor is a composite `(ordering value, pk)` boundary"

    Each opaque cursor encodes **both** the ordering field's value **and** the
    primary key of the boundary row, with the primary key used as an `ORDER BY`
    tiebreak. This means rows that share the same ordering value are never
    skipped or duplicated across pages — a plain value-only cursor would let a
    `field > value` filter jump over every other row tied at that same value.
    Nullable ordering fields are supported with deterministic placement:
    `NULL` values sort **last** when ascending and **first** when descending,
    and pages cross a `NULL` boundary without dropping rows.

    Cursors are **opaque**: treat them as an implementation detail returned by
    the server (`pageInfo.startCursor` / `pageInfo.endCursor`) and never build
    or edit one client-side. A tampered or malformed cursor — corrupted
    base64, wrong internal prefix, or a value that cannot be coerced to the
    ordering field's type — is caught internally and raised as a clean
    `GraphQLError("Invalid cursor")`.

### Basic Usage

```python
from django_graphex.fields import DjangoListObjectField
from django_graphex.core import ObjectType
from django_graphex.paginations import CursorGraphqlPagination
from django_graphex.types import DjangoListObjectType
from .models import Event


class EventListType(DjangoListObjectType):
    class Meta:
        model = Event
        description = "Event list with cursor pagination"
        pagination = CursorGraphqlPagination(ordering="id")  # use "-id" for newest-first


class Query(ObjectType):
    events = DjangoListObjectField(EventListType)
```

### Configuration Options

```python
CursorGraphqlPagination(
    ordering="-created",            # Server-side keyset field (single field; leading '-' = descending)
    cursor_query_param="cursor",    # GraphQL argument name for the cursor
    first_query_param="first",      # GraphQL argument name for the page size
    page_size=25,                   # Default page size (DEFAULT_PAGE_SIZE when omitted)
    max_page_size=100,              # Maximum `first` a client may request (MAX_PAGE_SIZE when omitted)
)
```

!!! warning "`ordering` is server-configured — single field only"

    - Unlike `LimitOffsetGraphqlPagination` and `PageGraphqlPagination`, cursor
      pagination exposes **no client `ordering` argument** — the keyset field is
      fixed by the server when the paginator is constructed.
    - The default is `"-created"` (newest-first), which assumes your model has a
      `created` field — pass your own `ordering` otherwise.
    - A leading `-` selects descending order.
    - An empty string falls back to `"id"`.
    - A comma-separated value is **not** an error: only the **first** term is
      used, the rest are silently ignored (keyset pagination is single-field).
    - **It must name a column your node type exposes.** Being server-configured
      buys no exemption here, because the cursor echoes the ordering value back
      to the client — see
      [Ordering Validation (Security)](#ordering-validation-security). Pointing
      it at a projected-away column raises
      `GraphQLError: Invalid ordering field: '<name>'` on every request.

!!! warning "The node type must expose its primary key"

    Every cursor is base64 of `cursor:<ordering value>\x1f<pk>`. The pk is the
    tiebreak that keeps rows sharing an ordering value from being skipped
    between pages, so it is in **every** token this paginator emits — which
    makes it a direct read of the primary key, whatever the ordering names.

    The rule is about the **SDL**, not about the kind of key: cursor pagination
    is refused whenever the node type's compiled fields do not publish the
    primary key's value. Concretely, these shapes **cannot** use it:

    | Shape | Why |
    |---|---|
    | `only_fields` that simply does not list the key | An omission hides the key exactly as an exclusion does — this is the common case, and it does not require a natural key |
    | `exclude_fields` naming the key | Explicitly removed from the SDL |
    | A **natural** key (a slug, a code, an email) projected away | Business data, hidden like any other column |

    And this shape **can**, even though its own primary-key field is absent from
    the SDL:

    | Shape | Why |
    |---|---|
    | A multi-table-inheritance child | Its pk is the implicit `<parent>_ptr` link, which is join plumbing the compiler never publishes — but the child publishes the parent's `id`, and the two hold the same value on every row |

    A refused configuration raises on **every** request, from both
    `results` and `pageInfo`:

    ```
    GraphQLError: Cursor pagination is unavailable on a type that hides its
    primary key: every cursor carries the key as its tiebreak. Expose the
    primary key or use offset/page pagination.
    ```

    Add the key to the type's published fields, or page that list with
    `LimitOffsetGraphqlPagination` / `PageGraphqlPagination`, which return rows
    and nothing else.

!!! info "Effective page size — never unbounded"

    The page size resolves as `first` (client) → `page_size` → `max_page_size`,
    always clamped at `max_page_size`. When **all three** are unset, the module
    constant `DEFAULT_CURSOR_PAGE_SIZE = 20` applies — unlike the other
    paginators, cursor pagination **never** returns an unbounded result set (the
    keyset always needs a concrete page size).

!!! note "`first` + `cursor` are the forward keyset parameters"

    `first` controls the page size and `cursor` carries the opaque boundary
    token from the previous page. If your API needs a different argument name,
    rename `first` per list via the constructor:

    ```python
    pagination = CursorGraphqlPagination(first_query_param="limit")
    # results(limit: Int, cursor: String) instead of results(first: Int, cursor: String)
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

!!! note "Why is there no backward pagination (`last`/`before`)?"
    This paginator is a deliberately **forward-only keyset** design: each page
    is a single compound `(field, pk) > (value, pk)` / `(field, pk) < (value,
    pk)` filter relative to the previous page's boundary row. Supporting
    `last`/`before` — and multi-field ordering — requires additional
    lexicographic `WHERE` chains (the general `(a, b, ...) > (x, y, ...)`
    row-comparison expansion for an arbitrary number of ordering fields), which
    is substantially more machinery than the current single-field-plus-pk
    boundary. That work is not scheduled: cursor pagination is `first` +
    `cursor` only, and `ordering` must be a single field (a leading `-` selects
    descending order) — order by a stable, indexed column such as the primary
    key.

    **If you need backward navigation today:** `LimitOffsetGraphqlPagination`
    has no backward mode either (a negative `offset` raises a clean
    `GraphQLError`), but `PageGraphqlPagination` supports it natively — see
    [Backward pagination](#backward-pagination) below.

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
- **`page < 0`**: valid — navigates backward from the end of the list; see
  [Backward pagination](#backward-pagination) for the exact row semantics.
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
| `page < 0` | Yes | Backward navigation needs the total row count to compute the window: `offset = total + page_size * page` (see [Backward pagination](#backward-pagination)) |

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
    from graphql import graphql_sync
    from .schema import schema   # a DjangoGraphQLSchema

    @pytest.mark.django_db
    def test_users_pagination():
        # Create test users
        for i in range(50):
            User.objects.create_user(
                username=f'user{i}',
                email=f'user{i}@example.com'
            )

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

        result = graphql_sync(
            schema.graphql_schema, query, variable_values={'limit': 10, 'offset': 20}
        )

        assert len(result.data['users']['results']) == 10
        assert result.data['users']['totalCount'] == 50
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
