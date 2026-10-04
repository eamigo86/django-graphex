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
  dependency refresh, benchmark timing, seed/reset or branch deletion.
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

- [ ] FG1 — Add a fail-closed pure-branch XML checker with executable boundary,
  malformed/missing/zero-count and CLI tests. Integer/decimal exact comparison,
  never rounded XML rates. Demonstrate the accepted 92.70% baseline fails.
  Delegated direct: multi-file script/tests and preparation require a writer.
- [ ] FG2 — Add behavior-focused optimizer/compiler/type tests until fresh
  full-suite pure branch coverage is at least 95.01%, with margin where useful.
  Keep runtime/source and denominator policy unchanged. Delegated direct:
  multiple non-trivial test modules and fresh native full-suite execution.
- [ ] FG3 — Wire the pure-branch checker into the existing coverage job, repair
  the 404 template, add a generated-site check to docs CI, and update contributor
  guidance and both prepared-release changelogs. Preserve the release graph.
  Delegated direct: workflow, template, helpers, tests and docs form one unit.
- [ ] FG4 — Independently verify exact final candidate, coverage arithmetic and
  negative controls, docs/site anchors, examples/Playground, quality and preserved
  state. Parent spot check, child/integration/tracker exact-head hosted gates;
  report remaining main/tag/publication approvals. Delegated verifier plus
  read-only parent remote orchestration; no invented release readiness.

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
