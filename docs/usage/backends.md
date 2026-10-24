# Model backend (Pydantic)

`DjangoModelType` and `DjangoModelMutation` validate input and persist objects
through a single, built-in **native backend** powered by **Pydantic v2** and the
Django ORM — **there is no serializer and no DRF**. The backend is selected
simply by pointing `Meta.model` at a Django model:

| Backend | Selected by | Needs DRF? |
|---|---|---|
| **Native (Pydantic)** | `Meta.model` | **no** |

The GraphQL schema is built from the Django *model*, and every mutation has the
same `{ ok, errors, <object> }` shape.

!!! note "No DRF backend"

    In the previous library the default backend was Django REST Framework,
    selected with `Meta.serializer_class`. django-graphex has **no** DRF backend
    and no `djangorestframework` dependency: declare `Meta.model` instead.
    See the [migration guide](../migration.md).

## Native (Pydantic) backend

Point `Meta.model` at a model and the library validates with **Pydantic v2** and
persists with the ORM — no DRF required:

```python
from django_graphex.types import DjangoModelType

class UserType(DjangoModelType):
    class Meta:
        model = User       # native backend; no DRF
```

It derives validation rules from the model: field types, `max_length`, `choices`
(as an `Enum`), `Decimal` precision, required/nullable/defaults, foreign-key **pk**
types and many-to-many (a list of pks). It also runs the DB-level checks Pydantic
can't see — **foreign-key existence**, **field-level `unique`**, `unique_together`,
and `Meta.constraints` `UniqueConstraint` entries — and supports partial updates
and nested writes (atomic, relation-aware).

For a model `EmailField`, generated create/update inputs also run Django's email
**syntax** validator on a supplied, nonempty value. An invalid address returns
`ok: false` with an `errors` entry for the email field; neither the parent nor
a nested child is saved. An `EmailField` without choices keeps its GraphQL `String` input; a field
with choices keeps its existing Enum SDL, and validation checks the stored
choice value rather than its display label. Keep application-specific email
rules in your declared `validate_<field>()` hook or `Meta.pydantic_model`.

### Model field validation

After Pydantic validation, create and update (including nested child writes)
run Django's field-level validation (`Field.clean`) on every field **present in
the payload**: type coercion, `choices`, `null`, `blank` and the field's
validators (`max_length`, `MinValueValidator`, `MaxValueValidator`,
`RegexValidator`, custom `validators=[...]`). Failures return the normal
`ok: false` response with one `errors[]` entry per field carrying all of
Django's messages; nothing is written, and a nested child's field is prefixed
with the nested field name (`items.score`).

What does **not** run: fields the client did not send (defaults and stored
values on a partial update are left alone), `Model.clean()`,
`validate_unique()` and `validate_constraints()` (uniqueness is checked as
described below), fields with `editable=False`, and an explicit `null` on a
`null=True` column. A relation field runs only its validators, with no query
to check the target (existence is reported by the foreign-key check). A value
the developer lists in `choices` is accepted even if it is empty. Validators
that query the database are the developer's choice and cost.

Generated inputs for `PositiveIntegerField` and `PositiveSmallIntegerField`
reject supplied negative values before a database write. They return the
existing structured mutation error on the field (`ok: false`), rather than a
database constraint error. Zero and positive values remain valid; the GraphQL
input remains `Int`, with its existing upper bound. Choice-backed fields retain
their existing Enum input and validate the stored numeric choice without
replacing the Enum value. Omitted values, allowed nulls, defaults, partial
updates, and `PositiveBigIntegerField` are unchanged. This is field-local input
validation; the model field validators above also run on the supplied value.

### Uniqueness validation

The backend checks the supported Django uniqueness mechanisms on write failure,
so attributable violations surface as a structured `ErrorType` in the mutation
response rather than as a top-level GraphQL error:

| Mechanism | Where errors land |
|---|---|
| `unique=True` on a field | `errors[].field` matching the field name |
| `Meta.unique_together` | `errors[].field == "non_field_errors"` |
| `Meta.constraints` `UniqueConstraint` (unconditional, single-field) | `errors[].field` matching the field name |
| `Meta.constraints` `UniqueConstraint` (unconditional, multi-field) | `errors[].field == "non_field_errors"` |

**Conditional and expression-based constraints** (`condition=Q(...)` or
`expressions=[...]`) are **not** pre-checked: replicating their predicate
server-side is not reliable, so they remain DB-enforced. If a conditional
constraint is violated the database can raise an `IntegrityError` that the
backend cannot attribute to a field. Generated mutation fields replace its SQL
detail with the top-level GraphQL message
`A database constraint prevented this operation.`; the backend's direct
`save_object` call still raises the original exception. This does not add
`full_clean()`, predicate scans, or structured errors for those constraints.

### Nested writes

`Meta.nested_fields` accepts a **Django model** for each native child (validated
with Pydantic). Forward FK, reverse FK and M2M children all work, atomically:

```python
class CategoryType(DjangoModelType):
    class Meta:
        model = Category
        nested_fields = {"products": Product}   # native reverse-FK children
```

```graphql
createCategory(newCategory: {
  name: "Books",
  products: [{ sku: "A1", name: "Widget", price: "9.99" }]   # created + linked
}) { ok errors { field messages } }
```

### Custom validation: inline `validate_<field>()`

The quickest way to add custom rules — declare them as methods right on the class
(the same ergonomics DRF serializers offered, without any serializer):

```python
class UserType(DjangoModelType):
    class Meta:
        model = User

    # per-field — runs only when `username` is provided
    def validate_username(self, value):
        if " " in value:
            raise ValueError("username must not contain spaces")
        return value            # return the (optionally transformed) value

    # object-level cross-field — `data` holds the fields the client set
    def validate(self, data):
        if data.get("password") == data.get("username"):
            raise ValueError("password must differ from username")
        return data
```

- `validate_<field>(self, value)` rejects with `ValueError`/`AssertionError`, and
  may **transform** the value by returning a new one. It runs only when that field
  is in the input (matching DRF / partial-update semantics).
- `validate(self, data)` is the cross-field hook; its errors land on
  `non_field_errors`.
- `self` is the **type/mutation class** (no DRF `self.context`/`self.instance`).
- A `validate_<x>` that matches no model field emits a `UserWarning` at startup.
- Only hooks **you declare** — on the class or on your own base classes — are
  collected. The framework bases a host inherits are not scanned, so
  `pydantic.BaseModel`'s deprecated `validate` classmethod is never mistaken for
  your object-level hook.

Under the hood these compile to Pydantic `field_validator` / `model_validator`, so
they also work on `DjangoModelMutation` and **compose** with `Meta.pydantic_model`.

### Django columns named like Pydantic internals

Generated create/update inputs accept Django columns named `model_dump`,
`model_validate`, or `model_config`. Their GraphQL names remain `modelDump`,
`modelValidate`, and `modelConfig`; validation errors and saved model attributes
use the original Django names. The generated validation schema isolates
`model_config` under a private Pydantic field name so it does not replace
Pydantic's configuration. Inline `validate_model_config` and object-level
`validate` hooks still receive the original Django name. Inherited
`Meta.pydantic_model` field validators and serializers declared for
`model_config` also run on the isolated field; the caller's base model and
its decorator metadata are not modified.

Only generated schemas with `model_dump` or `model_validate` relax Pydantic's
protected-name check. Pydantic may warn that these fields shadow its model
methods; other models keep their existing configuration. Prefer ordinary
column names for new models, but existing database columns do not need a
GraphQL or database rename.

### Custom validation: `Meta.pydantic_model`

For reusable rule sets (or when you prefer an explicit schema), provide a Pydantic
model with validators; the derived fields extend it:

```python
from pydantic import BaseModel, field_validator

class UserRules(BaseModel):
    @field_validator("username", check_fields=False)   # field comes from the model
    @classmethod
    def no_spaces(cls, value):
        if value and " " in value:
            raise ValueError("username must not contain spaces")
        return value

class UserType(DjangoModelType):
    class Meta:
        model = User
        pydantic_model = UserRules
```

!!! note "`check_fields=False`"

    Validators in `Meta.pydantic_model` reference fields that are added by the
    derived schema, so decorate them with `check_fields=False` (Pydantic
    otherwise rejects the validator for a "missing" field).

## Current limits of the native backend

### Exotic field types fall back to a permissive scalar

`HStoreField`, GIS geometry fields, and `GenericForeignKey` are not natively
modeled by the Pydantic schema the backend derives. They are accepted as-is
(permissive scalar) without type or length validation.

`ArrayField` and range fields ARE natively modeled in v2.0 output:
`ArrayField(CharField())` renders as `[String]` (nested arrays as `[[…]]`, a
choices base as `[<Enum>]`), and a `*RangeField` renders as a `{ lower, upper }`
composite typed by its bound scalar (e.g. `IntegerRangeField` → `{ lower: Int,
upper: Int }`). See the field-type conversion reference in
[Types](types.md).

**In practice:** the fields above pass through without constraint checks. If you
need validation on these, use a `validate_<field>()` method.

`FileField` and `ImageField` are **not** in that list: the derived schema types
them with a dedicated marker that accepts exactly two shapes — an uploaded file
object (what Django's multipart parser puts in `request.FILES`) and a storage
path string — and rejects anything else with a structured error. The column's
`max_length` still constrains the string branch. See
[Automatic multipart uploads](mutations.md#automatic-multipart-uploads).

### Conditional and expression-based `UniqueConstraint` entries are DB-enforced only

`Meta.constraints` entries with a `condition=Q(...)` or `expressions=[...]`
argument are **not** pre-checked by the backend. Replicating these predicates
server-side is unreliable (they may reference database functions or
non-deterministic expressions), so the backend skips them deliberately.

**Failure contract:** when a conditional unique constraint is violated, the
database raises an `IntegrityError` that the backend cannot map to a field. A
generated create/update/delete field reports the generic top-level GraphQL
execution error above (normally HTTP 200 with that field set to `null`), not
an `ok: false` payload; nested writes roll back. The direct backend API still
raises the original `IntegrityError`. Expression-based constraints remain
database-enforced and use the same generated-field boundary if they raise an
unmapped `IntegrityError`; no expression-specific predicate check is added.

**Workaround:** add a `validate_<field>()` or `validate()` method that queries
for the conflict and raises `ValueError` before the backend reaches the DB
write.

**Unconditional single-field `UniqueConstraint`** entries (no `condition`, no
`expressions`) are fully pre-checked and surfaced as a structured `ErrorType`.
See [Uniqueness validation](#uniqueness-validation) above.

### `unique_together` reports to `non_field_errors`

Multi-field `Meta.unique_together` violations (and multi-field unconditional
`UniqueConstraint` entries) are reported under `errors[].field == "non_field_errors"`,
not on the individual field names. This matches Django's own `ValidationError`
behavior for multi-field uniqueness.

**Example mutation response:**

```json
{
  "ok": false,
  "errors": [
    {
      "field": "non_field_errors",
      "messages": ["User with this username and email already exists."]
    }
  ]
}
```
