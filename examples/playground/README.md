# django-graphex — Playground

A small, runnable Django project to try **every** feature of
`django-graphex` end to end: queries, the three paginations, filtering,
generic single-object fields, **nested lists** (N+1-safe) with **nested
pagination/filtering**, **choices → enum**, **directives**, **mutations** with
**permissions**, and **public + private subscriptions** over Django Channels.

It uses the library from the parent checkout (editable), **uv**, **SQLite**, and a
`Makefile`.

---

## Quick start

```bash
cd examples/playground

make install     # uv sync (installs the local library + daphne)
make migrate     # create + apply migrations (SQLite)
make seed        # demo data: 5 authors x 4 posts x 3 comments, 3 notes
make run         # ASGI server at http://127.0.0.1:8000/graphql
```

Open **GraphiQL** at <http://127.0.0.1:8000/graphql>.

The seed creates a superuser **`demo` / `demo12345`**.

> **No PyPI release needed.** `make install` installs the library **from this
> repo checkout** (editable), via `[tool.uv.sources]` in `pyproject.toml` — so it
> always uses the current checkout, not PyPI. To install from a GitHub branch
> instead, see the commented `git = …` source in `pyproject.toml`.

### Authenticating (for private fields)

Private fields (`me`, `myNotes`, write mutations, `noteSubscription`) require an
authenticated user. Auth here is **Django session based**:

1. Open <http://127.0.0.1:8000/admin> and log in as `demo` / `demo12345`.
2. Go back to GraphiQL — it shares the session cookie, so `request.user` is now
   authenticated.

Log out of `/admin` to test the anonymous (public) behavior.

> **Introspection:** GraphiQL needs introspection, so the playground ships with
> `DJANGO_GRAPHEX["ALLOW_INTROSPECTION"] = True`. Set it to `False` in
> `config/settings.py` to watch `DisableIntrospectionMiddleware` block it
> (superusers still bypass).

> **Static files:** under `daphne` (ASGI) static files (the admin CSS,
> `/static/...`) are served by the `ASGIStaticFilesHandler` in `config/asgi.py`
> while `DEBUG` is `True` — try <http://127.0.0.1:8000/static/playground.txt>.
> For production, run `make collectstatic` and serve `STATIC_ROOT` with a real
> web server (or whitenoise).

---

## What the schema exposes

| Area | Field(s) | Feature |
|------|----------|---------|
| Single object | `post(id)` | `DjangoObjectField` |
| List (limit/offset) | `posts` | `DjangoListObjectField` + `LimitOffsetGraphqlPagination` |
| List (page) | `authors` | `PageGraphqlPagination` |
| List (cursor) | `comments` | `CursorGraphqlPagination` + `pageInfo` |
| Filtered list | `categories` | `DjangoFilterListField` |
| Filtered + paginated flat list | `postsFlat` | `DjangoFilterPaginateListField` |
| Nested list | `authors → posts → comments` | `results`/`totalCount`, N+1-safe |
| Nested M2M list | `post.tags` | `results`/`totalCount` over a ManyToMany |
| Choices enum | `post.status` | `TextChoices` → GraphQL enum |
| Private | `me`, `myNotes` | `AuthenticatedFieldsMiddleware` |
| Mutations | `noteCreate/Update/Delete`, `postCreate/...`, `commentCreate/...` | `DjangoModelType` / `DjangoModelMutation` + permissions |
| Input type | `createCategory(data: …)` | `DjangoInputObjectType` on a hand-written mutation |
| Subscriptions | `postSubscription` (public), `commentSubscription` (public, with `filters`), `noteSubscription` (private) | Channels |
| Views | `/graphql`, `/graphql/secure` | `SubscriptionGraphQLView`, `AuthenticatedGraphQLView` |

---

## Queries

### Single object + a choices enum

```graphql
{
  post(id: 1) {
    id
    title
    status          # enum: DRAFT | PUBLISHED | ARCHIVED
    author { name }
    category { name }
  }
}
```

> **Where the arguments go:** **filter** arguments live on the **list field**
> (`posts(status: …)`); **pagination / ordering** arguments live on the
> **`results`** subfield (`results(limit: …, ordering: …)`).

### List with limit/offset pagination + filtering

```graphql
{
  posts(status: PUBLISHED, title_Icontains: "Post") {   # filters on the field
    totalCount
    results(limit: 5, offset: 0, ordering: "-id") {      # pagination on results
      id title status
    }
  }
}
```

### Page pagination

```graphql
{
  authors {
    totalCount
    results(page: 1) { name }   # page size is fixed by the type (10)
  }
}
```

### Cursor pagination + non-opaque pageInfo

```graphql
{
  comments {
    totalCount
    results(first: 3) { text }
    pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
  }
}
```

Take `endCursor` from the response and page forward:

```graphql
{ comments { results(first: 3, cursor: "<endCursor>") { text } pageInfo { hasNextPage } } }
```

### Plain filtered list

```graphql
{ categories(name_Icontains: "te") { id name } }
```

### Flat filtered + paginated list

`postsFlat` is a `DjangoFilterPaginateListField`: it filters like the list types
but returns a **plain list** (no `results`/`totalCount` wrapper), with the
pagination args on the field itself.

```graphql
{ postsFlat(status: PUBLISHED, limit: 5, offset: 0, ordering: "-id") { id title } }
```

---

## Nested lists (N+1-safe) + nested pagination / filtering

Each nested relation is a full list with `results`/`totalCount`. **Filter**
arguments go on the nested field, **pagination/ordering** on its `results`.

Deep nesting (authors → posts → comments), each level paginated:

```graphql
{
  authors {
    totalCount
    results(page: 1) {
      name
      posts {
        totalCount
        results(limit: 2, ordering: "-id") {
          title
          status
          comments {
            totalCount
            results(first: 2) { text }
          }
        }
      }
    }
  }
}
```

A **filtered** nested list (the headline N+1 demo):

```graphql
{
  authors {
    results(page: 1) {
      name
      posts(title_Icontains: "Post") {        # filter pushed into one Prefetch
        totalCount
        results(limit: 2, ordering: "-id") { title status }
      }
    }
  }
}
```

> **N+1:** with 5 authors this runs a constant number of queries (the filtered
> nested `posts` come from one `Prefetch`, not one query per author). Set
> `OPTIMIZE_QUERYSET = False` in settings to feel the difference, or inspect
> `django.db.connection.queries` in `make shell`. A **filter on a nested level**
> combined with a **deeper nested list on the same path** (filtered `posts` *and*
> their `comments`) is also N+1-safe — the deeper list is prefetched through the
> filtered parent's queryset.

A **ManyToMany** relation gets the same nested-list shape. `Post.tags` is exposed
because a `TagType` is registered:

```graphql
{ posts { results(limit: 2) { title tags { totalCount results { name } } } } }
```

---

## Directives

Add the directive middleware (already wired) and use `@directive` in queries:

```graphql
{
  posts {
    results(limit: 3) {
      title @uppercase
      slug: title @slugify
      teaser: body @truncate(length: 20)
      status @lowercase
    }
  }
}
```

Arguments can be variables:

```graphql
query($n: Int!) { posts { results(limit: 1) { title @truncate(length: $n) } } }
# variables: { "n": 8 }
```

---

## Mutations (DjangoModelType + permissions)

`noteCreate` / `noteUpdate` / `noteDelete` are gated by
`IsAuthenticatedOrReadOnly` — **you must be logged in** (see "Authenticating").
The current user is set as the note owner automatically.

```graphql
mutation {
  noteCreate(newNote: { title: "Hello", body: "from graphql" }) {
    ok
    errors { field messages }
    note { id title owner { username } }   # owner is set to the current user
  }
}
```

```graphql
mutation { noteUpdate(newNote: { id: 1, title: "Edited" }) { ok note { id title } } }
mutation { noteDelete(id: 1) { ok } }
```

Anonymous write → `errors: [{ extensions: { code: "PERMISSION_DENIED" } }]`.

A failing validation shows the error shape:

```graphql
mutation { noteCreate(newNote: { title: "" }) { ok errors { field messages } } }
```

### Explicit input type (DjangoInputObjectType)

`DjangoModelMutation` generates input types for you, but you can also declare one
explicitly with `DjangoInputObjectType` and use it as an argument on a
hand-written `graphene.Mutation`. `createCategory` does exactly that:

```graphql
mutation { createCategory(data: { name: "graphql" }) { ok category { id name } } }
```

---

## Private vs public

Public (works logged out):

```graphql
{ posts { results(limit: 2) { title } } serverTime }
```

Private (needs a logged-in user; otherwise `Authentication required.`):

```graphql
{
  me { id username isSuperuser }
  myNotes { totalCount results { id title } }   # scoped to YOUR notes
}
```

---

## Subscriptions (public + private)

Subscriptions use a **two-channel** protocol: a WebSocket carries the
notifications, and an HTTP GraphQL operation registers/unregisters the
subscription using the channel id from the WebSocket handshake.

1. **Open the WebSocket** to `ws://127.0.0.1:8000/ws/graphql/`. On connect it
   sends:

   ```json
   { "channel_id": "specific.channel!abc...", "connect": "success" }
   ```

2. **Subscribe** over HTTP (`/graphql`) using that `channelId`:

   ```graphql
   subscription {
     postSubscription(
       channelId: "specific.channel!abc..."
       action: ALL_ACTIONS          # CREATE | UPDATE | DELETE | ALL_ACTIONS
       operation: SUBSCRIBE         # or UNSUBSCRIBE
     ) { ok error stream operation action }
   }
   ```

3. **Trigger** a change with a mutation **on the same running server**
   (`/graphql`) — the `InMemoryChannelLayer` is per-process, so the change must
   happen inside the ASGI server, not a separate `make shell`:

   ```graphql
   mutation { postCreate(newPost: { title: "Hi", author: 1 }) { ok post { id } } }
   ```

   The WebSocket receives:

   ```json
   {
     "stream": "posts",
     "payload": { "action": "create", "model": "blog.post",
                  "data": { "id": 99, "title": "Hi", "status": "draft", ... } }
   }
   ```

### Filtering: only one post's comments

`commentSubscription` shows per-subscriber `filters`. On a post-detail page you
subscribe with `filters: {post: <id>}` and receive **only** that post's comments:

```graphql
subscription {
  commentSubscription(
    channelId: "…"
    action: ALL_ACTIONS
    operation: SUBSCRIBE
    filters: { post: 7 }          # only comments of post 7
  ) { ok error stream operation action }
}
```

Then create comments on different posts (same server) and watch the filter work:

```graphql
mutation { commentCreate(newComment: { post: 7, authorName: "Ada", text: "hi" }) { ok comment { id } } }  # delivered
mutation { commentCreate(newComment: { post: 9, authorName: "Bob", text: "yo" }) { ok comment { id } } }  # NOT delivered
```

The **private** subscription is `noteSubscription` (stream `notes`) — it is gated
by `AuthenticatedFieldsMiddleware`, so subscribing without a logged-in session
returns `Authentication required.`:

```graphql
subscription {
  noteSubscription(channelId: "…", action: ALL_ACTIONS, operation: SUBSCRIBE) {
    ok error
  }
}
```

> GraphiQL doesn't drive the two-channel WebSocket flow on its own. This
> playground mounts the built-in **browser client** at
> <http://127.0.0.1:8000/graphql/client/> (the `SubscriptionClientView`) — open
> it, press **Connect**, then **▶** to subscribe and watch notifications stream
> in. Trigger a change by creating a `Post` (in the admin or `make shell`).

---

## Views

`config/urls.py` mounts the schema behind three views:

| Route | View | Notes |
|-------|------|-------|
| `/graphql` | `SubscriptionGraphQLView` | HTTP GraphQL + GraphiQL; also handles the subscribe/unsubscribe handshake |
| `/graphql/client/` | `SubscriptionClientView` | A browser client for the WebSocket subscription flow |
| `/graphql/secure` | `AuthenticatedGraphQLView` | The **same schema** behind **view-level** auth |

`AuthenticatedGraphQLView` (a subclass of the plain `GraphQLView`) rejects
unauthenticated requests with **HTTP 403 before any query runs** — a coarser gate
than the per-field `AuthenticatedFieldsMiddleware`. Log in via `/admin`, then open
<http://127.0.0.1:8000/graphql/secure>; anonymous requests get a 403. Override the
gate with `permission_classes`:

```python
# urls.py
AuthenticatedGraphQLView.as_view(graphiql=True, permission_classes=(IsStaff,))
```

> **Offline / strict-CSP GraphiQL:** the views render GraphiQL from a CDN by
> default. Pass `graphiql_template="path/to/graphiql.html"` to
> `GraphQLView.as_view(...)` to render your own bundled template instead (it
> receives `endpoint` and `subscription_path` in the context).

---

## Make targets

```text
make install     uv sync (local library + daphne)
make migrate     makemigrations + migrate
make seed        load demo data
make run         daphne ASGI server (HTTP + WebSocket)
make collectstatic  collect static files into STATIC_ROOT
make superuser   create your own superuser
make shell       Django shell
make reset       drop the SQLite db, re-migrate, re-seed
make clean       remove the db and caches
```
