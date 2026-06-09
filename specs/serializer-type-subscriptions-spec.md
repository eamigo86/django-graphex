# SPEC — `DjangoSerializerType` ↔ subscriptions integration

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/types.py`,
`graphene_django_extras/subscriptions/consumers.py`, subscription tests,
`examples/playground`, docs.
**Date:** 2026-06-08
**Origin:** "define once, get everything" — a single `DjangoSerializerType`
already yields queries and mutations; expose its subscription from the same
class so users don't write a parallel `Subscription` subclass.

---

## 1. Problem / Goals

A `DjangoSerializerType` and a `Subscription` both derive from a
`serializer_class`. The only extra a subscription needs is `stream` (and the
optional `serialize_data`). Today they are two separate declarations.

**Goals**

- **G1** — Add `stream` / `serialize_data` to `DjangoSerializerType.Meta`.
- **G2** — `cls.subscription_type()` returns a lazily-built, cached `Subscription`
  subclass; `cls.SubscriptionField()` mounts it on the schema's subscription root.
- **G3** — Keep the base install **Channels-free**: the `Subscription` import is
  done lazily inside `subscription_type()`, never at module import.
- **G4** — `GraphqlAPIDemultiplexer.subscriptions` also accepts an **iterable**
  (set/list) of `Subscription` / `DjangoSerializerType` classes, deriving each
  stream from `Meta.stream` (no key duplication), in addition to the legacy dict.
- **G5** — Tests (incl. a base-install channels-free probe) + playground + docs.

### Non-Goals
- Running `DjangoSerializerType.permission_classes` / `authorize` inside the
  generated subscription's subscribe (auth still via `private_subscription`).
- Mapping `filter_queryset` (row scoping) onto broadcast groups.

## 2. Design

### 2.1 `DjangoSerializerType`
`Meta` gains `stream` / `serialize_data` (stored on `DjangoSerializerOptions`).
`subscription_type()` builds `type(f"{cls.__name__}Subscription", (Subscription,),
{"Meta": ...})` from `serializer_class` / `stream` / `serialize_data`, caches it
on `cls._subscription_cls`, and raises `ImproperlyConfigured` when `stream` is
unset. The `from ...subscriptions import Subscription` is **inside** the method.
`SubscriptionField()` returns `subscription_type().Field(...)`.

### 2.2 Demultiplexer
`_resolved_subscriptions()` accepts a dict (legacy) or any non-dict iterable; for
iterables the stream is `subscription_cls._meta.stream`. `_resolve_subscription`
gains a branch: a value exposing `subscription_type()` (a `DjangoSerializerType`)
is resolved through it.

## 3. Acceptance Criteria
- **AC1** — `subscription_type()` returns a `Subscription` subclass with the
  expected `stream` / `model` / `serialize_data`, cached across calls.
- **AC2** — `SubscriptionField()` returns a `SubscriptionField`.
- **AC3** — Missing `Meta.stream` → `ImproperlyConfigured`.
- **AC4** — A demultiplexer with `subscriptions = {SomeDjangoSerializerType}`
  resolves to `{stream: generated Subscription}`.
- **AC5** — The generated subscription delivers notifications e2e.
- **AC6** — Importing the base (and defining a `DjangoSerializerType` with
  `stream`) does **not** import `channels`.
