# Changelog

## Unreleased

The current checkout requires `graphql-core>=3.3.0,<3.4`; the root and
Playground locks target 3.3. This is an unreleased migration: 4.0.0 is
selected but the package metadata remains 3.1.1. Custom 3.2
`ExecutionContext` subclasses must move to the 3.3 `Executor` API; the
legacy view keyword remains an alias with explicit-argument precedence.
Custom AST builders must construct immutable AST nodes, and subscription
transports must handle 3.3 source-stream results. Synchronous queryset
execution, directive coercion and query cost behavior retain compatibility
tests. New core33 whole-stack results and explicit run/replay guidance are
separate from the frozen 3.1.0 measurements. See the
[unreleased upgrade guide](docs/UPGRADE-4.0.md) and
[current comparison](docs/why.md#current-core33-comparison). The 3.1.1
security patch and its 3.2.13 requirement remain historical facts.

## 3.1.1 — 2026-10-01

This patch raises the required GraphQL-core version to 3.2.13 while staying
below 3.3. It includes upstream parser and validation denial-of-service fixes
and correct handling of truncated string escapes.
Production publication is tag-driven.

See the [full patch notes](docs/changelog.md#311--2026-10-01) and the
[security guidance](docs/usage/security.md#runtime-parser-and-validation-hardening).
The dated 3.1.0 history and its audit traceability remain in the full changelog.
