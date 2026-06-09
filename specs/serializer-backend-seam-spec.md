# SPEC — `SerializerBackend` seam (path to a native/Pydantic backend)

**Status:** IMPLEMENTED (seam + DRF backend) on branch `serializer-backend`;
full suite (399) green, no public API change. `backends.py` holds
`SerializerBackend` + `DRFSerializerBackend`; types/mutation/nested/subscriptions
route through `_meta.backend`. Decisions: (1)
seam + DRF now, native backend next; (2) keep `save()`/`get_serializer_kwargs()`
hooks; (3) route subscriptions output through `backend.to_representation`; (4)
make DRF optional only with the native backend.
**Branch:** `serializer-backend` (off `decouple-graphene-django`).
**Builds on:** `specs/serialization-backend-analysis.md` + the `spike-pydantic`
findings (Pydantic replaces only the *validation* third; persistence + the
user-validation surface are the bulk, and replacing `serializer_class` is a hard
break). **Conclusion already reached:** don't rip-and-replace — introduce a seam.

This SPEC covers **only the seam + a DRF backend** (no behavior change). The
**native Pydantic backend** is the *next* phase, built on the seam, opt-in and
experimental.

---

## 1. Goal

Route every validate/save/output that `DjangoSerializerType` and
`DjangoSerializerMutation` (and `NestedFieldsMixin`) perform through a small
**`SerializerBackend`** abstraction, with a **DRF backend** that reproduces
today's behavior byte-for-byte and stays the default. This makes a future
**native backend** a drop-in alternative selected per type, with **zero** public
API change now.

## 2. Current coupling (what the seam must absorb)

DRF's serializer is touched in exactly these places (verified):

| Site | Uses |
|---|---|
| `DjangoSerializerType.create/update`, `DjangoSerializerMutation.create/update` | build `serializer_class(instance, data=, partial=, **get_serializer_kwargs)`, then `cls.save(...)` |
| `…​.save()` | `serializer.is_valid()`, `serializer.save()`, `serializer.errors`, `serializer.initial_data` (enum unwrap) |
| `…​.delete()` | model lookup only (no serializer) |
| `NestedFieldsMixin` | builds the **parent** serializer + calls `cls.save`; builds **child** serializers and `is_valid()/save(**fk)` (upsert) |
| `subscriptions/mixins.py` | `serializer_class(instance).data` (output → dict) |
| `…​Meta` | `serializer_class.Meta.model` → the model |
| Schema generation | **none** — types are built from the *model* (`converter`), not the serializer |

Key insight (from the analysis): the schema is model-driven, so the backend only
owns **runtime** validate/save + the one output call.

## 3. The interface

```python
class SerializerBackend(Protocol):
    @classmethod
    def get_model(cls, meta) -> type[Model]:
        """Resolve the Django model from a type's Meta options."""

    @classmethod
    def save_object(
        cls, model, data, *,
        instance=None, partial=False, context=None, save_kwargs=None,
    ) -> tuple[bool, Model | list[ErrorType]]:
        """Validate `data` and create/update one object.

        Returns (True, instance) or (False, [ErrorType{field, messages}]).
        `save_kwargs` are injected at save time (the reverse-FK parent link).
        `context` carries request/info + the per-type config (serializer_class,
        get_serializer_kwargs result, …)."""

    @classmethod
    def to_representation(cls, model, instance) -> dict:
        """Serialize an instance to a JSON-safe dict (subscriptions)."""
```

`save_object` is the single per-object primitive. `NestedFieldsMixin` keeps its
relation orchestration (atomic, forward/reverse/M2M ordering) and calls
`save_object` for the parent **and** each child — so any backend's nested writes
work for free.

## 4. The DRF backend (this phase)

`DRFSerializerBackend` wraps a `serializer_class` and reproduces today's logic:
- `get_model` → `serializer_class.Meta.model`.
- `save_object` → build `serializer_class(instance, data=data, partial=partial,
  **context.serializer_kwargs)`, unwrap enums on `initial_data`, `is_valid()`,
  `save(**save_kwargs)`; on failure return the existing `get_errors_list`-style
  `ErrorType` list (field-prefixing preserved).
- `to_representation` → `serializer_class(instance).data`.

The host classes resolve the backend on class creation and stash it on
`_meta.backend`; `create/update/delete` and `NestedFieldsMixin` call
`_meta.backend.save_object(...)` / `to_representation(...)` instead of touching
DRF directly. `cls.save()` is kept as a thin shim that delegates to the backend
(back-compat for subclasses that call/override it).

## 5. Backend selection
- `Meta.serializer_class = <DRF serializer>` → **`DRFSerializerBackend`** (today).
- (next phase) `Meta.model = <Model>` (+ optional `Meta.backend="native"`) →
  **`PydanticBackend`** — no DRF needed.
- Optional `Meta.backend = <SerializerBackend subclass>` escape hatch for custom
  backends.
Exactly one of `serializer_class` / `model` must resolve a backend (clear error
otherwise).

## 6. Open questions (please confirm)
1. **Scope of this phase:** land **only the seam + DRF backend** (no behavior
   change, full suite stays green), and do the native Pydantic backend as the
   *next* phase? **Recommend: yes** (keeps risk isolated; the seam is the
   refactor, the backend is additive).
2. **`cls.save()` back-compat:** some users override `save()` /
   `get_serializer_kwargs()`. Keep both as supported hooks the DRF backend calls
   (so overrides keep working), rather than removing them? **Recommend: keep.**
3. **`to_representation` move:** route the subscriptions `.data` call through the
   backend too (so a native backend can serialize output)? **Recommend: yes.**
4. **DRF as optional extra:** once the seam lands, make `djangorestframework` an
   **optional** dependency (`[drf]` extra) so a native-backend-only install needs
   no DRF? Do this **now** (guarded import) or **with the native backend**?
   **Recommend: with the native backend** (no point until there's an alternative).

## 7. Acceptance Criteria (this phase)
- **AC1** — All serializer validate/save/output goes through
  `_meta.backend`; no direct DRF calls remain in `types.py` / `mutation.py` /
  `nested.py` / `subscriptions`.
- **AC2** — `DRFSerializerBackend` reproduces current behavior: the **entire
  existing suite passes unchanged** (create/update/delete, nested forward/reverse/
  M2M/upsert/atomic, errors, subscriptions).
- **AC3** — `save()` / `get_serializer_kwargs()` overrides still work.
- **AC4** — A backend can be unit-tested in isolation; selection errors are clear.

## 8. Next phase (separate SPEC)
`PydanticBackend` built on the `spike-pydantic` engine: model→Pydantic rules,
validate, FK-existence/uniqueness, persist, `to_representation`; selected by
`Meta.model`; experimental; DRF then becomes an optional extra.
