# Playground Project

The repository ships a small, fully **runnable** Django project at
[`examples/playground/`](https://github.com/eamigo86/django-graphex/tree/main/examples/playground)
that exercises every major django-graphex feature end-to-end: queries with all
three paginators, filtering (including a custom `@filter_field`), N+1-safe
nested lists, the full query-optimization surface, a typed
`GenericForeignKey` union, directives, CRUD mutations with permissions,
descriptor-API hand-written mutations, file uploads on **both** paths (base64
in the JSON body and a multipart part), the
[projection security boundary](../types.md#projection-security-boundary) on all
three axes, the relation scoping hatch in both directions, query depth/cost
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
  **Tech / Life / News** and tagged with one of **django / graphql / python**.
  Each body **names its own tag** (`"Body of post 9 by author 13. Topic:
  django."`) so the custom `@filter_field` has something to find —
  `posts(filter: { search: "django" })` answers `totalCount: 20` rather than an
  empty page that reads like a broken example
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

    `get_queryset` is **field-level**, and the playground shows both sides of
    that. Anonymously:

    | Query | Statuses returned |
    |---|---|
    | `{ posts { results { status } } }` | `PUBLISHED` only |
    | `{ categories { name posts { title status } } }` | `PUBLISHED` only — `CategoryType.posts` is a mounted `DjangoFilterListField`, so the scope runs |
    | `{ authors { results { posts { results { status } } } } }` | `DRAFT`, `ARCHIVED`, `PUBLISHED` — the auto-expanded relation reads the prefetch cache, so `PostType.get_queryset` never runs |

    The third row is not a bug; it is the boundary the
    [scoping hatch](../types.md#relation-scope-hatch) exists to close, and the
    second row is that hatch mounted. Declaring it costs the relation its
    nested filter paths — see the table under
    [Filtering](../filtering.md#filter-refusal-shapes).

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
| **File uploads, base64** | `UploadDocument` accepts a `Base64FileInput`; `MAX_UPLOAD_SIZE` (5 MB) and `MAX_REQUEST_BODY_SIZE` (20 MB) guard it in `config/settings.py` | [Mutations](../mutations.md#file-upload-support) |
| **File uploads, multipart** | `DocumentMutation` (`DjangoModelMutation`, `model_operations = ("create", "update")`) → `documentCreate` / `documentUpdate`; a part named `attachedFile` **or** `attached_file` lands on the same `Document.attached_file` column — one column, two documented ways in | [Mutations](../mutations.md#automatic-multipart-uploads) |
| **Projection = security boundary** | `AuthorType` hides `bio`, `UserType` hides `password`, `CommentType` / `CommentModelType` hide `internal_note` on read **and** write — each unreadable, unorderable and unfilterable through its type | [Types](../types.md#projection-security-boundary) |
| **Relation scoping hatch** | to-MANY: `CategoryType.posts = DjangoFilterListField(PostType)`; to-ONE: `AuthorType.user = Field(UserType)` + `resolve_user`. Beside them `AuthorType.posts` stays the auto-expanded shape, so the pair shows what the hatch buys and costs | [Types](../types.md#relation-scope-hatch) |
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

## The projection boundary, live

`AuthorType` projects `bio` away. The rule says a hidden column is not
readable, not orderable and not filterable
([the canonical statement](../types.md#projection-security-boundary)) — here
are all three axes, anonymously, with the answers the playground returns. It
sets `ALLOW_INTROSPECTION = True`, so the `Did you mean …?` tails below are
present; flip that flag off and the tails are stripped while the messages
themselves stay.

| Query | Answer |
|---|---|
| `{ authors { results { bio } } }` | `Cannot query field 'bio' on type 'AuthorType'. Did you mean 'id'?` |
| `{ authors { results(ordering: "bio") { name } } }` | `Invalid ordering field: 'bio'.` |
| `{ authors(filter: { bio: { icontains: "x" } }) { totalCount } }` | `Field 'bio' is not defined by type 'AuthorFilterInput'. Did you mean 'id'?` |
| `{ authors { results(ordering: "name", page: 1) { name } } }` | the control — still sorts, `Author 0`, `Author 1`, `Author 10`, … |

The same rule is told on two columns where it matters more than on a bio:

| Query | Answer |
|---|---|
| `{ authors { results { user { password } } } }` | `Cannot query field 'password' on type 'UserType'.` — without the exclusion `Author.user` answers the hash to every **authenticated** caller. Anonymous ones are stopped one layer earlier by `resolve_user` (see the hatch table below), so this column has two independent walls |
| `{ comments { results(first: 1) { internalNote } } }` | `Cannot query field 'internalNote' on type 'CommentType'.` |
| `mutation { commentCreate(newComment: { post: 1, authorName: "a", text: "t", internalNote: "x" }) { ok } }` | `Field 'internalNote' is not defined by type 'CommentCreateGenericType_p84059c'.` — the same projection on the **write** input |

The to-ONE hatch closes the ordering axis on the key behind it:

| Query | Answer |
|---|---|
| `{ authors { results { name user { username } } } }` | `user: null` for an anonymous caller — `resolve_user` scopes it |
| `{ authors { results(ordering: "userId") { name } } }` | `Invalid ordering field: 'user_id'.` — the term is normalized to the column *before* it is judged, so the message names `user_id`, not what you sent |

!!! warning "One surface in this playground does **not** honour the same projection"
    `CommentSubscription` is a hand-written `Subscription` bound to
    `Meta.model = Comment`, so it compiles its event type and its
    `CommentSubscriptionFilterInput` from the **model** — `internalNote` is
    selectable and equality-filterable there while `CommentType` hides it. That
    is the third of the
    [open boundaries](../types.md#projection-exception) the rule states, and
    the remedy is one line: repeat `exclude_fields` in the subscription's own
    `Meta`. The playground leaves it open on purpose and pins it with a test
    that goes red the day it is closed.

## Uploading a file

`documentCreate` is a `DjangoModelMutation` over a model with a `FileField`, so
a multipart part named after the field is merged into the payload with no extra
configuration. GraphiQL cannot send multipart, so this one is a `curl` demo —
run it against `make run`:

```bash
curl -s http://127.0.0.1:8000/graphql/ \
  -H 'X-Requested-With: XMLHttpRequest' \
  -F 'query=mutation { documentCreate(newDocument: { name: "Notes" }) { ok document { id name attachedFile } } }' \
  -F 'attachedFile=@notes.txt'
```

```json
{"data":{"documentCreate":{"ok":true,"document":{"id":"1","name":"Notes","attachedFile":"documents/notes.txt"}}}}
```

Three variations worth running, because each one teaches a rule:

| Change | What happens |
|---|---|
| rename the part to `attached_file` | same landing column — the part name is matched against **both** the camelCase alias the SDL publishes and the model attribute. The stored path picks up a uniqueness suffix (`documents/notes_ciyKdvA.txt`) only because the first upload already took `documents/notes.txt` |
| misspell the part (`attachedFyle`) | `ok: true` with `attachedFile: ""` — a part matching no exposed input field is ignored, so a typo looks exactly like success |
| drop `-H 'X-Requested-With: …'` | **HTTP 403**, `This content type requires the X-Requested-With header. …`, before the body is read |

## Two settings that ship on, and are invisible until they bite

`config/settings.py` deliberately does **not** set either of these — both ship
enabled, and pinning a key to its own default only hides that you depend on it.
The file names and explains them in comments instead, so a reader copying it
meets both walls at their desk:

| Setting | Default | What you meet |
|---|---|---|
| [`REQUIRE_CSRF_HEADER`](../security.md#cross-site-post-protection) | `True` | the 403 in the upload table above. `application/json` clients — GraphiQL included — never see it |
| [`MAX_SUBSCRIPTIONS_PER_CONNECTION`](../subscriptions.md#per-connection-subscription-cap) | `50` | the 51st concurrent `subscribe` on **one** WebSocket is answered with an `error` frame naming the limit; the socket and every subscription already running on it keep going |

## Try subscriptions live

The playground serves the v2 native subscription engine behind both
standards-based transports: `graphql-transport-ws` on `/ws/graphql/` and SSE
(`graphql-sse` / `text/event-stream`) on `/graphql/stream`. The easiest way
to watch them work is the built-in browser client:

1. Open <http://127.0.0.1:8000/graphql/client/>. **WS** mode is
   pre-selected and already points at `/ws/graphql/`; press **Connect**.
2. Press the run (▶) button. The editor is already holding a **runnable**
   document — the client ships `yourSubscription(action: ALL_ACTIONS) { id }`
   and its introspection renames the placeholder to the first field this
   schema's subscription root advertises, which here is `postSubscription`.
   Widen the selection set if you want more than the id:

    ```graphql
    subscription {
      postSubscription(action: ALL_ACTIONS) {
        id
        title
        status
      }
    }
    ```

    The rename needs introspection, and this playground sets
    `ALLOW_INTROSPECTION = True` so it happens. On a project that leaves the
    flag off, the document still says `yourSubscription` and pressing ▶ answers
    `Cannot query field 'yourSubscription' on type 'Subscription'` until you
    type your own field name.

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
round-trip, the multipart upload in all four spellings, the projection boundary
on every axis it can reach, both arms of the relation hatch, and the two
settings that ship on:

```bash
make test          # 49 passed
```

Several of them assert the **verbatim** answer strings this page and the
project's own `README.md` quote, so a message that changes turns the suite red
instead of leaving the documentation quietly wrong.

## Where to go next

- [Sample Application](blog-schema.md) — the illustrative tutorial companion
- [Query Recipes](queries.md) and [Mutation Recipes](mutations.md)
- [Subscriptions](../subscriptions.md) — the full transport and engine guide
- [Query Optimization](../query-optimization.md) — what the optimizer does on
  every playground query
