# Changelog

All notable changes to this library are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

!!! info "A fresh start"

    **`django-graphex`** is a new, rewritten library — the successor to
    `graphene-django-extras`. Its history starts at **1.0.0** below. If you are
    coming from `graphene-django-extras` 1.x, the [Migration Guide](migration.md)
    explains every change with before/after examples (install `django-graphex`,
    import `django_graphex`).

## 1.2.1 — 2026-06-12

### Security

- **Response-cache cross-user isolation** (`CACHE_ACTIVE`) — Cache keys now
  incorporate a per-identity token (`u{pk}` for authenticated users,
  `t{header_hash}` for token-auth, `anon` for anonymous). User A's cached
  response is never served to User B. Mutation invalidation advances a
  per-user version counter instead of `cache.clear()`, so one user's cache
  miss never evicts another user's valid entries. A malformed query now returns
  HTTP 400 even when `CACHE_ACTIVE=True` (parse guard). (#27, closes #11)
- **Subscriptions hardening** — Channel ownership is validated before a
  subscriber joins any group (prevents channel hijacking). Client-supplied
  `filters` keys are now checked against declared output fields (rejects
  arbitrary ORM field probing such as `password__contains`). Broadcast signal
  handlers are ASGI-safe (no deadlock under a running event loop). Percent-encoded
  index group names prevent ambiguous separators in filter values. A new
  `SUBSCRIPTIONS_CHANNEL_GUARD` setting (default `True`) controls the ownership
  check; set to `False` only when every worker shares the `"default"` cache
  backend. The channel registry is backed by `caches["default"]` so multi-worker
  deployments with a shared cache work without configuration. (#30, closes #14)
- **`MAX_BATCH_SIZE`** (default `10`) — Batch requests with more entries than
  this limit receive HTTP 400 before any query executes, capping amplification
  attacks. `None` restores the previous unlimited behavior. (#31, closes #15)
- **GraphiQL SRI pinning** — CDN assets (react@18.3.1, react-dom@18.3.1,
  graphiql@3.7.1) are pinned with SHA-384 `integrity=` and
  `crossorigin="anonymous"` attributes. A CDN compromise or silent version bump
  can no longer inject JavaScript to GraphiQL users. (#31, closes #15)
- **`@number` format-spec cap** — Client-supplied specs with width or precision
  > 100 raise a `GraphQLError` instead of allocating gigabytes of output.
  Normal specs (`.2f`, `,.2f`, `+.1%`) are unaffected. (#32, closes #16)

### Fixed

- **UniqueConstraint validation** — `model._meta.constraints` is now iterated
  for unconditional `UniqueConstraint` entries; violations return a structured
  `ErrorType` response instead of propagating an unhandled `IntegrityError`
  HTTP 500. Deduplication prevents double messages when a field has both
  `unique=True` and a `UniqueConstraint`. Conditional and expression-based
  constraints are intentionally left to DB enforcement. MTI `parent_link`
  fields are excluded from FK constraint checks, mirroring the guard already
  present in the type converter. (#29, closes #13)
- **`@skip` / `@include` honored by cost, depth, and optimizer** — Fields
  marked `@skip(if: true)` or `@include(if: false)` are excluded from cost
  counting, depth counting, and queryset optimization (no more false-positive
  `QUERY_TOO_COMPLEX` / `QUERY_TOO_DEEP` errors; skipped subtrees are not
  over-fetched). When the directive argument is an unbound variable, the
  selection is treated as *included* (conservative fallback). (#28, closes #12)
- **Pagination** — `page=0` now raises an explicit `GraphQLError` in all
  Python execution modes (the previous `assert` was a no-op under
  `python -O`). Tampered or corrupted cursors raise a clean
  `GraphQLError("Invalid cursor")` instead of HTTP 500. The `COUNT` query in
  `PageGraphqlPagination` is now conditional — it runs only for last-page
  navigation, removing one DB round-trip from every forward-paginated request.
  (#33, closes #17)
- **`@date(format: "iso")`** — Now emits real ISO 8601 (`2023-12-01T14:30:00`)
  instead of the previous locale-dependent month abbreviation format
  (`2023-Dec-01T14:30:00`) that was unparseable by `datetime.fromisoformat`.
  (#32, closes #16)
- **`@date` time-ago DST awareness** — `_format_time_ago` now computes "now"
  using `timezone.get_current_timezone()` instead of the fixed, DST-unaware
  `time.timezone` offset. Daylight-saving transitions no longer produce
  off-by-one-hour relative timestamps. (#32, closes #16)
- **`@base64` UTF-8 support** — `.encode("ascii")` raised `UnicodeEncodeError`
  on non-ASCII input; replaced with `.encode("utf-8")` / `.decode("utf-8")`.
  (#32, closes #16)
- **Custom-pk `delete` returns the correct `id`** — `mutation.py` and
  `types.py` now resolve via `old_obj._meta.pk.attname` instead of the
  hard-coded `old_obj.id`, so models with a custom primary key name (`pk_id`,
  `uuid`, etc.) return the right identifier in the delete payload. (#34, closes #18)
- **Enum unwrap in nested writes** — `_unwrap_enums` now uses
  `isinstance(value, enum.Enum)` instead of the fragile
  `"Enum" in type(value).__name__` substring check, matching the guard in
  `native/backend.py`. A class whose name contains "Enum" but is not an actual
  enum is no longer incorrectly unwrapped. (#34, closes #18)
- **Deterministic SDL field order** — `construct_fields` now sorts fields
  unconditionally. The previous `settings.DEBUG` gate meant dev and prod SDLs
  had different field orders, breaking snapshot tests, federation registries,
  and SDL diff tools. (#35, closes #19)
- **Introspection detection by AST** — Replaces the fragile
  `startswith("\n  query IntrospectionQuery")` string check with a proper AST
  walk (`_is_introspection_document`). Any query whose top-level selections are
  exclusively `__schema` or `__type` is detected as introspection regardless of
  formatting — fixing compact inline queries and `__type` variants. (#31, closes #15)

### Performance

- **Request-scoped field-map memoization** — `_relation_field_map` and
  `_concrete_field_map` accept a per-invocation `_cache` dict threaded through
  all walker functions by `_apply_optimizations`. Each `(model, map-kind)` pair
  calls `_meta.get_fields()` at most once per optimizer run (down from 6+ for a
  typical two-model query). (#36, closes #20)
- **Selection-aware mutation re-read** — `DjangoModelType.perform_mutate`
  locates the output-field sub-node in the mutation selection set and passes it
  through `_apply_optimizations` before the DB re-read, so forward-FK relations
  present in the mutation response are pre-joined via `select_related`. (#36, closes #20)
- **Single parse with `EXPOSE_QUERY_COST`** — `execute_graphql_request` accepts
  an optional `document=` kwarg; `GraphQLView.get_response` parses once and
  threads the document to both the executor and cost checker. With
  `EXPOSE_QUERY_COST=True`, `parse()` is called exactly once per request. (#31, closes #15)
- **One fewer `COUNT` per forward page** — `PageGraphqlPagination` now runs the
  `COUNT` query only when navigating to the last page (see Fixed above). (#33, closes #17)

### Packaging

- **`py.typed` shipped** — PEP 561 marker file added; mypy/pyright now resolve
  types from the installed package without additional configuration. (#37, closes #21)
- **sdist hygiene** — `[tool.hatch.build.targets.sdist]` allowlist ensures only
  `django_graphex/`, `tests/`, `docs/`, `README.md`, `LICENSE`, and
  `pyproject.toml` are included in the source distribution; `.claude/` and
  `specs/` are provably absent from the tarball. (#37, closes #21)
- **`__version__` from `importlib.metadata`** — Single source of truth: the
  installed package version is derived at import time; a `get_version(VERSION)`
  fallback handles editable/source installs. (#37, closes #21)
- **Dependency caps** — `channels-redis>=4.2,<5.0` and `daphne>=4.0,<5.0`
  prevent accidental upgrades to as-yet-untested major versions. (#37, closes #21)
- **Metadata fixes** — `Documentation` URL corrected; PyPy classifier removed
  (untested in CI); stale `README.rst` reference removed from `MANIFEST.in`.
  (#37, closes #21)

### Documentation

- **Overhaul** — All verified doc/code drift fixed: `only_fields`/`exclude_fields`
  kwarg names, `ListField()` `AttributeError` warning, `Registry` public import
  note, `DjangoUnionType` / `DjangoInterfaceType` API reference sections,
  `CACHE_ACTIVE` default clarification. Pydantic validation docs consolidated
  to `backends.md` (single home). Nested UPDATE worked examples, mutation
  complete example with client tab, `DjangoNestedListObjectField` documented in
  `fields.md`, pagination `page_size_query_param` semantics and cursor
  single-field design noted. Directive middleware required banner relocated.
  `docs/api/utils.md` removed. (#39, closes #23)
- **New caching guide** — `docs/usage/caching.md` documents key anatomy,
  per-user isolation, mutation invalidation, malformed-query handling, and
  `cache_key_prefix` customisation. Settings page expanded with security
  semantics. (#27, closes #11)

### Behavior changes

!!! warning "Upgrade actions required"

    Review each item below before upgrading. Most require no action; the ones
    marked **action required** need a one-time change in your project.

- **`MAX_BATCH_SIZE` default is now `10`** — Batch requests longer than 10
  entries are rejected with HTTP 400. Deployments that intentionally send large
  batches must set `DJANGO_GRAPHEX["MAX_BATCH_SIZE"] = None` (unlimited) or a higher
  integer. (#31, closes #15)
- **`@date(format: "iso")` output format changed** — The old output
  (`"2023-Dec-01T14:30:00"`) was locale-dependent and unparseable; the new
  output is real ISO 8601 (`"2023-12-01T14:30:00"`). If you have clients or
  tests that match the old locale-abbreviation format, update them. (#32, closes #16)
- **Schema SDL field order is now deterministic everywhere** — Previously
  `DEBUG=True` sorted fields but `DEBUG=False` did not, causing dev/prod
  divergence. The order is now consistently alphabetical in both modes.
  **Action required**: regenerate any SDL snapshot files once after upgrading.
  (#35, closes #19)
- **Cache key format changed** — The per-identity token added for cross-user
  isolation changes the shape of every cache key. The cache will be cold after
  upgrading; no stale cross-user entries will survive. No action required beyond
  accepting a one-time warm-up cost. (#27, closes #11)
- **`page=0` now raises a `GraphQLError`** — Previously `page=0` silently
  returned an empty result set (or crashed under `python -O`). Clients that
  sent `page=0` expecting an empty page must send `page=1` instead. (#33, closes #17)
- **Subscriptions guard is fail-closed** — `SUBSCRIPTIONS_CHANNEL_GUARD=True`
  (default) requires that the HTTP subscribe request and the WebSocket connect
  reach the same worker, or that all workers share the `"default"` cache
  backend (e.g. Redis). Single-worker / single-process deployments are
  unaffected. Multi-worker deployments must configure a shared cache or set
  `SUBSCRIPTIONS_CHANNEL_GUARD=False` to disable the guard. (#30, closes #14)
- **New settings introduced**: `MAX_BATCH_SIZE` (default `10`),
  `SUBSCRIPTIONS_CHANNEL_GUARD` (default `True`). Both live under the
  `DJANGO_GRAPHEX` dict in `settings.py`. (#31, closes #15; #30, closes #14)

## 1.2.0

### Added

- **`DjangoUnionType`** — a base for a GraphQL `Union` whose members are explicit
  `DjangoObjectType`s (`Meta.gfk_types = (MemberAType, MemberBType)`). Its main
  use is exposing a `GenericForeignKey` as a **typed** union instead of the flat
  `GenericForeignKeyType`, so clients select per-member fields via inline
  fragments. A GFK owner opts in with `Meta.gfk_unions = {"<fk_name>": TheUnion}`.
  Members are explicitly enumerated — the `django_content_type` table is never
  queried to discover them. A mandatory, provided `resolve_type` maps each row to
  its registered type (raising a descriptive `TypeError` on an unregistered
  model). Declaration order is load-bearing: **members → union → owner LAST**; a
  mis-ordered declaration logs a `WARNING` and falls back to `GenericForeignKeyType`.
  See [Types — DjangoUnionType](usage/types.md#djangouniontype-typed-genericforeignkey-targets).
- **`DjangoInterfaceType`** — a base for a GraphQL `Interface` that shares field
  declarations across multiple `DjangoObjectType` implementors (via the existing
  `Meta.interfaces` kwarg). Schema-level field sharing only — no new fetch path.
  See [Types — DjangoInterfaceType](usage/types.md#djangointerfacetype-shared-fields-across-types).
- **Per-content-type column narrowing for union GFKs (Django 5.0+)** — when
  `OPTIMIZE_ONLY_FIELDS` is on, a union-typed GFK is prefetched via
  `GenericPrefetch` with **one narrowed queryset per content type**, each
  `.only()`-restricted to that member's selected columns, batched across all
  parents (no N+1). On **Django < 5.0** the optimizer degrades gracefully to a
  single bare full-load `Prefetch` — it never imports `GenericPrefetch`, never
  narrows columns, and is never slower than before. Each distinct content type
  yields exactly one queryset; two members over one shared table are collapsed
  (merged `.only()` columns). See
  [Types — per-content-type narrowing](usage/types.md#per-content-type-column-narrowing-django-50).

### Fixed

- **Inline-fragment type-condition guard.** The query optimizer no longer
  descends into an inline fragment whose `type_condition` names a *different*
  concrete type than the one being walked, preventing field mis-attribution
  against the wrong model's relation map. Inert before this release (no
  polymorphic output types were exposed) but the correctness foundation the
  union/interface routing above builds on.
- **Nested writes now expose object inputs in the GraphQL schema.** A
  `DjangoModelMutation` (or `DjangoModelType`) declaring `Meta.nested_fields`
  reused the model's generic cached input type, so its nested relations were
  exposed as `[ID!]` and a client could not create children inline — even though
  the backend supported it. The mutation now builds a distinct nested-aware input
  (e.g. `PostCreateNestedCommentsType` with `comments: [CommentCreateInput!]`)
  while a sibling generic mutation on the same model keeps its `[ID!]` input
  unchanged, regardless of declaration order.

### Documentation

- Optimizer docs brought up to date with the 1.1.0 internals: documented
  `AnnotatedField`, the `OPTIMIZE_NESTED_PAGINATION` / `OPTIMIZER_SAFE_MODE` /
  `OPTIMIZE_ANNOTATED_FIELDS` settings, GenericForeignKey prefetch, and the
  safe-mode degrade. Corrected the nested-list pagination section, which
  previously said nested lists were sliced "in memory" — by default they are now
  sliced DB-side via `ROW_NUMBER()` window functions.

## 1.1.0

### Added

- **`OPTIMIZER_SAFE_MODE`** (default `False`) — opt-in coarse fail-safe: any
  exception raised inside the queryset-optimization block degrades the whole
  resolve to the un-optimized queryset and logs a `WARNING` instead of surfacing
  a 500. Default is fail-loud. See
  [Query Optimization — OPTIMIZER_SAFE_MODE](usage/query-optimization.md#optimizer_safe_mode-fail-safe-degrade).
- **GenericForeignKey / GenericRelation prefetch** — `GenericForeignKey` targets
  are added to `prefetch_related` (the parent's content-type-id and object-id
  columns are retained so the second query resolves) and `GenericRelation`
  reverse sides are prefetched and `.only()`-narrowed (their content-type /
  object-id attnames kept). See
  [Query Optimization](usage/query-optimization.md).
- **`OPTIMIZE_NESTED_PAGINATION`** (default `True`) — DB-side
  `ROW_NUMBER() OVER (PARTITION BY fk)` window slicing for reverse-FK nested
  paginated lists (`LimitOffsetGraphqlPagination` / `PageGraphqlPagination`),
  fetching only the requested page rows per parent in a single query, with a
  filter-aware `totalCount` carried per partition. Set `False` to fall back to
  the in-memory order+slice path. See
  [Nested Lists — Performance (N+1)](usage/nested-lists.md#performance-n1).
- **`AnnotatedField`** — a public, declarative GraphQL field backed by a Django
  ORM annotation
  (e.g. `comment_count = AnnotatedField(graphene.Int, Count("comments"))`),
  injected only when the field is selected in the query; gated by
  `OPTIMIZE_ANNOTATED_FIELDS` (default `True`). Forward-FK relations whose child
  selection contains an `AnnotatedField` are auto-promoted from `select_related`
  to `prefetch_related` (annotations can't cross a SQL JOIN). See
  [Fields — AnnotatedField](usage/fields.md#annotatedfield).
- **Per-field optimize hook** (`optimize_<field>`) on parent graphene types.
  Declare an `optimize_<snake_field>(queryset, info, **kwargs)` static method on
  the parent `DjangoObjectType` to customize the child queryset for a specific
  `DjangoNestedListObjectField`. The hook is applied after the optimizer builds
  the child queryset and before Django executes it — allowing you to add
  `select_related`, annotations, ordering, or any other queryset modification
  without disabling the global optimizer.  Hook kwargs include `filter_value`
  (the filter input or `None`) and `is_window` (`True` on the window-sliced
  path, `False` on all plain paths). When no hook is declared, behavior is
  byte-identical to the pre-1.1 baseline (purely additive). See
  [Nested Lists — Per-field optimize hook](usage/nested-lists.md#per-field-optimize-hook)
  for a worked example.

### Changed

- **BREAKING — minimum Django is now 4.2.** Django 4.0 and 4.1 (both end-of-life)
  are no longer supported. Projects pinned to those versions should stay on
  `django-graphex` 1.0.x.
- **BREAKING — public classes renamed (the `Extra` prefix is dropped).**
  `ExtraGraphQLSchema` → **`DjangoGraphQLSchema`** and
  `ExtraGraphQLDirectiveMiddleware` → **`GraphQLDirectiveMiddleware`**. Update your
  imports and the `GRAPHENE["MIDDLEWARE"]` dotted path to
  `django_graphex.GraphQLDirectiveMiddleware`. `DjangoGraphQLSchema` also avoids the
  name clash with `graphql.GraphQLSchema` from graphql-core.

## 1.0.0

The first release. A GraphQL + Django toolkit built directly on `graphene`
(graphene-core) and **Pydantic v2** — **no** `graphene-django`, **no**
`djangorestframework`, **no** `django-filter`.

### Model types, mutations & the native backend
- **`DjangoModelType` / `DjangoModelMutation`** — define a Django model once and get
  query, list and create/update/delete operations. Backed by `Meta.model` and a
  native **Pydantic v2** `SerializerBackend` that validates and persists with the
  Django ORM (field types, `max_length`, `Decimal` precision, required/nullable/
  defaults, `choices` → `Enum`, FK pk types, M2M as a list of pks), and runs the
  DB-level checks Pydantic can't — **FK existence**, **uniqueness** and
  `unique_together`. Supports partial updates.
- **Custom validation** without a serializer: declare DRF-style inline
  `validate_<field>(self, value)` and an object-level `validate(self, data)` directly
  on the class, and/or pass a `Meta.pydantic_model` with validators (they compose).
- **Atomic, relation-aware nested writes** — `Meta.nested_fields = {field: Model}`
  for forward FK, reverse FK and M2M children, written in one transaction (parent or
  child failure rolls everything back) with `field.subfield` error paths.
- **Custom output fields** declared on a `DjangoModelType` are honored, including
  their `resolve_<field>` resolver methods (and `source=`), inherited/overridable
  down the MRO.

### Filtering
- **Native `and` / `or` / `not` filtering** through a single nested `filter:`
  argument (a generated `<Model>FilterInput`), built on Django's ORM lookups + `Q`
  objects. Per-field lookups, relation descent (auto `.distinct()` on to-many joins),
  plain-pk / `UUIDField` filtering (`id: { exact/in }`), and `choices` filtered via
  their `Enum`. Declared with `Meta.filter_fields` (list or dict form); the common
  base lookup set is configurable via `COMMON_FILTER_LOOKUPS`. A `FilterBackend` seam
  keeps it swappable.
- Custom filtering logic via the `get_queryset` / `filter_queryset` hooks.

### Lists, pagination & performance
- Three paginators — **`LimitOffsetGraphqlPagination`**, **`PageGraphqlPagination`**
  and **`CursorGraphqlPagination`** (keyset cursor with a non-opaque `pageInfo`).
  Pagination/ordering live on the `results(...)` subfield; lists expose the uniform
  `results` / `totalCount` shape, including **nested** related lists.
- **Automatic N+1 query optimization** — `select_related` / `prefetch_related` /
  `.only()` derived from the GraphQL selection (incl. filtered nested-list
  prefetches), tunable with `OPTIMIZE_QUERYSET` / `OPTIMIZE_ONLY_FIELDS`.
- An effective `MAX_PAGE_SIZE` ceiling applied even when no page-size arg is sent.

### Subscriptions
- Real-time GraphQL **subscriptions over Django Channels 4** (optional
  `[subscriptions]` extra) with an in-house signal → `group_send` engine; configurable
  notification payload (id-only vs full) and value-scoped "indexed" groups.

### Permissions & security
- DRF-style **permission classes** (`BasePermission`, `IsAuthenticated`, `IsAdmin`,
  `IsAuthenticatedOrReadOnly`, …) usable on types, subscriptions and views.
- **Query depth limiting** (`MAX_QUERY_DEPTH` / `Meta.max_deep`) and **query cost
  analysis** (`MAX_QUERY_COST` / `Meta.complexity`, optional `extensions.cost`).
- **Security middlewares** — `DisableIntrospectionMiddleware`,
  `AuthenticatedFieldsMiddleware` — and `ExtraGraphQLSchema` for declaring private
  fields. Every execution error carries a machine-readable `extensions.code`.

### Views
- **`GraphQLView`** (response caching + depth/cost rules + `extensions.cost`),
  **`BaseGraphQLView`** (minimal, self-contained — no `graphene-django`), and
  **`AuthenticatedGraphQLView`** (endpoint-level auth gate via the library's own
  permission classes, no DRF). GraphiQL is served from a self-contained CDN page,
  overridable with `graphiql_template` for offline / strict-CSP setups.

### Directives
- Schema directives for string/number/list/date transforms (`@title_case`,
  `@snake_case`, `@slugify`, `@truncate`, `@round`, `@abs`, `@unique`, `@date`, …;
  custom directive names are snake_case), with directive arguments as GraphQL
  variables.

### Requirements
- **Python** 3.12–3.14, **Django** 4.2–6.0 (LTS 4.2 and 5.2 recommended for production), **graphene** >=3.3,<4, **pydantic** >=2,<3.

!!! note "Django range clarification"

    The 1.0.0 release initially listed Django 4.0–6.0 in its requirements. The
    true minimum is **Django 4.2** — Django 4.0 and 4.1 are end-of-life and were
    never tested. From 1.1.0 onward the supported range is explicitly 4.2–6.0.
