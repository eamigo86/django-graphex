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
  3.4 only after compatibility work. The user selected 4.0.0 for the later
  release; do not change 3.1.1 metadata in preparatory tasks.
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
- Initial migration forecast was 450-650 authored lines; that historical
  estimate is superseded for remaining work. T4b benchmark bootstrap is
  forecast at 200-320 authored lines and its separate new runner at 250-380;
  final examples/guidance and measured artifacts remain TBD. Generated locks
  are reported separately. The 400-line task heuristic does not justify
  dropping tests or docs; each delivered child PR still respects its hard
  authored-line budget. Delivery strategy: auto-chain using the human-approved feature-branch-chain.
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
- [x] T3 — Build immutable inline-fragment AST fixtures at construction time,
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
  guidance, and tracking changes. T3's local acceptance now includes both
  root and 3.3 changed-line coverage gates. T3b/T3c merged into only the
  integration branch as `637dcb71` and `61b8784e`; both fresh integration
  and tracker runs passed 15 validation jobs and tracker Codecov. No checkbox
  authorizes a main merge or dependency bump.
  - [x] T3a — AST, retired mapper test guards, and directive coercion adapter.
    Work-unit commit: 5063aa0d4617f798fccb74633b1c6418d8a29f9a.
  - [x] T3b — Resolve 3.3 cost/list-node compatibility and stale upstream
    constructor expectation with separate tests and guidance. Route: delegated
    direct on local child codex/graphql-core-3.3-cost from 5cdd2b13; own cost.py,
    cost regressions, native-list fixture, query-limit guidance, and this document.
    Observe RED under official 3.3.0, GREEN under 3.2.13 and 3.3.0, unchanged
    full 3.2.13 coverage gate, changed-line coverage, quality, and docs. Preserve
    the 16 HTTP dual-iterator failures for separately routed T3c. Roll back only
    this T3b slice; do not raise the root dependency floor or deliver remotely.
  - [x] T3c — Restore synchronous queryset execution under 3.3's dual-iterator
    list selection with a separate HTTP regression slice. Route: delegated
    direct on local child `codex/graphql-core-3.3-querysets` from T3b
    `b8abfbf148d5a3d42f0eb6fb655f0d484b91f144`. Own HTTP view selection,
    focused queryset/atomic/cache regressions, view guidance, and this document.
    Strict TDD from current user AGENTS.md: RED on official 3.3.0 first,
    then GREEN/REFACTOR with the `.venv/bin/python -m pytest <tests> --no-cov`
    focal runner. Require complete clean-clone suites on both 3.2.13 and
    3.3.0 with the unchanged 95.01% branch gate, plus changed-line coverage,
    quality and docs. The initially rejected T3b push was a historical
    authorization block; fresh explicit human authorization later enabled
    issue-linked PRs and integration-only merges. Rollback boundary is only
    T3c HTTP selection, tests, guidance, and tracking. Both full suites and
    changed-line gates passed after a real adapter-forwarding regression
    covered the native-3.3 capability path under the root runner without
    exclusions. Independent and current-head hosted verification passed.
- [ ] T4 — Adopt GraphQL-core 3.3 as the supported runtime, complete the
  example, benchmark, documentation, and release-readiness migration without
  rewriting historical results. Route: delegated direct in coherent child PRs.
  The user selected a new four-library comparison with compatible core
  versions chosen separately for each library. Compare disclosed whole stacks,
  not libraries alone. Preserve the eight historical JSON results, versions.env,
  constraints, and dated release notes. Package SemVer is still undecided.
  - [x] T4a — Raise only the runtime GraphQL-core bound to >=3.3.0,<3.4;
    scope-update root and Playground graphql-core lock entries; preserve
    package version 3.1.1. Own current-readiness contracts and bounded public
    floor/Executor guidance. Strict TDD: RED current floor/lock/document
    contracts, then GREEN/REFACTOR; focused runner uses
    `.venv/bin/python -m pytest <tests> --no-cov`. Prove a full clean-clone
    3.3 suite with unchanged 95.01% branch gate, check-only quality/docs,
    lock consistency, and diff checks. The original T4a RED/GREEN proof is
    retained below; the later privacy integration is a history merge, not a
    fabricated second RED. Fresh combined native-3.3 and hosted checks are
    required before integration. Reopened after exact-head project Codecov
    failed at 94.96% despite green validation jobs; T4q tests address the
    identified capability-path coverage gap without altering runtime code.
    Rollback only this floor/locks/readiness/guidance child.
  - [ ] T4b — Add a new comparison profile and benchmark harness/tests using
    per-library compatible core versions; keep historical replay isolated
    and historical artifacts byte-identical. No new performance result is
    claimed until measured.
    - [x] T4b1a/b — Locally verify named dependency freezes, preflight, and
      isolated setup; independent and hosted delivery checks remain pending.
    - [x] T4b1b-CI — Align disposable fake-uv fixtures with the test interpreter;
      retain the real 3.12.11 pin and wrong-interpreter rejection. Recheck the
      focused contracts, 3.14 portability, and clean native-3.3 full suite.
    - [x] T4b1c — Make the historical no-argument bootstrap fail closed before
      replacing any existing venv. Preserve all requested targets on invalid
      input, offline cache miss, or install failure; reserve fresh final paths
      without relocating venvs. Test RED on the old destructive path, then
      GREEN, fresh published-3.1.0-wheel setup, and clean-clone gates. Own only
      the legacy script, focused tests, benchmark guidance, and this checkpoint.
      Rollback only this safety child; no canonical results or pins change.
      Local proof and work-unit commits are recorded below. Independent and
      hosted verification remain pending.
    - [ ] T4b2 — Add the separately named runner, provenance, and measurements.
      - [x] T4b2a — Add an independently executable, read-only named-profile
        preflight for one selected stack: clean source identity, installed
        freeze, runtime import, prepared seed, and fresh external destination.
        Retain strict RED/GREEN and native-3.3 gates; size:exception applies
        only here. Route: delegated direct; preflight, tests, guidance.
        Initial 544 lines grew for fail-closed output, backend provenance,
        direct CLI import safety, and public docstrings; final count is 592.
        Four real stacks and clean native-3.3 gates passed without producing
        measurements. Proof: /private/tmp/graphex-t4b2a.eaFO6y.
        Commit 121714f942aa4201867881a0703faf25e8dae48d merged into
        integration as 5f1d4167379fd0d1f1facba904249b0b6c1cfe15.
      - [x] T4b2b1 — Add an opt-in measuring-child source/backend/profile
        witness, with focused tests and guidance. Route: delegated direct.
        Observe witness-specific RED, then GREEN; prove actual profile imports,
        dynamic source version, native-3.3 gates, and unchanged historical
        no-profile output. No measurement dispatch or publication in this unit.
        Candidate proof: /private/tmp/graphex-t4b2b.G0XXJU. Clean native-3.3
        clone passed 74 benchmark and 4,462 full tests at 96.23% branch;
        four real profile imports bound version, paths, hashes, commit, and
        tree. Ruff, mypy, both docstring gates, docs, and diff checks passed.
        The previous missing-database probe path was corrected before the
        asset-preservation proof. Work-unit commit 5d16273aa106342e51eaab3ab05580bbc2aee326
        has tree 1c6ddee80dcd3f94da8e823e84bbff61cbee5b8a.
      - [x] T4b2b2a — Validate a named-profile child's whole-stack witness,
        five-operation output, and selected freeze against read-only preflight.
        Route: delegated direct on codex/graphql-core-3.3-benchmark-execution
        from b5650d8; own runner validator, focused tests, brief guide, and
        this checkpoint. This extracts already GREEN-tested dispatch intent
        into a standalone read-only contract; new direct validator controls
        are post-GREEN strengthening, not a claimed validator-specific RED.
        The retained initial RED failed on absent run_single and specified
        five forged-witness fields; no full real run is claimed here.
        Fresh numeric RED: 25 malformed-value controls failed because the
        validator accepted infinity and booleans; valid integer/float timing
        control passed. After the focused fix, all five independent repros
        reject malformed data. Native-3.3 clean-clone: 4,507 full / 119
        benchmark tests, 96.23%; quality and docs pass. Proof:
        /private/tmp/graphex-t4b2b2.Qr4xxr/numeric-fix/.
        Original work unit: dff6703475bbec39fce5bca7edbb72852f952de7.
        Numeric correction: d934c045c42cc0c6f8a3e9c6a404719c4a7297a5.
        Roll back only this validator slice.
      - [x] T4b2b2b1 — Add an optional held-directory write boundary for
        named-profile harness output without changing historical output.
        Route: delegated direct on codex/graphql-core-3.3-benchmark-dispatch-run
        from integration 1413265; own only harness, focused isolation tests,
        brief guidance, and this checkpoint. Fresh RED proved a mismatched
        output descriptor was ignored and the path writer was still used;
        GREEN proved both held-directory controls. A further fresh RED proved
        traversal-bearing library names were accepted; the guard now rejects
        them. A renamed visible directory leaves the write on the held inode.
        This boundary is useful independently but does not dispatch or measure
        a full profile. Work unit: 50f38c657f864bfb1ce7a5cbe618bb9f4e48c141.
        Clean native-3.3 clone: 61 focal, 125 benchmark, 4,513 full tests;
        96.23% branch coverage above 95.01%, unchanged 258/266/282 gap sets,
        seven skips, three warnings, 23 subtests. Ruff, mypy 82 files, both
        public docstring gates, docs with five baseline anchors, and diff check
        passed. Full raw proof: /private/tmp/graphex-t4b2b2b.nXAbfN/.
        No heavy four-profile measurement was run. Roll back only the optional
        descriptor write and its controls.
      - [ ] T4b2b2b2 — Dispatch the existing five-operation harness using
        read-only preflight, the checked validator, and the held directory.
        Route: delegated direct on codex/graphql-core-3.3-benchmark-dispatch-single
        from integration cbc9ebe; own only the named runner, focused tests,
        concise benchmark guidance, and this task checkpoint. Keep default
        CLI preflight read-only and make execution explicit.
        Reserve fresh external output with safe empty prefix, sanitize the
        child, recheck source/runtime/freeze/seed around execution, reject
        witness/output drift, and retain failed-attempt output when creation
        ownership cannot be proved for safe cleanup. In particular, retain
        unvalidated result files and even empty directories instead of risking
        deletion of a foreign path. Do not claim loaded-byte
        attestation or a universal filesystem sandbox.
        The earlier public missing-entrypoint RED and basic mocked GREEN are
        retained; new safeguards need their own cause-correct RED before fix.
        Prove four real runs and rollback controls only AFTER a separate
        user-visible 2,340-request/20-build cost notice and explicit resume.
        The human approved a size:exception only for this coherent dispatcher
        PR after its observed 640 authored-line candidate was disclosed. This
        is not a separate exact ceiling or an exception for another unit.
        Work unit: 3778eda4e3fd16cfcd178bab8f6e27d8f6ca35dd.
        After the informational cost notice, four single-run diagnostics at
        source commit c99de0ff27cfd3daf50fc4461cdfba8784914164 validated
        all five operations, 100 samples per operation, and five schema builds
        per library. Each seed retained 1,000 authors, 10,000 posts, 50,000
        comments, identical SQLite sequences, and identical file hashes.
        The exact measured clone passed 75 focal, 139 benchmark, and 4,527
        full tests at 96.23% branch coverage with unchanged 258/266/282 gap
        sets. Ruff, mypy, both docstring gates, docs, and diff check passed.
        Full raw proof: /private/tmp/graphex-t4b2b2b2.csQs2s/. Independent
        verification and hosted gates remain pending, so this task stays open.
        A later independent control at `ce47fc4` exposed a mkdir-to-open
        ownership race: on synthetic child failure the dispatcher removed a
        replacement directory and its pre-existing result. The focused
        correction recorded a pathname identity before descriptor acquisition,
        but later independent verification proved a replacement before that
        first stat still reached the child and deleted a foreign regular result
        and directory. A second chronological RED failed regular-result and
        empty-directory preservation controls at that adjacent boundary. The
        final policy does not delete failed-attempt directories or unvalidated
        files automatically; these remain for manual inspection. Before-open
        regular-file, empty-directory, and symlink replacements are also
        regression-covered. The first chronological RED failed two
        before-open preservation controls; root Python 3.12.11/core 3.2.13
        GREEN passed three before-open and two before-first-stat controls.
        Independent native-3.3 proof at `3fa9390` passed 80 focal, 144
        benchmark, and 4,532 full tests at 96.23% branch coverage; complete
        258/266/282 gap sets match a fresh integration base. Eleven real
        filesystem controls passed. The actual configured standard docstring
        gate then found candidate-only DOC005 in this preservation test; a
        separate chronological RED preceded its truthful Raises correction.
        Both docstring gates and native focal tests pass after that correction.
        Full-suite and independent checks on the new exact head, four fresh
        real-profile diagnostics, and hosted gates remain pending. Earlier
        4,527 tests and four diagnostic runs are historical, not fresh proof
        for this corrected head.
        Leave three-run publication and quiet measurements for later slices;
        Engram mirror remains pending. Roll back only this dispatch slice.
  - [ ] T4c — Complete Playground/example and migration guidance, verify
    quiet measurements and docs without relabeling old results.
  - [ ] T4d — Resolve package SemVer by separate product decision, then run
    final independent and hosted release-readiness gates. No main merge or
    publication follows automatically.

## Progress and next step

T0-T3 and the JSON, validation-cache, HTTP privacy, subscription privacy,
and T4q capability-test children are integrated through
`fc0d730a87b90c5bc57387fad61a09ca761aac2a`.
PR #222 passed exact-head hosted checks before that integration-only merge;
its integration-push run `36945214190` and tracker run `36945219668` each
passed 15 validations, with three publication jobs skipped; both tracker
Codecov checks succeeded. This floor child
history-merges that reviewed integration without importing the rejected regex
branches. Its source diff remains limited to the GraphQL-core floor/locks,
readiness contracts, and current guidance; the package version stays 3.1.1.
The earlier `8093da0` floor head passed local native-3.3 checks but failed
project Codecov at 94.96%; no gate was waived. T4q PR #223 passed all 15
validation jobs and both Codecov checks before its integration-only merge.
The floor branch now history-merges T4q through `a886e60`; this new combined
head requires fresh local, independent, and hosted checks. The
new per-library benchmark comparison choice is resolved, while package SemVer
and T4b-T4d remain pending. Published 3.1.1 main/tag and canonical benchmark
files remain unchanged. Draft tracker #212 has no main merge, tag,
publication, or dispatch authorization. Engram mirror remains pending without
an authoritative runtime identity.

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

### T3a independent verification

- Exact candidate `2a136cc84e3a3c23861e3808431cfa43aa791e0b` passed an
  independent clean-clone check: 143 focused tests under each core version,
  4,385 full 3.2.13 passes, 7 skips, and 96.23% branch coverage; changed-line
  coverage was 100% (9/9). Ruff, mypy, both docstring gates, docs, and diff
  checks passed; five baseline docs anchor warnings remain. The parent
  independently spot-checked all 143 focused tests on 3.2.13. Proof:
  `/private/tmp/graphex-33-t3a-independent.3MRsAo/`.

### T3a remote delivery (local-only recovery checkpoint)

- Approved issue [#209](https://github.com/eamigo86/django-graphex/issues/209)
  remains open. [Child PR #215](https://github.com/eamigo86/django-graphex/pull/215)
  merged 372 authored changed lines, no exception, from head
  `c05c362c74264412325dc5ec950a583e3081f132` into integration.
- [Child CI](https://github.com/eamigo86/django-graphex/actions/runs/36920087103)
  passed all 15 validation jobs and both Codecov checks; three publication
  jobs skipped. Conventional merge `5cdd2b130af59ee65b35e71887625de3a615cf06`
  has tree `39dcee3d367f770103742e2662cfd49dc3e345a9`, identical to the
  reviewed child tree.
- [Integration push CI](https://github.com/eamigo86/django-graphex/actions/runs/36920536950)
  and [draft tracker CI](https://github.com/eamigo86/django-graphex/actions/runs/36920542837)
  each passed all 15 validation jobs on exact merge `5cdd2b13`; both tracker
  Codecov checks passed and three publication jobs skipped in each run.
  [Tracker #212](https://github.com/eamigo86/django-graphex/pull/212) remains
  draft, links T3a while reserving T3b/T3c/T4, and has not merged to main.
  Main remains `bb415efc10e4a4b85079344b1c3c607de7a06daa`; tag v3.1.1
  is unchanged. This checkpoint is local-only, not part of the green tracker
  tree; its Engram mirror is still pending runtime identity.

### T3b local verification

- RED on official 3.3.0: a frozen `FieldNode(arguments=None)` raised
  `TypeError` in cost estimation, while the historical NativeList test
  expected a `GraphQLList(ErrorType)` constructor error that 3.3 no longer
  raises. Four existing unpaginated-list cost tests share the same cause.
- GREEN: absent arguments act as an empty sequence without mutating the AST.
  The new regression checks `DEFAULT_PAGE_SIZE` fallback and node identity.
  NativeList still retains the uncompiled `ErrorType`; the compiled-schema
  test still checks the final `[ErrorType]` shape. Only the stale upstream
  constructor assertion changed. All 41 focused tests passed under both
  installed 3.2.13 and isolated official 3.3.0.
- A clean real local clone imported candidate source and installed 3.2.13.
  Its unchanged full runner passed 4,386 tests, 7 skips, 3 baseline warnings,
  7 subtests, and 96.23% branch-enabled coverage against the unchanged
  95.01% gate. Changed-line coverage was 100% (1/1). Ruff, mypy, both
  docstring gates (strict TOTAL 0), docs, and diff checks passed; the five
  established docs anchor warnings remain. Proof:
  `/private/tmp/graphex-33-t3b.quJD66/`.
- Full 3.3 diagnostic (no exclusions) reported 16 HTTP/field failures,
  4,370 passes, 7 skips, and 67 warnings, mostly on the known pending
  dual-iterator queryset path. These failures are not accepted final-state
  skips; T3c owns the separate fix. Roll back only this T3b cost loop,
  focused regression, stale fixture expectation, guide, and checkpoint.
  Remote delivery remains pending; mirror pending.
  Local work-unit commit: `8c9ab8fc2b156dbd6ad03e59b96ef9d142480764`.

### T3b independent verification

- Exact candidate `ef3c51263efc5fc90ae151d502a4770553819c8e` passed
  41 focused tests under each core version. A clean 3.2.13 clone passed 4,386
  tests, 7 skips, 3 baseline warnings, 7 subtests, 96.23% branch coverage,
  and 100% changed-line coverage (1/1). Ruff, mypy, both docstring gates,
  docs with five baseline anchor warnings, and diff checks passed. The parent
  independently spot-checked all 41 root-focused tests. Proof:
  `/private/tmp/graphex-33-t3b-independent.RWhjuV/`. T3c remains pending.

### T3c local verification

- RED under official 3.3.0: two real HTTP queryset operations returned a
  coroutine instead of a GraphQL result, and the predicate classified a
  dual-protocol Django queryset as async. The diagnostic emitted unawaited
  coroutine warnings. All three new regressions passed as 3.2.13 controls.
- GREEN: only native 3.3 execution receives `is_async_iterable`. Its predicate
  uses native async recognition but prefers synchronous completion for values
  that are also native synchronous iterables. Real queryset HTTP reads and a
  flagged atomic mutation evaluated on the request thread; the mutation's
  row rolled back. Async-only values remain classified async. Existing custom
  backend, cache-invalidation, HTTP security, and transport tests remained
  green: 168 related tests passed under each core version.
- Clean real clone candidate imports were verified for each core version.
  Unchanged full runner passed 4,389 tests, 7 skips, 7 subtests, and 96.21%
  branch-enabled coverage under both 3.2.13 and official 3.3.0, above the
  unchanged 95.01% gate. Each had the same 3 established warnings and no
  unawaited coroutine warning. Native 3.3 changed-line coverage passed at
  100% (5/5). Root 3.2.13 diff coverage was 60%, BELOW the required 95.01%
  hosted patch gate; this is an acceptance gap, not an exception. Ruff
  format/lint, mypy, both docstring gates (TOTAL 0), Zensical docs
  with five baseline anchor warnings, and diff checks passed. Proof:
  `/private/tmp/graphex-33-t3c.zDp9a3/`.
- Rollback only the HTTP predicate, focused regressions, view guidance, and
  this checkpoint. T3b remote push remains blocked by auto-review pending
  direct human authorization. T3c is local-only; T4 floor/locks/version and
  migration remote integration have not started. Engram mirror remains pending.
  Local work-unit commit: `24e52238148514925d8cdac842331f87459f7e06`.

### T3c root patch-gate correction

- The first root 3.2.13 diff-cover run was 60%, below the required 95.01%,
  because the native-3.3 forwarding branch had no root-runner regression.
  This failure was not waived or hidden. A new test injects the stable
  `executor_class` capability into the root runner, records a real view's
  execute options, and checks the legacy backend alias plus sync-only,
  dual-protocol, and async-only predicate decisions.
- RED on a clean prebehavior clone at T3b `b8abfbf`: the new test failed with
  missing `is_async_iterable` forwarding. GREEN on the T3c candidate: all
  four focused queryset tests passed under each core version. No production
  source change or dependency reinstall was needed for this correction.
- Clean real candidate imports resolved to its source and core 3.2.13 or the
  isolated official 3.3.0 overlay. The unchanged full runner passed 4,390
  tests, 7 skips, 7 subtests under each core: 96.23% branch coverage on 3.2.13
  and 96.21% on 3.3.0, both above 95.01%. Diff-cover now passes 100% (5/5)
  independently under BOTH versions, with no exclusions or merged coverage.
  Each run had only the 3 established warnings, no unawaited coroutine warning.
  Ruff, mypy, both docstring gates (TOTAL 0), docs with five baseline anchor
  warnings, and diff checks passed. Proof:
  `/private/tmp/graphex-33-t3c-gate.SiiZ16/`.
- The correction belongs to the same local T3c slice; T3b remote push remains
  blocked pending direct human authorization. Independent verification of this
  final candidate is recorded below; T4 remains pending. Engram mirror pending.
  Correction commit: `d3d1125789e928528c4247ece4f13c0187fbee8f`.

### T3c independent verification

- Exact candidate `bab1be79618b51c6c21a25f18ca079eef9df5d34` passed
  four new and 169 related tests under each core. Clean full suites each
  passed 4,390 tests, 7 skips, 7 subtests, and the same three baseline
  warnings; branch coverage was 96.23% on 3.2.13 and 96.21% on 3.3.0.
  Separate coverage XML files yielded 100% diff coverage (5/5) on each.
- Ruff, mypy, both docstring gates (TOTAL 0), docs with five baseline anchor
  warnings, and diff checks passed. No new coroutine warnings or defects were
  found. The parent spot-checked all four native 3.3 regressions. Proof:
  `/private/tmp/graphex-33-t3c-independent.33W2kc/`.
- T3 local acceptance was verified. At this historical checkpoint, T3b/T3c
  remote delivery was blocked pending fresh human authorization; the later
  integration is recorded below. Engram mirror remains pending without a
  registered runtime identity.

### T4a start and T3 checkpoint reconciliation

- The local-only tracking commit `c33c4e4a054c9777fdc9ed541822b0babe3fa6c1`
  reconciled the final T3 evidence. T3b behavior commit
  `8c9ab8fc2b156dbd6ad03e59b96ef9d142480764` merged via PR #216 at
  `637dcb714d3ec01e3df1a6d5a0115d39583eea35`; T3c behavior commit
  `24e52238148514925d8cdac842331f87459f7e06` and correction
  `d3d1125789e928528c4247ece4f13c0187fbee8f` merged via PR #217 at
  `61b8784e4d9779a48f62b0209f9abfa62e5323cd`. The latter tree is
  `19064b4ecd6dbc75083e3dff998567ea239e46ce`, identical to reviewed
  history-sync head `0e8b1d7e63049e6b329cb152ded1c8511d73a3a7`.
- Integration-push run 36927916167 and draft-tracker run 36927925471
  each passed 15 validation jobs and skipped three publishing jobs; both
  fresh tracker Codecov checks succeeded. Historical rejected-push notes
  above are past evidence, not an active block. The final independent T3c
  clean-clone proof is `/private/tmp/graphex-33-t3c-independent.33W2kc/`:
  4,390 full passes under each core, 7 skips, three established test warnings,
  coverage 96.23%/96.21%, separate diff coverage 100% (5/5), and five
  established docs-anchor warnings. No new coroutine warning.
- T4a route: delegated direct, multiple non-trivial metadata, lock, test,
  and public-doc files. Current user AGENTS.md enables strict TDD; use the
  existing root pytest runner and clean real local clone. Authored child
  budget ≤400 lines, generated lock lines reported separately. No source
  behavior, benchmarks, package version, root environment, main, or remote
  state changes are authorized in this local unit. Mirror remains pending.

### T4a local verification

- RED: `.venv/bin/python -m pytest tests/test_graphql_core_33_readiness.py
  --no-cov -q` failed both new contracts for the old 3.2.13 floor and current
  README. GREEN: the new current contract plus 3.1.1/3.1.0 release and CI
  contracts passed 51 tests with `--no-cov -q`. Historical 3.1.1 notes still
  describe the 3.2.13 security patch; the new Unreleased entries describe
  current source without inventing a package version or publication date.
- Both lockfiles resolve graphql-core 3.3.0 and retain django-graphex 3.1.1;
  a TOML package comparison found changes only in the graphql-core package
  and the local project's GraphQL requirement. Every other package pin,
  including Playground Django 6.0.8, is unchanged. Root and Playground
  `uv lock --check --no-build` passed. The initial resolver refreshed unrelated
  Autobahn/cbor2 packages, so only its verified official GraphQL metadata was
  retained before the checks; no broad dependency refresh was accepted.
- A clean real local Git clone imported candidate source and official 3.3.0
  from the existing isolated overlay; the root `.venv` still imports 3.2.13.
  Its unchanged `.venv/bin/python -m pytest` runner passed 4,392 tests,
  7 skips, 7 subtests, 3 established warnings, and 96.21% branch coverage
  against the unchanged 95.01% gate. Diff-cover reported no covered runtime
  lines changed (N/A); no waiver or exclusion was used. Proof:
  `/private/tmp/graphex-33-t4a-proof.Co6BJ6/`.
- Ruff format/check, mypy, standard and strict docstring gates (TOTAL 0),
  Zensical docs build, and diff checks passed. A second mypy run with
  `MYPYPATH` set to the official 3.3 overlay also passed; its verbose log
  confirms GraphQL imports from that overlay rather than root 3.2 stubs.
  Zensical retained five established anchor warnings. No local project build, root environment
  reinstall, benchmark rewrite, main merge, tag, or remote operation occurred.
  Runtime harness is the real full 3.3 suite above; it covers HTTP and
  subscriptions through candidate-source imports, not an editable install.
  Rollback only T4a's runtime bound, two GraphQL-only lock changes, current
  readiness tests, Unreleased notes, and current requirements/view guidance.
- Hosted 3.3 matrix, security/PG, and publication-readiness checks await
  authorized delivery. T4b new comparison profile, T4c example/migration
  guidance, and T4d SemVer/final gates remain pending. The Engram mirror
  remains pending without a registered runtime identity.
- T4a work-unit commit: `cbcd1da815f8bea95607eb6ec5251275df42b3fc`.
  Its first committed slice has 274 authored changed lines and 16 generated
  lock lines (290 total) against integration `61b8784e`; this local-only
  proof checkpoint adds no source or dependency changes. The initial RED log
  is `/private/tmp/graphex-33-t4a-red.log`; final focused and full-suite logs
  are `/private/tmp/graphex-33-t4a-focused-final.log` and
  `/private/tmp/graphex-33-t4a-proof.Co6BJ6/full-suite.log`.

### T4a independent verification

- Exact candidate `1729ece22b5b8978026e25a77bdb3a1fc447303b`, tree
  `ed71ab15a2efabb64fc06f3ccbdf91ae8cc7e8f0`, passed independent clean-clone
  checks: 51 focused tests and 4,392 full native-3.3 passes, 7 skips,
  7 subtests, three established warnings, and 96.21% branch coverage against
  the unchanged 95.01% gate. Diff-cover passed with no covered runtime lines
  changed (N/A). The parent separately spot-checked both new contracts.
- Ruff checked 461 files; mypy checked 79 source files while its verbose log
  resolved GraphQL from the official 3.3 overlay. Standard and strict
  docstring gates had TOTAL 0, and docs retained exactly five established
  anchor warnings. Root and Playground offline/no-cache lock checks resolved
  123 and 47 packages; seven in-memory negative controls rejected the old
  floor, wrong core generations, and mismatched project versions. Proof:
  `/private/tmp/graphex-33-t4a-independent.0r5pCl/`.
- Source metadata is still 3.1.1; the reused root editable distribution
  metadata reports 3.1.0. It is not an artifact-install or release-version
  proof, and no root reinstall occurred. Hosted 3.3 matrix, PostgreSQL,
  security, Playground, artifact, base-install, and Codecov checks remain
  pending until an authorized child PR runs. T4b-T4d and package SemVer remain
  pending; no main merge, tag, or publication is authorized.

### T4a privacy-prerequisite history sync

- The independently verified native-3.3 HTTP child `0c4917e` merged through
  PR #221 as `a99bbd67` with identical source tree. Its integration and
  tracker runs `36944307169` and `36944311598` each passed 15 validation
  jobs; both tracker Codecov checks passed and publication jobs skipped.
- The independently verified SSE/WS child `1eedc4e` passed 84 startup/core
  cases, 37 focused and 90 related tests, full suites of 4,425 under each
  core, coverage 96.23%/96.19%, and 100% patch coverage (22/22). Its hosted
  run `36944908273` passed all 15 validations and both Codecov checks; three
  publication jobs skipped. PR #222 merged only into integration as
  `b5a5207ebb80b70e95b49880b1b51b327500a5b7`, tree
  `5c56559b647ead22eedfce49b78ba8b765561d25`. Post-merge integration
  run `36945214190` and tracker run `36945219668` each passed 15 validation
  jobs, skipped three publication jobs, and both tracker Codecov checks passed.
- This T4a correction merges `b5a5207` into existing floor branch `4cd2f7d`
  without rebasing or rewriting either history. Original T4a RED/GREEN and
  independent proof remain valid for their exact earlier candidate; the new
  combined tree requires its own full native-3.3 and hosted checks. Floor
  PR #218's earlier Playground/Python 3.14 failures are historical, not waived.
  Roll back only this floor child if its fresh gates fail. The rejected T4s
  regex branches, frozen benchmarks, and dated 3.1.1/3.1.0 notes remain out.
- History-preserving merge `8093da0ecac2038a588adc020e8d7f0418b7145f`
  has tree `4f0981b58fbd136feb11bd0941cb51b2c6b46aec`. The focused
  floor diff against `b5a5207` is 352 authored plus 16 generated lock lines,
  368 changed lines total. A clean real clone imported source plus official
  GraphQL-core 3.3.0: 51 readiness, 66 HTTP/security, and 90 SSE/WS focal
  tests passed. The unchanged full runner passed 4,427 tests, 7 skips,
  3 established warnings, and 23 subtests at 96.19% branch coverage versus
  the unchanged 95.01% gate. Changed-line coverage is N/A because this floor
  slice changes no covered runtime line. Playground passed 59 tests on both
  Python 3.12 and 3.14 with native 3.3. Proof:
  `/private/tmp/graphex-33-t4a-resync.xqRKvD/`.
- Root and Playground offline no-build lock checks passed for 123 and 47
  packages. TOML comparison found only graphql-core and the project's GraphQL
  requirement changed; all other pins, eight historical benchmark results,
  constraints, versions.env, and dated changelog sections are unchanged.
  Ruff, native-3.3 mypy (79 files), both docstring gates (TOTAL 0), docs with
  five established anchor warnings, and diff checks passed. No own build,
  root environment install, remote operation, main merge, tag, or publication
  occurred in this local work unit. New floor-head independent and hosted
  checks remain pending; T4b-T4d and package SemVer remain undecided.

### T4b1 local proof and remaining gate

- The corrected profile child `b0f2fdba2888296ef117aa304602558ff11203a9`
  fixes the independent Graphex and Graphene startup blockers (345 authored
  plus 47 installer-observed freeze lines). Its clean native-3.3 suite passed
  4,438 tests at 96.23% branch coverage. Conventional merge
  `f7d39a4ffba8903371b4a412e783cade4fbee57c` carries it into this setup
  child without rewriting either history; focused setup diff remains 358 lines.
- Two fresh offline setup recreations produced four byte-identical freezes per
  round with valid activation and entrypoints. All four real seeded five-step
  HTTP workloads passed with mutation rollback; all 20 SQL counts matched the
  frozen contracts. Clean setup clone passed 56 benchmark and 4,444 full
  native-3.3 tests at 96.23%; Ruff, mypy, docstrings, docs, Bash, and pinned
  ShellCheck passed. Proof: `/private/tmp/graphex-t4b1-correction.efG5xu/`.
  Independent and hosted checks remain pending; T4b2 measurements are not run.
- Profile child `783385d35d25fdcfd7f91e595949e9076199016b` records observed
  per-library constraints and validates the selected direct pins. Its clean
  clone passed 46 benchmark tests and 4,434 full native-3.3 tests at 96.23%
  branch coverage. Setup commits through `624503147705866e59f781091ea593ce6cb3c369`
  add fail-closed final-path installation and the historical published-wheel
  pin; the exact clean clone passed 52 benchmark tests and 4,440 full native-3.3 tests at
  96.23%, above the unchanged 95.01% gate. Both runs had seven established
  skips, three warnings, and 23 passed subtests.
- Chronological RED before source: five new tests failed for absent profile,
  setup, and historical-wheel behavior. Separate new RED tests exposed ambient
  UV credential variables and venv relocation; both passed after focused fixes.
  Focused GREEN: 14 passed. Four stacks
  were recreated twice offline from the isolated cache with exact freezes;
  an empty-cache control failed without promoting or leaving a target venv.
  A fresh four-stack replay used isolated HOME, retained final-path activation
  scripts and console commands, and passed exact freeze comparisons.
  The published historical 3.1.0 wheel imported from site-packages when run
  from the benchmarks directory without a source-shadowing PYTHONPATH.
- Ruff, native-3.3 mypy (80 files), standard and strict Google docstrings
  (TOTAL 0), docs (five established anchor warnings), Bash syntax, and diff
  checks passed. Shellcheck was unavailable and was not waived or installed.
  No covered package-runtime line changed, so package patch coverage is N/A.
  Proof is under `/private/tmp/graphex-t4b1.8H68G9/`. Independent review,
  hosted CI, T4b2 runner, new measurements, T4c, and T4d remain pending;
  no GitHub delivery, main merge, tag, or publication occurred here.

### T4b1 named-profile bootstrap (focused local child)

- Independent verification reopened T4b1a/b: the source-backed Graphex venv
  cannot start without its declared Pydantic/dateutil/unidecode dependencies,
  and the unchanged Graphene adapter cannot import its django-filter field.
  Metadata/freeze equality alone is not a runnable-stack contract. Add failing
  source/adapter dependency tests first, then observed exact freezes and all
  five real HTTP workload contracts per library. Correct this profile child
  before history-merging it into the setup child; both remain local pending
  independent and hosted revalidation. Historical artifacts stay frozen.
- Correction commits `144b8ad177b55c5f1d55bcf28ff305f888d7445c` and
  `27a4474c5826f1de8d99e28785d7124c99e6de41` add two cause-correct RED
  tests, fail-closed required-package checks, and installer-observed 13-package
  Graphex/Graphene freezes. Six profile tests and 50 benchmark tests passed;
  all four unchanged seeded five-operation HTTP contracts passed with rollback
  and expected SQL counts, without timing publication. The clean native-3.3
  full suite passed 4,438 tests at 96.23% branch coverage; independent and
  hosted checks remain pending. Proof: `/private/tmp/graphex-t4b1-correction.efG5xu/`.
- Human-selected future package version is 4.0.0, not yet applied or released.
  The approved new comparison uses Strawberry 0.328.0 plus
  strawberry-django 0.90.0 on core 3.3.0; the earlier 0.320.1/0.86.4
  optimizer failure remains historical diagnostic evidence.
- Before this source unit, an isolated Python 3.12.11/Django 6.0.8 venv
  passed the unchanged seeded 20×10×5 Strawberry response contract in three
  SQL queries and verified mutation rollback. The four observed dependency
  freezes live under `/private/tmp/graphex-t4b1.8H68G9/`.
- Route: delegated direct; ownership is a new named-profile manifest and
  per-library observed constraints, preflight/bootstrap, benchmark tests,
  concise guide, and this narrow checkpoint. Strict TDD is enabled by current
  AGENTS.md: RED profile contract before implementation, then GREEN/refactor.
  Focused runner is `.venv/bin/python -m pytest tests/benchmarks --no-cov`;
  full native-3.3 runner retains the 95.01% branch gate in a clean clone.
  No canonical result/freeze, package version, benchmark timing, main, tag,
  or publication change belongs to this unit. Engram mirror remains pending.

### T4a capability-test history sync

- T4q PR #223 passed all 15 validation jobs and both Codecov checks before
  integration-only merge `fc0d730a87b90c5bc57387fad61a09ca761aac2a`.
  Conventional merge `a886e60d8d58f6d1400b96003d0eedd45e275a8e`
  preserves the old floor history and adds only those reviewed tests/docs.
- The combined clean-clone native-3.3 suite passed 4,432 tests, 7 skips,
  23 subtests, and the 3 established warnings at 96.23% branch coverage.
  Its XML has 258 missed lines and 266 partial branches, exactly matching
  T4q's 3.2 baseline; all six previously uncovered capability sites passed.
  Conservative projected line coverage is 95.018064%, an inference rather
  than a hosted Codecov verdict. Fresh independent and hosted checks on this
  combined floor head are still required before integration-only delivery.

### T4b1c legacy bootstrap safety (local)

- Chronological RED: the new disposable offline-cache regression lost an
  existing `.venv-graphex/keep.txt` because the old script deleted its target
  before installation. GREEN: 15 legacy bootstrap contracts passed, including
  directories, files, live/dangling symlinks, whole-request preflight, cache
  failure, and rollback after a later install failure.
- A separate real offline run without the local promise wheel failed while
  resolving Graphene and left all four venv paths and freeze files absent.
- A clean clone installed all four historical stacks offline into fresh final
  paths using the isolated cache and the verified upstream promise wheel.
  Each freeze matched its installed environment; all used Python 3.12.11,
  Django 6.0.6, and core 3.2.11. GraphEx 3.1.0 imported from the published
  wheel in site-packages, not this checkout. No timing or canonical result was
  written. Proof: `/private/tmp/graphex-t4b1c.sX1F3i/`.
- The exact clean-clone native-3.3 suite passed 4,453 tests, 7 skips,
  3 established warnings, and 23 subtests at 96.23% branch coverage against
  the unchanged 95.01% gate. All 65 benchmark tests, Ruff, native-3.3 mypy80,
  both docstring gates (TOTAL 0), docs with five established anchors, Bash,
  pinned ShellCheck, and diff checks passed. No covered package-runtime line
  changed, so package diff coverage is N/A.
- Rollback only the historical setup script, its safety regressions, current
  benchmark guidance, and this checkpoint. Independent/hosted checks remain
  pending. Separate PR #225 Python-version fixture failures are not addressed
  in this child; no source package version, main, tag, or publication changed.
