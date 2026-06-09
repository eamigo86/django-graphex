# SPEC — Drop DRF entirely (native-only package)

**Status:** DRAFT — awaiting confirmation of §5.
**Branch:** `drop-drf` (off `native-backend`).
**Decision (user):** clean break — remove `djangorestframework` support and the
dependency completely. The package becomes **native-only** (Pydantic backend).

This is a **breaking change**: `Meta.serializer_class`, `AuthenticatedGraphQLView`
and serializer-based subscriptions are removed. Users migrate `serializer_class =
XSerializer` → `model = XModel` (+ optional `Meta.pydantic_model`).

---

## 1. What is removed

| Area | Remove |
|---|---|
| `backends.py` | `DRFSerializerBackend`; the `serializer_class` branch of `resolve_backend` / `backend_for_nested`. `resolve_backend` requires `model`. |
| `types.py` (`DjangoSerializerType`) | `Meta.serializer_class`; the DRF-delegation hooks `save()`, `get_errors_list()`, `_errors_from_dict()`, `process_error_messages()`, `get_serializer_kwargs()` (the native backend owns validation/errors). |
| `mutation.py` (`DjangoSerializerMutation`) | `Meta.serializer_class`; `save()`, `get_serializer_kwargs()`; the `BaseSerializer` typing import. |
| `nested.py` | `backend_for_nested` becomes native-only (a child spec is a model). |
| `views.py` | `AuthenticatedGraphQLView`; the guarded DRF imports; the DRF `Request` branch in `parse_body`. |
| `subscriptions/subscription.py` | `Meta.serializer_class`; the DRF `Serializer` guard/assert. `model` required. |
| `subscriptions/mixins.py` | already backend-based; drop any DRF typing. |
| `pyproject.toml` | the `[drf]` extra **and** the dev `djangorestframework`. |
| `__init__.py` | drop `AuthenticatedGraphQLView` (and any DRF-only) exports. |

`ErrorType` stays (it's our vendored type). `Meta.model` / `Meta.pydantic_model`
become the only serializer source.

## 2. Public API after

```python
class UserType(DjangoSerializerType):
    class Meta:
        model = User                 # was: serializer_class = UserSerializer
        # pydantic_model = UserRules  # optional custom validation
```
Same for `DjangoSerializerMutation` and `Subscription`. `nested_fields` maps to
**models**. `get_serializer_kwargs`/`save` overrides no longer exist (custom
validation → `Meta.pydantic_model`). The base `ExtraGraphQLView` is unchanged
(it never required DRF); `AuthenticatedGraphQLView` is gone (use the base view +
your own auth, or Django's).

## 3. Tests

- **Migrate** the generic tests from `serializer_class = XSerializer` to
  `model = X` (they exercise depth/cost/nested/types/mutations/subscriptions/
  custom-fields/queryset-hooks — all backend-agnostic): `test_mutations`,
  `test_types`, `test_nested_objects`, `test_nested_lists`, `test_query_cost`,
  `test_depth_limit`, `test_field_resolver`, `test_serializer_type_custom_fields`,
  `test_serializer_queryset_hooks`, the subscription tests, `tests/schema.py`,
  `tests/subscriptions/schema.py`.
- **Delete** the DRF-integration-only tests: `test_serializer_backend.py` (DRF
  backend), and the DRF-specific cases in `test_error_messages.py` /
  `test_views.py` (the `AuthenticatedGraphQLView` / DRF-Request bits).
- **Remove** `tests/serializers.py` once unused; drop `djangorestframework` from
  the dev group.

## 4. Docs

- `usage/backends.md` → native-only (drop the DRF backend section / comparison;
  keep `Meta.model` + `Meta.pydantic_model`).
- `installation.md` → remove the `[drf]` extra section.
- `usage/subscriptions.md`, `usage/types.md`, `usage/mutations.md` → `model=`
  examples; remove `serializer_class` / `AuthenticatedGraphQLView`.
- `changelog.md` → **BREAKING**: DRF removed; migration note.

## 5. Open question (please confirm)
**Test strategy** — migrate the ~16 generic test files from `serializer_class` to
`model` (preserves full coverage, more work) and delete only the ~3 DRF-specific
files? **Recommend: yes** (migrate generic + delete DRF-specific). The alternative
(delete all DRF-touching tests) is faster but drops real coverage of the
type/mutation/subscription machinery.

## 6. Acceptance Criteria
- **AC1** — No `rest_framework` reference anywhere in `graphene_django_extras/`
  (not even guarded/TYPE_CHECKING) and none in `pyproject.toml`.
- **AC2** — The migrated suite is green with `djangorestframework` **uninstalled**.
- **AC3** — `Meta.serializer_class` / `AuthenticatedGraphQLView` no longer exist
  (clear `AttributeError`/`TypeError` if referenced); `Meta.model` is the path.
- **AC4** — ruff + mypy clean; docs build; changelog documents the break + migration.
