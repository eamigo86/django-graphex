# django-graphex — Playground

> **Targets django-graphex v2.2 — native `graphql-core` backend (no graphene).**
> Query-optimization, typed-GFK unions, `get_queryset` scoping + safe ordering,
> native subscriptions (SSE + WS), and the 2.2 permission story: nested writes
> authorized by the child, and a schema pruned to the caller.

A small, runnable Django project that exercises most of `django-graphex`
end-to-end: queries, all three paginators, filtering,
generic single-object fields, nested lists (N+1-safe) with nested
pagination/filtering, choices→enum, directives, CRUD mutations with
permissions, query depth/cost limits, response caching, the full
**query-optimization surface** (DB-side window pagination, selection-driven
`AnnotatedField`, per-field `optimize_<field>` hooks, and typed
`GenericForeignKey` unions), and public + private subscriptions over Django
Channels.

It installs the library from the parent checkout (editable), uses **uv**,
**SQLite**, and a `Makefile`.

Not everything the library ships is demonstrated here. The [feature coverage
matrix](#feature-coverage-matrix) marks each entry as demonstrated (✅), merely
imported so you can swap it in (`import only`), deliberately left out
(`not used`), or covered only in the docs (`doc` / `note`) — read the row before
copying the shape.

### Safe ordering (anti-oracle hardening)

The ordering allowlist is active on all paginated fields. It rejects
relation-spanning and non-existent terms to prevent column-oracle attacks:

| Query | Error |
|-------|-------|
| `posts { results(ordering: "author__user__password") { title } }` | `Relation-spanning ordering is not permitted` |
| `posts { results(ordering: "nonexistent") { title } }` | `Invalid ordering field` |

Try these in GraphiQL to see the guard in action.

---

## Quick start

```bash
cd examples/playground

make install     # uv sync — installs the local library + daphne
make migrate     # create + apply migrations (SQLite)
make seed        # demo data: 15 authors × 12 posts × 3 comments, 12 notes,
                 #            2 accounts + 2 invoices + 4 attachments (GFK union).
                 #            Each author's posts list spans multiple pages at
                 #            page size 10, so nested window pagination is real.
                 #            Scale with: python manage.py seed --authors N --posts M
make run         # ASGI server at http://127.0.0.1:8000/graphql/
```

Open **GraphiQL** at <http://127.0.0.1:8000/graphql/>.

The seed creates superuser **`demo` / `demo12345`**.

> **No PyPI release needed.** `make install` installs the library **from this
> repo checkout** (editable) via `[tool.uv.sources]` in `pyproject.toml`.
> To install from a GitHub branch instead, swap to the commented `git = …`
> source in `pyproject.toml`.

### Authenticating (for private fields)

Private fields (`me`, `myNotes`, `noteSubscription`), the note and comment
writes, and `postWithCommentsCreate` **when it carries a `comments` list**
require an authenticated user. The remaining writes (`postCreate`,
`createCategory`, `uploadDocument`) are deliberately open, so you can compare a
gated write against an ungated one. Auth here is **Django session-based**:

1. Open <http://127.0.0.1:8000/admin> and log in as `demo` / `demo12345`.
2. Return to GraphiQL — it shares the session cookie.

Log out of `/admin` to test anonymous (public) behaviour.

---

## Feature coverage matrix

| Feature | Status | Where (file:line or field name) |
|---------|--------|--------------------------------|
| **Types** | | |
| `DjangoObjectType` | ✅ | `schema.py` — `PostType`, `AuthorType`, `CommentType`, `CategoryType`, `TagType`, `UserType` |
| `DjangoListObjectType` | ✅ | `schema.py` — `PostListType`, `AuthorListType`, `CommentListType` |
| `DjangoInputObjectType` | ✅ | `schema.py` — `CategoryInput` |
| `DjangoModelType` | ✅ | `schema.py` — `NoteModelType` |
| `DjangoUnionType` (typed GFK target) | ✅ | `schema.py` — `AttachmentTargetUnion` (`Meta.types`) + `AttachmentType.Meta.unions = {"target": …}` |
| `DjangoInterfaceType` | doc | Covered in `docs/usage/types.md`; not in the playground (no shared abstract base fits Account/Invoice cleanly) |
| `TextChoices` → GraphQL enum | ✅ | `Post.status` / `PostType` |
| `max_depth` per-type depth limit | ✅ | `schema.py` — `PostType.Meta.max_depth = 4` |
| `complexity` per-type cost weight | ✅ | `schema.py` — `PostType.Meta.complexity = 2` |
| **Fields** | | |
| `DjangoObjectField` | ✅ | `PublicQuery.post` |
| `DjangoListObjectField` | ✅ | `PublicQuery.posts`, `authors`, `comments` |
| `DjangoFilterListField` | ✅ | `PublicQuery.categories` |
| `DjangoFilterPaginateListField` | ✅ | `PublicQuery.posts_flat` |
| **Pagination** | | |
| `LimitOffsetGraphqlPagination` | ✅ | `PostListType`, `NoteModelType`, `posts_flat` |
| `PageGraphqlPagination` | ✅ | `AuthorListType` |
| `CursorGraphqlPagination` | ✅ | `CommentListType` — also exposes `pageInfo` |
| **Filtering** | | |
| `filter_fields` on object types | ✅ | All `DjangoObjectType` subclasses |
| Filtering on list fields | ✅ | `posts(filter: { status: { exact: PUBLISHED }, title: { icontains: "…" } })` |
| `@filter_field` custom per-field filter (v1.3.0) | ✅ | `schema.py` — `PostType.search`; try: `posts(filter: { search: "django" }) { results { id title } totalCount }` |
| Filtered nested lists | ✅ | `authors { results { posts(filter: { title: { icontains: "…" } }) } }` |
| **Nested lists (N+1-safe)** | | |
| `results` / `totalCount` wrapper | ✅ | Every list field |
| Nested FK list | ✅ | `Author → posts`, `Post → comments` |
| Nested M2M list | ✅ | `Post.tags` — `TagType` registration triggers automatic nesting |
| Multi-level nesting | ✅ | `authors → posts → comments` (all paginated independently) |
| `GenericRelation` reverse list | wired | `Post.attachments` — prefetched + `.only()`-narrowed reverse side of the GFK. Wired on the model + schema; the seed leaves it empty so the `attachments` GFK-union demo stays runnable (a `Post` target is not an `AttachmentTargetUnion` member). Query `posts { results { attachments { results { caption } } } }` runs cleanly and returns rows once you attach an `Attachment` to a `Post` |
| **Mutations** | | |
| `DjangoModelMutation` (full CRUD) | ✅ | `PostMutation` → `postCreate/Update/Delete` |
| `DjangoModelType.MutationFields()` | ✅ | `NoteModelType` → `noteCreate/Update/Delete`; `CommentModelType` → `commentCreate/Update/Delete` |
| `Meta.model_operations` | ✅ | `CommentModelType` (writes only, reads served by `CommentType`), `PostWithCommentsMutation` (`create` only) |
| `DjangoInputObjectType` on hand-written mutation | ✅ | `CategoryInput` / `createCategory` |
| Nested writes (`nested_fields` — reverse FK) | ✅ | `PostWithCommentsMutation` → `postWithCommentsCreate`, authorized by the child's own permission — see [Nested writes are gated by the child](#nested-writes-are-gated-by-the-child-22) |
| **Permissions** | | |
| `BasePermission` (custom subclass) | ✅ | `schema.py` — `IsOwnerOrReadOnly`, assigned on `CommentModelType.permission_classes`. It gates `commentCreate/Update/Delete` **and** every comment written through `postWithCommentsCreate` |
| `IsAuthenticatedOrReadOnly` | ✅ | `NoteModelType.permission_classes` |
| `AllowAny` | import only | Imported in `schema.py` behind `# noqa: F401`; no type assigns it. Swap it into `NoteModelType.permission_classes` to see it act |
| `IsAuthenticated` | import only | Imported in `schema.py` behind `# noqa: F401`; no type assigns it. Swap it into `NoteModelType.permission_classes` to see it act |
| `IsAdmin` | import only | Imported in `schema.py` behind `# noqa: F401`; no type assigns it. Swap it into `NoteModelType.permission_classes` to see it act |
| `IsAdminOrReadOnly` | import only | Imported in `schema.py` behind `# noqa: F401`; no type assigns it. Swap it into `NoteModelType.permission_classes` to see it act |
| `DjangoModelPermissions` | not used | The playground gates on identity (`IsOwnerOrReadOnly`, `IsAuthenticatedOrReadOnly`), not on Django model permissions. Those still drive `PERMISSION_SCOPED_SCHEMA` below, which reads them straight off the caller |
| `PERMISSION_SCOPED_SCHEMA` (pruned per-caller schema) | ✅ | `config/settings.py` — active; visible at `/graphql/secure/` — see [A schema pruned to the caller](#a-schema-pruned-to-the-caller-22) |
| `API_ACCESS_GROUP` | not used | Endpoint-wide group gate; the playground keeps `/graphql/` public on purpose. Set it in `config/settings.py` to lock the endpoint to one Django `Group` |
| **Security / middleware** | | |
| `DisableIntrospectionMiddleware` | ✅ | `config/settings.py` DJANGO_GRAPHEX.MIDDLEWARE; toggle via `ALLOW_INTROSPECTION` |
| `AuthenticatedFieldsMiddleware` | ✅ | `config/settings.py` DJANGO_GRAPHEX.MIDDLEWARE |
| `GraphQLDirectiveMiddleware` | ✅ | `config/settings.py` DJANGO_GRAPHEX.MIDDLEWARE |
| `DjangoGraphQLSchema` (public + private roots) | ✅ | `schema.py` — `private_query=PrivateQuery`, `private_subscription=PrivateSubscriptions` |
| `collect_field_names` | note | Used internally by `DjangoGraphQLSchema`; can be called directly to build a custom protected-field set |
| `DenyAllRegistry` | note | Fail-closed sentinel for broken schemas; not needed in a healthy project |
| **Views** | | |
| `BaseGraphQLView` | ✅ | base of all views |
| `GraphQLView` (depth/cost rules, caching) | ✅ | queries + mutations at `/graphql/` |
| `AuthenticatedGraphQLView` | ✅ | `/graphql/secure/` — rejects unauthenticated requests with HTTP 403 |
| `subscription_sse_view` (native SSE) | ✅ | `/graphql/stream` |
| `subscription_ws_consumer` (graphql-transport-ws) | ✅ | `/ws/graphql/` (see `config/asgi.py`) |
| `SubscriptionClientView` | ✅ | `/graphql/client/` |
| **Query depth / cost limiting** | | |
| `DepthLimitValidationRule` | ✅ | Wired in `GraphQLView`; `PostType.Meta.max_depth = 4` activates per-type enforcement |
| `CostLimitValidationRule` | ✅ | Wired in `GraphQLView`; `PostType.Meta.complexity = 2`; enable budget via `MAX_QUERY_COST` |
| `analyze_cost` / `CostReport` | ✅ | Used internally by `GraphQLView.get_query_cost`; enable `EXPOSE_QUERY_COST` to see it |
| `MAX_QUERY_DEPTH` setting | ✅ | **Active at depth 6** in `config/settings.py:112` — the playground rejects any query nested more than 6 levels |
| `MAX_QUERY_COST` / `EXPOSE_QUERY_COST` | note | Commented in `config/settings.py` — uncomment to block expensive queries and expose cost |
| **Queryset optimization** | | |
| `OPTIMIZE_QUERYSET` | ✅ | Enabled by default; `select_related`/`prefetch_related` derived from the selection. Commented in `config/settings.py` to show how to flip it |
| `OPTIMIZE_ONLY_FIELDS` | ✅ | Enabled by default; `.only()` column narrowing (root span + inside each `Prefetch` child) |
| `OPTIMIZE_NESTED_PAGINATION` (DB-side window slicing) | ✅ | Exercised by `authors { results { posts(filter:…) { results(limit:…, ordering:…) } } }` — `ROW_NUMBER() OVER PARTITION BY author_id` slices each author's page DB-side |
| `OPTIMIZE_ANNOTATED_FIELDS` / `AnnotatedField` | ✅ | `schema.py` — `AuthorType.post_count = AnnotatedField(GraphQLInt, Count("posts"))`; `Count` injected only when `postCount` is selected |
| Per-field `optimize_<field>` hook | ✅ | `schema.py` — `AuthorType.optimize_posts` (composes on the optimizer-built `posts` child queryset, once per query) |
| `OPTIMIZER_SAFE_MODE` | note | Default `False` (fail loud); listed commented in `config/settings.py` — flip to `True` to degrade to the un-optimized base on any optimizer exception |
| **Generic relations (typed GFK union)** | | |
| `GenericForeignKey` exposed as a typed `DjangoUnionType` | ✅ | `schema.py` — `AttachmentType.target` via `AttachmentTargetUnion` (`Meta.types`) + `Meta.unions` |
| Per-content-type `GenericPrefetch` narrowing (Django 5.0+) | ✅ | One `.only()`-narrowed queryset per content type (`AccountType.balance`, `InvoiceType.amount`), batched across all attachments |
| `GenericForeignKey` / `GenericRelation` prefetch | ✅ / wired | `Attachment.target` (GFK) exercised by the seed; `Post.attachments` (reverse `GenericRelation`) is wired but left empty so the GFK-union demo stays runnable |
| **File uploads (v1.3.0)** | | |
| `Base64FileInput` (opt-in) | ✅ | `schema.py` — `UploadDocument` mutation; `Document` model has a `FileField`. Try: `mutation { uploadDocument(name: "readme" file: {filename: "readme.txt" data: "<base64>" contentType: "text/plain"}) { ok name document { id name created } } }` — the `document` payload field is what mounts `DocumentType` on the schema |
| `MAX_UPLOAD_SIZE` | ✅ | `config/settings.py` — `5 * 1024 * 1024` (5 MB) |
| `MAX_REQUEST_BODY_SIZE` | ✅ | `config/settings.py` — `20 * 1024 * 1024` (20 MB body guard, fires before JSON parse) |
| **Response caching** | | |
| `CACHE_ACTIVE` / `CACHE_TIMEOUT` | note | Commented in `config/settings.py` — uncomment to activate query-result caching |
| **Subscriptions** | | |
| Public `Subscription` | ✅ | `PostSubscription` (stream `posts`), `CommentSubscription` (stream `comments`, per-subscriber `filter`) |
| Private subscription via `DjangoModelType` | ✅ | `NoteModelType.SubscriptionField()` — gated by `AuthenticatedFieldsMiddleware` |
| `subscription_scope` (server-forced row scope) | ✅ | `NoteModelType.subscription_scope` — only own notes |
| `subscription_index_fields` | ✅ | `NoteModelType.Meta.subscription_index_fields = ("owner",)` |
| `payload_mode` | ✅ | `PostSubscription`, `CommentSubscription`, `NoteModelType.Meta.payload_mode = "full"` |
| Native WS consumer (`subscription_ws_consumer`) | ✅ | `consumers.py` — `AppWSConsumer` |

---

## How to run

```text
make install        uv sync (local library + daphne)
make migrate        makemigrations + migrate
make seed           load demo data
make run            daphne ASGI server (HTTP + WebSocket)
make collectstatic  collect static files into STATIC_ROOT
make superuser      create your own superuser
make shell          Django shell
make test           run the end-to-end tests (WS + SSE round-trips, schema, client)
make reset          drop the SQLite db, re-migrate, re-seed
make clean          remove the db and caches
```

The `make run` command starts daphne at <http://127.0.0.1:8000/graphql/>.

---

## Tests

The `tests/` directory holds **end-to-end** tests that run under the
playground's **own** Django settings (`config.settings`), not the library's
`tests/` settings. They drive the real `blog.schema`, the real WebSocket
consumer (`config/asgi.py` → `blog.consumers.AppWSConsumer`), and the real SSE
view (`config/urls.py`):

- **WS round-trip** — open a `postSubscription` over the graphql-transport-ws
  consumer, create a `Post` through the ORM (a genuine `post_save` broadcast),
  and assert a `next` frame with the new post arrives.
- **SSE round-trip** — open the same subscription over the SSE
  (`text/event-stream`) view, create a `Post`, and assert an `event: next`
  frame is delivered.
- **Schema + permission smoke** — the playground schema builds; a protected
  field (`me`) requires auth through `GraphQLView`/`AuthenticatedFieldsMiddleware`.
- **Permissions: nested + pruned** (`test_permissions_nested_and_scoped.py`) —
  the two demos above, over the wire: an anonymous caller denied `commentCreate`
  is denied the same write through `postWithCommentsCreate` (and the parent
  `Post` rolls back), while `/graphql/secure/` serves each caller a schema
  pruned to their Django model permissions.
- **Subscription client** — `/graphql/client/` serves the HTML client with both
  transports (graphql-transport-ws + graphql-sse) and the playground's WS/HTTP
  endpoints wired. (A full headless-browser round-trip is intentionally deferred
  — no Playwright/Selenium dependency is added.)

Run them with **make** (uses `uv`, installs the `test` dependency group):

```bash
cd examples/playground
make test
```

Or directly, with any environment that already has `pytest`, `pytest-django`,
`pytest-asyncio`, `channels`, and `daphne` available (e.g. the repo's own dev
venv) — `--no-migrations` builds the test DB straight from the models, since
the playground ships no migration files:

```bash
cd examples/playground
DJANGO_SETTINGS_MODULE=config.settings python -m pytest tests/ -q --no-migrations
```

---

## Example GraphQL operations

### 1. Nested lists with all three paginators

```graphql
{
  # Limit/offset: posts
  posts(filter: { status: { exact: PUBLISHED } }) {
    totalCount
    results(limit: 5, offset: 0, ordering: "-id") {
      id
      title
      status         # enum: DRAFT | PUBLISHED | ARCHIVED
      author { name }
      tags { totalCount results { name } }
      comments {
        totalCount
        results(first: 2) { text }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
  # Page pagination: authors
  authors {
    totalCount
    results(page: 1) {
      name
      posts(filter: { title: { icontains: "Post" } }) {
        totalCount
        results(limit: 2, ordering: "-id") { title status }
      }
    }
  }
  # Cursor pagination: comments
  comments {
    totalCount
    results(first: 3) { text }
    pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
  }
}
```

### 2. Query optimization (N+1 avoidance)

The optimizer is **on by default** (all five `OPTIMIZE_*` settings — see
`config/settings.py`). Each query below runs a **constant number of SQL
statements** no matter how many rows exist. To feel the difference, uncomment
`"OPTIMIZE_QUERYSET": False` in `config/settings.py` and watch the query count
explode (visible via the SQL panel, `django-debug-toolbar`, or
`assertNumQueries` in a test).

**(a) `AnnotatedField` — selection-driven DB annotation.**
`AuthorType.post_count = AnnotatedField(GraphQLInt, Count("posts"))`
(`GraphQLInt` is imported from `graphql`, the graphql-core scalar — no graphene).

```graphql
{
  authors {
    results { name postCount }
  }
}
```

The optimizer adds `.annotate(_gqx_ann_post_count=Count("posts"))` **only when
`postCount` is selected**. Drop `postCount` from the selection and that
`Count(*)` aggregate disappears from the SQL entirely — no wasted work.

**(b) Per-field `optimize_<field>` hook + DB-side window pagination.**
`AuthorType.optimize_posts` composes on top of the optimizer-built child
queryset (called **once per query**, not once per author). The paginated nested
`posts` list is sliced **DB-side** via `ROW_NUMBER() OVER (PARTITION BY
author_id)` — each author's page is fetched in a single prefetch, not
all-then-slice-in-memory.

```graphql
{
  authors {
    results {
      name
      posts(filter: { title: { icontains: "Post" } }) {
        results(limit: 2, ordering: "-id") { title category { name } }
        totalCount
      }
    }
  }
}
```

`totalCount` is the per-partition **filtered** `COUNT(*)` (read from a second
window function, `_gqx_total`), and the `category { name }` join rides along in
the same prefetch — N+1-safe regardless of how many authors or posts exist.

> The shipped `optimize_posts` adds a stable secondary ordering
> (`order_by("-id", "title")`) because it layers cleanly on top of the
> optimizer's `.only()` narrowing on **every** selection. The textbook variant
> is `return queryset.select_related("category")` — but the optimizer applies
> `.only()` to this child queryset *after* the hook, so when `category` is **not**
> selected, `category_id` is deferred and `select_related("category")` raises a
> Django `FieldError`. Add the `select_related` join only when the client also
> selects the relation (as the query above does). See the docstring on
> `AuthorType.optimize_posts` in `blog/schema.py` for the full reasoning.

**(c) Typed `GenericForeignKey` union (per-content-type narrowing).**
`Attachment.target` is a GFK exposed as `AttachmentTargetUnion` (a
`DjangoUnionType` with `Meta.types = (AccountType, InvoiceType)`); the owner
declares `Meta.unions = {"target": AttachmentTargetUnion}`. Clients select
per-member fields with inline fragments:

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

On **Django 5.0+** with `OPTIMIZE_ONLY_FIELDS`, the optimizer routes `target`
through a `GenericPrefetch` with **one `.only()`-narrowed queryset per content
type** (the `Account` bucket fetches only `balance`, the `Invoice` bucket only
`amount`), batched across all attachments — no N+1. On Django < 5.0 it degrades
to one bare full-load `Prefetch`. An inline-fragment type-condition guard
prevents the walker from mis-attributing `InvoiceType.amount` against the
`Account` relation map.

### 3. Directives on string/numeric fields

```graphql
{
  posts {
    results(limit: 3) {
      title @uppercase
      slug: title @slugify
      teaser: body @truncate(length: 40)
      lower_title: title @lowercase
    }
  }
}
```

> **Note on `@lowercase` and enum fields**: `Post.status` is a `TextChoices`
> CharField exposed as a GraphQL enum. Applying `@lowercase` to it has no
> visible effect because graphql-core re-serializes the field through the enum
> type *after* the directive runs, always returning the enum name (`PUBLISHED`,
> etc.). Use `@lowercase` on plain text fields (like `title` above) where the
> transformation is visible in the response.

All directives from `all_directives` are available: `@uppercase`,
`@lowercase`, `@capitalize`, `@title_case`, `@camel_case`, `@snake_case`,
`@kebab_case`, `@swap_case`, `@strip`, `@center`, `@replace`, `@truncate`,
`@slugify`, `@base64`, `@number`, `@currency`, `@default`, `@date`, `@abs`,
`@ceil`, `@floor`, `@round`, `@shuffle`, `@sample`, `@unique`.

### 4. Mutations with permissions + validation errors

Log in via `/admin` first (session cookie), then:

```graphql
# Create a note (requires auth; owner is set to the current user automatically)
mutation CreateNote {
  noteCreate(newNote: { title: "Hello", body: "from GraphQL" }) {
    ok
    errors { field messages }
    note { id title owner { username } }
  }
}

# Update
mutation UpdateNote {
  noteUpdate(newNote: { id: 1, title: "Edited title" }) {
    ok
    note { id title }
  }
}

# Delete
mutation DeleteNote {
  noteDelete(id: 1) { ok }
}
```

Attempt the same **without being logged in** — the permission gate returns:

```json
{
  "errors": [{ "message": "You do not have permission to perform this action.",
               "extensions": { "code": "PERMISSION_DENIED", "status_code": 403 } }]
}
```

A failing validation (blank title) returns the `errors` list instead of `ok: true`:

```graphql
mutation { noteCreate(newNote: { title: "" }) { ok errors { field messages } } }
```

### 5. Nested write — create a Post with inline Comments

`PostWithCommentsMutation` sets `Meta.nested_fields = {"comments": Comment}`.
django-graphex detects that `comments` is a **reverse FK** (one-to-many), saves
the Post first, then saves each Comment with `post` injected automatically — all
inside a single `transaction.atomic()`.  If any comment fails validation the
whole operation is rolled back.

```graphql
mutation CreatePostWithComments {
  postWithCommentsCreate(
    newPost: {
      title: "Hello from nested writes"
      body: "django-graphex handles the FK injection automatically."
      author: 1
      comments: [
        { authorName: "Ada", text: "Great post!" }
        { authorName: "Bob", text: "Really useful, thanks." }
      ]
    }
  ) {
    ok
    errors { field messages }
    post {
      id
      title
      comments {
        totalCount
        results(first: 5) { id authorName text }
      }
    }
  }
}
```

The `comments` list is optional — omit it and the mutation behaves exactly like
a plain `postCreate`.  Passing an empty list (`comments: []`) is a no-op
(existing comments are never removed).

#### Nested writes are gated by the child (2.2)

Run the mutation above **logged out**. It fails:

```json
{
  "errors": [{ "message": "You do not have permission to perform this action.",
               "extensions": { "code": "PERMISSION_DENIED", "status_code": 403 } }]
}
```

`PostWithCommentsMutation` declares no permission of its own. The denial comes
from the **child**: `CommentModelType.permission_classes = [IsOwnerOrReadOnly]`
is what gates `commentCreate`, and since 2.2.0 the nested writer runs the
child's own hosts too. So the caller who cannot write a `Comment` through the
front door cannot write one through the parent either — and because the child's
denial escapes the mutation's `transaction.atomic()` block, the parent `Post`
rolls back with it. Nothing lands.

Try it in three steps:

1. Logged out, run `commentCreate` — denied.
2. Logged out, run `postWithCommentsCreate` with a `comments` list — denied by
   the same class, and `posts { totalCount }` is unchanged.
3. Log in via `/admin`, run it again — the post and its comments are created.

Drop `permission_classes` from `CommentModelType` in `blog/schema.py` and step 2
succeeds anonymously again: that is the pre-2.2.0 shape, and it is why a child
model's own permissions are the thing to check when auditing a nested write.

### 6. A schema pruned to the caller (2.2)

`config/settings.py` ships with `"PERMISSION_SCOPED_SCHEMA": True`, so every
request to **`/graphql/secure/`** (`AuthenticatedGraphQLView`) is validated
against a schema pruned to the caller's **Django model permissions**. A field
the caller may not use does not exist for them: selecting it is graphql-core's
own `Cannot query field`, a not-found indistinguishable from a typo, never an
authorization error that would confirm the field is there.

Of the three permission-scoped features the release ships (`DjangoModelPermissions`,
`API_ACCESS_GROUP`, `PERMISSION_SCOPED_SCHEMA`), this is the one the playground
demonstrates, because it is the only one whose effect you can *see* rather than
merely be denied by — and because the field it prunes here is the nested one
from the demo above.

The seeded `demo` user is a superuser and always gets the **full** schema, so
make an ordinary user first:

```bash
uv run python manage.py shell -c "
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
u = get_user_model().objects.create_user('editor', password='editor12345', is_staff=True)
u.user_permissions.set(Permission.objects.filter(content_type__app_label='blog').exclude(content_type__model__in=['note', 'comment']))
"
```

`editor` may write posts but holds no `Note` or `Comment` permission at all.
`is_staff` only lets them log in at `/admin` so GraphiQL shares the session; it
grants no model permission. Log in as `editor` / `editor12345`, open
<http://127.0.0.1:8000/graphql/secure/> and run:

| Document at `/graphql/secure/` | Result |
|---|---|
| `mutation { noteCreate(newNote: { title: "x" }) { ok } }` | `Cannot query field 'noteCreate' on type 'RootMutation'. Did you mean 'postCreate'?` |
| `mutation { commentCreate(newComment: { … }) { ok } }` | `Cannot query field 'commentCreate' on type 'RootMutation'` |
| `postWithCommentsCreate(newPost: { …, comments: [...] })` | `Field 'comments' is not defined by type 'PostCreateNestedCommentsType'` — the mutation survives, the **nested input field** does not |
| `postWithCommentsCreate(newPost: { … })`, no `comments` | `ok: true` — the parent write is theirs to make |
| `{ serverTime posts { totalCount } }` | resolves normally — untagged and readable fields are untouched |

The `comments` row is the 2.2.0 part: the nested `comments` input is stamped with
the **child's** permission, so a caller who may write posts but not comments
loses the nested surface while keeping the parent. Prune and gate are two halves
of one model — `/graphql/` is **not** pruned, which is exactly why
`permission_classes` (the runtime half, section 5) is the one you must not skip.

Flip `PERMISSION_SCOPED_SCHEMA` to `False` in `config/settings.py` and every
pruned field comes back.

---

## Query depth and cost limits

Both rules are wired into `GraphQLView`.

**`MAX_QUERY_DEPTH` is active** in this playground: `config/settings.py` ships
with `"MAX_QUERY_DEPTH": 6`, so any query nested more than 6 levels deep is
rejected immediately with a `QUERY_TOO_DEEP` error.

**`MAX_QUERY_COST`** is commented out (no budget enforced). Uncomment both lines
in `config/settings.py` to try cost analysis:

```python
DJANGO_GRAPHEX = {
    ...
    # MAX_QUERY_DEPTH is already active at 6 — change or remove to adjust.
    "MAX_QUERY_COST": 200,         # reject queries with estimated cost > 200
    "EXPOSE_QUERY_COST": True,     # add extensions.cost to every response
}
```

`PostType` already sets `max_depth = 4` and `complexity = 2` so per-type
enforcement is active for free. A query that nests more than 4 levels under a
`post` field is rejected with `QUERY_TOO_DEEP`, and the global `MAX_QUERY_DEPTH`
of 6 applies on top (most-restrictive rule wins).

---

## Private vs public fields

Public (works without auth):

```graphql
{ posts { results(limit: 2) { title } } serverTime categories { name } }
```

Private (requires a logged-in session; otherwise `Authentication required.`):

```graphql
{
  me { id username isSuperuser }
  myNotes { totalCount results { id title } }
}
```

`DjangoGraphQLSchema` unions the public and private roots and attaches the
protected field registry to the schema. `AuthenticatedFieldsMiddleware` reads
it at resolve time; the client cannot bypass it without an authenticated session.

---

## Subscriptions

Subscriptions run over the **native transports**: a `graphql-transport-ws`
WebSocket (`/ws/graphql/`) or Server-Sent Events (`POST /graphql/stream`).
The subscription document travels IN the transport — there is no separate
HTTP registration step.

The easiest way to try them is the built-in browser client at
<http://127.0.0.1:8000/graphql/client/>:

1. Press **Connect** — the client opens the WebSocket (or SSE stream).
2. Run the pre-filled `postSubscription(action: ALL_ACTIONS) { id title }`.
3. Trigger a change (create a `Post` via `postCreate`) — the event arrives
   instantly.

Manual WebSocket flow (`wscat -c ws://127.0.0.1:8000/ws/graphql/ -s graphql-transport-ws`):

```json
→ {"type": "connection_init"}
← {"type": "connection_ack"}
→ {"type": "subscribe", "id": "1",
   "payload": {"query": "subscription { postSubscription(action: ALL_ACTIONS) { id title } }"}}
```

Trigger a change from GraphiQL:

```graphql
mutation {
  postCreate(newPost: { title: "Live update", author: 1 }) { ok post { id } }
}
```

The socket delivers a standard GraphQL result frame:

```json
{ "type": "next", "id": "1",
  "payload": { "data": { "postSubscription": { "id": "21", "title": "Live update" } } } }
```

Unsubscribe with `{"type": "complete", "id": "1"}` (or just close the socket).
For SSE, POST the same document to `/graphql/stream` and read the
`event: next` frames (see the [Subscriptions guide](https://github.com/eamigo86/django-graphex/blob/main/docs/usage/subscriptions.md)
for the full wire protocol of both transports).

### Filtered subscription (per-post comments)

Subscribe with `filter: { post: { exact: <id> } }` to receive only that post's
comments:

```graphql
subscription {
  commentSubscription(action: ALL_ACTIONS, filter: { post: { exact: 1 } }) { id text }
}
```

Trigger it with a comment write — log in via `/admin` first, since
`commentCreate` is gated by `IsOwnerOrReadOnly` (the subscribe itself stays
public):

```graphql
# Delivered (post 1):
mutation { commentCreate(newComment: { post: 1, authorName: "Ada", text: "hi" }) { ok } }
# NOT delivered (different post):
mutation { commentCreate(newComment: { post: 2, authorName: "Bob", text: "yo" }) { ok } }
```

### Private subscription (auth-gated)

`noteSubscription` requires an authenticated session. The generated
subscription's `authorize_subscription` hook calls `NoteModelType.authorize`,
which denies an anonymous `subscribe` before any Channels group is joined. Log
in via `/admin` first, then subscribe from the same browser session.

The gate lives on the **type**, not only on the schema root. `subscribe` is a
READ action, so `IsAuthenticatedOrReadOnly` alone lets anonymous callers
through, and `AuthenticatedFieldsMiddleware` only protects the fields mounted
under `private_subscription`. `NoteModelType` therefore overrides `authorize`
and makes `subscription_scope` fail closed: with no user there is no
server-forced `{"owner": ...}` filter, and an unscoped notes subscription is
every user's notes.

```graphql
subscription {
  noteSubscription(action: ALL_ACTIONS) { id title }
}
```

---

## Views

| Route | View | Notes |
|-------|------|-------|
| `/graphql/` | `GraphQLView` | HTTP GraphQL + GraphiQL (queries + mutations) |
| `/graphql/stream` | `subscription_sse_view` | Native Server-Sent Events subscription transport |
| `/ws/graphql/` | `subscription_ws_consumer` | Native `graphql-transport-ws` WebSocket (see `config/asgi.py`) |
| `/graphql/client/` | `SubscriptionClientView` | Browser client for the subscription flow (WS + SSE) |
| `/graphql/secure/` | `AuthenticatedGraphQLView` | Same schema behind **view-level** HTTP 403 auth, and **pruned per caller** (`PERMISSION_SCOPED_SCHEMA`, [section 6](#6-a-schema-pruned-to-the-caller-22)) |

`AuthenticatedGraphQLView` rejects unauthenticated requests before any query
runs. Override `permission_classes` for custom gates:

```python
# urls.py
AuthenticatedGraphQLView.as_view(graphiql=True, permission_classes=(IsAdmin,))
```

> **Introspection:** GraphiQL needs introspection, so the playground ships with
> `ALLOW_INTROSPECTION = True`. Set it to `False` in `config/settings.py` to
> watch `DisableIntrospectionMiddleware` block it (superusers still bypass
> thanks to `INTROSPECTION_ALLOW_SUPERUSER = True` by default).

> **Static files:** under `daphne` (ASGI), static files are served by
> `ASGIStaticFilesHandler` in `config/asgi.py` while `DEBUG = True`. For
> production, run `make collectstatic` and serve `STATIC_ROOT` with a web
> server or whitenoise.
