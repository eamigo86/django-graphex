# django-graphex 4.0.0 audit: disposition and remaining decisions

This is the local, source-verified disposition of the 100 IDs in the supplied
4.0.0 audit. It records what changed, what was merely clarified, and what still
needs a product or compatibility decision. It is **not a release announcement**,
not a claim that all 100 issues were fixed, and not authority to change public
defaults.
The original report was treated as an allegation; examples and test locators
below describe bounded evidence, not universal guarantees.

## Read this first

| Outcome | IDs | Meaning |
|---|---:|---|
| Bounded fix | 41 | A particular demonstrated behavior was corrected and regression-tested; related subclaims may remain. |
| Partial or residual | 26 | A slice is fixed or observed, but another subcase, backend, or policy remains open. |
| Contract or premise clarification | 9 | The reported expectation differs from the documented/current contract; no blanket runtime fix is implied. |
| Recommendation | 7 | Maintainability or coverage work, not seven extra runtime bugs. |
| Limited negative check | 6 | A proposed reassuring claim has only bounded evidence or is imprecisely worded; these are not six fixes. |
| Decision deferred | 11 | A new behavior, compatibility, security, or resource policy needs explicit design approval. |

Thus **41 does not mean 41 fully closed issues**. The 26 partial rows contain
additional decisions, and accepted work units do not automatically close their
parent areas. This report preserves the report's IDs and order exactly once in
the primary table. The status is the *primary disposition* of a multi-part ID,
not a verdict on every possible subcase.

For migration planning, start with the
[4.0 upgrade guide](UPGRADE-4.0.md), then the
[security](usage/security.md), [mutation](usage/mutations.md),
[pagination](usage/pagination.md), [cache](usage/caching.md), and
[subscription](usage/subscriptions.md) guides for current contracts.
The evidence column is a representative in-repository test, implementation,
guide, or the detailed audit work tracker at
`odd/tasks/audit-400-remediation.md`;
it is a locator, not a claim that one file proves every clause in its row.
The tracker retains precise work-unit approvals, rejected attempts and external
proof filenames. Paths here are repository-relative; no private machine path is
needed to use the report.

## Examples of corrected and unchanged behavior

### Numeric precision, fragments, and filters

- A BigInteger such as `9007199254740993` is emitted as a decimal **string**
  rather than a lossy JavaScript-number-sized Float. Decimal output also avoids
  losing the difference between `9007199254740993` and
  `9007199254740994`. This does not redefine relation IDs, enum values,
  non-finite Decimal inputs, or SQLite reload rounding. See
  `tests/core/test_bigint.py` and `tests/core/test_decimal_output.py`.
- An operation whose fragments cycle is rejected with a bounded
  `GraphQLError` before cost/depth evaluation recurses. Fragment effects use
  source order; a separate duplicate FieldNode policy was not changed. See
  `tests/test_fragment_cycles.py` and `tests/test_fragment_fanout.py`.
- Generated FK/M2M mutation input checks reject a **hidden destination ID**;
  the permission boundary for automatic output relation traversal remains
  field-level. A root `get_queryset` hook does not turn every FK or reverse-FK
  read into a globally scoped destination query. Joined filters can still
  reveal a hidden-row match under the documented model; a new strict-scope
  policy is deferred. See `tests/test_destination_link_scope.py` and
  `tests/test_permission_relation_bypass.py`.
- For finite typed subscription filters, `Decimal("1.0")` matches an
  event-time JSON-safe snapshot of `"1.00"`, including valid high-precision
  model values. The match does not fetch a later row. DateTime microseconds,
  delete-time snapshot semantics, and String-valued scopes are distinct
  contracts. See `tests/subscriptions/test_decimal_snapshot_filter.py`.

### Mutations, transport, and cache

- A GraphQL error during the covered default-database nested mutation rolls
  back sibling writes. A native mutation result with `ok: false` is not itself
  a GraphQL error, and cross-database writes are not one atomic transaction.
  Separately, a partial input assigns supplied fields but a model `save()`
  can issue a full SQL UPDATE: a stale instance can overwrite an omitted field.
  No automatic `update_fields`/lost-update policy was introduced. See
  `tests/test_views_atomic_errors.py` and the [mutation guide](usage/mutations.md).
- Automatic subscription broadcasts come from `post_save` and
  `post_delete` and are scheduled after the write's commit. Bulk operations,
  `QuerySet.update`, and M2M additions do not emit those model signals.
  `Subscription.get_binding().broadcast(action, instance)` is an immediate
  manual send, not an automatic commit callback; application-managed hooks
  should use a fresh instance after the outermost commit when that timing is
  required. See the [subscription guide](usage/subscriptions.md).
- The cache privacy gate rejects **any cookie**. A cookie-free **cache miss**
  enters the decorated view and `ensure_csrf_cookie` can set
  `csrftoken`; a following cookie-bearing browser request bypasses cache.
  A cookie-free **cache hit** returns before that dispatch and does **not**
  itself set `Set-Cookie`, so that client can remain eligible. Do not disable
  CSRF to seek cache hits. See `tests/test_views_cache_cookie_bypass.py`
  and the [cache guide](usage/caching.md).
- A public model JSONField receiving the string `"123"` keeps a string
  through input, DB reload, and output. The distinct `JSONString` scalar
  intentionally decodes JSON text `"123"` to integer `123`; these
  contracts must not be collapsed into “all JSON strings change type.”

### Pagination and negative checks

- The bounded SQLite cursor case uses NULL last ascending / first descending
  on DB and materialized-list paths, including pageInfo continuation.
  `LimitOffsetGraphqlPagination` and `PageGraphqlPagination` inherit the
  database's NULL placement for a queryset; their in-memory paths can differ.
  Applications may pass an explicit server-side
  `F(...).asc(nulls_last=True)` or
  `F(...).desc(nulls_first=True)`. Uniform ordering would be a separate
  compatibility decision, not a correction already made here.
- `page: -1` is a fixed-size **tail window**, not necessarily the shorter
  final remainder of positive page numbering. The exact SITE-B filtered
  prefetch allegation was contradicted by a public SQLite witness: the child
  optimize hook ran once, visible rows remained filtered, and one batched
  predicate query served the results. This does not prove every optimizer
  branch or database backend.
- `MUTATION_ERRORS_FLAG` is live; similarly named compiler/registry methods
  cannot all be declared dead from a name-only search. The permission schema
  cache uses an effective permission signature, not a unique per-user key.
  Core `MaxIntrospectionDepthRule` rejected a bounded nested introspection
  query, whereas the custom `MAX_QUERY_DEPTH` setting concerns a different
  rule. None of these observations proves universal access, DoS, or CI safety.

## All 100 original claims

Statuses are intentionally narrow. “Bounded-fixed” means the described slice
has accepted regression evidence, not every adjacent behavior. “Contract”
means a correction to an allegation or a documented boundary, not a new
security guarantee. “Negative-limited” means the reassuring statement needs
qualification. Each row gives a compact case, outcome or remaining limit.

| ID | Status | Finding, outcome, and limit | Evidence |
|---|---|---|---|
| C1 | bounded-fixed | Decimal primary keys no longer pass through Float/null conversion; distinct Decimal output and non-finite policies remain separate. | `tests/core/test_decimal_output.py` |
| C2 | bounded-fixed | Fragment-dependent selections now retain source order; duplicate FieldNode behavior was not changed. | `tests/test_fragment_fanout.py` |
| C3 | bounded-fixed | A shared fragment cycle is rejected as GraphQLError before the cost/depth walker can recurse indefinitely. | `tests/test_fragment_cycles.py` |
| A1 | partial | A GraphQL error rolls back covered default-DB sibling writes; native `ok: false`, multi-DB atomicity, and stale-row overwrites remain separate. | `tests/test_views_atomic_errors.py` |
| A2 | partial | The POST body-size guard runs before GraphQL body parsing; retained AST/cache bytes and aggregate memory are not capped by that change. | `tests/test_views_body_cap_cache.py` |
| A3 | bounded-fixed | Invalid output field selectors are rejected rather than silently bypassing the selection gate; this is not a proof about every unauthenticated request. | `tests/test_output_selector_validation.py` |
| A4 | bounded-fixed | Two different output types cannot silently take the same registered name; independent registry/fork behavior remains distinct. | `tests/test_output_registration_conflict.py` |
| A5 | bounded-fixed | A cold Django user in WS/SSE receives the covered permission pruning; a fake-user control does not prove every authentication source. | `tests/subscriptions/test_transport_real_user_resolution.py` |
| A6 | bounded-fixed | Automatic notification failures are best-effort rather than raising through model writes; manual broadcasts remain strict and delivery is not guaranteed. | `tests/subscriptions/test_automatic_best_effort.py` |
| A7 | bounded-fixed | Each input field's runtime factory executes independently instead of leaking a prior field's value. | `tests/core/test_input_factory_per_object.py` |
| A8 | bounded-fixed | A BigInteger value above JavaScript's exact-number range serializes as a decimal string; relation IDs and enum behavior are separate. | `tests/core/test_bigint.py` |
| A9 | bounded-fixed | Generated delete errors redact underlying database detail; arbitrary DB exceptions were not given a blanket catch. | `tests/test_generated_delete_security.py` |
| A10 | partial | Email input, two positive-number fields, and generated DB-error redaction have bounded fixes; a general full-clean/upsert policy remains open. | `tests/core/test_positive_input_validation.py` |
| A11 | bounded-fixed | A single result is bounded by a Unicode-aware output cap; an aggregate multi-result response quota was not added. | `tests/test_replace_output_limit.py` |
| A12 | bounded-fixed | AND across a to-many relation can match independent related rows; one relation predicate still uses same-row semantics. | `tests/test_and_many_filtering.py` |
| A13 | partial | valid Float/Decimal/UUID continuation + invalid decoded bounds; other cursor policies open. | `tests/test_pagination_cursor_typed_http.py` |
| SD1 | partial | confirmed automatic FK/reverse-FK relation traversal bypasses destination get_queryset under documented field-level scope; O2O/M2M unprobed and global policy unapproved. | `tests/test_permission_relation_bypass.py` |
| SD2 | partial | hidden-row ORM-join oracle confirmed; pruning/masking pass; M2M unprobed. | `tests/test_schema_pruner_filter_scope.py` |
| SD3 | bounded-fixed | Generated FK/M2M destination IDs are checked against the caller's visible choices; this does not make all relation reads globally scoped. | `tests/test_destination_link_scope.py` |
| SD4 | bounded-fixed | hostless nullable reverse-FK orphan adoption denied only. | `tests/test_nested_sd4_orphan_scope.py` |
| SD5 | bounded-fixed | flat GFK metadata pruned on target read/scope denial; not global ACL. | `tests/test_flat_gfk_pruned_security.py` |
| SD6 | recommendation | strict_scope/system-check recommendation; public semantics need decision. | `docs/usage/permission-scoped-schema.md` |
| M-S1 | bounded-fixed | variable-backed cost limits; no hard memory/DB cap. | `tests/test_cost_variable_http.py` |
| M-S2 | partial | default page size 100 already fixed; other defaults/width/depth unverified/policy, LRU not byte-cap proof. | `docs/usage/query-limits.md` |
| M-S3 | contract | The guide now states the configured introspection middleware requirement; the runtime default itself did not change. | `tests/test_introspection_docs.py` |
| M-S4 | bounded-fixed | Production-mode HTTP errors no longer expose the covered internal detail; this is a bounded response contract, not a blanket leak audit. | `tests/test_http_internal_error_diagnostics.py` |
| M-S5 | bounded-fixed | GET cache-key components are length-framed so adjacent values cannot collide inside one identity partition; cross-identity policy is separate. | `tests/test_views_cache_key_framing.py` |
| M-S6 | contract | shortcut required_perms raises TypeError; lowercase field works; untagged public documented. | `tests/test_permission_keyword_boundaries.py` |
| M-D1 | partial | external current native 3.3 witness shows sequential stale backend instance overwrites separately updated bio; not a threaded/PostgreSQL race. update_fields policy deferred for auto_now/custom save behavior. | `docs/usage/mutations.md` |
| M-D2 | partial | Stable/model-routed CREATE and existing-state UPDATE use their write alias for nested rollback; instance-dependent CREATE routing and cross-DB atomicity remain open. | `tests/test_routed_nested_atomic.py` |
| M-D3 | partial | Decimal output avoids Float precision loss; SQLite reload rounding and input coercion remain separate. | `tests/core/test_decimal_output.py` |
| M-D4 | partial | public mutation rejects NaN/±Infinity/1e1000 structurally/no save; exact 1E+999999999 untested. | `docs/usage/mutations.md` |
| M-D5 | contract | Public model JSONField input string '123' stays a string through DB/output; separate JSONString intentionally decodes JSON text to integer 123. | `tests/test_explicit_null_and_json_input.py` |
| M-D6 | decision-deferred | Undefined list/infinity errors require new scalar policy. | `docs/usage/mutations.md` |
| M-D7 | bounded-fixed | incompatible same-name choices rejected; reordered equivalent kept. | `tests/core/test_choices_enum_name_collisions.py` |
| M-D8 | bounded-fixed | reserved-name construction fixed; inherited-hook history qualified. | `tests/core/test_reserved_model_fields.py` |
| M-D9 | bounded-fixed | interface implementor name honored; general type rename unapproved. | `tests/test_model_type_list_type_name.py` |
| M-D10 | partial | Unsupported Literal/dict/set/Union input annotations still fall back to String, now with a diagnostic warning; no conversion policy was added. | `tests/core/test_input_typing_fallback_warnings.py` |
| M-F1 | bounded-fixed | nested related datepart/PK shadow fixed; SDL/null/A12 separate. | `tests/test_filter_lookup_boundaries.py` |
| M-F2 | bounded-fixed | numeric Date/DateTime parts typed Int; whole-value/TimeField policy unchanged. | `tests/test_datepart_filtering.py` |
| M-F3 | partial | exact:null/omission only; broader Boolean identities open. | `tests/test_exact_null_filtering.py` |
| M-F4 | bounded-fixed | explicit page:null equals omission; zero/negative unchanged. | `tests/test_pagination_page_null_http.py` |
| M-F5 | bounded-fixed | model-backed PK-ASC tie-break; offset/random unaffected. | `tests/test_pagination_pk_tiebreak.py` |
| M-F6 | bounded-fixed | no full fetch on negative-page count-error fallback; not universal DB proof. | `tests/test_negative_page_count_error_http.py` |
| M-F7 | bounded-fixed | omitted-page default fixed/documented; explicit None legacy unchanged. | `tests/test_default_page_size_http.py` |
| M-H1 | bounded-fixed | batch HTTP400 prior data/error/stop; prior writes persist, no batch transaction. | `tests/test_batch_http_error_partial.py` |
| M-H2 | bounded-fixed | sync/async misuse JSON500/cleanup; no general async support. | `tests/test_sync_async_http.py` |
| M-H3 | bounded-fixed | preserve 0/False; fragment classifier separate. | `tests/test_clean_response_http.py` |
| M-H4 | partial | success-only cache fixed; finite-safety/Ruff caveats retained. | `tests/test_success_response_cache.py` |
| M-O1 | bounded-fixed | merged-node optimizer N+1 fixed in bounded case. | `tests/test_optimizer_merged_field_nodes.py` |
| M-O2 | bounded-fixed | warm-hit lock split; no general concurrency guarantee. | `tests/test_permission_cache_lock_split.py` |
| M-U1 | partial | Real-ASGI startup now cleans a group joined before cancellation returns; the same failed-Source/same-channel retry works. Distributed-backend cleanup remains best-effort. | `tests/subscriptions/test_startup_cleanup.py` |
| M-U2 | decision-deferred | delete visibility/scope policy; do not remove checks to force match. | `docs/usage/subscriptions.md` |
| M-U3 | partial | Finite Decimal exact filters compare numeric event snapshots, including 1.0 versus 1.00 and valid 257-character values; DateTime/delete precision policy remains open. | `tests/subscriptions/test_decimal_snapshot_filter.py` |
| M-U4 | contract | Automatic post-save/post-delete signals schedule commit-time sends, while bulk/update paths emit no model signals and manual binding broadcast is immediate; use a fresh post-commit instance when timing matters. | `docs/usage/subscriptions.md` |
| M-U5 | bounded-fixed | Native async directive formatting waits for resolver values and preserves borrowed Future ownership; synchronous HTTP still returns its controlled JSON 500 rather than gaining async support. | `tests/test_async_directive_middleware.py` |
| M-U6 | partial | The directive guide clarifies naive `@date` values in Django's active timezone and bounded case formatting; null/date/acronym transformations remain separate. | `docs/directives.md` |
| M-T1 | bounded-fixed | fork-depth marker isolation; other registry races separate. | `tests/core/test_schema_fork_threads.py` |
| L-C1 | partial | malformed abc IDs in get_node/retrieve/DjangoObjectField yield GraphQL null plus wrapped ValueError; well-typed missing ID yields null/no errors. Not raw HTTP500; null-only vs client error policy deferred. | `odd/tasks/audit-400-remediation.md` |
| L-C2 | bounded-fixed | Two specific constructor validations now survive optimized Python (`-O`); no universal validation claim follows. | `tests/test_settings_boundary_values.py` |
| L-C3 | partial | public Base view non-null root error is HTTP200/data:null; enhanced view HTTP400/no data key. Contracts confirmed; alignment policy deferred. | `odd/tasks/audit-400-remediation.md` |
| L-C4 | decision-deferred | MAX_UPLOAD_SIZE/base64 request docs are separate; multipart per-file quota would be a new policy, not evidence of existing promise. | `odd/tasks/audit-400-remediation.md` |
| L-C5 | decision-deferred | zero-preserving minimum validation may alter behavior/errors; approval needed. | `odd/tasks/audit-400-remediation.md` |
| L-C6 | contract | A cache miss reaches ensure_csrf_cookie and can set csrftoken; a cache hit returns earlier without Set-Cookie. A later cookie-bearing request bypasses the any-cookie cache policy. | `tests/test_views_cache_cookie_bypass.py` |
| L-C7 | bounded-fixed | ambiguous enum members rejected; optional multiselect untested. | `tests/core/test_choices_enum_member_ambiguity.py` |
| L-C8 | contract | Negative page -1 means a fixed-size tail window, not the positive final page's short remainder. | `tests/test_pagination_page_null_http.py` |
| L-C9 | partial | Cursor DB/list paths agree on NULL last ascending/first descending in the bounded SQLite case; offset/page queryset order inherits backend NULL placement and can diverge. | `docs/usage/pagination.md` |
| L-C10 | decision-deferred | declarations include fragment spread/inline fragment; behavioral/SDL policy unresolved. | `odd/tasks/audit-400-remediation.md` |
| L-C11 | decision-deferred | truncate/title/floor Infinity are distinct paths; error semantics require decision. | `odd/tasks/audit-400-remediation.md` |
| L-C12 | partial | The covered GFK union-wrapper path no longer makes an N+1 query; broader multi-table-inheritance paths remain unproved. | `tests/test_optimizer_phase_e.py` |
| L-C13 | contract | The guide distinguishes native DateTime scalar naive parsing from `@date`'s active-timezone interpretation, including `USE_TZ=False`; no scalar policy changed. | `docs/directives.md` |
| L-E1 | bounded-fixed | get_fields failure surfaces model/cause; healthy path unchanged. | `tests/core/test_metadata_enumeration_failures.py` |
| L-E2 | bounded-fixed | explicit source property AttributeError surfaced; legitimate null/unrelated descriptors unchanged. | `tests/core/test_source_property_attribute_error.py` |
| L-E3 | partial | The exact SITE-B filtered-prefetch hook-loss allegation was contradicted by a public SQLite witness: hook called once, visible rows only, one batched predicate query. Other branches/backends remain unproved. | `tests/test_optimizer_phase_e.py` |
| L-E4 | partial | cancellation intentional; single-group aclose warning fixed only. | `tests/subscriptions/test_source.py` |
| L-M1 | decision-deferred | Declared input classes are intentionally registry-owned and a static three-schema reuse stayed bounded; dynamic class churn needs an ownership/lifecycle policy. | `tests/core/test_registry_compiler.py` |
| L-M2 | partial | A bounded internal live-field identity/lifetime case was corrected; public schema impact and Graphene behavior were not established. | `tests/core/test_native_field_identity_lifetime.py` |
| L-M3 | partial | A direct GraphQLSchema enum-cache race was corrected; public exposure was not established. | `tests/core/test_enum_cache_concurrency.py` |
| L-M4 | partial | A direct GraphQLSchema list-creation race was corrected; public exposure was not established. | `tests/core/test_registry_creation_concurrency.py` |
| L-S1 | decision-deferred | heartbeat/per-principal caps are absent-feature/product policy, not an existing behavioral contract. | `docs/usage/subscriptions.md` |
| L-S2 | decision-deferred | connection_init/token on_connect hook is new authentication/protocol policy, not an established contract. | `docs/usage/subscriptions.md` |
| L-S3 | decision-deferred | empty offered protocol handshake confirmed; accept/reject/close code is wire-policy decision. | `docs/usage/subscriptions.md` |
| L-S4 | bounded-fixed | WS operation cleanup and slot release precede the server `complete` frame, so immediate same-ID reuse is not mistaken for a duplicate; other lifecycle cases remain. | `tests/subscriptions/test_ws_completion_reuse.py` |
| Q1 | contract | pyproject/uv/tox/CI require graphql-core 3.3 consistently; root 3.2.13 is stale unsupported env, not refreshed; no tox config mismatch. | `tests/test_tox_dependency_contract.py` |
| Q2 | bounded-fixed | The benchmark reader selects eight canonical result files deterministically; missing or invalid results still fail, and no timing was regenerated. | `tests/benchmarks/test_core33_results.py` |
| Q3 | bounded-fixed | Direct-view tests now close their own multipart temporary upload and ASGI body spool, including exception exits; no ResourceWarning was observed and no production leak is inferred. | `tests/test_views_multipart_body_bound.py` |
| Q4 | recommendation | regression matrix duplicates existing IDs. | `odd/tasks/audit-400-remediation.md` |
| Q5 | recommendation | historical test naming suggestion only. | `odd/tasks/audit-400-remediation.md` |
| Q6 | recommendation | module split suggestion, no authority. | `odd/tasks/audit-400-remediation.md` |
| Q7 | recommendation | cross-reference plan only; verify before refactor. | `odd/tasks/audit-400-remediation.md` |
| Q8 | negative-limited | MUTATION_ERRORS_FLAG is live; other alleged dead symbols require qualified caller and compatibility review, not deletion. | `django_graphex/views.py` |
| Q9 | recommendation | historical Graphene names/comments only. | `odd/tasks/audit-400-remediation.md` |
| Q10 | decision-deferred | deriving non-null from null=False changes SDL. | `odd/tasks/audit-400-remediation.md` |
| P1 | recommendation | duplicate priority plan, not new finding/authority. | `odd/tasks/audit-400-remediation.md` |
| N1 | negative-limited | The schema cache uses an effective permission signature, not a unique user key; this is not a universal cross-user response-cache guarantee. | `odd/tasks/audit-400-remediation.md` |
| N2 | negative-limited | anonymous/falsy permission and scoped update/delete chain not universally runtime-proved. | `odd/tasks/audit-400-remediation.md` |
| N3 | negative-limited | Core MaxIntrospectionDepthRule rejected one bounded nested introspection query; custom MAX_QUERY_DEPTH is a different guard, and no universal DoS proof follows. | `tests/test_depth_limit.py` |
| N4 | contract | The GFK field-type cache is process-global Django class metadata; saying all caches are request-scoped is inaccurate. | `django_graphex/utils.py` |
| N5 | negative-limited | regex safety is bounded only; no universal conclusion. | `odd/tasks/audit-400-remediation.md` |
| N6 | negative-limited | Twenty-three tracked-test docstring findings were corrected, but seven ignored-profile DOC002 findings remain locally; original ignored preimages and a whole-CI-clean verdict are unavailable. | `scripts/check_docstrings.py` |

## Decisions still required

These items are **not implemented by this audit report**. They are grouped
because approving one does not silently approve another.

1. **Security and data scope:** SD1 automatic relation reads, SD2 joined-row
   oracles, and SD6 strict-scope/system-check semantics need a policy for
   destination and joined data. The exact SITE-B L-E3 case did not reproduce,
   but other branches/backends remain unproved. Generated input destination
   IDs and hostless reverse-FK adoption have narrower accepted safeguards.
2. **Mutation semantics:** A1 native `ok: false` sibling rollback,
   cross-database writes and lost updates; M-D1 partial-save
   `update_fields`, custom `save()`, `auto_now`, and derived fields;
   R05c instance-dependent CREATE routing; wider A10 `full_clean()` and
   upsert/uniqueness behavior all need separate compatibility decisions.
   Stable/model-routed same-alias nested rollback is not distributed
   atomicity.
3. **Subscriptions and transport:** M-U2 id-only delete visibility and
   non-PK scope, R02b DateTime snapshot precision/deletion, M-U3 Float
   generalization, M-U4 bulk/M2M signal policy, L-S1 heartbeat/principal
   cap, L-S2 `connection_init` auth hook, and L-S3 empty offered
   subprotocol handshake/close code are distinct decisions. Same failed
   Source retry was corrected, but backend cleanup remains best-effort.
4. **HTTP, cache, and resource limits:** A2 retained AST/cache bytes and
   aggregate memory, A11 aggregate response quota, M-S2 other defaults and
   Boolean width/depth, L-C3 error HTTP status alignment, L-C4 a new
   multipart per-file quota, L-C5 zero-valued negative-configuration errors,
   L-C6 any-cookie privacy override and cache byte limits must not be
   inferred from existing per-result/body caps. Existing
   `MAX_UPLOAD_SIZE` behavior does not promise a multipart file quota.
5. **Inputs, scalars, pagination, and SDL:** M-D4 extreme
   `1E+999999999` was intentionally not run without a bounded witness;
   M-D6 JSONRaw Undefined/non-finite policy, M-D10 Literal/dict/set/Union
   conversion, M-F3 empty Boolean identities, L-C1 malformed-ID null/error
   policy, L-C9 universal NULL ordering, L-C10 fragment-spread/inline
   directive behavior, L-C11 non-finite directive errors, M-U6 remaining
   conversion/null/date semantics, and Q10 non-null SDL derivation all
   need design. Existing warning-only typing diagnostics are not conversion.
6. **Quality and architecture:** Q5–Q7 and Q9 are structural recommendations,
   not authority to split large modules merely because the report suggested
   it. Q8 is a limited dead-code check that requires caller/compatibility
   review before removing public names, especially its live mutation flag.
   R09b asks whether eight ignored
   ad-hoc benchmark profiles should remain ignored; their original
   preincident bytes are unknown. Q4 and P1 are overlapping coverage and
   prioritization plans, not extra defect IDs.

## Verification and provenance limits

- The supported verification runtime is graphql-core 3.3.0 over the
  externally retained 3.3 overlay. The checkout's ambient 3.2.13
  installation is unsupported and was not refreshed. Current
  `pyproject.toml`, `uv.lock`, `tox.ini`, and CI dependency declarations
  agree on 3.3; that configuration check is not a fresh CI matrix run.
- The final local configured suite passed **5,624 tests**, with **7 skipped**
  and **10 warnings**. Raw branch coverage was **4,148 / 4,346 = 95.44%**;
  combined covered lines and branches were **15,546 / 15,927 = 97.61%**.
  The nonempty cumulative production diff against the initial feature-branch
  base covered **1,221 / 1,238 changed lines = 98.63%**, including branch
  coverage. This was a local supported-runtime run, not a clean CI matrix.
  The proof applies to the guarded finite inputs, not to every host file,
  physical index state, or power-loss mode. No package was published and no
  real PostgreSQL integration database was run.
- The whole local docstring scanner still finds **seven DOC002** findings
  in ignored profiling files; 23 tracked-test findings were corrected.
  The ignored files are not automatically part of clean-checkout CI, so
  neither “all CI green” nor “all local files clean” follows.
- The test-owned multipart/ASGI spool correction had a file-closed witness;
  no `ResourceWarning` was observed and no production endpoint leak was
  inferred. An actual client handler has different request ownership.
- Prior bounded attempts include rejected intermediate candidates, helper
  failures, and unknown original preimages for historical ignored profiles,
  some ignored reports, temporary/environment artifacts and the physical
  index. The work tracker preserves those qualifications rather than
  rewriting failed attempts as passing evidence. No new benchmark timings,
  PostgreSQL 17, CI matrix, dependency audit, package build, tag, or remote
  publication was run for this documentation unit; those checks were not run.
