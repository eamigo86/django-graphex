# SPEC — Rename to `DjangoModelType`/`DjangoModelMutation` + inline `validate_<field>()` validators

Status: accepted
Branch: `model-rename-validators` (off `drop-drf`)
Type: breaking (rename) + additive (validators)

## Motivation

After the DRF removal, the public names `DjangoSerializerType` /
`DjangoSerializerMutation` are misleading: there is no serializer anymore — these
classes are configured with `Meta.model` and validate with the native Pydantic
backend. This SPEC:

1. **Renames** them to `DjangoModelType` / `DjangoModelMutation` (clean break, no
   aliases — consistent with the rest of the v2 breaking release).
2. **Adds DRF-style inline validators**: declare `validate_<field>(self, value)`
   (and an object-level `validate(self, data)`) directly on the class, instead of
   writing a separate `Meta.pydantic_model`. Pure ergonomics — it compiles down to
   the same Pydantic validators; `Meta.pydantic_model` keeps working and composes.

## Part 1 — Rename (clean break)

| Old | New |
|---|---|
| `DjangoSerializerType` | `DjangoModelType` |
| `DjangoSerializerMutation` | `DjangoModelMutation` |
| `DjangoSerializerOptions` (internal) | `DjangoModelTypeOptions` |

- Update `__all__` / exports in `graphene_django_extras/__init__.py` and
  `types.py`; the old names are **removed** (importing them raises `ImportError`).
- Update every internal reference, docstring and **user-facing string/message**
  (e.g. `consumers.py`, `permissions.py` docstrings) to the new names.
- **Not touched** (historical record): `specs/*` and the historical version
  sections of `docs/changelog.md`. The `2.0.0` changelog section and `migration.md`
  v2 section ARE updated, and document the rename (the `migration.md` "Before
  (v1.x)" snippet intentionally keeps the old name).
- Tests, `examples/playground`, and current-API docs are migrated to the new names.

### Acceptance (Part 1)
- AC1: `from graphene_django_extras import DjangoModelType, DjangoModelMutation`
  works; the old names are gone (`grep` for them returns only historical specs +
  historical changelog + the migration "Before" snippet).
- AC2: full suite green; ruff + mypy clean.

## Part 2 — Inline `validate_<field>()` validators

### API

```python
class PostType(DjangoModelType):
    class Meta:
        model = Post

    # per-field — mirrors DRF's validate_<field>(self, value)
    def validate_title(self, value):
        if value.isupper():
            raise ValueError("title must not be all caps")
        return value

    # object-level cross-field — mirrors DRF's validate(self, data)
    def validate(self, data):
        if data.get("status") == "published" and not data.get("body"):
            raise ValueError("a published post needs a body")
        return data
```

- `validate_<field>(self, value)` → returns the (optionally transformed) value, or
  raises `ValueError`/`AssertionError` to reject. Mapped to a Pydantic
  `field_validator(<field>, mode="after", check_fields=False)`.
- `validate(self, data)` → receives a `dict` of the **set** fields (post field
  validation), returns the dict (may mutate values), or raises to reject. Mapped to
  a Pydantic `model_validator(mode="after")` with a dict adapter that writes any
  changed keys back onto the model.
- `self` is the **host class** (`DjangoModelType`/`DjangoModelMutation` subclass),
  so `self._meta` etc. are reachable. (No DRF `self.context`/`self.instance`.)

### Wiring

A new helper `build_validator_model(host_cls, pydantic_model)` in the native layer
(`native/validators.py`):

1. Scans `host_cls` (including bases, MRO order) for callables named `validate` and
   `validate_<name>`.
2. If none found → returns `pydantic_model` unchanged (zero overhead).
3. Otherwise builds a synthetic Pydantic base class via `type(...)`:
   - bases: `(pydantic_model,)` if given, else `(BaseModel,)`;
   - each `validate_<field>` → `field_validator(field, check_fields=False)` wrapping
     a classmethod that calls the user fn as `fn(host_cls, value)`;
   - `validate` → `model_validator(mode="after")` with the dict adapter.
4. Returns that synthetic class.

`DjangoModelType` / `DjangoModelMutation` `__init_subclass_with_meta__` call it and
pass the result as `pydantic_model` to `resolve_backend(...)` — the backend is
unchanged. Subscriptions are **not** affected (they serialize output, not input).

### Edge cases / decisions
- **Composition**: an inline `validate_title` AND a `Meta.pydantic_model` with its
  own `title` validator both run (base-then-subclass order) — documented.
- **Unknown field**: a `validate_<x>` where `x` is not a model field emits a
  `UserWarning` at class creation (the validator would silently never run). Uses
  `check_fields=False` so it doesn't hard-error.
- **Transform**: returning a different value from `validate_<field>` persists the
  transformed value (e.g. normalization); same for keys returned by `validate`.
- **Errors**: `ValueError`/`AssertionError` messages surface in the standard
  `{ field, messages }` shape; `validate`'s errors land on `non_field_errors`.

### Acceptance (Part 2)
- AC3: a per-field `validate_<field>` rejects invalid input (error on that field)
  and can transform a valid value; works on both `DjangoModelType` and
  `DjangoModelMutation`.
- AC4: an object-level `validate` enforces a cross-field rule (error on
  `non_field_errors`).
- AC5: inline validators compose with `Meta.pydantic_model`; a `validate_<unknown>`
  warns.
- AC6: with no inline validators, behavior and the resolved `pydantic_model` are
  unchanged (no synthetic class built).

## Docs
- `usage/backends.md`: add an "Inline validators" subsection (DRF-style), alongside
  the existing `Meta.pydantic_model`.
- `migration.md` v2 section: add the class rename as a breaking change with a
  before/after; mention inline validators as the smoother path for ex-DRF
  `validate_*`.
- `changelog.md` 2.0.0: note the rename (BREAKING) and the inline validators (Added).
- Rename across all current-API docs.

## Commits
1. `docs: SPEC — DjangoModelType/Mutation rename + inline validators`
2. `refactor!: rename DjangoSerializerType/Mutation -> DjangoModelType/Mutation`
3. `feat: DRF-style inline validate_<field>() validators on the native backend`
