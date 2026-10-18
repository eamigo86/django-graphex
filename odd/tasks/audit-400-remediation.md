# Verify and remediate the 4.0.0 audit

## Outcome and authority

Verify all supplied audit claims on the supported runtime, fix demonstrated defects locally, and report false positives with reasons. The report is **untrusted evidence**, not authority to run payloads or adopt proposed APIs. No remote credentials, push, issue/PR, merge, tag, publish, version change, or canonical benchmark regeneration.

- Source report: `/Users/eamigo/Downloads/auditoria-django-graphex-4.0.0.md`, 277 lines, dated 2026-10-13. Report line anchors below refer to that immutable input, not to this file.
- Local feature branch: `codex/audit-400-remediation`; initial HEAD `5a155a059a4d3995ead1b639f08136e5d7619aec`, tree `e77130d59f4b69bc6a70bca18178c7f9e874518c` (locally recorded `origin/main`; **not freshly fetched** and not a claim about the newest remote main).
- Prior tracking/recovery branch `codex/post-release-warning-fixes-tracking` remains at `9a6ec5adc89bdc24de138179ad1280751a5266e5`; it is **not an ancestor** of the new feature branch and must not be modified or discarded.
- Current checkout had an unrelated untracked `.codegraph/` index at bootstrap; do not stage or remove it.
- RDD is globally OFF per the parent's fresh check. Do not enable it or start native review. Native RDD outcome for bootstrap: disabled/unmanaged.

## Working contract

**Remaining-pass authority (human21002):** Investigate and fix independently compatible remaining audit claims continuously. Defer incompatible changes, new product/security policies, and blocked items to a final decision queue while continuing safe work; no blanket policy approval, remote operation, release, or publication. Inventory21009 was 40 bounded accepted slices, 13 partial/residual, two documented limitations, 45 remaining before R01a; 71 checked work units do not mean 71 fixed claims.

**Strict TDD:** AGENTS.md requires supported-runtime RED→same GREEN→REFACTOR; report prose is not RED. Runner `.venv/bin/python -m pytest`, focal `--no-cov`, full `-q`. Root graphql-core3.2.13 is unsupported (`pyproject.toml` requires 3.3); retained native3.3 overlay path/proof in T01/T08b. Use repo+overlay PYTHONPATH and PYTHONDONTWRITEBYTECODE=1; assert module/distribution/candidate each unit. No env refresh, mixed ABI or unsupported-result credit.

**Safety:** Use bounded witnesses, never blindly run report payloads or large DoS loads. Protect benchmark DBs, canonical JSON, root env, 16 original C/A IDs and 14 existing tags. Disposable pytest assets allowed; no new tags. Record each claim’s source/runtime, evidence/disposition/checks/reason. Report marks are untrusted; no-change alone proves no false positive.

**Public API gate:** Explain examples/migration impact and obtain individual approval for incompatible changes. Approved bounded policies: BP-C3-001, BP-A8-001, BP-MD3-001, BP-A11-001, BP-A4-001, BP-MD7-001, BP-LC7-001, BP-SD3-001, BP-SD4-001, BP-SD5-001, BP-A6-001, BP-A7-001, BP-MD9-001, BP-A9-001, BP-A10-EMAIL-001, BP-A10-POSITIVE-001, BP-A10-DBERROR-001, BP-MF3-EXACTNULL-001, BP-MF2-DATEPART-001, BP-A12-AND-MANY-001, **BP-T12-CURSORERROR-001** (human17667, accepted17715; only decoded unconvertible Float/Decimal/UUID bounds), **BP-MF4-NULLPAGE-001** (human17733; only explicit `page:null` equals omission/first page; zero/negative unchanged), **BP-MH2-SYNC-ASYNC-001** (human18659: controlled HTTP500 GraphQL JSON/owned coroutine cleanup; no async support). Exact prior descriptions/approval IDs: `t12b-typed-cursor-errors-closure/tracker-preclosure.md`; accepted-slice rows below retain scope. **BP-LE1-METADATA-001** (human20198/parent20226): two enumerators abort; two existing unwrap reraises retain original cause/class/message, healthy behavior unchanged. **BP-LE2-SOURCE-PROPERTY-001** (human20321): explicit source= Python @property internal AttributeError becomes GraphQL error with original exception; legitimate absence/null, nullable O2O, non-source and unrelated descriptors unchanged. **BP-SD1-READ-SCOPE-001** (human21642): automatic FK/reverse-FK output reads apply destination get_queryset; hidden nullable FK becomes null and reverse-FK lists are filtered. Optimized/prefetched and ordinary paths must agree. **BP-SD2-FK-FILTER-001** (human21718): forward-FK traversal filters apply destination get_queryset. Direct source FK-ID predicates retain their contract. **BP-SD2-REVERSE-FK-FILTER-001** (human21820): reverse-FK filters apply destination get_queryset, including child-ID traversal. Preserve Boolean/no-op/no-child/null and A12 witness semantics. **BP-SD2-M2M-FILTER-001** (human21939): declared/reverse M2M filters apply destination get_queryset, including target IDs, preserving grouped same-target versus independent AND and visible-universe Boolean/null/empty behavior. Through tables provide linkage, not a new ACL. **BP-SD2-FORWARD-O2O-FILTER-001** (human22033): forward OneToOne destination-field traversal filters apply destination get_queryset; preserve direct source-ID, real NULL, no-hook and existing reverse behavior. **BP-SD1-O2O-READ-SCOPE-001** (human22081): automatic direct/reverse OneToOne output reads apply destination get_queryset; hidden nullable targets return null while retaining visible parents. Optimized/ordinary paths agree. **BP-SD1-M2M-READ-SCOPE-001** (human22151): automatic declared/reverse M2M outputs apply destination get_queryset to members AND counts, retaining parents; hidden-only→[]/0. Optimized/ordinary paths agree; pagination derives from scoped rows. New through-ACL/nonnull SDL/order/customresolver/SD6/global and other incompatibilities stay gated. Other incompatibilities gated. Strict TDD/docs/coverage >95%; no tags/publication.

**Quality:** Hint changed/public signatures; Google Args/Returns/Raises, no repeated types/backticks. Tests/docs/changelog with behavior. Pure branch, combined, nonempty patch coverage each >=95.01%; patch otherwise N/A. No exclusion/skip/padding/addopts reset. Check Ruff/format/mypy/docstrings/docs/focal/full/diff; report all failures/skips. No artifact build.

**Cross-surface impact:** Inspect affected test apps, Playground/examples, docs and benchmark declarations per behavior unit; update affected surfaces or record concrete no-change evidence. No benchmark timing/canonical rewrite/public API policy. Omitted affected surfaces need bounded correction before acceptance.

**Implementation route:** Delegated direct, not SDD; broad preparation or 2+ nontrivial files to bounded writer and independent verifier. Conventional work-unit behavior/tests/docs commits; ~400 authored lines advisory, no code-golf. Delivery `ask-on-risk`, chain unresolved; no PR authority.

**Remaining-pass checks:** Delegated direct, no SDD or RDD lifecycle (globally OFF). Each behavior work unit requires permanent deterministic RED before production, same-byte GREEN then REFACTOR with seed21002; supported native3.3 identity guard; focal `--no-cov`, related and full `-q`, raw branch/combined/nonempty changed-production patch each >=95.01%, Ruff/format/mypy81/strict Google docstrings, docs and both changelogs, Playground in its own cwd with `--no-migrations --no-cov`, static benchmark and concrete cross-surface impact. No real PostgreSQL/CI/wheel/timing claim without evidence. Preserve finite36 JSON/14 tags/old branch/site/9 DB-lstat controls and T14g ignored/temp/environment/physical-index/unlisted UNKNOWN; fixed JSON/scripts only, no content-shell interpolation/eval/`shell=True`.

## Task sequence

**M2M output closeout preimage:** `sd1-m2m-output-closeout/tracker-preclosure.md` (49,150B; SHA `92dca76db311edd3b88396208dbb14e13b5b6744499a15143fd2f08864f2e51b`, mode0644) preserves the unchecked task and prior archive chain.

**Archive key:** Every shortened accepted task or ledger row marked `archive` points to the exact pre-compaction wording at `remaining-pass-preparation/tracker-preparation-preimage.md` (49,912 bytes; SHA-256 `442c725454b062a2db6b7b4fab70a68cceea2f613ff691d7b4e202aea0b50a94`). That preimage preserves approvals, failed/partial attempts, limits, and proof locators; compacting a row does not broaden acceptance or close a residual claim.

**M2M output preparation preimage:** `sd1-m2m-output-preparation/tracker-preedit.md` (49,868B; SHA `17a72eafec48d9f80f013968f7b15cf43e7f9a0076fae70e0ae9e855aabe6890`, mode0644) preserves exact shortened accepted rows, R06f TDD gap/later cycle, invalid auxiliary metrics, failed attempts/UNKNOWNs and the full earlier archive chain. Acceptance unchanged.

Unchecked needs evidence; `D` delegates; IDs persist. Prior wording/limits: `t13i-selected-introspection-classifier-implementation/tracker-pre-t13i.md` (SHA `5df41527bccd61ab2b5b36ccc19605162f10ba86d7a9b45c5d99ce31fc02e809`). All pre-T14h wording, proof chronology and qualifications are preserved byte-for-byte at `lm3-enum-cache-triage/tracker-prep-preimage.md` (49,745 bytes; SHA256 `ed104091d7cc73c396abd49e0bc19febbff359361c93bcaac6fc3bb8bac069d0`); shortened completed rows below are locators, not revised acceptance claims. Exact pre-T14i tracker: `lm4-registry-preparation/tracker-prep-preimage.md` (48,899 bytes; SHA256 `9e078429c84b9c9933740afc7ebb4c29f6fa5e0ea5b4473c6ca9173657fe3906`).

| Task | Route | Outcome and acceptance evidence | State |
|---|---|---|---|
| T00 | D, bootstrap | Record complete report traceability, local branch/runtime constraints and proof; mirror full file in Engram; tracking-only conventional commit. Structural readback only; runtime test N/A because no runtime/source behavior changed. | [x] |
| T01 | D | Q2 scoped completion; archive. | [x] |
| T02a | D | C3 scoped completion; archive. | [x] |
| T02b | D | C2 scoped completion; refs 92b1358f,7bec9571; archive. | [x] |
| T03a | D | C1 scoped completion; refs dbabfde; archive. | [x] |
| T03b | D | A8 scoped completion; refs 8f86dc8,12a7506; archive. | [x] |
| T03c | D | M-D3 scoped completion; refs d278321,4cc048b; archive. | [x] |
| T03 | D | Reproduce C1/A8/Decimal cases; use compatible fix if proven adequate. For each necessary incompatible SDL candidate, explain examples and migration impact to the user and obtain its separate explicit approval before implementation; output/input regression tests and docs. | [ ] |
| T04 | D | A2 POST body order accepted T04a; A11 per-result output cap accepted T04b. Retained-cache bytes/memory claims still OPEN; no broader resource policy approved. Exact history in `t14e-lc12-implementation/tracker-prep-preimage.md`/T04 proof. | [ ] |
| T04a | D | A2 scoped completion; refs 84369e4; archive. | [x] |
| T04b | D | A11 scoped completion; refs 441899a,40f0f57; archive. | [x] |
| T05 | D | A1 default-DB rollback accepted T05a; native ok:false, multi-DB and lost-update remain open/unapproved. Full qualifications in `t14e-lc12-implementation/tracker-prep-preimage.md`/T05a proof. | [ ] |
| T05a | D | A1 scoped completion; refs f91022e,cc67be5; archive. | [x] |
| T06 | D | A3/A4/M-D7/L-C7 independently accepted; M-S6 is a documented shortcut limitation. Other permission/schema claims remain open, including T07 scope investigations. `t06e-lc7-recheck/README.md`. | [ ] |
| T06a | D | A3 scoped completion; refs edb82a3,a2f329d; archive. | [x] |
| T06b-F1 | D | A4 scoped completion; refs 93edfdd; archive. | [x] |
| T06a-F2 | D | T06a-F2 scoped completion; refs 4643f9a; archive. | [x] |
| T06b | D | A4 scoped completion; refs 65e99d3,ff4741e; archive. | [x] |
| T06c | D | M-D7 scoped completion; refs 34b37e6,0b267da; archive. | [x] |
| T06e | D | L-C7 scoped completion; refs c3a35a7,da31d91,668de45; archive. | [x] |
| T07 | D | SD3/4/5, bounded automatic FK/reverse-FK/OneToOne/M2M outputs R06a/f/g and SD2 R06b–e accepted. Custom/global/newnonnull/unrelated policies excluded; T07 open. | [ ] |
| T07c | D, accepted | SD3 scoped completion; refs a96ca17,6275b6e,dcdd25b,6a964b4; archive. | [x] |
| T07d | D, read-only | SD4/SD5 scoped completion; read-only triage, no policy approval; archive. | [x] |
| T07e | D | SD4 scoped completion; refs 8521c02,c39b434; archive. | [x] |
| T07f | D | SD5 scoped completion; refs f0b3126,0a4ba13; archive. | [x] |
| T08 | D | Confirm/fix A5/A6 and subscription lifecycle, filters, events, and transport claims; real-user WS/SSE and failure-path tests. | [ ] |
| T08a | D, accepted16725 | A5 scoped completion; refs ac72aa7,c9cb4f1; archive. | [x] |
| T08b | D, accepted | A6 scoped completion; refs 901c35b,c3edeb3; archive. | [x] |
| T08c | D; human20540/root20555–20556; accepted20619 | L-E4/N6 scoped completion; diagnostic only; initial failures retained; refs 15834; archive. | [x] |
| T09 | D | A7/M-D8/M-D9 accepted; other annotation/interface claims remain open. | [ ] |
| T09a | D | A7 scoped completion; refs accepted16924; archive. | [x] |
| T09b | D | M-D8 scoped completion; refs accepted16997; archive. | [x] |
| T09c | D | M-D9 scoped completion; refs accepted17088; archive. | [x] |
| T10 | D | A9/T10a and bounded A10/T10b–d accepted; wider A10 open. Residual triage is read-only; no general `full_clean()`/upsert policy approved. | [ ] |
| T10a | D, accepted17162 | A9 scoped completion; refs accepted17162; archive. | [x] |
| T10b | D, accepted17234 | T10b scoped completion; refs accepted17234; archive. | [x] |
| T10c | D | A10/P1 scoped completion; positive two-field only; wider A10 open; refs accepted17314,6bd37b2,ebe32b0,fc3bccd0; archive. | [x] |
| T10d | D, accepted17370 | T10d scoped completion; refs accepted17370; archive. | [x] |
| T11 | D | A12/filter types/limits wider block open. T11a exact-null, T11b date-part, T11c A12 AND/to-many and T11d M-F1 compatible slices accepted; M-F3 empty-Boolean policy unchanged. | [ ] |
| T11a | D, accepted17430 | M-F3 scoped completion; refs c4273e2; archive. | [x] |
| T11b | D, accepted17503 | T11b scoped completion; refs 53b3481; archive. | [x] |
| T11c | D, accepted17607 | A12 scoped completion; DB-read/htmlcov safety violations retained; refs 4c3e4bb; archive. | [x] |
| T11d | D, accepted17812 | M-F1/A12 scoped completion; refs 954a2036; archive. | [x] |
| T12 | D | Confirm/fix A13 and pagination ordering/count/page boundary claims; backend-specific and in-memory regression tests. | [ ] |
| T12a | D, accepted17645 | A13 scoped completion; refs accepted17645; archive. | [x] |
| T12b | D, accepted17715 | T12b scoped completion; refs accepted17715; archive. | [x] |
| T12c | D, accepted17780 | T12c scoped completion; refs accepted17780; archive. | [x] |
| T12d | D, accepted17944 | M-F7 scoped completion; refs accepted17944; archive. | [x] |
| T12g | D, accepted19564 | M-F7 scoped completion; refs accepted19564; archive. | [x] |
| T12f | D, human18041; accepted18137 | M-F5 scoped completion; refs f6e88d4,d1a6a18; archive. | [x] |
| T12e | D, human17983; accepted18032 | M-F6 scoped completion; refs c75ea72; archive. | [x] |
| T13 | D | Confirm/fix HTTP/cache/error/introspection/limits and async-view claims, separating documented defaults from defects and optional hardening; each necessary incompatible public-default change needs its own explained user approval before implementation. | [ ] |
| T13a | D, human18167; accepted18241 | M-S1 scoped completion; shell-mirror effects UNPROVEN; refs 96e1f9e,bcd6686,88107; archive. | [x] |
| T13b | D, accepted18271 | M-S5 scoped completion; refs accepted18271; archive. | [x] |
| T13c | D, human18294; accepted18361 | M-S4 scoped completion; refs accepted18361; archive. | [x] |
| T13d | D, human18441; accepted18531 | M-H3 scoped completion; refs 043811e,cbfb9fb; archive. | [x] |
| T13d-doc | D, accepted18531; `cbfb9fb` | T13d-doc scoped completion; DOC002 correction only; archive. | [x] |
| T13e | D, human18554; accepted18627 | M-H4 scoped completion; Ruff cache effects UNPROVEN; refs 69d326e; archive. | [x] |
| T13f | D, human18659; accepted18829 | M-H2 scoped completion; initial PARTIALs retained; archive. | [x] |
| T13g | D, accepted18888 | M-S3 scoped completion; refs accepted18888; archive. | [x] |
| T13h | D, accepted18998 | M-H1 scoped completion; refs 347b2ff; archive. | [x] |
| T13i | D, accepted19287 | T13i scoped completion; refs accepted19287; archive. | [x] |
| T14a | D, accepted19162 | T14a scoped completion; refs 9fec11d; archive. | [x] |
| T14b | D, parent scope19589; accepted19665 | M-O1 scoped completion; refs 316844e; archive. | [x] |
| T14c | D, accepted19762 | M-O2 scoped completion; refs 961c018; archive. | [x] |
| T14d | D, accepted19885 | M-T1 scoped completion; archive. | [x] |
| T14e | D, accepted20126 | L-C12/N6 scoped completion; refs c8bb0dd; archive. | [x] |
| T14f | D, accepted20271; human20198 | L-E1/N6 scoped completion; refs 0c5e320; archive. | [x] |
| T14g | D; human20732/root20769; accepted20835 | Bounded internal live-GraphQLField identity/lifetime fix `a2ff209`, weak values and actual-instance gate; RED→GREEN6, independent/root PASS. Prior unsafe-shell verifier incident and T14g ignored/temp/environment/physical-index/unlisted UNKNOWN persist. Exact tests, coverage, incident and proof limits: `t14g-lm2-closure/tracker-preclosure.md`, `t14g-lm2-independent/{incident-audit.json,safe-attempt-01/VERIFICATION.md}`, and Q3 pre-edit archive. No public-schema or wider L-M2/N6/audit closure. | [x] |
| T14h | D; human20843; accepted20879 | L-M3 scoped completion; old RED/setup failures and public-schema gap retained; refs 14720eab,4f5161a,15845,13078; archive. | [x] |
| T14i | D; human20887/root20919; accepted20982 | L-M4 scoped completion; old witness failures and public-schema gap retained; refs 13b2e6b4,15857,13078; archive. | [x] |
| T14 | D | Confirm/fix optimizer selection/concurrency/thread-safety and remaining low-level exception/memory claims where reproducible; bounded tests. | [ ] |
| T15 | D | Confirm/fix scalar, directive, and low-level output-contract claims not already covered; behavior-specific tests/docs. | [ ] |
| T15a | D; human20321; accepted20475 | L-E2/N6 scoped completion; refs 7fb4c12; archive. | [x] |
| T16a | D | Q2 scoped completion; archive. | [x] |
| T16b | D, accepted | T16b scoped completion; refs ca6cfb7; archive. | [x] |
| T16c | D, accepted17162 | A9 scoped completion; refs 4ec40e8; archive. | [x] |
| T16d | D, accepted18385 | T16d scoped completion; refs 3e3af998; archive. | [x] |
| T16e | D, accepted19086 | T16e scoped completion; refs 9c431f6; archive. | [x] |
| T16f | D, accepted19403 | T16f scoped completion; refs 0606b34; archive. | [x] |
| T16g | D, accepted20001 | N6 scoped completion; archive. | [x] |
| T16 | D | Wider tooling, coverage, metadata, refactor and dead-code block OPEN; no benchmark regeneration. Q2=T16a, datepart=T16e, GET-body=T16f. Base-reproduced seed1823552487 test-fixture cached-pair leak is fixed in accepted T16g; not a new original audit ID and not N6 closure. | [ ] |
| T17 | D | Complete independent disposition of every ledger ID, verify section-9 negative claims, run full quality/coverage gates, list all final false positives with evidence and reasons, and report remaining design decisions or unavailable checks. | [ ] |

| R01 | D; human21002; unchecked | WS/SSE lifecycle: verify L-S4 complete frame before operation-slot release and M-U1; triage L-S3 on actual ASGI handshake before classifying. Compatible defect only, permanent deterministic RED before production; no new wire policy. | [ ] |
| R01a | D; human21002; accepted21102 | L-S4 completion/slot cleanup `9268da4` only; real-ASGI TDD, independent16/root2 PASS, full5576/7skip/9warn, patch19/19. No handshake change or parent closure. Exact failures/limits: `r01a-closure-r01b-preparation/tracker-preclosure.md` SHA `6e526cae`; `r01-ws-completion-{implementation,independent}/`. | [x] |
| R01b | D; human21002; accepted21184 | M-U1 source-owned join cleanup/same-failed-Source retry `514def1` only; intermediate `fe545832` **not accepted**. TDD/independent20/root8 PASS, full5584/7skip/9warn, patch17/17. No distributed guarantee/parent closure. Exact retries, failed attempts, guard limits: `r01b-closure-r03a-preparation/tracker-preclosure.md` SHA `ccafd49f`; `r01b-startup-cleanup-{implementation,correction,independent}/`. | [x] |
| R02 | D; human21002; unchecked | Subscription data delivery M-U2/M-U3/M-U4: separate contract, real-path witnesses, then compatible scoped work units. | [ ] |
| R02a | D; human21002; accepted21577 | Decimal snapshot equality only, corrected6df731e0. Initial6983455 256-char cap rejected21557/21558; valid257-char retained by causalRED1→sameGREEN1. No quota/DateTime change; R02b open. Exact proof/coverage/failed attempts/limits in M2M output preparation preimage and obs21577. | [x] |
| R02b | D; decision deferred; unchecked | **M-U3 DateTime residual:** JSON-safe snapshot may truncate microseconds; querying a later live row changes event-time semantics and fails for deleted rows. Defer capture/precision policy; do not claim DateTime or Float "never match" without separate evidence. | [ ] |
| R03 | D; human21002; unchecked | Directives/scalars: M-U5/M-U6, M-D4/M-D5/M-D6, L-C10/L-C11/L-C13; preserve established SDL/input contracts or defer incompatible policy. | [ ] |
| R03a | D; human21002; accepted21311 | Nativeasyncdirective correction finald1b7622/lazy031299c; eagerc610b leakedownedwork and NOTaccepted. BorrowedFuture ownership/HTTPJSON500/noasyncHTTP preserved. Original91ignoredreportpreimages UNKNOWN. Fullproof/failedhistory/limits in M2M output preparation preimage and obs21311; wider R03 open. | [x] |
| R04 | D; human21002; unchecked | Minor HTTP/pagination/cursor L-C1–6/L-C8/L-C9 and A13 residual; distinguish accepted bounded slices from remaining malformed-input cases. | [ ] |
| R05 | D; human21002; unchecked | Mutations A1 residual, M-D1/M-D2 and A10 validation/upsert; isolate compatibility and multi-DB/ok:false/lost-update policy gaps. | [ ] |
| R05a | D; human21002; accepted21526 | M-D2 save/delete signal alias only `bf1163e`; TDD4, independent21521/root15 PASS; full5603/7skip/10warn, patch8/8. R05b/cross-DB separate. Exact warning-control chronology, failures/UNKNOWNs: `r05b-routed-nested-atomic/tracker-preedit.md` SHA `229d1488`, `r05a-routed-subscription-commit/`. | [x] |
| R05b | D; human21002; accepted21547 scoped | c408989/41fbeec stable/model-routed same-alias nestedrollback only. CREATE router getsinstance=None; stateDBupdate. Instance-hintCREATEdiagnostic stillFAILS withpersistedparent/child; R05c deferred, no crossDB/newAPI closure. Exact TDD/proof/limits in M2M output preparation preimage and obs21547. | [x] |
| R05c | D; human decision deferred; unchecked | **M-D2 instance-dependent create routing residual:** planning with `instance=None` can differ from backend routing a populated parent, so same-alias rollback is not guaranteed. A design/policy decision is required before changing construction/routing or promising atomicity here; no new API, backend rewrite or distributed transaction is authorized. Independent witness: `r05b-routed-nested-independent/INSTANCE_ROUTER/output.txt`. | [ ] |
| R06 | D; human21002/21642/21718/21820/21939/22033/22081/22151 | R06a–g accepted bounded outputs/filters. Custom/global policy, L-E3 beyond SITE-B and L-C12 MTI deferred/unproven. | [ ] |
| R06a | D; human21642; accepted21711; BP-SD1-READ-SCOPE-001 | 73a85ab: automatic FK/reverse-FK outputs. Exact TDD/full/coverage/accessor correction/failed attempts/UNKNOWNs/exclusions in M2M output preparation preimage and obs21711. | [x] |
| R06b | D; human21718; accepted21796; BP-SD2-FK-FILTER-001 | 603a117: forward-FK filters/IDs/NULL/Boolean. Exact TDD/full5662/coverage, rejected empty/NOT candidate, failures/UNKNOWNs/exclusions retained in OneToOne output preparation preimage and obs21796. | [x] |
| R06c | D; human21820; accepted21929; BP-SD2-REVERSE-FK-FILTER-001 | 98ee545: reverse-FK witnesses/IDs/Boolean/null/A12/projection. Full5681/7skip/10warn; unit65/67/cumulative1444/1471. Exact TDD/coverage/nested-NULL correction/docs/failed attempts/UNKNOWNs/exclusions in OneToOne output preparation preimage and obs21929. | [x] |
| R06d | D; human21939; accepted21993; BP-SD2-M2M-FILTER-001 | 39dc696/8ab9ada: declared/reverse M2M visible-target filter scope/IDs/A12. Full5704/7skip/10warn; unit43/45/cumulative1485/1514. Exact TDD/freshness/failed attempts/ignored7DOC002/UNKNOWNs/exclusions and postcommit proof in OneToOne output preparation preimage, obs21993/22006. | [x] |
| R06e | D; human22033; accepted22059; BP-SD2-FORWARD-O2O-FILTER-001 | 0f64533/0665c24: forward OneToOne FIELDfilters/IDs/NULL/reverse. Exact TDD/full5710/coverage/freshness/failures/UNKNOWNs and postcommit parity in M2M output preparation preimage, obs22059/22079. | [x] |
| R06f | D; human22081; accepted22121; BP-SD1-O2O-READ-SCOPE-001 | 8ebfd43/8c6452c: automatic OneToOne outputs hiddennullable→null/parent retained. InitialRED ONLYforward; reverse chronologyGAP22091 retained, later separate reverseRED2→sameGREEN2 notretrorepair. Full5722/7skip/10warn; branches4266/4470, combined15926/16316, unit17/17/cumulative1499/1528; TRUEarcs6/6,684/706, writer369/386 invalid. Exact hashes/TDD/failures/94.44patch/freshness/ignored7DOC002/UNKNOWNs/exclusions and 13file postcommit parity in M2M output preparation preimage, obs22121/22136. | [x] |
| R06g | D; human22151; accepted22219; BP-SD1-M2M-READ-SCOPE-001 | 0ee46b94bb391bb59c599f9e88af46ce0a8f0f1b/tree7502ac27: automatic declared/reverse M2M members/counts scoped beforepagination, parent retained, explicit hatches unchanged. InitialRED8→sameGREEN8; independentrejectedwrongprefetchalias22186 (2FAIL), archive→aliasRED4→sameGREEN4. SAMEaliaswitness8PASS/rootquerygrowth1PASS. Final5745/7skip/10warn, raw4280/4484=95.45% floor, combined15958/16348=97.61%, FULL-INDEX unit22/22=100%, cumulative1517/1546=98.12%; arcs16/16,698/720.16file90103160…=full; docs130/54/43, quality/Playground60/staticbench357 PASS. Related85 predates only fixtureYieldsdocstring. Ignored7DOC002 FAIL. Exact TDD/hashes/rejectedalias/table/import/report/staledocs/DOC004/auditor-launch failures/freshness/UNKNOWNs/exclusions in obs22219 and sd1-m2m-output-{implementation,alias-correction,alias-independent}/.870authoredlines/noPR/RDD OFF/noPGCIwheelTimingTagRemote. | [x] |
| R07 | D; human21002; unchecked | Cache/limits A2 retained bytes/aggregate and M-S2 residual: current DEFAULT_PAGE_SIZE=100 already approved T12d, so the report's all-defaults-None wording is stale; byte/aggregate cache quotas and other limits/defaults/width/depth need separate evidence or policy decisions. M-F3 empty-Boolean identities remain unchanged by prior human choice. Count-based LRU is not a byte cap or runtime DoS proof. No R07 source/policy change in R01b. | [ ] |
| R08 | D; human21002; unchecked | Memory/input L-M1 and M-D10 broader SDL/input shapes; verify separately from accepted L-M2–4 internal fixes. | [ ] |
| R08a | D; human21002; accepted21363 | Warning-only M-D10 at7a1dfe3/e9a9477; SDL/coercion/rawdicts unchanged, no shapeconversion. Initial independent21357 helper/global-input PARTIAL remains despitefunctionalPASS. Exact TDD/full/coverage/root32/limits in M2M output preparation preimage and obs21363; wider claim open. | [x] |
| R09 | D; human21002; unchecked | Quality/tooling/tests Q1/Q3/Q4/N6 remain open. R09a fixed only the 23 tracked-test findings; the current 602-file local checker still reports seven DOC002 in ignored profiles, not a clean-CI result. Historical ignored count was 58 before the R09 incident; original profile preimages are UNKNOWN. R09b requires a user decision; preserve incident and benchmark evidence. | [ ] |
| R09a | D; human21002; accepted21497 | Tracked-test docs only `34e03d3`; RED23→GREEN0, independent21490/root109 PASS; full5598/7skip/10warn, production diff N/A. Seven ignored findings, history PARTIAL and original profile/cache UNKNOWN persist. Exact hashes/failures/finite limits: `r09a-closure-r05a-preparation/tracker-preclosure.md` SHA `674286ef`, `r09a-tracked-docstrings-{implementation,independent}/`. R09b/R09/N6 open. | [x] |
| R09b | D; human21002; unchecked; deferred | The historical 58 local profile findings (28 DOC001, 29 DOC101, 1 DOC201) were in eight files intentionally ignored by `benchmarks/.gitignore:38` as point-in-time ad-hoc scripts, not the tracked benchmark contract; current postincident scan reports seven DOC002 there. Do not force-add, change the ignore policy, remove files, or claim clean CI requires them without a user decision. The earlier attempt edited those ignored files without exact pre-edit copies; current postimages are archived externally, original preimages remain UNKNOWN. See the R09 incident record. No R09b acceptance or source commit. | [ ] |
| R09c | D; human21002; accepted21591 | Q3 test-owned upload/spool hygiene only e1f29e9; no production leak/ResourceWarning claim. Exact TDD/checks/failures/UNKNOWNs: reverse-filter preparation preimage, obs21591, `q3-upload-resource-ownership/`. Q3/T16/N6/audit open. | [x] |
| R10 | D; human21002; unchecked | Recommendation/negative-proof Q5–10, P1 and N1–5; classify evidence and reasons, not automatic code changes. | [ ] |
| R10a | D; human21002; accepted21610 | Current-boundary docs at5eb905d after rejected73b8f4e; docs-only, no runtime policy. Exact correction TDD/checks/reused full/failed attempts/UNKNOWNs: reverse-filter preparation preimage, obs21610, `r10a-cache-miss-correction/`. | [x] |
| R11 | D writer/verification, inline tracking; accepted21639; HISTORY_PARTIAL | Report a5f3a83 preserves100IDs/order/examples, historical41/26/9/7/6/11 statuses. Exact TDD mismatch, UNKNOWNs, correction/quality/full/coverage proofs and acceptance limits: SD2 preparation preimage and `r11-final-example-precision/`. Report delivery only, not audit/release closure. | [x] |

## Claim traceability ledger

The C1–C3/A1–A11 concise dispositions retain their exact full chronology, approvals, caveats and links in `t14d-mt1-thread-local-fork-implementation/tracker-preclosure.md` (SHA-256 `e028aca556b2b779174c2adafb7ce32caa43c847d3be13a954f2cbfb1beb46cf`). This archive is the immutable lossless preimage; the 100 claim IDs and order below remain current.

Status for **every** item below is `U` at bootstrap. The report's ✅/🔁/📖 labels are claims about its own methods, not acceptance evidence. Related rows are marked `↔` where they may share a root cause; they remain independently traceable. Exact line anchors prevent a later worker from silently dropping subclaims. `T17` closes every row, including duplicates and no-change decisions.

### Critical and high (original IDs preserved)

| ID | Report line | Distinct claim / dependency | Task |
|---|---:|---|---|
| C1 | 36–44 | Decimal PK Float/null propagation fixed T03a; M-D3 precision/M-D4 policy separate; archive. | T03a/T03 |
| C2 | 46–58 | Ordered fragment effects fixed T02b; duplicate FieldNode behavior unchanged; archive. | T02b |
| C3 | 60–72 | Shared cycle precheck fixed T02a for cost/depth; bounded GraphQLError behavior; archive. | T02a |
| A1 | 80 | T05a default-DB GraphQL-error rollback accepted; native ok:false sibling, multi-DB and lost-update remain open. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T05a/T05 |
| A2 | 81 | T04a POST body-order fix accepted; retained AST/cache bytes and aggregate memory claims remain unverified. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T04a/T04 |
| A3 | 82 | Invalid selector rejection fixed T06a; no general unauthenticated-bypass proof; archive. | T06a/T06 |
| A4 | 83 | Distinct output collision guard fixed T06b; separate registries/forks unchanged; archive. | T06b/T06 |
| A5 | 84 | Cold Django-user WS/SSE pruning fixed T08a; fake-user probes not universal proof; archive. | T08a/T08 |
| A6 | 85 | Automatic best-effort notification fixed T08b; manual strict, no delivery guarantee; archive. | T08b/T08 |
| A7 | 86 | Per-input runtime factories fixed T09a; no wider collision policy; archive. | T09a/T09 |
| A8 | 87 | BigInteger string output fixed T03b; relation-ID/Enum behavior separate; archive. | T03b/T03 |
| A9 | 88 | Generated delete-error redaction fixed T10a; no general DB catch; archive. | T10a/T10 |
| A10 | 89 | T10b/c/d accepted for Email, two positive fields and generated DB redaction; broader validation remains open. See exact archived pre-T14d ledger for approvals, chronology, caveats and proof links. | T10 |
| A11 | 90 | Per-result Unicode cap fixed T04b; no aggregate-response quota; archive. | T04b/T04 |
| A12 | 91 | Independent-row M2M AND fixed T11c; one relation filter stays same-row; other scope unchanged; refs BP-A12-AND-MANY-001,17607; archive. | T11/T11c |
| A13 | 92 | Valid emitted Float/Decimal/UUID continuation accepted T12a/17645; decoded unconvertible bounds raise Invalid cursor under approved T12b/17715. Other cursor policies remain open. | T12 |

### Security design (§4)

| ID | Report line | Distinct claim / dependency | Task |
|---|---:|---|---|
| SD1 | 98–99 | Automatic FK/reverse-FK R06a/21711, OneToOne R06f/22121 and declared/reverse M2M members/counts R06g/22219 accepted, including optimized M2M same-alias correction. Prior16223/22073/22131 bypasses confirmed. Customresolver/global policy excluded; broadclaim remains partial. | T07/R06a/R06f/R06g |
| SD2 | 100 | FK/reverse-FK/M2M/forward OneToOne R06b–e accepted (latest22059); original oracle16229 confirmed. Reverse O2O hook already applies in bounded probe. Ordering/custom/global and output policies excluded; whole claim stays partial. | T07/R06b/R06c/R06d/R06e |
| SD3 | 101 | Generated FK/M2M destination-ID scope fixed T07c; real writes and SD1/2/O2O/SD4/5 remain open; refs a96ca17; archive. | T07c/T07 |
| SD4 | 102 | Hostless nullable reverse-FK orphan adoption denied T07e; new/owned child unchanged; refs BP-SD4-001,16504; archive. | T07/T07d/T07e |
| SD5 | 103 | Flat GFK target metadata pruned T07f on actual-target read/scope denial; not global ACL; refs 16674; archive. | T07/T07d/T07f |
| SD6 | 105 | Proposed strict_scope mode/system check is a **recommendation**, not proof that the current documented contract is defective; public semantics require user decision. | T07 |

### Medium: security/defaults and data correctness

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| M-S1 | 114 | Variable-backed cost limit fixed T13a; no hard memory/DB cap; refs human18167,96e1f9e,bcd6686; archive. | T13/T13a |
| M-S2 | 115 | Original report claims all defaults None (page size, depth, cost, body), unbounded `in` list and Boolean breadth/depth. Current DEFAULT_PAGE_SIZE=100 was already approved in T12d; other defaults and width/depth remain separately unverified or policy-dependent. Count-based LRU is not a byte/aggregate cache cap or DoS proof. | T11/T13/R07 |
| M-S3 | 116 | Introspection configuration documented T13g; not a runtime-default fix; refs 18888; archive. | T13/T13g |
| M-S4 | 117 | DEBUG=False error exposure fixed T13c; bounded HTTP contract; refs 18361; archive. | T13/T13c |
| M-S5 | 118 | GET component framing fixed T13b; same-identity ambiguity only; refs d9d2c40,parent18271; archive. | T13/T13b |
| M-S6 | 119 | **Documented shortcut limitation, not silent bypass:** `Field`/`CharField`/`IntField(required_perms=...)` raise `TypeError`; lowercase `field(..., required_perms=...)` works (native3.3 scoped-view3 PASS). Untagged fields are documented public. Additive shortcut parity optional, not needed for this fix. `t06d-ms6-triage/README.md`, Engram16113. | T06 |
| M-D1 | 124 | Partial update allegedly saves whole row and causes lost concurrent update. | T05 |
| M-D2 | 125 | Nested atomic and binding on_commit allegedly omit database alias; two subcases. | T05/T08 |
| M-D3 | 126 | Approved breaking Decimal output precision fix T03c; SQLite reload rounding/input policy separate; refs 9007199254740993,9007199254740994,d278321,4cc048b; archive. | T03c/T03 |
| M-D4 | 127 | **Partly verified, still open:** scalar accepts nonfinite values; actual public model mutations reject NaN, Infinity, -Infinity and 1e1000 with structured field errors and zero save calls, not an unhandled Django exception. Exact report exponent 1E+999999999 remains untested because bounded processing was not established; no whole-row false-positive verdict. | T03 |
| M-D5 | 128 | JSON scalar allegedly parses a JSON-looking string into a different JSON type. | T15 |
| M-D6 | 129 | JSONRaw allegedly preserves Undefined in lists and accepts infinity-producing exponent; two subcases. | T15 |
| M-D7 | 130 | Incompatible same-name choices rejected T06c; reordered equivalent choices retained; initial PARTIAL archived; refs 34b37e6,0b267dab,16098; archive. | T06c/T06 |
| M-D8 | 131 | Reserved-name construction fixed T09b; inherited-hook initial PARTIAL archived; refs 16997; archive. | T09b/T09 |
| M-D9 | 132 | Interface/implementor name honored T09c; ordinary type naming not approved; P1/P2 PARTIAL archived; refs 17088,BP-MD9-001,17010,16966; archive. | T09c/T09 |
| M-D10 | 133 | **Partly confirmed/open:** native Literal/dict/set/Union inputs fall back to String!; R08a accepted21363 adds diagnostic warning only, preserving SDL/coercion/raw resolver dict and Optional/list controls. No Enum/JSON/set/input-union conversion, automatic validation, or wider shape policy approved. Original triage `t09-md10-triage/README.md`/17017; bounded proof in R08a row. | T09/R08a |

### Medium: filters, HTTP, optimizer, subscriptions, thread safety

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| M-F1 | 138 | Nested related date parts/PK shadow fixed T11d; SDL/null/A12 separate; refs 17812; archive. | T11/T11d |
| M-F2 | 139 | Date/DateTime numeric parts Int fixed T11b; whole values/TimeField policy unchanged; refs BP-MF2-DATEPART-001,17431,human17458,17503; archive. | T11/T11b |
| M-F3 | 140 | Triage `t11-mf3-boolean-filter-triage/README.md`: exact:null all3 vs isnull:true NULLrow1. Exact-null/omission slice accepted T11a/17430; wider Boolean identities remain open. Existing or:[]/not:{} no-op and or:[{},X]→X unchanged, not a new Boolean fix. | T11/T11a |
| M-F4 | 141 | Explicit page:null equals omission T12c; zero/negative unchanged; refs 9ab95cb,accepted17780; archive. | T12/T12c |
| M-F5 | 142 | Model-backed PK-ASC tie-break fixed T12f; offset shifts/random ordering unaffected; refs 18137; archive. | T12/T12f |
| M-F6 | 143 | Negative-page count-error fallback fixed T12e without full fetch; no universal DB-failure proof; refs human17983,accepted18032; archive. | T12/T12e |
| M-F7 | 144 | Omitted-page default fixed T12d; T12g docs only; explicit None legacy unchanged; refs accepted17944,accepted19564; archive. | T12/T12d/T12g |
| M-H1 | 149 | Partial-batch HTTP400 prior+error array/stop fixed T13h; writes persist, no batch transaction; archive. | T05/T13/T13h |
| M-H2 | 150 | Sync/async rejection JSON500/owned cleanup fixed T13f; no general async support; refs human18659; archive. | T13/T13f |
| M-H3 | 151 | 0/False preserved in response cleanup T13d; fragment classifier T13i separate; refs human18441,043811e,cbfb9fb,accepted19287; archive. | T13/T13d |
| M-H4 | 152 | Success-only cache fixed T13e; functional PASS, finite safety PARTIAL/Ruff caveat archived; refs human18554; archive. | T13/T13e |
| M-O1 | 157 | Merged-node optimizer N+1 fixed T14b; bounded five-row case; refs 316844e; archive. | T14/T14b |
| M-O2 | 158 | Warm-hit lock split fixed T14c; no general concurrency guarantee; refs 19762,961c018; archive. | T14/T14c |
| M-U1 | 163 | Confirmed real-ASGI backend-join-before-return cancellation ghost; bounded R01b accepted21184 at `514def143c42d6dad082e4590fb9edce813c90d6`. Source-owned attempted/confirmed groups best-effort cleaned; same failed Source retry retained. Intermediate `fe545832` unaccepted: its failed-source retry regression was new, whereas explicit-close-reopen pre-existed in base by code comparison (not fresh base run). Full proof/limits in R01b row and archived candidate; no distributed-backend guarantee. | T08/R01b |
| M-U2 | 164 | id_only delete allegedly drops events with scope or non-PK filters. | T08 |
| M-U3 | 165 | In-memory subscription filter string coercion allegedly fails Decimal/DateTime/Float. | T08 |
| M-U4 | 166 | m2m_changed and bulk/update paths allegedly emit no events; determine documented contract separately. | T08 |
| M-U5 | 167 | Bounded R03a native async transformation and borrowed-Future HTTP-bypass correction accepted21311 at `d1b7622` after rejected eager-wrapper leak and lazy `031299c` fix. Synchronous HTTP remains JSON500; no general async HTTP or wider directive policy. | T15/R03a |
| M-U6 | 168 | @date null/localtime/date-only; camel/snake/kebab conversion; @number/@currency null-to-zero—seven distinct behavior families. | T15 |
| M-T1 | 173 | Fork-depth thread isolation fixed T14d; other registry races separate; refs accepted19885; archive. | T14d/T14 |

### Low (§6)

| ID | Report line | Distinct claim / subcases | Task |
|---|---:|---|---|
| L-C1 | 180 | Malformed ID in get_node/retrieve/DjangoObjectField allegedly raises raw error instead of null; three entry points. | T15 |
| L-C2 | 181 | Two public constructor guards preserved under -O T14a; exact predicates only; refs 19162; archive. | T14/T14a |
| L-C3 | 182 | GraphQLView/BaseGraphQLView status and data:null response contracts diverge. | T13 |
| L-C4 | 183 | Multipart files allegedly bypass MAX_UPLOAD_SIZE. | T13 |
| L-C5 | 184 | LIMIT_MINIMUMS allegedly skips three named settings. | T13 |
| L-C6 | 185 | ensure_csrf_cookie allegedly prevents browser cache reuse after first request. | T13 |
| L-C7 | 186 | Ambiguous enum members rejected T06e; unique names unchanged, optional multiselect untested; refs c3a35a7,da31d91,16147,16210; archive. | T06e/T06 |
| L-C8 | 187 | page:-1 allegedly not last actual page. | T12 |
| L-C9 | 188 | Null ordering allegedly differs between DB and memory cursor. | T12 |
| L-C10 | 189 | Directives declared on fragment spreads/inline fragments allegedly ignored. | T15 |
| L-C11 | 190 | @truncate, @title and @floor allegedly mishandle infinity; independently check each. | T15 |
| L-C12 | 191 | Split: confirmed GFK union-wrapper N+1 fixed T14e `c8bb0dd`; direct-member already optimized. Concrete parent fragment on child invalid absent explicit interface/union; broader MTI N+1 UNPROVEN, not whole-row closure/false positive. Controlled prewarmed2/5/5 causal; mixed4/5/5 diagnostic only. Full history in pre-T14g archive. | T14/T14e |
| L-C13 | 192 | Naive/date-only scalar inputs allegedly assume local time without documentation. | T15 |
| L-E1 | 195 | get_fields failure now aborts T14f with model/cause; healthy path unchanged; refs 0c5e320; archive. | T14/T14f |
| L-E2 | 196 | Explicit source= property AttributeError surfaced T15a; legitimate null/unrelated descriptors unchanged; refs 20475; archive. | T15/T15a |
| L-E3 | 197 | Filtered prefetch merge allegedly drops optimize_<field> hook and may bypass scope. | T07/T14 |
| L-E4 | 198 | Cancellation claim split: expected cancellation intentional; single-group aclose warning fixed T08c only; refs 20555,human20540,20556,accepted20619; archive. | T08/T08c |
| L-M1 | 201 | Input registry allegedly grows unbounded and duplicates on redefine. | T14 |
| L-M2 | 202 | Bounded internal live-field identity fixed T14g; public impact/Graphene proof unestablished; refs 20835; archive. | T14/T14g |
| L-M3 | 203 | Bounded compiler/Registry enum race fixed T14h; direct GraphQLSchema only, public exposure unproven; refs 20879,14720eab; archive. | T14/T14h |
| L-M4 | 204 | Bounded singleton/list race fixed T14i; direct GraphQLSchema only, public exposure unproven; refs accepted20982,13b2e6b4; archive. | T14/T14i |
| L-S1 | 207 | SSE allegedly lacks heartbeat and per-user stream cap. | T08 |
| L-S2 | 208 | connection_init payload allegedly ignored; no token-auth on_connect hook. | T08 |
| L-S3 | 209 | Confirmed on actual ASGI handshake with empty offered subprotocol list (R01a LS3_DIAGNOSTIC); accept/reject/close-code change deferred for wire-policy decision. | T08/R01 |
| L-S4 | 210 | Confirmed real-ASGI complete-before-cleanup/slot-release RED; bounded compatible R01a fix accepted21102, implementation9268da4. Historical failure/proof limitations retained; wider R01/T08 remains open. | T08/R01a |

### Tooling, maintainability, recommendations, and negative checks

| ID | Report line | Distinct claim / relationship | Task |
|---|---:|---|---|
| Q1 | 15–18, 217 | **Partly observed T01:** root graphql module/distribution 3.2.13 vs required 3.3.0; source pyproject 4.0.0 vs package `__version__`/installed metadata 3.1.0. Current test counts differ from report. Tox, lint/mypy and proposed guard remain unverified. Do **not** run `uv sync` on root merely because report suggests it. | T01/T16 |
| Q2 | 218 | Eight canonical benchmark-result selection fixed T16a; missing/invalid still fail; archive. | T01/T16a |
| Q3 | 219 | Confirmed test-owned open upload/ASGI spool after direct view dispatch; scoped R09c cleanup accepted21591. No ResourceWarning observed and no production leak inferred. Wider Q3/T16/N6/audit remains open; exact preacceptance wording in R10a archive. | T16/R09c |
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
| N6 | 274 | Report says remaining lint/types/tests are clean. R09a accepted the 23 tracked-test docstring corrections; the current local whole-tree scan still fails with seven DOC002 in ignored postincident profiles. Historical ignored count 58 and original preimages remain recorded, not a clean-CI claim. R09b and broader N6 still need decisions/final evidence. | T17/R09a/R09b |


**R03a evidence locator:** Scoped acceptance21311 and all failures/limits are retained byte-for-byte in `r03a-closure-r08a-preparation/tracker-preclosure.md` (SHA `4fb523786fe8b951ee410acf65aa32160790c5adf3fb93a7628b242a1d418a74`) and the R10a pre-edit archive; wider R03/T15/N6 open.

## Progress and next action

**Recovery:** Complete pre-compaction/acceptance history is byte-for-byte in the R02a pre-edit archive above. Earlier locators and full hashes remain there, including R03a, R01b, retry correction, R01a, initial remaining-pass and T14i preimages; no history or qualification is discarded.

**Next:** 86 checked work units, not 86 fixed claims. SD1/R06a/f/g and FK/reverse-FK/M2M/forward OneToOne SD2/R06b–e accepted; all 15 principal T03–T17 blocks stay OPEN. Ordering/custom/global policy, R05c instance-dependent CREATE, R02b DateTime and R09b ignored profiles remain deferred. Fresh automatic M2M output full5745/7skip/10warn, branch95.45% floor, combined97.61% floor, unit100%, cumulative98.12% are local native3.3 proof, not PG/CI/wheel/dependency-audit/timing. R11 TDD stays PARTIAL; T14g ignored/temp/environment/physical-index/unlisted, R01a unguarded Ruff, R03a original report preimages and R09 original profile/cache preimages remain UNKNOWN. Older evidence remains historical; no tag/publication/remote/PR authority.

**R09 scope/guard incident (partial):** Original ignored-profile and bytecode preimages remain UNKNOWN. Full RED/GREEN/helper/restore chronology and exact qualifications are retained in `r09-global-docstrings-implementation/{README.md,incident-preservation.json,tracked-restoration.json}` and the R10a pre-edit archive; later passes do not repair them.

**Mirror:** Full tracker plus locator at `odd/audit-400-remediation/tasks` (obs15165).
