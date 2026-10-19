# Changelog

## Unreleased

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

- Add a local, evidence-bounded disposition of the 100 original audit claims
  in [the 4.0.0 audit report](docs/audit-4.0.0.md). It separates scoped fixes,
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

- Match finite typed Decimal subscription `exact` filters by numeric value
  against the event-time JSON-safe snapshot. A filter value of `1.0` now
  matches a full-payload `"1.00"` on create and delete without a row lookup.
  Valid high-precision model values also match without an arbitrary 256-character
  cutoff. String-valued server scopes, malformed/non-finite values, other scalar
  filters, and the wire payload retain their existing behavior; this does
  not resolve DateTime snapshot precision.

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

- Complete Google-style docstrings in tracked regression tests for metadata
  errors, schema isolation, source properties, optimizer plans, and permission
  caching. This is a test-documentation change only; library behavior is
  unchanged. Local ignored profiling scripts are outside the clean checkout.

- Warn when unsupported hand-authored input annotations such as `Literal`,
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

- Fix order-dependent registry tests by restoring the cached default schema
  pair after temporary test scopes, including nested and exceptional exits.
  This changes only test isolation; library behavior and public APIs are
  unchanged.

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

- Improve date-part test portability by removing exact runtime-version,
  checkout-path, and working-directory assertions from the behavioral test.
  A separate regression contract keeps those local proof checks external;
  this does not change date-part filtering or expand the supported version
  range.

- Preserve completed results when a valid GraphQL batch reaches an operation-
  level HTTP 400 request error. Return an HTTP 400 array ending with that
  error, stop later operations, and leave prior successful mutations committed.
  Previously the error-only object hid earlier results. Malformed batch
  bodies and non-400 transport errors keep their existing envelopes;
  `ATOMIC_MUTATIONS` remains per operation.

- Clarify that `ALLOW_INTROSPECTION=False` blocks `__schema` and `__type` only
  when `DisableIntrospectionMiddleware` is installed in GraphQL `MIDDLEWARE`.
  The default middleware chain is empty, so deployments relying on the setting
  alone should explicitly install the middleware. This is a documentation
  correction; the runtime defaults and introspection behavior are unchanged.

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

- Replace unexpected resolver-exception details on built-in HTTP views when
  `DEBUG=False` with safe `DATA_ACCESS_ERROR` or `INTERNAL_SERVER_ERROR`
  diagnostics and an opaque `errorId` correlated with restricted server logs.
  Clients must stop relying on raw exception text or custom extensions from
  these failures. Deliberate `GraphQLError`, validation errors, existing
  generated-mutation errors, `DEBUG=True`, and WebSocket/SSE formatting are
  unchanged; custom `format_error` overrides remain application-owned.

- Frame the default response-cache body and GET components before SHA-256
  hashing. Two different selected GET operations can no longer share a cache
  entry through ambiguous concatenation within one identity. Existing cached
  responses cold-miss and expire normally; the 64-hex digest shape and custom
  `fetch_cache_key(request)` override contract remain unchanged.

- Reject a selected GraphQL operation before resolution when its real,
  GraphQL-coerced request variables or defaults put it over `MAX_QUERY_COST`,
  including document-validation cache hits. A variable page size that previously
  passed the static fallback estimate may now return HTTP 400 / `QUERY_TOO_COMPLEX`.
  Conservative static validation remains: a cheap variable cannot undo an
  earlier fallback-based rejection. `MAX_PAGE_SIZE` is still optional, though
  recommended for unbounded lists; the public cost model/API is unchanged.
  A mutation refused before resolver execution does not invalidate a warmed
  response cache; an earlier executed mutation in a non-atomic batch still does.

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

- Hide table, column, and constraint details from unclassified Django
  `IntegrityError` failures in generated create/update/delete GraphQL fields,
  including nested writes. Clients now receive the fixed top-level message
  `A database constraint prevented this operation.` instead of raw database
  text; the field remains `null`, with its GraphQL path and normal HTTP shape.
  Nested and atomic sibling rollback remain intact. Mapped unique/FK field
  errors stay structured, direct backend exceptions stay unchanged, and no
  general constraint validation or upsert is added.

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

- Replace Django collector details in generated delete `PROTECT`/`RESTRICT`
  failures with a generic GraphQL execution error. Both mutation frontends keep
  the existing field-null, HTTP and atomic rollback behavior; blocked deletes
  do not become `ok: false` payloads. Clients relying on the old collector
  message must migrate to the generic error and field path.

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

- Reject bare-string and unknown `DjangoObjectType.Meta.only_fields` or
  `exclude_fields` selectors at class definition, before registry mutation.
  Previously a typo could leave a sensitive model field published. Valid model,
  reverse-relation, private, and declared custom field names remain accepted;
  declared custom fields still compile independently of model projection.

- Reject a second distinct public `DjangoObjectType` for the same exact Django
  model and `Registry` with `ImproperlyConfigured`, rather than silently
  replacing the type used by nested relations. Re-registering the same class
  remains idempotent; separate registries, input/mutation registrations, and
  non-registering internal forks are unchanged. Existing public/admin schema
  variants over one model must use separate registries.

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

- Make the converter integration test register its User relation target in a
  test-local, allowlisted registry. The test now passes in isolation without
  weakening its relation assertion or changing production relation behavior.
- Previously restored populated auto-derived `DecimalField` output under
  graphql-core 3.3 through the existing `Float` field; the new default above
  supersedes that interim Float output without changing Decimal input parsing.
- Bound optimizer planning for valid repeated-fragment graphs to distinct
  model, type, and relation-path contexts. Existing projections, prefetches,
  annotation promotion, ordered plan/alias precedence, GraphQL results, and SQL
  query counts remain unchanged.
- Reject cyclic named-fragment graphs before cost/depth expansion. Direct
  `analyze_cost()` now raises `GraphQLError` for a cyclic document rather than
  returning a truncated cost, including cycles outside the selected operation;
  validate first or catch the error. Acyclic costs and depth verdicts are unchanged.
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
[current comparison](docs/why.md#current-core33-comparison). The dated 3.1.1 security patch and its
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

This patch raises the required GraphQL-core version to 3.2.13 while staying
below 3.3. It includes upstream parser and validation denial-of-service fixes
and correct handling of truncated string escapes.
Production publication is tag-driven.

See the [full patch notes](docs/changelog.md#311--2026-10-01) and the
[security guidance](docs/usage/security.md#runtime-parser-and-validation-hardening).
The dated 3.1.0 history and its audit traceability remain in the full changelog.
