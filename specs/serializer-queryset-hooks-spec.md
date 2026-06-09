# SPEC — B: `get_queryset` / `filter_queryset` hooks on `DjangoSerializerType`

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/types.py`, tests, docs.
**Date:** 2026-06-07
**Origin:** downstream `ISNDjangoSerializerType.get_queryset` / `filter_queryset`.
Piece **B** of the SerializerType work (A done → B → C → D). Depends on A (the
injected `cls.retrieve` / `cls.list` now actually run).

---

## 1. Problem / Goals

`DjangoSerializerType` reads from `cls._meta.queryset` (a static base) and has no
override point to (a) build a **custom base queryset** per type (e.g. add
`select_related` / `annotate`) or (b) **filter per request** (e.g. scope rows to
the current user). Today you can only set a static `Meta.queryset`.

**Goals**
- **G1** — `get_queryset(cls, manager, info, **kwargs)` override hook that supplies
  the base queryset for retrieve/list.
- **G2** — `filter_queryset(cls, qs, info, **kwargs)` override hook applied inside
  `get_queryset` for per-request scoping.
- **G3** — Mutation responses reflect `get_queryset` (so annotated/related fields
  resolve), without ever dropping the just-mutated object from the response.

### Non-Goals
- Permission checks (piece C) — no superuser/permission logic here.
- Changing the read optimization (`queryset_factory`) or the filterset flow.

## 2. Design

Add two classmethods to `DjangoSerializerType`, consistent with the existing
`DjangoListObjectType.get_queryset(cls, queryset, info)` hook (both use `info`;
`info.context` is the request):

```python
from django.db.models import Manager

@classmethod
def get_queryset(cls, manager, info, **kwargs):
    """Base queryset for retrieve/list. Override to customize (annotate, etc.)."""
    qs = cls._meta.queryset if cls._meta.queryset is not None else manager
    if isinstance(qs, Manager):
        qs = qs.all()
    return cls.filter_queryset(qs, info, **kwargs)

@classmethod
def filter_queryset(cls, qs, info, **kwargs):
    """Per-request scoping hook. Override; default returns `qs` unchanged."""
    return qs
```

### 2.1 Wire into the read resolvers
`retrieve` and `list` take their base from `get_queryset` instead of
`cls._meta.queryset` directly; `queryset_factory` + the filterset flow are
unchanged:

```python
# retrieve
pk = kwargs.pop("id", None)
base = cls.get_queryset(manager, info, **kwargs)
qs = queryset_factory(base, root, info, **kwargs)
return qs.get(pk=pk)   # (DoesNotExist -> None, as today)

# list
base = cls.get_queryset(manager, info, **kwargs)
qs = queryset_factory(base, root, info, **kwargs)
qs = filterset_class(data=filter_kwargs, queryset=qs).qs
...
```

### 2.2 Mutation responses reflect `get_queryset`
`perform_mutate` re-reads the mutated object through `get_queryset` so
annotated/related fields resolve in the create/update response — but falls back
to the saved object if the re-fetch yields nothing (e.g. `filter_queryset`
excludes it), so a mutation never returns `null` for an object it just wrote:

```python
@classmethod
def perform_mutate(cls, obj, info):
    refreshed = (
        cls.get_queryset(cls._meta.model._default_manager, info, obj=obj)
        .filter(pk=obj.pk)
        .first()
    )
    resp = {cls._meta.output_field_name: refreshed or obj, "ok": True, "errors": None}
    return cls(**resp)
```
Cost: one extra query per successful create/update (documented).

## 3. Acceptance Criteria
- **AC1** Default `get_queryset` returns the `Meta.queryset` (as a queryset) passed
  through `filter_queryset`; default `filter_queryset` returns it unchanged;
  behavior is unchanged for types that don't override. [G1,G2]
- **AC2** Overriding `get_queryset` (e.g. `.annotate(...)`) is reflected by both
  list and retrieve. [G1]
- **AC3** Overriding `filter_queryset` (e.g. scope by `info.context.user`)
  restricts both list and retrieve (an excluded id retrieves as `null`). [G2]
- **AC4** With `filter_queryset` excluding everything, a `create` still returns the
  created object (`ok: true`, object not null) — the fallback. [G3]
- **AC5** Full suite green; base channels-free; lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/`)
A `DjangoSerializerType` on `BasicModel`:
- AC2: override `get_queryset` to `.annotate(...)` a computed value; expose it and
  assert list/retrieve show it (or assert the queryset is the overridden one).
- AC3: override `filter_queryset` to `qs.filter(text__startswith="keep")`; create
  in/out rows; assert list returns only the subset and retrieve of an excluded id
  is `null`.
- AC4: override `filter_queryset` to `qs.none()`; `create` returns `ok: true` with
  the object (fallback).
- AC1: a type without overrides keeps returning all rows.

## 5. Documentation
`docs/usage/types.md` (DjangoSerializerType): document `get_queryset` /
`filter_queryset`, the `info`/`info.context` signature, and that mutation
responses reflect `get_queryset` (with the extra-query note). Mirror the
downstream example (annotate + per-user scoping).

## 6. Definition of Done
1. SPEC approved. 2. Hooks + wiring per §2. 3. §3 ACs green via §4; full suite
green; base channels-free; lint + `mkdocs --strict` green. 4. Docs updated.
5. Committed and pushed to `pre-v2`.
