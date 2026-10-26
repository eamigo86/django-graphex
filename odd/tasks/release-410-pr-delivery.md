# Deliver the prepared 4.1.0 integration for review

Status: CORRECTING_HOSTED_FAILURES. Repository locator: odd/tasks/release-410-pr-delivery.md.

## Objective and authority

Create one reviewable integration pull request for the locally prepared
4.1.0 work and observe its hosted checks. This task is remote delivery for
review, **not** a release or merge.

- The human explicitly authorized one integration PR with a size exception,
  creation and maintainer approval of a tracking issue, one push, and waiting
  for all applicable checks, using account eamigo86 in
  eamigo86/django-graphex. The parent executes and records remote operations.
- Destination: the existing codex/audit-400-remediation branch targeting main
  in eamigo86/django-graphex. Keep this branch; no renaming for a generic
  branch-naming example. Starting local HEAD:
  ede8f93bcf67d66e8bcc63945b117f017d084381. Main reference:
  5a155a059a4d3995ead1b639f08136e5d7619aec.
- The parent-verified integration range contains 400 files, 90,181 additions,
  2,698 deletions and 588 commits. These are full-range review counts, **not**
  an authored-only line count or a claim about generated-file proportions.
  The human explicitly accepted size:exception for this single integrated PR;
  the earlier local-only exception did not grant this remote authority.
- Create the issue from the repository's feature-request fields, confirm the
  status:approved label before PR creation, link it in the PR body, and apply
  exactly one PR type label: type:breaking-change. Record size:exception on
  the PR. The actual issue form labels a new request enhancement and triage;
  it does not grant status:approved automatically. Parent-verified duplicate
  and label checks are preparation evidence, not proof that a new issue or PR
  already exists.
- Explicitly forbidden: merge, tag, PyPI/TestPyPI publication,
  workflow_dispatch, benchmark timing, local release-artifact build,
  modifications to original project environments, and any automatic release
  action. On 2026-10-26 the human explicitly authorized correcting these CI
  failures with strict TDD, official dependency downloads in disposable
  environments and repeating all checks without reducing any threshold.
  Consult before incompatible changes. Keep existing public support bounds;
  do not blindly pin away real compatibility failures or relabel them passes.
  Parent may push verified corrections to the same authorized PR and observe
  the resulting jobs; no new PR or publication authority is inferred. Do not edit the
  completed odd/tasks/release-410-preparation.md history or the frozen
  benchmark worktree.

## Workflow and verification policy

- ODD delegated direct, not SDD. Parent owns the issue, approval, commits,
  exact-head push, PR creation/attachment, mirror and tracker updates. RDD is
  globally OFF; do not start review or change its mode.
- Delivery strategy: exception-ok from the human's explicit single-PR remote
  consent. Do not split this approved integration into a chain or infer that
  size approval grants merge or publication.
- Strict TDD remains enabled by the user and AGENTS instructions if any
  implementation change is later authorized: observe RED, then GREEN and
  REFACTOR with the supported interpreter at
  /private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python.
  This delivery-metadata unit changes no executable behavior, so RED is N/A.
  Its runtime harness is N/A; structural readback and whitespace checks are
  the applicable local checks. No shell script changed, so Shellcheck is N/A.
- Prior local evidence: 7,788 root tests passed, six known skips and 4,064
  subtests; pure branch coverage 95.54846% and combined 97.58617%; Playground
  98 passed; strict docs built 44 pages with valid anchors. Offline Ruff,
  mypy, docstring and Bandit checks passed. These are local checks, not hosted
  status for the pending PR. Keep 4.1.0 changelogs Unreleased.
- The selected f9f4eae benchmark is a local SQLite batch with changing host
  load and mixed graphql-core stacks; it is not a paired historical or
  PostgreSQL performance comparison. Historical evidence remains qualified.

## Tasks

- [x] RD-1 — Establish the approved issue and local delivery record. Create
  the issue using the actual feature-request headings, verify its identity and
  status:approved, then commit this task record as a Conventional Commit work
  unit. Record issue URL/number, approval evidence, commit and exact HEAD.
  Do not mark complete from a drafted body or from human approval alone.
  Issue: https://github.com/eamigo86/django-graphex/issues/253, author eamigo86;
  status:approved confirmed before PR creation, needs-review removed.
  Initial tracking commit: 414df951840f74cb0e475769c3e86f50683284e6.
  Structural readback and diff check passed; no executable change (RED N/A).
- [x] RD-2 — Push and open the linked, typed integration PR. Confirm the local
  candidate and push only its explicit HEAD to the retained branch under the
  authorized account/destination. Create one PR to main with a real approved
  issue reference replacing the draft placeholder; apply exactly one
  type:breaking-change label and size:exception; attach its URL to the task.
  Record pushed SHA, PR URL/number and label/readback evidence. No merge.
  Explicit-head push of 414df951840f74cb0e475769c3e86f50683284e6 succeeded
  through the authorized gh credential helper with push.followTags=false.
  PR: https://github.com/eamigo86/django-graphex/pull/254, open, non-draft,
  author eamigo86, target main, retained codex head. Closing issue #253 and
  exactly type:breaking-change plus size:exception verified on readback.
  PR attachment succeeded. This evidence is saved in the RD-2 metadata commit.
  RD-2 evidence commit and pushed PR head:
  b74659f1bb78b674cf4a182d150622b850d49445.
- [x] RD-3 — Observe applicable hosted checks for that exact PR head until
  terminal. Inventory the matrix, base-install, quality/security, coverage,
  PostgreSQL, docs, Playground, artifact and PR-policy jobs that actually run.
  Record pass/fail/skip with links and collect diagnostics for failures. On a
  PR event, production publication jobs are expected to skip; a skipped
  release job is not a test pass. Do not infer CI-green from local proof or
  from incomplete checks, and do not dispatch a workflow.
  Observation completed, acceptance FAILED: run 40380745811 for the exact
  b74659f head is terminal; PR is still open on main with that head.
  https://github.com/eamigo86/django-graphex/actions/runs/40380745811
  Final check inventory: 9 pass, 8 fail, 3 expected skips, 0 pending; no
  separate commit-status contexts. The superseded 414df95 run is excluded.
  Failed: six Python/Django matrix jobs, base-install and Codecov patch.
  Django 5.2/base collection reports declared to-many filters as unpublished;
  the scalar-versus-relation classification must be reproduced before fixing.
  Django 6.0 matrix reports 26/26/28 test failures, despite local/full coverage
  proof passing; bounded diagnosis is pending before corrective scope.
  Codecov patch: 96.41% against 96.43%, not the passing diff-cover gate.
  Passed: lint-and-security, diff-check, coverage, postgresql, get-version,
  docs-build, playground, release-artifact and Codecov project.
  Hosted pure branches 5,087/5,324 = 95.5485%; local changed-line gate 98%;
  Codecov project 96.72%. Artifact build, single wheel/sdist, external wheel
  smoke, dependency audit, checksums and upload passed in this PR run.
  Skipped: publish, create-release and deploy-docs, as required for this PR.
  Evidence: /private/tmp/pr254-ci-OI1y9k/ci-report.md and status.json.
  Observation is complete, not CI approval; no retry, gate relaxation or
  publication occurred. RD-4 remains pending until a corrected head is green.
  Read-only diagnosis: /private/tmp/pr254-ci-diagnosis-zTXvcP/diagnosis.md.
  The passing locked job uses Django 6.0.8/graphql-core 3.3.0/Pydantic 2.13.4;
  the failing django60 tox label actually resolves Django 6.1.2, graphql-core
  3.3.1 and Pydantic 2.14.1. This difference is observed, not a proven sole
  root cause. Base-install also imports optional Channels in a core test.
  Stale exact-version/message assertions are separate from genuine omitted-
  default symptoms requiring isolated reproduction. Do not pin dependencies
  blindly, lower coverage gates or narrow public support without approval.
  Public status comment records the failed candidate without private logs:
  https://github.com/eamigo86/django-graphex/pull/254#issuecomment-6424751980.
- [ ] RD-4 — Close the delivery record without releasing. When checks are
  green, record the exact head, PR/issue identities, terminal check evidence,
  remaining release gates and a next-step boundary for maintainer review.
  If a check fails or access blocks monitoring, record the blocker and leave
  closure pending. Parent updates the task file and Engram mirror together;
  no merge, tag or publication follows automatically.

## Authorized corrective work

Route: delegated direct, one bounded writer per work unit, independent final
verification. Parent owns tracker/mirror, work-unit Conventional Commits and
GitHub mutations. Keep the approved single-PR size exception; approximately
400 authored lines per coherent unit remains advisory, never code golf.
Read the prior diagnosis as evidence, not as an already-proven root cause.

- [x] RDC-1 — Reproduce and restore collection across Django versions and
  the base install. Isolate official dependencies outside the repository;
  record exact package versions and source origin in actual test processes.
  Capture RED for declared direct to-many filters on Django 5.2 and missing
  Channels imports; fix classification only after reproducing, preserving
  hidden-relation filtering protections. Keep optional subscription-only tests
  scoped to the extra without dropping unrelated core tests. GREEN focused
  tests on 5.2 and 6.x, related tests, locked full coverage >95.01% and docs.
  Own filtering/native_schema.py, implicated tests, matching docs/changelog.
  Rollback: only this relation/base-collection unit. Root cause reproduced:
  Django 5.2 marks ManyToManyField concrete=True, unlike 6.0; exclude M2M
  from the scalar-column arm without weakening relation/target-key guards.
  Move optional subscription imports into only the Channels-dependent test.
  Observed RED for collection and import; GREEN 5.2 focal 30/3 optional skips,
  security 68; 6.1 focused 73/3 skips. Base without Channels: 7,057 passed,
  39 justified optional/service skips, 4,064 subtests. Locked full: 7,788
  passed, 7 skips, 4,064 subtests. The new seventh skip applies only to the
  new no-Channels regression when Channels is installed; previous six remain.
  Branch 95.54846%, combined 97.58617%, raw/XML agree; Ruff, mypy, docstrings,
  Bandit, strict docs/44-page anchors and preservation passed. Parent inspected
  all diffs and reran both new/relevant contracts on 5.2 without Channels: PASS.
  Official disposable profiles are under /private/tmp/rdc1-YKI1Kn; originals
  unchanged. Report: /private/tmp/rdc1-YKI1Kn/RDC1-report.md.
  Local coherent commit: 866ddd276df527d2af47192221eb8eae8273eb5f.
  RDD remains OFF; independent final verification is still required.
- [x] RDC-2 — Restore omitted-default provenance across supported dependency
  patches, and replace stale assertions with semantic tests. Separate actual
  regressions from exact graphql-core patch and Python-specific type-repr
  expectations. Reproduce Boolean-map and IntOrString defaults while varying
  graphql-core/Pydantic deliberately; preserve explicit-invalid rejection,
  mutable-default freshness, printed SDL and introspection. RED before minimum
  compiler fix; no public scalar/default contract changes without approval.
  Own core/input_compiler.py, core/schema_pruner.py, implicated default/
  native-base/reserved-field tests and matching docs/changelog. Controlled
  reproduction isolated graphql-core 3.3.1 moving default memoization from
  GraphQLDefaultInput to GraphQLInputField; Pydantic 2.14 alone affects the
  stale invalid-Meta expectation, not the omitted-default regression.
  Additional pruner ownership is parent-authorized within the same compatible
  fix: retain only the exact existing _memoized_coerced_value for surviving
  fields whose named GraphQL type preserves identity, never by name/equality
  or for remapped input objects. Independent read-only assumption challenge
  found this safe only with unchanged permission filtering and per-execution
  deepcopy; it is not implementation approval. Require FULL-first AND clone-
  first mutable list/JSON omissions across two permission signatures, hidden-
  sibling and explicit-invalid refusal, and a warmed remapped-input negative
  control. Preserve Undefined identity and the effective memo-owner path.
  Parent updates only this ownership record while the writer holds pruner
  edits; record that authorized parent-only tracker change in preservation.
  Verify latest isolated and locked full
  suites plus focused cross-version cases. Report:
  /private/tmp/rdc2-6NNKYG/RDC2-report.md. Controlled RED separated 25 graphql-
  3.3.1 default failures from one Pydantic-2.14 stale exception assertion.
  Final focal: 134 passed in each of four disposable profiles. Locked and
  latest full: 7,793 passed, 7 justified skips, 4,064 subtests; branches
  5,095/5,332 = 95.55514%, combined 18,541/18,999 = 97.58935%, raw/XML agree.
  Latest's single JSONField deprecation belongs to RDC-3 below, not filtered.
  Ruff/import normalization and final focal, mypy, docstrings, Bandit,
  strict docs/44-page anchors and preservation passed. Initial missing-
  editable metadata failures are retained as harness failures, not hidden.
  Parent inspected runtime/test/docs diffs and reran four cache-security/
  freshness cases on graphql-core 3.3.1: PASS. Independent full normalized-
  tree verification still pending. Local coherent commit:
  e649ca1de6a06560c23f1d82bf626f8a962c86ec. One automatic local-commit
  approval review timed out before process creation; its explicitly allowed
  single retry succeeded. No source/proof retry or remote mutation resulted.
- [ ] RDC-3 — Close the real Codecov patch deficit without weakening gates.
  Read exact missing lines/denominator from hosted evidence where available,
  add meaningful regression coverage for real branches, and retain every
  coverage threshold and exclusions. Document the existing locked-versus-tox
  dependency policy accurately without narrowing support or renaming away
  existing public tox commands. Full branch/combined/diff >95.01%, existing
  stricter Codecov target, quality/security, docs/examples/Playground checks.
  Rollback: only new branch tests and compatibility documentation; no gate
  reduction. Evidence/commit: pending.
  Read-only exact-head Codecov map: /private/tmp/pr254-codecov-map-h79iOh/diagnosis.md.
  Terminal GitHub patch check says 96.41% at 18:54:44; later public report at
  18:55:30 says 96.95% (3,641 changed executable lines: 3,530 hits, 50 misses,
  61 partials). Do not replace the failed check's result with later API data.
  A fresh corrected-head check must reconcile this; no padding unrelated tests
  or lowering thresholds. Native-schema partial lines are outside the PR diff.
  New latest-only warning to evaluate: tests/test_exact_null_filtering.py:265,
  RemovedInDjango2028Warning for JSONField exact=None used as the JSON-null
  oracle. Own this test's compatible oracle update if supported JSONNull is
  available, keeping JSON scalar null distinct from SQL NULL and retaining
  Django 5.2/6.0 behavior. No runtime-filter semantic change or warning filter.
  Local test/documentation work PASS: /private/tmp/rdc3-nyjt69/RDC3-report.md.
  JSONNull availability and deprecation verified in official installed source;
  RED on 6.1 with only that warning promoted to error, GREEN across 5.2/6.0/
  6.1. Related exact-null/docs contracts: 18 passed in each profile. Parent
  reran latest exact-null plus tox contracts with deprecation-as-error: PASS.
  Contributor guide accurately describes existing ranges; one new executable
  docs contract checks them, with no renamed factors or changed support bounds.
  Ruff, mypy, docstrings, Bandit, strict docs/44-page anchors and preservation
  passed. Independent normalized full suites and fresh hosted Codecov remain
  pending; no gate has been lowered. Local coherent commit: pending now.
- [ ] RDC-4 — Independently verify, push and repeat all hosted checks. Verify
  protected original/frozen data and environments before/after; no benchmark
  regeneration. Push only the candidate branch through eamigo86 with no tags.
  Inventory every actual check tied to the resulting exact PR head; require
  all applicable jobs and external Codecov statuses green, with only expected
  publication skips. Retain failed prior evidence; no retry-until-green or
  unsupported success claim. Evidence/commit: pending, then close RD-4.

## Progress and next step

Issue #253 was created under eamigo86 and its status:approved label was
confirmed before PR creation: https://github.com/eamigo86/django-graphex/issues/253.
The obsolete status:needs-review label was removed under the human's explicit
approval. RD-1/RD-2 delivery and RD-3 terminal observation are complete;
RD-4 CI-green closure is pending because eight checks failed.
The CLI rejected combining --template with --body-file before making a remote
change; the successful creation used the actual template headings in the body
and existing enhancement/status labels instead. No duplicate issue was created.
PR #254 is open and attached. Current observed head b74659f and run
40380745811 have 9 pass/8 fail/3 expected skips/0 pending. Source diagnosis
was read-only at that stage. The human has now authorized the bounded
corrective units above with TDD, disposable official dependencies and all
checks repeated. RDC-1/RDC-2 passed locally; next RDC-3 evaluates the new
JSON-null test warning and compatibility documentation, then independent
verification and a fresh hosted Codecov status. Keep gates/support intact;
consult before any incompatible change. Prior local tracking commit 6b620e0
is unpushed and can travel with verified corrections, not a standalone rerun.
No merge, tag, workflow dispatch or publication. Rollback for this metadata
unit is this task file and its external draft bodies; no package source or
measurement data is part of the unit.
