# django-graphex — Playground

> **Targets django-graphex v1.3.x** — includes v1.1.0 query-optimization,
> v1.2.0 typed-GFK unions, and v1.2.2 `get_queryset` scoping + safe ordering.

A small, runnable Django project that exercises **every major feature** of
`django-graphex` end-to-end: queries, all three paginators, filtering,
generic single-object fields, nested lists (N+1-safe) with nested
pagination/filtering, choices→enum, directives, CRUD mutations with
permissions, query depth/cost limits, response caching, the full
**query-optimization surface** (DB-side window pagination, selection-driven
`AnnotatedField`, per-field `optimize_<field>` hooks, and typed
`GenericForeignKey` unions), and public + private subscriptions over Django
Channels.

It installs the library from the parent checkout (editable), uses **uv**,
**SQLite**, and a `Makefile`.

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
make seed        # demo data: 5 authors × 4 posts × 3 comments, 3 notes,
                 #            2 accounts + 2 invoices + 4 attachments (GFK union)
make run         # ASGI server at http://127.0.0.1:8000/graphql/
```

Open **GraphiQL** at <http://127.0.0.1:8000/graphql/>.

The seed creates superuser **`demo` / `demo12345`**.

> **No PyPI release needed.** `make install` installs the library **from this
> repo checkout** (editable) via `[tool.uv.sources]` in `pyproject.toml`.
> To install from a GitHub branch instead, swap to the commented `git = …`
> source in `pyproject.toml`.

### Authenticating (for private fields)

Private fields (`me`, `myNotes`, write mutations, `noteSubscription`) require
an authenticated user. Auth here is **Django session-based**:

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
| `DjangoUnionType` (typed GFK target) | ✅ | `schema.py` — `AttachmentTargetUnion` (`Meta.gfk_types`) + `AttachmentType.Meta.gfk_unions = {"target": …}` |
| `DjangoInterfaceType` | doc | Covered in `docs/usage/types.md`; not in the playground (no shared abstract base fits Account/Invoice cleanly) |
| `TextChoices` → GraphQL enum | ✅ | `Post.status` / `PostType` |
| `max_deep` per-type depth limit | ✅ | `schema.py` — `PostType.Meta.max_deep = 4` |
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
| `DjangoModelMutation` (full CRUD) | ✅ | `PostMutation`, `CommentMutation` → `postCreate/Update/Delete`, `commentCreate/Update/Delete` |
| `DjangoModelType.MutationFields()` | ✅ | `NoteModelType` → `noteCreate/Update/Delete` |
| `DjangoInputObjectType` on hand-written mutation | ✅ | `CategoryInput` / `createCategory` |
| Nested writes (`nested_fields` — reverse FK) | ✅ | `PostWithCommentsMutation` → `postWithCommentsCreate` |
| **Permissions** | | |
| `BasePermission` (custom subclass) | ✅ | `schema.py` — `IsOwnerOrReadOnly` |
| `AllowAny` | ✅ | imported; available for `permission_classes` |
| `IsAuthenticated` | ✅ | imported; available for `permission_classes` |
| `IsAuthenticatedOrReadOnly` | ✅ | `NoteModelType.permission_classes` |
| `IsAdmin` | ✅ | imported; available for `permission_classes` |
| `IsAdminOrReadOnly` | ✅ | imported; available for `permission_classes` |
| **Security / middleware** | | |
| `DisableIntrospectionMiddleware` | ✅ | `config/settings.py` GRAPHENE.MIDDLEWARE; toggle via `ALLOW_INTROSPECTION` |
| `AuthenticatedFieldsMiddleware` | ✅ | `config/settings.py` GRAPHENE.MIDDLEWARE |
| `GraphQLDirectiveMiddleware` | ✅ | `config/settings.py` GRAPHENE.MIDDLEWARE |
| `DjangoGraphQLSchema` (public + private roots) | ✅ | `schema.py` — `private_query=PrivateQuery`, `private_subscription=PrivateSubscriptions` |
| `collect_field_names` | note | Used internally by `DjangoGraphQLSchema`; can be called directly to build a custom protected-field set |
| `DenyAllRegistry` | note | Fail-closed sentinel for broken schemas; not needed in a healthy project |
| **Views** | | |
| `BaseGraphQLView` | ✅ | base of all views |
| `GraphQLView` (depth/cost rules, caching) | ✅ | base of `SubscriptionGraphQLView` at `/graphql/` |
| `AuthenticatedGraphQLView` | ✅ | `/graphql/secure/` — rejects unauthenticated requests with HTTP 403 |
| `SubscriptionGraphQLView` | ✅ | `/graphql/` |
| `SubscriptionClientView` | ✅ | `/graphql/client/` |
| **Query depth / cost limiting** | | |
| `DepthLimitValidationRule` | ✅ | Wired in `GraphQLView`; `PostType.Meta.max_deep = 4` activates per-type enforcement |
| `CostLimitValidationRule` | ✅ | Wired in `GraphQLView`; `PostType.Meta.complexity = 2`; enable budget via `MAX_QUERY_COST` |
| `analyze_cost` / `CostReport` | ✅ | Used internally by `GraphQLView.get_query_cost`; enable `EXPOSE_QUERY_COST` to see it |
| `MAX_QUERY_DEPTH` setting | ✅ | **Active at depth 6** in `config/settings.py:94` — the playground rejects any query nested more than 6 levels |
| `MAX_QUERY_COST` / `EXPOSE_QUERY_COST` | note | Commented in `config/settings.py` — uncomment to block expensive queries and expose cost |
| **Queryset optimization** | | |
| `OPTIMIZE_QUERYSET` | ✅ | Enabled by default; `select_related`/`prefetch_related` derived from the selection. Commented in `config/settings.py` to show how to flip it |
| `OPTIMIZE_ONLY_FIELDS` | ✅ | Enabled by default; `.only()` column narrowing (root span + inside each `Prefetch` child) |
| `OPTIMIZE_NESTED_PAGINATION` (DB-side window slicing) | ✅ | Exercised by `authors { results { posts(filter:…) { results(limit:…, ordering:…) } } }` — `ROW_NUMBER() OVER PARTITION BY author_id` slices each author's page DB-side |
| `OPTIMIZE_ANNOTATED_FIELDS` / `AnnotatedField` | ✅ | `schema.py` — `AuthorType.post_count = AnnotatedField(graphene.Int, Count("posts"))`; `Count` injected only when `postCount` is selected |
| Per-field `optimize_<field>` hook | ✅ | `schema.py` — `AuthorType.optimize_posts` (composes on the optimizer-built `posts` child queryset, once per query) |
| `OPTIMIZER_SAFE_MODE` | note | Default `False` (fail loud); listed commented in `config/settings.py` — flip to `True` to degrade to the un-optimized base on any optimizer exception |
| **Generic relations (typed GFK union)** | | |
| `GenericForeignKey` exposed as a typed `DjangoUnionType` | ✅ | `schema.py` — `AttachmentType.target` via `AttachmentTargetUnion` (`Meta.gfk_types`) + `Meta.gfk_unions` |
| Per-content-type `GenericPrefetch` narrowing (Django 5.0+) | ✅ | One `.only()`-narrowed queryset per content type (`AccountType.balance`, `InvoiceType.amount`), batched across all attachments |
| `GenericForeignKey` / `GenericRelation` prefetch | ✅ / wired | `Attachment.target` (GFK) exercised by the seed; `Post.attachments` (reverse `GenericRelation`) is wired but left empty so the GFK-union demo stays runnable |
| **File uploads (v1.3.0)** | | |
| `Base64FileInput` (opt-in) | ✅ | `schema.py` — `UploadDocument` mutation; `Document` model has a `FileField`. Try: `mutation { uploadDocument(name: "readme" file: {filename: "readme.txt" data: "<base64>" contentType: "text/plain"}) { ok name } }` |
| `MAX_UPLOAD_SIZE` | ✅ | `config/settings.py` — `5 * 1024 * 1024` (5 MB) |
| `MAX_REQUEST_BODY_SIZE` | ✅ | `config/settings.py` — `20 * 1024 * 1024` (20 MB body guard, fires before JSON parse) |
| **Response caching** | | |
| `CACHE_ACTIVE` / `CACHE_TIMEOUT` | note | Commented in `config/settings.py` — uncomment to activate query-result caching |
| **Subscriptions** | | |
| Public `Subscription` | ✅ | `PostSubscription` (stream `posts`), `CommentSubscription` (stream `comments`, per-subscriber `filters`) |
| Private subscription via `DjangoModelType` | ✅ | `NoteModelType.SubscriptionField()` — gated by `AuthenticatedFieldsMiddleware` |
| `subscription_scope` (server-forced row scope) | ✅ | `NoteModelType.subscription_scope` — only own notes |
| `subscription_index_fields` | ✅ | `NoteModelType.Meta.subscription_index_fields = ("owner",)` |
| `serialize_data` | ✅ | `PostSubscription`, `CommentSubscription`, `NoteModelType.Meta.serialize_data = True` |
| `GraphqlAPIDemultiplexer` | ✅ | `consumers.py` — `AppDemultiplexer` |

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
make reset          drop the SQLite db, re-migrate, re-seed
make clean          remove the db and caches
```

The `make run` command starts daphne at <http://127.0.0.1:8000/graphql/>.

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
`AuthorType.post_count = AnnotatedField(graphene.Int, Count("posts"))`.

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
`DjangoUnionType` with `Meta.gfk_types = (AccountType, InvoiceType)`); the owner
declares `Meta.gfk_unions = {"target": AttachmentTargetUnion}`. Clients select
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
> visible effect because graphene re-serializes the field through the enum type
> *after* the directive runs, always returning the enum name (`PUBLISHED`, etc.).
> Use `@lowercase` on plain text fields (like `title` above) where the
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

---

## Query depth and cost limits

Both rules are wired into `GraphQLView` (and therefore `SubscriptionGraphQLView`).

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

`PostType` already sets `max_deep = 4` and `complexity = 2` so per-type
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

Subscriptions use a **two-channel** protocol: a WebSocket carries
notifications, and an HTTP GraphQL operation registers/unregisters the
subscription using the channel ID from the WebSocket handshake.

The easiest way to try them is the built-in browser client at
<http://127.0.0.1:8000/graphql/client/>:

1. Press **Connect** — the client opens the WebSocket and receives a `channel_id`.
2. Press **▶ Subscribe** to send the subscribe HTTP call.
3. Trigger a change (create a `Post` via `postCreate`) — the WebSocket delivers
   a notification instantly.

Manual flow (for `wscat` / custom clients):

1. `wscat -c ws://127.0.0.1:8000/ws/graphql/` — receive `{ "channel_id": "…" }`.

2. Subscribe over HTTP (`/graphql/`):

   ```graphql
   subscription {
     postSubscription(
       channelId: "<channel_id>"
       action: ALL_ACTIONS
       operation: SUBSCRIBE
     ) { ok error stream operation action }
   }
   ```

3. Trigger a change:

   ```graphql
   mutation {
     postCreate(newPost: { title: "Live update", author: 1 }) { ok post { id } }
   }
   ```

   The WebSocket delivers:

   ```json
   { "stream": "posts",
     "payload": { "action": "create", "model": "blog.post",
                  "data": { "id": 21, "title": "Live update", "status": "draft" } } }
   ```

### Filtered subscription (per-post comments)

Subscribe with `filters: { post: <id> }` to receive only that post's comments:

```graphql
subscription {
  commentSubscription(
    channelId: "…"
    action: ALL_ACTIONS
    operation: SUBSCRIBE
    filters: { post: 1 }
  ) { ok error }
}
```

```graphql
# Delivered (post 1):
mutation { commentCreate(newComment: { post: 1, authorName: "Ada", text: "hi" }) { ok } }
# NOT delivered (different post):
mutation { commentCreate(newComment: { post: 2, authorName: "Bob", text: "yo" }) { ok } }
```

### Private subscription (auth-gated)

`noteSubscription` requires an authenticated session (gated by
`AuthenticatedFieldsMiddleware`). Log in via `/admin` first, then subscribe
from the same browser session.

```graphql
subscription {
  noteSubscription(channelId: "…", action: ALL_ACTIONS, operation: SUBSCRIBE) { ok error }
}
```

---

## Views

| Route | View | Notes |
|-------|------|-------|
| `/graphql/` | `SubscriptionGraphQLView` | HTTP GraphQL + GraphiQL; handles subscribe/unsubscribe |
| `/graphql/client/` | `SubscriptionClientView` | Browser client for the WebSocket subscription flow |
| `/graphql/secure/` | `AuthenticatedGraphQLView` | Same schema behind **view-level** HTTP 403 auth |

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
