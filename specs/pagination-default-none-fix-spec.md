# SPEC — Fix: DjangoFilterPaginateListField crashes when no pagination is set

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/fields.py`, tests.
**Date:** 2026-06-07
**Origin:** surfaced while implementing piece A.

---

## 1. Problem
`DjangoFilterPaginateListField.__init__` does
`pagination = pagination or graphql_api_settings.DEFAULT_PAGINATION_CLASS()`.
When the field is built without a `pagination` argument **and**
`DEFAULT_PAGINATION_CLASS` is `None` (the default), this evaluates `None()` →
`TypeError: 'NoneType' object is not callable`. So a plain
`DjangoFilterPaginateListField(MyType)` cannot be constructed unless a global
pagination class is configured.

(The other two `DEFAULT_PAGINATION_CLASS` call sites in `types.py` already guard
with `if ... is not None`; only this one is affected.)

## 2. Design
Resolve the default class safely, mirroring the `types.py` guards:

```python
if pagination is None:
    default_paginator_class = graphql_api_settings.DEFAULT_PAGINATION_CLASS
    pagination = default_paginator_class() if default_paginator_class else None
```

The existing `if pagination is not None:` block already handles the no-pagination
case (it simply adds no pagination args and leaves `self.pagination` unset; the
list resolver reads it via `getattr(self, "pagination", None)`).

## 3. Acceptance Criteria
- **AC1** `DjangoFilterPaginateListField(MyType)` with no `pagination` and no
  `DEFAULT_PAGINATION_CLASS` builds without raising; `self.pagination` is unset.
- **AC2** With `DEFAULT_PAGINATION_CLASS` configured, the default paginator is
  still used. With an explicit `pagination=`, it is used as before.
- **AC3** Full suite green; lint + `mkdocs --strict` green.

## 4. Test Plan
`tests/test_paginations.py`: building `DjangoFilterPaginateListField(UserType)`
with the default (None) `DEFAULT_PAGINATION_CLASS` does not raise and yields a
field with no `pagination`.

## 5. Definition of Done
1. Fix per §2. 2. §3 ACs green via §4. 3. Committed and pushed to `pre-v2`.
