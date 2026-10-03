# Changelog

## Unreleased

## 4.0.0 — 2026-10-03

**Release prepared, not published.** The package and both editable project
locks now name 4.0.0, with `graphql-core>=3.3.0,<3.4`. A tag, built wheel,
hosted release-artifact verification, and publication remain separate gates.
Custom 3.2
`ExecutionContext` subclasses must move to the 3.3 `Executor` API; the
legacy view keyword remains an alias with explicit-argument precedence.
Custom AST builders must construct immutable AST nodes, and subscription
transports must handle the 3.3 source stream results. Synchronous queryset
execution, directive coercion and query cost behavior retain compatibility
tests. New core33 whole-stack results and explicit run/replay guidance are
separate from the frozen 3.1.0 measurements. Their measured django-graphex
source was still 3.1.1; no 4.0.0 benchmark was run. See the
[4.0 upgrade guide](docs/UPGRADE-4.0.md) and
[current comparison](docs/why.md#current-core33-comparison). The dated 3.1.1
security patch and its GraphQL-core 3.2.13 requirement remain historical facts.

SQLite generic mutations now validate only their directly saved FK rows
(including concrete inheritance parents) and updated M2M links after the
write, inside the rollback savepoint. This avoids
the table-wide deferred-FK scan that grew with unrelated rows, while retaining
immediate structured errors for the mutation's own invalid relations. Earlier
unrelated deferred violations remain the outer transaction's responsibility
and still prevent commit if unresolved. PostgreSQL's existing check is unchanged.
The frozen core33 results predate this change and are not new 4.0.0 timings.

## 3.1.1 — 2026-10-01

This patch raises the required GraphQL-core version to 3.2.13 while staying
below 3.3. It includes upstream parser and validation denial-of-service fixes
and correct handling of truncated string escapes.
Production publication is tag-driven.

See the [full patch notes](docs/changelog.md#311--2026-10-01) and the
[security guidance](docs/usage/security.md#runtime-parser-and-validation-hardening).
The dated 3.1.0 history and its audit traceability remain in the full changelog.
