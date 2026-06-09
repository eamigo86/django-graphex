# Prior art for the native (Pydantic) backend

Notes from two existing packages the user pointed at, distilled into actionable
decisions for the upcoming `PydanticBackend`. **Neither is adopted as a
dependency** — both are vendored *ideas* (see caveats).

## 1. `djantic` (jordaneremieff/djantic) — Django model → Pydantic

The **most relevant**: it does exactly our part-1 (model → validation rules),
more completely than the spike. Reusable ideas (`djantic/fields.py`):

- **Type map** — adopt its structure (improves the spike's hand map):
  - `INT_TYPES`: Auto/BigAuto/Integer/Small/Big/PositiveInteger/PositiveSmall → `int`
  - `STR_TYPES`: Char/Email/URL/Slug/Text/FilePath/File → `str`
  - explicit: `GenericIPAddressField→IPvAnyAddress`, `BinaryField→bytes`,
    `Date/DateTime/Time/Duration→date/datetime/time/timedelta`,
    `DecimalField→Decimal`, `FloatField→float`, `UUIDField→UUID`,
    `JSONField→Union[Json,dict,list]`, `ArrayField→List`
  - **MRO-traversal fallback** then `str` + warning (handles custom field subclasses).
- **Constraints**: `max_length` only when no `choices`; **`choices` → a real
  `Enum`** (not `Literal`); `max_digits/decimal_places` for Decimal.
- **Optional/defaults**: `has_default()` → `default` (callable → `default_factory`);
  `primary_key or blank or null` → `default=None`; `Optional` via
  `Union[T, None]` when nullable.
- **Relations**: FK/O2O → the **related model's pk internal type**; M2M/reverse →
  `List[Dict[str, pk_type]]` (list of `{id: ...}`).
- **FieldInfo**: `title=verbose_name.title()`, `description=help_text or name`,
  `max_length`; lazy `Promise` strings coerced with `str()`.
- **Construction**: a `ModelSchemaMetaclass` + `create_model(__base__=...)`. We
  don't need the metaclass sugar — a plain `build_pydantic_model(model)` function
  (as in the spike) is enough.

**Caveats:** archived, and **Pydantic v1-era** (FieldInfo/Optional handling
differs in v2). Use the **type map + constraint rules as a reference**, not the
code; rewrite for Pydantic v2.

### Decisions it settles for our native backend
1. **Replace the spike's ad-hoc map** with a djantic-shaped `FIELD_TYPES` +
   `INT_TYPES`/`STR_TYPES` + MRO fallback. (Closes most of the "field long-tail".)
2. **`choices` → `Enum`** (align with graphene/DRF), not the spike's `Literal`.
3. **Decimal**: carry `max_digits`/`decimal_places` constraints.
4. Keep our **pk-list M2M** shape (nested.py already writes M2M by pk); djantic's
   `List[Dict[str,pk]]` is for *output* reads — not needed for input/persist.

## 2. `graphene-pydantic` (graphql-python) — Pydantic → graphene

**Secondary / mostly not needed**: it builds GraphQL types *from Pydantic models*,
but our schema is **model-driven** (built from the Django model by `converter.py`),
so we don't convert Pydantic → GraphQL for the main path.

Worth keeping only as a reference **if** we later choose to derive **input types**
from the native Pydantic schema instead of the model:
- `find_graphene_type()` — recursive dispatch Python type → graphene
  (scalars; `__origin__` for `Union`/`List`/`Literal`; `Enum.from_enum`; nested
  models via deferred registration).
- Pydantic v2 introspection: `model.model_fields`, `field.annotation`,
  `field.is_required()`, `field.default is PydanticUndefined`.

**Caveat:** adds a dependency and the *wrong direction* for us; do **not** adopt —
just mirror the `model_fields`/`annotation` introspection if/when needed.

## Net effect on the native-backend plan
- Part-1 (model→rules) gets cheaper and more complete by porting djantic's type
  map + constraint rules to Pydantic v2 (no dependency).
- Parts 2–3 (validate, persist, DB checks) stay as the spike already proved.
- The `SerializerBackend` seam (already landed) is the integration point; the
  native backend implements `get_model`/`save_object`/`to_representation` using
  this map + the spike engine, selected by `Meta.model`.
