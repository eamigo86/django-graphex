# SPEC — v2 modernization roadmap (Poetry→UV, filtering, code quality, docstrings, docs)

**Status:** APPROVED — executing all phases on `pre-v2`.
**Date:** 2026-06-07
**Scope:** packaging, `graphene_django_extras/*`, tests, docs, CI.

Phases (each verified with full suite + flake8 + `mkdocs --strict`):

- **0** — Version fix: unify `__init__.VERSION` with `pyproject` (→ `2.0.0`).
- **1** — Poetry → UV: PEP 621 `[project]`, `[dependency-groups]`,
  `[project.optional-dependencies]`, hatchling build backend; Makefile/tox/CI to
  `uv`; drop `poetry.lock`, regenerate `uv.lock`.
- **2** — Filtering: memoize filterset classes (avoid duplicate filter input
  types / rebuilds); tidy the related-field resolver.
- **3** — Mechanical modernization: remove `six`, `super(Cls, self)` → `super()`,
  `x.__len__()`/`e.__str__()` → `len()`/`str()`, `%`/`.format` via tooling.
- **4** — f-strings (flynt) for remaining `.format`.
- **5** — Docstrings → Google style + type hints (pydocstyle convention=google),
  module by module.
- **6** — Docs freshness: installation extras, READMEs, changelog v2 + migration.

Then: review GitHub Actions and update for the new test suites / packaging.
