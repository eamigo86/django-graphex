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

    In `graphene-django-extras` the default backend was Django REST Framework,
    selected with `Meta.serializer_class`. django-graphex has **no** DRF backend
    and no `djangorestframework` dependency: declare `Meta.model` instead.
    See the [migration guide](../migration.md).

## Native (Pydantic) backend

Point `Meta.model` at a model and the library validates with **Pydantic v2** and
persists with the ORM — no DRF required:

```python
from django_graphex import DjangoModelType

class UserType(DjangoModelType):
    class Meta:
        model = User       # native backend; no DRF
```

It derives validation rules from the model: field types, `max_length`, `choices`
(as an `Enum`), `Decimal` precision, required/nullable/defaults, foreign-key **pk**
types and many-to-many (a list of pks). It also runs the DB-level checks Pydantic
can't see — **foreign-key existence**, **uniqueness** and `unique_together` — and
supports partial updates and nested writes (atomic, relation-aware).

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

Under the hood these compile to Pydantic `field_validator` / `model_validator`, so
they also work on `DjangoModelMutation` and **compose** with `Meta.pydantic_model`.

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

- Exotic field types (file/image, Postgres array/hstore/range, GIS,
  `GenericForeignKey`) fall back to a permissive type.
