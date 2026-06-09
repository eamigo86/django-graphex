# SPEC — Replace black + isort + flake8 with ruff

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** `pyproject.toml`, `tox.ini`, `Makefile`, CI, badges, docs.
**Date:** 2026-06-07
**Origin:** after Poetry→uv, modernize the formatter/linter to ruff (the
industry standard alongside uv).

---

## 1. Goal

Consolidate **black** (formatter), **isort** (imports) and **flake8**
(+ flake8-docstrings, flake8-bugbear, pyflakes) into **ruff** (`ruff format` +
`ruff check`). Keep **mypy** (ruff is not a type checker).

## 2. Design

### 2.1 `pyproject.toml`
- Dev group: drop `black`, `isort`, `flake8`, `flake8-docstrings`,
  `flake8-bugbear`, `pyflakes`; add `ruff`.
- Remove `[tool.black]`, `[tool.isort]`, `[tool.flake8]`.
- Add:
  ```toml
  [tool.ruff]
  line-length = 88
  target-version = "py312"

  [tool.ruff.lint]
  # Mirror the previous flake8 active rule set (E,W,F + docstrings D) plus
  # import sorting (I, replacing isort).
  select = ["E", "W", "F", "D", "I"]
  ignore = ["E203", "E501"]   # handled by the formatter
  [tool.ruff.lint.pydocstyle]
  convention = "google"
  [tool.ruff.lint.per-file-ignores]
  "__init__.py" = ["F401"]
  "tests/*" = ["D"]
  "examples/*" = ["D"]
  ```
  (`N`/`C` were inert under flake8 — no `pep8-naming`/complexity configured — so
  they are not enabled, keeping the migration behavior-equivalent. `ruff format`
  is black-compatible at line-length 88.)

### 2.2 `tox.ini`
`[testenv:quality]` deps → `ruff`, `mypy`, `types-python-dateutil`; commands:
```
ruff format --check .
ruff check .
mypy graphene_django_extras
```
Remove the `[flake8]` section (ruff reads pyproject).

### 2.3 `Makefile`
- `format`: `uv run ruff format .` then `uv run ruff check --fix .`
- `lint`: `uv run ruff check .`
- keep `type-check` (mypy).

### 2.4 CI
The `lint-and-security` job runs `tox -e quality`, so it picks up ruff
automatically — verify and keep the rest of the workflow unchanged.

### 2.5 Badge + docs
- Badge: `code style: black` → the official Ruff badge
  (`img.shields.io/endpoint?url=…/astral-sh/ruff/.../badge/v2.json`) in
  `README.md` and `docs/index.md`.
- `docs/contributing.md`: black/isort/flake8 → ruff.
- `docs/changelog.md` 2.0.0 tooling note: mention ruff.

### 2.6 Apply
Run `ruff format .` and `ruff check --fix .` over the repo, fix residual findings,
keep the full test suite green.

## 3. Acceptance Criteria
- **AC1** `ruff format --check .` and `ruff check .` are clean.
- **AC2** No black/isort/flake8 references remain in pyproject/tox/Makefile/CI
  (mypy stays). Full suite green; `mkdocs --strict` green.
- **AC3** `tox -e quality` runs ruff + mypy and passes.

## 4. Definition of Done
1. Config + tooling + badge + docs per §2. 2. §3 ACs green. 3. Committed and
pushed to `pre-v2`.
