# django-graphex 3.1.1 security patch

## Objective and authorization

Prepare a minimal security patch before the separately authorized future
GraphQL-core 3.3 migration. The user approved local implementation on 2026-10-01.
Local work-unit commits are authorized. The user subsequently authorized GitHub
issues and two chained pull requests toward 3.1.1 integration in
eamigo86/django-graphex using the eamigo86 gh session. This task delegates all
remote actions until after independent T3 verification. Merge, release tags and
publication remain unauthorized; main stays unchanged.

## Problem and scope

- The root and Playground locks still select GraphQL-core 3.2.11, before the
  parser and validation denial-of-service fixes in 3.2.12.
- Require and lock GraphQL-core 3.2.13 while retaining the upper bound below 3.3.
- Refresh the Playground's Django 6.0.6 selection to 6.0.8, preserving the tested
  Django line. Do not adopt Django 6.1 or future-dated 6.0.9.
- Exercise the upstream fixes through bounded regressions and the HTTP boundary.
- Prepare package version 3.1.1 and public documentation without deleting 3.1.0
  release history, audit traceability or published benchmark provenance.
- Do not rewrite canonical benchmark JSON or frozen historical constraints.
  Document why their recorded versions intentionally differ from the patch.
- Preserve pre-existing local files, especially the untracked .codegraph index.
- Do not build a local distribution. Do not enable receipt-driven development.

## Execution and delivery

- Branch: codex/security-3.1.1; branch point: a160d12e8be208cb5d00010f1c2819deae557089.
- Route: delegated direct for implementation and verification; no SDD artifacts.
- Trigger evidence: dependency locks, security tests, release contracts and docs
  require more than three files and two non-trivial edits.
- Strict TDD: enabled by the current user instructions. Observe RED for the
  intended cause, then minimal GREEN, then REFACTOR. Never lower coverage gates.
- Focused runner: .venv/bin/python -m pytest --no-cov.
- Full runner: .venv/bin/python -m pytest; configured branch threshold: 95.01%.
- RDD: off, observed via gentle-ai review mode status; deciding source: global.
  Use ordinary functional checks and independent verification, not native review.
- Delivery strategy: ask-on-risk, resolved to feature-branch-chain with two
  authorized PR slices: T1 commit 0706264 first, T2 release-readiness work unit
  second. T3 verification evidence belongs with the second slice. The user
  approved a size exception solely for the 883-line generated Playground lock;
  it does not waive review of authored code, tests or docs. Initial forecast was
  150-300 authored changed lines; actual T1 and T2 authored changes total 483
  (189 + 294), with generated lock content reported separately.

## Tasks

- [x] T1 — Secure dependency floor/locks and add executable security regressions.
  Route: delegated; includes bounded comment-token and validation-budget cases,
  truncated-escape errors, HTTP error responses, and secure Playground lock.
  Acceptance: RED observed on 3.2.11; GREEN on 3.2.13; root/playground keep
  GraphQL-core below 3.3 and Django on the tested line.
  Commit: 0706264 (local work unit). Review tier/outcome: high/unassessable
  in read-only assessment due untracked .codegraph inventory;
  RDD disabled/unmanaged. RED: all six new cases failed on
  GraphQL-core 3.2.11 for the intended parser, validator-budget and syntax
  causes. GREEN: six passed on 3.2.13; 85 related view/security tests passed.
  Root and Playground locks resolve 3.2.13; Playground resolves Django 6.0.8.
  Full suite: 4,349 passed, 7 skipped, 17 unrelated canonical-provenance
  failures caused by extra existing benchmark result files in this checkout
  (37 on disk versus eight tracked canonical JSON artifacts). Without that
  benchmark module: 4,345 passed, 7 skipped, 96.21% branch coverage, exceeding
  the unchanged 95.01% threshold. Quality, docstrings and docs build passed;
  docs build emitted five existing broken-anchor warnings.
- [x] T2 — Prepare 3.1.1 metadata, release contracts and public patch notes.
  Route: delegated; retain historical 3.1.0 contracts and benchmark evidence.
  Acceptance: release/documentation RED observed, then GREEN; explain security
  hardening and benchmark provenance; no accidental migration scope.
  Implementation and checks verified; the delivery-chain decision is resolved
  and the local work-unit commit closes this task. Its SHA is recorded in the
  post-commit evidence update. Review tier/outcome: high/unassessable
  in read-only assessment due untracked .codegraph inventory;
  RDD disabled/unmanaged. RED: four new release/documentation contracts failed
  on 3.1.0 metadata and missing patch notes/guidance; GREEN: 38 patch and
  historical readiness tests passed, and 93 related release/docs/security
  tests passed. Source version and installed distribution metadata are checked
  separately because no local distribution build is authorized.
- [ ] T3 — Verify the complete candidate and record release-readiness evidence.
  Route: delegated independent verification after writer checks.
  Acceptance: full suite, branch coverage >95%, patch coverage >95%, quality,
  frozen runtime audit, documentation, Playground and diff checks pass or any
  unavailable/failed checks are explicitly reported. No claim of hosted CI or
  publication without actually running them.
  Commit: pending (verification evidence). Review tier/outcome: pending;
  RDD disabled/unmanaged.

## Verification and rollback

Run focused pytest commands with --no-cov; never use -o addopts="" or weaken
--cov-fail-under. Run the full suite with its existing coverage configuration.
Use the existing quality, security and docs commands after inspecting tox.ini.
Run Playground tests with --no-migrations. Assess the committed diff read-only
and use an independent verifier for high/unassessable risk. Record exact commands,
results, changed-line coverage, unavailable environments and any known failures.

Rollback boundary: dependency specification, generated root/Playground locks,
new security regressions, patch metadata/contracts, patch docs and this task
document as coherent units. Preserve unrelated source and benchmark artifacts.

## Progress and next step

T1 dependency hardening and bounded regressions are implemented. The local
Playground lock was previously ignored by its own .gitignore; it is deliberately
included in the T1 work unit so a fresh Playground resolves the tested patches.
The pre-existing extra benchmark files remain untouched. T2 prepared 3.1.1 as
Unreleased while retaining the dated 3.1.0 history and benchmark freeze. The
user resolved delivery to two feature-branch-chained PRs, with a size exception
only for the generated Playground lock. Next: T3 independent release-readiness
verification in a clean tracked snapshot before any parent-routed remote action.

### T1 verification evidence

- RED: `.venv/bin/python -m pytest tests/test_graphql_core_security_patch.py --no-cov -q`
  on installed GraphQL-core 3.2.11: six failed for intended missing protections.
- GREEN: the same command on 3.2.13: six passed. Related command with
  `tests/test_view_base.py`, `tests/test_views_branches.py` and
  `tests/test_views_security_hardening.py`: 85 passed.
- Full `.venv/bin/python -m pytest -q`: 17 canonical-provenance failures,
  4,349 passed and 7 skipped. Isolating that pre-existing benchmark module with
  `--ignore=tests/benchmarks/test_canonical_provenance.py`: 4,345 passed,
  7 skipped and 96.21% branch coverage against the unchanged 95.01% gate.
- `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`,
  `.venv/bin/mypy django_graphex`, the repository docstring checker,
  `.venv/bin/zensical build --clean -f zensical.yml` and `git diff --check`
  passed. The docs builder reported five unrelated existing anchor warnings.
- Runtime harness: `test_truncated_escape_returns_json_http_400` confirmed
  a JSON 400 syntax error rather than an internal error. Rollback boundary:
  commit 0706264, covering the floor, both locks, regression tests and current
  requirement docs without touching frozen benchmark files.

### T2 verification evidence

- RED: `.venv/bin/python -m pytest tests/test_release_readiness_311.py --no-cov -q`
  failed four intended metadata, patch-note, security-guide and provenance
  contracts before implementation. GREEN: four passed after implementation;
  the paired 3.1.0 historical contract suite passed 34 tests.
- Focused release/docs/security command over seven modules: 93 passed.
  Version and packaging contracts after source/installed separation: 44 passed.
- Full `.venv/bin/python -m pytest -q`: 4,353 passed, 7 skipped, 17 existing
  canonical-provenance failures from extra ignored benchmark files. With only
  that module excluded, 4,349 passed, 7 skipped and 96.21% branch coverage;
  the configured 95.01% gate was unchanged. This is diagnostic, not a claim
  that the full suite passed. T3 will run all tests in a clean tracked snapshot.
- Ruff format/lint, mypy, docstring checker and Zensical build passed. Zensical
  still reported five unrelated broken-anchor warnings. No local package build
  or remote release action was run.
- The newly tracked Playground lock makes `make install` reproduce the tested
  local editable dependency closure: GraphQL-core 3.2.13 and Django 6.0.8.
  Its prior ignore rule allowed a fresh clone to resolve later compatible
  versions instead. It adds 883 generated lock lines, outside authored count.
- Engram mirror pending: the host currently provides no authoritative
  registered session identity, so no agent-attributed memory mutation is safe.
