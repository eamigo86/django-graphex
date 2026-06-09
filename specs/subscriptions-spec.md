# SPEC — GraphQL Subscriptions as an optional `graphene-django-extras[subscriptions]` extra

**Status:** APPROVED — implemented in `graphene-django-extras 1.2.0`.

> This design document originated in the `graphene-django-subscriptions` repo and
> now lives here, alongside the implementation it describes. The open questions in
> §15 were resolved before implementation (see the **Resolution** notes).

**Decision baseline (approved):**
- Wire protocol: **preserve** the current model (`channel_id` handshake + HTTP-resolved subscribe), reimplemented on Channels 4.
- Engine: **native in-house** (Django signals + Channels channel layer); drop `channels-api`.
- Packaging: **merge** subscriptions into `graphene-django-extras` as an optional
  `[subscriptions]` extra; keep `graphene-django-subscriptions` as a **deprecated
  compatibility shim**.
- Process: **SDD** — this document is the contract.

**Target release:** `graphene-django-extras 1.2.0` (adds the `subscriptions` extra) +
`graphene-django-subscriptions 0.1.0` (final, shim-only).
**Date:** 2026-06-05

---

## 1. Overview, Goals & Non-Goals

### 1.1 Context

`graphene-django-subscriptions` adds GraphQL subscriptions to `graphene-django` on top of
Django Channels. Its original code targeted a **Channels 1.x** world that no longer exists
(`channels-api` deprecated; `Group`/`WebsocketDemultiplexer`/`reply_channel`/`route_class`
removed; `rx`/`six`/`promise` are Python-2/graphene-2 era).

`graphene-django-extras` already runs on the modern stack and — critically — **already
depends on `djangorestframework`** (it powers `DjangoSerializerType`/`DjangoSerializerMutation`).
Subscriptions are built on the very same `serializer_class` abstraction. Therefore
subscriptions are merged into extras as an **opt-in** feature: base users get zero new
dependencies; subscription users opt in via the `subscriptions` extra.

### 1.2 Goals

- **G1** — Modern stack: Python ≥ 3.12, Django ≥ 4.0, graphene-django ≥ 3.2, Channels ≥ 4.0.
- **G2** — Install UX: base install never imports channels;
  `pip install "graphene-django-extras[subscriptions]"` enables subscriptions.
- **G3** — Preserve the public API and the wire protocol; old import paths keep working
  through the shim.
- **G4** — Native in-house broadcast engine replacing `channels-api`.
- **G5** — Async consumer, O(1) fan-out per event.
- **G6** — Fix latent correctness bugs without changing the public contract.
- **G7** — Rigorous tests + a CI matrix that proves base install stays channels-free.

### 1.3 Non-Goals

- **NG1** — Apollo `graphql-ws`/`graphql-transport-ws` protocol (legacy protocol preserved).
- **NG2** — Changing subscription schema semantics beyond the §11 correctness fixes.
- **NG3** — Python 2 / Channels < 4 / graphene < 3.
- **NG4** — Porting the `channels-api` inbound CRUD-over-websocket feature.

---

## 2. Deliverables & Repositories

| Repo | Role after this work |
|------|----------------------|
| `eamigo86/graphene-django-extras` | **Primary.** `graphene_django_extras/subscriptions/` package; `[subscriptions]` extra; tests; docs. Released as `1.2.0`. |
| `eamigo86/graphene-django-subscriptions` | **Shim.** Re-exports from extras with `DeprecationWarning`. Released as `0.1.0` (final). |

---

## 3. Target Compatibility Matrix

| Component            | Constraint        | Notes                                       |
|---------------------|-------------------|---------------------------------------------|
| Python              | `>=3.12,<4.0`     | Matches extras                              |
| Django              | `>=4.0,<7.0`      | CI tests 4.2 (LTS), 5.x, 6.0                |
| Channels            | `>=4.0,<5.0`      | **extra only**                              |
| channels-redis      | `>=4.2`           | **extra only**, prod multi-process          |
| graphene-django     | `>=3.2,<4.0`      | already an extras core dep                   |
| graphql-core        | `>=3.2,<3.3`      | transitive; `subscribe()` async path         |
| djangorestframework | `^3` (≥3.14)      | already an extras **core** dep (shared)      |
| django-filter       | `>=22.1`          | already an extras core dep                   |

**Removed for good:** `channels-api`, `rx`, `six`, `promise`.

---

## 4. Old → New Architecture Mapping

| Channels 1.x (legacy)                           | Channels 4 (new)                                                 |
|-------------------------------------------------|------------------------------------------------------------------|
| `message.reply_channel`                         | `consumer.channel_name`                                          |
| `Group(name).add(reply_channel)`                | `await channel_layer.group_add(name, channel_name)`             |
| `Group(name).discard(reply_channel)`            | `await channel_layer.group_discard(name, channel_name)`         |
| `Group(name).send({"text": …})`                 | `await channel_layer.group_send(name, event)`                   |
| `WebsocketDemultiplexer`                         | `AsyncJsonWebsocketConsumer` subclass                            |
| `channels_api` `ResourceBinding`                | in-house `SubscriptionBinding` (signals→`group_send`)           |
| `route_class` + `CHANNEL_LAYERS.ROUTING`        | `ProtocolTypeRouter`/`URLRouter` + `ASGI_APPLICATION`           |
| `rx.Observable.from_([conf])`                   | `async def _subscribe` generator yielding one confirmation       |
| `depromise_subscription` middleware             | `SubscriptionGraphQLView` HTTP executor                          |

**Two-channel flow (preserved):** (1) WS connect → server sends
`{"channel_id", "connect":"success"}`; (2) client POSTs a GraphQL `subscription{…}` over
HTTP echoing `channelId` → resolver joins/leaves groups, returns one-shot confirmation;
(3) model change → binding broadcasts serialized payload to the group → subscribers receive
it over WS.

---

## 5. Packaging Design

### 5.1 Dependency isolation (Poetry)

```toml
[tool.poetry.dependencies]
channels       = { version = ">=4.0,<5.0", optional = true }
channels-redis = { version = ">=4.2",      optional = true }

[tool.poetry.extras]
subscriptions = ["channels", "channels-redis"]
```

### 5.2 Import isolation

- All subscription code lives under `graphene_django_extras/subscriptions/`.
- `graphene_django_extras/__init__.py` does **not** import that subpackage (enforced by
  T-ISO).
- `graphene_django_extras/subscriptions/__init__.py` guards channels at import time with a
  friendly `[subscriptions]` error.

### 5.3 Canonical public import paths

```python
from graphene_django_extras.subscriptions import (
    Subscription, GraphqlAPIDemultiplexer, SubscriptionGraphQLView,
)
```

### 5.4 Compatibility shim — `graphene-django-subscriptions` 0.1.0 (final)

Reduced to `pyproject.toml` depending on `graphene-django-extras[subscriptions] >=1.2,<2`
plus a module tree mirroring the old import paths, each re-exporting from the new location
and emitting `DeprecationWarning`.

---

## 6. Public API Contract (preserved)

`Subscription` (Meta keys, output fields `ok/error/stream/operation/action`, arguments
`channelId/action/operation/id/data`, the `ActionSubscriptionEnum`/`OperationSubscriptionEnum`
and generated `<Model>Fields` enums, and the classmethods `Field`, `model_label`,
`_group_name`, `get_binding`) all behave as before. `GraphqlAPIDemultiplexer` is now an
`AsyncJsonWebsocketConsumer`. `get_binding()` returns a `SubscriptionBinding` (legacy
`.consumer` alias preserved). `SubscriptionGraphQLView` replaces the
`depromise_subscription` middleware. See [the subscriptions guide](../docs/usage/subscriptions.md).

---

## 7. Component Design

- **7.1 `Subscription` type** — graphene-3 enum/argument generation kept verbatim
  (`six.string_types`→`str`). The requested-field set is carried per-connection (§7.5),
  not on the shared `serializer_class.Meta`.
- **7.2 `SubscriptionBinding`** — per `(model, stream)`: `post_save`/`post_delete` receivers
  deduplicated via stable `dispatch_uid`; serialize once; `group_send` to `"<label>-<action>"`
  and `"<label>-<action>-<pk>"` with `{"type":"subscription.notify", …}`.
- **7.3 `SubscriptionGraphQLView`** — for `operation == "subscription"`, calls graphql-core
  `subscribe(...)`, drives the async iterator for exactly one value
  (`__anext__` then `aclose`), and returns that `ExecutionResult`.
- **7.4 `_subscribe` async generator** — resolves channel name from `channel_id`;
  `ALL_ACTIONS` iterates `(create, update, delete)`; `SUBSCRIBE`→`group_add` + register
  control message, `UNSUBSCRIBE`→`group_discard` + deregister; yields one confirmation.
  Over-long/invalid group labels are hashed.
- **7.5 Per-connection field selection** — on `SUBSCRIBE` the resolver
  `channel_layer.send(channel_name, {"type":"subscription.register","group":g,"fields":[…]})`;
  the consumer keeps `self._fields[group]` and filters notify payloads before `send_json`.
  `None`/empty ⇒ full data.
- **7.6 Consumer & routing** — `connect` accepts + sends the handshake + ensures bindings
  registered; handlers `subscription_notify`/`register`/`deregister`; best-effort
  `group_discard` on `disconnect`. Routing via `ProtocolTypeRouter`/`URLRouter` +
  `ASGI_APPLICATION`; prod uses a Redis channel layer.

---

## 8. File-level Plan (as built)

`graphene_django_extras/subscriptions/`: `__init__.py` (import-guard + exports),
`subscription.py`, `consumers.py`, `bindings.py`, `mixins.py`, `views.py`, `compat.py`.
Tests under `tests/subscriptions/`. Base-install proof in `scripts/check_base_install.py`.

---

## 9. Migration Guide (end users)

See the [subscriptions guide](../docs/usage/subscriptions.md#migrating-from-graphene-django-subscriptions).

---

## 10. Backward-Compatibility & Deprecations

- **Preserved:** `Subscription`, `GraphqlAPIDemultiplexer`, the wire protocol, and old
  import paths via the shim.
- **Deprecated (works + `DeprecationWarning`):** `graphene_django_subscriptions.*` imports;
  `consumers={stream: Sub.get_binding().consumer}` form; `depromise_subscription`.
- **Breaking (documented):** Channels-4 routing/settings change; `info.context.reply_channel`
  gone (resolver uses `channelId`); Python 2 / graphene 2 / Channels < 4 dropped.

---

## 11. Correctness / Security Fixes (no public-contract change)

- **11.1** `only_fields` global mutation race fixed by per-connection field selection (§7.5).
- **11.2** Broad `except Exception` swallowing replaced with logging; never catch `BaseException`.
- **11.3** Channels group-name charset/length enforced; overflowing labels hashed.
- **11.4** Idempotent signal registration via `dispatch_uid`.

---

## 12. Acceptance Criteria

AC1–AC11 as originally specified; each maps to ≥1 test in §14 and all pass. AC11's
base-install (no-extra) job asserts channels is absent.

---

## 13. Packaging & CI

extras `pyproject.toml` gains optional `channels`/`channels-redis` + the `subscriptions`
extra. CI (GitHub Actions): matrix Python {3.12, 3.13, 3.14} × Django {4.2, 5.0, 5.1, 5.2,
6.0}, running the subscription suite with the extra; a dedicated **base-install** job runs
`tox -e base-install` to assert `channels` is not importable and the base import works.

---

## 14. Test Plan

`pytest` + `pytest-django` + `pytest-asyncio`, Channels `WebsocketCommunicator` and
`InMemoryChannelLayer`. Suites: T-ISO, T-IMPORT, T-UNIT, T-CONSUMER, T-RESOLVER, T-VIEW,
T-E2E, T-CONCURRENCY, T-COMPAT, T-BINDING. Coverage ≥ 90% on subscription modules.

---

## 15. Risks & Open Questions

- **R1** HTTP-resolved subscribe needs a shared channel layer across HTTP+WS processes
  (Redis in prod). Documented; dev default InMemory.
- **R2** `SubscriptionGraphQLView` targets graphql-core's documented `subscribe()`.
- **R3** Field projection ships full data over the layer; fine for typical models.
- **R4** Release coupling: a subscriptions fix ships in an extras release. Accepted.
- **OQ1** `channel_id` value — **RESOLVED: use `self.channel_name` directly** (the resolver
  uses `channelId` as the channel name verbatim). The opaque-token indirection was not
  adopted.
- **OQ2** Django floor in CI — **RESOLVED: declare `>=4.0` but CI-test from `4.2`** (4.0/4.1
  are upstream-EOL). The CI matrix and tox envlist start at Django 4.2.
- **OQ3** Session scope — **RESOLVED: implemented in the `graphene-django-extras` repo**
  (this document and the code now live here).

---

## 16. Definition of Done

1. SPEC approved. ✔
2. extras `1.2.0`: `subscriptions/` package + `[subscriptions]` extra; all §12 ACs green via
   §14 tests; base install proven channels-free. ✔
3. shim `graphene-django-subscriptions` `0.1.0`: re-exports + deprecation warnings. *(separate repo)*
4. CI matrices green incl. the base-install no-extra job. ✔
5. READMEs + migration guide updated. ✔
6. Changes committed/pushed to the designated branch. ✔
