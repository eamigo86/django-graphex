# SPEC — D: error handling on `DjangoSerializerType` (nested + field paths)

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/types.py`, tests, docs.
**Date:** 2026-06-07
**Origin:** downstream `ISNDjangoSerializerType` error helpers. Final piece
(A, B, C done → D).

---

## 1. Problem / Goals

`DjangoSerializerType.save` builds the error list with
`serialized_obj.errors.items()`:

```python
errors = [ErrorType(field=key, messages=value)
          for key, value in serialized_obj.errors.items()]
```

Problems:
- **Crash on nested `many=True`.** A nested serializer built with `many=True` (via
  `Meta.nested_fields`) produces a **`ReturnList`** (a `list` of error dicts) for
  `.errors`; calling `.items()` on it raises `AttributeError`. So nested-list
  validation errors currently crash instead of being reported.
- **No field path.** Nested errors don't indicate which nested object/field
  failed (no `model_name` prefix), and `non_field_errors` is surfaced as a literal
  field name.
- Messages are passed through as `ErrorDetail` objects rather than plain strings.

**Goals**
- **G1** — Handle both a single serializer's error dict **and** a `ReturnList`
  (nested `many=True`) without crashing.
- **G2** — Prefix nested errors with a `model_name` and map `non_field_errors` to
  an empty field name (`model_name.field`, stripped).
- **G3** — Stringify messages.

### Non-Goals
- Changing the `ErrorType` shape (`field` / `messages`) or the success path.

## 2. Design

Refactor `save`'s error branch into reusable classmethods:

```python
@classmethod
def save(cls, serialized_obj, root, info, **kwargs):
    if serialized_obj.is_valid():
        return True, serialized_obj.save()
    return False, cls.get_errors_list(
        serialized_obj.errors, model_name=kwargs.get("model_name", "")
    )

@classmethod
def get_errors_list(cls, errors, model_name=""):
    """Build a list of ErrorType from a serializer's `.errors`.

    Accepts a dict (single serializer) or a list/ReturnList (many=True).
    """
    if isinstance(errors, list):           # ReturnList -> list of dicts
        result = []
        for error_dict in errors:
            result.extend(cls._errors_from_dict(error_dict, model_name))
        return result
    return cls._errors_from_dict(errors, model_name)

@classmethod
def _errors_from_dict(cls, error_dict, model_name=""):
    result = []
    for field_name, messages in error_dict.items():
        field = "" if field_name == "non_field_errors" else field_name
        field = "{}.{}".format(model_name, field).strip(".")
        result.append(
            ErrorType(field=field, messages=cls.process_error_messages(messages))
        )
    return result

@classmethod
def process_error_messages(cls, messages):
    if isinstance(messages, (list, tuple)):
        return [str(m) for m in messages]
    return [str(messages)]
```

`manage_nested_fields` passes the nested field name as `model_name` so its errors
are prefixed:

```python
ok, result = cls.save(serialized_data, root, info, model_name=field)
```

`isinstance(errors, list)` covers DRF's `ReturnList` (a `list` subclass) without
importing it; a single serializer's `.errors` is a `ReturnDict` (a `dict`).

## 3. Acceptance Criteria
- **AC1** A single serializer's validation errors produce `ErrorType` entries with
  the field name (unchanged shape) and **string** messages. [G1,G3]
- **AC2** A `many=True` serializer's errors (a `ReturnList`) are reported without
  crashing, one `ErrorType` per nested field. [G1]
- **AC3** With a `model_name`, fields are prefixed `model_name.field`;
  `non_field_errors` yields the bare `model_name` (or `""` at top level). [G2]
- **AC4** Existing mutation error behavior is preserved; full suite green; base
  channels-free; lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/`)
Use `HookModelSerializer` (requires `text`):
- AC1: `HookType.save(HookModelSerializer(data={}), None, None)` → `ok` False, an
  `ErrorType(field="text")` with string messages.
- AC2/AC3: `HookType.save(HookModelSerializer(data=[{}], many=True), None, None,
  model_name="items")` → `ok` False, `ErrorType(field="items.text")` (proves the
  ReturnList path no longer crashes and the prefix is applied).
- Unit: `_errors_from_dict({"non_field_errors": ["bad"]})` → field `""`;
  with `model_name="x"` → field `"x"`. `process_error_messages` stringifies.

## 5. Documentation
`docs/usage/types.md` (DjangoSerializerType): a short "Validation errors" note —
the `errors` field shape, nested error field paths (`model_name.field`), and that
nested `many=True` errors are reported.

## 6. Definition of Done
1. SPEC approved. 2. Refactor per §2. 3. §3 ACs green via §4; full suite green;
base channels-free; lint + `mkdocs --strict` green. 4. Docs updated.
5. Committed and pushed to `pre-v2`.
