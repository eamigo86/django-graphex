# SPEC — Registry: key by model class, end name collisions

**Status:** IMPLEMENTED in `pre-v2` (`registry.py`; tests in
`tests/test_registry.py::RegistryKeyCollisionTest`). Decisions: (1) drop the string-keyed
`_registry` (key by model class, no compat alias); (2) convert the `register()`
`assert`s to explicit `TypeError`/`ValueError` (survive `python -O`).
**Area:** 1 of 4 (order: 2 → 4 → 1 → 3).
**Scope (planned):** `registry.py` (internal storage only; public API unchanged);
update two test helpers; tests; changelog. No changes to `converter.py` /
`types.py` / `mutation.py` (they use the public methods).
**Date:** 2026-06-08

---

## 1. Problem

`Registry` stores every kind of object in one dict (`self._registry`) under a
**stringified, camelCased name** derived from the model class name:

```python
self._registry[to_camel_case("post")]          = PostType          # output
self._registry[to_camel_case("post_create")]   = PostCreateInput   # input
self._registry[to_camel_case("post_list")]     = PostListType      # list
self._registry["postStatusEnum"]               = PostStatusEnum    # enum
```

This creates several **silent** collision surfaces:

| # | Severity | Collision |
|---|----------|-----------|
| 1.1 | 🔴 | **Cross-app same class name.** `blog.Post` and `forum.Post` both key to `"post"`; the second registration silently overwrites the first. The key omits `app_label`. |
| 1.2 | 🟡 | **Suffix overlap.** A model named `PostList` keys to `"postList"`, colliding with `Post`'s list type; likewise `*Create`/`*Update` vs an input action. |
| 1.3 | 🟡 | **Enum vs type.** Enums share the same dict; an enum key can collide with a model type key. |
| 1.4 | 🟢 | `self._registry_models` is dead code (never read/written). |

Upstream graphene-django avoids all of this by keying on the **model class
object**, not a derived string.

---

## 2. Goals / Non-Goals

**Goals**
- **G1** — Key types by the **model class** (and input action), eliminating
  1.1 and 1.2 entirely.
- **G2** — Store enums (and directives) in their **own** dicts, eliminating 1.3.
- **G3** — Keep the **public API byte-for-byte**: `register`,
  `get_type_for_model`, `register_list_type`, `get_list_type_for_model`,
  `register_enum`, `get_type_for_enum`, `register_directive`, `get_directive` —
  same names, signatures and semantics. `converter.py` / `types.py` /
  `mutation.py` are untouched.
- **G4** — Remove dead code (`_registry_models`), de-duplicate key logic, drop the
  now-unused `to_camel_case`/`_list_key` machinery.

**Non-Goals**
- Changing registration *semantics* (last-registration-still-wins per
  `(model, action)`; that's intentional for type overrides).
- A public `unregister`/iteration API (not required by callers).

---

## 3. Design

Replace the single `_registry` + dead `_registry_models` with purpose-specific
stores:

```python
class Registry:
    def __init__(self):
        self._types: dict[tuple[type[Model], str | None], Any] = {}   # (model, action)
        self._list_types: dict[type[Model], Any] = {}                 # model
        self._enums: dict[str, Any] = {}                              # enum name
        self._registry_directives: dict[str, Any] = {}               # unchanged
```

| Method | Old | New |
|--------|-----|-----|
| `register(cls, for_input=None)` | `_registry[camel(model_action)] = cls` | `_types[(cls._meta.model, for_input)] = cls` (still honors `skip_registry`) |
| `get_type_for_model(model, for_input=None)` | `_registry.get(camel(...))` | `_types.get((model, for_input))` |
| `register_list_type(model, cls)` | `_registry[camel(model_list)] = cls` | `_list_types[model] = cls` |
| `get_list_type_for_model(model)` | `_registry.get(camel(model_list))` | `_list_types.get(model)` |
| `register_enum(key, enum)` / `get_type_for_enum(key)` | shared `_registry` | own `_enums` dict |
| `register_directive` / `get_directive` | `_registry_directives` | unchanged |

`to_camel_case` import and `_list_key` are removed (no string keys left).
`get_global_registry` keeps its lazy singleton (`if registry is None`).

### 3.1 Validation
Keep the two checks in `register` (only `DjangoObjectType`/`DjangoInputObjectType`
allowed; registry must match). **Proposed:** convert the `assert`s to explicit
`TypeError`/`ValueError` so they survive `python -O` (see Open Q2).

### 3.2 Test-helper update
`tests/test_query_cost.py` and `tests/test_depth_limit.py` force a fresh
serializer output type by popping registry entries:
```python
reg._registry.pop(to_camel_case(UUIDItem.__name__.lower()), None)
reg._registry.pop(reg._list_key(UUIDItem), None)
```
These become:
```python
reg._types.pop((UUIDItem, None), None)
reg._list_types.pop(UUIDItem, None)
```

---

## 4. Acceptance Criteria
- **AC1** — Two models with the **same class name in different apps** register and
  resolve to their **own** types (no overwrite). *(new regression test)*
- **AC2** — A model named `XList` and the list type of model `X` coexist without
  collision; likewise an enum key equal to a model name. *(new test)*
- **AC3** — `get_type_for_model` / `get_list_type_for_model` /
  `get_type_for_enum` round-trip exactly as before for the normal case; the full
  existing suite passes unchanged (public API intact).
- **AC4** — `_registry_models` is gone; no `to_camel_case`/`_list_key` left in
  `registry.py`.

---

## 5. Open questions (please confirm)
1. **No back-compat shim for `registry._registry[...]`.** It's a private
   attribute; only the two library test helpers (updated here) touch it by
   string. Confirm we don't keep a string-keyed `_registry` alias. **Recommend:
   drop it.**
2. **`assert` → explicit exceptions** in `register` (so checks aren't stripped
   under `python -O`)? **Recommend: yes** (raise `TypeError`). Low risk; the
   messages stay the same.
