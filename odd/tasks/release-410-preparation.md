# Promote the verified benchmark and prepare release 4.1.0 locally

Status: IN PROGRESS. Repository locator: odd/tasks/release-410-preparation.md.

## Objective and authority

Promote the verified current-source benchmark into public documentation and
prepare the declared 4.1.0 release locally, without executing remote delivery.

- User explicitly requested documentation promotion and release preparation on
  2026-10-26. Prior no-PR/push/tag/publication restrictions remain in effect.
- Preserve strict TDD, documentation, and pure branch/combined coverage >95.01%.
  Ask before incompatible behavior changes; no runtime change is proposed.
- No local publishable wheel/sdist build: the artifact is built once in GitHub
  Actions and its actual smoke/audit/checksum gates remain CI responsibilities.
- No remote GitHub/auth/session probing, dependency installation, new services,
  timing reruns, original database changes or edits to measurement artifacts.
- Use English artifacts; Google-style docstrings, type hints without repeated
  types and no backticks if test/helper code is added.

## Roots, version and evidence

- DEVELOPMENT ONLY: /Users/eamigo/Documents/Work/django-graphex,
  branch codex/audit-400-remediation, starting HEAD
  eb89b7d668e7f3a4100afdf8c48fa7d348c94721.
- The app's current working checkout is the FROZEN measurement copy at
  /Users/eamigo/.codex/worktrees/core33-benchmark-refresh/django-graphex.
  It must stay clean at f9f4eae81954959ab71e4a9037d5ba06486d6a8e; do not edit,
  switch or remove it. Managed archive refused task-primary removal.
- pyproject.toml declares 4.1.0. Changelog notes are Unreleased; no local v4.1
  tag was found. Do not claim a remote release/tag check or mark this published.
- Promote only benchmarks/results/core33-4.1.0-f9f4eae81954959ab71e4a9037d5ba06486d6a8e/.
  All eight JSON files remain immutable. Preserve the historical 460efb9 series.
- Independent benchmark proof: /private/tmp/core33-br3-eu4dwlq8/BR3-report.md.
  All 24 raw runs, eight artifacts and 248 scalar medians were validated.
- SQLite 50,000/100,000 comments; median of three run means and median of three
  run p50 values are different metrics. Derive tables/ratios from JSON only.
- Whole-stack profiles use Python 3.12.11/Django 6.0.8; GraphEx/Strawberry use
  graphql-core 3.3.0 and Graphene/Ariadne 3.2.13. Host load was 10.86 to 9.24
  on 16 logical CPUs: local/load-sensitive, not controlled or paired history.
  No fresh PostgreSQL performance claim or statistical significance claim.
- Historical preservation qualification remains in the closed benchmark tracker:
  ignored databases/migrations/old benchmark envs lacked pre-measurement hashes.
  No alteration was found; do not turn that into a full-preservation guarantee.
- The benchmark execution feature remains CLOSED_SCOPED. This is a separate
  authorized promotion/release-preparation feature, not rewritten history.

## Workflow and delivery

- ODD delegated direct, not SDD. Multi-file preparation and implementation use
  one writer, then an independent verifier. Parent owns tracker/mirror/commits.
- Strict TDD is enabled by user/AGENTS: select the new series in the executable
  documentation contract, observe failure against stale pointers/tables before
  documentation edits, then derive minimal GREEN and refactor without drift.
- Supported test interpreter:
  /private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python.
  Do not use uv run or root .venv; do not resync the original environment.
- Actual test processes assert Python 3.12.11, Django 6.0.8, graphql module and
  distribution 3.3.0, and DEVELOPMENT library origin. Use -B, clear ambient
  pytest/coverage/Django variables and put caches/DBs/reports/evidence outside.
- Focused checks use --no-cov with configured addopts intact. Full root keeps
  original branch threshold 95.01, warning policy and coverage exclusions; only
  external HTML/XML destinations may differ. Preserve PID-owned raw data and
  reconcile pure branch arcs/combined coverage with XML.
- Applicable checks: selected docs/changelog contracts, benchmark tests, full
  root, strict docs/links, mypy/docstrings/format checks as applicable, and
  release-source/workflow contracts without building or remote execution.
- RDD is globally OFF; no review transaction, consent or automatic enabling.
- Initial forecast: 300-380 authored lines, tables included; actual RP-1 is
  329 authored lines across six files plus the initial 109-line tracker (438
  before progress updates). On 2026-10-26 the human explicitly approved the
  size exception for completing and saving this LOCAL 4.1.0 preparation in
  coherent commits. Delivery strategy: exception-ok. No artificial trimming,
  omitted tests or PR/tag/publication authority is inferred from this approval.

## Tasks

- [x] RP-1 — Promote the measured series with executable docs contracts.
  Route: delegated writer; six meaningful documentation/test files.
  Add/adjust selector and meaningful caveat/value contracts, capture RED before
  editing prose/tables, then update README.md, docs/why.md and benchmark README
  from exact immutable JSON. Preserve history; update series counts/links and
  distinguish mean/p50, SQLite and whole-stack/load limitations. Mirror the
  promotion note in both changelogs. Run focal/related/full checks and docs.
  Rollback: only promotion docs/tests/notes, never old or new benchmark JSON.
  Implementation and writer proof PASS; local size exception is approved.
  Observed RED: 7 failed/7 passed on stale pointers/tables; GREEN: 14 passed;
  related benchmark contracts: 358 passed. Final root: 7,786 passed, 6 known
  skips, 4,064 subtests. Pure branches 5,087/5,324 = 95.54846%; combined
  18,516/18,974 = 97.58617%, with raw/XML agreement. Ruff, mypy, both docstring
  gates, strict docs (44 HTML pages), comparison anchors and diff checks pass.
  Evidence: /private/tmp/core33-rp1-final-20261026/full/proof.json and
  preservation-after/preservation-proof.json. RED/GREEN evidence:
  /private/tmp/core33-rp1-proof-20261026/red-final.log and stable.log.
  Only the six owned docs/test files changed; benchmark JSON, runtime and frozen
  measurement checkout remain unchanged. Parent spot-checked diff and coverage.
  Local work-unit commit: 98715cf0838fa56c773cce1ef8b55824ebced177
  (454 authored lines including the initial committed tracker), under the
  explicit local size exception. Read-only risk assessment was unavailable
  because of untracked reports; treat as high/unassessable, with independent
  RP-3 required. RDD remains OFF and no review transaction was started.
- [x] RP-2 — Prepare and audit local release metadata/readiness.
  Route: the same delegated worker; bounded source/workflow inspection and
  existing installed checks. Keep version 4.1.0 and notes Unreleased until
  actual release authorization; no invented completed-release date. Consolidate
  any applicable pending notes and record a precise release checklist/gate
  report, using an existing maintainer guide where appropriate. Distinguish
  completed local evidence from pending hosted matrix/PostgreSQL, security
  advisory/network checks, wheel/sdist smoke/audit/checksum and maintainer OK.
  No artifact build, tag, push or PR. If metadata is already correct, this is
  verification-only (RED N/A), not an unnecessary version/source change.
  Initial read-only audit passed 45 focused contracts and installed offline
  quality/doc checks; report: /private/tmp/core33-rp2-proof-20261026/RP2-release-readiness.md.
  It found overlapping production/manual conditions: a manual dispatch on a
  version-tag ref can satisfy both PyPI and TestPyPI predicates and downstream
  Release/Pages guards. No publication was observed. GitHub's public dispatch
  documentation confirms its ref can name a branch or tag.
  Bounded corrective scope is authorized by the existing manual-only-TestPyPI
  release policy: require a push event AND version tag for production selection,
  PyPI, GitHub Release and Pages. Preserve all existing gates, environments,
  single-artifact/checksum flow and staging dispatch. No runtime/API change.
  Same writer owns .github/workflows/cicd.yaml, tests/test_release_workflow.py,
  the existing release maintainer guide and both mirrored changelog notes only.
  Observe a meaningful RED for manual tag dispatch and production-only guards
  before the minimum YAML fix; then focused/related/full proof and docs checks.
  Rollback: only these policy-hardening tests/YAML/docs and tracking metadata;
  never benchmark data or public library code. Save one coherent local commit.
  Corrective proof: /private/tmp/core33-rp2-corrective-proof-20261026/RP2-corrective-release-readiness.md.
  RED: 2 failures on the missing push guards. GREEN: 2 passed; focused: 36
  passed; related: 49 passed. Full root: 7,787 passed, 6 known skips, 4,064
  subtests. Pure branch 5,087/5,324 = 95.54846%; combined 97.58617%; raw/XML
  agree. Ruff, mypy, standard/strict docstrings, Bandit, strict docs/44-page
  anchors and cumulative diff pass; cumulative changed-line coverage is 98%.
  Parent inspected all five source diffs and reran both boundary tests: PASS.
  Production selection and all PyPI/Release/Pages paths now require push AND
  version-tag ref; manual tag/branch runs stay staging/TestPyPI. All predecessor
  gates, single artifacts, checksums and environment names remain intact.
  Preservation proof: only five owned source files differ; 56,139 protected
  DEVELOPMENT entries, 35,846 supported-environment files, and all frozen
  measurement entries unchanged. Benchmark JSON/runtime/version untouched.
  Hosted CI, dependency advisories, built artifact smoke/audit/checksum,
  remote state and final maintainer release decision remain pending.
  Local work-unit commit: pending immediately after this evidence update.
  RDD remains OFF; independent RP-3 is required, not a claimed native approval.
- [ ] RP-3 — Independently verify and close local preparation.
  Route: independent verifier, then parent mechanical tracking closure.
  Recompute all published table/ratio claims from the selected JSON, verify no
  metric/provenance/source drift, and repeat relevant/full tests with coverage
  >95.01% and strict docs. Verify tracked/ignored protected assets explicitly
  BEFORE execution, including databases, migrations and historical envs; do not
  repeat the earlier inventory gap. Record unavailable CI/remote/artifact gates
  honestly and the exact next authorized delivery step. Save tracking closure.
  Rollback: tracking metadata only. Evidence/commit: pending.

## Progress and next step

Version 4.1.0 is confirmed. RP-1 is committed locally as
98715cf0838fa56c773cce1ef8b55824ebced177 with the approved size exception.
RP-2 and its manual tag-dispatch hardening passed local TDD/checks and are ready
for their coherent local commit. Next: independent RP-3. No PR, tags,
publication, new timing or local package artifacts. This enforces the existing
release policy, not an incompatible public API change. The frozen measurement
checkout and JSON remain immutable. Hosted release gates are still pending.
