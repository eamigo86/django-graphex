# SPEC — Fix: robust `choices` normalization in the converter

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/converter.py`, tests, docs.
**Date:** 2026-06-07
**Origin:** investigation — the converter breaks on the modern Django `choices`
declaration forms on Django < 5.0.

---

## 1. Problem

`converter.get_choices` iterates `for value, help_text in choices` directly. Since
**Django 5.0** `choices` accepts a **mapping**, a **callable**, or an
**enumeration type** (`TextChoices`/`IntegerChoices`) passed directly, and Django
5.0+ normalizes `field.choices` to a list of 2-tuples — but **Django 4.0–4.2**
(still supported, floor `>=4.0`) does **not** normalize. So on Django < 5.0,
defining a field with the modern, recommended syntax breaks the converter
(verified):

| `choices=` | extras `get_choices` |
|------------|----------------------|
| `Status` (TextChoices) | `ValueError: too many values to unpack` |
| `{"x": "X"}` (mapping) | `ValueError: not enough values to unpack` |
| `get_choices` (callable) | `TypeError: 'function' object is not iterable` |
| `[(v, l), …]` / grouped | OK |

graphene-django already normalizes via a `normalize_choices` compat helper;
extras does not.

## 2. Design

Add a `_normalize_choices` helper and call it at the top of `get_choices`,
mirroring graphene-django's proven approach (and a superset of it):

```python
from collections.abc import Callable, Mapping
from django.db.models import Choices

def _normalize_choices(choices):
    # TextChoices / IntegerChoices passed directly (the class is itself callable,
    # so this must come first).
    if isinstance(choices, type) and issubclass(choices, Choices):
        choices = choices.choices
    if isinstance(choices, Callable):
        choices = choices()
    if isinstance(choices, Mapping):
        choices = choices.items()
    return choices
```

`get_choices` becomes:
```python
def get_choices(choices):
    choices = _normalize_choices(choices)
    converted_names = []
    for value, help_text in choices:
        ...
```

Notes:
- Order matters: a `Choices` subclass is a callable class, so it is handled before
  the callable branch.
- On Django 5.0+ `field.choices` is already a list of 2-tuples, so
  `_normalize_choices` is a passthrough — no double work, no behavior change.
- Recursion is unaffected: grouped choices recurse with a list of tuples, which
  passes through.
- `django.db.models.Choices` exists since Django 3.0 (the floor is 4.0), so no
  version guard is needed.

## 3. Acceptance Criteria
- **AC1** `get_choices` handles all forms without raising and yields the same
  `(name, value, description)` tuples: a `TextChoices`/`IntegerChoices` class, a
  mapping, a callable returning choices, a plain list of 2-tuples, and grouped
  choices. [fix]
- **AC2** `convert_django_field_with_choices` builds a GraphQL enum from a field
  whose `choices` is defined in each modern form. [fix]
- **AC3** No behavior change for the legacy list-of-tuples form; full suite green;
  base channels-free; lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/test_converter_choices.py`)
Build `CharField` / `IntegerField` with `choices` in each form (TextChoices,
IntegerChoices, dict, callable, list-of-tuples, grouped) and assert
`list(get_choices(field.choices))` matches the expected names/values, and that
`convert_django_field_with_choices` returns an enum field whose values include the
choices. (The CI floor Django 4.2 does not pre-normalize, so this exercises the
fix directly.)

## 5. Documentation
`docs/directives.md` is unrelated; add a short note to the types/fields docs that
model `choices` (including Django 5.0 mappings/callables/enumeration types) are
converted to GraphQL enums.

## 6. Definition of Done
1. Fix per §2. 2. §3 ACs green via §4; full suite green; base channels-free;
lint + `mkdocs --strict` green. 3. Docs note. 4. Committed and pushed to
`pre-v2`.
