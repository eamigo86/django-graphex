# Changelog

## Unreleased

Current source raises the runtime GraphQL-core floor to
`graphql-core>=3.3.0,<3.4`. The root and Playground locks target the 3.3
line. This is an in-progress migration, not a published package release;
the package version and release date remain undecided. Custom execution
backends must move from 3.2 `ExecutionContext` subclasses to the 3.3
`Executor` API; renaming the view keyword alone is not sufficient. The
3.1.1 security patch and its 3.2.13 requirement remain historical facts.

## 3.1.1 — 2026-10-01

This patch raises the required GraphQL-core version to 3.2.13 while staying
below 3.3. It includes upstream parser and validation denial-of-service fixes
and correct handling of truncated string escapes.
Production publication is tag-driven.

See the [full patch notes](docs/changelog.md#311--2026-10-01) and the
[security guidance](docs/usage/security.md#runtime-parser-and-validation-hardening).
The dated 3.1.0 history and its audit traceability remain in the full changelog.
