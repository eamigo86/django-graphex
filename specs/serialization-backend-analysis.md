# Analysis — Decoupling from DRF & graphene-django (serialization layer for v2)

**Status:** ANALYSIS / RECOMMENDATION — no code. Input for the v2 direction.
**Date:** 2026-06-08
**Question:** Should v2 replace DRF serializers with a custom (Pydantic/msgspec)
serialization layer, and how tied are we to graphene-django?

---

## 1. TL;DR

- **The GraphQL schema is built from the Django *model*, not from the DRF
  serializer.** DRF is only used at **runtime** for three things: validate input,
  persist (create/update), and one output-serialization call in subscriptions.
  graphene-django is touched only at the **edges** (a 2-field `ErrorType`, the
  `GraphQLView`, a few utils/converter/filter helpers).
- So "migrate off DRF" does **not** mean rewriting type generation. It means
  re-implementing **validation + ORM persistence** for Django models. Pydantic /
  msgspec only replace the *validation* third; the **persistence** third
  (create/update with FK/M2M/reverse) is bespoke Django ORM code either way, and
  the **model→rules introspection** third is the genuinely hard, regression-prone
  part DRF already does well.
- The public extension point is literally `Meta.serializer_class = <a DRF
  serializer>`. Replacing it is a **hard breaking change** for every user who
  brought custom `validate_*`, `create()`/`update()` overrides, or custom fields.
- **Recommendation:** don't bet v2 on a rip-and-replace. Introduce a **serializer
  backend seam** (a small protocol) with the current DRF behavior as the default
  backend, and build a **native (Pydantic v2) backend incrementally** behind it.
  Separately, **vendor the thin graphene-django edges** (ErrorType, view, utils)
  to cut exposure to the unmaintained package. Both are non-breaking and can ship
  in v2; the native backend can mature across v2.x.

---

## 2. What we actually depend on

### 2.1 DRF (`djangorestframework`)
| Usage | Where | Notes |
|-------|-------|-------|
| `serializer_class.Meta.model` | `types.py`, `mutation.py` | just to get the **model**; the schema is then built from the model, not the serializer |
| `serializer(data=…, instance=…, partial=…)` + `.is_valid()` + `.save(**kw)` + `.errors` + `.initial_data` | `types.py`, `mutation.py`, `nested.py` | the **validate + persist** cycle |
| `serializer_class(instance).data` | `subscriptions/mixins.py` | one **output**-serialization call |
| `rest_framework.views.APIView`, `permissions`, `Request`, `api_settings` | `views.py` | **HTTP/auth layer** — separate concern from serialization |
| `rest_framework.serializers.Serializer/BaseSerializer` (typing), `APISettings` | `settings.py`, typing | trivial |

**Key point:** DRF is *not* used for schema/type generation (that's the project's
own `converter.py` + `factory_type`, model-driven). Its real job is the runtime
**validate → save** cycle.

### 2.2 graphene-django (the unmaintained one)
| Symbol | Where | Replaceable? |
|--------|-------|--------------|
| `ErrorType` (`{field, messages}` ObjectType) | types/mutation/nested | **trivially** — vendor a 2-field type |
| `GraphQLView` | `views.py`, subscriptions | moderate — subclass/vendor the view |
| `is_valid_django_model`, `maybe_queryset`, `DJANGO_FILTER_INSTALLED` | utils/types/fields | trivial helpers |
| `compat.{Array,HStore,JSON,Range}Field`, `to_const`, `forms.GlobalIDFormField`, `filter.utils` | converter/filters | small, vendor-able |

We are **not** deeply tied to graphene-django's type system — we roll our own
`DjangoObjectType`/converter. The dependency is a handful of edges. (Note: the
deep dependency is **graphene-core** itself — `ObjectType/Field/Schema/Int/…` —
which is *not* what's in question and is comparatively maintained.)

---

## 3. What replacing DRF really entails

A DRF `ModelSerializer.save()` quietly does a lot. A replacement must cover:

1. **Model → validation rules** (the hard third): per-field type, `required`,
   `max_length`, `choices`, `null`/`blank`, `unique`/`unique_together`, decimal
   places, datetime/UUID parsing, FK **existence**, validators. This is exactly
   what DRF generates from the model and where subtle behavior lives.
2. **Validation engine**: coerce + validate input against those rules, collect
   `{field: [messages]}`. *This is the only third Pydantic/msgspec replaces.*
3. **Persistence** (Django-specific): create/update an instance, set FKs by pk,
   handle M2M (`.set/.add`), reverse relations, `partial` updates,
   `transaction.atomic`. Neither Pydantic nor msgspec helps here — it's ORM code
   (we already wrote a chunk of it in `nested.py`).
4. **Output**: instance → JSON-safe dict (subscriptions). Easy with anything.

So the framing "use Pydantic" is misleading: Pydantic is the engine for **(2)**;
**(1)** and **(3)** are bespoke Django code we'd own and maintain — including the
DB-level checks (unique, FK existence) that aren't expressible as pure
Pydantic/msgspec validators (they need ORM queries).

---

## 4. Pydantic v2 vs msgspec (for *this* use case)

| | Pydantic v2 | msgspec |
|--|-------------|---------|
| Speed | fast (rust core) | **fastest**, lower mem |
| Dynamic schema from a model at runtime | `create_model()` — **ergonomic** | `defstruct()` — workable, clunkier |
| Per-field constraints (max_length, etc.) | rich, declarative | leaner; more manual |
| Custom/user validators (replacing `validate_*`) | **first-class**, ergonomic | stricter, less ergonomic |
| Ecosystem / familiarity | large | smaller |

The bottleneck here is the **database**, not parsing, so msgspec's raw-speed edge
is largely irrelevant to request latency. Our need is *dynamic, model-derived
schemas + user-extensible validation* — where **Pydantic v2 fits better**.
**Recommendation: Pydantic v2** as the native engine; your instinct on msgspec
("faster but harder to implement here") is right.

---

## 5. The breaking-change reality

`Meta.serializer_class` is *the* extension point, and users put real logic in
their DRF serializers (`validate_email`, `create()` overrides, `SerializerMethodField`,
nested serializers, custom fields, `to_representation`). A native backend can't
run those. Therefore a **full replacement is a hard break** and would orphan
existing serializers. This is the single biggest argument **against** rip-and-replace
and **for** a backend seam that keeps DRF working while offering a native option.

---

## 6. Options

| Option | What | Effort | Risk | Breaking |
|--------|------|--------|------|----------|
| **0. Soft-dep + edge-decouple** | Keep DRF; vendor `ErrorType`/view/utils; make graphene-django edges ours; pin/loosen versions | S | low | no |
| **1. Backend seam (recommended)** | Define a `SerializerBackend` protocol (`build/validate/save/to_representation/errors`); DRF is the default backend; add a **native Pydantic backend** incrementally | M (seam) + L (native) | medium | no (opt-in) |
| **2. Full replacement** | Native model-validation + ORM persistence; deprecate `serializer_class` | XL | high | **yes, large** |

### The seam (Option 1) sketch
```python
class SerializerBackend(Protocol):
    def get_model(self, cfg) -> type[Model]: ...
    def validate(self, data, *, instance=None, partial=False) -> Validated: ...
    def save(self, validated, *, instance=None) -> Model: ...
    def errors(self, exc) -> list[ErrorEntry]: ...           # {field, messages}
    def to_representation(self, instance) -> dict: ...        # subscriptions
```
- `types.py`/`mutation.py`/`nested.py` stop calling DRF directly and call the
  backend (the create/update/nested orchestration we just hardened stays).
- `Meta.serializer_class=<DRF>` → resolves to the **DRF backend** (today's
  behavior, byte-for-byte).
- New `Meta.model=…` (+ optional `Meta.validators`) → resolves to the **native
  backend**, no DRF needed.
- DRF becomes an **optional extra** (`pip install graphene-django-extras[drf]`);
  the native path needs neither DRF nor graphene-django.

---

## 7. Recommendation & phased plan

**Ship in v2 (non-breaking):**
1. **Edge-decouple graphene-django** (Option 0): vendor `ErrorType` (we already
   have an error shape), wrap the view, internalize the 4–5 util/converter/filter
   helpers. Removes most of the unmaintained-package surface. *Low risk, high
   signal for "v2 isn't built on abandonware".*
2. **Introduce the backend seam** (Option 1, seam only): route all
   validate/save/output through `SerializerBackend`; implement the **DRF backend**
   first (wrapping today's behavior). No user-visible change; DRF stays default.

**Across v2.x (incremental, opt-in):**
3. Build the **native Pydantic v2 backend**: model→Pydantic schema via
   `create_model`, validation, ORM persistence (reuse `nested.py`), DB-level
   checks (unique/FK existence) as explicit validators, output serialization.
   Ship behind `Meta.model`/`Meta.backend="native"`; mark experimental.
4. Once proven, make the native backend the default for `Meta.model` and DRF an
   optional extra. Never force-remove `serializer_class`.

**De-risk first:** a 1–2 day **spike** — take one non-trivial model (e.g. `Post`
with FK/M2M/choices/unique) and implement validate+save natively with Pydantic,
diffing behavior against the DRF path (error messages, edge cases). That spike
tells us the real cost of part (1)+(3) before committing.

---

## 8. Honest take

The decoupling worth doing **now** is graphene-django at the edges — cheap and it
directly addresses "v2 on unmaintained libs". The DRF replacement is **legitimate
but the persistence/rules layer is the real work, not the validation engine**, and
it's a breaking change at the most-used extension point — so it should be a
**seam now, native backend incrementally**, not a v2 rip-and-replace. Pydantic v2
is the right engine when we get there; msgspec's speed doesn't pay off against a
DB-bound workload.
