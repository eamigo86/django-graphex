# Changelog

## Unreleased

## 4.0.0 — 2026-10-03

**Release prepared, not published.** The package and both editable project
locks now name 4.0.0, with `graphql-core>=3.3.0,<3.4`. A tag, built wheel,
hosted release-artifact verification, and publication remain separate gates.
Custom 3.2 `ExecutionContext` subclasses must move to the 3.3 `Executor` API; the
legacy view keyword remains an alias with explicit-argument precedence.
Custom AST builders must construct immutable AST nodes, and subscription
transports must handle the 3.3 source stream results. Synchronous queryset
execution, directive coercion and query cost behavior retain compatibility
tests. The new official core33 SQLite comparison is in the immutable
`core33-4.0.0-01f82ab94c86a5f35918dec4ba51deee02a58ac9` series,
measured 4.0.0 source at commit
`01f82ab94c86a5f35918dec4ba51deee02a58ac9` and installed later at
`d4ef486af0e283c49a1c22a5c8fee92d51e8b42c`. Its GraphEx/Ariadne
create-comment p50 ratios are 0.57× and 0.59× for 50,000 and 100,000
comments, respectively; the GraphEx direct-write check retains four SQL
statements versus Ariadne's one. These are three-run per-statistic medians of
pinned SQLite whole stacks under accepted background load, not paired
cross-session speedups, PostgreSQL timings or a published wheel. The earlier
3.1.1-source core33 and 3.1.0 artifacts remain historical. See the
[current comparison](docs/why.md#current-core33-comparison). The dated 3.1.1
security patch and its GraphQL-core 3.2.13 requirement remain historical facts.

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
error. The official comparison above predates this correction and retains its
original source attribution; a final-source comparison is pending.

## 3.1.1 — 2026-10-01

This patch raises the required GraphQL-core version to 3.2.13 while staying
below 3.3. It includes upstream parser and validation denial-of-service fixes
and correct handling of truncated string escapes.
Production publication is tag-driven.

See the [full patch notes](docs/changelog.md#311--2026-10-01) and the
[security guidance](docs/usage/security.md#runtime-parser-and-validation-hardening).
The dated 3.1.0 history and its audit traceability remain in the full changelog.
