# SPEC — Filters: a plain-ID filter (`GraphqlIDFilter`)

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `graphene_django_extras/filters/`, top-level package exports, filter
tests, docs.
**Date:** 2026-06-07
**Origin:** ported from a downstream helper used to filter by id / related id
(e.g. `status_id = GraphqlIDFilter(field_name="user__status__id")`). The real
driver was **models with UUID (string) primary keys**: the auto-generated id
filter only accepted traditional `int` values and rejected the UUID string.

---

## 1. Problem / Goals

`graphene-django-extras` exposes integer object ids as **plain `graphene.ID`**
(it is not Relay/Node based — there are no base64 global ids). Filtering by id —
especially across relations, and **especially for models whose primary key is a
`UUIDField` (or any string pk)** — has no good built-in option:

- The auto-generated / numeric filter for an id (`NumberFilter`-shaped) only
  accepts **integers**, so a **UUID string** value is rejected and the GraphQL
  argument can't even carry it.
- graphene-django's `GlobalIDFilter` / `GlobalIDFormField` type the argument as
  `ID`, but their `clean()` runs `from_global_id(value)` and therefore **requires
  a base64 Relay global id** — a plain id like `5` / `"<uuid>"` raises
  *"Invalid ID specified."*.
- A plain `django_filters.CharFilter` accepts a string but types the GraphQL
  argument as `String`, **not `ID`**.

**Goal (G1):** provide a small, explicit-use filter — `GraphqlIDFilter` — whose
generated GraphQL argument is `ID` (which accepts both int and string literals)
and whose `clean()` accepts a **plain** id, **integer or string (UUID)**, usable
for arbitrary (including related) lookups via `field_name`.

### Decisions (approved)
- **Single only** — just the single-value `GraphqlIDFilter` (no `__in`/list
  variant in this SPEC).
- **Explicit use only** — ship the filter class for developers to declare in
  their own `FilterSet`s. **No** change to auto-generated filtersets / no
  auto-detection of id fields.

### Non-Goals
- Auto-applying the filter to `filter_fields`-generated filtersets.
- A multiple-choice (`id__in: [ID]`) variant.
- Relay/global-id support (explicitly not how this library models ids).

## 2. Design

### 2.1 Form field
New `graphene_django_extras/filters/fields.py`:

```python
class GraphqlIDFormField(GlobalIDFormField):
    """Like GlobalIDFormField (so the GraphQL arg is `ID`) but accepts a plain id."""

    def clean(self, value):
        if not value and not self.required:
            return None
        if isinstance(value, int):
            value = str(value)
        try:
            CharField().clean(value)
        except ValidationError:
            raise ValidationError(self.error_messages["invalid"])
        return value
```

- Subclassing `GlobalIDFormField` is deliberate: graphene-django's
  `convert_form_field` dispatches by MRO, so the subclass still converts to a
  graphene **`ID`** argument.
- `clean()` is fully overridden to skip `from_global_id` and accept a plain
  id (ints are stringified; emptiness/None is handled per `required`).

### 2.2 Filter
```python
class GraphqlIDFilter(Filter):
    field_class = GraphqlIDFormField
```

A standard `django_filters.Filter`; all the usual kwargs work
(`field_name`, `lookup_expr`, `required`, `exclude`, ...). Default
`lookup_expr="exact"`.

### 2.3 Exports
- `graphene_django_extras/filters/__init__.py`: export `GraphqlIDFilter` and
  `GraphqlIDFormField` (added to `__all__`).
- `graphene_django_extras/__init__.py`: re-export `GraphqlIDFilter` at the top
  level for convenience.

### 2.4 Usage (developer side)
```python
import django_filters as filters
from graphene_django_extras import GraphqlIDFilter

class OrderFilterSet(filters.FilterSet):
    # filter by a related id, exposed as `ID` and accepting a plain id
    customer_id = GraphqlIDFilter(field_name="customer__id")
    status_id = GraphqlIDFilter(field_name="customer__status__id")

    class Meta:
        model = Order
        fields = ["customer_id", "status_id"]
```

## 3. Acceptance Criteria
- **AC1** A `FilterSet` using `GraphqlIDFilter(field_name=...)` produces a GraphQL
  filtering argument of type **`ID`** (verified via
  `get_filtering_args_from_filterset` / the generated field args). [G1]
- **AC2** Filtering by a **plain** id works for both an `int`-shaped and a
  `str`-shaped value, across a related lookup (`field_name="rel__id"`). [G1]
- **AC2b** Filtering works for a model whose **primary key is a `UUIDField`**:
  passing the UUID as a string returns the matching row(s). [G1]
- **AC3** A non-required filter with an empty/absent value does **not** filter
  (returns the full queryset). [G1]
- **AC4** A base64 Relay global id is **not** required (and a plain id — int or
  UUID string — that would fail `from_global_id` is accepted). [G1]
- **AC5** `GraphqlIDFilter` and `GraphqlIDFormField` are importable from
  `graphene_django_extras` and `graphene_django_extras.filters`. Full suite
  green; base channels-free; lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/`)
Add a small UUID-pk model to `tests/models.py` (e.g. `UUIDThing` with
`id = UUIDField(primary_key=True, default=uuid4)`) and a related integer-pk model
referencing it, plus `FilterSet`s in `tests/filtersets.py` declaring
`GraphqlIDFilter(field_name=...)`. Tests:

- AC1: assert the argument type for a `GraphqlIDFilter` is graphene `ID`
  (via `get_filtering_args_from_filterset`).
- AC2: build rows, filter by a related **integer** id as `int` and as `str`,
  assert the expected subset.
- AC2b: filter by a **UUID** pk passed as a string, assert the matching row.
- AC3: empty value -> unfiltered queryset.
- AC4: `GraphqlIDFormField().clean("5") == "5"`, `clean(5) == "5"`, and a UUID
  string round-trips unchanged (values `GlobalIDFormField` would reject).
- AC5: import-path smoke test.

## 5. Documentation
`docs/usage/filtering.md` — a new "Filtering by ID" subsection: explain that ids
are plain (not Relay global ids), that `GraphqlIDFilter` exposes the argument as
`ID` and accepts a plain id **including UUID/string primary keys** (where the
auto-generated numeric filter only accepts ints), and show declaring
`GraphqlIDFilter(field_name="...__id")` in a custom `FilterSet`. Add the class to
`docs/api/` if a filters API page exists.

## 6. Definition of Done
1. SPEC approved.
2. `GraphqlIDFormField` + `GraphqlIDFilter` added and exported per §2.
3. §3 ACs green via §4 tests; full suite green; base channels-free; lint +
   `mkdocs --strict` green.
4. Docs updated.
5. Committed and pushed to `pre-v2`.
