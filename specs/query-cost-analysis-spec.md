# SPEC — Query cost analysis (`complexity` / `MAX_QUERY_COST`)

**Status:** IMPLEMENTED in `pre-v2`. Defaults confirmed: scalar `0` / object·list
`1`; `DEFAULT_LIST_MULTIPLIER=10`; warn-only when `MAX_PAGE_SIZE` is `None`;
`MAX_QUERY_COST` defaults to `None` (opt-in). Per-**field** `complexity=` is
**deferred** — graphene rejects unknown `Field` kwargs (treats them as
arguments), so iteration 1 ships per-**type** `Meta.complexity` only.
**Scope (planned):** new `graphene_django_extras/cost.py`; `types.py`,
`base_types.py`, `settings.py`, `views.py`, `__init__.py`; tests, docs.
**Date:** 2026-06-08
**Builds on:** the depth limiter (`DepthLimitValidationRule`) — same machinery
(a pre-execution `ValidationRule` that walks the AST, follows fragments, and
reads config from `_meta`). Cost analysis adds **per-field weight** and a
**pagination multiplier** so it captures *width × depth × page size* in one
number, subsuming a plain field-count limit.

---

## 1. Problem / Goals

A query can be shallow yet enormous: `rentalCompanies(limit: 100) { properties(
limit: 100) { units(limit: 100) { … } } }` materializes up to 1,000,000 objects.
Depth limiting doesn't catch this. We want a single **cost** estimated *before*
execution, comparable against a budget, and optionally surfaced to clients.

**Goals**
- **G1** — Estimate a query's cost from the AST + schema, pre-execution (no
  resolver / DB hit), via a shared engine.
- **G2** — Cost model: `cost(field) = own_cost + multiplier × Σ cost(children)`,
  where `multiplier` is the pagination size for list fields, `1` otherwise.
- **G3** — Per-type weight override (`Meta.complexity`), stored on `_meta` and
  read during the walk — exactly like `max_deep`. (Per-field `complexity=`
  deferred; see Status.)
- **G4** — Global budget `MAX_QUERY_COST` (None = disabled); over-budget queries
  are rejected during validation. Follows fragments (no bypass).
- **G5** — Optional exposure: when `EXPOSE_QUERY_COST`, inject
  `extensions.cost` into the response (`requestedCost` / `maxCost`).
- **G6** — No-op when nothing is configured; enabled by default on
  `ExtraGraphQLView` (added to the standard rules, not replacing them).

### Non-Goals (this iteration)
- Per-client budgets / leaky-bucket rate limiting with a recharging balance
  (needs Redis + auth coupling; build on top later).
- Field-argument-aware costing beyond the pagination size arg.
- A separate "field count" limit (subsumed: `own_cost=1`, no multipliers ⇒
  field count).

---

## 2. Cost model

```
cost(field):
    if field is a scalar leaf:            return 0          # already fetched
    own  = weight(field)                                    # default 1
    mult = list_multiplier(field)                           # default 1
    return own + mult * sum(cost(child) for child in selection_set)
```

### 2.1 Weight (`own_cost`)
Resolution order (first hit wins):
1. field-level `complexity=<int>` kwarg on the graphene field,
2. `Meta.complexity` on the field's **named return type**
   (`DjangoObjectType` / `DjangoListObjectType` / `DjangoSerializerType`),
3. default: **`0` for scalars, `1` for object/list fields**.

Stored on `_meta.complexity` and read via
`graphql_type.graphene_type._meta.complexity` (same path as `max_deep`).

### 2.2 List multiplier
A field is "a list" if its return type is a `List`/connection **or** it carries
a pagination size argument (`limit`, `page_size`, `first`, `last` — configurable
set `COST_PAGINATION_ARGS`). The multiplier is the **realistic worst case the
server would actually serve**:

1. literal value of the size arg in the query, **capped at `MAX_PAGE_SIZE`** if
   that setting is set;
2. else the size arg's **variable default** (if declared), capped;
3. else `MAX_PAGE_SIZE`, else `DEFAULT_PAGE_SIZE`, else
   `DEFAULT_LIST_MULTIPLIER` (new setting, **proposed default `10`**).

Capping at `MAX_PAGE_SIZE` matters: it closes the `limit: $n` bypass — an
unknown/huge page size is costed at the ceiling the server enforces anyway, not
at a small default.

### 2.3 Worked example
`MAX_PAGE_SIZE = 100`, all weights default:
```graphql
rentalCompanies(limit: 10) {        # list ×10, own 1
  name                              # scalar 0
  properties(limit: 20) {           # list ×20, own 1
    units { tenant { name } }       # units own 1; tenant own 1; name 0
  }
}
# cost(units)      = 1 + 1*(cost(tenant)) = 1 + 1*(1 + 1*0) = 2
# cost(properties) = 1 + 20*(cost(units)) = 1 + 20*2 = 41
# cost(rentalCos)  = 1 + 10*(0 + 41)      = 411
```
Budget `MAX_QUERY_COST = 1000` ⇒ passes (411). Bump `limit: 100` on both ⇒
`1 + 100*(1 + 100*2) = 20101` ⇒ rejected.

---

## 3. Design / Integration

- **`cost.py`**
  - `analyze_cost(schema, document, operation_name=None, variable_values=None)
    -> CostReport(total, max_cost)` — the shared engine; pure AST arithmetic,
    follows inline + named fragments (cycle-guarded), resolves types from the
    schema (mirrors the depth walker).
  - `CostLimitValidationRule(ValidationRule)` — runs the engine in
    `enter_operation_definition`; reports a `GraphQLError` when
    `total > MAX_QUERY_COST`. Variables aren't bound at validation, so it uses
    literals + variable defaults + the `MAX_PAGE_SIZE` ceiling (conservative).
- **Weights on types** — `Meta.complexity` on `DjangoObjectType` /
  `DjangoListObjectType` (`DjangoObjectOptions.complexity`); forwarded to the
  generated output type for `DjangoSerializerType` via `factory_type` (same
  wiring as `max_deep`). Field-level `complexity=` read from the graphene field.
- **Settings** (defaults): `MAX_QUERY_COST=None`, `EXPOSE_QUERY_COST=False`,
  `DEFAULT_LIST_MULTIPLIER=10`, `COST_PAGINATION_ARGS=("limit","page_size",
  "first","last")`. Read through the settings module (honors `override_settings`).
- **View** — `ExtraGraphQLView`:
  - adds `CostLimitValidationRule` to `validation_rules` (enforcement);
  - when `EXPOSE_QUERY_COST`, runs `analyze_cost` with the **real**
    `variable_values` and injects `extensions.cost = {requestedCost, maxCost}`
    into the response (exposure happens post-execution, where `extensions`
    lives; enforcement already happened in validation).

```python
GRAPHENE_DJANGO_EXTRAS = {
    "MAX_QUERY_COST": 1000,        # None = don't block (e.g. observation mode)
    "EXPOSE_QUERY_COST": False,    # True = add extensions.cost to responses
    "DEFAULT_LIST_MULTIPLIER": 10, # used only when no page size / cap is known
}
```
```python
class RentalCompanyModelType(DjangoSerializerType):
    class Meta:
        serializer_class = RentalCompanyModelSerializer
        complexity = 5     # base weight to resolve one rental company

expensive_report = graphene.Field(ReportType, complexity=50)  # per-field
```

### Modes (all from the two settings)
| `MAX_QUERY_COST` | `EXPOSE_QUERY_COST` | Behavior |
|---|---|---|
| set | `False` | block over budget, silent otherwise (default-ish) |
| set | `True` | block + report cost in `extensions` (GitHub-style) |
| `None` | `True` | **observation**: never block, just report cost |
| `None` | `False` | no-op |

---

## 4. Acceptance Criteria
- **AC1** — Scalars cost 0; an object field costs its weight; a list field
  multiplies its subtree by the page size.
- **AC2** — Literal page size used and capped at `MAX_PAGE_SIZE`; a variabled /
  absent page size falls back to the cap (or `DEFAULT_LIST_MULTIPLIER`).
- **AC3** — `Meta.complexity` (type) and `complexity=` (field) override the
  default weight; field beats type.
- **AC4** — Over `MAX_QUERY_COST` ⇒ one validation error, no execution; fragments
  can't bypass it.
- **AC5** — `EXPOSE_QUERY_COST=True` ⇒ response carries
  `extensions.cost.requestedCost` (exact, with real variables) and `maxCost`.
- **AC6** — `MAX_QUERY_COST=None` ⇒ never blocks (even with exposure on);
  nothing configured ⇒ no-op. `complexity` reaches `_meta` on object/list/
  serializer types; the view includes the rule alongside the standard rules.

---

## 5. Resolved decisions
1. **Default weights** — scalar `0`, object/list `1`.
2. **`DEFAULT_LIST_MULTIPLIER`** — `10`.
3. **No `MAX_PAGE_SIZE` set** — **warn-only**: cost still computes using
   `DEFAULT_LIST_MULTIPLIER`, with a one-shot `RuntimeWarning` recommending a cap.
4. **Default `MAX_QUERY_COST`** — `None` (opt-in), like the depth limiter.

## 6. Follow-ups (future)
- Per-**field** `complexity` via an `@cost`-style schema directive or a dedicated
  `CostField`, since graphene's `Field` can't take an arbitrary `complexity=`.
- Per-client budgets / leaky-bucket throttling with a recharging balance,
  surfaced in `extensions.cost.throttleStatus` (needs Redis + auth coupling).
