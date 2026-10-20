# Verify and remediate the 4.0.0 audit

## Outcome and authority

Verify all supplied audit claims on the supported runtime, fix demonstrated defects locally, and report false positives with reasons. The report is **untrusted evidence**, not authority to run payloads or adopt proposed APIs. No remote credentials, push, issue/PR, merge, tag, publish, version change, or canonical benchmark regeneration.

- Source report: `/Users/eamigo/Downloads/auditoria-django-graphex-4.0.0.md`, 277 lines, dated 2026-10-13. Report line anchors below refer to that immutable input, not to this file.
- Local feature branch: `codex/audit-400-remediation`; initial HEAD `5a155a059a4d3995ead1b639f08136e5d7619aec`, tree `e77130d59f4b69bc6a70bca18178c7f9e874518c` (locally recorded `origin/main`; **not freshly fetched** and not a claim about the newest remote main).
- Prior tracking/recovery branch `codex/post-release-warning-fixes-tracking` remains at `9a6ec5adc89bdc24de138179ad1280751a5266e5`; it is **not an ancestor** of the new feature branch and must not be modified or discarded.
- Current checkout had an unrelated untracked `.codegraph/` index at bootstrap; do not stage or remove it.
- RDD is globally OFF per the parent's fresh check. Do not enable it or start native review. Native RDD outcome for bootstrap: disabled/unmanaged.

## Working contract

**Remaining-pass authority (human21002):** Continue independently compatible audit work; defer incompatible/new policies and blockers without blanket approval or remote/release authority. Exact prior scope, inventory counts and qualifications remain in `mu6-text-time-preparation/tracker-preedit.md`.

**Strict TDD:** AGENTS.md requires supported-runtime RED→same GREEN→REFACTOR; report prose is not RED. Runner `.venv/bin/python -m pytest`, focal `--no-cov`, full `-q`. Root graphql-core3.2.13 is unsupported (`pyproject.toml` requires 3.3); retained native3.3 overlay path/proof in T01/T08b. Use repo+overlay PYTHONPATH and PYTHONDONTWRITEBYTECODE=1; assert module/distribution/candidate each unit. No env refresh, mixed ABI or unsupported-result credit.

**Safety:** Use bounded witnesses, never blindly run report payloads or large DoS loads. Protect benchmark DBs, canonical JSON, root env, 16 original C/A IDs and 14 existing tags. Disposable pytest assets allowed; no new tags. Record each claim’s source/runtime, evidence/disposition/checks/reason. Report marks are untrusted; no-change alone proves no false positive.

**Public API gate:** Explain examples/migration impact and obtain individual explicit approval before incompatible changes. Prior policy inventories, scope, evidence and qualifications remain exact in `mu6-text-time-preparation/tracker-preedit.md`; no prior approval is broadened or revoked. No tags/publication.

**Accepted prior bounded policies:** BP-R05C-INSTANCE-CREATE-ATOMIC-001, BP-LS3-SUBPROTOCOL-001, BP-LS2-ONCONNECT-001, BP-LS1-SSE-CONTROLS-001, L-S1 live validation and local delivery retain their exact scopes, authority, checks, failures, UNKNOWNs and archive chains in `mu6-text-time-preparation/tracker-preedit.md` and the M-U6 absolute-zone pre-edit archive below. None grants broader closure or policy change.

**Quality:** Hint changed/public signatures; Google Args/Returns/Raises, no repeated types/backticks. Tests/docs/changelog with behavior. Pure branch, combined, nonempty patch coverage each >=95.01%; patch otherwise N/A. No exclusion/skip/padding/addopts reset. Check Ruff/format/mypy/docstrings/docs/focal/full/diff; report all failures/skips. No artifact build.

**Cross-surface impact:** Inspect affected test apps, Playground/examples, docs and benchmark declarations per behavior unit; update affected surfaces or record concrete no-change evidence. No benchmark timing/canonical rewrite/public API policy. Omitted affected surfaces need bounded correction before acceptance.

**Implementation route:** Delegated direct, not SDD; broad preparation or 2+ nontrivial files to bounded writer and independent verifier. Conventional work-unit behavior/tests/docs commits; ~400 authored lines advisory, no code-golf. Delivery `ask-on-risk`, chain unresolved; no PR authority.

**Remaining-pass checks:** Exact runners, protected controls, exclusions and historical UNKNOWNs remain unchanged in `mu3-float-closeout/tracker-preacceptance.md`; Strict TDD and Quality above still apply.

## Task sequence

**Archive key:** Shortened completed task rows below point first to `mu6-naive-zone-preparation/tracker-preedit.md` (48,710 B; SHA-256 `63d5a374e6752498017906ef9c2b6ec65e16540f26c2618c60c48ae1d6a9c520`; mode 0644), the exact pre-R03e tracker. That immutable preimage preserves all completed wording, approvals, proof, failures, UNKNOWNs, limits and older archive chains; shortening never broadens acceptance or closes a residual claim. Its chain includes `remaining-pass-preparation/tracker-preparation-preimage.md` (49,912 B; SHA-256 `442c725454b062a2db6b7b4fab70a68cceea2f613ff691d7b4e202aea0b50a94`), still authoritative for earlier rows.


Unchecked needs evidence; `D` delegates; IDs persist. Prior wording/limits: `t13i-selected-introspection-classifier-implementation/tracker-pre-t13i.md` (SHA `5df41527bccd61ab2b5b36ccc19605162f10ba86d7a9b45c5d99ce31fc02e809`). All pre-T14h wording, proof chronology and qualifications are preserved byte-for-byte at `lm3-enum-cache-triage/tracker-prep-preimage.md` (49,745 bytes; SHA256 `ed104091d7cc73c396abd49e0bc19febbff359361c93bcaac6fc3bb8bac069d0`); shortened completed rows below are locators, not revised acceptance claims. Exact pre-T14i tracker: `lm4-registry-preparation/tracker-prep-preimage.md` (48,899 bytes; SHA256 `9e078429c84b9c9933740afc7ebb4c29f6fa5e0ea5b4473c6ca9173657fe3906`).

| Task | Route | Outcome and acceptance evidence | State |
|---|---|---|---|
| T00 | D, bootstrap | Archived bounded outcome. | [x] |
| T01 | D | Q2 scoped completion; archive. | [x] |
| T02a | D | C3 scoped completion; archive. | [x] |
| T02b | D | Archived bounded outcome. | [x] |
| T03a | D | Archived bounded outcome. | [x] |
| T03b | D | Archived bounded outcome. | [x] |
| T03c | D | Archived bounded outcome. | [x] |
| T03 | D | Reproduce C1/A8/Decimal cases; use compatible fix if proven adequate. For each necessary incompatible SDL candidate, explain examples and migration impact to the user and obtain its separate explicit approval before implementation; output/input regression tests and docs. | [ ] |
| T04 | D | A2 POST body order accepted T04a; A11 per-result output cap accepted T04b. Retained-cache bytes/memory claims still OPEN; no broader resource policy approved. Exact history in `t14e-lc12-implementation/tracker-prep-preimage.md`/T04 proof. | [ ] |
| T04a | D | Archived bounded outcome. | [x] |
| T04b | D | Archived bounded outcome. | [x] |
| T05 | D | A1 default-DB rollback T05a and R05b stable/model-routed nestedrollback accepted; included-Django instance-dependent CREATE R05c accepted22414/57e0aab (two-stage through checks, local rollback). Native ok:false, broader cross-DB and lost-update policies remain open. | [ ] |
| T05a | D | Archived bounded outcome. | [x] |
| T06 | D | A3/A4/M-D7/L-C7 independently accepted; M-S6 is a documented shortcut limitation. Other permission/schema claims remain open, including T07 scope investigations. `t06e-lc7-recheck/README.md`. | [ ] |
| T06a | D | Archived bounded outcome. | [x] |
| T06b-F1 | D | Archived bounded outcome. | [x] |
| T06a-F2 | D | Archived bounded outcome. | [x] |
| T06b | D | Archived bounded outcome. | [x] |
| T06c | D | Archived bounded outcome. | [x] |
| T06e | D | Archived bounded outcome. | [x] |
| T07 | D | SD3/4/5, bounded automatic FK/reverse-FK/OneToOne/M2M outputs R06a/f/g and SD2 R06b–e accepted. Custom/global/newnonnull/unrelated policies excluded; T07 open. | [ ] |
| T07c | D, accepted | Archived bounded outcome. | [x] |
| T07d | D, read-only | Archived bounded outcome. | [x] |
| T07e | D | Archived bounded outcome. | [x] |
| T07f | D | Archived bounded outcome. | [x] |
| T08 | D | Confirm/fix A5/A6 and subscription lifecycle, filters, events, and transport claims; real-user WS/SSE and failure-path tests. | [ ] |
| T08a | D, accepted16725 | Archived bounded outcome. | [x] |
| T08b | D, accepted | Archived bounded outcome. | [x] |
| T08c | D; human20540/root20555–20556; accepted20619 | Archived bounded outcome. | [x] |
| T09 | D | A7/M-D8/M-D9 accepted; other annotation/interface claims remain open. | [ ] |
| T09a | D | Archived bounded outcome. | [x] |
| T09b | D | Archived bounded outcome. | [x] |
| T09c | D | Archived bounded outcome. | [x] |
| T10 | D | A9/T10a and bounded A10/T10b–d accepted; wider A10 open. Residual triage is read-only; no general `full_clean()`/upsert policy approved. | [ ] |
| T10a | D, accepted17162 | Archived bounded outcome. | [x] |
| T10b | D, accepted17234 | Archived bounded outcome. | [x] |
| T10c | D | Archived bounded outcome. | [x] |
| T10d | D, accepted17370 | Archived bounded outcome. | [x] |
| T11 | D | A12/filter types/limits wider block open. T11a exact-null, T11b date-part, T11c A12 AND/to-many and T11d M-F1 compatible slices accepted; M-F3 empty-Boolean policy unchanged. | [ ] |
| T11a | D, accepted17430 | Archived bounded outcome. | [x] |
| T11b | D, accepted17503 | Archived bounded outcome. | [x] |
| T11c | D, accepted17607 | Archived bounded outcome. | [x] |
| T11d | D, accepted17812 | Archived bounded outcome. | [x] |
| T12 | D | Confirm/fix A13 and pagination ordering/count/page boundary claims; backend-specific and in-memory regression tests. | [ ] |
| T12a | D, accepted17645 | Archived bounded outcome. | [x] |
| T12b | D, accepted17715 | Archived bounded outcome. | [x] |
| T12c | D, accepted17780 | Archived bounded outcome. | [x] |
| T12d | D, accepted17944 | Archived bounded outcome. | [x] |
| T12g | D, accepted19564 | Archived bounded outcome. | [x] |
| T12f | D, human18041; accepted18137 | Archived bounded outcome. | [x] |
| T12e | D, human17983; accepted18032 | Archived bounded outcome. | [x] |
| T13 | D | Confirm/fix HTTP/cache/error/introspection/limits and async-view claims, separating documented defaults from defects and optional hardening; each necessary incompatible public-default change needs its own explained user approval before implementation. | [ ] |
| T13a | D, human18167; accepted18241 | Archived bounded outcome. | [x] |
| T13b | D, accepted18271 | Archived bounded outcome. | [x] |
| T13c | D, human18294; accepted18361 | Archived bounded outcome. | [x] |
| T13d | D, human18441; accepted18531 | Archived bounded outcome. | [x] |
| T13d-doc | D, accepted18531; `cbfb9fb` | Archived bounded outcome. | [x] |
| T13e | D, human18554; accepted18627 | Archived bounded outcome. | [x] |
| T13f | D, human18659; accepted18829 | Archived bounded outcome. | [x] |
| T13g | D, accepted18888 | Archived bounded outcome. | [x] |
| T13h | D, accepted18998 | Archived bounded outcome. | [x] |
| T13i | D, accepted19287 | Archived bounded outcome. | [x] |
| T14a | D, accepted19162 | Archived bounded outcome. | [x] |
| T14b | D, parent scope19589; accepted19665 | Archived bounded outcome. | [x] |
| T14c | D, accepted19762 | Archived bounded outcome. | [x] |
| T14d | D, accepted19885 | Archived bounded outcome. | [x] |
| T14e | D, accepted20126 | Archived bounded outcome. | [x] |
| T14f | D, accepted20271; human20198 | Archived bounded outcome. | [x] |
| T14g | D; human20732/root20769; accepted20835 | Archived bounded outcome. | [x] |
| T14h | D; human20843; accepted20879 | Archived bounded outcome. | [x] |
| T14i | D; human20887/root20919; accepted20982 | Archived bounded outcome. | [x] |
| T14 | D | Confirm/fix optimizer selection/concurrency/thread-safety and remaining low-level exception/memory claims where reproducible; bounded tests. | [ ] |
| T15 | D | Confirm/fix scalar, directive, and low-level output-contract claims not already covered; behavior-specific tests/docs. | [ ] |
| T15a | D; human20321; accepted20475 | Archived bounded outcome. | [x] |
| T16a | D | Q2 scoped completion; archive. | [x] |
| T16b | D, accepted | Archived bounded outcome. | [x] |
| T16c | D, accepted17162 | Archived bounded outcome. | [x] |
| T16d | D, accepted18385 | Archived bounded outcome. | [x] |
| T16e | D, accepted19086 | Archived bounded outcome. | [x] |
| T16f | D, accepted19403 | Archived bounded outcome. | [x] |
| T16g | D, accepted20001 | N6 scoped completion; archive. | [x] |
| T16 | D | Wider tooling, coverage, metadata, refactor and dead-code block OPEN; no benchmark regeneration. Q2=T16a, datepart=T16e, GET-body=T16f. Base-reproduced seed1823552487 test-fixture cached-pair leak is fixed in accepted T16g; not a new original audit ID and not N6 closure. | [ ] |
| T17 | D | Complete independent disposition of every ledger ID, verify section-9 negative claims, run full quality/coverage gates, list all final false positives with evidence and reasons, and report remaining design decisions or unavailable checks. | [ ] |

| R01 | D; human21002; unchecked | L-S4/R01a, M-U1/R01b, L-S3/R01c, optional L-S2/R01d and approved single-instance L-S1/R01e accepted in bounded scopes. Broader WS/SSE/HA policies and T08 remain open. | [ ] |
| R01a | D; human21002; accepted21102 | Archived bounded outcome. | [x] |
| R01b | D; human21002; accepted21184 | Archived bounded outcome. | [x] |
| R01c-I | D; approval22823; accepted22902; ef598a7 | Archived bounded outcome. | [x] |
| R01c-V | D; accepted22902 | Archived bounded outcome. | [x] |
| R01c-C | Inline; accepted22902; ef598a7/33885c0 | Archived bounded outcome. | [x] |
| R02 | D; human21002; unchecked | Subscription data delivery M-U2/M-U3/M-U4: separate contract, real-path witnesses, then compatible scoped work units. | [ ] |
| R02a | D; human21002; accepted21577 | Archived bounded outcome. | [x] |
| R02b | D; accepted22668;33ff878/08c9725 | Archived bounded outcome. | [x] |
| R03 | D; human21002; unchecked | Directives/scalars: M-U5/M-U6, M-D4/M-D5/M-D6, L-C10/L-C11/L-C13; preserve established SDL/input contracts or defer incompatible policy. | [ ] |
| R03a | D; human21002; accepted21311 | Archived bounded outcome. | [x] |
| R04 | D; human21002; unchecked | Minor HTTP/pagination/cursor L-C1–6/L-C8/L-C9 and A13 residual; distinguish accepted bounded slices from remaining malformed-input cases. | [ ] |
| R05 | D; human21002/22248; unchecked | Mutations A1/M-D1/M-D2/A10 residuals; R05c populated-parent singlealiasCREATE approved for includedDjango only. Other ok:false/lost-update/crossDB/custombackend policy gaps remain. | [ ] |
| R05a | D; human21002; accepted21526 | Archived bounded outcome. | [x] |
| R05b | D; human21002; accepted21547 scoped | Archived bounded outcome. | [x] |
| R05c | D; human22248/22326/22349; accepted22414 | Archived bounded outcome. | [x] |
| R06 | D; human21002/21642/21718/21820/21939/22033/22081/22151 | R06a–g accepted bounded outputs/filters. Custom/global policy, L-E3 beyond SITE-B and L-C12 MTI deferred/unproven. | [ ] |
| R06a | D; human21642; accepted21711; BP-SD1-READ-SCOPE-001 | Archived bounded outcome. | [x] |
| R06b | D; human21718; accepted21796; BP-SD2-FK-FILTER-001 | Archived bounded outcome. | [x] |
| R06c | D; human21820; accepted21929; BP-SD2-REVERSE-FK-FILTER-001 | Archived bounded outcome. | [x] |
| R06d | D; human21939; accepted21993; BP-SD2-M2M-FILTER-001 | Archived bounded outcome. | [x] |
| R06e | D; human22033; accepted22059; BP-SD2-FORWARD-O2O-FILTER-001 | Archived bounded outcome. | [x] |
| R06f | D; human22081; accepted22121; BP-SD1-O2O-READ-SCOPE-001 | Archived bounded outcome. | [x] |
| R06g | D; accepted22219;0ee46b9/4cbb458 | Archived bounded outcome. | [x] |
| R07 | D; human21002; unchecked | Cache/limits A2 retained bytes/aggregate and M-S2 residual: current DEFAULT_PAGE_SIZE=100 already approved T12d, so the report's all-defaults-None wording is stale; byte/aggregate cache quotas and other limits/defaults/width/depth need separate evidence or policy decisions. M-F3 empty-Boolean identities remain unchanged by prior human choice. Count-based LRU is not a byte cap or runtime DoS proof. No R07 source/policy change in R01b. | [ ] |
| R08 | D; human21002; unchecked | Memory/input L-M1 and M-D10 broader SDL/input shapes; verify separately from accepted L-M2–4 internal fixes. | [ ] |
| R08a | D; human21002; accepted21363 | Archived bounded outcome. | [x] |
| R09 | D; human21002; unchecked | Q1/Q3/Q4/N6 wider tooling block remains open. R09a fixed23tracked findings; R09b fixed7current local ignored-profile DOC002 without unignoring. Current local strict scan0 is not CI proof; historical58findings/original preincident images UNKNOWN remain. | [ ] |
| R09a | D; human21002; accepted21497 | Archived bounded outcome. | [x] |
| R09b | D; approved22685; accepted22777; f931cb9/e740fb6 | Archived bounded outcome. | [x] |
| R09c | D; human21002; accepted21591 | Archived bounded outcome. | [x] |
| R10 | D; human21002; unchecked | Recommendation/negative-proof Q5–10, P1 and N1–5; classify evidence and reasons, not automatic code changes. | [ ] |
| R10a | D; human21002; accepted21610 | Archived bounded outcome. | [x] |
| R11 | D writer/verification, inline tracking; accepted21639; HISTORY_PARTIAL | Archived bounded outcome. | [x] |

| R01d-I | D; approved22923/22957; accepted23010;98956fa | Archived bounded outcome. | [x] |
| R01d-V | D; accepted23010 | Archived bounded outcome. | [x] |
| R01d-C | Inline; accepted23010;98956fa | Archived bounded outcome. | [x] |

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
| M-U6 | 168 | Bounded date and directive-only ASCII case slices retained; guarded numeric-null passthrough R03h accepted24012. Schema names, other values and legacy other-character handling unchanged. Final whole-ID disposition/other input-contract scope remains for T17; no automatic broader closure. | T15 |
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


**M-U6 absolute-zone pre-edit archive:** `mu6-absolute-zone-preparation/tracker-preedit.md` (49,894 B; SHA-256 `bcd21eaa1aa84ac502945b920c398a91aad580703972415dcec31f2002fa7ed4`; mode 0644). It preserves all earlier wording, proof, qualifications, UNKNOWNs and archive chains. The exact R03h pre-edit archive below also preserves this pointer; no prior acceptance or residual claim is changed.

| Task | Route and retained bounded outcome | State |
|---|---|---|
| R01e-I | Scoped accepted; pre-R03e archive. | [x] |
| R01e-V | Scoped accepted; pre-R03e archive. | [x] |
| R01e-C | Scoped accepted; pre-R03e archive. | [x] |
| R02c-I | Scoped accepted; pre-R03e archive. | [x] |
| R02c-V | Scoped accepted; pre-R03e archive. | [x] |
| R02c-C | Scoped accepted; pre-R03e archive. | [x] |
| R02d-I | Scoped accepted; pre-R03e archive. | [x] |
| R02d-V | Scoped accepted; pre-R03e archive. | [x] |
| R02d-C | Scoped accepted; pre-R03e archive. | [x] |
| R03b-I | Scoped accepted; pre-R03e archive. | [x] |
| R03b-V | Scoped accepted; pre-R03e archive. | [x] |
| R03b-C | Scoped accepted; pre-R03e archive. | [x] |
| R03c-I | Scoped accepted; pre-R03e archive. | [x] |
| R03c-V | Scoped accepted; pre-R03e archive. | [x] |
| R03c-C | Scoped accepted; pre-R03e archive. | [x] |

**BP-MU6-TEXT-TIME-001 retained:** Human23567 approved omitted TIME in accepted TEXT -> zero only; missing DATE, explicit parts/zone, Python/None, relative path, SDL and other directives unchanged. Prior full 5,874pass/7skip/10warn; raw4,418/4,626=95.5036748811%, combined16,447/16,837=97.6836728633% (NOT R03e proof). M-U6 partial; 100 IDs, 41 primary pending/limited (not bugs), 7 recommendations, 15 principal blocks. Before R03d:110 checked/25 overlap-unchecked; after its three tasks:113/25. Full scope, TDD/helper/guard gaps and history in exact pre-R03e and older archives.

**BP-MU6-ABSOLUTE-ZONE-001** (human23667; accepted23732): every absolute `@date` format (`default`, `iso`, `js`/`javascript`, custom) converts originally aware Python `datetime` or TEXT with explicit numeric/Z offset to Django's active zone, preserving its instant and allowing date rollover. Relative formats, originally timezone-less/named-only TEXT under this older approval, naive Python/date/time/bytes/numeric/other kinds, missing-date/time defaults, None, SDL/scalars/directive API and other directives stayed unchanged. Human23759 separately changes ONLY genuinely timezone-less TEXT below; no broader policy follows.

| Task | Route, acceptance and checks | State |
|---|---|---|
| R03d-I | D; accepted23732; `dc556059c5c06e5d21bcf63388535901ffe3979a`. | [x] |
| R03d-V | D; accepted23732. | [x] |
| R03d-C | Inline; accepted23732; 455 authored lines, no PR. | [x] |

**R03d:** Exact native RED/GREEN, checks, failures, limits and archive chain are lossless in the R03h pre-edit archive below. Only approved absolute-zone slice closed.

**BP-MU6-NAIVE-ZONE-001** (human23759; R03e only): accepted GENUINELY timezone-less TEXT passed to `@date` uses its written wall clock in Django's **active** timezone for every absolute format (`default`, `iso`, `js`/`javascript`, custom) and both relative formats (`time ago`, `time ago 2d`), regardless of `USE_TZ`. Attach the zone; do not convert an assumed UTC instant. Keep missing-DATE/current-date and omitted-TIME/zero defaults, None, other input kinds and naive Python behavior. Prior numeric/Z TEXT absolute conversion (human23667) remains; numeric/Z relative, valid named UTC/GMT-only, and unknown-name fallback/warnings (e.g. XYZ) stay unchanged. Do not add a DST gap/fold policy, setting, dependency, API, SDL, scalar or other-directive change. Preserve accepted `(EET)`, RFC-year, nonterminal-offset and Z regressions. M-U6 remains partial; case conversion and number/currency null families remain open.

| Task | Route, acceptance and checks | State |
|---|---|---|
| R03e-I | D; human23759; accepted23842; `9faf5be77ccba11e18822b1bfd44aba66241da89`. | [x] |
| R03e-V | D; accepted23842. | [x] |
| R03e-C | Inline; accepted23842; 403 authored lines, no PR. | [x] |

**R03e:** Exact TDD, counts, failed/UNKNOWN checks, rollback and history are lossless in the R03h pre-edit archive below. R03e alone closed; M-U6 partial.

**Inherited offset follow-up (NOT R03e regression):** Independent baseline parity proves adjacent numeric zero offsets such as `2026-01-10T00:30+00:00` and `+0000` are rejected by the old regex negative-digit lookbehind, so absolute output stays UTC while equivalent Z localizes. Initial matrix assertion against assumed correctness failed; original script/output retained and corrected HEAD/current parity then passed. This residual is within human23667's prior all-offset conversion approval, not a new product policy or permission to change named zones/relative/defaults.

| Task | Route and retained evidence | State |
|---|---|---|
| R03d-Z | D; accepted23855; inherited offset gap, not R03e regression. | [x] |
| R03f-I | D; accepted23855; RED2/same-byte GREEN2; `2ca275cd475d209024d87ae1dee7cdb2fb7e1665`. | [x] |
| R03f-V | D; accepted23855; direct Python branch 0/0 N/A. | [x] |
| R03f-C | Inline; accepted23855; 100 authored lines, no PR. | [x] |

**R03f:** Exact preparation, checks, failures, limits and archive chain are lossless in the R03h pre-edit archive below. Adjacent numeric-zero absolute conversion only; M-U6 partial; RDD OFF.

**BP-MU6-CASE-001 (human23892; R03g only):** Normalize only the output of `@camel_case`, `@snake_case`, and `@kebab_case` from words separated by spaces, underscores or hyphens and from camel/Pascal boundaries, including acronym blocks. For example, `orderTotal` becomes `orderTotal`/`order_total`/`order-total`, and `HTTPServer` becomes `httpServer`/`http_server`/`http-server` in directive order. Preserve None, Python coercion, other directives, and already-normalized idempotence. Do not change schema field/argument names, SDL, settings, dependencies, shared `_strconv` helpers, or `utils.to_kebab_case`; consult the parent before any other incompatible boundary policy. Human approval does not close number/currency null families or wider M-U6.

| Task | Route, intended outcome and checks | State |
|---|---|---|
| R03g-I | D; human23892; accepted23933; directive-local `4b82906b44a4af22fad7502c291f9baeb29ab371`. | [x] |
| R03g-V | D; accepted23933. | [x] |
| R03g-C | Inline; accepted23933; 324 authored lines, no PR. | [x] |

**R03g:** Exact full proof/limits and archive chain are lossless in the pre-edit archive below. Native RED6/same-byte GREEN6 were recorded, but original RED test/source preimages and first-edit time were not retained; fresh bound-HEAD causality does not reconstruct history. 5,931 pass/7 skip/10 warn; raw branch 4,437/4,644=95.542636%, combined 16,515/16,903=97.704549%, direct 8/8 and cumulative 859/884 exits. Only approved directive case slice closed; M-U6 partial, RDD OFF.

**Current audit state:** 126 checked/25 overlap-unchecked;100 claim IDs,15 principal OPEN,41 pending/limited ID records(not41bugs)+7 recommendations. R03h closes only the approved numeric-null slice; final whole-ID disposition remains for T17.

**R03h pre-edit archive:** `mu6-number-null-preparation/tracker-preedit.md` (49,892 B; SHA-256 `03bccbb505315e47ccb9555d2fb8e75d115b39d3f93d8cca091278cf3e26fbee`; mode 0644) retains exact pre-compaction R03d/e/f/g wording, approvals, proof, failures, UNKNOWNs, limitations and all older archive chains. Shortening completed history changes no acceptance or residual claim.

**BP-MU6-NUMERIC-NULL-001 (human23947; R03h only):** `@number` and `@currency` must return Python None as GraphQL null, not `0.00`/`$0.00`; normal GraphQL NonNull error/bubbling applies. Retain all validation/caps: `@number` width/precision cap runs before the type gate even on None; applicable non-Int/Float format validation still rejects invalid `'.2q'` on None; oversized caps reject all types. Preserve raw Int/Float None, `0`, `'0'`, False, empty string and all other falsy/coercion/symbol/default behavior. No other numeric policy, directive, shared helper, schema/SDL, setting or dependency change; consult parent on incompatible extensions. M-U6 remains partial.

| Task | Route, intended outcome and checks | State |
|---|---|---|
| R03h-I | D writer; human23947, accepted24012. Guarded null passthrough, ordinary NonNull bubbling; current cap/typegate/format and other-value policies retained. Original RED test/source archived, ordered RED4→edit→same-byte GREEN4 verified. Feature `e84090e6411e95b4a5a9b2378ee8c8d07164cb52`. | [x] |
| R03h-V | D independent+parent; accepted24012. Fresh native matrix127rows/focal87; retained full5953pass/7skip/10warn, writerfocal191/related269, quality/docs43/Playground61/static5 audited,NOT rerun. Raw4439/4646=95.544554%,combined97.705228%;direct4/4lines2/2exits,cumulative861/886=97.178330%. Parent22PASS. | [x] |
| R03h-C | Inline local feature `e84090e6411e95b4a5a9b2378ee8c8d07164cb52`,10paths453authoredlines; advisory overrun retains tests/docs, no PR authority. Exact accepted disk/staged/Git blobs+modes. RDD OFF; no PR/push/tag/pub/build/timing. | [x] |

**R03h closeout:** Acceptance24012 under human23947/BP-MU6-NUMERIC-NULL-001. Exact 47,001B preclosure tracker archived at `mu6-number-null-closeout/tracker-preclosure.md` (SHA-256 `720803c7baa222898bd8d0e0571d28637320c23f34dc91daec882f2e67a70f0f`,mode0644). Writer `mu6-number-null-implementation/manifest.json` SHA1b01358f…; independent `mu6-number-null-independent/manifest.json` SHAb6d37abc1dae33abb9fb0f87805bdaffab2da2830ac28acdf7f330dfc6af44f0; parent `mu6-number-null-closeout/parent-spot.json` SHAd3a395ab…(22PASS,779finite source/candidate paths+Git guards). Sourceea396ad5…/newtestcf612300…/mode0644. Original RED test862f3acf…/source74bff17f… and ordered first-edit/identical-byte GREEN records were retained contemporaneously and verified. Exact historical writer argv/full environment unavailable after its compaction; no reconstruction claimed, fresh independent/parent commands captured exactly. All required retained outcomes/log hashes/runtime assertions validated. Actual5960 unique JUnit cases vs aggregate5983(+23 unexplained),zero errors/failures. Cumulative actual hits1958/1966 vs branch-sensitive1933/1966;actual exits861/886. Direct2/2 exits belong to Currency; Number ternary has no separate XML branch instrumentation. SDL changed only Number/Currency descriptions, not names/arguments/types/locations; no full-byte identity claim. Writer legacy assertion/static parser/inventory attempts, parent preparation header correction, final private-helper docstring clarification and verifier frozen-AST harness failure remain preserved; final source verified after correction. Seven skips(5PG,optional multiselect,retiredGraphene),10 existing warnings. Independent fresh matrix/focal; full/quality/docs/Playground/static proof audited,not rerun independently. Playground has no null-output example to change(61PASS); five benchmark queries use no numeric directives, canonical results/DB untouched. Finite14tags/protected branch unchanged; 101 independent JSON hashes vs writer selected67 are distinct inventories; DB checks lstat-only; CodeGraph directory-mtime watcher qualification retained. No livePG/Redis/CI/wheel/timing/remote/publication. Rollback only ten feature paths against parent3cacd9f, keep tracker/prior fixes/proof.

## Progress and next action

**Recovery:** Prior archive chains and qualifications remain byte-for-byte in `mu3-float-closeout/tracker-preacceptance.md`.

**Next:** R03h is locally complete. Investigate M-D5 JSON-string coercion read-only next, distinguishing text such as "123" from numeric 123; consult before any incompatible scalar policy. Wider audit residuals and final ID disposition remain open. No PR/push/tag/publication.

**R09 scope/guard incident (partial):** Original ignored-profile and bytecode preimages remain UNKNOWN. Full RED/GREEN/helper/restore chronology and exact qualifications are retained in `r09-global-docstrings-implementation/{README.md,incident-preservation.json,tracked-restoration.json}` and the R10a pre-edit archive; later passes do not repair them.

**Mirror:** Full tracker plus locator at parent-owned `odd/audit-400-remediation/tasks` (obs15165); require exact readback after each update.
