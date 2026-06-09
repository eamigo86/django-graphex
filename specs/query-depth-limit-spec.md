# SPEC — Query depth limiting (`max_deep` / `MAX_QUERY_DEPTH`)

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** new `graphene_django_extras/validation.py`; `types.py`, `base_types.py`,
`settings.py`, `views.py`, `__init__.py`; tests, docs.
**Date:** 2026-06-08
**Origin:** Models relate to other models recursively; a client can request very
deeply nested objects. We want to cap nesting depth per type (and globally).

---

## 1. Problem / Goals

Reject abusively/expensively nested queries **before execution**, configurable
per type and globally.

**Decisions (confirmed):**
- **Semantics:** the limit counts **nested object levels below a field** that
  returns the constrained type; scalar leaves don't count.
- **Scope:** per-type `Meta.max_deep` **and** a global `MAX_QUERY_DEPTH` default;
  most restrictive wins.
- **Types:** declarable on `DjangoObjectType`, `DjangoListObjectType`, and
  `DjangoSerializerType` (forwarded to its generated output type).

**Goals**
- **G1** — A graphql-core `ValidationRule` enforces the limit at validation time
  (no resolver runs on rejection).
- **G2** — Per-type limit read from the type during validation
  (`graphql_type.graphene_type._meta.max_deep`).
- **G3** — Global default from `MAX_QUERY_DEPTH` (measured from the root).
- **G4** — Fragments (named + inline) are followed; they cannot bypass the limit.
- **G5** — No-op when nothing is configured; enabled by default on
  `ExtraGraphQLView` (added to the standard rules, not replacing them).

### Non-Goals
- Field/argument cost analysis or complexity scoring (depth only).
- Auto-wiring into arbitrary third-party views (documented opt-in).

## 2. Design

- `DepthLimitValidationRule` analyzes each operation in
  `enter_operation_definition`, recursively walking selection sets and resolving
  each field's named type from the schema. It keeps a list of active budgets
  `(limit, origin_depth, label)`; entering an object field increments depth and
  fails if `depth - origin > limit` for any budget. A field whose named type has
  `max_deep` pushes a new budget; the global default seeds a budget at the root.
  One error per operation; fragment cycles are guarded.
- `max_deep` stored on `DjangoObjectOptions.max_deep` /
  `DjangoSerializerOptions.max_deep`; `DjangoObjectType` / `DjangoListObjectType`
  accept `Meta.max_deep`; `DjangoSerializerType` forwards it into the generated
  output type via `factory_type`.
- `MAX_QUERY_DEPTH` added to settings (default `None`). The rule reads it through
  the settings module so `override_settings` is honored.
- `ExtraGraphQLView.validation_rules = (*specified_rules, DepthLimitValidationRule)`.

## 3. Acceptance Criteria
- **AC1** — Within the per-type limit passes; one level deeper errors.
- **AC2** — Scalars don't add depth; `max_deep = 0` blocks any nested object.
- **AC3** — Named and inline fragments are counted (no bypass).
- **AC4** — With nested constrained types, the most restrictive wins.
- **AC5** — `MAX_QUERY_DEPTH` enforces a global cap; nothing configured = no-op.
- **AC6** — `max_deep` reaches `_meta` on object/list/serializer types; the view
  includes the rule alongside the standard rules.
