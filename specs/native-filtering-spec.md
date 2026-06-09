# SPEC — Native filtering (`Q`-based) with `and`/`or`/`not`, dropping django-filter

Status: accepted
Branch: `native-filtering` (off `model-rename-validators`)
Type: breaking (filter input shape) + dependency removal

## Goals

1. **Logical operators in the GraphQL client**: support `and` / `or` / `not` nested
   filtering (django-filter + the flat-arg bridge only ever AND filters together).
2. **Drop `django-filter`** entirely: own the model→filter-schema and the
   filter→queryset translation, using Django's native ORM lookups + `Q` objects.

`graphene-django-filter` was evaluated and rejected as a dependency: it is built
*on top of* django-filter and additionally pulls `graphene-django` (just removed)
and `psycopg2-binary`, and is unmaintained (last release 2023, Python ≤3.11). We
reuse its **design** (nested `and/or/not` input → `Q` tree), not its code.

## Confirmed decisions

1. **Clean break**: remove the flat per-field arguments (`author_name`, `status`, …).
   The only filter entry point is a single `filter:` argument of a generated nested
   input type.
2. **Leaves are nested-by-field**: `filter: { name: { icontains: "x" },
   author: { name: { exact: "y" } } }` (relations recurse), not flat
   `name_icontains`.
3. **Operators are `and` / `or` / `not`** (lowercase).

## Non-goals (this SPEC)

- Ordering / pagination (unchanged; they already live on the list field / `results`).
- Full-text search, trigram, regex, geo lookups — left as opt-in lookups for a
  later iteration (must NOT introduce a Postgres/`psycopg2` dependency).
- A custom-FilterSet escape hatch (the old `Meta.filterset_class`) is **removed**;
  a `get_queryset` / `filter_queryset` hook already exists for bespoke logic.

## GraphQL surface

For a model exposed with `Meta.filter_fields`, generate one recursive input type
`<Model>FilterInput`:

```graphql
input AuthorFilterInput {
  # logical composition (each list item is itself an AuthorFilterInput)
  and: [AuthorFilterInput!]
  or: [AuthorFilterInput!]
  not: AuthorFilterInput

  # per-field lookups (only the lookups declared in filter_fields)
  id: IDLookups            # plain-pk filtering: { exact, in }
  name: StringLookups      # { exact, icontains, ... }
  # relation field -> the related model's FilterInput (recurses)
  posts: PostFilterInput
}

input StringLookups {
  exact: String
  icontains: String
  in: [String!]
  isnull: Boolean
}
```

Example query (the motivating case):

```graphql
{
  authors(filter: {
    or: [
      { name: { icontains: "ada" } }
      { and: [
          { posts: { title: { icontains: "graphql" } } }
          { posts: { status: { exact: "published" } } }
      ] }
    ]
    not: { id: { exact: 7 } }
  }) {
    totalCount
    results { id name }
  }
}
```

### Semantics
- Multiple keys **within one node** are AND-ed.
- `and: [a, b]` → `Q(a) & Q(b)`; `or: [a, b]` → `Q(a) | Q(b)`; `not: a` → `~Q(a)`.
- An empty `filter: {}` (or omitted) is a no-op.
- A query whose Q traverses a to-many relation is de-duplicated with `.distinct()`.

## Input-type generation (from `Meta.filter_fields`)

`Meta.filter_fields` stays the opt-in declaration; its existing forms are kept:
- list form `["name", "author__name"]` → each field gets the **default lookup set**;
- dict form `{"name": ("exact", "icontains"), "author__name": ("exact",)}`.

Generation rules, reusing the model introspection from `native/fields.py`
(`get_internal_type()` → Python/graphene scalar, choices → `Enum`):

1. **Group `__` paths**: `author__name` becomes a nested `author` → `name` entry.
   A relation segment yields a nested `<RelatedModel>FilterInput`; the final segment
   yields a `<Lookups>` input for that field's scalar.
2. **Per-field `<Lookups>` input**: one GraphQL input field per declared lookup. The
   value type is derived from the model field:
   - scalar lookups (`exact`, `gt`, `icontains`, …) → the field's graphene scalar;
   - `in` → `List(scalar)`;
   - `range` → `List(scalar)` (validated length 2 at translate time);
   - `isnull` → `Boolean`;
   - a `choices` field → its generated `Enum` as the scalar.
3. **Relation field declared directly** (e.g. `"author"` with `("exact", "in")`) →
   plain-pk lookups on the FK id (`exact`, `in` typed as the related pk scalar),
   exposed as the relation's `id`-style lookups. (Replaces `GraphqlIDFilter`.)
4. The `and`/`or`/`not` keys are added to every `<Model>FilterInput` referencing
   itself. (`and`/`or`/`not` are Python keywords, so the input class is built
   dynamically via `type(name, (graphene.InputObjectType,), namespace)`.)

Default lookup set (configurable via a new `DEFAULT_FILTER_LOOKUPS` setting):
`("exact", "in", "isnull")` plus, by type — text: `icontains`, `istartswith`;
ordered (number/date/datetime): `gt`, `gte`, `lt`, `lte`, `range`.

## Query translation (`filter` value → `Q`)

A recursive `to_q(node, prefix="") -> (Q, touched_to_many: bool)`:

```
for key, value in node.items():
    if key == "and":  combine children with &
    elif key == "or": combine children with |
    elif key == "not": negate child
    elif key is a relation field: recurse with prefix + key + "__"
    else:  # a field with a {lookup: value} mapping
        for lookup, v in value.items():
            Q(**{f"{prefix}{key}__{lookup}": v})   # AND within the field
```

- Empty `or: []` contributes nothing; empty node → `Q()`.
- `range` validates a 2-element list (else a `non_field`/argument error).
- Apply: `queryset.filter(q)`, then `.distinct()` if any relation segment was
  traversed.

## Architecture — a `FilterBackend` seam

Mirror the `SerializerBackend` pattern so the layer is swappable and isolated.

New package `graphene_django_extras/filtering/`:
- `backend.py` — `FilterBackend` ABC + `NativeFilterBackend`:
  - `build_input_type(model, filter_fields, registry) -> type[graphene.InputObjectType] | None`
  - `apply(queryset, value) -> queryset`
- `schema.py` — input-type construction (rule set above), memoized per
  `(model, frozenset(filter_fields))`, enums/related inputs sourced from the registry.
- `translate.py` — `to_q` and `.distinct()` handling.
- `lookups.py` — lookup catalogs + per-type defaults (absorbs `filters/lookups.py`).

Resolvers stop building flat args and instead expose a single `filter` argument and
call `backend.apply(qs, filter_value)`. Touch points (from the code map):
- `fields.py` — `DjangoFilterListField`, `DjangoFilterPaginateListField`,
  `DjangoListObjectField` (`__init__` arg wiring + `list_resolver` application at
  `fields.py:237-239, 397, 519`).
- `types.py` — `DjangoModelType.list()` (`types.py:1098`).

## Removing django-filter

- Delete `filters/_vendor.py` and `filters/filter.py`; the form-field→graphene
  bridge and FilterSet factory are no longer needed (model introspection replaces
  them).
- `GraphqlIDFilter` / `GraphqlIDFormField` are **removed**; plain-pk filtering is now
  `id: { exact: <pk> }` / `id: { in: [<pk>] }`, where the scalar is the model's pk
  type. (Documented in migration.)
- `_compat.DJANGO_FILTER_INSTALLED` and all its guards are removed; filtering is a
  core capability again (no optional import). `filter_fields` with no model → the
  same `ImproperlyConfigured` we already raise for a missing model.
- `pyproject.toml`: drop `django-filter`. (One fewer dependency; keeps us
  DB-agnostic — no `psycopg2`.)

## Phases / commits

1. `docs: SPEC — native filtering with and/or/not, dropping django-filter` (this).
2. `feat: native Q-based filter backend (and/or/not nested input)` — the
   `filtering/` package + input generation + translate, behind the seam; list fields
   switch to the `filter:` arg and native application; **remove the flat args**.
   Tests for: per-field lookups, `in`/`range`/`isnull`, `and`/`or`/`not`, nested
   relations, plain-pk `id`, `.distinct()`, empty filter.
3. `refactor!: drop django-filter` — delete the vendored bridge + `GraphqlIDFilter`,
   remove the `DJANGO_FILTER_INSTALLED` guards, drop the dependency, migrate the
   filter tests (`test_filters_id.py`, `filtersets.py`) to the new shape.
4. `docs: native filtering guide + migration/changelog` — `usage/` filtering page,
   `migration.md` (flat→`filter:` clean break, `GraphqlIDFilter`→`id` lookups),
   `changelog.md` (BREAKING).

(Steps 2–3 may land together if review prefers a single drop.)

## Acceptance criteria

- AC1: `authors(filter: { or: [...], and: [...], not: {...} })` returns the
  expected rows; a nested-relation filter (`posts: { title: { icontains } }`) works
  and de-duplicates.
- AC2: each declared lookup (`exact`, `icontains`, `in`, `range`, `isnull`, ordered
  comparisons) maps to the correct ORM lookup; `choices` fields filter via their
  enum.
- AC3: plain-pk filtering via `id: { exact }` / `{ in }` replaces `GraphqlIDFilter`
  (int pk and UUID pk).
- AC4: the flat per-field arguments no longer exist on any list field; the only
  filter argument is `filter`.
- AC5: `import django_filters` appears nowhere in the package; `pyproject` has no
  `django-filter`; the suite passes with django-filter uninstalled.
- AC6: full suite green; ruff + mypy clean.

## Risks / mitigations

- **Value coercion edge cases** (dates, decimals, UUIDs, enums, lists): graphene
  scalars parse inputs; cover each type/lookup with tests. `range` length is
  validated explicitly.
- **`.distinct()` cost**: only applied when a to-many relation is traversed.
- **Lost niche django-filter features** (custom FilterSet methods, CSV filters):
  steer users to `get_queryset` / `filter_queryset`; document.
- **Breaking the filter API**: this is an intentional clean break in the 2.0 line;
  fully documented in `migration.md`.

## Open (future, not now)
- Full-text / trigram / regex / geo lookups as opt-in (no hard `psycopg2` dep).
- Ordering input parity (`order_by`) could later share the same nested-by-field
  shape.
