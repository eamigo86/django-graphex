# SPEC — A: Fields honor `self.resolver` (custom resolver / `Meta.queryset` fix)

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/fields.py`, tests, docs.
**Date:** 2026-06-07
**Origin:** downstream `ISNDjangoObjectField` / `ISNDjangoListObjectField`
overrode `get_resolver` to honor a custom resolver. This is **piece A** of the
SerializerType/permissions work (A → B → C → D).

---

## 1. Problem / Goals

The list/object fields **ignore a custom `resolver`** passed to them. Confirmed:
`DjangoObjectField(Type, resolver=fn).wrap_resolve(None)` wraps `object_resolver`,
not `fn` (and `self.resolver` is set but unused); same for
`DjangoListObjectField`, `DjangoFilterListField`,
`DjangoFilterPaginateListField`.

This is not just a missing feature — it is a **latent bug** in the library:
`DjangoSerializerType.RetrieveField` / `ListField` already build the fields with
`resolver=cls.retrieve` / `resolver=cls.list` (`types.py`), but because the field
ignores `resolver`, **`cls.retrieve` / `cls.list` never run** — so
`DjangoSerializerType.Meta.queryset` is silently ignored for retrieve/list (the
built-in resolvers use `_default_manager`).

**Goal (G1):** the four fields honor a custom `resolver` when one is supplied,
falling back to the built-in resolver otherwise — fixing the `DjangoSerializerType`
wiring (and unblocking pieces B/C, which rely on `cls.retrieve`/`cls.list`).

### Non-Goals
- The `get_queryset` / `filter_queryset` hooks (piece B) and permissions (C).
- Changing the built-in resolver behavior when no custom resolver is given.

## 2. Design

graphene 3 calls `wrap_resolve(self, parent_resolver)`; the base returns
`self.resolver or parent_resolver`. These subclasses override it and inject the
manager (and, for lists, the filterset + filtering args) so the resolver can reuse
the library plumbing. The fix keeps that injection but **uses `self.resolver` when
present**:

```python
# DjangoObjectField
def wrap_resolve(self, parent_resolver):
    resolver = self.resolver or self.object_resolver
    return partial(resolver, self.type._meta.model._default_manager)

# DjangoListObjectField / DjangoFilterListField / DjangoFilterPaginateListField
def wrap_resolve(self, parent_resolver):
    resolver = self.resolver or self.list_resolver
    <current_type resolution unchanged>
    return partial(resolver, manager, self.filterset_class, self.filtering_args)
```

**Resolver contract (unchanged from the built-ins, "injected-manager" signature):**
- object: `resolver(manager, root, info, **kwargs)`
- list: `resolver(manager, filterset_class, filtering_args, root, info, **kwargs)`

This matches the existing `object_resolver` / `list_resolver` **and**
`DjangoSerializerType.retrieve` / `list`, so passing `cls.retrieve` / `cls.list`
(as the library already does) now works.

Applies to all four fields that override `wrap_resolve` and inject a manager
(consistency; `DjangoNestedListObjectField` inherits the `DjangoListObjectField`
behavior — it passes no custom resolver, so it is unaffected).

### 2.1 `Meta.queryset` truthiness fix (same root cause)
`DjangoSerializerType` stored/used the queryset with `or`:
`_meta.queryset = queryset or model._default_manager` and
`queryset_factory(cls._meta.queryset or manager, …)`. A `QuerySet`'s truthiness
**executes** it (`__bool__` → `_fetch_all`) — so a `Meta.queryset` was run at
class-definition time and re-run for every retrieve/list (and an empty result
would wrongly fall back to the unrestricted manager). Changed to
`... if ... is not None else ...` so the queryset is never evaluated for
truthiness. Without this, `Meta.queryset` (the whole point of AC4) is unusable.

## 3. Acceptance Criteria
- **AC1** `DjangoObjectField(Type, resolver=fn).wrap_resolve(None)` wraps `fn`;
  with no resolver it wraps `object_resolver`. [G1]
- **AC2** `DjangoListObjectField` / `DjangoFilterListField` /
  `DjangoFilterPaginateListField` with `resolver=fn` wrap `fn`; without, the
  built-in. [G1]
- **AC3** `DjangoSerializerType.ListField().wrap_resolve(None)` now wraps
  `cls.list` (not `list_resolver`); `RetrieveField()` wraps `cls.retrieve`. [G1]
- **AC4** End-to-end: a `DjangoSerializerType` whose `Meta.queryset` is a
  restricted queryset returns only that subset from its list/retrieve (proving
  `cls.list`/`cls.retrieve` run). [G1]
- **AC5** No behavior change when no custom resolver is supplied; full suite
  green; base channels-free; lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/`)
- `test_fields.py` (or a new `test_field_resolver.py`): build each of the four
  fields with a sentinel `resolver` and assert `wrap_resolve(None)` wraps it
  (via the returned `partial.func`); assert the built-in is used otherwise.
- A `DjangoSerializerType` regression: define one with `Meta.queryset` limited to
  a subset, create rows in and out of the subset, run its `list`/`retrieve` and
  assert only the subset is returned (proves AC3/AC4).

## 5. Documentation
`docs/usage/fields.md` (and/or `docs/usage/types.md`): document that a custom
`resolver=` is honored, with the injected-manager signature, and note that
`DjangoSerializerType.Meta.queryset` is respected by list/retrieve.

## 6. Definition of Done
1. SPEC approved.
2. The four `wrap_resolve` methods honor `self.resolver` per §2.
3. §3 ACs green via §4 tests; full suite green; base channels-free; lint +
   `mkdocs --strict` green.
4. Docs updated.
5. Committed and pushed to `pre-v2`.
