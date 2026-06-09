# SPEC — Option A: eliminate N+1 on *filtered* nested lists (filtered `Prefetch`)

**Status:** APPROVED — implement in `graphene-django-extras 1.2.0`.
**Builds on:** `specs/nested-list-shape-spec.md` (nested `results`/`totalCount`) and
`specs/queryset-optimization-spec.md` (select/prefetch/only).
**Scope:** `utils.py` (optimizer), `fields.py` (`DjangoNestedListObjectField`),
tests, docs.
**Date:** 2026-06-06

---

## 1. Problem

A nested list **with filters** currently bypasses the `prefetch_related` cache (a
`FilterSet` needs a queryset), so it runs **one query per parent** (N+1). Goal:
fetch the *filtered* related set in **one query for all parents** using a
`django.db.models.Prefetch` whose queryset carries the (same-for-all-parents)
nested filter; per-parent pagination/ordering stay **in memory** over that cache.

## 2. Goals / Non-Goals

### Goals
- **G1** — When a nested list field has filter args, the parent query attaches a
  `Prefetch(lookup, queryset=<filtered queryset>)` so the filtered children are
  fetched in **one** query for all parents (no per-parent N+1).
- **G2** — The nested resolver reads that (already-filtered) prefetch cache and
  paginates/orders **in memory** (existing machinery); `totalCount` = filtered
  set size.
- **G3** — Falls back to the per-parent DB query only when the relation was **not**
  prefetched (e.g. `OPTIMIZE_QUERYSET=False`); honors the same setting.
- **G4** — Works for the single-object path too and for deeper nesting
  (`a__b` Prefetch lookups). Tests with `assertNumQueries`.

### Non-Goals
- **NG1** — Window-function per-parent SQL slicing (kept in memory). Pagination of
  a nested list still loads its filtered set into memory.
- **NG2** — Per-parent *different* filters (GraphQL gives one filter value per
  nested field for the whole query — the `Prefetch` filter is shared, which is
  exactly the semantics).

## 3. Design

### 3.1 Recover the nested field from the schema
graphene builds each nested list field's resolver as
`functools.partial(field.list_resolver, manager, filterset_class, filtering_args)`.
From a `GraphQLField.resolve` we recover the **field instance** via
`resolve.func.__self__` (a `DjangoNestedListObjectField`) and its `accessor` /
`filterset_class` / `filtering_args`. This lets the optimizer walk the **GraphQL
types alongside the selection AST**.

### 3.2 Build filtered prefetches (new optimizer pass)
`build_filtered_prefetches(info) -> list[Prefetch]` walks, from `info.return_type`,
the selection set and the GraphQL field defs together. For every selected field
whose resolver is a `DjangoNestedListObjectField.list_resolver`:
- extract the field's arguments from the AST node (resolving `VariableNode`s via
  `info.variable_values`);
- keep only the ones in `filtering_args` → `filter_kwargs`;
- if non-empty, build `Prefetch(<dotted lookup>, queryset=<filtered qs>)` via the
  field instance (§3.3) and recurse into the field's list type to discover deeper
  nested filtered lists (`a__b`).

Dotted lookup is accumulated like `recursive_params` (transparent through the
`results` wrapper).

### 3.3 `DjangoNestedListObjectField.build_prefetch(lookup, filter_kwargs, info)`
```python
qs = self.type._meta.model._default_manager.all()
if filter_kwargs and self.filterset_class is not None:
    qs = self.filterset_class(data=filter_kwargs, queryset=qs,
                              request=getattr(info, "context", None)).qs
return Prefetch(lookup, queryset=qs)
```
Only the **filter** is applied here; **ordering and pagination happen in memory**
downstream (the `results` paginator), so the Prefetch queryset is order-agnostic.

### 3.4 `queryset_factory`
After applying `select_related` / plain `prefetch_related` / `only`, apply the
filtered prefetches **last** so they override the plain prefetch for the same
lookup (Django: the last prefetch for a lookup wins):
```python
filtered = build_filtered_prefetches(info)
if filtered:
    base = base.prefetch_related(*filtered)
```

### 3.5 `DjangoNestedListObjectField.list_resolver`
Prefer the prefetch cache; only hit the DB per-parent when not prefetched:
```python
cache = getattr(root, "_prefetched_objects_cache", {})
if self.accessor in cache:                      # filtered or full, already fetched
    results = list(cache[self.accessor])
    return DjangoListObjectBase(count=len(results), results=results, ...)
# not prefetched -> resolve directly (filtered DB query or full list)
...
```

## 4. Acceptance Criteria
- **AC1** — A *filtered* nested list across P parents runs a **constant** number of
  queries (a single filtered `Prefetch` for the whole level). [assertNumQueries]
- **AC2** — The filtered nested list returns the correctly filtered rows, with
  `totalCount` = filtered size, and in-memory `limit`/`offset`/`ordering` applied.
- **AC3** — Deeper nesting (`posts(filter) { results { comments(filter) … } }`)
  uses nested `Prefetch` lookups; still constant queries.
- **AC4** — With `OPTIMIZE_QUERYSET=False`, the per-parent DB fallback is used
  (correct results, more queries).
- **AC5** — Unfiltered nested lists are unchanged (plain prefetch + in-memory);
  existing nested tests stay green.
- **AC6** — Full suite green; base channels-free; lint + `mkdocs --strict` green.

## 5. Test Plan (`tests/test_nested_lists.py`)
- `test_filtered_nested_constant_queries`: P authors, `posts(title_Icontains)` →
  `assertNumQueries` constant (vs the old per-parent count). [AC1]
- `test_filtered_nested_correct_and_paginated`: filtered rows + `limit`/`ordering`
  in memory + `totalCount`. [AC2]
- `test_filtered_fallback_when_optimization_disabled`: `OPTIMIZE_QUERYSET=False`
  still returns correct rows. [AC4]
- Update the existing `test_filtered_nested_costs_extra_queries` (now constant).

## 6. Documentation
- Update `docs/usage/nested-lists.md`: filtered nested lists are now N+1-free via a
  filtered `Prefetch`; note the in-memory pagination and the
  `OPTIMIZE_QUERYSET=False` fallback.

## 7. Definition of Done
1. SPEC approved.
2. Optimizer pass + field methods per §3; resolver prefers the cache.
3. §4 ACs green via §5 tests; full suite green; base channels-free; lint +
   `mkdocs --strict` green.
4. Docs updated.
5. Committed and pushed to `pre-v2`.
