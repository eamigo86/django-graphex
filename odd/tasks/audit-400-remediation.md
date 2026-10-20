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

**Public API gate:** Explain examples/migration impact and obtain individual approval before incompatible changes. All prior approved policies and their exact scopes remain unchanged and are preserved byte-for-byte in `ls3-subprotocol-preparation/tracker-preedit.md` (49,450 bytes; SHA256 `56b9462a9021ceb476422c81e5703b22afc86e6e7fff2f7a69aab2a2cac91354`), together with the existing accepted task rows/archive chains. This lossless locator replaces only the repeated approval inventory to keep the full recovery mirror below its 50,000-byte storage limit; it does not broaden or revoke any policy. The newly approved L-S3 scope is stated separately below. Strict TDD/docs/coverage >95%; no tags/publication.

**BP-R05C-INSTANCE-CREATE-ATOMIC-001** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

**BP-LS3-SUBPROTOCOL-001** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

**BP-LS2-ONCONNECT-001** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

**BP-LS1-SSE-CONTROLS-001** Approved bounded scope, authority, exact checks and size limits remain unchanged; full wording preserved in `mu2-delete-closeout/tracker-preacceptance.md`. No authority transfers to M-U2.

**L-S1 live validation authority** Approved bounded scope, authority, exact checks and size limits remain unchanged; full wording preserved in `mu2-delete-closeout/tracker-preacceptance.md`. No authority transfers to M-U2.

**L-S1 local delivery** Approved bounded scope, authority, exact checks and size limits remain unchanged; full wording preserved in `mu2-delete-closeout/tracker-preacceptance.md`. No authority transfers to M-U2.

**Quality:** Hint changed/public signatures; Google Args/Returns/Raises, no repeated types/backticks. Tests/docs/changelog with behavior. Pure branch, combined, nonempty patch coverage each >=95.01%; patch otherwise N/A. No exclusion/skip/padding/addopts reset. Check Ruff/format/mypy/docstrings/docs/focal/full/diff; report all failures/skips. No artifact build.

**Cross-surface impact:** Inspect affected test apps, Playground/examples, docs and benchmark declarations per behavior unit; update affected surfaces or record concrete no-change evidence. No benchmark timing/canonical rewrite/public API policy. Omitted affected surfaces need bounded correction before acceptance.

**Implementation route:** Delegated direct, not SDD; broad preparation or 2+ nontrivial files to bounded writer and independent verifier. Conventional work-unit behavior/tests/docs commits; ~400 authored lines advisory, no code-golf. Delivery `ask-on-risk`, chain unresolved; no PR authority.

**Remaining-pass checks:** Exact runners, protected controls, exclusions and historical UNKNOWNs remain unchanged in `mu3-float-closeout/tracker-preacceptance.md`; Strict TDD and Quality above still apply.

## Task sequence

**Archive key:** Every shortened accepted task or ledger row marked `archive` points to the exact pre-compaction wording at `remaining-pass-preparation/tracker-preparation-preimage.md` (49,912 bytes; SHA-256 `442c725454b062a2db6b7b4fab70a68cceea2f613ff691d7b4e202aea0b50a94`). That preimage preserves approvals, failed/partial attempts, limits, and proof locators; compacting a row does not broaden acceptance or close a residual claim.


Unchecked needs evidence; `D` delegates; IDs persist. Prior wording/limits: `t13i-selected-introspection-classifier-implementation/tracker-pre-t13i.md` (SHA `5df41527bccd61ab2b5b36ccc19605162f10ba86d7a9b45c5d99ce31fc02e809`). All pre-T14h wording, proof chronology and qualifications are preserved byte-for-byte at `lm3-enum-cache-triage/tracker-prep-preimage.md` (49,745 bytes; SHA256 `ed104091d7cc73c396abd49e0bc19febbff359361c93bcaac6fc3bb8bac069d0`); shortened completed rows below are locators, not revised acceptance claims. Exact pre-T14i tracker: `lm4-registry-preparation/tracker-prep-preimage.md` (48,899 bytes; SHA256 `9e078429c84b9c9933740afc7ebb4c29f6fa5e0ea5b4473c6ca9173657fe3906`).

| Task | Route | Outcome and acceptance evidence | State |
|---|---|---|---|
| T00 | D, bootstrap | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
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
| T05 | D | A1 default-DB rollback T05a and R05b stable/model-routed nestedrollback accepted; included-Django instance-dependent CREATE R05c accepted22414/57e0aab (two-stage through checks, local rollback). Native ok:false, broader cross-DB and lost-update policies remain open. | [ ] |
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
| T14g | D; human20732/root20769; accepted20835 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
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

| R01 | D; human21002; unchecked | L-S4/R01a, M-U1/R01b, L-S3/R01c, optional L-S2/R01d and approved single-instance L-S1/R01e accepted in bounded scopes. Broader WS/SSE/HA policies and T08 remain open. | [ ] |
| R01a | D; human21002; accepted21102 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01b | D; human21002; accepted21184 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01c-I | D; approval22823; accepted22902; ef598a7 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01c-V | D; accepted22902 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01c-C | Inline; accepted22902; ef598a7/33885c0 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R02 | D; human21002; unchecked | Subscription data delivery M-U2/M-U3/M-U4: separate contract, real-path witnesses, then compatible scoped work units. | [ ] |
| R02a | D; human21002; accepted21577 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R02b | D; accepted22668;33ff878/08c9725 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R03 | D; human21002; unchecked | Directives/scalars: M-U5/M-U6, M-D4/M-D5/M-D6, L-C10/L-C11/L-C13; preserve established SDL/input contracts or defer incompatible policy. | [ ] |
| R03a | D; human21002; accepted21311 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R04 | D; human21002; unchecked | Minor HTTP/pagination/cursor L-C1–6/L-C8/L-C9 and A13 residual; distinguish accepted bounded slices from remaining malformed-input cases. | [ ] |
| R05 | D; human21002/22248; unchecked | Mutations A1/M-D1/M-D2/A10 residuals; R05c populated-parent singlealiasCREATE approved for includedDjango only. Other ok:false/lost-update/crossDB/custombackend policy gaps remain. | [ ] |
| R05a | D; human21002; accepted21526 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R05b | D; human21002; accepted21547 scoped | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R05c | D; human22248/22326/22349; accepted22414 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R06 | D; human21002/21642/21718/21820/21939/22033/22081/22151 | R06a–g accepted bounded outputs/filters. Custom/global policy, L-E3 beyond SITE-B and L-C12 MTI deferred/unproven. | [ ] |
| R06a | D; human21642; accepted21711; BP-SD1-READ-SCOPE-001 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R06b | D; human21718; accepted21796; BP-SD2-FK-FILTER-001 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R06c | D; human21820; accepted21929; BP-SD2-REVERSE-FK-FILTER-001 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R06d | D; human21939; accepted21993; BP-SD2-M2M-FILTER-001 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R06e | D; human22033; accepted22059; BP-SD2-FORWARD-O2O-FILTER-001 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R06f | D; human22081; accepted22121; BP-SD1-O2O-READ-SCOPE-001 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R06g | D; accepted22219;0ee46b9/4cbb458 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R07 | D; human21002; unchecked | Cache/limits A2 retained bytes/aggregate and M-S2 residual: current DEFAULT_PAGE_SIZE=100 already approved T12d, so the report's all-defaults-None wording is stale; byte/aggregate cache quotas and other limits/defaults/width/depth need separate evidence or policy decisions. M-F3 empty-Boolean identities remain unchanged by prior human choice. Count-based LRU is not a byte cap or runtime DoS proof. No R07 source/policy change in R01b. | [ ] |
| R08 | D; human21002; unchecked | Memory/input L-M1 and M-D10 broader SDL/input shapes; verify separately from accepted L-M2–4 internal fixes. | [ ] |
| R08a | D; human21002; accepted21363 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R09 | D; human21002; unchecked | Q1/Q3/Q4/N6 wider tooling block remains open. R09a fixed23tracked findings; R09b fixed7current local ignored-profile DOC002 without unignoring. Current local strict scan0 is not CI proof; historical58findings/original preincident images UNKNOWN remain. | [ ] |
| R09a | D; human21002; accepted21497 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R09b | D; approved22685; accepted22777; f931cb9/e740fb6 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R09c | D; human21002; accepted21591 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R10 | D; human21002; unchecked | Recommendation/negative-proof Q5–10, P1 and N1–5; classify evidence and reasons, not automatic code changes. | [ ] |
| R10a | D; human21002; accepted21610 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R11 | D writer/verification, inline tracking; accepted21639; HISTORY_PARTIAL | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |

| R01d-I | D; approved22923/22957; accepted23010;98956fa | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01d-V | D; accepted23010 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01d-C | Inline; accepted23010;98956fa | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |

**L-S2 pre-edit archive:** `ls2-on-connect-preparation/tracker-preedit.md` preserves the exact49,554-byte prior tracker (SHA256 `9360137064090d9edf454e11599a4969a019a2dc1a9d6fb4706238bdfc783220`), including every shortened R01c/R09b acceptance qualification and historical archive chain. Lossless locators keep the complete mirror below50,000 bytes; no scope/history is revoked or broadened.

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
| M-D2 | 125 | Nested atomic and binding on_commit database-alias subclaims. R05b stable/model routing accepted; populated-parent CREATE guarantee for includedDjango approved22248/R05c pending. No broader cross-DB/custombackend closure. | T05/T08/R05b/R05c |
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
| M-U3 | 165 | Decimal snapshot equality corrected R02a; native DateTime precision/equality/output corrected R02b(22668). Other scalar/entry-path allegations remain separately scoped; no whole-row closure. | T08/R02 |
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
| L-S1 | 207 | Approved opt-in OFF/15s/5 SSE controls/shared authenticated-account Redis cap delivered R01e/7ec2264; real Lua/eight-process single-instance validation passed. HA/failover/partition guarantees remain unproved, outside this bounded closure. | T08/R01e |
| L-S2 | 208 | Approved optional on_connect accepted23010/R01d: authoritative authenticated socket user before ACK/provider/permissions; denied hook4403 without session fallback, malformed configured payload4400; default unchanged. No JWT/backend/session/HTTP/SSE/live-refresh policy or bypass claim. | T08/R01d |
| L-S3 | 209 | Approved exact-offer pre-accept rejection and static actionable diagnostic accepted22902/R01c. Missing/empty/wrong-only offers rejected; exact offer among alternatives accepted. ASGI4406 normally wireHTTP403; browser detail not guaranteed. No authentication/other transport policy change; proof qualifications retained. | T08/R01c |
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
| N6 | 274 | Current local strict scan0 after R09a/R09b; historical23tracked/58earlier ignored/7postincident counts remain. Ignored profiles stay local, originals UNKNOWN; no whole-CI-clean verdict. Wider tests/lint/types claim remains bounded. | T17/R09a/R09b |


**R03a evidence locator:** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.







**R02b original preparation:** `r02b-lossless-datetime-preparation/tracker-preedit.md` preserves exact49,826B prior state/R05c chains. Fullhashes/probe/approvedplan retained in the partial preimage below.

**R02b partial tracker preimage:** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

**L-S1 pre-edit archive:** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

| R01e-I | D; human23051/23232; accepted23298;7ec2264 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01e-V | D, independent + parent; accepted23298 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |
| R01e-C | Inline; human23303 local size exception;7ec2264 | Accepted bounded scope only; exact contract/commits/proof/failures/limits/UNKNOWNs in M-U2 pre-edit archive. No broader closure. | [x] |

**M-U2 pre-edit archive:** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

**BP-MU2-DELETE-MATCH-001** Exact approved scope, commits, checks, failures/UNKNOWNs and archive chains preserved byte-for-byte in `mu6-date-null-preparation/tracker-preedit.md`; no broader authority or closure.

| R02c-I | D | Accepted bounded scope; exact authority/commits/proof/failures/UNKNOWNs in M-U6 pre-edit archive. No broader closure. | [x] |
| R02c-V | D | Accepted bounded scope; exact authority/commits/proof/failures/UNKNOWNs in M-U6 pre-edit archive. No broader closure. | [x] |
| R02c-C | Inline | Accepted bounded scope; exact authority/commits/proof/failures/UNKNOWNs in M-U6 pre-edit archive. No broader closure. | [x] |

**M-U2 final proof:** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

**M-U2 local delivery** Exact approved scope, commits/proof, archive chains, historical failures and UNKNOWNs remain unchanged and preserved byte-for-byte in `mu3-float-preparation/tracker-preedit.md`; no broader closure or authority.

**M-U3 pre-edit archive:** Exact approved scope, commits, checks, failures/UNKNOWNs and archive chains preserved byte-for-byte in `mu6-date-null-preparation/tracker-preedit.md`; no broader authority or closure.

**BP-MU3-FLOAT-EXACT-001** Exact approved scope, commits, checks, failures/UNKNOWNs and archive chains preserved byte-for-byte in `mu6-date-null-preparation/tracker-preedit.md`; no broader authority or closure.

| R02d-I | D | Accepted bounded scope; exact authority/commits/proof/failures/UNKNOWNs in M-U6 pre-edit archive. No broader closure. | [x] |
| R02d-V | D | Accepted bounded scope; exact authority/commits/proof/failures/UNKNOWNs in M-U6 pre-edit archive. No broader closure. | [x] |
| R02d-C | Inline | Accepted bounded scope; exact authority/commits/proof/failures/UNKNOWNs in M-U6 pre-edit archive. No broader closure. | [x] |

**M-U3 closeout archive:** Exact approved scope, commits, checks, failures/UNKNOWNs and archive chains preserved byte-for-byte in `mu6-date-null-preparation/tracker-preedit.md`; no broader authority or closure.

**M-U3 accepted proof:** Exact approved scope, commits, checks, failures/UNKNOWNs and archive chains preserved byte-for-byte in `mu6-date-null-preparation/tracker-preedit.md`; no broader authority or closure.

**M-U6 pre-edit archive:** `mu6-date-null-preparation/tracker-preedit.md` preserves exact 49,731B tracker, SHA`87e080330c786e2dca752890b21621f265da612cb9bae2bf4245f4e714d1b2ac`, including shortened prior policies/proof/limits and all archive chains.

**BP-MU6-DATE-NULL-001** (human23502): only @date(value=None) passes None through, including normal GraphQL NonNull error/bubbling (root may annul data). No other directive, invalid/non-null input, parsing/timezone/localtime/date-only or SDL-type policy change. Strict TDD/docs/branch+combined+nonempty patch>=95.01%; baseline86e99af,cumulative5a155a0. Native diagnostic proof `mu6-date-null-investigation/run-record-v3.json` SHA1ff9198a… is not permanent RED; original setup/serializer and limited preimage/protection qualifications retained.

| R03b-I | D writer; human23502; accepted23550 | Null-only guard + native String/Date/DateTime nullable/root+nested NonNull regressions/docs; permanent RED7fail/3pass, same-byte GREEN10pass; final10PASS. Other directive policies unchanged. | [x] |
| R03b-V | D independent + parent; accepted23550 | Full5868pass/7skip/10warn; branches4416/4624,combined16442/16832; unit2/2,cumulative839/864 raw exits. Related142,Playground61,quality/docs43pages/static5ops PASS; parent10PASS/full frozen bindings. Preservation qualified below. | [x] |
| R03b-C | Inline; accepted23550;1f97d24 | Nine-path/239-line behavior/tests/docs commit verified against accepted disk/staged/Git bytes+modes. Full mirror synchronized. Rollback only this unit. No size exception; RDD OFF; no PR/push/tags/publish. | [x] |

**M-U6 proof/limits:** `mu6-date-null-independent/report.json` SHA7a9b4017… and `mu6-date-null-closeout/tracker-preacceptance.md` retain complete pre-closeout wording. Writer preimages9owned-only, cache metadata changes and initial related/full/docs failures remain qualified. Independent parser failure corrected; unauthorized zero-byte external placeholder retained (`scope-incident.json`), not a clean-preservation verdict. No CI/Postgres/Redis/build/timing claim. M-U6 partial;41 primary pending/limited IDs(not41bugs),7 recommendations separate;107checked/25overlapping unchecked tasks,15principalblocks open.

## Progress and next action

**Recovery:** Prior archive chains and qualifications remain byte-for-byte in `mu3-float-closeout/tracker-preacceptance.md`.

**Next:** Investigate remaining M-U6 date-only-text behavior before proposing any change; other incompatible policies remain gated. No PR/push/tag/publication.

**R09 scope/guard incident (partial):** Original ignored-profile and bytecode preimages remain UNKNOWN. Full RED/GREEN/helper/restore chronology and exact qualifications are retained in `r09-global-docstrings-implementation/{README.md,incident-preservation.json,tracked-restoration.json}` and the R10a pre-edit archive; later passes do not repair them.

**Mirror:** Full tracker plus locator at `odd/audit-400-remediation/tasks` (obs15165).
