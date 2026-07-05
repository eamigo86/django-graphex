# Upgrade Guide: 1.x → 2.0

`django-graphex` 2.0 **removes the legacy graphene backend entirely**. The library
is now built on **graphql-core + Pydantic** alone — graphene is no longer a
dependency and is never imported, even on a full build with mutations,
subscriptions and pagination.

This guide walks through every breaking change with copy-pasteable
before/after snippets, plus an automated codemod for the mechanical parts.

> **New to the library, coming from `graphene-django-extras`?** That's a
> different migration — see the [Migration Guide](migration.md). This page is
> only for projects already on `django-graphex` 1.x.

!!! tip "Run the codemod first"

    A migration helper ships with the repo:

    ```bash
    # Report every graphene construct that needs porting (read-only):
    python scripts/migrate_2_0.py path/to/your/project/

    # Apply the one safe, mechanical rewrite (GRAPHENE -> DJANGO_GRAPHEX settings):
    python scripts/migrate_2_0.py --apply path/to/your/project/
    ```

    It performs two mechanical rewrites automatically:

    1. Folds the `GRAPHENE` settings namespace into `DJANGO_GRAPHEX`.
    2. Repoints bundled-middleware dotted paths that were removed from the
       package root, e.g.
       `"django_graphex.GraphQLDirectiveMiddleware"` →
       `"django_graphex.middleware.GraphQLDirectiveMiddleware"` and the
       security middlewares → `"django_graphex.security.<Name>"` (v2.0 dropped
       the flat root re-exports, so the old dotted path no longer resolves).

    It also **flags** (with porting guidance) the graphene constructs you must
    port by hand. It never imports graphene, so it runs fine after the 2.0
    install.

## At a glance

| # | What changed | Effort |
|---|--------------|--------|
| 1 | graphene backend removed; `GDX_BACKEND` env var gone | none — automatic |
| 2 | `GRAPHENE` settings namespace → `DJANGO_GRAPHEX` (single namespace) | codemod `--apply` |
| 3 | `graphene.ObjectType` roots → `from django_graphex.core import ObjectType` | manual |
| 4 | `graphene.Schema(...)` → `DjangoGraphQLSchema(...)` | manual |
| 5 | graphene field descriptors → `field(GraphQLString)` | manual |
| 6 | `graphene.Argument(...)` in `class args` → `GraphQLArgument(...)` in `class Arguments` | manual |
| 7 | `choices` fields now render as a GraphQL **enum** (output **and** input) | wire-format — review clients |
| 8 | `InputField` and the 12 `*InputField` twins removed → one unified `Field` | manual |
| 9 | model `JSONField` / `JSONField()` now carry **raw JSON** (SDL scalar `JSON`), not a JSON string | wire-format — review clients |
| 10 | `DjangoUnionType` `Meta.gfk_unions` → `Meta.unions` | manual (guard raises) |
| 11 | cursor format is now composite (`value` + `pk`) — stored v1/beta cursors are invalid | re-fetch from page 1 |
| 12 | output camelCase digit parity: `phone_1` → `phone1` (was `phone_1`) | wire-format — review clients |
| 13 | filter input SDL name `<Model>Filterinput` → `<Model>FilterInput` | wire-format — review clients |
| 14 | version `1.3.0` → `2.0.0` | bump your pin |

---

## 1. The graphene backend is gone

**Why.** 1.x shipped two backends — a legacy graphene path and the native
graphql-core path — selected by the `GDX_BACKEND` environment variable. 2.0
deletes the graphene backend and the switch. The native path is the only path.

**What to do.** Remove any `GDX_BACKEND` setting; it is no longer read. Uninstall
graphene from your environment — `django-graphex` no longer requires it.

```diff
- GDX_BACKEND=graphene   # gone — there is no graphene backend in 2.0
```

```bash
pip uninstall graphene graphene-django   # no longer needed by django-graphex
```

---

## 2. `GRAPHENE` settings namespace → `DJANGO_GRAPHEX` (single namespace)

**Why.** The schema/middleware settings (`SCHEMA`, `MIDDLEWARE`,
`SUBSCRIPTION_PATH`, …) used to be read from the legacy `GRAPHENE` Django-setting
namespace (a graphene-django convention). 2.0 **unifies** all django-graphex
configuration into the single `DJANGO_GRAPHEX` dict — the schema/middleware keys
are merged in alongside this package's own settings (pagination, caching, query
limits, …). The `GRAPHENE` namespace is no longer consulted, and there is no
separate schema-settings namespace anymore.

!!! note "One namespace now"

    Earlier 2.0 pre-releases briefly used a separate `GRAPHEX` dict for the
    schema/middleware keys. The final 2.0 release drops that second dict: every
    setting lives in `DJANGO_GRAPHEX`. There are no key collisions, so merging is
    mechanical.

**Before**

```python
# settings.py
GRAPHENE = {
    "SCHEMA": "myapp.schema.schema",
    "MIDDLEWARE": ["django_graphex.middleware.GraphQLDirectiveMiddleware"],
}

DJANGO_GRAPHEX = {
    "DEFAULT_PAGE_SIZE": 20,
}
```

**After**

```python
# settings.py
DJANGO_GRAPHEX = {
    # schema/middleware keys merged in from the old GRAPHENE namespace
    "SCHEMA": "myapp.schema.schema",
    "MIDDLEWARE": ["django_graphex.middleware.GraphQLDirectiveMiddleware"],
    # this package's own settings (unchanged)
    "DEFAULT_PAGE_SIZE": 20,
}
```

The codemod's `--apply` performs exactly this fold: it merges the `GRAPHENE`
keys into an existing `DJANGO_GRAPHEX` dict (or renames `GRAPHENE` to
`DJANGO_GRAPHEX` when there is no target dict yet).

!!! note "`SCHEMA_OUTPUT` / `SCHEMA_INDENT` are back — inside `DJANGO_GRAPHEX`"

    graphene-django read `SCHEMA_OUTPUT` and `SCHEMA_INDENT` under its
    `GRAPHENE` namespace for the `graphql_schema` command. django-graphex ships
    [the same `graphql_schema` command](usage/settings.md#exporting-the-schema)
    (a drop-in), and those two keys now live inside `DJANGO_GRAPHEX` like every
    other setting. Move them there (the codemod folds them in automatically) and
    your existing `manage.py graphql_schema` export workflow keeps working — the
    introspection JSON is wrapped as `{"data": ...}`, the same shape as before.

---

## 3. `graphene.ObjectType` roots → native `ObjectType`

**Why.** Schema roots no longer subclass `graphene.ObjectType`. Use the native
root base exported from `django_graphex`.

**Before**

```python
import graphene
from django_graphex.fields import DjangoListObjectField


class Query(graphene.ObjectType):
    users = DjangoListObjectField(UserListType)
```

**After**

```python
from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField


class Query(ObjectType):
    users = DjangoListObjectField(UserListType)
```

The `Django*Field` query fields (`DjangoObjectField`, `DjangoListObjectField`,
`DjangoFilterListField`, …) are unchanged — they already worked on native roots.

---

## 4. `graphene.Schema(...)` → `DjangoGraphQLSchema(...)`

**Why.** The schema object is built with `DjangoGraphQLSchema` (already the public
schema class in 1.x), not `graphene.Schema`.

**Before**

```python
import graphene

schema = graphene.Schema(query=Query, mutation=Mutation)
```

**After**

```python
from django_graphex.schema import DjangoGraphQLSchema

schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
```

`directives=all_directives` and the other keyword arguments carry over unchanged:

```python
from django_graphex.directives import all_directives
from django_graphex.schema import DjangoGraphQLSchema

schema = DjangoGraphQLSchema(query=Query, mutation=Mutation, directives=all_directives)
```

---

## 5. graphene field descriptors → native `field(...)`

**Why.** Hand-declared (non-model) fields on a root/type body used graphene
descriptors (`graphene.String()`, `graphene.Field(...)`). 2.0 uses the
graphene-free `field()` helper carrying a graphql-core type verbatim.

**Before**

```python
import graphene


class Query(graphene.ObjectType):
    server_time = graphene.String(description="ISO timestamp")
    me = graphene.Field(UserType)
    tags = graphene.List(graphene.String)
```

**After**

```python
from django_graphex.core import ObjectType, field
from graphql import GraphQLList, GraphQLString


class Query(ObjectType):
    server_time = field(GraphQLString, description="ISO timestamp")
    me = field(UserType)
    tags = field(GraphQLList(GraphQLString))
```

`field()` accepts a graphql-core type (`GraphQLString`, `GraphQLList`,
`GraphQLNonNull`, …) or a `django-graphex` output type class. Use `name=` to pin
an explicit wire name when the Python attribute needs a trailing underscore:

```python
date_ = field(GdxDate, name="date")   # exposes the field as `date`
```

---

## 6. `graphene.Argument(...)` in `class args` → `GraphQLArgument(...)` in `class Arguments`

**Why.** Mutation arguments are declared with the native graphql-core
`GraphQLArgument`. This is a **clean break** with two parts: the inner
argument-container class is **renamed** from `class args` to `class Arguments`,
and its values must be native — a non-native value (such as the old
`graphene.Argument`) left in a `Mutation` `class Arguments` now raises
`TypeError` loudly, it is never silently dropped.

**Before**

```python
import graphene
from django_graphex.mutation import DjangoModelMutation


class CreateUser(graphene.Mutation):
    class args:
        name = graphene.Argument(graphene.String, required=True)

    ok = graphene.Boolean()

    def mutate(root, info, name):
        ...
```

**After**

```python
from django_graphex.core import Mutation, field
from graphql import GraphQLArgument, GraphQLBoolean, GraphQLNonNull, GraphQLString


class CreateUser(Mutation):
    class Arguments:
        name = GraphQLArgument(GraphQLNonNull(GraphQLString))

    ok = field(GraphQLBoolean)

    @staticmethod
    def mutate(root, info, name):
        ...
```

!!! tip "Bare types are auto-wrapped"

    A bare graphql-core type in `class Arguments` is accepted and wrapped in a
    `GraphQLArgument` for you:

    ```python
    class Arguments:
        age = GraphQLInt          # equivalent to GraphQLArgument(GraphQLInt)
    ```

!!! note "Model mutations are unaffected"

    If you use `DjangoModelMutation` (the model-first create/update/delete
    mutation), the arguments are derived from the model — there is nothing to
    port here. Only hand-declared `class Arguments` (formerly `class args`)
    using `graphene.Argument` need the change above.

---

## 7. `choices` fields now render as a GraphQL enum

**Why.** A model field with `choices` is now exposed as a real
`GraphQLEnumType` on **both** the output type and the filter/input types. In
earlier native builds a choices field could render as a plain `String`.

**Wire-format impact.** This is a **schema change** your clients can observe:

```graphql
# Before (plain scalar)
status: String

# After (enum)
status: CategoryStatusEnum
enum CategoryStatusEnum { ACTIVE ARCHIVED }
```

**What to do.** Review GraphQL clients/queries that send or read choices values
as raw strings. Enum values are the uppercased choice keys; filtering and input
accept the same enum. No Python code change is required — the enum is built
automatically from the model's `choices`.

---

## 8. `InputField` / `*InputField` twins removed — one unified `Field`

**Why.** 1.x (and the 2.0 pre-releases) shipped two parallel descriptor
families: `Field` for output positions and `InputField` (plus 12 typed
`*InputField` twins — `IntInputField`, `CharInputField`, …) for arguments. 2.0
**unifies** them: the single `Field` (and 11 typed shortcuts — `IntField`,
`CharField`, `FloatField`, `BooleanField`, `IDField`, `DateField`,
`DateTimeField`, `TimeField`, `DecimalField`, `UUIDField`, `JSONField`) works in
**both** an `ObjectType` / `Mutation` payload body **and** a `class Arguments`
body. `InputField` and every `*InputField` twin are **removed** — there is no
alias.

The direction is inferred from the **declaration site**, not the descriptor:
`resolver=` / `source=` / `args=` are **output-only** (they raise a clear
`TypeError` if left on a field used in an argument position), and `default=` is
**input-only** (it raises a `TypeError` at output compile time).

**Before**

```python
from django_graphex.core import Mutation, InputField, IntInputField, field
from graphql import GraphQLBoolean


class CreateUser(Mutation):
    class Arguments:
        data = InputField(UserInput, required=True)
        age = IntInputField(default=18)

    ok = field(GraphQLBoolean)

    @staticmethod
    def mutate(root, info, data, age):
        ...
```

**After**

```python
from django_graphex.core import Mutation, Field, IntField, field
from graphql import GraphQLBoolean


class CreateUser(Mutation):
    class Arguments:
        data = Field(UserInput, required=True)   # same Field, input position
        age = IntField(default=18)               # same shortcut, input position

    ok = field(GraphQLBoolean)

    @staticmethod
    def mutate(root, info, data, age):
        ...
```

The mechanical port is a search-and-replace: drop the `Input` infix
(`InputField` → `Field`, `IntInputField` → `IntField`,
`CharInputField` → `CharField`, and so on for all 12 twins). The raw
`GraphQLArgument` / `lambda: GraphQLArgument(...)` idiom stays public and
unchanged — you only need to touch code that used the capitalized
`*InputField` descriptors.

!!! note "The bare `GraphQLArgument` route is unaffected"

    A `class Arguments` that used native `GraphQLArgument(...)` (or a bare
    graphql-core type, auto-wrapped) needs **no change** — the unification only
    removes the `*InputField` descriptor twins.

---

## 9. `JSONField` now carries **raw JSON** on the wire (SDL scalar `JSON`)

**Why.** A model `models.JSONField` (and the `JSONField()` descriptor) used to be
transported as a JSON-encoded **string** (SDL scalar `JSONString`) — the client
had to `JSON.parse()` the value on the way out and `JSON.stringify()` it on the
way in. 2.0 flips the default: a `JSONField` now carries **raw, structured JSON**
(SDL scalar `JSON`) across **all three** paths — output types, mutation inputs,
and filters. Objects, lists, and scalars pass through structurally; inline object
and list literals are accepted directly in a query.

**Wire-format impact.** This is a **schema change** your clients can observe:

```graphql
# Before (JSON transported as a string)
payload: JSONString

# After (raw structured JSON)
payload: JSON
scalar JSON
```

**What to do.** Stop `JSON.parse()`-ing the value on read and stop
`JSON.stringify()`-ing it on write — send and receive the object / list
directly:

```graphql
# Before: the JSON value was a string the client had to parse
mutation { createWidget(input: { payload: "{\"a\":1,\"tags\":[1,2]}" }) { widget { payload } } }

# After: send the object structurally (inline literals are accepted)
mutation { createWidget(input: { payload: { a: 1, tags: [1, 2] } }) { widget { payload } } }
```

!!! tip "Escape hatch — keep the old string wire with `as_str=True`"

    If a client cannot move off the string wire, opt a **descriptor** field back
    into the string encoding with `JSONField(as_str=True)` — it binds the
    `JSONString` scalar (JSON-encoded string; the server `json.loads` it on
    input), reproducing the old behavior for that one field:

    ```python
    from django_graphex.core import JSONField

    class Query(ObjectType):
        raw = JSONField()               # SDL: JSON  (raw structured)
        legacy = JSONField(as_str=True)  # SDL: JSONString (JSON-encoded string)
    ```

!!! note "`GenericJSONField` and the `GenericScalar` SDL name are gone"

    The `GenericJSONField` descriptor and the `GenericScalar` SDL scalar name are
    **removed**. The raw JSON scalar is exported as `GdxJSON` (SDL name `JSON`);
    the string-encoded scalar stays `GdxJSONString` (SDL name `JSONString`). The
    old graphene `GenericScalar` class continues to resolve to the raw `JSON`
    scalar for backward compatibility with legacy graphene-name lookups, but you
    should reference `GdxJSON` / the `JSONField()` descriptor going forward.

---

## 10. `DjangoUnionType` `Meta.gfk_unions` → `Meta.unions`

**Why.** The GFK-owner opt-in key that maps a `GenericForeignKey` to a typed
union was renamed from `Meta.gfk_unions` to the shorter `Meta.unions` (aligning
with the `gfk_types` → `types` rename in the same release). This is a **hard
break**: a class still declaring the old key raises `ImproperlyConfigured` with a
rename hint — it is never silently ignored.

**Before**

```python
class PostType(DjangoObjectType):
    class Meta:
        model = Post
        gfk_unions = {"target": TargetUnion}
```

**After**

```python
class PostType(DjangoObjectType):
    class Meta:
        model = Post
        unions = {"target": TargetUnion}
```

Declaring `gfk_unions` now raises:

```text
PostType: gfk_unions was renamed to unions in v2.0.
Declare the typed GFK unions via Meta.unions = {...}.
```

---

## 11. Cursor pagination cursor format changed (composite keyset)

**Why.** `CursorGraphqlPagination` now encodes a **composite** keyset cursor —
the boundary row's ordering value **plus** its primary key as a deterministic
tiebreak. Previously the cursor carried only the ordering value, so rows with a
**tied** ordering value could be dropped or duplicated across page boundaries.
The pk tiebreak makes tied values page correctly (no dropped rows).

**Wire-format impact.** The cursor string is opaque and its encoding changed, so
any **stored** v1 / beta cursor string is no longer valid and raises a clean
`GraphQLError("Invalid cursor")`:

```graphql
# A cursor persisted before 2.0 (value-only) now fails:
{ users { results(first: 10, after: "<old-cursor>") { id } } }
# -> errors: [{ "message": "Invalid cursor" }]
```

**What to do.** Do not persist cursor strings across the upgrade. Re-fetch from
the first page after deploying 2.0; freshly issued cursors are composite and
page ties correctly. The `first` argument is unchanged.

---

## 12. Output camelCase digit parity (`phone_1` → `phone1`)

**Why (bugfix with wire impact).** On the **output** side, a field name with a
trailing digit component was camelCased incorrectly — `phone_1` rendered as
`phone_1` (a stray underscore), while the **input** side (Pydantic) already
produced `phone1`. Output and input therefore disagreed on the wire name for the
same field. 2.0 routes output through the same canonical camelCase used by the
input path, so `phone_1` → `phone1`, `address_2` → `address2`,
`iso_8601_date` → `iso8601Date` — restoring output/input parity (and v1 graphene
parity).

**Wire-format impact.** A field whose snake_case name has a digit component now
has a **different** output wire name:

```graphql
# Before (output only — stray underscore, mismatched with input)
phone_1: String

# After (matches the input wire name and v1 graphene)
phone1: String
```

**What to do.** Update any query / client that selected the old `phone_1`-style
name to the digit-joined `phone1` form. Fields without a digit component
(`created_at` → `createdAt`) are unchanged.

---

## 13. Filter input SDL name `<Model>Filterinput` → `<Model>FilterInput`

**Why (bugfix, wire-visible).** The generated filter input type was named
`<Model>Filterinput` (lower-case `i`) because the compound name was camelCased as
one token. 2.0 fixes the capitalization to `<Model>FilterInput` — the idiomatic
GraphQL casing.

**Wire-format impact.** The input type **name** changed in the SDL:

```graphql
# Before
input UserFilterinput { ... }

# After
input UserFilterInput { ... }
```

**What to do.** No change is needed for inline `filter: { ... }` usage — only the
**named** type changed. Update any query that referenced the filter input type by
name (e.g. a named variable `$filter: UserFilterInput`) or any SDL snapshot /
codegen artifact that pinned the old `Filterinput` spelling.

---

## 14. Version bump

`django-graphex` is now **2.0.0**. Update your dependency pin:

```diff
- django-graphex>=1.3,<2
+ django-graphex>=2,<3
```

The `subscriptions` extra (Django Channels 4) is unchanged:

```bash
pip install "django-graphex[subscriptions]"
```

---

## Verifying the upgrade

After porting, confirm graphene is truly gone:

```bash
# 1. No graphene import remains anywhere in your code:
rg "^\s*(import graphene|from graphene)" your_app/

# 2. graphene is not installed:
python -c "import importlib.util; assert importlib.util.find_spec('graphene') is None"

# 3. Your schema still builds and serves queries/mutations/subscriptions.
```

If the codemod reports zero findings and your test suite is green, the upgrade is
complete.
