# SPEC — Query optimization (`queryset_factory` / nested N+1)

**Status:** APPROVED — `.only()` enabled by default (`OPTIMIZE_ONLY_FIELDS=True`),
with the conservative safety valves in §3.3.
**Scope:** `graphene_django_extras/utils.py` (`queryset_factory`, `recursive_params`),
its callers in `fields.py` / `types.py`, `settings.py`, tests, docs.
**Target release:** `graphene-django-extras 1.2.0`.
**Date:** 2026-06-06

---

## 1. Motivation & current defects

`queryset_factory` is meant to inspect the GraphQL selection set and apply
`select_related` / `prefetch_related` so nested relations do not trigger N+1
queries. Today it only half-works.

`recursive_params` defects (see `utils.py`):

- **D1** — Dedup guard `temp.name not in [prefetch_related + select_related]`
  builds a list-of-one-list, so it is **always true** (no real dedup).
- **D2** — When a field **is** a relation it appends but **does not recurse** into
  its sub-selection (the `elif ...selection_set` only runs for non-relations), so
  only the **first level** of relations is captured.
- **D3** — Recursion always passes the **root** model's related fields and never
  builds dotted paths, so `author__profile` / `posts__comments` are never produced.
- **D4** — `a, b` returned are the same list objects passed in; the merge
  comprehensions are confusing no-ops.
- **D5** — No `.only()` / `.defer()` column narrowing exists.

`queryset_factory` defects:

- Depends on the broken `recursive_params` → **nested N+1 persists**.
- The custom-resolver path (`_get_custom_resolver`) calls
  `resolver(root, info, **kwargs)` and then applies `select_related`/
  `prefetch_related` to whatever it returns — fragile and can raise if it is not
  a queryset.

**Clarification:** N+1 is eliminated by correct nested `select_related` /
`prefetch_related`. `.only()`/`.defer()` only reduces transferred columns and is
**risky** (model properties, `__str__`, custom resolvers or signals touching a
deferred field cause an extra query per row or wrong data). Therefore the N+1 fix
is always on; `.only()` is opt-in.

---

## 2. Goals / Non-Goals

### Goals
- **G1** — Build **nested** dotted `select_related` (forward FK / one-to-one) and
  `prefetch_related` (M2M / reverse) paths from the GraphQL selection, descending
  through wrapper fields (`results`), fragments and inline fragments, to **any
  depth**, eliminating nested N+1.
- **G2** — Replace the recursive, shared-list implementation with a clear,
  iterative, well-tested traversal. Deterministic output (sorted).
- **G3** — Opt-in `.only()` column narrowing (off by default), conservative and
  safe (always keep pk + FK attnames + select_related join keys + ordering
  fields), gated by a setting.
- **G4** — Keep `queryset_factory(manager, root, info, **kwargs)` signature and
  every current caller working unchanged.
- **G5** — Robust custom-resolver handling (only optimize real querysets).
- **G6** — Tests proving N+1 elimination via `assertNumQueries`, plus docs.

- **G7** — *(amendment)* Optimize **single-object** retrieval too
  (`DjangoObjectField` and `DjangoSerializerType.retrieve`): route the lookup
  through `queryset_factory` so nested relations on a single object are
  `select_related` / `prefetch_related` / `.only()`-optimized before `.get(pk=…)`.

### Non-Goals
- **NG2** — A full hint/annotation system à la `graphene-django-optimizer`.
- **NG3** — Cross-`prefetch` `.only()` via `Prefetch(queryset=...)` (first
  iteration applies `.only()` only to the root `select_related` span; documented).

---

## 3. Design

### 3.1 Field classification (per model)

A helper returns, for a model, a map `name -> kind` where kind ∈
`{"select", "prefetch", "concrete", "skip"}`:

- forward `ForeignKey` / `OneToOneField` (`many_to_one`/`one_to_one`, concrete) →
  `select`
- `ManyToManyField` / reverse (`many_to_many`/`one_to_many`) → `prefetch`
- concrete local fields → `concrete`
- `GenericForeignKey`, generic rels, computed/unknown → `skip`

Relation names are matched against the GraphQL field name and its
`to_snake_case` form (existing behaviour).

### 3.2 Traversal (iterative)

`optimization_hints(model, selection_set, fragments) -> (select, prefetch, only)`:

- Work list of `(model, selection_set, path_prefix)`; start at `(root_model,
  selection, "")`.
- For each selected field:
  - `FragmentSpread` / `InlineFragment` → push `(current_model, fragment.selection,
    path_prefix)` (type-conditioned inline fragments resolved to their model when
    available, else current model).
  - A **wrapper** field that is not a model relation/concrete (e.g. `results`,
    `totalCount`, `pageInfo`) but has a sub-selection → descend with the **same**
    model and **same** path_prefix (so `{ results { author { ... } } }` maps to
    `author`). Wrapper detection: name not in the model field map.
  - `select` relation with a sub-selection → add `path_prefix + name` to
    `select`; push `(related_model, field.selection, path_prefix + name + "__")`.
  - `prefetch` relation with a sub-selection → add `path_prefix + name` to
    `prefetch`; push `(related_model, field.selection, path_prefix + name + "__")`.
    (Descendants of a prefetch contribute nested `prefetch_related` paths, which
    Django supports as `a__b`.)
  - `concrete` field → record `path_prefix + name` in `only[span]` (see §3.3).
- A relation **without** a sub-selection is ignored (nothing to optimize).
- De-duplicate; return sorted lists.

### 3.3 `.only()` (enabled by default, conservative)

Enabled when `GRAPHENE_DJANGO_EXTRAS["OPTIMIZE_ONLY_FIELDS"]` is true (**default
True**). Because narrowing columns can break model properties / custom resolvers
that read non-selected columns (re-introducing N+1 or returning stale data),
several **safety valves** apply:

- **Span:** collect the concrete fields requested **within the `select_related`
  span** (root model + forward / reverse-o2o descendants). Prefetched branches are
  **not** narrowed (separate querysets) — fields under a prefetch are ignored for
  `only()`.
- **Always include:** the model `pk` for every model entered in the span (so
  `select_related` join targets are not deferred), every forward-relation FK
  `attname` on the path, and the model's `Meta.ordering` fields.
- **Plumbing set:** GraphQL plumbing leaf names (`__typename`, `totalCount`/
  `count`, `pageInfo`, `cursor`, `startCursor`, `endCursor`, `hasNextPage`,
  `hasPreviousPage`, `edges`, `node`) are ignored — they never mark a model.
- **Wrapper descent:** an unknown field **with** a sub-selection (e.g. `results`
  or a renamed `results_field_name`) is transparent: descend with the *same*
  model / prefix. This is how the `DjangoListObjectType` wrapper is crossed.
- **Unknown-leaf safety:** if a model in the span has a selected leaf that maps to
  neither a concrete column nor a relation nor plumbing (i.e. a computed/property/
  method field), that model is marked **full** — *all* its concrete columns are
  loaded (not narrowed), so the property keeps working.
- **Fallback:** if the field set for a model cannot be computed safely, skip
  `only()` for that span.
- **Escape hatch:** `OPTIMIZE_ONLY_FIELDS=False` disables narrowing entirely.

Apply `qs.only(*sorted(fields))` with dotted paths aligned to the
`select_related` span.

### 3.3b Single-object resolvers (amendment)

For single-object lookups the GraphQL selection is already the node's fields (no
`results` wrapper), so `queryset_factory` works unchanged. Both resolvers build
the optimized queryset and then fetch by pk:

```python
# DjangoObjectField.object_resolver / DjangoSerializerType.retrieve
pk = kwargs.pop("id", None)
qs = queryset_factory(manager, root, info, **kwargs)
return qs.get(pk=pk)          # DoesNotExist -> None
```

This reuses the exact same nested `select_related` / `prefetch_related` / `.only()`
machinery and honors `OPTIMIZE_QUERYSET` / `OPTIMIZE_ONLY_FIELDS`. A single object
with nested relations then costs **1 query** (forward joins folded in) **+ 1 per
prefetched relation**, instead of one query per nested relation.

### 3.4 `queryset_factory`

```
def queryset_factory(manager, root, info, **kwargs):
    base = _get_queryset(manager)              # Model/Manager/QuerySet -> QuerySet
    model = base.model

    # custom resolver: only adopt it if it yields a real queryset
    custom = _get_custom_resolver(info)
    if custom is not None:
        produced = custom(root, info, **kwargs)
        if isinstance(produced, QuerySet):
            base = produced

    if not graphql_api_settings.OPTIMIZE_QUERYSET:
        return base

    # filter kwargs that traverse relations (a__b=...) also seed select/prefetch
    select, prefetch, only = optimization_hints(model, info.field_nodes[0].selection_set,
                                                 info.fragments, kwargs)
    if select:   base = base.select_related(*select)
    if prefetch: base = base.prefetch_related(*prefetch)
    if only and graphql_api_settings.OPTIMIZE_ONLY_FIELDS:
        base = base.only(*only)
    return base
```

`recursive_params` is **kept as a thin, corrected compatibility wrapper** that
delegates to the new traversal (it is a public-ish symbol), so external imports
keep working.

### 3.5 Settings (new, `settings.py` DEFAULTS)

| Setting | Default | Meaning |
|---------|---------|---------|
| `OPTIMIZE_QUERYSET` | `True` | Apply nested `select_related`/`prefetch_related`. |
| `OPTIMIZE_ONLY_FIELDS` | `True` | Also apply conservative `.only()` narrowing (§3.3). |

---

## 4. Acceptance Criteria

- **AC1** — A nested list query (`results { fk { ... } }`) over N rows runs a
  **constant** number of queries (independent of N): 1 for the base
  `select_related` span + 1 per `prefetch_related` relation. [assertNumQueries]
- **AC2** — Deep forward relations produce dotted `select_related`
  (`a__b__c`). [unit]
- **AC3** — M2M / reverse relations produce `prefetch_related`, nested ones as
  `a__b`. [unit + assertNumQueries]
- **AC4** — camelCase field names, `FragmentSpread` and `InlineFragment` are all
  traversed. [unit]
- **AC5** — Relations without sub-selections and unknown/computed fields add
  nothing (no crash). [unit]
- **AC6** — With `OPTIMIZE_ONLY_FIELDS=True`, `.only()` includes the requested
  concrete fields plus pk/FK/ordering, and does not increase query count for a
  model with a property reading another selected field. [assertNumQueries]
- **AC7** — `OPTIMIZE_QUERYSET=False` disables all of it (escape hatch). [unit]
- **AC8** — All four existing callers still return correct results; full suite
  green; base install channels-free. [regression]
- **AC9** — A single-object query (`DjangoObjectField` /
  `DjangoSerializerType.retrieve`) with nested relations runs a constant number
  of queries (forward joins folded in + 1 per prefetch), and returns the correct
  object / `None` when missing. [assertNumQueries]

---

## 5. Test Plan (`tests/`)

New relational test models (in `tests/models.py`): `Author`,
`Category`, `Post(author FK, category FK)`, `Tag`, `Post.tags M2M`. A schema
exposing them via `DjangoListObjectType` + `DjangoListObjectField`.

| Test | Asserts |
|------|---------|
| `test_select_related_nested_paths` | dotted `select_related` from selection. AC2 |
| `test_prefetch_related_paths` | M2M/reverse → prefetch, nested `a__b`. AC3 |
| `test_camelcase_and_fragments` | camelCase + fragment spread + inline. AC4 |
| `test_relation_without_subselection_noop` | no crash / nothing added. AC5 |
| `test_numqueries_constant` | list of K rows with nested FK+M2M → constant queries. AC1/AC3 |
| `test_only_optin_safe` | `.only()` opt-in keeps query count, includes pk/FK. AC6 |
| `test_optimize_disabled` | `OPTIMIZE_QUERYSET=False` → plain queryset. AC7 |
| regression | existing pagination/types/fields tests stay green. AC8 |

---

## 6. Documentation

- New `docs/usage/query-optimization.md` — how the optimizer maps a GraphQL
  selection to `select_related`/`prefetch_related`, an `assertNumQueries`
  before/after example, the two settings, and the `.only()` caveats.
- Link it from `docs/usage/` nav.
- This SPEC lives in `specs/` (excluded from the site).

---

## 7. Definition of Done

1. SPEC approved.
2. New traversal + `queryset_factory` per §3; `recursive_params` kept as a
   corrected compatibility wrapper; settings added.
3. All §4 ACs green via §5 tests; full suite green; base install channels-free;
   `ruff`/`black`/`isort`/`flake8` clean; `mkdocs --strict` green.
4. Docs (§6) written with examples.
5. Committed and pushed to `pre-v2`.
