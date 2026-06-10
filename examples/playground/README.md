# django-graphex — Playground

A small, runnable Django project that exercises **every major feature** of
`django-graphex` end-to-end: queries, all three paginators, filtering,
generic single-object fields, nested lists (N+1-safe) with nested
pagination/filtering, choices→enum, directives, CRUD mutations with
permissions, query depth/cost limits, response caching, queryset
optimization, and public + private subscriptions over Django Channels.

It installs the library from the parent checkout (editable), uses **uv**,
**SQLite**, and a `Makefile`.

---

## Quick start

```bash
cd examples/playground

make install     # uv sync — installs the local library + daphne
make migrate     # create + apply migrations (SQLite)
make seed        # demo data: 5 authors × 4 posts × 3 comments, 3 notes
make run         # ASGI server at http://127.0.0.1:8000/graphql
```

Open **GraphiQL** at <http://127.0.0.1:8000/graphql>.

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
| Filtering on list fields | ✅ | `posts(status: PUBLISHED, title_Icontains: "…")` |
| Filtered nested lists | ✅ | `authors { results { posts(title_Icontains: "…") } }` |
| **Nested lists (N+1-safe)** | | |
| `results` / `totalCount` wrapper | ✅ | Every list field |
| Nested FK list | ✅ | `Author → posts`, `Post → comments` |
| Nested M2M list | ✅ | `Post.tags` — `TagType` registration triggers automatic nesting |
| Multi-level nesting | ✅ | `authors → posts → comments` (all paginated independently) |
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
| `ExtraGraphQLDirectiveMiddleware` | ✅ | `config/settings.py` GRAPHENE.MIDDLEWARE |
| `ExtraGraphQLSchema` (public + private roots) | ✅ | `schema.py` — `private_query=PrivateQuery`, `private_subscription=PrivateSubscriptions` |
| `collect_field_names` | note | Used internally by `ExtraGraphQLSchema`; can be called directly to build a custom protected-field set |
| `DenyAllRegistry` | note | Fail-closed sentinel for broken schemas; not needed in a healthy project |
| **Views** | | |
| `BaseGraphQLView` | ✅ | base of all views |
| `GraphQLView` (depth/cost rules, caching) | ✅ | base of `SubscriptionGraphQLView` at `/graphql` |
| `AuthenticatedGraphQLView` | ✅ | `/graphql/secure` — rejects unauthenticated requests with HTTP 403 |
| `SubscriptionGraphQLView` | ✅ | `/graphql` |
| `SubscriptionClientView` | ✅ | `/graphql/client/` |
| **Query depth / cost limiting** | | |
| `DepthLimitValidationRule` | ✅ | Wired in `GraphQLView`; `PostType.Meta.max_deep = 4` activates per-type enforcement |
| `CostLimitValidationRule` | ✅ | Wired in `GraphQLView`; `PostType.Meta.complexity = 2`; enable budget via `MAX_QUERY_COST` |
| `analyze_cost` / `CostReport` | ✅ | Used internally by `GraphQLView.get_query_cost`; enable `EXPOSE_QUERY_COST` to see it |
| `MAX_QUERY_DEPTH` setting | note | Commented in `config/settings.py` — uncomment to activate global depth limit |
| `MAX_QUERY_COST` / `EXPOSE_QUERY_COST` | note | Commented in `config/settings.py` — uncomment to block expensive queries and expose cost |
| **Queryset optimization** | | |
| `OPTIMIZE_QUERYSET` | ✅ | Enabled by default; commented in `config/settings.py` to show how to flip it |
| `OPTIMIZE_ONLY_FIELDS` | ✅ | Enabled by default; commented in `config/settings.py` |
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

The `make run` command starts daphne at <http://127.0.0.1:8000/graphql>.

---

## Example GraphQL operations

### 1. Nested lists with all three paginators

```graphql
{
  # Limit/offset: posts
  posts(status: PUBLISHED) {
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
      posts(title_Icontains: "Post") {
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

### 2. Directives on string/numeric fields

```graphql
{
  posts {
    results(limit: 3) {
      title @uppercase
      slug: title @slugify
      teaser: body @truncate(length: 40)
      status @lowercase
    }
  }
}
```

All directives from `all_directives` are available: `@uppercase`,
`@lowercase`, `@capitalize`, `@titleCase`, `@camelCase`, `@snakeCase`,
`@kebabCase`, `@swapCase`, `@strip`, `@center`, `@replace`, `@truncate`,
`@slugify`, `@base64`, `@number`, `@currency`, `@default`, `@date`, `@abs`,
`@ceil`, `@floor`, `@round`, `@shuffle`, `@sample`, `@unique`.

### 3. Mutations with permissions + validation errors

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

### 4. Nested write — create a Post with inline Comments

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
They are **no-ops by default**; activate them by uncommenting the settings in
`config/settings.py`:

```python
DJANGO_GRAPHEX = {
    ...
    "MAX_QUERY_DEPTH": 6,          # reject queries nested > 6 levels
    "MAX_QUERY_COST": 200,         # reject queries with estimated cost > 200
    "EXPOSE_QUERY_COST": True,     # add extensions.cost to every response
}
```

`PostType` already sets `max_deep = 4` and `complexity = 2` so per-type
enforcement is active for free — even without `MAX_QUERY_DEPTH` in settings.
A query that nests more than 4 levels under a `post` field is rejected with
`QUERY_TOO_DEEP`, regardless of the global limit.

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

`ExtraGraphQLSchema` unions the public and private roots and attaches the
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

2. Subscribe over HTTP (`/graphql`):

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
| `/graphql` | `SubscriptionGraphQLView` | HTTP GraphQL + GraphiQL; handles subscribe/unsubscribe |
| `/graphql/client/` | `SubscriptionClientView` | Browser client for the WebSocket subscription flow |
| `/graphql/secure` | `AuthenticatedGraphQLView` | Same schema behind **view-level** HTTP 403 auth |

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
