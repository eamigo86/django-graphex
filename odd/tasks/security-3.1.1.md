# django-graphex 3.1.1 security patch

## Objective and authorization

Prepare a minimal security patch before the separately authorized future
GraphQL-core 3.3 migration. The user approved local implementation on 2026-10-01.
Local work-unit commits are authorized. Remote issues, pull requests, pushes,
merges, release tags and publication require separate user authorization.

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
- Delivery strategy: ask-on-risk. Forecast: 150-300 authored changed lines;
  generated lock changes excluded from this forecast but reported in total diff.
  Existing PR policy remains applicable if delivery is subsequently authorized.

## Tasks

- [x] T1 — Secure dependency floor/locks and add executable security regressions.
  Route: delegated; includes bounded comment-token and validation-budget cases,
  truncated-escape errors, HTTP error responses, and secure Playground lock.
  Acceptance: RED observed on 3.2.11; GREEN on 3.2.13; root/playground keep
  GraphQL-core below 3.3 and Django on the tested line.
  Commit: pending (local work unit). Review tier/outcome: pending read-only
  assessment; RDD disabled/unmanaged. RED: all six new cases failed on
  GraphQL-core 3.2.11 for the intended parser, validator-budget and syntax
  causes. GREEN: six passed on 3.2.13; 85 related view/security tests passed.
  Root and Playground locks resolve 3.2.13; Playground resolves Django 6.0.8.
  Full suite: 4,349 passed, 7 skipped, 17 unrelated canonical-provenance
  failures caused by extra existing benchmark result files in this checkout
  (37 on disk versus eight tracked canonical JSON artifacts). Without that
  benchmark module: 4,345 passed, 7 skipped, 96.21% branch coverage, exceeding
  the unchanged 95.01% threshold. Quality, docstrings and docs build passed;
  docs build emitted five existing broken-anchor warnings.
- [ ] T2 — Prepare 3.1.1 metadata, release contracts and public patch notes.
  Route: delegated; retain historical 3.1.0 contracts and benchmark evidence.
  Acceptance: release/documentation RED observed, then GREEN; explain security
  hardening and benchmark provenance; no accidental migration scope.
  Commit: pending. Review tier/outcome: pending; RDD disabled/unmanaged.
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
The pre-existing extra benchmark files remain untouched. Next: T2 patch metadata,
release contracts and notes, then T3 independent release-readiness verification.
