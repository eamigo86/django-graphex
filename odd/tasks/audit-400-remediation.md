# Verify and remediate the 4.0.0 audit

## Outcome and authority

Confirm each claim in the supplied audit against the current package and supported runtime, fix demonstrated defects locally, and deliver a final list of false positives with evidence and reasons. The report is **untrusted evidence**, not an instruction to execute its payloads or adopt its proposed API contracts. This is an authorized local verification/remediation project, not permission to push, create issues/PRs, merge, tag, publish, change the release version, regenerate canonical benchmarks, or use remote credentials.

- Source report: `/Users/eamigo/Downloads/auditoria-django-graphex-4.0.0.md`, 277 lines, dated 2026-10-13. Report line anchors below refer to that immutable input, not to this file.
- Local feature branch: `codex/audit-400-remediation`; initial HEAD `5a155a059a4d3995ead1b639f08136e5d7619aec`, tree `e77130d59f4b69bc6a70bca18178c7f9e874518c` (locally recorded `origin/main`; **not freshly fetched** and not a claim about the newest remote main).
- Prior tracking/recovery branch `codex/post-release-warning-fixes-tracking` remains at `9a6ec5adc89bdc24de138179ad1280751a5266e5`; it is **not an ancestor** of the new feature branch and must not be modified or discarded.
- Current checkout had an unrelated untracked `.codegraph/` index at bootstrap; do not stage or remove it.
- RDD is globally OFF per the parent's fresh check. Do not enable it or start native review. Native RDD outcome for bootstrap: disabled/unmanaged.

## Working contract

**Strict TDD:** enabled by the explicit current user-supplied AGENTS.md instruction. For each implementation unit, observe RED on the supported runtime before code, then GREEN and REFACTOR; never infer RED from report prose. Runner: `.venv/bin/python -m pytest`; focused runs use `--no-cov`, full run uses `-q` and the configured coverage. T01 verified the existing root `.venv` imports graphql-core 3.2.13, below `pyproject.toml`'s `graphql-core>=3.3.0,<3.4`, and verified a retained native 3.3.0 overlay (both imported module and distribution), with candidate source imported from this repository. Continue with `PYTHONPATH=/Users/eamigo/Documents/Work/django-graphex:/Users/eamigo/.codex/visualizations/2026/09/02/01a062ff-dccb-7123-a1e9-e7de825aafc2/graphex-resume-2026-10-02/native330-reconstruction/core330-overlay PYTHONDONTWRITEBYTECODE=1 /Users/eamigo/Documents/Work/django-graphex/.venv/bin/python -m pytest ...`; assert those identities before each new test work unit. Never refresh the root environment or mix ABIs. No test outcome is accepted from an unverified runtime.

**Safety:** never execute suggested attack payloads blindly. Use deterministic, bounded visit-count or allocation-guard reproductions for fan-out/cycles and bounded resource tests for memory risks; no large DoS load. Protect benchmark databases, canonical result JSON, and existing environments. Disposable pytest assets may be created by later implementation workers. Preserve all **16 original C/A finding IDs** and all **14 existing Git tags**; do not create a tag. For every claim, record source/runtime, reproducible RED or other evidence, disposition, fix/contract rationale, exact checks, and final false-positive reason. Initially **U = unverified**, regardless of the report's checkmark. A design limitation, documented default, unsupported contract, duplicate symptom, confirmed bug, and false positive are distinct outcomes; do not mark any as false positive just because it is not changed.

**Public API gate (current user decision):** The user conditionally authorizes incompatible changes **only when their necessity is demonstrated**, and only after each individual candidate is explained with examples and migration impact and receives separate explicit approval **before implementation**. The user individually approved **BP-C3-001** (`analyze_cost()` may raise `GraphQLError` for cyclic fragments) and **BP-A8-001** (decimal-string BigInt on regular BigIntegerField/PositiveBigIntegerField outputs, generated inputs, and automatic filters). This is not blanket approval. Decimal precision/default changes, nested tenant/permission scope semantics, relation-ID type changes, and every other incompatible contract remain unapproved. Independent verification and compatible fixes may continue. Do not select another scalar, security default, or cross-relation authorization contract on the user's behalf. Continue TDD and documentation with coverage above 95%; do not tag or publish.

**Quality:** all changed/public signatures fully hinted; full Google-style Args, Returns, and Raises sections where applicable, without repeated types or docstring backticks. Update tests, docs, and changelog alongside behavior. Pure branch and combined coverage must each be at least 95.01%; patch coverage at least 95.01% when nonempty (report N/A honestly otherwise). No warning filters, coverage exclusions, skips, padding, or `-o addopts=""` to manufacture passing checks. Run applicable Ruff check/format check, mypy, docstring audits, docs anchors, focused/full tests, and `git diff --check`; record every failed, unavailable, or skipped check. No local public artifact build.

**Implementation route:** delegated direct, not SDD. Broad preparation and two-or-more nontrivial files trigger one bounded writer per unit; verification/build execution is delegated. Commits are Conventional Commit work units on this feature branch, with behavior/tests/docs together and exact verification evidence. About 400 authored lines per work unit is advisory only, never a reason to code-golf. Rough total forecast is at least 1,000–1,800 authored lines for C/A alone, with high uncertainty from the remaining claims. Delivery strategy is `ask-on-risk`; chain strategy is **unresolved** until a real delivery decision. No PR is authorized now. Record eventual authored additions+deletions and PR-slice boundaries only if delivery is requested.

## Task sequence

Each task is an independently recoverable work unit. `T00` is tracking-only; all remaining tasks are pending and require evidence before closure. `D` means delegated route due to broad preparation, multiple nontrivial files, and/or test execution. A later worker may split a coherent task when required, preserving IDs and the claim ledger.

| Task | Route | Outcome and acceptance evidence | State |
|---|---|---|---|
| T00 | D, bootstrap | Record complete report traceability, local branch/runtime constraints and proof; mirror full file in Engram; tracking-only conventional commit. Structural readback only; runtime test N/A because no runtime/source behavior changed. | [x] |
| T01 | D | Supported graphql-core 3.3 baseline: verify module/distribution/candidate identities, focused baseline and full suite including environment-only benchmark provenance distinction; preserve exact failures without changing root env, benchmarks, or canonical results. Baseline established, full suite red on Q2; see T01 proof below. | [x] |
| T02a | D | **BP-C3-001 approved and implemented:** strict-TDD polynomial cycle precheck shared by direct cost analysis and cost/depth validation, before expensive expansion; preserve acyclic semantics and GraphQL endpoint errors; exact quality/coverage proof and documentation. C3 only; see proof below. | [x] |
| T02b | D | **Independently accepted, including ordered-effect correction:** initial source commit `92b1358f31a2973abe7a817b820d54775a9067a6` passed its original gates but failed independent compatibility. Correction commit `7bec957180edcf138d50256777a9e1bfb196f2b5` adds permanent RED tests and bounded replay of last-write-wins prefetch/alias effects. Native full, coverage, docs and quality gates pass from a pre-run source freeze; independent recheck and parent spot check pass. The old proof remains historical. No unapproved public-contract change. | [x] |
| T03a | D | **C1 independently accepted:** `dbabfde` adds RED→GREEN primary-key tests and retains prior `Float!`/null propagation; original related batch and full gates pass after distinct T16b fixture repair. Independent recheck and parent spot check pass. A8/M-D3/M-D4 and scalar defaults remain separate. | [x] |
| T03b | D | **Writer correction PASS; independent recheck pending:** approved A8 source `8f86dc8` passed its original gates but failed independent relation-ID/choices-Enum compatibility. Correction `12a7506` adds three permanent actual-mutation RED→GREEN cases and restores both contracts without changing approved direct-value BigInt. Native full, coverage, docs, quality and asset checks pass from final source freeze; see `t03b-validation-correction/README.md`. Initial writer and independent failure proofs remain historical. | [ ] |
| T03 | D | Reproduce C1/A8/Decimal cases; use compatible fix if proven adequate. For each necessary incompatible SDL candidate, explain examples and migration impact to the user and obtain its separate explicit approval before implementation; output/input regression tests and docs. | [ ] |
| T04 | D | Confirm/fix A2 cache byte/body-order limits and A11 expansion cap; bounded tests and resource checks. | [ ] |
| T05 | D | Confirm/fix A1 transaction/rollback and related batch/multi-DB/lost-update behavior; exact DB transaction tests and view parity. | [ ] |
| T06 | D | Confirm/fix A3/A4 plus permission descriptors and enum/type collisions; fail-safe schema tests and compatibility checks. | [ ] |
| T07 | D | Confirm §4 relationship/filter/link/adoption/GFK scope claims; use compatible fixes where sound. Explain each necessary incompatible cross-relation authorization change with examples/migration impact and obtain separate user approval before implementation; multi-tenant regression tests. | [ ] |
| T08 | D | Confirm/fix A5/A6 and subscription lifecycle, filters, events, and transport claims; real-user WS/SSE and failure-path tests. | [ ] |
| T09 | D | Confirm/fix A7 input default factories, unsupported annotations, Pydantic collisions, and interface names; schema/runtime regression tests. | [ ] |
| T10 | D | Confirm/fix A9/A10 delete/constraint/validator error mapping; safe error payload tests and docs. | [ ] |
| T11 | D | Confirm/fix A12 and medium filter semantics/types/limits; relational and truth-table regression tests. | [ ] |
| T12 | D | Confirm/fix A13 and pagination ordering/count/page boundary claims; backend-specific and in-memory regression tests. | [ ] |
| T13 | D | Confirm/fix HTTP/cache/error/introspection/limits and async-view claims, separating documented defaults from defects and optional hardening; each necessary incompatible public-default change needs its own explained user approval before implementation. | [ ] |
| T14 | D | Confirm/fix optimizer selection/concurrency/thread-safety and remaining low-level exception/memory claims where reproducible; bounded tests. | [ ] |
| T15 | D | Confirm/fix scalar, directive, and low-level output-contract claims not already covered; behavior-specific tests/docs. | [ ] |
| T16a | D | **Before core fixes:** strict-TDD compatible Q2 fix: select exactly the eight named canonical benchmark results even when unrelated ignored diagnostic JSON coexists; test fixtures copy only those names. Preserve missing/invalid canonical rejection, public CLI/output contract, benchmark assets, and fresh full-suite coverage evidence. Completed with source commit and checks below. | [x] |
| T16b | D | **Independently accepted fixture repair:** `ca6cfb7` registers an allowlisted User target in the test-local Registry, retains/adds relation assertions, and makes the isolated RED test GREEN. Independent isolation and parent spot checks pass; production relation-drop behavior unchanged. | [x] |
| T16 | D | Remaining tooling/test hygiene, missing test coverage, stale runtime/metadata, maintainability/refactor/dead-code suggestions; only justified, authorized local changes, no benchmark regeneration. Q2 belongs to T16a. | [ ] |
| T17 | D | Complete independent disposition of every ledger ID, verify section-9 negative claims, run full quality/coverage gates, list all final false positives with evidence and reasons, and report remaining design decisions or unavailable checks. | [ ] |

## Claim traceability ledger

Status for **every** item below is `U` at bootstrap. The report's ✅/🔁/📖 labels are claims about its own methods, not acceptance evidence. Related rows are marked `↔` where they may share a root cause; they remain independently traceable. Exact line anchors prevent a later worker from silently dropping subclaims. `T17` closes every row, including duplicates and no-change decisions.

### Critical and high (original IDs preserved)

| ID | Report line | Distinct claim / dependency | Task |
|---|---:|---|---|
| C1 | 36–44 | **Confirmed and independently accepted:** Decimal primary-key `Float!`/null propagation are restored in `dbabfde`; independent recheck, original related batch and parent spot check pass after separate T16b fixture repair. Separate M-D3 precision/M-D4 scalar acceptance remain open. | T03a/T03 |
| C2 | 46–58 | **Confirmed defect, independently accepted T02b:** initial visit-only fan-out fix changed valid interleaved plan and alias writes. Correction `7bec957` replays cached ordered effects and passes permanent endpoint/alias tests, bounded visits, native full and coverage gates. The duplicate FieldNode output of `_iter_promotion_fields` remains unchanged. | T02b |
| C3 | 60–72 | **Confirmed defect, fixed T02a:** bounded native 3.3 cyclic fan-out required 767 cost/depth visits at eight levels versus 27 acyclic visits. Shared iterative fragment-graph precheck now stops cyclic expansion before either walker; direct `analyze_cost()` raises the individually approved `GraphQLError`. Standard endpoint rejects the document without resolver calls. | T02a |
| A1 | 80 | ATOMIC_MUTATIONS and ATOMIC_REQUESTS errors allegedly commit; view parity/flag claims. | T05 |
| A2 | 81 | Count-bounded cache retains unbounded AST bytes; body limit allegedly after parse/cache. | T04 |
| A3 | 82 | Invalid/string only_fields/exclude_fields can expose excluded fields or empty types. | T06 |
| A4 | 83 | Duplicate model type registration silently selects last type and may expose admin fields. | T06 |
| A5 | 84 | Permission-scoped WS/SSE schema provider allegedly runs sync ORM on event loop. | T08 |
| A6 | 85 | Failed Redis/binding representation callback allegedly surfaces after commit and interrupts later callbacks. | T08 |
| A7 | 86 | Pydantic default_factory allegedly evaluated at compile time, sharing UUID/list across requests. | T09 |
| A8 | 87 | **Confirmed; approved T03b writer correction passes, independent recheck pending:** prior Int rejected 2147483648/9007199254740993; `8f86dc8` maps regular BigIntegerField/PositiveBigIntegerField values to decimal-string BigInt. Independent `t03b-independent/README.md` proved relation-ID/choices-Enum validation regressions; `12a7506` restores both with permanent actual-mutation tests and final gates. | T03b/T03 |
| A9 | 88 | Protected/restricted delete allegedly leaks raw error instead of mutation envelope. | T10 |
| A10 | 89 | Constraint/upsert IntegrityError and Django validators allegedly bypass clean mapping/validation; includes blank/email/positive/overflow variants. | T10 |
| A11 | 90 | @replace empty-old expansion allegedly unbounded; bounded no-allocation reproduction required. | T04 |
| A12 | 91 | AND over to-many relations allegedly reuses JOIN and loses valid matches. | T11 |
| A13 | 92 | In-memory cursor ordering for float/Decimal/UUID allegedly compares unlike types. | T12 |

### Security design (§4)

| ID | Report line | Distinct claim / dependency | Task |
|---|---:|---|---|
| SD1 | 98–99 | Destination type get_queryset allegedly not applied to relation reads. | T07 |
| SD2 | 100 | Related filter allegedly acts as an oracle for hidden records. | T07 |
| SD3 | 101 | Foreign/M2M linking allegedly permits cross-tenant IDs and existence oracle. | T07 |
| SD4 | 102 | Orphan reverse-child adoption allegedly crosses tenant boundary. | T07 |
| SD5 | 103 | GenericForeignKeyType allegedly exposes target identity without target permission. | T07 |
| SD6 | 105 | Proposed strict_scope mode/system check is a **recommendation**, not proof that the current documented contract is defective; public semantics require user decision. | T07 |

### Medium: security/defaults and data correctness

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| M-S1 | 114 | Variable limit allegedly costed at default page size versus literal actual size when MAX_PAGE_SIZE=None. | T13 |
| M-S2 | 115 | Default limit settings None (page size, depth, cost, body); unbounded `in` list; unbounded Boolean breadth/depth—three separately verifiable subcases. | T11/T13 |
| M-S3 | 116 | ALLOW_INTROSPECTION=False allegedly inert without middleware despite documentation. | T13 |
| M-S4 | 117 | Errors allegedly expose SQL/constraint/table details with DEBUG=False. | T13 |
| M-S5 | 118 | GET cache concatenated-key collision, including comment-based variant. | T13 |
| M-S6 | 119 | Field shortcut descriptors allegedly omit required_perms and stay public under scoped schema. | T06 |
| M-D1 | 124 | Partial update allegedly saves whole row and causes lost concurrent update. | T05 |
| M-D2 | 125 | Nested atomic and binding on_commit allegedly omit database alias; two subcases. | T05/T08 |
| M-D3 | 126 | DecimalField mapped to Float loses precision; ↔ C1. | T03 |
| M-D4 | 127 | Decimal scalar allegedly accepts NaN, Infinity and huge exponents that break Django validation; each input class to test. | T03 |
| M-D5 | 128 | JSON scalar allegedly parses a JSON-looking string into a different JSON type. | T15 |
| M-D6 | 129 | JSONRaw allegedly preserves Undefined in lists and accepts infinity-producing exponent; two subcases. | T15 |
| M-D7 | 130 | Different model/field paths allegedly collide on enum name. | T06 |
| M-D8 | 131 | Model fields colliding with Pydantic methods allegedly break type creation. | T09 |
| M-D9 | 132 | Interface field naming allegedly ignores explicit `name=`. | T09 |
| M-D10 | 133 | Literal/dict/set/Union input annotations allegedly degrade to String without warning; classify each annotation. | T09 |

### Medium: filters, HTTP, optimizer, subscriptions, thread safety

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| M-F1 | 138 | Related field named year/month/day/range allegedly misclassified as PK lookup and raises TypeError. | T11 |
| M-F2 | 139 | Date-part lookups allegedly typed DateTime instead of Int. | T11 |
| M-F3 | 140 | exact:null drops filter; not:{} and or:[] match all; or:[{},X] yields X—four truth-table cases. | T11 |
| M-F4 | 141 | page:null allegedly raises raw TypeError. | T12 |
| M-F5 | 142 | LimitOffset/Page allegedly lack stable PK tie-breaker and skip/duplicate rows. | T12 |
| M-F6 | 143 | Count DatabaseError fallback allegedly materializes full queryset. | T12 |
| M-F7 | 144 | Page pagination without page size allegedly returns null results with positive count. | T12 |
| M-H1 | 149 | Batch HttpError allegedly aborts all results after earlier mutations commit. | T05/T13 |
| M-H2 | 150 | Async resolver in sync view allegedly causes coroutine AttributeError/500. | T13 |
| M-H3 | 151 | CLEAN_RESPONSE allegedly removes falsy 0/False/empty string/list as well as null. | T13 |
| M-H4 | 152 | Response cache allegedly retains error results. | T13 |
| M-O1 | 157 | Root optimizer allegedly reads only first field node, causing missed fragment selection/N+1. | T14 |
| M-O2 | 158 | Permission-signature cache allegedly holds global RLock through prune_fn and serializes hits. | T14 |
| M-U1 | 163 | complete/disconnect during start allegedly leaves ghost subscription. | T08 |
| M-U2 | 164 | id_only delete allegedly drops events with scope or non-PK filters. | T08 |
| M-U3 | 165 | In-memory subscription filter string coercion allegedly fails Decimal/DateTime/Float. | T08 |
| M-U4 | 166 | m2m_changed and bulk/update paths allegedly emit no events; determine documented contract separately. | T08 |
| M-U5 | 167 | Directive wrapping async resolver allegedly stringifies coroutine. | T15 |
| M-U6 | 168 | @date null/localtime/date-only; camel/snake/kebab conversion; @number/@currency null-to-zero—seven distinct behavior families. | T15 |
| M-T1 | 173 | Global _forking_depth allegedly races across schema-building threads and loses field inclusion settings. | T14 |

### Low (§6)

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| L-C1 | 180 | Malformed ID in get_node/retrieve/DjangoObjectField allegedly raises raw error instead of null; three entry points. | T15 |
| L-C2 | 181 | Configuration guards allegedly use assert and disappear under python -O. | T14 |
| L-C3 | 182 | GraphQLView/BaseGraphQLView status and data:null response contracts diverge. | T13 |
| L-C4 | 183 | Multipart files allegedly bypass MAX_UPLOAD_SIZE. | T13 |
| L-C5 | 184 | LIMIT_MINIMUMS allegedly skips three named settings. | T13 |
| L-C6 | 185 | ensure_csrf_cookie allegedly prevents browser cache reuse after first request. | T13 |
| L-C7 | 186 | Positional enum suffix allegedly changes on choices reorder. | T06 |
| L-C8 | 187 | page:-1 allegedly not last actual page. | T12 |
| L-C9 | 188 | Null ordering allegedly differs between DB and memory cursor. | T12 |
| L-C10 | 189 | Directives declared on fragment spreads/inline fragments allegedly ignored. | T15 |
| L-C11 | 190 | @truncate, @title and @floor allegedly mishandle infinity; independently check each. | T15 |
| L-C12 | 191 | Inline fragment applicability allegedly misses unions and MTI parents, causing N+1. | T14 |
| L-C13 | 192 | Naive/date-only scalar inputs allegedly assume local time without documentation. | T15 |
| L-E1 | 195 | Broad exception handlers allegedly silently drop model-derived/relation fields; two paths. | T14 |
| L-E2 | 196 | getattr default allegedly hides AttributeError raised inside property. | T15 |
| L-E3 | 197 | Filtered prefetch merge allegedly drops optimize_<field> hook and may bypass scope. | T07/T14 |
| L-E4 | 198 | WS cancellation allegedly swallows CancelledError and other exceptions. | T08 |
| L-M1 | 201 | Input registry allegedly grows unbounded and duplicates on redefine. | T14 |
| L-M2 | 202 | Native identity cache allegedly vulnerable to recycled id(). | T14 |
| L-M3 | 203 | Enum type cache allegedly lacks lock. | T14 |
| L-M4 | 204 | Global/list-object registry creation allegedly has check-then-act race. | T14 |
| L-S1 | 207 | SSE allegedly lacks heartbeat and per-user stream cap. | T08 |
| L-S2 | 208 | connection_init payload allegedly ignored; no token-auth on_connect hook. | T08 |
| L-S3 | 209 | WS allegedly accepts subprotocol not offered by client. | T08 |
| L-S4 | 210 | WS allegedly sends complete before releasing operation ID, causing spurious 4409. | T08 |

### Tooling, maintainability, recommendations, and negative checks

| ID | Report line | Distinct claim / relationship | Task |
|---|---:|---|---|
| Q1 | 15–18, 217 | **Partly observed T01:** root graphql module/distribution 3.2.13 vs required 3.3.0; source pyproject 4.0.0 vs package `__version__`/installed metadata 3.1.0. Current test counts differ from report. Tox, lint/mypy and proposed guard remain unverified. Do **not** run `uv sync` on root merely because report suggests it. | T01/T16 |
| Q2 | 218 | **Confirmed defect, fixed T16a:** all-JSON validator and copied-directory tests failed on 28 protected local extras beyond eight tracked top-level canonical files. Explicit eight-name selection now ignores unrelated diagnostics while missing/invalid canonical results still fail; RED/GREEN and full-suite proof below. Not a false positive. | T01/T16a |
| Q3 | 219 | Multipart tests allegedly leak temporaries and emit ResourceWarning. | T16 |
| Q4 | 221–233 | Suggested missing regression matrix for Decimal, BigInt, C2/C3, A1–A7, A9/A10, A12/A13 and page:null; **coverage recommendation**, duplicates behavior rows, not new defect IDs. | T03–T16 |
| Q5 | 235 | Historical test-file names allegedly obstruct feature discovery; maintainability suggestion, not a runtime bug. | T16 |
| Q6 | 238 | Mega-module sizes and proposed split; maintainability suggestion, not automatic refactor authority. | T16 |
| Q7 | 239–242 | Repeated fragment walkers ↔ C2; mutation delete/update ↔ A9; view get_response divergence ↔ A1/L-C3. Check independently before any refactor. | T02/T05/T10/T16 |
| Q8 | 243–248 | Claimed dead factory/compiler/registry/get_fields/mutation flag/model lookup symbols; verify callers and public compatibility before removal. | T16 |
| Q9 | 249 | Historical graphene names/comments; naming suggestion only. | T16 |
| Q10 | 250 | Nullable output fields despite null=False; proposed opt-in non-null derivation changes SDL and requires product decision. | T16 |
| P1 | 256–265 | Prioritized action plan (Decimal, fragments, cache, rollback, subscriptions, schema controls, scalar/errors, hardening, strict_scope, refactors) **duplicates above IDs**; neither an extra finding nor authority to run uv sync/change defaults. | T01–T17 |
| N1 | 269 | Report says permission signature cache is user-isolated; independently verify as negative claim. | T17 |
| N2 | 270 | Report says anonymous/falsy permission classes fail closed and update/delete first use scoped queryset; independently verify. | T17 |
| N3 | 271 | Report says nested introspection is blocked by MaxIntrospectionDepthRule; independently verify. | T17 |
| N4 | 272 | Report says utils caches are request-scoped; independently verify. | T17 |
| N5 | 273 | Report says format_graphql_error regex is not exploitable due to truncation; bounded check only. | T17 |
| N6 | 274 | Report says remaining lint/types/tests are clean; verify under supported environment. | T17 |

## Progress and next action

The ledger above is authoritative for **100 claim IDs**; the evidence below is a compact recovery index. Detailed commands, RED/GREEN streams, timestamps, source freezes and preserved historical failures remain in the immutable local proof folders under `/Users/eamigo/.codex/visualizations/2026/09/02/01a062ff-dccb-7123-a1e9-e7de825aafc2/audit-400-remediation/` and in this tracker’s Git/Engram history. Do not reinterpret a superseded PARTIAL run as PASS.

| Unit | Commits and outcome | Coverage and retained caveat | Proof folders |
|---|---|---|---|
| T00/T01 | Tracker `10431d754ed9944ccdd5728d44affa8152dd54e3`; baseline `74c252b93083d089928be5f91961d7a488808054`. Native module/distribution 3.3.0 overlay, root 3.2.13 retained. Initial 29 focal passed; full 4940 passed/7 skipped/**17 Q2 provenance failed**/3 warnings. | No accepted fresh XML on failing baseline; patch N/A. Old branch and 14 tags preserved. | `t01-baseline/README.md` |
| T16a/Q2 | Source `e31333468774344e176031d1241e25c2d1642dd3`, independently accepted. Eight canonical files selected; unrelated diagnostic JSON left untouched. RED 2 → GREEN 2; related 59, benchmark 357; full 4960 passed/7 skipped/3 warnings. | Pure branches 3672/3864=95.0311%; combined 97.37%; runtime patch N/A. Earlier external Zensical config panic was corrected by isolated relative-copy build; not a final failure. | `t16a-canonical/README.md`, `t16a-independent/README.md` |
| T02a/C3 | User individually approved BP-C3-001 only. Source `2943f4544fe0c56064895a35b8606effe50013be`, docstring correction `c57485594f83244f0dd4fcfdc71165cfb7d4da02`, independently accepted. Direct cost now raises GraphQLError on fragment cycles; endpoint rejects before resolvers. RED 2 → GREEN 2, focal 56, full 4966 passed/7 skipped/3 warnings. | Pure 3695/3888=95.0360%; combined 97.3626%; patch 40/40. Earlier 94.9383% branch run failed; independent DOC003×2 in changed tests led to correction; runtime-only audit was insufficient. | `t02a-cycles/README.md`, `t02a-doc-correction/README.md`, `t02a-recheck/README.md`, `t02a-parent-spot/focal.log` |
| T02b/C2 | Initial source `92b1358f31a2973abe7a817b820d54775a9067a6`; ordered-effect correction `7bec957180edcf138d50256777a9e1bfb196f2b5`, independently accepted. Small valid fanout caused 4/16/64/256 visits; final memo/replay retains endpoint data, SQL and alias precedence. Corrected RED 2 → GREEN 2; related 287; full 4977 passed/7 skipped/3 warnings. | Pure 3737/3932=95.0407%; combined 14253/14638=97.3699%; final independently measured patch 76/76 (writer 68/68). Earlier 94.9898% branch gate and candidate order regressions were PARTIAL; original freeze was after its full run, correction freeze was before. | `t02b-reproduction/result.txt`, `t02b-optimizer/README.md`, `t02b-independent/README.md`, `t02b-ordered-correction/README.md`, `t02b-recheck/README.md`, `t02b-parent-spot/focal.log` |
| T03a/C1 + T16b | Initial C1 `bd45a6546cbb70a3e4151b087ff51110eed00706`; Float! wrapper correction `dbabfde2f1367f869c88ed22cfe91ce267ba02ca`; isolated converter fixture `ca6cfb72bb388783e02bec20e4b29795b78e3abf`; tracking `43287f7ff42d26ac2eef6cbd3035abd8a63ad6fc`. Independently accepted. Decimal output stays Float, precision limitation remains M-D3; custom Decimal input/overrides unaffected. New PK RED 2 → GREEN 2; converter isolated RED 1 → GREEN 1; exact related 212; full 4988 passed/7 skipped/3 warnings. | Pure 3739/3934=95.0432%; combined 14262/14647=97.3715%; patch 7/7. Initial source PARTIAL: required related 209 passed/1 failed due separate pre-existing fixture, and independent Float! regression; corrected separately. | `t03-decimal-triage/result.txt`, `t03a-decimal-output/README.md`, `t03a-independent/README.md`, `t03a-wrapper-and-fixture/README.md`, `t03a-recheck/README.md`, `t03a-parent-spot/focal.log` |

All accepted units passed their applicable Ruff, mypy, changed-Python docstring, strict isolated Zensical/42-page anchors, diff and protected-asset checks. Writer full suites were authenticated rather than rerun by independent verifiers; parent focal spot checks passed. The Q2/C1/C2/C3/T16b claims are **not** false positives. RDD is OFF; no native review approval is claimed. Old root coverage/site, all eight tracked plus 28 ignored top-level benchmark JSON, benchmark DBs, root environment, prior proof and all 14 tags remain protected.

**BP-A8-001 individual approval (T03b only):** The latest human explicitly said, “Sí, apruebo A8: BigInt con valores como cadenas en salida, entradas y filtros. Continúa con TDD, documentación y cobertura >95%, sin tags ni publicar. Los demás cambios incompatibles me los explicas antes.” Native triage `t03-bigint-triage/result.txt` demonstrates 2147483647 works while 2147483648 and 9007199254740993 fail output/generated input before resolver; automatic filters use Int. T03b may change only regular BigIntegerField/PositiveBigIntegerField output, generated input and automatic filters to a bounded decimal-string BigInt scalar (including small values). Ordinary integers, AutoField/BigAutoField ID, custom overrides, Decimal/Float semantics, permissions and unrelated defaults remain unchanged. Client migration: GraphQL type/variable names and wire values become BigInt/string on these surfaces. Every other incompatible candidate requires its own explanation, examples, migration impact and explicit approval **before** implementation.

**T03b/A8 writer proof:** Approved source/tests/docs commit `8f86dc8927eb66a62dcdcf8936c40b659d6e6ead`, tree `ef7cb8f0769e8e1979bf87da8a091a185355b2f7`, **778 insertions + 18 deletions = 796 authored lines** (cohesive public scalar, boundary tests and docs; 400 advisory exceeded honestly). Cause-correct RED 8, same initial GREEN 8; final focal 31 and related 242 passed. Real generated mutation persists `9007199254740993` from a string; automatic ORM filter selects it, with string output. Invalid numeric/float/bool/malformed/superlong input stops before resolver; signed 64-bit bounds, positive validation, nullable output/PK non-null, explicit override, ordinary Int/Auto ID and existing M2M relation-ID `[Int!]` are pinned. One intermediate test-only table creation failed because pytest had synced it already, then corrected; initial RED also had a corrected test-local registry typo. Final frozen native-3.3 full **5019 passed/7 skipped/3 warnings**; pure branches **3755/3950 = 95.0633%**, combined **14309/14694 = 97.3799%**, committed runtime patch **31/31 = 100%**. Ruff, mypy, all nine changed-Python docstring audits, strict isolated docs/42 anchors, diff checks, 14-file pre-run freeze and **87,186** protected files/14 tags pass. Examples/benchmarks use BigAuto IDs or ordinary integers, so no source change there; eight canonical and 28 diagnostic JSON remain untouched. Exact logs/commands/UTC/rollback: external `t03b-bigint/README.md`. **Writer proof is not independent acceptance**; no other incompatible contract was implemented.

**T03b independent finding and correction boundary:** `t03b-independent/README.md` independently reproduced two actual generated-mutation regressions: numeric `42` and string `"42"` for an unchanged `ID!` ForeignKey input to a BigInteger primary key both fail Pydantic `BigIntValue` validation (exact pre-A8 runtime persists target ID 42); numeric choices Enum `ONE=1` for PositiveBigIntegerField fails unconditional `ge=0` application (exact pre-A8 runtime persists 1). Independent ordinary boundary controls, 31 focal tests and 242 related tests passed; these did **not** exercise the regressions. Writer 5019-pass coverage proof above is retained but does not close T03b. Correction is limited to preserving relation-ID coercion and choices-Enum validation while retaining approved decimal-string BigInt for direct values. New proof root: `t03b-validation-correction/`.

**T03b writer correction proof:** `12a7506a8b83c75ee211e1174dca9c3fbdf748c2` (tree `6ba5ef7d72af8865b0b0b852ef2f488265cecb95`; 182 insertions + 4 deletions = 186 authored lines) changes only Pydantic type/constraint guards, three actual-mutation tests and synchronized A8 documentation. Native 3.3 RED 3 → same GREEN 3; final freeze precedes focal 34, exact related 245 and configured full **5022 passed/7 skipped/3 warnings**. Fresh pure branches **3755/3950=95.0633%**, combined **14310/14695=97.3801%**, runtime patch **35/35=100%**. Ruff, mypy, changed-Python docstring audits, strict isolated docs/42 anchors, diff and source-hash checks pass. Initial DOC002 audit failure was corrected before final freeze and full rerun; a proof-manifest attempt blocked on a retained pytest FIFO and was interrupted, then corrected to hash only regular files/symlinks. Final protected before/after manifests match for **95,398** assets; **95,217** common files also match the prior independent byte hashes (the seven deliberately edited files are excluded); all 14 tags and old tracking ref are unchanged. Exact commands, UTC, failed intermediates and rollback boundary: external `t03b-validation-correction/README.md`. This is writer proof, not independent acceptance.

**Next:** Obtain bounded independent A8 recheck and parent spot check before closing T03b/A8. T03 remains open for M-D3/M-D4; all other public incompatibilities require individual approval. No tags or publication.

**Mirror:** `odd/audit-400-remediation/tasks` in project `django-graphex`, observation `15165`; save/read back the complete current document with locator `odd/tasks/audit-400-remediation.md` after updates.
