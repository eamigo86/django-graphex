# Synchronize documented examples with the 4.1 implementation

## Objective and authority

Correct the five findings from the component synchronization review and add
tests that execute the documented examples, not handwritten substitutes.
Authorized on 2026-10-25. Base: `35e7a801500a01c5be50106da78c5007dd74d59a`,
branch `codex/audit-400-remediation`.

No PR, push, tag, publication, benchmark regeneration, package build, dependency
installation, or new service is authorized. Ask before an incompatible change;
none is expected because this work corrects docs/tests, not production behavior.
Preserve user-owned audit reports, root coverage outputs, and benchmark artifacts.

## Confirmed problems

1. Playground README and guide request `results(first: 2/3)` but leave `pageInfo`
   at its default size of 10. The root example skips seven rows on continuation.
2. Anonymous subscription instructions create a default draft, then promise a
   published-post event. Adding `status: PUBLISHED` makes that walkthrough work.
3. The numeric-directive API reference omits supported Decimal/BigInt behavior.
4. The upgrade guide lacks the reverse-FK `to_field` filter/count correction note
   already present in the changelog.
5. A cursor-test comment incorrectly rules out physically stored finer SQLite
   Decimal values; current assertions correctly support representable ties.

Evidence: observation 25765 and
`/private/tmp/graphex-sync-review-20261025-jffi50kt/`.

## Tasks and routing

- [x] **T1 — Execute and correct both Playground walkthroughs.**
  Delegated direct: more than three mapped files and multiple non-trivial
  tests/docs. Extract literal fenced operations under the existing headings in
  README and guide. Execute root/nested cursor pages and AST-derived
  continuations; require exact rows and matching cursor metadata. Execute the
  documented subscription/mutation as an anonymous client over HTTP/WebSocket.
  Observe RED from page-size mismatch and draft suppression before editing docs.
  Fix both copies, retain anonymous-draft suppression tests, and update mirrored
  changelogs. Keep Channels-only tests in the Playground transport module.
- [x] **T2 — Complete API/migration guidance and correct the stale comment.**
  Delegated direct, same single writer after T1: execute the numeric reference's
  literal operation with exact Decimal/BigInt outputs, and literal upgrade
  operations against existing crossed-PK/target fixtures. Observe the documented
  omission failures before adding the guidance. Explain non-PK target changes
  without implying ordinary FK-to-PK configurations changed. Correct only the
  inaccurate cursor comment, retaining its assertions and SQLite tie regressions.
- [ ] **T3 — Independently verify, commit evidence, and close.**
  Delegated verification; parent structural readback and one command spot check.
  Verify example extraction is literal, continuations retain selections/limits,
  event assertions prove delivery, and new root tests do not require Channels or
  the excluded example tree. Run root and standalone Playground suites,
  applicable quality/docs/coverage checks, preserve all failures and skipped
  checks, and record local Conventional work-unit commits and full mirror.

## TDD and acceptance

Strict TDD is enabled by current user request and project instructions:
observed RED, minimal GREEN, then REFACTOR; do not invent runtime failures for
missing documentation. The source implementation remains unchanged. Existing
native schema/fixtures are preferred to new models or a generic test framework.
Public docstrings use complete Google style, annotations, no repeated types and
no backticks. Artifacts remain English; conversation remains Spanish.

Supported runner: existing graphql-core 3.3.0 interpreter invoking pytest with
`-B`; verify module and distribution versions and checkout imports in the same
process as final suite execution. Root `.venv` is not the credited interpreter.

- Playground focal: `tests/test_readme_examples.py` and
  `tests/test_subscription_transports_e2e.py`, with `--no-cov --no-migrations`
  and an external settings wrapper overriding only database/media/static paths.
- Root focal: new documentation examples, exact-numeric directive, to-field
  filter/window, cursor parity, and packaging-input tests with `--no-cov`.
- Final: both complete suites; configured coverage unchanged, pure branch and
  combined coverage each **at least 95.01%**; applicable diff gate. Report N/A,
  not fabricated 100%, if no executable production lines change.
- Ruff format/check, mypy, Bandit, standard/strict docstrings, docs build,
  changelog mirror/link checks, and `git diff --check`.
- Do not clear configured addopts, weaken assertions, add skips/exclusions, or
  reduce thresholds. Keep new root tests independent of Channels and examples.
- All temporary DBs, cache, media, JUnit, logs, raw coverage and HTML/XML outputs
  stay outside the checkout. Use the proven full-run isolation wrapper/config
  copy and retain raw PID-owned coverage before exit cleanup; never accumulate
  extra report flags while leaving root destinations active.

## Delivery and rollback

Two coherent work units are forecast at approximately 320–420 authored lines
excluding this tracker; retain useful tests/docs if more are required. Current
delivery is local only. Future PR strategy is `ask-on-risk`, deferred while PRs
are explicitly forbidden. No artificial compression or PR chain creation.

Each implementation task closes with a Conventional work-unit commit containing
its tests/docs; no AI attribution. RDD is **off (global)**, verified at start;
record disabled/unmanaged, do not enable native review.

Rollback boundaries: T1 restores only the copied Playground examples/tests and
its changelog note; T2 restores only numeric/to-field guidance/tests and the
comment. Neither rollback changes library semantics or benchmark measurements.

## Progress and evidence

- Tracked tree/index clean at start; existing audit reports and `.codegraph/`
  remain untracked and must not be staged.
- Baseline: `/private/tmp/graphex-sync-fix-20261025-judoi459/before.json`.
- T1: both literal Markdown copies now use matching page sizes for cursor
  metadata and explicitly publish the anonymous-subscription example's post.
  The new local extraction helper is included in the work-unit inventory.
- T1 RED: four semantic failures before doc edits; GREEN: four new cases and
  **98 complete Playground tests passed**. An initial external harness error
  was corrected before the valid RED run and retained in the logs.
- Independent T1: **98 passed, zero skipped**; executing the four current tests
  against external copies of the original docs produced all four expected
  failures. Root/nested continuation and actual anonymous HTTP-to-WS delivery
  are verified; draft suppression is unchanged. Parent read back the docs/helper
  diff and reran the whitespace check.
- T1 Ruff format/check, mypy, configured standard and canonical strict
  docstrings, changelog mirror and whitespace gates passed. An extra unconfigured
  broad standard scan reports pre-existing DOC005 at
  `integration/live_redis/test_sse_live_redis.py:326,541`; that file is unchanged
  and no required gate failed. It was not expanded into this authorized scope.
- T1 evidence: `writer/t1/` and `verification/t1/report.md` under the baseline
  evidence directory; all 98 protected files unchanged.
- T1 local commit: `f544eed` (tests/docs/helper and initial tracker),
  **457 additions + 7 deletions**, including 129 tracker lines; 335 authored
  source/test/public-doc changed lines. Rollback is this work unit alone.
  Risk assessment was unassessable/high because of the existing untracked
  inventory. RDD remains disabled/unmanaged; independent verification provided
  the additional functional check, with no native review started.
- T2: numeric guidance now includes exact Decimal/BigInt wire examples;
  upgrade guidance explains non-PK targets and demonstrates reverse filters and
  nested counts; the inaccurate SQLite comment is corrected without changing
  cursor assertions. Mirrored changelog additions remain under 4.1 Unreleased.
- T2 RED: three missing-documentation failures before doc edits, not runtime
  failures. Initial GREEN had 251 related tests. Independent readback found a
  richer fixture masking an incomplete Python model snippet (`name` missing).
  A new literal Python/GraphQL AST contract first failed on the missing field;
  adding the field resolved it. Initial quality DOC002 and the partial report
  are retained, not hidden or treated as proof of a source implementation bug.
- Corrected T2 independent and writer checks: **252 related tests passed**;
  all four new root documentation tests also pass with Channels/Daphne imports
  prohibited. Existing Float example and cursor assertions remain valid.
  Parent reran the four root documentation tests: **4 passed**.
- T2 Ruff format/check, mypy, configured standard/strict docstrings, changelog
  mirror and whitespace checks passed. All 98 protected files remain unchanged.
  Evidence: `writer/t2/`, `verification/t2/report-initial.md`,
  `verification/t2/report-corrected.md` and `parent-spot-final.log`.
- T2 local commit: being recorded with its docs/tests and this evidence. No
  production implementation, API, defaults or benchmark artifacts changed.
- T3 final root coverage, whole-Playground validation and docs build: pending.
- Next: record T2 commit identity, then independently verify the frozen final
  candidate. Keep all source/tests/docs bytes unchanged during final checks.
