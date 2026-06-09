# SPEC — Nested objects rework for `DjangoSerializerType` (and `DjangoSerializerMutation`)

**Status:** IMPLEMENTED in `pre-v2` (`nested.py` `NestedFieldsMixin`; tests in
`tests/test_nested_objects.py`). Decisions: (1) **additive** M2M/reverse
semantics (never remove/delete existing children); (2) empty `[]`/`{}` = **no-op**;
(3) `many=True` does **per-item upsert** by pk; (4) **one level** of nesting
(no grandchildren) this iteration.
**Area:** 2 of 4 (order: 2 → 4 → 1 → 3).
**Scope (planned):** new `graphene_django_extras/nested.py` (shared mixin);
`types.py` + `mutation.py` (use the mixin); tests; docs; changelog.
**Date:** 2026-06-08

---

## 1. Problem

`DjangoSerializerType.manage_nested_fields` (and the identical copy in
`DjangoSerializerMutation`) saves nested children and the parent with no
transaction, a broken error path, and a fragile relation heuristic. There are
**no tests** for it today.

### Current behavior (recap)
`Meta.nested_fields = {field_name: DRFSerializerClass}`. The input type builds a
nested input for each such field (`converter.py`); on create/update,
`manage_nested_fields` pops each `sub_data`, serializes it, **saves it
immediately**, then either injects `data[field] = child.id` (single) or collects
it for `parent.<field>.add(*children)` (list).

### Confirmed defects
| # | Severity | Defect |
|---|----------|--------|
| 2.1 | 🔴 | **No atomicity.** Children are persisted before the parent; if the parent fails validation, orphan rows remain. No `transaction.atomic` anywhere. |
| 2.2 | 🔴 | **Broken error path.** On a nested failure `manage_nested_fields` returns an error *response object*, but `create`/`update` don't check it — they save the parent, then `elif nested_objs:` calls `.items()` on the response → `AttributeError`. |
| 2.3 | 🟡 | **Fragile relation heuristic.** Assumes `list → .add()` (M2M) and `single → forward FK`. No introspection; reverse-FK / O2O mishandled. |
| 2.4 | 🟡 | **No update of existing children.** Always creates new (serializer without `instance`); no upsert by pk. |
| 2.5 | 🟢 | `if sub_data:` skips empty list/dict → a relation can't be cleared. |
| 2.6 | 🟡 | **Duplicated** verbatim in `types.py` and `mutation.py`. |

---

## 2. Goals / Non-Goals

**Goals**
- **G1** — Create/update are **atomic**: any nested or parent failure rolls back
  everything (`transaction.atomic`).
- **G2** — Nested validation errors are returned as a clean `ErrorType` list
  (field-prefixed), never crash; no partial writes.
- **G3** — **Relation-aware** save ordering via Django introspection
  (`model._meta.get_field`), covering forward FK / forward O2O / reverse FK /
  reverse O2O / M2M.
- **G4** — **Upsert by pk**: a nested payload with a pk updates that child
  (partial), without a pk creates a new one.
- **G5** — One **shared mixin** used by both `DjangoSerializerType` and
  `DjangoSerializerMutation`; behavior identical.
- **G6** — Preserve the public contract: `Meta.nested_fields = {name:
  SerializerClass}`, and the generated nested input shape.

**Non-Goals**
- Arbitrary-depth recursive nesting (grandchildren): we support **one** level of
  nesting per declared field (children may themselves have scalar fields). Deeper
  graphs are out of scope this iteration.
- Auto-discovery of nestable relations (still opt-in via `nested_fields`).
- Deleting children not present in the payload (no "sync/replace" semantics);
  see Open Questions.

---

## 3. Design

### 3.1 Relation direction → save strategy
For each `field_name` in `nested_fields`, introspect
`parent_model._meta.get_field(field_name)` and branch on Django's relation flags:

| Relation | Flags | Order | Attach |
|----------|-------|-------|--------|
| Forward FK | `many_to_one`, concrete | child **first** | set `data[fk] = child.pk` before parent save |
| Forward O2O | `one_to_one`, concrete, not auto-created | child **first** | set `data[fk] = child.pk` |
| Reverse FK | `one_to_many` (`ManyToOneRel`) | parent **first** | set child's FK to parent, then save each child |
| Reverse O2O | `one_to_one`, auto-created | parent **first** | set child's FK to parent, save child |
| M2M (either side) | `many_to_many` | parent **first** | save children, then `parent.<field>.add(*children)` |

Single vs list is taken from the **relation**, not from the payload shape
(forward FK/O2O = single; reverse FK / M2M = list; reverse O2O = single).

### 3.2 Flow (create)
```
with transaction.atomic():
    forward, reverse = split nested by direction
    # 1. forward children first (parent needs their pk)
    for f in forward:
        child = save_child(serializer_cls, sub_data)      # validate+save (upsert)
        data[fk_attname] = child.pk
    # 2. validate + save parent
    parent = save_parent(data)                            # raises -> rollback
    # 3. reverse / m2m children (need parent.pk)
    for f in reverse_fk/o2o: child.fk = parent; save_child(...)
    for f in m2m:            parent.<f>.add(*save_children(...))
    return parent
# any ValidationError collected -> ErrorType list, atomic already rolled back
```
`update` is the same with `instance=old_obj, partial=True` for the parent and pk
lookups for forward children.

### 3.3 Upsert + validation
- `save_child`: if `sub_data` (dict) carries a pk → load instance, serializer with
  `instance=…, partial=True`; else create. `many=True` payloads upsert per item.
- All children are validated **inside** the atomic block; the first failure
  raises a sentinel carrying the field-prefixed `ErrorType` list (reusing
  `get_errors_list(model_name=field)`), the block rolls back, and the caller
  returns `get_errors(...)`.

### 3.4 Shared mixin
New `nested.py` with `NestedFieldsMixin` providing `manage_nested_fields`,
`_save_child`, relation introspection, and the atomic orchestration. Both
`DjangoSerializerType` and `DjangoSerializerMutation` mix it in; the ~40 duplicated
lines in each are removed. Existing method names kept for back-compat.

---

## 4. Acceptance Criteria
- **AC1** — Parent validation failure after a forward-child save ⇒ **no** child
  row persists (rollback), response is `ok:false` with the parent errors.
- **AC2** — Nested validation failure ⇒ `ok:false` with field-prefixed errors
  (`addresses.zip_code`), no crash, no writes.
- **AC3** — Forward FK, reverse FK, M2M, forward O2O each create correctly and
  link to the parent.
- **AC4** — A nested payload with a pk **updates** the existing child (no
  duplicate row); without a pk creates one.
- **AC5** — `DjangoSerializerType` and `DjangoSerializerMutation` behave
  identically (shared mixin); existing non-nested create/update/delete unchanged.
- **AC6** — Input type shape for nested fields is unchanged (no schema break).

---

## 5. Resolved decisions
1. **Additive** semantics: M2M uses `.add`, reverse children are never removed or
   deleted. "Replace the set" is out of scope (documented limitation).
2. **Empty payload** (`[]` / `{}`) is a **no-op** (relation untouched).
3. `many=True` does **per-item upsert** by pk (pk present → update partial; absent
   → create).
4. **One level** of nesting (parent → direct children). Grandchildren are out of
   scope this iteration.
