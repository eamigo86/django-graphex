# django-graphex — Playground

> **Targets the django-graphex 4.1.0 checkout with graphql-core 3.3 (no graphene).**
> Query-optimization, typed-GFK unions, `get_queryset` scoping + safe ordering,
> native subscriptions (SSE + WS), and the 2.2 permission story: nested writes
> authorized by the child, a schema pruned to the caller, safe account
> registration, and the 3.1 response-cache contract.

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

### The projection boundary

`Meta.only_fields` / `Meta.exclude_fields` are a **security boundary**, not an
output shape: a column a type projects away must not be **readable, orderable
or filterable** through that type. `AuthorType` here demonstrates it with one
line — `exclude_fields = ("bio",)` — and `Author.bio` is seeded with real
content, so every refusal below is a refusal to hand out data that exists:

```python
class AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        exclude_fields = ("bio",)
        filter_fields = {"id": ("exact",), "name": ("icontains",)}
```

Paste these into GraphiQL. All three axes close, and the fourth line is the
control that proves only the one column moved:

| Query | Answer |
|-------|--------|
| `{ authors { results(page: 1) { bio } } }` | `Cannot query field 'bio' on type 'AuthorType'. Did you mean 'id'?` |
| `{ authors { results(page: 1, ordering: "bio") { id } } }` | `Invalid ordering field: 'bio'.` |
| `{ authors(filter: { bio: { icontains: "x" } }) { totalCount } }` | `Expected value of type 'AuthorFilterInput' not to include unknown field 'bio'. Did you mean 'id'? Found: { bio: { icontains: "x" } }.` |
| `{ authors { results(page: 1, ordering: "name") { id name } } }` | The rows, ordered by name. |

The input-field wording can vary with graphql-core. With
`ALLOW_INTROSPECTION = True`, it may suggest `id`; flip the setting to `False`
(as the [Views section](#views) suggests) and that schema-derived suggestion
is stripped from rows 1 and 3. The rejection survives, including graphql-core
3.3's trailing `Found` clause, and row 2 is untouched:
`Invalid ordering field: 'bio'.` names the term *you* sent, not a schema member.

Ordering is refused at **query time**; filtering is refused earlier still.
Adding `"bio"` to that `filter_fields` dict does not drop the entry quietly —
it raises `ImproperlyConfigured` and the schema **stops building**, because a
`filter_fields` entry naming a projected-away column is a contradiction between
two `Meta` options and only you can say which half was meant. Try it: edit
`blog/schema.py` and run `make test`. Every test that imports the schema fails
with the same message, which names the `Meta` you just edited:

```text
AuthorType.Meta.filter_fields entry 'bio' names 'bio', which AuthorType does
not publish -- Meta.only_fields / Meta.exclude_fields removed it, or a declared
attribute publishes the name over a different value. […] Publish 'bio' on
AuthorType, or drop the entry.
```

`bio` is the teaching example; the schema applies the same one line to two more
columns, so you can read the rule where getting it wrong actually costs
something:

| Type | Column | What it would leak |
|------|--------|--------------------|
| `AuthorType` | `Author.bio` | Seeded prose — a value you can watch not come back |
| `UserType` | Every field except `id`, `username`, `first_name`, `last_name` | Password hashes, privilege flags, groups, permissions, login timestamps and unrelated reverse relations never enter the SDL. `only_fields` is safer here than trying to maintain a blacklist |
| `CommentType` + `CommentModelType` | `Comment.internal_note` | A moderation scratchpad — hidden on **reads and writes alike**, so the column is missing from `CommentFilterInput`, from `commentCreate`'s input **and** from the nested `comments` input under `postWithCommentsCreate` |

`tests/test_projection_boundary.py` pins every one of those. The full rule, its
one documented exception (an operator-configured `ordering=` default) and the
boundaries it cannot close live in
[the Types guide](https://github.com/eamigo86/django-graphex/blob/main/docs/usage/types.md#projection-security-boundary).

One boundary the library itself leaves open, and how the playground closes it:
`CommentSubscription` is a hand-written `Subscription` bound to
`Meta.model = Comment`, and it builds its event type and its filter input from
the **model**, not from `CommentType`'s projection. A subscription that declares
no projection of its own would therefore publish `internalNote` (selectable and
filterable) even though every query surface refuses it. The playground repeats
`exclude_fields = ("internal_note",)` in `CommentSubscription.Meta`, so
`internalNote` is absent from `CommentSubscriptionEvent` and
`CommentSubscriptionFilterInput`; `test_projection_boundary.py` pins both the
closure and the underlying library gap. Do the same on every model-bound
subscription you write.

### The relation-scope hatch

`PostType.get_queryset` hides `DRAFT` posts from anonymous callers. It runs on
every top-level field **and** on automatic FK and reverse-FK output reads, so an
anonymous caller never sees a draft through a relation either. The playground
still mounts the documented escape hatch for both arms, because the declaration
changes the wire shape and makes the filter-axis contract explicit:

| Query (run it logged out) | Drafts? | Why |
|---|---|---|
| `{ posts { results { title status } } }` | hidden | Top-level field: the hook runs |
| `{ categories { name posts { title status } } }` | hidden | **to-MANY hatch**: `CategoryType.posts = DjangoFilterListField(PostType)` carries a resolver, and the resolver runs the hook. The wire shape is a plain list |
| `{ authors { results { posts { results { status } } } } }` | hidden | Auto-expanded container: the automatic reverse-FK read applies `PostType.get_queryset` to its rows and to `totalCount` |
| `{ authors { results { name user { username } } } }` | `user: null` | **to-ONE hatch**: `AuthorType.user = Field(UserType)` + `resolve_user`. A bare `resolve_user` with no declaration does *nothing* |

Rows 2 and 3 differ only in wire shape (plain list versus `results` /
`totalCount` container); `tests/test_relation_scope_hatch.py` pins that both hide
drafts. The hatch is no longer needed merely to hide drafts.

**Declaring either arm costs the relation its other two axes**, because a
relation served by your own resolver is a *mask* — what the client reads is
what the callable returns, not what the row holds:

| Axis | What happens |
|---|---|
| `ordering` | `{ authors { results(ordering: "userId") { name } } }` → `Invalid ordering field: 'user_id'.` The term is normalized to the column first, so `"user_id"` is refused identically. Ranking rows by the raw foreign key reads a key no type in the schema hands out |
| `filter` | A `filter_fields` entry through the declared relation — `{"posts__title": ("icontains",)}` on `CategoryType`, `{"user": ("exact",)}` on `AuthorType` — **stops the schema building** with `ImproperlyConfigured`. That entry compiles to an ORM join that reaches exactly the rows the resolver hides |

The to-MANY arm costs less than the to-ONE arm: a reverse FK owns no column on
the parent row, so **nothing leaves the ordering allowlist** on `CategoryType`
and only the nested `posts__…` filter paths go. `PostType.author` is the
control — no resolver, so it keeps both axes and
`posts { results(ordering: "authorId") { title } }` still sorts.

`tests/test_relation_scope_hatch.py` pins all of it.

Generated mutation ID links have a **different** boundary from these read
paths: `commentCreate` linking `Comment.post` by ID now checks the destination
`PostType.get_queryset` before writing the comment. Anonymous callers already
fail the playground's comment write permission; authenticated callers see the
full Post queryset. This does not make row scope global for auto-expanded reads
or relation-filter joins. See
[mutation ID-link migration](../../docs/usage/mutations.md#migrating-id-links-hidden-by-a-destination-scope).

### Safe ordering (anti-oracle hardening)

The ordering allowlist is active on all paginated fields. Beyond the projection
above, it rejects relation-spanning and non-existent terms:

| Query | Error |
|-------|-------|
| `posts { results(ordering: "author__user__password") { title } }` | `Invalid ordering field: 'author__user__password'. Relation-spanning ordering is not permitted.` |
| `posts { results(ordering: "nonexistent") { title } }` | `Invalid ordering field: 'nonexistent'.` |

Try these in GraphiQL to see the guard in action.

---

## Quick start

```bash
cd examples/playground

make install     # uv sync --group test — local library + daphne + test tools
make migrate     # create + apply migrations (SQLite)
make seed        # demo data: 15 authors × 12 posts × 3 comments, 12 notes,
                 #            2 accounts + 2 invoices + 4 attachments (GFK union).
                 #            Each author has 12 posts (4 published), so logged in
                 #            their posts list spans two pages at page size 10 and
                 #            nested window pagination is real; logged out you see
                 #            only the 4 published ones (one page).
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
writes, `postUpdate`, `postDelete`, `documentUpdate`, and
`postWithCommentsCreate` **when it carries a `comments` list** require an
authenticated user. Exactly these writes are deliberately open to anonymous
callers, so you can compare a gated write against an ungated one:

| Open mutation | Why it is open |
|---|---|
| `postCreate` | Drives the public `postSubscription` demo without a session |
| `postWithCommentsCreate` (no `comments`) | Behaves like `postCreate`; with comments the child's `IsOwnerOrReadOnly` gate applies |
| `createCategory` | Hand-written mutation demo (duplicate names return `ok: false`) |
| `documentCreate` | The multipart `curl` demo needs no session |
| `uploadDocument` | The base64 upload demo |
| `registerUser` | Account registration is public by nature |

The destructive or modifying siblings, `postUpdate`, `postDelete` and
`documentUpdate`, are mounted under `PrivateMutation`
(`private_mutation=` on `DjangoGraphQLSchema`), so `AuthenticatedFieldsMiddleware`
answers an anonymous call with `Authentication required.`. `DjangoModelMutation`
honors no `permission_classes`, so a private root is the supported way to gate
one of its operations; use a `DjangoModelType` (as `NoteModelType` does) when you
need per-action or per-object rules. Any logged-in user may update or delete any
post here; add an ownership check for real data. Auth here is **Django
session-based**:

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
| `only_fields` / `exclude_fields` as a **security boundary** | ✅ | `schema.py` — `UserType` allowlists only four safe profile fields; `AuthorType` hides `bio`; `CommentType` + `CommentModelType` hide `internal_note` on **reads and writes alike** (including the nested child input). Each excluded field is unreadable, unorderable **and** unfilterable — see [The projection boundary](#the-projection-boundary) |
| Relation-scope hatch, to-**MANY** arm | ✅ | `schema.py` — `CategoryType.posts = DjangoFilterListField(PostType)` (plain-list wire shape) runs `PostType.get_queryset`; the auto-expanded `AuthorType.posts` container beside it applies the same hook — see [The relation-scope hatch](#the-relation-scope-hatch) |
| Relation-scope hatch, to-**ONE** arm | ✅ | `schema.py` — `AuthorType.user = Field(UserType)` + `resolve_user`; a bare `resolve_user` with no declaration would be silently ignored |
| `get_queryset` (per-request row scoping) | ✅ | `schema.py` — `PostType.get_queryset` hides drafts from anonymous callers. It also scopes automatic FK / reverse-FK reads; filters, custom resolvers and ID links keep their own contracts — see [The relation-scope hatch](#the-relation-scope-hatch) |
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
| `CursorGraphqlPagination` | ✅ | `CommentListType` — also exposes `pageInfo`; omitting `first` inherits this Playground's `DEFAULT_PAGE_SIZE = 10`, with a `MAX_PAGE_SIZE = 100` cap |
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
| `DjangoModelMutation` (full CRUD) | ✅ | `PostMutation` → `postCreate` (open) and `postUpdate/Delete` (mounted under `PrivateMutation`, login required) |
| `private_mutation` (auth-gated mutation root) | ✅ | `schema.py` — `PrivateMutation`: `postUpdate`, `postDelete`, `documentUpdate`; pinned by `tests/test_write_access.py` |
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
| `PERMISSION_SCOPED_SCHEMA` (pruned per-caller schema) | ✅ | `config/settings.py` — active; visible at `/graphql/secure/` — see [A schema pruned to the caller](#6-a-schema-pruned-to-the-caller-22) |
| `API_ACCESS_GROUP` | not used | Endpoint-wide group gate; the playground keeps `/graphql/` public on purpose. Set it in `config/settings.py` to lock the endpoint to one Django `Group` |
| **Security / middleware** | | |
| `DisableIntrospectionMiddleware` | ✅ | `config/settings.py` DJANGO_GRAPHEX.MIDDLEWARE; toggle via `ALLOW_INTROSPECTION` — flipping it also strips the `Did you mean …?` tail from schema-derived errors, see [Views](#views) |
| `REQUIRE_CSRF_HEADER` (cross-site POST guard) | ✅ default | **Inherited, not set** — `config/settings.py` names it in a comment and leaves the default alone. A CORS-simple POST (form-encoded, multipart, `text/plain`, or no content type) needs `X-Requested-With` or gets HTTP 403 — see [Security defaults you inherit](#security-defaults-you-inherit) |
| `MAX_SUBSCRIPTIONS_PER_CONNECTION` | ✅ default | **Inherited, not set** — 50. One WebSocket may hold 50 concurrent operations; the 51st gets an `error` frame naming the limit and the socket plus its running subscriptions keep going |
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
| `CostLimitValidationRule` | wired, **off by default** | Wired in `GraphQLView` but enforces nothing until `MAX_QUERY_COST` is set (commented in `config/settings.py`); `PostType.Meta.complexity = 2` weights `Post` fields |
| `analyze_cost` / `CostReport` | wired, **off by default** | Used internally by `GraphQLView.get_query_cost`; enable `EXPOSE_QUERY_COST` to see it |
| `MAX_QUERY_DEPTH` setting | ✅ | **Active at depth 6** in `config/settings.py` (the `DJANGO_GRAPHEX` block) — the playground rejects any query nested more than 6 levels |
| `MAX_QUERY_COST` / `EXPOSE_QUERY_COST` | note (off by default) | Commented in `config/settings.py` with a measured `10_000_000` budget — uncomment to block expensive queries and expose cost; see [Query depth and cost limits](#query-depth-and-cost-limits) |
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
| **File uploads** | | |
| Automatic **multipart** upload (2.2.0) | ✅ | `schema.py` — `DocumentMutation` → `documentCreate` / `documentUpdate`; a part named after a `FileField` the input exposes is merged and saved, with **no configuration at all** — see [Multipart uploads](#7-multipart-uploads-22) |
| `Base64FileInput` (opt-in, v1.3.0) | ✅ | `schema.py` — `UploadDocument` mutation, writing the same `Document.attached_file` column. Try: `mutation { uploadDocument(name: "readme" file: {filename: "readme.txt" data: "<base64>" contentType: "text/plain"}) { ok name document { id name attachedFile created } } }` — the `document` payload field is what mounts `DocumentType` on the schema |
| `MAX_UPLOAD_SIZE` | ✅ | `config/settings.py` — `5 * 1024 * 1024` (5 MB) |
| `MAX_REQUEST_BODY_SIZE` | ✅ | `config/settings.py` — `20 * 1024 * 1024` (20 MB body guard, fires before JSON parse) |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` (Django's own) | ✅ | `config/settings.py` — raised to 20 MB to match. A base64 upload travels inside the JSON body, so Django's 2.5 MB default refuses a 5 MB file with an opaque HTML 400 before either library cap sees it. Multipart never needs it — it streams to disk |
| **Response caching** | | |
| `CACHE_ACTIVE` / `CACHE_TIMEOUT` | ✅ safe default | `CACHE_ACTIVE=False` is explicit in `config/settings.py`. If enabled later, the default `should_cache_query()` bypasses requests with cookies so session/cart context is not shared accidentally |
| `CACHE_INVALIDATION_SCOPE` | ✅ | `"global"` is explicit: a successful mutation invalidates reads cached by every identity. `"identity"` preserves the narrower 3.0 mode and is only safe for fully private caches |
| **Subscriptions** | | |
| Public `Subscription` | ✅ | `PostSubscription` (stream `posts`), `CommentSubscription` (stream `comments`, per-subscriber `filter`) |
| Private subscription via `DjangoModelType` | ✅ | `NoteModelType.SubscriptionField()` — gated by `AuthenticatedFieldsMiddleware` |
| `subscription_scope` (server-forced row scope) | ✅ | `NoteModelType.subscription_scope` — only own notes; `PostSubscription.subscription_scope` — anonymous subscribers receive published posts only, mirroring `PostType.get_queryset` |
| `subscription_index_fields` | ✅ | `NoteModelType.Meta.subscription_index_fields = ("owner",)` |
| `payload_mode` | ✅ | `PostSubscription`, `CommentSubscription`, `NoteModelType.Meta.payload_mode = "full"` |
| Native WS consumer (`subscription_ws_consumer`) | ✅ | `consumers.py` — `AppWSConsumer` |
| SSE heartbeat (`SSE_HEARTBEAT_ENABLED`) | not demonstrated | Commented, off by default in `config/settings.py`; needs no Redis, so you can uncomment it. Not exercised by the suite |
| SSE connection lease (`SSE_CONNECTION_LIMIT_ENABLED`, per-account cap) | not demonstrated | Commented in `config/settings.py`; it needs a shared Redis URL, which a local playground does not run. See the [subscription guide](../../docs/usage/subscriptions.md#sse-connection-controls) for lease expiry and failover limits |
| WS `on_connect` credential hook | not demonstrated | `AppWSConsumer` uses the default session auth; the hook needs a project-specific token verifier. See [Optional connection authentication](../../docs/usage/subscriptions.md#optional-connection-authentication) |
| `BigInt` scalar (4.1) | ✅ | `models.py` — `Post.view_count` (`BigIntegerField`); the seed gives the first post `2**53 + 1` and leaves it a **draft**, so log in first (anonymous callers never see drafts) and run `{ postsFlat(ordering: "-viewCount", limit: 1) { id viewCount } }`: it answers the string `"9007199254740993"`, and `viewCount: "…"` is the matching input |
| `Decimal` scalar (4.1) | ✅ | `Account.balance` / `Invoice.amount` (`DecimalField`) serialize as strings: `{ attachments { results { target { ... on AccountType { balance } } } } }` answers `balance: "1200.50"`, not a float |

---

## How to run

```text
make install        uv sync --group test (local library + daphne + test tools)
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

> **Updating an existing checkout.** `blog/migrations/0*.py` is gitignored, so
> a fresh clone is never affected. But if you ran `make migrate` before
> pulling, `makemigrations` may ask you to confirm a column **rename**
> (`Document.file` became `Document.attached_file`). The prompt defaults to
> *no*, which drops the column and its stored files — and with no TTY it fails
> outright with `EOFError`. Run `make reset` instead: the playground's database
> is demo data, so throwing it away costs nothing.

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
- **Safe account boundary** — `UserType` exposes exactly four read-only fields,
  `/graphql/secure/` rejects anonymous reads, and public `registerUser` hashes
  the password while leaving `is_staff` and `is_superuser` false.
- **3.1 cache defaults** — caching starts disabled, invalidation scope is global,
  and the default cache hook refuses cookie-dependent queries.
- **Permissions: nested + pruned** (`test_permissions_nested_and_scoped.py`) —
  the two demos above, over the wire: an anonymous caller denied `commentCreate`
  is denied the same write through `postWithCommentsCreate` (and the parent
  `Post` rolls back), while `/graphql/secure/` serves each caller a schema
  pruned to their Django model permissions.
- **Projection boundary** (`test_projection_boundary.py`) — all three columns
  the schema projects away, pinned unreadable, unorderable and unfilterable
  over the wire, with a published column ordered successfully as the control.
  The answers this README quotes are asserted **verbatim**, on both sides of
  the `ALLOW_INTROSPECTION` toggle, so the two sections cannot contradict each
  other. `Comment.internal_note` is pinned on the write inputs too, standalone
  and nested.
- **Relation-scope hatch** (`test_relation_scope_hatch.py`) — both arms scope
  their relation for an anonymous caller, the auto-expanded reverse-FK and
  reverse-M2M shapes beside them hide drafts too, and the ordering and filter
  axes the declaration costs are pinned closed with a non-masked relation as the
  control.
- **Open and gated writes** (`test_write_access.py`) — the writes the README
  lists as open accept an anonymous caller; `postUpdate`, `postDelete` and
  `documentUpdate` are refused until login and change nothing.
- **Registration** (`test_registration.py`) — weak and username-similar
  passwords are refused, a duplicate username gets the generic message, and a
  valid password still registers.
- **Cost budget** (`test_cost_budget.py`) — every plain query this README shows
  runs under the suggested `MAX_QUERY_COST`, reports its cost, and an unbounded
  nested list is refused.
- **Scalars, media, upload errors** (`test_scalars_media_uploads.py`) — `BigInt`
  strings in and out, uploaded files served while `DEBUG` is on, and an
  unexpected upload failure answered generically while the detail is logged.
- **Public subscription scope** (`test_subscription_transports_e2e.py`) — an
  anonymous `postSubscription` never receives a draft over WebSocket or SSE,
  while a logged-in subscriber does.
- **Multipart uploads** (`test_multipart_upload.py`) — `documentCreate` saves a
  part under either spelling, ignores an unmatched part while still answering
  `ok: true`, and is refused HTTP 403 without `X-Requested-With`. Uploads are
  written into a tmp `MEDIA_ROOT`, so a run leaves no files behind.
- **Shipped defaults** (`test_shipped_defaults.py`) — the two settings this
  project inherits without configuring them:
  `REQUIRE_CSRF_HEADER` (here) and `MAX_SUBSCRIPTIONS_PER_CONNECTION` (in the
  transports module, where the WS communicator lives).
- **Subscription client** — `/graphql/client/` serves the HTML client with both
  transports (graphql-transport-ws + graphql-sse) and the playground's WS/HTTP
  endpoints wired, and the document it ships **pre-filled parses and validates
  against this schema** after the client's own placeholder rewrite — which is
  the exact thing step 2 of the [subscriptions walkthrough](#subscriptions)
  tells you to press Run on. (A full headless-browser round-trip is
  intentionally deferred — no Playwright/Selenium dependency is added.)

Run them with **make** (uses `uv`; `make install` already installs the `test`
dependency group, and `make test` requests it again so it also works on an
environment created with a plain `uv sync`):

```bash
cd examples/playground
make install
make test
```

Without `make`, the same thing with `uv`:

```bash
cd examples/playground
uv sync --group test
uv run --group test pytest -q --no-migrations
```

Or directly, with any environment that already has `pytest`, `pytest-django`,
`pytest-asyncio`, `channels`, and `daphne` available (e.g. the repo's own dev
venv) — `--no-migrations` builds the test DB straight from the models, since
the playground ships no migration files. The playground has no coverage
plugin configured, so there is no `--no-cov` flag to pass:

```bash
cd examples/playground
DJANGO_SETTINGS_MODULE=config.settings python -m pytest tests/ -q --no-migrations
```

The shipped `ALLOWED_HOSTS` contains only `127.0.0.1`, `localhost`, and
`testserver` (the host Django's test client and Channels' test communicator
use, so the suite can connect; remove it from a copy that does not run these
tests). This keeps `AllowedHostsOriginValidator` effective for the
session-authenticated WebSocket endpoint. If you expose the playground through
a tunnel or proxy, add that hostname explicitly — do not replace the list with
`["*"]`.

### These settings are not production-ready

`config/settings.py` is a development fixture, and `manage.py check --deploy`
says so with seven warnings: `DEBUG = True`, a short hard-coded `SECRET_KEY`, no
`SECURE_HSTS_SECONDS`, no `SECURE_SSL_REDIRECT`, insecure session and CSRF
cookies, and no `XFrameOptionsMiddleware`. Copy the patterns (the
`DJANGO_GRAPHEX` block, the schema wiring), not the file, and set those values
deliberately. Uploaded files are served by Django only while `DEBUG` is on
(`MEDIA_URL` in `config/urls.py`); in production a web server or object store
serves them.

---

## Example GraphQL operations

> **Ids in the examples assume a fresh database** (`make reset`, which drops the
> database, migrates and seeds). `make seed` on a database that already has rows
> deletes and recreates them, and SQLite keeps counting, so the new ids no longer
> start at 1. Look the id up first (`{ postsFlat(limit: 1) { id title } }`) and
> substitute it where an example says `id: 1` or `author: 1`.

### 0. Safe account registration and authenticated reads

Account creation is a purpose-built mutation on the public `/graphql/`
endpoint. It accepts **only** `username` and `password`, delegates to Django's
`create_user()` (so the password is hashed), and cannot set staff/superuser,
groups, or permissions:

```graphql
mutation {
  registerUser(username: "reader", password: "correct-horse-battery-staple") {
    ok
    error
    user { id username firstName lastName }
  }
}
```

The password goes through Django's `AUTH_PASSWORD_VALIDATORS` (set in
`config/settings.py`) before the account exists, so `password: "x"` answers
`ok: false` with the validator messages ("This password is too short…") and
creates nothing. The username goes through the `User` model's own field rules
first (no spaces or NUL bytes, at most 150 characters, not blank, NFKC-normalised
like the admin), and a refusal is `ok: false` with Django's message. A **taken username** answers `ok: false` with the generic
`Registration failed. Try different details.`, never the raw database error. That
removes the table name and the verbatim "already exists" text, but a public
sign-up still lets someone who tries a strong password tell a free name from a
taken one, so add rate limiting or e-mail verification before exposing it.

There is deliberately no generated `userCreate`, `userUpdate`, or
`userDelete`. Read the current user after logging in with a Django session.
Any logged-in user can run `me` on `/graphql/`; `/graphql/secure/` serves it
only to a caller whose pruned schema includes it (the seeded `demo` superuser
always does, an ordinary user does not):

```graphql
{
  me { id username firstName lastName }
}
```

`UserType.Meta.only_fields` is the last wall: even an authenticated caller
cannot select `password`, `isStaff`, `isSuperuser`, groups, permissions, or
login metadata. The public route remains available because it also hosts the
registration demo; application user reads belong on the authenticated route.

**An account made by `registerUser` cannot log in anywhere in this project.**
It is not staff, the Django admin login accepts staff only, and the playground
ships no other login view, so the registration demo ends at `ok: true`. To
read `me` as a session user, log in at `/admin` as the seeded `demo` /
`demo12345` (or as a staff user you create with `manage.py createsuperuser`, or
as `editor` from [section 6](#6-a-schema-pruned-to-the-caller-22)).

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

A failing validation returns `ok: false` and the `errors` list. Generated
writes check the column's type, nullability and `max_length` (Pydantic) **and**
run its Django validators, including `blank=False`. A title over
`Note.title`'s `max_length=200`:

```graphql
mutation { noteCreate(newNote: { title: "xxx… 250 chars …xxx" }) { ok errors { field messages } } }
```

```json
{ "data": { "noteCreate": { "ok": false,
  "errors": [{ "field": "title", "messages": ["String should have at most 200 characters"] }] } } }
```

An empty `title: ""` is refused too, with Django's own message
(`"This field cannot be blank."`), because `Note.title` is `blank=False`:

```json
{ "data": { "noteCreate": { "ok": false,
  "errors": [{ "field": "title", "messages": ["This field cannot be blank."] }] } } }
```

Model-level `Model.clean()` is not run; for rules that live outside the column
use an inline `validate_<field>` hook — see
[Custom validation](https://eamigo86.github.io/django-graphex/usage/backends/#custom-validation-inline-validate_field).

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
| `mutation { noteCreate(newNote: { title: "x" }) { ok } }` | `Cannot query field 'noteCreate' on type 'Mutation'. Did you mean 'postCreate'?` |
| `mutation { commentCreate(newComment: { … }) { ok } }` | `Cannot query field 'commentCreate' on type 'Mutation'. Did you mean 'documentCreate', 'postCreate', or 'documentUpdate'?` |
| `postWithCommentsCreate(newPost: { …, comments: [...] })` | Rejected: `comments` is not an input field of `PostCreateNestedCommentsType`; the mutation survives, the **nested input field** does not. |
| `postWithCommentsCreate(newPost: { … })`, no `comments` | `ok: true` — the parent write is theirs to make |
| `{ serverTime posts { totalCount } }` | resolves normally — untagged and readable fields are untouched |

The first two rows are quoted as shipped, with `ALLOW_INTROSPECTION = True`.
With introspection off the `Did you mean 'postCreate'?` tail is stripped and the
rest of each message stands — see [Views](#views).

The `comments` row is the 2.2.0 part: the nested `comments` input is stamped with
the **child's** permission, so a caller who may write posts but not comments
loses the nested surface while keeping the parent. Prune and gate are two halves
of one model — `/graphql/` is **not** pruned, which is exactly why
`permission_classes` (the runtime half, section 5) is the one you must not skip.

Flip `PERMISSION_SCOPED_SCHEMA` to `False` in `config/settings.py` and every
pruned field comes back.

### 7. Multipart uploads (2.2)

`DocumentMutation` is four lines of `Meta` and mounts `documentCreate` /
`documentUpdate`. There is **nothing to configure**: a part named after a
`FileField` the mutation input exposes is merged into the payload and saved to
that column, on create and on update alike.

Send the operation and the file in **one** `multipart/form-data` request: a
`query` part carrying the document, an optional `variables` part carrying its
variables as JSON, and one part per file. There is no `operations` / `map`
envelope — this library does not implement the graphql-multipart-request spec;
it reads a multipart body straight out of `request.POST`. GraphiQL cannot send
a multipart body, so this one is a `curl` demo by nature:

```bash
echo hello > /tmp/notes.txt

curl -sS http://127.0.0.1:8000/graphql/ \
  -H 'X-Requested-With: XMLHttpRequest' \
  -F 'query=mutation { documentCreate(newDocument: { name: "Notes" }) { ok document { id name attachedFile } } }' \
  -F 'attachedFile=@/tmp/notes.txt'
```

```json
{"data": {"documentCreate": {"ok": true,
  "document": {"id": "1", "name": "Notes", "attachedFile": "documents/notes.txt"}}}}
```

Three things that request teaches, each of which the suite pins:

- **Either spelling of the part name works.** `attachedFile` is the only
  spelling the SDL publishes; `attached_file` is the model attribute. Both are
  derived from the same compiled input field, so both land on the same column.
  Re-run the call with `-F 'attached_file=@/tmp/notes.txt'` and watch it.
- **A misspelled part is ignored — and still answers `ok: true`.** Try
  `-F 'attachedFyle=@/tmp/notes.txt'`: the row is created, `ok` is true, and
  `attachedFile` comes back `""`. A typo looks exactly like success, so check
  the payload rather than the status.
- **The header is not optional.** Drop `-H 'X-Requested-With: …'` and the
  request is refused with HTTP 403 before the body is read —
  `multipart/form-data` is a CORS-simple content type, so exempting it would
  leave the mutations that *write files* as the only unprotected surface. See
  [Security defaults you inherit](#security-defaults-you-inherit).

The same column also accepts a **base64** upload inside the JSON body
(`uploadDocument`, v1.3.0), which is the path GraphiQL can drive. One column,
two ways in — compare them side by side in `blog/schema.py`.

**Uploads are open to anonymous callers, so the column is an allow-list.**
`Document.attached_file` accepts only `.txt`, `.pdf`, `.png`, `.jpg`, `.jpeg`
and `.gif` (`FileExtensionValidator`, applied by both paths); anything else —
an `.html` or `.svg` page, say — answers `ok: false` and stores nothing. While
`DEBUG` is on, `config/urls.py` serves `MEDIA_URL` through a small view that
adds `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and
`Content-Security-Policy: sandbox`, so even an allowed file is a download and
never a page on the same origin as `/admin`. **In production, never serve user
uploads from your application's origin:** put them on a separate domain or CDN
(object storage) with the same headers, and add antivirus and size limits as the
data requires. The tests write into a temporary `MEDIA_ROOT`, so a run leaves no
files behind.

---

## Query depth and cost limits

Both rules are wired into `GraphQLView`.

**`MAX_QUERY_DEPTH` is active** in this playground: `config/settings.py` ships
with `"MAX_QUERY_DEPTH": 6`, so any query nested more than 6 levels deep is
rejected immediately with a `QUERY_TOO_DEEP` error.

**`MAX_QUERY_COST`** is **off by default** (the playground comments it out, so no
budget is enforced). Pick the number by measuring: the cost model charges a list
with no explicit page size at `MAX_PAGE_SIZE` (100) and multiplies per nested
list. Measured with `analyze_cost` on the seeded schema:

| Query | Cost |
|---|---|
| `{ posts { results(limit: 1) { id } } }` | 201 |
| `{ post(id: 1) { id title author { name } comments { results(first: 5) { text } } } }` | 104 |
| README example 1 (three paginators, nested tags and comments) | 2,162,003 |
| README example 2(b) (`authors → posts` with filter and `category`) | 4,010,101 |
| `{ authors { results { posts { results { comments { results { text } } } } } } }` | 10,102,010,101 |

So the commonly suggested `200` blocks every list query, and the richest README
example needs about 4 million. This playground suggests **10 million**, which
lets every README example run while refusing three unbounded nested lists.
Uncomment both lines in `config/settings.py` to try it; `MAX_QUERY_DEPTH` is
already active at 6:

```python
DJANGO_GRAPHEX = {
    ...
    # MAX_QUERY_DEPTH is already active at 6 — change or remove to adjust.
    "MAX_QUERY_COST": 10_000_000,  # reject queries with estimated cost > 10M
    "EXPOSE_QUERY_COST": True,     # add extensions.cost to every response
}
```

Then watch `extensions.cost` (`requestedCost` / `maxCost`) on any response and
tune the budget to what your own clients send. A rejected query answers
`Query cost … exceeds the maximum of 10000000.` with code `QUERY_TOO_COMPLEX`.
`tests/test_cost_budget.py` runs every query this README shows under these
settings.

`PostType` already sets `max_depth = 4` and `complexity = 2` so per-type
enforcement is active for free. A query that nests more than 4 levels under a
`post` field is rejected with `QUERY_TOO_DEEP`, and the global `MAX_QUERY_DEPTH`
of 6 applies on top (most-restrictive rule wins).
If you enable `MAX_QUERY_COST`, a selected operation's variable page size is
checked after GraphQL coercion and before its resolvers run. The Playground's
existing `MAX_PAGE_SIZE = 100` also caps list sizes; this setting is not newly
required for variable-cost enforcement.

---

## Private vs public fields

Public (works without auth):

```graphql
{ posts { results(limit: 2) { title } } serverTime categories { name } }
```

Private (requires a logged-in session; otherwise `Authentication required.`):

```graphql
{
  me { id username firstName lastName }
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
2. Press **Run**. Nothing to type: the editor arrives holding a runnable
   document, and against this schema it reads

   ```graphql
   subscription {
     postSubscription(action: ALL_ACTIONS) {
       id
     }
   }
   ```

   The client ships that document with a **placeholder** field name,
   `yourSubscription`, and renames it to the first subscription your schema
   advertises as soon as its introspection query comes back — here
   `postSubscription`. Two consequences worth knowing: add `title` to the
   selection yourself if you want to read it in the frames, and if you have set
   `ALLOW_INTROSPECTION = False` the rename cannot happen, so the editor still
   says `yourSubscription` and you replace it by hand.
3. Trigger a change (create a `Post` via `postCreate`) — the event arrives
   instantly.

Manual WebSocket flow (`wscat -c ws://127.0.0.1:8000/ws/graphql/ -s graphql-transport-ws -o http://127.0.0.1:8000`):

Keep the `-o` (Origin) option too: the route sits behind
`AllowedHostsOriginValidator`, which refuses a handshake that sends no `Origin`
header with HTTP 403, and `wscat` sends none unless told to. The value must be
one of the `ALLOWED_HOSTS` (`127.0.0.1`, `localhost`); a browser always sends it.

Keep the `-s graphql-transport-ws` option: the server rejects a WebSocket
handshake without that offered subprotocol before it can read
`connection_init`. It logs the required offer, while a browser may report only
a generic connection failure (the pre-accept rejection is normally HTTP 403).
This Playground deliberately uses the default session-based consumer: it does
not configure the optional `on_connect` credential hook. Its empty
`connection_init` payload remains valid. Applications that opt in to that hook
must provide their own token verifier and send the corresponding initialization
payload; a denied callback closes the accepted socket with `4403`.

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

### Public subscription, scoped like the query

Subscriptions do **not** run `PostType.get_queryset`, so the visibility rule a
query enjoys is not inherited by a stream. Without a scope, an anonymous
`postSubscription` would receive every `DRAFT` post as it is saved, over both
transports. `PostSubscription.subscription_scope` restates the rule: anonymous
subscribers are forced to `{"status": "published"}`, enforced per event at
delivery, while logged-in subscribers get `None` (no scoping) and see every
post. Try it with two clients, one logged out and one logged in via `/admin`,
then create a draft with `postCreate` (drafts are the default status):
only the logged-in one receives it. `tests/test_subscription_transports_e2e.py`
pins both transports.

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

## Security defaults you inherit

Two settings that will bite a client are ones this project never sets, because
they ship **on**: copy `config/settings.py` and you get them either way. The
file names both in a commented block — the values shown there *are* the
defaults — and this is what they do.

**`REQUIRE_CSRF_HEADER` (default `True`).** The endpoint is `csrf_exempt` and
reads form-encoded and multipart bodies, and both of those are CORS-*simple*
content types: a `<form>` on any origin can POST to `/graphql/` with no
preflight while the browser attaches your session cookie. So a POST whose
content type is `application/x-www-form-urlencoded`, `multipart/form-data`,
`text/plain`, or absent must carry the **`X-Requested-With`** header, or it is
answered HTTP 403 before the body is read:

```console
$ curl -sS -X POST http://127.0.0.1:8000/graphql/ -d 'query={ serverTime }'
{"errors": [{"message": "This content type requires the X-Requested-With header.
A browser can POST it cross-site without a CORS preflight, so the header is what
proves the request was not forged. Send 'X-Requested-With: XMLHttpRequest', post
'application/json' instead, or set REQUIRE_CSRF_HEADER=False to opt out."}]}

$ curl -sS -X POST http://127.0.0.1:8000/graphql/ \
       -H 'X-Requested-With: XMLHttpRequest' -d 'query={ serverTime }'
{"data":{"serverTime":"2026-08-27T06:07:28.997769+00:00"}}
```

(`curl -d` sends `application/x-www-form-urlencoded`; the message above is one
line in the real response, wrapped here to fit.)

The value is never inspected — the header is not CORS-safelisted, so merely
requiring it forces back the preflight the attacker page cannot pass. **GraphiQL
and every `application/json` client change nothing**: `application/json` is not
simple, so it already required a preflight. The same guard runs on the SSE
endpoint, which answers a plain-text 403 there because an `EventSource` client
does not parse a JSON envelope. Set `REQUIRE_CSRF_HEADER: False` in
`DJANGO_GRAPHEX` only if a client genuinely cannot set a header **and** the
endpoint is protected another way.

**`MAX_SUBSCRIPTIONS_PER_CONNECTION` (default `50`).** One WebSocket may hold 50
concurrent operations. A `subscribe` past the cap is answered with the
transport's own `error` frame naming the limit; **the socket and every
subscription already running on it survive**, and a slot frees itself the moment
its operation ends (client `complete`, stream end, or disconnect). This is
**per WebSocket**, not per account; set it to `None` for the old unbounded
WebSocket behaviour.

**Optional SSE controls (both off by default).**
`SSE_HEARTBEAT_ENABLED=True` sends an idle comment every
`SSE_HEARTBEAT_INTERVAL=15` seconds without restarting the source. The separate
`SSE_CONNECTION_LIMIT_ENABLED=True` cap uses a shared Redis URL to admit at most
`SSE_MAX_CONNECTIONS_PER_USER=5` concurrent streams for an authenticated
account across workers. A sixth request gets HTTP 429 before subscribing;
unavailable admission gets HTTP 503. Anonymous SSE and WebSocket behavior do
not change. Uncomment the example settings in `config/settings.py` only when a
shared Redis backend is available; see the
[subscription guide](../../docs/usage/subscriptions.md#sse-connection-controls)
for lease expiry, cleanup, and failover limitations.

These defaults are pinned by `tests/test_shipped_defaults.py` and
`tests/test_subscription_transports_e2e.py`, so this section cannot drift from
the defaults without the suite saying so.

---

## Response cache defaults in 3.1

The playground is safe before it is fast: `CACHE_ACTIVE` is explicitly
`False`. If you turn it on, django-graphex 3.1 still skips cache reads and
writes whenever `request.COOKIES` is non-empty. That prevents two anonymous
shopping carts, tenants, or Django sessions from sharing one cached response.

The configured invalidation scope is `"global"`: after a mutation actually
starts executing, all django-graphex response-cache identities observe the new
version. Rejected GET mutations, validation failures, and atomic rollbacks do
not invalidate. The alternative `"identity"` preserves 3.0's per-identity
counter and should only be used when every cache entry is private.

If an application overrides the protected `GraphQLView.should_cache_query()`
hook to cache cookie-bearing requests, its cache key must include **every**
session and tenant dependency. Merely returning `True` recreates the cross-user
cache leak that the 3.1 default closes.

---

## Views

| Route | View | Notes |
|-------|------|-------|
| `/graphql/` | `GraphQLView` | Public demos and purpose-built `registerUser`; never generic User CRUD |
| `/graphql/stream` | `subscription_sse_view` | Native Server-Sent Events subscription transport |
| `/ws/graphql/` | `subscription_ws_consumer` | Native `graphql-transport-ws` WebSocket (see `config/asgi.py`) |
| `/graphql/client/` | `SubscriptionClientView` | Browser client for the subscription flow (WS + SSE) |
| `/graphql/secure/` | `AuthenticatedGraphQLView` | Authenticated user reads behind **view-level** HTTP 403, and the same schema **pruned per caller** (`PERMISSION_SCOPED_SCHEMA`, [section 6](#6-a-schema-pruned-to-the-caller-22)) |

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
>
> Flipping it also changes **error messages** this README quotes. With
> introspection actually disabled — the middleware installed *and* the setting
> off, which is what `config/settings.py` gives you — the HTTP view omits
> schema-derived `Did you mean …?` hints from field, input, type, argument,
> and enum errors. GraphQL-core 3.3 may place an input hint before `Found`;
> that detail remains while the hint is omitted. Probing with
> invented names is how a hidden schema is rebuilt one guess at a time, so the
> suggestion is part of what the toggle hides. Nothing else moves: the rest of
> the message, the `locations` and the `path` all survive, and a refusal this
> library raises itself (`Invalid ordering field: 'bio'.`) keeps every word,
> because it names the term the client sent rather than a schema member. The
> quoted answers in [The projection boundary](#the-projection-boundary) and
> [section 6](#6-a-schema-pruned-to-the-caller-22) are the
> `ALLOW_INTROSPECTION = True` forms.

> **Static files:** under `daphne` (ASGI), static files are served by
> `ASGIStaticFilesHandler` in `config/asgi.py` while `DEBUG = True`. For
> production, run `make collectstatic` and serve `STATIC_ROOT` with a web
> server or whitenoise.
