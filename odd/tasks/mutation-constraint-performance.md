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
50,000 to 100,000 rows. Initial static inspection did not quantify the check's
share of elapsed time; the separate diagnostic evidence below now does.

## Authority and boundaries

- User explicitly authorized profiling and optimization on 2026-10-03.
- The user subsequently explicitly accepted immediate SQLite checks limited to
  the mutation's direct writes, leaving earlier unrelated deferred violations
  for enforcement at outer commit if they remain unresolved. Implement this
  selected contract with strict TDD; do not ask the same choice again.
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
  Owner/route: one delegated writer. Local native-3.3 runtime and diagnostic
  evidence passed at 3721404, but independent verification reopened this task:
  valid multi-table inheritance with a parent-owned FK fails on the new checker.
  Actual PostgreSQL remains pending, not inferred from the routing stand-in.
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

Historical MP1 checkpoint: profiling verified; the human semantic-boundary
decision for MP2 is accepted. No production code/test/docs or canonical
benchmark artifact has
changed yet. Next: delegate one bounded strict-TDD writer for MP2, then rerun
diagnostic timings with fresh data and independently verify the exact candidate.

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

Human decision: the user explicitly accepted immediate validation of SQLite
changes directly saved by the mutation, with database enforcement of remaining
violations at outer commit. This permits replacing the table-wide SQLite scan,
not skipping the mutation's own FK/M2M validation or its rollback boundary.
PostgreSQL and other backends retain their current deferred-constraint path.
Tests and current documentation must explicitly demonstrate the accepted
earlier-unrelated-row behavior and the still-failing unresolved outer commit.

Reports are retained under the authorized visualization root:
graphex-resume-2026-10-02/mutation-constraint-profile/report.md and
mutation-constraint-profile/independent-verification/report.md. Both report
partial/complete statuses precisely: profiling PASS, optimization pending.

## Work-unit evidence

MP1 work-unit commit: 42102f6ed829a88628c96f3094f60b3ab2f0b3e6
(docs(perf): record constraint profiling and contract decision). Its 147 authored
lines are profiling recovery only; no runtime implementation commit exists.
Running authored runtime changed-line count: 0. Rollback boundary: only this new
constraint-cost unit and its tests/docs, never the previously validated migration
integration. The Engram mirror remains explicitly pending.

The following small tracking checkpoint records MP1's immutable commit identity;
it does not close MP2/MP3 or claim optimized performance, coverage or delivery.

## MP2 implementation checkpoint

Strict TDD produced two cause-correct REDs before the SQLite source edit:
`tests/core/test_scoped_mutation_constraints.py` rejected the table-wide
`PRAGMA foreign_key_check` and proved the old check rejected a valid mutation
because of an earlier unrelated invalid row. A later non-primary target-field
regression failed on the diagnostic path's primary-key-only lookup before that
lookup was corrected. Raw chronological logs are under
`mutation-constraint-performance-mp2/`; neither RED is reconstructed.

The candidate now checks persisted constrained FK values on the saved row and
the current object's directly updated M2M through rows after writing, within
the existing rollback boundary. It uses the write's database alias and actual
referenced target columns; `db_constraint=False` is not invented as a database
constraint. PostgreSQL and other backends retain their previous check path.
The existing golden error, rollback, nested-write and autocommit contracts plus
five new focused tests passed (19 total); related core/mutation tests passed
1,295. The earlier invalid row remains for outer-commit enforcement, as chosen.
This is not yet full native-3.3/quality/performance or independent acceptance;
MP2 and MP3 remain open until those checks and separate review are observed.

The first behavior commit, 3dc7e27bc4fff4e86abee2f16feca266aa5d3343,
failed its unchanged clean-clone full suite in three candidate-caused contracts:
the new bounded-query test, the four-statement benchmark SQL contract, and a
reverse-child reread count. That 4,731-pass/three-failure run is retained, not
relabeled as proof. A bounded correction folds persisted FK checks into one
NULL-guarded CASE statement, keeps one explicit scoped-check SQL assertion
separate from the two ORM rereads, and updates the benchmark statement shape
without changing its four-statement count. An existing nullable-FK test now
distinguishes an eager standalone category probe from the NULL-guarded branch
of that single post-write statement. The observed correction RED and subsequent
seven-test and 1,257-test GREEN logs are retained under the same proof root.
A fresh UUID key regression then failed on an unadapted through-owner value;
it passed after preparing row and owner key parameters with their Django
fields. Composite primary keys retain the previous table-scoped fallback,
rather than silently dropping checks for an unsupported row-key shape.
The final exact-head full suite, changed-line coverage and disposable 50k/100k
performance profile are still pending at this checkpoint.

The first clean correction clone at dd90b97 still failed one new test under
the full suite's richer fixture order: unrelated relation serialization added
extra SELECTs outside the checker. The corrected assertion bounds the checker
itself to exactly one saved-row-key-filtered CASE query and forbids the
table-wide PRAGMA, without claiming all serialization SQL is fixed. That
failed full run (4,734 pass/one fail) is also retained; the 17-test focal
passed after the assertion correction. Its exact-head full run remains pending.

At fea81d7e372282f26bc24c1acd6a24aa7c926805, the clean native-3.3 full
suite passed 4,735 tests with seven skips, three warnings, 23 subtests and
96.16% total branch coverage (unchanged 95.01% floor). All 331 benchmark
tests, 59 Playground tests, configured 79/82-file typing, both docstring gates,
Ruff and docs build passed. The first changed-runtime diff-cover measured only
83% (51/61 lines), so MP2 remains open: focused composite-key fallback and
non-SQLite branch-routing tests were added without claiming that a SQLite
stand-in is actual PostgreSQL integration. Their initial fixture typo failed
before correction, and the two-test focused rerun passed. A new exact-head
full/diff-coverage proof and post-change disposable performance profile remain
pending.

## MP2 local acceptance at executable commit 3721404

The clean REAL clone at 37214043ff4959d7640c2c7b56e5712e08fb9f2f passed
the unchanged native-3.3 full suite: 4,737 passed, seven skipped, three
warnings, 23 subtests, and 96.25% branch coverage against the unchanged
95.01% floor. Its gap **counts** equal the CBC baseline (258 missing lines,
266 partial branch sites, 274 total missing branch sites, 282 missing arcs);
runtime edits shift line identities, so count equality is not gap-identity
equality. Diff-cover found 60/61 changed runtime executable lines covered
(98.4%). Of 22 arcs on 11 changed branch sites, 21 were covered (95.45%);
the missing arc is the saved-row-disappeared defensive branch at line 117.
The 331 benchmark tests and all 59 standalone Playground tests passed.
Ruff, configured mypy 79/82 files, both public docstring gates at zero,
Zensical build with no issues, and diff checks passed in that same clone.

Only two NEW disposable databases under the MP2 proof root were migrated and
seeded for post-change diagnostic profiling. Their 50k/100k-comment
create-comment outer-atomic request p50 values were 0.635958/0.476375 ms
across 25 timed requests each. One separate instrumented request at each size
had four statements: SAVEPOINT, INSERT, one primary-key-filtered CASE FK
query, and RELEASE. Its FK query took 0.0077/0.0067 ms respectively; these
instrumented values are not p50 components. Both private fixture hashes,
row counts and SQLite sequences were unchanged before/after the rollback
requests. This is a separate-session diagnostic against MP1's 5.851500 and
10.595166 ms old-source baselines, NOT a paired controlled speedup estimate,
new canonical median, quiet-host attestation, or Ariadne comparison. The 82
retained protected objects remained byte-and-stat identical. No retained
database was opened for SQLite work. Actual PostgreSQL integration and MP3
independent verification are still pending; no main merge/tag/release is
authorized. Full raw tests, SQL, driver commands, protections and limits are
under graphex-resume-2026-10-02/mutation-constraint-performance-mp2/.

## MP3 blocker and bounded MP2 correction

Independent verification of 2cebebc624420a8d831c1f710c68f6d6cd0faaf1
confirmed a candidate-caused regression: a valid multi-table-inherited model
whose concrete parent owns a foreign key raises OperationalError because the
new CASE reads child.target_id from the child table, while that column is stored
in the parent table. The identical fixture succeeds on exact base 7eb3935.
Rollback and connection usability remained correct; no corruption was observed.
All 82 protected objects remained unchanged. Broader MP3 gates were deferred,
not passed; actual PostgreSQL remains pending.

MP2 is reopened for a cause-correct regression test and bounded correction that
validates direct saved rows in their actual owning tables, with parent-row FK
failure and rollback controls. Preserve the accepted mutation-owned scope and
ordinary four-statement comment contract. Do not hide the issue with weakened
tests or a global scan of unrelated rows. After correction, rerun final exact
gates and diagnostic timings, then repeat independent MP3 acceptance.

The failed-candidate report and exact base/candidate reproduction are retained
under graphex-resume-2026-10-02/independent-mutation-2cebebc/report.md.

The inheritance correction has a fresh permanent cause-correct RED before the
production edit. Its first fixture used a non-primary target input rejected
by the existing schema before reaching SQL; that failed attempt is retained,
not claimed as the target RED. The corrected normal-FK fixture produced two
`no such column: child.target_id` failures on 2cebebc. The fix groups
constrained concrete FKs by `field.model`, queries each physical owner table
through that owner's prepared primary key, and still checks the child's
parent link. Valid inherited create, invalid parent-FK create/update,
nullable inheritance, rollback and connection reuse passed the 25-test
focused run. Ordinary comment SQL remains four statements. Both changelogs,
mutation guidance and the comparison page now explain the physical parent
scope and that retained numbers predate this change. Final exact-head gates,
independent recheck and fresh disposable post-correction profiling remain
pending at this checkpoint.

Independent verification also found a second direct-write regression at the
same 2cebebc candidate: a standard symmetric self-M2M with a custom through
model creates forward and mirror rows, but the scoped checker inspected only
the new owner's outgoing rows. A callable default made the newly written
mirror row's extra FK invalid; the backend returned success until outer COMMIT
failed. Exact base 7eb3935 rejected it inside the mutation savepoint. MP2
remains open for a fresh cause-correct RED and a mirror-only correction on
genuinely symmetric self-relations. The inheritance-only 3a777b9 full and
quality checks are intermediate proof, not final acceptance. The immutable
reproduction is in independent-mutation-symmetric/report.md; MP3 remains open.

The symmetric correction's first test fixture assumed its new installed-app
tables were absent, but Django had already created them; that setup failure is
retained separately and is not the cause-correct RED. The corrected fixture
failed on inheritance-only 3a777b9 because the invalid mirror returned success.
After the bounded mirror predicate, 25 FK/savepoint/scoped tests passed,
including invalid mirror rollback and valid callable-default links. The
non-self custom-through test asserts source-owner-only SQL. Final exact-head
gates, disposable profile and independent MP3 remain pending here.

The first GREEN fixture registered temporary symmetric models globally in the
installed tests app. A combined core/mutation run then failed one unrelated
delete because a separately registered test model's table was absent; the
isolated delete alone passed. An uninstalled fixture app could not resolve the
M2M reverse relation. The final fixture uses Django's isolated app registry
and explicit temporary schema; the combined core/mutation run then passed
1,261 tests. Both failed experiments and the corrected result are retained.
