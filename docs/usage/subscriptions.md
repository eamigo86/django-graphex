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
    backend. Set `GDX_BACKEND=native` (read at import time) for subscriptions to
    work. The legacy graphene transport (the HTTP `channelId` handshake, the
    demultiplexer consumer, and `SubscriptionGraphQLView`) was removed in v2.0 and
    replaced by two standards-based transports — see
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
        serialize_data = None                  # optional, see "Notification payload"
```

The notification payload is serialized through the native (Pydantic) backend.

This generates a real GraphQL `subscription` field whose **output type is the
model's projected fields** (the serialized instance) — a true streaming
subscription, not the legacy one-shot confirmation object. It exposes:

- **Arguments:** `action` (required, see the enum below), `id` (optional — scope
  to one instance by pk), and `filters` (optional — see
  [Filtering notifications](#filtering-notifications)). The legacy `channelId` and
  `operation` arguments are **gone** (the transport handles connection lifecycle).
- **Enum:** `ActionSubscriptionEnum {CREATE, UPDATE, DELETE, ALL_ACTIONS}`.

## 2. Mount it on the schema

```python
import graphene
from myapp.subscriptions import UserSubscription


class Subscription(graphene.ObjectType):
    user_subscription = UserSubscription.Field()


schema = graphene.Schema(query=Query, subscription=Subscription)
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
    path("graphql/stream", subscription_sse_view(schema=schema)),
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
            [path("ws/graphql/", subscription_ws_consumer(schema=schema).as_asgi())]
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

## From a `DjangoModelType` (one definition)

If you already use a [`DjangoModelType`](types.md#djangomodeltype) for
queries and mutations, you can get its subscription from the **same class** — no
separate `Subscription` subclass. Add `stream` (and optionally `serialize_data`)
to its `Meta`:

```python
from myapp.models import User

class UserModelType(DjangoModelType):
    class Meta:
        model = User
        stream = "users"          # enables the subscription
        serialize_data = True     # optional; defaults to the global setting
```

Mount it on the schema — then serve it through either transport (see
[Serve subscriptions](#3-serve-subscriptions-over-sse-or-websocket)):

```python
# schema.py
class Subscription(graphene.ObjectType):
    user_subscription = UserModelType.SubscriptionField()

schema = graphene.Schema(query=Query, subscription=Subscription)
```

`UserModelType.subscription_type()` builds (and caches) the `Subscription`
lazily, so the **base install stays Channels-free** until you actually wire a
subscription. The generated subscription supports the same arguments — including
[`filters`](#filtering-notifications). Setting `Meta.stream` is required to use
`SubscriptionField()` / `subscription_type()`. The transport (SSE or WS) is chosen
at routing time; the subscription class is transport-agnostic.

### Authorization and row-scoping

The generated subscription honors the type's authorization and scoping:

- **`permission_classes` / `authorize`** gate the **subscribe** itself. Authorize
  runs at registration (the HTTP request, so `info.context.user` is available)
  for the read-like `"subscribe"` action; a denial yields `ok: False` / `error`
  and no group is joined. `IsAuthenticatedOrReadOnly` therefore lets anyone
  subscribe to a public stream, while `IsAuthenticated` requires a login.
- **`subscription_scope(info, **kwargs)`** returns a server-forced filter mapping
  (e.g. `{"owner": info.context.user.pk}`). It is evaluated at subscribe time and
  enforced **per event at delivery**, merged over the client `filters` with
  server precedence — the client can neither widen nor drop it. Equality scopes
  on a serialized field (like `owner`) are decided **in memory**, so there is no
  per-event query.

```python
from myapp.models import Note

class NoteModelType(DjangoModelType):
    permission_classes = [IsAuthenticated]

    class Meta:
        model = Note
        stream = "notes"
        serialize_data = True

    @classmethod
    def subscription_scope(cls, info, **kwargs):
        return {"owner": info.context.user.pk}   # only my notes
```

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
from myapp.models import Message

class MessageModelType(DjangoModelType):
    class Meta:
        model = Message
        stream = "messages"
        serialize_data = True
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
- **Independent of `serialize_data`.** The index reads the live instance, not the
  payload, so it works in id-only mode too.
- The full filter is still applied on delivery, so indexing is purely a routing
  optimization -- correctness never depends on it.

## Browser client view

`SubscriptionClientView` serves a self-contained HTML page to try subscriptions
live. It speaks the same standards as the transports: `graphql-transport-ws` over
WebSocket and `graphql-sse` over an `EventSource`. Add it to your URLConf like the
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
routes `/ws/graphql/` (WS) and `/graphql` (HTTP); override them if yours differ:

```python
path(
    "graphql/client/",
    SubscriptionClientView.as_view(ws_path="/ws/graphql/", http_path="/graphql"),
),
```

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
- Unsubscribing is the transport's own lifecycle: close the SSE `EventSource`, or
  send a `graphql-transport-ws` `complete` for the operation id. There is no
  `operation: UNSUBSCRIBE` argument anymore.
- Which fields are deliverable depends on the payload mode — in id-only mode only
  `id` is present (see [Notification payload](#notification-payload)).

### Filtering notifications

`id` scopes by the changed object's own primary key. To scope by **field
values** instead — e.g. a post-detail page that should only receive the comments
of *that* post — pass the optional `filters` argument: a mapping of Django ORM
lookup to value.

```graphql
subscription {
  commentSubscription(
    action: ALL_ACTIONS
    filters: { post: 7 }          # only comments whose post == 7
  ) {
    id
    text
  }
}
```

Filters are evaluated **per connection at delivery time**:

- **Equality** filters (`{post: 7}`) are decided in memory against the
  serialized payload — no extra query.
- **Lookups** (`{text__icontains: "urgent"}`, `{created__gte: "..."}`) fall back
  to a single-row database check, so any Django lookup works.
- Combine them: `filters: { post: 7, text__icontains: "urgent" }`.
- Omitting `filters` keeps the previous behavior (every event in the group).

!!! note "Delete + lookup filters"
    On a `delete` the row no longer exists, so only the in-memory (equality)
    path applies. With `serialize_data = True` the payload still carries the
    field values, so equality filters work on deletes; with id-only payloads,
    non-pk filters cannot be evaluated on delete and the notification is dropped.

!!! tip "Scoping vs. security"
    Client-supplied `filters` are a **convenience** scope, not an authorization
    boundary. To enforce row-level access (e.g. "only my records"), gate the
    subscription with `private_subscription` / your auth layer rather than
    relying on a client-provided filter.

Each subscribed WebSocket receives notifications shaped like this in the default
**id-only** mode:

```json
{
  "stream": "users",
  "payload": {
    "action": "update",
    "model": "auth.user",
    "data": {"id": 5}
  }
}
```

…or, in **full-payload mode**, with the serialized instance (optionally
projected to the requested `data` fields):

```json
{
  "stream": "users",
  "payload": {
    "action": "update",
    "model": "auth.user",
    "data": {"username": "neo", "email": "neo@example.com"}
  }
}
```

## Notification payload

On every model change the binding builds the notification `data`. By default it
is **id-only** — `{"id": <pk>}` — which **skips serialization entirely** (the
fastest option for hot models, where clients typically refetch on notification).
Set it to **full** to serialize the whole instance through the native (Pydantic)
backend.

Two controls, in order of precedence:

| Control | Values | Effect |
|---------|--------|--------|
| `Meta.serialize_data` | `None` (default), `True`, `False` | Per-subscription. `None` inherits the global setting; `True` = full; `False` = id-only. |
| `DJANGO_GRAPHEX["SUBSCRIPTION_SERIALIZE_DATA"]` | `False` (default), `True` | Global default for subscriptions that don't override it. |

```python
# settings.py — make every subscription serialize the full instance by default
DJANGO_GRAPHEX = {
    "SUBSCRIPTION_SERIALIZE_DATA": True,
}
```

```python
# ...or decide per subscription, regardless of the global default
class UserSubscription(Subscription):
    class Meta:
        model = User
        stream = "users"
        serialize_data = True   # full payload for this one; True/False/None
```

!!! warning "id-only is the default"

    `graphene-django-subscriptions` always sent the full serialized instance.
    django-graphex defaults to id-only for performance. In id-only mode the
    payload carries only `{"id": <pk>}`, so a subscription selection set can
    deliver only `id` — to receive other fields, opt into full mode via
    `Meta.serialize_data = True` / the global setting. The payload mode is fixed
    when the subscription class is defined.

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

### Filter key validation

Client-supplied `filters` are now validated at subscribe time: each filter key
must **root on a declared output field** of the subscription's serialized
payload (everything before the first `__`).  Filters like
`{"username__icontains": "neo"}` are accepted (`username` is declared);
filters that root on non-output fields (e.g. `{"auth_token__key": "x"}`)
are rejected with a `GraphQLError`.

**Why:** the `filters` argument executes as ORM lookups at event-delivery time.
Without validation an attacker can use it as a boolean oracle over fields that
are never serialized in the payload (e.g. `{"password__contains": "a"}`).

**Declared fields** are the names returned by the subscription's
`backend.output_field_names()`.  Multi-hop lookups like
`{"groups__name": "admin"}` are accepted if `groups` is a declared output
field; the traversal into the `Group` model is handled by Django's ORM.  If
you need tighter control, override `subscription_scope` to enforce server-side
filters that cannot be widened or removed by the client.

### Percent-encoded index group names

Subscription index fields (see `subscription_index_fields`) use `=` and `&`
as delimiters in the group name suffix.  Starting with v1.2.1, field **values**
are percent-encoded (`urllib.parse.quote`) before the suffix is assembled, so
a value like `"a=b"` no longer produces a name that is ambiguous with two
separate key-value pairs.

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

### Commit-time broadcast delivery (v1.2.2)

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
    A comprehensive GRAPHENE → GRAPHEX upgrade guide (including the subscription
    transport cutover) ships with the v2.0 release notes. The steps below cover
    the subscription-specific moves.

The transport changed in v2.0: the HTTP `channelId` handshake, the
`GraphqlAPIDemultiplexer` consumer, and `SubscriptionGraphQLView` were removed in
favor of native SSE and `graphql-transport-ws`. To migrate:

1. Install the extra: `uv add "django-graphex[subscriptions]"` (or `pip install "django-graphex[subscriptions]"`).
2. Set `GDX_BACKEND=native` — subscriptions are native-only in v2.0.
3. Update imports to `django_graphex.subscriptions`.
4. Replace the demultiplexer consumer + `SubscriptionGraphQLView` URL with the
   native transports: route `subscription_ws_consumer(schema=...)` for WebSocket
   and/or mount `subscription_sse_view(schema=...)` for SSE (see
   [Serve subscriptions](#3-serve-subscriptions-over-sse-or-websocket)).
5. Update clients: drop the `channelId` / `operation` arguments and the
   `{ok, error, stream, operation, action}` confirmation selection — select the
   model's fields instead, and rely on the transport for unsubscribe (close the
   `EventSource` or send a `graphql-transport-ws` `complete`).
6. Notifications are **id-only by default**. If your clients relied on the full
   serialized payload, set `Meta.serialize_data = True` on those subscriptions or
   `DJANGO_GRAPHEX["SUBSCRIPTION_SERIALIZE_DATA"] = True` globally. See
   [Notification payload](#notification-payload).
7. Configure a Redis channel layer for multi-process deployments.
