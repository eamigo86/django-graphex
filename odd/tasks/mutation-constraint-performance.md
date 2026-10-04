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
- [x] MP2 — Correct the scaling path after the contract decision below. Add a
  cause-correct failing regression; implement the smallest safe bounded check;
  preserve invalid FK/M2M errors, nested rollback and connection reuse. Update
  current docs and both changelogs alongside behavior and tests. Run focal and
  related checks, then close one Conventional work-unit commit with evidence.
  Owner/route: one delegated writer. Local native-3.3 runtime and diagnostic
  evidence passed at 3721404, but independent verification reopened this task
  for inherited-parent and symmetric-mirror regressions. Both have permanent
  correction tests and final local proof at 60ab332. Independent MP3 and
  actual PostgreSQL remain pending, not inferred from routing stand-ins. MP2
  was reopened for the proxy-mirror regression below and now has fresh local
  correction proof at e04a1ab; independent MP3 acceptance remains open.
- [x] MP3 — Independently validate the exact candidate. Run the unchanged full
  native-3.3 suite and applicable coverage/quality/docs/example/Playground and
  benchmark gates. Reconcile profiling results and limitations; record actual,
  unavailable and pending checks. Close a tracking work-unit commit only after
  observed proof. Owner/route: independent delegated verifier, parent readback.
  Local acceptance is verified at 4972464; actual PostgreSQL, fresh hosted
  matrix/gates, canonical comparison and delivery remain separate pending work.

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

## MP2 corrected local acceptance at executable commit 60ab332

The bounded symmetric fix checks both source-owner and mirror target-owner
through rows only for an actual symmetric self-relation. Other relations retain
source-owner-only SQL. A valid callable-default pair and an invalid mirror
created by ordinary Django relation management are tested. The invalid mirror
raises inside the mutation savepoint; its owner and links roll back and the
outer connection remains usable. The inheritance fix still checks parent-owned
FK columns in their physical parent table. The immutable independent findings
and all failed fixture and broader-run experiments remain retained separately.

The final clean 60ab332 clone passed 4,740 native-3.3 full-suite tests with
seven skips, three warnings, 23 subtests and 96.26% global branch coverage
against the unchanged 95.01% floor. Diff-cover found 70/71 changed runtime
lines covered (98.6%). Changed-branch analysis found 27/28 arcs covered
(96.43%). Full gap counts are now 258 missing lines, 265 partial sites,
273 all missing branch sites and 281 missing arcs versus the old CBC
258/266/274/282; these are counts, not identical source positions. All 331
benchmark and 59 standalone Playground tests, configured 79/82-file mypy,
Ruff, both zero-issue docstring gates, zero-issue docs build and diff check
passed. The exact command logs and coverage XML are under
graphex-resume-2026-10-02/mutation-constraint-performance-inheritance/.

Two new disposable 50k/100k-comment fixtures from 60ab332 supplied 25
rollback-only timed create-comment requests each. Their post-only p50 values
were 0.726333/0.729459 ms. One separately instrumented request at each size
had four statements: SAVEPOINT, INSERT, keyed CASE FK check and RELEASE; the
FK checks took 0.007458/0.006542 ms in those individual requests. Both new
database hashes, cardinalities and SQLite sequences stayed unchanged across
the rollback requests. The prior MP1 baseline was measured in another session:
this is not a paired controlled speedup, an updated canonical median,
continuous quiet-host proof or an Ariadne comparison. All 82 original retained
objects remained byte-and-stat identical; no retained database was opened for
SQLite work. Actual PostgreSQL integration and independent MP3 acceptance
remain pending. No main merge, tag or release is authorized.

## MP3 proxy-mirror blocker at bc3f826

Fresh independent verification reproduced another direct-write regression with
a standard Django proxy of the symmetric self-M2M model. The exact-class check
against the saved instance excludes the proxy although its actual related
manager still creates both forward and mirror rows. Candidate bc3f826 returns
success with an invalid newly created mirror; exact base 7eb3935 rejects it
inside the recovery savepoint. Outer commit still enforces integrity. The
permanent suite passing 4,740 tests is therefore not acceptance of this candidate.

MP2 is reopened for an observed proxy-specific RED and a bounded correction
using Django's declared relation/manager semantics, while retaining source-owner
only scope for ordinary non-self relations. Then repeat exact-source local gates
and independent acceptance. The failed-candidate evidence remains immutable in
graphex-resume-2026-10-02/independent-mutation-final/report.md. No broader audit,
canonical remeasurement, main merge, tag or publication is authorized.

Metric clarification: the configured branch-enabled coverage report's 96.26%
combines executable lines and branch arcs. The independently counted branch-arcs
only ratio is 92.7013%; these are distinct metrics. Do not label the combined
percentage as branch-arcs-only coverage. Preserve the configured 95.01% gate and
independently verify the changed-runtime line and changed-arc floors.

The proxy correction has a permanent three-way direct-write fixture: concrete,
proxy, and concrete child inheriting the parent-declared symmetric relation.
Before the source edit, the concrete case passed while proxy and inherited
cases failed with the same missing immediate `IntegrityError`; the raw RED is
under mutation-constraint-performance-proxy/red-proxy-inherited.log. Replacing
instance exact-class identity with declaration self-identity made all 27 focal
FK/savepoint/scoped tests pass. Ordinary non-self source-owner SQL remains an
explicit control. Final exact-source full/quality/diagnostic and independent
MP3 acceptance remain pending at this checkpoint.

One related-only test selection omitted `tests/test_converter.py`, whose
collection registers `tests_testmodel`; an unrelated user-delete cascade then
failed because that model's table was absent. The failed 1,262-pass run is
retained. Including that fixture-owning module in the related selection passed
1,292 tests. This does not replace the required unchanged full suite.

## MP2 proxy and inherited-relation local acceptance at e04a1ab

The minimal correction uses the declared symmetric self-relation's model
identity rather than the saved instance's exact Python class. A proxy and a
concrete child inheriting the relation now both reject an invalid newly
written mirror FK inside the recovery savepoint. The corresponding valid
mutations succeed in the same outer transaction. An ordinary non-self
custom-through relation remains source-owner-only. The raw RED and GREEN
logs are retained under mutation-constraint-performance-proxy/.

The exact clean e04a1ab clone passed 4,742 native-3.3 full-suite tests,
seven skips, three warnings and 23 subtests. The unchanged configured
branch-enabled combined line-plus-arc coverage gate passed at 96.26%
(13,886/14,425) against the 95.01% threshold. The branch-arcs-only ratio is
3,569/3,850 = 92.7013%; it is not a separate configured 95.01% gate.
Changed-runtime diff-cover was 70/71 lines (98.6%), and changed-branch
coverage was 27/28 arcs (96.43%), both above the requested 95.01% floor.
Gap counts are 258 missing lines, 265 partial sites, 273 total missing
branch sites and 281 missing arcs; counts are not source-position identities.
All 331 benchmark and 59 standalone Playground tests, Ruff, configured
79/82-file typing, both zero-issue docstring gates, zero-issue docs build
and diff check passed on the behavior commit.

Two NEW disposable 50k/100k-comment datasets from e04a1ab yielded post-only
create-comment p50 values of 0.735667/0.621292 ms over 25 rollback-only
timed requests each. A separate instrumented request at each size emitted
SAVEPOINT, INSERT, keyed CASE FK SELECT and RELEASE. Both new database file
hashes, cardinalities and SQLite sequences stayed unchanged across samples.
These are not paired speedups, canonical medians, quiet-host guarantees or
Ariadne comparisons. All 82 original protected objects and 295 prior proof
files remained byte-and-stat identical; no retained DB was SQLite-opened.
Actual PostgreSQL integration, hosted gates and independent MP3 acceptance
remain pending; no main merge, tag, publication or environment refresh is
authorized. The behavior commit is e04a1ab; this factual task checkpoint
must not relabel older failed candidates or the independent PARTIAL as PASS.

## MP3 independent local acceptance at 4972464

The independent verifier inspected and executed immutable candidate
4972464cc1b8301ee8c5fd706b1c449c12fc4d39, tree
b1e2239bf2a96e0cf7c05460bc3094878d8704a3. Its executable source matches
e04a1abda35bf6def27eedb89bd37354b2d73202. All original inherited-parent,
symmetric-mirror and proxy controls now pass, along with an actual separate
SQLite write-alias control whose default database remained unopened.

Fresh independent checks passed: 27 focal, 4,742 full, 331 benchmark and
59 standalone Playground tests; Ruff, check-only format, configured 79/82-file
mypy, both zero-issue docstring audits, zero-issue documentation build,
generated anchors/document readbacks and git diff check. The seven skips,
three warnings and 23 subtests match the retained baseline exactly; five skips
are pending actual PostgreSQL cases. Configured combined line-plus-arc coverage
is 13,886/14,425 (96.2634%). Global arcs alone are 3,569/3,850 (92.7013%),
a distinct metric. Changed-runtime coverage independently passes at 70/71
lines (98.5915%) and 27/28 arcs across 14 sites (96.4286%). The sole missing
changed arc is the defensive saved-row-disappeared path, 120 to 121.

The verifier authenticated the retained causal RED/GREEN sequences and
recomputed latest post-only diagnostic p50 values of 0.735667/0.621292 ms
from the 25 timed samples at each size. Each separate probe has four SQL
statements and one row-keyed FK check, not a table-wide scan. All recorded
responses pass the shared create-comment contract; recorded row/sequence and
file-hash witnesses match. No profiling database was reopened or remeasured.
These remain separate-session diagnostics, not paired speedups, canonical
medians, continuous host-quietness evidence or an Ariadne ranking.

Preservation passed for all 82 original protected objects, 295 prior evidence
files and 172 additional proof files, plus all 640 out-of-scope tracked blobs
and modes. Main, tag, root environment, canonical results and dependencies
remain unchanged. The parent read the full report and independently repeated
the exact 27-test focal command with the native 3.3 overlay from the clean
verified clone; exit 0, 27 passed. Its log is retained under
graphex-resume-2026-10-02/parent-mutation-4972464/focal-spot.log.

Full local acceptance report:
graphex-resume-2026-10-02/independent-mutation-4972464/report.md.
Earlier failed-candidate reports remain unchanged and are not retroactively
accepted. This checkpoint edits only this task document; no functional proof
is claimed for changed runtime bytes because none change here.

Next: separately validate actual PostgreSQL and the fresh hosted version matrix
before integration/delivery; a new official whole-stack benchmark comparison
requires its own measurement scope. No main merge, tag or publication is
authorized or performed. Engram recovery mirror remains pending under the
current unregistered-runtime restriction; RDD remains off.

MP3 tracking work-unit commit: 3400425f08fac89af14ceaf0a5568d1cdff094fc
(docs(perf): record independent scoped-validation acceptance). This identity
link changes only this feature document; the verified executable witness is
still e04a1ab and the independently tested candidate is still 4972464.

## Hosted security correction before dependency delivery

The first hosted run for dependency PR #243 at 9846515 passed PostgreSQL 17
and 14 of 15 validation jobs with both Codecov checks, but the lint/security
job failed Bandit B608 at three dynamically assembled scoped-check statements
in backend.py (old lines 102, 111 and 155). That run is a real failure, not a
hosted pass or a reason to relax the security job. A fresh local configured
Bandit command reproduced exactly those three findings before correction.

The identifiers in those statements originate in Django model metadata and
use connection.ops.quote_name; caller-owned row keys and diagnostic field
names are passed as bound parameters. A new disposable-schema regression
records pre-interpolation SQL and parameters for a SQL-looking owner key and
SQL-keyword declared table names, verifies a valid mutation and scoped link,
and confirms an invalid direct link is rejected without damaging unrelated
rows or the outer connection. This behavioral control already passed before
source annotations; the cause-correct RED is the actual configured Bandit
scan. Exactly three local B608 annotations explain the identifier/parameter
boundary, and Python AST equality confirms no runtime semantics changed.
The configured local Bandit scan then passed with no issues. Final clean-clone
native-3.3/full/quality/protection checks and fresh hosted delivery are still
pending at this checkpoint. No previous report or dataset is reclassified.

Security behavior commit 354391d68334a1bc1babf221e68f327cce1a7e42
passed the exact configured Bandit scan with zero issues in a clean real
native-3.3 clone. That source's unchanged full suite passed 4,743 tests,
seven skips, three warnings and 23 subtests at 96.26% configured combined
coverage (95.01% floor). The 28-test FK/security focal, 331 benchmark tests
and all 59 standalone Playground tests passed. Whole Ruff, 79/82-file mypy,
both zero-issue docstring gates, zero-issue documentation build and diff check
passed. Diff-cover against base 7eb3935 found 70/71 changed executable
runtime lines covered (98.6%). The correction is annotation-only and has the
same Python AST as 9846515, so it introduces no new runtime branch arcs;
the earlier independent 27/28 changed-arc proof remains for those unchanged
branches, not a newly measured arc-only percentage. All 82 retained protected
objects match prior SHA, size, device, inode, mode and link count. The first
test fixture attempted a direct dynamic-model M2M mutation whose registry
relation was unavailable; that setup failure is retained, not called a
security RED. The corrected SQL-binding control passed before annotation.
Fresh hosted lint/matrix checks at this new head remain pending. Actual
PostgreSQL17 passed on the earlier failed hosted run, not yet this candidate.
