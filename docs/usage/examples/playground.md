# Playground Project

The repository ships a small, fully **runnable** Django project at
[`examples/playground/`](https://github.com/eamigo86/django-graphex/tree/main/examples/playground)
that exercises every major django-graphex feature end-to-end: queries with all
three paginators, filtering (including a custom `@filter_field`), N+1-safe
nested lists, the full query-optimization surface, a typed
`GenericForeignKey` union, directives, CRUD mutations with permissions,
descriptor-API hand-written mutations, base64 file uploads, query depth/cost
limits, and native subscriptions over WebSocket and SSE.

!!! note "Playground vs. the tutorial"
    The [Sample Application](blog-schema.md) page is a **standalone,
    illustrative tutorial** — its models exist only to demonstrate framework
    concepts and are not backed by runnable code. The playground is the
    opposite: a **real project you clone, seed and run**, installing the
    library from the repo checkout (editable, via `[tool.uv.sources]`) — no
    PyPI release needed. Use the tutorial to learn the concepts and the
    playground to try them live.

## Quick start

You need [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone https://github.com/eamigo86/django-graphex.git
cd django-graphex/examples/playground

make install     # uv sync — installs the local library (editable) + daphne
make migrate     # generate + apply migrations (SQLite)
make seed        # load demo data (see below)
make run         # daphne ASGI server (HTTP + WebSocket) on 127.0.0.1:8000
```

Open **GraphiQL** at <http://127.0.0.1:8000/graphql/>. The seed creates the
superuser **`demo` / `demo12345`**.

All the `Makefile` targets:

| Target | What it does |
|--------|--------------|
| `make install` | `uv sync` — creates the venv, installs `django-graphex[subscriptions]` from the parent checkout (editable) plus `daphne` |
| `make migrate` | `makemigrations blog` + `migrate` (SQLite) |
| `make seed` | Loads the demo data via `python manage.py seed` |
| `make run` | Starts `daphne` (ASGI: HTTP **and** WebSocket) at `http://127.0.0.1:8000/` |
| `make superuser` | `createsuperuser` — create your own admin user |
| `make shell` | Django shell |
| `make test` | Runs the end-to-end test suite (WS + SSE subscription round-trips, schema and client smoke tests) |
| `make collectstatic` | Collects static files into `STATIC_ROOT` |
| `make reset` | Drops `db.sqlite3`, re-migrates, re-seeds |
| `make clean` | Removes the database and `__pycache__` caches |

## What the seed creates

`python manage.py seed` (idempotent — it clears the demo tables first) loads:

- **15 authors x 12 posts each** (180 posts), statuses cycling
  `DRAFT` / `PUBLISHED` / `ARCHIVED`, each post in one of the categories
  **Tech / Life / News** and tagged with one of **django / graphql / python**
- **3 comments per post** (540 comments)
- **12 private notes** owned by the demo user
- **2 accounts + 2 invoices + 4 attachments** — the attachments alternate
  between `Account` and `Invoice` targets so the typed
  `GenericForeignKey` union query returns **both** member types
- The superuser **`demo` / `demo12345`** (also linked to the first author)

The counts are deliberate: 12 posts per author is **more than the page size
of 10**, so nested `posts` lists span real multiple pages and the DB-side
window-pagination path (`ROW_NUMBER() OVER (PARTITION BY ...)`) is genuinely
exercised — try `results(offset: 10)` on a nested list. Scale the dataset
without editing code:

```bash
uv run python manage.py seed --authors 25 --posts 15   # explicit counts
uv run python manage.py seed --scale 2                 # doubles authors + posts
```

## Endpoints

| Route | View | Notes |
|-------|------|-------|
| `/graphql/` | `GraphQLView` | Queries + mutations over HTTP, with **GraphiQL** |
| `/graphql/secure/` | `AuthenticatedGraphQLView` | Same schema behind **view-level** auth — rejects anonymous requests with HTTP 403 before any query runs |
| `/graphql/stream` | `subscription_sse_view` | Native SSE subscription transport (`text/event-stream`) |
| `/ws/graphql/` | `subscription_ws_consumer` | Native `graphql-transport-ws` WebSocket (routed in `config/asgi.py`) |
| `/graphql/client/` | `SubscriptionClientView` | Self-contained [browser client](../subscriptions.md#browser-client-view) to try subscriptions live |
| `/admin/` | Django admin | Log in here to authenticate your GraphiQL session |

### Authenticating (private fields)

Auth is **Django session-based**. Private fields (`me`, `myNotes`, the note
mutations, `noteSubscription`) require a logged-in user:

1. Open <http://127.0.0.1:8000/admin/> and log in as `demo` / `demo12345`.
2. Return to GraphiQL — it shares the session cookie.

Log out of `/admin` to test the anonymous (public) behaviour again.

!!! tip "Anonymous users see fewer posts — on purpose"
    `PostType.get_queryset` scopes the base queryset per request: anonymous
    users only see `PUBLISHED` posts, authenticated users see everything.
    Compare `posts { totalCount }` before and after logging in — it is the
    [`get_queryset` hook](../permissions.md) working on every top-level field
    type.

## Schema tour

Everything lives in [`blog/schema.py`](https://github.com/eamigo86/django-graphex/blob/main/examples/playground/blog/schema.py)
(with settings in `config/settings.py`). What each part demonstrates:

| Feature | Where in the playground | Docs |
|---------|-------------------------|------|
| **All three paginators** | `PostListType` — `LimitOffsetGraphqlPagination(default_limit=10, ordering="-id")`; `AuthorListType` — `PageGraphqlPagination(page_size=10)`; `CommentListType` — `CursorGraphqlPagination(ordering="-created")` (exposes `pageInfo`) | [Pagination](../pagination.md) |
| **Filtering** | `Meta.filter_fields` on every object type, queried through the nested `filter:` argument | [Filtering](../filtering.md) |
| **Custom `@filter_field`** | `PostType.search` — `@filter_field(GraphQLString)` full-text search over title *and* body | [Filtering](../filtering.md) |
| **Nested lists (N+1-safe)** | `authors → posts → comments`, each independently paginated and filterable; `Post.tags` (M2M) nests automatically | [Nested Lists](../nested-lists.md) |
| **Query optimization** | `AuthorType.post_count = AnnotatedField(GraphQLInt, Count("posts"))` (annotation injected **only when selected**); the `AuthorType.optimize_posts` per-field hook; DB-side window pagination of nested pages — all `OPTIMIZE_*` settings are ON by default | [Query Optimization](../query-optimization.md) |
| **Typed GFK union** | `AttachmentTargetUnion` (`DjangoUnionType`, `Meta.types = (AccountType, InvoiceType)`) mapped via `AttachmentType.Meta.unions = {"target": AttachmentTargetUnion}` | [Types](../types.md) |
| **Directives** | `DjangoGraphQLSchema(..., directives=all_directives)` + `GraphQLDirectiveMiddleware` in `DJANGO_GRAPHEX["MIDDLEWARE"]` | [Directives](../../directives.md) |
| **Model CRUD mutations** | `PostMutation` (`DjangoModelMutation`) → `postCreate/Update/Delete`; `CommentModelType.MutationFields()` and `NoteModelType.MutationFields()` (`DjangoModelType`) → `commentCreate/Update/Delete` and `noteCreate/Update/Delete` | [Mutations](../mutations.md) |
| **Nested writes** | `PostWithCommentsMutation` — `Meta.nested_fields = {"comments": Comment}` creates a `Post` plus its comments in one atomic operation | [Mutations](../mutations.md#nested-fields-support) |
| **Descriptor-API mutations** | `CreateCategory` / `UploadDocument` — hand-written `Mutation` classes with `class Arguments` (`Field(CategoryInput, required=True)`, `CharField(required=True)`) and payload fields declared with `BooleanField()` / `CharField()` / `Field(CategoryType)` | [Mutations](../mutations.md) |
| **File uploads** | `UploadDocument` accepts a `Base64FileInput`; `MAX_UPLOAD_SIZE` (5 MB) and `MAX_REQUEST_BODY_SIZE` (20 MB) guard it in `config/settings.py` | [Mutations](../mutations.md) |
| **Permissions** | `NoteModelType.permission_classes = [IsAuthenticatedOrReadOnly]`; a custom `IsOwnerOrReadOnly(BasePermission)` assigned on `CommentModelType`, which is also the gate the nested `postWithCommentsCreate` runs for each inline comment; per-request scoping via `filter_queryset` (`myNotes` returns only your notes) | [Permissions](../permissions.md) |
| **Public/private schema split** | `DjangoGraphQLSchema(query=..., private_query=..., subscription=..., private_subscription=...)` + `AuthenticatedFieldsMiddleware` protects the private roots at resolve time | [Security](../security.md) |
| **Subscriptions** | Public `PostSubscription` / `CommentSubscription` (`payload_mode = "full"`, per-subscriber `filter`); private `NoteModelType.SubscriptionField()` with `subscription_scope` (server-forced "only my notes") and `subscription_index_fields = ("owner",)` | [Subscriptions](../subscriptions.md) |
| **Query limits** | Global `MAX_QUERY_DEPTH = 6` in settings; per-type `PostType.Meta.max_depth = 4` and `complexity = 2` (most-restrictive wins) | [Query Limits](../query-limits.md) |

!!! warning "Safe ordering, live"
    The ordering allowlist is active on all paginated fields. Try these in
    GraphiQL to see the anti-oracle guard reject them:

    - `posts { results(ordering: "author__user__password") { title } }` →
      `Relation-spanning ordering is not permitted`
    - `posts { results(ordering: "nonexistent") { title } }` →
      `Invalid ordering field`

## Starter queries

Paste these into GraphiQL at `/graphql/` right after `make seed` — they all
work anonymously.

=== "All three paginators"

    Limit/offset (`posts`), page (`authors`) and cursor (`comments`) — plus
    nested M2M tags and cursor-paginated nested comments in one request:

    ```graphql
    {
      posts(filter: { status: { exact: PUBLISHED } }) {
        totalCount
        results(limit: 5, ordering: "-id") {
          id
          title
          status
          author { name }
          tags { totalCount results { name } }
          comments {
            totalCount
            results(first: 2) { authorName text }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
      authors {
        totalCount
        results(page: 1) { name }
      }
      comments {
        totalCount
        results(first: 3) { text }
        pageInfo { hasNextPage endCursor }
      }
    }
    ```

=== "Custom filter + optimizer"

    `search` is the custom `@filter_field` (title **or** body); `postCount`
    is an `AnnotatedField` whose `Count()` is added to the SQL **only because
    it is selected**; the nested `posts` page is sliced DB-side with a window
    function:

    ```graphql
    {
      posts(filter: { search: "author 3" }) {
        totalCount
        results(limit: 5) { id title }
      }
      authors {
        results(page: 1) {
          name
          postCount
          posts(filter: { title: { icontains: "Post 1" } }) {
            totalCount
            results(limit: 3, ordering: "-id") {
              title
              status
              category { name }
            }
          }
        }
      }
    }
    ```

=== "Typed GFK union"

    Each `Attachment.target` is a `GenericForeignKey` exposed as a
    `DjangoUnionType` — select per-member fields with inline fragments. The
    seed mixes `Account` and `Invoice` targets so both branches return data:

    ```graphql
    {
      attachments {
        totalCount
        results {
          caption
          target {
            __typename
            ... on AccountType { label balance }
            ... on InvoiceType { number amount }
          }
        }
      }
    }
    ```

!!! tip "Try the directives too"
    Every directive from `all_directives` is registered. For example:

    ```graphql
    {
      posts {
        results(limit: 3) {
          title @uppercase
          slug: title @slugify
          teaser: body @truncate(length: 40)
        }
      }
    }
    ```

## Try subscriptions live

The playground serves the v2 native subscription engine behind both
standards-based transports: `graphql-transport-ws` on `/ws/graphql/` and SSE
(`graphql-sse` / `text/event-stream`) on `/graphql/stream`. The easiest way
to watch them work is the built-in browser client:

1. Open <http://127.0.0.1:8000/graphql/client/>. **WS** mode is
   pre-selected and already points at `/ws/graphql/`; press **Connect**.
2. Enter a subscription and press the run (▶) button:

    ```graphql
    subscription {
      postSubscription(action: ALL_ACTIONS) {
        id
        title
        status
      }
    }
    ```

3. Trigger a change from GraphiQL in another tab (any existing author id
   works — grab one with `{ authors { results(page: 1) { id name } } }`):

    ```graphql
    mutation {
      postCreate(newPost: { title: "Live update", author: 1 }) {
        ok
        post { id title }
      }
    }
    ```

    The client streams the `next` event with the new post instantly. Both
    playground subscriptions set `payload_mode = "full"`, so the whole
    serialized instance is deliverable — not just the `id`.

To try the **SSE** transport instead, switch the client's toggle to **SSE**
and set the SSE endpoint to `http://127.0.0.1:8000/graphql/stream` (the
playground mounts the SSE view on that route) before connecting.

More things to try:

- **Per-subscriber filters** — subscribe with
  `commentSubscription(action: ALL_ACTIONS, filter: { post: { exact: 1 } }) { id text }`
  and only that post's comments are delivered.
- **Private subscription** — log in at `/admin/` first, then subscribe to
  `noteSubscription(action: ALL_ACTIONS) { id title }` from the same browser
  session. It is gated by `AuthenticatedFieldsMiddleware`, and
  `subscription_scope` server-forces "only my notes" — another user's note
  changes never reach you.

## Run the test suite

The playground ships genuine end-to-end tests that drive the same consumer,
SSE view and schema the server runs — a WS round-trip (subscribe → ORM
`Post.objects.create()` → `next` frame received) and the equivalent SSE
round-trip, plus schema/permission and client smoke tests:

```bash
make test
```

## Where to go next

- [Sample Application](blog-schema.md) — the illustrative tutorial companion
- [Query Recipes](queries.md) and [Mutation Recipes](mutations.md)
- [Subscriptions](../subscriptions.md) — the full transport and engine guide
- [Query Optimization](../query-optimization.md) — what the optimizer does on
  every playground query
