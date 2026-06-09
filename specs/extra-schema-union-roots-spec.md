# SPEC — `ExtraGraphQLSchema`: union public + private roots

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/schema.py`, security tests,
`examples/playground`, docs.
**Date:** 2026-06-08
**Origin:** per-app modularity — each app defines a public and a private subset;
the project aggregates all public subsets into one root and all private into
another, and the schema's `subscription` / `private_subscription` (and
query/mutation) receive those two disjoint roots.

---

## 1. Problem / Goals

Previously `ExtraGraphQLSchema` passed `subscription=` straight to graphene and
read `private_subscription` only for **field names**. So the *full* set of fields
had to live in the public root, and the private fields were **duplicated** in a
marker root (e.g. the playground declared `note_subscription` in both
`RootSubscription` and `_PrivateSubscriptions`).

**Goals**

- **G1** — Treat each `private_*` as a **disjoint subset**: `query` /
  `mutation` / `subscription` carry the public fields, `private_*` the private
  fields, and the schema root is their **union**.
- **G2** — Apply uniformly to query, mutation and subscription.
- **G3** — Keep the private field names recorded as protected (unchanged).
- **G4** — **Back-compat**: a single full root + a `private_*` marker subset of
  names must keep working (no double-merge).
- **G5** — Tests + playground (queries + subscriptions to the disjoint form) +
  docs.

### Non-Goals
- Changing the `AuthenticatedFieldsMiddleware` / protection mechanism.

## 2. Design

`ExtraGraphQLSchema.__init__` pulls `query`/`mutation`/`subscription` out of the
kwargs (and supports a single positional query), and runs each through
`_merge_root(name, public, private)` before handing the result to
`graphene.Schema`:

```text
_merge_root:
  private is None            -> public
  public is None             -> private
  public is private          -> public
  private fields ⊆ public    -> public            # legacy full-root + marker
  otherwise                  -> type(name, (public, private, ObjectType), {})  # union
```

The subset check is what preserves back-compat: when the public root already
contains the private fields (the old marker pattern), the root is returned
unchanged and only protection is recorded.

## 3. Acceptance Criteria
- **AC1** — Disjoint public/private subscription roots → the schema's
  subscription type exposes the **union**, and only the private field is
  protected.
- **AC2** — Same for the query root.
- **AC3** — Back-compat: a full root + a marker subset still builds the same
  schema and protects the marker's names (existing security tests stay green).
- **AC4** — Playground passes disjoint subsets (no hand-built `RootQuery` /
  `RootSubscription`); `note_subscription` is declared once.
