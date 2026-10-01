# GraphQL-core 3.3 migration

## Objective and authorization

Migrate django-graphex from GraphQL-core 3.2.13 to the stable 3.3 line while
preserving the published 3.1.1 security release. The user approved local
implementation and the feature-branch-chain delivery strategy toward an
integration branch in eamigo86/django-graphex using the authorized eamigo86
session. The user subsequently authorized issue creation and approval for this
migration, plus feature-branch-chain PR delivery toward the integration branch.
Child remote delivery may integrate only into that branch. Main merge, a release
tag, publication, workflow dispatch, and unrelated remote changes remain out
of scope.

## Problem and scope

- [GraphQL-core 3.3.0](https://github.com/graphql-python/graphql-core/releases/tag/v3.3.0)
  is a stable but breaking migration from 3.2.13: immutable AST nodes, renamed
  execution context APIs, and changed subscription source construction require
  code and regression work before raising the runtime dependency floor.
- Implement the compatibility work while 3.2.13 remains the root runtime, so
  ordinary full-suite checks stay green. Future tasks can use a separate 3.3
  wheel-overlay environment for focused new-API proof without changing the root
  environment prematurely; no dual-version public support promise is implied.
- Raise the final runtime minimum to GraphQL-core 3.3.0 with an upper bound below
  3.4 only after compatibility work. The package release version remains
  undecided; do not change 3.1.1 metadata in preparatory tasks.
- Retain the dated 3.1.1 and 3.1.0 changelogs, audit traceability, eight
  canonical benchmark JSON artifacts, and frozen historical constraints.
  Append migration guidance later rather than relabeling old results.
- Preserve the pre-existing untracked .codegraph index and local Python
  environment. No local distribution build or uncontrolled dependency refresh.

## Execution and delivery

- Branch: `codex/graphql-core-3.3`; branch point:
  `bb415efc10e4a4b85079344b1c3c607de7a06daa` (published 3.1.1 main).
- Route: delegated direct by bounded task. T0 touches CI and its contract;
  T1-T4 require multiple non-trivial runtime, test, lock, or documentation files.
- Strict TDD: enabled by current user AGENTS.md instructions. Each behavioral
  unit observes RED for the intended cause, minimum GREEN, then REFACTOR.
  Focused runner: `.venv/bin/python -m pytest <tests> --no-cov`.
  Full runner: `.venv/bin/python -m pytest` with unchanged 95.01% branch gate.
  Use a clean real local Git clone for full verification because this checkout
  has ignored extra benchmark JSON that causes unrelated provenance failures.
- RDD is globally off. Do not enable or invoke a native review lifecycle;
  independent verification follows ordinary checks. Engram mirror
  `odd/graphql-core-3.3/tasks` is pending because the host has no authoritative
  registered session identity. Do not write memory without that identity.
- Forecast: 450-650 authored changed lines for migration behavior/tests, plus
  CI and task-document overhead; generated lock lines are reported separately.
  Delivery strategy: auto-chain using the human-approved feature-branch-chain.
  Keep each child PR at or below 400 authored changed lines, with no authored
  `size:exception` approved. The integration tracker remains draft until each
  child passes its own checks. PRs require an approved linked issue and exactly
  one `type:*` label; issue creation and approval are explicitly authorized.
  No main merge, versioned release, tag, or publication follows automatically.
- Approved issue map: [T0 #206](https://github.com/eamigo86/django-graphex/issues/206),
  [T1 #207](https://github.com/eamigo86/django-graphex/issues/207),
  [T2 #208](https://github.com/eamigo86/django-graphex/issues/208),
  [T3 #209](https://github.com/eamigo86/django-graphex/issues/209), and
  [T4 #210](https://github.com/eamigo86/django-graphex/issues/210).

## Tasks

- [x] T0 — Admit the migration integration branch and its child PR bases to CI.
  Route: delegated direct; ownership is `.github/workflows/cicd.yaml`,
  `tests/test_release_workflow.py`, and this task document. Add narrow push and
  pull-request branch filters for `codex/graphql-core-3.3` and
  `codex/graphql-core-3.3-*` only. Preserve existing main, release-branch,
  3.1.1 child and tag triggers, permissions, job graph, and publication guards.
  Observe a RED workflow contract first, then GREEN and full checks. Runtime
  harness: N/A, because this only selects hosted CI events. Rollback boundary:
  the new branch filters, their test contract, and this planning checkpoint.
  RED, GREEN, clean-clone full coverage and quality evidence are recorded below.
  Work-unit commit: b8cf6d163a3b58f51487fa80f2d25fa3a66fa1d0.
- [x] T1 — Adapt HTTP views to Executor and renamed execution keyword handling.
  Keep the current 3.2.13 suite green while providing focused 3.3-API proof.
  Document that callers with old 3.2 custom ExecutionContext subclasses must
  upgrade them; do not promise transparent compatibility for those subclasses.
  Route: delegated direct. Own only the HTTP view, focused tests, public view
  guidance, and this recovery document. Evidence and rollback are below.
  Work-unit commit: 62edc33f5c47a12f8ae51bb04c08557473f08ad7.
  Reopened after independent verification found that an explicit keyword could
  not override a subclass default stored under the other alias. Both cross-name
  real-HTTP regressions now pass after correcting explicit-over-default
  precedence; the bounded correction proof is recorded below.
  Correction commit: 78f8040f72584d0a79b4f176db433aa117bd82d2.
- [x] T2 — Adapt SSE and WebSocket subscription sources to an Executor-built
  source. Cover both transport paths and sync/async error behavior with bounded
  regressions before changing the runtime floor. Route: delegated direct; own
  the SSE and WebSocket transports, focused transport regressions, subscription
  guidance, and this document. First observe RED under the official 3.3.0
  overlay for both transports, then GREEN/REFACTOR while preserving the root
  3.2.13 suite. Verify both-version focused transports, unchanged full 3.2.13
  clean-clone coverage gate, changed-line coverage, quality, and docs before
  marking complete. Roll back only T2 transport integration, tests, and guide.
  Work-unit commit: a07fb18719c76e8b7e1524c8e8bce922061dea71.
- [ ] T3 — Build immutable inline-fragment AST fixtures at construction time,
  replace test-only removed MapAsyncIterator imports without weakening the
  delivery guards, and verify coercion plus valid schema/query behavior under
  GraphQL-core 3.2.13 and isolated 3.3.0. Route: delegated direct; own focused
  optimizer, coverage, delivery, and streaming tests, concise migration
  guidance, and this document. A real 3.3 Boolean-variable query exposed a
  bounded directive-coercion incompatibility; the parent separately authorized
  its T3 adapter in the shared directive/argument seams, preserving native
  variable source metadata and conservative unbound behavior. Observe RED on
  3.3 fixture/import/coercion behavior, then GREEN/REFACTOR; run both-version
  focused tests and unchanged full 3.2.13 clean-clone gate. A full 3.3
  diagnostic may identify later blockers but is not the T3 acceptance gate.
  Roll back only T3 AST/test compatibility, coercion adapter/regressions,
  guidance, and tracking changes. Overall T3 remains pending until the
  separate cost/list-fixture and HTTP dual-iterator slices resolve the 3.3
  diagnostic failures; do not treat those failures as accepted skips.
  - [x] T3a — AST, retired mapper test guards, and directive coercion adapter.
    Work-unit commit: 5063aa0d4617f798fccb74633b1c6418d8a29f9a.
  - [ ] T3b — Resolve 3.3 cost/list-node compatibility and stale upstream
    constructor expectation with separate tests and guidance.
  - [ ] T3c — Restore synchronous queryset execution under 3.3's dual-iterator
    list selection with a separate HTTP regression slice.
- [ ] T4 — Raise the dependency floor to `graphql-core>=3.3.0,<3.4`, scope-update
  root and Playground locks, examples, migration guidance, and benchmark harness
  without rewriting historical results. Resolve a package release version only
  after a separate product decision. Run independent clean-clone full/coverage,
  quality, docs, Playground, security, and hosted-release-readiness checks.
  Benchmark profile decision remains pending: replay the historical four-way
  results from a historical source ref/profile and run a separate current
  diagnostic, or design a new comparison with per-library core versions. Do not
  silently substitute peers or alter frozen historical artifacts.

## Progress and next step

T0, T1, and T2 passed independent verification and merged into the
integration branch after hosted checks. T2's exact child `fc1df815` merged as
`f079967e` with identical tree and all 15 child/integration/tracker validation
jobs plus Codecov green; its separate local-only recovery checkpoint is
`278983b47fd6138c961bd8150881bfbb4cd50928`. The draft
[tracker #212](https://github.com/eamigo86/django-graphex/pull/212) must not
merge to main. T3a passed its local two-version and clean 3.2.13 gates,
but T3b/T3c are pending, as are T4, its benchmark-profile choice, and the
package release version. Published 3.1.1 main remains unchanged; no dependency
floor, lock, package metadata, benchmark result, or historical release note
changed. Keep the Engram mirror pending until a
registered session identity is available.

### T0 verification evidence

- RED: `.venv/bin/python -m pytest
  tests/test_release_workflow.py::test_graphql_core_migration_branches_run_ci_without_widening_publish
  --no-cov -q` failed for the intended missing integration push branch.
  GREEN: `.venv/bin/python -m pytest tests/test_release_workflow.py
  tests/test_release_readiness_311.py --no-cov -q` passed 15 tests. The related
  3.1.0 docs/readiness command passed 75 tests.
- A clean real local clone with the three-file candidate overlay passed the
  complete suite: 4,372 passed, 7 skipped, 96.21% branch-enabled coverage
  against the unchanged 95.01% gate. No module was excluded. Evidence:
  `/private/tmp/graphex-33-t0.J99X1K/full-suite.log`.
- Ruff format/lint, mypy, standard and strict docstring gates (strict TOTAL 0),
  Zensical build and diff checks passed in the clean clone. The docs build
  retained five previously verified broken-anchor warnings. No local build,
  dependency reinstall, issue, push, PR, merge or workflow dispatch occurred.
- Runtime harness: N/A, because this change only selects CI events. The
  rollback boundary is the three migration branch filters, their structural
  test, and this T0 planning checkpoint; publication guards are unchanged.
- Read-only risk assessment returned high/unassessable because pre-existing
  untracked .codegraph requires explicit inventory. RDD remains off; no native
  review status, start or lifecycle was run. Independent verification passed.
- T4 discovery: `benchmarks/setup_envs.sh` installs the current editable
  GraphEx against frozen `graphql-core==3.2.11`, which will conflict with the
  future 3.3 floor. [Graphene 3.4.3 metadata](https://pypi.org/pypi/graphene/3.4.3/json)
  requires `graphql-core<3.3`; a shared 3.3 four-way profile is not viable with
  that historical peer. This does not block the T0 CI-only change.

### T0 independent verification

- Candidate `cdfd2736522079a4f0d9d78e9634be8370df5b46` passed an independent
  clean-clone check: 75 focused tests; 4,372 full-suite tests, 7 skipped,
  7 subtests, and 96.21% branch-enabled coverage with the unchanged 95.01% gate.
- Ruff, mypy, both docstring gates, docs build, and diff checks passed. The
  five baseline documentation warnings remain. Diff coverage is N/A because
  no covered runtime lines changed. No hosted checks or 3.3 runtime tests ran.
- Parsed YAML and combined contract checks preserve publication guards,
  permissions, the complete job graph, and the prior 3.1.1 branch coverage.
  Evidence: `/private/tmp/graphex-33-t0-independent.CK7TLL/`.

### T0 remote delivery

- Approved [issue #206](https://github.com/eamigo86/django-graphex/issues/206)
  backs [child PR #211](https://github.com/eamigo86/django-graphex/pull/211):
  `codex/graphql-core-3.3-ci` at
  `74b32a7e998346b9e66d01efea210645e93ebec6` into the integration branch.
  The slice has 188 additions and 1 deletion, all authored, with no exception.
- [Child CI](https://github.com/eamigo86/django-graphex/actions/runs/36905293149)
  passed all 15 validation jobs and both Codecov checks. The three publication
  jobs skipped as intended. Conventional merge
  `977560446f74abe7fdfdb695311ba19da721b806` has the reviewed child tree
  `f3cafb98e9a48bca6329283771625f42f2a75e89`.
- The integration [push CI](https://github.com/eamigo86/django-graphex/actions/runs/36905712173)
  and draft [tracker CI](https://github.com/eamigo86/django-graphex/actions/runs/36905838138)
  each passed all 15 validation jobs, with the three publication jobs skipped;
  both tracker Codecov checks passed. Tracker #212 is draft, links approved
  issues #206-#210, and remains unmerged. Main remains at
  `bb415efc10e4a4b85079344b1c3c607de7a06daa`; the 3.1.1 tag is unchanged.
- This evidence checkpoint is local-only. It is not part of the reviewed
  integration tree or tracker PR; no task-document commit was pushed after T0.

### T1 local implementation and verification

- RED on both installed 3.2.13 and isolated official 3.3.0: the preferred
  `executor_class` view keyword was rejected, and the legacy keyword failed
  3.3 execution. Conflicting backend names were not rejected as configured.
  After the minimal adapter, all four new or updated focused contracts passed
  under both versions; the related HTTP and security selection passed 88 tests
  under each. The tests execute a real HTTP query with a recording backend.
- `BaseGraphQLView` accepts `executor_class` and the compatibility alias
  `execution_context_class`. Supplying the same class twice is allowed; distinct
  non-None classes raise `ImproperlyConfigured` at construction. The adapter
  selects GraphQL's native keyword by the installed execution module's
  `Executor` export, not by an optionally patched `execute` call signature.
  GraphQL-core 3.2 custom ExecutionContext subclasses must be ported to the
  3.3 Executor base and methods; the alias does not port their implementation.
  No `from_schema` view factory exists here, so constructor and `as_view` are
  the applicable configuration paths.
- An isolated official 3.3.0 wheel overlay in `/private/tmp/graphex-33-t1-overlay`
  supplied only GraphQL-core; the root environment and dependency floor stayed
  at 3.2.13. A clean local Git clone proved imports came from its candidate
  source and the overlay package. Its unchanged full runner passed 4,375 tests,
  7 skipped, 7 subtests, and 96.22% branch-enabled coverage against the
  unchanged 95.01% gate. Changed runtime lines reached 100% diff coverage.
  Proof: `/private/tmp/graphex-33-t1.9xmCtW/`.
- Ruff format and lint, mypy, standard and strict docstrings (TOTAL 0),
  Zensical docs build, and diff checks passed. The docs build kept five
  verified pre-existing anchor warnings. No local package build, root
  dependency refresh, benchmark rewrite, remote push, PR, main merge, tag, or
  dispatch occurred. Rollback only T1's HTTP backend adapter, tests, and view
  guidance; preserve the independently integrated T0 CI gate.

### T1 bounded correction after independent verification

- Root cause: each alias fell back to its subclass default before explicit
  constructor choices were compared, so a default under the other name looked
  like a second explicit class. Two new real-HTTP cross-name override tests
  each failed RED with `ImproperlyConfigured` under both GraphQL-core 3.2.13
  and 3.3.0, then passed GREEN after explicit arguments took precedence over
  defaults. Distinct explicitly supplied classes still fail; identical ones
  remain allowed. Public view guidance now states this precedence.
- The corrected HTTP/security selection passed 90 tests under each version.
  Clean tracked-candidate source imported from
  `/private/tmp/graphex-33-t1-corrected.vWVmF7/candidate`, while the isolated
  official 3.3.0 overlay supplied GraphQL-core only. The unchanged 3.2.13 full
  runner passed 4,377 tests, 7 skipped, 7 subtests, and 96.22% branch-enabled
  coverage against the unchanged 95.01% gate. Changed runtime lines had 100%
  diff coverage (15 lines, zero missing).
- Ruff format/lint, mypy, standard and strict docstrings (TOTAL 0), docs build,
  and diff checks passed in the clean candidate. The five established anchor
  warnings remain. No test exclusion, coverage override, root dependency or
  lock change, local package build, remote delivery, or benchmark rewrite was
  used. Proof: `/private/tmp/graphex-33-t1-corrected.vWVmF7/`.

### T1 independent reverification

- Exact candidate `1086c012f97b5713ef04925b06be321786347c68` passed 90
  focused real-HTTP/security tests under both GraphQL-core 3.2.13 and 3.3.0.
  The clean-clone 3.2.13 suite passed 4,377 tests, 7 skipped, 7 subtests,
  and 96.22% branch coverage against the unchanged 95.01% gate. Changed
  runtime lines reached 100% diff coverage across 15 lines.
- Ruff, mypy, both docstring gates (strict TOTAL 0), docs, and diff checks
  passed; the five established docs anchor warnings remain. The parent
  independently spot-checked the same 90 focused tests on 3.2.13. Proof:
  `/private/tmp/graphex-33-t1-reverify.FP6LvF/`. Hosted checks are recorded below.

### T1 remote delivery (checkpoint carried forward)

- Approved issue #207's [child PR #213](https://github.com/eamigo86/django-graphex/pull/213)
  merged 334 authored lines (no exception) into integration as
  `849781c257f4b0a0ffed0711e5dbc74f4fd24115`, tree
  `e476d12c4ebd044c2754cf34ba9f66bfc47ae13c`, identical to child
  `ec2b42c7ac1da5f5fe4bc28ac435adb8d7d0108a`.
- [Child](https://github.com/eamigo86/django-graphex/actions/runs/36911350914),
  [integration](https://github.com/eamigo86/django-graphex/actions/runs/36911769469),
  and [tracker](https://github.com/eamigo86/django-graphex/actions/runs/36911776002)
  CI each passed 15 validation jobs, skipped three publication jobs, and the
  child/tracker Codecov checks passed. Draft tracker #212 remains unmerged;
  main `bb415efc` and tag v3.1.1 are unchanged. Full remote proof remains in
  local-only checkpoint `eb538e609508960cf6b72b2dcc476fc4a453f0a7`.

### T2 local verification

- RED under official 3.3.0: SSE raised the old keyword TypeError; WS framed
  that error instead of the expected variable error. Both 3.2.13 controls
  passed. Expanded 3.3 testing also caught malformed WS variables reaching
  the resolver; the adapter restores 3.2's early TypeError.
- GREEN: 56 focused and 100 expanded transport tests passed under each of
  3.2.13 and 3.3.0, including live delivery, sync/awaitable source results,
  executor-build errors, authorization, and wire framing.
- Clean real clone imported candidate source and root GraphQL-core 3.2.13:
  full suite 4,382 passed, 7 skipped, 3 expected warnings, 7 subtests;
  96.22% branch coverage exceeds the unchanged 95.01% gate. Diff coverage:
  100% of 18 changed runtime lines. Ruff, mypy, both docstring gates (strict
  TOTAL 0), docs, and diff checks passed; five baseline anchor warnings remain.
- Exploratory full 3.3 subscriptions collection remains blocked by a retired
  MapAsyncIterator test import; T4 owns full 3.3 migration validation. No
  modules were excluded from the 3.2 full run. Proof:
  `/private/tmp/graphex-33-t2-proof.iEKsNh/`.

### T3a local verification and remaining migration blockers

- RED under isolated official GraphQL-core 3.3.0: the old stock-mapper import
  stopped collection, and 17 AST fixture tests failed because
  `InlineFragmentNode` now requires its selection set at construction. A new
  real union Boolean-variable query passed 3.2.13 but failed 3.3.0 with
  `dict has no attribute coerced` from directive evaluation; its invalid
  variable/default and valid-query assertions remain in the regression.
- GREEN: 143 focused optimizer, directive, and delivery tests passed under
  each of 3.2.13 and 3.3.0. AST fixtures use constructor-supplied immutable
  fields and tuple selections. The structural delivery guard still rejects
  each generation's stock mapping type. The 3.2 historical stock/optimized
  speed ratio remains guarded; 3.3 retains the absolute latency ceiling.
- The small capability adapter wraps only legacy dicts as native 3.3
  `VariableValues(sources={}, coerced=values)` and preserves real native
  objects, including default/source metadata. Core 3.2 mappings pass through.
  Existing unbound skip/include cases remain conservative. No broad exception
  handling or backend keyword changes were added.
- A clean real candidate clone imported its source and the unchanged root
  3.2.13 environment. Its full runner passed 4,385 tests, 7 skipped,
  3 expected warnings, 7 subtests, and 96.23% branch coverage against the
  unchanged 95.01% gate; changed runtime lines had 100% diff coverage (9/9).
  Ruff format/lint, mypy, both docstring gates (strict TOTAL 0), docs, and
  diff checks passed; five established docs anchor warnings remain. Proof:
  `/private/tmp/graphex-33-t3-prelim.wjFbg6/`.
- A diagnostic full 3.3.0 run collected all tests without the retired mapper
  import, then reported 21 failures, 4,364 passes, and 7 skips. These later
  migration blockers include four query-cost tests, one native-list constructor
  expectation, and 16 HTTP/field tests affected by dual-iterator querysets;
  they are not accepted skips and must be resolved
  before T4 can claim a full 3.3 pass. No module was excluded or gate lowered.
  No dependency floor, lock, package metadata, benchmark artifact, or release
  note changed. Roll back only this T3 adapter, tests, view guidance, and
  recovery checkpoint; preserve integrated T0-T2.
