# GraphQL-core 3.3 migration

## Objective and authorization

Migrate django-graphex from GraphQL-core 3.2.13 to the stable 3.3 line while
preserving the published 3.1.1 security release. The user approved local
implementation and the feature-branch-chain delivery strategy toward an
integration branch in eamigo86/django-graphex using the authorized eamigo86
session. This T0 work unit remains local: no issue creation or approval change,
push, PR, merge, release tag, publication, or workflow dispatch is authorized
here. Issue-first permission must be resolved before remote delivery.

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
  one `type:*` label; issue-creation authority is unresolved in this T0 unit.
  No main merge, versioned release, tag, or publication follows automatically.

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
- [ ] T1 — Adapt HTTP views to Executor and renamed execution keyword handling.
  Keep the current 3.2.13 suite green while providing focused 3.3-API proof.
  Document that callers with old 3.2 custom ExecutionContext subclasses must
  upgrade them; do not promise transparent compatibility for those subclasses.
- [ ] T2 — Adapt SSE and WebSocket subscription sources to an Executor-built
  source. Cover both transport paths and sync/async error behavior with bounded
  regressions before changing the runtime floor.
- [ ] T3 — Replace mutable AST construction patterns and cover stricter value
  coercion, frozen node collections, and schema/query correctness regressions.
- [ ] T4 — Raise the dependency floor to `graphql-core>=3.3.0,<3.4`, scope-update
  root and Playground locks, examples, migration guidance, and benchmark harness
  without rewriting historical results. Resolve a package release version only
  after a separate product decision. Run independent clean-clone full/coverage,
  quality, docs, Playground, security, and hosted-release-readiness checks.

## Progress and next step

T0 local implementation is verified. The published 3.1.1 main tree remains the
immutable starting boundary; no migration runtime source, dependency, lock,
package metadata, benchmark result or historical release note changed. Next:
independently verify this T0 slice and resolve issue-first remote permission
before any push or PR. T1 is the next implementation task. Keep the Engram
mirror pending until a registered session identity is available.

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
