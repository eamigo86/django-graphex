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

## 4.1.0 — Unreleased

### Compatibility policy

4.1.0 is a minor release. The changes listed under "Behavior changes" alter wire
output, defaults, validation or schema-build behavior in ways a client or an
application may notice. They are treated as bug fixes: each corrects incorrect,
unsafe or inconsistent behavior of 4.0.0, and each has a migration note in the
[4.1 upgrade guide](UPGRADE-4.1.md). Everything else below is a fix or an addition that does
not change documented behavior.

### Behavior changes

Each item links to its migration note in the [4.1 upgrade guide](UPGRADE-4.1.md).

- Decimal output is a `Decimal` string and BigInteger fields are `BigInt` strings (outputs, inputs, filters) ([migration](UPGRADE-4.1.md#decimal-and-bigint-scalars-in-outputs-inputs-and-filters)).
- `DEFAULT_PAGE_SIZE` is `100` instead of `None`: unpaginated lists return the first 100 rows ([migration](UPGRADE-4.1.md#default_page_size-is-now-100)).
- A second public output type for one model in one registry raises `ImproperlyConfigured` ([migration](UPGRADE-4.1.md#one-public-output-type-per-model-and-registry)).
- Unknown or bare-string `only_fields`/`exclude_fields` raise on object types and write hosts ([migration](UPGRADE-4.1.md#strict-only_fields-and-exclude_fields)).
- Ambiguous or colliding `choices` enums raise ([migration](UPGRADE-4.1.md#ambiguous-and-colliding-choices-enums)).
- Reserved `__` `Literal` values and failing `get_fields()` stop the schema build ([migration](UPGRADE-4.1.md#reserved-double-underscore-enum-values)).
- Configuration checks raise `ImproperlyConfigured` instead of `AssertionError` ([migration](UPGRADE-4.1.md#configuration-checks-raise-improperlyconfigured)).
- Interface fields: only fields the interface declares use the explicit wire name ([migration](UPGRADE-4.1.md#interface-field-wire-names)).
- Mutable input defaults are copied per request; zero-argument factories run per input ([migration](UPGRADE-4.1.md#mutable-defaults-are-copied)).
- `not` inside a to-many relation filter means NOT EXISTS; separate `and` branches use separate rows ([migration](UPGRADE-4.1.md#not-inside-to-many-relation-filters)).
- An `or` operand holding a relation key next to a sibling relation key (or a negated operand) matches its own related row, like an `and` operand ([migration](UPGRADE-4.1.md#not-inside-to-many-relation-filters)).
- A `not` enclosing a to-many relation object is the exact complement of its same-row match; a double negation beside a sibling relation key uses its own related row ([migration](UPGRADE-4.1.md#not-inside-to-many-relation-filters)).
- `exact: null` selects NULL rows ([migration](UPGRADE-4.1.md#explicit-exact-null-selects-null-rows)).
- Numeric `DateField`/`DateTimeField` part filters take `Int` ([migration](UPGRADE-4.1.md#numeric-date-part-filters-take-int)).
- Generated writes run all model field validators (`blank`, `choices`, `max_length`, `validators`) ([migration](UPGRADE-4.1.md#model-field-validators-run-on-generated-writes)).
- `ATOMIC_MUTATIONS`/`ATOMIC_REQUESTS` roll back on GraphQL errors, on every database alias ([migration](UPGRADE-4.1.md#rollback-on-graphql-errors-on-every-alias)).
- Generated update/delete and nested writes honor the output type `get_queryset` ([migration](UPGRADE-4.1.md#update-and-delete-honor-the-output-type-scope)).
- Linked foreign-key, one-to-one and many-to-many ids must be visible; orphan adoption needs an update host ([migration](UPGRADE-4.1.md#linked-rows-must-be-visible)).
- A nested child `id` that matches no visible child is an error instead of creating a child ([migration](UPGRADE-4.1.md#nested-child-ids-that-match-no-visible-child)).
- Batches answer every item and isolate items in savepoints ([migration](UPGRADE-4.1.md#batches-answer-every-item)).
- `@replace` is capped at 1,000,000 characters; `MAX_DIRECTIVE_OUTPUT_TOTAL` bounds directive output ([migration](UPGRADE-4.1.md#output-caps-for-directives)).
- `Decimal` rejects `NaN`/`Infinity`; `@round` rounds half to even on `Decimal` ([migration](UPGRADE-4.1.md#decimal-and-bigint-scalars-in-outputs-inputs-and-filters)).
- Custom scalar coercion errors are client errors ([migration](UPGRADE-4.1.md#custom-scalar-errors-are-client-errors)).
- Subscription WebSocket handshakes without `graphql-transport-ws` are rejected before accept ([migration](UPGRADE-4.1.md#websocket-subprotocol-is-required)).
- Generated database error messages are generic ([migration](UPGRADE-4.1.md#database-error-messages-are-generic)).
- Primary-key tie-break can reorder tied rows ([migration](UPGRADE-4.1.md#ties-are-ordered-by-primary-key)).
- Cursors are validated by one rule on the database and in-memory paths: tampered cursors answer `Invalid cursor`, finite decimals above float range are valid, a naive datetime cursor is refused when the column is timezone-aware, and a `DecimalField` cursor with more fractional digits than `decimal_places` is refused ([migration](UPGRADE-4.1.md#tampered-and-unconvertible-cursors)).
- `page: null` on a page-number list is the first page instead of an error ([migration](UPGRADE-4.1.md#explicit-page-null-is-the-first-page)).
- Nullable columns order NULL last ascending and first descending in offset and page results ([migration](UPGRADE-4.1.md#nullable-ordering-in-offset-and-page-results)).
- `Meta.name` is honored as the GraphQL name of an `InputType`, and two types made by one factory are distinct types, not a re-executed declaration ([migration](UPGRADE-4.1.md#one-public-output-type-per-model-and-registry)).
- Automatic forward and reverse foreign-key output reads apply the destination `get_queryset`: a hidden author is `author: null`, reverse lists and `totalCount` hold only visible rows ([migration](UPGRADE-4.1.md#review-automatic-forward-and-reverse-fk-output-reads)).
- Automatic OneToOne and many-to-many output reads apply the destination `get_queryset` ([migration](UPGRADE-4.1.md#review-automatic-onetoone-output-reads); [migration](UPGRADE-4.1.md#review-automatic-m2m-output-lists-and-counts)).
- Filters that traverse a forward FK, forward OneToOne, reverse FK or M2M relation only match destinations the destination type's `get_queryset` shows ([migration](UPGRADE-4.1.md#review-filters-that-traverse-a-forward-fk); [migration](UPGRADE-4.1.md#review-filters-that-traverse-a-forward-onetoone); [migration](UPGRADE-4.1.md#review-filters-that-traverse-a-reverse-fk); [migration](UPGRADE-4.1.md#review-filters-that-traverse-an-m2m-relation)).
- Generic foreign key targets (flat and typed unions) are scoped by their output type; only target types present on the page run their hook ([migration](UPGRADE-4.1.md#genericforeignkey-targets-are-scoped)).
- Malformed model primary-key ids answer a field error with `extensions.code` `INVALID_ID` instead of `null` ([migration](UPGRADE-4.1.md#distinguish-malformed-ids-from-missing-objects)).
- Library transformation directives declare only the `FIELD` location, and `@date`, `@number` and `@currency` keep `null` ([migration](UPGRADE-4.1.md#move-transformation-directives-from-fragments-to-fields); [migration](UPGRADE-4.1.md#review-null-values-under-numeric-formatting-directives); [migration](UPGRADE-4.1.md#review-nullable-fields-formatted-with-date)).
- `@round`, `@floor`, `@ceil` and `@abs` compute exactly on `Decimal` and `BigInt` (`@round` rounds half to even) ([migration](UPGRADE-4.1.md#numeric-directives-on-decimal-and-bigint)).
- `MAX_DIRECTIVE_OUTPUT_TOTAL` is one budget per HTTP request shared by every batch item, also when `get_context` returns a dict or another mutable mapping; `COST_DIRECTIVE` is validated ([migration](UPGRADE-4.1.md#output-caps-for-directives)).
- Exact `set[...]`, `dict[str, ...]`, `Union[int, str]`, `Literal` and nested-list input annotations compile to typed GraphQL inputs, which changes the SDL ([migration](UPGRADE-4.1.md#input-annotations)).
- The enhanced `GraphQLView` answers an execution error through a non-null root field with HTTP 200 and `data: null` instead of HTTP 400 ([migration](UPGRADE-4.1.md#execution-errors-return-http-200)).
- A `query` that is not a string and `variables` that are not an object (including `[]`) answer a clean HTTP 400; a masked internal error outside field execution answers HTTP 500 ([migration](UPGRADE-4.1.md#malformed-requests-and-server-faults)).
- Unexpected resolver exceptions answer `DATA_ACCESS_ERROR` or `INTERNAL_SERVER_ERROR` with an `errorId` instead of raw text when `DEBUG=False`, also over SSE and WebSocket ([migration](UPGRADE-4.1.md#subscription-errors-are-masked-like-http-errors)); custom scalar `ValueError`/`TypeError` are client errors ([migration](UPGRADE-4.1.md#custom-scalar-errors-are-client-errors)).
- A subscription operation over the HTTP views answers HTTP 400 `SUBSCRIPTION_NOT_SUPPORTED` instead of `data: null` with HTTP 200 ([migration](UPGRADE-4.1.md#subscriptions-are-rejected-over-http)).
- Synchronous views answer a controlled HTTP 500 for async resolver, middleware and executor results ([migration](UPGRADE-4.1.md#synchronous-views-reject-async-results)).
- `MAX_UPLOAD_SIZE` limits each received multipart file, including unmapped parts ([migration](UPGRADE-4.1.md#multipart-upload-size-limit)).
- Negative `MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE` and `DOCUMENT_CACHE_MAXSIZE` raise, and the limits added in 4.1 accept only integers or `None` ([migration](UPGRADE-4.1.md#negative-operational-limits)).
- The request body cap runs before Django's CSRF check; the response cache stores only HTTP 200 data responses and its default key changes ([migration](UPGRADE-4.1.md#request-body-and-upload-limits); [migration](UPGRADE-4.1.md#document-caches-skip-very-large-documents)).
- Cost is checked before resolving and `pageSize` is costed; documents deeper than 100 object levels answer HTTP 400 `QUERY_TOO_DEEP` ([migration](UPGRADE-4.1.md#cost-is-checked-before-resolving-and-pagesize-is-costed); [migration](UPGRADE-4.1.md#structural-depth-ceiling)).
- Raw `JSON` rejects non-finite numbers in output (any container) and input; `CLEAN_RESPONSE` keeps `0` and `false` ([migration](UPGRADE-4.1.md#numbers-in-json-output)).
- `CLEAN_RESPONSE` keeps introspection nulls for fragment roots ([migration](UPGRADE-4.1.md#clean-responses-keep-introspection-nulls)).
- `subscription_scope` is intersected with the client `filter`; numeric snapshots compare by value ([migration](UPGRADE-4.1.md#subscription_scope-intersects-the-client-filter); [migration](UPGRADE-4.1.md#best-effort-notifications-and-exact-filters)).
- Automatic subscription notifications are best-effort and the drop log ends with `exception=<qualified chain>`; sync fan-out isolates each group; SSE leases tolerate renewal errors ([migration](UPGRADE-4.1.md#best-effort-notifications-and-exact-filters); [migration](UPGRADE-4.1.md#fan-out-isolation-and-sse-leases)).

### Added settings

- `OPTIMIZER_WORK_BUDGET` (default 2000) ([details](UPGRADE-4.1.md#optimizer-work-budget)).
- `DOCUMENT_CACHE_MAX_QUERY_LENGTH` (default 65536) ([details](UPGRADE-4.1.md#document-caches-skip-very-large-documents)).
- `MAX_DIRECTIVE_OUTPUT_TOTAL` (default 10,000,000) and `COST_DIRECTIVE` (default 0) ([details](UPGRADE-4.1.md#output-caps-for-directives)).
- Also `DEFAULT_PAGE_SIZE` now defaults to `100` (see Behavior changes).

### Security

- Fix: the parse and validation document caches no longer retain very large
  documents. They were bounded by entry count only, so `DOCUMENT_CACHE_MAXSIZE`
  documents near `MAX_REQUEST_BODY_SIZE` could pin gigabytes of ASTs. The new
  `DOCUMENT_CACHE_MAX_QUERY_LENGTH` setting (default 65536 characters; `None`
  removes the bound; a negative integer is rejected) keeps longer documents out
  of both caches: they are parsed and validated on every request. Smaller
  documents are cached as before. The bound also covers the parsed AST: a
  document is retained only when its AST has at most an eighth of that many
  tokens, and each cache holds at most that many tokens in total (about 40 MB
  of ASTs at the default), because a dense document such as `{ a a a ... }`
  parses to roughly 270 times the size of its text.

- Fix: a GraphQL error now rolls back writes on every database alias that is
  inside a transaction opened for the request, not only the default one. Each
  alias with `ATOMIC_REQUESTS` is marked for rollback (in a batch, its entry
  savepoint is), and `DATABASES[alias]["ATOMIC_MUTATIONS"] = True` now wraps
  that alias in `transaction.atomic()` for mutations. The global
  `ATOMIC_MUTATIONS` setting still covers only the default alias, and aliases
  outside an atomic block are untouched.

- Fix: `Meta.only_fields` and `Meta.exclude_fields` are validated on the write
  hosts too. `DjangoModelMutation`, `DjangoModelType`, `DjangoListObjectType`
  and `DjangoInputObjectType` accepted a typo (`exclude_fields = ("nmae",)`) or
  a bare string (`exclude_fields = "name"`) in silence, so the column the
  developer meant to hide stayed writable. They now raise
  `ImproperlyConfigured` at class creation with the same message
  `DjangoObjectType` gives.

- Fix: the request body cap now runs before Django's CSRF check. A multipart
  POST carrying a `csrftoken` cookie was parsed (and its files spooled to disk)
  by that check before `MAX_REQUEST_BODY_SIZE` could answer 413. `dispatch` now
  checks the cap first, so an oversized body is refused unparsed whether or not
  the client holds the cookie. CSRF behavior is unchanged.
  A `BaseGraphQLView` mounted behind Django's `CsrfViewMiddleware` is still
  parsed by the middleware first; bound the body with a proxy limit or a
  body-size middleware placed before it.

- Fix: bound the total text that directives add to one response. Only a
  per-field cap existed (`MAX_REPLACE_OUTPUT_LENGTH`), so many aliases and rows
  each under the cap could still produce hundreds of megabytes. New setting
  `MAX_DIRECTIVE_OUTPUT_TOTAL` (default 10,000,000 characters per request,
  `None` disables) charges every directive for the text it adds; once spent,
  further directive uses become field errors. New opt-in setting
  `COST_DIRECTIVE` (default `0`, so existing costs do not change) adds cost per
  custom directive use so aliases x directives counts toward `MAX_QUERY_COST`.

- Apply the target output type's `get_queryset` to flat `GenericForeignKey`
  targets in every schema. Without `PERMISSION_SCOPED_SCHEMA` the flat
  `GenericForeignKeyType` still returned `appLabel`, `modelName` and `id` of a
  target that its registered output type hid; it now resolves to `null`, like
  the permission-pruned field already did, and the pruned and full schemas use
  one rule. The check is batched in one `GenericPrefetch` for optimized and list
  reads (query counts do not grow with the number of owners); a resolver
  without it issues one membership query per target of a type that overrides
  the hook. Targets of unregistered models, and types keeping the default
  hook, are unchanged.

- Apply a member type's `get_queryset` to typed `GenericForeignKey` union
  targets. A `Meta.unions` union returned the target of any member in full even
  when that member type's hook hid the row. A hidden target now resolves to
  `null`, like a missing one. Optimized and list reads scope the targets in one
  batched `GenericPrefetch` per request, stored under a dedicated attribute so a
  cached unscoped target is never trusted, so query counts do not grow with the
  number of owners; only the union's own member models are scoped, and a member
  with a hook loads full rows instead of the narrowed `.only()` columns. A
  resolver without that prefetch issues one membership query per target of a
  type that overrides the hook. A sliced hook, or two scoped members sharing a
  content type, resolves per row instead. Types keeping the default hook are
  unchanged.

- Require a child update host to adopt an existing reverse `OneToOneField`
  orphan by ID. Naming the ID of a child whose nullable one-to-one key is null
  in a parent update re-parented and rewrote that child with no host check and
  no scope, because the adoption guard only covered reverse `ForeignKey`. It
  now follows the same rule: a registered child `DjangoModelType` or
  `DjangoModelMutation` serving update must exist, and its scope and
  permissions apply. Children the parent already owns and new children are
  unchanged.

- Scope forward `OneToOneField` links like `ForeignKey` links. A generated
  create or update could point a one-to-one field (scalar ID or nested id-only
  payload) at a row hidden by the destination output type's `get_queryset`, and
  a nonexistent ID answered differently, so it was also an existence oracle.
  Hidden and nonexistent IDs now return the same `Invalid pk ... object does
  not exist.` relation error. The ID membership check also runs one query per
  relation instead of one per ID (200 tags cost 209 queries before), and the
  nested M2M existence and already-linked checks are batched.

- Make the depth and cost walkers iterative. `DepthLimitValidationRule` and the
  cost estimator recursed once per fragment link and per nesting level, so an
  acyclic chain of ~1000 fragments (~38 KB) raised `RecursionError` and answered
  HTTP 500. They now use an explicit stack with the same verdicts, messages and
  memoization. Documents that exceed graphql-core's own recursive parser or
  validator (about 250 nested selection sets, several hundred chained
  fragments) are answered as HTTP 400 `QUERY_TOO_DEEP` instead of 500, on the
  HTTP view and the subscription transports; resolver errors are unaffected.
  `DepthLimitValidationRule` also enforces a hard ceiling of 100 nested object
  levels even when `MAX_QUERY_DEPTH` is unset or larger: Python's stack cannot
  execute deeper documents (with data, requests fail with an internal error
  from about 130 levels), and fragments hide depth from the parser. Deeper
  documents get HTTP 400 `QUERY_TOO_DEEP` instead of an internal error.

- Bound the queryset optimizer for fragments reached through distinct relation
  paths. Memoizing by selection context only helped a fragment repeated in the
  same context; a document such as `author { ...A }` / `coAuthors { results {
  ...A } }` where each fragment reaches the next through four relations
  describes 4**n distinct `select_related`/`prefetch_related` lookups, so a
  ~1 KB anonymous request took more than 20 s of CPU on an empty database. The
  new `OPTIMIZER_WORK_BUDGET` setting (default 2000, `None` disables) caps the
  selection contexts each optimizer walker expands per operation execution, including the
  scoped to-one walker that ran a second exponential pass. The budget is shared
  by every root field of the execution. Once spent, the root field is resolved
  without the optimizer plan, exactly like `OPTIMIZE_QUERYSET = False` (the
  data is identical and scoped relations stay scoped; a truncated plan is never
  kept because it could drop the ordering, limit or offset of nested lists); a
  DEBUG record names the walker.

- Scope automatic declared and reverse M2M output lists with the destination
  type's request-specific `get_queryset`. A visible parent retains its row,
  while hidden linked targets leave `results` and the pre-pagination
  `totalCount`; an empty or hidden-only relation returns `[]` and `0`.
  Optimized reads use a scoped prefetch rather than trusting an unrelated
  relation cache. Explicit resolvers, through-model access rules, custom
  filters, and ordering are not changed.

- Apply the destination type's request-specific `get_queryset` to automatic
  forward and reverse OneToOne output reads. A visible parent keeps its row
  while a hidden linked destination resolves to `null`; genuine absent
  relations and the nullable output shape are unchanged. Scoped to-one reads
  are batched for ordinary list traversal, including when queryset optimization
  is disabled. Explicit resolvers and M2M output reads have separate rules.

- Scope nested forward OneToOne destination-field filters to the destination
  type's request-specific `get_queryset`. A visible profile cannot match a
  hidden linked user's fields; real absent OneToOne NULL matches, unrelated
  Boolean branches, and direct source-column ID lookups keep their existing
  meanings. Reverse OneToOne filters already used the destination hook.
  Automatic OneToOne output reads have the separate rule above; custom filters
  and ordering are unchanged.

- Scope forward and reverse many-to-many filters to each destination type's
  request-specific `get_queryset`. A linked hidden target no longer satisfies
  a nested field or target-ID predicate. One relation object retains one
  visible target witness, separate `and` branches may use different targets,
  and `not` complements the matching-parent set. Empty and absent-target
  predicates keep their existing meanings. M2M output reads have the separate
  rule above; through models, custom filter bodies and ordering are unchanged.

- Scope public nested forward-FK filters to the destination type's
  request-specific `get_queryset`. Hidden target rows no longer make a
  visible source row match; each hop in a forward-FK chain is checked.
  Real absent-FK NULL matches, unrelated Boolean branches, and direct source
  FK-ID predicates retain their existing meanings. This does not scope
  custom filter bodies or ordering. Forward OneToOne
  and M2M filters have separate bounded rules.

- Scope public reverse-FK filters to the child type's request-specific
  `get_queryset`. One visible child must satisfy each grouped predicate;
  separate `and` branches retain independent visible witnesses, and `not`
  complements the matching-parent set. Direct reverse-child IDs are scoped,
  unlike direct forward source FK IDs. Default and named output accessors now
  resolve declarations using their ORM query names without reopening a
  declared or pruned relation. M2M has the separate bounded rule above;
  forward OneToOne has the separate bounded rule above.

- Apply the destination type's `get_queryset` hook to automatic forward-FK
  and reverse-FK output reads. Hidden nullable FK targets now resolve to
  `null`; reverse-FK results, windows, and `totalCount` include only visible
  rows. Optimized scoped FK reads stay batched, while disabling optimization
  can add per-parent scope queries. Automatic OneToOne has the separate rule
  above; M2M outputs have their own rule, while custom resolvers and other
  joined filters remain outside this FK rule. Clients previously relying on expanded
  hidden rows should review their destination hooks before upgrading.

- Replace unexpected resolver-exception details on built-in HTTP views when
  `DEBUG=False` with safe `DATA_ACCESS_ERROR` or `INTERNAL_SERVER_ERROR`
  diagnostics and an opaque `errorId` correlated with restricted server logs.
  Clients must stop relying on raw exception text or custom extensions from
  these failures. Deliberate `GraphQLError`, validation errors, existing
  generated-mutation errors, `DEBUG=True`, and WebSocket/SSE formatting are
  unchanged; custom `format_error` overrides remain application-owned.

- Reject a selected GraphQL operation before resolution when its real,
  GraphQL-coerced request variables or defaults put it over `MAX_QUERY_COST`,
  including document-validation cache hits. A variable page size that previously
  passed the static fallback estimate may now return HTTP 400 / `QUERY_TOO_COMPLEX`.
  Conservative static validation remains: a cheap variable cannot undo an
  earlier fallback-based rejection. `MAX_PAGE_SIZE` is still optional, though
  recommended for unbounded lists; the public cost model/API is unchanged.
  A mutation refused before resolver execution does not invalidate a warmed
  response cache; an earlier executed mutation in a non-atomic batch still does.

- Hide table, column, and constraint details from unclassified Django
  `IntegrityError` failures in generated create/update/delete GraphQL fields,
  including nested writes. Clients now receive the fixed top-level message
  `A database constraint prevented this operation.` instead of raw database
  text; the field remains `null`, with its GraphQL path and normal HTTP shape.
  Nested and atomic sibling rollback remain intact. Mapped unique/FK field
  errors stay structured, direct backend exceptions stay unchanged, and no
  general constraint validation or upsert is added.

- Replace Django collector details in generated delete `PROTECT`/`RESTRICT`
  failures with a generic GraphQL execution error. Both mutation frontends keep
  the existing field-null, HTTP and atomic rollback behavior; blocked deletes
  do not become `ok: false` payloads. Clients relying on the old collector
  message must migrate to the generic error and field path.

- Redact the whole flat `GenericForeignKeyType` target to `null` in
  permission-pruned schemas when the actual target model's read permission is
  absent or its registered row hook excludes the row. The flat SDL, unpruned
  schemas, and typed GFK unions are unchanged. Schema-variant and HTTP response
  caches now include all grants only for schemas with the native flat fallback,
  so target permission grants and revocations do not reuse stale responses.
  Apps that relied on source-only permission for flat target metadata must
  grant target read permission and review target row scopes.

- Require a registered update-serving child write host to adopt an existing
  nullable reverse-FK orphan by ID through a generated parent update. The
  host's existing scope and permissions apply; without one the mutation
  returns a structured error and rolls back. New children, already-owned
  children, and the different-parent guard are unchanged. Applications that
  intentionally adopted hostless or read-hidden orphans must register an
  appropriate child update host and review their authorization policy.

- Check generated create/update foreign-key and many-to-many ID links against
  the request schema's destination `DjangoObjectType.get_queryset` when it is
  overridden. Hidden and nonexistent target IDs now share the ordinary
  structured invalid-pk error before persistence, including nested link
  operations whose extra attributes are ignored. Actual child writes and
  unscoped/default-hook paths retain their previous behavior and query
  cost; child-write permissions, relation reads, and ORM filter joins are
  unchanged. Apps that intentionally link read-hidden rows must migrate their
  destination scope or link workflow. Destination scopes may use callable hooks,
  duplicate-producing JOINs, ordered slices, or same-table proxies; membership
  follows the actual returned queryset window. A queryset for a different
  concrete table is rejected.

- Reject bare-string and unknown `DjangoObjectType.Meta.only_fields` or
  `exclude_fields` selectors at class definition, before registry mutation.
  Previously a typo could leave a sensitive model field published. Valid model,
  reverse-relation, private, and declared custom field names remain accepted;
  declared custom fields still compile independently of model projection.

- Roll back default-database writes when GraphQL execution returns errors
  under `ATOMIC_MUTATIONS=True`, and mark Django `ATOMIC_REQUESTS` requests
  for rollback on those errors or the established mutation error flag.
  Rolled-back writes no longer advance the GraphQL response-cache version;
  durable non-atomic writes still invalidate it. Structured native mutation
  `ok: false` data remains distinct from a GraphQL execution error.

- Limit each `@replace` result to 1,000,000 Unicode characters by default,
  predicting Python's nonoverlapping replacement length before allocation.
  Over-limit results now produce a GraphQL field error, including when no
  replacement occurs; a result at the cap remains valid. Configure
  `MAX_REPLACE_OUTPUT_LENGTH` with a positive integer or `None` to restore
  uncapped legacy behavior. This is a per-result cap, not a query-wide quota,
  and does not change other directives or the HTTP body limit.

- Enforce the existing `MAX_REQUEST_BODY_SIZE` POST limit before the cache-active
  view parses a GraphQL document or accesses parse, validation, or response
  caches. Oversized requests keep their HTTP 413 response; the configured limit,
  default, valid/cache-hit behavior, and multipart measurement remain unchanged.

- Bound optimizer planning for valid repeated-fragment graphs to distinct
  model, type, and relation-path contexts. Existing projections, prefetches,
  annotation promotion, ordered plan/alias precedence, GraphQL results, and SQL
  query counts remain unchanged.

- Reject cyclic named-fragment graphs before cost/depth expansion. Direct
  `analyze_cost()` now raises `GraphQLError` for a cyclic document rather than
  returning a truncated cost, including cycles outside the selected operation;
  validate first or catch the error. Acyclic costs and depth verdicts are unchanged.

- Nested child payloads that carry an `id` no longer create a child when the
  `id` does not resolve to a visible child. A hidden `id` (outside the child's
  host or output scope) answered `<Model> with id N does not exist.` while a
  nonexistent `id` silently created a new child, so a client could probe which
  ids exist. Both now return the same error and write nothing, for reverse
  `ForeignKey`, reverse `OneToOneField` and many-to-many nested payloads
  (including models with a natural primary key). Payloads without an `id` still
  create, and children the parent already owns still update. Clients that
  relied on sending an unknown `id` together with child data to create a row
  must omit the `id`.

- Generated `update` and `delete` (`DjangoModelMutation` and `DjangoModelType`)
  now also require the target row to be visible in the model's registered
  output type: when that `DjangoObjectType` overrides `get_queryset`, a row it
  hides on reads can no longer be edited or deleted by id (`postUpdate` and
  `postDelete` returned `ok: true` for a hidden row). The host scope and the
  output scope are intersected in one query, a hidden row answers exactly like
  a nonexistent id. Nested child payloads that write fields of an existing
  child (reverse FK, reverse OneToOne, M2M, or a forward relation carrying the
  current target's id plus data) follow the same rule with the child's output
  type; an id-only re-send of a forward current target is not re-scoped.
  Types keeping the default hook add no query. Code that relied on writing rows its
  public type hides must widen that type's `get_queryset` (or register a
  broader type) for the schema that serves the write.

### Fixes and changes

- Mask exceptions raised while iterating a subscription source. An async-generator
  `subscribe` that raised on iteration, a channel-layer error or a scope lookup
  failure reached the client as `GraphQLError(str(exc))`, which counted as
  deliberate, and was logged by the transport. SSE and WebSocket now route it
  through `security.format_client_error`: `INTERNAL_SERVER_ERROR` or
  `DATA_ACCESS_ERROR` with an `errorId` and exactly one ERROR record. A
  `GraphQLError` raised on purpose keeps its message. The same applies to any
  other failure of a WebSocket operation before it streams.
- Keep rejected subscriber filters public over SSE and WebSocket. The subscribe-time
  filter validation raised a plain `ValueError` for client input (an
  undeclared field, a lookup the ORM refuses such as `tags: {iexact: 1}`), which
  the new transport masking turned into `INTERNAL_SERVER_ERROR` with an ERROR log
  per attempt. It now raises `ClientFilterError`, a `GraphQLError` (and still a
  `ValueError`), with the same message.
- Mask unexpected exceptions over SSE and WebSocket like the HTTP view. A
  `subscribe` or event resolver raising `RuntimeError("password=...")` sent that
  text to the client. The classification and masking now live in one function,
  `security.format_client_error`, used by the HTTP view and both transports at
  every point they format an error; the log message names the transport. An
  undecodable WebSocket frame still closes `4400` but is logged at DEBUG, not as
  an ERROR traceback.
- Answer variables too deep to coerce over subscriptions with `QUERY_TOO_DEEP`.
  The transports build the executor, which coerces the variables, outside any
  guard, so SSE let a bare `RecursionError` escape and WebSocket sent its raw
  message with no code. Both now frame the same coded error as HTTP ("Variables
  are nested too deeply to be coerced."), unlogged and without an `errorId`; a
  `RecursionError` raised by a subscribe resolver is unchanged.
- Keep the per-execution directive budget and optimizer work state alive as long
  as their execution. They were found in a 1024-entry LRU keyed by variable and
  root identity, so a still-running (for example async) execution lost its
  counter after 1024 other executions and restarted from zero. State is now keyed
  weakly by the graphql-core executor. The events of one subscription share their
  stream's executor, so that entry also remembers the current event's root value
  and starts a fresh counter for the next one.
- Share the directive output budget across a batch when `get_context` returns a
  dict. `bind_request_budget` swallowed the `TypeError` of a context without an
  instance `__dict__`, so each item got its own budget; a mutable mapping now
  carries it under the private key `_graphex_request_budget`.
- Make the cursor parity matrix independent of the database pk sequence. A decimal
  boundary such as `1e-999` compared as zero on SQLite but exactly in memory, so
  the pages differed whenever row pks were not `1..5`; both paths now refuse a
  `DecimalField` boundary that no stored value can equal.
- Correlate reverse-FK filters on the column the foreign key targets. A child FK
  with `to_field` pointing at a non-pk column was compared with the parent `pk`, so
  `not`, `or` and destination-scoped relation filters returned the wrong parents
  whenever the parent pk and that column differ. They now match Django's
  `exclude()` and `filter()`.
- Bound the cost of `@round` with a huge negative precision on an `Int` or `BigInt`.
  `round(n, -k)` built `10 ** k`, so `@round(precision: -10000000)` on `1` took
  seconds and `-2147483648` could exhaust memory. A whole number far below half of
  `10 ** k` now answers `0` at once; every other result is unchanged and still
  rounds half to even.
- Refuse subscription operations over the HTTP views. A subscription POSTed to
  `/graphql/` resolved to `{"data": {"field": null}}` with HTTP 200, no error and
  no hint. `GraphQLView`, `BaseGraphQLView` and `AuthenticatedGraphQLView` now
  answer HTTP 400 with the error `Subscriptions are not supported over HTTP; use
  the WebSocket or SSE transport.` and `extensions.code`
  `SUBSCRIPTION_NOT_SUPPORTED`. Only the selected operation is judged, and each
  subscription item of a batch gets its own error entry.

- Make a `not` that encloses a to-many relation object the exact complement of
  that object's match. `{ not: { tags: { and: [z, x] } } }` excluded posts that
  had a `z` tag and a different `x` tag because the ORM tests each criterion of
  an `exclude()` separately; it now compiles to `NOT EXISTS` of one tag
  satisfying every same-row criterion, and `not: { not: { tags } }` beside a
  sibling relation key uses its own related row. The seeded oracle test now
  generates these shapes.

- Validate cursor boundaries with one rule on the database and the in-memory
  path. The database path refused finite decimals above float range (`1e999`,
  400-digit values) that the in-memory path accepted, and accepted a naive
  datetime cursor (with a Django naive-datetime warning) that the in-memory
  path refused. Both now use one coercion function: numbers must be finite
  (checked on the parsed value, not through a float conversion; magnitudes
  beyond ten to the 10,000th are refused), and a datetime or time must be
  timezone-aware exactly when the column is. A parity matrix test pins it.

- Give `or` operands over a to-many relation their own related rows, like `and`
  operands. `{ or: [{ tags: x }], tags: z }` returned nothing for a post tagged
  `x` and `z` because both criteria shared one join, while
  `{ and: [{ tags: x }], tags: z }` matched it; an `or` of a relation operand
  and a negated one had the same flaw. Each such operand now compiles to its
  own `EXISTS`. A seeded randomized test checks and/or/not/relation mixes
  against a plain-Python oracle.

- `subscription_scope` now intersects with the client `filter` instead of
  replacing it. A subscriber asking for `filter: {status: {exact: DRAFT}}`
  under a scope of `PUBLISHED` used to receive the published rows it had
  filtered out; an event is now delivered only when it matches both. A client
  value that contradicts the scope on the same key joins no group and delivers
  nothing. Subscriptions without a scope are unchanged.

- Compare numeric subscription snapshots with typed exact filters by value. A
  float snapshot on a DecimalField no longer dropped against `Decimal("1.50")`
  while an integer matched, and `2**53 + 1` now matches `float(2**53)`. When a
  float is on either side the other operand is rounded to the nearest float
  first, like a float column; bool, NaN, Infinity and integers beyond the
  float range still never match.

- Honor the retry delay of the first in-stream SSE lease renewal. A failed
  first renewal waited the full 15 seconds instead of the documented five
  before the next attempt.

- Harden the shared SSE lease Redis client. It now pings idle pooled
  connections (`health_check_interval`) and enables TCP keepalive, and lease
  admission retries once, with a fresh token, after a connection error so a
  stale pooled connection no longer answers the first stream with HTTP 503.

- Answer variables too deep to coerce with HTTP 400 `QUERY_TOO_DEEP`. Roughly
  600 nested `and`/`or` levels in variables raised a `RecursionError` during
  coercion, answered as 400 `INTERNAL_SERVER_ERROR` with an ERROR traceback in
  the log. A bare `RecursionError` that escapes before any field ran is now a
  client error like an over-deep document; one raised by a resolver keeps its
  path, mask and log.

- Answer over-deep subscription documents with `QUERY_TOO_DEEP` on both
  transports. They parsed with plain `parse`, so SSE answered the plain-text 400
  `GraphQL syntax error: maximum recursion depth exceeded` and WebSocket sent
  `Syntax error: <raw exception>`, neither with a code. Both now share the HTTP
  view's parse wrapper: SSE answers a JSON 400 with `extensions.code`
  `QUERY_TOO_DEEP`, WebSocket sends an `error` frame with the same code, and
  neither echoes raw exception text (a non-string `query` gets a generic
  message).

- Include the GET `pretty` parameter in the default response-cache key. The view
  pretty-prints the body when `?pretty=` is set, but the key ignored it, so a
  pretty-printed cached response could be served to a compact request (and the
  reverse). Compact requests keep their previous key. Also refresh the stale
  comments around the request-body cap now that it runs before the CSRF check.

- Validate the type of the newer limits. `DOCUMENT_CACHE_MAX_QUERY_LENGTH` and
  `OPTIMIZER_WORK_BUDGET` only had a range check, so `"65536"` raised a
  `TypeError` on every request and `True` silently meant 1. Like
  `MAX_DIRECTIVE_OUTPUT_TOTAL`, they now raise `ImproperlyConfigured` when read
  unless the value is an integer or `None`.

- Answer server faults outside field execution with HTTP 500. The status rule
  was "an error without a path means 400", so a failing hook such as
  `get_root_value`, or any other masked internal error raised before a field
  ran, answered 400 as if the client were at fault. A masked internal error now
  answers 500; syntax, validation and variable-coercion errors stay 400, and
  field errors stay inside HTTP 200.

- Answer malformed request shapes as clean 400s. A `query` that is not a string
  (`{"query": 123}`, `{"query": ["a"]}`) or `variables` that are not a JSON
  object (`"variables": "[1]"`, `[1]`) answered 400 `INTERNAL_SERVER_ERROR` with
  an `errorId` and an ERROR traceback in the log, which let any client flood the
  log. They now answer `Must provide query string.` or `Variables must be a
  JSON object.` with HTTP 400 and no ERROR log, on GET, JSON, form and batch
  requests (a batch item fails alone).

- Keep coercion-time server faults internal. A scalar that raised any exception
  while coercing variables or literals (a database outage inside an id-lookup
  scalar, say) was answered as a silent client error with no log. Only
  `GraphQLError`, `ValueError` and `TypeError` (and subclasses) raised before
  execution are client errors now; any other exception keeps the production
  mask, the `errorId` and the ERROR log.

- Reject non-finite floats inside every container the JSON encoder emits. The
  `JSON` scalar's finite-number check only looked inside `dict` and `list`, so
  `(1, nan)`, an `OrderedDict` holding `inf`, a namedtuple or a set still
  produced `NaN`/`Infinity` in the response. Any mapping, non-text sequence and
  set is now traversed (iteratively, and cycle-safe).

- Bound the document caches by retained AST size. `DOCUMENT_CACHE_MAX_QUERY_LENGTH`
  capped the query text, but a 64,000-character `{ a a a ... }` parses to about
  17 MB, so 128 entries could pin gigabytes per worker. A document is now cached
  only when its AST has at most an eighth of that many tokens, and each cache
  retains at most that many tokens in total (about 40 MB at the default,
  least recently used entries evicted first). The validation cache also keys on
  a digest of the query text instead of the text itself.

- Stop caching the stack-depth verdict. A validation `RecursionError` answers
  `QUERY_TOO_DEEP`, but that outcome depends on how deep the calling thread
  already was, not on the document; it was stored in the validation cache and
  then served to every later caller of the same query. It is no longer cached.

- Validate `COST_DIRECTIVE`. A negative, fractional, boolean or non-number
  value was silently truncated or clamped; it now raises
  `ImproperlyConfigured` when the setting is read, like the other cost limits.
  A directive on a scalar list field is costed once because it runs once on
  the whole list; this is now documented and pinned by a test.

- Fix the scope of the directive output budget. `MAX_DIRECTIVE_OUTPUT_TOTAL`
  was counted per execution, so a 10-item batch got ten times the budget; it is
  now per HTTP request (the GraphQL view binds one counter to the request, and
  every batch item draws from it). A subscription event keeps its own budget.
  Executions the view does not start use a per-execution counter in one bounded
  table that no longer evicts live counters at 64 concurrent executions (limit
  1,024), and the counter is read from the context's own `__dict__`, so a
  context whose `__getattr__` invents values (a mock) can no longer disable it.
  The optimizer work budget shares the same table and stays per execution
  (each batch item plans its own selection); it also no longer depends on the
  context type.

- Fix `@round` on `Decimal` values. The precision clamp turned a zero or
  negative precision into a positive one (`0.0004` gave `0.00` instead of `0`,
  `1E-30` with precision 5 gave 28 decimals). It now quantizes half to even to
  exactly the requested precision in a context sized to the result, returns an
  integral value for a precision of zero or below, and never raises
  `InvalidOperation`. `@floor`, `@ceil` and `@round` no longer expand a value
  with a huge exponent into a giant integer (quadratic time, or a `ValueError`
  past 4300 digits): past the Decimal scalar's plain-notation bound the value
  is already whole and is returned unchanged in constant time.

- Fix the same-declaration rule of the one-public-output-type guard. Two types
  made by one factory function share module and qualified name, so they were
  taken for a re-executed declaration and the broader variant silently became
  the canonical type of the model. A type now replaces a stale one only when
  module, qualified name and public GraphQL name all match; factory variants
  with different names raise like any two distinct types. `InputType` honors
  `Meta.name` as its GraphQL name and keeps factory-made inputs with different
  names registered instead of dropping the earlier one.

- Fix: nested and plain id links are checked in chunks below the database's
  bound-parameter limit, so a list of 32,767 or more ids no longer fails with
  `too many SQL variables` on SQLite. An id beyond the database integer range
  (for example `author: {id: "99999999999999999999999"}`) answers `Invalid pk
  ... does not exist` as a field error instead of a top-level error, and a key
  that a case-insensitive collation returns in another letter case counts as
  existing.
- Fix: a many-to-many or forward foreign-key `id` link hidden only by the
  child's update host is refused exactly like a nonexistent id (it used to be
  linked, which revealed which ids exist). Re-sending only the `id` of a forward
  relation's current target is now a true no-op: the row is not saved and no
  `post_save` fires.

- Fix: a flat or typed-union `GenericForeignKey` selection only runs the
  `get_queryset` hook of a target type some owner on the page points to. A hook
  of an unrelated type (for example one that raises for anonymous users) no
  longer nulls the whole list and no longer costs a call. A hook that raises
  for a present target still fails the field.

- Fix: the raw `JSON` scalar no longer emits `NaN` or `Infinity` in its output.
  A resolver or `JSONField` value that is or contains a non-finite float, at any
  depth, is now a field error (`JSON cannot represent non-finite numbers`) with
  the field set to `null`, so the HTTP, WebSocket and SSE payloads stay valid
  JSON for strict parsers. Finite values and the `JSONString` scalar are
  unchanged; this mirrors the existing input-side rejection.

- Fix: a populated `DecimalRangeField` and a `DurationField` selected on a
  subscription event type no longer fail on every read. The declared types are
  unchanged (the SDL is the same). A finite `Decimal` range bound is now
  delivered as a `Float` instead of raising `Float cannot represent non numeric
  value` (precision beyond about 15-17 digits is lost; a non-finite bound is
  still an error). A subscription `DurationField` is delivered as total seconds,
  the same `Float` the query output returns, instead of failing on the ISO
  string in the payload; this applies to both WebSocket and SSE events. A
  `BigIntegerRangeField` bound beyond 32 bits still fails with the `Int` scalar
  and is documented as a known limitation, with the workaround, in the types
  guide.

- Fix: a subscription `exact` filter on a `Float` or `Decimal` field now matches
  an event whose snapshot holds a plain integer. A FloatField or DecimalField
  saved with an int (`floating=1`) serializes to the JSON number `1`, which never
  equalled the typed filter `1.0` or `Decimal("1")`, so the event was silently
  dropped. A non-bool int snapshot now matches an equal finite float or Decimal
  exactly; unequal values, NaN, Infinity and booleans still do not match. Other
  lookups (`in`, `gt`, `range`, `isnull`) were never affected: they are decided
  by the database check against the current row.

- Fix: a mutable literal default is no longer shared between requests. A
  default such as `tags: list[str] = []` or `flags: dict[str, bool] = {"a":
  True}` on an `InputType` field, or `default=[...]` on a field argument, was
  coerced once and the very same object was handed to every execution, so a
  resolver that appended to it showed up in the next request. Every execution
  now receives its own deep copy, also inside nested input objects and lists of
  inputs. Immutable defaults are not copied. A resolver receives an equal copy
  of the declared default, not the declared object itself.

- Fix: an `AttributeError` raised while computing a `functools.cached_property`,
  a Django `cached_property` or a custom descriptor with `__get__` is reported
  as a resolution error, like one raised inside an `@property`, instead of
  being read as a missing attribute and answering null. A truly missing
  attribute stays null. A class that defines `__getattr__` keeps the null
  answer, because Python discards the descriptor's error before calling it
  (documented in the fields guide).

- Fix: configuration and input checks no longer depend on `assert`. Under
  `python -O` the `assert` statements in runtime code vanish, so an invalid
  `Meta.model`, `Meta.registry`, `Meta.queryset`, `input_for`, an empty
  `DjangoUnionType`, a bad paginator or an abstract type with extra options was
  accepted in silence. These now raise `ImproperlyConfigured` with the same
  message (they raised `AssertionError` before). The scalar serializers
  `CustomTime`, `CustomDate` and `CustomDateTime` and the internal invariants
  (filter input completeness, subscription routing parity) keep raising
  `AssertionError`, now explicitly. No `assert` remains in the package, and the
  Bandit `B101` skip is removed so none can come back.

- Fix: a `Decimal` value of `NaN`, `sNaN` or an infinity is rejected as invalid
  input. In a filter (`{amt: {exact: "Infinity"}}`) it reached the ORM and came
  back as Django's raw `“%(value)s” value must be a decimal number.` with the
  whole list nulled. The `Decimal` scalar now fails with `Decimal cannot be a
  nonfinite Decimal: 'Infinity'` before execution, for every lookup (`exact`,
  `in`, `gt`, `range`) and for mutation inputs too. Float, Int, BigInt and Date
  filters already rejected their invalid values and are unchanged.

- Fix: a tampered cursor on an in-memory (prefetched or nested) list answers
  `Invalid cursor`, like the database path. A `NaN` Decimal, a non-numeric pk,
  a bad date or a naive/aware datetime mismatch raised `InvalidOperation` or
  `TypeError`, which the client saw as a masked internal error and the server
  logged at ERROR. The boundary is now converted once to the rows' type for
  every integer, float, Decimal, UUID, date, datetime and time ordering field,
  and a non-finite float or Decimal boundary is refused on both paths (the
  database path used to run the comparison with it).

- Fix: a base64 upload of exactly `MAX_UPLOAD_SIZE` bytes is accepted. The
  decoded-size pre-check ignored `=` padding and over-counted by up to two
  bytes, so the same file passed as multipart but was refused as base64. The
  limit now means the same number of bytes on both transports.

- Fix: the schema-suggestion strip in error formatting runs in linear time.
  `format_graphql_error` removed the "Did you mean ...?" sentence with a regex
  whose cost grew with the square of the message length (2.5 s for 224 KB). It
  is now a linear scan with the same results.

- Fix: cost analysis now reads the page-size argument by its wire name too.
  `COST_PAGINATION_ARGS` was compared literally, so the camelCase `pageSize`
  that the page paginator exposes was ignored and `items(pageSize: 5000)` was
  costed at the default page size. Argument names are now compared in
  snake_case form on both sides (`pageSize` matches `page_size`; a custom
  `perPage` is matched by listing `per_page` or `perPage`).

- Fix: reject enum members that GraphQL reserves. A `Literal["__x"]` input
  generated the member `__X`, so the schema built and every query failed.
  The schema build now raises an error naming the input type, field and value.
  A Django choice whose value starts with `__` no longer generates a reserved
  member name either: it falls through the usual label / `A_<value>` naming.

- Fix: adding an interface no longer changes the wire name of fields that are
  not part of it. An object type that implements an interface used the explicit
  `name=` of every declared field verbatim, while the same type without
  interfaces ignored it, so `Meta.interfaces` silently renamed unrelated
  fields. Now only a field that the interface also declares uses the explicit
  wire name; every other field keeps the naming it has without interfaces.

- Behavior change: define `not` inside a to-many relation object as "no
  related row matches the operand". A `not` used to be evaluated on the same
  related row when it sat beside a positive criterion, and its `and` operand
  was split across rows, so `tags: { not: { and: [x, y] } }` was not the
  complement of `tags: { and: [x, y] }`. Now (posts tagged with every subset of
  x, y, z): `tags: { and: [x, { not: z }] }` returns posts tagged x and not z
  (`x`, `xy`; was also `xyz`, `xz`), `tags: { label: x, not: y }` returns
  `x`, `xz` (was also `xy`, `xyz`), `tags: { or: [z, { not: y }] }` no longer
  returns `xy`, and `tags: { not: { and: [x, y] } }` returns every post. A
  `not` alone, `not: { or: ... }`, top-level `not` and every filter outside
  relation objects are unchanged.

- Compile nested `and` filters over to-many relations without nested EXISTS.
  Each level of a nested `and` re-correlated on the root table, so a chain of
  about 25 levels failed on SQLite ("Expression tree is too large") and
  surfaced as `DATA_ACCESS_ERROR`, and wide `and` lists produced several times
  more SQL than before. Operands that are only an `and` list are now flattened
  (AND is associative) and every to-many conjunct is one sibling EXISTS, so SQL
  nesting depends on relation nesting only. Results are unchanged; the
  structural query-depth ceiling still bounds literal nesting.

- Keep SSE streams open through transient lease-renewal errors. With the
  Redis-backed per-account stream cap, a single failed renewal (for example a
  two-second Redis timeout) closed the stream although the 45-second lease
  allows several renewals, so a short Redis blip closed every stream at once and
  clients reconnected into 503s. A failed renewal is now retried every five
  seconds while the last confirmed renewal is less than 40 seconds old (lease
  TTL minus a five-second safety margin); a renewal that Redis answers with "not
  owned", or errors that outlast that window, still end the stream exactly as
  before, without backend details. Streams of one process also share a single
  Redis client (connection pool) per URL instead of opening one connection per
  stream.

- Isolate each channel-layer group in automatic subscription fan-out on the
  synchronous (WSGI, Celery, management command) path. A model write sends its
  event to up to four groups; when the first `group_send` raised, the remaining
  groups never received the event, while the ASGI path already isolated each
  group. Each group now fails independently on both paths. The drop log also
  names the qualified exception class and its causes (for example
  `redis.exceptions.ConnectionError`) instead of only the bare class name; it
  still never includes exception messages, group names or event data.

- Serialize `Decimal` output in plain positional notation. Values loaded with
  `decimal_places >= 7` were emitted through `str()` as `0E-8` or `5.0E-7`; they
  now come out as `0.00000000` and `0.00000050`. Normal values are unchanged.
  A value whose plain form would need more than 1000 padded zeros (for example
  `1E+999999999` echoed by a resolver) keeps its exact scientific form, so a
  14-byte literal can no longer expand into a gigabyte response.

- Make the numeric directives work on `Decimal` and `BigInt` fields. `@round`,
  `@floor`, `@ceil` and `@abs` converted the value to `float`, so `@round` on a
  `Decimal` returned the binary expansion of the float
  (`12.3499999999999996...`) and `@abs` on a `BigInt` returned null with a
  coercion error. They now compute on the exact `Decimal` or `int` (`@round`
  rounds half to even), and `@number`/`@currency` return the raw value on these
  scalar types, as they already did on `Int` and `Float`.

- Isolate batch items from each other and answer every item. With
  `ATOMIC_REQUESTS`, any error in one item of a batched request marked the whole
  request transaction for rollback: the first item answered 200 with `ok: true`
  but nothing was persisted, and later mutations failed with "Unable to complete
  the data operation.". Each batch item now runs in its own savepoint on every
  connection that wraps the request in a transaction, so an erroring item rolls
  back only its own writes and earlier and later items commit; the request-level
  mutation error flag is also scoped to one item. A non-batched request keeps its
  request-level rollback. The batch abort rule was also inconsistent: only an
  HTTP 400 request error cut the batch short, while syntax, validation and
  `operationName` errors continued, so the response had fewer entries than the
  request. Every item now yields exactly one entry, in order, and later items
  always run; the HTTP status is the highest entry status. This replaces the
  "stop later operations" behavior introduced earlier in this release (M-H1).

- Keep custom scalar coercion failures as client errors in production. A custom
  scalar whose `parse_value`/`parse_literal` raises `ValueError`/`TypeError`
  (the graphql-core convention for invalid input) was classified as an internal
  error by the production formatter: the client got HTTP 400 with
  `INTERNAL_SERVER_ERROR` and every such request wrote an ERROR log with
  traceback. Errors raised while parsing, validating or coercing variables are
  now classified by phase as validation errors: graphql-core's message is kept
  without the raw exception text (unless `DEBUG`), there is no ERROR log, and
  errors raised during execution keep their masking and log.

- Fix import-time failures of the one-public-output-type guard. A user
  `DjangoObjectType` declared after a mutation (or `DjangoModelType`, or list
  type) for the same model now replaces the generated placeholder, and the
  mutation payload resolves to the user type instead of exposing every column.
  Re-executing the same declaration (reload, re-import, notebooks, the
  benchmark harness) replaces the stale type instead of raising, and no longer
  leaves stale compile entries or duplicate input names behind. Two distinct
  user types for one model in one registry are still rejected; the error now
  suggests `skip_registry = True` or a separate `Registry`.

- Compile only direct `typing.Union[int, str]` and `int | str` input fields,
  in either member order, as a shared `IntOrString` scalar instead of `String`.
  Integer and string values retain their Python types without casts; integers
  must fit signed 32-bit range. Booleans, floats, objects and lists reject
  before mutation. Outer nullable forms, omitted fixed/factory defaults and
  aliases remain unchanged; other Union shapes and global scalars do not.
  Clients must update variable declarations and generated bindings.

- Compile exact `dict[str, bool]` and `typing.Dict[str, bool]` direct mutation
  inputs as strict `JSON` instead of `String`. Require string keys and exact
  Boolean values before resolution without changing the global JSON scalar
  or omitted fixed/factory defaults. Clients must send JSON objects, not
  encoded strings; list-wrapped and other map forms retain their fallback.

- Compile exact `set[decimal.Decimal]` and `typing.Set[decimal.Decimal]`
  mutation inputs as `[Decimal!]!` instead of `String!`. Existing native
  Decimal coercion preserves finite precision through list/singleton inputs;
  resolvers receive a deduplicated Python set without ordering guarantees.
  A field-local check rejects supplied NaN, sNaN and infinities before
  resolution and omitted sibling factories. Global Decimal and legacy
  fixed/factory-default behavior remain unchanged; other sets keep fallback.
  Clients must migrate encoded strings to native Decimal lists or singletons.

- Compile exact `set[uuid.UUID]` and `typing.Set[uuid.UUID]` mutation inputs
  as `[UUID!]!` instead of `String!`. The existing native UUID scalar accepts
  canonical, uppercase and 32-hex strings in lists or singleton form and
  rejects invalid UUIDs before resolution. Resolvers receive a deduplicated
  Python set of UUID objects without an ordering guarantee. Existing outer
  optional/default behavior remains; other set forms keep fallback. Clients
  must migrate encoded strings to UUID string arrays or singletons.

- Compile exact `set[float]` and `typing.Set[float]` mutation inputs as
  `[Float!]!` instead of `String!`. Native GraphQLFloat coerces finite numeric
  list/singleton inputs, including integers, before resolvers receive a
  deduplicated Python set without ordering guarantees. A field-local check
  rejects overflowing numeric literals before resolution while preserving
  malformed legacy defaults. Other unapproved set forms keep fallback;
  existing optional/default behavior remains. Clients must migrate
  encoded strings to numeric arrays or singletons.

- Compile exact `set[bool]` and `typing.Set[bool]` mutation inputs as
  `[Boolean!]!` instead of `String!`. Native GraphQLBoolean validation and
  list/singleton coercion apply; `false` reaches resolvers as `{False}`.
  Duplicates are removed with no ordering guarantee. Existing outer
  optional/default behavior remains; unapproved set forms retain fallback.
  Clients must migrate encoded strings to boolean arrays or singletons.

- Compile exact `set[str]` and `typing.Set[str]` mutation inputs as
  `[String!]!` instead of `String!`. Native GraphQLString validation and
  list/singleton coercion apply; resolvers receive a deduplicated Python set
  with no ordering guarantee. A singleton `"ab"` stays one member, not
  two characters. Existing outer optional/default behavior remains; other
  set forms keep their fallback. Clients must migrate encoded strings to
  string arrays or singleton strings.

- Compile exact `set[int]` and `typing.Set[int]` inputs as `[Int!]!` rather
  than `String!`.
  GraphQL applies its standard integer validation and singleton-list coercion;
  resolvers receive a deduplicated Python set with no ordering guarantee.
  Existing optional/default behavior remains, while other unapproved set forms keep
  their earlier fallback. Clients must replace encoded strings with integer
  arrays or singleton integers.

- Compile nested lists of already-supported input leaves with recursive
  GraphQL list/nullability wrappers instead of a one-level String fallback.
  GraphQL applies ordinary singleton-list coercion at each level; supported
  JSON, strict typed-map, Literal enum, and nested input leaves keep their
  existing contracts. Unsupported leaves keep the earlier fallback. Valid
  nested JSON list defaults can now render in SDL and introspection.

- Compile exact `dict[str, str]` and `typing.Dict[str, str]` input fields
  to the shared raw `JSON` scalar. Require object inputs with string keys
  and string values without conversion; invalid values fail before mutation
  resolution. Clients must replace legacy encoded String values with JSON
  objects. Other dictionary forms remain unchanged.

- Treat exact `typing.Dict[str, int]` input fields like `dict[str, int]`: shared
  JSON scalar, strict plain-integer object checks before mutation resolution,
  and the same wrapper/default behavior. Clients using the typing alias must
  replace legacy encoded String values with JSON objects. Other typing forms
  remain unchanged.

- Do not register a generated model output type for a `DjangoModelMutation`
  rejected by unsupported `permission_classes` or `model_operations`.
  This removes a test-order-dependent registry conflict without changing the
  error messages, valid CRUD declarations, or the one-public-type rule.

- Compile exact `dict[str, int]` input fields to the existing raw `JSON`
  scalar instead of `String`. Accept objects with string keys and plain
  integer values without implicit conversion; invalid values fail before
  mutation resolution. Bare `dict` and other typed-container fallbacks stay
  unchanged. Clients must replace JSON-encoded strings with objects.
  Fixed JSON defaults with GraphQL Name object keys now render in SDL and
  default-value introspection without changing runtime values. Defaults with
  non-Name keys retain runtime behavior and their metadata limitation; use
  a zero-argument factory when metadata must render. Valid fixed JSON list
  defaults now render in SDL and introspection; their outer list may be copied
  while elements stay unchanged. Malformed list defaults retain legacy behavior.
  Unpaired
  Unicode surrogates and integers beyond Python's configured
  integer-to-string limit also retain runtime defaults without new SDL metadata.

- Compile all-string hand-authored input `Literal` annotations as generated
  GraphQL enums. Inline operations and JSON variables now send enum members
  rather than raw strings; resolvers still receive the original strings.
  Numeric/mixed literals and other unsupported typing forms retain their
  warning and `String` fallback.

- Align automatic nullable-column ordering in limit/offset and page pagination
  across queryset, nested SQL-window, and materialized-list paths: NULL last
  ascending, first descending. Explicit ORM expressions, term priorities,
  primary-key ties, and Cursor pagination retain their existing behavior.

- Reject negative integer `MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE`, and
  `DOCUMENT_CACHE_MAXSIZE` values when each setting is read, using the existing
  configuration error with a minimum of zero and a remedy. Zero, `None`,
  positive values, defaults, and existing noninteger handling are unchanged;
  this does not add eager startup validation.

- Apply configured `MAX_UPLOAD_SIZE` to each received multipart file, including
  unused and repeated parts. Files over the limit now receive JSON HTTP 413
  before resolver execution; equality and `None` retain their documented
  behavior. Base64 limits and the separate whole-request body cap are unchanged.

- Return HTTP 200 with `data: null` and `errors` from the enhanced JSON view
  when a field execution error nulls a non-null root result. Syntax,
  validation, and variable-coercion failures remain HTTP 400 without data;
  errored responses are not cached. Batch transport errors and other HTTP
  policies are unchanged.

- Distinguish malformed model primary-key IDs from well-formed missing or
  scoped-out IDs in `get_node`, generated retrieve fields, and
  `DjangoObjectField`. Malformed IDs now produce a safe `INVALID_ID` GraphQL
  error with an expected-format hint; missing/hidden IDs still resolve to
  `null` without an error. Valid text IDs and existing ORM coercion remain.

- Report a stable GraphQL field error when `@floor` receives NaN or either
  infinity, including numeric strings that coerce to those values. Finite and
  null values, malformed-number errors, other directives, and schema metadata
  are unchanged.

- Declare library transformation directives on GraphQL fields only. Placing
  them on fragment spreads or inline fragments now fails validation instead
  of silently doing nothing; place transforms on fields inside fragments.
  Standard `@skip`/`@include`, raw third-party directive locations, and
  field-transform execution remain unchanged.

- Reject non-finite numbers in raw `JSON` inputs, including nested variable
  values and overflowing float literals, with a GraphQL input error before
  resolver execution. Finite values, numeric strings, missing-variable
  handling, raw `JSON` outputs, and `JSONString` remain unchanged.

- Preserve positions in raw `JSON` list literals when an optional variable is
  omitted: the missing member now resolves to `null` instead of leaking an
  unserializable sentinel. Missing object-literal keys remain omitted;
  supplied values, defaults, explicit null, and ordinary typed lists are
  unchanged. This does not change `JSONString`, top-level missing-argument
  behavior; non-finite raw input rejection is documented separately above.

- Preserve GraphQL null values through `@number` and `@currency` instead of
  formatting absent values as zero. Required fields now use normal GraphQL
  nullability errors and bubbling. Format validation, width/precision caps,
  raw numeric field passthrough, and non-null falsy value handling remain.

- Normalize output values of `@camel_case`, `@snake_case`, and `@kebab_case`
  across spaces, underscores, hyphens, camel/Pascal boundaries, and acronym
  blocks. `orderTotal` now becomes `order_total` or `order-total`, and
  `HTTPServer` becomes `httpServer`, `http_server`, or `http-server` in
  directive order. Schema names, shared converters, and other directives are
  unchanged; punctuation and other character forms retain prior handling.

- Display aware Python datetimes and text with an explicit numeric offset or
  `Z` in Django's active timezone for absolute `@date` formats, preserving
  the instant while allowing date rollover. Explicit-offset/Z text retains
  its prior relative behavior; `iso` still omits its output offset and
  microseconds. Clock-adjacent `+00:00` and `+0000` now receive the same
  absolute conversion as equivalent `Z` text.

- Interpret accepted timezone-less text passed to `@date` as its written wall
  clock in Django's active timezone for absolute and relative formats,
  regardless of `USE_TZ`. Relative wording can change. Named UTC/GMT and
  unknown timezone names, Python inputs and missing-date filling retain their
  existing behavior; no daylight-saving gap/overlap policy was added.

- Default omitted time components in accepted textual `@date` values to zero,
  including seconds and microseconds of partial times. Missing date components
  still use the current date; explicit components and null behavior are
  unchanged. The aware-value conversion above is a separate change.

- Preserve GraphQL null values through `@date`, including fields with an
  explicit format. Non-null fields now follow normal GraphQL error and null
  propagation when their resolver returns null; other directives are unchanged.

- Match exact finite native Float subscription filters against finite float
  event snapshots by numeric equality. Full-payload signed zeros now match in
  either direction, including direct legacy `split_filters` calls with two
  actual floats. Previously dropped matching events may arrive. Raw strings,
  mixed types, Boolean/null, non-finite fallback, missing fields, other
  lookups, and indexed group routing keep their existing behavior.

- Match automatic delete notifications against signal-time projected scalar
  equalities even with id-only public payloads. Server-forced scope still wins
  over conflicting client filters, and private values never become GraphQL
  output. Deferred, missing, nonprojected, id-only relation, and lookup conditions remain
  conservative; create/update and manual notification behavior is unchanged.

- Reject subscription WebSocket handshakes before acceptance when the client
  does not offer the exact `graphql-transport-ws` subprotocol. Accepted clients
  may offer it among alternatives. The server logs an actionable diagnostic;
  pre-accept rejection is normally HTTP 403 on the wire, so browsers may show
  only a generic connection failure. Configure the client's subprotocol offer;
  no authentication, SSE, or HTTP behavior changed.

- Preserve microseconds in native full-payload subscription DateTime event
  snapshots. Typed exact DateTime filters now compare the captured instant,
  including equivalent aware offsets, and native DateTime event fields use the
  existing output scalar without a later row lookup. SSE and WebSocket share
  the corrected delivery path; nullable and other scalar fields, id-only
  payloads, and custom resolver contracts are unchanged. Previously dropped
  equal events can now arrive; older truncated snapshots cannot recover lost
  precision.

- Match finite typed Decimal subscription `exact` filters by numeric value
  against the event-time JSON-safe snapshot. A filter value of `1.0` now
  matches a full-payload `"1.00"` on create and delete without a row lookup.
  Valid high-precision model values also match without an arbitrary 256-character
  cutoff. String-valued server scopes, malformed/non-finite values, other scalar
  filters, and the Decimal wire payload retain their existing behavior.
  Native DateTime snapshots have the separate lossless rule above.

- Route nested creates using one populated, unsaved parent instance with the
  included Django backend, then pin native parent and child writes to that
  selected alias in one transaction. A later child failure rolls back earlier
  same-alias writes and commit callbacks. Updates retain the existing parent's
  alias; direct non-nested creates and custom serializer backend create calls
  keep their prior contracts. A divergent M2M through route fails before the
  first write, or before linking after a generated ID while rolling back local
  writes. Cross-database transactions and routers changing answers between
  the check and link operation are not coordinated.

- Queue automatic subscription save and delete notifications on the database
  alias that performed the write. Routed secondary writes now wait for their
  own commit, disappear on rollback, and are not delayed by an unrelated
  default-database transaction. Missing-channel-layer warnings follow the
  same alias; this does not add cross-database atomicity.

- Warn when unsupported hand-authored input annotations such as numeric or mixed `Literal`,
  parameterized `dict` or `set`, and non-optional `Union` fall back to GraphQL
  `String`. Existing SDL, coercion, and resolver dictionaries are unchanged;
  this does not add structured input conversion or automatic Pydantic validation.

- Apply field directives after awaiting resolver values in native asynchronous
  graphql-core execution, rather than formatting coroutine representations.
  Built-in synchronous HTTP views still reject asynchronous execution with
  their existing JSON 500 error; this does not add asynchronous HTTP support
  or change directive names, arguments, or synchronous results. Defer directive
  coroutine creation until native execution awaits it so an outer middleware
  cannot leave an unawaited inner coroutine after synchronous HTTP rejection.

- Clean up subscription group memberships when WebSocket or SSE startup is
  cancelled after a backend join but before the join call returns. Partial
  startup failures attempt the same source-owned cleanup while preserving the
  original error. Failed sources remain retryable unless explicitly closed;
  backend discard failures are logged and remain best-effort. Wire frames,
  authentication, and ordinary subscription delivery are unchanged.

- Release a WebSocket subscription's operation ID after source teardown and
  before sending its server `complete` frame, so an immediate same-ID subscribe
  is not mistaken for a concurrent duplicate. Late callbacks cannot remove a
  replacement operation; client cancellation and existing error framing are
  unchanged.

- Share one global registry instance on concurrent first access and one
  auto-generated list class per model and built-in registry on concurrent
  misses. Explicit list registration keeps its last-registration-wins rule;
  names, SDL, pagination and filter configuration are unchanged. This is not
  a general registry or schema thread-safety guarantee.

- Share one enum type for concurrent equivalent cache misses and retain the
  existing incompatible-choices error when definitions race in one registry.
  Native enum names, member order, values and serial schema output are
  unchanged; this is not a general registry thread-safety guarantee.

- Track native mutation field identity only while the field remains alive.
  This prevents a stale integer identity marker from classifying an unrelated
  raw GraphQL field internally, while retaining live fields after a later
  mutation class overwrites their model-and-operation registry slot. Mutation
  SDL and public declarations are unchanged; this does not promise general
  schema or registry reclamation.

- Diagnose a suppressed `RuntimeError` while closing a subscription delivery
  source with a server-side warning and original traceback. Close remains
  best-effort and idempotent, with no new client frame or propagation; a benign
  already-closing generator race can also produce this warning. Normal
  cooperative cancellation is unchanged.

- Report an explicit `source=` Python property's original `AttributeError`
  as a GraphQL field error when it escapes normal Python lookup, including
  getters wrapped with `functools.partial` or `functools.lru_cache`. Successful
  dynamic fallback, final dynamic absence, missing attributes, legitimate
  null values, and absent Django reverse one-to-one relations keep their
  existing behavior; required fields and production HTTP formatting are
  unchanged.

- Stop schema construction when Django model field enumeration fails instead
  of publishing a concrete-fields-only type that may omit reverse relations.
  The configuration error names the model and retains the original exception
  as its cause, including through eager and lazy GraphQL field compilation.
  Existing installations that depended on the partial-schema fallback must
  fix the underlying metadata error; healthy schema output is unchanged.

- Batch typed GenericForeignKey targets selected through valid inline or named
  fragments on the enclosing union. Member-specific column projection and
  nested relation joins now match direct member fragments, avoiding per-row
  queries without changing the schema or public API.

- Keep output registrations independent of an unrelated thread's forked schema
  build. A projected node/list type no longer degrades a later list result to
  `[String]` under that overlap; same-thread fork isolation remains intact.

- Keep a cached permission-scoped schema available while an unrelated cold
  signature is being pruned. Cold builds and cache clearing remain serialized;
  permission keys, cache bounds and public settings are unchanged.

- Plan queryset relations, annotations, filtered prefetches, and column
  projection across all field nodes merged under one root GraphQL response key.
  A relation selected only in a later root fragment no longer triggers
  per-row queries; schema and public settings remain unchanged.

- Preserve `null` and empty-list schema values for selected `__schema` and
  `__type` queries whose root fields are reached through inline or named
  fragments when `CLEAN_RESPONSE=True`. Previously those fragmented
  introspection responses could be cleaned into incomplete data. Mixed ordinary
  roots still use normal cleaning; `CLEAN_RESPONSE=False`, defaults, and
  introspection authorization are unchanged.

- Keep the two public HTTP view constructor checks active under optimized
  Python (`-O`): a schema without `graphql_schema` or simultaneous GraphiQL
  and batch modes still raise their existing `AssertionError` messages when
  the view is constructed. Other assertions and validation policies are
  unchanged.

- Preserve completed results when a valid GraphQL batch reaches an operation-
  level HTTP 400 request error. Return an HTTP 400 array ending with that
  error, stop later operations, and leave prior successful mutations committed.
  Previously the error-only object hid earlier results. Malformed batch
  bodies and non-400 transport errors keep their existing envelopes;
  `ATOMIC_MUTATIONS` remains per operation.

- Reject unsupported async resolver, middleware, and executor results on the
  synchronous built-in HTTP views with a controlled HTTP 500 GraphQL JSON
  error. Newly created, unstarted coroutines owned by execution are closed
  without running them. Previously this configuration could produce an HTML
  500 and unawaited-coroutine warnings. Use synchronous resolvers and
  middleware for HTTP; this does not add async HTTP support or change SSE and
  WebSocket subscriptions.

- Cache only HTTP 200 GraphQL data responses without errors when
  `CACHE_ACTIVE=True`. Partial-data execution errors, validation failures and
  other non-200 responses are returned normally but re-execute on the next
  request; previously stored failed entries are ignored without clearing the
  cache. A later success can be cached under the existing key. Clients or
  operators relying on cached error replay should allow fresh execution;
  successful cache hits, identity isolation, hooks, cookies and mutation
  invalidation remain unchanged.

- Preserve numeric zero and `false` in ordinary `GraphQLView` responses when
  `CLEAN_RESPONSE=True`, including nested fields and arrays. Clients that
  relied on these values being omitted will now receive them. Nulls, empty
  strings and empty containers are still removed recursively; the default
  `CLEAN_RESPONSE=False` and selected introspection responses are unchanged.

- Frame the default response-cache body and GET components before SHA-256
  hashing. Two different selected GET operations can no longer share a cache
  entry through ambiguous concatenation within one identity. Existing cached
  responses cold-miss and expire normally; the 64-hex digest shape and custom
  `fetch_cache_key(request)` override contract remain unchanged.

- Make bounded model-backed LimitOffset and Page slices deterministic within ties by
  appending the primary key ascending after the existing ordering, unless the
  key is already present. This includes nested window and materialized model
  paths; explicit primary-key direction and client ordering validation remain.
  Clients relying on unspecified tie order may see rows move. Offset pages can
  still shift after concurrent inserts/deletes or random primary ordering.
  Unbounded, unconfigured LimitOffset lists retain their original queryset and
  `totalCount` cache behavior. Existing server queryset reversal and legacy
  `extra(order_by=...)` precedence remain effective ahead of the new key,
  including nested pages.

- Return a generic GraphQL error when a negative page's database `COUNT` fails,
  instead of loading the full queryset to recover the page. Clients relying on
  a successful page after a count-only failure should handle `Unable to
  calculate pagination count`; database details stay out of the response.
  Positive pages and the separate `totalCount` resolver are unchanged.

- Change the library `DEFAULT_PAGE_SIZE` from `None` to `100`. Omitted sizes on
  the global LimitOffset paginator and default-constructed Page/Cursor
  paginators now return the first 100 rows; clients must paginate for later
  rows. An explicit positive global or per-type size still wins. This is not a
  new maximum (`MAX_PAGE_SIZE` remains `None`), and explicit `None` retains each
  paginator's existing behavior, including Page's `results: null` when no
  effective size exists. Set `DEFAULT_PAGE_SIZE` before importing paginator
  classes at startup; existing instances are not hot-reloaded.

- Fix generated relation filters when a related field is named `year`,
  `month`, `day`, `range`, or `exact`: nested field lookups now reach that
  field, while direct relation `exact`/`in`/`range` lookups target the related
  primary key even when a field has the same name. Generated SDL and input
  shapes are unchanged; previously failing valid requests now return their
  matching rows.

- Treat explicit `page: null` as omitted `page` (first page 1) for page-number
  pagination on root and nested lists. This replaces the previous raw
  comparison error for null; clients relying on that error should reject null
  before sending a request. The nullable `page: Int = 1` schema, zero-page
  error, and negative-page behavior are unchanged.

- Continue in-memory cursor pages ordered by FloatField, DecimalField, or
  UUIDField using server-emitted cursors. Nested materialized lists now match
  queryset-backed lists on the next page; cursor tokens, SDL, ordering,
  and queryset behavior are unchanged.

- Report decoded cursor values that cannot convert to FloatField, DecimalField,
  or UUIDField as `GraphQLError("Invalid cursor")` for results and pageInfo on
  both queryset-backed and materialized lists. Previously, materialized lists
  exposed a raw comparison TypeError; clients matching that message should
  handle `Invalid cursor` instead. Valid server-emitted cursors, cursor bytes,
  SDL, and other scalar error policies are unchanged.

- Let separate explicit `and` filter branches over a many-to-many or reverse
  foreign-key relation match different related rows, including when nested
  beneath `or` or `not` and inside another relation object. One outer related
  row must satisfy that object's criteria; its deeper `and` branches may use
  different rows of their own relation. Queries that previously returned no
  parent may now return one;
  group criteria in one relation object to require same-row matching. Scalar,
  direct to-one, null and empty-Boolean behavior, generated SDL, and subscription
  filters are unchanged.

- Type explicitly declared numeric `DateField` and `DateTimeField` part filters
  as GraphQL `Int` so integer literals and variables reach Django. `DateField`
  supports `year`, `month`, `day`, `week_day`; `DateTimeField` also supports
  `hour`, `minute`, `second`. Clients using `$year: Date` or
  `$year: DateTime` must change to `$year: Int` and send an integer. Lookup
  exposure/defaults, full-value ISO `Date`/`DateTime` filters, `TimeField`,
  null/Boolean behavior, and subscription filters are unchanged.

- Make an explicitly supplied `exact: null` in generated query filters select
  SQL NULL rows, matching `isnull: true`; an omitted lookup still adds no
  predicate. This includes nullable relation IDs and JSON fields (SQL NULL,
  not JSON `null`). Clients using `exact: null` to mean “ignore this filter”
  must omit the lookup. Other null lookups, custom filters, empty Boolean
  operands, and the generated input schema are unchanged.

- Validate supplied negative `PositiveIntegerField` and
  `PositiveSmallIntegerField` generated inputs before SQL, returning a
  structured field error without saving that mutation. Zero, positive values,
  `Int` bounds, choice Enum inputs, and omission/default behavior are unchanged.
  Because this is `ok: false` data rather than a GraphQL execution error, an
  earlier successful sibling root now commits even with `ATOMIC_MUTATIONS=True`;
  clients requiring all-or-nothing business operations must account for that
  migration. Unrelated execution errors still roll back.

- Validate supplied nonempty Django `EmailField` values with Django's email
  syntax rules in generated create/update and nested inputs. Invalid values
  now produce the existing structured field error without persistence; the
  GraphQL `String` schema for fields without choices, existing Enum SDL for
  choice-backed fields, and omission, null, empty-string, default, and
  partial-update behavior remain unchanged. Choice syntax checks use stored
  values, not display labels. This does not enable `full_clean()`
  or change other Django field validators. Clients previously sending malformed
  nonempty addresses must correct them.

- Honor an explicit `name=` on `DjangoInterfaceType` fields and matching
  declared implementor fields. Their SDL, introspection, and queries now use
  the requested wire name; attributes without an explicit name retain
  camelCase. This changes the old accidental name (for example,
  `internalName` to `name`), so clients must update affected queries and
  generated types. No legacy alias is added.

- Preserve generated mutation create/update inputs for Django columns named
  `model_dump`, `model_validate`, or `model_config`. These previously failed
  Pydantic schema construction; their GraphQL names, validation errors, and
  persisted Django attributes now retain the original naming. Existing
  working column names and model-derived omission semantics are unchanged.
  Inherited `Meta.pydantic_model` validators and serializers for `model_config`
  continue to run without modifying the caller's base model.

- Evaluate zero-argument factories on hand-authored `InputType` fields for
  each new GraphQL-coerced input object rather than once at schema build.
  Factory values no longer appear as fixed SDL defaults; plain literal
  defaults, explicit values/null, resolver dict shape, model-derived partial
  updates, and validated-data factories keep their existing contracts. Clients
  relying on a generated SDL factory value must move to runtime input behavior.

- Make automatic model-signal subscription notifications best-effort across
  snapshot preparation and delivery. Ordinary notification errors now log
  metadata only and drop the event without failing a successful database save
  or generated mutation; later commit callbacks continue. Rollback still emits
  nothing, and explicit manual broadcasts remain strict. Applications that
  depended on automatic delivery exceptions should handle delivery explicitly;
  this does not add retries or an outbox.

- Run the documented synchronous WS/SSE subscription `schema_provider` in a
  thread-sensitive worker. Real Django users with cold permission caches can
  now use `pruned_schema_for` without synchronous ORM access on the event loop.
  Provider inputs, schema results, per-socket/per-request caching, and existing
  transport error behavior are unchanged; coroutine-returning providers are
  not a new supported contract.

- Reject ambiguous generated `choices` enum member names with
  `ImproperlyConfigured` instead of assigning positional suffixes that could
  change literal meaning when choices are reordered. Adjust affected choices
  to generate distinct names and migrate clients using suffixed literals;
  unambiguous members and automatic enum type names are unchanged.

- Reject incompatible automatic `choices` enums that normalize to the same
  GraphQL type name in one registry with `ImproperlyConfigured` naming both
  model fields. Compatible definitions, including reordered members, still
  reuse one enum; existing noncolliding names and output, mutation-input and
  filter behavior are unchanged. Distinct registries remain isolated. Resolve
  a collision by separating schema surfaces or renaming an app, model or field.
  Such a change needs a corresponding client/schema migration; no enum-name
  override was added.

- Reject a second distinct public `DjangoObjectType` for the same exact Django
  model and `Registry` with `ImproperlyConfigured`, rather than silently
  replacing the type used by nested relations. Re-registering the same class
  remains idempotent; separate registries, input/mutation registrations, and
  non-registering internal forks are unchanged. Existing public/admin schema
  variants over one model must use separate registries.

- Change auto-derived `DecimalField` output from `Float` numbers to the
  existing `Decimal` scalar's exact JSON strings, including model objects
  returned by generated mutations. `19.99` becomes `"19.99"`; large values no
  longer round through binary Float. Clients must migrate output SDL/types and
  number handling. Generated Decimal inputs and filters, explicit overrides,
  ordinary Float fields, and primary-key nullability are unchanged. An
  explicitly declared `Float` field with a Decimal-to-float resolver retains
  the former numeric output at the cost of precision. This output scalar cannot
  recover digits already rounded by a database backend.

- Map auto-derived `BigIntegerField` and `PositiveBigIntegerField` to the
  precise `BigInt` scalar in output, generated mutation inputs and automatic
  filters. Wire values are bounded decimal strings, including small values;
  model/ORM values remain Python integers. This is an approved breaking SDL and
  client-variable change; ordinary `Int`, generated `ID`, and explicit scalar
  overrides are unchanged. Relation IDs to BigInteger primary keys still accept
  string or integer values through `ID` input; numeric-choice fields keep their
  generated Enum input.

- Previously restored populated auto-derived `DecimalField` output under
  graphql-core 3.3 through the existing `Float` field; the new default above
  supersedes that interim Float output without changing Decimal input parsing.

- Generated create and update (`DjangoModelMutation`, `DjangoModelType`, and
  nested child writes) now run Django's model field validation on every field
  the client wrote: the field's validators (`MinValueValidator`,
  `RegexValidator`, custom `validators=[...]`, `max_length`, ...), `blank`,
  `null` and `choices`, with Django's own messages. Values that were previously
  accepted, such as `""` into a `blank=False` field or a number below a
  `MinValueValidator`, now return `ok: false` with one `errors[]` entry per
  field and write nothing; a nested child error is prefixed with the nested
  field name. Fields the client did not send (including developer defaults) are
  not validated, an explicit `null` on a nullable column stays valid, and a
  relation field runs its validators without an existence query. `Model.clean()`,
  `validate_unique()` and `validate_constraints()` are not run. Clients that
  relied on invalid values being stored must fix the data or relax the field's
  validators.

### Added

- Add independently opt-in SSE idle heartbeat comments (15-second setting)
  and a shared Redis-backed concurrent stream cap for authenticated accounts
  (five-stream setting). Both remain off by default. A full account receives
  HTTP 429, unavailable admission HTTP 503, and a lost midstream lease a
  generic SSE error and completion; anonymous, WebSocket, and authentication
  behavior is unchanged. Redis lease expiry and failover are documented limits.

- Add optional async `on_connect(scope, payload)` authentication to the
  subscription WebSocket consumer. An authenticated callback result replaces
  the socket user before ACK, schema resolution, and permission checks;
  malformed payloads close with `4400`, denied credentials with `4403`, and a
  stalled callback with `4408`. Without the hook, existing session identity
  and ignored initialization payloads are unchanged. Projects provide their
  own credential verifier; HTTP, SSE, and persistent sessions are unchanged.

### Docs and tests

- Ship the root files that test modules read (`CHANGELOG.md`, the two 4.0.0
  remediation reports, `tox.ini`, `uv.lock` and `zensical.yml`) in the sdist, and
  guard the allowlist with a static test. Directories such as `benchmarks/` and
  `examples/` are still not shipped.
- Publish the 4.1.0 core33 comparison as the current series,
  `core33-4.1.0-460efb9b7c29b097f2939c05e79514f2fda3242c`, measured from
  4.1.0 source `460efb9b7c29b097f2939c05e79514f2fda3242c` with the unmodified harness.
  SQL counts are identical to the 4.0.0 series and the GraphEx p50 differences
  are within noise; GraphEx/Ariadne create-comment p50 is 0.55× at 50,000 and
  100,000 comments. The run had a heavier background load than the previous
  series (about 8-10 against 4-6), so cold-import figures (GraphEx about 52-54
  ms, graphene-django about 25-29 ms) are not comparable across series. The
  earlier `core33-4.0.0` series stay as historical evidence.

- Playground example: describe the closed draft and `internalNote` leaks as
  closed; scope `postSubscription` for anonymous subscribers with
  `subscription_scope`; require login for `postUpdate`, `postDelete` and
  `documentUpdate` through a `private_mutation` root; run Django password
  validators in `registerUser` and answer a duplicate username generically;
  suggest a measured `MAX_QUERY_COST` (10,000,000, not 200); serve media in
  development, log upload failures instead of echoing them, and add a `BigInt`
  field. Several Playground README commands and examples were corrected in
  follow-up entries below.

- Playground example: restrict `Document.attached_file` to an allow-list of inert
  extensions on both upload paths, serve `MEDIA_URL` as a sandboxed download
  (`attachment`, `nosniff`, `Content-Security-Policy: sandbox`) instead of
  inline, and validate `registerUser` usernames with the `User` model's own
  field rules. The Playground tests write uploads into a temporary `MEDIA_ROOT`.
  The README `BigInt` and `Decimal` examples now return the values they quote
  (a test pins them), the `wscat` command sends the required `Origin`, the
  `registerUser` accounts are documented as unable to log in, and the seed
  summary no longer claims multiple pages for a small dataset.

- Add a local, evidence-bounded disposition of the 100 original audit claims
  in [the 4.0.0 audit report](audit-4.0.0.md). It separates scoped fixes,
  current contracts, recommendations, limited negative checks, and pending
  policy decisions. This is not a release or a claim that all issues are closed.

- Document current subscription, timezone, cache-cookie, partial-update and
  pagination boundaries without changing runtime behavior. The guides now
  distinguish automatic signals from manual broadcast, directive timezone
  assumptions, browser cookie cache bypass, partial-input versus SQL saves,
  and cursor versus offset/page NULL ordering.

- Close test-owned temporary multipart uploads and ASGI request-body spools
  after direct view dispatch, including exceptional exits. This changes test
  fixture ownership only; HTTP behavior and upload limits are unchanged.

- Complete Google-style docstrings in tracked regression tests for metadata
  errors, schema isolation, source properties, optimizer plans, and permission
  caching. This is a test-documentation change only; library behavior is
  unchanged. Local ignored profiling scripts are outside the clean checkout.

- Fix order-dependent registry tests by restoring the cached default schema
  pair after temporary test scopes, including nested and exceptional exits.
  This changes only test isolation; library behavior and public APIs are
  unchanged.

- Clarify the explicit-`None` pagination documentation: when no request size,
  default, or maximum supplies a size, LimitOffset returns all rows, Page
  returns `results: null`, and Cursor uses its final 20-row fallback. Ordinary
  omitted constructor sizes still inherit the 100-row startup default; this
  corrects an ambiguous API table without changing runtime or error behavior.

- Correct the cache-key documentation: `fetch_cache_key(request)` hashes the
  raw body even on a GET request that carries one, alongside framed GET
  parameters. This is not a recommendation to send GET bodies; use query
  parameters or POST JSON. Cache-key behavior and existing entries are
  unchanged.

- Improve date-part test portability by removing exact runtime-version,
  checkout-path, and working-directory assertions from the behavioral test.
  A separate regression contract keeps those local proof checks external;
  this does not change date-part filtering or expand the supported version
  range.

- Clarify that `ALLOW_INTROSPECTION=False` blocks `__schema` and `__type` only
  when `DisableIntrospectionMiddleware` is installed in GraphQL `MIDDLEWARE`.
  The default middleware chain is empty, so deployments relying on the setting
  alone should explicitly install the middleware. This is a documentation
  correction; the runtime defaults and introspection behavior are unchanged.

- Make the converter integration test register its User relation target in a
  test-local, allowlisted registry. The test now passes in isolation without
  weakening its relation assertion or changing production relation behavior.

- Validate only the eight named canonical benchmark results and copy only those
  files into provenance-test fixtures. Ignored local diagnostic JSON no longer
  causes unrelated validation failures; missing or invalid canonical results
  still fail, with no timing or published-artifact changes.

- Make the non-paginator resolver fixture own its partial on the field instance,
  preserving bound-method identity and observing the paginator type-guard path
  across Python versions without changing production pagination behavior.

- Close SQLite connections deterministically in named comparison preflight and
  seed-identity readers, including errors. Disposable benchmark-test writers
  commit or roll back before close; historical results and timings are unchanged.

## 4.0.0 — 2026-10-05

Release validation now checks the exact pure-branch coverage percentage in
addition to combined and changed-line coverage. The documentation build checks
generated local links and provides the 404 page's theme skip-link target.

CI installs pinned `codecov-cli` 11.3.1 from official PyPI over verified HTTPS,
keeping the existing action, authentication and coverage gates. This replaces
the standalone-binary GPG/checksum verification with PyPI distribution trust;
`fail_ci_if_error: true` makes installation or upload errors fail the job.
Actual upload and both exact-commit Codecov checks remain required for release.

**django-graphex 4.0.0 requires `graphql-core>=3.3.0,<3.4`.** The package
and both editable project locks use this version and dependency range.
Custom 3.2 `ExecutionContext` subclasses must move to the 3.3 `Executor` API; the
legacy view keyword remains an alias with explicit-argument precedence.
Custom AST builders must construct immutable AST nodes, and subscription
transports must handle the 3.3 source stream results. Synchronous queryset
execution, directive coercion and query cost behavior retain compatibility
tests. The current official core33 SQLite comparison is in the immutable
`core33-4.0.0-bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e` series,
measured from 4.0.0 source `bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e` and installed later at
`826d5bae87ed7bbe705cf309d46a16d3ad3cdf33`. Its GraphEx/Ariadne create-comment p50 ratios are
0.57× and 0.51× for 50,000 and 100,000 comments, respectively; the
GraphEx direct-write check retains four SQL statements versus Ariadne's one.
These are three-run per-statistic medians of pinned SQLite whole stacks under
accepted background load, not paired cross-session speedups, PostgreSQL
timings or a published wheel. The earlier 4.0.0 pre-fragment, 3.1.1-source
core33 and 3.1.0 artifacts remain historical. See the
[current comparison](why.md#current-core33-comparison). The dated 3.1.1 security patch and its
GraphQL-core 3.2.13 requirement remain historical facts.

SQLite generic mutations now validate only their directly saved FK rows
(including concrete inheritance parents) and updated M2M links, including
both rows of a symmetric self-relation accessed through a proxy or concrete
child, after the write, inside the rollback savepoint. This avoids
the table-wide deferred-FK scan that grew with unrelated rows, while retaining
immediate structured errors for the mutation's own invalid relations. Earlier
unrelated deferred violations remain the outer transaction's responsibility
and still prevent commit if unresolved. PostgreSQL's existing check is unchanged.
The earlier core33 results predate this change; the new 4.0.0-source series
records the scoped SQLite check without rewriting that history.

Related `AnnotatedField` selections inside applicable named or inline GraphQL
fragments now receive the same optimizer promotion as direct selections;
fragment type conditions and bound directives remain respected. Previously,
valid fragment-only related annotations could return `null` without a GraphQL
error. The current comparison above includes this correction; the earlier 4.0.0
pre-fragment series retains its original source attribution.

## 3.1.1 — 2026-10-01

**Security patch.** Production publication is tag-driven. The supported runtime
floor is now `graphql-core>=3.2.13,<3.3`, without moving to the separate 3.3
migration.
The root and Playground locks resolve 3.2.13; the Playground also moves from
Django 6.0.6 to 6.0.8 on the already-tested 6.0 line.

- [GraphQL-core 3.2.12](https://github.com/graphql-python/graphql-core/releases/tag/v3.2.12)
  makes `max_tokens` count skipped comment tokens and gives the
  `OverlappingFieldsCanBeMerged` validator a per-document comparison budget.
  The default is 250,000 field comparisons. A query that exhausts it now returns
  a validation error; callers using an explicit parser token limit may also see
  comment-heavy documents rejected where they were previously accepted.
- [GraphQL-core 3.2.13](https://github.com/graphql-python/graphql-core/releases/tag/v3.2.13)
  reports a truncated string escape as `GraphQLSyntaxError` instead of an
  unhandled `IndexError`. The HTTP view returns a JSON 400 syntax error for this
  malformed input.

The HTTP view does **not** pass `max_tokens` to the parser, so the upstream token
accounting fix is not itself an HTTP token cap. Configure request-size limits for
your deployment; see [runtime security guidance](usage/security.md#runtime-parser-and-validation-hardening).
The canonical benchmark artifacts remain historical 3.1.0 measurements with
their original Django 6.0.6 and GraphQL-core 3.2.11 freeze. They have not been
rerun or relabeled for this patch.

## 3.1.0 — 2026-09-03

**Audit-hardening release.** This release closes all 24 findings from the 3.0
post-release audit across runtime correctness, security guidance, the test suite,
release automation and benchmarks. The public GraphQL API remains compatible,
but cache invalidation is deliberately safer by default.

### What you need to act on

- **Shared cached reads now invalidate globally.**
  `CACHE_INVALIDATION_SCOPE="global"` is the new default, so a successful
  mutation advances one shared GraphQL version and no identity keeps stale
  shared data. Set it to `"identity"` only when every cached response is truly
  private and the narrower 3.0 invalidation policy is intentional. Cache keys
  now carry a `v2` format marker and the selected scope, so old entries cannot
  reappear after the policy changes.
- **Cookie-dependent queries bypass the response cache by default.** The new
  protected `GraphQLView.should_cache_query(request)` hook rejects requests
  with cookies because the standard key cannot represent session, cart, tenant,
  locale or feature-flag state. An override may re-enable them only if its cache
  key represents every varying part of that context. Executed mutations still
  invalidate normally.
- **CRUD permission hooks remain synchronous.** If a `BasePermission` create,
  update or delete hook returns an awaitable, django-graphex now closes it and
  raises `ImproperlyConfigured` before any row is written. Subscription
  authorization continues to support its documented async hooks.

### Fixed

- A syntactically valid mutation rejected with HTTP 405 or a validation error
  used to advance the cache version even though no resolver ran. Invalidation
  now occurs only after execution could have produced durable writes; atomic
  rollbacks still leave the version unchanged.
- Anonymous requests with different cookies could share a response through the
  common `anon` identity. Cookie-bearing queries now skip both cache lookup and
  storage, while cookie-free public queries can still share entries.
- Subscription `on_commit` callbacks captured a mutable model instance. A
  create followed by update or delete in one transaction could therefore
  publish the final state twice or publish a create event with `pk=None`.
  Callbacks now carry immutable per-save snapshots and emit nothing on rollback.
- `CLEAN_RESPONSE` classified a multi-operation document by its first operation
  instead of `operationName`; selected introspection responses now preserve
  their required `null` and empty-list values.
- Renamed subclasses of `MultiSelectField` now compile to list-shaped enum types
  in both output and mutation input.
- Query-cost analysis no longer treats a singular field as a collection merely
  because it has an application argument named `limit`; multiplication applies
  only to list-shaped GraphQL return types.

### Documentation and example project

- The authenticated-user quickstart is safe to copy: it projects only public
  user fields, uses `AuthenticatedGraphQLView`, disables response caching in the
  example, and implements registration with `create_user()` instead of generic
  writes. Passwords are hashed and callers cannot assign staff, superuser,
  group or permission state.
- Mutation documentation now states that `permission_classes` on
  `DjangoModelMutation` raises `ImproperlyConfigured`, describes generated
  operations as Create/Update/Delete, and uses neutral models for generic CRUD.
- The playground reset removes stale generated migrations while preserving
  `__init__.py`, and its test commands consistently avoid local migration drift.
  WebSockets now ship with explicit localhost/testserver origin defaults rather
  than an effective allow-all configuration.
- The verified [2.x → 3.0 upgrade guide](UPGRADE-3.0.md) is now published. It
  documents and reproduces behavior that already shipped in 3.0; it is not a
  claim that those 3.0 changes were introduced again in 3.1.

### Test and release engineering

- [#146](https://github.com/eamigo86/django-graphex/issues/146) adds the global CI gate: public APIs require
  complete Google-style contracts and type hints without repeated types, every
  docstring is free of backticks, and CI combines `--strict-public` with
  `--strict-content` without a changed-owner ratchet.
- Channels-free runs keep collecting transaction/savepoint tests, broad
  `pytest.raises(Exception)` contracts were replaced by exact failures, and
  focused commands use `--no-cov`. CI enforces branch coverage and changed-line
  coverage above 95%, while tox tools resolve inside explicit version bounds.
- A PostgreSQL 17 gate now exercises foreign-key failures, nested rollbacks,
  many-to-many rollback, autocommit and connection reuse against the real
  backend instead of relying solely on SQLite.
- Release automation builds the wheel and sdist once, smoke-tests the installed
  wheel outside the checkout, audits that exact wheel, records checksums, and
  carries the same immutable artifact to PyPI and the GitHub Release.
- Tagged publication now waits for the complete test matrix, base install,
  security/quality, coverage, PostgreSQL, documentation, playground and
  distribution checks. Manual dispatch targets TestPyPI only; PyPI and Pages
  publication remain tag-driven.

### Benchmarks

- The nested workload now enforces the documented 20 authors × 10 posts × 5
  comments with exact IDs, order and content across all four libraries.
- Every validation, SQL probe, warmup and timed mutation rolls back, so library
  order cannot accumulate rows or bias later measurements.
- Direct and transitive benchmark dependencies are pinned, offline replay has
  explicit cache semantics, and Ariadne's Django adapter is a required input.
- `python benchmarks/run_publish.py --authors 1000 2000 --runs 3` is the sole
  canonical-results publisher. It recreates each database, rotates library
  order, validates every run, computes medians and writes results atomically;
  `run_all.sh` remains a non-publishing diagnostic.

### Audit traceability

| # | Area | Resolution in 3.1.0 |
|---:|---|---|
| 1 | Cache isolation | Cookie-dependent anonymous queries bypass response caching. |
| 2 | Cache invalidation | Rejected or unexecuted mutations no longer advance versions. |
| 3 | Documentation security | The `auth.User` quickstart uses safe projection, auth and registration. |
| 4 | Release gates | Every validation job blocks tagged PyPI publication. |
| 5 | Immutable artifact | PyPI and GitHub Release consume one checked wheel/sdist artifact. |
| 6 | Subscriptions | Transaction callbacks publish immutable per-save snapshots. |
| 7 | HTTP response cleaning | `operationName` selects whether introspection data is preserved. |
| 8 | Type compilation | `MultiSelectField` subclasses stay list-shaped in output and input. |
| 9 | Cache freshness | Global invalidation is default; identity scope remains opt-in. |
| 10 | Query limits | Singular fields named `limit` no longer receive list multiplication. |
| 11 | Permissions | Async CRUD permission hooks fail closed before writes. |
| 12 | Packaging | A clean external environment tests the exact release wheel. |
| 13 | Test suite | Core savepoint tests run without the optional Channels extra. |
| 14 | Test suite | Exception contracts assert exact classes and messages. |
| 15 | Coverage | Focused tests avoid false global gates; CI checks patch coverage. |
| 16 | Tooling | Tox and development tools use explicit compatible bounds. |
| 17 | PostgreSQL | Real-backend transaction integration is a release gate. |
| 18 | Documentation | Mutation permission and generated-operation contracts are accurate. |
| 19 | Playground | Reset and test workflows recover from stale local migrations. |
| 20 | Playground security | Default WebSocket origins are restricted to local hosts. |
| 21 | Benchmarks | Nested results must satisfy the full 20×10×5 contract. |
| 22 | Benchmarks | Measured mutations roll back and cannot contaminate later runs. |
| 23 | Benchmarks | Environments are pinned and support deterministic offline replay. |
| 24 | Benchmarks | Validated three-run medians are published atomically. |

## 3.0.0 — 2026-08-27

**Security release, and the largest set of breaking changes since 2.0.** Read
this section before upgrading: it names every one of them in one place, and each
is expanded in the entries below.

The major bump is what the breaking changes below require, not a rewrite: the
API you write is the 2.x API. What changed is what the library **refuses**. A
schema that never answered a question its own projection said it would not
answer builds unchanged.

The theme is a single rule finally enforced everywhere it was already written
down: **`Meta.only_fields` / `Meta.exclude_fields` are a security boundary, not
an output shape.** A column a type hides must be unreadable, unorderable **and**
unfilterable through it. Read it once in
[Types › The projection is a security boundary](usage/types.md#projection-security-boundary);
every other page links there.

**Two new settings ship ON.** Both change behaviour for existing clients.

- **`REQUIRE_CSRF_HEADER`** (`True`) demands an **`X-Requested-With`** header on
  POSTs whose content type a browser can send cross-site with no CORS
  preflight — `application/x-www-form-urlencoded`, `multipart/form-data`,
  `text/plain`, and a body-less POST with no content type — on the HTTP views
  **and** the SSE subscription endpoint. Without it: **HTTP 403** before the
  body is read. Form-encoded clients break, and so does **any multipart upload
  client written against 2.2.0**. `application/json` and `application/graphql`
  clients change nothing.
- **`MAX_SUBSCRIPTIONS_PER_CONNECTION`** (`50`) caps the concurrent operations
  one `graphql-transport-ws` socket may hold. The socket and everything already
  running on it survive a refusal; SSE is unaffected. `None` restores the old
  unbounded behaviour.

**Requests that used to succeed are now refused at query time.** All on the
ordering axis, all closing a read the rule always prohibited:

- ordering by a column the type projects away, by a type's **own** hidden
  primary key, or by a model field name a `resolve_<name>` of yours masks;
- ordering by a relation's `_id` when that relation is served by a resolver of
  your own — the [scoping hatch](usage/types.md#relation-scope-hatch), in either
  direction;
- ordering by a forward FK's `_id` when the **target** type hides the key it
  points at;
- an operator-configured `ordering=` naming a projected-away column, which now
  raises on **every** request through `CursorGraphqlPagination` (it echoes the
  value in the cursor); `LimitOffset` / `Page` keep their operator exemption;
- cursor-paginating a list type whose SDL does not publish its primary key.

**Schemas that build today can stop building.** That is the point — every one
of them was answering a question the projection said it would not:

- a `filter_fields` entry naming a projected-away column, a masked relation, a
  hop through either arm of the scoping hatch, `pk`, or a lookup spelled into
  the key instead of the value;
- `only_fields` / `exclude_fields` / `include_fields` on a
  `DjangoListObjectType` that reuses a node type already registered for the
  model (restating that node's own projection is still accepted).

**And one that does NOT stop the build, which is worse.**
`MAX_QUERY_DEPTH` / `MAX_QUERY_COST` set to `0` or a negative value used to
switch the guard off silently, and is now refused — but the refusal fires when
the setting is READ, on the first request, not while the schema builds.
So the schema builds, `manage.py check` stays green, and the first signal is a
failing request. `None` remains the only way to disable a guard. Grep your
settings for a literal `0` on either key before you deploy; the value you want
is `None`.

**Four more behaviour changes worth checking before you upgrade:**

- **Subscriptions are now measured against `MAX_QUERY_DEPTH` / `MAX_QUERY_COST`.**
  Both transports previously validated with graphql-core's default rules, so
  neither guard ever saw a subscription document. This can only reach a
  **hand-written** subscription with a nested payload: the library's own
  generated event types are flat by construction, so they measure depth 1 and
  cost 1, and neither setting can legally go below 1.
- **An `async def` subscribe gate now actually denies.** It failed **open**:
  `authorize_subscription`'s wrapper discarded the coroutine, so the check never
  ran. A subscription that used to be granted may now be refused — by the gate
  you wrote.
- **`BaseGraphQLView.format_error` is an instance method** taking the request:
  `format_error(self, error, request=None)`. A subclass overriding the old
  `@staticmethod format_error(error)` must be updated.
- **A chunked multipart body now gets `411` instead of a confusing `400`** when
  `MAX_REQUEST_BODY_SIZE` is configured and the request declares no
  `Content-Length`. The **413** for an over-sized multipart body is *not* new —
  2.2.0 answered it with a byte-identical message. Only when the setting is
  configured; the `None` default is inert on every content type.

**Removed.** The **`CAMELCASE_ERRORS`** setting (it had zero consumers and
changed nothing), plus six internal names — four of which were importable, so
`from django_graphex.utils import get_obj` / `create_obj` and
`converter.assert_valid_name` / `convert_choice_name` now raise `ImportError`.

### Security

- **A relation served by a `resolve_` method of your own ranked and filtered by
  the key behind it.** The mask stamp — which withdraws a declared attribute
  that publishes a column's NAME over a resolver serving something else — was
  carved out for a declared RELATION, on the argument that a relation's name is
  not a column's and the key behind it is the *target* type's answer. That
  argument holds for the AUTO-EXPANDED relation, whose value really is the row's.
  It does not hold for a declaration served by a resolver: `ordering: "authorId"`
  ranks by the raw foreign key on the parent's own row and
  `filter_fields = {"author__name": …}` joins straight past the target type, so
  a `resolve_author` returning a redacted stand-in — or nothing at all — left a
  live ranking oracle over a key **no type in the schema serves**. That shape is
  indistinguishable at build time from the to-one scoping hatch
  [Types › Custom queryset](usage/types.md#relation-scope-hatch) documents, whose
  resolver returns a *scoped* target and still ranks the rows it hides: the
  difference lives in a resolver body no static analysis can read. Both now fail
  **closed**, like every other masked declaration. **This rejects orderings that
  used to succeed and fails a schema that builds today**: declaring the hatch
  withdraws that relation's `_id` column from the ordering allowlist, and a
  `filter_fields` path through the declared relation raises
  `ImproperlyConfigured` while the schema builds. Both were already the guide's
  own written remedy for the leak — drop the relation's filter paths, project
  the key away — so the boundary now does by itself what the reader was being
  asked to do by hand. A declaration carrying **no** resolver is untouched: it
  serves the attribute, so it keeps both axes.
- **The to-MANY half of that same hatch stayed open.** Closing the to-one arm
  left its byte-equivalent twin fail-open: a relation declared as
  `posts = DjangoFilterListField(PostType)` — which
  [Types › Custom queryset](usage/types.md#relation-scope-hatch) teaches for the
  identical purpose, and which carries a resolver of its own by construction —
  never reached the mask stamp, so `filter_fields = {"posts__title": …}`
  compiled to an ORM join that reaches every row the mounted list field's
  `get_queryset` exists to hide. One user intent, one release, two opposite
  answers. Both arms now answer the same. The to-MANY arm's cost is strictly
  smaller than the to-one arm's, because a reverse foreign key or a
  many-to-many owns no column on the parent row: **nothing leaves the ordering
  allowlist**, the relation stays selectable and stays scoped, and what goes is
  the nested `posts__…` filter path — **which stops the schema building** with
  `ImproperlyConfigured`. Drop those entries when you declare either arm.
- **The shared filter input could be widened by a build the guard never saw.**
  The union of every declaration sharing one `<Model>FilterInput` is measured
  against every type serving it — but the measurement read the cache BEFORE the
  assertion, and the assertion FORCES compiled field maps, which re-enters the
  builder for the same model through a nested list field's own thunk. On that
  path the cache entry was born inside the assertion, and the branch that
  returned it recorded the narrow type as a server of paths nothing had ever
  measured: its list field answered `filter: {bio: {icontains: …}}` for a column
  its own SDL denies. The union is now measured in a loop that re-reads the
  cache until it stops moving, so the shape being served and the shape being
  measured cannot differ.
- **One WebSocket socket could open unbounded subscriptions.** The
  `graphql-transport-ws` consumer registered every accepted `subscribe` with no
  ceiling, and each live operation joins its own channel-layer group — so a
  single client turned one connection into hundreds of subscribers (500
  concurrent operations on one socket was reproduced) while the HTTP side had
  bounded its analogous surface with `MAX_BATCH_SIZE` since 1.2.1. The new
  **`MAX_SUBSCRIPTIONS_PER_CONNECTION`** setting (default `50`) caps the
  concurrent operations one socket may hold. **This rejects subscriptions that
  used to be accepted**, but only past 50 concurrent operations on a *single*
  connection; a `subscribe` past the cap is answered with the transport's own
  `error` frame naming the limit, and the socket plus every subscription
  already running on it survive untouched. A slot frees itself the moment its
  operation ends (client `complete`, stream end, or disconnect). Set
  `MAX_SUBSCRIPTIONS_PER_CONNECTION = None` to restore the previous unbounded
  behaviour. The SSE transport is unaffected: one request carries exactly one
  subscription. See
  [Subscriptions › Per-connection subscription cap](usage/subscriptions.md#per-connection-subscription-cap).
- **A cross-site form could execute mutations under the victim's session.** The
  endpoint is `csrf_exempt` and `parse_body` accepts
  `application/x-www-form-urlencoded` and `multipart/form-data`. Both are
  CORS-*simple* content types, so a `<form>` on any origin posted straight
  through with no preflight and the browser attached the victim's session
  cookie — a plain CSRF hole on every mutation. The same hole was open on the
  **SSE subscription endpoint**, which is `csrf_exempt` too and reads a
  form-encoded `query` straight out of `request.POST`. The new
  **`REQUIRE_CSRF_HEADER`** setting (default **`True`**) now demands the
  **`X-Requested-With`** header on the CORS-simple set — form-encoded,
  multipart, `text/plain`, and a body-less POST carrying no content type at all
  — and answers HTTP 403 before the body is read otherwise, on the HTTP views
  **and** on the SSE endpoint (whose refusal is a plain body, not a JSON
  envelope, because an `EventSource` client does not parse one). The header is
  not CORS-safelisted, so requiring it forces back the preflight the attacker
  page cannot pass; the value itself is never inspected. The check runs **ahead
  of every dispatch**, wrapped around the view callable, because
  `GraphQLView.dispatch` owns the whole response-cache interaction and reaches
  the shared dispatch only through `super_call`: a guard behind it is bypassed
  by a warm cache entry, has its own 403 stored and replayed to legitimate
  callers, and still lets a rejected mutation flush the caller's cache
  namespace. **`application/json` and `application/graphql` clients change
  nothing**: neither is simple, so both already required a preflight. See
  [Security › Cross-site POST protection](usage/security.md#cross-site-post-protection).

    !!! warning "This is a breaking change for two kinds of client, on by default"

        **Who breaks.** Anyone POSTing `query=` as
        `application/x-www-form-urlencoded`, and **anyone using the multipart
        file upload shipped in 2.2.0** — that feature works in the published
        release, so upload clients written against 2.2.0 do break here.

        **What they see.** HTTP 403 with
        `This content type requires the X-Requested-With header. …`, before the
        body is read. The message names the header; there is no silent failure
        and no partial execution.

        **The fix, one line.** Add the header to the request:
        `headers={"X-Requested-With": "XMLHttpRequest"}` (`requests`),
        `xhr.setRequestHeader(...)`, or the equivalent. The value is never
        inspected. Nothing else about the request changes.

        **The opt-out.** `REQUIRE_CSRF_HEADER = False` restores the previous
        behaviour wholesale. Use it only if a client genuinely cannot set a
        header **and** the endpoint is protected another way.

        **Why multipart is not exempted.** `multipart/form-data` is itself a
        CORS-simple content type, so a cross-site `<form enctype="multipart…">`
        posts to the endpoint with no preflight at all. Exempting it to spare
        the upload clients would reopen exactly the hole this closes — and
        would leave the *upload* mutations, the ones that write files, as the
        only unprotected surface.

- **Disabling introspection still leaked the schema, one guess at a time.**
  `format_error` returned graphql-core's `formatted` mapping verbatim, so the
  `Did you mean 'email'?` suggestion appended to an unknown field, type or
  argument rode out even with `DisableIntrospectionMiddleware` installed —
  probing with invented names rebuilt much of a schema the operator believed
  was hidden. The WS and SSE transports leaked it by the same route, serializing
  raw `error.formatted` of their own, so any deployment exposing subscriptions
  kept the oracle open on a `subscribe` frame or a direct POST to the SSE
  endpoint. The trailing suggestion sentence is now stripped whenever
  introspection is **actually** disabled (the middleware installed *and*
  `ALLOW_INTROSPECTION=False`), through **one shared formatter**
  (`django_graphex.security.format_graphql_error`) that the HTTP view and both
  transports call — WS covers its validation errors, its subscribe-entry
  failures and its in-stream `next{errors}` frames. The strip is keyed on the
  **rules that actually leak** — `FieldsOnCorrectTypeRule`,
  `KnownTypeNamesRule`, `KnownArgumentNames*Rule`, `ValuesOfCorrectTypeRule` /
  `coerce_input_value` and enum-value coercion — by matching the message each
  one writes ahead of its suggestion, not by matching the shape of a trailing
  `Did you mean …?` sentence. Nothing else changes: the rest of the message, the
  `locations` and the `path` all survive; `ScalarLeafsRule`'s
  `Did you mean 'field { … }'?` guidance (built from the name the *client*
  typed, not from the schema) and a resolver-raised application error that
  happens to end in a question keep every word; and with introspection allowed
  the suggestion is kept because the same names are public anyway. The strip is
  request-independent by design, so the `INTROSPECTION_ALLOW_SUPERUSER` bypass
  does not restore it — an error body reaches the response cache, where a
  per-user decision would serve one caller's body to another. See
  [Security › "Did you mean" suggestions are stripped too](usage/security.md#did-you-mean-suggestions-are-stripped-too).
- **`PERMISSION_SCOPED_SCHEMA` treated a typed GFK union as public.** The
  implicit relation label is derived from the output type's
  `extensions["gdx"]._meta.model`, and a `GraphQLUnionType` has no model — so a
  `Meta.unions` GenericForeignKey field stayed untagged, and untagged means
  public. The abstract arm of the relation-traversal bypass the 2.2.0 notes
  describe: a caller whose *direct* root field to a member type was pruned away
  still read that member's rows through the union. A union's requirement is now
  the **union of its members'** read permissions, so keeping the field takes
  every member's `view_M`. **This prunes a field that used to survive**: a
  caller holding one member's permission but not another's now loses the field
  entirely, because the union can return either member and the requirement
  applies to the whole field. Expose the members as their own fields if they
  are meant to be reachable independently. See
  [Permission-scoped schema › A typed GFK union requires every member's permission](usage/permission-scoped-schema.md#a-typed-gfk-union-requires-every-members-permission).
- **`ordering` was a read oracle over every column the type hides.** The
  allowlist was built from `model._meta.concrete_fields` — the MODEL's columns,
  not the TYPE's projection — so a column removed with `only_fields` /
  `exclude_fields` was absent from the SDL, unselectable and unfilterable, and
  still fully sortable. Sorting by it ranks the visible rows by the hidden
  value; with a filter narrow enough to isolate a pair of rows the value is
  recovered exactly, and a hidden boolean was read back for every row of a test
  table. The docstring of the guard claimed it already rejected
  `password` / `is_superuser`, and there was no `ordering_fields` option
  anywhere in the package, so a project had no way to mitigate it. The
  allowlist is now **read off the compiled node type that actually serves
  `results`** — the type in the SDL, resolved per schema when that schema is
  built — and enforces it on all three ordering paths: the queryset path, the
  prefetch-cache (in-memory) path, and the nested window-prefetch optimization
  — which applied its `ORDER BY` in SQL and returned pre-sliced rows, so no
  later guard ever saw the term. For `LimitOffsetGraphqlPagination` and
  `PageGraphqlPagination` the allowlist gates the **client argument only**: the
  `ordering=` you pass when constructing one of those paginators is your own
  configuration, identical on every request and never echoed back — the response
  is the rows — so it may name a projected-away column and still serve. A client
  that repeats that value is still rejected — the check follows the value's
  provenance, not its text. **This rejects orderings that used to succeed**: any
  client sorting by a column its type projects away now gets
  `Invalid ordering field: '<name>'`. Affected are
  projects that hid a column with `only_fields` / `exclude_fields` while still
  ordering by it — expose the column if the ordering is legitimate, or drop the
  ordering. A forward FK exposed as `author` keeps `author_id` orderable **only
  when the type behind `author` publishes the key it points at** — see the
  shared-predicate entry below — and paginators constructed directly, outside a
  list type, keep the model-wide
  allowlist. **The prefetch-cache path is stricter too**: it previously enforced
  nothing at all on a type that declared no projection, so the same nested list
  answered differently depending on whether its rows came from the database or
  from the prefetch cache. It now refuses the terms the queryset path already
  refused — a relation-spanning `author__name` on a nested list raises instead of
  sorting by nothing. See
  [Pagination › Ordering validation](usage/pagination.md#ordering-validation-security).
- **Two shapes the ordering allowlist wrongly refused, and one it shared across
  schemas.** The allowlist used to be built by re-applying the output compiler's
  `only_fields` / `exclude_fields` / `include_fields` filters by hand, which is a
  copy of the compiler held in a second place — and a copy is wrong for every
  shape it did not anticipate. Three consequences, all closed by reading the
  compiled type instead of re-deriving it:
    - A **multi-table-inheritance child** whose `only_fields` names `id` was
      judged to be hiding its primary key, because a child's own pk is the
      implicit `<parent>_ptr` link and no `only_fields` list can contain it. That
      refused cursor pagination on a working configuration, with a message
      asserting the type hides a key its SDL plainly publishes. Such a type now
      paginates by cursor again.
    - An **explicitly declared class attribute** that re-publishes a column
      `only_fields` removed (`bio = CharField()` on a type restricted to
      `id` / `name`) made that column appear in the SDL while the allowlist still
      refused to order by it. It is now orderable, because it is selectable —
      provided the declaration carries **no resolver**, so that the field really
      does serve the column (see the masked-declaration entry below).
    - **Two schemas over one list container class** shared a single paginator
      object, so building the second schema overwrote the first schema's
      allowlist — the first schema then accepted a hidden column it had refused a
      moment earlier. The per-schema answer now lives on a per-schema copy; the
      instance you construct and mount is never mutated.
- **A natural primary key hidden by the projection was still sortable.** The
  allowlist exempted the primary key unconditionally, after the projection
  filters ran. That is right for a surrogate `id` — ranking rows by an
  identifier the client already reads gives nothing away — but a **natural** key
  (a slug, a code, an email) carries business data and can be projected away
  like any other column, so the exemption handed the read oracle straight back
  on every such model: `ordering: "slug"`, `ordering: "pk"` and the pk's own
  attname all passed the check, on the queryset path, the in-memory path and the
  nested window-prefetch path alike. The pk is now added to the allowlist only
  when the SDL publishes the key's **value**, and the `pk` alias rides
  with it rather than standing on its own. On a multi-table-inherited child that
  value is the parent's `id`, which the SDL does publish, so `ordering: "pk"` and
  the parent-link column keep working there. **This rejects orderings that used to
  succeed** on any type whose `only_fields` / `exclude_fields` removes its own
  primary key. Nothing else changes: the paginators' generated pk tiebreak is
  not client input and is not gated, and where the nested window optimization
  cannot serve that tiebreak it declines and the plain prefetch path returns the
  same rows.
- **`CursorGraphqlPagination` published its ordering column through the
  cursor.** The server-default exemption above rests on the configured ordering
  never being echoed back. `CursorGraphqlPagination` takes the same `ordering=`
  kwarg and *does* echo it: `pageInfo.startCursor` and `endCursor` are base64 of
  `cursor:<ordering value>\x1f<pk>`, so a paginator pointed at a column the node
  type projects away printed that column verbatim to any client willing to
  base64-decode the token — a direct read of the hidden value, not merely a
  ranking of it. The cursor paginator now enforces the projection allowlist on
  its configured ordering regardless of provenance, at the one seam both
  `paginate_queryset` and `get_page_info` resolve the ordering through.
  **This is a hard failure, not a downgrade**: a `CursorGraphqlPagination`
  configured to order by a projected-away column now raises
  `GraphQLError: Invalid ordering field: '<name>'` on every request. Point it at
  a column the node type exposes. See
  [Pagination › Ordering validation](usage/pagination.md#ordering-validation-security).
- **`CursorGraphqlPagination` also published a hidden primary key through the
  cursor.** Gating the ordering column left the other half of the token open: a
  composite cursor is `cursor:<ordering value>\x1f<pk>`, and that `<pk>` is
  appended unconditionally. A type whose `only_fields` / `exclude_fields` removes
  its own **natural** primary key — a slug, a code, an email — therefore had that
  key printed verbatim in `pageInfo.startCursor` and `endCursor` even when the
  ordering named a perfectly public column. The tiebreak is what makes the keyset
  boundary total, so it cannot simply be dropped: without it a `value > boundary`
  page silently skips every row tied on the ordering value. Encrypting the cursor
  would keep both properties at the cost of a key to manage, a rotation story and
  a wire-format break; tiebreaking on an exposed column instead needs that column
  to be unique, which nothing can promise. So **the configuration is refused**: a
  list type whose SDL does not publish its primary key's value can no longer be
  paginated by cursor, and every request raises `GraphQLError` naming the problem
  without naming the hidden column. That covers an `only_fields` list that simply
  omits the key as much as an `exclude_fields` that names it, and it does **not**
  cover a multi-table-inherited child, which publishes the parent's `id`. Publish
  the key, or use `LimitOffsetGraphqlPagination` /
  `PageGraphqlPagination`, which echo nothing. **The cursor's wire format is
  unchanged** — existing cursors keep decoding exactly as before. See
  [Pagination › Ordering validation](usage/pagination.md#ordering-validation-security).
- **A nested list whose child type hides its pk failed on an empty `ordering`.**
  The prefetch-cache path substitutes the paginator's own pk ordering when none
  was resolved, so the in-memory page matches the DB-side window slice. Provenance
  was read off *whether the client sent an `ordering` argument*, and an argument
  can normalize to nothing (`","`, `" "`, `"+"`): the projection allowlist then
  survived while the value did not, and the server's own tiebreak was validated as
  if the client had asked for it. Any such value answered
  `Invalid ordering field: 'id'` on a nested list whose child type projects its
  primary key away. The substitution now drops the allowlist along with the value
  it replaces. A real client term outside the allowlist is still rejected.
- **A declared field could publish a column's NAME while hiding its value, and
  `ordering` believed the name.** Reading the allowlist off the compiled type
  answers "is this name in the SDL", which is not the same question as "does
  this field serve that column". A declared class attribute wins over the
  model-derived field of the same name, so a type could drop `bio` with
  `only_fields`, declare `bio = CharField()` with a `resolve_bio` returning
  `"[redacted]"`, and hand every client the redaction while
  `ordering: "bio"` ranked the rows by the raw column — the read oracle the
  projection exists to close, rebuilt out of the type's own declaration. On
  `CursorGraphqlPagination` it was not even a ranking: the hidden value came
  back verbatim inside `pageInfo.startCursor`. A masked `id` did the same for
  the primary key, carrying `ordering: "pk"` in with it. The compiler now marks
  a declared field whose value does **not** come from the column — the test is
  the resolver it compiled, so a field-level `resolver=` and a class
  `resolve_<name>` are both covered — and the allowlist skips those columns.
  **This rejects orderings that used to succeed** on any type that declares a
  resolver over a model field name; a declaration with no resolver keeps the
  default attribute resolver, still serves the column, and stays orderable. The
  rule fails closed: a `resolve_<name>` that happens to return the real column
  loses the ordering term too, because no build-time check can read a resolver
  body. Drop the resolver, or publish the substitute under a different name. See
  [Pagination › Ordering validation](usage/pagination.md#ordering-validation-security).
- **A pruned schema answered ordering questions with the FULL schema's
  allowlist.** Under `PERMISSION_SCOPED_SCHEMA` the pruned schema is a clone,
  and cloning a field carried its resolver through verbatim — including the
  paginator the allowlist is stamped on, which was derived once against the
  *unpruned* node type. A caller denied `view_author` was served a schema with
  no `author` field on the post node and no author type in the type map at all,
  and could still send `results(ordering: "-authorId")` and rank the rows by
  that foreign key. Every pruned clone now stamps its own paginator copy from
  the node type **that clone** publishes, so the answer belongs to the schema
  actually serving the request; a caller holding the permission keeps the term
  on the very same field. Both paginating shapes are covered: the list
  container's `results` and a flat `DjangoFilterPaginateListField`. Schemas
  built without the flag are untouched. See
  [Permission-scoped schema › `ordering` follows the pruned schema](usage/permission-scoped-schema.md#ordering-follows-the-pruned-schema-not-the-full-one).
- **An anonymous caller could plant unbounded permanent cache entries.**
  `GraphQLView.cache_key_prefix` partitions the response cache by a hash of the
  `Authorization` header when the request is not authenticated — unverified
  input a client can vary per request — and each identity seeds its own
  namespace version counter, stored with `timeout=None` so it never expires (it
  has to outlive the responses it namespaces). One anonymous client sending a
  fresh token per request therefore minted a fresh never-expiring cache key per
  request. The counter's namespace is now **bucketed** for any identity derived
  from an unauthenticated request: a fixed 64 buckets, so what an anonymous
  caller can create is bounded no matter how many credentials it invents.
  Authenticated identities (bounded by your user table) and the single shared
  `anon` partition keep their exact namespace. **Isolation is unchanged** — the
  response entry still carries the full identity, so two callers sharing a bucket
  never share a response body. **Invalidation granularity is a behaviour
  change**: two token-only callers that land in the same bucket now share a
  version counter, so a mutation from one makes the other's cached entries
  unreachable. The counter only moves forward, so that can only turn a cache
  **hit** into a **miss** — the next read re-executes against current data and
  nothing stale is ever resurrected — but a token-only client that relied on its
  reads surviving another client's mutation will see extra misses. Authenticate
  it to get its own counter back. A custom `cache_key_prefix` inherits the bound
  automatically. **The spent property is reachable by an attacker, and that is
  stated rather than closed**: the bucket is a pure function of a caller-chosen
  header, so an unauthenticated client can hash candidates until one lands in any
  bucket it likes and evict that bucket's members. Salting would not help — the
  namespace is small by construction, so a caller that cannot aim can still cover
  it by volume. The ceiling is misses, never bodies. See
  [Caching › Bucketing for unauthenticated identities](usage/caching.md#bucketing-for-unauthenticated-identities-in-identity-scope)
  and
  [Views › Response caching and cache identity](usage/views.md#response-caching-and-cache-identity).
- **A hand-mounted interface field leaked its implementors' rows.** The
  permission-scoped schema derives a field's implicit label from its output
  type's model; an abstract type has none, and the pruner treats an untagged
  field as public. 2.2.0 closed this for typed GFK unions but left the sibling
  interface arm open, so `field(SomeDjangoInterfaceType)` handed a caller rows
  of every implementor while a direct field to the very same implementor type
  was pruned away. An interface's label is now the **union of the read
  permissions of every implementor the schema mounts**, exactly as a union's is
  — an AND, because the field can return any of them. A caller holding some but
  not all of those `view` permissions **loses the interface field** rather than
  keeping one that can still return a row they may not read; expose those
  implementors through their own gated fields instead. The implementors are read
  from the schema's own `get_possible_types`, not from the process-wide registry:
  a registry is populated at class-definition time and is a strict superset of
  what any one schema mounts, so scoping the label to it would have cost a caller
  the field over a type no query could ever reach — turning a leak into an
  outage. The schema-level label set is derived from the same schema, so the two
  can never disagree.
- **A multipart POST under ASGI was bounded by nothing but the client's own
  claim.** `MAX_REQUEST_BODY_SIZE` measures the body itself precisely because
  `Content-Length` is client-supplied — but that measurement reads the body,
  which for `multipart/form-data` breaks the streamed upload and collides with
  the CSRF check, so multipart was left with the declared length as its only
  check. Nothing downstream re-imposed that declaration under ASGI:
  `ASGIHandler.read_body` spools every chunk with no cap and hands the spool
  straight to `request._stream` (no `LimitedStream`, unlike WSGI), and
  `MultiPartParser` builds its reader from `_chunk_size`, consulting
  `_content_length` only to shortcut a **zero**-length body. A multipart POST
  declaring `Content-Length: 100` and sending 8 MiB was therefore answered
  `200 OK` with all 8,388,608 bytes parsed, under a cap of 1 KiB. Multipart is
  now measured **without being read**: `request._stream` is seeked to its end and
  straight back, which allocates nothing, leaves the parser an untouched stream,
  keeps the upload streaming to disk, and reports the real size — the same
  measurement Django's own `HttpRequest.body` performs on a seekable stream, done
  one level up so the answer is a 413 rather than a 400. WSGI is unaffected: its
  `LimitedStream` already truncates an under-declared body, and where the stream
  cannot be seeked a multipart POST declaring **no** length is refused with
  **HTTP 411 Length Required** instead. **This rejects requests that used to be
  accepted** — an under-declared multipart body now gets a 413, and a chunked one
  a 411 on WSGI — and only when the cap is configured; projects leaving it at its
  `None` default are unaffected. Note the boundary, now stated plainly in the
  docs: **no view-level setting can stop a multipart body from being received
  under ASGI**, only from being processed. Bound reception at your ASGI server.
  See
  [Settings › What this cannot do under ASGI](usage/settings.md#what-this-cannot-do-under-asgi).
- **A column a type hid was still fully filterable — the sharpest read oracle in
  the library.** `Meta.only_fields` / `Meta.exclude_fields` removed a column from
  the SDL and, since 2.2.0, from `ordering` — but the filter input ignored the
  projection completely. It is compiled from `Meta.filter_fields` against the
  MODEL, with no idea which columns the type publishes, so
  `filter: { bio: { exact: "…" } }` answered **exactly, in one request**, for a
  column the schema said did not exist. `icontains` turned the same argument into
  a prefix walk that recovers the value character by character, and the whole
  lookup set was published in the SDL as `<Model>FilterInput.bio`, so the oracle
  was discoverable by introspection rather than guessed. Every other door led to
  the same place: a relation-spanning `author__bio` reached it across a join, the
  `and` / `or` / `not` combinators composed over it, a nested list filter and a
  per-field `fields=` override both resolved to the same shared per-model input,
  and a narrow declaration was silently **widened** to the model's root paths, so
  a list that declared only `name` still served `bio`. The projection is now
  what it was always documented to be — a **security boundary, not an output
  shape** — and a `filter_fields` entry naming a column its type projects away
  raises `ImproperlyConfigured` while the schema builds, naming the type, the
  entry and the column. Each hop of a `__` path is measured against the type
  that publishes THAT hop, so hiding `bio` on the author's type also refuses
  `PostType.filter_fields = {"author__bio": …}`; widening a cached input is
  checked on the same path, so the second door is shut with the first. **A schema
  that builds today can therefore fail to build after upgrading — which is the
  point: every schema that stops building was answering that oracle.** The entry
  is refused rather than silently dropped, following the 2.2.0 precedent, because
  dropping it would repeat the exact defect 2.2.0 fixed — an option accepted and
  ignored — and only the operator can say which of the two contradicting options
  was meant. The fix is one line: publish the column (`only_fields` /
  `include_fields`, or drop it from `exclude_fields`), or drop the
  `filter_fields` entry. **One boundary stays open, deliberately and documented**:
  the BODY of an `@filter_field` method, whose argument is an opaque scalar and
  whose ORM lookup lives in user Python where no build-time analysis can see it —
  keep those bodies inside your own projection. Its **name** is checked, so the
  one-line rename out of a refusal is not a bypass; see the shared-predicate
  entry below. Subscription filter inputs were
  already correct (they are built from the projected output field names) and are
  unchanged. See
  [Filtering › The projection is the outer boundary](usage/filtering.md#projection-boundary).
- **The ordering axis and the filter axis had each invented their own notion of
  "hidden", and they contradicted each other.** The two entries above were
  written against the same rule and implemented twice: ordering read the
  compiled type and honoured the compiler's mask stamp, while filtering
  re-derived the answer from `Meta`. On the identical declaration — a column
  `only_fields` removed and a declared attribute put back with a resolver — the
  ordering axis said *published* and the filter axis said *hidden*. That is the
  same drift the ordering axis had already suffered internally, now repeated
  BETWEEN axes, and a schema whose two guards disagree is a schema whose rule
  nobody can state. Both axes now ask **one predicate**,
  `core.output_compiler.publishes_column_value`, against the compiled type that
  will serve the request: *does this type hand out the VALUE this column holds?*
  Absence, a projection, a masking declaration and a compiler-dropped relation
  are one answer, and neither axis can drift from the SDL again. Three
  behaviour changes fall out of it, all breaking, all in the same direction —
  **closing a read the rule always prohibited**:
    - **A forward FK's `_id` column now follows the TARGET type's key.**
      `ordering: "author_id"` was admitted unconditionally whenever the node
      published `author`, justified by "the id is already readable through
      `author { id }`" — a claim about the *author's* type that nobody asked.
      Where that type projects its own key away, `author { id }` does not exist
      either, so the ordering ranked rows by a key nothing in the schema hands
      out. It is now refused with `Invalid ordering field: 'author_id'.`, and
      `filter_fields = {"author": ("exact",)}` is refused at build time on the
      same configuration, because a relation named with no tail filters on that
      same key. **Publish the key on the target type** if the ordering or the
      lookup is legitimate.
    - **A `filter_fields` path through a relation whose target model has no
      registered type now fails the build.** The output compiler drops such a
      relation, so the schema could never name the rows the nested filter input
      reached — a substring oracle over a model no query can select. Register a
      type for the target, or drop the path.
    - **An `@filter_field` method spelled like a projected-away column now fails
      the build.** Its name compiles the very `<Model>FilterInput` field a
      `filter_fields` entry naming it is refused, so the rename out of a refusal
      is shut. The method **body** remains the documented open boundary; a
      method whose name is not a column on the model is untouched.

  One over-refusal was closed in the same pass, in the opposite direction: the
  same-name `source=` shortcut (`bio = CharField(source="bio")`) compiles to a
  resolver that provably reads that very attribute, so it is no longer stamped
  as a mask and the column stays orderable **and** filterable. A `source=`
  naming a different attribute, and a `resolve_<name>`, still withdraw the
  column. The rule, its one exception and the two boundaries it cannot close are
  now stated once, in
  [Types › The projection is a security boundary](usage/types.md#projection-security-boundary);
  every other page links there.
- **The filter guard measured the projection of a type that was not serving the
  request.** It resolved the serving type by MODEL through the graphene
  registry — a last-wins index a type opts out of with the public
  `Meta.skip_registry` — so the boundary was measured against whichever type
  happened to hold the model's slot. A narrow type that left the registry, or
  simply lost the slot to a wider sibling declared after it, was checked against
  the sibling's projection and its own hidden columns sailed through: the guard
  was a no-op for exactly the type about to answer. The compiler path now NAMES
  the type it is measuring — `core.base.resolved_output_type` on the pair being
  built, so a permission-scoped clone is measured as itself, and a list-object
  field is measured against the node it paginates rather than the container.
- **A relation-direct filter entry over a reverse FK or a many-to-many skipped
  the boundary entirely.** `{"posts": ("exact",)}` filters on the *post's*
  primary key, but a reverse foreign key and a many-to-many own no column on the
  declaring model, so the predicate declined them and the last-hop check let
  them through — while the byte-identical `{"posts__id": …}` spelling of the
  same query was refused. Same query, two spellings, opposite answers. The
  target's key is now asked of the target type directly, so both spellings agree.
- **Two node types over one model shared one `<Model>FilterInput`, and only one
  of them was measured.** The input is cached per **model** and every context
  converges on the model's root declaration, so a narrow `DjangoObjectType`
  mounted beside a wide one is served the **union** of both declarations — while
  the guard only ever saw the declaration in front of it. The narrow type's list
  field was therefore filterable by a column its own SDL projects away, with no
  build failure at all. The boundary is now measured against the union the shared
  input will actually serve, and against **every** type that will serve it.
- **A `DjangoListObjectType`'s projection was silently discarded whenever a
  `DjangoObjectType` was already registered for the model** — which is the
  ordinary documented arrangement. The container builds its node type from
  `Meta.only_fields` / `include_fields` / `exclude_fields` **only** when it mints
  it; reusing a registered type dropped all three without a word, so every column
  the operator meant to hide stayed readable, orderable and filterable.
  Declaring one in that situation now raises `ImproperlyConfigured` at class
  definition, naming the option, the model and the type that registered the node
  — the same answer 2.2.0 gave the identical defect on `DjangoModelType`. **This
  fails a schema that builds today**, deliberately: only the already-leaking
  configuration is affected, and the fix is to move the projection to the node
  type, where it was always taking effect. See
  [Types › Configuration Options](usage/types.md#configuration-options).
- **Under `PERMISSION_SCOPED_SCHEMA` the two axes disagreed on the same pruned
  schema.** The ordering allowlist is re-derived from the pruned clone and
  refuses a dropped relation's column; the `filter` argument and its whole nested
  `<Model>FilterInput` rode through the prune verbatim. One schema, two answers —
  and the surviving half was a prefix oracle over a model the clone does not
  mount. The pruned filter input now narrows with the schema on the same
  predicate: a relation the pruned node type no longer publishes is dropped from
  it, and a nested input left over an unmounted model falls out of the type map.
  The full schema is untouched, and each pruned variant carries its own clone.
  See
  [Permission-scoped schema › `filter` follows the same prune](usage/permission-scoped-schema.md#filter-follows-the-same-prune).
- **A `filter_fields` entry naming nothing was accepted and ignored.** `"pk"` is
  an ORM alias `_meta.get_field` does not answer to, and `"id"` names no column
  on a natural-key model; either one compiled to **nothing**, so an operator
  reading their own `Meta` believed the list was filterable by its key while
  every request returned the unfiltered set. A segment naming no field on the
  model that owns it now fails the build, naming the model's real primary key.
  A lookup spelled into the KEY (`"name__icontains"`) is refused by the same
  guard, and for the same reason: lookups are declared in the entry's **value**,
  so the compound key lands on the model's own leaves where `_meta.get_field`
  does not answer to it and the field thunk dropped it. It compiled to exactly
  as much as `"pk"` — nothing — and exempting it refused one dead spelling while
  accepting its byte-equivalent twin. **This rejects a declaration that used to
  build**: move the lookup into the value (`{"name": ("icontains",)}`), which is
  what it was always compiled from.

### Changed

- **Subscriptions are now measured against `MAX_QUERY_DEPTH` and
  `MAX_QUERY_COST`.** Both transports validated with graphql-core's default
  rules, so the depth and cost guards never saw a subscription document — while
  [Mutations](usage/mutations.md) says they are enforced on "query, mutation,
  and subscription selection sets" and
  [Query optimization](usage/query-optimization.md) says "**all** GraphQL
  operation types". The WebSocket and SSE transports now validate with the same
  settings-driven rule tuple the HTTP view uses. A subscription's selection set
  is re-executed for every delivered event, so an over-deep or over-costly
  document was paid for repeatedly rather than once — the guard matters more
  here than on a one-shot query, not less. **Which subscriptions this can reject
  is narrower than it sounds**, and worth stating so nobody raises a limit they
  did not need to: the library's own generated event types are FLAT by
  construction — the build-time guard in `subscriptions/guard.py` enforces it,
  and relations render as IDs — so a generated subscription measures depth 1 and
  cost 1, and neither setting can legally be set below 1. Only a **hand-written**
  subscription with a nested payload can trip either guard; that project must
  raise the limit far enough to cover its documents, or flatten the payload.
- **`BaseGraphQLView.format_error` is now an instance method taking the
  request** — `format_error(self, error, request=None)`, previously
  `@staticmethod format_error(error)`. It has to be: the formatter decides
  whether to strip the schema suggestion by looking at the middleware chain, and
  the chain that actually ran comes from `get_middleware(request)`, the same
  per-request hook execution asks. A static, request-less formatter could reach
  neither, and a subclass that resolves middleware per request got a formatter
  whose verdict disagreed with the chain that ran. **Migration:** a subclass
  overriding it as `def format_error(error)` (or a caller invoking
  `MyView.format_error(err)` on the class) must become
  `def format_error(self, error, request=None)`. Calls through an instance —
  `self.format_error(err)` — are unaffected.

### Fixed

- **An SSE subscription sent no bytes at all until its first event.** Django's
  ASGI handler emits `http.response.start` before iterating the body, but a
  server only writes the status line and headers when the first body chunk
  arrives — daphne stores them on `http.response.start` and flushes on the
  first `write()`. So an idle stream left the client with no response
  whatsoever: a browser's `fetch` never resolved (the bundled client could not
  show a connected state), and an intermediary proxy times a silent connection
  out. Every stream now opens with an SSE comment line (`:\n\n`) before
  anything else — including before an in-stream denial, so a refused subscribe
  flushes too. A comment is not an event; conforming clients ignore it, and the
  bundled browser client was taught to as well — its parser had no comment
  guard, so it reported "Connection Error" on a healthy stream. Both transports
  are now verified end to end in a real browser.
- **The depth-limit refusal named an operation the client never sent.** The
  budget was labelled `'query'` unconditionally, so an over-deep mutation — and,
  now that both subscription transports validate with the shared rule tuple, an
  over-deep subscription — was refused for a query that was not in the request.
  The label is the operation's own kind.
- **Both transports reported a document they could not SELECT from as the wrong
  error.** `get_operation_ast` answers `None` for three unrelated reasons: the
  operation is not a subscription, the document carries several and the request
  named none, and the name matches no operation at all. All three produced
  "only serves subscriptions", which sends the caller hunting for a query or
  mutation their document does not contain. The two selection failures now name
  themselves — one says to pick an operation with `operationName`, the other
  names the operation the document does not define.
- **A WebSocket subscribe could end in total silence.** Two changes in this
  release interact: both transports now validate with the shared rule tuple,
  whose depth rule READS `MAX_QUERY_DEPTH` at validation time, and the settings
  reader now refuses a limit of `0`. `ImproperlyConfigured` is not a
  `GraphQLError`, so it never became a validation error — it escaped the
  operation task, whose done-callback only *logged* it. The client received no
  `error`, no `complete` and nothing else, and waited forever: byte-for-byte
  the shape the malformed-payload fix eliminated, reached by another route, and
  reachable by a misconfiguration that fails loudly on HTTP while hanging
  silently here. Every operation is now wrapped so any escaping error is framed
  as `error{id}`; `CancelledError` still propagates untouched, because a client
  `complete` or a disconnect is a teardown and not a fault.
- **The SSE transport answered 500 where the HTTP view answers 400.** A
  `variables` value that is not a mapping reached graphql-core, which raises a
  plain `TypeError` that nothing wrapped, so it escaped the async view. Two
  reachable shapes: a JSON body carrying `variables` as an encoded string
  (which the HTTP view has always decoded), and any form-encoded body, where
  every value is a string by construction. The transport now decodes and
  validates it the same way the HTTP view does.
- **The published sdist could not run its own test suite.** The allowlist ships
  `/tests`, and three of those modules load a script from `/scripts` by path
  (`spec_from_file_location`), which was not shipped — so collection aborted in
  the tarball. Same class as the `pytest_coverage_isolation.py` omission fixed
  above it.
- **Two `pytest` runs in one checkout reported each other's coverage, then
  `0.00%`.** `pytest-cov` collects into a per-process file and then COMBINES
  every sibling file next to the configured data file. With the data file at the
  repo root, a second run in the same checkout is a sibling: each run swept up —
  and deleted — the other's partials, so the loser reported the winner's totals
  and then `FAIL Required test coverage of 95% not reached. Total coverage:
  0.00%` and exited 1, with 4120 tests passing above it. Every concurrent
  verification of this repository was unreliable, and the failure reads exactly
  like a real coverage regression. Each process now gets its own data-file
  directory, so the combine sweep can only find its own partials. `coverage.xml`
  and `htmlcov/` stay where they were, because CI uploads them from there.
- **The flat paginated list field ranked by a type its schema does not serve.**
  Every other ordering-allowlist stamper reads the node type the schema being
  built holds; `DjangoFilterPaginateListField` stamped
  `_type._meta.graphql_output_type` — the CLASS-DEF canonical instance — once,
  while the root class body was still executing. That instance is measurably not
  the object the schema serves (twelve of the fields this project's own suite
  builds resolve to a different one), and it agreed only because a fork
  recompiles the same class from the same `Meta`. The allowlist is now derived
  from the served node type on every mount path, so a schema publishing less can
  no longer be ranked by a column its SDL denies.
- **A projection MIRRORING the reused type's own was refused.** Declaring a node
  type beside its `DjangoListObjectType` — the ordinary documented
  arrangement — and restating the same `only_fields` / `exclude_fields` on both
  failed the build, because the guard fired on the mere PRESENCE of the option
  rather than on it making a difference. Honouring a mirror and dropping it
  publish the same columns, so the schema cannot tell them apart and neither
  can a reader: the refusal cost a defensive restatement an outage, and it broke
  the "every common option in one place" sample in
  [Types](usage/types.md#configuration-options). The guard now compares the
  SELECTED columns, through the same predicate `converter.construct_fields`
  selects with, so an equivalent projection spelled differently stands too. The
  same allowance applies to the identical guard on `DjangoModelType`. A
  projection that would genuinely change what is exposed is refused exactly as
  before.
- **A build-time refusal reached the caller as a `TypeError`.** Every guard in
  the filter builder raises `ImproperlyConfigured` from inside a graphql-core
  fields thunk, and graphql-core rewraps ANYTHING a thunk raises as a bare
  `TypeError` whose message chains generated type names. The schema build
  already dug the real error back out; the two EAGER force sites
  (`compile_all_outputs`, which the app-ready hook and every schema module call,
  and the forked `compile_outputs_into`) did not — so which site happened to
  force the thunk first decided the exception type the operator saw, and the
  documented contract was wrong for the most common path. All three now force
  fields through one helper that surfaces the buried configuration error.
- **A filter refusal named a `Meta` that does not exist.** The message opened
  with `<Model>.filter_fields`, and a model has no `Meta.filter_fields`: the
  declaration lives on a TYPE, and the input is shared per model, so the type
  that contributed the path is not always the type serving the rows. Each path
  now carries the name of the class whose `Meta` declared it — the node's, not
  the container's, when a `DjangoListObjectType` inherited the declaration — and
  the refusal names it, so "drop the entry" points at a file the reader can
  open. An entry whose deep hop names nothing is attributed the same way: the
  entry to the declaration it was written in, the missing segment to the model
  that fails to hold it.
- **…and then named a class that exists in no user file.** An auto-expanded
  to-many gets a container the reader never wrote: `get_or_create_list_object_type`
  mints one and SEEDS its `Meta` with the node type's own `filter_fields` so the
  nested list stays filterable. A seeded declaration looked self-declared, so
  the attribution above handed the blame to `GenericListType.Meta.filter_fields`
  — a factory class inside this library, which is the exact defect the fix above
  set out to close, reintroduced one code path over. The container is now
  credited with a declaration only when it is not the very object its node type
  holds, so an inherited entry names the node's `Meta` whether the container was
  written by hand or minted by the compiler.
- **A relation refused for the wrong reason listed every cause but the likely
  one.** The traversal refusal offered three explanations — the projection
  removed it, a declared attribute publishes the name over a leaf, or the
  compiler dropped it for an unregistered target — and none of them fits the
  reader who declared the to-one scoping hatch. They read "publish `author`"
  while looking at `author` in their own `only_fields`. The message now names
  the fourth cause: a declared attribute publishing the name over a resolver of
  its own.
- **`totalCount` was counted whether or not the client asked for it.** A list
  served by `DjangoModelType` issued its `COUNT(*)` eagerly, so a query
  selecting only `results` paid for two round trips where the
  `DjangoListObjectField` path paid for one — while
  [Pagination](usage/pagination.md) states the count is "only issued when the
  client actually **selects** `totalCount`". The count is now deferred to first
  access, matching the sibling path and the documented behaviour. A client that
  does select it sees the same number as before, including under a filter or a
  page limit, because the deferred call still closes over the unsliced queryset.
- **A nested child was fetched and authorized twice on every write.** The
  reverse-relation and many-to-many paths resolved the child by primary key,
  ran the ownership and scope checks, and then handed the raw payload to the
  writer, which resolved the same row again and repeated the same checks — two
  lookups plus two scope queries per host, per child, growing linearly with the
  payload. The already-resolved row is now passed through. Every check still
  runs, and runs against the same row: the authorization outcome is unchanged
  for every relation kind, for a permitted and a denied caller alike.
- **A multipart part spelled the way the SDL spells it was silently dropped.**
  The merge that folds an upload into a mutation payload built its allow-list
  from each input field's snake_case model attribute, so `profilePhoto` — the
  only spelling a client can discover from the schema — matched nothing: the
  part was dropped and the mutation still answered `ok: true` with no file
  written. Both spellings are now accepted, derived from the same compiled input
  field so neither can name a target the other does not. The projection guard is
  unchanged: a part naming a field the input does not publish is still ignored
  under either name.
- **A request naming one field under BOTH spellings let part order decide which
  file landed.** Accepting the alias and the attribute made a self-contradicting
  request possible — `profilePhoto` and `profile_photo` in one body, two files,
  one column — and the merge folded the accepted parts in whatever order
  `request.FILES` yielded them, so which file was written depended on how the
  client happened to serialize the body rather than on the body itself. The
  alias is now applied first and the model attribute second, so the attribute
  always wins and the outcome is a property of the request. A body naming a
  field under exactly one spelling, which is every ordinary body, is unaffected.
- **A malformed batch entry answered HTTP 500 where the docs promise 400.** A
  batch body was checked for being a non-empty list but never for what the list
  held, so an entry that was not a JSON object reached `get_graphql_params`,
  where `data.get("query")` raised an `AttributeError` that escaped the view's
  error handler: posting `[1, 2, 3]` returned a 500 while
  [Views](usage/views.md) documents a 400. Every entry is now checked alongside
  the outer list and a non-object one is rejected with the documented 400. A
  well-formed batch executes exactly as before.
- **A misconfigured write host was accepted in silence, three ways.**
  `DjangoModelMutation` never ran the unknown-`Meta`-option check its sibling
  `DjangoModelType` has run since 2.0, so `exclude_field` — a typo for
  `exclude_fields` — built a mutation whose input still carried the very column
  the declaration meant to hide, and a `Meta.queryset` was accepted while
  scoping nothing (this host scopes through `filter_queryset`).
  `permission_classes` was worse than a no-op: the plain assignment raised a raw
  Pydantic error telling you to annotate it `ClassVar`, and taking that advice
  bought a class that builds with a permission that never fires, because the
  class reads the name nowhere. And a `nested_fields` key naming no relation was
  skipped when the input surface was built and skipped again on the write path,
  yet the generated input type was still *named* after it — so `{'bookz': Book}`
  minted an `AuthorCreateNestedBookzType` carrying no nested field at all, on
  both hosts. All three now raise `ImproperlyConfigured` at class definition,
  the nested one listing the accessors that would have worked. A schema that
  builds today can therefore fail to build after upgrading — which is the point:
  each of these classes was running a configuration its author had written down
  and the library had thrown away.
- **An unknown `Meta` option that is real on a sibling class read as a typo.**
  `registry` is a supported option on `DjangoModelMutation`, but declared on a
  `DjangoModelType` it was reported with nothing but "Check for typos", sending
  you hunting for a misspelling in a word spelled correctly. The message now
  names the classes that do accept the option, read from their own signatures so
  the list cannot drift out of date.
- **…and then told you to look for the typo anyway.** The sentence naming the
  sibling class was *appended* to the typo hint rather than replacing it, so the
  user who spelled `registry` correctly still read "Check for typos" and went
  looking for a misspelling that was not there. The hint is now emitted only
  when at least one unknown name is a `Meta` option on no class at all. A real
  typo reads exactly as it did.
- **A write-only `DjangoModelType` seized the model's read container.** Every
  generated list container claims the model's canonical registry slot on a
  last-write-wins basis, and that slot is what a reverse to-many relation
  resolves through — so a host declaring
  `Meta.model_operations = ("create", "update", "delete")`, which says in as
  many words that it does not serve `list`, still displaced the
  `DjangoListObjectType` the project had declared for its reads. Attaching a
  permission to a model's write path (`permission_classes` lives on
  `DjangoModelType`, not on `DjangoModelMutation`) therefore silently rewrote
  that model's shape everywhere it appears nested, and a query selecting the
  declared container's `pageInfo` stopped validating. A host that does not serve
  `list` now hands the slot back to whoever holds it, and still fills an empty
  one so a project with a single write-only host keeps that host's own
  pagination. A host that *does* serve `list` is unchanged, and
  `_meta.output_list_type` is still populated on every host, so
  `list_object_type()` and `ListField()` are unaffected.
- **Both subscription transports stopped importing without configured Django
  settings.** Sharing the HTTP view's validation-rule tuple — and, for SSE, its
  CSRF guard — put a module-level `from ...views import ...` in each transport,
  and `views` reaches `core.permission_signature_cache`, which reads
  `DJANGO_GRAPHEX` *while it is being imported*. So
  `import django_graphex.subscriptions.transports.ws` raised
  `ImproperlyConfigured` on the import alone, breaking any ASGI entrypoint that
  reaches the consumer (directly or through a routing module) before it points
  the process at a settings module — a dependency neither transport had before.
  Both imports are deferred into the request/operation path, so the shared rule
  tuple and the shared CSRF guard are unchanged and the transports import
  settings-free again.
- **Two write-only hosts over one model resolve to the first one declared.** The
  container-slot fix above reverses the old outcome for this case: the first
  host fills the empty slot, so the second finds it taken and hands it back,
  where last-write-wins used to give the slot to the second. Neither declaration
  claims `list`, so nothing in either ranks them; first-wins is kept because it
  is the choice that does not move a model's read shape when a second write
  concern is added later, and it drops nothing — the losing container is still
  on its own `_meta`, and a write-only host's `ListField()` raises, so it can
  never reach a schema. Only a project declaring **two** write-only hosts for
  one model is affected; one host, or any host that serves `list`, is unchanged.
- **The test suite was order-dependent: some shuffles died with `Schema must
  contain uniquely named types`.** No library behaviour changed — the defect was
  test hygiene. The output registry is keyed by **model**, so when two unrelated
  test modules declared a class under the *same* GraphQL type name for the same
  model on the **global** registry, one module kept its own compiled node while
  the registry handed the other's out through the relation graph, and any schema
  reaching both died. Nine such names were reachable from a real schema
  (`_PostListType`, `_PostType`, `_PostT`, `_TagT`, `_AuthorT`, `_AuthorType`,
  `_AuthorList`, `HookType`, `ScopedDocType`); each is now module-unique. The
  four node types the six subscription-transport modules each re-declared, and
  the subscription schema each of them rebuilt on every call, now live once in
  `tests/subscriptions/_transport_schema.py`. The root cause behind two of the
  names was `tests/test_optimizer_phase_c.py` passing `{}` as `Meta.registry`:
  an empty dict is falsy, so `Meta.registry` fell back to the global registry
  and every type built there published itself process-wide. Two further modules
  now keep the throwaway types they declare only to read `_meta` off the global
  registry entirely, and the two `ScalarKindsModel` round-trip tests mount only
  the scalar field they assert instead of the whole compiled type, so neither
  drags the shared relation graph into a schema. Verified with the full suite
  under 150 distinct `--randomly-seed` values, including the seeds that used to
  fail.
- **The SSE subscription endpoint answered HTTP 500 for a JSON body that was
  not an object.** `[1,2,3]`, `"x"` and `null` all decode cleanly and only then
  broke the transport's mapping assumption (`body.get(...)` →
  `AttributeError`), so SSE was the one surface in the library returning a
  server error for a body `GraphQLView` already classifies as a client error.
  It now answers `400 Bad Request` with the HTTP view's own message, *The
  received data is not a valid JSON query.* The same decode guard now also
  catches `RecursionError`, so a deeply nested JSON body — which is not a
  `ValueError` and used to escape as a 500 — is a plain 400 too. A well-formed
  request on the endpoint is unaffected.
- **A WebSocket `subscribe` with a non-object `payload` was silently dropped.**
  The payload went straight into the operation task, where `payload.get(...)`
  raised, was logged, and then vanished: no `error` frame, no `complete`, no
  response of any kind, leaving the client unable to tell the protocol
  violation from a slow server. The consumer now answers with its own
  `{"type": "error", "id": …}` frame — the same shape every other malformed
  `subscribe` gets — and the socket plus every operation already running on it
  keep going.
- **A limit set to `0` did the opposite of what it says.** `MAX_QUERY_DEPTH: 0`
  and `MAX_QUERY_COST: 0` were read as falsy by their validation rules, which
  returned early — so a limit that reads as "allow nothing" allowed
  *everything*, with no warning, while `None` was documented as the way to
  disable them. A negative value was worse: it enforced a budget no query could
  meet and named that negative in the error. `PERMISSION_SCHEMA_CACHE_MAXSIZE:
  0` had the same shape in reverse, quietly restoring the default `64` instead
  of caching nothing. All three are now validated where every reader routes
  through — the settings reader itself — and a value below the key's minimum
  raises `ImproperlyConfigured` naming the key, the minimum and the remedy.
  **`None` remains the only off switch for the two query limits**, and `0` is
  now honored for the cache bound as "cache nothing". Projects on the defaults
  are unaffected; a project that had written `0` was already running without
  the guard it thought it had. See
  [Settings › Query depth & cost](usage/settings.md#query-depth-cost).
- **`PERMISSION_SCHEMA_CACHE_MAXSIZE` was frozen at import.** The bound was
  captured in the cache's constructor and the cache is a module singleton, so
  the setting was fixed for the life of the process and `override_settings`
  could never reach it. It is now read on every eviction pass instead; nothing
  else about the cache's identity depends on it, since the bound only decides
  when to evict, never what a key means.
- **`MAX_REQUEST_BODY_SIZE` turned every multipart POST after the first into a
  500.** `dispatch` carries `@ensure_csrf_cookie`, whose token check reads
  `request.POST` whenever the client holds a `csrftoken` cookie — and for
  multipart that drains the upload stream. The body guard then called
  `len(request.body)` on the drained request and raised
  `RawPostDataException`. Since the endpoint plants that cookie on every
  response, only a fresh client's *first* multipart POST ever worked. The same
  read also dragged multipart under Django's `DATA_UPLOAD_MAX_MEMORY_SIZE`
  (2.5 MB by default), which a streamed upload otherwise escapes, so a 3 MB file
  that uploaded fine with the guard off became an opaque Django 400 with the
  20 MB cap the docs recommend — and the documented workaround, raising
  `DATA_UPLOAD_MAX_MEMORY_SIZE`, doubled peak memory by pulling the whole body
  into RAM. The guard now measures multipart **without reading it** — every
  other content type is still measured by reading. This fix first fell back to
  the declared `Content-Length` alone, on the belief that Django caps the
  request stream at `CONTENT_LENGTH`; that is true only under WSGI, so the
  fallback bounded nothing under ASGI. See *A multipart POST under ASGI was
  bounded by nothing but the client's own claim* above for the measurement that
  replaced it, and
  [Settings › How the guard reads each content type](usage/settings.md#how-the-guard-reads-each-content-type).
- **`DOCUMENT_CACHE_MAXSIZE = None` took the whole endpoint down.** `None` is
  the documented "no limit" value for every sibling bound in the namespace, but
  here it reached `int(None)` and every single request came back HTTP 400
  carrying the leaked `TypeError` text. It now means unbounded, as it reads.
- **Three malformed bodies answered 500 instead of 400.** A deeply nested JSON
  body (20 KB is enough) raised `RecursionError` out of `json.loads`, which is
  not a `ValueError` and so missed the decoder's handler; an
  `application/graphql` body that is not valid UTF-8 raised `UnicodeDecodeError`
  from a `decode()` the neighbouring JSON branch already guarded; and with
  `CACHE_ACTIVE` a `query` that is not a string, or one holding a literal nested
  past the parser's recursion limit, escaped the `except GraphQLSyntaxError` in
  the cache's pre-parse. All three are ordinary bad client input and are now
  reported as such. The pre-parse now matches the sibling call site in
  `execute_graphql_request`, which already treated any parse failure the same
  way.
- **The documented `source=` shortcut silently cost a column its ordering.** The
  ordering guard treats a declared attribute carrying a resolver as publishing
  the field's *name* without its *value*, and `source="x"` is compiled into a
  resolver — so `email = CharField(source="email")`, the no-logic shortcut
  [Types](usage/types.md#custom-fields-with-resolvers) documents, made `email`
  unsortable on a type that hides nothing, and `id = IDField(source="id")` took
  the primary key with it, which is the tiebreak every cursor page needs. A
  source naming the field's **own** attribute is now recognized as the
  passthrough it is. A source naming any other attribute, and a
  `resolve_<name>`, are unchanged: both still withdraw the column, because no
  build-time analysis can read a resolver body.
- **A filter refusal named the type it asked, not the type you have to change.**
  A deep path (`author__posts__title`) told the reader to publish the missing
  hop on the *root* type, which never held it, and a relation the compiler
  dropped told them to publish a name whose absence has a cause the message did
  not list — no `Meta` edit brings back a to-one relation whose target model has
  no registered type. Each refusal now names the type owning the failing hop,
  and a dropped relation names the target model that needs a
  `DjangoObjectType`. The documentation's standing advice to disregard the
  message is gone with it.
- **`FilterBackend.build_input_type` could not name the serving type**, so the
  public seam fell back to `registry.get_type_for_model` — the model-keyed,
  last-wins index a type opts out of with `Meta.skip_registry`, and the very
  lookup this release removed from the compiler path — which made the projection
  guard a no-op through it. The seam now takes `node_type` and forwards it. The
  registry fallback is kept for callers that name none.
- Three write-only assignments on `DjangoObjectType._meta` (`only_fields`,
  `include_fields`, `exclude_fields`) were removed. Nothing read them: the
  output compiler takes the projection from the registration entry, and neither
  projection guard reads a declaration at all. The comment beside them named a
  reader that does not exist.
- **Every authenticated SSE subscription died with `SynchronousOnlyOperation`.**
  `AuthenticationMiddleware` leaves `request.user` an unresolved
  `SimpleLazyObject`, and the SSE view is `async`: the first reader of
  `info.context.user` — any `authorize_subscription` gate, or a
  `schema_provider` pruning by permission — therefore fired the session and user
  query inside the event loop. A gate saw
  `You cannot call this from an async context` in place of its answer and denied
  the subscription; a provider raised it straight out of the view, past the
  in-stream framing, as a 500. Anonymous callers never noticed, because an empty
  session resolves to `AnonymousUser` without touching the database — which is
  why every SSE test (all of which injected an already-resolved user object) and
  the anonymous playground samples stayed green. The view now resolves the user
  once, in a thread, before anything else reads it; because a `SimpleLazyObject`
  resolves in place, every later reader — hooks, middleware, resolvers reaching
  back through `context.request` — sees a plain loaded user. The WebSocket
  transport was never affected: Channels' `AuthMiddleware` awaits the lookup
  before the consumer runs. Both transports are now pinned to the same contract
  by one test matrix driven through the real middleware chains — authenticated,
  anonymous, a session whose user row was deleted, no session at all, and an
  auth gate that denies as well as one that grants.
- **An `async def` subscribe gate failed OPEN.** The engine awaits an awaitable
  hook result, and `subscription_scope`'s wrapper forwards one — but
  `authorize_subscription`'s wrapper discarded its return, so a gate declared
  `async def` produced a coroutine nobody awaited and the subscribe was
  **granted**. Python reports it as nothing louder than a
  `RuntimeWarning: coroutine … was never awaited`. `async def` is the only shape
  that can reach the ORM from these hooks, because both transports run them on
  the event loop, so this is the shape a permission check wants. The wrapper now
  forwards the return, like its sibling. A synchronous gate behaves exactly as
  before. See
  [Subscriptions › ORM access in the subscribe hooks](usage/subscriptions.md#orm-access-in-the-subscribe-hooks),
  whose previous text claimed both hooks were lifted into a thread pool and
  could query the ORM freely — they never were, and that claim is what made the
  async-context failure above look impossible.
- **The bundled subscription client's pre-filled document was a syntax error.**
  Its editor shipped a `subscription { }` whose entire selection set was
  commented out, so pressing the run button — step 2 of the playground's own
  walkthrough — answered `Syntax Error: Expected Name, found '}'`. The editor now
  ships a runnable document, and the introspection the client already performs
  for autocomplete renames its placeholder field to the first subscription the
  live schema advertises, so the button works on first press against any schema.
  An editor the reader has already typed into is never rewritten.

### Removed

- Six internal names that nothing in the package reached, each confirmed
  callerless before deletion. None was exported through `django_graphex.__all__`
  or documented anywhere. Four of them were nonetheless importable by name —
  `utils.py` and `converter.py` declare no `__all__`, so
  `from django_graphex.utils import get_obj`, `create_obj`,
  `converter.assert_valid_name` and `converter.convert_choice_name` resolved on
  2.2.0 and raise `ImportError` here. None had a caller inside the package, and
  `create_obj` returned an error *string* rather than raising, so a project
  depending on it was already handling a value it could not distinguish from
  success. The names:
  `paginations.utils._nonzero_int` (which also still carried the zero
  passthrough its sibling `_positive_int` documents fixing — `_nonzero_int(0,
  strict=True)` returned `0` instead of raising, and it accepted negatives);
  `Registry._interface_implementors` (never written and never read —
  `get_member_models` derives implementors from `_types` on demand, so the
  second store could only go stale); `utils.get_obj` and `utils.create_obj`
  (test-only, and `get_obj`'s whole `except` chain was unreachable because
  `get_Object_or_None` already swallows those exceptions); and
  `converter.assert_valid_name` / `converter.convert_choice_name`, superseded by
  `_is_valid_name` and `choice_enum_name`.
- The `NullBooleanField` key from the two internal-type-keyed field maps
  (`core.fields.FIELD_TYPES` and the filter-schema scalar map). Django reports
  `"BooleanField"` from `get_internal_type()` for a `NullBooleanField`, so the
  key was unreachable in both — and the package's third field map had already
  dropped it, leaving the three to drift apart. A `NullBooleanField` resolves to
  a boolean exactly as before, now through one key in all three.
- The **`CAMELCASE_ERRORS`** setting, which had **zero consumers**. It shipped
  with a documented default of `True` and a promise to camelCase the `field` /
  `path` keys of error objects; no code in the package ever read it, so setting
  it — to either value — changed nothing at all. It is removed rather than
  implemented, because a setting an operator flips while believing something
  changed is worse than no setting. A project that still passes it now gets the
  `django_graphex.W001` unknown-key warning from `manage.py check` naming it,
  and error payloads are byte-identical to 2.2.0.

### Documentation

- **There is an upgrade guide for 2.x → 3.0.** The 1.x → 2.0 jump had a
  605-line guide in the nav; the largest set of breaking changes since 2.0 had
  only this changelog, organised by category — which answers "what changed" and
  not the question an upgrader actually brings, *"what will break, and when will
  I find out?"*. [Upgrade Guide (2.x → 3.0)](UPGRADE-3.0.md) is organised by
  **when the failure reaches you**: the build stops, nothing fails until a
  request arrives, your clients start getting refused, your own code changes
  behaviour, your SDL changes. It opens with five `rg` commands that triage a
  project in about a minute, because three of these changes do not fail the
  build and one of them is a gate the reader wrote that was never running.
  Every message in it was produced by executing the code on 3.0.0 and compared
  against the same code on 2.2.0 — which is how the two corrections above were
  found. It also names the three diff hunks that **look** like breaking changes
  and are not, so nobody edits working code because of them.
- **Nothing told you to validate the WebSocket handshake's `Origin`, and the
  example project did not.** A handshake is an ordinary HTTP request: the
  browser sends cookies with it and **CORS does not apply**, so any other site
  could open a socket to a session-authenticated endpoint *as your logged-in
  visitor* and read every subscription that user is entitled to. It routes
  straight around `REQUIRE_CSRF_HEADER`, which this release turns on for exactly
  this threat on the HTTP side and never sees this endpoint. The library cannot
  fix it — it never sees the handshake, your ASGI routing does — so
  [Subscriptions › Validate the WebSocket handshake's Origin](usage/subscriptions.md#websocket-origin)
  now says so under a `danger` admonition with the wiring, and the playground
  ships `AllowedHostsOriginValidator` around its router, pinned by a test that
  rebuilds the app under a real host list (the playground's own
  `ALLOWED_HOSTS = ["*"]` makes the validator accept everything, so a test that
  did not rebuild it would pass without the wrapper).
- **The multipart upload rule was documented as it behaved before this
  release.** `docs/api/mutations.md` still said *every* entry in
  `request.FILES` is merged under its own form-field name. It is now merged
  only when the name matches a file field the mutation's input **publishes**,
  under either spelling, and a part matching nothing is ignored rather than
  saved — the projection is the same boundary on the multipart path as on the
  JSON one.
- **The example project's public subscription published a column its query
  surface hides.** `CommentSubscription` names `Meta.model` and declared no
  projection, so `internalNote` — described in the model as a moderation
  scratchpad — was selectable **and** equality-filterable by an anonymous
  subscriber on both transports, while `CommentType` refused it everywhere
  else. The subscription now restates the exclusion, and the model comment,
  which claimed the column was "written in the Django admin, never on the
  wire", says what is actually true: the playground registers no admin at all,
  and the subscription surface is the fourth place the column has to be hidden
  because it is the only one that inherits nothing. The library-level gap it
  compensates for is unchanged and stays pinned by its own isolated test — see
  [Types › The one exception, and the three open boundaries](usage/types.md#projection-exception).
- **An upgrade instruction that was the exact inverse of reality.** The
  3.0.0 preamble listed "importing either subscription transport
  before Django settings are configured" as something that "now raises
  `ImproperlyConfigured` on the import alone" — under a heading about schemas
  that stop building. That is what this release **fixed**, as its own `Fixed`
  entry says; no published version ever raised it. An upgrader following the
  preamble would have rearranged their ASGI entrypoint for a failure that does
  not exist. The bullet is gone.
- **Three claims in the example project that a reader could disprove.** The
  password-hash lesson said the hash reaches **anonymous** callers without
  `UserType.exclude_fields`; `Author.resolve_user` already stops those, so the
  true statement — every **authenticated** caller, which is still an incident —
  is what it says now, with the second wall named rather than conflated. The
  validation section demonstrated a "failing validation" with `title: ""`,
  which returns `ok: true` and creates the row, because validation is Pydantic
  and `blank` is a form-level concern Django never enforces on `save()`; the
  sample is now a `max_length` refusal with its literal message, and both
  halves are pinned by a test. A pruned-schema refusal was quoted without the
  tail this release added to it.
- **A projection rule the code does not implement, and a table that outgrew its
  own sentence.** [Types › What "hidden" means](usage/types.md#what-hidden-means)
  promised that a relation published over a type bound to **another** model
  measures as unpublished on both axes, on the grounds that no target answers
  for the key. It never did, and it must not: such a declaration carries no
  resolver, so the default attribute resolver hands out the real target row and
  `author { id }` returns the author's own primary key — refusing to rank by a
  value the same request returns is precisely the SDL-versus-guard drift the
  predicate exists to end. The promise is withdrawn rather than implemented, and
  the shape it described is named for what it is: a schema bug, not a projection
  boundary. The sentence introducing that table also announced four causes over
  six rows; the table is now five rows and the count matches.
- **The example project demonstrated none of the 2.2.0 permission story, and its
  nested mutation was the exact shape those release notes call vulnerable.**
  `examples/playground` imported five permission classes to assign one, and
  neither `commentCreate` nor the nested `postWithCommentsCreate` carried any —
  so an anonymous caller created a `Post` *and* its `Comment` rows through the
  parent, in a project whose README claimed it showed "every major feature".
  Comment writes are now served by a `CommentModelType` carrying the
  `IsOwnerOrReadOnly` the module already defined, which is the same gate the
  nested write runs: the caller denied the child's own mutation is denied it
  through the parent, and the parent rolls back with the denial.
  `PERMISSION_SCOPED_SCHEMA` is switched on so `/graphql/secure/` serves each
  caller a schema pruned to their model permissions — including the nested
  `comments` input, which is stamped with the *child's* permission — and the
  README's coverage matrix now separates what the playground demonstrates from
  what it merely imports. See
  [Permission-scoped schema](usage/permission-scoped-schema.md).
- **Four pages described a codebase that had moved.** The playground schema tour
  still named a `CommentMutation` that no longer exists and still called
  `IsOwnerOrReadOnly` a pattern no type assigns; the example project's settings
  claimed subscription connections validate against a pruned schema, when both
  transports there are wired with `schema=` and pruning happens only through
  `schema_provider=`; the mutation examples still said a multipart part must be
  named after the model's snake_case attribute while the guide it links to now
  says either spelling works; and the `DjangoModelMutation` `Meta` reference
  claimed its table was the whole list while the graphene base still accepts
  `name`, `_meta`, `interfaces`, `possible_types`, `default_resolver` and
  `container`. All four now say what the code does.
- **The multipart upload pages never named the part that carries the document.**
  Both the guide and the API reference described "the part carrying the JSON
  body under whatever key your view reads", which sent readers looking for the
  `operations` / `map` envelope of the graphql-multipart-request spec — an
  envelope this library does not implement. A multipart body is read straight
  out of `request.POST`, so the parts are **`query`** and (optionally)
  **`variables`**; anything else answers `Must provide query string.` with HTTP
  400. Both pages now name them, show a working `requests.post` call, and carry
  the `X-Requested-With` requirement (the API reference had neither). See
  [Mutations › Automatic multipart uploads](usage/mutations.md#automatic-multipart-uploads).
- **Three more pages contradicted the code, and one contradicted another page.**
  The directives guide still called the spec bundle three directives in three
  places — it is five of thirty (`@skip`, `@include`, `@deprecated`,
  `@specifiedBy`, `@oneOf`), which the API reference already said; the
  pagination API reference still promised backward cursor pagination "for a
  future release" while the guide it links to says the work is **not
  scheduled**, and `CursorGraphqlPagination.__init__` takes no `last` /
  `before`; the `DjangoObjectType` `Meta` table was billed as the full set yet
  omitted `unions` and `name`, so its "every other key is rejected at startup"
  was false; and the nested-list example named a `Group.users` accessor Django
  does not create (`user_set`, compiled as `userSet`) while promising a
  `DjangoListObjectType` the example never declared. All four now say what the
  code does.
- **Two links 404'd and three snippets could not have run.** A relative link in
  the blog-schema tutorial resolved to a `permissions.md` that does not exist
  beside it, and the frontend guide reached four directories above the site root
  for `examples/playground/`. Building both tutorial schemas and validating the
  guides' queries against them also caught three snippets that fail before the
  server sees them: a nested M2M selected as `tags { name }` when a nested list
  is a container (`tags { results { name } }`), a `status` variable typed
  `String` where a field with `choices` compiles to `<app_label><Model><field>Enum`,
  and enum values sent as the model's stored `'draft'` / `'published'` instead
  of the schema's `DRAFT` / `PUBLISHED`.
- **`DjangoObjectType.get_queryset` did not scope a to-ONE relation, and nothing
  said so.** The to-MANY boundary was documented — an auto-expanded nested list
  reads the parent's prefetch cache and skips the hook — but the forward
  `ForeignKey` / `OneToOneField` arm has the same boundary and was documented
  nowhere, while `apply_object_type_get_queryset` called itself "the single
  choke point … every path". So `{ allAuthors { results { name } } }` hides a
  scoped-out row and `{ allPosts { results { author { name } } } }` serves it.
  The boundary note now names both directions, spells out that `get_queryset` is
  a **field-level** scope that must not be relied on to hide relation-reachable
  rows, and shows the escape hatch for each: an explicitly **declared** relation
  field — a `DjangoFilterListField` for the to-MANY arm, a `Field(TargetType)`
  plus its `resolve_` method for the to-ONE arm. A bare `resolve_<relation>`
  method with no declaration does **nothing** — an auto-expanded relation field
  is derived from the model, so nothing on the parent class is consulted — and
  the note now says so, because a mitigation snippet that silently no-ops is
  worse than the boundary it claims to close. Both snippets are executed by the
  suite. The docstring names its three real callers instead of claiming every
  path. The
  behaviour is unchanged: enforcing the to-ONE arm would trade the
  `select_related` join for one query per parent row on exactly the types that
  opted into scoping. See
  [Types › Custom queryset (per-request filtering)](usage/types.md#custom-queryset-per-request-filtering).
- **The example project shipped an upload demo its own settings rejected.** The
  playground advertises a 5 MB `Base64FileInput` upload and a 20 MB
  `MAX_REQUEST_BODY_SIZE`, but left Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` at
  its 2.5 MB default — and a base64 upload travels inside the JSON body, so a
  5 MB file was refused with an opaque HTML 400 long before either library cap
  saw it. The project now sets `DATA_UPLOAD_MAX_MEMORY_SIZE` to match, and the
  settings guide has a table saying which content types that ceiling applies to:
  base64 and every other in-memory body, never multipart, which streams to disk.
  The views guide gained the matching per-content-type note on the 413 guard.
- **Two pages disagreed about `0` in one release.** The settings reference says
  `MAX_QUERY_DEPTH` and `MAX_QUERY_COST` refuse `0` and negatives with
  `ImproperlyConfigured` — but [Query depth & cost limits](usage/query-limits.md),
  the page a reader actually lands on for those two settings, still presented
  them as ordinary values (`None (default) = never block`, with nothing said
  about the boundary). It now states that `None` is the only way to disable
  either guard, and disambiguates the neighbouring note about a per-type
  `Meta.max_depth = 0`, which **is** a real value there — that one forbids
  nested objects rather than disabling anything.
- **The published benchmark table was measured on 2.0.0, read from gitignored
  files, and rested on single runs.** [Why django-graphex](why.md) went out in
  2.2.0 with a table whose own conditions list said `django-graphex 2.0.0`, from
  result files nobody could open — a reader could neither tell which code had
  been timed nor check one figure. All eight artifacts are now **tracked**, were
  **re-measured on this branch's code**, and each is the **median of three
  runs**, recorded in the file under a new `aggregation` key. Three runs matter:
  repeating identical code minutes apart drifts up to **8 %** on the reference
  hardware, so the old single samples could not resolve any smaller difference —
  and an earlier re-measurement on this branch was discarded rather than
  published because latencies rose uniformly across **all four** libraries,
  three of which nobody here has touched. Against the 2.0.0-era figures the
  operations read: `nested` **15.97 → 12.26 ms**, `create_comment`
  **0.62 → 0.58 ms**, `filtered` **1.18 → 1.16 ms**, `flat_list`
  **0.81 → 0.79 ms**, `single` **0.38 ms**, unmoved. The scaling pair behind the
  `O(table)` claim holds: graphene's `filtered` reads **3.23 ms** at 1,000
  authors and **5.17 ms** at 2,000, against graphex's 1.19 and 1.16. **No SQL
  count moved on any operation of any library, and no `surface` moved** — the
  structural story is exactly what it was.
- **"Schema build" was never measuring schema build.** The figure was the wall
  time of `import bench_schema`, which pays the library's **entire dependency
  tree** and the **schema construction** in one number — and those differ by two
  orders of magnitude, so their sum answers neither question. Measured apart:
  strawberry costs **~106 ms to import and ~6 ms to build**, ariadne **~49 ms and
  ~2 ms**, graphene-django **~10 ms and ~4 ms**, graphex **~9 ms and ~3 ms**. So
  the old claim that "strawberry pays 10× and ariadne 5×" was describing how
  heavy those libraries are to *load*, not how fast they *compile a schema* —
  and on compilation the ordering is different again. The harness now reports
  `schema_import_ms` (the cold import, the comparable one) and
  `schema_rebuild_samples_ms` (five rebuilds with the dependency tree already
  loaded) separately.
- **The cold-import row was biased toward graphex; the harness now removes the
  bias rather than the page apologising for it.** `run_all.sh` runs
  `makemigrations`, `migrate` and `seed_bench` under the **graphex** virtualenv,
  so graphex was timed warm and the other three cold — on the one row where the
  libraries are closest. It now warms **every** virtualenv before the measured
  loop, and the spread on that row fell from **24–51 % to 3–15 %**. Even so, no
  winner is claimed between graphex and graphene-django: successive revisions of
  that page named opposite ones — graphene by 0.05 ms, then graphex by 1 ms —
  and **both were beneath the instrument's resolution.**
- **The rebuild series ships as raw samples, because it is a diagnostic and not
  a ranking.** Re-executing declarations perturbs each library's process state
  differently: **django-graphex's cost climbs across repeated in-process
  rebuilds** (`[2.99, 3.38, 3.70, 3.89, 4.34]` is typical) where ariadne's is
  flat, and `gc.collect()` between rebuilds makes graphex's *worse* rather than
  better, so something is retained. It has no effect on a deployment that builds
  its schema once. It is not a cache hit either — in all four libraries the
  rebuilt schema object, its `GraphQLSchema`, its Author type and that type's
  fields are all new objects. Part of that build cost is this release's own
  projection boundary, priced rather than implied: `benchmarks/guard_cost.py`
  counts and times the shared predicate at **46 calls / 0.69–0.71 ms** and **17
  calls / about 0.015 ms per `nested` request**, 0.13 % of that operation.
- **The example project demonstrated none of this release.** The 2.2.0 headline
  — automatic multipart uploads — had no write host to exercise it at all
  (`Document` was read-only, reachable only through a hand-written base64
  mutation), so the feature the release is named for could not be run.
  `Document.file` is now `Document.attached_file` (a two-word column, because a
  one-word one spells both accepted part names identically and therefore cannot
  show that either works) behind a `DocumentMutation` serving `documentCreate` /
  `documentUpdate`. `Comment` gained an `internal_note` moderation column that
  the schema hides on **both** sides, so one projection can be watched
  travelling through the output type, the filter input, the write input and the
  nested child input a `Meta.nested_fields` parent exposes. Both arms of the
  relation scoping hatch are mounted — `CategoryType.posts` and
  `AuthorType.user` — beside the auto-expanded `AuthorType.posts` that is *not*
  scoped, so the pair teaches the boundary instead of implying a defect.
  `UserType` now excludes `password`, which any anonymous caller could read
  through `Author.user`. The two settings that ship on are named and explained
  in `config/settings.py` as comments rather than pinned to their own defaults.
  And the README's own suggested `search: "django"` returned zero rows, because
  no seeded post contained the word: each body now names its tag, so it answers
  20. The suite grew from 23 tests to **49**, several asserting the verbatim
  answer strings the README quotes.
- **`docs/usage/settings.md` told you to budget for an envelope this library
  does not implement.** Two pages were corrected in this release to say the
  multipart contract is a `query` part plus an optional `variables` part — with
  no `operations` / `map` envelope — and the settings page was missed, still
  telling readers to size `MAX_REQUEST_BODY_SIZE` and
  `DATA_UPLOAD_MAX_MEMORY_SIZE` against "a multi-thousand-entry `map`". Posting
  that envelope answers `400 Must provide query string`; the page now names the
  two parts that do count.
- **A sample in the types API reference could not run for a reader who followed
  the page.** The [Types API reference](api/types.md) under `DjangoModelType`
  showed a read-only `UserCard(DjangoModelType)` carrying `only_fields` over
  `User` — and the first code block on that page registers a `UserType` over
  `User`, which makes exactly that declaration raise the `ImproperlyConfigured`
  documented in the warning ten lines below it. The sample now uses a model no
  other block on the page registers, and the warning quotes the refusal the old
  one produced.
- **The projection boundary had a third open edge nobody had written down.** A
  hand-written `Subscription` binding `Meta.model` compiles its event type and
  its `<Model>SubscriptionFilterInput` from the **model**, so it does not
  inherit the projection of whatever `DjangoObjectType` the schema registered
  for that model: a column hidden on the node type stays selectable **and**
  equality-filterable there. The remedy is one line — repeat the projection in
  the subscription's own `Meta` — and a subscription generated by
  `DjangoModelType.SubscriptionField()` needs none, because that host forwards
  its own projection into the class it builds. Stated once alongside the other
  two open boundaries in
  [Types › The one exception, and the three open boundaries](usage/types.md#projection-exception),
  and repeated where a reader meets the filter surface.
- **A build-time guarantee that reads stronger than it is.** The filter axis
  refuses a `filter_fields` entry naming a hidden column *while
  `<Model>FilterInput` compiles* — and that input compiles only because some
  field mounts a filtered list of the type. A declaration on a type nothing
  mounts that way is never measured and the schema builds in silence.
  [Filtering › The projection is the outer boundary](usage/filtering.md#projection-boundary)
  now says so: a clean build is a statement about the filter surface you serve,
  not a review of every `Meta` in the file.
- **Three pages still described pre-branch behaviour.** The sample application
  said two hosts over one model are allowed "only while neither declares a
  projection", which stopped being true when this release started accepting a
  projection that **mirrors** the registered type's own; the same page and the
  types guide now say so, and say why restating it is worth doing. The bundled
  subscription client's editor was described as something you type into, when
  it now ships a runnable document and renames its placeholder field from
  introspection — including what happens when introspection is off. And the
  playground page documented neither the multipart host, nor either arm of the
  relation hatch, nor the projection boundary, nor the two settings that ship
  on; it now walks all four with the answers they return.
- **The nav never reached the 2.0 upgrade guide.** `docs/UPGRADE-2.0.md` is
  built and linked from three pages, but no `nav:` entry listed it, so it was
  reachable only by following a link. It is now under **Getting Started**.

## 2.2.0 — 2026-08-24

**Security release. Upgrade if you use `Meta.nested_fields`.**

Two authorization defects let a caller write child rows they were not permitted
to write, both reproduced over the wire against a real schema before being
fixed. A nested write never consulted the child's own `permission_classes`, so a
parent a caller could write was a door into a child they could not; and
`Meta.nested_fields` derived the child's input from a shared registry slot
rather than from the child's declared type, so a column hidden with
`exclude_fields` — the shape the guides teach for `is_staff` and friends —
stayed writable through the parent, and through the child's own mutation too.
`PERMISSION_SCOPED_SCHEMA` made the first one worse rather than better: it
pruned the child's own mutation and left the nested write surface untouched, so
it granted confidence it had not earned. Details in **Fixed** below.

The rest is a correctness pass over the 2.1.0 audit backlog: confirmed defects,
each reproduced before the fix and covered by a regression test.

One behaviour change worth calling out before you upgrade: declaring
`only_fields` / `exclude_fields` / `include_fields` on a type whose output type
is reused from the registry now raises `ImproperlyConfigured` at class
definition instead of dropping the option silently. A schema that builds today
can therefore fail to build after upgrading — which is the point: every schema
that stops building was silently exposing a field it was told to hide.

One rename is wire-visible: the list container a `DjangoModelType` generates is
now `<Model>ListGenericType` instead of `<Model>ListType`, which was colliding
with the name the guides give your own `DjangoListObjectType`. Field names and
shapes are unchanged; only a client document that spells the container's type
name out needs updating.

A second rename is wire-visible for the same reason: the child input a nested
field exposes is now built per nesting parent and named
`<Child><Op>In<Parent>Type` (for example `CommentCreateInPostType`) instead of
borrowing the child's own `<Child><Op>GenericType`. Field names and shapes are
unchanged apart from the fix below; only a client document that spells the
nested child input type name out needs updating.

Nested writes now run the child's own permissions, which is a behaviour change
in two directions. A nested payload that used to be accepted can now be denied —
that is the fix. And the child's checks are called with a new `nested_parent`
keyword argument, which is passed only to a check whose signature can absorb it:
an `authorize` override or a permission class that spells its arguments out
(`def authorize(cls, info, action, data=None)`) keeps working and simply never
sees the marker, treating a nested write exactly like a direct one. That holds
for a `has_permission` override too — the narrowing happens at the call that
lands on your method, not at the outer call site, so the `**kwargs` on the
built-in `has_<action>_permission` in between does not leak the marker through.
Accept `**kwargs` to see it.

Nested pk lookups resolve through `get_queryset`, which folds in `Meta.queryset`
— but only for the child hosts that **serve the write**. Which hosts those are
follows from `Meta.model_operations`, which `DjangoModelType` now takes as well
(see below): a host restricted to `model_operations = ("create",)` has no
`update` to mirror, so its scope is not applied to a nested update, and a
`DjangoModelType` declaring `model_operations = ("list", "retrieve")` is a read
host that leaves the nested write path entirely. Left undeclared, a
`DjangoModelType` still serves everything, so its `Meta.queryset` — the queryset
its own `update` and `delete` already resolve through — now gates the nested
path as well: a row outside it answers *not found*. Check any `DjangoModelType`
whose `Meta.queryset` is a display default (hiding archived or unpublished rows)
before upgrading, and declare it a read host if a parent should still be able to
update those children inline.

One configuration that used to build now raises `ImproperlyConfigured`: a host
declaring `only_fields` / `exclude_fields` / `required_perms` for a model whose
nested input has **already** been built. graphql-core caches an input object's
field map, so such a host could never reach the nested surface, and being
ignored silently is how the leak used to happen. A late host that only repeats a
declaration already contributing is accepted, since the merge is idempotent and
refusing a no-op buys nothing. Otherwise: declare every host for a model before
the first schema build.

Where a child model has more than one host, the two projection axes merge
differently, and together they can leave nothing behind. `exclude_fields` is a
prohibition and is unioned across every declared host; `only_fields` is an
allowance and is unioned across the hosts serving the operation; the prohibition
is applied last. A child whose every allowed column is excluded by a sibling host
would therefore end up with a nested input carrying no field, which graphql-core
does not accept as a legal schema — so that configuration is now refused at build
time with an `ImproperlyConfigured` naming the child, the parent and every
contributing host with both of its axes, rather than returning a schema whose
every request fails validation. Give such a child at least one column no host
forbids, or declare the read host with `model_operations = ("list", "retrieve")`.

### Added

- **`Meta.model_operations` on `DjangoModelType`.** It already existed on
  `DjangoModelMutation`; the type class now takes the same option, widened to
  the five operations it generates — `("create", "update", "delete", "list",
  "retrieve")`, which is also the default, so a project that declares nothing
  behaves exactly as it did before. An operation left out has its `*Field()`
  builder raise `AttributeError`, and `QueryFields()` / `MutationFields()`
  return only what is enabled.

    This is the opt-out for the nested-write scoping this release introduces. A
    `DjangoModelType` is a **write host** for the models a parent nests, so its
    `Meta.queryset` and its `only_fields` gate a nested write — and in the
    common read-type-plus-write-mutation split, that queryset is a plain display
    default, not a policy. Declaring
    `model_operations = ("list", "retrieve")` says so: the card stops gating the
    nested write path and stops contributing a write allowance to it, while its
    read fields work exactly as before. Declaring nothing keeps the option
    itself inert — but note that is also what leaves the card a write host, and
    therefore what makes its `Meta.queryset` gate nested writes.

### Fixed

- **A multipart upload to a `FileField` / `ImageField` could never be saved.**
  The merge that folds `request.FILES` into the input payload has been there
  since the first release, but the derived validation schema typed a file column
  as a plain string, so the uploaded file it merged came straight back as
  `{ ok: false, errors: [{ field: "attachment", messages: ["Input should be a
  valid string"] }] }` — on create and on update, on both mutation hosts, with
  no way to opt out, since the derived annotation overrides whatever a
  `Meta.pydantic_model` base declares. A file column is now typed with a marker
  that accepts exactly the two shapes it can hold: an uploaded file object, and
  the storage path string a query reads back. Every other shape is still a
  structured validation error rather than a crash at save time, and the column's
  `max_length` still constrains the string branch. Nothing moves on the wire —
  the field is `String` on input and on output, as before.

    The merge now honours the input projection, which matters precisely because
    the value validates: while a file could never be saved, a part named after a
    column the type hides with `Meta.exclude_fields` was merged and then thrown
    out by validation, so nothing landed. Making the value valid would have
    turned that same merge into a live write reaching a column the wire surface
    deliberately does not expose. Only a part naming a field the input actually
    publishes is merged; anything else is ignored, and the part must carry the
    model's snake_case attribute name rather than its camelCase alias.

    The merge is flat, so it still reaches only the model the mutation is bound
    to. A file field on a child declared in `Meta.nested_fields` remains
    unreachable, and naming a multipart part after a nested relation still
    replaces the nested payload and fails in the nested handler. That gap is
    unchanged by this fix and is now documented where the feature is described;
    for nested uploads use the base64 input.

- **`Meta.nested_fields` dropped the child's declared input projection.** The
  nested child input was never derived from the child's own type — it was
  whatever object happened to occupy the shared `(child model, operation)`
  registry slot, so the outcome depended on which class was declared first. With
  the parent declared first the slot was empty, so an **unprojected** input was
  minted straight from the Django model: every writable column landed on the
  parent's nested payload, `exclude_fields` and all. Worse, that minted input was
  registered in the shared slot, so the child's **own** mutation, declared later,
  reused it and lost its projection too — the classic
  `exclude_fields = ("is_staff", "is_superuser")` became settable through both
  the parent's nested list *and* the child's own root field, and the child's
  required back-reference `post: ID!` was silently relaxed to `post: ID` on its
  standalone surface. With the child declared first the projection survived, but
  the parent reused the child's own input, whose required back-reference foreign
  key graphql-core rejects before any resolver runs — so that order produced a
  nested field that could not be used at all. The two orders were not
  symmetric: one leaked, the other was unusable, which means every project whose
  nested writes actually worked had landed on the leaking one. Each nesting
  parent now builds its own copy of the child input, inside the parent's field
  thunk, from the hosts **declared for the child in that registry**. The two
  projection axes are merged differently, because they say different things: an
  `only_fields` is a positive allowance, so the hosts that serve the operation
  being built **union** theirs — a create-only and an update-only mutation for
  one child no longer poison each other's nested surface, and neither do a read
  card and a write mutation projecting different columns — while an
  `exclude_fields` is a prohibition — *this column is never client-writable* —
  and is unioned across **every** declared host and applied last, so a create
  host's exclusion no longer vanishes from the nested update surface and let a
  client write, on an existing row through the parent, a column the project's
  own write mutation refuses. The shared registry slot is never written, and
  only that copy relaxes the back-reference key — per parent, so a child nested
  under two parents relaxes each parent's own key and nothing else. Both
  declaration orders now produce the same, working surface. The remaining way
  that merge could have failed open is closed with it: a host declared after the
  nested input was already built raises rather than being silently dropped — the
  memo is not what freezes the surface, graphql-core's own field-map cache is,
  so no rebuild or cache clear could have recovered it.
- **A nested write never ran the child's own permissions.** `create` and
  `update` authorized the parent once and then handed the whole payload —
  children included — to the nested writer, whose only call was into the child's
  validation backend, a seam with no permission concept. A caller allowed to
  write the parent could create and update rows of a child whose own type denied
  it: `postCreate` answered `PERMISSION_DENIED` and wrote nothing, while the
  identical write smuggled inside `authorCreate`'s nested list returned
  `ok: true` and persisted the row. Under `PERMISSION_SCOPED_SCHEMA` this was
  worse than a plain gap: the pruner correctly removed the child's own
  `postCreate` root and cloned the parent's input type verbatim, so the feature
  closed the front door, left the back door open, and granted false confidence
  while doing it. Every declared host for the child model is now authorized
  before a nested create or update — all of them, so two hosts for one model
  fail closed — and the nested input field is pruned by the child's write
  permissions, whose labels now reach the schema label-set even for a child that
  has no root field of its own. Those permissions cover what the field can
  actually do rather than what the parent's verb suggests: a nested payload's
  `id` is optional on an **update** input, so omitting it creates a row, and the
  field therefore requires the child's `add` **and** `change` there — otherwise
  a caller holding `change_child` alone kept, inside the parent's update
  payload, the exact create the child's own pruned-away root refused. The
  `required_perms` of every child host that **serves** one of those verbs is
  then **unioned** onto that default, never substituted for it, so an override
  can only ever *add* a requirement: a write host declaring something stricter
  genuinely reaches the nested field — otherwise a caller who has the child's
  own roots pruned away keeps the identical write inside the parent's payload —
  while a read label is not silently read as a licence to write. Being a union
  term is not free, though: a `DjangoModelType` serves every operation unless it
  says otherwise, so a read card carrying `required_perms` also gates the nested
  field,
  and a caller lacking that label loses it even where a differently-hosted
  `childCreate` still accepts the same write. Declare such a host with
  `model_operations = ("list", "retrieve")` so its label stays on the read side.
  And an input object every field of which is pruned is
  no longer emitted unfiltered — the mutation field that takes it is pruned
  instead, so a parent whose `Meta.only_fields` names nothing but the nested
  relation loses the root rather than regaining an ungated write. A denial is
  the same `PERMISSION_DENIED` / 403 the direct mutation returns and rolls the
  whole write back. Checks receive `nested_parent`, the parent model class, so a
  child that must be writable *only* inside its parent is now expressible (under
  a permission-scoped schema that pattern needs no label of its own — the caller
  doing the nested write holds the child's write permission, and simply not
  mounting the child's own root leaves the pruner nothing to prune). The link
  paths — attaching an
  existing forward-FK or M2M row by pk — stay ungated by design: they write
  nothing on the child and offer exactly the reachability the plain
  `category: ID` surface always had.
- **A nested upsert could reach a row the child's own host hides.** The nested
  writer resolved the target row against the bare model while the top-level
  `update` / `delete` both scope theirs through `get_queryset` /
  `filter_queryset`. Naming another tenant's primary key in a nested payload
  therefore rewrote that row in place, because Django's `save()` with a primary
  key issues an `UPDATE`. Nested pk lookups now resolve through the scope of the
  child hosts that serve the write, and answer a hidden row with the same *not
  found* the child's own mutation returns — never a create at that key, never an
  update of the row the scope was hiding. The scope decision is taken **before**
  the reverse-ownership guard, which resolves the pk unscoped: a hidden row that
  happened to belong to another parent used to be answered with *does not belong
  to this &lt;Parent&gt;*, confirming its existence, while an ownerless hidden row got
  the not-found. Both now answer identically.
- **A second registry's host rewrote the first registry's nested surface.** The
  per-parent input memo and the materialization record that refuses a late host
  both live on the registry, but the host list they read from did not: it was a
  process-wide table keyed by model alone. Every nested decision reads that list
  — the projection merge, the permission stamp, the write-time row scoping and
  the write-time `authorize` loop — so a host bound to a second registry through
  `Meta.registry`, the documented multi-schema hatch, silently narrowed the
  first registry's nested payload, added its own label to it, and applied its
  `filter_queryset` to writes in a schema it has nothing to do with. Merely
  importing the other schema's module could turn every nested update in the
  first into a *not found*. The list now lives on the registry beside the two
  memos, and dies with it — but it is read as the parent's registry **unioned
  with the global one**, because `Meta.registry` is an option on
  `DjangoModelMutation` alone: a `DjangoModelType`, the only host class carrying
  `permission_classes`, can only ever register globally, so reading the parent's
  registry by itself left a parent declared with `Meta.registry` finding no
  hosts at all and the nested permission gate silent — the same front-door /
  back-door shape, reopened for multi-schema projects. A host bound to a
  non-global registry still cannot reach any other registry's parents.
- **A projected `only_fields` on a nested child stripped the pk from the update
  input.** The nested update input is what makes the documented upsert-by-id
  work, and a child write host whose `only_fields` did not happen to list the
  primary key silently removed `id` from it — so the payload the guide's worked
  example shows was rejected over the wire, and a client that dropped the
  rejected `id` got a duplicate **create** instead of an update. The same
  omission reached the host's **own** update root, whose resolver also takes the
  pk from inside the input — so `only_fields = ("headline",)` shipped an update
  mutation no client could address at all. The pk is not a projectable column on
  an update surface — it is how the row is identified — and it now survives both
  projection axes, on the nested input and on the host's own. The **create**
  input still carries no pk at all, so creates stay create-only.
- **A host's `only_fields` was silently dropped when another host had already
  registered the model's input.** The `(model, operation)` input slot holds one
  type per model, so the first host to reach it decided the wire surface for
  every later one: a `DjangoModelMutation` declaring
  `only_fields = ("headline",)` behind an already-declared display card kept
  accepting every writable column on its own root — the exact leak `only_fields`
  is documented to close — and the reverse order narrowed the card's input to
  the mutation's projection. This lot made it worse by reading the declaration
  rather than the built type when merging a nested surface, so the nested
  payload could end up wider than every mutation root in the schema. A host that
  declares a projection now gets its own input type, named after that projection
  and memoized so two hosts declaring the same one share it. Hosts that declare
  no projection keep the shared slot and are unaffected; a projected input's
  GraphQL type name gains a short `_p<hash>` suffix.
- **A child host declared after its parent had only half of it honoured.** The
  nested field's permission stamp was frozen when the parent's input class was
  defined, while the projection it must match is resolved later, inside the
  parent's field thunk. A child write host declared after the parent but before
  the schema build — the ordinary *parent app imports the child app later*
  order — therefore had its `exclude_fields` applied and its `required_perms`
  dropped, and the guard that exists to make a too-late host loud never fired,
  because the record it keys off is only written at thunk time. A caller with
  the child's own roots pruned away kept the identical write inside the parent's
  payload. The stamp is now resolved in the same thunk, from the same host list,
  as the projection. In the same pass it became operation-aware: a host's
  `required_perms` is read only for the verbs that host serves, so a delete-only
  host's label no longer removes the nested *create* field.
- **The comment defending the ungated link paths argued something untrue.** It
  claimed a linkable row *belongs to nobody, so no scope hid it either*, which
  is false whenever the child has a host with a `filter_queryset` or
  `Meta.queryset` scope. The real reason is the one the guide gives: a link
  writes nothing on the child and offers exactly the reachability the plain
  `category: ID` relation input already has, unscoped, so gating only the nested
  spelling would make two surfaces for one operation disagree. Behaviour is
  unchanged; only the reasoning is now the true one.
- **`required_perms` could not be written on a `DjangoModelType`.** The guide
  documents the plain class attribute for the mutation fields a
  `DjangoModelType` generates, and the field builder reads it — but only
  `DjangoModelMutation` declared it as a `ClassVar`, and these classes are
  Pydantic-backed, so the documented form raised `PydanticUserError` at
  class-definition time. `DjangoModelType` now declares it too, exactly as it
  already declares `permission_classes` and for the same reason. Nothing changes
  for a class that spelled the annotation out by hand.
- **A permission-scoped schema could be served for the wrong schema.** The
  pruned-schema cache keys on `id(full)` and stores a weak reference to detect
  address reuse, but a reference that had gone *dead* — the exact state an
  `id` recycle leaves behind, since the original schema must be collected before
  its address can be reused — was treated as "still valid" and the collected
  schema's pruned variant was served to the new schema. Only a reference
  resolving to the requested schema (or an entry stored without one, for a
  schema that cannot be weakly referenced) is now trusted.
- **Every validator-free type ran pydantic's deprecated `validate` on each
  write.** The inline-validator collector walked the whole MRO, so it picked up
  `pydantic.BaseModel.validate` — inherited by every host — as if it were a
  user-declared object-level hook. `Meta.pydantic_model` stopped passing through,
  a synthetic validator model was built for hosts that declared nothing, and each
  save re-validated the payload against the host type itself (a
  `PydanticDeprecatedSince20` warning per write, and a hard rejection for any
  host with required fields). The walk now stops at `BaseModel`.
- **The optimizer returned wrong rows for aliased nested lists.** Selecting the
  same relation twice under different filters made *both* aliases return the
  unfiltered set, and adding a filtered or paginated alias next to a plain one
  silently corrupted the plain one. The dedup guard counted only selections that
  emitted a prefetch, so mismatched siblings were never detected. It now records
  a row-set signature for every nested-list selection, keeps one shared prefetch
  when the signatures agree, and drops the ambiguous lookup (and its
  descendants) from `prefetch_related` so each alias resolves its own rows.
- **A nested window under a windowed parent was paginated twice**, truncating
  the inner page and reporting the page size as `totalCount`. The re-rooted
  child prefetch now carries its `to_attr`, so the page is no longer sliced a
  second time in memory.
- **`optimize_<field>` crashed on a reverse FK declared without `related_name`.**
  The accessor (`<model>_set`) was looked up in a map keyed by the relation name,
  and the bare `except` substituted the owner model, producing a prefetch that
  failed at query time. Both walk sites now resolve through the accessor-indexed
  helper and leave an unresolvable segment untouched.
- **Filtering a list by a to-many primary-key set returned duplicate parent
  rows.** The `to_many` flag was only set on the nested-relation branch, so a
  direct pk lookup never triggered `.distinct()`.
- **Grouped `choices` with a repeated label produced a broken enum.** The
  duplicate-name guard was re-created on every recursive call, so two groups
  sharing a label collapsed into one member: the enum lost a value, rows holding
  the losing value became unserialisable, and writing that member stored the
  wrong value. Colliding names are now disambiguated deterministically; enums
  without a collision are unchanged.
- **Subscriptions were broken for any model whose primary key is not named
  `id`.** The broadcast payload hardcoded the key `"id"`, so every event failed
  the non-null check on the real pk field — in the default `id_only` mode.
- **Subscriptions delivered only errors to clients using GraphQL variables.**
  The per-event execution received neither `variable_values` nor
  `operation_name`, so subscribing succeeded and every delivered event failed.
  This affected every standard client (Apollo, urql, graphql-ws) and the bundled
  browser client.
- **Every read of a populated `DurationField` returned `null` plus a field
  error**, because `timedelta` cannot coerce to `Float`. The value is now
  resolved through `total_seconds()`, and the input side accepts it back.
- **The `id` returned by a query could not be sent back to an update
  mutation.** Output emitted `ID!` (a JSON string) while the update input
  declared the raw pk type, so echoing it back raised a coercion error — the
  sibling delete mutation already used `ID!`.
- **`ordering: "+field"` returned a 500 that enumerated every column of the
  model.** The allowlist stripped every leading `-`/`+` while the term handed to
  the ORM kept them. Prefixes are now normalised before validation, so the
  validated term is the one executed; a malformed `--field` is rejected with a
  clean error instead of leaking the field list.
- **With `CACHE_ACTIVE`, a malformed request body raised an unhandled exception
  instead of returning 400.** The pre-cache preamble parsed the body outside the
  handler that turns those errors into responses.
- **A multi-operation document with `operationName` silently discarded the
  mutation** and replayed a cached success payload without executing it. The
  operation name is now honoured when classifying the request, and an
  undeterminable operation bypasses the cache.
- **`ordering` did nothing on any list that used the default paginator.** With
  the then-shipped defaults (no `pagination=` on the list type, no `DEFAULT_PAGE_SIZE`
  or `MAX_PAGE_SIZE`) the paginator was unbounded, and it returned the queryset
  from its unbounded early-return *before* reading `ordering` — so the argument
  was advertised in the schema, autocompleted in GraphiQL, and silently ignored:
  `ordering: "name"` and `ordering: "-name"` both returned insertion order, and
  an invalid ordering field was not even rejected. Ordering is now resolved and
  applied independently of the page-size decision, so it works on bounded and
  unbounded lists alike, across `DjangoListObjectField`,
  `DjangoFilterPaginateListField` and nested lists. Explicitly configured
  paginators are unchanged.
- **An unset variable inside a `JSON` literal aborted the whole operation.**
  `createOdd(newOdd: {payload: {a: $v, b: 1}})` sent without `$v` embedded the
  `Undefined` sentinel in the parsed value and failed with `Object of type
  UndefinedType is not JSON serializable` — so leaving an optional variable
  unset broke the request instead of omitting the key. The literal parser now
  drops such a field, exactly as graphql-core does for input-object fields. See
  [Types › `JSONField` → `JSON`](usage/types.md#jsonfield-json).
- **A `JSONString` value could not be read back by its own scalar.** A resolver
  returning a plain string (`"hello"`) put it on the wire verbatim, which is not
  valid JSON, so sending the same value back raised `JSONString cannot parse`.
  Anything that is not already valid JSON text is now `json.dumps`-encoded;
  text that already parses as JSON is still passed through unchanged. See
  [Types › `JSONField` → `JSON`](usage/types.md#jsonfield-json).
- **An input model using a Pydantic 2.10+ validated-data `default_factory`
  could not build a schema at all.** `Field(default_factory=lambda data: ...)`
  was invoked with no argument at compile time, so the type died with `<Input>
  fields cannot be resolved`. Such a factory has no compile-time value: the
  field now renders without an SDL default and Pydantic applies it per
  instance. See [Types API › `DjangoInputObjectType`](api/types.md#djangoinputobjecttype).
- **A wrapped root field made a per-schema registry pair unbuildable.** A root
  declaring `field(NativeList(SomeType))` or `field(NativeNonNull(SomeType))`
  fell through to the scalar branch of the root compiler, and that branch was
  the only one that did not carry the schema's registry pair — so the inner type
  resolved against the process-global one and the build aborted with
  `assert_schema_pair_isolation`. A bare `field(SomeType)` was unaffected, which
  is why the wrapper looked like the culprit.
- **A type implementing an interface could not be used in a second schema.** The
  per-schema copy of the type kept the interface instance compiled for the
  default schema, while a root `field(SomeInterface)` compiled a fresh one, so
  two same-named interfaces reached one schema and it failed to build with
  `Schema must contain uniquely named types`. Interfaces are now recompiled
  against the schema that owns the type.
- **`name=` was honoured on the root only.** A field declared as
  `date_ = field(GdxDate, name="date")` rendered `date` on the root and `date_`
  everywhere else — mutation payloads and nested object types camelCased the
  attribute name instead, leaking the keyword-dodging underscore onto the wire.
  See [Fields › The unified `Field`](usage/fields.md#the-unified-field).
- **A nested list ignored the `@filter_field` filters it advertised.** The
  nested `filter:` argument mounts the same `<Model>FilterInput` as the root
  list, custom filters included, but every nested path applied only the
  standard lookups — so `posts(filter: {search: "…"})` returned the unfiltered
  set (and an unfiltered `totalCount`) while the identical root query filtered
  correctly. All the nested paths — the plain prefetch, the DB-side window, its
  count subquery, and the resolver's own branches — now run both filter stages
  through one choke point. See
  [Nested Lists](usage/nested-lists.md) and
  [Filtering › Composition order](usage/filtering.md#composition-order).
- **A nested list reported a different `totalCount` on its last page.** The
  count for an empty or past-the-end window page was rebuilt from the child's
  default manager, dropping the `optimize_<field>` hook that had scoped the
  page itself: a pagination UI reading the total off the overshoot page saw the
  *unscoped* row count. The count now reuses the queryset the page was computed
  from, and the per-parent fallback re-applies the hook. See
  [Nested Lists › Per-field optimize hook](usage/nested-lists.md#per-field-optimize-hook).
- **A declared `Meta.queryset` could freeze at the first request.** The queryset
  is built once at class definition and bound as the resolver base; it was
  handed to the resolver verbatim, so with `OPTIMIZE_QUERYSET = False` (nothing
  else clones it) the first request filled its result cache and every later
  request in that process replayed it — rows created afterwards stayed invisible
  until a restart. The base queryset is now cloned per request. See
  [Types](usage/types.md) and the
  [`DjangoListObjectType` options](api/types.md).
- **With `CACHE_ACTIVE` and `ATOMIC_MUTATIONS`, the cache-invalidation bump
  fired *before* the mutation ran.** It was scheduled through
  `transaction.on_commit` from the pre-dispatch preamble, but the atomic block
  `ATOMIC_MUTATIONS` opens lives inside the execution of the mutation — so at
  scheduling time there was no open transaction and Django ran the bump
  immediately, leaving the TOCTOU window it was written to close wide open: a
  concurrent reader could cache pre-mutation data under the post-mutation
  version. The bump is now scheduled after the mutation has run. See
  [Caching › Post-commit invalidation](usage/caching.md#post-commit-invalidation-toctou-safety).
- **With `CACHE_ACTIVE`, a cached GraphiQL page was served to API clients.** The
  response-cache key ignores content negotiation, so the HTML render and the
  JSON answer for the same query shared one slot: whichever arrived first
  decided what everyone else received — a browser could warm the page and the
  next `Accept: application/json` request got `text/html` back. A request that
  would render GraphiQL now bypasses the cache entirely. See
  [Caching › Requests that bypass the cache](usage/caching.md#requests-that-bypass-the-cache).
- **A batch endpoint answered HTTP 500 for any non-JSON body.** Only an
  `application/json` body was checked for being a list; `application/graphql`,
  form-encoded and multipart bodies were iterated as-is and died with
  `AttributeError: 'str' object has no attribute 'get'`. Every batch request now
  goes through one non-list guard and gets the documented HTTP 400. See
  [Views › Batch endpoints](usage/views.md#batch-endpoints).
- **A quality value written with a space (`Accept: text/html; q=0.1`) was
  ignored**, and the entry was ranked as `q=1` — so a JSON client that
  de-prioritised HTML the perfectly legal way was served the GraphiQL page.
  Whitespace after the semicolon is now tolerated. See
  [Views › GraphiQL](usage/views.md#graphiql).
- **A nested write skipped the child type's own validation.** The nested path
  built its child validator from the child MODEL alone, so the inline
  `validate_<field>` / `validate` methods and the `Meta.pydantic_model` declared
  on that child's own `DjangoModelType` / `DjangoModelMutation` never ran: the
  exact payload the child's own mutation rejected was accepted — and written —
  through a parent's `nested_fields`. A rule expressed once, in the documented
  place, was enforced on one of the two routes to the same table. The nested
  path now reuses the child host's backend, so both routes run the same
  validator. See [Mutations](usage/mutations.md#how-nested-writes-work).
- **A malformed primary key answered with Django's internals instead of the
  error envelope.** `update` and `delete` on both `DjangoModelType` and
  `DjangoModelMutation` passed the client's `id` straight to the ORM, so
  `id: "abc"` surfaced `Field 'id' expected a number but got 'abc'.` (and a
  malformed UUID surfaced a `ValidationError`) rather than the documented
  `ok: false` / `<Model> with id <pk> does not exist.`. A value no row can hold
  matches no row, so it is now reported exactly as an absent one, at the single
  lookup helper all four resolvers share.
- **A delete input could not be declared for a model whose primary key is not
  named `id`.** `input_for = "delete"` looked the pk up under the literal key
  `"id"`, so a model on a `UUIDField`, a `SlugField` or any renamed pk raised
  `KeyError: 'id'` at class-definition time — the module simply would not
  import, with no workaround. The delete branch now reads `model._meta.pk` and
  keys the field on the real primary-key name. See
  [Types API › `DjangoInputObjectType`](api/types.md#djangoinputobjecttype).
- **An inherited `class Arguments` lost every inherited argument.** The helper
  behind the mutation argument compiler read only the class body, so factoring
  shared arguments into a base class (`class Arguments(CommonArgs)`) dropped
  them from the compiled SDL with no error at all — a required `tenant: String!`
  scope key simply disappeared. The whole MRO is now read, base classes first,
  with the most-derived declaration winning a name clash. See
  [Mutations › Custom Arguments](usage/mutations.md#custom-arguments-with-field).
- **A `@filter_field` named after a `filter_fields` key silently ate that
  field's lookups.** The custom-filter loop ran last and overwrote the compiled
  `<Model><Field>Lookups` entry, so the field became unfilterable in *both*
  shapes and the only symptom was a raw `'str' object has no attribute 'items'`
  from the query-time `Q` builder. Such a collision — including one with an
  `and` / `or` / `not` combinator — now raises `ImproperlyConfigured` when the
  filter input is built, mirroring the existing reserved-name check. See
  [Filtering › Reserved argument names](usage/filtering.md#reserved-argument-names).
- **Declaring a relation *and* a path through it dropped the nested filter.**
  `{"author": ("exact",), "author__name": ("icontains",)}` put `author` in both
  the relation and the plain-pk bucket, and the two compile loops wrote the same
  wire key, so the `AuthorFilterInput` never mounted and the declared nested
  filter vanished from the schema. The plain-pk lookups now fold onto the nested
  input under the related model's primary-key name, keeping both halves. See
  [Filtering › Filtering across relations](usage/filtering.md#filtering-across-relations).
- **An explicit nested lookup was replaced wholesale by the related type's
  own.** The canonical-shape check tested only whether the requested *path*
  existed on the related model's root declaration, then returned that root and
  discarded the requested lookups — so `PostType.filter_fields =
  {"author__name": ("icontains",)}` compiled to the root's `("exact",)` and
  `{author: {name: {icontains: "…"}}}` was rejected by validation. The
  short-circuit now requires the root's lookups to actually cover the request;
  otherwise the two are unioned, as they already were for divergent paths. See
  [Filtering › Filtering across relations](usage/filtering.md#filtering-across-relations).
- **Every string directive rendered a null field as the literal text `"None"`.**
  `@uppercase` answered `"NONE"`, `@slugify` answered `"none"`, and so on for
  the whole family, because the shared coercion helper called `str(value)`
  unconditionally — while the numeric directives already returned `null`. All of
  them now pass `null` straight through. See
  [Directives API › String Directives](api/directives.md#string-directives).
- **`@default` replaced any falsy value, not just null and the empty string.** A
  legitimate `0`, `false` or `[]` was substituted with the `to` **string** and
  then failed serialization outright (`Expected Iterable, but did not find one`,
  `Int cannot represent non-integer value`). Only `null` and `""` are
  substituted now. See
  [Directives API › `DefaultGraphQLDirective`](api/directives.md#defaultgraphqldirective).
- **`@number` and `@currency` nulled the very fields they are documented for.**
  Both always returned a formatted string, so `viewCount @number(as: ",.0f")` on
  an `Int` field and `price @currency` on a `Float` field answered `null` plus
  an opaque `Int cannot represent non-integer value: '1,234'`. On a field that
  cannot serialize a string the raw value is now returned unchanged; the
  format-spec width/precision cap still applies on every field type. See
  [Directives](directives.md#number-directives).
- **A subscription filter the schema accepted could crash the live stream.** A
  to-many field declares lookups the ORM then refuses across the join
  (`filter: { tags: { iexact: 3 } }`), so the key passed the subscribe gate and
  raised `FieldError` at delivery — escaping the SSE generator *after* the `200`
  was committed, and killing the WebSocket operation task with no frame at all.
  Client filters are now validated against the ORM itself at subscribe time, and
  a delivery-time failure on either transport is framed as `next{errors}`
  followed by `complete` instead of tearing the connection down silently. See
  [Subscriptions › Filter key validation](usage/subscriptions.md#filter-key-validation).
- **One malformed WebSocket frame leaked every live subscription on the socket.**
  A body that is not valid JSON, or a non-string operation `id`, raised out of
  the consumer, so Channels never ran `disconnect()` and every running
  operation kept its task *and* its channel-layer group. Any frame the consumer
  cannot dispatch now closes with `4400` after the full teardown.
- **An SSE response that was never iterated leaked its groups permanently.**
  The groups are joined before the response is returned, but teardown lived only
  in the streaming generator's `finally` — so a client that aborts during the
  subscribe handshake left a ghost group member every future broadcast fanned
  out to. Teardown is now registered on the response, which Django closes
  whether or not the body was read.
- **Two subscriptions on the same model cross-delivered each other's events.**
  Group names carried the model and the action but not `Meta.stream`, while the
  signal bindings registered per stream — so both fanned out into the identical
  groups and a `full`-payload subscriber received a duplicate, all-null event
  from the `id_only` one on every change. `Meta.stream` is now part of the group
  name.
- **`subscription_scope` and `authorize_subscription` were dead on both
  transports.** The subscribe hooks receive the transport context as their
  `info`, and it had no `.context` attribute — so the documented
  `info.context.user` raised `AttributeError` and the subscribe failed closed,
  with no source started. The transport contexts now expose `.context` alongside
  `.user`, so both spellings resolve. See
  [Subscriptions › Authorization and row-scoping](usage/subscriptions.md#authorization-and-row-scoping).
- **A subscription on a model with a `FileField` or `BinaryField` crashed on
  every save.** The broadcast payload is JSON-encoded, and the serializer handed
  it a raw `FieldFile` / `bytes`. File fields now serialize as their storage
  name and binary fields as base64 — matching the `String` both already render
  as on the event type.
- **The bundled subscription client pointed its SSE field at the JSON
  endpoint.** There was no `sse_path`, so the SSE input was seeded from
  `http_path`; the first-run playground POSTed a subscription to `GraphQLView`,
  got a `200 application/json` body with no `event:` line, and showed a
  connected stream with zero data and zero errors. `SubscriptionClientView` now
  has an `sse_path` (default `/graphql/stream`), and a frame the client cannot
  recognise is logged as an error instead of discarded. See
  [Subscriptions › Browser client view](usage/subscriptions.md#browser-client-view).
- **An `AnnotatedField` reached through two chained forward foreign keys
  resolved to `null`.** The select→prefetch promotion pass never recursed, so it
  only ever saw the first hop from the root: `{ comments { post { author {
  postCount } } } }` left `post__author` in `select_related`, where the
  annotation cannot ride along, and the field came back empty with no error. The
  pass now descends the whole chain carrying the dotted lookup, so the hop that
  actually owns the annotated child is the one promoted. See
  [Query Optimization › Selection-driven annotations](usage/query-optimization.md#selection-driven-annotations-annotatedfield).
- **An `... on <Interface>` fragment inside a prefetched child cost one query
  per row.** The `.only()` walkers were given the list *container*'s identity
  and no source class at all, so the guard could neither match the interface
  (only the source class carries `Meta.interfaces`) nor recognise the row type —
  every interface fragment was dropped from the projection and its columns were
  reloaded row by row. Both walkers now carry the GraphQL type through the
  `results` wrapper down to the row type. Two further walk sites read the source
  class off a `graphene_type` attribute that a natively compiled type never
  has, which silently made the same guard inert there; both now resolve it
  properly.
- **A named fragment spread on a `GenericForeignKey` union member was ignored.**
  The per-content-type bucket collector only looked at inline fragments, so a
  selection mixing `... on AccountType { balance }` with `...Money` narrowed the
  member queryset to the inline fragment's columns and fetched the rest one
  query per row. Spreads are now resolved against the document's fragments and
  merged into the same bucket. See
  [Query Optimization › Typed GenericForeignKey unions](usage/query-optimization.md#typed-genericforeignkey-unions-per-content-type-narrowing).
- **A nested list on a child with two relations back to its parent always
  resolved empty.** Every relation pointing at the parent was collected into one
  filter mapping, and a mapping is a conjunction — so a child with `created_by`
  *and* `updated_by` foreign keys (or a foreign key beside a many-to-many) was
  scoped to the rows matching both, which is nothing. Which relation is meant
  cannot be inferred, so the ambiguity now raises `ImproperlyConfigured` naming
  the relations instead of silently returning `[]`; mount such a list through
  its relation accessor. See
  [Fields › DjangoFilterPaginateListField](usage/fields.md#djangofilterpaginatelistfield).
- **A manual `prefetch_related` in `get_queryset` collided with the optimizer's
  own.** The derived lookups were appended without checking what the base
  queryset already carried, and Django rejects two lookups on the same path — so
  the documented `return queryset.prefetch_related('posts')` failed the whole
  field with `'posts' lookup was already seen with a different queryset`. A
  manual lookup the optimizer is about to re-derive is now dropped first, which
  is the "replaced" behaviour the docs already promised; manual prefetches of
  other relations are untouched. See
  [Query Optimization › Custom resolvers](usage/query-optimization.md#custom-resolvers).

### Security

- **`update` and `delete` ignored the queryset scoping that protected reads.**
  Both resolved their target row from the bare model, while `retrieve` and
  `list` went through `get_queryset` → `filter_queryset` — so the documented
  multi-tenant pattern (`qs.filter(tenant=info.context.user.tenant)`) hid
  another tenant's row from a query and still let any caller overwrite or
  delete it by primary key, returning `ok: true`. That is the worst possible
  shape: a developer verifying the scope on the read path concludes it works.
  Both write methods now resolve the row through the same scoped queryset, and
  a row outside the scope answers exactly as a missing one (`ok: false` with
  `<Model> with id <pk> does not exist.`), so the response cannot be used to
  probe which primary keys exist. See
  [Filtering › `filter_queryset`](usage/filtering.md#filter_queryset-scope-the-base-queryset).
- **A permission returning `None`, `0` or `""` was treated as *allowed*.** The
  check compared the result with the `False` singleton (`is False`), so only a
  literal `False` denied: `return user and user.is_staff` — the single most
  idiomatic way to write it — returns `None` for an anonymous caller and
  granted every action, reads and writes alike. Any falsy value now denies.
  See [Permissions › Writing a custom permission](usage/permissions.md#writing-a-custom-permission).
- **`only_fields` / `exclude_fields` were silently dropped, keeping a sensitive
  column exposed.** When a `DjangoObjectType` was already registered for the
  model, the `DjangoModelType` reused that output type and discarded its own
  projection without a word (the existing warning only fired for custom
  fields), so `exclude_fields = ("secret",)` built a schema that still served
  `secret` — defeating the control this library documents as *the* way to keep
  a column out. Declaring `only_fields` / `include_fields` / `exclude_fields`
  in that situation now raises `ImproperlyConfigured` at class definition,
  naming the option, the model and the type that registered the output type.
  This **fails the build for a schema that builds today**, deliberately: a
  warning is filterable and would leave the leak live in production, and the
  only configurations affected are the ones already leaking. Move the
  projection to the registered `DjangoObjectType`, or drop the option. See
  [Types › Custom output fields](usage/types.md#custom-output-fields).
- **`DjangoObjectType.get_node` ignored `get_queryset`.** The sibling of the
  item above on the plain-type hierarchy: it resolved its row on the bare
  manager instead of the documented scoping choke point every other row-serving
  path uses, so a caller passing a primary key straight to it got back exactly
  the rows the scope exists to hide. It now runs through `get_queryset`, and an
  excluded row is reported as missing.
- **A nested reverse `OneToOneField` child could be stolen from its owner.** The
  ownership guard on the nested-write path only tested the reverse-FK kind, so
  updating your own parent row with `{id: <yours>, profile: {id: <theirs>, ...}}`
  silently re-pointed another tenant's one-to-one child at you and returned
  `ok: true` — while the same payload on a reverse FK was correctly rejected.
  The guard now covers both reverse kinds with the identical error, so the two
  paths are indistinguishable to a client. Forward FK/O2O and M2M children are
  unaffected: those rows are not owned by the parent, so no ownership check
  applies. See [Mutations](usage/mutations.md#how-nested-writes-work).
- **Setting `root_value` silently disabled every private field.**
  `AuthenticatedFieldsMiddleware` used "the root value is not `None`" as its
  proxy for "this is a nested field", but `root_value` is a public seam (a
  `GraphQLView` kwarg, a class attribute and an overridable `get_root_value()`).
  Any view configured with one served every protected field to anonymous
  callers, and the gate was skipped on each delivered subscription event too —
  the event payload *is* the root value there. The top level is now read from
  the resolve path, which is also correct for a field reached through an inline
  fragment and for one nested inside a list element; an unreadable path is
  treated as top level, so the gate fails closed. See
  [Security](usage/security.md#field-level-authentication).
- **A deactivated superuser could still introspect the schema.** The
  `INTROSPECTION_ALLOW_SUPERUSER` bypass tested `is_superuser` alone, unlike
  every sibling superuser check in the library, so an `is_active=False` account
  kept full `__schema` access on backends that do not run Django's
  `user_can_authenticate` (token / JWT). The bypass now requires an **active**
  superuser. See [Security](usage/security.md#disable-introspection).
- **Row-level scoping leaked through a parent relation.** A
  `DjangoFilterListField` mounted on a parent type read the rows straight off
  the relation accessor, a shortcut that skipped the node type's
  `get_queryset`. A type that hid rows correctly at the top level exposed all of
  them when reached through the parent — `{ authors { createdPosts { title } } }`
  returned the rows `{ posts { title } }` withheld. The hook is now applied on
  that path too, from a single shared choke point; it also rejects a hook that
  returns a non-`QuerySet` instead of quietly serving unscoped rows. Types that
  declare no scope keep the prefetch cache and the single query; a scoped type
  costs one query per parent on that field. Auto-expanded nested lists
  (`DjangoNestedListObjectField`) remain the documented boundary. See
  [Types](usage/types.md#custom-queryset-per-request-filtering).
- **A misspelled `DJANGO_GRAPHEX` key was dropped without a signal.** An unknown
  key never reaches the reader, so the setting it was meant to configure keeps
  its default: `"MAX_PAGE_SIZ": 10` left `MAX_PAGE_SIZE` at `None` (no page-size
  cap) and `"CACHE_ACTIV": True` left the cache off, with nothing reported by
  `manage.py check`. A Django system check (`django_graphex.W001`,
  `Tags.compatibility`, registered from the app config) now compares your keys
  against the known settings and names the closest match. It is a **warning**,
  never an exception, so an app that starts today keeps starting. See
  [Settings](usage/settings.md#typos-in-the-django_graphex-dict).
- **The playground's "private" note subscription had no gate on the type.**
  `examples/playground` documented `noteSubscription` as auth-gated, but the
  only thing denying an anonymous subscriber was the schema-root wiring:
  `"subscribe"` is a READ action, so `IsAuthenticatedOrReadOnly` allowed it, and
  `subscription_scope` returned `None` — no scope, i.e. **every** user's notes —
  for a caller with no user. Copied into a project that does not mount
  `AuthenticatedFieldsMiddleware`, the type leaked the whole stream.
  `NoteModelType` now denies the anonymous `subscribe` in `authorize` (before
  any Channels group is joined) and fails closed in `subscription_scope`. See
  [Subscriptions](usage/subscriptions.md#authorization-and-row-scoping).
- **A negative page size bought budget for a sibling field, bypassing
  `MAX_QUERY_COST`.** The cost estimator used a list's page size as its
  multiplier verbatim, so `limit: -1000` multiplied that subtree by a negative
  number and *subtracted* from the operation total: a query rejected on its own
  (`requestedCost 1001` against a budget of `50`) sailed through with one extra
  aliased field whose limit was negative, and the expensive sibling executed in
  full. Page sizes are now clamped to `0` before the `MAX_PAGE_SIZE` cap, so a
  field can only ever add cost. See
  [Query limits › Query cost analysis](usage/query-limits.md#query-cost-analysis).
- **A variable default declared in the document defeated `MAX_QUERY_COST`.**
  Variables are not bound during validation, so the enforcing rule fell back to
  the operation's own `$n: Int = 1` default — a value written by the same client
  that then sends `{"n": 1000}` at execution time. The query executed, and with
  `EXPOSE_QUERY_COST` the response even reported the real
  `requestedCost` over its `maxCost`. The rule no longer reads document
  defaults: a variabled page size is costed at `MAX_PAGE_SIZE` (else
  `DEFAULT_PAGE_SIZE` / `DEFAULT_LIST_MULTIPLIER`), the same conservative
  fallback an unknown variable already used. The reporting path, which does
  receive the request's real variables, is unchanged. See
  [Query limits › Query cost analysis](usage/query-limits.md#query-cost-analysis).
- **A customized `perms_map` was ignored for subscriptions.**
  `DjangoModelPermissions.has_subscribe_permission` resolved a forwarded
  subscribe action against the library's hardcoded permission table instead of
  the class's own `perms_map`, and the generated subscription always forwards
  one. A subclass tightening the `subscribe` row (`"subscribe":
  ("{app_label}.stream_{model_name}",)`) was silently not enforced — a user
  without that codename could still subscribe — and a loosened row was silently
  denied. Both halves of the composite check now resolve through
  `get_required_permissions`, so the required codenames are the union of the
  `subscribe` row and the row the action maps to. The default mapping is
  unchanged: `view` plus the action's write verb. See
  [Permissions › Customizing the codenames](usage/permissions.md#customizing-the-codenames).
- **A per-request `validation_rules=` could be skipped entirely.** The
  validation cache keyed its verdicts on `id(rules)`, and an address is unique
  only while the object is alive: once a rules tuple built for one request was
  freed, CPython handed the same address to the next one, and the *previous*
  rule set's verdict was replayed — a stricter rule set silently never ran. The
  key is now derived from the rules themselves (their dotted names, in order).
  Views using the shipped class-attribute tuple were never affected.
- **`extensions.cost` was a schema-existence oracle.** With
  `EXPOSE_QUERY_COST`, the cost payload was computed against the FULL schema and
  attached even to a failed validation — so under
  `PERMISSION_SCOPED_SCHEMA` a caller could tell a field pruned out of their
  schema (`requestedCost: 1`) from one that does not exist (`requestedCost: 0`),
  although both answer with the same `Cannot query field` error. That undoes the
  point of the pruned schema. The cost is now computed against the schema the
  request is actually served, and is not attached to a response that carries
  errors and no data. See
  [Query limits › Query cost analysis](usage/query-limits.md#query-cost-analysis).
- **A nested forward FK or M2M payload could rewrite any row of the related
  table.** Declaring `nested_fields = {"category": Category}` was read by the
  writer as *clients may edit any row of the Category table*: naming a pk in the
  nested payload updated that row, whatever it was. The ownership guard did not
  apply (a forward or M2M target is not owned by the parent) and no scope did
  either — a shared lookup row belongs to nobody, so nothing hid it. Updating
  your own document with `{ id: <yours>, category: { id: <any pk>, name: "x" } }`
  returned `ok: true` and renamed a category every tenant reads, while the same
  payload on a reverse FK was correctly rejected. A pk the parent is **not
  already attached to** is now a **link**: the row is set on the parent (or
  `.add()`-ed) and the payload's other fields are ignored. The row the parent is
  already attached to is still updated in place, so the documented use —
  *change the category attached to this document* — is unchanged, as is
  attaching an existing row. See
  [Mutations](usage/mutations.md#how-nested-writes-work).
- **`DjangoModelMutation` had no row-scoping hook at all.** Its sibling
  `DjangoModelType` resolves `update` and `delete` through
  `get_queryset` → `filter_queryset`; the mutation host went straight to the
  bare model and had no such hook to override, so a `filter_queryset` written on
  it — spelled exactly as the documented one, with no error, no warning — was
  never called and every row stayed writable by any caller. Both hooks now exist
  on `DjangoModelMutation` with the same names and signatures, and its `update`
  and `delete` resolve through them. Authorization stays asymmetric and is now
  documented as such: `permission_classes` / `authorize` remain
  `DjangoModelType`-only. See
  [Mutations › Row scoping](usage/mutations.md#row-scoping-get_queryset-filter_queryset).
- **A multi-table-inheritance child could not be put in a schema at all.** The
  native compilers walked `model._meta.get_fields(include_parents=False)` —
  correct for an abstract base, which copies its columns onto the child, and
  wrong for multi-table inheritance, where everything inherited lives in the
  parent's table. An inherited reverse relation was therefore still listed on
  the type but had no compiled counterpart, and the schema build died with
  `RestaurantType fields cannot be resolved. Cannot convert None to a
  graphql-core type` — an error naming nothing that would let you find the
  cause. The field walk in `types.py` now goes through one helper that
  enumerates parents too, so an inherited reverse relation renders as its usual
  `<Model>ListType` container. Models that do not use multi-table inheritance
  are provably untouched (`include_parents` is a no-op for abstract and proxy
  inheritance). The output compiler walks parents too, so the inherited
  **columns** render as well — a multi-table child used to reach the schema
  without so much as an `id`, because every column it inherits (its primary key
  included) lives on the parent. The implicit `<parent>_ptr` link is hidden: the
  child now exposes each inherited column directly, so the link would only offer
  a redundant hop back to a copy of the same row. See
  [Types › Model inheritance](usage/types.md#model-inheritance).
- **`editable=False` relations were accepted in mutation input and silently
  dropped.** The scalar path already honoured `field.editable`, but the
  relation path did not, so a server-managed `ForeignKey` / `OneToOneField` /
  `ManyToManyField` (`created_by`, `tenant`, anything a custom `save()` owns)
  advertised itself as writable, returned `ok: true`, and wrote nothing. Such
  relations are now excluded from the create and update inputs. The guard is
  restricted to concrete fields on purpose: Django hardcodes `editable = False`
  on every reverse relation object, so applying it there would have deleted the
  reverse-relation injection wholesale. The validation-model layer honours
  `editable` on many-to-many too, so a non-editable `ManyToManyField` no longer
  leaks back in as a raw primary-key list.
- **A populated `BinaryField` always read as `null`.** The output compiler
  mapped it to a bare `String` with no resolver, so the `bytes` the column
  yields reached graphql-core's string serializer, which cannot represent them.
  It now resolves through the same shape the `DurationField` precedent uses, and
  delivers the column as **base64** — unconditionally, matching what the
  subscription payload encoder already sends for the same field, so a client is
  never left guessing whether it received text or base64.
- **`DjangoModelType`'s generated list container took the name the docs teach
  you to use.** The container was minted as `<Model>ListType` — the exact name
  the guides give your own `DjangoListObjectType` — so declaring both over one
  model put two different types with one name into a schema and the build
  failed with `Schema must contain uniquely named types`. It is now
  `<Model>ListGenericType`, matching the `Generic` name-space the same type
  already mints its node (`<Model>GenericType`) and inputs
  (`<Model>CreateGenericType`) into. **This is wire-visible**: update any
  client document that spells the container's type name out. Reusing a
  registered container instead was rejected — a `DjangoModelType` carries its
  own `pagination` / `results_field_name` / projection, which a container built
  from someone else's `Meta` would silently discard.
- **A `DjangoModelType` mutation could not be mixed into a forked schema.** The
  generated field stamped only `gdx_required_perms`, while the compiler keys
  its forked-schema payload re-compile off `extensions["gdx_mutation_source"]`
  — the key `DjangoModelMutation` has always stamped. Without it the field
  opted out of the re-fork and every schema built with `registries=` shared the
  payload instance pinned at class-definition time. The field now records its
  source class, so a forked schema compiles its own payload; args, resolver,
  permissions and field shape are unchanged.

### Documentation

- The main tutorial (`Sample Application`), the first example on the Fields
  page, the file-upload guide and several Query Recipes did not compile or
  taught a pattern that crashes at runtime. Every snippet on the affected pages
  was executed against a real schema and corrected.

## 2.1.0 — 2026-08-23

**Security release — upgrade is strongly recommended.** This release closes five
defects confirmed in 2.0.0 by a line-by-line audit of the published code (see
**Security** below), and unifies the subscription filter argument with the query
one.

**The subscription filter argument is now a real typed input object.** Queries
took `filter` as a generated `<Model>FilterInput`; subscriptions took `filters`
as a plain `String` carrying JSON — two names, two shapes, and no schema
validation or autocompletion on the subscription side. That inconsistency is why
the documented subscription filter syntax was wrong for two releases. This
release unifies them.

### Changed (BREAKING)

- **`filters` → `filter`, typed `<Model>SubscriptionFilterInput`.** The
  subscription argument is renamed to the singular query term and takes a
  generated input object with the same nested `{field: {lookup: value}}` shape
  queries use. There is **no `filters` alias** — 2.0.0 shipped one day before
  2.1.0 and the documented syntax never worked, so the exposed surface is
  minimal.

    Before (2.0.x):

    ```graphql
    subscription {
      commentSubscription(action: ALL_ACTIONS, filters: "{\"post\": 7}") {
        id
        text
      }
    }
    ```

    After (2.1.0):

    ```graphql
    subscription {
      commentSubscription(action: ALL_ACTIONS, filter: { post: { exact: 7 } }) {
        id
        text
      }
    }
    ```

    Combining lookups works the same way:
    `filter: { post: { exact: 7 }, status: { in: ["open", "urgent"] } }`.

- **The schema is now the filter boundary.** The generated input type is
  deliberately **not** the query's `<Model>FilterInput` — reusing it would
  re-expose every lookup and reopen the extraction oracle closed in this release. It
  declares exactly the subscription's projected output fields (honouring
  `Meta.only_fields` / `Meta.exclude_fields`) and exactly the four allowed
  lookups (`exact`, `iexact`, `in`, `isnull`). It is flat, so relation traversal
  is unexpressible. A banned lookup, an excluded column or a relation path is now
  a **GraphQL validation error** instead of a runtime rejection. The runtime
  check remains as defence in depth for anything reaching the engine without
  schema coercion.

  Both input types coexist in one schema; the query-side
  `<Model>FilterInput` SDL is unchanged.

### Security

*The five items below were prepared as 2.0.1; that patch was never published —
they ship here in 2.1.0.*

- **Relation traversal bypassed permission scoping.** Only generated root fields
  carried the permission label the pruner reads, so a user could read a model
  they had no `view_<model>` permission for by traversing a relation from a
  parent they *could* read (`post { comments { ... } }`). Untagged fields now
  fall back to the implicit label of their output type, and the schema label set
  is widened accordingly, so `PERMISSION_SCOPED_SCHEMA` removes those relation
  fields. See [Permission-Scoped Access](usage/permission-scoped-schema.md).
- **Subscription client filters were an extraction oracle.** The filter
  whitelist was built from the unprojected model, and only the segment before
  the first `__` was validated — so a subscriber could probe any column
  (including `password`) one comparison at a time via lookups such as
  `startswith`, and could traverse into related models. `Meta.only_fields` /
  `Meta.exclude_fields` are now honoured by the subscription backend, relation
  traversal is rejected, and client filters accept only `exact`, `iexact`, `in`
  and `isnull`. Ordered and pattern lookups (`startswith`, `icontains`, `gt`,
  `regex`, `range`, date parts) are refused — move that logic to
  `subscription_scope`. See [Subscriptions](usage/subscriptions.md).
- **`private_subscription` was not enforced on either transport.**
  `DJANGO_GRAPHEX['MIDDLEWARE']` was read only by `GraphQLView`, while
  subscriptions are served exclusively by the SSE view and the WebSocket
  consumer — so `AuthenticatedFieldsMiddleware` never ran and an anonymous
  subscriber received protected events. Both transports now build and apply the
  configured middleware chain for the subscribe and delivery paths.
- **Sub-kilobyte documents could pin a worker (DoS).** The bundled depth and
  cost validation rules re-walked each fragment once per reachable path, so a
  ~1 KB document with fan-out fragments took over ten seconds of CPU — before
  authentication, on any stock `GraphQLView`. Both rules now memoize each
  fragment's contribution; reported depth and cost values are unchanged.

### Fixed

- **`<Model>FilterInput` name collision refused to build the schema.** Filtering
  a relation by a column the related type does not itself declare (for example
  `filter_fields = {"author__email": ("exact",)}`) produced two input types with
  the same name and a hard `TypeError` at schema construction — the application
  did not start. One canonical instance per model is now cached and widened in
  place, converging regardless of build order.
- **Documented `filters` syntax could never work.** Every snippet showed
  `filters: { post: 7 }`, but the argument is a `String` carrying JSON, so the
  object literal failed input coercion. Docs and the playground now show the
  JSON-encoded form.

## 2.0.0 — 2026-06-17

**graphene removed — `django-graphex` now runs on native graphql-core + Pydantic
alone.** The legacy graphene backend is deleted; graphene is no longer a
dependency and is never imported, even on a full build with mutations,
subscriptions and pagination. See the [Upgrade Guide](UPGRADE-2.0.md) for
before/after snippets and a migration codemod (`scripts/migrate_2_0.py`).

### Changed (BREAKING)

- **graphene backend removed entirely.** The `GDX_BACKEND` environment variable
  that selected the legacy graphene path is gone; the native graphql-core path is
  the only path. graphene (and graphene-django) are no longer required and can be
  uninstalled.
- **`GRAPHENE` settings namespace → `DJANGO_GRAPHEX` (single namespace).**
  Schema/middleware settings (`SCHEMA`, `MIDDLEWARE`, `SUBSCRIPTION_PATH`, …) are
  merged into the single `DJANGO_GRAPHEX` Django-setting dict alongside this
  package's own settings (pagination, caching, query limits, …); there is no
  longer a separate schema-settings namespace, and the legacy `GRAPHENE`
  namespace is no longer consulted. The codemod `--apply` folds an existing
  `GRAPHENE` dict into `DJANGO_GRAPHEX` (no key collisions).
- **`graphene.ObjectType` schema roots → native `ObjectType`.** Import the root
  base from `django_graphex.core` (`from django_graphex.core import ObjectType`).
- **`graphene.Schema(...)` → `DjangoGraphQLSchema(...)`.** Build the schema with
  the public `django_graphex.schema.DjangoGraphQLSchema` class.
- **graphene field descriptors → native `field(...)`.** Hand-declared (non-model)
  fields use `field(GraphQLString)` / `field(GraphQLList(...))` with graphql-core
  types instead of `graphene.String()` / `graphene.Field(...)`.
- **`graphene.Argument(...)` in a Mutation `class Arguments` → `GraphQLArgument(...)`.**
  Mutation arguments are declared with native graphql-core `GraphQLArgument` (a
  bare graphql-core type is auto-wrapped) inside the `class Arguments` inner class.
  This is a **clean break**: a non-native value left in `class Arguments` now
  raises `TypeError` instead of being silently dropped.
- **`choices` fields now render as a GraphQL enum on both output and input.** A
  model field with `choices` is exposed as a real `GraphQLEnumType` on the output
  type and on filter/input types (previously a choices field could render as a
  plain `String` on the native path). This is an observable wire-format change —
  review clients that send/read choices values as raw strings.
- **Update mutations now honour an explicit `null` (GraphQL-spec-correct:
  omitted ≠ null).** Previously `update()` stripped every `None` from the input
  and treated `null` as "not provided", so a nullable field or an M2M could not
  be cleared over the wire. Now an **omitted** field is left unchanged (partial
  update), while an **explicit `null`** sets a nullable scalar/FK column to
  `NULL` and clears a top-level (`ID`-list) M2M — `tags: null` is equivalent to
  `tags: []`. A `null` on a **required** field returns a clean validation
  `errors[]` payload (`ok: false`), never a 500. **Nested** inputs
  (`Meta.nested_fields`) still treat `null` / `[]` / `{}` as a **no-op** (related
  children are never deleted). This is an observable behavior change — review
  clients that relied on `null` being silently ignored on update. Both mutation
  surfaces (`DjangoModelMutation` and `DjangoModelType`) behave identically. See
  [Mutations → Explicit-null semantics](usage/mutations.md#explicit-null-semantics-in-update-mutations).
- **Public-API renames.** Five names were renamed for clarity and consistency
  (no deprecated aliases — update call sites directly):
    - **`Meta.max_deep` → `Meta.max_depth`** on `DjangoObjectType`,
      `DjangoListObjectType`, and `DjangoModelType` (aligns with the
      `MAX_QUERY_DEPTH` setting). The unknown-option guard names the new spelling.
    - **`@filter_field(graphene_type=…)` → `@filter_field(graphql_type=…)`**
      (graphene is gone; the argument type must be a graphql-core `GraphQLType`).
    - **`DjangoUnionType` `Meta.gfk_types` → `Meta.types`**. Declaring the old
      `gfk_types` now raises `ImproperlyConfigured` with a rename hint.
    - **GFK-owner `Meta.gfk_unions` → `Meta.unions`** (the key that maps a
      `GenericForeignKey` to a typed union on a `DjangoObjectType`). Declaring the
      old `gfk_unions` now raises `ImproperlyConfigured` with a rename hint
      (`gfk_unions was renamed to unions in v2.0`).
    - **Mutation argument container `class args` → `class Arguments`** on the
      native hand-written `Mutation` base (unifies with `DjangoModelMutation` /
      `DjangoModelType`, which already used `Arguments`). A subclass that still
      declares the legacy inner `class args` (and no `Arguments`) raises
      `TypeError` with a rename hint at `Field()` build time.
    - **Subscription `Meta.serialize_data` → `Meta.payload_mode`** and the
      **`SUBSCRIPTION_SERIALIZE_DATA` setting → `SUBSCRIPTION_PAYLOAD_MODE`**. The
      boolean flag becomes a string mode: `serialize_data=True` → `payload_mode=
      "full"`, `serialize_data=False` → `payload_mode="id_only"` (the new global
      default), `None` still inherits the setting. Semantics are unchanged (id-only
      broadcasts `{"id": <pk>}`; full broadcasts a flat serialization). Declaring
      the old `Meta.serialize_data` key or the old `SUBSCRIPTION_SERIALIZE_DATA`
      setting key raises `ImproperlyConfigured` with a rename hint, and an invalid
      `payload_mode` value names both valid values.
- **`InputField` and the 12 `*InputField` twins removed — one unified `Field`.**
  The `Field` / `InputField` split is gone: the single `Field` descriptor (and 11
  typed shortcuts — `IntField`, `CharField`, `FloatField`, `BooleanField`,
  `IDField`, `DateField`, `DateTimeField`, `TimeField`, `DecimalField`,
  `UUIDField`, `JSONField`) now works in **both** an output body **and** a
  `class Arguments` body. `InputField` and every `*InputField` twin
  (`IntInputField`, `CharInputField`, …) are **removed** with no alias — port with
  a search-and-replace that drops the `Input` infix (`InputField` → `Field`,
  `IntInputField` → `IntField`, …). `resolver=` / `source=` / `args=` are
  output-only (a `TypeError` in an argument position) and `default=` is input-only
  (a `TypeError` at output compile). The raw `GraphQLArgument` idiom is unaffected.
  See [Upgrade Guide → §8](UPGRADE-2.0.md#8-inputfield-inputfield-twins-removed-one-unified-field).
- **`JSONField` now carries raw JSON on the wire (SDL scalar `JSON`).** A model
  `models.JSONField` and the `JSONField()` descriptor are transported as **raw,
  structured JSON** (SDL scalar `JSON`) across all three paths — output, mutation
  input, and filters — instead of the JSON-encoded string wire (SDL scalar
  `JSONString`) used before. Objects, lists, and scalars pass through
  structurally, and inline object / list literals are accepted directly in a
  query. **Clients that `JSON.parse()`d the old `JSONString` wire (or
  `JSON.stringify()`d it on input) must stop.** The escape hatch
  `JSONField(as_str=True)` keeps the old `JSONString` (string-encoded) wire for a
  single descriptor field. `GenericJSONField` and the `GenericScalar` SDL scalar
  name are **removed** (the raw scalar is exported as `GdxJSON`, SDL name `JSON`;
  the legacy graphene `GenericScalar` class still resolves to it for backward
  compatibility, and `GdxJSONString` stays). This is an observable SDL change.
  See [Upgrade Guide → §9](UPGRADE-2.0.md#9-jsonfield-now-carries-raw-json-on-the-wire-sdl-scalar-json).
- **Cursor pagination cursor format is now composite (`value` + `pk`).**
  `CursorGraphqlPagination` encodes the boundary row's ordering value **plus** its
  primary key as a deterministic tiebreak, so tied ordering values page correctly
  (rows are never dropped or duplicated across a boundary). Any **stored** v1 /
  beta cursor string is no longer valid and raises a clean
  `GraphQLError("Invalid cursor")` — re-fetch from the first page after upgrading.
  The `first` argument is unchanged.
  See [Upgrade Guide → §11](UPGRADE-2.0.md#11-cursor-pagination-cursor-format-changed-composite-keyset).
- **Output camelCase digit parity — `phone_1` → `phone1` (bugfix, wire-visible).**
  A field name with a trailing digit component was camelCased incorrectly on the
  **output** side (`phone_1` stayed `phone_1`), diverging from the **input** side
  (Pydantic), which already produced `phone1`. Output now routes through the same
  canonical camelCase, so `phone_1` → `phone1`, `address_2` → `address2`,
  `iso_8601_date` → `iso8601Date` — restoring output/input wire parity (and v1
  graphene parity). Fields without a digit component (`created_at` → `createdAt`)
  are unchanged. Review clients that selected the old `phone_1`-style output name.
  See [Upgrade Guide → §12](UPGRADE-2.0.md#12-output-camelcase-digit-parity-phone_1-phone1).
- **Filter input SDL name `<Model>Filterinput` → `<Model>FilterInput` (bugfix,
  wire-visible).** The generated filter input type name is now capitalized
  idiomatically (`UserFilterInput`, not `UserFilterinput`). Inline
  `filter: { ... }` usage is unaffected; update any named-variable reference
  (`$filter: UserFilterInput`) or SDL snapshot / codegen artifact that pinned the
  old spelling.
  See [Upgrade Guide → §13](UPGRADE-2.0.md#13-filter-input-sdl-name-modelfilterinput-modelfilterinput).

### Removed

- The graphene backend producer code, the `GDX_BACKEND` / dual-backend switch, and
  the graphene dependency from `pyproject.toml`.

### Added

- **Django-style field descriptor API** (`django_graphex.core`), **unified across
  positions**. One capitalized, Django-model-field-style `Field` descriptor
  declares custom (non-model) fields in **both** an `ObjectType` / `Mutation`
  payload body **and** a `class Arguments` body — direction is inferred from the
  declaration site, not the descriptor. It is sugar over the `field()` /
  `GraphQLArgument` substrate (every descriptor compiles byte-identical, no
  wire/SDL change). `Field(type, *, source=None, required=False, default=_UNSET,
  description=None, name=None, resolver=None, args=None, deprecation_reason=None)`:
  `source=` / `resolver=` / `args=` are **output-only** (a clear `TypeError` if left
  on an argument-position field) and `default=` is **input-only** (a `TypeError` at
  output compile). Ships **11 typed scalar shortcuts** usable in both positions —
  `IntField`, `CharField`, `FloatField`, `BooleanField`, `IDField`, `DateField`,
  `DateTimeField`, `TimeField`, `DecimalField`, `UUIDField`, `JSONField` — plus a
  **collision guard** that raises a loud `TypeError` naming the likely import
  mistake if a `django.db.models.Field` is used where a descriptor is expected. The
  low-level `field()` helper and the raw `GraphQLArgument` / lambda-thunk idiom stay
  public and unchanged. See
  [Declaring fields: the descriptor API](usage/types.md#declaring-fields-the-descriptor-api).
- **Ordering values accept camelCase (GraphQL-consistency).** Because every field
  *name* is exposed in camelCase on the wire, the `ordering` **value** now accepts
  camelCase too: each term is normalized to its snake_case attname (preserving the
  `-`/`+` direction prefix) at one canonical point, so `ordering: "createdAt"`
  behaves **exactly** like `ordering: "created_at"` — on the DB path, the
  in-memory (prefetch-cache) path, **and** the nested window-prefetch optimization
  (which no longer declines for a camelCase term). snake_case keeps working
  unchanged; an invalid camelCase field still raises the same
  `Invalid ordering field` `GraphQLError`, and relation-spanning terms are still
  rejected. `CursorGraphqlPagination` (server-configured ordering) is unaffected.
  This also fixes a latent bug where a camelCase ordering term **silently degraded**
  on the in-memory path (it sorted by a missing attribute — a no-op) instead of
  matching the DB path.
- **Permission-scoped schema** (`PERMISSION_SCOPED_SCHEMA` setting, default
  `False` — fully inert until enabled). `AuthenticatedGraphQLView` can serve each
  authenticated request a schema **pruned to the caller's permissions**: a field
  whose required perms the caller lacks is *absent* from validation, so selecting
  it reads as a native `Cannot query field` (a not-found, never an authorization
  error — no existence leak). Both validation and execution run against the
  pruned schema; a caller whose entire `Query` root is pruned away gets the
  endpoint's generic `403`; an active superuser always gets the full schema; the
  public `GraphQLView` is never pruned. Includes:
    - **`field(required_perms=…)`** and a **`Mutation.required_perms`** class
      attribute to label fields explicitly, on top of the automatic labels
      stamped on every generated CRUD field (`extensions["gdx_required_perms"]`);
      an unlabeled field is treated as public.
    - a **revised composite `DjangoModelPermissions.perms_map`** — because a
      write payload returns instance data, `create`/`update`/`delete` now require
      the write verb **and** `view` (read actions stay `view`-only; override
      `perms_map` to restore write-only behavior).
    - **per-action subscription authorization** — `authorize_subscription` now
      forwards the requested `action`, so subscribe permissions are enforced per
      CRUD action (defense in depth: the action's enum value is pruned at
      validation *and* denied at runtime).
    - a **per-connection `schema_provider`** on the WS/SSE subscription
      transports, so subscriptions prune to the same schema as HTTP for a user.
    - **cache-key hardening** — pruned schemas are memoized in a bounded
      in-process LRU keyed by the caller's *permission signature*
      (`perms ∩ schema label-set`, never by user id, revoke-safe;
      `PERMISSION_SCHEMA_CACHE_MAXSIZE`, benchmark-calibrated default `64`), and
      the HTTP response cache folds the signature into its key so a low-permission
      caller can never read a high-permission caller's cached response body.

  Requires a labeled `DjangoGraphQLSchema`; with the flag `False` behavior is
  byte-identical to today. See
  [Views → Permission-scoped schema](usage/views.md#permission-scoped-schema-permission_scoped_schema),
  [Security → Permission-scoped schema](usage/security.md#permission-scoped-schema-permission_scoped_schema),
  and [Settings → Security](usage/settings.md#security).
- **`API_ACCESS_GROUP` setting** (`DJANGO_GRAPHEX`). Restricts the authenticated
  endpoint (`AuthenticatedGraphQLView`) to members of a single Django auth
  `Group` (by name). `""` (default) disables the gate — zero impact. When set,
  non-members are rejected with a generic **HTTP 403** before any GraphQL
  parsing/execution (the message never leaks the group requirement), an **active
  superuser always bypasses** the gate (hardcoded invariant), and a
  missing/anonymous user is denied (fail-closed, independent of
  `permission_classes`). The public `GraphQLView` is **not** affected. See
  [Views → Endpoint-level auth](usage/views.md#restricting-the-endpoint-to-a-group-api_access_group)
  and [Settings → Security](usage/settings.md#security).
- **`DjangoModelPermissions` permission class** (`django_graphex.permissions`).
  A DRF-style permission that maps each CRUD action to Django's built-in model
  permissions (`add`/`change`/`delete`/`view`) and checks them with
  `user.has_perms`. Fail-closed (anonymous users, a missing model, and unknown
  actions are denied), superusers pass automatically, and the per-action
  codenames are customizable via the `perms_map` class attribute or by
  overriding `get_required_permissions`. Intended for
  `DjangoModelType.permission_classes`. See
  [Permissions → `DjangoModelPermissions`](usage/permissions.md#djangomodelpermissions).
- **`graphql_schema` management command** (introspection JSON / SDL export).
  Mirrors graphene-django's command of the same name (a drop-in for migrating
  users) but is built on graphql-core with no graphene import. Writes
  introspection JSON wrapped as `{"data": ...}` (matching graphene-django's
  shape) to `DJANGO_GRAPHEX["SCHEMA_OUTPUT"]` (default `schema.json`), or SDL
  when the output path ends in `.graphql` / `.gql`. Supports `--out`/`-o`
  (incl. `-` for stdout), `--indent`/`-i`, and `--schema <dotted.path>`. New
  settings `SCHEMA_OUTPUT` and `SCHEMA_INDENT` back the command's defaults. See
  [Settings → Exporting the schema](usage/settings.md#exporting-the-schema).
- **`deprecation_reason=` across the descriptor API and every Django field/mutation
  builder.** `field()`, `Field`, and all 11 typed shortcuts accept a
  `deprecation_reason=`, and so do every Django mounting builder —
  `DjangoObjectField`, `DjangoListObjectField`, `DjangoFilterListField`,
  `DjangoFilterPaginateListField`, `RetrieveField`, `QueryFields`, and the mutation
  builders (`CreateField` / `DeleteField` / `UpdateField` / `MutationFields`). When
  set, the reason is wired into the compiled field / argument so the SDL renders
  `@deprecated(reason: "…")`.
- **Pydantic `InputType` `list[...]` fields render as GraphQL lists with defaults.**
  A `list[...]`-annotated field on an `InputType` now compiles to a GraphQL list
  input (`[T]`), and a Python field default is carried into the SDL as the
  argument's default value.

### Performance

Five behavior-preserving optimizations (response shape is unchanged in all
five; SQL query counts and per-request timings improve). A reproducible
cross-library benchmark harness lives at `benchmarks/` if you want to measure
these against your own workload.

- **`totalCount` is computed lazily.** The `COUNT` query is only issued when
  the client actually selects `totalCount`, and reuses an already-materialized
  results list (`len()`) instead of a fresh query when one is available.
  Skips one `COUNT` query per request for any list operation that doesn't
  select `totalCount`.
- **Parse + validate document cache** (`DOCUMENT_CACHE_MAXSIZE` setting,
  default `128`). graphql-core's `parse()` and `validate()` are memoized in two
  bounded LRUs — a global parse cache keyed on the query string (the AST is
  immutable and schema-independent) and a per-schema validation cache keyed by
  the schema **object** (a `WeakKeyDictionary`, so a permission-pruned schema
  never shares a verdict with another schema). Shaves the re-parse/re-validate
  cost (each on the order of a fraction of a millisecond) on every repeated
  document. See
  [Settings → Document cache](usage/settings.md#document-cache-parse-validate).
- **Cached Pydantic validator build.** `build_model_schema` (the dynamically
  generated Pydantic model backing create/update validation) is now memoized
  per `(model, partial, base, exclude)` instead of rebuilt on every mutation
  call — the derived class is a pure function of that key, so rebuilding it per
  request was wasted work.
- **FK existence check moves to the mutation failure path.** A valid
  create/update mutation issues a single `INSERT`/`UPDATE` — the per-FK
  existence pre-check no longer runs on the happy path. A bad FK still returns
  the same structured `errors[]` envelope; the diagnostics that produce it now
  run only after an `IntegrityError`. Saves one `SELECT` per FK field on every
  successful mutation.
- **Nested-write savepoint opens only when nested work is present.** A
  create/update mutation with `Meta.nested_fields` no longer opens a
  `transaction.atomic()` savepoint when the request has no nested child
  payload — a plain, parent-only mutation pays no savepoint overhead.

See [Mutations → performance note](usage/mutations.md#error-handling) and
[Pagination → `totalCount` is computed lazily](usage/pagination.md#query-examples)
for the user-facing behavior these changes preserve.

### Fixed

- **Subscription transports' `schema_provider` now respects
  `PERMISSION_SCOPED_SCHEMA`.** Once a `schema_provider` was wired on
  `subscription_ws_consumer` / `subscription_sse_view`, the bundled
  `pruned_schema_for` helper pruned **unconditionally** — the provider path never
  read `PERMISSION_SCOPED_SCHEMA` even though the HTTP `AuthenticatedGraphQLView`
  is gated by it, so the transports diverged from HTTP. The bundled helper now
  reads the flag **per connection** (never at import): it returns the **full**
  schema when the flag is off (default) and the **pruned** schema when on, so one
  flag rules the feature across HTTP, SSE, and WebSocket. The active-superuser
  invariant is unchanged (always the full schema), and a **custom** provider
  callable that does not route through `pruned_schema_for` is honored as-is (the
  flag gates the bundled helper only).
- **Model-derived `JSONField` mutation inputs now store a real Python object.** A
  model-derived `JSONField` (and `HStoreField`) was rendered as a plain `String`
  on the mutation **input** type, so the submitted JSON text was assigned to the
  column verbatim — a double-encoded string instead of the parsed value. Model
  `JSONField` / `HStoreField` inputs now render as the raw `JSON` scalar (see the
  JSON-flip breaking change above) and store a dict **or** a list as a real Python
  object on both create and update — output, input, and filter paths all agree on
  the `JSON` scalar. The custom scalars are exported for reuse:
  `from django_graphex.core import GdxJSON` (also `GdxJSONString`, `GdxDate`,
  `GdxDateTime`, `GdxTime`, `GdxDecimal`, `GdxUUID`).
- **Pagination `limit` / `first` guards — zero and negative now raise a clean
  `GraphQLError`.** A `limit: 0` / `first: 0` or a negative `limit` / `first`
  previously slipped through (or produced a negative-offset slice); both now raise
  a structured `GraphQLError` (e.g. `Invalid limit: -5. Limit must be a positive
  integer.`) instead of an HTTP 500 or an empty page. Negative `offset` already
  raised.
- **`PageGraphqlPagination` supports backward (negative-page) access.** `page: -1`
  returns the **last** `page_size` rows in true `list[-N:]` order, `page: -2` the
  window before it, and an overshoot clamps to the first rows. A negative page
  costs one `COUNT` (needed to compute the count-relative offset) and opts out of
  the nested window-prefetch optimization; `page: 0` still raises a `GraphQLError`.
- **`prune_schema` forwards interface implementers (`PERMISSION_SCOPED_SCHEMA`
  polymorphic fix).** A surviving object type that implemented a surviving
  interface but was only ever returned *via* the interface used to fall out of the
  pruned schema's `type_map`, leaving `possible_types` empty and breaking
  inline-fragment queries. The pruner now forwards those implementers, so an
  interface keeps its implementers in the pruned schema exactly as in the full one.
- **SSE subscription transport hardening.** The bundled SSE view is now
  `csrf_exempt` (the event-stream endpoint no longer trips CSRF), and the SSE
  client's request path building and value escaping were corrected.
- **GenericForeignKey custom-PK resolution uses `root.pk`.** A GFK whose owner has
  a non-default primary key name is now resolved via `root.pk` (rather than a
  hard-coded `id`), so custom-PK owners resolve their GFK target correctly.
- **Inline JSON literals are accepted on `JSON` arguments.** The `JSON` scalar's
  literal parser recurses `ObjectValueNode` / `ListValueNode` (and resolves nested
  `VariableNode` references), so an inline object / list literal
  (`payload: { a: 1, tags: [1, 2] }`) is parsed into a real Python `dict` / `list`
  instead of being rejected.

## 1.3.0 — 2026-06-13

### Added

- **`@filter_field` decorator** (#26) — declare custom per-field GraphQL filter
  arguments directly on a `DjangoObjectType` or `DjangoModelType`, co-located
  with the resolver logic. The method name becomes the GraphQL argument name;
  the graphene type (default `graphene.String`) and an optional description are
  configurable. `filter_fields` continues to work for model-field lookups; custom
  logic is now exclusively via `@filter_field`. Composition order at query time:
  `get_queryset`/`filter_queryset` scoping first, then standard lookups, then
  `@filter_field` methods (declaration order). (#26)
  <small>*Erratum: this entry originally described `filter_queryset` as running
  last — the scoping hook has always run first. See
  [Filtering → Composition order](usage/filtering.md#composition-order).*</small>

- **`Base64FileInput` — opt-in base64 file uploads** (#25) —
  `Base64FileInput(graphene.InputObjectType)` with `filename` (required),
  `data` (required, base64-encoded), and `content_type` (optional, default
  `application/octet-stream`). Call `.to_uploaded_file(max_size=None)` in any
  mutation resolver to obtain a Django `SimpleUploadedFile` ready for
  `FileField.save()`. Also importable as `decode_base64_file(value, *,
  max_size=None)` for cases where you hold the raw dict.

  Two new settings enforce memory safety:

  - **`MAX_UPLOAD_SIZE`** (int bytes, required when `Base64FileInput` is used)
    — global decoded-size cap. A pre-check fires before base64 decoding to
    avoid the allocation. Per-field `max_size` overrides this. Raises
    `ImproperlyConfigured` if absent and no per-field override is given.
  - **`MAX_REQUEST_BODY_SIZE`** (int bytes, `None` = disabled) — HTTP body-size
    guard in `BaseGraphQLView.dispatch`, checked before JSON parsing. Rejects
    oversized bodies with **HTTP 413**. This is the primary memory cap (the
    base64 string is already in RAM once the body is parsed).

  Malformed base64 raises `GraphQLError` (never HTTP 500). Content-type
  validation (magic bytes) is out of scope — use `FileField` validators.
  Batch requests: `MAX_BATCH_SIZE` (op count) + `MAX_REQUEST_BODY_SIZE`
  (bytes) compose; no special upload-batch logic. Upload mutations bypass the
  response cache automatically (mutations are never cached). See
  [Mutations → File Upload Support](usage/mutations.md#file-upload-support) and
  [Settings → File uploads](usage/settings.md#file-uploads). (#25)

### Changed

- **BREAKING — minimum Django raised to 5.2** (#75) — Django 4.2, 5.0, and 5.1
  are no longer supported (all end-of-life). The supported matrix is now
  **Django 5.2 (LTS) + 6.0** × **Python 3.12–3.14**. Tooling: `pytest-asyncio`
  pinned to `>=1.0`, `ruff` constraint updated, CI uses `setup-uv` v8.

- **`filter_fields = {"field": None}` now raises `ImproperlyConfigured`** (#26) —
  The `None` sentinel (which previously applied the default lookup set and crashed
  with `TypeError`) was un-Pythonic and has been replaced by the `@filter_field`
  decorator. The error message directs users to the new API.

### Fixed

- **Docs accuracy** (#71) — Five follow-up fixes: migration guide import corrected
  (`graphene_django_extras` → `django_graphex`); fragile changelog anchor removed
  from query-optimization guide; `Meta` validation options table added to types
  docs; `!!! warning` callout added to API types reference; `BaseGraphQLView`
  views docstring reworded to match the actual tuple-store/reconstruct caching
  mechanism.

- **TTL and CSRF-replay tests now have teeth** (#72) — The TTL test previously
  read `_cache[raw_key]` (LocMemCache stores expiry in `_expire_info`, not in the
  value tuple), making the assertion vacuous. Replaced with a `cache.get()`
  presence check plus `_expire_info` TTL assertion. The CSRF-replay test's
  `if`-gated `assertNotEqual` was replaced with an unconditional
  `assertNotIn('Set-Cookie', resp2)` plus a super-call count assertion that
  verifies the cache hit.

- **Test infrastructure hardened** (#73) — Multi-backend cache fixture covering
  both `LocMemCache` and `DatabaseCache`; concurrency test for parallel mutation
  invalidation; dead `reset_global_registry` call removed; fixture deduplication.

- **Playground updated** (#74) — `PostType.get_queryset` scoping example (anonymous
  → published only, authenticated → all); safe-ordering comment on `PostListType`;
  version signal markers updated; README banner added ("Targets django-graphex
  v1.3.x") with safe-ordering table.

### New settings

| Setting | Default | Description |
|---|---|---|
| `MAX_UPLOAD_SIZE` | `None` | Global decoded-size cap for `Base64FileInput` (bytes). Required when using uploads unless a per-field `max_size` is set. |
| `MAX_REQUEST_BODY_SIZE` | `None` | HTTP body-size guard (bytes). Requests exceeding this limit are rejected with HTTP 413 before JSON parsing. |

### Behavior changes

!!! warning "Review before upgrading"

    Review each item below before upgrading.

- **Django < 5.2 is no longer supported** — Upgrade Django to ≥ 5.2 before
  upgrading `django-graphex` to 1.3.0. Projects on Django 4.2, 5.0, or 5.1 must
  stay on `django-graphex` 1.2.x. (#75)

- **`filter_fields = {"field": None}` now raises `ImproperlyConfigured`** —
  Previously this crashed with `TypeError`; the error is now explicit and
  directive. Replace `None` entries with a `@filter_field`-decorated method on
  the same type. (#26)

- **Custom filters are now declared exclusively via `@filter_field`** — Passing
  callable values through `filter_fields` is no longer supported. Use the
  `@filter_field` decorator instead; it co-locates the filter logic with the
  declaration. (#26)

- **`Base64FileInput` requires `MAX_UPLOAD_SIZE` or a per-field `max_size`** —
  Using `Base64FileInput` without either a global `MAX_UPLOAD_SIZE` setting or a
  per-field `max_size` kwarg raises `ImproperlyConfigured` at resolution time.
  (#25)

## 1.2.3 — 2026-06-13

!!! note "Hotfix"

    Corrective release only — no behavior changes beyond restoring the two
    pre-1.2.2 behaviors described below.

### Fixed

- **Subscription delete broadcasts no longer send `pk=None`** — `_on_delete`
  now snapshots the pk (and the serialized payload in `serialize_data=True`
  mode) at signal time before deferring via `transaction.on_commit`, instead
  of capturing the live instance whose pk Django nulls before the callback
  runs. Fixes misrouted per-object delete notifications in the default
  id-only mode and a `ValueError` that escaped the user's transaction in
  `serialize_data=True` mode. Regression from 1.2.2 (#63). (#69)
- **Pagination `ordering` now accepts the idiomatic `pk` / `-pk` alias** —
  The 1.2.2 ordering allowlist (#59) rejected it, breaking any paginator
  configured with `ordering="pk"` on every request. Relation-spanning (`__`)
  ordering remains rejected. Regression from 1.2.2. (#70)

## 1.2.2 — 2026-06-13

### Security

- **`DjangoObjectType.get_queryset` now actually applied on object, list, paginated,
  and list-object fields** — The hook was documented but never invoked on those field
  types, making every override a silent no-op. It is now called for
  `DjangoObjectField`, `DjangoFilterListField`, `DjangoFilterPaginateListField`, and
  `DjangoListObjectField` (results + totalCount). (#58)
- **Pagination `ordering` validated against the model's concrete columns** —
  Client-supplied `ordering` values are now checked before they reach the ORM. An
  unknown field name can no longer trigger a `FieldError` that discloses the model's
  full field list, nor a relation-traversal `JOIN` that enables a DoS via
  index-missing foreign keys. (#59) *Corrected: this entry originally said
  "validated against exposed columns". It was not — the allowlist came from the
  model, so a column the type projected away stayed sortable. See the 3.0.0
  Security section.*
- **Response cache skips cookie-bearing and multipart requests** — The
  `CACHE_ACTIVE` cache no longer stores responses to requests that carry cookies or
  are `multipart/form-data`. Previously such responses could be replayed to unrelated
  clients (CSRF-cookie replay) or cause a 500 on multipart uploads. (#53)

### Fixed

- **Directives and pagination raise `GraphQLError` instead of HTTP 500 on bad client
  input** — `@base64`, `@currency`, `@floor`, `@ceil`, `@round`, `@abs`, `@center`,
  and negative-offset pagination now return a structured `GraphQLError` for invalid
  arguments rather than an unhandled exception that propagates as HTTP 500. (#50)
- **Nested-write integrity** — M2M writes with a bad primary key now return a
  structured error instead of crashing; the reverse-FK ownership guard prevents
  cross-owner row "stealing"; to-one fields that receive a list are rejected at
  input validation; `pk=0` upsert correctly routes to the update path; enum values
  inside a list input are properly unwrapped before persistence. (#62, #51)
- **Subscriptions run `authorize`/`scope` and registry I/O via `sync_to_async`** —
  Resolves `SynchronousOnlyOperation` errors that appeared when authenticated
  subscriptions called ORM-backed permission or scope logic from an async context.
  The `disconnect` handler is also now safe to call without a prior `connect`. (#61)
- **Subscription broadcasts fire on transaction commit** — Notifications are now
  deferred to `transaction.on_commit` rather than being sent at `save()` time. Rows
  inserted in a rolled-back transaction no longer emit phantom notifications to
  subscribers. (#63)
- **Enum registry keyed by model class** — The enum registry now uses the model
  class as the key, preventing collisions between apps that define a model with the
  same name. Self-referential `OneToOneField` relations are no longer silently
  dropped during schema construction. (#52)
- **`Meta`-option hygiene** — Unknown or mistyped `Meta` options (e.g.
  `filter_Filed` instead of `filter_fields`) now raise `ImproperlyConfigured`
  instead of being silently ignored. `include_fields` is honored on input and list
  types; an `id`-excluded `only_fields` no longer breaks the update mutation;
  `DjangoListObjectType.Meta.queryset` is now consumed as the base queryset. (#65)
- **Cache version counter uses `transaction.on_commit`** — The version-bump that
  invalidates a user's cache is now deferred to commit, closing the pre-commit stale
  window. Non-expiring version keys no longer resurrect after a cache flush; a cold
  key correctly heals to `1` rather than `0`. (#60)

### Performance

- **Empty window-sliced nested pages skip per-parent `COUNT`** — When a
  window-sliced nested list returns zero rows for a parent, no additional `COUNT`
  query is issued for that parent. (#64)
- **Request-scoped field-map cache threaded through filtered-prefetch descent and
  `.only()`-narrowing pass** — The per-request `_cache` dict is now correctly
  propagated through the filtered-prefetch and column-narrowing code paths,
  preventing redundant `_meta.get_fields()` calls on queries with nested filtering
  or `.only()` projections. (#57, #66)

### Packaging / Docs

- **`all_directives` static type matches runtime instances** — The type annotation
  was broadened to match the actual runtime list of directive instances returned by
  the function. (#66)
- **Install "verify" snippet works on a clean install** — `docs/installation.md`
  now uses `importlib.metadata.version('django-graphex')` (no `django.setup()`
  required) and carries an accurate Python × Django compatibility statement.
  Development Status classifier set to "5 - Production/Stable". (#67)
- **README and migration link fixes** — Migration guide URL corrected from
  `.../migration.html` to `.../migration/`; stale `#18` tracking links removed from
  `docs/usage/mutations.md`. mypy dev dependency pinned to `>=2.1,<3` to match CI;
  `daphne` upper bound `<5.0` restored in tox test environments;
  `filter_fields={"field": None}` no longer raises at schema build. (#55)

### Behavior changes

!!! warning "Review before upgrading"

    Review each item below before upgrading. Items marked **action required** need
    a one-time change in your project.

- **Subscription broadcasts now deliver on COMMIT, not at `save()` time** —
  Downstream tests that use `@pytest.mark.django_db` (non-transactional) will not
  observe broadcasts unless the test database wraps the write in a real transaction.
  **Action required for test authors**: switch to
  `@pytest.mark.django_db(transaction=True)` in any test that asserts on
  subscription notifications. (#63)
- **Response cache stores a `(body, status, content_type)` tuple, not a raw
  `HttpResponse`** — Deployments that introspect or inject into the response cache
  directly (e.g. custom cache backends that serialise the value) must account for
  the new tuple shape. Cookie-bearing and multipart requests are never cached. (#53)
- **Unknown `Meta` options now raise `ImproperlyConfigured`** — A previously
  silent typo (e.g. `filter_Filed`) will now surface at server startup rather than
  being ignored. This surfaces real bugs; review your `DjangoObjectType` and
  `DjangoListObjectType` subclasses for typos before upgrading. (#65)
- **`DjangoObjectType.get_queryset` is now actually invoked** — Any
  `get_queryset` override that was previously dormant (documented as active but
  never called on list/paginated/list-object fields) will now execute on every
  relevant query. **Action required**: review your `get_queryset` overrides to
  confirm they are safe to apply globally on those field types, then upgrade. (#58)
- **mypy dev dependency moved to `>=2.1,<3`** — Projects that pin mypy via the
  `django-graphex` dev extras should update their own mypy constraint accordingly.
  (#55)

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
  `django_graphex.middleware.GraphQLDirectiveMiddleware`. `DjangoGraphQLSchema` also avoids the
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
- **Query depth limiting** (`MAX_QUERY_DEPTH` / `Meta.max_depth`) and **query cost
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
