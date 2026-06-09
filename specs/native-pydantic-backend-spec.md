# SPEC — Native (Pydantic) serializer backend

**Status:** IMPLEMENTED on branch `native-backend`. `Meta.model` selects the
native backend; full suite (411) green with DRF installed, and the native path +
`import graphene_django_extras` work with **DRF uninstalled** (DRF moved to the
`[drf]` extra; settings vendored off `APISettings`). Decisions: (1) `Meta.pydantic_model` for
custom validation, DRF-style `validate_*` deferred; (2) `choices` → `enum.Enum`;
(3) `pydantic` becomes a core dep, `djangorestframework` → optional `[drf]` extra;
(4) **total** field coverage in v1 (map keyed by `get_internal_type()` so
postgres/GIS classes are never imported; env-specific types degrade gracefully).
**Branch:** `native-backend` (off `serializer-backend`).
**Builds on:** the landed `SerializerBackend` seam, the `spike-pydantic` engine,
and `specs/native-backend-prior-art.md` (djantic type map + caveats).

A DRF-free validate/save/output backend selected by `Meta.model`, so a type/
mutation can run without `djangorestframework`. Experimental and **opt-in**; DRF
stays the default. The schema is still built from the Django model by the
converter — the backend only owns runtime validate/persist/output.

---

## 1. Goal

Implement `PydanticBackend(SerializerBackend)` so:
```python
class AuthorType(DjangoSerializerType):
    class Meta:
        model = Author          # -> native backend, no DRF
```
behaves like the DRF-backed equivalent for create/update/delete, nested writes,
errors and subscription output — with **no graphene-django and no DRF** imported.

## 2. Components

1. **`native/fields.py`** — `build_model_schema(model, *, partial)`: Django model
   → a Pydantic v2 model. Ports djantic's map (rewritten for v2):
   - `INT_TYPES`/`STR_TYPES` + explicit map (UUID, Decimal, datetime/date/time,
     duration, bool, bytes, IP, JSON, float) + **MRO fallback → str + warning**.
   - constraints: `max_length` (no choices), Decimal `max_digits`/`decimal_places`.
   - **`choices` → `enum.Enum`** (align with graphene/DRF), not `Literal`.
   - optional/defaults: `has_default()` → default (callable → `default_factory`);
     `pk|blank|null` → `default=None`; nullable → `T | None`.
   - FK/O2O → related model's **pk type**; M2M handled out-of-band (list of pks).
   - FieldInfo: `description = help_text or verbose_name`, `max_length`.
2. **`native/backend.py`** — `PydanticBackend(SerializerBackend)` using the
   spike engine:
   - `get_model()` → the configured model.
   - `save_object(...)` → validate via the Pydantic model (only
     `model_fields_set` persisted, so Django defaults apply); DB checks (FK
     existence, uniqueness, `unique_together`); persist scalars + FK pk; M2M
     `.set()`; honor `save_kwargs` (reverse-FK) and `partial`; return
     `(ok, instance | [ErrorType])` (same shape the seam expects — so nested
     prefixing works unchanged).
   - `to_representation(instance)` → JSON-safe dict (fields, FK→pk, M2M→[pk]).
3. **Selection** — `backends.resolve_backend(meta)`:
   - `Meta.serializer_class` → `DRFSerializerBackend` (today).
   - `Meta.model` (no serializer_class) → `PydanticBackend`.
   - both set → error (ambiguous). `Meta.backend=<cls>` escape hatch kept.

## 3. User validation (the extension point)

Auto-derivation can't run a user's custom rules. v1 supports, in order:
- **`Meta.pydantic_model`** — a user Pydantic model (with `@field_validator`/
  `@model_validator`) used as the **base** the derived fields extend → full
  Pydantic-native custom validation.
- DB-level rules (FK existence, uniqueness, `unique_together`) built in.

DRF-style `validate_<field>()` method hooks are **deferred** (documented); users
needing them stay on the DRF backend.

## 4. Dependency changes
- Add `pydantic>=2,<3` as a dependency.
- Make `djangorestframework` an **optional extra** (`[drf]`): the DRF backend
  imports it lazily; using `serializer_class` without the extra raises a friendly
  error. `pytest`/dev keep both. (Decision 4 from the seam SPEC — "with the
  native backend" = now.)

## 5. Field coverage (v1)
Common 80%: Char/Text/Email/URL/Slug, Integer family, Float, Decimal, Boolean,
Date/DateTime/Time/Duration, UUID, JSON, FK/O2O (by pk), M2M (by pk), choices,
defaults, nullable, partial. **Deferred** (documented, fall back to DRF): file/
image fields, Array/HStore/range, GenericForeignKey, GIS, nested-by-object via
`pydantic_model`.

## 6. Acceptance Criteria
- **AC1** — `Meta.model` builds a working type/mutation with **no DRF imported**;
  create/update/delete behave like the DRF backend on the representative model
  (`SpikeProduct`-style: decimal/choices/unique/FK/M2M/default/partial).
- **AC2** — Nested writes (forward/reverse/M2M, atomic rollback, upsert, prefixed
  errors) work through the native backend (reusing `NestedFieldsMixin`).
- **AC3** — `Meta.pydantic_model` custom validators run and surface as field
  errors.
- **AC4** — Subscription output (`to_representation`) returns a JSON-safe dict.
- **AC5** — DRF moved to an optional extra; the existing DRF-backed suite still
  passes with the extra installed; a native-only path imports without DRF.
- **AC6** — Selection errors (both/neither configured) are clear.

## 7. Open questions (please confirm)
1. **Validation extension for v1:** `Meta.pydantic_model` (Pydantic-native
   validators) as the supported custom-validation path, DRF-style `validate_*`
   hooks deferred? **Recommend: yes.**
2. **`choices` representation:** `enum.Enum` (djantic-aligned, nicer errors) vs
   `Literal`? **Recommend: `Enum`.**
3. **`pydantic` as a hard dependency** (small, fast) vs a `[native]` extra?
   **Recommend: hard dep** (it's the strategic direction; keeps install simple).
4. **DRF → optional `[drf]` extra now** (paired with the native backend), with a
   lazy import + friendly error? **Recommend: yes.**
5. **Scope of v1 field coverage** — the 80% in §5, rest deferred to DRF?
   **Recommend: yes.**
