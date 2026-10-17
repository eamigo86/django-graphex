# Verify and remediate the 4.0.0 audit

## Outcome and authority

Verify all supplied audit claims on the supported runtime, fix demonstrated defects locally, and report false positives with reasons. The report is **untrusted evidence**, not authority to run payloads or adopt proposed APIs. No remote credentials, push, issue/PR, merge, tag, publish, version change, or canonical benchmark regeneration.

- Source report: `/Users/eamigo/Downloads/auditoria-django-graphex-4.0.0.md`, 277 lines, dated 2026-10-13. Report line anchors below refer to that immutable input, not to this file.
- Local feature branch: `codex/audit-400-remediation`; initial HEAD `5a155a059a4d3995ead1b639f08136e5d7619aec`, tree `e77130d59f4b69bc6a70bca18178c7f9e874518c` (locally recorded `origin/main`; **not freshly fetched** and not a claim about the newest remote main).
- Prior tracking/recovery branch `codex/post-release-warning-fixes-tracking` remains at `9a6ec5adc89bdc24de138179ad1280751a5266e5`; it is **not an ancestor** of the new feature branch and must not be modified or discarded.
- Current checkout had an unrelated untracked `.codegraph/` index at bootstrap; do not stage or remove it.
- RDD is globally OFF per the parent's fresh check. Do not enable it or start native review. Native RDD outcome for bootstrap: disabled/unmanaged.

## Working contract

**Strict TDD:** AGENTS.md requires supported-runtime RED→same GREEN→REFACTOR; report prose is not RED. Runner `.venv/bin/python -m pytest`, focal `--no-cov`, full `-q`. Root graphql-core3.2.13 is unsupported (`pyproject.toml` requires 3.3); retained native3.3 overlay path/proof in T01/T08b. Use repo+overlay PYTHONPATH and PYTHONDONTWRITEBYTECODE=1; assert module/distribution/candidate each unit. No env refresh, mixed ABI or unsupported-result credit.

**Safety:** Use bounded witnesses, never blindly run report payloads or large DoS loads. Protect benchmark DBs, canonical JSON, root env, 16 original C/A IDs and 14 existing tags. Disposable pytest assets allowed; no new tags. Record each claim’s source/runtime, evidence/disposition/checks/reason. Report marks are untrusted; no-change alone proves no false positive.

**Public API gate:** Explain examples/migration impact and obtain individual approval for incompatible changes. Approved bounded policies: BP-C3-001, BP-A8-001, BP-MD3-001, BP-A11-001, BP-A4-001, BP-MD7-001, BP-LC7-001, BP-SD3-001, BP-SD4-001, BP-SD5-001, BP-A6-001, BP-A7-001, BP-MD9-001, BP-A9-001, BP-A10-EMAIL-001, BP-A10-POSITIVE-001, BP-A10-DBERROR-001, BP-MF3-EXACTNULL-001, BP-MF2-DATEPART-001, BP-A12-AND-MANY-001, **BP-T12-CURSORERROR-001** (human17667, accepted17715; only decoded unconvertible Float/Decimal/UUID bounds), **BP-MF4-NULLPAGE-001** (human17733; only explicit `page:null` equals omission/first page; zero/negative unchanged), **BP-MH2-SYNC-ASYNC-001** (human18659: controlled HTTP500 GraphQL JSON/owned coroutine cleanup; no async support). Exact prior descriptions/approval IDs: `t12b-typed-cursor-errors-closure/tracker-preclosure.md`; accepted-slice rows below retain scope. All other incompatible policies gated. Strict TDD/docs/coverage >95%; no tags/publication.

**Quality:** Hint changed/public signatures; Google Args/Returns/Raises, no repeated types/backticks. Tests/docs/changelog with behavior. Pure branch, combined, nonempty patch coverage each >=95.01%; patch otherwise N/A. No exclusion/skip/padding/addopts reset. Check Ruff/format/mypy/docstrings/docs/focal/full/diff; report all failures/skips. No artifact build.

**Cross-surface impact:** Inspect affected test apps, Playground/examples, docs and benchmark declarations per behavior unit; update affected surfaces or record concrete no-change evidence. No benchmark timing/canonical rewrite/public API policy. Omitted affected surfaces need bounded correction before acceptance.

**Implementation route:** Delegated direct, not SDD; broad preparation or 2+ nontrivial files to bounded writer and independent verifier. Conventional work-unit behavior/tests/docs commits; ~400 authored lines advisory, no code-golf. Delivery `ask-on-risk`, chain unresolved; no PR authority.

## Task sequence

Unchecked needs evidence; `D` delegates; IDs persist. Prior wording/limits: `t13i-selected-introspection-classifier-implementation/tracker-pre-t13i.md` (SHA `5df41527bccd61ab2b5b36ccc19605162f10ba86d7a9b45c5d99ce31fc02e809`).

| Task | Route | Outcome and acceptance evidence | State |
|---|---|---|---|
| T00 | D, bootstrap | Record complete report traceability, local branch/runtime constraints and proof; mirror full file in Engram; tracking-only conventional commit. Structural readback only; runtime test N/A because no runtime/source behavior changed. | [x] |
| T01 | D | Supported graphql-core 3.3 baseline: verify module/distribution/candidate identities, focused baseline and full suite including environment-only benchmark provenance distinction; preserve exact failures without changing root env, benchmarks, or canonical results. Baseline established, full suite red on Q2; see T01 proof below. | [x] |
| T02a | D | **C3 accepted:** polynomial cycle precheck for direct cost and cost/depth paths; acyclic/error contracts retained. Proof below. | [x] |
| T02b | D | **C2 accepted:** `92b1358f`/`7bec9571`; bounded fragment work, last-write semantics, endpoint/SQL/alias unchanged. Initial PARTIAL/coverage/freeze qualified; final proof `t02b-recheck/README.md`. | [x] |
| T03a | D | **C1 accepted:** `dbabfde` preserves prior Float!/null propagation; RED→GREEN PK tests, related/full gates, independent/parent PASS after separate T16b fixture repair. A8/M-D3/M-D4 and defaults separate. Exact prior row in immutable T11b tracker. | [x] |
| T03b | D | **A8 accepted:** `8f86dc8`+`12a7506` add BigInt strings, preserve relation-ID/Enum; RED3→GREEN3, full/quality/independent/parent PASS. Exact prior row in immutable T11b tracker. | [x] |
| T03c | D | **M-D3 accepted:** `d278321`/`4cc048b`; exact Decimal output, inputs unchanged. Initial PARTIAL corrected; final full5031/7/3, pure95.060790%/combined97.378456%, patch N/A. `t03c-recheck/README.md`. | [x] |
| T03 | D | Reproduce C1/A8/Decimal cases; use compatible fix if proven adequate. For each necessary incompatible SDL candidate, explain examples and migration impact to the user and obtain its separate explicit approval before implementation; output/input regression tests and docs. | [ ] |
| T04 | D | A2 POST body order accepted T04a; A11 per-result output cap accepted T04b. Retained-cache bytes/memory claims still OPEN; no broader resource policy approved. Exact history in `t14e-lc12-implementation/tracker-prep-preimage.md`/T04 proof. | [ ] |
| T04a | D | **A2 body-order accepted:** `84369e4`; POST cap precedes cache parse, HTTP413/defaults retained. Final proof and interim failures in `t04a-independent/README.md`; retained-cache bytes open. Exact prior row in immutable T11b tracker. | [x] |
| T04b | D | **A11 accepted:** `441899a` source/`40f0f57` docs; 1M Unicode per-result cap, None opt-out. False chronology caveat and final parent proof `t04b-recheck/README.md`. Aggregate/cache-byte policy open; exact prior row in immutable T11b tracker. | [x] |
| T05 | D | A1 default-DB rollback accepted T05a; native ok:false, multi-DB and lost-update remain open/unapproved. Full qualifications in `t14e-lc12-implementation/tracker-prep-preimage.md`/T05a proof. | [ ] |
| T05a | D | **A1 default-DB rollback accepted:** `f91022e` source/`cc67be5` docs. Initial settings-table PARTIAL corrected; full5068/7/3, pure95.0732693%, combined97.3841555%, patch4/4 `t05a-recheck/README.md`. Native ok:false/multi-DB open; exact prior row in immutable T11b tracker. | [x] |
| T06 | D | A3/A4/M-D7/L-C7 independently accepted; M-S6 is a documented shortcut limitation. Other permission/schema claims remain open, including T07 scope investigations. `t06e-lc7-recheck/README.md`. | [ ] |
| T06a | D | **A3 accepted:** `edb82a3`/`a2f329d`; malformed selectors rejected; reverse/custom retained. Initial P1/P2 PARTIAL and final PASS in `t06a-{independent,recheck}/README.md`; full preimage retains chronology. | [x] |
| T06b-F1 | D | **A4 fixture isolation accepted:** `93edfdd`; scoped Registry, base pair1/23→23/23 and related44/44. `t06a-{selector-validation,recheck}/README.md`; full preimage. | [x] |
| T06a-F2 | D | **Base-only CostViewWiring isolation accepted:** `4643f9a`; seed4172946021 base136/1→candidate148/1, same-seed153 and F1pair23 PASS. No global reset/weakened assertion. `t06a-{independent,recheck}/README.md`. | [x] |
| T06b | D | **A4 accepted:** `65e99d3`/`ff4741e`; distinct public output/Registry collision fails, compatible paths retained. Initial fixture/P2 failures corrected; full5077/7/3, coverage/patch/parent PASS; `t06b-a4-recheck/README.md`. | [x] |
| T06c | D | **M-D7 accepted:** `34b37e6`/`0b267da`; incompatible enum rejected; reordered-equivalent correction. Initial independent PARTIAL; final full5101/7/3, coverage/patch/parent PASS; `t06c-md7-recheck/README.md`. | [x] |
| T06e | D | **L-C7 accepted:** `c3a35a7`/`da31d91`/`668de45`; RED7→GREEN7, final PASS. Initial Raises/freeze/semantic/protection caveats and absent optional multiselect remain in `t06e-lc7-{implementation,independent,doc-correction,recheck,parent-spot}/README.md`. | [x] |
| T07 | D | SD1–SD5 triaged; SD3/T07c, SD4/T07e and SD5/T07f independently accepted. SD1 reads, SD2 joins, unrelated child writes and unprobed O2O remain outside these approvals. Broader T07 stays open. | [ ] |
| T07c | D, accepted | SD3 destination-ID scope `a96ca17`/`6275b6e`/`dcdd25b`/`6a964b4`; initial V1–V4 PARTIAL/patch7/9/replay corrected, final PASS. `t14e-lc12-implementation/tracker-prep-preimage.md`/T07c proof. T07 OPEN. | [x] |
| T07d | D, read-only | SD4/SD5 native3.3 triage only, no policy approval: `t07d-sd4-sd5-triage/README.md` and parent spot. Two focal passes; setup/transcript-only failures retained; full/coverage/docs not rerun. Probe SHA and exact historical row in closure preimage. | [x] |
| T07e | D | **SD4 accepted:** `bb592d`/`8521c02`/`c39b434`; orphan adoption needs child UPDATE host; CREATE-ID unsupported. RED6→GREEN6, initial Raises PARTIAL corrected; final PASS, `t07e-sd4-{implementation,independent,doc-correction,recheck,parent-spot}/README.md`. | [x] |
| T07f | D | **SD5 accepted:** `f0b3126`/`0a4ba13`; pruned flat GFK target null, unpruned/typed unchanged. Initial guide P2 PARTIAL corrected; final PASS, `t07f-sd5-{implementation,independent,doc-correction,recheck,parent-spot}/README.md`. | [x] |
| T08 | D | Confirm/fix A5/A6 and subscription lifecycle, filters, events, and transport claims; real-user WS/SSE and failure-path tests. | [ ] |
| T08a | D, accepted16725 | A5 cold WS/SSE user pruning `ac72aa7`/`c9cb4f1`; independent base4 RED/candidate4 PASS. Immediate GREEN hash absent and writer caveats preserved in `t14e-lc12-implementation/tracker-prep-preimage.md`/T08a proof. T08 OPEN. | [x] |
| T08b | D, accepted | A6 automatic best-effort/manual strict (`901c35b`/`c3edeb3`); final PASS. Initial related/Playground/CLI/DOC005/patch32/35/four-Raises PARTIAL and immediate GREEN hash gap preserved in `t14e-lc12-implementation/tracker-prep-preimage.md`/T08b proof. | [x] |
| T09 | D | A7/M-D8/M-D9 accepted; other annotation/interface claims remain open. | [ ] |
| T09a | D | **A7 accepted16924:** per-input factories/alias, no fixed SDL value. Initial PARTIAL/harness/semantic failures; final PASS. `t09a-a7-{implementation,independent,alias-correction,recheck,parent-spot}/`. | [x] |
| T09b | D | **M-D8 accepted16997:** inherited hook corrected. Initial P1/P2, four RED/four harness, replay8, patch23/24, field-order/quality failures retained; final PASS. `t09b-md8-{implementation,independent,hook-correction,recheck}/`. | [x] |
| T09c | D | **M-D9 accepted17088:** interface/implementor explicit name only. Initial MATERIAL P1/P2, DOC002/refreeze/interrupted-full/parser99 harness retained; final PASS. `t09c-md9-{independent,recheck,parent-spot}/`. | [x] |
| T10 | D | A9/T10a and bounded A10/T10b–d accepted; wider A10 open. Residual triage is read-only; no general `full_clean()`/upsert policy approved. | [ ] |
| T10a | D, accepted17162 | A9 blocked delete GraphQL error `74146dd`/`54f68e5`; initial P2/order failures fixed T16c, final PASS. Limits in `t14e-lc12-implementation/tracker-prep-preimage.md`/T10a proof. | [x] |
| T10b | D, accepted17234 | EmailField-only choice-Enum correction `81f79492`/`6101629`; RED4→GREEN4, final PASS. Initial PARTIAL/harness/protected-asset caveats in `t14e-lc12-implementation/tracker-prep-preimage.md`/T10b proof. | [x] |
| T10c | D | **Positive two-field accepted17314; A10 open:** `6bd37b2`/`ebe32b0`/`fc3bccd0`; RED8→same GREEN8, final PASS. Initial P1/harness/patch/skipped-preflight and restored index-only qualification: `t13f-mh2-sync-async-rejection-implementation/tracker-before-evidence.md`. | [x] |
| T10d | D, accepted17370 | Generated unclassified IntegrityError redaction only; RED8→GREEN8, final PASS. Direct/handwritten errors unchanged; historical argv/diff-cover/docstring limits in `t14e-lc12-implementation/tracker-prep-preimage.md`/T10d proof. | [x] |
| T11 | D | A12/filter types/limits wider block open. T11a exact-null, T11b date-part, T11c A12 AND/to-many and T11d M-F1 compatible slices accepted; M-F3 empty-Boolean policy unchanged. | [ ] |
| T11a | D, accepted17430 | Exact SQL NULL `c4273e2`, omission/Boolean/subscriptions unchanged. Permanent first-RED/helper/PARTIAL and temporal equality unproven: `t14e-lc12-implementation/tracker-prep-preimage.md`/T11a proof. M-F3 OPEN. | [x] |
| T11b | D, accepted17503 | `53b3481` numeric Date/DateTime parts use Int; whole values unchanged. Author PG/mypy/T11a gaps in pre-T13i archive. T11 open. | [x] |
| T11c | D, accepted17607 | Human17513 bounded A12 `4c3e4bb`; RED/runner, DB-read/htmlcov violations permanent. Full checks/scope in pre-T13i archive; T11 open. | [x] |
| T11d | D, accepted17812 | M-F1 `954a2036` nested date parts/PK shadow; SDL/null/A12 unchanged. Helper/fsync and prior failures in pre-T13i archive. T11 open. | [x] |
| T12 | D | Confirm/fix A13 and pagination ordering/count/page boundary claims; backend-specific and in-memory regression tests. | [ ] |
| T12a | D, accepted17645 | A13 emitted Float/Decimal/UUID cursors only `e18f02b`/`5528767`; RED3→GREEN5/final PASS. Malformed TypeError unchanged. Full history: `t14e-lc12-implementation/tracker-prep-preimage.md`/T12a proof. | [x] |
| T12b | D, accepted17715 | `c3a063a`: invalid Float/Decimal/UUID cursor bounds become Invalid cursor; emitted/ORM/nested unchanged. PASS; v1 guard, aggregate, special-number/PG limits in `t12b-typed-cursor-errors-{implementation,independent}/README.md` and exact pre-T14a tracker. T12 open. | [x] |
| T12c | D, accepted17780 | `9ab95cb`: explicit `page:null` equals omitted first page, root/nested/materialized; SDL/zero/negative unchanged. PASS; checks, helper-copy and harness/quality caveats: `t12c-mf4-null-page-implementation/README.md` and exact pre-T14a tracker. T12 open. | [x] |
| T12d | D, accepted17944 | M-F7 DEFAULT_PAGE_SIZE100 omitted global LO/Page/Cursor only. Initial full24/independent PARTIAL and source/postimage gaps in `t14e-lc12-implementation/tracker-prep-preimage.md`/T12d proof. No M-F6/None-error/hot-reload policy. T12 OPEN. | [x] |
| T12g | D, accepted19564 | M-F7 docs only `0d4f3b7`+`da9c3c4`; full5521/7/9, patch N/A; original PARTIAL/setup retained in `t12g-mf7-none-pagination-docs-closure/README.md` and pre-T14c archive. T12 OPEN. | [x] |
| T12f | D, human18041; accepted18137 | M-F5 `f6e88d4`+`d1a6a18` model PK-ASC tie; unbounded/explicit PK unchanged. PARTIAL/patch gaps in pre-T13i archive. T12 open. | [x] |
| T12e | D, human17983; accepted18032 | M-F6 `c75ea72` negative-Page DB count errors; initial RED copies/fsync missing and doc/mirror corrected. Full proof/limits in pre-T13i archive. T12 open. | [x] |
| T13 | D | Confirm/fix HTTP/cache/error/introspection/limits and async-view claims, separating documented defaults from defects and optional hardening; each necessary incompatible public-default change needs its own explained user approval before implementation. | [ ] |
| T13a | D, human18167; accepted18241 | M-S1 `96e1f9e`+`bcd6686`; T13a shell-mirror 88107 effects UNPROVEN. Proof: `t13a-ms1-variable-cost-closure/README.md`. T13 open. | [x] |
| T13b | D, accepted18271 | M-S5 `d9d2c40`; scope/RED/input-copy limits: `t13b-ms5-get-cache-key-{implementation,independent,closure}/README.md`. T13 open. | [x] |
| T13c | D, human18294; accepted18361 | M-S4 DEBUG=False `a401f9e`+`407060e`; scope/failures/hashes: `t13c-ms4-http-error-diagnostics-closure/README.md`. T13 open. | [x] |
| T13d | D, human18441; accepted18531 | M-H3 `043811e` preserves 0/False (not null/empty); `cbfb9fb` fixes DOC002. Full recheck, original RED/prelaunch/runner and T13a limits: `t13d-mh3-clean-response-closure/README.md`. T13 open. | [x] |
| T13d-doc | D, accepted18531; `cbfb9fb` | Five DOC002s only; RED5→GREEN0, AST equal, patch N/A. Quality substep, not claim; full proof: `t13d-mh3-clean-response-closure/README.md`. | [x] |
| T13e | D, human18554; accepted18627 | M-H4 `69d326e` functional PASS; Ruff cache effects UNPROVEN, T13a unknown. `t13e-mh4-success-cache-closure/README.md`. T13 open. | [x] |
| T13f | D, human18659; accepted18829 | M-H2 JSON500/no async; owned cleanup/native falsey admission. Two PARTIALs/limits: `t13f-mh2-sync-async-rejection-closure/README.md`, pre-T13i archive. T13 open. | [x] |
| T13g | D, accepted18888 | M-S3 docs-only `11bd843`+`3a37b72`; no runtime/default/SDL/install change. Full proof/limits: `t13g-ms3-introspection-docs-closure/README.md`. T13 open. | [x] |
| T13h | D, accepted18998 | M-H1 `347b2ff` HTTP400 partial array/stop; no batch transaction. RED omitted `tests/models.py`; full proof/limits in `t13h-mh1-partial-batch-closure/README.md` and pre-T13i archive. T13 open. | [x] |
| T13i | D, accepted19287 | Fragment classifier `408e2aa`+`bbc8e9a`; PASS, patch44/44. Initial fsync/PARTIAL gaps retained in `t13i-selected-introspection-classifier-closure/README.md` and pre-T14c archive; T13 OPEN. | [x] |
| T14a | D, accepted19162 | `9fec11d`: two public constructor guards survive -O with exact predicates/messages/AssertionError. PASS/limits: `t14a-lc2-compatible-view-validation-closure/README.md`, pre-T13i archive. T14 open. | [x] |
| T14b | D, parent scope19589; accepted19665 | M-O1 `316844e`: RED21→GREEN2, full5523/7/9, pure95.336%/combined97.552%/patch95.45%; independent PASS. Compatible; proof/limits in `t14b-mo1-merged-root-implementation/README.md` and preclosure archive. | [x] |
| T14c | D, accepted19762 | M-O2 fixed, not false positive: BUILD/ENTRY split `961c018`, causal RED1→GREEN4, full5527/7/9, patch19/19, independent/parent PASS. Timing claim unverified and original oracle/refactor qualifications in `t14e-lc12-implementation/tracker-prep-preimage.md` and T14c proof READMEs. T14 OPEN. | [x] |
| T14d | D, accepted19885 | M-T1 confirmed fixed, not false positive: public causal and docstyle RED→GREEN, independent/parent PASS. All initial failures and seed1823552487 historical RED (current/base1586) retained in `t14e-lc12-implementation/tracker-prep-preimage.md` and `t14d-mt1-thread-local-fork-{implementation,independent,closure}/README.md`. No general Registry/async/PR claim. | [x] |
| T14e | D, human20029/parent20058; **implemented, independent pending** | **L-C12 valid union-wrapper GFK candidate** `c8bb0dd`: bounded inline/named wrapper descent in dedicated bucket collector, member-only and cycle/work guards; generic fragment policy, SDL/API/MTI unchanged. Public three-Order causal RED 5 SQL/3 Account SELECT vs 2/0 direct → same-byte GREEN 2/0 with equal data/join/.only; post-GREEN cycle/nonmember/malformed control PASS. First NameError setup is NOT RED. Full5537/7/9; raw branch4116/4316=95.366%, combined15407/15792=97.562%; nonempty production patch18/18=100%. Related131, focal2, Ruff/format/mypy81/docstrings, strict docs129/links42, Playground59, static benchmark5 PASS. Initial Ruff/patch94.44 failures corrected and retained, no retroactive PASS. All160 overlay and frozen inputs, finite named controls unchanged; README `t14e-lc12-implementation/README.md` SHA `80f2abdfbe9be7450b27647c9285aa586eae0f4dd0b1e329b9451e25365b5779`. Full prep intent/history `t14e-lc12-implementation/tracker-before-evidence.md` SHA `58d386e93dc9a95282c6de607641f67c2473be94110b4e67e69f30426571036a`. **Unchecked** until independent+parent acceptance; T14 OPEN, MTI unverified. | [ ] |
| T14 | D | Confirm/fix optimizer selection/concurrency/thread-safety and remaining low-level exception/memory claims where reproducible; bounded tests. | [ ] |
| T15 | D | Confirm/fix scalar, directive, and low-level output-contract claims not already covered; behavior-specific tests/docs. | [ ] |
| T16a | D | **Q2 accepted before core fixes:** select exactly eight canonical benchmark results despite unrelated ignored JSON; fixtures copy only those names. Missing/invalid canonical rejection, public CLI/output, assets and full-suite coverage preserved; source commit/checks below. | [x] |
| T16b | D, accepted | Fixture-only `ca6cfb7` allowlists User target in local Registry; relation assertions retained, isolated RED→GREEN. Production unchanged; `t14e-lc12-implementation/tracker-prep-preimage.md`/T16b proof. | [x] |
| T16c | D, accepted17162 | Reverse-O2O fixture isolation `4ec40e8`; A9 behavior unchanged. RED8/2→GREEN10, full5226/7/9, independent/parent PASS. Exact history: `t10a-a9-{order-triage,fixture-isolation,final-recheck,parent-spot}/README.md`, pre-T16e tracker. | [x] |
| T16d | D, accepted18385 | Two-suite test portability `3e3af998`; no production change. Full checks, 12 ASTs, qualifications: `t16d-test-runtime-portability-closure/README.md` and exact pre-T16e tracker. Datepart later T16e; GET-body/T16 open. | [x] |
| T16e | D, accepted19086 | Test-only `9c431f6`: proof asserts/imports removed, business AST retained. MODELED3.3.1 ≠ installed CI; full counts/limits: `t16e-datepart-test-portability-closure/README.md`, pre-T13i archive. T16 open. | [x] |
| T16f | D, accepted19403 | GET-body docs/test `0606b34`; RED1→GREEN1, parent PASS; runtime unchanged. Setup/count limits in `t16f-get-body-cache-key-docs-closure/README.md` and pre-T14c archive. T16 OPEN. | [x] |
| T16g | D, accepted20001 | Test-only cached default-pair fixture leak fixed in current tests by `3cefed7`: RED4→GREEN4, seed1823552487 pair/five order failures→PASS; independent/parent PASS, full5535/7/9, branch95.381%, combined97.571%, production patch N/A. Historical failures/selected-six-overlay PARTIAL remain. Exact all evidence/qualifications: `t14e-lc12-implementation/tracker-prep-preimage.md` (SHA `f1fca3988eb40c3e2ac6604c26abc9918aecec38106297f6ca6fe169d76ea40e`) and `t16g-registry-order-{implementation,independent,closure}/README.md`. No production/API/N6 closure. | [x] |
| T16 | D | Wider tooling, coverage, metadata, refactor and dead-code block OPEN; no benchmark regeneration. Q2=T16a, datepart=T16e, GET-body=T16f. Base-reproduced seed1823552487 test-fixture cached-pair leak is fixed in accepted T16g; not a new original audit ID and not N6 closure. | [ ] |
| T17 | D | Complete independent disposition of every ledger ID, verify section-9 negative claims, run full quality/coverage gates, list all final false positives with evidence and reasons, and report remaining design decisions or unavailable checks. | [ ] |

## Claim traceability ledger

The C1–C3/A1–A11 concise dispositions retain their exact full chronology, approvals, caveats and links in `t14d-mt1-thread-local-fork-implementation/tracker-preclosure.md` (SHA-256 `e028aca556b2b779174c2adafb7ce32caa43c847d3be13a954f2cbfb1beb46cf`). This archive is the immutable lossless preimage; the 100 claim IDs and order below remain current.

Status for **every** item below is `U` at bootstrap. The report's ✅/🔁/📖 labels are claims about its own methods, not acceptance evidence. Related rows are marked `↔` where they may share a root cause; they remain independently traceable. Exact line anchors prevent a later worker from silently dropping subclaims. `T17` closes every row, including duplicates and no-change decisions.

### Critical and high (original IDs preserved)

| ID | Report line | Distinct claim / dependency | Task |
|---|---:|---|---|
| C1 | 36–44 | Confirmed/accepted T03a: Decimal PK Float/null propagation restored; M-D3 precision and M-D4 scalar acceptance remain separate. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T03a/T03 |
| C2 | 46–58 | Confirmed/accepted T02b: ordered cached fragment effects restored after initial visit-only regression; duplicate FieldNode output unchanged. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T02b |
| C3 | 60–72 | Confirmed/fixed T02a: shared cycle precheck bounds cost/depth traversal; approved GraphQLError behavior. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T02a |
| A1 | 80 | T05a default-DB GraphQL-error rollback accepted; native ok:false sibling, multi-DB and lost-update remain open. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T05a/T05 |
| A2 | 81 | T04a POST body-order fix accepted; retained AST/cache bytes and aggregate memory claims remain unverified. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T04a/T04 |
| A3 | 82 | T06a invalid selectors fix accepted; reverse/custom fields retained; no unauthenticated bypass proven. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T06a/T06 |
| A4 | 83 | T06b distinct output collision guard accepted; same class, separate registries and internal forks retained. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T06b/T06 |
| A5 | 84 | T08a cold Django-user WS/SSE pruning fix accepted; fake-user probes did not prove universal failure. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T08a/T08 |
| A6 | 85 | T08b approved automatic best-effort notification accepted; manual broadcasts stay strict; no durability/retry claim. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T08b/T08 |
| A7 | 86 | T09a runtime factory handling accepted; no broader collision policy or unrelated validation claim. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T09a/T09 |
| A8 | 87 | T03b BigInteger string output accepted; relation-ID/choices-Enum behavior retained. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T03b/T03 |
| A9 | 88 | T10a generated delete-error redaction accepted; no general DB catch or ok:false policy. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T10a/T10 |
| A10 | 89 | T10b/c/d accepted for Email, two positive fields and generated DB redaction; broader validation remains open. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T10 |
| A11 | 90 | T04b approved per-result Unicode limit accepted; no total-response quota or global memory proof. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T04b/T04 |
| A12 | 91 | Public M2M SQLite triage: separate explicit AND tag-label x/y returned [], while chained ORM found parent; one tags object correctly required SAME tag. Source folded one Q/one filter; empty JOIN_SQL capture, reverse-FK not triaged. BP-A12-AND-MANY-001 approved17513 and accepted T11c/17607: separate branches may match independent related rows; one relation filter remains same-row. Other filtering/scoping unchanged. `t11-a12-and-many-triage/README.md`, `t11c-a12-and-many-{implementation,correction,recheck}/README.md`. | T11/T11c |
| A13 | 92 | Valid emitted Float/Decimal/UUID continuation accepted T12a/17645; decoded unconvertible bounds raise Invalid cursor under approved T12b/17715. Other cursor policies remain open. | T12 |

### Security design (§4)

| ID | Report line | Distinct claim / dependency | Task |
|---|---:|---|---|
| SD1 | 98–99 | Confirmed documented field-level boundary: root `get_queryset` scopes, auto FK/reverse-FK bypasses destination hook (native 19+2; `t07a-sd1-triage/README.md`, Engram16223). Not false positive/undisclosed bug; O2O/M2M unprobed; global policy unapproved. | T07 |
| SD2 | 100 | Confirmed documented ORM-join row oracle: filter matches hidden author with hook0; permission pruning/masking pass (48+2; `t07b-relation-input-scope-triage/README.md`, Engram16229). Not pruner bypass; M2M variants unprobed. | T07 |
| SD3 | 101 | **Confirmed documented design gap, independently fixed and accepted in T07c:** generated FK/M2M ID links formerly accepted hidden destination rows; `a96ca17` checks actual link operations (including nested IDs with ignored extras) against the request Registry destination hook and requested-ID membership before persistence, with hidden/missing structured error equivalence. Existing real child writes/SD1/SD2/O2O/SD4/SD5 remain outside approval. Original 48+2 triage `t07b-relation-input-scope-triage/README.md`, approval Engram16303, writer proof `t07c-sd3-implementation/README.md`; not a false positive. | T07c/T07 |
| SD4 | 102 | **Confirmed, BP-SD4-001/16504 accepted T07e.** Hostless existing nullable reverse-FK orphan ID adoption denied; scoped child UPDATE host required. New/already-owned child unchanged; CREATE existing-ID unsupported; missing-ID error not uniformly not-found. Historical P2/proofs: `t07e-sd4-independent/README.md`, `t07e-sd4-doc-correction/README.md`, `t07e-sd4-recheck/README.md`, `t07e-sd4-parent-spot/README.md`; triage `t07d-sd4-sd5-triage/README.md`. Not false positive. | T07/T07d/T07e |
| SD5 | 103 | **Confirmed metadata boundary, independently fixed and accepted in T07f (16674); not a false positive.** Source-view-only flat GFK formerly exposed target appLabel/modelName/id while target root was pruned; no secret field/target hook. Permission-pruned schema now nulls whole target on actual-target model-read or registered scope denial, retaining authorized metadata/SDL and unpruned/typed unions. Field/operation tags remain separate, not a global type ACL. Historical PARTIAL and final evidence: `t07d-sd4-sd5-triage/README.md`, `t07f-sd5-independent/README.md`, `t07f-sd5-recheck/README.md`, `t07f-sd5-parent-spot/README.md`. Other T07 scope gaps remain open. | T07/T07d/T07f |
| SD6 | 105 | Proposed strict_scope mode/system check is a **recommendation**, not proof that the current documented contract is defective; public semantics require user decision. | T07 |

### Medium: security/defaults and data correctness

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| M-S1 | 114 | **Accepted18241 (human18167):** variable150 cost151>120 formerly passed; no hard cap (memory/no DB). `96e1f9e`+`bcd6686` check selected real cost before resolvers; static rule retained. Refusal no cache bump; earlier executed batch/late write still invalidates. Wider T13 open. | T13/T13a |
| M-S2 | 115 | Default limit settings None (page size, depth, cost, body); unbounded `in` list; unbounded Boolean breadth/depth—three separately verifiable subcases. | T11/T13 |
| M-S3 | 116 | **Accepted T13g/18888, documented configuration error, not runtime-default bug:** False alone permits introspection; installed middleware blocks, True reopens. Docs/test only; triage `t13-introspection-cleaning-triage/README.md`; proof above. | T13/T13g |
| M-S4 | 117 | Synthetic DEBUG=False DatabaseError/ValueError exposure confirmed; approved M-S4 HTTP fix accepted T13c (18361). DEBUG=True/intentional GraphQLError/A9/A10 and wider T13 separate. `t13-ms4-error-details-triage/README.md`. | T13/T13c |
| M-S5 | 118 | **Accepted T13b:** same-identity GET component ambiguity fixed by default framing (`d9d2c40`, parent18271); hook/identity/scope/version unchanged, cold misses, no cross-identity claim. Wider T13 open. | T13/T13b |
| M-S6 | 119 | **Documented shortcut limitation, not silent bypass:** `Field`/`CharField`/`IntField(required_perms=...)` raise `TypeError`; lowercase `field(..., required_perms=...)` works (native3.3 scoped-view3 PASS). Untagged fields are documented public. Additive shortcut parity optional, not needed for this fix. `t06d-ms6-triage/README.md`, Engram16113. | T06 |
| M-D1 | 124 | Partial update allegedly saves whole row and causes lost concurrent update. | T05 |
| M-D2 | 125 | Nested atomic and binding on_commit allegedly omit database alias; two subcases. | T05/T08 |
| M-D3 | 126 | **Confirmed defect, independently accepted approved breaking output change:** prior auto Float rounded Decimal 9007199254740993.01 to 9007199254740994.0; source `d278321` now uses existing GdxDecimal for automatic output and returns the exact JSON string from the Django value. Comment correction `4cc048b`, independent recheck and parent spot pass. SQLite can separately round high-magnitude values on persisted reload; output cannot recover that. Input/filter/parser and M-D4 policy remain separate. Not a false positive. | T03c/T03 |
| M-D4 | 127 | **Partly verified, still open:** scalar accepts nonfinite values; actual public model mutations reject NaN, Infinity, -Infinity and 1e1000 with structured field errors and zero save calls, not an unhandled Django exception. Exact report exponent 1E+999999999 remains untested because bounded processing was not established; no whole-row false-positive verdict. | T03 |
| M-D5 | 128 | JSON scalar allegedly parses a JSON-looking string into a different JSON type. | T15 |
| M-D6 | 129 | JSONRaw allegedly preserves Undefined in lists and accepts infinity-producing exponent; two subcases. | T15 |
| M-D7 | 130 | **Confirmed defect; approved fix independently accepted:** `shop.Order.line_status` and `shop_order.Line.status` normalized to one enum name and silently shared incompatible choices. `34b37e6` now rejects incompatible effective definitions with enum name+origins; `0b267dab` corrects the initial false rejection of equivalent reordered choices. Existing names/order, Registry isolation and compatible reuse remain; no override, eager scan or L-C7 policy. Initial independent PARTIAL is historical; final `t06c-md7-recheck/README.md` PASS plus parent spot. Engram16025/16098. | T06c/T06 |
| M-D8 | 131 | **Confirmed compatible fix, independently and parent accepted (16997); not a whole-row false positive.** Three reserved names previously failed construction; warning-only names persisted. Inherited hook omissions caused initial PARTIAL, then corrected with original ORM/GraphQL names and base immutability; full qualifications and proof in T09b. | T09b/T09 |
| M-D9 | 132 | **Confirmed fixed and accepted (17088) under approved BP-MD9-001/17010.** Interface/implementor `name=` honored; ordinary non-interface naming extension NOT approved. Initial MATERIAL P1/P2 PARTIAL, corrected; `t09c-md9-{independent,recheck,parent-spot}/` (parent spot JSON only). Native triage `t09-md9-triage/README.md`/16966 initial two harness errors not evidence. | T09c/T09 |
| M-D10 | 133 | **Partly confirmed/open:** native Literal/dict/set/Union inputs silently String!, Optional/list controls work (`t09-md10-triage/README.md`/17017). Full conversion undocumented; warning-only SDL-preserving candidate not implemented; no Enum/JSON/input-union policy. | T09 |

### Medium: filters, HTTP, optimizer, subscriptions, thread safety

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| M-F1 | 138 | **Confirmed, bounded compatible T11d fixed and accepted 17812:** nested related year/month/day/range/exact work while direct relation PK exact/in/range select PK despite shadow fields. SDL/input and A12/null/Boolean/date-part policies unchanged. Original TDD bytegraph qualified; see T11d proof. Wider T11 open. | T11/T11d |
| M-F2 | 139 | One-list SQLite triage: DateField parts typed Date, DateTimeField numeric parts DateTime; integer literal/variable HTTP400, ISO exact PASS. BP-MF2-DATEPART-001/17431, human17458, accepted bounded T11b/17503; 4/7 existing numeric part inputs now Int. Client part variables migrate to Int; whole-value Date/DateTime and wider T11/TimeField policies remain unchanged/open. TimeField/other transforms/custom lookup names unapproved; failed setup/metadata retained in `t11-mf2-datepart-filter-triage/README.md`. | T11/T11b |
| M-F3 | 140 | Triage `t11-mf3-boolean-filter-triage/README.md`: exact:null all3 vs isnull:true NULLrow1. Exact-null/omission slice accepted T11a/17430; wider Boolean identities remain open. Existing or:[]/not:{} no-op and or:[{},X]→X unchanged, not a new Boolean fix. | T11/T11a |
| M-F4 | 141 | Confirmed root HTTP200 raw TypeError for explicit page:null; omission page 1; SDL `page: Int = 1`. Human17733 approved exact null==omission, zero/negative unchanged. T12c `9ab95cb` independently accepted17780 across root/nested prefetch/materialized HTTP paths. Prior root-only triage `t12-mf4-null-page-triage/README.md` inferred nested failure; implementation HTTP RED4 proved it. No wider page policy. | T12/T12c |
| M-F5 | 142 | Confirmed missing tie-break for nonunique order; actual skips/duplicates not observed. Human18041 bounded model-backed LO/Page DB/window/list PK ASC accepted T12f/18137 after reverse/extra-order correction and independent/parent PASS. Concurrent offset shifts/random ordering unaffected; unbounded/no-order LO retains QS/cache. | T12/T12f |
| M-F6 | 143 | Count `DatabaseError` fallback did materialize the full queryset; human17983 bounded negative-page generic error/no-fetch fix accepted18032. Ordinary lazy `totalCount` and other policies unchanged; not a universal real-DB-failure claim. | T12/T12e |
| M-F7 | 144 | T12d accepted17944 shipped DEFAULT_PAGE_SIZE100 for omissions; explicit None legacy unchanged. T12g accepted19564 **docs/test clarification**, not runtime fix: effective all-None LO all, Page null, Cursor20; constructor omission inherits configured startup setting. Earlier17808 GraphQLError proposal unapproved/unnecessary. Wider T12 open; full proof/limits in T12g closure and exact preclosure archive. | T12/T12d/T12g |
| M-H1 | 149 | **Accepted18998, qualified:** T13h valid-batch HTTP400 prior+error array/stop; prior writes persist. No batch transaction/other-status change; ATOMIC_REQUESTS untested. Historical RED transitive-input gap retained. `t13h-mh1-partial-batch-closure/README.md`. T13 open. | T05/T13/T13h |
| M-H2 | 150 | **Accepted18829 (human18659):** T13f JSON500/no async, bounded owned coroutine cleanup and native falsey middleware admission. Independent/parent PASS; no arbitrary hidden-graph or general async guarantee. `t13f-mh2-sync-async-rejection-closure/README.md`. T13 OPEN. | T13/T13f |
| M-H3 | 151 | **Accepted18531, human18441:** 0/False preserved; null/empty cleanup, selected direct introspection and CLEAN_RESPONSE=False unchanged. `043811e`+`cbfb9fb`, current PASS with history in `t13d-mh3-clean-response-closure/README.md`; wider T13 OPEN; separate T13i fragment follow-up accepted19287 with historical proof qualifications, not part of the zero/False policy. | T13/T13d |
| M-H4 | 152 | **Accepted18627 (human18554):** success-only response cache/T13e; functional PASS, finite safety PARTIAL. Ruff cache caveat, scope and old row: `t13e-mh4-success-cache-closure/README.md`. T13 OPEN. | T13/T13e |
| M-O1 | 157 | **Accepted19665, not false positive:** T14b `316844e` real five-row merged-node RED21 vs combined2, GREEN2; report's 16-vs-1 unverified. Broader T14 open. | T14/T14b |
| M-O2 | 158 | **Accepted T14c/19762, not false positive:** global RLock blocked warm hits during cold prune; `961c018` separates locks without parallel cold builds or public behavior change. Timing 0.9s unverified; T14 open. | T14/T14c |
| M-U1 | 163 | complete/disconnect during start allegedly leaves ghost subscription. | T08 |
| M-U2 | 164 | id_only delete allegedly drops events with scope or non-PK filters. | T08 |
| M-U3 | 165 | In-memory subscription filter string coercion allegedly fails Decimal/DateTime/Float. | T08 |
| M-U4 | 166 | m2m_changed and bulk/update paths allegedly emit no events; determine documented contract separately. | T08 |
| M-U5 | 167 | Directive wrapping async resolver allegedly stringifies coroutine. | T15 |
| M-U6 | 168 | @date null/localtime/date-only; camel/snake/kebab conversion; @number/@currency null-to-zero—seven distinct behavior families. | T15 |
| M-T1 | 173 | **Confirmed/fixed T14d:** process-global fork depth suppressed another thread's projected output/list entries; thread-local depth plus safe fork exit restores declared only/exclude projection. Parent accepted19885; no general Registry concurrency claim. Separate seed1823552487 registry-identity order failure remains open with unknown cause. | T14d/T14 |

### Low (§6)

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| L-C1 | 180 | Malformed ID in get_node/retrieve/DjangoObjectField allegedly raises raw error instead of null; three entry points. | T15 |
| L-C2 | 181 | **Bounded T14a/19162 accepted:** two public constructor guards now explicit under `-O`; exact AssertionError, predicates/messages/order and healthy views retained. Other asserts, whole L-C2 and T14 remain open. Optional ImproperlyConfigured19042 **UNAPPROVED** and unnecessary. Proof: `t14a-lc2-compatible-view-validation-closure/README.md`. | T14/T14a |
| L-C3 | 182 | GraphQLView/BaseGraphQLView status and data:null response contracts diverge. | T13 |
| L-C4 | 183 | Multipart files allegedly bypass MAX_UPLOAD_SIZE. | T13 |
| L-C5 | 184 | LIMIT_MINIMUMS allegedly skips three named settings. | T13 |
| L-C6 | 185 | ensure_csrf_cookie allegedly prevents browser cache reuse after first request. | T13 |
| L-C7 | 186 | **Confirmed compatibility limitation; independently fixed and accepted:** duplicate labels formerly bound `ALPHA`/`ALPHA_1` by order; `c3a35a7` rejects ambiguous generated members with `ImproperlyConfigured`, without changing unique member or enum type names. Existing ambiguous choices must generate distinct names (e.g. distinct fallback labels). `da31d91` corrected the source Raises contract; initial independent PARTIAL and harness failures remain historical. Final `t06e-lc7-recheck/README.md` PASS plus parent spot; optional multiselectfield absent/not tested. Separate from M-D7 type-name rule. Engram16124/16147/16210. | T06e/T06 |
| L-C8 | 187 | page:-1 allegedly not last actual page. | T12 |
| L-C9 | 188 | Null ordering allegedly differs between DB and memory cursor. | T12 |
| L-C10 | 189 | Directives declared on fragment spreads/inline fragments allegedly ignored. | T15 |
| L-C11 | 190 | @truncate, @title and @floor allegedly mishandle infinity; independently check each. | T15 |
| L-C12 | 191 | Confirmed valid union-wrapper GFK N+1; local compatible T14e candidate `c8bb0dd` restores direct-member 2 SQL/0 per-row Account SELECT with equal data, independent acceptance pending. Original controlled 5/3 and noncausal uncontrolled4/5/5 preserved in T14e archive; MTI parent-fragment claim unproven/GraphQL-invalid absent explicit interface/union. | T14/T14e |
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

**Recovery:** Exact pre-T14e tracker `t14e-lc12-implementation/tracker-prep-preimage.md` (SHA `f1fca3988eb40c3e2ac6604c26abc9918aecec38106297f6ca6fe169d76ea40e`) and exact pre-evidence tracker `t14e-lc12-implementation/tracker-before-evidence.md` (SHA `58d386e93dc9a95282c6de607641f67c2473be94110b4e67e69f30426571036a`) losslessly preserve all earlier rows/history/qualifications/approvals/pointers. T16g closure preimage remains at `t16g-registry-order-closure/tracker-preclosure.md`.

**Next:** 61 checked (60 remediation+1 quality); 15 principal blocks OPEN. T14e local candidate `c8bb0dd` passes bounded TDD, full/coverage/patch/docs/quality/Playground/static checks but remains UNCHECKED pending fresh independent verification and parent acceptance. MTI claim remains unverified/out of scope. Initial failed setup/Ruff/patch and historical T16g/M-T1/base failures/partial provenance stay recorded, never retroactively green. T14/T16/N6 and whole audit OPEN; no PR authority.

**Mirror:** Full tracker plus locator at `odd/audit-400-remediation/tasks` (obs15165).
