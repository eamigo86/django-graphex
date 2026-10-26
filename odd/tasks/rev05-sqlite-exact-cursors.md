# REV-05: preserve exact finer Decimal cursor comparisons on SQLite

## Objective and authority

Fix the SQLite row omission confirmed after the 4.1 audit, preserving the
approved exact-comparison contract. The user authorized this correction and
the related stale documentation updates on 2026-10-25. No PR, push, tag,
publication, dependency installation, package build, or service setup is
authorized. Ask before any incompatible change.

Base: `e7ad3f4a673433a843fd06076393f026fb9f3a28` on
`codex/audit-400-remediation`. Keep user-owned audit reports, `.codegraph/`,
root `coverage.xml`, and existing `htmlcov/` outputs unchanged.

## Problem and accepted approach

SQLite does not enforce a DecimalField's declared scale: storing `1.075` in a
two-place field leaves the physical value finer than the declaration. Snapping
a cursor at `1.074` upward to `1.08` then omits that row. Removing snapping alone
would restore the earlier `1e-999` underflow/false-PK-tie bug.

Only for finer-than-scale Decimal cursors on the queryset's SQLite database,
use adjacent representable bounds from the union of binary64 and signed int64.
Bind native numeric expressions without casting the column. Retain PK ties only
for exactly representable boundaries, while still validating every supplied PK.
Leave aligned cursors, other backends, and exact in-memory comparisons unchanged.
This does not promise universal parity between physical SQLite values and
Django's already-quantized Decimal objects.

Read-only design proof: 4,616 SQLite predicate cases and Django probes in
`/private/tmp/graphex-review-data.FIvcOG/sqlite_boundary_design.py` and its log.
The initial prototype missed an int64 endpoint; the corrected union/clamping
algorithm passed. That prototype is evidence, not production implementation.

## Tasks and routing

- [x] **T1 — Correct the predicate with regression tests and documentation.**
  Route: delegated direct; mapping required more than three files and the fix
  spans non-trivial source, tests, and docs. Observe RED before changing source,
  then minimal GREEN and REFACTOR. Cover signs/directions, legacy/composite
  cursors, exact fine ties, tiny boundaries, INTEGER/REAL neighbors, NULLs,
  malformed PKs, selected database alias, aligned controls, lazy/index-friendly
  queries, and unchanged non-SQLite planning. Update both changelogs and the
  upgrade/pagination guidance, including the stale weak-executor/request-budget
  descriptions. No example/Playground/benchmark change is expected because the
  public API and their configured workloads remain unchanged; verify that claim.
- [x] **T2 — Independently verify and record closure.**
  Route: delegated verification for the numeric correction and a fresh full
  suite/coverage proof; parent performs one spot check and structural readback.
  Record actual failures, skips, warnings, coverage, local commit identities,
  rollback boundary, protected-file comparison, and any remaining limitations.

## TDD and acceptance

Strict TDD is enabled by the current user request and project instructions.
Runner: the existing supported Python interpreter invoking `pytest`; root
`.venv` has an unsupported graphql-core version and must not supply credited
results. Verify graphql module and distribution version `3.3.0` and checkout
imports in the same process as final full execution.

- Focal: `python -B -m pytest tests/test_pagination_cursor_parity.py --no-cov`,
  extending the explicit selection for new tests; external cache/basetemp/logs.
- Related: cursor, server-ordering, and PK-tiebreak tests with `--no-cov`.
- Final: full configured suite, branch coverage and combined coverage each
  at least **95.01%**; applicable diff coverage; Ruff format/check, mypy,
  Bandit, standard/strict docstrings, documentation build, `git diff --check`.
- Preserve all configured coverage checks/exclusions and addopts. Redirect only
  coverage HTML/XML destinations using an external config copy; retain raw
  coverage before the isolation plugin's exit cleanup. Do not overwrite root
  reports, disable addopts, add skips, lower thresholds, or inflate coverage.
- Preserve lazy bounded database filtering, cursor wire format, error messages,
  NULL placement, and PK validation. No new SQLite functions or connections.

## Delivery and rollback

Forecast: approximately 380 authored changed lines; retain coherent tests/docs
even if more are necessary. Strategy: `ask-on-risk` for any future PR; current
delivery is local only, with no PR preparation or chain creation. Conventional
work-unit commits only, without AI attribution. RDD is **off (global)** as
verified at start; do not enable it or run native review.

Rollback: revert this feature's predicate/tests/docs work unit, not prior audit
fixes. Original tiny-boundary protection must not be removed independently.

## Evidence and progress

- Start: tracked tree/index clean; only existing audit reports and `.codegraph/`
  untracked. Protected-file baseline and tracked bytes/modes captured in
  `/private/tmp/graphex-rev05-20261025-2ic2j0w9/before.json`.
- T1 implementation: native SQLite INTEGER/REAL bounds apply only after the
  finer-than-scale check. Exact binary fractions retain PK ties; unrepresentable
  bounds use inclusive adjacent values without accepting malformed PKs.
  The unreachable integral shortcut was removed during verification; integer
  neighbor selection remains necessary and covered. No public incompatibility.
- TDD RED: four new signed raw-storage legacy/composite cases failed with `[]`
  instead of `[10]` before the source edit (`writer/red.log`). GREEN/REFACTOR:
  final writer selection **270 passed**; parent spot check **209 passed**.
- Independent numeric proof: **211 tests passed**, including **864 actual ORM
  comparisons** against an exact Fraction oracle and **216 finer-boundary
  checks**. Queryset planning remains lazy and bounded, without column casts.
- Final full suite: **7,778 passed, 4,064 subtests, 6 skipped, 18 warnings**;
  seed `1182471920`, 182.48 seconds, exit 0. Same-process Python 3.12.11,
  Django 6.0.8, graphql-core module/distribution 3.3.0, checkout imports verified.
- Final raw coverage reconciles with XML: lines **13,425/13,646 (98.38048%)**;
  branches **5,085/5,322 (95.54679%)**; combined **18,510/18,968 (97.58541%)**.
  Diff coverage versus the base, including unstaged changes: **37/37 (100%)**.
- Ruff format/check, mypy, Bandit, standard and strict docstrings, and
  `git diff --check` passed. External documentation mirror built **44 HTML
  pages**, with no issues and source hashes matching the checkout.
- Earlier evidence is retained, not replaced: the first full run passed 7,768
  tests, but four DOC002 violations and 92.5% diff coverage required correction.
  Four test docstrings were fixed, the unreachable integral shortcut removed,
  and real finite fractional overflow cases added before the final full run.
  The first docs build hit an absolute-path tooling panic; the external mirror
  using original relative configuration succeeded without a repository workaround.
- Limits: five PostgreSQL opt-in tests and one retired Graphene test skipped;
  no live PostgreSQL, benchmark, or Playground run. Example/Playground timestamp
  cursor and benchmark offset configurations need no change for this fix.
- Preservation: **98 protected files and 871 unrelated tracked files unchanged**;
  the six source/test/doc candidate files were frozen for final verification.
- Evidence: `/private/tmp/graphex-rev05-20261025-2ic2j0w9/`, including
  `writer/`, `verification/final/`, and `parent-spot.log` / `parent-spot.xml`.
- Delivery remains local only. The coherent correction exceeds the advisory
  initial forecast; no tests/docs were omitted or compressed to meet it. Any
  future PR size/chain decision remains deferred because PRs are not authorized.
- T1 work-unit commit and T2 functional-check evidence: `577adfb`
  (`fix(pagination): preserve exact SQLite Decimal cursor boundaries`). Its
  authored count is **579 additions + 69 deletions**, including **128 tracker
  lines**; the source/test/public-doc correction is **520 changed lines**.
  This follow-up tracker-only commit records closure; no verified source bytes
  are changed after the final proof.
- RDD disposition for both tasks: **disabled/unmanaged (global off)**; no native
  review or consent flow was started. Independent functional verification is
  recorded above and does not claim native review approval.
- Status: **CLOSED**, with the complete tracker mirrored to Engram. No remaining
  blocker in this authorized correction. Future PR planning, CI matrix/live
  PostgreSQL and any release remain outside this local-only task.
- Next step: maintainer review when desired; no automatic remote action.
