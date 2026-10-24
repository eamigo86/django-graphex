# Fix the 4.0.0 re-audit findings

## Objective

Fix every finding of the re-audit (`reauditoria-django-graphex-4.0.0.md`, repo root, untracked): new regressions R1-R13, residuals P1-P23, the docs items D1-D7 and the Playground items G1-G7. Then run a fresh independent audit, update docs, the example project (Playground) and rerun the benchmark.

## Problem and why

The 4.0.0 remediation fixed most original findings but left C2 open for distinct relation paths, introduced 13 regressions (R1 breaks valid imports and the repo benchmark), left authorization gaps (GFK unions, forward/reverse OneToOne), broke two CI gates and left docs/Playground stale.

## Scope and constraints

- Authorized by the user on 2026-10-24: fix R1 and C2 first, then everything else, with TDD; new audit; docs, Playground, benchmark.
- Standing user rules: no PR, no tag, no publication, no push. Ask before any incompatible public API or wire change (each one individually). Keep coverage above 95.01 %.
- Branch: `codex/audit-400-remediation` (feature branch). Work-unit Conventional Commits, no AI attribution. Stage files explicitly; never stage `.codegraph/` or the two root audit reports.
- RDD: globally off (checked 2026-10-24). No native review.
- TDD: strict (global CLAUDE.md). RED observed before GREEN, then REFACTOR.
- Runner: `S=/private/tmp/claude-501/-Users-eamigo-Documents-Work-django-graphex/beff4e6e-3a6e-47db-be34-debf3cc0d12e/scratchpad; $S/venv-head/bin/pytest` from the repo root (Python 3.12.11, graphql-core 3.3.0, Django 6.0.8; editable install of this checkout). Focal runs add `--no-cov -p no:randomly`; the full run uses the default addopts (coverage gate 95.01 %). The root `.venv` is stale (graphql-core 3.2.13) and is not used.
- Quality gates per task: `ruff format --check .`, `ruff check .`, `mypy django_graphex`, `python scripts/check_docstrings.py django_graphex examples/playground tests`, `bandit -r django_graphex/ -c pyproject.toml` (from task T13 on, all must be clean).
- Docstrings: Google style, no backticks, no repeated types, type hints everywhere (`docs/contributing.md`).
- Each behavior change ships with tests, CHANGELOG (Unreleased) and docs in the same commit.

## Tasks

Route: D = delegated writer (sonnet), I = inline. Evidence lists the commit and checks.

| ID | Finding(s) | Outcome | Route | State | Evidence |
|---|---|---|---|---|---|
| T01 | R1 | Registry accepts a user type replacing a generated placeholder and same-declaration re-import; distinct types (incl. subclass with own Meta.model) still rejected with an actionable message; mutation payload follows the user type; real `_import_schema` test | D | [x] | `6a161a7`; RED 4 tests; full 6708 passed / 6 skipped, cov 97.80 %; ruff, mypy, docstrings (touched) clean |
| T02 | P1 (C2), R13 | New `OPTIMIZER_WORK_BUDGET` (default 2000) charged per selection-context expansion in the five path-keyed walkers; past it relations load lazily (same data, same scoping) | D | [x] | `4f67ebf`; RED call count 92839 > 3000; n=8 4.05 s -> 0.15 s, n=16 0.09 s; R13 n=7 23207/15016 -> 2006/2007 calls; full 6712 passed, cov 97.82 %; parent sweep budgets 1-39: identical data, no hidden rows |
| T03 | P9 | Depth and cost walkers iterative; parse/validate stack exhaustion -> 400 `QUERY_TOO_DEEP`; private structural depth ceiling 100 (sync execution with cyclic data fails at ~130) applied even with `MAX_QUERY_DEPTH` unset | D | [x] | `c863deb`, `e24dbbc`, `d8188f3`; RED 9+3+1 tests; full 6731 passed, cov 97.83 %; parent re-ran chain/deep-frag/inline-band repros: no 500, no internal error, no ERROR log |
| T04 | P3, R9 | Forward OneToOne destinations scoped like FK (hidden = missing error); one batched membership query per relation | D | [x] | `56c5be3`; RED 3 tests (hidden accepted; 13/68 queries for 5/60 tags; SQLite int overflow); full 6737 passed, cov 97.81 %; parent re-ran t_sd3 write attacks: all rejected |
| T05 | P4 | Reverse OneToOne orphan adoption needs a child update host (same rule as reverse FK) | D | [x] | `e2d7de1`; RED adoption without host; full 6741 passed, cov 97.81 %; parent re-ran t_sd4: refused |
| T06 | P7 | Id-bearing nested child payload matching no visible child (hidden or missing) -> same not-found error, nothing written; id-less payload still creates | D | [x] | `6ab28e5`; RED 5/7; 4 pinned tests rewritten to the approved contract; parent re-ran t_oracle: identical errors |
| T07 | P2 | Typed GFK union targets resolve through the member type `get_queryset` (hidden -> null), batched via scoped GenericPrefetch | D | [x] | `6673531`; RED 4 leak tests; parent re-ran t_gfk_union: target null |
| T08 | P5 | Flat GFK target redacted by the registered type's `get_queryset` in every schema (pruned or not); unregistered targets unchanged | D | [x] | `3e6535b`; RED 4 tests; full 6751 passed, cov 97.78 %; parent re-ran t_sd5 matrix |
| T09 | P6 | Generated update/delete (DjangoModelMutation, DjangoModelType) and nested child writes scoped by the registered output type's `get_queryset`; hidden = missing byte-for-byte | D | [x] | `0583f62`, `47cfed9`; RED hidden rows rewritten; parent full run 6770 passed / 6 skipped, cov 97.78 %; t_sd3 update/delete refused |
| T10 | R3 | Custom scalar coercion errors stay client errors (no INTERNAL, no ERROR log) | D | [ ] | |
| T11 | R4, P18 | Batch with `ATOMIC_REQUESTS`: item errors do not roll back other items; consistent batch abort | D | [ ] | |
| T12 | R5, R10 | Numeric directives correct on Decimal/BigInt; Decimal output without scientific notation | D | [ ] | |
| T13 | R2 | `check_docstrings` and bandit gates clean | D | [ ] | |
| T14 | R7 | Sync fan-out isolates each group; useful failure log | D | [ ] | |
| T15 | R6 | SSE lease tolerates transient renew errors within the TTL | D | [ ] | |
| T16 | R8, P17 | Nested to-many AND without per-level EXISTS explosion; NOT complement consistent | D | [ ] | |
| T17 | R11 | Interfaces do not change unrelated `name=` handling | D | [ ] | |
| T18 | R12 | `Literal` values that map to reserved `__` names rejected or renamed at build | D | [ ] | |
| T19 | P8 | Aggregate output cap / directive cost | D | [ ] | |
| T20 | P10 | Mutation `only_fields`/`exclude_fields` validated like object types | D | [ ] | |
| T21 | P11 | `pageSize` counted by cost analysis | D | [ ] | |
| T22 | P12 | Tampered in-memory cursors return "Invalid cursor" | D | [ ] | |
| T23 | P13 | Multipart size limit enforced before CSRF reads `request.POST` | D | [ ] | |
| T24 | P14 | Remaining runtime `assert`s replaced by explicit errors | D | [ ] | |
| T25 | P15 | `format_graphql_error` regex linear | D | [ ] | |
| T26 | P16 | Subscription snapshot int vs Float/Decimal filter values match | D | [ ] | |
| T27 | P19 | `cached_property` and `__getattr__` AttributeError not turned into null | D | [ ] | |
| T28 | P20 | Not changed (user chose 4.1.0): document range fields and subscription DurationField mapping as a known limitation | D | [ ] | |
| T29 | P21 | Mutable literal defaults not shared between requests | D | [ ] | |
| T30 | P22 | Base64 upload size accounts for padding | D | [ ] | |
| T31 | P23 | Decimal filter invalid value returns a clean field error | D | [ ] | |
| T32 | Residual partials (A1, A2, A10, M-D6, M-D10, M-F3, SD6, Q8, others) | Fix compatible residuals; list incompatible ones for approval | D | [ ] | |
| T33 | D2, D3, D5, D6 | Upgrade guide split by version, audit disposition fixes, docs cleanup | D | [ ] | |
| T34 | G1-G7 | Playground README/docs, `subscription_scope`, password validation, commands | D | [ ] | |
| T35 | D1 | Set version 4.1.0 (pyproject, docs, README); changelog section and compatibility note | D | [ ] | |
| T36 | Audit | Fresh independent audit of HEAD; fix confirmed new findings | D | [ ] | |
| T37 | Benchmark, D4, D7 | Rerun core33 benchmark; update why.md, README, benchmarks README | D | [ ] | |

## Acceptance criteria

- Every task has a RED test observed before the fix and a GREEN run after it, unless it is docs-only.
- Full suite green with coverage >= 95.01 %; all quality gates above clean.
- The repo benchmark harness runs on HEAD without patches.
- Fresh audit finds no unfixed Critical/High issue; any remaining item is listed with a reason.

## Progress

- 2026-10-24: document created; 37 tasks.
- T01 done (`6a161a7`). Subclass case kept rejected on purpose: it is the A4 hazard itself (a broader variant silently becoming canonical); the re-audit's claim that it is valid was overstated.

- T02 done (`4f67ebf`). A lookup set that is exponential in the document cannot be planned in linear time, so a budget was the only correct fix. Real data can still produce exponentially large responses; only `MAX_QUERY_DEPTH`/`MAX_QUERY_COST` stop that (defaults unchanged, not approved).
- Pending user decision (asked 2026-10-24): version 5.0.0 vs 4.1.0; P20 wire change depends on it.

- T03 done. Documents deeper than 100 object levels are now refused (they already crashed once rows existed); list in the upgrade guide (T33).

- T04, T05 done. T06 blocked on an incompatible-change decision (queued after the version question).

## User decisions

1. 2026-10-24: version **4.1.0**, with the wire changes declared as bug fixes under an explicit compatibility policy in the changelog/upgrade guide. P20 (range fields, subscription DurationField) stays out: documented limitation, no wire change.
2. 2026-10-24: T06 option **B** (fail-closed): a nested child id that does not resolve to a visible child returns the same error as a hidden one.
3. 2026-10-24: T09 close P6: generated update/delete honor the registered output type's `get_queryset`; hidden row = same error as missing.

- T07, T08 done.

- T06, T09 done.

## Next step

T10 + T11 (views.py), then T12.
