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

    It folds the `GRAPHENE` settings namespace into `DJANGO_GRAPHEX`
    automatically and **flags** (with native guidance) the graphene constructs
    you must port by hand. It never imports graphene, so it runs fine after the
    2.0 install.

## At a glance

| # | What changed | Effort |
|---|--------------|--------|
| 1 | graphene backend removed; `GDX_BACKEND` env var gone | none — automatic |
| 2 | `GRAPHENE` settings namespace → `DJANGO_GRAPHEX` (single namespace) | codemod `--apply` |
| 3 | `graphene.ObjectType` roots → `from django_graphex import ObjectType` | manual |
| 4 | `graphene.Schema(...)` → `DjangoGraphQLSchema(...)` | manual |
| 5 | graphene field descriptors → `field(GraphQLString)` | manual |
| 6 | `graphene.Argument(...)` in `class args` → `GraphQLArgument(...)` | manual |
| 7 | `choices` fields now render as a GraphQL **enum** (output **and** input) | wire-format — review clients |
| 8 | version `1.3.0` → `2.0.0` | bump your pin |

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
    "MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"],
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
    "MIDDLEWARE": ["django_graphex.GraphQLDirectiveMiddleware"],
    # this package's own settings (unchanged)
    "DEFAULT_PAGE_SIZE": 20,
}
```

The codemod's `--apply` performs exactly this fold: it merges the `GRAPHENE`
keys into an existing `DJANGO_GRAPHEX` dict (or renames `GRAPHENE` to
`DJANGO_GRAPHEX` when there is no target dict yet).

---

## 3. `graphene.ObjectType` roots → native `ObjectType`

**Why.** Schema roots no longer subclass `graphene.ObjectType`. Use the native
root base exported from `django_graphex`.

**Before**

```python
import graphene
from django_graphex import DjangoListObjectField


class Query(graphene.ObjectType):
    users = DjangoListObjectField(UserListType)
```

**After**

```python
from django_graphex import ObjectType
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
from django_graphex import DjangoGraphQLSchema

schema = DjangoGraphQLSchema(query=Query, mutation=Mutation)
```

`directives=all_directives` and the other keyword arguments carry over unchanged:

```python
from django_graphex import DjangoGraphQLSchema, all_directives

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
from django_graphex import ObjectType, field
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

## 6. `graphene.Argument(...)` in `class args` → `GraphQLArgument(...)`

**Why.** Mutation arguments are declared with the native graphql-core
`GraphQLArgument`. This is a **clean break**: a non-native value (such as the old
`graphene.Argument`) left in a `Mutation` `class args` now raises `TypeError`
loudly — it is never silently dropped.

**Before**

```python
import graphene
from django_graphex import DjangoModelMutation


class CreateUser(graphene.Mutation):
    class args:
        name = graphene.Argument(graphene.String, required=True)

    ok = graphene.Boolean()

    def mutate(root, info, name):
        ...
```

**After**

```python
from django_graphex import Mutation, field
from graphql import GraphQLArgument, GraphQLBoolean, GraphQLNonNull, GraphQLString


class CreateUser(Mutation):
    class args:
        name = GraphQLArgument(GraphQLNonNull(GraphQLString))

    ok = field(GraphQLBoolean)

    @staticmethod
    def mutate(root, info, name):
        ...
```

!!! tip "Bare types are auto-wrapped"

    A bare graphql-core type in `class args` is accepted and wrapped in a
    `GraphQLArgument` for you:

    ```python
    class args:
        age = GraphQLInt          # equivalent to GraphQLArgument(GraphQLInt)
    ```

!!! note "Model mutations are unaffected"

    If you use `DjangoModelMutation` (the model-first create/update/delete
    mutation), the arguments are derived from the model — there is nothing to
    port here. Only hand-declared `class args` using `graphene.Argument` need the
    change above.

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

## 8. Version bump

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
