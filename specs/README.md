# Design specs (SDD)

Repo-internal **Spec-Driven Development** documents: the design contract is
written and approved here *before* implementation. These files are intentionally
kept **out of the published documentation site** (`mkdocs`/GitHub Pages) — they
are for contributors, not end users. End-user docs live under `docs/`.

| Spec | Subject |
|------|---------|
| [`subscriptions-spec.md`](subscriptions-spec.md) | GraphQL subscriptions as the optional `graphene-django-extras[subscriptions]` extra (Channels 4). |
| [`pagination-pageinfo-spec.md`](pagination-pageinfo-spec.md) | Opt-in `pageInfo` for `CursorGraphqlPagination`. |
