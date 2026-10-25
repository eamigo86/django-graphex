# Upgrading to django-graphex 4.1

This guide covers the move from 4.0 to 4.1. The 3.x to 4.0 migration
(graphql-core 3.3, `Executor`, immutable AST nodes) stays in the
[4.0 upgrade guide](UPGRADE-4.0.md); do that first if you are still on 3.x.

## Compatibility policy

4.1.0 is a minor release. Several changes below alter wire output, defaults,
validation or schema-build behavior in ways a client or an application may
notice. They are treated as bug fixes: each one corrects incorrect, unsafe or
inconsistent behavior of 4.0.0 (a hidden row that could be edited, a number that
lost precision, a typo that left a column published, a transaction that did not
roll back). Each has a section here saying what changed, who is affected and how
to migrate. The [changelog](changelog.md) lists the same changes under
"Behavior changes".

```bash
uv add "django-graphex==4.1.0"
# or
pip install "django-graphex==4.1.0"
```

The `graphql-core>=3.3.0,<3.4` requirement is unchanged.

## Upgrade checklist

Run your test suite and a schema comparison (`print_schema` before and after)
against 4.1, then check these in order. Items near the top fail loudly; items
near the bottom change results silently.

1. **Startup errors:** a second public output type for one model, an unknown or
   bare-string `only_fields`/`exclude_fields`, ambiguous or colliding `choices`
   enums, reserved `__` `Literal` values, a model whose `get_fields()` fails.
   See [Schema and startup changes](#schema-and-startup-changes).
2. **Schema and client types:** `Decimal` and `BigInt` scalars,
   `DEFAULT_PAGE_SIZE`, typed input annotations, `DateField` part filters,
   interface field names. Regenerate client types.
3. **Writes:** model field validators, visibility of update/delete targets and
   linked rows, nested child ids, rollback on GraphQL errors. See
   [Mutations and writes](#mutations-and-writes).
4. **Reads and visibility:** automatic forward and reverse FK, OneToOne, M2M and
   GenericForeignKey output reads and the filters that traverse them now apply the
   destination type's `get_queryset`; malformed ids answer `INVALID_ID`. See
   [Relations and output](#relations-and-output) and
   [Pagination, ordering and filters](#pagination-ordering-and-filters).
5. **Ordering and pagination:** NULL placement, primary-key ties, cursor
   validation, `page: null`, `DEFAULT_PAGE_SIZE`.
6. **Directives:** library transforms accept only field locations, `@date` and
   `@number` keep `null`, numeric directives are exact. See
   [Directives](#directives).
7. **HTTP status and error handling:** execution errors answer HTTP 200 (see
   [Execution errors return HTTP 200](#execution-errors-return-http-200)),
   malformed bodies and server faults have their own status codes, subscriptions
   over HTTP are refused, multipart files are capped one by one, async results
   fail on the synchronous views, negative limits raise. See
   [HTTP, limits and execution](#http-limits-and-execution).
8. **Subscriptions:** `subscription_scope` is intersected with the client filter,
   the WebSocket subprotocol is required, notifications are best-effort. See
   [Subscriptions](#subscriptions).
9. **New settings** you may want to tune: see
   [New settings](#new-settings).

## Schema and startup changes

### Decimal and BigInt scalars in outputs, inputs and filters

Auto-derived `DecimalField` output changes from a `Float` number to the existing
`Decimal` scalar, which is serialized as an exact JSON string:

```json
{"price": 19.99}
```

becomes

```json
{"price": "19.99"}
```

Large values no longer round through a binary float, and values with
`decimal_places >= 7` print in plain positional notation (`0.00000050`, not
`5.0E-7`; only a value that would need more than 1000 padded zeros keeps its
scientific form). Auto-derived `BigIntegerField` and `PositiveBigIntegerField` map to
the `BigInt` scalar in output, generated mutation inputs and automatic filters;
the wire value is a decimal string, even for small values (`"42"`). Python and
ORM values stay `int`. Who is affected: any client that reads these fields as JSON
numbers, declares variables of type `Float`/`Int` for them, or has generated
types from the SDL. Migrate by regenerating types and parsing the string (for
JavaScript, `BigInt(value)` or a decimal library). An explicitly declared
`Float` field with a resolver that returns a `Decimal`, explicit scalar
overrides, ordinary `Int` fields and generated `ID` fields are unchanged.
Relation IDs pointing at a BigInteger primary key still accept a string or an
integer through `ID`. The `Decimal` scalar also rejects `NaN`, `sNaN` and
infinities at coercion (`Decimal cannot be a nonfinite Decimal: 'Infinity'`) for
every lookup and for mutation inputs, instead of reaching the ORM.

### One public output type per model and registry

Declaring a second distinct public `DjangoObjectType` for the same Django model
in the same `Registry` now raises `ImproperlyConfigured` at class creation; 4.0
silently replaced the type used by nested relations. Re-registering the same
class stays idempotent, and re-executing the same declaration (module reload,
notebook, benchmark harness) replaces the stale type instead of raising. "Same
declaration" means the same module, the same qualified name and the same public
GraphQL name (`Meta.name`, default the class name). Two types built by one
factory function share module and qualified name, so variants with different
names (`PublicAuthor` and `AdminAuthor`) are distinct types and raise. A user
type declared after a mutation, `DjangoModelType` or list type for the same
model replaces the generated placeholder. If you serve public and admin
variants of one model, give each its own registry or set `skip_registry = True`
on the secondary type. `InputType` follows the same rule and now honors
`Meta.name` as its GraphQL name (it was ignored before): code that set
`Meta.name` on an `InputType` sees that name in the SDL, and factory-made inputs
with different names stay registered side by side instead of the later one
replacing the earlier.

```python
class AdminArticleType(DjangoObjectType):
    class Meta:
        model = Article
        skip_registry = True  # or build it against a separate Registry
```

### Strict only_fields and exclude_fields

`Meta.only_fields` and `Meta.exclude_fields` are validated at class creation
before the registry changes. An unknown name or a bare string
(`exclude_fields = "name"` instead of a tuple) raises `ImproperlyConfigured`.
`DjangoModelMutation`, `DjangoModelType`, `DjangoListObjectType` and
`DjangoInputObjectType` now apply the same check as `DjangoObjectType`; before,
a typo silently left the column you meant to hide published or writable. Valid
model, reverse-relation, private and declared custom field names are still
accepted. The selectors `pk` and a foreign key's attname (`author_id`) are
not field names either: 4.0 silently ignored them, so the column stayed
published or writable, and they now raise as well. Name the field (`id`,
`author`) instead. Fix the name or the tuple.

### Ambiguous and colliding choices enums

Generated `choices` enum member names that would need a positional suffix to be
unique now raise `ImproperlyConfigured`, because reordering the choices could
silently change what a literal means. Two incompatible automatic `choices`
enums that normalize to the same GraphQL type name in one registry also raise,
naming both model fields. Compatible definitions (including reordered members)
still share one enum. Rename the colliding app, model or field, change the
choices so each member name is distinct, or separate the schema surfaces with
different registries; clients using suffixed literals must migrate to the new
names.

### Reserved double-underscore enum values

A `Literal["__x"]` input value would generate the reserved member `__X`, so the
schema built but every query failed. The build now raises an error naming the
input type, field and value. A Django choice whose value starts with `__` falls
through the usual label or `A_<value>` naming instead. Rename the value.

### Model field enumeration failures

When Django cannot enumerate a model's fields (`get_fields()` raises), schema
construction now stops with a configuration error naming the model and keeping
the original exception as its cause, instead of publishing a type with concrete
fields only that may omit reverse relations. Fix the underlying model metadata
error; healthy schemas are unchanged.

### Configuration checks raise ImproperlyConfigured

The package no longer relies on `assert` for configuration and input checks,
which vanish under `python -O`. An invalid `Meta.model`, `Meta.registry`,
`Meta.queryset`, `input_for`, an empty `DjangoUnionType`, a bad paginator or an
abstract type with extra options now raises `ImproperlyConfigured` with the same
message (it raised `AssertionError`). If you catch `AssertionError` around
schema construction, catch `ImproperlyConfigured` instead. The scalar
serializers `CustomTime`, `CustomDate` and `CustomDateTime` and internal
invariants still raise `AssertionError`.

### Interface field wire names

Adding an interface to an object type no longer renames fields that are not part
of the interface: only a field the interface also declares uses its explicit
`name=`, and every other field keeps the name it has without interfaces.
Explicit `name=` on `DjangoInterfaceType` fields and matching implementor fields
is honored in SDL, introspection and queries (`internalName` becomes `name`, no
legacy alias). Compare the schema before and after and update affected queries.

### Mutable defaults are copied

A mutable literal default such as `tags: list[str] = []` on an `InputType` field,
or `default=[...]` on a field argument, used to be coerced once and shared by
every request. Each execution now receives its own deep copy, also inside nested
inputs. A resolver receives an equal copy of the declared default, not the
declared object, so do not rely on identity. Zero-argument factories on
hand-authored `InputType` fields are evaluated per coerced input object, and
their values no longer appear as fixed SDL defaults.

## Input annotations

### String Literal input values

All-string `Literal` annotations on hand-authored inputs now expose GraphQL
enums instead of `String`. For `ArticleInput.status: Literal["draft",
"published"]`, the generated `ArticleInputStatusEnum` accepts `DRAFT` and
`PUBLISHED`. Update inline operations from `status: "draft"` to
`status: DRAFT`; update JSON variables from `"status": "draft"` to
`"status": "DRAFT"`. Resolvers still receive the raw string `"draft"`.
Invalid members are rejected before resolver execution. Numeric or mixed
`Literal`, other parameterized sets, other parameterized dictionaries, and
other unions keep their existing warning and `String` fallback; this
does not add automatic Pydantic validation.

### Direct integer-or-string Union input values

A direct `typing.Union[int, str]` or `int | str` field (either member order)
now changes from `String!` to the shared `IntOrString!` scalar. Outer nullable
forms use `IntOrString`. Change a GraphQL variable declaration from
`$value: String!` to `$value: IntOrString!` and regenerate typed client code.
For example, `{"value": 123}` reaches the resolver as Python `int(123)`;
`{"value": "123"}` remains Python `str("123")`. Only signed 32-bit
integers are valid. Booleans, all floats including `1.0`, objects, lists, and
out-of-range integers reject before mutation; there are no implicit casts.
Existing omitted fixed/factory default values stay unchanged, including
malformed legacy defaults. Other Union shapes and global scalar behavior do
not change.

### Typed integer-map input values

`dict[str, int]` and `typing.Dict[str, int]` input fields change from
GraphQL `String` to the existing raw `JSON` scalar. Change JSON variables from an encoded string such as
`"mapping": "{\"count\":3}"` to an object, `"mapping": {"count": 3}`;
inline GraphQL values use `mapping: {count: 3}`. The object must have string
keys and plain integer values: booleans, numeric strings, floats, nested
containers and non-object values fail before mutation execution. Empty
objects and integers beyond 32-bit are valid. Bare `dict` remains permissive
raw `JSON`; no global Pydantic validation or other typed-container conversion
is introduced.

### Typed string-map input values

Exact `dict[str, str]` and `typing.Dict[str, str]` input fields now use
`JSON` instead of the legacy `String` fallback. Replace encoded-string
variables with JSON objects, for example `"mapping": {"name": "Ada"}`,
or use `mapping: {name: "Ada"}` inline. Both string keys and string values are required;
other types are rejected before mutation resolution without conversion.
Empty objects remain valid. Other parameterized dictionary forms remain
unchanged, and a bare `dict` remains permissive raw JSON.

Exact `dict[str, bool]` and `typing.Dict[str, bool]` direct mutation inputs now
use the same `JSON` scalar instead of `String`. Send a JSON object such as
`"mapping": {"enabled": true}` or inline `mapping: {enabled: true}`;
encoded JSON strings no longer match the wire type. Every key must be a
string and every value must be an exact Boolean (`true` or `false`): `1`,
`0`, `"true"`, null and nested values fail before the resolver or omitted
sibling factories run. Empty objects are valid. Outer Optional, alias and
fixed/factory-default behavior, including malformed omitted legacy defaults,
is unchanged. This is field-local validation, not a change to bare `dict`,
other maps, list-wrapped maps or the global JSON scalar.

### Nested supported input lists

Nested lists of already-supported input leaves now expose their full GraphQL
list shape instead of the earlier one-level `String` fallback. For example,
`rows: list[list[int]]` changes from `[String!]!` to `[[Int!]!]!`; send
`[[1, 2], [3]]` rather than encoded strings. GraphQL's normal coercion also
wraps `[1, 2]` as `[[1], [2]]` and `1` as `[[1]]`, without casting leaf
values. Optionality applies separately to the outer list, each inner list,
and each leaf. Supported input objects, all-string `Literal` enums, JSON,
and exact strict typed maps retain their existing leaf semantics inside these
wrappers. Unsupported leaves still warn and use the earlier `String` fallback.

### Exact integer-set input values

An exact `set[int]` or `typing.Set[int]` input field changes from GraphQL
`String!` to `[Int!]!`.
Replace the old encoded string with an integer array, for example
`"numbers": [2, 1, 2]`; GraphQL also accepts a singleton integer
`"numbers": 3`. The mutation resolver now receives a Python set (`{1, 2}`
or `{3}`), with duplicates removed and no promised iteration order. Native
`GraphQLInt` rejects booleans and numeric strings before resolution; there is
no custom cast or automatic Pydantic validation. Existing optionality and
default behavior remain. Other unapproved set leaves and sets inside lists keep their
warning and `String` fallback.

### Exact string-set input values

Exact `set[str]` and `typing.Set[str]` mutation inputs change from
`String!` to `[String!]!`. Replace an encoded string with a string array,
for example `"colors": ["red", "red", "blue"]`. A singleton
`"colors": "ab"` is also valid and reaches the resolver as `{"ab"}`,
not separate characters. Duplicate list values become one Python set member;
iteration order is not promised. Native `GraphQLString` rejects invalid
non-string inputs before resolution without custom casts. Outer optionality
and default behavior stay unchanged; other unapproved set leaves and nested sets retain
the warning and `String` fallback.

### Exact boolean-set input values

Exact `set[bool]` and `typing.Set[bool]` mutation inputs change from
`String!` to `[Boolean!]!`. Replace an encoded string with a boolean
array, for example `"flags": [true, false, true]`. A singleton
`"flags": false` is valid and reaches the resolver as `{False}`.
Duplicates become one Python set member; iteration order is not promised.
Native `GraphQLBoolean` rejects 0, 1, strings and null list items before
resolution without truthiness casts. Outer optionality and defaults stay
unchanged; other unapproved set leaves and nested sets retain the warning/`String`
fallback.

### Exact float-set input values

Exact `set[float]` and `typing.Set[float]` mutation inputs change from
`String!` to `[Float!]!`. Replace an encoded string with a finite numeric
array, for example `"amounts": [1.5, 1.5, 2.0]`. A singleton
`"amounts": 2` is also valid and reaches the resolver as `{2.0}`.
Duplicate values become one Python set member; iteration order is not
promised. Native `GraphQLFloat` rejects booleans, strings and null items;
variables reject nonfinite values. A field-local check rejects overflowing
numeric literals such as `1e999` before resolution, without a second cast.
Outer optionality and defaults remain; other unapproved set leaves and
nested sets retain warning/`String` fallback.

### Exact UUID-set input values

Exact `set[uuid.UUID]` and `typing.Set[uuid.UUID]` mutation inputs change from
`String!` to `[UUID!]!`. Replace an encoded string with a UUID string array,
for example `"keys": ["12345678-1234-5678-1234-567812345678"]`.
A singleton `"keys": "12345678123456781234567812345678"` remains one
UUID, not individual characters. The existing native UUID scalar also accepts
uppercase and 32-hex strings; invalid UUIDs and null items reject before the
resolver. Duplicates become one Python set member with no ordering promise.
Outer optionality and defaults remain; other unapproved set leaves and nested
sets retain warning/`String` fallback.

### Exact finite Decimal-set input values

Exact `set[decimal.Decimal]` and `typing.Set[decimal.Decimal]` mutation inputs
change from `String!` to `[Decimal!]!`. Migrate an encoded string to a native
Decimal list such as `"amounts": ["10.10", "10.10"]`, or a singleton
`"amounts": "10.10"`. The existing Decimal scalar preserves finite precision,
including huge finite exponents; the resolver receives a deduplicated Python
set with no ordering promise. Supplied NaN, sNaN and positive/negative
Infinity now reject before resolution and omitted sibling factories. Existing
Optional/default/alias/pruning behavior, including malformed legacy omitted
defaults, remains unchanged. This does not change the global Decimal scalar or
other unsupported set leaves.

A fixed JSON default whose object keys are GraphQL Names, such as
`{"views": 0}`, now prints as `mapping: JSON = { views: 0 }` and appears in
default-value introspection. The omitted input still receives the same raw
value. Keys such as `"x-y"` cannot be GraphQL Names: their existing runtime
default behavior is unchanged, but `print_schema` and introspection cannot
render a valid GraphQL object literal for them. Valid fixed list-wrapped JSON defaults, including correctly shaped nested
lists, also render in SDL and introspection. Their resolver receives an equal
list value with unchanged JSON leaves;
malformed list defaults retain their prior runtime and metadata behavior.
For defaults whose metadata cannot render,
`Field(default_factory=lambda: {"views": 0})` supplies each omitted input
without publishing a fixed SDL default. A nullable `None` default remains
unaffected; cyclic and non-JSON-native fixed values, strings containing
unpaired Unicode surrogates, and integers beyond Python's configured
integer-to-string limit gain no new metadata support. Their runtime defaults
remain unchanged.

## Pagination, ordering and filters

### DEFAULT_PAGE_SIZE is now 100

The library default `DEFAULT_PAGE_SIZE` changes from `None` to `100`. A list
queried without a size on the global LimitOffset paginator, or on a
default-constructed Page or Cursor paginator, now returns the first 100 rows;
before, it returned every row. Clients that relied on receiving everything must
paginate. An explicit positive global or per-type size still wins, this is not a
maximum (`MAX_PAGE_SIZE` stays `None`), and an explicit `None` keeps each
paginator's old behavior (Page still answers `results: null` when no size
exists). To keep the old behavior set it back, before paginator classes are
imported at startup (existing instances are not hot-reloaded):

```python
DJANGO_GRAPHEX = {"DEFAULT_PAGE_SIZE": None}
```

### Ties are ordered by primary key

Bounded model-backed LimitOffset and Page slices (including nested window and
materialized paths) append the primary key ascending after the existing
ordering unless it is already present, so pages are deterministic within ties.
Rows that tie on the sort key and had no defined order may appear in a
different order. An explicit primary-key direction and client ordering
validation are unchanged. A negative page whose database `COUNT` fails now
returns the generic error `Unable to calculate pagination count` instead of
loading the whole queryset to recover the page.

### Explicit page null is the first page

`page: null` on a page-number list is treated as an omitted `page` (page 1)
instead of failing with a raw comparison error. Clients that relied on that error
should reject `null` before sending the request. The zero-page error and the
negative-page behavior are unchanged.

### Explicit exact null selects NULL rows

An explicitly supplied `exact: null` in a generated query filter now selects
SQL NULL rows, like `isnull: true` (for nullable relation IDs and JSON fields,
SQL NULL rather than JSON `null`). An omitted lookup still adds no predicate.
A client that sent `exact: null` to mean "ignore this filter" must omit the
lookup:

```graphql
# Before: no filter. After: only rows whose category is NULL.
posts(filter: { category: { exact: null } }) { ... }
```

### Not inside to-many relation filters

Inside a to-many relation object, `not` now means "no related row matches the
operand" (a `NOT EXISTS`), not "this same related row does not match". Results
change when `not` sits beside a positive criterion or wraps an `and`. For posts
tagged with every subset of `x`, `y`, `z`:

| Filter on `tags` | 4.0 | 4.1 |
| --- | --- | --- |
| `{ and: [x, { not: z }] }` | `x`, `xy`, `xz`, `xyz` | `x`, `xy` |
| `{ label: x, not: y }` | `x`, `xy`, `xz`, `xyz` | `x`, `xz` |
| `{ not: { and: [x, y] } }` | not the complement of `{ and: [x, y] }` | every post |

A `not` alone, `not: { or: ... }`, a top-level `not` and every filter outside
relation objects are unchanged. Separate explicit `and` branches over a
many-to-many or reverse foreign-key relation now match different related rows
(even nested under `or` or `not`), so a query that returned no parent may now
return one; group criteria inside one relation object to require the same row.
Deeply nested `and` chains over to-many relations compile to sibling `EXISTS`
and no longer fail on SQLite with `Expression tree is too large`.

The same rule now applies to an `or` operand that holds a relation key. On a
post, `{ or: [{ tags: x }], tags: z }` used to test both criteria on one shared
tag row and returned nothing for a post tagged `x` and `z`; it now matches that
post, like `{ and: [{ tags: x }], tags: z }`. An `or` of a relation operand and
a negated one (`{ or: [{ tags: x }, { not: { tags: z } }] }`) tests "has x" and
"has no z" independently. Results change only for these shapes; `or` operands
without a sibling relation key or a `not` are unchanged.

A `not` that encloses a relation object is now the exact complement of that
object's match. `{ not: { tags: { and: [z, x] } } }` used to exclude posts
tagged `x` and `z` on different tags (the ORM's `exclude()` tests each
criterion separately) although no single tag is both; it now returns every
post. A double negation `{ not: { not: { tags: x } }, tags: y }` uses a
separate tag for each key.

### Numeric date-part filters take Int

Explicitly declared numeric `DateField` and `DateTimeField` part filters
(`year`, `month`, `day`, `week_day`; plus `hour`, `minute`, `second` for
datetimes) are typed as `Int`. Change `$year: Date` or `$year: DateTime` to
`$year: Int` and send an integer. Full-value ISO filters are unchanged.

### Tampered and unconvertible cursors

A tampered cursor on an in-memory (prefetched or nested) list answers
`Invalid cursor`, like the database path, instead of a masked internal error. The
cursor boundary is converted once to the ordering field's type for integer,
float, Decimal, UUID, date, datetime and time fields, and a non-finite float or
Decimal boundary is refused on both paths. Clients should treat `Invalid cursor`
as a client error and drop the cursor.

Both paths apply one rule: a finite `Decimal` of any size up to ten to the
10,000th is valid (the database path used to refuse values above float range,
such as `1e999`), and a datetime or time cursor must carry a timezone exactly
when the column does, so a naive datetime cursor is now refused on the
database path too when `USE_TZ` is on. Cursors issued by the server are
unchanged.

When the ordering column is a model `DecimalField`, a boundary with more
fractional digits than the field's `decimal_places` (trailing zeros ignored, so
`2.50` and `2.5` both fit two places) is `Invalid cursor` on both paths. No
stored value can equal such a boundary, and the database used to round it
(`1e-999` compared as zero on SQLite) while memory compared it exactly. Huge
magnitudes stay valid, and annotation orderings are unchanged.

### Nullable ordering in offset and page results

`LimitOffsetGraphqlPagination` and `PageGraphqlPagination` now place NULL last
ascending and first descending for automatic ordering by a nullable concrete
model column, including nested SQL-window pages and materialized lists. For
example, `ordering: "categoryId"` on nullable `category_id` now returns
category 1, category 2, then NULL; descending returns NULL first. On SQLite,
queryset pages previously used the opposite implicit NULL placement, so a
client that depended on that order will see a changed page boundary. Use an
explicit queryset expression such as
`F("category_id").asc(nulls_first=True)` to keep NULL first ascending.
Explicit ORM expressions and their NULL flags, custom expressions, relation
ordering, term priority, PK ties, and Cursor pagination are unchanged. The
automatic policy is not a promise about arbitrary annotations or SQL aliases.

### Review filters that traverse a forward FK

A public nested filter such as
`posts(filter: { author: { name: { exact: "Ada" } } })` now applies
`AuthorType.get_queryset` for the current request before the author can
satisfy the predicate. A post linked to a hidden author no longer matches,
even when the post itself remains visible. Each forward-FK hop in a longer
filter path is scoped. If clients previously expected hidden destinations to
match, review those filters and destination hooks.

Direct source FK-ID filters such as `author: { exact: 7 }` keep their existing
contract; a hidden target ID may still match the source row. An omitted filter
and real nullable-FK matches also keep their meanings. Forward OneToOne
and M2M filters have their own bounded rules below; custom filter bodies,
ordering, and OneToOne output reads are separate from this FK filter rule;
automatic FK output reads have [their own rule](#review-automatic-forward-and-reverse-fk-output-reads). See
[forward-FK filter scope](usage/filtering.md#forward-fk-filter-scope).

### Review filters that traverse a forward OneToOne

A declared destination-field filter such as
`profiles(filter: { user: { name: { exact: "Ada" } } })` now applies
`UserType.get_queryset` before the linked user can satisfy the predicate.
Review clients that previously selected visible profiles through hidden
users. A direct source-column `user: { exact: 7 }` filter and a genuinely
absent nullable OneToOne relation retain their prior meanings. An omitted or
empty relation filter is still a no-op. The existing reverse OneToOne filter
path already invoked its destination hook; automatic OneToOne output reads
have the separate rule above. See
[forward OneToOne filter scope](usage/filtering.md#forward-o2o-filter-scope).

### Review filters that traverse a reverse FK

Nested reverse-FK predicates now use the child type's `get_queryset` for the
current request. A hidden child can no longer make its visible parent match;
direct reverse-child ID lookups are scoped as well. `not` complements the
visible matching-child set, while separate `and` branches can use different
visible children. An absent or hidden-only child set retains the ordinary NULL
lookup behavior. Review callers that previously used hidden child fields or
IDs to select parents. An automatic reverse output accessor remains required:
an explicitly declared or permission-pruned relation still has no filter path.
See [reverse-FK filter scope](usage/filtering.md#reverse-fk-filter-scope).

### Review filters that traverse an M2M relation

Both forward and reverse M2M filter paths now apply the destination type's
request-specific `get_queryset` before a linked target can satisfy the
predicate. Hidden targets no longer make visible sources match. Direct and
nested target-ID lookups are scoped as well; unlike a direct forward-FK ID,
an M2M ID is read through the target table. An absent or hidden-only visible
target set retains ordinary relation-NULL behavior, and separate `and`
branches can still use different visible targets. Review filters that
previously selected sources through hidden tags or other M2M destinations.
Automatic M2M output reads have the separate rule above. Through-model
permissions, custom filter bodies and ordering are unchanged. See
[M2M filter scope](usage/filtering.md#m2m-filter-scope).

## Mutations and writes

### Model field validators run on generated writes

Generated create and update (`DjangoModelMutation`, `DjangoModelType` and nested
child writes) run Django's field validation on every field the client wrote:
`field.validators` (`MinValueValidator`, `RegexValidator`, custom
`validators=[...]`), `max_length`, `blank`, `null` and `choices`, with Django's
messages. This includes `EmailField` syntax and non-negative
`PositiveIntegerField`/`PositiveSmallIntegerField` values. A value that used to
be stored, such as `""` into a `blank=False` column or a number below a
`MinValueValidator`, now returns `ok: false` with one `errors[]` entry per field
and writes nothing (a nested child error is prefixed with the nested field
name). Fields the client did not send, including defaults, are not validated, so
a create that omits a `blank=False` column stores the model default (often `""`)
without an error; an explicit `null` on a nullable column stays valid. `Model.clean()`,
`validate_unique()` and `validate_constraints()` are not run.

Because these are `ok: false` payloads rather than GraphQL execution errors, an
earlier successful sibling root field commits even with `ATOMIC_MUTATIONS=True`.
Clients that need all-or-nothing business operations must account for that.
Fix the data or relax the validators.

### Rollback on GraphQL errors, on every alias

With `ATOMIC_MUTATIONS=True`, a GraphQL execution error rolls back the default
database's writes, and `ATOMIC_REQUESTS` requests are marked for rollback on
those errors or on the mutation error flag. This now covers every database alias
inside a transaction opened for the request: each alias with `ATOMIC_REQUESTS`
is marked for rollback (in a batch, its entry savepoint is), and
`DATABASES[alias]["ATOMIC_MUTATIONS"] = True` wraps that alias in
`transaction.atomic()` for mutations. The global `ATOMIC_MUTATIONS` setting still
covers only the default alias. Rolled-back writes no longer advance the response
cache version. Structured `ok: false` data is not a GraphQL error and does not
roll back.

### Update and delete honor the output type scope

Generated `update` and `delete` now also require the target row to be visible in
the model's registered output type: if that `DjangoObjectType` overrides
`get_queryset`, a row it hides on reads can no longer be edited or deleted by id
(`postUpdate` and `postDelete` used to answer `ok: true` for a hidden row). A
hidden row answers exactly like a nonexistent id. Nested child payloads that
write fields of an existing child follow the same rule with the child's output
type; an id-only re-send of a forward current target is not re-scoped. Types
that keep the default hook add no query. If you relied on writing rows the public
type hides, widen that type's `get_queryset`, or register a broader type for the
schema that serves the write.

### Linked rows must be visible

Generated create and update check foreign-key, one-to-one and many-to-many id
links against the destination `DjangoObjectType.get_queryset` when it is
overridden. Hidden and nonexistent ids share the structured error `Invalid pk ...
object does not exist.` before anything is persisted, so the response is no
longer an existence oracle. This now covers forward `OneToOneField` links, which
were not checked. The id membership check runs one query per relation instead of
one per id. Apps that intentionally linked read-hidden rows must widen the
destination scope or change the workflow.

The existence checks send their lookups in chunks below the database's
bound-parameter limit (one query per chunk), so a very long id list no longer
fails with `too many SQL variables`, and an id beyond the database integer
range answers `does not exist` as a field error instead of a top-level error.
A key the database matches in another letter case (a case-insensitive
collation) counts as existing.

### Nested child ids that match no visible child

A nested child payload that carries an `id` no longer creates a child when the
`id` does not resolve to a visible child. A nonexistent id used to create a new
child silently while a hidden id answered `<Model> with id N does not exist.`;
both now return that error and write nothing, for reverse `ForeignKey`, reverse
`OneToOneField` and many-to-many payloads. Payloads without an `id` still create,
and children the parent already owns still update. Clients that sent an unknown
`id` together with child data to create a row must omit the `id`:

```graphql
# Before: created a child. After: error "Comment with id 999 does not exist."
postUpdate(newPost: { id: 1, comments: [{ id: 999, text: "hi" }] }) { ok }
```

Any `id` counts, including `""` and `"0"`, which used to create a child and
now return the same error. A client-chosen primary key (for example a UUID) on a
nested create is therefore an error as well: the `id` of a nested payload only
names an existing visible child, and the database assigns or defaults the key of
a new one.

The same rule covers existing rows linked by `id` through a many-to-many or a
forward foreign key: an id hidden only by the child's update host is refused
with the error a nonexistent id gets (`<Model> with id N does not exist.` for
many-to-many, `Invalid pk "N" - object does not exist.` for a forward key), where
the link used to succeed. Re-sending only the `id` of a forward relation's
current target is a no-op: the row is not saved and no signals fire.

### Adopting orphan children needs an update host

Naming the id of an existing child whose nullable reverse foreign key or
one-to-one key is null, inside a parent update, now requires a registered child
`DjangoModelType` or `DjangoModelMutation` serving update; that host's scope and
permissions apply. Without one the mutation returns a structured error and rolls
back. New children, children the parent already owns and the different-parent
guard are unchanged. Register an appropriate child update host if you adopted
orphans on purpose.

### Database error messages are generic

Unclassified Django `IntegrityError` failures in generated create/update/delete
fields (including nested writes) answer the fixed message `A database constraint
prevented this operation.` instead of raw table, column and constraint text; the
field is `null` and mapped unique/foreign-key field errors stay structured. A
blocked delete (`PROTECT`/`RESTRICT`) returns a generic GraphQL execution error
instead of Django's collector details. Clients that parsed those messages must
use the error path and your own domain errors.

### Database routers see the parent on nested create

For nested creates using the included Django backend, a database router now
receives a populated but unsaved parent instance before any related write.
It may therefore choose an alias from a supplied scalar such as `region` or
from a model default. Native parent and child saves share that alias and one
transaction; a late child failure rolls back those writes and commit callbacks.
Check routers that previously expected `instance=None` on nested create.
Direct creates without nested work and custom serializer backend create calls
retain their prior behavior. If an M2M through router explicitly selects a
different alias, native nested CREATE returns a field error before any write.
A router that chooses differently only after a generated ID triggers a second
check before linking; earlier writes on the selected alias roll back and no
foreign through write is attempted. Routers should keep the through model on
the parent's alias. Transactions across aliases and arbitrary stateful router
changes between checks and Django's link operation are not coordinated.

## Relations and output

### Review automatic forward and reverse FK output reads

An automatically published forward `ForeignKey` object field and reverse
`ForeignKey` list now apply the destination type's request-specific
`get_queryset`. A visible parent keeps its row while a hidden nullable target
resolves to `null` (`post { author { name } }` becomes `author: null` when
`AuthorType.get_queryset` hides that author); reverse lists, their windows and
`totalCount` contain only visible rows. Optimized reads stay batched through a
scoped prefetch; with `OPTIMIZE_QUERYSET=False` each parent can add a scope
query. Review destination hooks before upgrading: a client that displayed
authors, comments or other FK destinations your public type hides will stop
seeing them. Explicit relation resolvers and custom filter bodies are unchanged;
OneToOne and M2M output reads have the separate rules below. See
[automatic output relation scope](usage/types.md#relation-scope-hatch).

### Review automatic OneToOne output reads

An automatically published forward or reverse OneToOne object field now
applies the destination type's `get_queryset` for the current request. A
visible parent whose linked object is hidden still appears, but that nullable
relation resolves to `null`. A genuinely absent relation remains `null`, and
the GraphQL field's nullability does not change. Review clients that previously
expanded a hidden linked user or profile, and review the destination hooks
before upgrading. Ordinary list reads batch scoped destinations; an automatic
field on a custom-returned cached parent still checks its destination. Explicit
relation resolvers have separate rules; forward and reverse `ForeignKey` output
reads follow [the same scope](#review-automatic-forward-and-reverse-fk-output-reads),
and M2M output reads have [their own](#review-automatic-m2m-output-lists-and-counts).
See [automatic output relation scope](usage/types.md#relation-scope-hatch).

### Review automatic M2M output lists and counts

An automatically published declared or reverse M2M field now applies the
destination type's request-specific `get_queryset` before constructing its
`results` and `totalCount`. For a visible post linked to one visible and one
hidden tag, `tags { totalCount results { label } }` returns only the visible
tag and a count of one. A hidden-only relation returns an empty result and a
zero count; the parent remains visible. Pagination slices this visible set,
not the original links. Review clients that previously displayed hidden
members or relied on their counts. Explicit relation resolvers and
through-model access control are unchanged. See
[automatic output relation scope](usage/types.md#relation-scope-hatch).

### Distinguish malformed IDs from missing objects

Model-backed single-object lookups now distinguish an ID the model cannot
convert from a well-formed ID that finds no visible row. The malformed case
returns a GraphQL field error with `extensions.code` set to `INVALID_ID` and a
safe expected-format message: `Invalid ID: expected an integer.`, `Invalid ID:
expected a UUID.`, or the generic `The ID format is invalid.` for other
primary keys. The nullable field is `null` and a non-null parent follows
ordinary GraphQL error bubbling. Missing or scoped-out rows still return
`null` without an error. A text primary key such as `abc` is not rejected
merely because it is not numeric.

Clients that previously interpreted every `null` as "not found" should now
check the GraphQL `errors` array and `extensions.code`. The input value and
Django conversion details are not included in the public message. This does
not change schema fields, argument types, or valid-ID coercion.


### GenericForeignKey targets are scoped

A flat `GenericForeignKeyType` target whose registered output type hides the row
now resolves to `null` in every schema (before, a schema without
`PERMISSION_SCOPED_SCHEMA` still returned its `appLabel`, `modelName` and `id`).
In permission-pruned schemas the whole flat target is `null` when the target
model's read permission is absent or its row hook excludes the row, and the
schema and response caches include all grants for such schemas. Typed
`Meta.unions` targets apply the member type's `get_queryset` the same way: a
hidden target resolves to `null`, like a missing one. Targets of unregistered
models and types that keep the default hook are unchanged. Optimized and list
reads scope targets in one batched `GenericPrefetch`, so query counts do not grow
with the number of owners. Only the `get_queryset` hooks of target types some
owner on the page points to run, so a hook that raises for anonymous users no
longer nulls an unrelated list; a hook that raises for a present target still
fails the field. Grant target read permission and review target row scopes if you
relied on source-only permission.

## Directives

### Move transformation directives from fragments to fields

The library's transformation directives now declare only the GraphQL `FIELD`
location. A query placing `@uppercase` or another library transform on a
fragment spread or inline fragment fails validation before resolver execution;
it no longer succeeds while silently leaving the value unchanged. Move the
directive to each selected field that should be transformed:

```graphql
# Before: invalid fragment-spread placement.
query { ...Words @uppercase }
fragment Words on Query { text }
```

```graphql
# After: valid field placement inside the same fragment.
query { ...Words }
fragment Words on Query { text @uppercase }
```

Fields inside inline fragments work the same way. Standard `@skip` and
`@include` keep their fragment and field locations and behavior. This change
does not make transformations inherit from a fragment or restrict locations
declared by third-party raw GraphQL directives.

### Handle non-finite values before applying `@floor`

`@floor` now reports a GraphQL field error for `NaN`, positive infinity, or
negative infinity, including numeric strings such as `"nan"` and `"inf"`.
Nullable fields resolve to `null` with the error path; non-null fields follow
ordinary GraphQL bubbling. Previously, Python's integer conversion error
surfaced instead. If non-finite values are possible, handle them in the
resolver before selecting `@floor`, or allow the client to handle the field
error. `None`, finite values (including negative zero), malformed-number
errors, and the behavior of `@ceil`, `@round`, `@abs`, `@truncate`, and
`@title_case` are unchanged. This is a runtime error-message policy, not a
schema or directive-location change.

### Review null values under numeric formatting directives

`@number` and `@currency` now preserve a resolver's `None` as GraphQL `null`
instead of rendering `"0.00"` or `"$0.00"` on otherwise formatted fields.
If the field is non-null, GraphQL reports the ordinary nullability error and
bubbles to the nearest nullable parent. Review clients that treated a
formatted zero as evidence of a missing value. Return an explicit zero from
the resolver when zero is intended, or use `@default` deliberately where a
fallback is appropriate. Existing format validation and width/precision caps
still apply; `Int` and `Float` fields continue to pass through raw values.

### Review case-conversion directive output values

`@camel_case`, `@snake_case`, and `@kebab_case` now recognize words separated
by spaces, underscores or hyphens, camelCase/PascalCase boundaries, and
acronym blocks. For example, `orderTotal` now yields `order_total` with
`@snake_case` and `order-total` with `@kebab_case`; previously both collapsed
to `ordertotal`. Likewise, `order_total @kebab_case` changes from
`order_-total` to `order-total`, while `HTTPServer` converts to `httpServer`,
`http_server`, or `http-server` in directive order. Review clients that compare
these formatted response values. Field and argument names in the schema,
other directives, shared conversion helpers, and handling of other
punctuation or characters are unchanged.

### Review aware values formatted with absolute @date formats

The `@date` directive now displays originally aware Python `datetime` values
and text with an explicit numeric offset or `Z` in Django's active timezone
for `default`, `iso`, `js`/`javascript`, and custom absolute formats. It
preserves the instant but may change the displayed calendar date. For example,
with `America/New_York` active, `"2026-01-01T03:30:00+02:00"` now displays
as `"2025-12-31T20:30:00"` under `@date(format: "iso")`, rather than
`"2026-01-01T03:30:00"`.
Clock-adjacent zero offsets are included: in the same active zone,
`"2026-01-10T00:30:00+00:00"` and `"2026-01-10T00:30:00+0000"` now
display as `"2026-01-09T19:30:00"`, matching the equivalent `Z` value.

If clients relied on the input offset's wall clock, review their expectations
or choose an explicit display zone in the resolver. The `iso` output still
omits offset and microseconds; it is not an offset-bearing timestamp. Explicit
offset/Z text retains its prior relative behavior. Naive Python datetimes,
Python dates, other input kinds, null handling and directive arguments remain
unchanged.

### Review timezone-less text in absolute and relative @date formats

Accepted text with no timezone information now means its **written wall
clock in Django's active timezone**, regardless of `USE_TZ`. This does not
convert an assumed UTC instant. With `TIME_ZONE="UTC"` and `Europe/Madrid`
active in July, `"2026-07-10 14:30"` gives `"14:30 +0200"` for
`@date(format: "HH:mm ZZ")`, rather than `"14:30 +0000"`. The same active-zone
interpretation applies to `"time ago"` and `"time ago 2d"`, so their relative
wording may change. Audit callers that previously relied on the default
timezone's interpretation; supply an explicit offset when the instant is
known. Named UTC/GMT text and unknown timezone names retain their existing
handling and warnings. A time-only string still takes its missing date from
the parser's current-date default, even when the active zone has crossed
midnight; no new daylight-saving gap/overlap policy was added.

### Review text values formatted with @date

The `@date` directive now fills omitted time components of accepted text
values with zeros, rather than the server's current hour, minute, second, or
microsecond. For example, a resolver returning `"2026-01-10"` with
`@date(format: "iso")` previously produced a value such as
`"2026-01-10T08:15:21"` when the server clock read 08:15:21; it now produces
`"2026-01-10T00:00:00"`. A partial value `"2026-01-10 14:30"` now produces
`"2026-01-10T14:30:00"` instead of inheriting the current seconds.

Check clients that relied on an implicit server time. Supply the intended
time explicitly in the resolver value instead. A time-only string still uses
the current date; explicit time components and null behavior are unchanged.
The aware-value timezone conversion above is a separate change. The `iso`
output format itself is unchanged and does not display offsets or microseconds.

### Review nullable fields formatted with @date

The `@date` directive now passes a resolver's `None` through as GraphQL
`null`. Previously, a nullable Date/DateTime field could expose
`"INVALID FORMAT STRING"` instead, while a String field could expose the
wrapper's text. For example, a nullable `publishedAt` queried as
`publishedAt @date(format: "YYYY-MM-DD")` now returns
`"publishedAt": null` when the resolver has no date.

If the field is declared non-null, the same resolver result now triggers the
normal GraphQL nullability error and bubbles null to the nearest nullable
parent. A non-null root field can make `data` null, so clients should check
`errors` and the field's SDL nullability. The null change does not alter SDL or
other directives; the separate text-time default change is described above.

### Output caps for directives

`@replace` results are limited to 1,000,000 Unicode characters by default
(`MAX_REPLACE_OUTPUT_LENGTH`); an over-limit result, even one with no
replacement, is a GraphQL field error, and a result at the cap stays valid. New
`MAX_DIRECTIVE_OUTPUT_TOTAL` (default 10,000,000 characters per HTTP request,
`None` disables) charges every directive for the text it adds; once spent,
further directive uses become field errors. The budget is shared by every item
of a batch (the GraphQL view binds one counter to the request), restarts for
each subscription event, and is per execution for anything the view does not run
(a direct `execute` call, a transport) or a context that cannot carry the
counter (`None`, an immutable mapping, `__slots__`). A `get_context` that
returns a dict or another mutable mapping carries the counter under the private
key `_graphex_request_budget`, so batch items still share it. Many aliases and rows each under the
per-field cap can no longer produce hundreds of megabytes. Raise either setting
or set it to `None` if you legitimately transform very large text. The opt-in
`COST_DIRECTIVE` setting (default `0`) adds cost per custom directive use, so
aliases times directives counts toward `MAX_QUERY_COST`; the default does not
change existing costs.

### Numeric directives on Decimal and BigInt

`@round`, `@floor`, `@ceil` and `@abs` compute on the exact `Decimal` or `int`
instead of converting to `float` (`@round` on a Decimal used to return the
binary expansion; `@abs` on a BigInt returned null with a coercion error).
`@round` rounds half to even and quantizes to exactly the requested precision
(`0.0004` with `precision: 2` is `0.00`); with a precision of zero or below it
returns an integral value (`0.0004` is `0`). A value already at or beyond the
requested scale is unchanged. A value whose magnitude reaches the Decimal
scalar's plain-notation bound (an exponent past 1,000, such as `1E+100000`) is
already integral, so `@floor`, `@ceil` and `@round` return it unchanged and the
scalar keeps its scientific form, in constant time. `@number` and `@currency`
return the raw value on these scalars, as they already do on `Int` and `Float`.
Review clients that compared the old formatted values.

## HTTP, limits and execution

### Cost is checked before resolving, and pageSize is costed

A selected operation is rejected before resolution when its real,
GraphQL-coerced variables or defaults put it over `MAX_QUERY_COST`, including on
document-validation cache hits. A variable page size that passed the static
fallback estimate may now return HTTP 400 `QUERY_TOO_COMPLEX`. Cost analysis
also reads the page-size argument by its wire name: argument names are compared
in snake_case form, so the camelCase `pageSize` that the page paginator exposes
matches `COST_PAGINATION_ARGS` entry `page_size` (a custom `perPage` is matched
by listing `per_page` or `perPage`), and `items(pageSize: 5000)` is no longer
costed at the default size. `analyze_cost()` called directly raises
`GraphQLError` for a cyclic named-fragment document instead of returning a
truncated cost; validate first or catch the error. Set `MAX_PAGE_SIZE` for
unbounded lists.

### Structural depth ceiling

`DepthLimitValidationRule` enforces a hard ceiling of 100 nested object levels
even when `MAX_QUERY_DEPTH` is unset or larger, because Python's stack cannot
execute deeper documents. Deeper documents, and documents that exceed
graphql-core's own parser or validator limits (about 250 nested selection sets,
several hundred chained fragments), get HTTP 400 `QUERY_TOO_DEEP` instead of an
internal error or HTTP 500, on the HTTP view and the subscription transports.
Variables nested so deeply that coercing them exhausts the stack get the same
400 `QUERY_TOO_DEEP` on the HTTP view.
Documents within the ceiling are unaffected.

### Batches answer every item

A batch response has exactly one entry per request entry, in order, and later
items always run. The HTTP status is the highest entry status. With
`ATOMIC_REQUESTS`, each item runs in its own savepoint on every connection that
wraps the request, so an item that errors rolls back only its own writes and
earlier and later items commit; before, one failed item could mark the whole
request for rollback while the first item still answered `ok: true`. This
replaces the intermediate behavior that stopped later operations after an HTTP
400 item. A non-batched request keeps its request-level rollback. See
[Batch endpoints](usage/views.md#batch-endpoints).

### Document caches skip very large documents

The parse and validation caches no longer retain documents longer than the new
`DOCUMENT_CACHE_MAX_QUERY_LENGTH` (default 65536 characters; `None` removes the
bound; a negative integer is rejected). Longer documents, and documents whose
parsed AST has more than an eighth of that many tokens, are parsed and
validated on every request. Each cache also retains at most that many AST
tokens in total (about 40 MB of ASTs per cache at the default). The validation
cache keys on a digest of the query text, not the text. The response cache stores only HTTP
200 data responses without errors; partial-data errors, validation failures and
other non-200 responses re-execute on the next request, and previously stored
failed entries are ignored. The default response-cache key frames its body and
GET components before hashing, so existing cached responses cold-miss once.

### Optimizer work budget

The new `OPTIMIZER_WORK_BUDGET` setting (default 2000, `None` disables) caps the
selection contexts each queryset-optimizer walker expands per operation
execution, so fragments reached through many distinct relation paths cannot
cost seconds of CPU. The budget is shared by every root field (alias) of one
execution; unlike the directive output budget it is not shared across the items
of a batch, because each item plans its own selection. Once any
walker spends it, the root field being planned is resolved without the
optimizer plan, exactly as with `OPTIMIZE_QUERYSET = False`, and so are the
request's later root fields: the data and the scoping of `get_queryset`
relations are identical, only the query count can grow. A DEBUG log record
names the walker. Raise it if a large legitimate document shows more queries
than before.

### Custom scalar errors are client errors

Errors raised by a custom scalar's `parse_value`/`parse_literal` (`ValueError`
or `TypeError`) while parsing, validating or coercing variables are classified
as validation errors in production: graphql-core's message is kept without the
raw exception text (unless `DEBUG`), the response is a client error, and there is
no ERROR log. Before, they answered HTTP 400 with `INTERNAL_SERVER_ERROR` and
logged a traceback. Errors raised during execution keep their masking and log,
and so does any other exception type a scalar raises while coercing (for
example a database error): only `ValueError`, `TypeError` and `GraphQLError`
mean invalid input. A masked internal error raised outside field execution (a
failing hook such as `get_root_value`) now answers HTTP 500 instead of 400.
With `DEBUG=False`, unexpected resolver exceptions on the built-in HTTP views
answer with `DATA_ACCESS_ERROR` or `INTERNAL_SERVER_ERROR` and an opaque
`errorId` correlated with server logs; clients must not rely on raw exception
text.

### Subscription errors are masked like HTTP errors

With `DEBUG=False`, the SSE and WebSocket transports now use the HTTP view's
masking. An unexpected exception raised by a `subscribe` resolver or by an event
resolver (a `RuntimeError`, a `FieldError`, a `DatabaseError`) is sent as
`An internal error occurred.` (`INTERNAL_SERVER_ERROR`) or `Unable to complete
the data operation.` (`DATA_ACCESS_ERROR`), keeps `locations` and `path`, carries
an opaque `extensions.errorId`, and logs one ERROR record with the traceback on
`django_graphex.internal_errors`. Before, the raw exception text reached the
client. Deliberate `GraphQLError`, validation, coercion and other client-input
errors keep their messages, and `DEBUG=True` keeps the raw text. Raise
`GraphQLError` for a message that is safe to show. A WebSocket frame that cannot
be decoded still closes with `4400` but is no longer logged as an ERROR with a
traceback.

### Malformed requests and server faults

A `query` that is not a string (`{"query": 123}`) answers HTTP 400 `Must provide
query string.`, and `variables` that are not a JSON object (`"variables": "[1]"`,
`"variables": []`) answer HTTP 400 `Variables must be a JSON object.`, on GET,
JSON, form and batch requests (a batch item fails alone, the others run). They
used to answer 400 `INTERNAL_SERVER_ERROR` with a traceback in the server log.
Conversely, a masked internal error that carries no field path, such as a
failing `get_context`/`get_root_value` hook, now answers HTTP 500 instead of
400. Syntax, validation and variable-coercion errors stay 400, and field errors
stay inside HTTP 200. Client code that retried or alerted on `INTERNAL_SERVER_ERROR`
400s for malformed bodies should treat them as ordinary client errors.

### Subscriptions are rejected over HTTP

A subscription operation sent to the HTTP views (`GraphQLView`, `BaseGraphQLView`
and `AuthenticatedGraphQLView`) answers HTTP 400 with the error `Subscriptions
are not supported over HTTP; use the WebSocket or SSE transport.` and
`extensions.code` `SUBSCRIPTION_NOT_SUPPORTED`. Before, the response was HTTP 200
with `{"data": {"field": null}}` and no hint. Only the operation selected by
`operationName` is judged, and each subscription item of a batch gets its own
error entry. Point subscription clients at the WebSocket or SSE endpoint; see
[Subscriptions](usage/subscriptions.md).

### Synchronous views reject async results

Unsupported async resolver, middleware and executor results on the synchronous
HTTP views now produce a controlled HTTP 500 GraphQL JSON error and close the
unstarted coroutines, instead of an HTML 500 with unawaited-coroutine warnings.
Use synchronous resolvers and middleware over HTTP.

### Request body and upload limits

`MAX_REQUEST_BODY_SIZE` is enforced before Django's CSRF check and before the
cache-active view parses a document, so an oversized multipart POST is refused
with HTTP 413 unparsed even when the client holds a `csrftoken` cookie. A base64
upload of exactly `MAX_UPLOAD_SIZE` bytes is accepted, as it already was over
multipart. If `BaseGraphQLView` sits behind Django's `CsrfViewMiddleware`, the
middleware may still parse a multipart body before the view runs: place a proxy
or body-size middleware ahead of CSRF.

### Numbers in JSON output

The raw `JSON` scalar no longer emits `NaN` or `Infinity` in output: a resolver or
`JSONField` value that is or contains a non-finite float, at any depth, is a
field error (`JSON cannot represent non-finite numbers`) with the field `null`.
Every container the encoder emits is checked (mappings including `OrderedDict`,
tuples, lists, sets), not only `dict` and `list`. Raw `JSON` inputs reject
non-finite numbers too, including nested variable values, and an optional
variable omitted inside a list literal keeps the positions of the other
elements. Finite values and `JSONString` are unchanged. With `CLEAN_RESPONSE=True`, numeric
zero and `false` are preserved in ordinary responses (they used to be dropped);
nulls, empty strings and empty containers are still removed.

### Negative operational limits

`MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE`, and `DOCUMENT_CACHE_MAXSIZE` now
raise `ImproperlyConfigured` when read with a negative integer. Correct a
negative configuration to a meaningful nonnegative limit, or use `None` for
the setting's existing uncapped behavior. Zero retains its distinct meaning:
no batch operations, no request-body bytes, or disabled document caches,
respectively. Defaults and positive values are unchanged. Validation occurs
when the setting is read; it is not a new startup system check or a general
type validator. The settings added in 4.1 are stricter about type:
`DOCUMENT_CACHE_MAX_QUERY_LENGTH`, `OPTIMIZER_WORK_BUDGET` and
`MAX_DIRECTIVE_OUTPUT_TOTAL` raise `ImproperlyConfigured` unless the value is an
integer or `None` (`"65536"` and `True` are rejected), and `COST_DIRECTIVE`
raises for a negative, fractional, boolean or non-number value instead of being
truncated.

### Multipart upload size limit

If you configure `MAX_UPLOAD_SIZE`, it now limits **each received multipart
file**, including unused or unmapped parts and repeated parts under one name.
A file at the limit is accepted; a larger file receives a JSON HTTP 413 before
resolver execution. This may reject requests that previously ignored an
oversized extra part. Remove unwanted parts or raise the limit deliberately.
`None` leaves multipart files without this per-file cap, while
`MAX_REQUEST_BODY_SIZE` still controls the whole body independently.

This does not change the `Base64FileInput` requirement for a limit or its
per-call override. The multipart check occurs after Django parses the upload;
configure server-level ingress limits separately. Malformed batch requests
retain their existing HTTP 400 response before this per-file check.

### Execution errors return HTTP 200

The enhanced `GraphQLView` now returns HTTP 200 with `data: null` and `errors`
when a field execution error bubbles through a non-null root field. Previously
that case returned HTTP 400 with no `data` member; `BaseGraphQLView` already
returned the execution envelope. Update clients that treated every HTTP 400 as
an execution failure or assumed HTTP 200 implies no GraphQL errors. Syntax,
validation, and variable-coercion failures still return HTTP 400 without
`data`. Errored responses remain uncached. For batches, an execution-error
entry has status 200 and retains its null data while a validation-result entry
has status 400; neither stops later entries, and neither does a transport-level
HTTP 400. See
[production execution errors](usage/views.md#production-execution-errors).

### Disabled introspection needs the middleware

If your deployment relies on disabled schema introspection, explicitly add
`django_graphex.security.DisableIntrospectionMiddleware` to
`DJANGO_GRAPHEX["MIDDLEWARE"]`. The default `ALLOW_INTROSPECTION=False` does not
enforce a block while the default GraphQL middleware chain is empty. See the
[security configuration](usage/security.md#disable-introspection) for a complete
example; this clarification does not install middleware automatically or change
the default setting.

### Clean responses keep introspection nulls

When `CLEAN_RESPONSE=True`, selected introspection operations expressed with
root inline or named fragments now preserve schema `null` and empty-list
values, just like direct `__schema` and `__type` roots. Clients that previously
saw those values omitted should accept the full introspection response. Mixed
ordinary root fields are still cleaned, and the default
`CLEAN_RESPONSE=False` is unchanged. See [response cleaning](usage/security.md#ast-based-introspection-detection-clean_response).

### View constructor checks survive python -O

The built-in HTTP views now reject a schema without `graphql_schema` and the
combination `graphiql=True, batch=True` even under `python -O`. They retain
their existing `AssertionError` type and messages; only these two constructor
checks changed. The check occurs when a view instance is constructed, not
necessarily when Django evaluates `as_view()`.

## Subscriptions

### WebSocket subprotocol is required

A subscription WebSocket handshake is rejected before acceptance unless the
client offers the exact `graphql-transport-ws` subprotocol (it may offer it among
alternatives). The server logs an actionable diagnostic; pre-accept rejection is
normally HTTP 403 on the wire, so browsers may show only a generic connection
failure. Configure the client's subprotocol offer, for example
`new WebSocket(url, "graphql-transport-ws")`. Authentication, SSE and HTTP are
unchanged.

### Best-effort notifications and exact filters

Automatic model-signal subscription notifications are best-effort: an ordinary
notification error logs metadata only and drops the event without failing a
successful save or generated mutation. Explicit manual broadcasts stay strict.
Handle delivery explicitly if you depended on automatic delivery exceptions.
Subscription `exact` filters on `Float` and `Decimal` fields compare numeric
snapshots by value like a database column: an integer snapshot matches an equal
float or Decimal, a float snapshot matches `Decimal("1.50")`, and
`2**53 + 1` matches `float(2**53)` (when a float is on either side the other
operand is rounded to the nearest float first). Booleans, NaN, infinities and
integers beyond the float range still never match. Also, a `DecimalRangeField` bound or `DurationField`
selected on an event type is delivered as a `Float` (total seconds for
durations) instead of failing on every read. That last change is a fix, not a
behavior change: those fields raised on every read before, so no working client
depends on the old result, and the SDL is unchanged.

### subscription_scope intersects the client filter

`subscription_scope` used to replace a client `filter` on the same key. It now
intersects with it: an event is delivered only when it matches both. A client
asking for `filter: {status: {exact: DRAFT}}` under a scope of `PUBLISHED` used to
receive the published rows it had filtered out; it now receives nothing (a value
that contradicts the scope on the same key joins no group). Subscriptions without
a scope are unchanged. See [Subscriptions](usage/subscriptions.md).

### Fan-out isolation and SSE leases

Automatic fan-out on the synchronous path (WSGI, Celery, management commands)
sends to each channel-layer group independently, like the ASGI path: one failing
group no longer prevents the others from receiving the event. The drop log line
now ends with `exception=<qualified chain>` (the dotted class names of the
exception and its causes, for example `redis.exceptions.ConnectionError`) instead
of only the bare class name; it still never contains exception messages, group
names or event data, so update log alerts that matched the old text.

With the Redis-backed per-account SSE stream cap, streams of one process share a
single Redis client per URL, with a health check on idle connections and TCP
keepalive, and lease admission retries once after a connection error, so a stale
pooled connection no longer answers the first stream with HTTP 503. A failed
lease renewal, including the first one, is retried after five seconds while the
last confirmed renewal is less than 40 seconds old (45-second lease minus a
five-second margin); a renewal Redis answers with "not owned", or errors lasting
longer than that, still end the stream.

## New settings

| Setting | Default | Effect |
| --- | --- | --- |
| `DEFAULT_PAGE_SIZE` | `100` (was `None`) | Rows returned when the client omits a size. |
| `DOCUMENT_CACHE_MAX_QUERY_LENGTH` | `65536` | Longest document kept in the parse and validation caches; `None` removes the bound. |
| `OPTIMIZER_WORK_BUDGET` | `2000` | Selection contexts each optimizer walker expands per operation execution (shared by all root fields; each batch item has its own); `None` disables. |
| `MAX_DIRECTIVE_OUTPUT_TOTAL` | `10000000` | Characters directives may add per HTTP request (shared by all batch items; each subscription event has its own); `None` disables. |
| `MAX_REPLACE_OUTPUT_LENGTH` | `1000000` | Characters per `@replace` result; `None` restores uncapped behavior. |
| `COST_DIRECTIVE` | `0` | Cost added per custom directive use. |
