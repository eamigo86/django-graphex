# Bound mutation constraint-validation cost

## Objective

Profile and optimize the data-size-dependent cost of generic comment creation,
without weakening validation, referential integrity, atomic rollback, or usable
connection guarantees. This is an additional authorized unit before closing the
prepared 4.0.0 migration, not authorization to merge main or publish a tag.

## Problem and evidence

The retained core33 comparison reports GraphEx create-comment p50 of 4.7725 ms
at 1,000 authors and 9.2149 ms at 2,000, versus Ariadne's 0.7818 and 0.7766 ms.
GraphEx emits four request-only statements at both sizes. Static inspection found
that the harness's rollback-only outer transaction activates the backend's
savepoint and table-wide SQLite foreign-key check. The comment table grows from
50,000 to 100,000 rows. Static inspection does not yet quantify the check's share
of elapsed time; timings must separate diagnostics from canonical comparisons.

## Authority and boundaries

- User explicitly authorized profiling and optimization on 2026-10-03.
- Base: integration commit 7eb3935b60310a1358cf204aeb0917c31c3546df.
- Branch: codex/graphql-core-3.3-mutation-performance.
- Authorized source scope: the generic mutation save/constraint path, focused
  regressions, any necessary benchmark contracts, current documentation and both
  changelogs. Example and Playground changes only if required by this behavior.
- No main merge, tag, publication, workflow dispatch, or branch deletion.
- Never open, reset, copy for measurement, or alter retained benchmark databases.
  Existing JSON results, raw runs, journals, manifests, and constraints stay
  immutable. New profiling uses fresh disposable data and separate evidence.
- No environment refresh, dependency changes, or local distribution build.
- No silent replacement of old measurements with post-change claims.
- No unrelated audit-backlog expansion or changes to warning/skip/coverage gates.

## Workflow and checks

- Route: delegated direct. Preparation spans more than four source/test files;
  implementation spans multiple non-trivial files; execution checks are delegated.
- Strict TDD is enabled by the current user-supplied AGENTS.md and explicit
  profiling authorization: observed cause-correct RED, minimum GREEN, REFACTOR.
- Focal runner: .venv/bin/python -m pytest <selected-tests> --no-cov.
- Full runner: .venv/bin/python -m pytest, with existing PID-owned coverage
  isolation and unchanged branch floor 95.01. No reset of addopts or exclusions.
- Native 3.3 checks use the retained official overlay in a clean real Git clone;
  the root environment remains unchanged. Do not confuse its installed 3.2.13
  runtime with verification of the prepared package's 3.3 requirement.
- Required acceptance: existing and new FK/M2M/nested/rollback/connection tests,
  full native-3.3 suite, branch and changed-runtime-line coverage >=95.01%,
  quality/types/docstrings, docs links/build, benchmark contracts, Playground,
  and protected-object preservation. PostgreSQL proof must be actual or pending.
- Receipt-driven development is globally off, verified this turn. Do not start
  reviews, ask review consent, or enable it. Independent functional verification
  remains applicable to this integrity-sensitive change.
- Delivery strategy: exception-ok, retaining the user's existing coherent
  pending-version size exception without a numeric ceiling. Forecast: roughly
  250-500 authored lines; do not trim tests or docs to force a size target.
- Engram mirror: pending, because the runtime has no registered session identity
  and explicitly prohibits attributed memory tools. Do not substitute another ID.

## Tasks

- [x] MP1 — Profile and map the scaling path on fresh disposable data. Quantify
  request-only timings and separately instrumented SQL; preserve all existing
  witnesses; independently verify the measurements and semantic boundary.
  Owner/route: delegated profiler and independent verifier. Both completed;
  parent read both full reports and repeated the 14-test native-3.3 baseline.
- [ ] MP2 — Correct the scaling path after the contract decision below. Add a
  cause-correct failing regression; implement the smallest safe bounded check;
  preserve invalid FK/M2M errors, nested rollback and connection reuse. Update
  current docs and both changelogs alongside behavior and tests. Run focal and
  related checks, then close one Conventional work-unit commit with evidence.
  Owner/route: one delegated writer. Runtime evidence is required, not N/A.
- [ ] MP3 — Independently validate the exact candidate. Run the unchanged full
  native-3.3 suite and applicable coverage/quality/docs/example/Playground and
  benchmark gates. Reconcile profiling results and limitations; record actual,
  unavailable and pending checks. Close a tracking work-unit commit only after
  observed proof. Owner/route: independent delegated verifier, parent readback.

## Acceptance and next step

The successful path must not scan unrelated comment rows merely to create one
valid comment, and failure handling must remain safe inside an outer transaction.
No target latency is promised before measurement. Timings alone cannot replace a
structural bounded-work regression or correctness tests. A new whole-stack
canonical comparison and hosted delivery are separate follow-ups; old numbers
must remain explicitly attributed to their original measuring checkout.

Progress: MP1 profiling verified; MP2 is waiting for the human semantic-boundary
decision. No production code/test/docs or canonical benchmark artifact changed.
Next: ask one question about earlier unrelated deferred violations. Do not start
production edits until answered; optimization is not complete.

## Verified baseline and contract decision

The clean measuring checkout is exactly the base commit above, with prepared
metadata 4.0.0, Python 3.12.11, Django 6.0.8, SQLite 3.49.1 and the official
GraphQL-core 3.3.0 overlay. Four fresh external fixtures were generated explicitly
with BENCH_DATABASE; retained databases were never opened or copied.

| Mode / initial comments | 25-sample request p50 | Separate instrumented FK check |
| --- | ---: | ---: |
| Outer atomic, 50,000 | 5.851500 ms | 4.917541 ms; 87.137% of its own request |
| Outer atomic, 100,000 | 10.595166 ms | 9.565208 ms; 92.698% of its own request |
| Autocommit, 50,000 | 0.725125 ms | Absent; INSERT-only probe |
| Autocommit, 100,000 | 0.742333 ms | Absent; INSERT-only probe |

These are diagnostic single-machine measurements, not replacement canonical
medians or a promised speedup. Instrumented and p50 samples are distinct. The
initial autocommit driver incorrectly assumed every ID remained seed-count + 1;
its failed attempt is retained. The corrected driver used fresh autocommit data
and validated the actual incrementing IDs. Journals record order and elapsed
durations, not per-event UTC timestamps or continuous host quietness.

Both writer and independent verifier confirmed all 82 protected objects' bytes,
sizes, devices/inodes, modes and links unchanged. The focused 14-test baseline
passed; the parent independently repeated it with the same clean-source/official
overlay import selection and observed exit 0. No new full coverage/PG assertion
is made in this profiling-only phase.

The incidental-row probe demonstrated that a valid mutation currently raises
for an earlier unrelated invalid comment in the same outer transaction. Existing
tests require the mutation's own invalid-FK/M2M errors and rollback but do not
promise this unrelated-row detection. A post-write, mutation-scoped SQLite
checker would change that immediate behavior; unresolved deferred violations
would still be rejected at outer commit with FK enforcement enabled. Target
fields, M2M/custom through rows, aliases and side effects require actual tests;
this proposed checker is not implemented or verified. PostgreSQL remains on its
existing path unless separately justified and tested.

Human decision required: retain immediate detection of all earlier violations
in each checked table, or accept immediate checks scoped to the mutation's own
writes plus database enforcement at outer commit. Never infer that choice from
profiling PASS or silently remove the table check.

Reports are retained under the authorized visualization root:
graphex-resume-2026-10-02/mutation-constraint-profile/report.md and
mutation-constraint-profile/independent-verification/report.md. Both report
partial/complete statuses precisely: profiling PASS, optimization pending.

## Work-unit evidence

MP1 profiling recovery is a documentation-only work unit; its commit identity is
recorded after creation. No runtime implementation commit exists. Running
authored runtime changed-line count: 0. Rollback boundary: only this new
constraint-cost unit and its tests/docs, never the previously validated migration
integration. The Engram mirror remains explicitly pending.
