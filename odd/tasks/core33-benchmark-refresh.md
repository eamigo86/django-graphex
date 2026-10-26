# Rerun the current core33 SQLite comparison safely

Status: IN PROGRESS. Repository locator: odd/tasks/core33-benchmark-refresh.md.

## Objective and authorization

Execute the official current-source comparison for 1,000 and 2,000 authors,
three repetitions per library, and report validated results without replacing
historical snapshots or publishing a release.

- User authorized benchmark regeneration and explicitly approved a clean
  temporary measuring checkout and four disposable pinned environments.
- Use the local cache first; download missing dependencies only from public
  PyPI without credentials. Do not modify the original project environment.
- No PR, push, tags, package/release publication, remote execution, ambient
  database access, or unrelated source changes. Ask before incompatible changes.
- Preserve user audit reports, existing SQLite database/migrations, root coverage
  outputs, prior result series, benchmark constraints and unrelated changes.
- Do not promote the new series into the selected public comparison or change
  hard-coded documentation selectors in this run. Report the new results first.

## Frozen measurement and workflow

- Primary branch: codex/audit-400-remediation.
- Frozen measurement commit: f9f4eae81954959ab71e4a9037d5ba06486d6a8e.
- Use a separate clean checkout of that exact commit; later tracking commits in
  the primary checkout do not change the measured source identity.
- Clean managed checkout:
  /Users/eamigo/.codex/worktrees/core33-benchmark-refresh/django-graphex.
- Owned setup/evidence root: /private/tmp/core33-br1.wrp6LvAu; profile environments
  are under venvs/, separate from the original project environment.
- Use benchmarks.run_publish_core33, never historical run_publish.py: the latter
  uses obsolete pins and deletes the old database/migrations.
- Fresh immutable series: core33-4.1.0-f9f4eae81954959ab71e4a9037d5ba06486d6a8e.
- Profile runtime: Python 3.12.11, Django 6.0.8; GraphEx/Strawberry use
  graphql-core 3.3.0 and Graphene/Ariadne use 3.2.13, as pinned by core33.
- SQLite only: 10 posts per author and 5 comments per post, producing 50,000
  and 100,000 comments. Do not imply a fresh PostgreSQL comparison.
- Total: 24 serial dispatches, 12,000 timed requests and 1,800 warmup requests,
  plus validation, SQL probes, schema diagnostics and seeding.
- Do not run tests or other agent workloads concurrently with timing. Record
  host/load/provenance facts, avoid claiming a paired improvement versus the
  older snapshot, and retain all failed attempts without cherry-picking.
- SQL flat/nested/single/filter/create expectations: GraphEx 1/3/1/1/4;
  Graphene 2/442/2/2/1; Strawberry 1/3/1/1/8; Ariadne 1/221/2/1/1.

## Implementation route and checks

- ODD delegated direct, not SDD. Setup, orchestration and contract analysis
  require one bounded worker; independent verification follows measurements.
- Strict TDD remains enabled by user/AGENTS. This is measurement/data generation
  with existing harness code: no new runtime behavior, so feature RED is N/A.
  Execute existing benchmark contract tests before measuring. Any necessary
  code correction is separate scope and requires observed RED before a fix;
  never relax version/surface/dataset/SQL/provenance gates to obtain numbers.
- Supported test interpreter:
  /private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python.
- Bootstrap runtime already present:
  /Users/eamigo/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12.
- Bootstrap: bash benchmarks/setup_envs.sh --profile core33 with explicit
  Python, venv-root, cache and wheel directories. Disable managed-Python
  downloads. Record exact freezes, archive/wheel digests and build provenance.
  If PyPI offers only a promise sdist, do not claim a locally built wheel is an
  official wheel; verify source provenance and stop on an unresolvable pin.
- Run all eight profile/seed preflights before the official publisher. Validate
  every run and median before copying the new eight-JSON series to the primary
  checkout. New outputs must never overwrite old series or raw evidence.
- Post-run independent gates: contract tests, median/provenance/SQL verification,
  full configured root coverage (pure branch and combined >95.01%), applicable
  docs/quality and protected-file checks. Test outputs stay external.
- RDD is globally OFF. No native review transaction or automatic mode changes.
- Forecast: 180-300 authored tracking/report lines, generated JSON excluded;
  delivery ask-on-risk, local Conventional Commits only. Do not code-golf.
- All technical artifacts are English; Google-style public docstrings with
  type hints, no repeated types and no backticks if any code is later authorized.

## Tasks

- [x] BR-1 — Prepare isolated source and exact profile environments.
  Route: delegated worker; environment setup and executable contract preflight.
  Create/reuse a suitable managed clean worktree at the frozen commit, preserve
  all original untracked reports, prepare owned private cache/wheel/env/seed/raw
  paths, verify public PyPI dependency provenance, all four freezes and library
  import origins. Run existing harness contracts and eight preflights. Record
  any missing dependency/contract blocker honestly. Save tracking evidence in a
  local work-unit commit. Rollback: only newly owned disposable setup resources.
  Evidence: /private/tmp/core33-br1.wrp6LvAu/BR1-evidence.md. Four freezes match
  the unchanged constraints byte-for-byte; uv pip check and all eight read-only
  preflights passed. Existing harness tests: 358 passed, no coverage override.
  Promise 2.3 has only an official PyPI source archive; its verified SHA-256 is
  dfd18337c523ba4b6a58801c164c1904a9d4d1b1747c7d5dbf45b693a49d93d0.
  The required wheel was built locally in a private helper, SHA-256
  137e6fa2aceaa785bb8103cf78479d661ec8d665046b32716f830922cd27e3d8;
  it is not a PyPI-published wheel. A private-cache offline attempt missed
  annotated-types; the official script cleaned its owned partial venv before
  the approved public-PyPI retry. No original environment changed.
  Both source snapshots remained unchanged; primary protected inventory has
  37,019 entries. Measurement HEAD/tree/status are exact and clean. Publisher
  seed/output/results parents are empty, distinct and mode 0700. No timing has
  run. The local setup tracking commit is recorded after saving this unit.
- [ ] BR-2 — Execute and retain a validated new comparison series.
  Route: the same single worker, serial execution without concurrent tests.
  Run the unchanged official publisher for both scales and all four libraries,
  three rotated repetitions, preserving raw runs and exact source/constraints
  provenance. Stop on validation failure, do not change workload or SQL gates.
  Copy only a complete validated new eight-JSON bundle to the primary checkout;
  retain prior series and report a results table with operation units and fair
  ratio direction. Save generated result work unit locally.
  Rollback: the new result series only, never the historical measurements.
  Evidence/commit: pending.
- [ ] BR-3 — Independently verify results and close tracking.
  Route: independent verifier, then parent mechanical metadata closure.
  Recompute medians from raw runs, validate all eight new artifacts and seed/
  operation/version/SQL contracts, confirm no cherry-picking or source drift,
  run related tests and complete root coverage after timing, and verify original
  environment/database/reports/prior snapshots unchanged. Do not rerun timing
  merely to improve results. Keep selected public docs frozen pending explicit
  promotion authority. Save tracking-only closure and deliver observed numbers.
  Rollback: metadata only. Evidence/commit: pending.

## Progress and next step

Readiness, isolated setup and preflight are complete; no measurements yet.
Parent read the complete setup evidence and independently checked both Git
states. Next: save BR-1 locally, then run the unchanged official publisher from
the frozen clean checkout, without concurrent tests or other agent workloads.
