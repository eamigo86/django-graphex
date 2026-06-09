# SPEC — Subscriptions honor `DjangoSerializerType` auth + row-scoping

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/{permissions,types}.py`,
`graphene_django_extras/subscriptions/subscription.py`, subscription tests,
`examples/playground`, docs.
**Date:** 2026-06-08
**Origin:** Phase 2 of the `DjangoSerializerType` subscription integration —
"the subscription should respect the type's definition", with the explicit
priority of being airtight (no security gaps) without a big performance cost.

---

## 1. Problem / Goals

The generated subscription ignored the type's `permission_classes` / `authorize`
and any row-scoping, so anyone could subscribe and a broadcast subscription on a
scoped model leaked other users' changes.

**Key constraint.** The user is available at **subscribe** (HTTP → `info.context`)
but not necessarily at **notify** (the WebSocket consumer may be unauthenticated).
And `filter_queryset` is an opaque queryset transform — applying it per event
needs the request and a per-event query.

**Goals**

- **G1** — Gate the subscribe with `permission_classes` / `authorize`, evaluated
  at registration, as a read-like `"subscribe"` action. Denial → `ok: False`.
- **G2** — Row-scope deliveries with a **server-forced filter** captured at
  subscribe time and enforced per event at delivery, in memory where possible
  (no per-event query for equality scopes), with **no** WebSocket-auth
  requirement.
- **G3** — The forced scope cannot be widened or dropped by the client.
- **G4** — Zero overhead for subscriptions that declare neither.
- **G5** — Tests + playground (Note owner-scoping) + docs.

### Non-Goals
- Re-running `filter_queryset` at notify time (opaque + per-event query + needs an
  authenticated WS). `subscription_scope` is the explicit, performant equivalent.

### Follow-up (implemented): indexed groups
- **G6** — `Meta.subscription_index_fields` routes a change to a value-scoped
  group built from the instance (`<base>:k=v&...`, keys sorted, via `safe_group_name`)
  so only matching subscribers are woken. Opt-in/additive; a field absent from the
  scope falls back to the coarse group. Channels has **no group enumeration**, so
  the broadcast side *constructs* the exact name from the instance (reading each
  field's `attname`) rather than searching groups — the subscribe and broadcast
  sides agree by construction.
- **AC6** — A subscription indexed by `text` scoped to `text="keep"` receives a
  `text="keep"` change but never a `text="drop"` one (routed to a different group),
  proving the two sides build the same name end-to-end. Validation: an unknown
  index field fails fast at class definition.

## 2. Design

- **`permissions.py`**: `"subscribe"` is a read action (`READ_ACTIONS`) and
  `BasePermission` gains `has_subscribe_permission` (delegates to
  `has_permission(info, "subscribe", model)`).
- **`Subscription`** base gains two hooks (no-op / `None` defaults):
  `authorize_subscription(info, **kwargs)` and
  `subscription_scope(info, **kwargs) -> dict | None`. `_subscribe` calls
  `authorize_subscription` first (a raised `GraphQLError` is surfaced as
  `ok: False`), then merges `subscription_scope` over the client `filters` with
  **server precedence** before the existing `subscription.register` carries them.
- **`DjangoSerializerType`** gains a `subscription_scope(info, **kwargs)` hook
  (default `None`); `subscription_type()` injects, on the generated subscription,
  `authorize_subscription -> parent.authorize(info, "subscribe")` and
  `subscription_scope -> parent.subscription_scope(info, ...)`.
- Delivery reuses the existing notify-time `split_filters` pipeline (in-memory
  equality, DB fallback only for lookups).

## 3. Acceptance Criteria
- **AC1** — A type with `IsAuthenticated`: anonymous subscribe → `ok: False`;
  authenticated → `ok: True`.
- **AC2** — A `subscription_scope` of `{text: "keep"}` delivers only matching
  changes; non-matching are dropped (decided in memory).
- **AC3** — The forced scope overrides a conflicting client `filters` key.
- **AC4** — No hook declared → unchanged behavior, no extra query.
- **AC5** — Playground `NoteModelType` scopes its subscription to the owner.
