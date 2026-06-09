# SPEC — Uniform list shape for nested relations (`results` + `totalCount` everywhere)

**Status:** APPROVED — implemented in `graphene-django-extras 1.2.0`.
**Decisions (approved):** in-memory pagination/ordering over the `prefetch_related`
cache (keeps N+1 at zero); **no setting — always on** (hard breaking change).
**Scope:** `converter.py`, `registry.py`, `fields.py`, `paginations/pagination.py`,
`base_types.py`/`types.py`, tests, docs.
**Target release:** `graphene-django-extras 1.2.0`.
**Date:** 2026-06-06

---

## 1. Problem

Related **list** fields (M2M, reverse FK, M2M-rel, `GenericRel`,
`GenericRelation`) are converted (`converter.py`) to `DjangoFilterListField` /
`DjangoListField`, i.e. a plain `[Node]`. They can be **filtered** but **not
paginated or ordered**, and they do **not** carry the canonical `results` +
`totalCount` shape that root lists (`DjangoListObjectType` + `DjangoListObjectField`)
have. Mutation output types build their nested lists through the same converters,
so they have the same gap.

**Goal:** every list — root, nested, and in mutation responses — has the same
shape and capabilities: `{ results(pagination, ordering) { … } totalCount }`,
filterable + paginable + orderable.

## 2. Goals / Non-Goals

### Goals
- **G1** — Map every related list field to the related model's
  `DjangoListObjectType` (`results` + `totalCount`).
- **G2** — Nested lists support **filtering** (args on the nested field),
  **pagination + ordering** (args on `results`), like root lists.
- **G3** — Preserve N+1 elimination: an **unfiltered** nested list resolves from
  the parent's `prefetch_related` cache (no extra query); pagination/ordering
  happen **in memory**.
- **G4** — Mutation create/update outputs get the same nested shape (free, same
  converters).
- **G5** — Tests (incl. `assertNumQueries`) + docs.

### Non-Goals
- **NG1** — Per-parent DB pagination via window functions.
- **NG2** — Changing root list behavior or the wire shape of scalar/FK fields.
- **NG3** — In-memory **filtering**: when filter args are supplied on a nested
  list, it falls back to a per-parent DB query (a `FilterSet` needs a queryset).
  Documented; unfiltered nested lists stay cache-based.

## 3. Design

### 3.0 Registry: one entry per (model, CRUD action)
Generalize `registry.py` to a single entry per **(model, action)** with
`action ∈ {create, update, delete, list, detail}`:

- `detail` → the node `DjangoObjectType` (current bare `<model>` key);
- `create` / `update` / `delete` → the input types (current `<model>_<action>`);
- `list` → the model's `DjangoListObjectType`.

Add `register_list_type(model, cls)` / `get_list_type_for_model(model)` (action
`list`); keep the existing node/input keys for backward compatibility. As with
node types, the **last** registered list type for a model wins (a model has one
canonical list type).

### 3.1 Self-registering + auto-generated list types
- `DjangoListObjectType.__init_subclass_with_meta__` **registers itself** as the
  model's `list` type (so a user-defined list type — and the list type built
  inside `DjangoSerializerType` — becomes the canonical one, carrying *that*
  model's `pagination` / `filterset`).
- `get_or_create_list_object_type(model, registry)`:
  1. return the registered `list` type for `model` if present (**respects the
     per-model paginator/filterset** — answers the `Group { users }` case);
  2. else build one via `factory_type("list", DjangoListObjectType, model=model,
     pagination=<default>, registry=registry)` (which self-registers).
- default paginator = instance of `DEFAULT_PAGINATION_CLASS` if set, else
  `LimitOffsetGraphqlPagination()` (so `results` exposes `limit`/`offset`/
  `ordering`).

### 3.2 Nested list field + resolver
`DjangoNestedListObjectField(DjangoListObjectField)` — a **thin subclass** that
reuses the existing `results` + `totalCount` machinery and only changes where the
base queryset comes from. It is **not** `DjangoFilterPaginateListField` (that one
returns a plain `[Node]` with field-level pagination, not the
`results`/`totalCount` shape, and resolves from the model's default manager).

- built with the related model's (registered/auto) `DjangoListObjectType`, the
  parent-relation `accessor`, and the related type's filterset/filter args;
- resolver scopes to the parent instance and prefers the prefetch cache:
  ```python
  related_manager = getattr(root, accessor)
  if filter_kwargs:                          # NG3: filtering -> per-parent DB query
      qs = filterset_class(data=filter_kwargs, queryset=related_manager.all(),
                           request=info.context).qs
      return DjangoListObjectBase(results=qs, count=qs.count(), ...)
  results = list(related_manager.all())      # uses prefetch cache -> no extra query
  return DjangoListObjectBase(results=results, count=len(results), ...)
  ```
- `results` (the list type's `GenericPaginationField`) then paginates/orders
  `root.results` — a **queryset** (filtered path) or a **list** (cache path), §3.3.

The `accessor` is derived at convert time: forward M2M → `field.name`; reverse →
`field.get_accessor_name()`; `GenericRelation` → `field.name`.

### 3.3 In-memory paginators
`LimitOffsetGraphqlPagination` / `PageGraphqlPagination` / `CursorGraphqlPagination`
`paginate_queryset` detect a non-`QuerySet` input (a list) and apply ordering +
slicing **in Python** (shared helpers `_inmemory_order` / `_inmemory_slice`),
mirroring the DB semantics (`ordering` string, `limit`/`offset` or `page`,
keyset cursor). Querysets keep the existing DB path. `totalCount` is the full set
size (`len`), consistent with the root behavior (`DjangoListObjectBase.count`).

### 3.4 Converter changes
`convert_field_to_list_or_connection` (M2M), `convert_many_rel_to_djangomodel`
(reverse FK / M2M-rel / `GenericRel`) and `convert_generic_relation_to_object_list`
(`GenericRelation`): for the **output** case (not `input_flag`) return
`Dynamic(lambda: DjangoNestedListObjectField(get_or_create_list_object_type(model),
accessor=…, …))`. **Input** cases (`input_flag`) are unchanged (`[ID]` lists).

### 3.5 Mutation outputs
`DjangoSerializerMutation` output node types are built through `construct_fields`
→ the same converters, so nested lists in create/update responses get the shape
for free. Verified by a test.

### 3.6 Optimization interplay
`recursive_params` already treats `results` as a transparent wrapper, so the
relation is still added to `prefetch_related`; the unfiltered nested resolver then
reads the populated cache (`list(manager.all())`), and the in-memory paginator
slices it — constant queries.

## 4. Acceptance Criteria
- **AC1** — A nested M2M / reverse-FK field has type `…ListType` with `results` +
  `totalCount` (introspection).
- **AC2** — Nested `results` accepts `limit`/`offset`/`ordering`; `totalCount` is
  the full related-set size.
- **AC3** — Nested filtering works (filter args on the nested field).
- **AC4** — An **unfiltered** nested list across P parents resolves in a constant
  number of queries (prefetch cache + in-memory pagination). [assertNumQueries]
- **AC5** — A `DjangoSerializerMutation` create/update response exposing a nested
  list has the `results` + `totalCount` shape.
- **AC6** — In-memory ordering / limit-offset / page slicing are correct. [unit]
- **AC7** — Existing suite updated & green; base install channels-free;
  `mkdocs --strict` green.
- **AC8** — A nested list reuses the model's **registered** list type, so a
  per-model paginator/filterset (e.g. `UserSerializerType.Meta.pagination =
  PageGraphqlPagination()`) is honored when `User` appears nested under another
  model (`Group { users { results(page: …) … } }`). [introspection/e2e]

## 5. Test Plan
- Reuse the relational models (`Author`/`Post`/`Tag`/`Category`).
- `test_nested_list_shape`: introspection — nested field is a list type.
- `test_nested_pagination_ordering`: `posts { results(limit/offset/ordering) }`.
- `test_nested_filtering`: filter args on the nested field.
- `test_nested_numqueries_constant`: list of authors → nested posts, constant
  queries (prefetch + in-memory). [AC4]
- `test_inmemory_paginators`: unit for list ordering/slicing. [AC6]
- `test_mutation_nested_list_shape`: serializer mutation output. [AC5]
- `test_nested_reuses_registered_paginator`: a model with a custom paginator is
  nested under another model and keeps its paginator/filterset. [AC8]
- `test_registry_one_entry_per_action`: create/update/delete/list/detail keys.
- Update existing converter/type/field tests that asserted the old `[Node]` shape.

## 6. Documentation
- `docs/usage/types.md` / a new section: the uniform nested list shape, with a
  query example (root + nested `results`/`totalCount`, nested pagination), and the
  N+1 note (unfiltered = cache; filtered = per-parent query).
- This SPEC lives in `specs/` (excluded from the site).

## 7. Definition of Done
1. SPEC approved.
2. Converter/registry/field/paginator changes per §3; mutations covered.
3. All §4 ACs green via §5 tests; full suite updated & green; base channels-free;
   lint clean; `mkdocs --strict` green.
4. Docs updated with examples.
5. Committed and pushed to `pre-v2`.
