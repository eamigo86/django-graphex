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

**Public API gate:** Explain examples/migration impact and obtain individual approval for incompatible changes. Approved bounded policies: BP-C3-001, BP-A8-001, BP-MD3-001, BP-A11-001, BP-A4-001, BP-MD7-001, BP-LC7-001, BP-SD3-001, BP-SD4-001, BP-SD5-001, BP-A6-001, BP-A7-001, BP-MD9-001, BP-A9-001, BP-A10-EMAIL-001, BP-A10-POSITIVE-001, BP-A10-DBERROR-001, BP-MF3-EXACTNULL-001, BP-MF2-DATEPART-001, BP-A12-AND-MANY-001, **BP-T12-CURSORERROR-001** (human17667, accepted17715; only decoded unconvertible Float/Decimal/UUID bounds), **BP-MF4-NULLPAGE-001** (human17733; only explicit `page:null` equals omission/first page; zero/negative unchanged), **BP-MH2-SYNC-ASYNC-001** (human18659: controlled HTTP500 GraphQL JSON/owned coroutine cleanup; no async support). Exact prior descriptions/approval IDs: `t12b-typed-cursor-errors-closure/tracker-preclosure.md`; accepted-slice rows below retain scope. **BP-LE1-METADATA-001** (human20198/parent20226): two enumerators abort; two existing unwrap reraises retain original cause/class/message, healthy behavior unchanged. **BP-LE2-SOURCE-PROPERTY-001** (human20321): explicit source= Python @property internal AttributeError becomes GraphQL error with original exception; legitimate absence/null, nullable O2O, non-source and unrelated descriptors unchanged. Other incompatibilities gated. Strict TDD/docs/coverage >95%; no tags/publication.

**Quality:** Hint changed/public signatures; Google Args/Returns/Raises, no repeated types/backticks. Tests/docs/changelog with behavior. Pure branch, combined, nonempty patch coverage each >=95.01%; patch otherwise N/A. No exclusion/skip/padding/addopts reset. Check Ruff/format/mypy/docstrings/docs/focal/full/diff; report all failures/skips. No artifact build.

**Cross-surface impact:** Inspect affected test apps, Playground/examples, docs and benchmark declarations per behavior unit; update affected surfaces or record concrete no-change evidence. No benchmark timing/canonical rewrite/public API policy. Omitted affected surfaces need bounded correction before acceptance.

**Implementation route:** Delegated direct, not SDD; broad preparation or 2+ nontrivial files to bounded writer and independent verifier. Conventional work-unit behavior/tests/docs commits; ~400 authored lines advisory, no code-golf. Delivery `ask-on-risk`, chain unresolved; no PR authority.

## Task sequence

Unchecked needs evidence; `D` delegates; IDs persist. Prior wording/limits: `t13i-selected-introspection-classifier-implementation/tracker-pre-t13i.md` (SHA `5df41527bccd61ab2b5b36ccc19605162f10ba86d7a9b45c5d99ce31fc02e809`). All pre-T14h wording, proof chronology and qualifications are preserved byte-for-byte at `lm3-enum-cache-triage/tracker-prep-preimage.md` (49,745 bytes; SHA256 `ed104091d7cc73c396abd49e0bc19febbff359361c93bcaac6fc3bb8bac069d0`); shortened completed rows below are locators, not revised acceptance claims.

| Task | Route | Outcome and acceptance evidence | State |
|---|---|---|---|
| T00 | D, bootstrap | Record complete report traceability, local branch/runtime constraints and proof; mirror full file in Engram; tracking-only conventional commit. Structural readback only; runtime test N/A because no runtime/source behavior changed. | [x] |
| T01 | D | Supported 3.3 baseline accepted; Q2 full-suite failure retained in exact preimage. | [x] |
| T02a | D | **C3 accepted:** polynomial cycle precheck for direct cost and cost/depth paths; acyclic/error contracts retained. Proof below. | [x] |
| T02b | D | **C2 accepted:** `92b1358f`/`7bec9571`; bounded fragment work, last-write semantics, endpoint/SQL/alias unchanged. Initial PARTIAL/coverage/freeze qualified; final proof `t02b-recheck/README.md`. | [x] |
| T03a | D | C1 accepted dbabfde; Float!/null retained; proof/limits in exact preimage. | [x] |
| T03b | D | A8 accepted 8f86dc8/12a7506; BigInt strings, relation-ID/Enum retained; exact preimage. | [x] |
| T03c | D | M-D3 accepted d278321/4cc048b; Decimal output only; exact preimage. | [x] |
| T03 | D | Reproduce C1/A8/Decimal cases; use compatible fix if proven adequate. For each necessary incompatible SDL candidate, explain examples and migration impact to the user and obtain its separate explicit approval before implementation; output/input regression tests and docs. | [ ] |
| T04 | D | A2 POST body order accepted T04a; A11 per-result output cap accepted T04b. Retained-cache bytes/memory claims still OPEN; no broader resource policy approved. Exact history in `t14e-lc12-implementation/tracker-prep-preimage.md`/T04 proof. | [ ] |
| T04a | D | A2 accepted 84369e4; POST cap before cache parse; retained-cache bytes open; exact preimage. | [x] |
| T04b | D | A11 accepted 441899a/40f0f57; per-result cap, None opt-out; aggregate policy open; exact preimage. | [x] |
| T05 | D | A1 default-DB rollback accepted T05a; native ok:false, multi-DB and lost-update remain open/unapproved. Full qualifications in `t14e-lc12-implementation/tracker-prep-preimage.md`/T05a proof. | [ ] |
| T05a | D | A1 default-DB rollback accepted f91022e/cc67be5; wider A1 open; exact preimage. | [x] |
| T06 | D | A3/A4/M-D7/L-C7 independently accepted; M-S6 is a documented shortcut limitation. Other permission/schema claims remain open, including T07 scope investigations. `t06e-lc7-recheck/README.md`. | [ ] |
| T06a | D | A3 accepted edb82a3/a2f329d; malformed selectors rejected; exact preimage. | [x] |
| T06b-F1 | D | A4 fixture isolation accepted 93edfdd; exact preimage. | [x] |
| T06a-F2 | D | Base-only CostViewWiring isolation accepted 4643f9a; exact preimage. | [x] |
| T06b | D | A4 accepted 65e99d3/ff4741e; distinct public output collision rejected; exact preimage. | [x] |
| T06c | D | M-D7 accepted 34b37e6/0b267da; incompatible choices enum rejected; exact preimage. | [x] |
| T06e | D | L-C7 accepted c3a35a7/da31d91/668de45; ambiguous members rejected; exact preimage. | [x] |
| T07 | D | SD1–SD5 triaged; SD3/T07c, SD4/T07e and SD5/T07f independently accepted. SD1 reads, SD2 joins, unrelated child writes and unprobed O2O remain outside these approvals. Broader T07 stays open. | [ ] |
| T07c | D, accepted | SD3 destination-ID scope accepted a96ca17/6275b6e/dcdd25b/6a964b4; exact preimage. | [x] |
| T07d | D, read-only | SD4/SD5 native3.3 triage only, no policy approval: `t07d-sd4-sd5-triage/README.md` and parent spot. Two focal passes; setup/transcript-only failures retained; full/coverage/docs not rerun. Probe SHA and exact historical row in closure preimage. | [x] |
| T07e | D | SD4 accepted bb592d/8521c02/c39b434; orphan adoption needs child UPDATE host; exact preimage. | [x] |
| T07f | D | SD5 accepted f0b3126/0a4ba13; pruned flat GFK target null; exact preimage. | [x] |
| T08 | D | Confirm/fix A5/A6 and subscription lifecycle, filters, events, and transport claims; real-user WS/SSE and failure-path tests. | [ ] |
| T08a | D, accepted16725 | A5 cold WS/SSE pruning `ac72aa7`/`c9cb4f1`; independent base4 RED/candidate4 PASS, immediate GREEN hash absent. Writer caveats in exact pre-T08c archive/T08a proof; T08 OPEN. | [x] |
| T08b | D, accepted | A6 automatic best-effort/manual strict (`901c35b`/`c3edeb3`) PASS. Initial PARTIAL and GREEN-hash gap in exact pre-T08c archive/T08b proof; T08 OPEN. | [x] |
| T08c | D; human20540/root20555–20556; accepted20619 | L-E4 bounded diagnostic only: `DeliveryIterator.aclose` suppressed `RuntimeError` now emits neutral warning+`exc_info` without propagation/retry/frame/cancellation change. Real WS RED→same GREEN, independent/parent PASS; full5557/7/9, pure4129/4328, combined15451/15834, patch3/3. Initial proof/helper/regex limits remain in exact pre-T14g archive and `t08c-le4-{implementation,independent,closure}/README.md`; T08/N6 OPEN. | [x] |
| T09 | D | A7/M-D8/M-D9 accepted; other annotation/interface claims remain open. | [ ] |
| T09a | D | A7 accepted16924; per-input factories/alias; exact preimage. | [x] |
| T09b | D | M-D8 accepted16997; inherited hook corrected; exact preimage. | [x] |
| T09c | D | M-D9 accepted17088; explicit interface/implementor names only; exact preimage. | [x] |
| T10 | D | A9/T10a and bounded A10/T10b–d accepted; wider A10 open. Residual triage is read-only; no general `full_clean()`/upsert policy approved. | [ ] |
| T10a | D, accepted17162 | A9 accepted17162; blocked delete GraphQL error; exact preimage. | [x] |
| T10b | D, accepted17234 | EmailField-only Enum correction accepted17234; exact preimage. | [x] |
| T10c | D | **Positive two-field accepted17314; A10 open:** `6bd37b2`/`ebe32b0`/`fc3bccd0`; RED8→same GREEN8, final PASS. Initial P1/harness/patch/skipped-preflight and restored index-only qualification: `t13f-mh2-sync-async-rejection-implementation/tracker-before-evidence.md`. | [x] |
| T10d | D, accepted17370 | Unclassified generated IntegrityError redaction accepted17370; exact preimage. | [x] |
| T11 | D | A12/filter types/limits wider block open. T11a exact-null, T11b date-part, T11c A12 AND/to-many and T11d M-F1 compatible slices accepted; M-F3 empty-Boolean policy unchanged. | [ ] |
| T11a | D, accepted17430 | Exact SQL NULL `c4273e2`, omission/Boolean/subscriptions unchanged. Permanent first-RED/helper/PARTIAL and temporal equality unproven: `t14e-lc12-implementation/tracker-prep-preimage.md`/T11a proof. M-F3 OPEN. | [x] |
| T11b | D, accepted17503 | `53b3481` numeric Date/DateTime parts use Int; whole values unchanged. Author PG/mypy/T11a gaps in pre-T13i archive. T11 open. | [x] |
| T11c | D, accepted17607 | Human17513 bounded A12 `4c3e4bb`; RED/runner, DB-read/htmlcov violations permanent. Full checks/scope in pre-T13i archive; T11 open. | [x] |
| T11d | D, accepted17812 | M-F1 `954a2036` nested date parts/PK shadow; SDL/null/A12 unchanged. Helper/fsync and prior failures in pre-T13i archive. T11 open. | [x] |
| T12 | D | Confirm/fix A13 and pagination ordering/count/page boundary claims; backend-specific and in-memory regression tests. | [ ] |
| T12a | D, accepted17645 | A13 emitted typed cursor accepted17645; other malformed TypeError cases unchanged; exact preimage. | [x] |
| T12b | D, accepted17715 | Invalid typed cursor bound error accepted17715; broader pagination open; exact preimage. | [x] |
| T12c | D, accepted17780 | Explicit page:null equals omission accepted17780; other page behavior unchanged; exact preimage. | [x] |
| T12d | D, accepted17944 | M-F7 omitted-page default accepted17944; explicit None/hot reload not changed; exact preimage. | [x] |
| T12g | D, accepted19564 | M-F7 docs-only accepted19564; runtime unchanged; exact preimage. | [x] |
| T12f | D, human18041; accepted18137 | M-F5 `f6e88d4`+`d1a6a18` model PK-ASC tie; unbounded/explicit PK unchanged. PARTIAL/patch gaps in pre-T13i archive. T12 open. | [x] |
| T12e | D, human17983; accepted18032 | M-F6 `c75ea72` negative-Page DB count errors; initial RED copies/fsync missing and doc/mirror corrected. Full proof/limits in pre-T13i archive. T12 open. | [x] |
| T13 | D | Confirm/fix HTTP/cache/error/introspection/limits and async-view claims, separating documented defaults from defects and optional hardening; each necessary incompatible public-default change needs its own explained user approval before implementation. | [ ] |
| T13a | D, human18167; accepted18241 | M-S1 `96e1f9e`+`bcd6686`; T13a shell-mirror 88107 effects UNPROVEN. Proof: `t13a-ms1-variable-cost-closure/README.md`. T13 open. | [x] |
| T13b | D, accepted18271 | M-S5 accepted18271; exact scope and limitations in preimage. | [x] |
| T13c | D, human18294; accepted18361 | M-S4 DEBUG=False accepted18361; exact scope and limitations in preimage. | [x] |
| T13d | D, human18441; accepted18531 | M-H3 `043811e` preserves 0/False (not null/empty); `cbfb9fb` DOC002. RED/prelaunch/T13a limits in exact pre-T08c archive/T13d proof; T13 OPEN. | [x] |
| T13d-doc | D, accepted18531; `cbfb9fb` | Five DOC002s only; RED5→GREEN0, AST equal, patch N/A. Quality substep, not claim; full proof: `t13d-mh3-clean-response-closure/README.md`. | [x] |
| T13e | D, human18554; accepted18627 | M-H4 `69d326e` functional PASS; Ruff cache effects UNPROVEN, T13a unknown. `t13e-mh4-success-cache-closure/README.md`. T13 open. | [x] |
| T13f | D, human18659; accepted18829 | M-H2 JSON500/no async; owned cleanup/native falsey admission. Two PARTIALs/limits: `t13f-mh2-sync-async-rejection-closure/README.md`, pre-T13i archive. T13 open. | [x] |
| T13g | D, accepted18888 | M-S3 docs-only accepted18888; no runtime/default/SDL change; exact preimage. | [x] |
| T13h | D, accepted18998 | M-H1 `347b2ff` HTTP400 partial array/stop, not batch transaction. RED omitted `tests/models.py`; limits in exact pre-T08c archive/T13h proof; T13 OPEN. | [x] |
| T13i | D, accepted19287 | Selected introspection classifier accepted19287; prior fsync/PARTIAL limits in preimage. | [x] |
| T14a | D, accepted19162 | `9fec11d`: two public constructor guards survive -O with exact predicates/messages/AssertionError. PASS/limits: `t14a-lc2-compatible-view-validation-closure/README.md`, pre-T13i archive. T14 open. | [x] |
| T14b | D, parent scope19589; accepted19665 | M-O1 `316844e`: RED21→GREEN2, full5523/7/9, pure95.336%/combined97.552%/patch95.45%; independent PASS. Compatible; proof/limits in `t14b-mo1-merged-root-implementation/README.md` and preclosure archive. | [x] |
| T14c | D, accepted19762 | M-O2 warm-hit lock split 961c018, causal RED→GREEN, independent/parent PASS; 0.9s timing unverified. Full qualifications/proofs in exact pre-T15a archive and T14c READMEs; T14 OPEN. | [x] |
| T14d | D, accepted19885 | M-T1 global fork-depth fixed, public RED→GREEN/independent PASS; no general Registry/async claim. Failed-seed history in exact pre-T08c archive/T14d proofs; T14 OPEN. | [x] |
| T14e | D, accepted20126 | L-C12 GFK union-wrapper N+1 fixed `c8bb0dd`; direct-member already worked, MTI unproven. Independent PASS; counts/limits in exact pre-T08c archive/T14e proofs; T14/N6 OPEN. | [x] |
| T14f | D, accepted20271; human20198 | L-E1 metadata fail-fast `0c5e320` preserves model/cause; RED→GREEN/independent PASS. No healthy/converter claim; failures in exact pre-T08c archive/T14f proofs; T14/N6 OPEN. | [x] |
| T14g | D; human20732/root20769; accepted20835 | **Bounded L-M2 internal identity/lifetime fix** `a2ff209`: weak-valued live GraphQLField tracking, actual-instance `is` gate, four registration/collector paths. Deterministic dead-marker RED→same GREEN6; independent safe attempt/parent spot PASS (full5563/7skip/9warn; pure4129/4328; combined15451/15834; patch8/8; docs/quality/Playground59/static5). **Verifier incident persists:** unsafe Markdown shell quoting launched uncontrolled pytest; PIDs8478/8487 terminated/absent, no result credited; original session ID/full child output unavailable. Audit found 743 tracked bytes/modes, logical index, refs and finite controls unchanged, but ignored reports/cache, temp, installed environment, physical index and unlisted effects UNKNOWN; later safe PASS does not erase this. Writer setup/formatter/docstring/wrong-PURE/seed history retained in exact `t14g-lm2-closure/tracker-preclosure.md`; independent `t14g-lm2-independent/{incident-audit.json,safe-attempt-01/VERIFICATION.md}`. No public-exposure, Graphene, SDL/API, concurrency or global-reclamation claim; T14/N6/audit OPEN. | [x] |
| T14h | D; human20843; implementation pending acceptance | **L-M3 bounded fix implemented:** compiler RLock serializes cache get/create and full reset-to-schema lifecycle; per-Registry RLock serializes native choices comparison, construction, origin and registration. Historical registry-shaped adapters retain serial behavior without a new concurrency guarantee. Six deterministic tests: old-code RED 5 causal failures/1 control pass, same-test-byte GREEN 6 passes; plugin seeds differed, later one pinned-seed focal 6 passes. First full run had two real adapter failures and two proof-runner COVERAGE_FILE isolation failures; both corrected, not credited as PASS. Final precommit normal suite 5,569 passed/7 skipped/9 warnings; pure branches 4,127/4,326=95.3999%, combined 97.58%, nonempty actual production patch 61/61=100%. Ruff/format, mypy 81, changed-source/test docstrings, strict 129-input docs build and 42-page/13,078-link check, Playground 59, static 5-operation benchmark contract passed. Proof under `t14h-lm3-implementation/`; prior triage and exact pre-T14h archive retained. Names/member order/values/serial SDL and M-D7/L-C7 errors unchanged. No DjangoGraphQLSchema public exposure, general registry thread-safety, timing or remote claim. Above ~400 authored lines is the coherent code+six tests+docs, not a size exception. Unchecked until independent/root acceptance; no tag, publish or PR. | [ ] |
| T14 | D | Confirm/fix optimizer selection/concurrency/thread-safety and remaining low-level exception/memory claims where reproducible; bounded tests. | [ ] |
| T15 | D | Confirm/fix scalar, directive, and low-level output-contract claims not already covered; behavior-specific tests/docs. | [ ] |
| T15a | D; human20321; accepted20475 | Bounded L-E2 explicit `source=` Python `@property` fix `7fb4c12`, including partial/lru and original exception; legitimate null/dynamic/O2O/HTTP/required retained. Independent/parent PASS; initial failures and exact counts in pre-T14g archive/T15a proofs. No native/C/cached/generic/default-resolver claim; T15/N6 OPEN. | [x] |
| T16a | D | Q2 accepted: select/copy only eight canonical benchmark results; reject missing/invalid, public CLI/assets/full-suite preserved. Details in exact pre-T08c archive/T16a proof. | [x] |
| T16b | D, accepted | Fixture-only `ca6cfb7` allowlists User target in local Registry; relation assertions retained, isolated RED→GREEN. Production unchanged; `t14e-lc12-implementation/tracker-prep-preimage.md`/T16b proof. | [x] |
| T16c | D, accepted17162 | Reverse-O2O fixture `4ec40e8`; A9 unchanged, RED→GREEN/independent PASS. Counts/history in exact pre-T08c archive/T16c proof. | [x] |
| T16d | D, accepted18385 | Test portability `3e3af998`, production unchanged; 12 ASTs/limits in exact pre-T08c archive/T16d proof. T16 OPEN. | [x] |
| T16e | D, accepted19086 | Test-only `9c431f6`; modeled3.3.1 ≠ installed CI. AST/limits in exact pre-T08c archive/T16e proof; T16 OPEN. | [x] |
| T16f | D, accepted19403 | GET-body docs/test `0606b34`, RED→GREEN/parent PASS, runtime unchanged. Limits in exact pre-T08c archive/T16f proof; T16 OPEN. | [x] |
| T16g | D, accepted20001 | Test-only default-pair leak/seed1823552487 fixed; independent PASS. Historical PARTIAL in exact pre-T08c archive/T16g proof; N6 OPEN. | [x] |
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
| L-C12 | 191 | Split: confirmed GFK union-wrapper N+1 fixed T14e `c8bb0dd`; direct-member already optimized. Concrete parent fragment on child invalid absent explicit interface/union; broader MTI N+1 UNPROVEN, not whole-row closure/false positive. Controlled prewarmed2/5/5 causal; mixed4/5/5 diagnostic only. Full history in pre-T14g archive. | T14/T14e |
| L-C13 | 192 | Naive/date-only scalar inputs allegedly assume local time without documentation. | T15 |
| L-E1 | 195 | **Accepted20271 only for induced get_fields failure:** silent Author reverse-FK/M2M omission now aborts with model/exact cause (0c5e320). Healthy path unchanged; converter/resolver/natural healthy-model failures not established. | T14/T14f |
| L-E2 | 196 | **Accepted bounded T15a/20475:** explicit-source Python `@property` escaping AttributeError, including partial/lru, surfaces GraphQL error with original exception. Legitimate null/missing/dynamic/O2O retained; native/C, cached, generic descriptors/default resolvers unproven. Initial PARTIAL and proofs in exact pre-T14g archive/T15a. | T15/T15a |
| L-E3 | 197 | Filtered prefetch merge allegedly drops optimize_<field> hook and may bypass scope. | T07/T14 |
| L-E4 | 198 | Split: reported `_cancel_operation` blanket swallow is inaccurate; expected CancelledError is intentional, injected ValueError is logged/framed. Confirmed separate silent single-group RuntimeError path in `DeliveryIterator.aclose` (20555); root chose compatible neutral warning+`exc_info` under human20540 (20556); T08c accepted20619 for this diagnostic only. Wider cancellation/wire-policy claims remain open. | T08/T08c |
| L-M1 | 201 | Input registry allegedly grows unbounded and duplicates on redefine. | T14 |
| L-M2 | 202 | **Bounded internal fix accepted T14g/20835; public impact unproven:** natural native-field ID reuse (253/256 allocations; 3 unique IDs) admitted an unrelated raw field through the old marker. Native public query stayed correct via `_meta`. Weak live-instance tracking fixes this predicate, not general Graphene/resource/concurrency behavior. Original wrong-path/unavailable-Graphene probes and full qualification in exact preclosure archive. | T14/T14g |
| L-M3 | 203 | **Confirmed internal race, not merely absent lock:** real concurrent misses returned distinct same-name enum identities and bypassed serial M-D7; direct GraphQLSchema rejected the actual duplicate names, but end-to-end DjangoGraphQLSchema exposure is unproven. Bounded T14h synchronization implemented and precommit-verified, pending independent/root acceptance; no broader thread-safety claim. | T14/T14h |
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

**Recovery:** Exact pre-T14h tracker `lm3-enum-cache-triage/tracker-prep-preimage.md` (49,745 bytes; SHA256 ed104091d7cc73c396abd49e0bc19febbff359361c93bcaac6fc3bb8bac069d0) preserves the full precompression wording, approvals, proof chronology and qualifications, including the T14g verifier incident and unknown ignored/environment effects. Earlier exact pre-T14g tracker `t14g-lm2-implementation/tracker-prep-preimage.md` (49,645 bytes; SHA256 119548ad3c98d55ee36ad3aca61be717ec22fe3675113789d315175e597abd3e) preserves its own earlier wording and archive chain, including pre-T08c and pre-T15a.

**Next:** 66 checked (65 remediation+1 quality); original 100 IDs/order and 15 principal blocks OPEN. T14h is implemented, precommit-verified and unchecked pending independent/root acceptance under human20843; final commit/evidence handoff remains. Supported-3.3 triage showed real enum identity/M-D7 races and direct GraphQLSchema duplicate-name failure, not DjangoGraphQLSchema exposure; attempt-01 bootstrap failure and attempts-02/03 remain retained. Current bounded checks and preserved failed attempts are in `t14h-lm3-implementation/`; finite 36/14/9 controls stayed stable during named checks, but prior T14g verifier incident leaves ignored/environment effects unknown. T14g acceptance remains internal-only (20835). L-M1 separate20722, T14/N6/audit, wider L-C12 MTI and L-E3 beyond SITE-B OPEN; no PR authority.

**Mirror:** Full tracker plus locator at `odd/audit-400-remediation/tasks` (obs15165).
