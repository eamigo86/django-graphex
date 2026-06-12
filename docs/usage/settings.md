# Settings

All configuration lives under a single `DJANGO_GRAPHEX` dict in your
Django settings. Every key is optional — unset keys fall back to the defaults
below.

```python
# settings.py
DJANGO_GRAPHEX = {
    # --- Pagination -------------------------------------------------------- #
    "DEFAULT_PAGINATION_CLASS": "django_graphex.paginations.LimitOffsetGraphqlPagination",
    "DEFAULT_PAGE_SIZE": None,
    "MAX_PAGE_SIZE": None,

    # --- Response cache ---------------------------------------------------- #
    "CACHE_ACTIVE": False,
    "CACHE_TIMEOUT": 300,
    "CLEAN_RESPONSE": False,

    # --- Queryset optimization (N+1) --------------------------------------- #
    "OPTIMIZE_QUERYSET": True,
    "OPTIMIZE_ONLY_FIELDS": True,
    "OPTIMIZE_NESTED_PAGINATION": True,
    "OPTIMIZER_SAFE_MODE": False,
    "OPTIMIZE_ANNOTATED_FIELDS": True,

    # --- Subscriptions ----------------------------------------------------- #
    "SUBSCRIPTION_SERIALIZE_DATA": False,

    # --- Security ---------------------------------------------------------- #
    "ALLOW_INTROSPECTION": False,
    "INTROSPECTION_ALLOW_SUPERUSER": True,
    "PROTECTED_FIELDS": (),

    # --- Query depth & cost ------------------------------------------------ #
    "MAX_QUERY_DEPTH": None,
    "MAX_QUERY_COST": None,
    "EXPOSE_QUERY_COST": False,
    "DEFAULT_LIST_MULTIPLIER": 10,
    "COST_PAGINATION_ARGS": ("limit", "page_size", "first", "last"),

    # --- Filtering --------------------------------------------------------- #
    "COMMON_FILTER_LOOKUPS": ("exact", "in", "isnull"),
}
```

## Pagination

| Setting | Default | Description |
|---|---|---|
| `DEFAULT_PAGINATION_CLASS` | `LimitOffsetGraphqlPagination` | Dotted path (or class) of the paginator applied to list fields that don't set their own. Set to `None` to disable default pagination (list fields then return a plain list). See [Pagination](pagination.md). |
| `DEFAULT_PAGE_SIZE` | `None` | Page size used when the client omits it. `None` = unbounded unless a paginator default applies. |
| `MAX_PAGE_SIZE` | `None` | Hard ceiling on the effective page size, applied **even when no page-size argument is sent**. `None` = no ceiling. |

## Response cache

| Setting | Default | Description |
|---|---|---|
| `CACHE_ACTIVE` | `False` | Enable response caching in `GraphQLView`. |
| `CACHE_TIMEOUT` | `300` | Cache TTL in seconds. |
| `CLEAN_RESPONSE` | `False` | Strip `null` values from the response payload. |

## Queryset optimization (N+1)

| Setting | Default | Description |
|---|---|---|
| `OPTIMIZE_QUERYSET` | `True` | Auto-apply `select_related` / `prefetch_related` derived from the query selection. See [Query Optimization](query-optimization.md). |
| `OPTIMIZE_ONLY_FIELDS` | `True` | Also narrow columns with `.only()` across the `select_related` span **and** inside each `Prefetch` child queryset. Set `False` if resolvers/properties read non-selected columns. |
| `OPTIMIZE_NESTED_PAGINATION` | `True` | DB-side `ROW_NUMBER()` window slicing for reverse-FK nested paginated lists (`LimitOffset` / `Page`). `False` = in-memory order+slice fallback. See [Nested Lists](nested-lists.md#performance-n1). |
| `OPTIMIZER_SAFE_MODE` | `False` | When `True`, any exception in the optimization block degrades to the un-optimized queryset and logs a `WARNING` (instead of a 500). Default fail-loud. See [Query Optimization](query-optimization.md). |
| `OPTIMIZE_ANNOTATED_FIELDS` | `True` | Inject `AnnotatedField` DB annotations only when the field is selected. Runtime kill-switch for annotation injection. See [Fields → AnnotatedField](fields.md#annotatedfield). |

## Subscriptions

| Setting | Default | Description |
|---|---|---|
| `SUBSCRIPTION_SERIALIZE_DATA` | `False` | When `False`, change notifications carry only `{"id": <pk>}`; `True` serializes the full instance through the subscription's backend. Per-subscription override: `Meta.serialize_data`. See [Subscriptions](subscriptions.md). |

## Security

| Setting | Default | Description |
|---|---|---|
| `ALLOW_INTROSPECTION` | `False` | Allow `__schema` / `__type` introspection (`DisableIntrospectionMiddleware`). |
| `INTROSPECTION_ALLOW_SUPERUSER` | `True` | Let superusers bypass the introspection block. |
| `PROTECTED_FIELDS` | `()` | Top-level field names requiring auth via `AuthenticatedFieldsMiddleware` (when not using `DjangoGraphQLSchema`). See [Security](security.md). |

## Query depth & cost

| Setting | Default | Description |
|---|---|---|
| `MAX_QUERY_DEPTH` | `None` | Global max nested-object depth (`DepthLimitValidationRule`). `None` disables the global limit; per-type `Meta.max_deep` still applies. |
| `MAX_QUERY_COST` | `None` | Reject queries whose estimated cost exceeds this (`CostLimitValidationRule`). `None` disables the budget. |
| `EXPOSE_QUERY_COST` | `False` | Add `extensions.cost` (`requestedCost` / `maxCost`) to responses. Combine with `MAX_QUERY_COST=None` for a non-blocking observation mode. |
| `DEFAULT_LIST_MULTIPLIER` | `10` | Cost multiplier for a list field whose page size is unknown (no literal/variable value and no `MAX_PAGE_SIZE` cap). |
| `COST_PAGINATION_ARGS` | `("limit", "page_size", "first", "last")` | Argument names treated as a list's page size when costing a field. |

See [Query Optimization](query-optimization.md) and [Security](security.md) for the depth/cost guides.

## Filtering

| Setting | Default | Description |
|---|---|---|
| `COMMON_FILTER_LOOKUPS` | `("exact", "in", "isnull")` | The **common base** lookup set every field receives when `Meta.filter_fields` declares it in **list form**. Text fields additionally get `icontains` / `istartswith`, and ordered (number/date/datetime) fields `gt` / `gte` / `lt` / `lte` / `range`. Dict-form declarations are explicit and ignore this. See [Filtering](filtering.md). |

## How settings are read

`DJANGO_GRAPHEX` is read through a small self-contained reader (no DRF
dependency). Changes are picked up automatically in tests via Django's
`setting_changed` signal, so `@override_settings(DJANGO_GRAPHEX={...})`
works as expected. An unknown key raises `AttributeError` to catch typos early.
