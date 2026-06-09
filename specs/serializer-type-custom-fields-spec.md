# SPEC — Custom output fields on `DjangoSerializerType`

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/{types,base_types}.py`, tests, docs.
**Date:** 2026-06-08
**Origin:** Exposing a field not present on the serializer (a model `@property`,
an annotated value, a computed URL) required declaring a **separate**
`DjangoObjectType` for the model just so `DjangoSerializerType` would pick it up
from the registry. Goal: declare such fields straight on the
`DjangoSerializerType`.

---

## 1. Problem / Goals

`DjangoSerializerType` resolves its output type via
`registry.get_type_for_model(model)` (falling back to a generated
`DjangoObjectType`), and the list type reuses the same item type from the
registry. Graphene fields written on the `DjangoSerializerType` body were
silently dropped (its `_meta.fields` is overwritten with a single
`{output_field_name: Field(output_type)}`).

**Goals**

- **G1** — Graphene fields declared on a `DjangoSerializerType` body are exposed
  on the generated output type, in both `RetrieveField()` and `ListField()`.
- **G2** — No separate `DjangoObjectType` required.
- **G3** — Additive: types without custom fields are unchanged.
- **G4** — When a `DjangoObjectType` is already registered for the model, the
  declared fields cannot be injected; warn instead of silently dropping them.
- **G5** — Fields are inherited along the MRO (e.g. an abstract base / mixin),
  and a subclass may override an inherited field — standard OOP semantics.

### Non-Goals
- Merging custom fields into an already-registered `DjangoObjectType`.

## 2. Design

- In `DjangoSerializerType.__init_subclass_with_meta__`, collect graphene fields
  across the MRO — every class that is a strict subclass of `DjangoSerializerType`
  (bases first so a subclass overrides an inherited field; the base itself is
  skipped because its `ok` / `errors` are wrapper fields) — and pass them as
  `factory_kwargs["extra_fields"]`. After `super().__init_subclass_with_meta__`,
  pop those names from the wrapper's `_meta.fields` so they live only on the
  output type (a `delattr` can't reach inherited fields, hence the post-pop).
- `factory_type("output", ...)` builds the generated `DjangoObjectType` via
  `type("GenericType", (_type,), {"Meta": ..., **extra_fields})` so graphene's
  `ObjectType` base collects them and merges them with the model-derived fields.
- The generated output type registers itself, so the list type's
  `registry.get_type_for_model(model)` reuses it — custom fields appear in lists
  for free.
- If `registry.get_type_for_model(model)` already returns a type and custom
  fields were declared, emit a `UserWarning`.

## 3. Acceptance Criteria
- **AC1** — A field declared on the type is in `output_type._meta.fields` and in
  the list type's `baseType._meta.fields`.
- **AC2** — It resolves from the instance (`source=` / `resolve_<name>`).
- **AC3** — It is not left on the `DjangoSerializerType._meta.fields` wrapper.
- **AC4** — With a pre-registered `DjangoObjectType`, declaring fields warns and
  the registered type is used unchanged.
- **AC5** — Types without custom fields behave exactly as before.
- **AC6** — A field declared on an abstract base is inherited onto the output
  type and resolves; a subclass redeclaring it overrides the inherited one.
