# Deliver the prepared 4.1.0 integration for review

Status: READY_FOR_AUTHORIZED_TAG. Repository locator: odd/tasks/release-410-pr-delivery.md.

## Current 4.1.0 release authority and plan (2026-10-27 UTC)

The maintainer has now given final, conditional approval: close both 4.1.0
changelogs with the real UTC release date, verify the documentation-only
change, and create/push tag `v4.1.0` **only after every check on the dated
`main` commit passes**. That tag is intended to trigger PyPI publication,
the GitHub Release and production documentation deployment. No further
approval is needed for this same conditional publication; a failing,
missing or pending check blocks the tag rather than becoming an exception.
The earlier approval-pending statements below are historical and superseded
only by this explicit final authorization. The one-time Codecov exception
for PR #254 remains historical and does not waive the new checks.

- Date: `2026-10-27` UTC, confirmed by the official clock before editing.
  New local branch `codex/release-4.1.0-close` starts at verified merged
  `main` SHA `2fcdbd1f960ecbcf2695d6242c08ce260e26b8fb`. The old
  `codex/audit-400-remediation` branch retains local metadata commit
  `5ca9d6e659f35a5f873142761f5ab1db6c274980`; this tracker was restored
  exactly from that commit before dated-note edits, preserving prior proof.
  `pyproject.toml` still declares version `4.1.0` (read-only confirmation).
- Scope: change only the 4.1.0 headings in root and docs changelogs from
  `Unreleased` to the confirmed UTC date, preserving all notes and anchors.
  The parent owns the Conventional Commit, normal fast-forward push to the
  authorized `main`, complete fresh check inventory, annotated tag push and
  immutable artifact verification. Do not change thresholds, exclusions,
  configuration, runtime code, support bounds or benchmark evidence. No
  local package build or installation is part of this documentation unit.
- Dated closure was committed as
  `72808056f1cc16e99a29a792597452a315fbaa1c`
  (`docs(release): finalize 4.1.0 changelog date`) and normally
  fast-forward pushed through the verified `eamigo86` account with
  `push.followTags=false`. Fresh readback shows remote `main` at exactly
  that SHA. The commit changes only the two dated headings and this
  tracker history. No tag or publication occurred. Its automatic run
  https://github.com/eamigo86/django-graphex/actions/runs/40435107342 is
  terminal **FAILURE** on this dated head: 8 Actions failures (six matrix,
  base-install and coverage), 7 passes and 3 expected skips. A representative
  Python 3.12/Django 6 job reported 5 failed, 7,789 passed, 7 skipped and
  4,064 subtests. Base-install also reported the same five failures with
  7,058 passed, 39 skipped and 4,064 subtests; coverage reported the same
  five with 7,789 passed, 7 skipped and 4,064 subtests. The failures were
  stale assertions or release-section splits that assumed the 4.1.0 heading
  was always `Unreleased`. The initial four passing changelog-consistency
  tests did not exercise those contracts. The official PyPI 4.1.0 JSON
  preflight returned 404; no tag or publication has occurred. Tagging stays
  blocked until a new exact head passes every applicable check. No source,
  threshold, exclusion or configuration change is authorized by this failure.
- Route: delegated direct because the coordinated tracker restoration and
  two-document release closure span multiple files. Forecast under 400
  authored lines. Strict TDD remains enabled, but RED/GREEN and a runtime
  harness are N/A because no executable behavior changes. Applicable local
  evidence is the existing focused docs/changelog contracts, exact-heading
  and preservation readback, and `git diff --check`. Delivery uses the
  existing approved release scope, not a newly invented pull request.

### Release tasks

- [x] R41-1 — Date only the two 4.1.0 changelog headings to `2026-10-27`,
  verify the existing focused documentation contracts and preserve every
  note, anchor and prior release section. Precommit comparison to merged
  baseline `2fcdbd1f960ecbcf2695d6242c08ce260e26b8fb` showed one heading
  substitution per file and no other changelog byte changes.
  Focused check command:

  ```sh
  PYTHONDONTWRITEBYTECODE=1 /private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python -m pytest tests/test_docs_changelog_consistency.py --no-cov -p no:cacheprovider
  ```

  Canonical result: 4 passed in 0.09s. An earlier invocation with a blank
  `addopts` override also passed but was not accepted as verification
  evidence; this recorded run used the configured options. `git diff --check`:
  PASS.
  Runtime harness: N/A, metadata only. Rollback boundary: these two dated
  headings and this tracker update, without touching source or prior proof.
  Parent accepted the canonical focal proof and independently spot-checked
  the same contracts: 4/4 passed. Documentation closure commit:
  `72808056f1cc16e99a29a792597452a315fbaa1c`. Hosted verification
  remains R41-2, not part of this checkbox.
- [x] R41-1b — Reproduce and correct only the five existing documentation
  contracts invalidated by the authorized dated 4.1.0 headings. Observe RED
  on the exact failing tests before editing, then GREEN and REFACTOR, while
  retaining meaningful assertions for release notes, migration guidance,
  4.0 history, root/docs parity and audit-report navigation. Own only the
  five implicated test modules and this tracker. Run those five modules plus
  the existing changelog-consistency module; record exact results and
  applicable style checks. Do not change changelog content, runtime behavior
  or any release gate. Rollback boundary: these compatibility-test edits.
  Observed RED on the five exact named tests: 5 failed in 0.19s, each at the
  stale `Unreleased` heading or dependent split. Updated only their test
  contracts to require the single exact dated 4.1.0 heading while retaining
  compatibility-policy order, migration links, GraphQL-core floor and 3.1.1
  patch history, 4.0 dated notes, audit-report navigation and audit-scope
  claims, root/docs parity and documentation-only behavior boundaries.
  Renamed the obsolete audit test to describe audit scope rather than
  incorrectly suggesting 4.1.0 itself is unpublished. Focused GREEN:
  5 passed in 0.16s. After one Ruff formatting normalization, the five full
  modules plus `tests/test_docs_changelog_consistency.py` passed 38/38 in
  the final normalized run (0.40s). Ruff check and format check passed for
  all five changed test files;
  mypy found no issues in those five files. The canonical pytest invocations
  used the verified Python 3.12 interpreter, `--no-cov`,
  `-p no:cacheprovider`, and no `addopts` override. Runtime harness: N/A,
  tests validate documentation contracts only. Parent independently reran
  the six-module command: 38 passed in 0.43s. A fresh-context functional
  verifier also passed all 38 in 0.41s and inspected all three retained CI
  failure logs: PASS_SCOPED, no weakened assertions, skips or exclusions.
  The local RED duration remains writer-reported (tool output only, not a
  retained proof file); the earlier exact-head CI RED was independently
  verified. No full-suite or coverage acceptance follows from focal proof.
  Correction commit `c576baa241b999693c9cf14d70d101751ed83fcd` was
  normally fast-forward pushed to `main`; remote readback matches. New
  exact-head hosted checks and tag remain pending.
- [x] R41-2 — Commit the documentation-only closure, fast-forward it to the
  authorized `main`, then observe every applicable fresh Actions and classic
  status context on that exact commit until terminal. Record success, failure
  and expected skip separately. Any failed, missing or pending required check
  blocks tagging; the earlier PR exception is not a substitute. Commit and
  normal fast-forward push completed as
  `72808056f1cc16e99a29a792597452a315fbaa1c`; remote `main` readback
  matches. Automatic run
  https://github.com/eamigo86/django-graphex/actions/runs/40435107342 is
  terminal FAILURE: 8 failed, 7 passed, 3 expected skips. This failed head
  cannot be tagged. The verified R41-1b correction was normally pushed as
  `c576baa241b999693c9cf14d70d101751ed83fcd`. Its fresh automatic run
  https://github.com/eamigo86/django-graphex/actions/runs/40437276472 is
  terminal SUCCESS; the read-only watcher session `69197` completed with
  exit 0. Fresh readback confirms all 15 applicable Actions jobs succeeded,
  with 3 expected publication skips and 0 pending. Both classic statuses are
  successful: Codecov project `96.72%`, and patch "Coverage not affected"
  against `2fcdbd1`. Total: 17 success, 0 fail, 3 expected skips, 0 pending.
  Remote `main` is exactly `c576baa241b999693c9cf14d70d101751ed83fcd`,
  whose metadata version is `4.1.0`. Local and remote tag `v4.1.0` remain
  absent at this pre-tag check. This corrected exact commit, not a later
  local tracking checkpoint, is the authorized tag target. The prior failed
  `72808056` run remains historical; no blind rerun or reuse of its earlier
  PR exception was needed.
- [ ] R41-3 — Only after R41-2 has all required checks passing, create and
  push annotated tag `v4.1.0` on the checked exact `main` commit. Record tag
  target and push evidence. Do not infer publication from a tag request.
- [ ] R41-4 — Verify the immutable PyPI package, GitHub Release and
  production documentation artifacts, including independent installation
  evidence where applicable. Record artifact identities and any failures;
  do not claim the release complete from a triggered workflow alone.

## Historical merge result and prior release boundary (2026-10-26)

The maintainer explicitly approved a **one-time Codecov patch exception** for
PR #254 and authorized merging its exact current head into `main`, without
changing coverage thresholds. Approval to tag or publish 4.1.0 remains
separate and must be requested before either action. The prior
`WAITING_FOR_CODECOV_READ_ACCESS` status and earlier no-merge scope below are
historical; they do not override this later, narrower merge authority. The
maintainer declined contacting Codecov support. Do not send a support request.

- Merged target: PR https://github.com/eamigo86/django-graphex/pull/254,
  head `acf61d08fc79a5f048c03a5fa16e1346d12bc1bf`, base
  `5a155a059a4d3995ead1b639f08136e5d7619aec`. The SHA-locked standard
  merge completed without admin override, force or squash. The API returned
  `merged: true`; fresh readback shows `MERGED` by `eamigo86` at
  `2026-10-26T22:31:24Z`, with merge SHA
  `2fcdbd1f960ecbcf2695d6242c08ce260e26b8fb`. Remote `main` points to
  exactly that SHA. The remote PR head and merge tree both equal
  `010473ce05f1a038ce185432b2e370dfd7819463`. Linked issue #253 closed
  automatically at `2026-10-26T22:31:26Z`. The Conventional merge title is
  `feat(release)!: integrate audited 4.1.0 changes (#254)`; its body links
  the exception and disclaims tag/publication authority.
- The exception applies only to existing failed Codecov patch check
  `121851206201`: `96.12403%` against `96.43%`. A later authenticated
  dashboard reading of `96.97%` does not establish why this check failed and
  does not turn it green. Codecov project passes at `96.72%`.
- The exact-head rollup remains **16 pass, 1 fail, 3 expected skips, 0
  pending**. Its 15 GitHub Actions jobs and Codecov project pass; only the
  named patch check fails. The hosted coverage job independently enforced
  pure branch coverage `95.5551%` and changed-line coverage `98%`, both
  passing unchanged `95.01%` gates.
  Historical PR run:
  https://github.com/eamigo86/django-graphex/actions/runs/40401439029.
  Do not assert that all PR checks were green or that Codecov has a proven
  defect. The later green `main` statuses neither retroactively change the
  failed PR check nor establish the cause of its calculation mismatch.
- The automatic `main` push run
  https://github.com/eamigo86/django-graphex/actions/runs/40413092948 is
  terminal **SUCCESS** for exact head
  `2fcdbd1f960ecbcf2695d6242c08ce260e26b8fb`. All 15 Actions jobs
  succeeded; publish, create-release and deploy-docs are the three expected
  skips, with zero pending. The 18 GitHub check-run records are Actions only;
  the separate classic commit-status API reports two successful contexts:
  `codecov/project` `96.72%` (+0.29 versus base `5a155a0`) and
  `codecov/patch` `96.96%` against `96.43%`. Combined `main` rollup:
  **17 success, 0 fail, 3 expected skips, 0 pending**. Fresh coverage job
  `121888492000` reports 7,794 passed, 7 skipped, 4,064 subtests passed in
  419.61 seconds; combined coverage `97.62%`, pure branches
  `5,095/5,332 = 95.5551%` against the unchanged `95.01%` gate, PASS.
  The changed-line enforcement job also succeeded; no exact `main` diff
  percentage is claimed. Release artifact build, smoke, audit and checksum
  passed, with no publication.
- Scope: the exception was documented, the factual PR comment was posted,
  the exact head was merged and `main` checks were verified. Final explicit
  human approval remains required before tag or publication. No threshold,
  exclusion, configuration, source or status-forgery change; no Codecov
  rerun, workflow dispatch, support contact, or production publication is
  authorized here.
  The automatic `main` checks are not release approval.
- Route: delegated direct for an operational documentation edit because
  preparation and evidence reconciliation precede writing. The parent owns
  the mirror, Conventional Commit, PR comment, merge and remote readback.
  Delivery strategy remains `exception-ok` for the existing integration PR;
  there is no new source implementation or PR. Forecast: approximately 80
  authored lines. Strict TDD stays enabled, but RED/GREEN and a runtime
  harness are N/A for this documentation-only unit. Structural readback and
  `git diff --check` are the applicable local checks.
- Release boundary: tag `v4.1.0` is absent. The root and docs 4.1.0 changelog
  headings remain `Unreleased`, as previously required. Close both with the
  actual publication date and validate that documentation-only closure only
  after final human release approval; the merge consent authorizes neither
  tagging nor publishing.

### Merge tasks

- [x] RD-M1 — Record the exact one-time exception in this tracker and a
  public-English PR comment before merge. Keep the failed patch status and
  calculation mismatch visible, with source links and no private evidence.
  Authenticated comment/body readback as `eamigo86`:
  https://github.com/eamigo86/django-graphex/pull/254#issuecomment-6428876354.
  Local Conventional documentation commit
  `526156a58ccb3cd154b4de04a18ec12fcec10e59` records this evidence;
  it is unpushed, alongside prior local metadata commit
  `69989e587457b5c6fad87a4445d0f0c1009b8b7e`.
  Remote merged `main` remains `2fcdbd1f960ecbcf2695d6242c08ce260e26b8fb`.
- [x] RD-M2 — Reconfirm PR #254's exact head/base and merge only that head
  into `main` through the authorized `eamigo86` account. Record merge method,
  resulting merge SHA and remote readback. Do not infer completion from
  approval or a merge request alone. SHA-locked standard merge, no override,
  force or squash; `merged: true` and fresh `MERGED` readback at
  `2026-10-26T22:31:24Z`. Merge SHA and `main` ref:
  `2fcdbd1f960ecbcf2695d6242c08ce260e26b8fb`. PR head and merge tree
  both `010473ce05f1a038ce185432b2e370dfd7819463`.
- [x] RD-M3 — Verify post-merge `main` state and observed checks without
  calling them release gates. Preserve RDC-3's unresolved Codecov patch
  calculation mismatch as an accepted one-time exception, not a fix. Remote
  `main` ref and linked issue readback passed. Automatic `main` run
  `40413092948` and both classic Codecov statuses are terminal successful:
  17 success, 0 fail, 3 expected skips, 0 pending. The final human release
  approval question is **PENDING**, not answered by this verification. Before
  any tag, release, PyPI upload or production documentation publication, seek
  explicit approval; then close both `Unreleased` 4.1.0 changelog headings
  with the actual publication date and validate the documentation-only
  closure. No tag or publication has occurred.

## Historical PR-delivery objective and authority

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
- [x] RD-4 — Close the PR-delivery record without releasing. The original
  CI-green condition was not met; closure instead rests on the maintainer's
  explicit one-time exception for failed Codecov patch check `121851206201`
  on head `acf61d08fc79a5f048c03a5fa16e1346d12bc1bf`. The full PR rollup
  remained 16 pass, 1 fail, 3 expected skips, 0 pending. PR #254 merged as
  `2fcdbd1f960ecbcf2695d6242c08ce260e26b8fb`; RD-M3 retains the
  post-merge checks and final release-approval boundary.
  Superseded historical rule: close only with green checks; otherwise leave
  closure pending and do not merge. The later explicit exception changed only
  this PR's merge decision, not any coverage gate or release approval.

## Historical corrective work and exception disposition

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
  pending; no gate has been lowered. Local coherent commit:
  0bd7c908b0484ee595e87ed97b8136120d62c458. Parent spot-check: 7 passed on
  Django 6.1 with the deprecation promoted to error.
  Current disposition: the Codecov patch calculation mismatch remains
  unresolved, not fixed or green. The maintainer accepted this exact failed
  check as a one-time merge exception for PR #254; the compatible JSONNull
  test and dependency-policy documentation portions passed as recorded above.
  No future check waiver or threshold change follows from this exception.
- [x] RDC-4 — Independently verify, push and repeat all hosted checks. Verify
  protected original/frozen data and environments before/after; no benchmark
  regeneration. Push only the candidate branch through eamigo86 with no tags.
  Inventory every actual check tied to the resulting exact PR head; require
  all applicable jobs and external Codecov statuses green, with only expected
  publication skips. Retain failed prior evidence; no retry-until-green or
  unsupported success claim. Evidence/commit: pending, then close RD-4.
  Independent local verdict PASS_SCOPED at 0bd7c90, report:
  /private/tmp/rdc4-independent-fmiy4s4_/RDC4-report.md and status.json.
  Locked 6.0.8/core3.3.0 and latest 6.1.2/core3.3.1 full suites each pass
  7,794 tests, 7 justified skips and 4,064 subtests, with zero test warnings.
  Pure branches 5,095/5,332 = 95.55514%; combined 18,541/18,999 = 97.58935%,
  raw/XML reconciled and all original global thresholds intact.
  Fresh base Django5.2.18/core3.3.1/Pydantic2.14.1 truly without Channels:
  7,063 passed, 39 justified optional/service skips, 4,064 subtests; base's
  existing tox coverage policy is unchanged, not falsely reported above 95%.
  Playground 98, benchmark contracts 358 (no timing), focal base 306,
  warning/docs 14, quality/security, strict docs/44 anchors all passed.
  Local cumulative diff cover 98.63425%; not an actual Codecov status.
  Eight before/after inventories match, including original/frozen data and
  prior proof. External base-runner cache-option exit4 was retained and only
  that incompatible external argument removed before the valid final run.
  No source findings remain within these corrections. RDD OFF; unavailable
  native risk assessment was not substituted for independent proof.
  Parent next commits this metadata and pushes the verified correction batch;
  all actual hosted checks on the resulting new head remain PENDING.
  Verified batch was pushed as acf61d08fc79a5f048c03a5fa16e1346d12bc1bf.
  New run https://github.com/eamigo86/django-graphex/actions/runs/40401439029
  is terminal SUCCESS for Actions: all six matrix jobs, base-install,
  lint/security, diff, coverage, PostgreSQL, version, docs, Playground and
  release-artifact passed. Coverage branches 95.5551%, changed-line 98%;
  artifact build/smoke/audit/checksum/upload passed. No publication occurred.
  Full exact-head PR rollup is NOT green: 16 pass, 1 fail, 3 expected skips,
  0 pending. Codecov project passes at 96.72%; patch check 121851206201 fails
  at 96.12% versus 96.43%. Later public exact-head data reports 96.97%
  (3,550 hits, 50 misses, 61 partials), not a substitute for the failed check.
  Evidence: /private/tmp/pr254-ci-corrected-pSXkTp/ci-report.md and status.json.
  A bounded read-only investigation must establish the check's actual basis
  and supported re-request behavior before any retry; no coverage padding,
  threshold change, forged green check or indiscriminate rerun is allowed.
  Bounded diagnosis complete, no safe retry recommended. Report:
  /private/tmp/pr254-codecov-discrepancy-20261026T2119Z/diagnosis.md.
  Check output says 96.12403% with 75 missing lines, but the public API's
  line-level totals do not expose that calculation's denominator/aggregation.
  Exact head/base match and sessions=1; neither stale data nor a backend defect
  is proven. No Codecov YAML exists at either tracked base or head. The
  observed Codecov app does not subscribe to check_run, so the documented
  GitHub rerequest webhook has no supported recomputation route here.
  Final GitHub readback still confirms 16 pass/1 fail/3 expected skips on acf61d0.
  Need the human's explicit authorization for read-only Codecov account/admin
  diagnostics; no Codecov authenticated session/credential was inspected.
  Public status: https://github.com/eamigo86/django-graphex/pull/254#issuecomment-6427683770.
  Closure is under the explicit one-time Codecov patch exception in RD-M1,
  not under the original all-green criterion. This failed status remains
  recorded and does not waive any future gate. The automatic `main` run
  `40413092948` later reached terminal SUCCESS, with both classic Codecov
  statuses successful on the merge SHA, as reconciled in RD-M3.

## Historical progress before merge approval

Issue #253 was created under eamigo86 and its status:approved label was
confirmed before PR creation: https://github.com/eamigo86/django-graphex/issues/253.
The obsolete status:needs-review label was removed under the human's explicit
approval. RD-1/RD-2 delivery and RD-3 terminal observation are complete;
RD-4 CI-green closure is pending because Codecov patch still fails.
The CLI rejected combining --template with --body-file before making a remote
change; the successful creation used the actual template headings in the body
and existing enhancement/status labels instead. No duplicate issue was created.
PR #254 is open and attached. Initially head b74659f and run
40380745811 had 9 pass/8 fail/3 expected skips/0 pending. Source diagnosis
was read-only at that stage. The human has now authorized the bounded
corrective units above with TDD, disposable official dependencies and all
checks repeated. RDC-1/RDC-2 and RDC-3's test/docs portion passed locally;
independent normalized full verification also passed. The verified batch was
pushed as acf61d0: all Actions jobs passed, but Codecov patch still fails.
Current rollup: 16 pass/1 fail/3 expected skips/0 pending. Public data cannot
explain the discrepancy; ask for read-only Codecov account diagnostics before
proceeding. Keep gates/support intact and consult before incompatible changes.
Prior local tracking commit 6b620e0 traveled with the verified correction batch.
The final blocker record is saved locally only; do not start another identical
CI run solely for bookkeeping while the external check remains unexplained.
No merge, tag, workflow dispatch or publication. Rollback for this metadata
unit is this task file and its external draft bodies; no package source or
measurement data is part of the unit.
