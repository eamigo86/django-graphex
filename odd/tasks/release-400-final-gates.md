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
- [x] FG2 — Add behavior-focused optimizer/compiler/type tests until fresh
  full-suite pure branch coverage is at least 95.01%, with margin where useful.
  Do not alter runtime merely to improve coverage or change denominator policy.
  Delegated direct:
  multiple non-trivial test modules and fresh native full-suite execution.
- [x] FG2-R — Correct the independently observed valid-fragment annotation
  failure in the optimizer, with strict cause-correct RED/GREEN, real GraphQL
  result and SQL regressions, behavioral documentation and both prepared-release
  changelogs. The user explicitly authorized this runtime correction after the
  read-only premise probe; it is not coverage padding or a proven regression
  against a prior release. Delegated direct: runtime, tests and docs form one
  coherent bounded unit. Functional correction passed, but independent patch
  coverage was initially 23/27 changed lines, below 95.01%; the later private
  walker test boundary reached 30/30. No benchmark measurement was performed
  in the correction unit.
- [x] FG3 — Wire the pure-branch checker into the existing coverage job, repair
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

### FG2-R private AST walker refactor authorization

The parent authorized a behavior-preserving extraction of the existing nested
fragment selection walker into one private module-level helper. Direct AST
contracts can then exercise None input, unknown type, missing and cyclic
fragments, repeated spreads, bound directives and schema type applicability
without presenting invalid GraphQL documents as successful API requests. This
is the REFACTOR phase of the already observed public behavior RED/GREEN, not a
new public feature or permission to delete guards. Fresh helper-availability
RED and then actual contract GREEN are required before rerunning the unchanged
public regressions. The current package tree and both coverage failures above
remain historical facts until a new exact candidate is measured; FG5 still
waits for final runtime stabilization. No timing occurs in this unit.

### FG2-R private walker local acceptance

The new direct AST contract failed at collection before extraction because
the private iterator did not exist (red-01 exit 2); it was an internal seam
RED, not a second public behavior bug. The module-level private iterator now
accepts explicit selection, current schema object type, schema, fragment map
and bound directive values, and the three existing promotion call levels reuse
it. Direct tests cover applicable typed/untyped, interface, alias, missing,
repeated, unknown-type and directive selections, plus conservative None and
cyclic unvalidated-AST boundaries. No cyclic AST is described as a valid
GraphQL request. The original public fragment regressions remain unchanged.

Behavior/tests commit dab451964f7c62dcac3f3a0fd4a122156b66e35e first
passed 140 focused cases. Its native full suite passed, but diff-cover exposed
two newly added type-only import lines as uncovered (30/32), so that candidate
is not claimed as patch PASS. The narrow type-import correction commit
4776fa50f2bbda83f8436cdd00f24087616ffce2 (tree
603c0f41c0d204aad2d5b7847c9534c068e0e39e; package tree
9d275e6fbf65529aab49d2f448ee5528d46df452) is the exact tested source.
Its clean real native-3.3 clone passed 140 focused and 4,860 full tests,
seven skips, three warnings and 23 subtests, with 96.74% combined coverage.
Both genuine nonempty diff-cover comparisons, against e220800 and integration
3415e9, passed **30/30 changed runtime lines** without coverage exclusions.
All 344 benchmark contracts, 59 standalone Playground tests, Ruff/check-only
format, configured/expanded/CLI mypy, Bandit, both zero-issue docstring gates,
clean Zensical build and diff check passed. Protected 129-item byte/stat
identities matched; old canonical data and retained databases were untouched.
Raw chronology and exact commands are under final-gates-fragment-walker/.

FG2-R is locally complete, subject to parent independent verification. The
distinct FG2 pure-branch floor remains open: **3,617/3,864 = 93.6077%**,
below 95.01%, although five covered outcomes were gained with no denominator
change. FG3, FG5 final-source comparison and FG4 remain pending. The package
hash changed intentionally under the authorized refactor; older official
benchmark series retain their prior measured-source labels. This factual
checkpoint is not a second full-suite run or hosted gate.

### FG2 non-utils test continuation

Independent verification accepted the private walker correction at 4776fa5:
140 focused controls plus 22 fresh controls passed, and both genuine nonempty
runtime patch comparisons covered 30/30 lines. This closes FG2-R's independent
functional and patch gate, not the distinct FG2 global pure-branch gate.
The next delegated direct work unit tests existing native input/compiler and
date-format boundaries with concrete GraphQL shapes and formatted values.
Its coverage objective starts at 3,617/3,864; tests of already-correct
behavior can pass immediately without inventing a new behavioral RED. Package
runtime, exclusions and measured benchmark sources remain unchanged. FG3,
FG5 and FG4 remain pending, and the Engram mirror is still unavailable.

The test work-unit commit d2b446cf0ec2129f5c136ce1a51c489bb86cbcbc
adds 22 fixed-date and native input/compiler controls. They assert exact
leap-day token output and malformed-token rejection, enum and relation input
shapes for create/update/MTI/non-editable fields, and preservation of an
ordinary field across a forked schema pair. Existing behavior passed the
focused tests immediately. Its clean real native-3.3 clone passed 4,882 full
tests, seven skips, three warnings and 23 subtests at 96.84% combined
coverage; all 344 benchmark contracts and 59 standalone Playground tests
passed. Nine formerly missing branch outcomes are now covered, with no newly
missing outcomes or denominator change. The pure branch gate still correctly
fails at **3,626/3,864 = 93.8406%**; 46 more covered outcomes are needed for
95.01% at this denominator. Both genuine nonempty runtime patch comparisons
remain 30/30 changed lines, since package tree
9d275e6fbf65529aab49d2f448ee5528d46df452 is unchanged. Ruff, format,
configured/expanded/CLI typing, Bandit, both zero-issue docstring audits,
Zensical and diff checks passed. This is a bounded FG2 partial, not FG2
acceptance or authority to wire FG3. Raw exact-clone proof is under
final-gates-fg2-native-boundaries/; task-only evidence after the tested commit
does not itself claim another full run.

### FG2 transport and subscription-permission continuation

The next delegated direct test unit exercises supported malformed SSE
variables, WebSocket initialization and orphan-source lifecycle, and
subscription permission denial. The frozen package tree
9d275e6fbf65529aab49d2f448ee5528d46df452 and 3,626/3,864 pure-branch
starting point remain unchanged before test edits. Existing correct behavior
may pass immediately; the already-observed pure-branch failure is the
coverage-objective RED. No production code, policy, benchmark or retained
database mutation is authorized in this unit.

The test work-unit commit 3b0fd1658e7d991c6d50a2b94c4d3605ba59e17a
adds malformed SSE request, WebSocket timer/source teardown, and subscription
permission-denial controls. Its clean native-3.3 clone passed 56 transport and
permission focal tests, 4,891 full tests with seven skips, three warnings and
23 subtests, 344 benchmark contracts without timing, and 59 standalone
Playground tests. Combined coverage is 96.92%. Seven previously missing pure
branch outcomes are covered, none newly missing, and the denominator remains
3,864: **3,633/3,864 = 94.0217%**, still below 95.01% by 39 outcomes.
The exact pure gate therefore exits 1; FG2 remains unchecked. Both genuine
nonempty runtime diff-coverage comparisons remain 30/30 lines. Ruff, check-only
format, configured/expanded/CLI typing, Bandit, both zero-issue docstring
audits, Zensical and diff checks passed. The 129 current protected identities
matched before and after. Raw logs and exact command ledger are under
final-gates-fg2-transports/. A first configured docstring audit found seven
test-docstring findings; corrected source passed before the tested commit.
No package, coverage policy, benchmark or retained database was changed.
This bounded FG2 partial does not start FG3 or FG5; the Engram mirror is pending.

### FG2 helper and schema-identity continuation

The next delegated direct test-only unit targets supported manager/queryset
normalization and schema-registry identity/no-op boundaries. Its baseline is
3,633/3,864 pure branches; existing behavior may pass new tests immediately,
while the exact pure-branch gate is the coverage-objective RED. Test real
model, schema and pair effects rather than helper call counts or fabricated
registry corruption. Package source, coverage policy, old results and retained
databases remain unchanged. FG2 stays open until a fresh full-suite XML meets
95.01%; FG3, FG5 and FG4 are not started by this unit.

Test work unit 89179c18dd8f2ecb22521467e741ddb59d73774f covers real
manager-to-queryset normalization, scalar-only isolated schema construction,
global app-ready exclusion of a valid custom-registry output, stable same-pair
recompilation, and two fields sharing one model type without cross-pair aliasing.
It does not force legacy reverse-relation metadata absent from the observed
Django 6.0.8 relation objects, or manufacture abstract model-free types. The
exact clean native-3.3 clone passed 29 focal, 4,896 full, 344 benchmark-contract
and 59 standalone Playground tests. Seven skips, three warnings and 23 subtests
remained; combined
coverage was 97.01%. Six previously missing branch outcomes are covered with
no new missing outcome or denominator change: **3,639/3,864 = 94.1770%**.
The pure gate exits 1; 33 additional outcomes are needed at this denominator,
so FG2 remains unchecked. Both genuine nonempty runtime patch gates pass 30/30
lines. Ruff/check-only format, configured/expanded/CLI mypy, Bandit, both
zero-issue docstring audits, Zensical, diff check and 129 protected identity
checks passed. Prior failed focal, docstring and formatter attempts remain in
the new final-gates-fg2-registry-helpers/ proof directory. Package source,
coverage policy and retained benchmark assets remain unchanged. FG3, FG5 and
FG4 are still pending; the Engram mirror remains unavailable.

### FG2 declaration and configuration continuation

The next delegated direct, test-only unit exercises documented list-container
configuration, model declaration errors and compatibility, native class-driver
options, and nested-input permissions. Its baseline is 3,639/3,864 pure branch
outcomes. Existing correct behavior may pass new tests immediately; the pure
branch acceptance gate is the observed RED. No package source, coverage policy,
benchmark result, or retained database change is authorized. FG2 remains open
until fresh full-suite XML proves at least 95.01%; FG3, FG5 and FG4 remain
pending. Rollback removes only this unit's tests and progress checkpoint.

Test work unit 96106e52554eb340a145d36302b975bd373b2cba exercises a real
unpaginated list container, configured auto-list fallback, model declaration
errors and argument compatibility, nonreserved filtering, subscription stream
validation and class caching, native driver options/Meta/MRO behavior, and
concrete nested-input permission labels. Its 15 focused controls pass. An
initial fixture NameError and two incorrect test-surface assumptions were
fixed before the tested commit; they were not runtime defects. A separate
focused-coverage calibration passed the tests but predictably failed the
configured full-suite coverage gate; it was not acceptance evidence.

The exact clean native-3.3 clone of that work-unit commit passed 4,911 full
tests, seven skips, three warnings and 23 subtests at 97.18% combined
coverage; 344 benchmark contracts without timing and 59 standalone Playground
tests passed. Seventeen formerly missing pure branch outcomes are covered,
none newly missing, and the denominator is unchanged: **3,656/3,864 =
94.6170%**. The exact pure checker still exits 1, leaving 16 outcomes to
reach 95.01% at this denominator. Both nonempty runtime patch comparisons
remain 30/30 changed lines. Ruff/check-only format, configured/expanded/CLI
typing, Bandit, both zero-issue docstring audits, Zensical, diff check and all
129 protected identity checks passed. Package source remains
9d275e6fbf65529aab49d2f448ee5528d46df452. Raw evidence is under
final-gates-fg2-declarations/. This task-only checkpoint follows the tested
commit and does not claim a second full run. FG2 remains unchecked; FG3, FG5
and FG4 have not started. The Engram mirror remains pending.

### FG2 optional-extra placement and final boundary continuation

A clean-base simulation that blocked only optional Channels imports exposed a
test-placement defect in the declaration unit: its positive cached-stream
control fails in the core test module with the documented subscriptions-extra
ImportError, although 14 other core controls pass. The production lazy-import
behavior is correct. Move that positive control to the existing subscription
suite, retain the pre-import missing-stream guard in core, and prove the core
module succeeds without Channels before adding the next supported field and
extension-boundary tests. This is a cause-correct test contract RED, distinct
from the still-failing pure-branch coverage objective at 3,656/3,864. No
runtime/package source, coverage policy, or retained data changes are allowed.

Test work unit c0118ce4471ed467b40df2ff8213cba497bd332f moves the
positive cached-stream control to the optional subscription suite. A clean
clone with Channels imports deliberately blocked first failed that mixed core
module (14 passed, one failed), then the corrected core module passed all 14
controls; the moved subscription control passed with the optional extra. New
field and input contracts cover a plain list item, an explicit paginated
description, inherited native descriptors, canonical registered nested input
identity, and repeated model-free input identity. An initial input fixture
mistakenly expected a nonexistent Category.name field; correcting it to the
real title field was a test-fixture repair, not a runtime defect.

The exact clean native-3.3 clone passed 4,916 full tests, 344 benchmark
contracts without timing, and 59 standalone Playground tests. Seven skips,
three warnings, and 23 subtests remained. Combined coverage is 97.25%; five
formerly missing pure outcomes are covered with none lost and an unchanged
denominator: **3,661/3,864 = 94.7464%**. The pure gate still exits 1, with 11
more outcomes needed at this denominator. Both nonempty package patch gates
pass 30/30 changed lines; Ruff/check-only format, configured/expanded/CLI
typing, Bandit, both zero-issue docstring audits, Zensical, and all 129
protected identity checks pass. Package source remains
9d275e6fbf65529aab49d2f448ee5528d46df452. Raw commands and arc diff are
under final-gates-fg2-final-boundaries/. This task-only checkpoint follows the
tested commit; it does not claim a second full run. FG2 remains unchecked;
FG3, FG5, and FG4 have not started. The Engram mirror remains pending.

### FG2 interface permission and schema boundary continuation

This delegated direct test-only unit starts from 3,661/3,864 pure outcomes.
Its primary contract is the conservative interface-permission fallback when
no built schema can narrow the registered implementors, including an
unmounted model. Additional supported schema boundaries may be covered with
real parsed/executable GraphQL types and explicit output assertions. No
production code, coverage policy, benchmark artifact or retained database
change is authorized. Existing correct behavior may pass new tests at once;
the observed pure-branch gate remains the coverage-objective RED. FG2 stays
unchecked unless a fresh full XML reaches 95.01%; FG3, FG5 and FG4 remain
pending. Rollback removes only this unit's tests and factual checkpoint.

Test work unit dea9e9c33a5994aecde26fecb67b7e37b2e40fae covers the
conservative interface-permission fallback with and without a built schema,
including an unmounted registered implementor; positional native-root schema
execution; an explicitly named argument; positional-only permission hook
keywords; configured lookup deduplication and a non-text field; an omitted
filter beside an active sibling; and cross-registry GFK union refusal. The
first argument test used the wrong adapter and failed before it was corrected
to the intended native argument API; this was test-fixture repair, not a
production defect. Correct existing behavior passed new tests immediately;
the prior exact pure-branch gate failure was the coverage-objective RED.

The exact clean native-3.3 clone passed 4,925 full tests, seven skips, three
warnings and 23 subtests, with **97.37% combined coverage**. Eleven formerly
missing pure outcomes are covered, none lost, at unchanged denominator:
**3,672/3,864 = 95.0311%**, so the exact pure gate now exits 0. Both genuine
nonempty runtime patch comparisons remain 30/30 changed lines. All 344
benchmark contracts passed without timing and all 59 standalone Playground
tests passed. Ruff/check-only format, configured/expanded/CLI typing, Bandit,
both zero-issue docstring audits, Zensical, diff check and all 129 protected
identity checks passed. The package tree remains
9d275e6fbf65529aab49d2f448ee5528d46df452. Raw exact-command streams,
fresh XML and arc diff are under final-gates-fg2-permission-boundaries/.
FG2 is locally checked; independent and hosted acceptance remain separate.
FG3, FG5 and FG4 have not started. This task-only checkpoint follows the
tested commit and does not claim a second full run. The Engram mirror remains
pending.

### FG3 CI and generated-site gate

FG3 is the active delegated-direct unit: wire the exact pure-branch checker
after fresh coverage XML without replacing the combined or changed-line gates;
repair the generated 404 skip target in a repository-owned theme override;
and run a local-anchor checker after the documentation build. Add executable
workflow, checker and 404 controls before implementation, retaining RED then
GREEN evidence. Update contributor guidance and the prepared changelogs only
for these gates. The 15-job validation graph, runtime package, coverage policy,
pins and benchmark artifacts remain unchanged. Rollback is this unit's CI,
template, checker, tests and documentation only. FG5 and FG4 remain pending.

FG3 work unit cb9061411f48341d5f2425fa7573f84f5adfd3a4 wires the exact
branch gate after fresh coverage XML and retains the changed-line gate and
existing validation job graph. A repository-owned 404
override supplies the actual theme skip target; the generated-site checker
resolves local HTML destinations and fragments under the configured deployment
path. Six new contract tests failed before the checker, workflow and override
existed; the generated 404 had the skip link but no target. The focused suite
then passed 18 tests, and the clean built site passed 43 HTML pages with no
broken local links and no Zensical issues.

The exact clean native-3.3 clone of cb90614 passed 4,931 full tests with seven
skips, three warnings, 23 subtests and 97.37% combined coverage. The separate
pure gate passed at 3,672/3,864 = 95.0311%; both nonempty runtime patch checks
remained 30/30. All 344 benchmark contracts, 59 standalone Playground tests,
Ruff/check-only formatting, configured/expanded/CLI typing, Bandit, both
zero-issue docstring audits, docs build, generated-site anchor check and diff
check passed. The runtime package tree is unchanged at
9d275e6fbf65529aab49d2f448ee5528d46df452; all 129 protected paths have
matching FG3 before/after byte and filesystem identities. Raw commands and
streams are under final-gates-fg3/. This factual checkpoint does not claim a
second full run or independent/hosted acceptance. FG5 and FG4 remain pending;
the Engram mirror remains pending.

### FG3 independent correction

Independent verification of cb90614 is partial, so FG3 is reopened. A clean
site build copies the raw 404 Jinja override because its custom directory is
inside docs; also, a nested page's deployment-root absolute link is incorrectly
resolved relative to that nested page. The actual rendered 404 skip target and
CI gate order passed. This bounded correction moves only the override outside
the content root and preserves root-relative URL status through prefix removal,
with real failing regressions before either fix. The prior local PASS and raw
proof remain historical, not independent acceptance. FG5 and FG4 remain
pending; the Engram mirror remains pending.

Correction work unit 9991651472189f8efcf3dc66598c7427e8e7c9fd fixes
both independently observed FG3 findings without changing the runtime package.
A new nested deployment-root link test and an external theme-directory contract
failed for their exact causes before the fix; the clean pre-fix build also
emitted the raw 100-byte Jinja template. The override now lives outside docs,
and the checker retains root-relative status after removing the deployment
prefix. Focused tests pass 21 controls, including missing fragment and encoded
escape failures. A fresh clean build emits 42 HTML pages with no raw override,
retains the rendered 404 skip target, and passes all local anchor checks.

The exact clean native-3.3 correction clone passed 4,934 full tests, seven
skips, three warnings and 23 subtests at 97.37% combined coverage. The pure
gate remained 3,672/3,864 = 95.0311%, and both genuine nonempty patch gates
remained 30/30. All 344 benchmark contracts, 59 standalone Playground tests,
Ruff/check-only formatting, configured/expanded/CLI typing, Bandit, both
zero-issue docstring audits and Zensical passed. All 129 protected paths match
the correction's before/after SHA and filesystem identities. Raw proof is under
final-gates-fg3-correction/. FG3 remains unchecked until independent targeted
acceptance; FG5 and FG4 remain pending. This task-only checkpoint does not
claim a second full run. The Engram mirror remains pending.

### FG3 deployment-root empty suffix completion

Independent targeted verification of 9991651 passed the external theme
override and nested guide link, but found one remaining path in that same
root-relative contract: after removing the deployment prefix, an empty suffix
is overwritten with the source page. Bare deployment-root links and homepage
fragments from a nested page must resolve to the site root; fragment-only
links must stay on their source page. Add a focused cause-correct failing CLI
control before the one-condition checker fix. The previous independent PARTIAL
and all proof remain intact. FG3 stays unchecked; FG5/FG4 remain pending.

Work unit 247e149d98409ddf4bf998605844f43fe7444698 adds the exact
deployment-home regression before its one-condition fix. The focused RED was
one genuine nested homepage-anchor failure; GREEN passes 23 focal/release
controls, including bare root, homepage anchor, same-document fragment, missing
home anchor, percent-decoded nested guide, encoded traversal and missing-page
boundaries. The previous targeted independent PARTIAL remains attached to
9991651 and is not rewritten as acceptance.

The exact clean native-3.3 clone at 247e149 passed 4,936 full tests with seven
skips, three warnings, 23 subtests and 97.37% combined coverage. Pure branches
remain 3,672/3,864 = 95.0311%; both nonempty runtime patch checks remain
30/30. The actual prior deployment-home fixture now passes the production CLI.
The clean build emits 42 HTML pages, no raw Jinja override, and passes local
anchor checks. All 344 benchmark contracts, 59 standalone Playground tests,
Ruff/check-only format, configured/expanded/CLI typing, Bandit, both zero-issue
docstring audits, Zensical and all 129 protected identity checks passed. The
runtime package remains 9d275e6fbf65529aab49d2f448ee5528d46df452. The
full final-check ledger has 18 commands, not the earlier writer report's 17.
Raw proof is under final-gates-fg3-root-completion/. FG3 remains unchecked
until targeted independent regression acceptance; FG5/FG4 remain pending.
This task-only checkpoint does not claim a second full run. The Engram mirror
remains pending.

### FG5 final-source measurement checkpoint

Independent targeted verification accepted the final FG3 deployment-root
correction at 247e149 (see final-gates-fg3-root-targeted-acceptance/), so FG3
is checked. FG5 now owns exactly one additive named-profile batch from a clean
real clone of this checkpoint commit: fresh private 1,000/2,000-author seeds,
three rotated repetitions across four existing whole-stack profiles, 24 raw
dispatches, eight validated median artifacts in a new commit-named result
series. Preserve the existing series and all retained databases/results.
The user accepted existing background load; pre/post aggregate observations
do not establish continuous quietness, thermal stability or a paired speedup.
No local verification runs concurrently with timed requests. Actual result
and documentation changes follow measured evidence in separate commits, with
historical source attribution unchanged. FG5 remains unchecked until those
outcomes and checks are observed; FG4 is separate. The Engram mirror remains
pending.

The clean measurement source is bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e
(tree 619d81147c006c1eeb4a10eadc4867140649e4dc), with the same runtime
package tree 9d275e6fbf65529aab49d2f448ee5528d46df452. One official
named-profile run completed 24 dispatches and installed eight JSON artifacts
in the fresh core33-4.0.0-bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e
series. Two fresh private seeds contain 50,000 and 100,000 comments; 24 raw
results and 72 post-batch receipt records are retained externally. The old
129 protected assets matched before and after by bytes and filesystem state.
The aggregate CPU observations do not prove stable background load. The
current public table and documentation still describe the earlier 01f82
series; updating them from these JSON files and independent arithmetic
acceptance remain pending. FG5 therefore remains unchecked.

The artifact work unit 58146dced3e62924a4b2aaae03ccd596bfccc80e
published eight portable JSON files locally without changing runtime code.
The documentation and executable parity contract at
990c0eccabf90f7b678151f65d345ece6e8a33e0 derive the current table
and both create-comment ratios from those files, link the artifact commit
separately from measuring source bf6e1ed, and retain the 01f82 series as
historical. The documentation contract first failed against the stale public
pointer and table, then passed all six tests after the update. This is local
repository publication only, not a hosted release or remote publication.

The exact clean native-3.3 clone of 990c0ec passed 4,936 full tests with seven
skips, three warnings, 23 subtests and 97.37% combined coverage. Pure branches
were 3,672/3,864 = 95.0311%; both nonempty runtime patch comparisons covered
30/30 changed lines. All 344 benchmark contracts, 59 standalone Playground
tests, Ruff/check-only format, configured and expanded mypy, CLI mypy,
Bandit, both zero-issue docstring gates, Zensical's clean build and all 42
site-page local-link checks passed. The original 129 protected identities and
new eight artifact/two-seed SHA-256 values remained unchanged. The measured
SQLite create-comment GraphEx/Ariadne p50 ratios were 0.57x (about 43% lower)
at 50,000 comments and 0.51x (about 49% lower) at 100,000; these are scoped
whole-stack observations with accepted background load, not a guarantee.
Full raw proof is under final-gates-fg5-official-final-source/. Independent
arithmetic and provenance acceptance is pending, so FG5 remains unchecked;
FG4 and hosted/main/tag/publication approval are separate. This task-only
checkpoint follows tested executable/documentation bytes and does not claim
another full run or CI for its own commit. The Engram mirror remains pending.

### FG5 local commit-policy normalization

The branch-pr Conventional Commit pattern rejected the local artifact subject
`data(benchmarks): retain final-source core33 results`; the other 39 subjects
matched. Before changing history, the original final FG5 head
125ac55441c63e22564dae521bf054300ab11c0b was retained at local branch
`codex/recovery-fg5-pre-policy-125ac55`. Three descendant commit objects were
recreated with their original trees and author metadata and adjusted parent
links, without checkout or worktree/index reset. The artifact subject is now
`chore(benchmarks): retain final-source core33 results` at
826d5bae87ed7bbe705cf309d46a16d3ad3cdf33; its tree is exactly the old
artifact tree c3277d40389a41ecfe8b024dc0f60afc247f634d. The unchanged
docs and task trees moved to e31a2f5782b7ec062b0fc2c43538f02d951d7e80
and 5697ac5ad1518d9e05c6a7376d5741b74de9ddc0. The measured source
bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e did not move. All 40 current
branch subjects match the supported pattern; all 139 old/new protected asset
bytes and filesystem identities matched before and after the metadata-only
rewrite. The old commits and earlier proof remain reachable on the recovery
branch and are not relabeled as current publication identities.

The executable current-doc contract then failed on the stale old artifact
SHA before public docs were corrected to the new 826d artifact commit. The
corrected public JSON links target the first commit containing those eight
files; the measured source remains bf6e. No measurement, seed, replay,
package, pin, version, or canonical JSON bytes were changed. Fresh exact-head
functional proof follows in the separate commit-policy report. FG5 remains
pending independent acceptance; FG4 and hosted delivery remain separate.
