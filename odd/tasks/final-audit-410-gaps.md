# Fix the gaps found by the analysis of the 4.1.0 final audit

## Objective

Fix the six gaps REV-01..REV-06 that `analisis-auditoria-final-django-graphex-4.1.0.md` (repo root, untracked, Spanish) found in HEAD `80c343d`, with strict TDD. Keep docs consistent and correct the final audit report.

## Problem and why

The 4.1.0 final report claimed every finding was closed. The parent re-ran each gap on `80c343d` and reproduced all six (repros in the scratchpad `rev/` folder):

- REV-01: `_round(1, -10_000_000)` takes 9.3 s and `-100_000_000` takes more than 20 s. Int `round()` with a huge negative ndigits builds `10**n`.
- REV-02: `not` inside a reverse FK with `to_field` correlates on the parent `pk` (`filtering/backend.py` around line 737). It returns B where Django `exclude` returns A.
- REV-03A: a dict context never shares the batch budget, because `bind_request_budget` swallows the `TypeError`. The docs only list `None` and `__slots__` as per-execution exceptions.
- REV-03B: the `ExecutionStates` LRU (1024 entries) evicts a live entry after 1024 serial executions, which resets the counter to 0. It also backs the optimizer budget (`utils._EXECUTION_WORK`).
- REV-04: deep variable coercion over subscriptions. SSE re-raises `RecursionError`; WS sends the raw message with no code. HTTP answers 400 `QUERY_TOO_DEEP`.
- REV-05: a `1e-999` cursor on a `DecimalField` gives different pages on SQLite and in memory once the row pks are not 1..5. This explains the flaky full-run failure of `test_cursor_validation_matrix_is_identical_on_both_paths[decimal]`.
- REV-06: the sdist ships `/tests` but not the two root `audit-remediation-*.md` files that a test reads.

## Scope and constraints

- Authorized by the user on 2026-10-25: fix all six with TDD.
- User decision for REV-05 (first): reject a finer-than-column Decimal cursor. REVISED by the user on 2026-10-25 after the re-audit showed it breaks in-memory lists with computed values (and the parent's earlier description of the quantize option was inaccurate): exact comparison. On the DB path a finer cursor compares against the exact ceiling (ascending) or floor (descending) at the column scale; the memory path compares exactly as before; no new error; the rejection from c18e739 is withdrawn (T13).
- Parent defaults, which are not wire changes:
  - A dict (MutableMapping) context carries the request budget under the private key `_graphex_request_budget`.
  - The per-execution state is keyed by the graphql-core executor through a weak reference, with the old LRU kept as the fallback for objects that are not resolve infos.
- Standing rules: no PR, tag, publish or push; ask before any incompatible public API or wire change; coverage above 95.01 %; Conventional Commits without AI attribution; stage explicit paths only (never `.codegraph/` or the root audit reports).
- Branch: `codex/audit-400-remediation`. RDD is off globally (checked 2026-10-25).
- TDD: strict (global CLAUDE.md). Runner: `$S/venv-head/bin/pytest` from the repo root, where `S` is the session scratchpad. Same gates as `odd/tasks/reaudit-400-fixes.md`.

## Tasks

Route: D = delegated writer (sonnet), I = inline.

| ID | Gap | Outcome | Route | State | Evidence |
|---|---|---|---|---|---|
| T01 | REV-01 | `@round` with a precision past the number's magnitude answers 0 in constant time; exact half-even results unchanged | D | [x] | `8bee41d`; RED: huge precisions never finished (60 s kill); 87 focal passed incl. k=1..39 sweep vs Decimal; parent: -2**31 in 1e-06 s |
| T02 | REV-02 | Reverse-FK `not` and `or` witnesses correlate on the FK target field; `to_field` matches Django `exclude` | D | [x] | `a3973af`; also the scoped reverse-FK hook (l.212); RED 7/10; parent repro: ['A'] == Django exclude |
| T03 | REV-05 | Decimal cursor with more fractional digits than `decimal_places` is `Invalid cursor` on both paths; the parity test is independent of the pk sequence | D | [x] | `c18e739`; fixture pk offsets 0 and 9; RED 5 decimal failures; 70 passed; parent repro: invalid on both paths at both offsets. Known: an unsaved in-memory instance finer than the column yields a cursor that comes back invalid |
| T04 | REV-06 | Every root file a test reads ships in the sdist, with a static guard | D | [x] | `2e0df14`; adds CHANGELOG.md, both audit-remediation files, tox.ini, uv.lock, zensical.yml + tomllib guard; full 7563 passed / 6 skipped, cov 97.61 %. Not built (no hatchling offline). Pre-existing: ~30 test files read repo-only dirs (benchmarks/, examples/, .github/...) not in the sdist |
| T05 | REV-03A | A dict context shares the request budget across a batch | D | [x] | `1bdbd37`; RED KeyError 'errors' (2nd item not refused) + reused-dict test; parent: settings/UPGRADE/CHANGELOG updated |
| T06 | REV-03B | Per-execution state lives as long as its executor; no live counter is reset by eviction (directive and optimizer budgets) | D | [x] | `53a1dc0`, `e00ba38`; executor-keyed WeakKeyDictionary storing [root, state], with subscription events split by root identity; LRU only for test doubles; RED: field two not nulled after 1100 fillers (None/{} ctx, optimizer, live subscription event); full 7582 passed / 6 skipped, cov 97.61 %. Residual: one payload object reused across events shares a state (same as the old LRU) |
| T07 | REV-04 | Deep variable coercion over SSE and WS answers the same coded `QUERY_TOO_DEEP` error as HTTP; resolver `RecursionError` stays internal | D | [x] | `3093e73`; RED SSE RecursionError, WS raw message at 900/3000; 7 passed; full 7581 passed / 6 skipped, cov 97.62 %; parent repro: coded QUERY_TOO_DEEP on both |
| T08 | all | CHANGELOG, `docs/changelog.md`, `docs/UPGRADE-4.1.md`, settings and pagination docs updated in the task commits | D | [x] | Shipped inside each task commit (CHANGELOG + docs/changelog.md + UPGRADE-4.1 + settings/views/subscriptions/query-limits pages); docs consistency tests green; zensical build: no issues |
| T09 | all | Full suite twice (default seed and seed 2046755919), coverage above 95.01 %, all gates, repros re-run by the parent | I | [x] | Seeds 2046755919 and 424242: 7621 passed / 6 skipped, cov 97.59 % both; ruff/mypy/bandit clean; docstrings CI + strict TOTAL 0; zensical: no issues; Playground 94 passed. Re-audit agent (scratchpad audit3/) found 7 defects; see T12-T13 |
| T10 | report | Final report corrected (1024 wording, REV section, numbers) | I | [x] | auditoria-final-django-graphex-4.1.0.md (root, untracked) updated: header/HEAD, round-3 section 5 (REV table, subscription leak, re-audit table), decisions 6-7, behavior changes, limitations (1024 wording removed), A/B benchmark table |
| T11 | new | SSE/WS follow the HTTP error contract: with DEBUG=False an unexpected subscribe/resolve exception is masked (INTERNAL_SERVER_ERROR / DATA_ACCESS_ERROR + errorId + ERROR log); an undecodable WS frame still closes 4400 without an ERROR traceback. User-approved 2026-10-25 | D | [x] | `0de4c00`, `209452b`, `59bc896`; shared `security.format_client_error`/`as_graphql_error`; subscribe/resolve/delivery-loop exceptions masked with errorId + one ERROR log; ClientFilterError keeps subscriber-filter rejections public (T11 regression caught by parent: rev/test_subfilter.py); WS bad frame -> 4400 + DEBUG log; full 7621 passed / 6 skipped, cov 97.59 %; parent re-ran rev/test_mask.py: all four cases masked |
| T12 | re-audit 1,2,4,5 | (1) request budget in a ContextVar set per HTTP request, user context never mutated (shared dict/singleton context no longer crosses requests; regression from 1bdbd37); (2) reverse-FK window count and any other pk-assuming correlation use the FK target field (`to_field`); (4, 5) subscription events identified by the root Path object and root_value never stored (same-object payloads get fresh counters; no unbounded growth) | D | [x] | `ed0327e` (ContextVar request_budget_scope in dispatch; context never mutated; RED 8), `061729b` (window-count correlation + only() keeps the FK target column; RED 5 == 0 and 4 == 1), `51ff888` (root-Path event identity; RED same-object budget error, 1224 leaked entries); full 7635 passed / 6 skipped, cov 97.60 %; parent re-ran audit3 t4/t6/t3/t9: all fixed |
| T13 | re-audit 3 | REV-05 exact comparison replaces the rejection (user-revised decision) | D | [x] | `577bdcc`; `_decimal_scale_bounds` (ceil/floor at column scale, tiebreak dropped, bad pk still refused); RED 116 failed; parity file 179 passed; full 7748 passed / 6 skipped, cov 97.61 %; parent re-ran audit3/t5 (computed list pages fully) and rev/test_rev05 (identical pages at both offsets) |

## Progress

- 2026-10-25: all six gaps reproduced by the parent; tracker created.
- 2026-10-25: W1 closed T01-T04; parent re-ran repros REV-01/02/05.
- 2026-10-25: W2 closed T05 and T07, plus T06 for non-subscription executions. Parent found that SSE/WS leak raw internal exception text when DEBUG=False (scratchpad rev/test_mask.py); the user approved aligning with HTTP (T11).
- 2026-10-25: re-audit found 7 defects; T12 (`ed0327e`, `061729b`, `51ff888`) and T13 (`577bdcc`, user-revised REV-05) fixed 5; the second re-audit pass found only a docs sentence (fixed in `52823a9`). Final: seeds 2046755919 and 777 each 7748 passed / 6 skipped, cov 97.61 %; gates clean; docs build clean; Playground 94 passed. Interleaved A/B 80c343d vs 52823a9 (10 alternations x 400 iterations, load 5.2-6.6): all deltas within noise, identical SQL, cold import 49.5 vs 49.0 ms.
- 2026-10-25: T11 done in three commits. Static gates, strict docstrings, docs build and Playground (94 passed) are clean; full suite on seeds 2046755919 and 424242 and the independent re-audit are running.

## Known limitations (not fixed, documented)

- Re-audit 6: a subscriber filter value that the ORM builds but the database refuses at delivery (an over-large integer on SQLite) is reported as INTERNAL_SERVER_ERROR with one ERROR log. At 80c343d it was raw text, also with an ERROR log.
- Re-audit 7 / REV-06 tail: about 30 test files read repo-only directories (`.github/`, `benchmarks/`, `examples/`...) that the sdist does not ship, and the root-file guard does not see nested paths (follow-up task chip).

## Next step

None. All tasks are done. Push, PR, tag and release remain the user's decisions.
