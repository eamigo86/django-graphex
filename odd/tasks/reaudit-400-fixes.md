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
| T10 | R3 | Parse/validation/variable-coercion errors classified by phase as client errors; raw exception text scrubbed unless DEBUG; no log; execution errors still masked + ERROR | D | [x] | `e8d9bb3`; RED 12/16; parent re-ran test_p8: validation messages, 0 ERROR records |
| T11 | R4, P18 | Each batch item in its own savepoint per ATOMIC_REQUESTS alias; per-item MUTATION_ERRORS_FLAG; every item answered in order (no early stop); status = highest entry status | D | [x] | `76f01bf`; RED 22/32; full 6818 passed, cov 97.76 %; parent re-ran t_a1 poison: persisted 1. Note: replaces the unreleased M-H1 stop-on-400 rule (4.0.0 release failed the whole batch) |
| T12 | R5, R10 | Numeric directives compute on exact Decimal/int (`@round` half-even); `@number`/`@currency` return the raw value on Decimal/BigInt like on Int/Float; Decimal serialized with `format(v, 'f')` | D | [x] | `6273127`, `a7ded4e`; RED 11/18 + 4/10; full 6846 passed, cov 97.77 %; parent re-ran test_dir/test_dec_sci |
| T13 | R2 | Docstring gate TOTAL 0 (446 test docstrings rewritten); bandit exit 0 (justified `# nosec B110` per repo convention) | D | [x] | `3a39b00`, `4106c39`, `d2b3939`; parent re-ran both gates: TOTAL 0, bandit exit 0 |
| T14 | R7 | Automatic sync fan-out isolates each group like the async path; drop log names the qualified exception cause chain (no payload/message); manual broadcast still raises | D | [x] | `83ebcd2`; RED 2 tests; full 6849 passed |
| T15 | R6 | SSE lease renew errors tolerated while `renewed_at + TTL - 5 s` holds (retry every 5 s), stamped at acquire; one shared Redis client per URL | D | [x] | `3747d9b`, `962fc9d`; RED behavior + sharing + first-renewal; full 6853 passed, cov 97.75 %, gates clean |
| T16 | R8, P17 | `_flat_and` splices nested `and` (flat sibling EXISTS, same results); approved rule: `not` inside a to-many relation object = NOT EXISTS of a matching related row (scoped rows respected) | D | [x] | `7afa80c`, `be4f85b`, `038c191`; RED 10/35 + matrix f/i/k/o; full 6899 passed, cov 97.65 %; parent re-ran t_fdeep (data) and t_ident (f x,xy; i; k x,xz; o all 8) |
| T17 | R11 | Only fields declared by an interface use the explicit `name=`; other fields keep their no-interface naming | D | [x] | `1625f3b`; RED non-interface name changed |
| T18 | R12 | `Literal["__x"]` rejected at build (`ImproperlyConfigured`); Django choice values with `__` prefix fall back to the label/`A_` cascade | D | [x] | `2508127`; RED 2 tests; full 6902 passed, cov 97.65 %, gates clean |
| T19 | P8 | New `MAX_DIRECTIVE_OUTPUT_TOTAL` (default 10,000,000 chars per execution) charged by the directive middleware for grown text, state kept on the request context (never in variables); opt-in `COST_DIRECTIVE` (default 0) | D | [x] | `352caac`, `bbafd7d`; RED settings/cost + variable-injection bypass; full 6929 passed, cov 97.66 % |
| T20 | P10 | A3 selector validation on every write host (DjangoModelMutation, DjangoModelType, DjangoListObjectType, DjangoInputObjectType) | D | [x] | `6a4873f`; RED 13/25; parent re-ran test_a3b: typo/bare rejected |
| T21 | P11 | Pagination args matched in snake_case (pageSize = page_size); custom names via `COST_PAGINATION_ARGS` documented | D | [x] | `ea2e4ca`; RED 101 > 5000 |
| T22 | P12 | Strict cursor coercion once per request; in-memory and DB paths both answer "Invalid cursor" (non-finite values refused on both) | D | [x] | `89715ae`; RED 16/27; parent re-ran t_pg4: all Invalid cursor |
| T23 | P13 | Body cap runs in `dispatch` before `@ensure_csrf_cookie` (moved to an inner method); auth-before-cap precedence kept | D | [x] | `2b5c99b`; RED parse calls 1 != 0 with cookie |
| T24 | P14 | All 18 runtime asserts replaced (ImproperlyConfigured / explicit errors); B101 skip removed from bandit; `-O` subprocess test | D | [x] | `39e343d`; RED 10/10; parent ran lc2 with -O: rejected; 0 asserts left |
| T25 | P15 | `_SUGGESTION_RE` replaced by linear `_strip_suggestion`; old regex kept as test oracle (4000 random + 22 samples equal) | D | [x] | `97461e2`; RED 2.55 s |
| T26 | P16 | Non-bool int snapshot matches equal finite float/Decimal exact filters (lookups with `__` already DB-checked) | D | [x] | `ca0d0ec`; RED split_filters None |
| T27 | P19 | AttributeError raised inside any class descriptor (cached_property x2, custom `__get__`) surfaces; `__getattr__` classes documented | D | [x] | `4c6b537`; RED 3/6 |
| T28 | P20 | SDL unchanged (user chose 4.1.0); compatible fixes for fields that always errored: DecimalRangeField bounds -> float, subscription DurationField -> total seconds; BigIntegerRangeField 32-bit limit documented; current mapping pinned by test | D | [x] | `b69b4a1`, `a2060eb`; RED 3 tests; full 7104 passed, cov 97.61 % |
| T29 | P21 | Mutable input-field and argument defaults deep-copied per execution (immutables untouched) | D | [x] | `9fb321d`; RED 3 behavior tests; parent re-ran test_a7b: pristine per request; full 7093 passed, cov 97.60 % |
| T30 | P22 | Base64 decoded-size estimate subtracts `=` padding; same byte limit as multipart | D | [x] | `3ebc835`; RED 12 > 10 at the limit; full 6938 passed, cov 97.67 %, gates clean |
| T31 | P23 | Decimal scalar rejects NaN/sNaN/Infinity at coercion (Float/Int/BigInt/Date already did); mutation inputs now get a coercion error like BigInt (4.0.0 Float did the same) | D | [x] | `33862e8`; RED 16/68; full 7033 passed, cov 97.61 % |
| T32a | A10 residual (approved) | `PydanticBackend.save_object` runs `Field.clean` on each written editable field (validators, blank, null, max_length; relations/files run validators only); no Model.clean / validate_unique / validate_constraints | D | [x] | `219fd8f`; RED 12/15; full 7119 passed, cov 97.61 %; test fixtures' `TextField(default="")` got `blank=True` |
| T32b | A1 other aliases, A2 cache bytes, M-D6 raw JSON non-finite output | Rollback on every ATOMIC_REQUESTS alias in an atomic block (+ per-alias ATOMIC_MUTATIONS); `DOCUMENT_CACHE_MAX_QUERY_LENGTH` (65536) per-entry bound; JSON scalar output rejects NaN/Infinity at any depth | D | [x] | `323482e`, `a8e1e99`, `32aac70`; RED 3 + settings + 14; full 7163 passed, cov 97.61 % |
| T32c | M-F3, M-D10, L-M1, SD6, Q8, Q10, M-D2, L-E4, M-U6, M-D1, L-E3 | Document contracts/dispositions (M-F3: every empty boolean construct is a no-op, verified 2026-10-24) | D | [ ] | |
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
4. 2026-10-24: T16 P17 full rule: any `not` inside a to-many relation object = NOT EXISTS of a related row matching its operand (Django `~Q` semantics); changes cases f, k, i, o.
5. 2026-10-24: T32 A10 residual: generated create/update run each written field's validators (field.validators + blank/choices/max_length), like full_clean without Model.clean() or extra validate_unique; errors as ok:false per field.

- T07, T08 done.

- T06, T09 done.

- T10, T11 done. Residual for T32: rollback of non-default aliases on item errors.

- T12 done. Note for audit: plain-notation Decimal output of a server-side value with a huge exponent is unbounded in length.

- T13 done. From here on every task must keep all gates clean.

- T14, T15 done. Left: lease calls still use the loop default executor (larger change, not needed for correctness).

- T16 done. Case k under the approved rule is `x, xz` (the question text said `x, xy`; the rule, not the example, was approved).

- T17, T18 done. Audit note: explicit field `name=` is ignored on types without interfaces (pre-existing; SDL unchanged).

- T19, T21 done. Parent review caught a budget bypass through a client-declarable variable name in the first T19 commit; fixed in `bbafd7d`.

- T23, T25, T30 done. Follow-up for T33 docs: `BaseGraphQLView` (not csrf_exempt) behind Django's `CsrfViewMiddleware` still has its multipart body parsed by the middleware before the view's cap; document a proxy/body-size middleware placed before CSRF.

- T22, T31 done.

- T20, T24, T27, T29 done.

- T26, T28 done.

- T32a done. Note for T34/T37: Playground and benchmark models must not send "" to `blank=False` columns.

- T32b done. `docs/audit-4.0.0.md` rows for A1, A2, M-D6 still say partial: update in T33.

## Next step

Docs: T35 + D2 (version 4.1.0, upgrade guide split), then T32c + T33.
