# Restore real Redis integration without changing public transports

Status: IN PROGRESS. Repository locator: odd/tasks/redis-unix-compatibility.md.

## Objective and scope

Correct the private Unix Redis client construction incompatibility, establish the
causes of the three secondary live failures, and repeat complete and real-backend
verification. Preserve the public TCP/TLS-only SSE URL contract.

- Authorized by the user on 2026-10-26: compatible correction, investigation,
  strict TDD, documentation, coverage above 95%, full suite and real Redis.
- No PR, push, tags, publishing, benchmark regeneration, dependency installation,
  downloads, ambient Redis access, or unrelated changes.
- Ask before any incompatible public change; none is currently proposed.
- Preserve all existing audit reports, official benchmark artifacts, root
  coverage artifacts, and pre-existing untracked files.

## Starting evidence

- Branch: codex/audit-400-remediation.
- Starting commit: f3621be3ac760e320ef73e4f9e3b197844dcebdc.
- Prior proof: /private/tmp/graphex-full-live-redis-fdi1tty6/report.md.
- Root: 7,782 passed, 6 existing skips, 18 warnings; Playground: 98 passed.
- Real Redis: 5 passed, 5 failed. All five public TCP SSE tests passed.
- Two private Unix cases directly expose an unsupported socket_keepalive
  constructor keyword. Two child exits and one commit-event wait need direct
  causal evidence, not attribution by similarity.
- Fresh root branch coverage: 5,085/5,322 = 95.5468%; combined: 97.5854%.

## Workflow and delivery

- Route: delegated direct; mapping/preparation and multiple non-trivial files
  require delegation. One writer, followed by independent verification.
- TDD: ENABLED by explicit user request and AGENTS.md strict mode.
- Runner: /private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad/venv-head/bin/python.
- Verify Python 3.12.11, Django 6.0.8, graphql module and distribution 3.3.0,
  and current-checkout library origin inside each actual test process.
- RED before production edits, then minimal GREEN and REFACTOR. Retain both
  expected and unexpected failures. Do not weaken assertions or timeouts.
- Focal runner: supported Python -B -m pytest --no-cov; explicit Redis suite
  additionally loads -p tests.conftest integration/live_redis/test_sse_live_redis.py.
- Root full runner: external isolated harness using the complete unchanged
  coverage configuration except external HTML/XML output destinations. Preserve
  PID-owned raw data; reconcile pure branch arcs and combined coverage with XML.
- All test outputs, databases, caches, Redis state and evidence remain external.
- RDD: globally OFF; no native review transaction. Ordinary checks remain.
  Read-only risk assessment was unavailable because of undeclared untracked
  reports; treated as high/unassessable, so independent verification is required.
  No review lifecycle or consent request was started while RDD is off.
- Delivery strategy: ask-on-risk; no PR is planned or authorized. Forecast:
  250-350 authored changed lines including this tracker. Target one behavior
  commit and one verification/tracking commit. Record actual counts at closure.
- Technical artifacts are English. Public docstrings use complete Google style,
  type hints without repeated types, and no backticks.

## Tasks and acceptance

- [x] RUX-1 — Correct transport options and attribute all five live failures.
  Route: delegated writer (multi-file implementation and test execution).
  Add constructor-options regression cases for Unix, TCP and TLS; observe Unix
  RED before the fix. Preserve timeouts and health checks for all transports and
  TCP keepalive for redis/rediss. Do not broaden public setting validation.
  Capture bounded child stderr and cancellation task exceptions on failure;
  demonstrate the cause of each secondary case before production correction.
  Isolate the session-scoped Redis URL's cached client per test: the first
  complete post-fix live run exposed reply-wrapper bypass dependent on order.
  Preserve lost/delayed-reply assertions and clean up owned clients.
  Add tests for diagnostic behavior where applicable. Run focal, related,
  complete root, and all ten real Redis cases. Update subscription documentation
  and Unreleased changelog. Save one coherent Conventional Commit with tests and
  docs. Rollback boundary: the transport-option fix, its diagnostic/regression
  tests, and associated explanatory docs, without unrelated remediation.
  Evidence: /private/tmp/dgx-rux-1-1s8rLmXf/RUX-1-report.md. All ten real cases
  pass, with direct pre-fix TypeError evidence for each secondary failure.
  Final root: 7,784 passed, 6 existing skips, 18 warnings, 4,064 subtests.
  Branches: 5,087/5,324 = 95.5485%; combined: 18,516/18,974 = 97.5862%.
  Ruff check/format, mypy, standard/strict docstrings, strict docs build and
  diff checks passed. Changelog mirror RED (one failure) was corrected in both
  CHANGELOG.md and docs/changelog.md before the final full GREEN run.
  Owned Redis PID 1691 exited normally; socket gone, no persistence. All 267
  protected files unchanged. Implementation commit: recorded at RUX-2 closure.
- [ ] RUX-2 — Independently verify and close the work unit.
  Route: delegated verifier, then parent mechanical tracking update.
  Read the exact diff, confirm every previously failing scenario passes without
  mocks or transport substitution, repeat full root and real Redis serially,
  and verify Playground. Verify pure branch and combined coverage >95.01%,
  formatting, type/lint/docstring and documentation checks applicable to edits.
  Verify unchanged public URL validation, official benchmarks, audit reports,
  unrelated library bytes, root coverage artifacts, and owned Redis cleanup.
  Record failed/skipped/unavailable checks honestly. Save tracking closure in a
  local Conventional Commit. Rollback boundary: tracking metadata only.
  Evidence/commit: pending.

## Progress and next step

Read-only map completed: socket_keepalive is unconditional in _shared_client;
private Unix tests intentionally differ from public TCP/TLS configuration. The
smallest compatible correction can omit only this TCP option for Unix clients.
All three secondary failures now have direct pre-fix evidence of the same
unsupported Unix keepalive keyword. Constructor RED: 1 failed (Unix), 2 passed
(TCP/TLS); GREEN: 34 controls and 693 related subscription tests passed. Each
secondary real scenario passes individually after the option fix. The first
complete live run then exposed an additional fixture-order problem: 8 passed,
2 failed because the reused URL's cached client bypasses monkeypatched reply
wrappers. This private test-isolation correction is part of RUX-1; assertions,
timeouts and public behavior must remain unchanged. Evidence:
/private/tmp/dgx-rux-1-1s8rLmXf. Per-case cache cleanup now closes only clients
for the owned endpoints; the unchanged ten-case suite passes as a whole. Final
normalized full root and applicable quality/docs gates pass. No incompatible
change was introduced. Authored implementation diff: 131 lines, plus this
tracker (initially 98 lines); delivery remains below 400 lines with no PR.
Next: save the behavior work-unit commit, then run independent RUX-2 against
those exact committed source bytes. RDD remains disabled/unmanaged.
