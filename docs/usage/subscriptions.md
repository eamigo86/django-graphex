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

## How it works

The engine preserves the original **two-channel wire protocol**, reimplemented on
Channels 4:

1. A client opens a WebSocket. On connect the server replies with a handshake
   frame `{"channel_id": "<id>", "connect": "success"}`.
2. The client sends a GraphQL `subscription { ... }` operation **over HTTP**,
   echoing the `channelId` from the handshake. The resolver joins (or leaves) the
   relevant broadcast groups and returns a single confirmation
   `{ok, error, stream, operation, action}`.
3. When a model instance changes, an in-house signal binding serializes it once
   and broadcasts the payload to the group. Every subscribed WebSocket receives
   the notification, projected to the fields it requested.

A cross-process channel layer (Redis) is required when the HTTP and WebSocket
processes are separate; the in-memory layer is fine for development.

!!! tip "Try it interactively"
    Add the [browser client view](#browser-client-view) to your URLConf to
    connect, subscribe and watch notifications stream in — straight from the
    browser, served from your own server.

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

This generates, with the same names and semantics as the legacy package:

- **Output fields:** `ok`, `error`, `stream`, `operation`, `action`.
- **Arguments:** `channelId` (required), `action` (required), `operation`
  (required), `id` (optional), and — **only in full-payload mode** — `data`
  (optional, `[<Model>FieldsEnum]`). See
  [Notification payload](#notification-payload).
- **Enums:** `ActionSubscriptionEnum {CREATE, UPDATE, DELETE, ALL_ACTIONS}`,
  `OperationSubscriptionEnum {SUBSCRIBE, UNSUBSCRIBE}` and a generated
  `<Model>Fields` enum (full-payload mode only).

## 2. Mount it on the schema

```python
import graphene
from myapp.subscriptions import UserSubscription


class Subscription(graphene.ObjectType):
    user_subscription = UserSubscription.Field()


schema = graphene.Schema(query=Query, subscription=Subscription)
```

## 3. Wire the consumer and routing

```python
# myapp/consumers.py
from django_graphex.subscriptions import GraphqlAPIDemultiplexer
from myapp.subscriptions import UserSubscription


class AppDemultiplexer(GraphqlAPIDemultiplexer):
    subscriptions = {"users": UserSubscription}
```

```python
# project/asgi.py
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from myapp.consumers import AppDemultiplexer

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(
            [path("ws/", AppDemultiplexer.as_asgi())]
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

Mount it on the schema and wire the consumer:

```python
# schema.py
class Subscription(graphene.ObjectType):
    user_subscription = UserModelType.SubscriptionField()

# consumers.py — the demultiplexer also accepts an iterable (set/list); the
# stream is derived from each entry's Meta.stream, so you never repeat it.
class AppDemultiplexer(GraphqlAPIDemultiplexer):
    subscriptions = {UserModelType}        # or mix: {UserModelType, OtherSubscription}
```

`UserModelType.subscription_type()` builds (and caches) the `Subscription`
lazily, so the **base install stays Channels-free** until you actually wire a
subscription. The generated subscription supports the same arguments — including
[`filters`](#filtering-notifications). Setting `Meta.stream` is required to use
`SubscriptionField()` / `subscription_type()`.

!!! note "Demultiplexer auto-calls `subscription_type()`"

    When you pass a `DjangoModelType` directly to the demultiplexer's
    `subscriptions` dict (or set), `GraphqlAPIDemultiplexer` automatically calls
    `subscription_type()` on it to retrieve the generated `Subscription` class.
    You do **not** need to call `UserModelType.subscription_type()` yourself
    before passing the type — passing the `DjangoModelType` directly is the
    correct and intended pattern:

    ```python
    class AppDemultiplexer(GraphqlAPIDemultiplexer):
        subscriptions = {UserModelType}   # ✅ correct — auto-resolved
        # NOT: subscriptions = {UserModelType.subscription_type()}  # redundant
    ```

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

## 4. Serve subscriptions over HTTP

The standard `GraphQLView` cannot execute subscription operations. Use
`SubscriptionGraphQLView`, which resolves the one-shot subscribe/unsubscribe
confirmation:

```python
# urls.py
from django.urls import path
from django_graphex.subscriptions import SubscriptionGraphQLView

urlpatterns = [
    path("graphql", SubscriptionGraphQLView.as_view(graphiql=True)),
]
```

## Browser client view

`SubscriptionClientView` serves a self-contained HTML page (WebSocket + GraphQL)
to try subscriptions live. Add it to your URLConf like the admin — because it is
served from **your own origin**, there is no CORS to configure:

```python
# urls.py
from django_graphex.subscriptions import SubscriptionClientView

urlpatterns = [
    ...,
    path("graphql/client/", SubscriptionClientView.as_view()),
]
```

Open `/graphql/client/`: it connects the WebSocket (capturing the
`channel_id`), lets you send a `subscription { … }` over HTTP, and streams the
notifications back. The editor supports **Tab** to indent (Shift+Tab to outdent)
and **schema-aware autocomplete** — it introspects the configured HTTP endpoint
and suggests types, fields, arguments and enum values as you type (Ctrl+Space to
trigger, Enter/Tab to accept). If introspection is disabled on the server,
autocomplete falls back to GraphQL keywords only. The endpoints default to the
page's own host with the routes `/ws/graphql/` and `/graphql`; override them if
yours differ:

```python
path(
    "graphql/client/",
    SubscriptionClientView.as_view(ws_path="/ws/graphql/", http_path="/graphql"),
),
```

## 5. Subscribe from a client

```graphql
subscription {
  userSubscription(
    channelId: "the-channel-id-from-the-handshake"
    action: UPDATE
    operation: SUBSCRIBE
    id: 5
    data: [USERNAME, EMAIL]
  ) {
    ok
    error
    stream
    operation
    action
  }
}
```

- `action: ALL_ACTIONS` subscribes to `CREATE`, `UPDATE` and `DELETE`.
- Omit `id` to subscribe to **every** instance for that action.
- The `data` argument only exists in **full-payload mode** (see
  [Notification payload](#notification-payload)). When present, omit it to
  receive the full serialized payload, or pass a field list to project the
  notification `data` down to exactly those fields. In the default **id-only**
  mode there is no `data` argument.
- Use `operation: UNSUBSCRIBE` (same arguments) to stop receiving events.

### Filtering notifications

`id` scopes by the changed object's own primary key. To scope by **field
values** instead — e.g. a post-detail page that should only receive the comments
of *that* post — pass the optional `filters` argument: a mapping of Django ORM
lookup to value.

```graphql
subscription ($channelId: String!) {
  commentSubscription(
    channelId: $channelId
    action: ALL_ACTIONS
    operation: SUBSCRIBE
    filters: { post: 7 }          # only comments whose post == 7
  ) {
    ok error stream operation action
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
    subscription has **no `data`
    argument** and **no `<Model>Fields` enum** (there are no fields to pick), so
    clients that sent `data: [...]` must either drop it or opt back into full
    mode via `Meta.serialize_data = True` / the global setting. The argument's
    presence is fixed when the subscription class is defined.

## Per-connection field selection

In **full-payload mode**, field projection is tracked **per connection**, not on
the shared serializer, so two clients subscribed to the same group with
different `data` arguments each receive their own projection. (This fixes a
global-state race present in the legacy implementation.)

## Security hardening (v1.2.1)

Several security defenses were added in v1.2.1.  Knowing how they work helps
you integrate them correctly in production.

### Channel ownership guard (fail-closed)

The subscribe/unsubscribe HTTP mutation now verifies that the `channel_id`
argument belongs to the requesting session **before** any
`channel_layer.group_add` or `channel_layer.group_send` call.

**How it works:**

1. When the WebSocket consumer connects it registers the channel name with an
   ownership token derived from the Django session key
   (`request.session.session_key`).  Anonymous / sessionless connections
   register with an empty string token.
2. The registration is stored in Django's **`"default"` cache** under the key
   `dgx:subchan:<channel_name>` with a 24-hour TTL (refreshed on reconnect,
   deleted on disconnect).
3. The HTTP subscribe mutation must supply `_session_key` (injected
   automatically by the middleware or your own view).  If the presented token
   does not match the stored owner, the subscription is rejected with a
   `GraphQLError` and `ok: False`.
4. On disconnect the cache entry is removed so a reconnected socket with the
   same channel name cannot be claimed by a stale session.

**Fail-closed policy:** an unknown (never-registered) channel is also rejected,
so an attacker that guesses or intercepts a channel name cannot subscribe to it
before the legitimate owner has connected.

**Multi-worker deployments (important):** The guard reads and writes the
Django `"default"` cache.  With `LocMemCache` (Django's built-in in-memory
backend) each process has its own isolated cache, so if the WebSocket `connect`
request is handled by a different worker than the HTTP `subscribe` request the
guard will see the channel as unregistered and reject it.

To make the guard work correctly across workers you **must** configure a
**shared** cache backend (Redis or Memcached) in `CACHES["default"]`:

```python
# settings.py — Redis example
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379",
    }
}
```

If a shared cache cannot be provisioned, set
`DJANGO_GRAPHEX["SUBSCRIPTIONS_CHANNEL_GUARD"] = False` to bypass the guard
entirely.  This disables the channel-hijack protection — do it only as a
temporary measure.  The failure mode with the guard **on** and no shared cache
is a loud rejection (`ok: False`, `error: "channel_id is not registered"`),
never a silent data leak.

**Custom consumers:** if you subclass `GraphqlAPIDemultiplexer` and override
`connect`, call `register_channel(self.channel_name, session_key=<token>)` and
`unregister_channel(self.channel_name)` in `disconnect`.  The functions are
importable from `django_graphex.subscriptions.subscription`.

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

### Async-safe subscription hooks (v1.2.2)

`authorize_subscription` and `subscription_scope` are synchronous classmethods
(user-overridable).  When a subscription is processed inside an ASGI server
(Daphne, Uvicorn), the `_subscribe` coroutine runs on the event loop.
Calling a synchronous function that touches the Django ORM directly from that
coroutine raises `SynchronousOnlyOperation`, which is silently swallowed into
`ok: False` — making authenticated subscriptions appear permanently rejected.

Starting with v1.2.2, both hooks are lifted via `asgiref.sync_to_async` so they
execute in a thread-pool worker regardless of whether the implementation is
trivial or makes real ORM queries.  No change is needed in user code.

### Async-safe consumer cache I/O (v1.2.2)

`GraphqlAPIDemultiplexer.connect` and `disconnect` register and unregister the
channel in Django's default cache.  Under a non-`LocMemCache` backend (Redis,
Memcached) this is blocking network I/O.  Starting with v1.2.2, both calls are
wrapped in `sync_to_async` so the event loop is never stalled.

### Graceful disconnect without connect (v1.2.2)

If the WebSocket handshake is rejected (bad headers, auth failure) before the
`connect()` body executes, `disconnect()` is still called by Channels.  Before
v1.2.2 this raised an `AttributeError` because `_groups`, `_fields`, and
`_filters` were only initialized inside `connect()`.  They are now declared as
class-level defaults, making `disconnect()` safe in all scenarios.

### JavaScript path escaping

`SubscriptionClientView` injects `ws_path` and `http_path` into inline
JavaScript via `json.dumps`, which escapes double quotes and backslashes.
Injecting raw strings would allow XSS if a path contained a double-quote
(`"`) that could close the surrounding JS string literal.

## Migrating from `graphene-django-subscriptions`

The old package is now a thin, deprecated shim that re-exports from here. To
migrate:

1. Install the extra: `uv add "django-graphex[subscriptions]"` (or `pip install "django-graphex[subscriptions]"`).
2. Update imports to `django_graphex.subscriptions` (old import paths
   keep working for one deprecation cycle, emitting a `DeprecationWarning`).
3. Remove `channels_api` from `INSTALLED_APPS`.
4. Replace `routing.py` + `CHANNEL_LAYERS.ROUTING` with `asgi.py` +
   `ASGI_APPLICATION` (`ProtocolTypeRouter`/`URLRouter`).
5. Replace the `GRAPHENE.MIDDLEWARE` `depromise_subscription` entry with the URL
   served by `SubscriptionGraphQLView`.
6. Rename `consumers = {stream: Sub.get_binding().consumer}` to
   `subscriptions = {stream: Sub}` (the old form still works, with a warning).
7. Notifications are now **id-only by default**. If your clients relied on the
   full serialized payload (or sent a `data` field list), set
   `Meta.serialize_data = True` on those subscriptions or
   `DJANGO_GRAPHEX["SUBSCRIPTION_SERIALIZE_DATA"] = True` globally. See
   [Notification payload](#notification-payload).
8. Configure a Redis channel layer for multi-process deployments.
