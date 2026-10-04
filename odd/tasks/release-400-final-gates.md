# Close the prepared 4.0.0 release gates

## Objective and authorized scope

The user explicitly authorizes the remaining work: raise actual global branch
coverage to at least 95.01%, enforce that distinct metric in CI, repair the
generated 404 skip-link target with a regression, and revalidate integration.
The prior 96.26% combined line-plus-branch result does not satisfy the pure
branch requirement. Do not change library behavior merely to improve coverage.

- Base: integration 3415e904c9acaf90b4403d97cfbd18b6c15ba491, tree
  47f6a8f94ba9c40bca53597d0cc373faf4a060c1; prepared version 4.0.0.
- Feature branch: codex/graphql-core-3.3-release-gates.
- The previous local recovery commit 2dcc3c7 remains on its existing branch;
  it is not silently pushed or mixed into this child.
- GitHub scope: eamigo86/django-graphex, HTTPS/keyring account eamigo86,
  approved issue #210 and draft tracker #212. Retained authorization permits
  child pushes/PRs/comments and integration-only merges after exact-head gates.
- No main merge, tag, publication, workflow dispatch, remote server access,
  dependency refresh or branch deletion. FG5 separately authorizes additive
  fresh private seeds and final-source benchmark timing; earlier retained
  databases and canonical results remain protected. No timing occurs in FG2.
- Runtime identity is unregistered. All agent-attributed Engram tools are
  prohibited; the local task file is the recovery record and mirror is pending.
- RDD remains globally off. Do not start or enable a native review lifecycle.

## Findings and constraints

- Accepted native-3.3 XML has 3,569/3,850 covered branch outcomes (92.70%).
  At least 3,658/3,850 are needed for 95.01%; target a reasonable margin, then
  prove the actual denominator and outcomes in fresh full-suite XML.
- Optimizer and compiler/type construction tests provide meaningful uncovered
  behavior seams. Assert ORM/schema/result behavior, not just helper invocation.
- Preserve all coverage sources, branch measurement, existing exclusions,
  combined 95.01% and patch 95.01% gates. No skips, pragma exclusions, dummy
  branch removal, addopts overrides or ignored warnings to make a gate green.
- Zensical's pinned 404 template bypasses the content partial that normally
  provides the skip target. Use a repo-owned template override, not a global
  dependency patch, generated-site edit, hidden link or dependency upgrade.
- Keep every old/new benchmark artifact, raw batch, pin, report and retained
  database intact. Databases are hash/stat only; never connect, copy or reset.
- Root core 3.2.13 stays unchanged. Verify in clean real clones with the retained
  native-3.3 overlay and explicit source/module/distribution assertions.
- Technical artifacts are English. Docstrings are complete Google style,
  with parameter/return hints, no repeated types and no backticks anywhere.

## Tasks and implementation route

- [x] FG1 — Add a fail-closed pure-branch XML checker with executable boundary,
  malformed/missing/zero-count and CLI tests. Integer/decimal exact comparison,
  never rounded XML rates. Demonstrate the accepted 92.70% baseline fails.
  Delegated direct: multi-file script/tests and preparation require a writer.
- [ ] FG2 — Add behavior-focused optimizer/compiler/type tests until fresh
  full-suite pure branch coverage is at least 95.01%, with margin where useful.
  Do not alter runtime merely to improve coverage or change denominator policy.
  Delegated direct:
  multiple non-trivial test modules and fresh native full-suite execution.
- [ ] FG2-R — Correct the independently observed valid-fragment annotation
  failure in the optimizer, with strict cause-correct RED/GREEN, real GraphQL
  result and SQL regressions, behavioral documentation and both prepared-release
  changelogs. The user explicitly authorized this runtime correction after the
  read-only premise probe; it is not coverage padding or a proven regression
  against a prior release. Delegated direct: runtime, tests and docs form one
  coherent bounded unit. Functional correction passed, but independent patch
  coverage was 23/27 changed lines, below 95.01%; test-only boundary proof is
  pending. No benchmark measurement in the correction unit.
- [ ] FG3 — Wire the pure-branch checker into the existing coverage job, repair
  the 404 template, add a generated-site check to docs CI, and update contributor
  guidance and both prepared-release changelogs. Preserve the release graph.
  Delegated direct: workflow, template, helpers, tests and docs form one unit.
- [ ] FG4 — Independently verify exact final candidate, coverage arithmetic and
  negative controls, docs/site anchors, examples/Playground, quality and preserved
  state. Parent spot check, child/integration/tracker exact-head hosted gates;
  report remaining main/tag/publication approvals. Delegated verifier plus
  read-only parent remote orchestration; no invented release readiness.
- [ ] FG5 — After the corrected runtime and FG2/FG3 stabilize, regenerate the
  official named-profile comparison from that final source, keeping earlier
  measurements attributed to their original source and preserving both series.
  The user authorized this future cost; actual datasets, timings, arithmetic,
  protected-state checks and publication are a separate bounded unit before
  FG4 final acceptance, not part of FG2-R.

## Strict TDD and checks

Strict TDD is ON from user AGENTS.md. For new checker, YAML and template
contracts, retain cause-correct RED before implementation, minimal GREEN and
REFACTOR. For coverage-only tests of already-correct behavior, the observed
RED is the honest baseline coverage acceptance failure, not an artificial
runtime bug or deliberately broken test. Record that distinction explicitly.

- Focal runner: .venv/bin/python -m pytest <selected tests> --no-cov.
- Full runner: .venv/bin/python -m pytest, unchanged addopts and PID-owned
  coverage; use an absolute retained interpreter and clean native-3.3 clone.
- Exact fresh coverage XML: pure branches >=95.01%, combined >=95.01% and
  applicable existing patch gate >=95.01%. Do not claim N/A as 100%.
- Benchmark contracts and byte equality, no timing/republication required
  while measured package runtime remains unchanged.
- Ruff, check-only format, configured/expanded/CLI typing, Bandit, both
  zero-issue docstring audits, clean docs build and generated-site anchors,
  standalone Playground/examples, git diff --check and full suite.
- Hosted six-version matrix, real PostgreSQL 17, base install, coverage,
  quality/security, docs, Playground and external wheel/audit checks, all
  validation jobs and both Codecov checks on exact child and integration heads.
- Publication/create-release/deploy-docs must remain skipped on branch events.

## Delivery and progress

Chosen route is delegated direct, not SDD. One sole writer handles sequential
units; independent verification is read-only. Each unit closes with a
Conventional Commit, its tests/docs, exact checks and rollback boundary.
Never add Co-Authored-By or AI attribution. Record commit identities below.

Forecast: 1,000-2,000 authored changed lines, no generated benchmark files.
Delivery strategy: exception-ok, feature-branch-chain into the existing tracker
integration, under the maintainer's already-approved coherent pending-version
size exception without a numeric ceiling. Keep logical commits; do not shrink
tests, comments or documentation for cosmetic line savings. The cohesive child
follows #245 and carries exactly one type label plus size:exception if needed.

Read-only mapping verified the branch denominator, existing coverage job and
Zensical template origin. Issue #210 remains OPEN/status:approved; tracker
#212 is OPEN/DRAFT at the base above. No implementation checks are claimed yet.

Next: FG1 checker TDD, then coverage acceptance RED and FG2 meaningful tests,
then FG3 CI/template/documentation and FG4 independent/hosted validation.

## Evidence and rollback

Keep raw command logs and immutable reports in a new owned external proof
directory, preserving failed attempts. Do not overwrite prior evidence.
FG1 rollback removes only its checker/tests; FG2 removes its new tests;
FG3 removes its workflow/template/docs/checker changes; prior runtime and
benchmark results remain intact. A final local recovery-only checkpoint may
record hosted results without pretending its own task bytes had a new CI run.

## FG1 local acceptance and FG2 boundary

The missing-checker focused suite failed 21 executable controls before the
script existed; the first implementation passed all 21. Normalization added
Google-style test docstrings and check-only formatting, then the configured
coverage-policy test and new suite passed 22 controls. The standalone checker
reads only the Cobertura root's integer branches-covered/branches-valid and
was intended to compare the exact fraction to the default 95.01% threshold.
It rejects absent/malformed reports, zero totals, invalid counts and invalid thresholds;
the XML's rounded branch-rate value never decides acceptance. The contributor
guide documents this manual command without claiming CI wiring.

Behavior, tests and guide work-unit commit:
167a057d97a00ad863358e36bb092afb0e16013f (tree
5ff92481a79c67cb6f55fafae2199188468be8c9). A fresh clean native-3.3
clone of that exact commit passed 22 focused controls and the unchanged full
suite: 4,778 passed, seven skipped, three warnings and 23 subtests, with
96.26% combined coverage above the existing 95.01% floor. Ruff/check-only
format, standalone-script and configured/expanded/CLI typing, both zero-issue
docstring audits, Bandit and clean Zensical build passed. Package runtime
tree remains 125843bf27db5ce3af004e52e429c03a26054eeb. No coverage
configuration, exclusion, denominator or existing gate changed.

The accepted old XML and this fresh full-suite XML both correctly **fail**
the new pure-branch checker: 3,569/3,850 = 92.7013%, below 95.01%. This is
the real FG2 acceptance RED, not a checker failure or a fabricated runtime
bug. FG2 must add meaningful behavior-focused tests and achieve the pure
branch floor before FG3 wires the checker into CI. This task-only evidence
checkpoint does not reclassify the unmet release gate as passed. Full local
proof: final-gates-fg1/report.md under the retained external proof root.
No installer, remote operation, database connection, benchmark measurement,
main merge, tag or publication occurred. Engram mirror remains pending.
Read-only protection checking found no content mismatch among 82 original and
47 newer assets. Eight tracked new-series JSON files have inode numbers
different from the earlier OC2 inventory; their SHA, size, device, mode and
link counts match. This metadata drift is disclosed, not called full
filesystem-identity equality or attributed to an unverified cause. Retained
databases were hash/stat only and retain their recorded identities.

## FG1 precision correction

Parent structural review found that Decimal multiplication in the first
checker could round a threshold immediately above 95.01% down to the covered
fraction. A new real CLI control using 9,501/10,000 and threshold
95.0100000000000000000000000001 failed against commit 8049fe12d561c6304a8eb2285803b7498aea744c:
the checker incorrectly returned PASS. Before the source fix, this is a
distinct cause-correct RED; it is not reconstructed from the first FG1 RED.

The correction converts the parsed Decimal threshold to an exact Fraction
and compares integer crossproducts; percentage rounding is display-only.
The real CLI control then passed. Behavior/tests commit
41198fff65e393e4887043b5abc6dbf8592e1ed0 (tree
0bd5149e00fc8bdbe264da4190f1fc478c8dd7e8) passed 23 focal controls
and a fresh native-3.3 clean-clone full run: 4,779 passed, seven skipped,
three warnings, 23 subtests and 96.26% combined coverage. Ruff/check-only
format, script/package/expanded/CLI typing, both zero-issue docstring audits,
Bandit and clean Zensical build passed. Old and fresh XML still correctly
fail the pure-branch gate at 3,569/3,850 = 92.7013%; FG2 remains open.

A new FG1-correction snapshot before and after the edit/checks compared the
same 129 protected paths and found exact SHA, size, device, inode, mode and
link equality. It does not erase or explain the eight earlier new-series
JSON inode differences versus the older OC2 inventory; no FG1-start inode
snapshot exists. Retained databases were hash/stat checked only. Proof is
under final-gates-fg1-precision/; original FG1 logs and report are unchanged.
This task-only evidence checkpoint does not imply a separate full-suite run.
FG2, FG3 and FG4 remain pending; package source tree is unchanged.

## FG2 partial test-coverage progress

FG2 remains unchecked. The real FG1 baseline was 3,569/3,850 pure branches
(92.7013%). Two new behavior-test work units cover conservative optimizer
prefetch handling and pair-local compiler safeguards:
79e2158f46027268cf94bd50971c9b42879f9eb1 and
1b4d25afc7926c9568c0a1a596e53b27caa088e6. The tests assert join
columns, full-load fallbacks, fragment plans, stable pair identity and
fail-closed registry behavior; no package runtime or coverage policy changed.
These existing behaviors passed immediately, so their objective was coverage
of the already observed branch-gate RED, not a fabricated behavior RED.

A fresh exact-commit native-3.3 clean-clone full run at 1b4d25a passed
4,789 tests with seven skips, three warnings, 23 subtests and 96.42%
combined coverage. The new pure-branch gate still correctly **fails**:
3,582/3,850 = 93.0390%, a gain of 13 covered arcs with no denominator
change or newly missing arc. Exactly 76 more covered arcs are required for
95.01% at the unchanged denominator. The seven optimizer tests yielded 11
arcs; three compiler safeguards yielded two. This is meaningful but well
short of acceptance, so there is no FG2 completion claim and no FG3 wiring.

Focal optimizer and compiler suites, all 344 benchmark contracts and all
59 standalone Playground tests passed. The full clean-clone quality checks
passed: Ruff/check-only format, script/configured/expanded/CLI mypy, both
zero-issue docstring gates, Bandit, Zensical and diff check. A first
Playground proof driver used the wrong settings module and failed before
collection; its raw failure is retained, and the corrected existing
config.settings invocation passed all 59. This was a proof-driver mistake,
not a candidate test failure. The first benchmark log was overwritten by
the corrected driver's duplicate benchmark run; its original command and
observed 344-pass result remain in the driver and tool record, not an
immutable separate stdout file.

Next bounded cluster: exercise meaningful wrapper/fragment, nested prefetch
and annotated promotion outcomes in utils.py, then native relation/type
and schema/output compiler shapes. Current missing-arc concentrations are
utils.py 57, types.py 44 and the schema/output compilers 22; there is no
claim every arc is feasible or that merely calling a helper suffices.
Evidence and exact raw logs are under final-gates-fg2/ in the retained
external proof root; before/after protected snapshots of the same 129
paths match exactly, including inode and database hash/stat identities.
The historical older-OC2 inode distinction remains separate.

### FG2 native relation and compiler continuation

Work unit ba95c1f3b56b70e4bfbcc911768bb03216e2b31b adds 29 executable
behavioral cases across native output scalar/choice handling, forward and
reverse relation projection, reverse one-to-one resolution, permission labels,
resolver binding, and compiled Django output arguments. They check concrete
GraphQL field shapes, selected containers, values, and absent-relation behavior;
existing correct behavior passed without a fabricated runtime RED. An initial
test call omitted the documented third compiler argument and failed; its log
is retained separately from the corrected focal run.

The normalized exact-commit clean-clone run passed 4,818 tests, seven skips,
three warnings and 23 subtests with 96.60% combined coverage. The exact
pure-branch gate still correctly fails at **3,594/3,850 = 93.3506%**: 12 new
arcs, no new missing arcs and an unchanged denominator. Exactly 64 additional
covered arcs are needed for the 95.01% floor. All 344 benchmark contracts,
59 standalone Playground tests, 88 selected compiler/relation tests, Ruff,
check-only formatting, configured/expanded/CLI mypy, both zero-issue docstring
audits, Bandit and the zero-issue documentation build passed. The 129 protected
asset records matched byte and stat identity before/after this unit; package
source tree 125843bf27db5ce3af004e52e429c03a26054eeb and all public
documentation bytes remain unchanged. Raw commands and arc identities are in
the external final-gates-fg2-types/ proof directory.

FG2 remains unchecked, with FG3 and FG4 pending. The next coherent behavior
test cluster should target the larger remaining optimizer/type gaps rather than
claiming that the current compiler cases meet the release floor. Rolling back
this work unit removes its three test-file changes only; this factual task
checkpoint is not a fresh full-suite execution.

## FG2-R authorized runtime correction boundary

The read-only exact-e220800 optimizer premise probe found a valid-query bug:
flat `author { name postCount }` returned the annotated value 1 with two
request SQL statements, but the same selection inside valid named and inline
fragments returned null without GraphQL errors and emitted one joined query
without the annotation. The original failed two-of-three probe is retained
under final-gates-fg2-optimizer/ and did not change repository source.

The user explicitly approved correcting this behavior with strict TDD and
regenerating the official comparison against final code. FG2-R owns only the
fragment-aware promotion correction, real GraphQL/ORM tests and behavior docs;
FG5 owns the later costly benchmark regeneration. FG2, FG3, FG4 and FG5 remain
pending. The previously measured package tree and pure 3,594/3,850 coverage
are historical facts at e220800, not invariants after a justified runtime
change. Keep the coverage policy unchanged and disclose the new denominator.
The local Engram mirror remains pending; RDD is off. This checkpoint precedes
source edits and claims no new RED/GREEN or verification outcome.

### FG2-R observed local acceptance

The new real GraphQL/ORM fragment contract failed five positive fragment
cases against e220800 before the source correction; three direct/directive
controls passed. Its initial corrected run passed all eight, and the frozen
behavior candidate 4d974a7ee6f936928d520087648ab0d53349169a (tree
236f63db0315b6c89cef083cc208fb182b86fdee) passed 106 selected optimizer
and directive tests. The promotion walker now follows applicable named and
inline fragments at relation, child and list-wrapper levels, applying bound
directives and schema type conditions. The tests assert actual non-null values
and annotation SQL, not helper call counts.

A clean real native-3.3 clone of that exact candidate passed 4,826 full tests,
seven skips, three warnings and 23 subtests at 96.63% combined coverage. All
344 benchmark contracts and 59 standalone Playground tests passed. Ruff and
check-only format, configured/expanded/CLI mypy, Bandit, both zero-issue
docstring audits, Zensical zero-issue build and diff check passed. The same
129 protected files matched byte and stat identity before/after; retained
databases were hash/stat only. Package source changed intentionally; the
existing official benchmark series still describes its old measurement source
and must not be relabeled. Complete raw proof is under final-gates-fragment-fix/.

FG2 remains open: fresh pure branches are **3,608/3,864 = 93.3747%**, below
95.01%; the checker correctly exits nonzero. This is 14 additional covered
arcs with 14 additional valid outcomes versus e220800, not a coverage-policy
change. At the new denominator, 64 more covered arcs are needed. FG3, FG4 and
the separately authorized final-source benchmark regeneration FG5 remain
pending. This task-only acceptance checkpoint has not had a separate full run;
its rollback boundary is the behavior work unit above, with the prior
measurements and canonical artifacts untouched.

Independent read-only verification of 4d974a7 passed 106 writer-selected
controls and 14 additional real GraphQL/ORM fragment controls. It found no
scoped behavior defect. The authenticated writer XML and nonempty path-bound
diff-cover result, however, covered only 23/27 changed runtime lines
(85.1852%). An earlier empty-denominator diff-cover exit zero was not a
passing gate. Missing lines are the untyped inline condition, unavailable
current type, absent selection set and active cyclic spread guards. The full
partial report is under final-gates-fragment-independent/. FG2-R remains open
for test-only boundary coverage; FG2's global pure floor also remains open.

### FG2 test-only boundary continuation

Test work unit a95549238c9a0ae657c38bdd07b09b067892e3a8 (tree
5284dea98392c453ad6e3303b3bf95b3873f571d) adds 16 meaningful cases:
valid nested named/typed/untyped fragments with distinct real author counts,
bound directives, selected wrapper count, and explicit optimizer column-plan
contracts for computed versus stored leaves, annotations, reverse-FK owner
keys and the registered list wrapper. A later test-docstring-only correction
is 0cd0b58671ce0c2514e2aa14ae76ec893d92a7b6. The runtime package tree
remains f682c637f25ecaaaaf19b287617d3248f50ef391.

The exact 0cd0b58 clean-clone run passed 122 selected tests, 4,842 full tests
at 96.68% combined coverage, all 344 benchmark contracts, 59 standalone
Playground tests and all Ruff, type, Bandit, zero-docstring and documentation
gates. The pure checker still correctly fails: **3,612/3,864 = 93.4783%**;
60 further covered outcomes are required at this denominator. The nonempty,
source-path-bound patch result improved from 23/27 to **24/27 = 88.89%**,
still below 95.01%, against both e220800 and integration 3415e9. Missing
changed runtime statements are the unavailable-current-type, absent-selection
and active-cycle guards. An unvalidated cyclic GraphQL AST returned an error
before reaching the new promotion walker; this did not prove that guard or
become a valid-query success test. No runtime source, coverage policy or
canonical artifact changed. All 129 protected path identities matched.

FG2-R and FG2 remain unchecked. This bounded test unit did not establish the
two coverage floors. The local report and immutable attempts are under
final-gates-fg2-boundaries/. A further authorized decision is needed for
remaining guard-line proof if those states cannot be reached through supported
optimizer inputs; do not delete guards, add exclusions or count an empty
diff-cover denominator as PASS. FG3/FG5/FG4 remain pending.
