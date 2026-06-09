# SPEC — Consistent, readable error messages

**Status:** IMPLEMENTED in `pre-v2` (tests in `tests/test_error_messages.py` +
`tests/test_security.py`). Choices below;
all are trivially reversible. Codes: `QUERY_TOO_DEEP`, `QUERY_TOO_COMPLEX`,
`INTROSPECTION_DISABLED`. Not-found text: `"{Model} with id {pk} does not exist."`
**Area:** 3 of 4 (order: 2 → 4 → 1 → 3).
**Scope:** `types.py`, `mutation.py`, `security.py`, `validation.py`, `cost.py`,
`utils.py`, `converter.py`; tests; docs (security codes table); changelog.
**Date:** 2026-06-08

---

## 1. Problem

| # | Severity | Issue |
|---|----------|-------|
| 3.1 | 🟡 | The "object not found" message is grammatically broken and inconsistent: `"A {} obj with id {} do not exist"` (×2), `"...id: {}..."` (×2), `"Model {}.{} do not exist."` — "obj", "do not", stray `:`. |
| 3.2 | 🟡 | Only auth/permission `GraphQLError`s carry `extensions.code`; introspection, depth and cost errors have none, so clients can't discriminate them programmatically. |
| 3.3 | 🟢 | Config/conversion failures raise bare `Exception`, which is hard to catch and untyped. |

## 2. Design

### 3.1 Unified not-found error
Add `not_found_error(model, pk)` to `utils.py` returning a one-entry
`ErrorType` list:
```python
[ErrorType(field="id", messages=[f"{model.__name__} with id {pk} does not exist."])]
```
Replace the 4 inline `ErrorType(field="id", …)` blocks in
`DjangoSerializerType.delete/update` and `DjangoSerializerMutation.delete/update`.
Fix the separate assert text in `utils.get_*` (`"do not exist."` →
`"does not exist."`).

### 3.2 `extensions.code` on every raised `GraphQLError`
| Source | Code | `status_code` |
|--------|------|---------------|
| `DisableIntrospectionMiddleware` | `INTROSPECTION_DISABLED` | 403 |
| `DepthLimitValidationRule` | `QUERY_TOO_DEEP` | — (validation) |
| `CostLimitValidationRule` | `QUERY_TOO_COMPLEX` | — (validation) |
| auth middleware (existing) | `UNAUTHENTICATED` | 401 |
| permission check (existing) | `PERMISSION_DENIED` | 403 |

`GraphQLError(..., extensions={"code": ...})`; validation rules pass `extensions`
through `report_error`. Document the full code table in `security.md`.

### 3.3 Typed configuration errors
- `ImproperlyConfigured` (misconfiguration): the two `filter_fields`/`filterset_class`
  "Django-Filter not installed" raises, and the two `serializer_class is required`
  raises (`types.py`, `mutation.py`).
- `TypeError` (wrong runtime input): `"Received incompatible instance"`
  (`types.py`) and `"Don't know how to convert the Django field"` (`converter.py`).

## 3. Acceptance Criteria
- **AC1** — Delete/update of a missing object returns `field="id"`,
  `"{Model} with id {pk} does not exist."` (both `DjangoSerializerType` and
  `DjangoSerializerMutation`).
- **AC2** — Introspection/depth/cost errors carry their `extensions.code`.
- **AC3** — Missing `serializer_class` / `filter_fields` without django-filter
  raise `ImproperlyConfigured`; the existing suite still passes.
- **AC4** — Docs list the error codes.

## 4. Notes
The two error *channels* are intentionally kept distinct and will be documented:
mutation **business** errors are structured `ErrorType{field, messages}` in the
`errors` payload with `ok: false`; **execution** errors are top-level
`GraphQLError`s with `extensions.code`.
