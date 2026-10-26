# Query depth & cost limits

GraphQL lets a client shape its own queries, which means a single request can ask
for far more work than you intend — by nesting deeply, or by paging wide.
`django-graphex` ships two **validation rules** that reject such queries
**before any resolver runs**: a depth limiter and a cost analyzer. Both are
enabled by default in the library's `GraphQLView`. When a cost budget is set,
the view also checks the selected operation against coerced request variables
after document validation and before resolution.

- [`DepthLimitValidationRule`](#query-depth-limiting) — reject abusively *nested*
  queries.
- [`CostLimitValidationRule`](#query-cost-analysis) — reject (or just report)
  queries whose estimated *cost* exceeds a budget.

All the settings used below live under `DJANGO_GRAPHEX` — see
[Settings](settings.md#query-depth-cost) for the full reference. For auth,
introspection and protected fields, see [Security](security.md).

## Query depth limiting

Deeply related models let a client ask for `author { posts { comments {
author { posts { … } } } } }`, which can be expensive or abusive.
`DepthLimitValidationRule` rejects over-nested queries **during validation**, so
no resolver runs. It counts **nested object levels** below a field; scalar leaves
do not count, and it follows fragments (so they can't be used to bypass it).

Two sources combine — the **most restrictive** wins:

| Source | Where | Measured from |
|---|---|---|
| Global default | `DJANGO_GRAPHEX['MAX_QUERY_DEPTH']` | the query root |
| Per-type | `Meta.max_depth` on a `DjangoObjectType` / `DjangoListObjectType` / `DjangoModelType` | any field returning that type |

```python
from django_graphex.types import DjangoModelType
from myapp.models import Category

class CategoryModelType(DjangoModelType):
    class Meta:
        model = Category
        max_depth = 2     # from a category, allow 2 nested object levels
```

```graphql
category {                 # depth 0
  name                     # scalar — free
  posts {                  # depth 1  ✅
    comments {             # depth 2  ✅
      author { username }  # depth 3  ❌ -> "Query exceeds the maximum nesting depth of 2 ..."
    }
  }
}
```

### Enabling it

The library's `GraphQLView` includes the rule by default — per-type
`max_depth` works out of the box. To set a global cap:

```python
# settings.py
DJANGO_GRAPHEX = {
    "MAX_QUERY_DEPTH": 10,   # None (default) is the ONLY way to disable it
}
```

`None` is the only value that turns the global cap off. `0` and negatives used
to disable it silently, which made a typo look like a configured limit; reading
either now raises `ImproperlyConfigured`. The smallest usable value is `1`.

On a plain `BaseGraphQLView` (or your own view), add it alongside the standard rules (passing a list
**replaces** the defaults, so include them):

```python
from graphql.validation import specified_rules
from django_graphex.validation import DepthLimitValidationRule
from django_graphex.views import BaseGraphQLView

class MyGraphQLView(BaseGraphQLView):
    validation_rules = (*specified_rules, DepthLimitValidationRule)
```

!!! note "What counts as a level"

    Only fields with a sub-selection (object/list-of-object fields) add depth;
    scalars don't. A per-type `Meta.max_depth = 0` forbids selecting any nested
    object on that type — `0` is a real value there, unlike in the global
    `MAX_QUERY_DEPTH`, which refuses it. With nothing configured, the rule is a
    no-op.

## Query cost analysis

Depth limiting doesn't catch a query that is shallow but *wide*:
`categories(limit: 100) { posts(limit: 100) { comments(limit: 100) { … } } }`
can materialize a million objects in three levels. Cost analysis estimates the
work a query asks for **during validation and, for a selected operation, after
variable coercion** and rejects it over a budget — and can optionally report the
cost back to clients. It captures *width × depth × page
size* in one number:

```
cost(field) = own_cost + multiplier × Σ cost(children)
```

- **`own_cost`** — `0` for scalar leaves, `1` for object/list fields, or the
  type's `Meta.complexity` when declared.
- **`multiplier`** — a list field's page size (the `limit` / `page_size` /
  `first` / `last` argument), clamped to `0` at the low end and capped at
  `MAX_PAGE_SIZE`; `1` otherwise. A zero or negative page size is rejected at
  runtime, so it contributes no children — and it can never *subtract* cost
  from a sibling field. Those argument names multiply only real GraphQL lists
  and django-graphex list containers; a singular business field may use an
  argument such as `limit` without being treated as a list.

It follows fragments, so they can't be used to under-count.

### Configuring

```python
# settings.py
DJANGO_GRAPHEX = {
    "MAX_QUERY_COST": 1000,        # None (default) is the ONLY way to disable it
    "EXPOSE_QUERY_COST": False,    # True = add extensions.cost to responses
    "DEFAULT_LIST_MULTIPLIER": 10, # used only when no page size / cap is known
    "MAX_PAGE_SIZE": 100,          # the realistic per-list ceiling (recommended)
    "DEFAULT_PAGE_SIZE": 100,      # library default; not a hard cap
    # Argument names treated as a list's page size (default below):
    "COST_PAGINATION_ARGS": ("limit", "page_size", "first", "last"),
}
```

| Setting | Default | Effect |
|---------|---------|--------|
| `MAX_QUERY_COST` | `None` | Budget; queries over it are rejected by static validation or, for the selected operation, after request-variable coercion and before resolution. `None` is the **only** way to disable the budget; `0` or a negative value raises `ImproperlyConfigured`. |
| `EXPOSE_QUERY_COST` | `False` | When `True`, responses include `extensions.cost`. |
| `MAX_PAGE_SIZE` | `None` | Caps every list multiplier (also a pagination setting). |
| `DEFAULT_PAGE_SIZE` | `100` | Fallback multiplier when `MAX_PAGE_SIZE` is not set; also the library's inherited page size, not a hard cap. |
| `DEFAULT_LIST_MULTIPLIER` | `10` | Last-resort multiplier when neither `MAX_PAGE_SIZE` nor `DEFAULT_PAGE_SIZE` is set; triggers a `RuntimeWarning`. |
| `COST_DIRECTIVE` | `0` | Cost added per custom directive use on a field. |
| `COST_PAGINATION_ARGS` | `("limit", "page_size", "first", "last")` | Argument names read as a real list field's page size. Names are compared in snake_case form, so `page_size` also matches the wire name `pageSize`. A custom `page_size_query_param` such as `per_page` must be added here. |

When a list field has no pagination argument, cost analysis uses
`MAX_PAGE_SIZE`, then `DEFAULT_PAGE_SIZE`, then `DEFAULT_LIST_MULTIPLIER`.
This applies even when the GraphQL parser represents an empty argument list as
absent; the last fallback still emits its one-time unbounded-list warning.

Declare per-type weights with `Meta.complexity`, so expensive types eat more of
the budget:

```python
class CategoryModelType(DjangoModelType):
    class Meta:
        model = Category
        complexity = 5     # base weight to resolve one category
```

`Meta.complexity` is read on `DjangoObjectType`, `DjangoListObjectType`, and
`DjangoModelType` (forwarded to its generated output type). The library's
`GraphQLView` enables the rule by default. On a custom view, add it next to
the standard rules (and the depth rule, if you want both):

```python
from graphql.validation import specified_rules
from django_graphex.cost import CostLimitValidationRule
from django_graphex.validation import DepthLimitValidationRule
from django_graphex.views import BaseGraphQLView

class MyGraphQLView(BaseGraphQLView):
    validation_rules = (*specified_rules, DepthLimitValidationRule, CostLimitValidationRule)
```

### Operating modes

The two settings give you four behaviors:

| `MAX_QUERY_COST` | `EXPOSE_QUERY_COST` | Behavior |
|---|---|---|
| set | `False` | block over budget, silent otherwise |
| set | `True` | block **and** report cost in `extensions` (GitHub-style) |
| `None` | `True` | **observation** — never block, just report the cost |
| `None` | `False` | no-op |

When exposed, responses carry:

```json
{ "data": { ... }, "extensions": { "cost": { "requestedCost": 411, "maxCost": 1000 } } }
```

`extensions.cost` is attached only to a **successful** response, and it is
computed against the schema *that request* is served — the pruned one when
[`PERMISSION_SCOPED_SCHEMA`](permission-scoped-schema.md) is active. A request
that fails validation (HTTP 400) carries no cost payload: the estimate is
derived from the fields the document *names*, so reporting it next to a
`Cannot query field` error would tell the caller whether the field exists in
the full schema.

Observation mode (`MAX_QUERY_COST=None`, `EXPOSE_QUERY_COST=True`) is the safe way
to roll this out: watch real costs in production, calibrate `complexity` weights
and the budget, then set `MAX_QUERY_COST` to start enforcing.

!!! warning "Set `MAX_PAGE_SIZE`"

    The multiplier for a list is its page size. If a list has no page-size
    argument in the query and `MAX_PAGE_SIZE` is `None`, the cost falls back to
    `DEFAULT_PAGE_SIZE`, then `DEFAULT_LIST_MULTIPLIER` (a soft guess that
    emits a one-shot `RuntimeWarning`). Set `MAX_PAGE_SIZE` so unbounded lists
    are costed at a ceiling the server actually enforces. A bound `limit: $var`
    is checked against its real, coerced value before a resolver runs even
    without this cap; the cap remains useful for omitted limits.

!!! warning "Static validation uses a conservative variable fallback"

    A default declared in the document (`query Q($n: Int = 1)`) is written by
    the client, so the static validation rule still ignores it and prices an
    unresolved variable at `MAX_PAGE_SIZE`, else `DEFAULT_PAGE_SIZE` /
    `DEFAULT_LIST_MULTIPLIER`. After validation, `GraphQLView` also checks the
    selected operation with GraphQL-coerced request values and defaults before
    any resolver runs, including when document validation is cached. A low
    request value does **not** undo a prior static rejection. A high value that
    previously passed the fallback check may now return HTTP 400 with
    `QUERY_TOO_COMPLEX` instead of executing. The public `analyze_cost` API
    and cost model are unchanged.

    For example, with `MAX_QUERY_COST=120`, `DEFAULT_PAGE_SIZE=100`, and no
    `MAX_PAGE_SIZE`, a list whose nested cost is `1 + limit` passes static
    validation for `limit: $n` at 101. Sending `{"n": 150}` now rejects the
    selected operation at cost 151; sending `{"n": 5}` remains within budget.
    Explicit `limit: 150` was already rejected by static validation.

    A response-cache hit serves a stored response without executing a resolver;
    this new bound check runs when the request proceeds to GraphQL execution.
    A mutation rejected by this bound check has not run a resolver, so it does
    not invalidate an already-warmed response cache. In a non-atomic batch, an
    earlier mutation that did execute still invalidates the cache even if a
    later operation is rejected. Resolver errors after a non-atomic write keep
    their existing invalidation behavior. This check does not change hot-setting
    behavior.

!!! note "Per-type only (for now)"

    Weights are declared per **type** via `Meta.complexity`. Per-**field** weights
    aren't supported yet; wrap an expensive field's return in a type with
    `Meta.complexity`, or watch for a future `@cost` directive.

## Programmatic cost analysis

Sometimes you want a query's estimated cost **without** running it through a view —
to assert a budget in a test, gate a query in CI, or log the cost of a generated
operation. `analyze_cost()` returns a `CostReport` for any parsed document against
your schema, using the exact same estimator the `CostLimitValidationRule` uses.

```python
from graphql import parse

from django_graphex.cost import analyze_cost, CostReport

query = parse("""
    query {
      categories {
        results(limit: 50) {
          id
          name
          posts {
            id
            title
          }
        }
        totalCount
      }
    }
""")

report: CostReport = analyze_cost(schema.graphql_schema, query)
print(report.total)     # estimated cost, e.g. 52
print(report.max_cost)  # the configured MAX_QUERY_COST budget (or None)
```

Note how the multiplier only bites once a list's children include a nested
*object* field: without `posts`, `results(limit: 50) { id name }` alone would
cost only `2` — `id` and `name` are scalar leaves (`own_cost = 0`), so the
`50×` multiplier has nothing non-zero to multiply. Adding `posts { id title }`
under `results` gives the multiplier an object field (`own_cost = 1`) to act
on: `posts` costs `1`, so `results` costs `1 + 50×1 = 51`, and `categories`
costs `1 + 1×(51 + 0) = 52`.

`CostReport` is a `NamedTuple` with two fields:

| Field | Type | Meaning |
|---|---|---|
| `total` | `int` | The estimated cost of the operation. |
| `max_cost` | `int \| None` | The configured `MAX_QUERY_COST` budget (`None` when unset). |

`analyze_cost(schema, document, operation_name=None, variable_values=None)` takes:

- **`schema`** — the graphql-core schema (`schema.graphql_schema` on a `DjangoGraphQLSchema`).
- **`document`** — the parsed query (`graphql.parse(...)`).
- **`operation_name`** — required only when the document holds several operations;
  otherwise the sole/first operation is costed.
- **`variable_values`** — bound variables, so a variabled page size (`limit: $first`)
  is costed exactly instead of falling back to the `MAX_PAGE_SIZE` cap.

### Very deep documents

Independently of `MAX_QUERY_DEPTH`, `DepthLimitValidationRule` always enforces a
hard ceiling of 100 nested object levels (a private constant). Python's stack
cannot execute deeper documents: graphql-core completes each level through
several nested frames, and with real data a request fails with an internal
error from roughly 130 levels, while its parser only refuses inline documents
at about 232 levels. Fragments split a deep document into shallow pieces that
parse fine, so they get the same HTTP 400 `QUERY_TOO_DEEP` as an equally deep
inline document. The ceiling also applies to subscriptions, which share the
rule, and a larger `MAX_QUERY_DEPTH` cannot raise it; a smaller one still
wins.

Both rules walk the document with an explicit stack, so a long chain of
fragments or deep inline nesting cannot exhaust the Python stack inside them.
graphql-core itself is still recursive: its parser fails at roughly 250 nested
selection sets and its `NoFragmentCycles` rule at several hundred chained
fragments (with the default recursion limit). The view answers those documents
with an HTTP 400 and `extensions.code` `QUERY_TOO_DEEP` ("Query is nested too
deeply to be parsed/validated") instead of an HTTP 500, whether or not
`MAX_QUERY_DEPTH` is set. Only parsing and validation are guarded this way;
`RecursionError` raised by a resolver is still a server error. Variables nested
too deeply to coerce get the same code ("Variables are nested too deeply to be
coerced.") over HTTP, SSE and WebSocket.

### Cyclic fragments and direct callers

The cost and depth rules now inspect the named-fragment reference graph before
expanding selections. Standard GraphQL validation still reports cyclic
fragments as request errors before resolvers run; a compact branching cycle
cannot make either rule repeatedly traverse its expanded paths. Acyclic
documents, including repeated spreads that each contribute full cost, keep
their existing estimates and depth verdicts.

**Compatibility change for direct callers:** `analyze_cost()` now raises
`GraphQLError` when *any* named fragments in the parsed document form a cycle,
even if the selected operation does not spread that fragment. Previously it
could return a truncated, misleading `CostReport`. For example,
`{ root { ...F } } fragment F on Node { child { ...F } }` is cyclic; it no
longer has a usable cost report. Validate the document first, or catch the
exception when accepting unvalidated documents:

```python
from graphql import GraphQLError, parse, validate
from django_graphex.cost import analyze_cost

document = parse(query_text)
errors = validate(schema.graphql_schema, document)
if errors:
    raise errors[0]  # Includes standard cyclic-fragment errors.

try:
    report = analyze_cost(schema.graphql_schema, document)
except GraphQLError:
    # Needed when calling directly without prior validation.
    raise
```

A handy use is a regression test that fails if a query gets more expensive:

```python
def test_dashboard_query_stays_within_budget(schema):
    report = analyze_cost(schema.graphql_schema, parse(DASHBOARD_QUERY))
    assert report.total <= 500
```

!!! tip "Same numbers as the runtime rule"

    `analyze_cost()` shares the estimator with `CostLimitValidationRule`, so a
    `report.total` over `report.max_cost` is exactly what the view would reject at
    runtime. During validation the rule has no bound variables, so it costs
    variabled page sizes at the `MAX_PAGE_SIZE` cap — ignoring any default the
    document declares for them. Pass `variable_values` to `analyze_cost()` to
    mirror a specific request precisely; only then is a variable's declared
    default used for the variables the request left unbound.

## Error codes

Both rules fail during **validation** and tag their error with a
machine-readable `extensions.code`:

| Code | Raised by |
|------|-----------|
| `QUERY_TOO_DEEP` | `DepthLimitValidationRule`, and documents too deep for graphql-core's parser/validator |
| `QUERY_TOO_COMPLEX` | `CostLimitValidationRule` |

```json
{ "errors": [{ "message": "Query exceeds the maximum nesting depth of 2 for 'CategoryGenericType'.",
               "extensions": { "code": "QUERY_TOO_DEEP" } }] }
```

```json
{ "errors": [{ "message": "Query cost 1411 exceeds the maximum of 1000.",
               "extensions": { "code": "QUERY_TOO_COMPLEX" } }] }
```

See [Security](security.md#error-codes) for the full table of execution-time
error codes (auth, permissions, introspection).

## @skip and @include directives

Both rules honor the built-in `@skip` and `@include` directives. A field (or
inline fragment or fragment spread) that is statically excluded is **not counted**
toward cost or depth:

```graphql
# @skip(if: true) → the users field and its subtree are not counted
query GetData($loadUsers: Boolean!) {
  profile { name }
  users(limit: 10) @skip(if: true) {
    posts { title }
  }
}
```

### Literal conditions are exact

| Directive | Result |
|-----------|--------|
| `@skip(if: true)` | Field **excluded** from cost/depth |
| `@skip(if: false)` | Field **included** (normal counting) |
| `@include(if: true)` | Field **included** (normal counting) |
| `@include(if: false)` | Field **excluded** from cost/depth |

### Variable conditions — conservative fallback

Validation rules run **before** variables are bound. When the directive argument
is a variable reference (`@skip(if: $flag)`) and no value is available, the
library applies a **conservative policy**: the field is treated as included and
counted. This prevents a query from slipping through a cost budget by hiding an
expensive subtree behind an unknown variable.

When variables are bound (the `EXPOSE_QUERY_COST` reporting path, or a direct
call to `analyze_cost(..., variable_values={"flag": True})`), the directive is
resolved exactly.

```python
from graphql import parse
from django_graphex.cost import analyze_cost

# With bound variables: exact evaluation
report = analyze_cost(schema.graphql_schema, parse(query), variable_values={"flag": True})
# flag=True → @skip(if:$flag) skips the subtree → lower cost
```

!!! note "Directives and cost"

    Custom directives such as `@date` and `@number` transform the value of an
    already-fetched field, so they do not change depth or the optimizer's
    select/prefetch planning. By default they do not add cost either. Set
    `COST_DIRECTIVE` (default `0`) to charge each custom directive use that
    amount, multiplied by the enclosing list sizes. `@skip` and `@include` are
    never charged. Independently of cost, `MAX_DIRECTIVE_OUTPUT_TOTAL` caps the
    text directives may add to a whole response (see
    [Settings](settings.md#string-directive-output)).
