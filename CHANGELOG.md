# Changelog

## Unreleased

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
