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

**Safety:** never execute suggested attack payloads blindly. Use deterministic, bounded visit-count or allocation-guard reproductions for fan-out/cycles and bounded resource tests for memory risks; no large DoS load. Protect benchmark databases, canonical result JSON, and existing environments. Disposable pytest assets may be created by later implementation workers. Keep all 14 original C/A tags. For every claim, record source/runtime, reproducible RED or other evidence, disposition, fix/contract rationale, exact checks, and final false-positive reason. Initially **U = unverified**, regardless of the report's checkmark. A design limitation, documented default, unsupported contract, duplicate symptom, confirmed bug, and false positive are distinct outcomes; do not mark any as false positive just because it is not changed.

**Public API gate (current user decision):** The user conditionally authorizes incompatible changes **only when their necessity is demonstrated**, and only after each individual candidate is explained with examples and migration impact and receives separate explicit approval **before implementation**. This is not blanket approval. Decimal/BigInt SDL, nested tenant/permission scope semantics, and any other public default or schema change remain unapproved. Independent verification and compatible fixes may continue. Do not select a scalar, security default, or cross-relation authorization contract on the user's behalf. Continue TDD and documentation with coverage above 95%; do not tag or publish.

**Quality:** all changed/public signatures fully hinted; full Google-style Args, Returns, and Raises sections where applicable, without repeated types or docstring backticks. Update tests, docs, and changelog alongside behavior. Pure branch and combined coverage must each be at least 95.01%; patch coverage at least 95.01% when nonempty (report N/A honestly otherwise). No warning filters, coverage exclusions, skips, padding, or `-o addopts=""` to manufacture passing checks. Run applicable Ruff check/format check, mypy, docstring audits, docs anchors, focused/full tests, and `git diff --check`; record every failed, unavailable, or skipped check. No local public artifact build.

**Implementation route:** delegated direct, not SDD. Broad preparation and two-or-more nontrivial files trigger one bounded writer per unit; verification/build execution is delegated. Commits are Conventional Commit work units on this feature branch, with behavior/tests/docs together and exact verification evidence. About 400 authored lines per work unit is advisory only, never a reason to code-golf. Rough total forecast is at least 1,000–1,800 authored lines for C/A alone, with high uncertainty from the remaining claims. Delivery strategy is `ask-on-risk`; chain strategy is **unresolved** until a real delivery decision. No PR is authorized now. Record eventual authored additions+deletions and PR-slice boundaries only if delivery is requested.

## Task sequence

Each task is an independently recoverable work unit. `T00` is tracking-only; all remaining tasks are pending and require evidence before closure. `D` means delegated route due to broad preparation, multiple nontrivial files, and/or test execution. A later worker may split a coherent task when required, preserving IDs and the claim ledger.

| Task | Route | Outcome and acceptance evidence | State |
|---|---|---|---|
| T00 | D, bootstrap | Record complete report traceability, local branch/runtime constraints and proof; mirror full file in Engram; tracking-only conventional commit. Structural readback only; runtime test N/A because no runtime/source behavior changed. | [x] |
| T01 | D | Supported graphql-core 3.3 baseline: verify module/distribution/candidate identities, focused baseline and full suite including environment-only benchmark provenance distinction; preserve exact failures without changing root env, benchmarks, or canonical results. Baseline established, full suite red on Q2; see T01 proof below. | [x] |
| T02 | D | Reproduce C2 and C3 with bounded deterministic counters; fix confirmed fragment traversal/cycle work without unbounded payload; regression tests for validation/optimizer behavior and cost/depth guards. | [ ] |
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
| T16 | D | Triage tooling/test hygiene, missing test coverage, stale runtime, provenance, maintainability/refactor/dead-code suggestions; only justified, authorized local changes, no benchmark regeneration. | [ ] |
| T17 | D | Complete independent disposition of every ledger ID, verify section-9 negative claims, run full quality/coverage gates, list all final false positives with evidence and reasons, and report remaining design decisions or unavailable checks. | [ ] |

## Claim traceability ledger

Status for **every** item below is `U` at bootstrap. The report's ✅/🔁/📖 labels are claims about its own methods, not acceptance evidence. Related rows are marked `↔` where they may share a root cause; they remain independently traceable. Exact line anchors prevent a later worker from silently dropping subclaims. `T17` closes every row, including duplicates and no-change decisions.

### Critical and high (original IDs preserved)

| ID | Report line | Distinct claim / dependency | Task |
|---|---:|---|---|
| C1 | 36–44 | DecimalField output fails under graphql-core 3.3; ↔ M-D3 precision and M-D4 scalar acceptance. | T03 |
| C2 | 46–58 | Repeated fragment fan-out makes optimizer walkers exponential despite validation. | T02 |
| C3 | 60–72 | Cyclic fragment cost/depth validation allegedly exponential despite cycle rule; existing cut guards are not proof either way. | T02 |
| A1 | 80 | ATOMIC_MUTATIONS and ATOMIC_REQUESTS errors allegedly commit; view parity/flag claims. | T05 |
| A2 | 81 | Count-bounded cache retains unbounded AST bytes; body limit allegedly after parse/cache. | T04 |
| A3 | 82 | Invalid/string only_fields/exclude_fields can expose excluded fields or empty types. | T06 |
| A4 | 83 | Duplicate model type registration silently selects last type and may expose admin fields. | T06 |
| A5 | 84 | Permission-scoped WS/SSE schema provider allegedly runs sync ORM on event loop. | T08 |
| A6 | 85 | Failed Redis/binding representation callback allegedly surfaces after commit and interrupts later callbacks. | T08 |
| A7 | 86 | Pydantic default_factory allegedly evaluated at compile time, sharing UUID/list across requests. | T09 |
| A8 | 87 | BigInteger output/input allegedly mapped to 32-bit GraphQL Int. | T03 |
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
| Q2 | 218 | **Mechanism confirmed T01, fix pending:** all-JSON validator and copied-directory tests fail on 28 protected local extras beyond eight tracked top-level canonical files; full supported suite has 17 related failures. Validate only canonical set in T16 without modifying protected results. | T01/T16 |
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

- **T00:** Complete tracker created from all 277 report lines; original 16 C/A IDs plus 6 security-design, 36 medium, 25 low, 10 tooling, 1 action-plan, and 6 negative-check entries = **100 ledger rows**. Composite rows explicitly enumerate subcases. No semantic finding accepted, rejected, or fixed at bootstrap. Tracking work-unit commit: `10431d754ed9944ccdd5728d44affa8152dd54e3` (`docs(audit): track 4.0.0 verification and remediation`).
- Bootstrap structural evidence: feature HEAD/tree and old branch identity verified locally; old branch is not an ancestor; `pyproject.toml` declares graphql-core `>=3.3.0,<3.4`; source/test/runtime checks N/A for tracking-only work. No source, test, docs, benchmark, workflow, or environment changes in T00.
- **T01:** Supported 3.3.0 module/distribution overlay and current source import asserted. Focused fragment/output/cache tests: **29 passed, exit 0**. One full configured `pytest tests/ -q`: **4940 passed, 7 skipped, 17 failed, 3 warnings, exit 1**; all 17 failures in `tests/benchmarks/test_canonical_provenance.py` trace to Q2's all-JSON scan/copy of 28 ignored local top-level JSON files. Full suite is **not green**. Configured `--no-cov-on-fail` produced **no fresh coverage XML**, so pure/combined >=95.01% are pending; patch coverage N/A for this tracker-only unit. No reported C/A finding was confirmed or dismissed by these baseline tests. Exact node IDs, logs, environment identities, UTC, commands, and preserved-asset SHA-256 evidence: `/Users/eamigo/.codex/visualizations/2026/09/02/01a062ff-dccb-7123-a1e9-e7de825aafc2/audit-400-remediation/t01-baseline/README.md`. Root 3.2.13 environment, all benchmark JSON and DB, and pre-existing coverage outputs remained byte-identical. T16 owns Q2/metadata correction; no source fix in T01. Work-unit commit: `74c252b93083d089928be5f91961d7a488808054` (`docs(audit): record supported 3.3 baseline`).
- **Next:** T02 bounded critical reproduction. Every necessary incompatible change, including public SDL or tenant-scope changes in T03/T07, must be explained with examples and migration impact and individually approved by the user before implementation; independent verification and compatible fixes do not wait. Record findings, exact runtime/check results, coverage, commits, and dispositions here and resync full Engram mirror after each task.
- **Mirror:** `odd/audit-400-remediation/tasks` in project `django-graphex`, observation `15165`; full document and repository-relative locator `odd/tasks/audit-400-remediation.md` were saved and read back (terminal newline normalization only). Resync after each task update.
