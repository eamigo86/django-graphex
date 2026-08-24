# GraphQL Subscriptions

`django-graphex` ships an **optional** GraphQL subscriptions engine built
on [Django Channels 4](https://channels.readthedocs.io/). It is the modern
successor of the standalone `graphene-django-subscriptions` package, merged here
as an opt-in extra so that the base install never depends on `channels`.

!!! note "Optional extra"
    Subscriptions are **not** installed by default. The base package never
    imports `channels`. You opt in explicitly:

    ```bash
    uv add "django-graphex[subscriptions]"
    # or
    pip install "django-graphex[subscriptions]"
    ```

    Importing `django_graphex.subscriptions` without the extra raises a
    friendly error telling you to install it.

!!! warning "Subscriptions are native-only in v2.0"
    The v2.0 subscription engine runs exclusively on the native graphql-core
    backend — there is nothing to configure (`graphene` is gone, so the old
    `GDX_BACKEND` toggle no longer exists). The legacy graphene transport (the HTTP
    `channelId` handshake, the demultiplexer consumer, and
    `SubscriptionGraphQLView`) was removed in v2.0 and replaced by two
    standards-based transports — see
    [Serve subscriptions](#3-serve-subscriptions-over-sse-or-websocket).

## How it works

v2.0 ships **one serialize-once engine** behind **two standards-based
transports** — you pick the transport at routing time, the engine is the same:

- **SSE** ([Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html)) —
  a single async HTTP `text/event-stream` response. Simplest to deploy; great for
  a one-way notification feed.
- **WebSocket** ([`graphql-transport-ws`](https://github.com/enisdenjo/graphql-ws/blob/master/PROTOCOL.md)) —
  the modern bidirectional protocol used by `graphql-ws` clients; multiplexes many
  subscriptions over one socket.

The data path:

1. A client sends a GraphQL `subscription { ... }` operation over the chosen
   transport (an SSE HTTP request or a WS `subscribe` message). Authentication is
   the transport's own request/scope — there is **no** separate `channelId`
   handshake.
2. The engine runs the subscription's authorize/scope hooks **before** joining any
   broadcast group, then streams events.
3. When a model instance changes, an in-house signal binding serializes it **once**
   and broadcasts the payload to the group. Every subscriber receives the
   notification, projected to the fields it requested.

Broadcast groups are named after the model, the subscription's `Meta.stream` and
the action, so two subscriptions on the **same model** under different streams
never receive each other's events — including when they disagree on
`payload_mode`. Group names are an internal detail; nothing in your code should
depend on their spelling.

A cross-process channel layer (Redis) is required when the producer (the process
running model writes) and the subscriber processes are separate; the in-memory
layer is fine for development.

!!! tip "Try it interactively"
    Add the [browser client view](#browser-client-view) to your URLConf to
    subscribe and watch notifications stream in — straight from the browser,
    served from your own origin.

## 1. Define a subscription

A `Subscription` is declared like a `DjangoModelType`, through `Meta`:

```python
from django_graphex.subscriptions import Subscription
from myapp.models import User


class UserSubscription(Subscription):
    class Meta:
        model = User                          # required, a Django model class
        stream = "users"                      # required, a str
        queryset = None                        # optional
        description = "User Subscription"     # optional
        payload_mode = None                    # optional, see "Notification payload"
```

The notification payload is serialized through the native (Pydantic) backend.

This generates a real GraphQL `subscription` field whose **output type is the
model's projected fields** (the serialized instance) — a true streaming
subscription, not the legacy one-shot confirmation object. It exposes:

- **Arguments:** `action` (required, see the enum below), `id` (optional — scope
  to one instance by pk), and `filter` (optional — see
  [Filtering notifications](#filtering-notifications)). The legacy `channelId` and
  `operation` arguments are **gone** (the transport handles connection lifecycle).
- **Enum:** `ActionSubscriptionEnum {CREATE, UPDATE, DELETE, ALL_ACTIONS}`.

## 2. Mount it on the schema

```python
from django_graphex.core import ObjectType
from django_graphex.schema import DjangoGraphQLSchema
from myapp.subscriptions import UserSubscription


class Subscription(ObjectType):
    user_subscription = UserSubscription.Field()


schema = DjangoGraphQLSchema(query=Query, subscription=Subscription)
```

## 3. Serve subscriptions over SSE or WebSocket

Both transports are factories that take the live native schema and return a
Django view (SSE) or a Channels consumer class (WebSocket). Mount either, or both.

### SSE (HTTP `text/event-stream`)

`subscription_sse_view(schema=...)` returns an **async** Django view (requires
Django >= 5.2). It parses the subscription operation, runs the engine's
authorize/scope hooks before joining any group, and streams `next` / `complete`
frames.

```python
# urls.py
from django.urls import path
from django_graphex.subscriptions.transports.sse import subscription_sse_view
from myapp.schema import schema

urlpatterns = [
    path("graphql/stream", subscription_sse_view(schema=schema.graphql_schema)),
]
```

### WebSocket (`graphql-transport-ws`)

`subscription_ws_consumer(schema=...)` returns a Channels
`AsyncJsonWebsocketConsumer` subclass speaking the `graphql-transport-ws`
protocol (`connection_init`/`ack`, multiplexed `subscribe`, `ping`/`pong`,
per-id `complete`). Route it via your ASGI app:

```python
# project/asgi.py
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from django_graphex.subscriptions.transports.ws import subscription_ws_consumer
from myapp.schema import schema

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(
            [path("ws/graphql/", subscription_ws_consumer(schema=schema.graphql_schema).as_asgi())]
        ),
    }
)
```

```python
# settings.py
ASGI_APPLICATION = "project.asgi.application"

# Development: in-memory layer. Production: use a Redis layer.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
# Production example:
# CHANNEL_LAYERS = {
#     "default": {
#         "BACKEND": "channels_redis.core.RedisChannelLayer",
#         "CONFIG": {"hosts": [("127.0.0.1", 6379)]},
#     },
# }
```

### Per-connection schema (permission-scoped subscriptions)

Both transports accept an optional `schema_provider` in addition to the plain
`schema=`. A `schema_provider` is a callable `provider(user) -> GraphQLSchema`
resolved **per connection** with the connection's user (`request.user` for SSE,
`scope["user"]` for WebSocket). When given, it **wins** over `schema=`.

This lets a subscription connection use the **same pruned schema as HTTP**: wire
the provider to the bundled `pruned_schema_for` helper so a subscription
**action the user is not permitted to observe is absent from the connection's
schema** and a `subscribe` naming it fails at **validation** (`Cannot query
field`), exactly like the HTTP endpoint.

The bundled `pruned_schema_for` helper is gated by
[`PERMISSION_SCOPED_SCHEMA`](settings.md) — the **same one flag** that gates the
HTTP `AuthenticatedGraphQLView` — read **per connection** (never at import):

- **`PERMISSION_SCOPED_SCHEMA = False`** (the default): the helper returns the
  **full** schema, so a provider wired to it is inert and every field validates.
- **`PERMISSION_SCOPED_SCHEMA = True`**: the helper returns the schema **pruned**
  to the connection user's permissions. An **active superuser** always receives
  the full schema.

```python
from django_graphex.core.permission_signature_cache import pruned_schema_for
from django_graphex.subscriptions.transports.sse import subscription_sse_view
from django_graphex.subscriptions.transports.ws import subscription_ws_consumer
from myapp.schema import schema

_full = schema.graphql_schema

# SSE: the provider is resolved with request.user.
sse_view = subscription_sse_view(
    schema_provider=lambda user: pruned_schema_for(user, _full),
)

# WebSocket: the provider is resolved once per socket with scope["user"].
ws_consumer = subscription_ws_consumer(
    schema_provider=lambda user: pruned_schema_for(user, _full),
)
```

!!! note "Prerequisites for pruning"

    Pruning via `pruned_schema_for` requires a **labeled** `DjangoGraphQLSchema`
    (the schema carries a `gdx_label_set` and per-field `gdx_required_perms`, the
    same labeling the HTTP endpoint uses). It also needs a real user on the
    connection: SSE reads `request.user`, WebSocket reads `scope["user"]` — so the
    WS routing MUST be wrapped in Channels' `AuthMiddlewareStack` (or an equivalent
    that populates `scope["user"]`), otherwise the provider sees `AnonymousUser`.

!!! note "Per-socket resolution and staleness"

    For **WebSocket**, the provider is resolved **once per socket** (on the first
    `subscribe`) and cached for the life of the connection, so every multiplexed
    operation on that socket shares one schema. A permission change (or a
    `PERMISSION_SCOPED_SCHEMA` toggle) therefore only takes effect on the **next**
    connection, not mid-socket. For **SSE** (one request = one stream) the provider
    is resolved per request, so each new stream picks up the current state.

Passing a plain `schema=` (no `schema_provider`) is fully **backward
compatible** — the transport behaves exactly as before, so existing wiring such
as `subscription_ws_consumer(schema=schema.graphql_schema)` keeps working
unchanged. You must pass at least one of `schema=` or `schema_provider=`.

A **custom** `schema_provider` callable that does **not** route through
`pruned_schema_for` is your own code and is **not** gated by the setting — the
flag gates the bundled helper only, so whatever schema your callable returns is
used as-is.

## From a `DjangoModelType` (one definition)

If you already use a [`DjangoModelType`](types.md#djangomodeltype) for
queries and mutations, you can get its subscription from the **same class** — no
separate `Subscription` subclass. Add `stream` (and optionally `payload_mode`)
to its `Meta`:

```python
from django_graphex.types import DjangoModelType
from myapp.models import User

class UserModelType(DjangoModelType):
    class Meta:
        model = User
        stream = "users"          # enables the subscription
        payload_mode = "full"     # optional; defaults to the global setting
```

Mount it on the schema — then serve it through either transport (see
[Serve subscriptions](#3-serve-subscriptions-over-sse-or-websocket)):

```python
# schema.py
from django_graphex.core import ObjectType
from django_graphex.schema import DjangoGraphQLSchema

class Subscription(ObjectType):
    user_subscription = UserModelType.SubscriptionField()

schema = DjangoGraphQLSchema(query=Query, subscription=Subscription)
```

`UserModelType.subscription_type()` builds (and caches) the `Subscription`
lazily, so the **base install stays Channels-free** until you actually wire a
subscription. The generated subscription supports the same arguments — including
[`filter`](#filtering-notifications). Setting `Meta.stream` is required to use
`SubscriptionField()` / `subscription_type()`. The transport (SSE or WS) is chosen
at routing time; the subscription class is transport-agnostic.

### Authorization and row-scoping

The generated subscription honors the type's authorization and scoping:

- **`permission_classes` / `authorize`** gate the **subscribe** itself. Authorize
  runs at registration (the HTTP request, so `info.context.user` is available)
  for the read-like `"subscribe"` action; a denial yields `ok: False` / `error`
  and no group is joined. `IsAuthenticatedOrReadOnly` therefore lets anyone
  subscribe to a public stream, while `IsAuthenticated` requires a login.
- **Per-action check (defense in depth).** The requested subscription `action`
  (`CREATE` / `UPDATE` / `DELETE` / `ALL_ACTIONS`) is forwarded to the permission
  check, so a class can gate each action independently. Because a subscription
  payload returns instance data, `DjangoModelPermissions` treats a subscribe
  action as **composite**: it requires the codenames of its `perms_map`
  `subscribe` row **plus** those of the row the action maps to — with the
  default mapping, the model's `view` permission plus the action's write verb
  (`ALL_ACTIONS` requires every write verb). Because both halves are resolved
  through `get_required_permissions`, a subclass that customizes `perms_map`
  for `subscribe` (or for `create` / `update` / `delete`) is honored here too.
  A user permitted
  only `CREATE` is therefore denied a `subscribe` for `UPDATE` at **runtime**,
  even if the request reaches the full schema — this is the runtime half of the
  same model that [`PERMISSION_SCOPED_SCHEMA`](settings.md) enforces at the schema
  layer (the action's enum value is pruned away). Custom `permission_classes` read
  the action via `has_subscribe_permission(info, model, **kwargs)` (the action
  arrives under `kwargs["subscription_action"]`).
- **`subscription_scope(info, **kwargs)`** returns a server-forced filter mapping
  (e.g. `{"owner": info.context.user.pk}`). The `info` a subscribe hook receives
  is the transport's own context object, and it exposes **both** `info.user` and
  `info.context.user` — the second is the spelling a resolver uses, so hook code
  reads the same either way. It is evaluated at subscribe time and
  enforced **per event at delivery**, merged over the client `filter` with
  server precedence — the client can neither widen nor drop it. Equality scopes
  on a serialized field (like `owner`) are decided **in memory**, so there is no
  per-event query.

```python
from django_graphex.permissions import IsAuthenticated
from django_graphex.types import DjangoModelType
from myapp.models import Note

class NoteModelType(DjangoModelType):
    permission_classes = [IsAuthenticated]

    class Meta:
        model = Note
        stream = "notes"
        payload_mode = "full"

    @classmethod
    def subscription_scope(cls, info, **kwargs):
        return {"owner": info.context.user.pk}   # only my notes
```

!!! warning "Make `subscription_scope` fail closed"

    `None` means **no scoping**, not "no notifications". A scope written as
    `return {"owner": user.pk} if user.is_authenticated else None` therefore
    serves an anonymous subscriber **every** row on the stream. Pair it with a
    `permission_classes` / `authorize` gate that denies the anonymous
    `subscribe` — remember `"subscribe"` is a READ action, so
    `IsAuthenticatedOrReadOnly` does **not** deny it — and raise from the scope
    itself when there is no user to scope by. `examples/playground`
    (`NoteModelType`) does both.

!!! note "Why not `filter_queryset`?"

    `filter_queryset` is an opaque queryset transform used by the query/list
    resolvers; it cannot be applied to a single changed instance without a
    per-event query (and needs the request at delivery time). `subscription_scope`
    returns a plain mapping instead, so scoping is enforced in memory and the
    WebSocket connection itself does not need to be authenticated.

### Indexed groups (optional, for high fan-out)

With only `subscription_scope`, a change is broadcast to **one group per
model+action** and every subscriber's connection is woken to evaluate the filter
in memory (cheap, but `O(subscribers)`). For streams with very many concurrent
subscribers partitioned by a value (per owner, per tenant, per room), declare
`subscription_index_fields` to route each change to a **value-scoped group** so
only the matching subscribers are woken:

```python
from django_graphex.types import DjangoModelType
from myapp.models import Message

class MessageModelType(DjangoModelType):
    class Meta:
        model = Message
        stream = "messages"
        payload_mode = "full"
        subscription_index_fields = ("tenant", "room")   # compound (AND) index

    @classmethod
    def subscription_scope(cls, info, **kwargs):
        return {"tenant": info.context.tenant_id, "room": kwargs.get("room")}
```

How it works: at subscribe the group name gets a canonical suffix built from the
scope (e.g. `messages-create:room=42&tenant=7`); at broadcast the **same** suffix
is built from the changed instance (reading each field's `attname`, so a foreign
key yields its raw id without a query). The two names match by construction, so
Channels delivers only to that group -- no group enumeration is involved.

- **Opt-in and additive.** Omit it and everything works exactly as before.
- **Must be a subset of the scope.** Every index field has to be present in what
  `subscription_scope` returns; if any is missing the subscriber transparently
  **falls back to the coarse group** (still correct, just not narrowed).
- **Good index fields are high-cardinality** equality keys (FKs like `owner`,
  `tenant`, `room`). A low-cardinality boolean would only create two groups and
  buy nothing.
- **Independent of `payload_mode`.** The index reads the live instance, not the
  payload, so it works in id-only mode too.
- The full filter is still applied on delivery, so indexing is purely a routing
  optimization -- correctness never depends on it.

## Browser client view

`SubscriptionClientView` serves a self-contained HTML page to try subscriptions
live. It speaks the same standards as the transports: `graphql-transport-ws` over
WebSocket and `graphql-sse` over a streamed `fetch()` POST — the browser
`EventSource` API is not used to *start* the subscription, since `EventSource`
cannot carry the operation (see [the SSE wire protocol](#sse-the-wire-protocol)).
The response it reads back **is** a standard `text/event-stream`, though — see
the tip below for watching it live in DevTools. Add it to your URLConf like the
admin — because it is served from **your own origin**, there is no CORS to
configure:

```python
# urls.py
from django_graphex.subscriptions import SubscriptionClientView

urlpatterns = [
    ...,
    path("graphql/client/", SubscriptionClientView.as_view()),
]
```

Open `/graphql/client/`: it connects to the chosen transport, lets you send a
`subscription { … }` operation, and streams the notifications back. The editor
supports **Tab** to indent (Shift+Tab to outdent) and **schema-aware
autocomplete** — it introspects the configured endpoint and suggests types,
fields, arguments and enum values as you type (Ctrl+Space to trigger, Enter/Tab to
accept). If introspection is disabled on the server, autocomplete falls back to
GraphQL keywords only. The endpoints default to the page's own origin with the
routes `/ws/graphql/` (WS), `/graphql/stream` (SSE) and `/graphql/` (HTTP);
override them if yours differ:

```python
path(
    "graphql/client/",
    SubscriptionClientView.as_view(
        ws_path="/ws/graphql/",
        sse_path="/graphql/stream",
        http_path="/graphql/",
    ),
),
```

!!! warning "`sse_path` is a separate route from `http_path`"
    The SSE transport is its own view (`subscription_sse_view`) returning
    `text/event-stream`; `http_path` is the JSON `GraphQLView`. They are
    different URLs, so the client has a **`sse_path`** of its own. Point it at
    the JSON endpoint and the POST still returns `200 application/json` — the
    client shows a connected stream and no data at all, because the body carries
    no `event:` line. A frame the client cannot recognise is now logged as an
    error instead of being dropped, so that misconfiguration is visible.

## 5. Subscribe from a client

Send a normal GraphQL `subscription` operation over the SSE or WebSocket
transport. The selection set is the **model's projected fields** — each event
delivers the (optionally filtered) serialized instance:

```graphql
subscription {
  userSubscription(action: UPDATE, id: 5) {
    id
    username
    email
  }
}
```

- `action: ALL_ACTIONS` subscribes to `CREATE`, `UPDATE` and `DELETE`.
- Omit `id` to subscribe to **every** instance for that action.
- Unsubscribing is the transport's own lifecycle — see
  [Unsubscribing](#unsubscribing). There is no `operation: UNSUBSCRIBE` argument
  anymore.
- Which fields are deliverable depends on the payload mode — in id-only mode only
  `id` is present (see [Notification payload](#notification-payload)).
- Relations are delivered as **flat pks** (`post: ID`, `tags: [ID]`) — selecting
  their subfields is a validation error (see
  [Relations are flat IDs](#relations-are-flat-ids-no-nested-selections)).

### SSE: the wire protocol

The SSE transport implements the server side of
[`graphql-sse`](https://github.com/enisdenjo/graphql-sse)'s **distinct
connections mode**: one HTTP request carries **one** subscription. The operation
travels in a **POST body** — a JSON object with `query`, `variables` and
`operationName` — and the response is a `text/event-stream` that stays open:

```bash
curl -N -X POST http://localhost:8000/graphql/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "subscription { userSubscription(action: UPDATE) { id username } }"}'
```

Each delivered event is a `next` frame carrying a standard GraphQL result; the
terminal `complete` frame ends the stream (its empty `data:` line is part of the
protocol — an `EventSource`-style listener never fires `complete` without it):

```text
event: next
data: {"data": {"userSubscription": {"id": "5", "username": "neo"}}}

event: complete
data: 
```

!!! warning "The browser `EventSource` API cannot start a subscription"

    The limitation is in the **`EventSource` JavaScript API**, not the wire
    format: `EventSource` only issues **GET** requests and cannot send a body,
    so it has no way to deliver the GraphQL document — the view answers such a
    query-less request with **HTTP 400**. Subscribe with a streamed `fetch()`
    POST instead (exactly what the bundled
    [browser client view](#browser-client-view) does), or use the
    [`graphql-sse`](https://github.com/enisdenjo/graphql-sse) client library,
    which speaks this protocol out of the box. The response itself is a
    standard `text/event-stream` either way — see the tip below to watch it in
    DevTools.

!!! tip "Watching the raw stream in DevTools"

    Because the response really is `text/event-stream`, you can watch the
    `next` / `complete` frames arrive live without any client library: open
    your browser's DevTools → **Network** tab, find the streaming request, and
    open its **EventStream** tab (Chrome/Edge) or **Response** tab (Firefox).
    Each frame appears as it is flushed, even though the request itself was
    sent as a POST (not via `EventSource`).

!!! note "CSRF is exempt on this view"

    `subscription_sse_view` ships `csrf_exempt`, mirroring `GraphQLView`: the
    GraphQL document *is* the request payload and the engine's own
    authorize/scope hooks gate the subscription, so session-cookie CSRF adds no
    protection to a same-origin JSON POST. This means a plain `fetch()` POST or
    a `curl` command (like the one above) reaches the view without needing a
    CSRF token.

Error surfacing splits at the moment the stream is committed:

- **Pre-stream (HTTP 400)** — a missing `query`, a GraphQL **syntax** error, or
  a non-subscription operation is rejected as a plain `400 Bad Request` before
  any stream starts.
- **In-stream** — everything after that (**validation errors** and
  **authorize-denials**) is delivered inside the committed
  `200 text/event-stream` response as a single `next` frame carrying
  `{"errors": [...]}` followed by the `complete` frame — never an HTTP 4xx,
  because a status code cannot change once the streaming response has begun.

### WebSocket: the wire protocol

The consumer speaks
[`graphql-transport-ws`](https://github.com/enisdenjo/graphql-ws/blob/master/PROTOCOL.md) —
your client must request that subprotocol when opening the socket. One socket
multiplexes any number of operations, each identified by a client-chosen `id`:

| # | Direction | Message |
|---|-----------|---------|
| 1 | client → server | `{"type": "connection_init"}` — must be the first message (the auth boundary) |
| 2 | server → client | `{"type": "connection_ack"}` |
| 3 | client → server | `{"type": "subscribe", "id": "1", "payload": {"query": "subscription { … }"}}` |
| 4 | server → client | `{"type": "next", "id": "1", "payload": {"data": {…}}}` — one frame per delivered event |
| 5 | server → client | `{"type": "complete", "id": "1"}` — only when the stream itself ends |

The `subscribe` payload carries the same `query` / `variables` /
`operationName` keys as an HTTP POST. A subscribe-time failure (parse error,
validation error, authorize-deny) is answered with
`{"type": "error", "id": "1", "payload": [...]}` instead of `next` frames, and
the server answers a client `{"type": "ping"}` with `{"type": "pong"}`. The
[`graphql-ws`](https://github.com/enisdenjo/graphql-ws) JavaScript client
speaks this protocol out of the box.

Protocol violations close the socket with the spec's codes: `4400` malformed
message, `4401` `subscribe` before the ack, `4408` no `connection_init` within
the init timeout, `4409` duplicate operation `id`, `4429` a second
`connection_init`. `4400` covers **any** frame the consumer cannot dispatch —
including a body that is not valid JSON and a non-string `id` — and the close
tears down every live operation on that socket first, so a malformed frame can
never leave a task or a joined group behind.

A failure that happens **after** delivery started is not a close and not an
`error` frame: it arrives as `{"type": "next", "payload": {"errors": [...]}}`
followed by the terminal `complete`, so the client always gets a protocol signal
instead of a stream that goes quiet forever. The SSE transport does the same
thing with its own framing (`event: next` carrying `errors`, then
`event: complete`) — once the `200 text/event-stream` response is committed an
HTTP error is impossible.

### Unsubscribing

Both transports guarantee that a gone client is a gone subscriber — teardown
discards every channel-layer group the operation had joined.

**WebSocket** — send a `complete` frame for the operation id:

```json
{"type": "complete", "id": "1"}
```

This cancels **only** operation `"1"`: its task is cancelled and its groups are
discarded, while the other operations multiplexed on the same socket keep
streaming. Per the protocol the server does **not** echo a `complete` back for
a client-initiated one — a server `complete` means "this stream ended on its
own". Closing the socket cancels **all** operations and discards every joined
group.

**SSE** — one request is one stream, so unsubscribing means closing the HTTP
connection: abort the `fetch()` (`AbortController.abort()`), dispose the
`graphql-sse` client subscription, or `Ctrl-C` the `curl`. Django ≥ 5.2
guarantees the disconnect cancels the streaming generator, and the transport's
cleanup then leaves every joined group — no ghost subscribers. Teardown is also
registered on the **response** itself, so a client that aborts during the
subscribe handshake — before the response body is ever read — releases its
groups too.

### Filtering notifications

`id` scopes by the changed object's own primary key. To scope by **field
values** instead — e.g. a post-detail page that should only receive the comments
of *that* post — pass the optional `filter` argument. It is a real generated
input object, `<Model>SubscriptionFilterInput`, with the **same nested shape**
queries use:

```graphql
subscription {
  commentSubscription(
    action: ALL_ACTIONS
    filter: { post: { exact: 7 } }       # only comments whose post == 7
  ) {
    id
    text
  }
}
```

The type exposes exactly the subscription's **projected output fields** (see
`only_fields` / `exclude_fields`), each with exactly **four** lookups —
`exact`, `iexact`, `in`, `isnull`. Nothing else is expressible: the schema
itself is the boundary now, so your IDE autocompletes the valid keys and an
invalid one fails validation before the request ever reaches the engine.

Filters are evaluated **per connection at delivery time**:

- **`exact`** is decided in memory against the serialized payload — no extra
  query. This is the fast path the whole serialize-once engine is built around,
  so prefer it for scoping.
- **The other three lookups** fall back to a single-row database check.
- Combine them:
  `filter: { post: { exact: 7 }, status: { in: ["open", "urgent"] } }`.
- Omitting `filter` delivers every event in the group.

!!! warning "Breaking change in 2.1.0 — `filters` is now `filter`"
    Through 2.0.x the argument was `filters`, typed `String`, carrying a
    JSON-encoded object (`filters: "{\"post\": 7}"`). There is **no alias**: the
    old name and the old string form are gone. Rewrite

    ```graphql
    commentSubscription(action: ALL_ACTIONS, filters: "{\"post\": 7}")
    ```

    as

    ```graphql
    commentSubscription(action: ALL_ACTIONS, filter: { post: { exact: 7 } })
    ```

    See the [changelog](../changelog.md) for the full before/after.

!!! warning "Ordered and pattern lookups are rejected"
    `startswith`, `icontains`, `regex`, `gt`/`gte`/`lt`/`lte`, `range` and the
    date-part transforms (`year`, `month`, `day`, …) are **not declared** on the
    generated input type, so they fail schema validation — on **every** field,
    including declared ones. Delivery evaluates a filter as an ORM lookup and
    whether the event arrives is observable, so a comparison lookup is a boolean
    oracle an attacker can walk one character (or one bisection) at a time.
    Equality and membership only answer "is it exactly this value?", which
    forces a whole-value guess.

    2.0.0 documented `text__icontains` as usable; 2.1.0 started rejecting it at
    subscribe time and 2.1.0 makes it unexpressible in the schema. Move the
    substring match to `subscription_scope` (server code, exempt from this
    check) or filter client-side on the delivered payload.

!!! note "Delete + lookup filters"
    On a `delete` the row no longer exists, so only the in-memory (equality)
    path applies. With `payload_mode = "full"` the payload still carries the
    field values, so equality filters work on deletes; with id-only payloads,
    non-pk filters cannot be evaluated on delete and the notification is dropped.

!!! tip "Scoping vs. security"
    A client-supplied `filter` is a **convenience** scope, not an authorization
    boundary. To enforce row-level access (e.g. "only my records"), gate the
    subscription with `private_subscription` / your auth layer rather than
    relying on a client-provided filter.

!!! warning "Client filters can still test equality against any declared field"
    A filter key is evaluated as an ORM lookup at delivery time, and whether the
    event arrives is observable — so a client filter remains a boolean oracle
    over **every field the subscription declares as output**. Restricting the
    lookups to equality and membership (see
    [Filter key validation](#filter-key-validation)) removes *incremental*
    extraction, not the oracle itself: a client can still ask "is this field
    exactly `X`?" about any declared field, one guess at a time. That is fine
    for a value with a large space (a password hash) and **not** fine for one
    with a small space (a boolean flag, a status enum, a short token).

    Keep sensitive columns out of that surface with `only_fields` /
    `exclude_fields` on the subscription's `Meta` — they gate the event payload
    **and** the declared filter set in one move:

    ```python
    class UserSubscription(Subscription):
        class Meta:
            model = User
            stream = "users"
            exclude_fields = ("password", "user_permissions")
    ```

What the client receives is a normal GraphQL result — its own selection set
projected from the event (wrapped in the transport's frame: an SSE `next`
event or a WS `next{id, payload}` message). Subscribing with
`{ id username email }` in the default **id-only** mode delivers:

```json
{"data": {"userSubscription": {"id": "5", "username": null, "email": null}}}
```

…and in **full-payload mode**, the serialized values:

```json
{"data": {"userSubscription": {"id": "5", "username": "neo", "email": "neo@example.com"}}}
```

!!! note "The broadcast envelope is internal"

    The `{"stream": ..., "payload": {"action": ..., "model": ..., "data": ...}}`
    message you may see in channel-layer captures is the **internal** broadcast
    between the signal binding and the subscriber processes — it never reaches
    the client. Clients only see the transport frames above.

## Notification payload

On every model change the binding builds the notification `data`. By default it
is **id-only** — `{"id": <pk>}` — which **skips serialization entirely** (the
fastest option for hot models, where clients typically refetch on notification).
Set it to **full** to serialize the whole instance through the native (Pydantic)
backend.

Two controls, in order of precedence:

| Control | Values | Effect |
|---------|--------|--------|
| `Meta.payload_mode` | `None` (default), `"full"`, `"id_only"` | Per-subscription. `None` inherits the global setting; `"full"` = full; `"id_only"` = id-only. |
| `DJANGO_GRAPHEX["SUBSCRIPTION_PAYLOAD_MODE"]` | `"id_only"` (default), `"full"` | Global default for subscriptions that don't override it. |

```python
# settings.py — make every subscription serialize the full instance by default
DJANGO_GRAPHEX = {
    "SUBSCRIPTION_PAYLOAD_MODE": "full",
}
```

```python
# ...or decide per subscription, regardless of the global default
class UserSubscription(Subscription):
    class Meta:
        model = User
        stream = "users"
        payload_mode = "full"   # full payload for this one; "full"/"id_only"/None
```

!!! note "File and binary columns"

    The payload is JSON-encoded before it crosses the channel layer, so the two
    field kinds whose Python value is not JSON-encodable are converted: a
    `FileField` / `ImageField` is delivered as its **storage name** (the string
    its GraphQL `String` output already carries) and a `BinaryField` as
    **base64** text. Both render as `String` on the event type. Before this,
    `payload_mode = "full"` on a model carrying either column raised
    `TypeError: Object of type FieldFile is not JSON serializable` on **every**
    save.

!!! warning "id-only is the default"

    `graphene-django-subscriptions` always sent the full serialized instance.
    django-graphex defaults to id-only for performance. In id-only mode the
    payload carries only `{"id": <pk>}`, so a subscription selection set can
    deliver only `id` — to receive other fields, opt into full mode via
    `Meta.payload_mode = "full"` / the global setting. The payload mode is fixed
    when the subscription class is defined.

## Relations are flat IDs (no nested selections)

The generated event type — `<Model>SubscriptionEvent` — renders every relation
**flat**: a `ForeignKey` / `OneToOneField` field is the related object's pk
scalar (`ID` for the usual auto pk, otherwise the pk field's own scalar), and a
`ManyToManyField` is a **list** of pks (`[ID]`). This is the serialize-once
design working as intended: a change is serialized **once** (`FK → pk`,
`M2M → [pk]`) and that single flat payload feeds every subscriber with **zero
per-subscriber database queries** — resolving a nested object per subscriber
would reintroduce exactly the per-event N+1 the engine exists to avoid.

Select relations as scalars:

```graphql
subscription {
  commentSubscription(action: CREATE) {
    id
    text
    post      # ID — the related post's pk, not an object
    tags      # [ID] — the related pks
  }
}
```

Selecting **subfields** on a relation fails GraphQL **validation** — before any
event is delivered:

```graphql
subscription {
  commentSubscription(action: CREATE) {
    post { id title }
  }
}
```

```text
Field 'post' must not have a selection since type 'ID' has no subfields.
```

(On SSE the error arrives in-stream; on WebSocket as an `error` frame — see
[the wire protocols](#sse-the-wire-protocol).)

The payload mode does **not** change this schema — `payload_mode` only decides
which keys the broadcast payload carries, and the flat resolvers simply read
their key from it:

| Client selects… | `payload_mode = "id_only"` (default) | `payload_mode = "full"` |
|---|---|---|
| `id` | the pk | the pk |
| a concrete scalar (`text`, `username`, …) | `null` — no error | the serialized value |
| a FK / O2O (`post`) | `null` — no error | the related pk (`ID`) |
| a M2M (`tags`) | `null` — no error | the related pks (`[ID]`) |
| nested subfields (`post { id }`) | validation error | validation error |

In id-only mode the payload is just `{"id": <pk>}`, so any selected non-`id`
field resolves `null` — the selection still validates against the same schema,
and nothing errors at delivery. In full mode the broadcast carries **all**
concrete fields plus the M2M pk lists, and each subscriber's selection projects
from that single dict.

## Per-connection field selection

Each subscriber's GraphQL selection set is its own projection: two clients on the
same stream requesting different fields each receive only the fields they asked
for, resolved **per event** from the single serialized payload (no shared
serializer state, no re-serialization).

## Security hardening

### Transport-level authentication

v2.0 has **no** separate `channelId` handshake or channel-ownership cache to
guard — the legacy two-channel protocol (and its `SUBSCRIPTIONS_CHANNEL_GUARD`
setting) was removed. Authentication is now the transport's own request/scope:

- **SSE** authenticates the **HTTP request** (`request.user` / session /
  middleware) before the engine joins any group.
- **WebSocket** authenticates the **connection scope** at `connection_init`
  (the auth boundary) before any subscription is accepted.

The subscription's `authorize_subscription` / `permission_classes` hooks run
**before** any `group_add`, so a denial short-circuits before the source is
created — there is no window where an unauthorized subscriber is joined.

### GraphQL execution middleware

Both transports build the `DJANGO_GRAPHEX['MIDDLEWARE']` chain **once per
connection** and run it on the subscribe entry *and* on every per-event delivery
`execute` — the same chain `GraphQLView` runs for queries and mutations. So
`AuthenticatedFieldsMiddleware` (the enforcement half of `private_subscription`,
see [Security](security.md#field-level-authentication)) actually protects
subscription fields: an unauthenticated subscriber is denied **before** any
`group_add`, and no event is ever delivered to it.

!!! warning "Fixed in 2.1.0"
    In 2.0.0 the setting was read only by `GraphQLView`, and subscriptions are
    served *only* by the SSE / WS transports — so every configured GraphQL
    middleware was inert on subscriptions and `private_subscription` protected
    nothing there. Upgrade to 2.1.0 if you rely on it.

### Filter key validation

Since 2.1.0 the **schema** is the first gate: `<Model>SubscriptionFilterInput`
declares only the projected output fields, each with only the four allowed
lookups, so anything else fails GraphQL validation before the subscribe
resolver runs. A second, runtime check (`_validate_client_filters`) still
validates the flattened key as defence in depth for anything that reaches the
engine without going through schema coercion:

1. the **root** (everything before the first `__`) must be a declared output
   field of the subscription's serialized payload;
2. every **remaining segment** must be a Django lookup or transform registered
   on that field;
3. every **remaining segment** must also be one of the four allowed lookups:
   `exact`, `iexact`, `in`, `isnull`;
4. the whole mapping must be a query the **ORM itself** can build.

| Filter | Verdict |
|--------|---------|
| `{ post: { exact: 7 } }` | accepted — equality, decided in memory |
| `{ post: { in: [7, 9] } }` | accepted — membership |
| `{ username: { iexact: "neo" } }` | accepted |
| `{ deletedAt: { isnull: true } }` | accepted |
| `{ authToken: { exact: "x" } }` | rejected — undeclared field, not in the input type |
| `{ groups: { name: { startswith: "adm" } } }` | rejected — relation traversal is unexpressible (the input is flat) |
| `{ password: { startswith: "pbkdf2" } }` | rejected — pattern lookup, not declared |
| `{ created: { gte: "2024-01-01" } }` | rejected — ordered lookup, not declared |
| `{ created: { year: { gte: 2024 } } }` | rejected — date-part transform, not declared |
| `{ text: { icontains: "urgent" } }` | rejected — pattern lookup, not declared |
| `{ tags: { iexact: 3 } }` | rejected — the ORM refuses `iexact` across a to-many join |

Schema rejections arrive as a normal GraphQL validation error and **no** group
is joined; a runtime rejection likewise raises **before** any group is joined,
and its message names the offending lookup alongside the allowed ones.

Step 4 exists because a Django field's declared lookup registry is **wider** than
what the query compiler accepts once a join is involved. A to-many field
(`tags`) declares `iexact` and then refuses it, so `{ tags: { iexact: 3 } }`
passed steps 1–3 and blew up at delivery instead — deep inside the stream, after
the SSE `200` was already committed. The engine now builds the same query at
subscribe time (no SQL is issued, only the lookup resolution), so an
unsatisfiable filter is a clean denial with no group joined.

**Why:** the `filter` argument executes as ORM lookups at event-delivery time
and delivery is observable, so a filter key is a boolean oracle. Rooting it on a
declared field bounds *which* column it can probe; restricting the lookup bounds
*how much* each probe reveals. An ordered or pattern lookup answers a
comparison, so a few hundred probes recover a password hash character by
character; equality and membership answer only "is it exactly this value?",
which forces a whole-value guess.

**What remains:** a client can still test **equality** against any declared
output field. That is a weak oracle for a high-entropy value and a real one for
a low-entropy value — a boolean flag falls in two probes. **Declared fields**
are the names returned by the subscription's `backend.output_field_names()`
**after** the `Meta.only_fields` / `Meta.exclude_fields` projection, so use that
projection to keep sensitive columns out of both the payload and the filter
surface. If you need tighter control still, override `subscription_scope` to
enforce server-side filters that cannot be widened or removed by the client.

!!! note "Relation and comparison lookups are server-side only"
    Multi-hop keys such as `{"author__name": "alice"}` and comparison keys such
    as `{"text__icontains": "urgent"}` are not accepted from a client — since
    2.1.0 they cannot even be written, because the generated input type is flat
    and declares only the four allowed lookups. Both remain available from
    `subscription_scope`, which is server code and therefore exempt from
    filter-key validation.

### Percent-encoded index group names

Subscription index fields (see `subscription_index_fields`) use `=` and `&`
as delimiters in the group name suffix.  Field **values** are percent-encoded
(`urllib.parse.quote`) before the suffix is assembled, so a value like `"a=b"`
no longer produces a name that is ambiguous with two separate key-value pairs.

### Asserts replaced with explicit raises

The validation guards in `Subscription.__init_subclass_with_meta__` that were
expressed as `assert` statements are now `raise TypeError(...)` calls.  Python's
`-O` flag strips `assert` at compile time; the explicit raises survive.

### Safe `async_to_sync` in signal handlers

The signal binding (`SubscriptionBinding`) calls `channel_layer.group_send`
from a synchronous Django signal handler.  Under an ASGI server a running event
loop is already present on the calling thread; a naive `async_to_sync(…)()`
call in that context deadlocks.

`bindings.py` detects whether a loop is running (`asyncio.get_running_loop`).
On the **ASGI path** (loop present), the coroutine is scheduled as a
fire-and-forget task via `loop.create_task` — the call returns immediately
without blocking the loop thread, and a done-callback logs any delivery failure
via the module logger.  On the **WSGI / sync path** (no running loop),
`async_to_sync` is used and errors propagate synchronously as before.

### Commit-time broadcast delivery

Subscription broadcasts (`_on_save`, `_on_delete`) are now deferred via
`django.db.transaction.on_commit`.  This means:

- **No phantom notifications**: if a nested write runs inside `transaction.atomic()`
  and a later child save raises an `IntegrityError` (triggering a rollback), the
  broadcast callbacks are discarded — subscribers never receive events for rows
  that were rolled back.
- **Auto-commit path unchanged**: when no explicit transaction is open, Django's
  auto-commit mode causes `on_commit` to call the callback immediately, so
  broadcast delivery is instant for standalone saves.
- **Nested `atomic()` blocks**: callbacks accumulate until the outermost
  transaction commits, matching Django's standard `on_commit` semantics.

!!! note "Test setup"
    Django's `TestCase` wraps every test in a transaction that is rolled back
    after the test; `on_commit` callbacks never execute inside that wrapper.
    If your subscription tests assert on `captured_group_sends`, mark them with
    `@pytest.mark.django_db(transaction=True)` so real commits occur.

### Async-safe subscription hooks

`authorize_subscription` and `subscription_scope` are synchronous classmethods
(user-overridable). When a subscription is driven inside an ASGI server (Daphne,
Uvicorn), the engine runs on the event loop, so both hooks are lifted via
`asgiref.sync_to_async` and execute in a thread-pool worker — they may make real
Django ORM queries safely. No change is needed in user code.

### JavaScript path escaping

`SubscriptionClientView` injects `ws_path` and `http_path` into inline
JavaScript via `json.dumps`, which escapes double quotes and backslashes.
Injecting raw strings would allow XSS if a path contained a double-quote
(`"`) that could close the surrounding JS string literal.

## Migrating from `graphene-django-subscriptions` / v1.x

!!! note "Full v2.0 upgrade guide"
    A comprehensive GRAPHENE → DJANGO_GRAPHEX upgrade guide (including the subscription
    transport cutover) ships with the v2.0 release notes. The steps below cover
    the subscription-specific moves.

The transport changed in v2.0: the HTTP `channelId` handshake, the
`GraphqlAPIDemultiplexer` consumer, and `SubscriptionGraphQLView` were removed in
favor of native SSE and `graphql-transport-ws`. To migrate:

1. Install the extra: `uv add "django-graphex[subscriptions]"` (or `pip install "django-graphex[subscriptions]"`).
2. Update imports to `django_graphex.subscriptions`.
3. Replace the demultiplexer consumer + `SubscriptionGraphQLView` URL with the
   native transports: route `subscription_ws_consumer(schema=...)` for WebSocket
   and/or mount `subscription_sse_view(schema=...)` for SSE (see
   [Serve subscriptions](#3-serve-subscriptions-over-sse-or-websocket)).
4. Update clients: drop the `channelId` / `operation` arguments and the
   `{ok, error, stream, operation, action}` confirmation selection — select the
   model's fields instead, and rely on the transport for unsubscribe (abort the
   SSE request or send a `graphql-transport-ws` `complete` — see
   [Unsubscribing](#unsubscribing)).
5. Notifications are **id-only by default**. If your clients relied on the full
   serialized payload, set `Meta.payload_mode = "full"` on those subscriptions or
   `DJANGO_GRAPHEX["SUBSCRIPTION_PAYLOAD_MODE"] = "full"` globally. See
   [Notification payload](#notification-payload).
6. Configure a Redis channel layer for multi-process deployments.
