# Permission-Scoped Schema: End-to-End Guide

This is the narrative guide to django-graphex's v2 permission stack. It walks a
single Blog API through every layer — what each user **sees**, what each user
**may do**, and how the pieces reinforce each other — with real, runnable code
and the exact responses the server returns.

The reference pages remain [Permissions](permissions.md) (permission classes),
[Security](security.md) (middlewares and the security model),
[Views](views.md) (the HTTP endpoints) and
[Subscriptions](subscriptions.md) (transports). This page ties them together.

## The three layers at a glance

| Layer | What it gates | Where it acts | Configured by |
|---|---|---|---|
| **`DjangoModelPermissions`** | *May this action run?* Each CRUD/subscribe action checks the caller's Django model permissions at **runtime**, right before the resolver. | Per `DjangoModelType` (`permission_classes`) | [`permission_classes`](permissions.md#djangomodelpermissions) on the type |
| **`API_ACCESS_GROUP`** | *May this caller use the endpoint at all?* Members of one Django auth `Group` pass; everyone else gets a generic `403` before any GraphQL parsing. | The whole `AuthenticatedGraphQLView` endpoint | [`API_ACCESS_GROUP`](settings.md#security) setting |
| **`PERMISSION_SCOPED_SCHEMA`** | *What schema does this caller even see?* Each request validates and executes against a schema **pruned to the caller's permissions** — fields they lack perms for do not exist for them. | Per request on `AuthenticatedGraphQLView`; per connection on the subscription transports | [`PERMISSION_SCOPED_SCHEMA`](settings.md#security) setting |

The third layer is where **hide, block and reject unify** under one flag:

- **Hide** — introspection reflects only the caller's pruned schema, so hidden
  fields never show up in tooling or autocomplete.
- **Block** — selecting a pruned field fails *validation* with a native
  `Cannot query field "…"` — a not-found indistinguishable from a typo, never
  an authorization error that would confirm the field exists.
- **Reject** — a caller whose entire `Query` root prunes away gets the
  endpoint's generic `403`, byte-identical to every other endpoint denial.

Layers 1 and 3 are two halves of the same model: the schema layer makes a
forbidden operation *invisible*, the runtime layer makes it *fail* even if a
request somehow reaches the full schema (the public `GraphQLView`, the flag
turned off, a custom transport). Use both.

## Worked example: a Blog API

Two models, one schema, three users.

=== "blog/models.py"

    ```python
    from django.db import models


    class Post(models.Model):
        title = models.CharField(max_length=200)
        body = models.TextField()


    class Comment(models.Model):
        post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
        text = models.TextField()
    ```

=== "blog/schema.py"

    ```python
    from django_graphex.core import BooleanField, ObjectType
    from django_graphex.permissions import DjangoModelPermissions
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    from blog.models import Comment, Post


    class PostType(DjangoModelType):
        permission_classes = [DjangoModelPermissions]   # layer 1: runtime

        class Meta:
            model = Post
            stream = "posts"        # enables the subscription (optional)


    class CommentType(DjangoModelType):
        permission_classes = [DjangoModelPermissions]

        class Meta:
            model = Comment


    class Query(ObjectType):
        post, all_posts = PostType.QueryFields()
        comment, all_comments = CommentType.QueryFields()


    class Mutation(ObjectType):
        create_post = PostType.CreateField()
        update_post = PostType.UpdateField()
        delete_post = PostType.DeleteField()
        # Untagged custom field -> PUBLIC: it survives every pruned variant.
        newsletter_signup = BooleanField(description="Public, untagged")

        def resolve_newsletter_signup(root, info):
            return True


    class Subscription(ObjectType):
        post_subscription = PostType.SubscriptionField()


    schema = DjangoGraphQLSchema(query=Query, mutation=Mutation, subscription=Subscription)
    ```

=== "settings.py"

    ```python
    DJANGO_GRAPHEX = {
        "SCHEMA": "blog.schema.schema",
        "PERMISSION_SCOPED_SCHEMA": True,   # layer 3: per-role pruned schema
    }
    ```

=== "urls.py"

    ```python
    from django.urls import path

    from django_graphex.views import AuthenticatedGraphQLView

    urlpatterns = [
        path("graphql", AuthenticatedGraphQLView.as_view(graphiql=True)),
    ]
    ```

!!! note "Subscriptions are optional here"

    `Meta.stream` / `SubscriptionField()` require the `[subscriptions]` extra
    (`uv add "django-graphex[subscriptions]"`). Drop the `Subscription` root and
    `stream` if you only want queries and mutations — everything else on this
    page works the same.

`DjangoGraphQLSchema` labels every generated CRUD field with the permissions it
requires (the [composite table](#the-composite-permission-table) below) — that
labeling is what the pruner consumes, and it is why
`PERMISSION_SCOPED_SCHEMA` requires a `DjangoGraphQLSchema`.

Now the three users:

```python
from django.contrib.auth.models import Permission, User

ana = User.objects.create_user("ana", password="…")
ana.user_permissions.add(
    Permission.objects.get(codename="view_post", content_type__app_label="blog"),
)

luis = User.objects.create_user("luis", password="…")
luis.user_permissions.add(
    *Permission.objects.filter(
        codename__in=["view_post", "change_post"], content_type__app_label="blog"
    ),
)

admin = User.objects.create_superuser("admin", "admin@example.com", "…")
```

### What each role sees

With `PERMISSION_SCOPED_SCHEMA: True`, each caller's introspection — GraphiQL,
codegen, `__schema` queries — reflects **their** schema. Side by side
(descriptions elided; the object types themselves are unchanged):

=== "ana — `view_post`"

    ```graphql
    type Query {
      post(id: ID!): PostGenericType
      allPosts: PostListType
    }

    type PostGenericType {
      id: ID!
      title: String
      body: String
    }

    type Mutation {
      newsletterSignup: Boolean
    }

    # comment / allComments, every Post mutation, the whole Subscription
    # root and every type reachable only through them are ABSENT.
    # So is PostGenericType.comments — the RELATION into Comment — because
    # ana lacks blog.view_comment (see "Relation traversal" below).
    ```

=== "luis — `view_post` + `change_post`"

    ```graphql
    type Query {
      post(id: ID!): PostGenericType
      allPosts: PostListType
    }

    type Mutation {
      updatePost(newPost: PostUpdateGenericType!): PostType
      newsletterSignup: Boolean
    }

    type Subscription {
      postSubscription(action: PostSubscriptionAction!, id: ID, filter: PostSubscriptionFilterInput): PostSubscriptionEvent
    }

    enum PostSubscriptionAction {
      UPDATE
    }

    # createPost / deletePost are absent; the subscription action enum
    # keeps ONLY the UPDATE value (see the subscriptions section below).
    ```

=== "admin — superuser"

    ```graphql
    type Query {
      post(id: ID!): PostGenericType
      allPosts: PostListType
      comment(id: ID!): CommentGenericType
      allComments: CommentListType
    }

    type Mutation {
      createPost(newPost: PostCreateGenericType!): PostType
      updatePost(newPost: PostUpdateGenericType!): PostType
      deletePost(id: ID!): PostType
      newsletterSignup: Boolean
    }

    type Subscription {
      postSubscription(action: PostSubscriptionAction!, id: ID, filter: PostSubscriptionFilterInput): PostSubscriptionEvent
    }

    enum PostSubscriptionAction {
      CREATE
      UPDATE
      DELETE
      ALL_ACTIONS
    }

    # An ACTIVE superuser always receives the FULL schema — no permission
    # signature is even computed for them.
    ```

You can watch the pruning live: ana introspecting the `Mutation` type sees only
the public field, luis sees his one mutation too.

```graphql
{ __type(name: "Mutation") { fields { name } } }
```

=== "ana's response"

    ```json
    { "data": { "__type": { "fields": [{ "name": "newsletterSignup" }] } } }
    ```

=== "luis's response"

    ```json
    { "data": { "__type": { "fields": [{ "name": "updatePost" }, { "name": "newsletterSignup" }] } } }
    ```

### Denials never leak

**ana tries `updatePost`.** The field is not in her schema, so validation fails
with a native *not-found* — HTTP `400`, no authorization vocabulary, nothing
confirming the field exists for anyone else:

```graphql
mutation { updatePost(newPost: { id: 1, title: "Edited" }) { ok } }
```

```json
{
  "errors": [
    {
      "message": "Cannot query field 'updatePost' on type 'Mutation'.",
      "locations": [{ "line": 1, "column": 12 }]
    }
  ]
}
```

Even the *did-you-mean* suggestions are computed against **her** pruned schema —
ana querying `allComments` gets `"Cannot query field 'allComments' on type
'Query'. Did you mean 'allPosts'?"` — only fields she can see are ever
suggested.

**A user with zero relevant permissions.** Every `Query` field requires a perm
they lack, so their pruned `Query` root is empty — the request is refused
**before** validation or execution with the endpoint's generic `403`,
byte-identical to a `permission_classes` or `API_ACCESS_GROUP` denial:

```json
{
  "errors": [{ "message": "You do not have permission to access this endpoint." }]
}
```

**luis runs `updatePost`.** The field is in his schema, the runtime
`DjangoModelPermissions` check passes (`change_post` + `view_post`), the
mutation executes — HTTP `200`:

```json
{
  "data": {
    "updatePost": { "ok": true, "post": { "id": "1", "title": "Edited" } }
  }
}
```

**admin sees and can do everything.** An active superuser gets the full schema
(no signature computed) and Django's `ModelBackend` grants every permission, so
the runtime layer passes too.

!!! note "Why does ana still have a `Mutation` root?"

    The untagged `newsletterSignup` field is public, so it survives every
    pruned variant and keeps the `Mutation` root alive — which is exactly why
    ana's `updatePost` reads as `Cannot query field` on `Mutation`. Untagged
    fields are the "public surface" of a permission-scoped schema; a root with
    no public fields simply disappears for callers with no relevant perms
    (and an empty **Query** root triggers the generic `403` above).

### Relation traversal is covered too

Pruning is **not** limited to the root fields. Every generated field whose
output type is a model type — a forward `ForeignKey`/`OneToOneField` object
field, and the `<Model>ListType` container a `ManyToManyField` or a reverse FK
renders as — requires the **target** model's read permission (`view_M`), the
same one its own `retrieve`/`list` roots require.

So ana, holding only `blog.view_post`, cannot reach comments the long way
round:

```graphql
{ post(id: 1) { title comments { totalCount results { text } } } }
```

```json
{
  "errors": [
    { "message": "Cannot query field 'comments' on type 'PostGenericType'." }
  ]
}
```

The relation field is simply **absent** from her `PostGenericType`, so this is
the same not-found she gets for `allComments` — no authorization vocabulary, no
confirmation that comments exist. A caller holding both `blog.view_post` and
`blog.view_comment` keeps the field and reads straight through it.

This holds however deep the path runs and whether or not the target model has
root fields of its own: `Comment` exposed *only* through `Post.comments` is
still gated by `blog.view_comment`.

!!! note "Explicit labels win"

    A field carrying an explicit
    [`required_perms`](#labeling-custom-fields-and-mutations-required_perms)
    label keeps that label — the target-model requirement is a *fallback*, used
    only for the generated relation fields nothing else labels. A field
    returning a plain (non-model) type stays untagged and therefore public.

### Nested write inputs are covered too

The same argument runs on the input side. A parent declaring
`Meta.nested_fields = {"comments": Comment}` exposes
`comments: [CommentCreateInPostType!]` inside its own mutation input, and that
field **is** a way to create and update comments. It therefore requires the
child's write permissions, exactly like `commentCreate` / `commentUpdate`.

Which verbs, exactly, follows from what the nested payload can do. The child's
`id` is absent from a **create** input, so that field can only create:
`add_M` + `view_M`. On an **update** input the `id` is *optional*, and omitting
it creates a row — so that field requires `add_M` + `change_M` + `view_M`. A
caller holding `change_comment` but not `add_comment` would otherwise have
`commentCreate` pruned away while the identical create stayed reachable inside
`postUpdate`'s payload.

A caller who lacks them keeps `postCreate` but the `comments` field is **absent**
from its input type, so the nested write is rejected at validation — the same
not-found shape as a pruned root. And when the nested field was the input's
**only** field, the input object would be left empty (which is not a legal
schema), so the mutation field that takes it is pruned instead: `postCreate`
disappears rather than reappearing ungated. Without this, pruning
`commentCreate` away would have removed the front door and left the back door
open.

Write labels of a **nesting-only** child (one with no mutation root of its own)
enter the schema label-set from the input types, so a caller who holds them
keeps the nested field. Every other input field is unlabeled and therefore
untouched.

!!! warning "`required_perms` on the child host can only ADD to this field"

    [`required_perms`](#labeling-custom-fields-and-mutations-required_perms)
    labels every operation field *the class it is declared on generates* — the
    child's own roots. The nested field belongs to the **parent's** input, so it
    starts from the composite table above and the override of every child host
    **that serves one of the verbs the nested field enables** is **unioned** on
    top. It is never a substitute: a child host is very often an ordinary read
    host carrying a read label, and letting that label stand in for the write
    one would hand a caller holding nothing but `view_comment` a working write
    of comments through their post. As a union term a write host declaring
    something stricter (say `required_perms = ["blog.publish_comment"]`)
    genuinely reaches the nested field, so a caller who has `commentCreate`
    pruned away does not keep the identical write inside `postCreate`'s payload.

    A label you did not mean as a write gate still costs you the field. A
    `DjangoModelType` serves every operation unless it says otherwise, so a read
    card labelled `required_perms = ["blog.read_comment_card"]` also labels the
    nested `comments` field, and a caller who holds every write permission on
    `Comment` but not that label loses it — while a differently-hosted
    `commentCreate` stays reachable. Fail-closed, and consistent with what the
    same label does to the card's own create/update roots, but say what the host
    is for: `model_operations = ("list", "retrieve")` on the card keeps its
    label off the nested create and update entirely, exactly as a
    `model_operations = ("delete",)` mutation's does.

    A child that is
    [writable only through its parent](mutations.md#writable-only-through-its-parent)
    needs no opt-out at all. The caller performing that write holds
    `add_comment`; what the pattern withholds is `commentCreate`, and a root you
    never mount gives the pruner nothing to prune.

## Layer 1: runtime enforcement with `DjangoModelPermissions`

`permission_classes = [DjangoModelPermissions]` on a `DjangoModelType` checks
the caller's Django model permissions at runtime, per action, with
`user.has_perms` — see
[Permissions](permissions.md#djangomodelpermissions) for the full reference.

### The composite permission table

Both the runtime check **and** the schema labels the pruner consumes come from
the same normative table. It is *composite*: because a mutation or subscription
payload returns instance data, every write verb also requires `view`:

| Action | Required permission(s) (`M` = `{app_label}.{verb}_{model_name}`) |
|---|---|
| `retrieve` / `list` | `view_M` |
| `create` | `add_M` **+** `view_M` |
| `update` | `change_M` **+** `view_M` |
| `delete` | `delete_M` **+** `view_M` |
| `subscribe CREATE` | `view_M` **+** `add_M` |
| `subscribe UPDATE` | `view_M` **+** `change_M` |
| `subscribe DELETE` | `view_M` **+** `delete_M` |
| `subscribe ALL_ACTIONS` | `view_M` **+** `add_M` **+** `change_M` **+** `delete_M` |

That is why luis (`view_post` + `change_post`) gets the Post read fields,
`updatePost` and the `UPDATE` subscribe action — and nothing else.

### The write-only escape hatch

Because the default is composite, a **write-only** flow (an inbox where users
may submit records they can never read back) overrides `perms_map` for that
action with just the write verb:

```python
from django_graphex.permissions import DjangoModelPermissions


class WriteOnlyInbox(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        # create requires only `add` — the `view` requirement is dropped.
        "create": ("{app_label}.add_{model_name}",),
    }
```

!!! warning "Keep both layers in sync"

    `perms_map` customizes the **runtime** check only. The **schema labels**
    (what the pruner hides) come from the composite table unless you override
    them explicitly with [`required_perms`](#labeling-custom-fields-and-mutations-required_perms) —
    for a write-only inbox that mounts only the create field, pair the
    `perms_map` subclass with `required_perms = ["myapp.add_message"]` on that
    mutation class so the field stays *visible* to write-only users.
    (`required_perms` applies to every operation field the class generates, so
    keep write-only mutation classes single-purpose.)

## Labeling custom fields and mutations: `required_perms`

Generated CRUD fields are labeled automatically. Hand-declared fields are
**untagged by default — untagged means public**: they survive every pruned
variant and are never runtime-checked by this stack. To opt a custom field into
pruning, pass `required_perms` to the low-level `field()` descriptor:

```python
from graphql import GraphQLString

from django_graphex.core import ObjectType, field


class Query(ObjectType):
    # Visible only to callers holding blog.view_post:
    editorial_notes = field(GraphQLString, required_perms=["blog.view_post"])
    # Untagged -> public, in everyone's schema:
    server_time = field(GraphQLString)
```

On a `DjangoModelMutation` (or the mutation fields a `DjangoModelType`
generates), the `required_perms` **class attribute** replaces the composite
default for every operation field the class generates:

```python
from django_graphex.mutation import DjangoModelMutation

from blog.models import Post


class PublishPostMutation(DjangoModelMutation):
    # Replaces the composite default (add/change/delete + view) on the
    # generated createPost/updatePost/deletePost fields.
    required_perms = ["blog.publish_post"]

    class Meta:
        model = Post
```

The schema's global label-set (the union of every stamped permission, plus the
read permission of every model type reachable in the schema — that is what
covers [relation traversal](#relation-traversal-is-covered-too)) is what a
caller's permissions are projected onto — permissions outside it can never
affect pruning, so unrelated grants don't fragment the
[schema cache](#operations-the-pruned-schema-cache).

## Layer 2: the endpoint gate — `API_ACCESS_GROUP`

Independently of what a caller could see or do *inside* the schema,
[`API_ACCESS_GROUP`](settings.md#security) locks the whole
`AuthenticatedGraphQLView` endpoint to members of one Django auth `Group`:

```python
DJANGO_GRAPHEX = {
    "SCHEMA": "blog.schema.schema",
    "PERMISSION_SCOPED_SCHEMA": True,
    "API_ACCESS_GROUP": "api-users",   # "" (default) = gate off
}
```

```python
from django.contrib.auth.models import Group

api_users = Group.objects.create(name="api-users")
api_users.user_set.add(ana, luis)      # members may use the endpoint
```

A member gets a normal response:

```bash
curl -s https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -H "Cookie: sessionid=<ana-session>" \
  -d '{"query": "{ allPosts { totalCount } }"}'
# HTTP 200
# {"data":{"allPosts":{"totalCount":1}}}
```

A non-member — authenticated or not — is rejected **before any GraphQL
parsing**, with the same generic message as every other endpoint denial (the
group requirement is never leaked):

```bash
curl -s https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -H "Cookie: sessionid=<non-member-session>" \
  -d '{"query": "{ allPosts { totalCount } }"}'
# HTTP 403
# {"errors":[{"message":"You do not have permission to access this endpoint."}]}
```

An **active superuser always bypasses** the gate (hardcoded invariant):

```bash
curl -s https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -H "Cookie: sessionid=<admin-session>" \
  -d '{"query": "{ allPosts { totalCount } }"}'
# HTTP 200 — superusers pass regardless of group membership
```

The gate is fail-closed (a missing/anonymous user is denied), runs on top of
`permission_classes` (it survives `as_view(permission_classes=…)` overrides),
and does not affect the public `GraphQLView`. Full semantics:
[Views → Restricting the endpoint to a group](views.md#restricting-the-endpoint-to-a-group-api_access_group).

## Subscriptions: per-action pruning

A subscription field is labeled **per action** (the composite table above), and
pruning acts on the `action` **enum values**, not just the field:

- A caller holding `view` + `change` keeps the subscription field, but its
  action enum keeps **only** `UPDATE` — luis's schema above shows exactly that.
- `ALL_ACTIONS` survives only when **every** write verb is held.
- A caller with **no** permitted action (e.g. ana: `view_post` but no write
  verb) loses the entire subscription field — and if nothing else is left, the
  whole `Subscription` root.

So when luis tries to subscribe to an action he may not observe, the operation
is **rejected at validation** — the enum value does not exist in his schema:

```graphql
subscription { postSubscription(action: DELETE) { id } }
```

```json
{
  "errors": [
    { "message": "Value 'DELETE' does not exist in 'PostSubscriptionAction' enum." }
  ]
}
```

### Wiring the transports

Subscriptions are served by the SSE/WS transports, not the HTTP view, so the
pruned schema reaches them through their `schema_provider` — a callable
`provider(user) -> GraphQLSchema` resolved per connection. Wire it to the
bundled `pruned_schema_for` helper, which honors the **same**
`PERMISSION_SCOPED_SCHEMA` flag (read per connection; an active superuser gets
the full schema; with the flag off it returns the full schema unchanged):

=== "WebSocket (asgi.py)"

    ```python
    # project/asgi.py
    import os

    from django.core.asgi import get_asgi_application

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
    django_asgi_app = get_asgi_application()

    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter
    from django.urls import path

    from django_graphex.core.permission_signature_cache import pruned_schema_for
    from django_graphex.subscriptions.transports.ws import subscription_ws_consumer

    from blog.schema import schema

    _full = schema.graphql_schema

    application = ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            # The provider is resolved once per socket with scope["user"].
            "websocket": AuthMiddlewareStack(
                URLRouter(
                    [
                        path(
                            "ws/graphql/",
                            subscription_ws_consumer(
                                schema_provider=lambda user: pruned_schema_for(user, _full),
                            ).as_asgi(),
                        ),
                    ]
                )
            ),
        }
    )
    ```

=== "SSE (urls.py)"

    ```python
    # urls.py
    from django.urls import path

    from django_graphex.core.permission_signature_cache import pruned_schema_for
    from django_graphex.subscriptions.transports.sse import subscription_sse_view

    from blog.schema import schema

    _full = schema.graphql_schema

    urlpatterns = [
        # The provider is resolved per request/stream with request.user.
        path(
            "graphql/stream",
            subscription_sse_view(
                schema_provider=lambda user: pruned_schema_for(user, _full),
            ),
        ),
    ]
    ```

!!! note "Prerequisites"

    - **A labeled schema** — the pruner needs the `DjangoGraphQLSchema` labels,
      same as the HTTP endpoint.
    - **A real user on the connection** — SSE reads `request.user`; WebSocket
      reads `scope["user"]`, so the WS routing MUST be wrapped in Channels'
      `AuthMiddlewareStack` (or an equivalent that populates `scope["user"]`).
      Otherwise the provider sees `AnonymousUser`.

!!! note "Per-socket resolution and staleness"

    For **WebSocket**, the provider is resolved **once per socket** (on the
    first `subscribe`) and cached for the life of the connection — every
    multiplexed operation on that socket shares one schema, and a permission
    change (or a flag toggle) only takes effect on the **next** connection. For
    **SSE** (one request = one stream), each new stream picks up the current
    state.

And the runtime half still stands: `DjangoModelPermissions` checks the
requested subscribe action **at runtime** with the same composite rule, so even
a request that reaches the full schema (custom provider, flag off) is denied a
`subscribe` for an action whose write verb the caller lacks. See
[Subscriptions → Authorization and row-scoping](subscriptions.md#authorization-and-row-scoping).

## Operations: the pruned-schema cache

!!! info "How pruned schemas are built, cached and invalidated"

    - **One schema per permission-set, not per user.** Each caller's live
      permissions are projected onto the schema's label-set and hashed into a
      *permission signature* (SHA-256 of the sorted relevant perms). Callers who
      differ only in irrelevant perms share one signature — and one pruned
      schema.
    - **Lazy, bounded LRU.** A pruned variant is built on the **first** request
      for its signature (concurrent first-requests build it exactly once) and
      cached in-process in an LRU bounded by
      [`PERMISSION_SCHEMA_CACHE_MAXSIZE`](settings.md#security) (default `64`,
      sized so a realistic role-driven working set of ~50 signatures fits; a
      full cache stays well under 1 MiB).
    - **Revocation applies on the next request.** The signature is recomputed
      from `user.get_all_permissions()` on every request — never keyed by user
      id, never stored in an external cache — so a grant or revoke changes the
      signature and the caller gets the matching schema on their **next**
      request (next *connection* for WebSocket). No stale schema is possible.
    - **A restart resets the cache.** It is in-process only; pruned variants are
      rebuilt lazily after every deploy/restart.
    - **The response cache is signature-aware.** With
      [`CACHE_ACTIVE`](caching.md) on, the caller's permission signature is
      folded into the response-cache key, so two callers sharing a cache
      identity but holding different relevant perms can never read each other's
      cached bodies. (Superusers and flag-off requests contribute an empty
      segment — keys stay byte-identical to the unpruned setup.)

## See also

- [Security → Permission-scoped schema](security.md#permission-scoped-schema-permission_scoped_schema) — the threat-model summary
- [Views → `AuthenticatedGraphQLView`](views.md#endpoint-level-auth-authenticatedgraphqlview) — endpoint semantics
- [Permissions](permissions.md) — every permission class, custom checks
- [Subscriptions](subscriptions.md) — transports, payloads, scoping
- [Settings → Security](settings.md#security) — the setting reference rows
