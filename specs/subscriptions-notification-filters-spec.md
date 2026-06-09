# SPEC — Subscriptions: per-subscriber notification filters

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/subscriptions/{subscription,consumers,bindings,mixins}.py`,
subscription tests, `examples/playground`, docs.
**Date:** 2026-06-07
**Origin:** real use case — a post-detail page that subscribes to a model's
changes but must only receive the ones related to *that* parent (e.g. comments
of post X, not of every post).

---

## 1. Problem / Goals

Today a subscriber can scope notifications only by the changed object's **own
pk** (the `id` argument → per-object group) or not at all (the broad
`<model>-<action>` group). There is no way to say "only notifications where
`post == 7`". A reader on the Post 7 page receives comment notifications for
*every* post.

**Goals**

- **G1** — Add an optional `filters` argument to every subscription so a
  subscriber can scope delivery by field values, e.g. `filters: {post: 7}` or
  `filters: {text__icontains: "urgent"}`.
- **G2** — Evaluate filters **at delivery time, per connection**: the broad
  group still fans out, and each consumer decides whether the changed instance
  matches *its* stored filters before forwarding to its socket.
- **G3** — Fast path: plain-equality filters whose field is in the serialized
  payload are decided **in memory** (no DB). Anything else (lookups, fields not
  in the payload) falls back to a single-row DB check.
- **G4** — Per-connection isolation, reusing the existing `subscription.register`
  control-message pipeline (the same one that carries the field projection).
- **G5** — Tests + playground example (Comment ↔ Post) + docs.

### Non-Goals
- **Indexed dynamic groups** (route by `post=7` so non-matching subscribers are
  never woken). That is a scalability *optimization* layered on top of this and
  is tracked separately; this SPEC delivers the simple, expressive default.
- Integrating subscriptions into `DjangoSerializerType` (separate, later step).

## 2. Design

### 2.1 GraphQL argument
A `filters` argument (`GenericScalar`, optional) is added to every subscription's
arguments — a mapping of Django ORM lookup → value
(`{post: 7}`, `{text__icontains: "urgent"}`). Omitting it preserves today's
behavior (deliver everything in the group).

### 2.2 Wire pipeline (no new channel)
The subscribe resolver already sends a `subscription.register` control message
carrying the field projection; we add `filters` to it. The consumer stores it in
`self._filters[group_name]` (sibling of `self._fields`), created in `connect`,
set in `subscription_register`, dropped in `subscription_deregister`. State lives
per **connection** (one consumer instance per socket) → no cross-talk.

### 2.3 Delivery-time matching (`subscription_notify`)
Before projecting/sending, if the group has stored filters, the consumer decides:
1. **In memory** — for each plain-equality key (`no "__"`) present in the
   serialized `data`, compare `str(data[key]) == str(value)`. A mismatch drops
   immediately (no DB); a match is satisfied without DB.
2. **DB fallback** — remaining keys (lookups / fields absent from `data`) are
   checked once via `model.objects.filter(pk=<pk>, **remaining).exists()`
   (`database_sync_to_async`). Bad lookups fail closed (drop + log).

The binding adds the instance `pk` to the notify envelope (not the client
payload) so the DB check is robust regardless of which fields the serializer
exposes.

### 2.4 Edge cases (documented)
- `delete` + a DB-requiring filter: the row is gone, so only the in-memory path
  applies. With `serialize_data=True` the payload still carries the field values,
  so equality filters work; with id-only payloads, non-pk filters can't be
  evaluated on delete and the notification is dropped.
- Same connection re-subscribing to the same group with different filters: last
  wins (same `group_name` key), mirroring the existing `_fields` behavior.

## 3. Acceptance Criteria
- **AC1** — `filters: {post: X}` delivers only notifications whose instance has
  `post == X`; others are not delivered (e2e, two posts).
- **AC2** — A lookup filter (`text__icontains`) is honored via the DB fallback.
- **AC3** — No `filters` → unchanged behavior (all group notifications delivered).
- **AC4** — Per-connection isolation: two connections, different filters, each
  gets only its matches.
- **AC5** — Playground exposes `commentSubscription` + a `commentCreate` mutation
  to drive it; README/docs updated.
