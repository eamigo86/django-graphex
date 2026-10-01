# django-graphex 3.1.1 security patch

## Objective and authorization

Prepare a minimal security patch before the separately authorized future
GraphQL-core 3.3 migration. The user approved local implementation on 2026-10-01.
Local work-unit commits are authorized. The user subsequently authorized GitHub
issues and two chained pull requests toward 3.1.1 integration in
eamigo86/django-graphex using the eamigo86 gh session. This task delegates all
remote actions until after independent T3 verification. The user then authorized
merging both child PRs into v3.1.1 and opening its draft tracker toward main.
The user has now authorized closing the 3.1.1 changelog and, after fresh CI,
merging the tracker into main. Release tags, publication, workflow dispatch and
branch cleanup remain unauthorized.

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
  second. T3 verification and the narrow chained-PR CI correction belong with
  the second slice. The integration ref is v3.1.1; the first child head is
  codex/v3.1.1-security at 0706264, and the existing codex/security-3.1.1 head
  targets that first child. The user
  approved a size exception solely for the 883-line generated Playground lock;
  it does not waive review of authored code, tests or docs. Initial forecast was
  150-300 authored changed lines; T1 and committed T2 total 505 authored lines
  (189 + 316). The T2 commit has 320 total changed lines including four lock
  metadata lines; the generated T1 Playground lock is reported separately.

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
  Implementation and checks verified; the delivery-chain decision is resolved.
  Commit: 1c76ea9 (local work unit; SHA entered in this post-commit evidence
  update for T3 to include). Review tier/outcome: high/unassessable
  in read-only assessment due untracked .codegraph inventory;
  RDD disabled/unmanaged. RED: four new release/documentation contracts failed
  on 3.1.0 metadata and missing patch notes/guidance; GREEN: 38 patch and
  historical readiness tests passed, and 93 related release/docs/security
  tests passed. Source version and installed distribution metadata are checked
  separately because no local distribution build is authorized.
- [x] T3 — Verify the local candidate and record release-readiness evidence.
  Route: delegated independent verification after writer checks.
  Acceptance: full suite, branch-enabled total and applicable patch coverage
  at least 95.01%, quality,
  frozen runtime audit, documentation, Playground and diff checks pass or any
  unavailable/failed checks are explicitly reported. No claim of hosted CI or
  publication without actually running them.
  Clean tracked snapshot at b765246: all 4,371 tests passed, 7 skipped,
  7 subtests passed; 96.21% branch-enabled total coverage exceeds 95.01%.
  The final docstring-only correction at 63e527d passed independent checks.
  Local checks passed; hosted matrix, artifact and PostgreSQL checks also passed.
  Commit: b765246 (verification and CI correction; SHA recorded in this
  post-commit evidence update for final delivery). RDD disabled/unmanaged.
- [x] T4 — Integrate reviewed children and open the draft main tracker.
  Route: delegated remote delivery; local checkpoint is an atomic inline update.
  PR #202 merged as d42e20e; PR #203 was retargeted, synchronized without source
  changes, revalidated and merged as 4e2aa5d. Their merge subjects are conventional.
  Draft PR #204 targets main from v3.1.1. Its 15 validation jobs and both Codecov
  checks passed; publication jobs were skipped. The integration tree equals the
  reviewed 78bdddae tree. Main remains at a160d12; no v3.1.1 tag was created.
- [ ] T5 — Close the 3.1.1 changelog and integrate only after fresh CI.
  Route: delegated direct; this new work unit spans release-date contracts and
  two public changelogs. Start from v3.1.1 at 4e2aa5d on
  codex/v3.1.1-release-notes. Strict TDD remains enabled from current user
  instructions: date contract RED, minimal notes GREEN, then REFACTOR. Focused
  runner is `.venv/bin/python -m pytest <release tests> --no-cov`; the full
  branch-enabled gate stays at 95.01%. Forecast: one small, cohesive release
  notes slice under 400 authored changed lines. Acceptance: date both 3.1.1
  changelogs 2026-10-01 without claiming PyPI publication or changing 3.1.0;
  focused and clean full checks pass. After independent verification, use one
  approved-issue-linked notes PR into v3.1.1, fresh CI, then merge it and the
  updated tracker only after fresh green CI. No tag or publication is in scope.
  Local date/contract implementation is verified; the issue-linked notes PR,
  fresh hosted checks and main merge remain pending. Engram mirror remains
  pending without an authoritative session identity.

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
only for the generated Playground lock. The clean-snapshot local verification
passed, including the corrected CI candidate and hosted release gates. Both
children are merged into v3.1.1 and draft tracker #204 is green. The user has
authorized the dated 3.1.1 notes and a conditional main merge after fresh CI.
Next: independently verify the dated T5 candidate, then use the authorized
review path. Tag creation and publication still require separate explicit
approval. The prior T4 checkpoint was carried into this local T5 work unit;
no unreviewed bytes were added to the green tracker. Its Engram mirror remains
pending host session registration.

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
- Post-decision spot check: `.venv/bin/python -m pytest
  tests/test_graphql_core_security_patch.py tests/test_release_readiness_311.py
  --no-cov -q`: 10 passed. `git diff --cached --check` passed before commit.
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

### T3 local proof and delivery CI correction

- Independent clean tracked snapshot at b765246: full suite 4,371 passed,
  7 skipped, 7 subtests passed; 96.21% branch-enabled coverage with the unchanged
  95.01% gate. No tests or benchmark modules were excluded. Evidence:
  /private/tmp/graphex-311-verify.0MpK5X/correction-full-suite.log.
  Skips: five PostgreSQL-only cases, optional multiselectfield and the retired
  Graphene container; the three expected test warnings remain unchanged.
- At 1c76ea9, runtime audit found no known vulnerabilities; Bandit, Ruff, mypy,
  both docstring checks, docs build, root/Playground frozen locks and diff checks passed.
  Playground: 59 tests passed. Docs retained the same five baseline anchor
  warnings. The independent verifier also observed six vulnerable-version RED
  cases and 27 patched-version GREEN cases.
- Patch coverage is N/A because no covered runtime source lines changed;
  the diff-cover threshold check passed. Wheel/sdist, external-wheel smoke,
  six-version matrix and PostgreSQL checks require hosted CI; no local package
  build, publication, tag, dispatch or merge was run.
- Delivery blocker: PR #2 targets codex/v3.1.1-security, which the prior
  pull-request branch filter did not admit. A narrow pull-request-only pattern
  now covers codex/v3.1.1-* while push, dispatch and tag-only publication
  remain unchanged. RED: the new workflow contract failed on the missing
  pattern. GREEN: the workflow plus 3.1.1 contracts passed (14 tests), and
  related historical-readiness contracts passed (48 total). Ruff format/lint
  and diff check passed. Runtime harness: N/A, because this
  change only selects the GitHub Actions PR event.
- Rollback boundary: the pull-request branch pattern and its workflow contract;
  neither runtime security fixes nor release publication gates depend on it.
- Final 63e527d: `.venv/bin/python -m pytest tests/test_release_workflow.py
  tests/test_release_readiness_311.py --no-cov -q` passed 14 tests; clean-clone
  strict docstrings, Ruff format/lint and diff checks passed.
  DOC002 was observed RED, then fixed by an atomic inline docstring-only edit;
  no runtime or test logic changed after the full-suite proof. Parsed YAML
  confirms both intended PR bases match, with every job, push and dispatch
  unchanged.

### T5 local release-note proof

- RED: `.venv/bin/python -m pytest
  tests/test_release_readiness_311.py::test_dated_patch_notes_preserve_310_history
  --no-cov -q` failed once for the intended pre-change 3.1.1 Unreleased heading.
  GREEN: `.venv/bin/python -m pytest tests/test_release_readiness_311.py
  tests/test_release_readiness_310.py tests/test_docs_310_parity.py
  tests/test_release_workflow.py --no-cov -q` passed all 74 tests.
- A clean local Git clone with the four-file candidate overlay passed all
  4,371 tests with 7 skips and 96.21% branch-enabled coverage against the
  unchanged 95.01% gate; no test or benchmark module was excluded. Ruff
  format/lint, mypy, both docstring gates (strict TOTAL 0), and Zensical docs
  build passed. Docs retained five known baseline anchor warnings. Evidence:
  `/private/tmp/graphex-311-t5-clone.RfnZv2/`.
- An initial archive-only harness lacked `.git` and caused two provenance
  failures; the real Git clone above resolved both without changing tests or
  excluding modules. The existing ignored extra benchmark files remain untouched.
- Runtime HTTP and distribution-artifact checks are not applicable to this
  release-note-only unit. Hosted wheel, matrix, PostgreSQL and Codecov checks
  must be rerun after the notes PR. Rollback boundary: the dated 3.1.1 headings,
  publication-pending wording, date contract, and this task checkpoint only.
  The 3.1.0 history, frozen benchmark artifacts and runtime dependency floor
  remain unchanged. No release tag or publication was performed.
