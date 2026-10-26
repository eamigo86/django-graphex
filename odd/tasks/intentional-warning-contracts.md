# Assert intentional warnings without hiding diagnostics

Status: IN PROGRESS. Repository locator: odd/tasks/intentional-warning-contracts.md.

## Objective and authorized scope

Review the 18 warnings from the latest root run and correct the necessary test
contracts without changing public behavior or suppressing diagnostics.

- User authorization: 2026-10-26, strict TDD, documentation, coverage above 95%.
- Ask before any incompatible change; none is proposed.
- No PR, push, tags, publishing, benchmark regeneration, dependency installation,
  downloads, ambient services, global warning filters or relaxed assertions.
- Preserve all production files, examples, Playground, benchmark artifacts,
  root coverage outputs, audit reports and unrelated changes.

## Verified inventory

Starting branch: codex/audit-400-remediation. Starting commit:
0ab29a0bb59c2f2ce2892673860c1af4bb3e1e90.
Evidence: /private/tmp/dgx-rux-2-1vbhrgan/full/full-suite.log.

| Intentional diagnostic | Default summary entries | Contract |
| --- | ---: | --- |
| Unsupported input annotations | 11 | Retain GraphQL String fallback and its UserWarning. |
| Private fields without authentication middleware | 1 | Retain the schema security RuntimeWarning. |
| Pydantic reserved model field names | 6 | Retain UserWarning and supported field/method behavior. |

Total: 18 default-summary entries across 11 test definitions. Explicit capture
uses an always filter locally: four Pydantic parameter cases emit twice each,
plus two emissions in the original-methods case. That is 10 raw Pydantic
emissions and 22 raw diagnostics in total, not a change in runtime behavior.
No production defect or resource leak was identified in this bounded map.
Existing assertions prove fallback and field behavior but did not consistently
verify warning category and message.

## Workflow and checks

- Implementation route: delegated direct. Six meaningful test files and their
  preparation trigger delegation; one writer, then an independent verifier.
- Strict TDD is enabled by user instruction and AGENTS.md. RED: run the affected
  existing cases with warnings treated as errors before edits. GREEN: assert
  only each intentional diagnostic with pytest.warns(category, match=...),
  preserving every existing behavior assertion. Unexpected warnings must still
  fail strict focal execution; no blanket capture, ignore or config changes.
- Runner: /private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python.
- Assert in actual test processes Python 3.12.11, Django 6.0.8, graphql module
  and distribution 3.3.0, and current-checkout library origin. Root .venv is not
  the supported environment. Use -B and external-only caches/logs/databases.
- Focused tests use --no-cov; the warning-contract focal run also uses -W error.
  Complete root verification retains configured addopts, branch threshold
  95.01, includes/exclusions and warning policy, with only external HTML/XML
  output destinations. Reconcile PID-owned raw data with XML before cleanup.
- Applicable checks: focal strict-warning cases, related tests, full root,
  Playground, Ruff lint/format, docstrings, strict docs build, diff checks.
- RDD is globally OFF; do not start review, consent, or enable it. Ordinary
  functional and independent verification remain required.
  Read-only risk assessment was high/unassessable because of undeclared
  untracked reports; independent verification is required, not a review start.
- Forecast: 180-300 authored changed lines including this tracker. Delivery
  strategy: ask-on-risk; local work-unit commits only, no PR planned. Record
  actual commit identities/counts at closure; do not code-golf for line counts.
- Technical artifacts are English. Public docstrings: complete Google style,
  type hints without repeated types, no backticks.

## Tasks

- [x] WN-1 — Strengthen intentional-warning contracts and document them.
  Route: delegated writer; multi-file tests, preparation and verification.
  Capture strict focal RED before source edits; add category/message assertions
  in the four compiler-related files, schema registry test and reserved-fields
  test. Preserve exact runtime fallback, security and Pydantic diagnostics.
  Test both standard and strict-warning execution; verify counts/messages where
  multiple warnings occur. Document this testing convention in an existing
  contributor/testing guide and mirror the test-quality note in both changelogs.
  Run related checks and full root with coverage >95.01%. Retain all failures.
  Rollback boundary: only warning assertions and their documentation; no runtime
  code, warning filters, schema or benchmark changes. Save one behavior-focused
  Conventional Commit. Evidence: /private/tmp/dgx-warn-wn1-final-7HiPh8;
  original strict RED: /private/tmp/dgx-warn-wn1-MyDlXM/red.log (14 failing
  parametrized nodes, 187 passing). Final strict and standard focal runs each
  pass 201 tests. Missing-warning and wrong-message negative controls fail as
  required. Final root: 7,784 passed, 6 existing skips, 4,064 subtests, no
  warning summary. Branches 5,087/5,324 = 95.5485%; combined 18,516/18,974 =
  97.5862%, with raw/XML agreement. Ruff lint/format, canonical strict
  docstrings, strict docs build and diff checks passed. All 267 prior protected
  artifacts and production/warning-policy bytes remain unchanged.
  Documentation: docs/contributing.md plus both changelog mirrors. Initial
  full proof was retained separately before final exact-category tightening;
  the final normalized candidate received a fresh full run. Implementation
  commit is recorded in the closure metadata after this unit is saved.
- [ ] WN-2 — Independently verify and close.
  Route: delegated verifier, then parent mechanical tracking closure.
  Verify intentional diagnostics remain emitted, unexpected warnings are not
  hidden, and public behavior/production bytes are unchanged. Independently run
  strict focal and configured full root, reconcile coverage >95.01%, check
  Playground and documentation/quality, and verify protected artifact hashes.
  Explicitly report remaining warnings, skips, unavailable checks and limits.
  Save tracking-only closure in a local Conventional Commit.
  Rollback boundary: tracking metadata only. Evidence/commit: pending.

## Progress and next step

The 18 displayed entries and 22 raw emissions are reconciled. Only test warning
contracts and their documentation changed; existing fallback, schema, mutation
and field-method checks remain. No global filters, suppression, public API or
dependency change was necessary. Nine owned files total 160 authored changed
lines, plus this tracker; delivery remains below 400 lines. Next: save the WN-1
work unit locally, then independently verify WN-2 against committed test bytes.
