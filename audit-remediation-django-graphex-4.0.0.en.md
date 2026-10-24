# Django GraphEx 4.0.0 audit remediation: detailed evidence and decisions

> **Later round (4.1.0).** This retrospective is frozen at the 4.0.0 remediation snapshot. A later round on the 4.1.0 branch changed several dispositions (for example A1, A2, A10, A13, M-D4 and M-D6 gained fixes, and M-F3 and L-M1 became documented contracts). The current dispositions are in the [disposition guide](docs/audit-4.0.0.md) and [CHANGELOG.md](CHANGELOG.md). The Before and After JSON blocks are reduced illustrations, not captured output, whatever their label says; claims with no implementation carry no After block.

This companion to the [original Spanish audit](auditoria-django-graphex-4.0.0.md) explains what happened, why, and what remains. It is a **frozen local retrospective**, not a release statement or a claim that 100 bugs were fixed. The original report is untracked user evidence (SHA-256 `6a0ee92c2fd51ce104080bf4ac5403c24c0e00abc075882735949036d478e561`), not a trusted payload source. The implementation base is `5a155a059a4d3995ead1b639f08136e5d7619aec`; the frozen snapshot is `8d93483d2fd654012a544ce68365baf1964056f3`, committed **2026-10-23 23:13:45 -04:00 (America/New_York)**. The earlier `9a6ec5adc89bdc24de138179ad1280751a5266e5` audit branch is not an ancestor of this implementation.

## Read the outcome first

| Primary disposition | IDs | Correct interpretation |
|---|---:|---|
| bounded-fixed | 51 | Demonstrated bounded behavior was corrected; adjacent subclaims can remain open. |
| partial | 25 | Some evidence or accepted slice exists, but a residual, backend, or policy is unresolved. |
| contract | 9 | The original expectation differed from the current/documented contract; no blanket code fix follows. |
| recommendation | 7 | Coverage, organization, or refactoring advice, not seven independent bugs. |
| negative-limited | 6 | Reassuring negative claims have only bounded evidence; they are not six fixes. |
| decision-deferred | 2 | A proposed public/security/lifecycle policy requires explicit approval. |

The source [disposition guide](docs/audit-4.0.0.md) has exactly 100 primary rows. Its concise summaries must not replace the original allegation: **C1** originally covered every auto-derived `DecimalField` output on graphql-core 3.3, not just decimal primary keys; **C2** originally alleged exponential optimizer CPU from repeated fragments, while encounter order was a follow-up. **C3** was a separate cyclic-fragment cost/depth path. Many M/L/SD/Q/N labels were normalized by the tracking ledger for unnumbered source prose; line anchors identify the real original text. The work tracker has **215 tasks: 190 checked, 25 overlapping or parent rows unchecked**, with **15 principal T03–T17 areas open**. The **33 primary pending/limited records** are 25 partial + 2 deferred + 6 negative-limited; they are not 33 proven new bugs.

This report distinguishes an original allegation, source-diff-inspected causal fix, accepted related commit, guide/tracker-only disposition, and representative test. A test file changed in the same commit is not by itself causal evidence. “Added” or “modified” on a test refers to base-to-snapshot AST definitions; it is not a pytest-case count. The code-like before/after snippets in every case are **simplified illustrations** of a specific contract, not copied logs or newly executed original payloads. Where no fix was made, “after” explicitly describes unchanged behavior or a bounded observation. All links are relative to this repository; historical external proof is described, not silently assumed available in CI.

## How the work unfolded

1. **Environment and blocking paths, October 13–14.** The team separated the supported graphql-core 3.3.0 runtime from the stale root 3.2.13 environment, fixed canonical benchmark-result selection without rerunning timings, then addressed independent cyclic-fragment precheck, repeated-fragment optimizer planning/order, Decimal output/nullability/precision, and BigInteger representation. `C1`, `C2`, and `C3` therefore have different causes and different proof chains.
2. **Schema, relation and mutation safety, October 14–15.** Output registry conflicts and selector validation stopped silent field exposure; generated relation links, orphan adoption, flat GFK metadata, cold permission pruning, and selected destination `get_queryset` paths received bounded safeguards. Automatic notification failure isolation, input factories, reserved names, explicit interface names, generated delete redaction, email/positive validation, null/date-part/to-many filters, and typed pagination followed. These slices did not create global `strict_scope`, general `full_clean()`, or cross-database atomicity.
3. **Pagination, HTTP and concurrency, October 15–18.** Cursor coercion, null-page semantics, page-size default, count failure, tie-breaking and null ordering were separated. HTTP cost variables, cache framing, production error redaction, failed-response caching, batch behavior and sync/async cleanup were corrected in different work units. Warm permission-cache lock splitting, schema fork isolation, GFK union-wrapper batching, metadata errors, property errors, enum/list races and live field identity each had narrower proofs than a universal concurrency guarantee.
4. **Subscriptions and directive boundaries, October 18–23.** WS lifecycle and pre-accept guards, optional `on_connect`, automatic delete snapshots, finite Decimal/DateTime/Float matching, optional SSE heartbeat/lease controls and `@date`/JSON/directive cases were developed with explicit compatibility limits. The accepted SSE source commit `7ec2264c763859cd840e1475e8f4cec9a47ed8fc` and tracker closeout `1d26aa6478e2dd7e39585c349a466a34f41c1175` are in the final ancestry, contrary to an obsolete intermediate evidence-map sentence. Later M-D10 typed inputs/warnings resolved its original silence allegation while broader annotation policies remain open.
5. **Verification and closure.** The frozen audit feature's last recorded full suite was **6697 passed, 7 skipped, 18 warnings**, raw branch coverage **4687/4894 = 95.770331%**, and combined coverage **17228/17616 = 97.797457%**. These are *historical snapshot* results, not fresh verification of this report. Separately, the L-S1 accepted closeout records a prior full **5825 passed, 7 skipped, 10 warnings** and ten real Redis integration passes against one instance; no full-suite rerun followed those L-S1 commits. The final `8d93483` commit only closed original M-D10 wording in documentation. No PR, push, tag, publication, runtime API change, Redis rerun, or new performance benchmark belongs to this report.

## All original findings, in source order


### C1 — DecimalField output was mapped to GraphQLFloat, which rejected Decimal on graphql-core 3.3

**Status:** bounded-fixed

**Original problem:** DecimalField output was mapped to GraphQLFloat, which rejected Decimal on graphql-core 3.3; the allegation covered every auto-derived DecimalField, not only primary keys. [original audit](auditoria-django-graphex-4.0.0.md), lines 36–44. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 192; [task T03a/T03](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** DecimalField value Decimal("12.5"). The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
{ item { amount } }
```

**Before (illustrative):**
```json
{"data": {"item": {"amount": null}}, "errors": ["Float cannot represent Decimal"]}
```

**After (observed/current):**
```json
{"data": {"item": {"amount": "12.5"}}}
```

**How the result was reached:**
1. In _to_graphql_field, auto-derived DecimalField first received a resolver adapter for the old Float output; the later precision change mapped it to the exact Decimal scalar. A separate primary-key projection retained non-null propagation.
2. `bd45a6546cbb70a3e4151b087ff51110eed00706`: source changes in [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py). Follow-up source commits: `dbabfde2f1367f869c88ed22cfe91ce267ba02ca`, `d27832188f55e72d88551c16e077032d633c9875`.
3. Scope check: Decimal primary keys no longer pass through Float/null conversion; distinct Decimal output and non-finite policies remain separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py), `test_automatic_decimal_output_preserves_exact_text` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data == {"item": {"amount": str(amount), "ratio": 1.5}}
   ```
   - [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py): `test_automatic_decimal_output_preserves_exact_text` (added definition); `test_automatic_decimal_primary_key_uses_decimal_nonnull` (added definition); `test_automatic_decimal_field_executes_as_exact_decimal` (added definition); `test_explicit_decimal_scalar_and_input_mapping_stay_precise` (added definition); `test_explicit_float_resolver_retains_legacy_numeric_contract` (added definition); `test_decimal_filter_literals_and_variables_remain_precise` (added definition); `test_generated_create_mutation_returns_exact_decimal_output` (added definition); `test_decimal_primary_key_keeps_nonnull_and_exact_output` (added definition); `test_null_decimal_primary_key_propagates_nonnull_error` (added definition).
**Reading the guide:** Guide C1 row summarizes PK no Float/null propagation; original allegation was broader DecimalField output failure. Keep the separate precision policy distinct.


### C2 — Repeated fragment spreads made optimizer walkers expand a small document exponentially

**Status:** bounded-fixed

**Original problem:** Repeated fragment spreads made optimizer walkers expand a small document exponentially; validation and source-order effects were separate concerns. [original audit](auditoria-django-graphex-4.0.0.md), lines 46–58. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 193; [task T02b](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** valid repeated-spread optimizer DAG; the separate B-before-A selection-order regression is checked by the follow-up. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
query Q { user { ...F0 } }
fragment F0 on User { ...F1 ...F1 }
fragment F1 on User { username }
```

**Before (illustrative):**
```json
{"optimizer_visits": "same selection context expanded along up to 2^8 paths"}
```

**After (observed/current):**
```json
{"optimizer_visits": "bounded to <=64 in each tested collector", "effects": "replayed in source encounter order"}
```

**How the result was reached:**
1. In recursive_params and the filtered-prefetch walkers, the optimizer caches selection-context planning rather than rewalking each exponentially repeated spread. The follow-up replays cached prefetch effects in document encounter order, so memoization does not erase the second occurrence.
2. `92b1358f31a2973abe7a817b820d54775a9067a6`: source changes in [django_graphex/utils.py](django_graphex/utils.py). Follow-up source commits: `7bec957180edcf138d50256777a9e1bfb196f2b5`.
3. Scope check: Fragment-dependent selections now retain source order; duplicate FieldNode behavior was not changed.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_optimizer_fragment_fanout.py](tests/test_optimizer_fragment_fanout.py), `test_valid_repeated_fragment_graph_has_bounded_optimizer_visits` (short source excerpt, not a reconstructed failure):
   ```python
   if calls > 64:
       pytest.fail(f"{name} expanded a repeated fragment more than 64 times")
   ```
   - [tests/test_optimizer_fragment_fanout.py](tests/test_optimizer_fragment_fanout.py): `test_bounded_promotion_iterator_handles_absent_and_cyclic_internal_inputs` (added definition); `test_interleaved_fragment_restores_last_annotation_alias_value` (added definition); `test_interleaved_fragment_restores_last_prefetch_annotation_plan` (added definition); `test_promotion_consumer_bounds_repeated_spreads_without_changing_rows` (added definition); `test_reused_fragment_keeps_distinct_relation_path_contexts` (added definition); `test_valid_repeated_fragment_graph_has_bounded_optimizer_visits` (added definition).
**Reading the guide:** Guide C2 row emphasizes encounter order; source allegation is exponential optimizer planning. C3 cycle precheck is separate.


### C3 — A cyclic fragment graph reached cost and depth walkers during parallel validation before the ordinary cycle error…

**Status:** bounded-fixed

**Original problem:** A cyclic fragment graph reached cost and depth walkers during parallel validation before the ordinary cycle error stopped their expensive traversal. [original audit](auditoria-django-graphex-4.0.0.md), lines 60–72. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 194; [task T02a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** fragment A spreads B; fragment B spreads A. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
{ root { ...F } }
fragment F on Node { name child { ...F } }
```

**Before (illustrative):**
```json
{"cost_walk": "re-enters F without a precheck"}
```

**After (observed/current):**
```json
{"error": "Cyclic fragment reference", "resolver_calls": 0}
```

**How the result was reached:**
1. A shared iterative fragment-graph cycle check runs before depth and cost expansion. It rejects a cycle with GraphQLError while leaving acyclic and missing-target controls distinguishable.
2. `2943f4544fe0c56064895a35b8606effe50013be`: source changes in [django_graphex/_fragment_cycles.py](django_graphex/_fragment_cycles.py), [django_graphex/cost.py](django_graphex/cost.py), [django_graphex/validation.py](django_graphex/validation.py).
3. Scope check: A shared fragment cycle is rejected as GraphQLError before the cost/depth walker can recurse indefinitely.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_fragment_cycles.py](tests/test_fragment_cycles.py), `test_cyclic_fanout_is_rejected_before_expensive_walks` (short source excerpt, not a reconstructed failure):
   ```python
   assert counts["depth"] <= 10
   ```
   - [tests/test_fragment_cycles.py](tests/test_fragment_cycles.py): `test_cyclic_fanout_is_rejected_before_expensive_walks` (added definition); `test_disconnected_fragment_cycle_rejects_direct_cost_analysis` (added definition); `test_acyclic_spreads_and_missing_targets_do_not_trigger_cycle_check` (added definition); `test_dense_multi_entry_cycle_is_detected` (added definition); `test_long_fragment_chain_uses_iterative_cycle_check` (added definition); `test_default_view_rejects_cycle_without_running_resolver` (added definition).


### A1 — GraphQL errors were returned in result.errors without causing covered mutation transactions to roll back

**Status:** partial

**Original problem:** GraphQL errors were returned in result.errors without causing covered mutation transactions to roll back. [original audit](auditoria-django-graphex-4.0.0.md), lines 80. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 195; [task T05a/T05](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** create sibling then resolver raises. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
mutation {
  userCreate(newUser: {username: "example" email: "example@example.test" firstName: "T" lastName: "User" password: "testpassword123"}) { ok user { username } errors { field messages } }
  explode
}
```

**Before (illustrative):**
```json
{"errors": [{"path": ["explode"]}], "persisted_users": 1}
```

**After (observed/current):**
```json
{"errors": [{"path": ["explode"]}], "persisted_users": 0}
```

**How the result was reached:**
1. BaseGraphQLView/GraphQLView checks ExecutionResult.errors after GraphQL execution and marks the active Django transaction for rollback, including ATOMIC_REQUESTS. Successful GraphQL data may remain in the HTTP body although the covered default-DB write is undone.
2. `f91022e7a00deda481e63c5b316cc9db003ae1a5`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: A GraphQL error rolls back covered default-DB sibling writes; native ok: false, multi-DB atomicity, and stale-row overwrites remain separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_views_atomic_errors.py](tests/test_views_atomic_errors.py), `test_atomic_mutations_execution_error_rolls_back_native_write` (short source excerpt, not a reconstructed failure):
   ```python
   assert User.objects.filter(username=username).count() == 0
   ```
   - [tests/test_views_atomic_errors.py](tests/test_views_atomic_errors.py): `test_atomic_mutations_execution_error_rolls_back_native_write` (added definition); `test_atomic_requests_execution_error_rolls_back_native_write` (added definition); `test_atomic_requests_explicit_flag_rolls_back_without_graphql_error` (added definition); `test_atomic_mutations_explicit_flag_still_rolls_back` (added definition); `test_nonatomic_execution_error_keeps_durable_write_and_invalidates` (added definition); `test_atomic_execution_error_does_not_invalidate_rolled_back_write` (added definition); `test_atomic_success_commits_and_invalidates` (added definition); `test_native_ok_false_does_not_retroactively_rollback_prior_root` (added definition); `test_batch_failed_atomic_operation_then_success_invalidates_once` (added definition).


### A2 — The parse/validation cache had no memory bound: its LRU counts entries (128), not bytes

**Status:** partial

**Original problem:** The parse/validation cache had no memory bound. Its LRU is bounded by entry count (128), not bytes; per the original report a 1.5 MB query yields an AST of about 120 MB, so 128 distinct queries would pin about 15 GB per process. With `CACHE_ACTIVE`, the document was also parsed and hashed before the `MAX_REQUEST_BODY_SIZE` guard (repro: a correct 413, but the AST was already cached). [original audit](auditoria-django-graphex-4.0.0.md), lines 81. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 196; [task T04a/T04](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** POST body exceeds configured cap with cache active. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```http
POST /graphql/
Content-Type: application/json

{"query":"{ ping }", "padding":"...above MAX_REQUEST_BODY_SIZE..."}
```

**Before (illustrative):**
```json
{"cache_reads": 1, "http_status": 413}
```

**After (observed/current):**
```json
{"cache_reads": 0, "http_status": 413}
```

**How the result was reached:**
1. The enhanced view checks the actual POST body against the cap before parsing or reading its response cache. A spoofed low Content-Length cannot bypass the actual-body check; retained cache bytes are a different quota.
2. `84369e41431e16a6ebe53159c2b7b6fd3401b1db`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: The POST body-size guard runs before GraphQL body parsing; retained AST/cache bytes and aggregate memory are not capped by that change.
4. Actual test locators, with base-to-snapshot definition provenance:
   - [tests/test_views_body_cap_cache.py](tests/test_views_body_cap_cache.py): `test_oversized_cache_active_body_is_rejected_before_parse_or_cache` (added definition); `test_body_at_cap_still_warms_and_hits_response_cache` (added definition); `test_tightened_cap_rejects_an_already_cached_query` (added definition); `test_spoofed_low_content_length_still_rejects_actual_body` (added definition); `test_cache_disabled_retains_early_base_view_rejection` (added definition); `test_disabled_cap_allows_the_same_query` (added definition); `test_get_with_invalid_body_keeps_bad_request_not_body_cap` (added definition); `test_authentication_denial_precedes_body_cap` (added definition).


### A3 — Unknown or string-valued output field selectors could silently bypass exclusion and expose sensitive model fields

**Status:** bounded-fixed

**Original problem:** Unknown or string-valued output field selectors could silently bypass exclusion and expose sensitive model fields. [original audit](auditoria-django-graphex-4.0.0.md), lines 82. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 197; [task T06a/T06](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** exclude_fields=("pasword",) on User. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"model": "User", "exclude_fields": ["pasword"]}
```

**Before (illustrative):**
```json
{"registered_fields": ["id", "password"]}
```

**After (observed/current):**
```json
{"schema_build_error": "unknown field pasword"}
```

**How the result was reached:**
1. Output construction validates selector shape and resolves each name against model, reverse relation, and declared fields before registration. A misspelled exclusion fails configuration instead of falling back to an all-field projection.
2. `edb82a30dae7bd96b5a56627963746d6e87b00cd`: source changes in [django_graphex/types.py](django_graphex/types.py).
3. Scope check: Invalid output field selectors are rejected rather than silently bypassing the selection gate; this is not a proof about every unauthenticated request.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_output_selector_validation.py](tests/test_output_selector_validation.py), `test_reverse_accessor_and_query_name_selectors_remain_valid` (short source excerpt, not a reconstructed failure):
   ```python
   assert ("entries" in fields) == (option == "only_fields")
   ```
   - [tests/test_output_selector_validation.py](tests/test_output_selector_validation.py): `test_reverse_accessor_and_query_name_selectors_remain_valid` (added definition); `test_unknown_output_selector_fails_before_registration` (added definition); `test_bare_string_output_selector_is_rejected` (added definition); `test_valid_model_and_declared_selectors_remain_supported` (added definition); `test_noninterface_declared_wire_name_keeps_existing_contract` (added definition); `test_generic_foreign_key_and_set_selectors_remain_supported` (added definition); `test_declared_custom_only_output_remains_valid` (added definition); `test_corrected_exclusion_hides_sensitive_user_field` (added definition); `test_one_shot_selector_is_reused_for_projection` (added definition); `test_custom_slug_key_and_empty_selector_are_valid` (added definition); `test_non_name_selectors_fail_in_configuration` (added definition).


### A4 — Registering two public outputs for one Django model could let import order choose a broader type silently

**Status:** bounded-fixed

**Original problem:** Registering two public outputs for one Django model could let import order choose a broader type silently. [original audit](auditoria-django-graphex-4.0.0.md), lines 83. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 198; [task T06b/T06](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** PublicAuthor then AdminAuthor for Author in one Registry. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```python
registry = Registry()
# PublicAuthor and AdminAuthor both use Meta.model = Author and Meta.registry = registry.
# PublicAuthor.only_fields = ("id", "name")
# AdminAuthor.only_fields = ("id", "name", "bio")
```

**Before (illustrative):**
```json
{"registered_output": "AdminAuthor", "exposed_fields": ["id", "name", "bio"]}
```

**After (observed/current):**
```json
{"error": "ImproperlyConfigured on second incompatible output"}
```

**How the result was reached:**
1. Registry.register now compares the Django model and public output identity before replacing an entry. A second incompatible type in one Registry raises, while separately owned registries remain independent.
2. `65e99d35bd3392a640619a089307a7977627b57f`: source changes in [django_graphex/registry.py](django_graphex/registry.py), [django_graphex/types.py](django_graphex/types.py).
3. Scope check: Registry.register keys public outputs by Django model: a distinct output type for the same model and same registry is rejected regardless of type names; separate registries may define distinct schemas.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_output_registration_conflict.py](tests/test_output_registration_conflict.py), `test_second_public_author_type_fails_without_shadowing_nested_author` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data == {"post": {"author": {"name": "Public"}}}
   ```
   - [tests/test_output_registration_conflict.py](tests/test_output_registration_conflict.py): `test_second_public_author_type_fails_without_shadowing_nested_author` (added definition); `test_identical_class_reregistration_is_idempotent` (added definition); `test_distinct_registries_may_publish_distinct_author_views` (added definition); `test_non_registering_internal_view_does_not_replace_public_type` (added definition); `test_registered_node_remains_list_and_filter_target` (added definition); `test_input_registration_and_proxy_model_keys_remain_distinct` (added definition); `test_model_mutation_reuses_registered_public_output` (added definition); `test_public_and_admin_user_schemas_bind_post_user_independently` (added definition).


### A5 — Cold real Django users triggered synchronous permission ORM work in the WS/SSE event loop

**Status:** bounded-fixed

**Original problem:** Cold real Django users triggered synchronous permission ORM work in the WS/SSE event loop. [original audit](auditoria-django-graphex-4.0.0.md), lines 84. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 199; [task T08a/T08](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** cold Django user opens WS/SSE. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```python
user = await _real_user(may_view_post=False)
# WS/SSE schema_provider receives this cold Django user.
```

**Before (illustrative):**
```json
{"event_loop": "sync ORM permission lookup / error"}
```

**After (observed/current):**
```json
{"schema": "permission-pruned for effective user", "event_loop": "ORM lookup offloaded"}
```

**How the result was reached:**
1. subscription_sse_view and subscription_ws_consumer resolve a cold Django user's permission-pruned schema in a thread instead of issuing synchronous ORM work on the event loop. The effective user still determines private-field pruning.
2. `ac72aa7b9ca4b4532c26535f43e569c1cda0503e`: source changes in [django_graphex/subscriptions/transports/sse.py](django_graphex/subscriptions/transports/sse.py), [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Scope check: A cold Django user in WS/SSE receives the covered permission pruning; a fake-user control does not prove every authentication source.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_transport_cold_permissions.py](tests/subscriptions/test_transport_cold_permissions.py), `test_sse_provider_resolves_cold_real_user_permissions` (short source excerpt, not a reconstructed failure):
   ```python
   assert response.status_code == 200
   ```
   - [tests/subscriptions/test_transport_cold_permissions.py](tests/subscriptions/test_transport_cold_permissions.py): `test_sse_provider_resolves_cold_real_user_permissions` (added definition); `test_sync_providers_preserve_context_and_error_paths` (added definition); `test_ws_concurrent_operations_resolve_provider_once` (added definition); `test_ws_provider_resolves_cold_real_user_permissions` (added definition); `test_ws_real_auth_handshake_prunes_cold_permissions` (added definition).
   - [tests/subscriptions/test_transport_real_user_resolution.py](tests/subscriptions/test_transport_real_user_resolution.py): `test_sse_authenticated_caller_streams` (historical locator; not in the changed-path inventory); `test_sse_anonymous_caller_is_denied` (historical locator; not in the changed-path inventory); `test_sse_session_of_a_deleted_user_is_denied` (historical locator; not in the changed-path inventory); `test_sse_request_without_any_session_is_denied` (historical locator; not in the changed-path inventory); `test_sse_schema_provider_receives_a_resolved_user` (historical locator; not in the changed-path inventory); `test_ws_authenticated_caller_streams` (historical locator; not in the changed-path inventory); `test_ws_anonymous_caller_is_denied` (historical locator; not in the changed-path inventory); `test_ws_session_of_a_deleted_user_is_denied` (historical locator; not in the changed-path inventory); `test_ws_scope_without_a_user_is_denied` (historical locator; not in the changed-path inventory).
**Reading the guide:** A5 bounded fix addresses cold permission-provider queries; not every auth source or subscription policy.


### A6 — Automatic Redis notification exceptions could escape an on_commit callback after the model row had already…

**Status:** bounded-fixed

**Original problem:** Automatic Redis notification exceptions could escape an on_commit callback after the model row had already committed. [original audit](auditoria-django-graphex-4.0.0.md), lines 85. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 200; [task T08b/T08](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** model save commits; Redis send raises. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```python
with transaction.atomic():
    row = HookModel.objects.create(text="committed-before-send")
    transaction.on_commit(lambda: later.append("continued"))
# The automatic channel-layer group_send raises after commit.
```

**Before (illustrative):**
```json
{"row_exists": true, "caller_exception": "post-commit send failure", "later_on_commit_callback_ran": false}
```

**After (observed/current):**
```json
{"row_exists": true, "caller_exception": null, "later_on_commit_callback_ran": true, "delivery_guaranteed": false}
```

**How the result was reached:**
1. SubscriptionBinding automatic post-commit dispatch catches and logs Redis delivery exceptions after the row is durable. Explicit manual broadcast keeps its strict propagation contract rather than silently swallowing caller-visible failures.
2. `901c35bd9b754f6b21b6f61715c0f62ea0604d15`: source changes in [django_graphex/subscriptions/bindings.py](django_graphex/subscriptions/bindings.py).
3. Scope check: Automatic notification failures are best-effort rather than raising through model writes; manual broadcasts remain strict and delivery is not guaranteed.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_automatic_best_effort.py](tests/subscriptions/test_automatic_best_effort.py), `test_snapshot_failure_does_not_abort_atomic_save` (short source excerpt, not a reconstructed failure):
   ```python
   assert HookModel.objects.filter(pk=row.pk).exists()
   ```
   - [tests/subscriptions/test_automatic_best_effort.py](tests/subscriptions/test_automatic_best_effort.py): `test_snapshot_failure_does_not_abort_atomic_save` (added definition); `test_failed_snapshot_does_not_change_generated_mutation_result` (added definition); `test_failed_delivery_preserves_autocommit_update_and_delete` (added definition); `test_explicit_manual_broadcast_remains_strict` (added definition); `test_rollback_discards_automatic_failures_and_snapshots` (added definition); `test_async_automatic_failure_logs_only_metadata` (added definition); `test_base_exception_is_not_swallowed` (added definition); `test_logging_backend_failure_does_not_abort_save` (added definition); `test_database_write_error_remains_strict` (added definition); `test_broken_notification_transaction_still_propagates_database_error` (added definition); `test_missing_layer_warning_backend_failure_is_best_effort` (added definition); `test_send_failure_keeps_committed_write_and_later_callback` (added definition).


### A7 — Default factories were evaluated during schema compilation, sharing a UUID or list across later input objects

**Status:** bounded-fixed

**Original problem:** Default factories were evaluated during schema compilation, sharing a UUID or list across later input objects. [original audit](auditoria-django-graphex-4.0.0.md), lines 86. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 201; [task T09a/T09](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** two independent input objects omit uid. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
mutation { submit(payload: {}) { result } }
```

**Before (illustrative):**
```json
{"uids": ["same-schema-time-UUID", "same-schema-time-UUID"]}
```

**After (observed/current):**
```json
{"uids": ["fresh-UUID-A", "fresh-UUID-B"]}
```

**How the result was reached:**
1. compile_input_type retains factory metadata rather than invoking callables while building SDL. Coercion evaluates a missing field per input object and prunes factory metadata for overwritten aliases; explicit values and introspection do not call it.
2. `eee1a6dd2b7743763066d81f544e709c7c76d180`: source changes in [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py), [django_graphex/core/schema_pruner.py](django_graphex/core/schema_pruner.py). Follow-up source commits: `ef7f6b5ad5b9e711d36ab7d3c45694fc3c987906`.
3. Scope check: An omitted-field factory runs per coerced input object, not per selected field or alias. Explicit values skip it; schema construction and introspection do not evaluate it.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_input_factory_per_object.py](tests/core/test_input_factory_per_object.py), `test_omitted_factory_values_are_fresh_across_graphql_executions` (short source excerpt, not a reconstructed failure):
   ```python
   assert second.data == {"submit": {"result": "uid-2:seed,changed"}}
   ```
   - [tests/core/test_input_factory_per_object.py](tests/core/test_input_factory_per_object.py): `test_omitted_factory_values_are_fresh_across_graphql_executions` (added definition); `test_factory_respects_variables_explicit_values_and_field_aliases` (added definition); `test_nested_inputs_and_inline_aliases_create_distinct_objects` (added definition); `test_factory_failures_are_graphql_input_errors_without_private_text` (added definition); `test_permission_pruned_input_does_not_reinsert_hidden_factory_field` (added definition); `test_validated_data_factory_remains_a_model_validation_default` (added definition); `test_model_derived_input_keeps_omitted_factory_field_absent` (added definition); `test_overwritten_wire_alias_only_runs_effective_field_factory` (added definition); `test_literal_field_overwriting_factory_alias_does_not_run_factory` (added definition).


### A8 — BigIntegerField used GraphQL Int's 32-bit range and failed for large output/input values

**Status:** bounded-fixed

**Original problem:** BigIntegerField used GraphQL Int's 32-bit range and failed for large output/input values. [original audit](auditoria-django-graphex-4.0.0.md), lines 87. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 202; [task T03b/T03](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** BigIntegerField = 9007199254740993. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"model_field": "BigIntegerField", "value": 9007199254740993}
```

**Before (illustrative):**
```json
{"graphql_type": "Int", "data": null, "error": "32-bit range"}
```

**After (observed/current):**
```json
{"graphql_type": "decimal-string scalar", "data": "9007199254740993"}
```

**How the result was reached:**
1. The model BigInteger mapping uses a decimal-string scalar at GraphQL boundaries, avoiding the 32-bit GraphQL Int limit and floating-point rounding. Relation identifiers and choice validation were adjusted separately.
2. `8f86dc8927eb66a62dcdcf8936c40b659d6e6ead`: source changes in [django_graphex/core/__init__.py](django_graphex/core/__init__.py), [django_graphex/core/fields.py](django_graphex/core/fields.py), [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py), [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py), [django_graphex/core/scalars.py](django_graphex/core/scalars.py). Follow-up source commits: `12a7506a8b83c75ee211e1174dca9c3fbdf748c2`.
3. Scope check: A BigInteger value above JavaScript's exact-number range serializes as a decimal string; relation IDs and enum behavior are separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_bigint.py](tests/core/test_bigint.py), `test_auto_output_uses_decimal_string_bigint` (short source excerpt, not a reconstructed failure):
   ```python
   assert fields["positive"].type.name == "BigInt"
   ```
   - [tests/core/test_bigint.py](tests/core/test_bigint.py): `test_auto_output_uses_decimal_string_bigint` (added definition); `test_explicit_bigint_primary_key_keeps_nonnull_wrapper` (added definition); `test_nullable_bigint_output_keeps_null` (added definition); `test_explicit_scalar_override_keeps_its_declared_contract` (added definition); `test_null_bigint_primary_key_propagates_nonnull_error` (added definition); `test_signed_minimum_and_out_of_range_output` (added definition); `test_generated_input_parses_decimal_strings_to_python_int` (added definition); `test_bigint_rejects_invalid_variables_before_resolver` (added definition); `test_bigint_accepts_only_string_literals` (added definition); `test_positive_bigint_validation_keeps_nonnegative_constraint` (added definition); `test_relation_ids_with_explicit_bigint_pk_keep_old_input_type` (added definition); `test_bigint_foreign_key_id_mutation_accepts_existing_wire_values` (added definition); `test_positive_bigint_numeric_choice_mutation_accepts_valid_enum` (added definition); `test_generated_model_mutation_persists_exact_bigint` (added definition); `test_automatic_filter_lookups_use_bigint` (added definition); `test_automatic_bigint_filter_executes_orm_query` (added definition).


### A9 — A protected generated delete could expose raw database/model details instead of a safe mutation error

**Status:** bounded-fixed

**Original problem:** A protected generated delete could expose raw database/model details instead of a safe mutation error. [original audit](auditoria-django-graphex-4.0.0.md), lines 88. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 203; [task T10a/T10](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** delete protected row. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"mutation": "generated delete", "row_id": 7, "constraint": "protected relation"}
```

**Before (illustrative):**
```json
{"errors": ["database constraint/table detail"]}
```

**After (observed/current):**
```json
{"errors": ["safe generated delete error"]}
```

**How the result was reached:**
1. The generated delete error path maps protected and unmapped database integrity failures to a safe GraphQL mutation error. It does not catch arbitrary application exceptions or expose constraint/model names.
2. `74146dd55f74108b9b3c4b5d913c2a21b36c550a`: source changes in [django_graphex/mutation.py](django_graphex/mutation.py), [django_graphex/types.py](django_graphex/types.py). Follow-up source commits: `8db3083585f44e65cbf5f7eba496f3b4e004e728`.
3. Scope check: Generated delete errors redact underlying database detail; arbitrary DB exceptions were not given a blanket catch.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_generated_delete_security.py](tests/test_generated_delete_security.py), `test_blocked_generated_delete_hides_collector_details` (short source excerpt, not a reconstructed failure):
   ```python
   assert payload["data"] == {"deleteCategory": None}
   ```
   - [tests/test_generated_delete_security.py](tests/test_generated_delete_security.py): `test_blocked_generated_delete_hides_collector_details` (added definition); `test_blocked_delete_preserves_sibling_rollback` (added definition); `test_generated_delete_keeps_success_and_not_found_contract` (added definition); `test_unclassified_integrity_error_uses_generic_generated_policy` (added definition).


### A10 — Generated inputs and nested saves missed selected Django validation paths and surfaced raw IntegrityError details

**Status:** partial

**Original problem:** Generated inputs and nested saves missed selected Django validation paths and surfaced raw IntegrityError details. [original audit](auditoria-django-graphex-4.0.0.md), lines 89. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 204; [task T10](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** create email="not-an-email" or positive=-1. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"generated_create": {"email": "not-an-email", "positive_count": -1}}
```

**Before (illustrative):**
```json
{"save_attempt": "invalid covered values reached persistence"}
```

**After (observed/current):**
```json
{"save_attempt": false, "errors": ["email/positive input validation"]}
```

**How the result was reached:**
1. Generated input conversion validates covered positive-number and email shapes before persistence and redacts mapped write failures. It does not call full_clean on every model or make nested upserts atomic.
2. `6bd37b2d9dcac7359f3f0c94fc47f65a350bac5f`: source changes in [django_graphex/core/fields.py](django_graphex/core/fields.py). Follow-up source commits: `81f79492a3b5906687194cbf143ca483c80cfee9`, `610162956ca645d85bf7e7749a19ada81aac055f`.
3. Scope check: Email input, two positive-number fields, and generated DB-error redaction have bounded fixes; a general full-clean/upsert policy remains open.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_positive_input_validation.py](tests/core/test_positive_input_validation.py), `test_positive_validator_preserves_null_and_reports_invalid_choice_value` (short source excerpt, not a reconstructed failure):
   ```python
   assert validator(None) is None
   ```
   - [tests/core/test_positive_input_validation.py](tests/core/test_positive_input_validation.py): `test_positive_validator_preserves_null_and_reports_invalid_choice_value` (added definition); `test_generated_positive_input_rejects_negative_before_sql` (added definition); `test_positive_field_error_preserves_earlier_sibling_write` (added definition); `test_positive_choices_validate_stored_number_and_keep_enum` (added definition); `test_custom_schema_preserves_nullable_positive_choice_enum` (added definition); `test_nested_positive_input_rejects_child_before_parent_persists` (added definition).


### A11 — A replace directive could expand one input into a huge string before any output-length check

**Status:** bounded-fixed

**Original problem:** A replace directive could expand one input into a huge string before any output-length check. [original audit](auditoria-django-graphex-4.0.0.md), lines 90. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 205; [task T04b/T04](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** @replace(old:"",new:"long") on repeated input. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"directive": "@replace", "source": "aaaa", "old": "", "new": "long", "max_output_length": 8}
```

**Before (illustrative):**
```json
{"result": "expansion longer than 8 code points"}
```

**After (observed/current):**
```json
{"error": "result exceeds configured output cap"}
```

**How the result was reached:**
1. The replace directive computes a bounded prospective Unicode result before allocating the full expansion. Oversized single outputs fail; many individually small outputs have no new aggregate quota.
2. `441899a520778e03518d81816eef0ddbd00dab8a`: source changes in [django_graphex/directives/string.py](django_graphex/directives/string.py), [django_graphex/settings.py](django_graphex/settings.py).
3. Scope check: A single result is bounded by a Unicode-aware output cap; an aggregate multi-result response quota was not added.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_replace_output_limit.py](tests/test_replace_output_limit.py), `test_replace_rejects_expansion_before_returning_result` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data == {"text": None, "other": "safe"}
   ```
   - [tests/test_replace_output_limit.py](tests/test_replace_output_limit.py): `test_replace_rejects_expansion_before_returning_result` (added definition); `test_replace_nonnull_error_bubbles` (added definition); `test_replace_limit_default_is_one_million` (added definition); `test_replace_limit_rejects_nonpositive_values` (added definition); `test_replace_limit_rejects_noninteger_values` (added definition); `test_replace_limit_none_preserves_uncapped_behavior` (added definition); `test_replace_exact_python_semantics` (added definition); `test_replace_rejects_already_oversized_noop` (added definition); `test_replace_rejects_without_calling_replace` (added definition); `test_replace_preserves_null_field` (added definition).


### A12 — AND predicates across a to-many relation reused one JOIN and required two values on the same related row

**Status:** bounded-fixed

**Original problem:** AND predicates across a to-many relation reused one JOIN and required two values on the same related row. [original audit](auditoria-django-graphex-4.0.0.md), lines 91. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 206; [task T11/T11c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** post has tag x and tag y; AND two tag filters. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"post_id": 1, "tags": ["x", "y"], "filter": {"AND": [{"tag": "x"}, {"tag": "y"}]}}
```

**Before (illustrative):**
```json
{"result_ids": []}
```

**After (observed/current):**
```json
{"result_ids": [1]}
```

**How the result was reached:**
1. The filter backend gives distinct to-many AND branches separate relational predicates, allowing different related rows to satisfy each branch. Predicates grouped inside one branch still refer to the same related row.
2. `342a4ab92b2797e142a325d11311495cfc5808e2`: source changes in [django_graphex/filtering/backend.py](django_graphex/filtering/backend.py). Follow-up source commits: `4c3e4bbd0df9948c53eb3d2d4846064571934d10`.
3. Scope check: AND across a to-many relation can match independent related rows; one relation predicate still uses same-row semantics.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_and_many_filtering.py](tests/test_and_many_filtering.py), `test_public_deeper_and_keeps_one_outer_comment` (short source excerpt, not a reconstructed failure):
   ```python
   assert sorted(row["title"] for row in rows["results"]) == expected
   ```
   - [tests/test_and_many_filtering.py](tests/test_and_many_filtering.py): `test_public_deeper_and_keeps_one_outer_comment` (added definition); `test_public_deeper_grouping_and_missing_child_sql_null` (added definition); `test_public_m2m_and_branches_match_distinct_rows` (added definition); `test_public_reverse_fk_and_branches_match_distinct_rows` (added definition); `test_public_and_keeps_relation_object_same_row` (added definition); `test_public_nested_or_not_and_multihop_correlation` (added definition); `test_public_exact_null_and_isnull_keep_absent_reverse_row` (added definition); `test_empty_boolean_operands_and_direct_many_ids` (added definition); `test_unset_boolean_children_keep_independent_branch` (added definition); `test_scoped_queryset_alias_projection_and_one_sql` (added definition); `test_public_paginated_count_and_variables` (added definition).


### A13 — An in-memory cursor decoded Float, Decimal or UUID values as strings and compared unlike types

**Status:** partial

**Original problem:** An in-memory cursor decoded Float, Decimal or UUID values as strings and compared unlike types. [original audit](auditoria-django-graphex-4.0.0.md), lines 92. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 207; [task T12](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** second page after Decimal or UUID cursor. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"order_field": "Decimal", "cursor": "typed boundary at 1.25", "next_page": true}
```

**Before (illustrative):**
```json
{"error": "string/Decimal comparison TypeError"}
```

**After (observed/current):**
```json
{"continuation": "next matching window", "malformed_cursor": "GraphQL error"}
```

**How the result was reached:**
1. Cursor decoding restores typed Float, Decimal, and UUID bounds before in-memory comparison and rejects malformed values. The fix is for covered typed continuations, not a redesign of every cursor backend.
2. `e18f02b8b15b7cdfaf1fad06adc545527f1f8026`: source changes in [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py). Follow-up source commits: `c3a063aeaaa0e765d9b3d3dc7749168ec6f2c842`.
3. Scope check: valid Float/Decimal/UUID continuation + invalid decoded bounds; other cursor policies open.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_pagination_cursor_typed_http.py](tests/test_pagination_cursor_typed_http.py), `test_generated_root_cursor_and_nested_relation_http` (short source excerpt, not a reconstructed failure):
   ```python
   assert token == nested_first["pageInfo"]["endCursor"]
   ```
   - [tests/test_pagination_cursor_typed_http.py](tests/test_pagination_cursor_typed_http.py): `test_generated_root_cursor_and_nested_relation_http` (added definition); `test_malformed_cursor_is_existing_graphql_error_envelope` (added definition); `test_typed_invalid_cursor_value_http_error` (added definition); `test_typed_invalid_cursor_direct_pagination_and_page_info` (added definition); `test_unapproved_other_type_coercion_fallback_is_unchanged` (added definition); `test_tied_boundaries_match_orm_in_both_orderings` (added definition).


### SD1 — Destination get_queryset was skipped across automatic relation reads, allowing hidden targets to be traversed

**Status:** partial

**Original problem:** Destination get_queryset was skipped across automatic relation reads, allowing hidden targets to be traversed. [original audit](auditoria-django-graphex-4.0.0.md), lines 98–99. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 208; [task T07/R06a/R06f/R06g](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** visible parent points to hidden target. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"parent_id": 1, "destination_id": 9, "destination_visible": false}
```

**Before (illustrative):**
```json
{"data": {"parent": {"destination": {"id": 9}}}}
```

**After (observed/current):**
```json
{"data": {"parent": {"destination": null}}}
```

**How the result was reached:**
1. Automatic relation fields scope destination querysets before exposing FK, one-to-one, reverse-FK, and M2M values or counts. Custom resolvers are not silently rewritten into this policy.
2. `0ee46b94bb391bb59c599f9e88af46ce0a8f0f1b`: source changes in [django_graphex/converter.py](django_graphex/converter.py), [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/utils.py](django_graphex/utils.py). Follow-up source commits: `603a117f67a41502f93d6551dbc5355c592b23ca`, `8ebfd43fce7071660795398e70f90ed0e2359054`.
3. Scope check: Automatic forward-FK/reverse-FK, forward/reverse OneToOne, and declared/reverse M2M outputs apply destination get_queryset. M2M results/counts exclude hidden targets before pagination; custom output resolvers and through-model access remain separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_sd1_m2m_output_scope.py](tests/test_sd1_m2m_output_scope.py), `test_optimized_m2m_scope_uses_source_database_alias` (short source excerpt, not a reconstructed failure):
   ```python
   assert context.calls
   ```
   - [tests/test_sd1_m2m_output_scope.py](tests/test_sd1_m2m_output_scope.py): `test_optimized_m2m_scope_uses_source_database_alias` (added definition); `test_declared_m2m_members_follow_destination_scope` (added definition); `test_reverse_m2m_members_follow_destination_scope` (added definition); `test_declared_m2m_count_only_is_scoped` (added definition); `test_reverse_m2m_count_only_is_scoped` (added definition); `test_m2m_scope_uses_current_request_and_compiled_schema` (added definition); `test_m2m_count_precedes_nested_page_limit` (added definition); `test_unscoped_prefetch_cache_cannot_authorize_m2m_output` (added definition); `test_custom_through_and_reverse_accessor_scope_m2m_output` (added definition); `test_optimized_scoped_m2m_prefetch_does_not_grow_per_parent` (added definition).


### SD2 — Filters through relations could reveal hidden targets as an existence oracle despite root queryset scoping

**Status:** partial

**Original problem:** Filters through relations could reveal hidden targets as an existence oracle despite root queryset scoping. [original audit](auditoria-django-graphex-4.0.0.md), lines 100. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 209; [task T07/R06b/R06c/R06d/R06e](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** filter source by hidden related row. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"source_id": 1, "children": [{"id": 7, "visible": false, "tag": "x"}], "filter": {"child_tag": "x"}}
```

**Before (illustrative):**
```json
{"result_ids": [1]}
```

**After (observed/current):**
```json
{"result_ids": [], "direct_source_fk_id": "unchanged"}
```

**How the result was reached:**
1. Relation-filter translation intersects traversed destination IDs with each destination get_queryset. For reverse-FK and M2M, predicates against the same child use one visible child witness rather than combining facts from different children; direct reverse-child/M2M target IDs are scoped. A direct source FK/OneToOne ID is owned by the source and retains its old meaning. Output projection scope is a different boundary.
2. `0f64533aff4210b77f4b4659d74fa264f46cf283`: source changes in [django_graphex/filtering/backend.py](django_graphex/filtering/backend.py). Follow-up source commits: `603a117f67a41502f93d6551dbc5355c592b23ca`.
3. Scope check: Forward-FK, forward-OneToOne, reverse-FK and M2M filters apply each traversed destination get_queryset. Reverse-FK and M2M predicates use one visible child witness; direct reverse child and M2M target IDs are scoped, while direct source FK/OneToOne IDs remain source-owned. Output scopes are separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_sd2_forward_o2o_filter_scope.py](tests/test_sd2_forward_o2o_filter_scope.py), `test_forward_and_reverse_destination_policies` (short source excerpt, not a reconstructed failure):
   ```python
   assert found == ["visible-user"]
   ```
   - [tests/test_sd2_forward_o2o_filter_scope.py](tests/test_sd2_forward_o2o_filter_scope.py): `test_forward_and_reverse_destination_policies` (added definition); `test_null_and_direct_id_controls` (added definition); `test_boolean_and_empty_forward_nodes_keep_visible_sources` (added definition); `test_reverse_then_forward_one_to_one_scopes_each_destination` (added definition); `test_forward_scope_errors_fail_closed` (added definition).

**Important scope distinction:** With one visible source and two related children, `child.color="red" AND child.size="large"` must use the **same visible child** as witness; one red-only child plus one large-only child is not a match. A hidden child is never a witness. Direct reverse child/M2M target IDs are destination-scoped; a direct FK/OneToOne ID belonging to the source is not silently redefined. See `tests/test_sd2_forward_o2o_filter_scope.py` and the accepted guide row; custom traversal and output scopes remain separate.


### SD3 — Generated FK/M2M mutation links accepted a destination ID hidden from the caller

**Status:** bounded-fixed

**Original problem:** Generated FK/M2M mutation links accepted a destination ID hidden from the caller. [original audit](auditoria-django-graphex-4.0.0.md), lines 101. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 210; [task T07c/T07](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** link category ID from another tenant. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"mutation": "link category", "category_id": 9, "category_visible": false}
```

**Before (illustrative):**
```json
{"linked_category_id": 9}
```

**After (observed/current):**
```json
{"error": "destination not visible", "linked_category_id": null}
```

**How the result was reached:**
1. Generated nested relation linking resolves each submitted target ID through the destination's visible candidate set before assignment. A hidden ID fails link construction rather than being attached and later concealed.
2. `a96ca179b90714f39c4b69a79ebb24255aa17578`: source changes in [django_graphex/nested.py](django_graphex/nested.py), [django_graphex/utils.py](django_graphex/utils.py).
3. Scope check: Generated FK/M2M destination IDs are checked against the caller's visible choices; this does not make all relation reads globally scoped.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_destination_link_scope.py](tests/test_destination_link_scope.py), `test_hidden_relation_id_has_the_same_error_as_missing` (short source excerpt, not a reconstructed failure):
   ```python
   assert not Post.objects.filter(title__in=("hidden-link", "missing-link")).exists()
   ```
   - [tests/test_destination_link_scope.py](tests/test_destination_link_scope.py): `test_hidden_relation_id_has_the_same_error_as_missing` (added definition); `test_nested_link_is_scoped_before_parent_save` (added definition); `test_existing_nested_child_update_is_not_reclassified_as_a_link` (added definition); `test_request_registry_not_global_registry_selects_destination_scope` (added definition); `test_unregistered_destination_adds_no_fk_lookup` (added definition); `test_destination_hook_for_wrong_model_fails_before_write` (added definition).


### SD4 — A nullable reverse-FK orphan could be adopted by an unrelated parent using its primary key

**Status:** bounded-fixed

**Original problem:** A nullable reverse-FK orphan could be adopted by an unrelated parent using its primary key. [original audit](auditoria-django-graphex-4.0.0.md), lines 102. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 211; [task T07/T07d/T07e](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** parent 10 adopts parentless child 7. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"parent_id": 10, "child_id": 7, "child_parent_id": null}
```

**Before (illustrative):**
```json
{"child_parent_id": 10}
```

**After (observed/current):**
```json
{"error": "orphan adoption denied", "child_parent_id": null}
```

**How the result was reached:**
1. Reverse-FK nested update requires the child to belong to the current host before adoption. A parentless row cannot be claimed merely by presenting its primary key.
2. `bb592ddb7c1e90e0300ee4be8f30252b2c19d6a6`: source changes in [django_graphex/nested.py](django_graphex/nested.py).
3. Scope check: hostless nullable reverse-FK orphan adoption denied only.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_nested_sd4_orphan_scope.py](tests/test_nested_sd4_orphan_scope.py), `test_existing_orphan_requires_child_update_host` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data["updateParent"]["ok"] is False
   ```
   - [tests/test_nested_sd4_orphan_scope.py](tests/test_nested_sd4_orphan_scope.py): `test_existing_orphan_requires_child_update_host` (added definition); `test_update_host_preserves_scope_and_child_permission` (added definition); `test_existing_owned_and_new_children_keep_prior_paths` (added definition); `test_later_orphan_denial_rolls_back_earlier_sibling_write` (added definition); `test_update_serving_mutation_host_admits_visible_orphan` (added definition); `test_unrelated_registry_cannot_supply_child_update_host` (added definition); `test_parent_create_keeps_new_child_path` (added definition).


### SD5 — Flat GenericForeignKey metadata disclosed target app, model and key even when target access was denied

**Status:** bounded-fixed

**Original problem:** Flat GenericForeignKey metadata disclosed target app, model and key even when target access was denied. [original audit](auditoria-django-graphex-4.0.0.md), lines 103. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 212; [task T07/T07d/T07f](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** GFK target is hidden. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"query": "{ comment { body target { appLabel modelName id } } }", "permissions": ["tests.view_track2gfkcomment"], "target_exists": true}
```

**Before (illustrative):**
```json
{"data": {"comment": {"body": "public", "target": {"appLabel": "tests", "modelName": "Track2Account", "id": "<target id>"}}}}
```

**After (observed/current):**
```json
{"data": {"comment": {"body": "public", "target": null}}}
```

**How the result was reached:**
1. The permission pruner checks the GenericForeignKey target before projecting flat app, model, and key metadata. If target read/scope fails, it drops those flat fields together.
2. `f0b3126260224c62ff1422e1e8e86ba5d8bf11bb`: source changes in [django_graphex/core/_flat_gfk_scope.py](django_graphex/core/_flat_gfk_scope.py), [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py), [django_graphex/core/permission_signature_cache.py](django_graphex/core/permission_signature_cache.py), [django_graphex/core/schema_pruner.py](django_graphex/core/schema_pruner.py), [django_graphex/views.py](django_graphex/views.py).
3. Scope check: flat GFK metadata pruned on target read/scope denial; not global ACL.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_flat_gfk_pruned_security.py](tests/test_flat_gfk_pruned_security.py), `test_flat_target_denied_by_actual_model_permission` (short source excerpt, not a reconstructed failure):
   ```python
   assert print_schema(denied) == print_schema(allowed)
   ```
   - [tests/test_flat_gfk_pruned_security.py](tests/test_flat_gfk_pruned_security.py): `test_flat_target_denied_by_actual_model_permission` (added definition); `test_missing_flat_target_stays_null` (added definition); `test_flat_target_uses_registered_scope_per_request` (added definition); `test_registered_default_hook_adds_no_membership_query` (added definition); `test_invalid_registered_scope_fails_closed` (added definition); `test_registered_scope_preserves_join_and_slice_membership` (added definition); `test_flat_cache_keys_unregistered_target_grants` (added definition); `test_explicit_prune_grants_never_widen_from_context_or_reprune` (added definition); `test_unmarked_schema_keeps_projected_signature` (added definition); `test_http_cache_rechecks_same_users_target_grant` (added definition).


### SD6 — The audit proposed strict_scope and a system check as a broader product/security policy, not a demonstrated…

**Status:** recommendation

**Original problem:** The audit proposed strict_scope and a system check as a broader product/security policy, not a demonstrated single-line repair. [original audit](auditoria-django-graphex-4.0.0.md), lines 105. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 213; [task T07](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** proposed strict_scope=True for all relations. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"current opt-in relation behavior"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. No strict_scope option or Django system check was installed. Such a default would reject schemas that currently opt into relation scoping and needs a separate public compatibility decision.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: strict_scope/system-check recommendation; public semantics need decision.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### M-S1 — Variable-backed operations could bypass a selected operation's cost estimate before execution

**Status:** bounded-fixed

**Original problem:** Variable-backed operations could bypass a selected operation's cost estimate before execution. [original audit](auditoria-django-graphex-4.0.0.md), lines 114. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 214; [task T13/T13a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** variable selects expensive branch. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"query": "query Probe($n: Int = 5) { items(limit: $n) { child { name } } }", "operationName": "Probe", "variables": {"n": 150}, "MAX_QUERY_COST": 120}
```

**Before (illustrative):**
```json
{"resolver_calls": 1}
```

**After (observed/current):**
```json
{"resolver_calls": 0, "status": 400, "error_code": "QUERY_TOO_COMPLEX", "computed_cost": 151}
```

**How the result was reached:**
1. The selected operation is analyzed with supplied variable values before resolver execution, and a cost above the configured threshold is rejected. This is an execution guard, not a SQL or memory budget.
2. `96e1f9efb0569d27a08235c84656cf6be100caf1`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: variable-backed cost limits; no hard memory/DB cap.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_cost_variable_http.py](tests/test_cost_variable_http.py), `test_high_variable_is_rejected_before_resolver_on_validation_cache_hits` (short source excerpt, not a reconstructed failure):
   ```python
   assert validate_spy.call_count == 1
   ```
   - [tests/test_cost_variable_http.py](tests/test_cost_variable_http.py): `test_high_variable_is_rejected_before_resolver_on_validation_cache_hits` (added definition); `test_small_and_declared_default_variables_remain_accepted` (added definition); `test_high_declared_default_is_checked_when_variable_is_omitted` (added definition); `test_no_cost_budget_remains_a_noop` (added definition); `test_static_fallback_still_rejects_a_small_bound_variable` (added definition); `test_only_selected_operation_is_bound_checked_and_invalid_input_keeps_its_error` (added definition); `test_unselected_operation_still_receives_static_validation` (added definition); `test_bound_skip_directive_controls_actual_cost` (added definition); `test_custom_scalar_and_executor_build_once_before_cost_refusal` (added definition); `test_input_default_factories_are_not_recoerced_for_bound_cost` (added definition).


### M-S2 — Several public resource defaults were described as permissive without separating page size from depth/width/byte…

**Status:** partial

**Original problem:** Several public resource defaults were described as permissive without separating page size from depth/width/byte limits. [original audit](auditoria-django-graphex-4.0.0.md), lines 115. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 215; [task T11/T13/R07](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** omitted pageSize on paginated field. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"paginated_field": "posts", "pageSize": "omitted", "configured_default": 100}
```

**Before (illustrative):**
```json
{"default_bound": "not established by original premise"}
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Inspection separated the already accepted page-size default of 100 from depth, width, and byte-limit policies. No extra resource default was changed to satisfy a bundled allegation.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
   The page-size 100 default is the separate `M-F7` change (`5faeef7188`); this row did not add depth, width, or retained-byte defaults.
3. Scope check: default page size 100 already fixed; other defaults/width/depth unverified/policy, LRU not byte-cap proof.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### M-S3 — Introspection middleware behavior was asserted without accounting for the configured opt-in middleware contract

**Status:** contract

**Original problem:** Introspection middleware behavior was asserted without accounting for the configured opt-in middleware contract. [original audit](auditoria-django-graphex-4.0.0.md), lines 116. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 216; [task T13/T13g](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** request introspection without configured middleware. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"audit assumes hard block by default"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The documented introspection guard remains conditional on installing the middleware. No default middleware was silently added; deployment must configure the opt-in boundary.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: The guide now states the configured introspection middleware requirement; the runtime default itself did not change.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_introspection_docs.py](tests/test_introspection_docs.py), `test_security_guide_installs_middleware_before_blocking_introspection` (short source excerpt, not a reconstructed failure):
   ```python
   assert configuration["ALLOW_INTROSPECTION"] is False
   ```
   - [tests/test_introspection_docs.py](tests/test_introspection_docs.py): `test_security_guide_installs_middleware_before_blocking_introspection` (added definition); `test_introspection_setting_requires_installed_middleware` (added definition).


### M-S4 — Unexpected production-mode GraphQL HTTP errors could leak internal exception details

**Status:** bounded-fixed

**Original problem:** Unexpected production-mode GraphQL HTTP errors could leak internal exception details. [original audit](auditoria-django-graphex-4.0.0.md), lines 117. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 217; [task T13/T13c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** production resolver raises internal exception. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"environment": "production", "resolver_exception": "database table secret"}
```

**Before (illustrative):**
```json
{"errors": ["database table secret"]}
```

**After (observed/current):**
```json
{"errors": ["sanitized internal error"]}
```

**How the result was reached:**
1. The production HTTP view classifies unexpected execution exceptions and emits redacted GraphQL error content rather than raw internal details. Development diagnostics and other error classes remain distinct.
2. `a401f9e25e6989ccb28571815931fc6baf624593`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: Production-mode HTTP errors no longer expose the covered internal detail; this is a bounded response contract, not a blanket leak audit.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_http_internal_error_diagnostics.py](tests/test_http_internal_error_diagnostics.py), `test_internal_failures_have_safe_http_diagnostics_and_correlated_logs` (short source excerpt, not a reconstructed failure):
   ```python
   assert payload["data"] == {"healthy": "healthy", "failure": None}
   ```
   - [tests/test_http_internal_error_diagnostics.py](tests/test_http_internal_error_diagnostics.py): `test_internal_failures_have_safe_http_diagnostics_and_correlated_logs` (added definition); `test_ids_are_unique_and_wrapped_internal_extensions_are_dropped` (added definition); `test_public_errors_validation_and_http_parse_errors_keep_their_contract` (added definition); `test_debug_and_shared_transport_formatter_keep_existing_diagnostics` (added definition); `test_shared_formatter_is_unchanged_in_production` (added definition); `test_nonnull_error_keeps_null_data_and_safe_message_in_every_view` (added definition); `test_logger_failure_cannot_change_safe_http_response` (added definition); `test_custom_view_formatter_remains_an_explicit_override` (added definition); `test_production_error_documentation_example_matches_the_wire_contract` (added definition).


### M-S5 — GET response-cache key components were concatenated ambiguously inside one identity partition

**Status:** bounded-fixed

**Original problem:** GET response-cache key components were concatenated ambiguously inside one identity partition. [original audit](auditoria-django-graphex-4.0.0.md), lines 118. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 218; [task T13/T13b](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** cache parts ["ab","c"] versus ["a","bc"]. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"key_parts_a": ["ab", "c"], "key_parts_b": ["a", "bc"]}
```

**Before (illustrative):**
```json
{"encoded_a": "abc", "encoded_b": "abc"}
```

**After (observed/current):**
```json
{"encoded_a": "2:ab1:c", "encoded_b": "1:a2:bc"}
```

**How the result was reached:**
1. Cache-key construction frames request components with lengths before hashing; ambiguous concatenations can no longer alias within the same identity partition. It does not redesign cross-identity policy.
2. `d9d2c40f7bb4af2fc2125f76d344c124f8a3df74`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: GET cache-key components are length-framed so adjacent values cannot collide inside one identity partition; cross-identity policy is separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_views_cache_key_framing.py](tests/test_views_cache_key_framing.py), `test_comment_boundary_cannot_select_another_cached_operation` (short source excerpt, not a reconstructed failure):
   ```python
   assert response.status_code == 200
   ```
   - [tests/test_views_cache_key_framing.py](tests/test_views_cache_key_framing.py): `test_comment_boundary_cannot_select_another_cached_operation` (added definition); `test_get_components_and_body_have_unambiguous_boundaries` (added definition); `test_get_raw_body_is_documented_and_changes_default_cache_key` (added definition); `test_utf8_and_framing_like_text_cannot_cross_get_components` (added definition); `test_frame_length_counts_utf8_bytes` (added definition); `test_missing_and_empty_get_parameters_remain_equivalent` (added definition); `test_custom_fetch_cache_key_override_remains_in_dispatch` (added definition).


### M-S6 — A shortcut permission keyword was assumed to work although only the documented lower-case field keyword was…

**Status:** contract

**Original problem:** A shortcut permission keyword was assumed to work although only the documented lower-case field keyword was supported. [original audit](auditoria-django-graphex-4.0.0.md), lines 119. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 219; [task T06](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** shortcut(required_perms=["x"]). The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"assumed accepted by audit"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The checked field API accepts its documented lower-case permission keyword, not the proposed shortcut required_perms. Keeping the TypeError avoids inventing a new public signature.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: shortcut required_perms raises TypeError; lowercase field works; untagged public documented.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_permission_keyword_boundaries.py](tests/test_permission_keyword_boundaries.py), `test_permission_hook_excludes_positional_only_and_varargs_names` (short source excerpt, not a reconstructed failure):
   ```python
   assert policy(object(), action=narrowed["action"]) == "list"
   ```
   - [tests/test_permission_keyword_boundaries.py](tests/test_permission_keyword_boundaries.py): `test_permission_hook_excludes_positional_only_and_varargs_names` (historical locator; not in the changed-path inventory).


### M-D1 — A stale backend model instance can overwrite another update because save writes more columns than the partial…

**Status:** partial

**Original problem:** A stale backend model instance can overwrite another update because save writes more columns than the partial input supplied. [original audit](auditoria-django-graphex-4.0.0.md), lines 124. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 220; [task T05](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** instance A loads title old; B writes title new; A saves bio. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"loaded_instance": {"title": "old", "bio": "old"}, "other_writer": {"title": "new"}, "first_instance_save": {"bio": "new"}}
```

**Before (illustrative):**
```json
{"final_title": "old"}
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. A sequential stale-instance witness confirmed that a broad save can overwrite a newer column value. The report records the lost-update risk; it did not add universal update_fields or claim a PostgreSQL race test.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: external current native 3.3 witness shows sequential stale backend instance overwrites separately updated bio; not a threaded/PostgreSQL race. update_fields policy deferred for auto_now/custom save behavior.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### M-D2 — Nested CREATE routing across databases could produce writes on the wrong alias or partial state

**Status:** partial

**Original problem:** Nested CREATE routing across databases could produce writes on the wrong alias or partial state. [original audit](auditoria-django-graphex-4.0.0.md), lines 125. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 221; [task T05/T08/R05b/R05c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** nested CREATE parent routed to alias B. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"nested_create": {"parent": "new", "child": "new"}, "parent_alias": "B", "through_route_after_generated_id": "A"}
```

**Before (illustrative):**
```json
{"possible_child_alias": "A", "possible_partial_write": true}
```

**After (observed/current):**
```json
{"alias_B_rows_after_rollback": 0, "alias_A_through_rows": 0}
```

**How the result was reached:**
1. The included Django backend chooses the populated unsaved parent write alias and pins child writes to it. It checks an explicit M2M through-table route before any DML, then rechecks after a generated parent ID before linking; later divergence rolls back writes in that local alias. UPDATE alias behavior, custom backends, cross-database atomicity, and route changes after final check remain distinct.
2. `c408989f75d4d4f5729edd5296d93c36108f8efe`: source changes in [django_graphex/nested.py](django_graphex/nested.py). Follow-up source commits: `57e0aaba2de6954f6aa1dc10b4ea690d4e16a686`.
3. Scope check: The included Django backend routes a populated unsaved parent for nested CREATE and pins native nested writes to that alias; divergent M2M through routing is checked before writes and again before linking after a generated ID, rolling back local writes on later divergence. UPDATE keeps its existing alias. Custom backends, cross-DB atomicity, and changing router answers between check and link remain separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_routed_nested_atomic.py](tests/test_routed_nested_atomic.py), `test_explicit_divergent_through_router_rejects_before_any_write` (short source excerpt, not a reconstructed failure):
   ```python
   assert writes == []
   ```
   - [tests/test_routed_nested_atomic.py](tests/test_routed_nested_atomic.py): `test_explicit_divergent_through_router_rejects_before_any_write` (added definition); `test_post_id_divergent_through_router_rolls_back_without_foreign_sql` (added definition); `test_late_failure_after_real_writes_rolls_back_chosen_alias` (added definition); `test_later_child_failure_rolls_back_create` (added definition); `test_later_child_failure_rolls_back_update` (added definition); `test_nested_create_succeeds_on_own_alias` (added definition); `test_populated_parent_routes_entire_nested_create_to_one_alias` (added definition); `test_instance_routed_create_initializes_once_and_commits_only_on_success` (added definition); `test_instance_routed_forward_and_m2m_writes_share_parent_boundary` (added definition); `test_custom_backend_keeps_existing_create_instance_contract` (added definition); `test_nested_routing_contract_documents_native_instance_create_boundary` (added definition).

**Two routing checkpoints:** (1) For an explicit cross-alias M2M through route, reject before DML. (2) For a route that changes once the database assigns the parent PK, re-evaluate before the link and roll back writes in the selected local alias on divergence. This does not make writes on multiple databases one transaction, and cannot guarantee a router answer will remain fixed after the final check. `tests/test_routed_nested_atomic.py` exercises these distinct cases.


### M-D3 — Mapping Decimal output to Float lost precision at 17 or more significant digits even when serialization succeeded

**Status:** partial

**Original problem:** Mapping Decimal output to Float lost precision at 17 or more significant digits even when serialization succeeded. [original audit](auditoria-django-graphex-4.0.0.md), lines 126. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 222; [task T03c/T03](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** Decimal("9007199254740993") output. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"model_value": "Decimal(\"9007199254740993\")"}
```

**Before (illustrative):**
```json
{"graphql_output": 9007199254740992}
```

**After (observed/current):**
```json
{"graphql_output": "9007199254740993"}
```

**How the result was reached:**
1. Auto-derived Decimal output now uses the exact decimal-string scalar instead of floating-point conversion. SQLite reload rounding and input coercion are separate boundaries, not evidence against output precision.
2. `d27832188f55e72d88551c16e077032d633c9875`: source changes in [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py).
3. Scope check: Decimal output avoids Float precision loss; SQLite reload rounding and input coercion remain separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py), `test_automatic_decimal_output_preserves_exact_text` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data == {"item": {"amount": str(amount), "ratio": 1.5}}
   ```
   - [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py): `test_automatic_decimal_output_preserves_exact_text` (added definition); `test_automatic_decimal_primary_key_uses_decimal_nonnull` (added definition); `test_automatic_decimal_field_executes_as_exact_decimal` (added definition); `test_explicit_decimal_scalar_and_input_mapping_stay_precise` (added definition); `test_explicit_float_resolver_retains_legacy_numeric_contract` (added definition); `test_decimal_filter_literals_and_variables_remain_precise` (added definition); `test_generated_create_mutation_returns_exact_decimal_output` (added definition); `test_decimal_primary_key_keeps_nonnull_and_exact_output` (added definition); `test_null_decimal_primary_key_propagates_nonnull_error` (added definition).


### M-D4 — The Decimal scalar allegedly accepted non-finite or extreme exponents that could fail later in Django validation

**Status:** partial

**Original problem:** The Decimal scalar allegedly accepted non-finite or extreme exponents that could fail later in Django validation. [original audit](auditoria-django-graphex-4.0.0.md), lines 127. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 223; [task T03](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** Decimal input NaN / Infinity / 1e1000. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"generated_mutation_decimal": "NaN"}
```

**Before (illustrative):**
```json
{"save_attempt": "possible downstream validation failure"}
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The public mutation rejects NaN, both infinities, and the exercised extreme exponent before saving. The specific 1E+999999999 token in the audit was not run, so its exact failure path is not asserted.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: public mutation rejects NaN/±Infinity/1e1000 structurally/no save; exact 1E+999999999 untested.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### M-D5 — The audit conflated raw JSONField strings with the JSONString scalar's intentional JSON-text decoding

**Status:** contract

**Original problem:** The audit conflated raw JSONField strings with the JSONString scalar's intentional JSON-text decoding. [original audit](auditoria-django-graphex-4.0.0.md), lines 128. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 224; [task T15](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** JSONField input "123" vs JSONString input "123". The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"audit treats both as numeric coercion"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. A raw JSONField string is preserved through input, database and output; JSONString deliberately parses JSON text into a JSON value. These are two scalar contracts, not a single decoding defect.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: Public model JSONField input string '123' stays a string through DB/output; separate JSONString intentionally decodes JSON text to integer 123.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_explicit_null_and_json_input.py](tests/test_explicit_null_and_json_input.py), `test_python_type_mapping_via_build_model_schema` (short source excerpt, not a reconstructed failure):
   ```python
   assert isinstance(gql_input, GraphQLInputObjectType)
   ```
   - [tests/test_explicit_null_and_json_input.py](tests/test_explicit_null_and_json_input.py): `test_update_bio_null_clears_field` (historical locator; not in the changed-path inventory); `test_update_bio_omitted_keeps_field` (historical locator; not in the changed-path inventory); `test_update_nullable_fk_null_clears` (historical locator; not in the changed-path inventory); `test_update_m2m_null_clears` (historical locator; not in the changed-path inventory); `test_update_m2m_empty_list_clears` (historical locator; not in the changed-path inventory); `test_update_m2m_omitted_untouched` (historical locator; not in the changed-path inventory); `test_update_required_field_null_is_validation_error` (historical locator; not in the changed-path inventory); `test_create_explicit_null_on_nullable_field` (historical locator; not in the changed-path inventory); `test_update_bio_null_clears_field` (historical locator; not in the changed-path inventory); `test_update_bio_omitted_keeps_field` (historical locator; not in the changed-path inventory); `test_update_m2m_null_clears` (historical locator; not in the changed-path inventory); `test_update_required_field_null_is_validation_error` (historical locator; not in the changed-path inventory); `test_python_type_mapping_via_build_model_schema` (historical locator; not in the changed-path inventory); `test_input_sdl_renders_json` (historical locator; not in the changed-path inventory); `test_create_stores_dict` (historical locator; not in the changed-path inventory); `test_create_stores_list` (historical locator; not in the changed-path inventory); `test_update_stores_dict` (historical locator; not in the changed-path inventory); `test_create_dict_through_graphql` (historical locator; not in the changed-path inventory); `test_json_marker_maps_to_raw_json` (historical locator; not in the changed-path inventory); `test_bare_any_still_falls_back_to_string` (historical locator; not in the changed-path inventory); `test_json_scalar_importable_from_core` (historical locator; not in the changed-path inventory); `test_jsonstring_escape_hatch_still_importable` (historical locator; not in the changed-path inventory).


### M-D6 — Missing variables inside raw JSON lists and non-finite numbers had different coercion and output-policy issues

**Status:** partial

**Original problem:** Missing variables inside raw JSON lists and non-finite numbers had different coercion and output-policy issues. [original audit](auditoria-django-graphex-4.0.0.md), lines 129. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 225; [task T15/R03i/R03j](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** [1,$missing,3] with missing variable. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"raw_json_input": [1, "omitted $v", 3], "variables": {}}
```

**Before (illustrative):**
```json
{"list_slot": "ambiguous omitted position"}
```

**After (observed/current):**
```json
{"resolver_input": [1, null, 3], "raw_1e999": "rejected before resolver"}
```

**How the result was reached:**
1. Raw JSON coercion places null in an array slot for an omitted variable while still omitting an absent object key. It rejects non-finite numeric input before resolver invocation; output policy remains distinct.
2. `3a7f2da0ac65e49d2fde02d403dbe95de664f143`: source changes in [django_graphex/core/scalars.py](django_graphex/core/scalars.py).
3. Scope check: Missing raw JSON list variables become null in place while missing object keys stay omitted; non-finite numeric raw JSON inputs now fail before resolution. Raw output and whole-ID disposition remain separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_json_nonfinite_input.py](tests/test_json_nonfinite_input.py), `test_literal_overflow_rejected_before_resolver` (short source excerpt, not a reconstructed failure):
   ```python
   assert "JSON cannot represent non-finite numbers" in result.errors[0].message
   assert _CALLS == []
   ```
   - [tests/test_json_nonfinite_input.py](tests/test_json_nonfinite_input.py): `test_literal_overflow_rejected_before_resolver` (added definition); `test_nested_variable_infinity_rejected_before_resolver` (added definition); `test_variable_nonfinite_values_fail_before_resolver` (added definition); `test_overflow_literal_shapes_fail_before_resolver` (added definition); `test_nonfinite_default_literal_rejected` (added definition); `test_available_variable_literal_path_rejects_nonfinite` (added definition); `test_finite_and_string_values_keep_identity_and_wire_shape` (added definition); `test_huge_finite_int_and_native_container_aliases_are_not_rewritten` (added definition); `test_defaults_missing_members_and_explicit_null_keep_their_contract` (added definition); `test_http_input_error_uses_graphql_error_wire` (added definition); `test_raw_output_and_json_string_scalar_remain_separate` (added definition).


### M-D7 — Generated enums sharing a name could represent incompatible choices, while equivalent reordered choices should…

**Status:** bounded-fixed

**Original problem:** Generated enums sharing a name could represent incompatible choices, while equivalent reordered choices should remain reusable. [original audit](auditoria-django-graphex-4.0.0.md), lines 130. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 226; [task T06c/T06](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** two fields produce same enum name with different values. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"enum_name": "shopOrderLineStatusEnum", "first_field_choices": ["OPEN", "CLOSED"], "second_field_choices": ["OPEN", "ARCHIVED"]}
```

**Before (illustrative):**
```json
{"second_field_reused_first_enum_values": ["OPEN", "CLOSED"]}
```

**After (observed/current):**
```json
{"error": "incompatible shopOrderLineStatusEnum registration", "first_enum_values_remain": ["OPEN", "CLOSED"]}
```

**How the result was reached:**
1. Enum creation compares name and choice-value shape before cache reuse; incompatible same-name types raise. Equivalent choices in another order reuse the enum without changing their wire values.
2. `34b37e6f014c8c6d3308dabc1427fbd68748eac6`: source changes in [django_graphex/converter.py](django_graphex/converter.py), [django_graphex/core/compiler.py](django_graphex/core/compiler.py). Follow-up source commits: `0b267dab424c506ed85b080b2754a496c39ee6c1`.
3. Scope check: incompatible same-name choices rejected; reordered equivalent kept.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_choices_enum_name_collisions.py](tests/core/test_choices_enum_name_collisions.py), `test_incompatible_choices_collision_rejects_schema` (short source excerpt, not a reconstructed failure):
   ```python
   assert set(original.values) == expected_values
   ```
   - [tests/core/test_choices_enum_name_collisions.py](tests/core/test_choices_enum_name_collisions.py): `test_incompatible_choices_collision_rejects_schema` (added definition); `test_distinct_registries_keep_colliding_names_isolated` (added definition); `test_compatible_same_name_reuses_registry_enum` (added definition); `test_colliding_choice_descriptions_are_incompatible` (added definition); `test_generated_create_input_rejects_incompatible_enum` (added definition); `test_filter_input_rejects_incompatible_enum` (added definition); `test_reordered_compatible_choices_share_public_schema_and_inputs` (added definition).


### M-D8 — Django model fields named like internal mutation helpers could collide with generated constructors

**Status:** bounded-fixed

**Original problem:** Django model fields named like internal mutation helpers could collide with generated constructors. [original audit](auditoria-django-graphex-4.0.0.md), lines 131. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 227; [task T09b/T09](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** Django model column named model_config collides with Pydantic configuration metadata. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```python
class Record(models.Model):
    model_config = models.CharField(max_length=40)
# GraphQL input: {modelConfig: "created"}; backend column: model_config
```

**Before (illustrative):**
```json
{"schema_build": "Pydantic reserved-name collision"}
```

**After (observed/current):**
```json
{"validation_alias": "model_config", "internal_field": "isolated private name", "django_value": "created"}
```

**How the result was reached:**
1. Pydantic-reserved Django columns such as model_config are assigned a collision-free private schema field with validation_alias="model_config" and an original-name map. The public input remains modelConfig and backend model attribute remains model_config; inherited field validators/serializers are retargeted to the isolated field on a derived base without mutating the caller base. model_dump/model_validate are covered separately.
2. `480167af7d17354d477041f76a4a662b1814604e`: source changes in [django_graphex/core/backend.py](django_graphex/core/backend.py), [django_graphex/core/fields.py](django_graphex/core/fields.py), [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py), [django_graphex/core/validators.py](django_graphex/core/validators.py). Follow-up source commits: `9e36576513cf1e0ced46ad96a799666caa39a3f0`.
3. Scope check: reserved-name construction fixed; inherited-hook history qualified.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_reserved_model_fields.py](tests/core/test_reserved_model_fields.py), `test_inherited_model_config_hooks_use_original_field` (short source excerpt, not a reconstructed failure):
   ```python
   assert row.model_config == "original"
   ```
   - [tests/core/test_reserved_model_fields.py](tests/core/test_reserved_model_fields.py): `test_inherited_model_config_hooks_use_original_field` (added definition); `test_inherited_mixed_hooks_preserve_modes_and_caller_base` (added definition); `test_generated_mutation_persists_reserved_field` (added definition); `test_internal_name_avoids_real_column_and_preserves_inline_validation` (added definition); `test_reserved_default_and_partial_omission_keep_original_presence` (added definition); `test_original_methods_remain_available_on_generated_class` (added definition); `test_existing_custom_base_config_and_dump_override_remain_active` (added definition).

**Name mapping, not a discarded field:** For a Django column `model_config`, Pydantic's same-named configuration attribute cannot be reused as a generated field. `build_model_schema` creates a collision-free internal name, adds `Field(validation_alias="model_config")`, and records the original-name mapping. The GraphQL mutation still accepts `modelConfig`; the backend persists the real `model_config` column. The derived Pydantic base retargets inherited validators/serializers of that column while leaving the caller's base and unrelated hooks intact. `model_dump`/`model_validate` are separate covered reserved names, not evidence that every Python keyword is supported.


### M-D9 — An explicitly named interface field was rendered under a camel-cased Python attribute instead of its declared…

**Status:** bounded-fixed

**Original problem:** An explicitly named interface field was rendered under a camel-cased Python attribute instead of its declared GraphQL wire name; the resolver still needed the Python key. [original audit](auditoria-django-graphex-4.0.0.md), lines 132. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 228; [task T09c/T09](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** interface field internal_name = field(..., name="name"). The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```python
class Named(DjangoInterfaceType):
    internal_name = field(GraphQLString, name="name")
    custom_label = field(GraphQLString, name="label")
# Resolver lookup keys remain internal_name and custom_label.
```

**Before (illustrative):**
```json
{"SDL": "internalName: String", "query_name": "unavailable"}
```

**After (observed/current):**
```json
{"SDL": "name: String", "query": "{ asInterface { name } }", "data": {"asInterface": {"name": "Ada"}}}
```

**How the result was reached:**
1. DjangoInterfaceType now renders each declared field through _rendered_field_name(field, field_name), retaining explicit GraphQL names on the interface and implementor. Resolver lookup remains keyed by Python internal_name/custom_label; the wire fields are name/label/displayLabel, not internalName/customLabel. The second commit scopes that projection to implementors, without renaming NamedAuthor.
2. `0ea68ac4f120bc2bfedfde65c6e3fb7c97a7111e`: source changes in [django_graphex/core/polymorphic_compiler.py](django_graphex/core/polymorphic_compiler.py), [django_graphex/types.py](django_graphex/types.py). Follow-up source commits: `a64d7f58adc370ac250a4c61fc2c82e84eeb7c01`.
3. Scope check: Explicit GraphQL **field wire names** survive on interface and implementor; Python resolver keys and the NamedAuthor type identity are unchanged. The guide’s shorter implementor-name wording is imprecise for the causal fix.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_audit_forked_pair_and_field_names.py](tests/core/test_audit_forked_pair_and_field_names.py), `test_explicit_interface_name_is_shared_with_implementor` (short source excerpt, not a reconstructed failure):
   ```python
   assert {"name", "label", "displayLabel"} <= set(fields)
   ```
   - [tests/core/test_audit_forked_pair_and_field_names.py](tests/core/test_audit_forked_pair_and_field_names.py): `test_explicit_interface_name_is_shared_with_implementor` (added definition).


### M-D10 — Literal, dict, set and Union annotations allegedly degraded silently to String input types

**Status:** bounded-fixed

**Original problem:** Literal, dict, set and Union annotations allegedly degraded silently to String input types. [original audit](auditoria-django-graphex-4.0.0.md), lines 133. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 229; [task T09/R08a/R08b/R08c/R08d/R08e/R08f/R08g/R08h/R08i/R08j/R08k/R08l/R08m/R08n/R08o/R08p/R08q/R08r](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** Literal["a"] or dict[str,int] annotation. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```python
class Payload(InputType):
    state: Literal["draft", "published"]
    flags: dict[str, bool]
    amounts: set[float]
    value: Union[int, str]
```

**Before (illustrative):**
```json
{"SDL": "String fallback without warning for alleged shapes"}
```

**After (observed/current):**
```json
{"SDL": {"state": "named enum", "flags": "JSON", "amounts": "[Float!]!", "value": "IntOrString"}, "wire_input": {"state": "DRAFT", "flags": {"enabled": true}, "amounts": [1.5, 1.5, 2.0], "value": "42"}, "resolver_values": {"state": "draft", "flags": {"enabled": true}, "amounts": "{1.5, 2.0} (Python set)", "value": "42"}}
```

**How the result was reached:**
1. Supported annotations gained precise mappings in separate accepted units; remaining unsupported Literal, dict, set or Union forms produce explicit warnings before the legacy String fallback. The fallback is visible, not universally removed.
2. `7a1dfe3b8406a15fc1fdd2b7221196181449e350`: source changes in [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py). Follow-up source commits: `b5e48232e4615b0ae5e1d4b29ed874f55a3f859b`, `7d0165c2df1b3e0006b5a4fd28abf55bd2d4975b`, `ca95f9039978693562e7c26294a2c3d9e7a0e9d3`, `d66b1752449a0441bd06d6e0167f2790ab32c907`.
3. Scope check: The original report's line 133 alleged that Literal, dict, set, and Union inputs degrade to String without warning. Unsupported forms still retain String but emit UserWarning when the field type is materialized; approved exact forms below do not silently fall back. This bounded disposition does not promise typed support for every annotation. Approved all-string Literal inputs compile to named enums/raw resolver strings; exact dict[str, int]/typing.Dict[str, int] and dict[str, str]/typing.Dict[str, str] inputs use shared JSON with strict declared-value checks before resolution; nested lists of already-supported input leaves preserve recursive nullability and GraphQL list coercion; exact direct dict[str, bool]/typing.Dict[str, bool] use the same JSON scalar with strict Boolean values before resolution while preserving omitted defaults (regression: tests/core/test_boolean_dict_json_input.py); exact set[int] and typing.Set[int] use [Int!]! and a deduplicated resolver-facing Python set (alias regression: tests/core/test_typing_set_int_input.py); exact set[str] and typing.Set[str] use [String!]! with native validation and whole-string singleton coercion (regression: tests/core/test_string_set_input.py); exact set[bool] and typing.Set[bool] use [Boolean!]!, native True/False-only validation, singleton/list coercion and a resolver-facing deduplicated Python set (regression: tests/core/test_boolean_set_input.py); exact set[float] and typing.Set[float] use [Float!]!, native numeric coercion plus field-local overflow-literal rejection before resolution and a resolver-facing deduplicated Python set (regression: tests/core/test_float_set_input.py); exact set[uuid.UUID] and typing.Set[uuid.UUID] use [UUID!]! with existing native UUID validation and a deduplicated resolver-facing Python set (regression: tests/core/test_uuid_set_input.py); exact set[decimal.Decimal] and typing.Set[decimal.Decimal] use [Decimal!]!, native finite precision and field-local rejection of supplied NaN/sNaN/±Infinity before resolution and omitted sibling factories, then a deduplicated Python set (regression: tests/core/test_decimal_set_input.py); direct int/string Union (both spellings/orders) now uses shared strict IntOrString with Int32 and nullable-outer rules (regression: tests/core/test_int_or_string_union_input.py); numeric/mixed Literal, other parameterized dict/set, list-wrapped and other Union shapes still warn and fall back to String; typed support for them is a separate policy, not an open original missing-warning defect.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_input_typing_fallback_warnings.py](tests/core/test_input_typing_fallback_warnings.py), `test_public_input_mutation_warns_without_changing_wire_behavior` (short source excerpt, not a reconstructed failure):
   ```python
   assert sum(name in message for message in messages) == count
   ```
   - [tests/core/test_input_typing_fallback_warnings.py](tests/core/test_input_typing_fallback_warnings.py): `test_public_input_mutation_warns_without_changing_wire_behavior` (added definition); `test_supported_annotations_do_not_gain_fallback_warnings` (added definition).

**Exact accepted input contracts (not a generic annotation rewrite):**
1. An all-string `Literal["draft", "published"]` becomes a named enum in SDL but reaches the resolver as the original string. A numeric or mixed Literal still warns and uses the legacy String fallback.
2. Exact `dict[str, int]`, `dict[str, str]`, and `dict[str, bool]`, including their `typing.Dict` spellings, use shared JSON input and validate the declared value type without coercing strings to numbers/booleans. A missing field retains its declared default; omitted and explicit-null are not conflated. Supported nested lists retain recursive element nullability and GraphQL's normal singleton-to-list coercion.
3. Exact `set[int]`, `set[str]`, `set[bool]`, `set[float]`, `set[uuid.UUID]`, and `set[decimal.Decimal]`, including `typing.Set` aliases, expose the corresponding `[Int!]!`, `[String!]!`, `[Boolean!]!`, `[Float!]!`, `[UUID!]!`, and `[Decimal!]!` inputs. Accepted singleton/list input reaches the resolver as a deduplicated Python `set` with no order guarantee. Boolean members must be actual booleans; float/decimal use their native numeric/UUID/precision validation. A supplied overflowing Float literal or NaN/sNaN/±Infinity Decimal set value is rejected **for that field**, before resolution; omitted legacy fixed defaults/factories are not silently rewritten.
4. A direct `Union[int, str]` or `int | str` (either order) uses strict shared `IntOrString`: Int32 for integers, unchanged strings, no boolean-as-int or string/number conversion, and the declared optional outer wrapper. A list-wrapped Union, other Union, non-string Literal or other parameterized map/set remains warning-backed String. Its future typed semantics need separate approval; the original missing-warning defect is bounded, not globally erased.
**Representative tests:** `tests/core/test_literal_string_enum_input.py`, `test_boolean_dict_json_input.py`, `test_recursive_input_lists.py`, `test_float_set_input.py`, `test_decimal_set_input.py`, and `test_int_or_string_union_input.py`. These named suites prove separate accepted shapes; they do not imply all annotations are supported.
**Named checks:** `test_public_mutation_uses_literal_enum_and_raw_resolver_value`, `test_exact_boolean_map_uses_json_input`, `test_nested_list_nullability_and_singleton_coercion`, `test_typing_set_int_list_reaches_resolver_as_set`, `test_float_sets_publish_list_and_reach_resolver_as_set`, `test_decimal_sets_publish_list_and_reach_resolver_as_set`, and `test_direct_union_publishes_shared_scalar` are current definitions in the respective files above. The complete 189-path appendix gives their base-to-snapshot definition provenance.


### M-F1 — Related date-part and primary-key lookup names could shadow one another in nested filters

**Status:** bounded-fixed

**Original problem:** Related date-part and primary-key lookup names could shadow one another in nested filters. [original audit](auditoria-django-graphex-4.0.0.md), lines 138. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 230; [task T11/T11d](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** nested relation has datepart and pk-like name. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"rows": [{"owner": "first", "target": {"code_pk": 1, "year": 2024, "exact": 7}}, {"owner": "second", "target": {"code_pk": 2, "year": 2023, "exact": 8}}], "nested_query": "{ owners(filter: { target: { year: { exact: 2024 } } }) { name } }", "direct_pk_query": "{ owners(filter: { target: { exact: 1 } }) { name } }"}
```

**Before (illustrative):**
```json
{"direct_pk_query_names": [], "reason": "target__exact selected related exact column (7/8), not code PK (1/2)"}
```

**After (observed/current):**
```json
{"nested_query_names": ["first"], "direct_pk_query_names": ["first"], "direct_lookup_path": "target__pk__exact"}
```

**How the result was reached:**
1. Related date-part lookup paths are disambiguated from a model's primary-key lookup name during nested filter translation. This does not collapse the separate null and to-many identity questions.
2. `954a2036b53a540e4db9829b6373eb66b2570474`: source changes in [django_graphex/filtering/translate.py](django_graphex/filtering/translate.py).
3. Scope check: nested related datepart/PK shadow fixed; SDL/null/A12 separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_relation_lookup_name_collision.py](tests/test_relation_lookup_name_collision.py), `test_nested_lookup_name_and_direct_pk_exact` (short source excerpt, not a reconstructed failure):
   ```python
   assert reverse_many is True
   ```
   - [tests/test_relation_lookup_name_collision.py](tests/test_relation_lookup_name_collision.py): `test_nested_lookup_name_and_direct_pk_exact` (added definition).


### M-F2 — Numeric Date and DateTime part lookups used the whole field scalar, so the filter SDL required Date or DateTime…

**Status:** bounded-fixed

**Original problem:** Numeric Date and DateTime part lookups used the whole field scalar, so the filter SDL required Date or DateTime where an integer year/month was needed. [original audit](auditoria-django-graphex-4.0.0.md), lines 139. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 231; [task T11/T11b](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** DateTime field created_at, filter year=2026. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
# DateTime field createdAt, numeric date-part filter
{ posts(filters: {createdAt: {year: 2026}}) { results { id } } }
```

**Before (illustrative):**
```json
{"SDL": "year: DateTime", "result": "integer literal rejected"}
```

**After (observed/current):**
```json
{"SDL": "year: Int", "result": "integer literal accepted"}
```

**How the result was reached:**
1. The native filter builder identifies numeric date-part lookups and supplies GraphQLInt to _build_lookups_type instead of reusing _field_scalar(field). Thus year/month components accept integers; whole Date/DateTime values and TimeField retain their existing scalar rules.
2. `53b3481fff2eed6eb1a0a7d5ee07cd85f8f975e8`: source changes in [django_graphex/filtering/native_schema.py](django_graphex/filtering/native_schema.py).
3. Scope check: numeric Date/DateTime parts typed Int; whole-value/TimeField policy unchanged.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_datepart_filtering.py](tests/test_datepart_filtering.py), `test_numeric_date_parts_have_int_sdl_and_work_over_http` (short source excerpt, not a reconstructed failure):
   ```python
   assert payload["data"][root_name] == [{"label": "match"}]
   ```
   - [tests/test_datepart_filtering.py](tests/test_datepart_filtering.py): `test_numeric_date_parts_have_int_sdl_and_work_over_http` (added definition); `test_lookup_type_boundaries_and_shared_inputs` (added definition).


### M-F3 — Exact null, an omitted predicate, and empty Boolean branches were being treated as one filter-identity policy

**Status:** partial

**Original problem:** Exact null, an omitted predicate, and empty Boolean branches were being treated as one filter-identity policy. [original audit](auditoria-django-graphex-4.0.0.md), lines 140. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 232; [task T11/T11a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** filter exact:null versus omitted exact. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"filters": [{"exact": null}, {}]}
```

**Before (illustrative):**
```json
{"branches": ["same", "same"]}
```

**After (observed/current):**
```json
{"branches": ["is-null", "omitted"], "empty_boolean": "unchanged"}
```

**How the result was reached:**
1. The translator emits SQL IS NULL for explicit exact:null rather than treating it as omission. Empty Boolean branches are not silently given a new algebraic identity.
2. `c4273e2b09624cfdd615e8f908abcb30ad2efb54`: source changes in [django_graphex/filtering/translate.py](django_graphex/filtering/translate.py).
3. Scope check: exact:null/omission only; broader Boolean identities open.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_exact_null_filtering.py](tests/test_exact_null_filtering.py), `test_public_literal_exact_null_is_distinct_from_omission` (short source excerpt, not a reconstructed failure):
   ```python
   assert _titles(path_name, explicit) == ["Django deep dive"]
   ```
   - [tests/test_exact_null_filtering.py](tests/test_exact_null_filtering.py): `test_public_literal_exact_null_is_distinct_from_omission` (added definition); `test_public_variable_exact_null_is_distinct_from_omission` (added definition); `test_native_coercion_preserves_lookup_presence` (added definition); `test_public_exact_null_composes_without_changing_empty_nodes` (added definition); `test_exact_null_field_matrix_and_json_sql_null` (added definition); `test_nullable_choice_and_text_exact_null` (added definition); `test_direct_relation_and_unset_lookup_boundaries` (added definition); `test_to_many_null_keeps_distinct_and_nested_prefix` (added definition).


### M-F4 — An explicit page:null could hit a different path than an omitted page argument

**Status:** bounded-fixed

**Original problem:** An explicit page:null could hit a different path than an omitted page argument. [original audit](auditoria-django-graphex-4.0.0.md), lines 141. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 233; [task T12/T12c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** page:null in paginated query. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"pagination": {"page": null, "size": 10}}
```

**Before (illustrative):**
```json
{"page_path": "different from omission"}
```

**After (observed/current):**
```json
{"page_path": "first-page omission semantics"}
```

**How the result was reached:**
1. Pagination normalizes an explicitly supplied null page to the omitted-page first-page path before arithmetic. Zero and negative-page semantics are not redefined.
2. `9ab95cb26b95af0fb2baae04c79108bdcbd1765f`: source changes in [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py).
3. Scope check: explicit page:null equals omission; zero/negative unchanged.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py), `test_explicit_null_page_matches_omission_http` (short source excerpt, not a reconstructed failure):
   ```python
   assert expected["totalCount"] == 5
   ```
   - [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py): `test_explicit_null_page_matches_omission_http` (added definition); `test_existing_page_boundaries_http` (added definition); `test_omitted_nullable_variable_keeps_default_http` (added definition); `test_nested_null_page_reaches_materialized_list_without_optimizer` (added definition); `test_direct_page_null_normalizes_both_paths` (added definition).


### M-F5 — Rows tied on an ordered value could move between model-backed pages without a stable secondary key

**Status:** bounded-fixed

**Original problem:** Rows tied on an ordered value could move between model-backed pages without a stable secondary key. [original audit](auditoria-django-graphex-4.0.0.md), lines 142. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 234; [task T12/T12f](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** rows A,B share sort value. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"rows": [{"id": 2, "score": 5}, {"id": 1, "score": 5}], "order": "score asc"}
```

**Before (illustrative):**
```json
{"ids": [2, 1]}
```

**After (observed/current):**
```json
{"ids": [1, 2]}
```

**How the result was reached:**
1. For covered model ordering, pagination appends ascending primary key as a deterministic tie-break after effective queryset ordering. Random and offset ordering remain separate behaviors.
2. `f6e88d446f492324b5ec09f72c880c88842acb6d`: source changes in [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py). Follow-up source commits: `d1a6a18c167451546f8cf8bb4c91614cbd18c492`.
3. Scope check: model-backed PK-ASC tie-break; offset/random unaffected.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_pagination_pk_tiebreak.py](tests/test_pagination_pk_tiebreak.py), `test_limit_offset_db_appends_pk_to_client_order` (short source excerpt, not a reconstructed failure):
   ```python
   assert page.query.order_by == ("-title", "id")
   ```
   - [tests/test_pagination_pk_tiebreak.py](tests/test_pagination_pk_tiebreak.py): `test_limit_offset_db_appends_pk_to_client_order` (added definition); `test_page_db_appends_pk_to_client_order` (added definition); `test_materialized_model_list_uses_same_tie_break` (added definition); `test_explicit_descending_pk_is_not_overridden` (added definition); `test_explicit_id_inside_multiple_terms_is_not_duplicated` (added definition); `test_no_order_uses_pk_and_page_materialized_rows_match` (added definition); `test_queryset_default_and_explicit_order_are_preserved` (added definition); `test_queryset_expression_order_stays_ahead_of_pk` (added definition); `test_queryset_extra_ordering_stays_ahead_of_pk` (added definition); `test_col_pk_expression_is_not_duplicated` (added definition); `test_unbounded_no_order_preserves_original_queryset_cache` (added definition); `test_unbounded_no_order_retains_meta_ordering_without_a_clone` (added definition); `test_internal_pk_does_not_expand_client_ordering_allowlist` (added definition); `test_model_meta_ordering_survives_db_and_materialized_paths` (added definition); `test_unsupported_meta_list_ordering_keeps_pk_fallback` (added definition); `test_natural_pk_uses_field_name_not_id` (added definition); `test_natural_pk_alias_and_attname_keep_explicit_direction` (added definition); `test_reverse_fk_window_row_number_uses_pk_secondary` (added definition); `test_reverse_fk_window_keeps_model_meta_ordering` (added definition); `test_reverse_fk_window_keeps_hook_queryset_ordering` (added definition); `test_reverse_fk_window_keeps_extra_queryset_ordering` (added definition); `test_reverse_fk_window_falls_back_for_unsupported_hook_terms` (added definition); `test_nested_hidden_pk_is_internal_not_client_ordering` (added definition); `test_public_graphql_pages_cover_equal_name_rows_once` (added definition); `test_http_offset_pages_keep_equal_name_rows_disjoint` (added definition).


### M-F6 — A negative-page count failure could trigger fallback materialization of the whole collection

**Status:** bounded-fixed

**Original problem:** A negative-page count failure could trigger fallback materialization of the whole collection. [original audit](auditoria-django-graphex-4.0.0.md), lines 143. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 235; [task T12/T12e](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** page:-1 and count() raises. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"page": -1, "queryset_count": "raises DatabaseError"}
```

**Before (illustrative):**
```json
{"fallback": "iterate/materialize rows"}
```

**After (observed/current):**
```json
{"results": null, "error": "controlled GraphQLError"}
```

**How the result was reached:**
1. Negative-page calculation fails with a controlled GraphQL error if count() fails instead of materializing the entire iterable as fallback. Result data remains null for that page.
2. `c75ea72fb0576fb86b1dbe829d6e4b3f42c93933`: source changes in [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py), [django_graphex/paginations/utils.py](django_graphex/paginations/utils.py).
3. Scope check: A failed negative-page count raises a controlled GraphQLError instead of trying length, iteration, or a full fetch; results are null, not fallback rows.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_negative_page_count_error_http.py](tests/test_negative_page_count_error_http.py), `test_failed_negative_page_count_is_generic_and_does_not_fetch_rows` (short source excerpt, not a reconstructed failure):
   ```python
   assert not any('FROM "tests_post"' in item["sql"] for item in queries)
   ```
   - [tests/test_negative_page_count_error_http.py](tests/test_negative_page_count_error_http.py): `test_failed_negative_page_count_is_generic_and_does_not_fetch_rows` (added definition); `test_failed_count_does_not_use_length_or_iteration` (added definition); `test_list_fallback_and_unrelated_count_errors_are_unchanged` (added definition); `test_positive_page_does_not_attempt_count_when_not_selected` (added definition).


### M-F7 — Without a page size, PageGraphqlPagination could return results: null while totalCount remained positive. The…

**Status:** bounded-fixed

**Original problem:** Without a page size, PageGraphqlPagination could return results: null while totalCount remained positive. The later default change and explicit server-side None contract are distinct. [original audit](auditoria-django-graphex-4.0.0.md), lines 144. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 236; [task T12/T12d/T12g](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** 105 rows; no client pageSize; default 100. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
{ pagePosts { totalCount results(ordering: "id") { id } } }
# 105 rows; no client pageSize; DEFAULT_PAGE_SIZE = 100.
```

**Before (illustrative):**
```json
{"data": {"pagePosts": {"results": null, "totalCount": 105}}}
```

**After (observed/current):**
```json
{"selected_root": "pagePosts", "selected_item_shape": {"id": "<post pk>"}, "totalCount": 105, "first_page_result_count": 100, "second_page_result_count": 5}
```

**How the result was reached:**
1. The constructor now inherits DEFAULT_PAGE_SIZE=100 when page_size is omitted, so a positive total has a concrete first result window. PageGraphqlPagination(page_size=None, max_page_size=None) is a distinct explicit server opt-out preserving legacy behavior; a client pageSize:null resolves to the configured default rather than unlimited.
2. `5faeef718816e9e3fda12472f588da92ade02edf`: source changes in [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py), [django_graphex/settings.py](django_graphex/settings.py).
3. Scope check: Server PageGraphqlPagination(page_size=None, max_page_size=None) retains its legacy behavior; client pageSize: null instead resolves to the configured default, normally 100.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_default_page_size_http.py](tests/test_default_page_size_http.py), `test_omitted_size_uses_library_default_across_public_paginators` (short source excerpt, not a reconstructed failure):
   ```python
   assert graphql_api_settings.DEFAULT_PAGE_SIZE == 100
   ```
   - [tests/test_default_page_size_http.py](tests/test_default_page_size_http.py): `test_omitted_size_uses_library_default_across_public_paginators` (added definition); `test_default_is_not_a_maximum_http` (added definition); `test_nested_omitted_size_uses_library_default_http` (added definition); `test_explicit_none_preserves_each_legacy_paginator_policy` (added definition); `test_startup_global_override_and_local_size_take_precedence` (added definition).


### M-H1 — A malformed later batch item could discard earlier result data while returning HTTP 400

**Status:** bounded-fixed

**Original problem:** A malformed later batch item could discard earlier result data while returning HTTP 400. [original audit](auditoria-django-graphex-4.0.0.md), lines 149. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 237; [task T05/T13/T13h](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** batch item 1 succeeds; item 2 invalid. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"batch": ["valid query", "invalid second request"]}
```

**Before (illustrative):**
```json
{"http_status": 400, "data": null}
```

**After (observed/current):**
```json
{"http_status": 400, "first_data": "retained", "second_error": "reported", "later_items": "not run"}
```

**How the result was reached:**
1. Batch handling retains earlier completed item data and its error while stopping on a malformed later item with HTTP 400. It does not roll back prior durable writes.
2. `347b2ff7ac383bf791b795b6c51d9f825236ceeb`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: batch HTTP400 prior data/error/stop; prior writes persist, no batch transaction.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_batch_http_error_partial.py](tests/test_batch_http_error_partial.py), `test_later_http_400_keeps_prior_result_and_stops_batch` (short source excerpt, not a reconstructed failure):
   ```python
   assert payload[1]["status"] == 400
   ```
   - [tests/test_batch_http_error_partial.py](tests/test_batch_http_error_partial.py): `test_later_http_400_keeps_prior_result_and_stops_batch` (added definition); `test_partial_response_does_not_depend_on_response_cache` (added definition); `test_non_400_http_error_keeps_existing_request_level_envelope` (added definition); `test_first_http_400_has_one_error_entry_and_no_invalidation` (added definition); `test_validation_error_continues_until_later_transport_error` (added definition); `test_outer_preflight_and_single_error_keep_existing_object_envelope` (added definition).


### M-H2 — A synchronous HTTP view could accidentally receive asynchronous execution and leave coroutine cleanup ambiguous

**Status:** bounded-fixed

**Original problem:** A synchronous HTTP view could accidentally receive asynchronous execution and leave coroutine cleanup ambiguous. [original audit](auditoria-django-graphex-4.0.0.md), lines 150. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 238; [task T13/T13f](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** async resolver enters sync view. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"view": "synchronous", "resolver": "returns coroutine"}
```

**Before (illustrative):**
```json
{"response": "uncontrolled coroutine path"}
```

**After (observed/current):**
```json
{"http_status": 500, "body": {"errors": ["controlled internal error"]}, "cleanup": "performed"}
```

**How the result was reached:**
1. The synchronous view detects unsupported async execution, closes nested coroutine resources, and returns controlled JSON 500. It does not become an async HTTP endpoint.
2. `23c06e0b6b7d86f2b082b86a50e4a6d715a3e78e`: source changes in [django_graphex/views.py](django_graphex/views.py). Follow-up source commits: `e8d0cf9eb5e40c03d9a1b2ee8fb3a9d42e63f3e6`, `dd1cf898dd94d01e44ff7672e764ea6807cf2f7b`.
3. Scope check: sync/async misuse JSON500/cleanup; no general async support.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_sync_async_http.py](tests/test_sync_async_http.py), `test_falsey_object_middleware_is_ignored_like_native` (short source excerpt, not a reconstructed failure):
   ```python
   assert response.status_code == 200
   ```
   - [tests/test_sync_async_http.py](tests/test_sync_async_http.py): `test_falsey_object_middleware_is_ignored_like_native` (added definition); `test_callable_object_middleware_remains_active` (added definition); `test_async_resolver_returns_json_500_and_closes_owned_coroutines` (added definition); `test_sync_middleware_closes_nested_owned_resolver_coroutines` (added definition); `test_sync_middleware_keeps_borrowed_coroutine_open` (added definition); `test_async_middleware_is_rejected_without_running_its_body` (added definition); `test_custom_executor_owned_coroutine_is_closed` (added definition); `test_executor_exception_after_async_value_closes_owned_coroutine` (added definition); `test_async_mutation_is_rejected_with_transaction_policy` (added definition).


### M-H3 — Response cleaning treated false and zero as absent values

**Status:** bounded-fixed

**Original problem:** Response cleaning treated false and zero as absent values. [original audit](auditoria-django-graphex-4.0.0.md), lines 151. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 239; [task T13/T13d](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** response contains 0 and false. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"resolver_data": {"zero": 0, "flag": false}}
```

**Before (illustrative):**
```json
{"response_data": {}}
```

**After (observed/current):**
```json
{"response_data": {"zero": 0, "flag": false}}
```

**How the result was reached:**
1. Response cleaning tests for absence rather than truthiness, preserving numeric zero and false in output. Fragment-introspection classification was handled independently.
2. `043811eefaec7c4662eb53672b994ec65f9ac545`: source changes in [django_graphex/utils.py](django_graphex/utils.py).
3. Scope check: preserve 0/False; fragment classifier separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_clean_response_http.py](tests/test_clean_response_http.py), `test_selected_operation_controls_introspection_cleaning` (short source excerpt, not a reconstructed failure):
   ```python
   assert normal["data"] == {"count": 0, "enabled": False}
   ```
   - [tests/test_clean_response_http.py](tests/test_clean_response_http.py): `test_clean_response_keeps_zero_false_and_nonempty_values` (added definition); `test_disabled_cleaning_leaves_the_full_payload_unchanged` (added definition); `test_selected_operation_controls_introspection_cleaning` (added definition).


### M-H4 — A failed GraphQL response could enter the response cache as though successful

**Status:** partial

**Original problem:** A failed GraphQL response could enter the response cache as though successful. [original audit](auditoria-django-graphex-4.0.0.md), lines 152. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 240; [task T13/T13e](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** GraphQL execution returns errors. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"GET_query": "{ unstable }", "first_result": {"errors": ["resolver failed"]}}
```

**Before (illustrative):**
```json
{"cache_entry": "failed response"}
```

**After (observed/current):**
```json
{"cache_entry": null, "second_request": "re-executes"}
```

**How the result was reached:**
1. Response-cache insertion now requires a successful GraphQL response; an error-bearing result is returned but not stored for later hits.
2. `69d326eecee9c71ffe19db64e9019812297c74a1`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: success-only cache fixed; finite-safety/Ruff caveats retained.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_success_response_cache.py](tests/test_success_response_cache.py), `test_partial_execution_error_recovers_then_success_hits` (short source excerpt, not a reconstructed failure):
   ```python
   assert third.content == second.content
   ```
   - [tests/test_success_response_cache.py](tests/test_success_response_cache.py): `test_partial_execution_error_recovers_then_success_hits` (added definition); `test_validation_error_is_not_stored_or_reused` (added definition); `test_legacy_failed_entry_is_ignored_and_replaced` (added definition); `test_malformed_legacy_entry_is_ignored` (added definition); `test_disabled_cache_executes_without_response_cache_io` (added definition); `test_cookie_bearing_queries_bypass_response_cache` (added definition).


### M-O1 — Merged root FieldNodes could make optimizer prefetch planning miss a relation and create N+1 queries

**Status:** bounded-fixed

**Original problem:** Merged root FieldNodes could make optimizer prefetch planning miss a relation and create N+1 queries. [original audit](auditoria-django-graphex-4.0.0.md), lines 157. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 241; [task T14/T14b](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** merged alias selects relation across rows. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"rows": [1, 2, 3], "selection": "related author under merged alias"}
```

**Before (illustrative):**
```json
{"relation_fetches": 3}
```

**After (observed/current):**
```json
{"relation_fetches": "one covered batch"}
```

**How the result was reached:**
1. Optimizer planning merges all root FieldNode selections for one response field before collecting relation prefetches. A missed sibling relation no longer causes the exercised N+1, without promising constant queries for every ORM shape.
2. `316844e376f9585f873903a60d73eb25a39aeb58`: source changes in [django_graphex/utils.py](django_graphex/utils.py).
3. Scope check: merged-node optimizer N+1 fixed in bounded case.
4. Actual test locators, with base-to-snapshot definition provenance:
   - [tests/test_optimizer_merged_field_nodes.py](tests/test_optimizer_merged_field_nodes.py): `test_direct_and_fragment_root_fields_share_relation_and_column_plan` (added definition); `test_second_root_node_promotes_annotated_relation` (added definition).


### M-O2 — A cold permission-pruning cache fill held a lock that blocked unrelated warm hits

**Status:** bounded-fixed

**Original problem:** A cold permission-pruning cache fill held a lock that blocked unrelated warm hits. [original audit](auditoria-django-graphex-4.0.0.md), lines 158. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 242; [task T14/T14c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** warm signature hit beside cold fill. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"cache": "warm permission signature", "other_thread": "cold signature fill"}
```

**Before (illustrative):**
```json
{"warm_hit": "waits on global cold-fill lock"}
```

**After (observed/current):**
```json
{"warm_hit": "served without cold-fill wait"}
```

**How the result was reached:**
1. Permission-signature cache serves already warm keys outside the lock held for another cold signature's build. Cold pruning still happens once per signature and remains permission-sensitive.
2. `961c018e2d089962679c65329ebdb6bff765ba26`: source changes in [django_graphex/core/permission_signature_cache.py](django_graphex/core/permission_signature_cache.py).
3. Scope check: warm-hit lock split; no general concurrency guarantee.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_permission_cache_lock_split.py](tests/test_permission_cache_lock_split.py), `test_warm_hit_completes_before_unrelated_cold_prune_is_released` (short source excerpt, not a reconstructed failure):
   ```python
   assert results[0] is cached_b
   ```
   - [tests/test_permission_cache_lock_split.py](tests/test_permission_cache_lock_split.py): `test_warm_hit_completes_before_unrelated_cold_prune_is_released` (added definition); `test_cold_builds_remain_serial_and_same_key_is_shared` (added definition); `test_clear_waits_for_build_then_removes_entry` (added definition); `test_reentrant_clear_and_failed_prune_leave_cache_recoverable` (added definition).


### M-U1 — A cancelled ASGI subscription startup could leave a joined group and prevent immediate same-source retry

**Status:** partial

**Original problem:** A cancelled ASGI subscription startup could leave a joined group and prevent immediate same-source retry. [original audit](auditoria-django-graphex-4.0.0.md), lines 163. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 243; [task T08/R01b](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** cancel startup after group join. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"startup": "cancel after WS group join", "operation_id": "op1"}
```

**Before (illustrative):**
```json
{"group_membership": "stale", "retry": "blocked"}
```

**After (observed/current):**
```json
{"group_membership": "removed", "retry": "admitted"}
```

**How the result was reached:**
1. Cancelled ASGI startup releases the joined group and operation slot before a retry using the same source. The fix is local cleanup, not a distributed lease guarantee.
2. `fe545832513244bdddf2d35cea4cc845fc34cad9`: source changes in [django_graphex/subscriptions/source.py](django_graphex/subscriptions/source.py). Follow-up source commits: `514def143c42d6dad082e4590fb9edce813c90d6`.
3. Scope check: Real-ASGI startup now cleans a group joined before cancellation returns; the same failed-Source/same-channel retry works. Distributed-backend cleanup remains best-effort.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_startup_cleanup.py](tests/subscriptions/test_startup_cleanup.py), `test_client_complete_during_real_join_discards_membership` (short source excerpt, not a reconstructed failure):
   ```python
   assert not layer.groups
   ```
   - [tests/subscriptions/test_startup_cleanup.py](tests/subscriptions/test_startup_cleanup.py): `test_client_complete_during_real_join_discards_membership` (added definition); `test_disconnect_during_real_join_discards_membership` (added definition); `test_sse_cancel_during_real_join_discards_membership` (added definition); `test_failed_second_join_discards_only_its_memberships` (added definition); `test_failure_before_backend_join_preserves_original_error` (added definition); `test_cleanup_failure_does_not_replace_startup_failure` (added definition); `test_same_source_retry_after_failed_join_delivers_and_cleans_up` (added definition); `test_explicit_close_after_failed_join_stays_closed` (added definition).


### M-U2 — An id-only automatic delete event lacked loaded fields needed for server-scope and equality filtering after commit

**Status:** partial

**Original problem:** An id-only automatic delete event lacked loaded fields needed for server-scope and equality filtering after commit. [original audit](auditoria-django-graphex-4.0.0.md), lines 164. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 244; [task T08](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** id-only delete for matching tenant. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"deleted_row": {"pk": 7, "tenant": "A"}, "filter": {"tenant": "A"}}
```

**Before (illustrative):**
```json
{"event": null}
```

**After (observed/current):**
```json
{"event": {"pk": 7}, "wrong_tenant_event": null}
```

**How the result was reached:**
1. The automatic delete signal captures already-loaded, concrete projected private scalar values before the row disappears. After commit, equality and server-scope matching can use that trusted snapshot and emit a PK-only event; missing/deferred/nonprojected scalars, id-only relations, custom backends and lookup predicates stay conservative. This does not authorize arbitrary external payloads.
2. `1ee78e2548dcb7fc4d466a1c702f1ae9e060671d`: source changes in [django_graphex/subscriptions/bindings.py](django_graphex/subscriptions/bindings.py), [django_graphex/subscriptions/source.py](django_graphex/subscriptions/source.py), [django_graphex/subscriptions/subscription.py](django_graphex/subscriptions/subscription.py).
3. Scope check: Automatic delete captures loaded private projected concrete scalar values at signal time, so id-only plain equality and server scope can match after commit without widening public data. Deferred/missing/nonprojected values, id-only relations, custom backends and lookup filters remain conservative; unfiltered PK-only events still deliver. This is not a general visibility policy.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_delete_snapshot_matching.py](tests/subscriptions/test_delete_snapshot_matching.py), `test_private_capture_excludes_relations_containers_nonfinite_and_custom_backend` (short source excerpt, not a reconstructed failure):
   ```python
   assert ProjectedSubscription._serialize_delete_match(instance) == {}
   ```
   - [tests/subscriptions/test_delete_snapshot_matching.py](tests/subscriptions/test_delete_snapshot_matching.py): `test_private_capture_excludes_relations_containers_nonfinite_and_custom_backend` (added definition); `test_real_delete_uses_signal_time_projected_equality` (added definition); `test_missing_or_malformed_private_delete_snapshot_fails_closed` (added definition); `test_private_delete_equality_preserves_typed_scalar_contract` (added definition).

**Why an id-only delete can match:** The deleted database row cannot be reloaded after commit. The automatic signal therefore records only **already-loaded, concrete, projected** private scalars before deletion. For `{pk: 7, tenant: "A"}`, an equality filter `tenant: "A"` can match and the published data can remain `{"pk": 7}`; `tenant: "B"` does not match. A deferred, missing or unprojected `tenant` is not guessed from the PK. Relation-ID-only and lookup predicates, custom backends, and arbitrary external broadcast payloads are outside this trust boundary. See `tests/subscriptions/test_delete_snapshot_matching.py`.


### M-U3 — Decimal, DateTime and Float subscription snapshots could compare unequal representations of the same finite value

**Status:** partial

**Original problem:** Decimal, DateTime and Float subscription snapshots could compare unequal representations of the same finite value. [original audit](auditoria-django-graphex-4.0.0.md), lines 165. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 245; [task T08/R02](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** Decimal 1.0 versus 1.00; Float -0.0 versus 0.0. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"event_decimal": "1.00", "filter_decimal": "1.0", "float_values": [-0.0, 0.0]}
```

**Before (illustrative):**
```json
{"match": false}
```

**After (observed/current):**
```json
{"finite_match": true, "non_finite_policy": "unchanged"}
```

**How the result was reached:**
1. Subscription comparisons normalize supported finite Decimal, exact native DateTime and Float values (including signed zero) along distinct paths. Mixed-type and non-finite policy was not globally rewritten.
2. `c664db3fe7d727e073de7725564a9cbe8a49e0fa`: source changes in [django_graphex/subscriptions/mixins.py](django_graphex/subscriptions/mixins.py). Follow-up source commits: `6df731e0d01b67997bf2fa6de457c372f4a33855`, `33ff8786e03901ef1ca9bf0e7f34c82ab2b0a0b5`.
3. Scope check: Finite Decimal and native DateTime exact snapshots have separate corrections. Actual finite Float pairs now use exact numeric equality, including either signed-zero direction; ordinary finite Float matches were already working. Other scalar policies remain unchanged.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_float_snapshot_filter.py](tests/subscriptions/test_float_snapshot_filter.py), `test_real_float_field_exact_event` (short source excerpt, not a reconstructed failure):
   ```python
   assert type(parsed_filters[0]["floating"]) is float
   ```
   - [tests/subscriptions/test_float_snapshot_filter.py](tests/subscriptions/test_float_snapshot_filter.py): `test_real_float_field_exact_event` (added definition); `test_float_pair_only_changes_finite_exact_equality` (added definition).


### M-U4 — The audit conflated automatic model-signal delivery with immediate manual binding broadcasts and bulk operations

**Status:** contract

**Original problem:** The audit conflated automatic model-signal delivery with immediate manual binding broadcasts and bulk operations. [original audit](auditoria-django-graphex-4.0.0.md), lines 166. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 246; [task T08](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** model save vs bulk_update vs manual broadcast. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"all assumed commit-time automatic"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Post-save/delete model signals schedule automatic delivery after commit; bulk updates have no signal, while direct manual broadcast remains immediate. These are documented lifecycle boundaries, not a changed implementation.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: Automatic post-save/post-delete signals schedule commit-time sends, while bulk/update paths emit no model signals and manual binding broadcast is immediate; use a fresh post-commit instance when timing matters.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### M-U5 — Async directive formatters could see an unresolved resolver value or cancel a Future they did not own

**Status:** bounded-fixed

**Original problem:** Async directive formatters could see an unresolved resolver value or cancel a Future they did not own. [original audit](auditoria-django-graphex-4.0.0.md), lines 167. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 247; [task T15/R03a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** async resolver value passed through directive. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"resolver_value": "borrowed Future[str]", "directive": "@uppercase"}
```

**Before (illustrative):**
```json
{"formatter_input": "Future object", "cancellation": "may propagate to borrowed future"}
```

**After (observed/current):**
```json
{"formatter_input": "awaited string", "borrowed_future_cancelled": false}
```

**How the result was reached:**
1. Async directive middleware awaits resolver output before formatting and does not cancel a Future it does not own. Synchronous HTTP continues to reject unsupported async execution separately.
2. `ace6638e65f70843d123263f7ea09b7c780a595b`: source changes in [django_graphex/middleware.py](django_graphex/middleware.py). Follow-up source commits: `031299c46e3127c080a3554f0c708b01147ad7a2`.
3. Scope check: Native async directive formatting waits for resolver values and preserves borrowed Future ownership; synchronous HTTP still returns its controlled JSON 500 rather than gaining async support.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_async_directive_middleware.py](tests/test_async_directive_middleware.py), `test_native_async_execution_applies_directive_after_await` (short source excerpt, not a reconstructed failure):
   ```python
   assert started == ["resolver"]
   ```
   - [tests/test_async_directive_middleware.py](tests/test_async_directive_middleware.py): `test_native_async_execution_applies_directive_after_await` (added definition); `test_sync_http_rejects_async_resolver_with_directive` (added definition); `test_sync_http_preserves_borrowed_future_with_directive` (added definition); `test_synchronous_directive_behavior_is_unchanged` (added definition); `test_http_outer_wrapper_does_not_leak_directive_coroutine` (added definition).


### M-U6 — The original multi-directive allegation covered inconsistent text date/timezone handling, case conversion, and…

**Status:** partial

**Original problem:** The original multi-directive allegation covered inconsistent text date/timezone handling, case conversion, and number/currency null behavior; it was not solely native DateTime parsing. [original audit](auditoria-django-graphex-4.0.0.md), lines 168. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 248; [task T15](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** nullable @date/@number/@currency; date-only, offset and timezone-less text; HTTPServer case. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```graphql
{ dateValue @date(format: "yyyy-MM-dd HH:mm") numberValue @number }
# Nullable resolver values are None; separate text-date and case examples follow below.
```

**Before (illustrative):**
```json
{"null_result": "formatting error", "case": "inconsistent"}
```

**After (observed/current):**
```json
{"null_result": null, "date_clock": "00:00:00", "camel": "httpServer", "snake": "http_server", "kebab": "http-server"}
```

**How the result was reached:**
1. The directive pipeline preserves nullable None for @date, @number and @currency while GraphQL NonNull still bubbles. Text date-only/partial time fills missing clock components with zero; offset/Z or aware values preserve their instant in the active zone, while timezone-less text attaches the active zone to its written wall clock regardless of USE_TZ. Relative formatting may therefore differ; named/unknown zones remain bounded. The three case directives handle approved words/acronym blocks (HTTPServer -> httpServer/http_server/http-server) without renaming schema fields or shared helpers.
2. `1f97d24d06309309601e029eb21766dcd1da6e67`: source changes in [django_graphex/directives/date.py](django_graphex/directives/date.py). Follow-up source commits: `35199aa09a2ce3331456accb72348171cb9b98e5`, `dc556059c5c06e5d21bcf63388535901ffe3979a`.
3. Scope check: The directive guide clarifies @date formatting and bounded case behavior. Null passes through with ordinary NonNull bubbling. Accepted text fills omitted time components with zeros; missing dates still use the parser's current date. Absolute formats display originally aware Python datetime and explicit-offset/Z text in the active zone, preserving the instant; clock-adjacent +00:00/+0000 now match equivalent Z. Genuinely timezone-less text now attaches the active zone to its written wall clock for absolute and relative formats, regardless of USE_TZ; explicit-offset/Z relative and named/unknown-zone behavior remains. The three case directives now normalize approved word forms and acronym blocks without renaming schema fields or changing shared helpers. @number/@currency now preserve null and normal NonNull bubbling while retaining format validation and caps; wider M-U6 remains open.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_directive_date_null.py](tests/test_directive_date_null.py), `test_nullable_date_field_stays_null` (short source excerpt, not a reconstructed failure):
   ```python
   assert next(iter(result.data.values())) is None
   ```
   - [tests/test_directive_date_null.py](tests/test_directive_date_null.py): `test_date_only_value_still_uses_existing_formatting` (added definition); `test_date_resolver_none_is_not_a_format_wrapper` (added definition); `test_invalid_non_null_value_keeps_fallback` (added definition); `test_nullable_date_field_stays_null` (added definition); `test_required_nested_date_bubbles_only_to_nullable_parent` (added definition); `test_required_root_date_uses_normal_non_null_error` (added definition); `test_valid_datetime_still_formats` (added definition).
   - [tests/test_directive_date_text_time.py](tests/test_directive_date_text_time.py): `test_parser_zeros_microseconds_without_changing_explicit_or_nontext_values` (added definition); `test_text_default_preserves_active_timezone_with_use_tz_false` (added definition); `test_text_time_components_are_zero_in_native_graphql` (added definition); `test_text_time_only_keeps_current_date_across_days` (added definition).
   - [tests/test_directive_date_timezone.py](tests/test_directive_date_timezone.py): `test_absolute_formats_localize_only_explicit_instants` (added definition); `test_active_zone_applies_to_aware_instants_with_use_tz_false` (added definition); `test_adjacent_zero_offset_relative_formats_keep_instant` (added definition); `test_clock_adjacent_zero_offsets_match_z_absolute_zone` (added definition); `test_dst_conversion_uses_each_instants_active_offset` (added definition); `test_explicit_offset_before_accepted_abbreviation_is_localized` (added definition); `test_explicit_offset_before_trailing_year_is_localized` (added definition); `test_invalid_offset_text_keeps_string_fallback` (added definition); `test_naive_text_and_typed_inputs_keep_existing_wall_clock` (added definition); `test_parser_accepted_adjacent_zero_spellings_are_explicit` (added definition); `test_public_helpers_and_other_input_kinds_are_unchanged` (added definition); `test_relative_formats_keep_current_path` (added definition).
   - [tests/test_directive_date_naive_timezone.py](tests/test_directive_date_naive_timezone.py): `test_missing_components_keep_the_parser_default_across_midnight` (added definition); `test_named_unknown_and_numeric_offset_text_keep_previous_paths` (added definition); `test_original_explicit_offset_helper_retains_its_boolean_contract` (added definition); `test_timezone_less_summer_text_uses_each_active_zone` (added definition); `test_timezone_less_text_uses_active_zone_for_absolute_and_relative_formats` (added definition).

**Directive-specific boundary examples:** Nullable `@date`, `@number`, and `@currency` return null for null input; a GraphQL NonNull field still bubbles normally. `"2026-01-10"` becomes midnight, and `"2026-01-10 14:30"` fills missing seconds/microseconds with zero; a time-only string still needs the parser's current-date policy. For absolute output, `2026-01-10T23:30:00+00:00` may show **the next calendar day** in an active +02:00 zone while preserving the instant; zone-less `"2026-01-10 14:30"` attaches the active zone to its written wall clock even with `USE_TZ=False`. Relative wording can differ because the reference zone changes. Equivalent `Z`, `+00:00`, and `+0000` offsets are recognized on the covered path; named/unknown zone policies remain open. Case directives normalize `orderTotal` to `order_total`/`order-total` and `HTTPServer` to `httpServer`/`http_server`/`http-server`; they do not rename schema fields. Number/currency null preservation does not waive format validation or output caps. Native DateTime scalar parsing is a separate contract. Representative tests include `tests/test_directive_date_text_time.py`, `test_directive_date_timezone.py`, `test_directive_date_naive_timezone.py`, and `test_directive_date_null.py`.


### M-T1 — A fork-depth marker shared across threads could affect an ordinary schema in another thread

**Status:** bounded-fixed

**Original problem:** A fork-depth marker shared across threads could affect an ordinary schema in another thread. [original audit](auditoria-django-graphex-4.0.0.md), lines 173. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 249; [task T14d/T14](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** thread A forks; thread B compiles ordinary schema. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"thread_A": "schema fork depth 1", "thread_B": "ordinary compilation"}
```

**Before (illustrative):**
```json
{"thread_B_depth": 1}
```

**After (observed/current):**
```json
{"thread_B_depth": 0}
```

**How the result was reached:**
1. Schema fork registration depth moved from cross-thread shared state to thread-local context. Concurrent ordinary schema construction no longer inherits another thread's fork marker.
2. `4df64c4ff7dadb0c61b82fb72324f72179af4fc0`: source changes in [django_graphex/core/base.py](django_graphex/core/base.py), [django_graphex/schema.py](django_graphex/schema.py).
3. Scope check: fork-depth marker isolation; other registry races separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_schema_fork_threads.py](tests/core/test_schema_fork_threads.py), `test_concurrent_fork_preserves_sibling_output_projections` (short source excerpt, not a reconstructed failure):
   ```python
   assert str(types["MT1AuthorList"].fields["results"].type) == "[MT1AuthorOnly]"
   ```
   - [tests/core/test_schema_fork_threads.py](tests/core/test_schema_fork_threads.py): `test_concurrent_fork_preserves_sibling_output_projections` (added definition); `test_serial_projected_list_keeps_its_node_type` (added definition); `test_fork_marker_is_nested_and_restored_after_error` (added definition).


### L-C1 — Malformed IDs in get_node/retrieve/DjangoObjectField could escape as raw errors rather than a safe GraphQL result

**Status:** bounded-fixed

**Original problem:** Malformed IDs in get_node/retrieve/DjangoObjectField could escape as raw errors rather than a safe GraphQL result. [original audit](auditoria-django-graphex-4.0.0.md), lines 180. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 250; [task T15/R04a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** get_node id="abc" for integer key. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"node_id": "abc", "model_pk": "integer"}
```

**Before (illustrative):**
```json
{"exception": "raw conversion error"}
```

**After (observed/current):**
```json
{"errors": [{"code": "INVALID_ID"}]}
```

**How the result was reached:**
1. ID coercion distinguishes malformed values from well-formed absent or hidden rows; malformed input becomes safe INVALID_ID, while no matching visible node returns null.
2. `0512657622e64c731db94a699693999865c34703`: source changes in [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/types.py](django_graphex/types.py), [django_graphex/utils.py](django_graphex/utils.py).
3. Scope check: Malformed primary-key IDs in get_node/retrieve/DjangoObjectField now yield safe INVALID_ID GraphQL errors with integer, UUID or generic format hints; well-formed missing/hidden IDs remain null without errors. Valid text IDs and existing ORM coercion remain. No unrelated errors are relabeled.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_invalid_id_contract.py](tests/test_invalid_id_contract.py), `test_malformed_integer_id_has_safe_public_error` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data == {"article": None}
   ```
   - [tests/test_invalid_id_contract.py](tests/test_invalid_id_contract.py): `test_malformed_integer_id_has_safe_public_error` (added definition); `test_malformed_uuid_id_has_safe_public_error` (added definition); `test_get_node_rejects_malformed_integer_id` (added definition); `test_malformed_id_in_generated_retrieve_field` (added definition); `test_valid_missing_and_char_primary_keys_keep_orm_meaning` (added definition); `test_hidden_row_still_looks_missing` (added definition); `test_unrelated_queryset_errors_are_not_relabelled` (added definition); `test_custom_primary_key_prepared_once_with_generic_error` (added definition); `test_custom_primary_key_renamed_argument_keeps_safe_public_error` (added definition); `test_http_production_wire_keeps_deliberate_error` (added definition); `test_existing_numeric_and_null_coercion_remain_orm_owned` (added definition); `test_non_null_field_bubbles_the_deliberate_error` (added definition); `test_uuid_missing_and_valid_ids_keep_lookup_behavior` (added definition); `test_retrieve_authorization_error_precedes_id_conversion` (added definition); `test_existing_missing_exception_boundary_in_hooks_is_preserved` (added definition).


### L-C2 — Constructor guards used assert and disappeared under optimized Python

**Status:** bounded-fixed

**Original problem:** Constructor guards used assert and disappeared under optimized Python. [original audit](auditoria-django-graphex-4.0.0.md), lines 181. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 251; [task T14/T14a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** invalid constructor under python -O. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"runtime": "python -O", "constructor": "invalid schema or conflicting mode"}
```

**Before (illustrative):**
```json
{"assertion": "optimized away", "accepted": true}
```

**After (observed/current):**
```json
{"error": "explicit AssertionError", "accepted": false}
```

**How the result was reached:**
1. The two identified constructor preconditions became explicit exceptions rather than assert statements, so Python -O cannot remove them. Other guards were not exhaustively audited.
2. `9fec11da77a76f697ff6365a6c0bc5ed6c33f4d7`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: Two specific constructor validations now survive optimized Python (-O); no universal validation claim follows.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_view_base.py](tests/test_view_base.py), `test_view_constructor_does_not_use_optimized_away_validation` (short source excerpt, not a reconstructed failure):
   ```python
   assert not any(isinstance(node, ast.Assert) for node in ast.walk(constructor))
   ```
   - [tests/test_view_base.py](tests/test_view_base.py): `test_view_constructor_rejects_invalid_schema` (added definition); `test_view_constructor_rejects_conflicting_modes` (added definition); `test_view_constructor_does_not_use_optimized_away_validation` (added definition).
**Inherited locator correction:** The guide lists `tests/test_settings_boundary_values.py`, which tests settings and not the two view-constructor guards. The causal `9fec11d` tests are in `tests/test_view_base.py`; the old locator is retained only as a historical guide citation.


### L-C3 — The enhanced and base GraphQL views diverged on status/data:null for a non-null-root execution error

**Status:** bounded-fixed

**Original problem:** The enhanced and base GraphQL views diverged on status/data:null for a non-null-root execution error. [original audit](auditoria-django-graphex-4.0.0.md), lines 182. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 252; [task T13/R04b](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** non-null root resolver raises. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"query": "{ requiredRoot }", "resolver": "raises"}
```

**Before (illustrative):**
```json
{"http_status": 400, "data": "omitted"}
```

**After (observed/current):**
```json
{"http_status": 200, "data": null, "errors": ["resolver failed"]}
```

**How the result was reached:**
1. The enhanced and base views preserve GraphQL execution's data:null plus errors under HTTP 200 for non-null root failures. Parse/validation errors still use HTTP 400 without data.
2. `276841a9f9ff1796153c6ca52194f20866067373`: source changes in [django_graphex/views.py](django_graphex/views.py).
3. Scope check: Enhanced JSON view now matches the base view for a path-bearing non-null-root execution error: HTTP 200 with data: null and errors; syntax, validation, and variable-coercion errors remain HTTP 400 without data. Auth, transport, and other media policies are separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_http_execution_error_contract.py](tests/test_http_execution_error_contract.py), `test_nonnull_root_execution_error_has_null_data_in_both_views` (short source excerpt, not a reconstructed failure):
   ```python
   assert payload["errors"][0]["path"] == ["required"]
   ```
   - [tests/test_http_execution_error_contract.py](tests/test_http_execution_error_contract.py): `test_nonnull_root_execution_error_has_null_data_in_both_views` (added definition); `test_null_execution_envelope_survives_cleaning_and_production_formatting` (added definition); `test_request_errors_stay_http_400_without_data` (added definition); `test_nullable_error_and_success_keep_existing_data_and_cost` (added definition); `test_null_execution_errors_are_not_cached_or_replayed` (added definition); `test_batch_execution_error_continues_and_validation_error_remains_scoped` (added definition); `test_multipart_form_uses_same_execution_envelope` (added definition).


### L-C4 — Multipart uploads bypassed MAX_UPLOAD_SIZE, including files not mapped into operations

**Status:** bounded-fixed

**Original problem:** Multipart uploads bypassed MAX_UPLOAD_SIZE, including files not mapped into operations. [original audit](auditoria-django-graphex-4.0.0.md), lines 183. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 253; [task T13/R04c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** cap=3 bytes; unused upload=4 bytes. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"upload_bytes": 4, "configured_cap_bytes": 3, "upload_referenced": false}
```

**Before (illustrative):**
```json
{"resolver_calls": 1}
```

**After (observed/current):**
```json
{"http_status": 413, "resolver_calls": 0}
```

**How the result was reached:**
1. Multipart parsing measures every received file against MAX_UPLOAD_SIZE before mapping it into operations, including repeated and unused entries. Other upload encodings are not covered.
2. `dfb47a0078466b96eb59d9ccba150639db08e225`: source changes in [django_graphex/settings.py](django_graphex/settings.py), [django_graphex/views.py](django_graphex/views.py).
3. Scope check: Configured MAX_UPLOAD_SIZE now checks each received multipart file, including unused and repeated parts, after parsing and before resolver or successful GraphiQL rendering. A file at the cap passes; above it returns safe JSON HTTP 413. None leaves multipart without this cap. The independent whole-body limit and Base64 contract remain; malformed batches still return their existing HTTP 400. This is not ingress protection.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_multipart_file_size_http.py](tests/test_multipart_file_size_http.py), `test_oversized_multipart_file_is_rejected_before_resolver` (short source excerpt, not a reconstructed failure):
   ```python
   assert "MAX_UPLOAD_SIZE" in payload["errors"][0]["message"]
   ```
   - [tests/test_multipart_file_size_http.py](tests/test_multipart_file_size_http.py): `test_oversized_multipart_file_is_rejected_before_resolver` (added definition); `test_single_file_boundary_and_uncapped_mode` (added definition); `test_every_repeated_file_is_checked` (added definition); `test_multiple_files_are_not_summed` (added definition); `test_malformed_multipart_batch_keeps_400_before_file_cap` (added definition); `test_graphiql_success_path_still_checks_files` (added definition); `test_cache_active_multipart_cannot_bypass_file_cap` (added definition); `test_independent_total_body_cap_still_rejects_first` (added definition); `test_temporary_uploaded_file_is_rejected_and_closed` (added definition); `test_csrf_header_refusal_precedes_file_cap` (added definition); `test_oversized_file_prevents_mutation_resolver` (added definition).


### L-C5 — Three minimum-limit settings accepted negative integer values despite their declared zero minimum

**Status:** bounded-fixed

**Original problem:** Three minimum-limit settings accepted negative integer values despite their declared zero minimum. [original audit](auditoria-django-graphex-4.0.0.md), lines 184. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 254; [task T13/R04d](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** MAX_BATCH_SIZE=-1. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"setting": "MAX_BATCH_SIZE", "value": -1}
```

**Before (illustrative):**
```json
{"startup": "accepted invalid value"}
```

**After (observed/current):**
```json
{"error": "ImproperlyConfigured: minimum 0"}
```

**How the result was reached:**
1. Settings parsing rejects negative integers for MAX_BATCH_SIZE, MAX_REQUEST_BODY_SIZE and DOCUMENT_CACHE_MAXSIZE at read time. Zero and None retain their defined meanings.
2. `9760b29773e3f62e9afebe7ac878779398878256`: source changes in [django_graphex/settings.py](django_graphex/settings.py).
3. Scope check: MAX_BATCH_SIZE, MAX_REQUEST_BODY_SIZE, and DOCUMENT_CACHE_MAXSIZE now reject negative integers with ImproperlyConfigured when read, naming the setting, value, minimum zero, and remedy. Zero, None, positives, defaults, and existing noninteger handling retain their prior behavior. This is not eager startup validation.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_settings_minimum_zero.py](tests/test_settings_minimum_zero.py), `test_negative_integer_limit_fails_on_public_setting_read` (short source excerpt, not a reconstructed failure):
   ```python
   assert remedy in message
   ```
   - [tests/test_settings_minimum_zero.py](tests/test_settings_minimum_zero.py): `test_negative_integer_limit_fails_on_public_setting_read` (added definition); `test_approved_boundary_values_are_retained` (added definition); `test_default_is_unchanged` (added definition); `test_existing_nonnegative_bool_and_noninteger_policy_is_unchanged` (added definition); `test_negative_limit_is_validated_lazily` (added definition).


### L-C6 — The audit assumed ensure_csrf_cookie made all future browser cache behavior impossible

**Status:** contract

**Original problem:** The audit assumed ensure_csrf_cookie made all future browser cache behavior impossible. [original audit](auditoria-django-graphex-4.0.0.md), lines 185. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 255; [task T13/R04e](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** cookie-free miss vs hit. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"all paths assumed to set cookie"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The cookie/cache trace was documented, not patched: a no-cookie miss can set csrftoken, a no-cookie hit returns earlier without setting it, and a later cookie request bypasses server response caching.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: A cache miss reaches ensure_csrf_cookie and can set csrftoken; a cache hit returns earlier without Set-Cookie. A later cookie-bearing request bypasses the any-cookie cache policy.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_views_cache_cookie_bypass.py](tests/test_views_cache_cookie_bypass.py), `test_issued_csrf_cookie_bypasses_next_server_cache_lookup` (short source excerpt, not a reconstructed failure):
   ```python
   assert second.status_code == 200
   ```
   - [tests/test_views_cache_cookie_bypass.py](tests/test_views_cache_cookie_bypass.py): `test_cookie_dependent_anonymous_queries_are_not_shared` (unchanged definition); `test_default_hook_rejects_cookie_bearing_queries` (unchanged definition); `test_default_hook_allows_cookie_free_queries` (unchanged definition); `test_cookie_bearing_mutation_still_invalidates` (unchanged definition); `test_issued_csrf_cookie_bypasses_next_server_cache_lookup` (added definition).


### L-C7 — Position-derived choice enum names could be ambiguous or unstable when choices were reordered

**Status:** bounded-fixed

**Original problem:** Position-derived choice enum names could be ambiguous or unstable when choices were reordered. [original audit](auditoria-django-graphex-4.0.0.md), lines 186. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 256; [task T06e/T06](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** two choices normalize to same enum member. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"enum_choices": [["1", "A B"], ["2", "A_B"]], "normalized_name": "A_B"}
```

**Before (illustrative):**
```json
{"members": ["A_B", "A_B_1"]}
```

**After (observed/current):**
```json
{"error": "choice name collision"}
```

**How the result was reached:**
1. Choice enum construction rejects an ambiguous member name generated from positional choices, avoiding order-dependent wire identity. Optional multiselect was not included in the witness.
2. `c3a35a741a769cbb90bc6846062f0800b1199f9b`: source changes in [django_graphex/converter.py](django_graphex/converter.py).
3. Scope check: ambiguous enum members rejected; optional multiselect untested.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_choices_enum_member_ambiguity.py](tests/core/test_choices_enum_member_ambiguity.py), `test_ambiguous_members_reject_public_schema_without_cache_pollution` (short source excerpt, not a reconstructed failure):
   ```python
   assert list(corrected.values) == ["ALPHA", "BETA"]
   ```
   - [tests/core/test_choices_enum_member_ambiguity.py](tests/core/test_choices_enum_member_ambiguity.py): `test_ambiguous_members_reject_all_supported_choices_forms` (added definition); `test_ambiguous_members_reject_public_schema_without_cache_pollution` (added definition); `test_ambiguous_members_reject_generated_input_and_filter` (added definition).


### L-C8 — The audit expected page:-1 to equal the final positive page instead of the defined fixed-size tail window

**Status:** contract

**Original problem:** The audit expected page:-1 to equal the final positive page instead of the defined fixed-size tail window. [original audit](auditoria-django-graphex-4.0.0.md), lines 187. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 257; [task T12](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** 23 rows; size=10; page=-1. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"expect final page's 3 rows"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. No pagination code changed for this allegation: page:-1 already denotes the final fixed-size window, not the short remainder of the last positive page. The audit's expected equivalence was incorrect.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: Negative page -1 means a fixed-size tail window, not the positive final page's short remainder.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py), `test_explicit_null_page_matches_omission_http` (short source excerpt, not a reconstructed failure):
   ```python
   assert expected["totalCount"] == 5
   ```
   - [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py): `test_explicit_null_page_matches_omission_http` (added definition); `test_existing_page_boundaries_http` (added definition); `test_omitted_nullable_variable_keeps_default_http` (added definition); `test_nested_null_page_reaches_materialized_list_without_optimizer` (added definition); `test_direct_page_null_normalizes_both_paths` (added definition).


### L-C9 — Nullable ordering differed between database and in-memory pagination paths

**Status:** bounded-fixed

**Original problem:** Nullable ordering differed between database and in-memory pagination paths. [original audit](auditoria-django-graphex-4.0.0.md), lines 188. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 258; [task T12/R04f](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** nullable values [null,1] ascending. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"values": [null, 1], "order": "asc"}
```

**Before (illustrative):**
```json
{"sqlite_ids": ["null", "one"]}
```

**After (observed/current):**
```json
{"covered_ids": ["one", "null"]}
```

**How the result was reached:**
1. Automatic nullable ordering adds explicit NULL placement—last ascending, first descending—on covered database and in-memory paths. User-specified ORM expressions and cursor policy remain separate.
2. `ebeb63ab665f650551470b3db107f8c98f28e87a`: source changes in [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py).
3. Scope check: Automatic nullable concrete-column order now places NULL last ascending/first descending for offset/page DB, nested window and list paths; Cursor already agreed. Explicit ORM expressions/null flags, custom terms and broader backend parity are separate.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_pagination_null_order_parity.py](tests/test_pagination_null_order_parity.py), `test_nullable_queryset_and_materialized_pages_agree` (short source excerpt, not a reconstructed failure):
   ```python
   assert [row.pk for row in queryset_page] == expected
   ```
   - [tests/test_pagination_null_order_parity.py](tests/test_pagination_null_order_parity.py): `test_nullable_queryset_and_materialized_pages_agree` (added definition); `test_nested_nullable_order_matches_window_and_plain_prefetch` (added definition); `test_explicit_orm_null_placement_remains_authoritative` (added definition); `test_multifield_priority_and_relation_name_remain_intact` (added definition); `test_malformed_prefix_is_not_normalized_into_a_valid_column` (added definition).


### L-C10 — Transformation directives declared fragment locations but silently did nothing on those locations

**Status:** bounded-fixed

**Original problem:** Transformation directives declared fragment locations but silently did nothing on those locations. [original audit](auditoria-django-graphex-4.0.0.md), lines 189. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 259; [task T15/R03k](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** @uppercase on FRAGMENT_SPREAD. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"query": "{ ...Words @uppercase } fragment Words on Query { text }", "directive_location": "FRAGMENT_SPREAD"}
```

**Before (illustrative):**
```json
{"validation": "accepted", "transform": "ignored"}
```

**After (observed/current):**
```json
{"data": null, "validation_error": "@uppercase invalid on fragment spread", "resolver_calls": 0}
```

**How the result was reached:**
1. Transformation directive declarations now advertise FIELD only, so GraphQL validation rejects use on spread or inline fragment before resolver execution. A field nested inside a fragment may still transform normally.
2. `03cd107e028dd096a759e95b5bbb4f98dde15c2c`: source changes in [django_graphex/directives/base.py](django_graphex/directives/base.py).
3. Scope check: Library transforms now declare FIELD only; fragment-spread and inline-fragment placements fail validation before resolver execution. Fields inside fragments still transform; spec built-ins and raw third-party directive locations are unchanged.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_directive_field_locations.py](tests/test_directive_field_locations.py), `test_transform_on_fragment_is_rejected_before_resolution` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data is None
   ```
   - [tests/test_directive_field_locations.py](tests/test_directive_field_locations.py): `test_transform_on_fragment_is_rejected_before_resolution` (added definition); `test_field_transform_inside_fragment_still_executes` (added definition); `test_spec_builtins_still_control_fragment_and_field_selection` (added definition); `test_library_locations_and_builtin_metadata_are_distinct` (added definition); `test_raw_third_party_directive_keeps_explicit_fragment_locations` (added definition); `test_field_transform_order_is_unchanged` (added definition); `test_invalid_fragment_transform_has_http_error_wire` (added definition); `test_guide_states_field_only_contract_with_fragment_migration` (added definition).


### L-C11 — The report grouped @floor non-finite failures with @truncate and an unregistered @title name

**Status:** bounded-fixed

**Original problem:** The report grouped @floor non-finite failures with @truncate and an unregistered @title name. [original audit](auditoria-django-graphex-4.0.0.md), lines 190. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 260; [task T15/R03l](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** @floor("inf"). The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"directive": "@floor", "value": "inf"}
```

**Before (illustrative):**
```json
{"exception": "Python integer conversion detail"}
```

**After (observed/current):**
```json
{"errors": ["stable GraphQL field error"]}
```

**How the result was reached:**
1. The floor directive maps NaN and Infinity conversion failure to a stable GraphQL error. The alleged @title directive is unregistered; @title_case and @truncate were not changed by this fix.
2. `5b1022bcb5649016afc1ebada00b8e941e713170`: source changes in [django_graphex/directives/numbers.py](django_graphex/directives/numbers.py).
3. Scope check: @floor now raises the approved GraphQL error for NaN and either infinity. The report's @title is not registered; actual @title_case and @truncate stringify non-finite values and have no demonstrated defect. Their behavior is unchanged.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_floor_nonfinite_error.py](tests/test_floor_nonfinite_error.py), `test_floor_public_execution_returns_nullable_error` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data == {"value": None}
   ```
   - [tests/test_floor_nonfinite_error.py](tests/test_floor_nonfinite_error.py): `test_floor_directly_rejects_nonfinite_values` (added definition); `test_floor_public_execution_returns_nullable_error` (added definition); `test_floor_rejects_numeric_strings_that_coerce_to_nonfinite` (added definition); `test_floor_keeps_finite_and_boolean_values` (added definition); `test_floor_preserves_none_and_malformed_value_policy` (added definition); `test_floor_nonnull_error_uses_standard_bubbling` (added definition); `test_other_directives_and_floor_schema_metadata_remain_unchanged` (added definition).


### L-C12 — A GFK union-wrapper fragment could miss batched optimization

**Status:** partial

**Original problem:** A GFK union-wrapper fragment could miss batched optimization; broader MTI behavior was asserted without proof. [original audit](auditoria-django-graphex-4.0.0.md), lines 191. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 261; [task T14/T14e](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** GFK union wrapper over several rows. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"rows": [1, 2, 3], "generic_fk_target_type": "Author"}
```

**Before (illustrative):**
```json
{"target_fetches": 3}
```

**After (observed/current):**
```json
{"target_fetches": "one covered type batch"}
```

**How the result was reached:**
1. The GFK union-wrapper optimizer collects branch relation plans instead of losing them at the wrapper boundary, eliminating the exercised N+1. Multi-table inheritance outside this shape remains unproved.
2. `c8bb0dd2d7700eec80cadbab3ade0af4f3a655e8`: source changes in [django_graphex/utils.py](django_graphex/utils.py).
3. Scope check: The covered GFK union-wrapper path no longer makes an N+1 query; broader multi-table-inheritance paths remain unproved.
4. Actual test locators, with base-to-snapshot definition provenance:
   - [tests/test_optimizer_phase_e.py](tests/test_optimizer_phase_e.py): `test_returns_hook_when_present` (unchanged definition); `test_returns_none_when_absent` (unchanged definition); `test_returns_none_when_gql_type_is_none` (unchanged definition); `test_returns_none_when_no_graphene_type` (unchanged definition); `test_camel_case_field_name_is_snake_cased` (unchanged definition); `test_returns_qs_unchanged_when_hook_is_none` (unchanged definition); `test_returns_hook_result_when_valid_queryset` (unchanged definition); `test_hook_receives_filter_value_and_is_window_kwargs` (unchanged definition); `test_non_queryset_return_emits_warning_and_returns_original` (unchanged definition); `test_exception_propagates_when_safe_mode_false` (unchanged definition); `test_exception_propagates_from_helper_even_when_safe_mode_true` (unchanged definition); `test_ac1_window_hook_fires_with_is_window_true` (unchanged definition); `test_ac5_hook_adds_distinct_falls_back_to_plain` (unchanged definition); `test_ac6_hook_aliasing_gqx_rn_is_silently_overwritten_noop` (unchanged definition); `test_ac2_filtered_plain_hook_fires_with_is_window_false` (unchanged definition); `test_ac2b_unfiltered_top_level_hook_fires` (unchanged definition); `test_ac2b_no_hook_is_noop` (unchanged definition); `test_site_b_hook_fires_for_reroot_child` (unchanged definition); `test_hook_fires_through_forward_fk_relation` (unchanged definition); `test_multiple_children_and_multi_segment_hooks_all_fire` (unchanged definition); `test_hook_fires_when_only_and_annotated_off` (unchanged definition); `test_hook_does_not_fire_when_optimize_queryset_false` (unchanged definition); `test_hooked_case_has_join_control_does_not` (unchanged definition); `test_safe_mode_raising_hook_degrades_whole_resolve_coarsely` (unchanged definition); `test_no_hook_no_error_and_no_behavior_change` (unchanged definition).


### L-C13 — Naive DateTime scalar parsing and @date active-timezone formatting were treated as one undocumented policy

**Status:** contract

**Original problem:** Naive DateTime scalar parsing and @date active-timezone formatting were treated as one undocumented policy. [original audit](auditoria-django-graphex-4.0.0.md), lines 192. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 262; [task T15](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** naive DateTime scalar vs naive @date text. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"assumed both use same local-zone policy"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The documentation separated native DateTime naive parsing from @date's active-timezone formatting, including USE_TZ=False. The scalar implementation was not silently changed.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: The guide distinguishes native DateTime scalar naive parsing from @date's active-timezone interpretation, including USE_TZ=False; no scalar policy changed.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### L-E1 — Broad exception handling around get_fields could silently remove model-derived relations

**Status:** bounded-fixed

**Original problem:** Broad exception handling around get_fields could silently remove model-derived relations. [original audit](auditoria-django-graphex-4.0.0.md), lines 195. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 263; [task T14/T14f](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** get_fields() raises during type build. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"model": "Book", "relation": "author", "get_fields": "raises RuntimeError"}
```

**Before (illustrative):**
```json
{"schema": "author relation silently omitted"}
```

**After (observed/current):**
```json
{"error": "Book field introspection failed with cause"}
```

**How the result was reached:**
1. Model field enumeration now surfaces get_fields failure with model and underlying cause instead of swallowing it and producing a truncated schema. Healthy enumeration remains unchanged.
2. `0c5e32065fc43799b36872ea6bc1cdaf9f007af7`: source changes in [django_graphex/core/base.py](django_graphex/core/base.py), [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py), [django_graphex/schema.py](django_graphex/schema.py), [django_graphex/types.py](django_graphex/types.py).
3. Scope check: get_fields failure surfaces model/cause; healthy path unchanged.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_metadata_enumeration_failures.py](tests/core/test_metadata_enumeration_failures.py), `test_model_derived_fields_identifies_model_and_preserves_cause` (short source excerpt, not a reconstructed failure):
   ```python
   assert caught.value.__cause__ is original
   ```
   - [tests/core/test_metadata_enumeration_failures.py](tests/core/test_metadata_enumeration_failures.py): `test_model_derived_fields_identifies_model_and_preserves_cause` (added definition); `test_output_compiler_identifies_model_and_preserves_cause` (added definition); `test_public_schema_rejects_relation_metadata_failure` (added definition); `test_eager_field_recompile_retains_original_cause` (added definition); `test_eager_field_recompile_keeps_uncaused_error_unchained` (added definition); `test_lazy_schema_keeps_uncaused_configuration_error` (added definition); `test_lazy_schema_leaves_generic_type_error_untouched` (added definition).


### L-E2 — getattr(..., None) could swallow AttributeError raised inside an explicitly sourced property

**Status:** bounded-fixed

**Original problem:** getattr(..., None) could swallow AttributeError raised inside an explicitly sourced property. [original audit](auditoria-django-graphex-4.0.0.md), lines 196. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 264; [task T15/T15a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** explicit source property raises AttributeError. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"source_property": "book.title", "getter": "raises AttributeError"}
```

**Before (illustrative):**
```json
{"data": {"title": null}, "errors": []}
```

**After (observed/current):**
```json
{"data": {"title": null}, "errors": ["property failure"]}
```

**How the result was reached:**
1. An explicitly sourced property getter's AttributeError is surfaced rather than treated as an absent attribute; genuine missing optional attributes may still resolve to null.
2. `72fbcbdccecfb955ad71666b31ae7c02618803eb`: source changes in [django_graphex/core/descriptors.py](django_graphex/core/descriptors.py). Follow-up source commits: `7fb4c121dca116d9e0192e87d744f555444c1c27`.
3. Scope check: explicit source property AttributeError surfaced; legitimate null/unrelated descriptors unchanged.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_source_property_attribute_error.py](tests/core/test_source_property_attribute_error.py), `test_wrapped_python_property_source_preserves_original_error` (short source excerpt, not a reconstructed failure):
   ```python
   assert result.data == {"alias": None, "healthy": "visible"}
   ```
   - [tests/core/test_source_property_attribute_error.py](tests/core/test_source_property_attribute_error.py): `test_wrapped_python_property_source_preserves_original_error` (added definition); `test_source_property_attribute_error_surfaces_graphql_resolution_error` (added definition); `test_inherited_source_property_failure_preserves_required_propagation` (added definition); `test_source_absence_and_successful_dynamic_fallback_remain_nullable` (added definition); `test_absent_django_reverse_one_to_one_stays_nullable_through_property` (added definition); `test_custom_attribute_lookup_and_nested_required_propagation` (added definition); `test_unrelated_descriptor_and_dynamic_absence_keep_legacy_null` (added definition); `test_explicit_resolver_precedes_source_and_method_body_error_is_unchanged` (added definition); `test_source_property_failure_keeps_safe_http_diagnostics` (added definition).


### L-E3 — Filtered-prefetch merging was suspected of dropping optimize_<field> and leaking unscoped rows

**Status:** partial

**Original problem:** Filtered-prefetch merging was suspected of dropping optimize_<field> and leaking unscoped rows. [original audit](auditoria-django-graphex-4.0.0.md), lines 197. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 265; [task T07/T14](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** SITE-B filtered prefetch with optimizer hook. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"site": "SITE-B", "optimizer_hook": "filtered prefetch"}
```

**Before (illustrative):**
```json
{"audit_prediction": "hook missing / hidden row leak"}
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The exact SITE-B witness showed optimize_<field> called once, visible rows only, and the grouped predicate intact. No optimizer patch was justified for that route; other sites remain unmeasured.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: The exact SITE-B filtered-prefetch hook-loss allegation was contradicted by a public SQLite witness: hook called once, visible rows only, one batched predicate query. Other branches/backends remain unproved.
4. Actual test locators, with base-to-snapshot definition provenance:
   - [tests/test_optimizer_phase_e.py](tests/test_optimizer_phase_e.py): `test_returns_hook_when_present` (unchanged definition); `test_returns_none_when_absent` (unchanged definition); `test_returns_none_when_gql_type_is_none` (unchanged definition); `test_returns_none_when_no_graphene_type` (unchanged definition); `test_camel_case_field_name_is_snake_cased` (unchanged definition); `test_returns_qs_unchanged_when_hook_is_none` (unchanged definition); `test_returns_hook_result_when_valid_queryset` (unchanged definition); `test_hook_receives_filter_value_and_is_window_kwargs` (unchanged definition); `test_non_queryset_return_emits_warning_and_returns_original` (unchanged definition); `test_exception_propagates_when_safe_mode_false` (unchanged definition); `test_exception_propagates_from_helper_even_when_safe_mode_true` (unchanged definition); `test_ac1_window_hook_fires_with_is_window_true` (unchanged definition); `test_ac5_hook_adds_distinct_falls_back_to_plain` (unchanged definition); `test_ac6_hook_aliasing_gqx_rn_is_silently_overwritten_noop` (unchanged definition); `test_ac2_filtered_plain_hook_fires_with_is_window_false` (unchanged definition); `test_ac2b_unfiltered_top_level_hook_fires` (unchanged definition); `test_ac2b_no_hook_is_noop` (unchanged definition); `test_site_b_hook_fires_for_reroot_child` (unchanged definition); `test_hook_fires_through_forward_fk_relation` (unchanged definition); `test_multiple_children_and_multi_segment_hooks_all_fire` (unchanged definition); `test_hook_fires_when_only_and_annotated_off` (unchanged definition); `test_hook_does_not_fire_when_optimize_queryset_false` (unchanged definition); `test_hooked_case_has_join_control_does_not` (unchanged definition); `test_safe_mode_raising_hook_degrades_whole_resolve_coarsely` (unchanged definition); `test_no_hook_no_error_and_no_behavior_change` (unchanged definition).


### L-E4 — Cancellation swallowed exceptions and a single-group close warning was independently observed

**Status:** partial

**Original problem:** Cancellation swallowed exceptions and a single-group close warning was independently observed. [original audit](auditoria-django-graphex-4.0.0.md), lines 198. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 266; [task T08/T08c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** cancel source with one group. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"source": "one subscribed group", "action": "cancel stream"}
```

**Before (illustrative):**
```json
{"close": "RuntimeError warning leaked"}
```

**After (observed/current):**
```json
{"close": "warning handled on covered path"}
```

**How the result was reached:**
1. Expected cancellation swallowing was retained; only the observed single-group aclose warning received targeted cleanup. Unexercised cancellation phases are not marked fixed.
2. `e04394b6fcc4b4ac02e31793e7e6479fea785e9c`: source changes in [django_graphex/subscriptions/delivery.py](django_graphex/subscriptions/delivery.py).
3. Scope check: cancellation intentional; single-group aclose warning fixed only.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_delivery_runtimeerror_diagnostic.py](tests/subscriptions/test_delivery_runtimeerror_diagnostic.py), `test_delivery_close_runtimeerror_warns_once_and_stays_idempotent` (short source excerpt, not a reconstructed failure):
   ```python
   assert warnings[0].exc_info[1] is failure
   ```
   - [tests/subscriptions/test_delivery_runtimeerror_diagnostic.py](tests/subscriptions/test_delivery_runtimeerror_diagnostic.py): `test_client_complete_logs_suppressed_delivery_runtimeerror` (added definition); `test_client_complete_valueerror_keeps_existing_error_frame` (added definition); `test_delivery_close_runtimeerror_warns_once_and_stays_idempotent` (added definition).
   - [tests/subscriptions/test_source.py](tests/subscriptions/test_source.py): `test_all_actions_joins_exactly_three_groups` (historical locator; not in the changed-path inventory); `test_single_action_joins_exactly_one_group_1420_guard` (historical locator; not in the changed-path inventory); `test_context_manager_start_joins_groups` (historical locator; not in the changed-path inventory); `test_broadcast_to_joined_group_yields_flat_data_dict` (historical locator; not in the changed-path inventory); `test_serialize_instance_not_called_on_consumer_yield_path` (historical locator; not in the changed-path inventory); `test_assertNumQueries_zero_on_consumer_yield_path` (historical locator; not in the changed-path inventory); `test_non_matching_filter_event_dropped_pre_execute` (historical locator; not in the changed-path inventory); `test_no_filters_yields_every_event` (historical locator; not in the changed-path inventory); `test_aclose_group_discards_every_joined_group` (historical locator; not in the changed-path inventory); `test_aexit_group_discards_every_joined_group` (historical locator; not in the changed-path inventory); `test_aclose_releases_blocked_receive_promptly` (historical locator; not in the changed-path inventory); `test_aclose_idempotent` (historical locator; not in the changed-path inventory); `test_group_discard_runs_even_on_abnormal_teardown` (historical locator; not in the changed-path inventory); `test_aclose_discard_sweep_is_exception_isolated` (historical locator; not in the changed-path inventory); `test_external_cancellation_propagates` (historical locator; not in the changed-path inventory); `test_aclose_initiated_cancel_still_stops_cleanly` (historical locator; not in the changed-path inventory); `test_lookup_filter_without_verifier_drops_conservatively` (historical locator; not in the changed-path inventory); `test_lookup_filter_with_verifier_true_yields_false_drops` (historical locator; not in the changed-path inventory); `test_source_module_has_no_graphene_import` (historical locator; not in the changed-path inventory); `test_source_module_is_async_iterator` (historical locator; not in the changed-path inventory).


### L-M1 — An input registry might grow under dynamic class redefinition

**Status:** decision-deferred

**Original problem:** An input registry might grow under dynamic class redefinition; static schema reuse was used as evidence but not a lifecycle policy. [original audit](auditoria-django-graphex-4.0.0.md), lines 201. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 267; [task T14](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** three static schemas reuse input class. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"audit predicts unbounded duplicates"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Three static schemas reused input classes without observed growth, but dynamic class churn lacks an ownership/eviction contract. No global registry lifecycle change was made.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: Declared input classes are intentionally registry-owned and a static three-schema reuse stayed bounded; dynamic class churn needs an ownership/lifecycle policy.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_registry_compiler.py](tests/core/test_registry_compiler.py), `test_mutual_recursion_terminates` (short source excerpt, not a reconstructed failure):
   ```python
   assert compiled_b.name == "NodeB"
   ```
   - [tests/core/test_registry_compiler.py](tests/core/test_registry_compiler.py): `test_mutual_recursion_terminates` (historical locator; not in the changed-path inventory); `test_mutual_recursion_thunks_resolve_correctly` (historical locator; not in the changed-path inventory); `test_self_referential_type_compiles` (historical locator; not in the changed-path inventory); `test_compile_all_raises_on_missing_gdx_extensions` (historical locator; not in the changed-path inventory); `test_compile_all_no_error_when_all_types_have_gdx` (historical locator; not in the changed-path inventory).


### L-M2 — An internal field identity table keyed by id() could suffer object-ID reuse after lifetime ended

**Status:** partial

**Original problem:** An internal field identity table keyed by id() could suffer object-ID reuse after lifetime ended. [original audit](auditoria-django-graphex-4.0.0.md), lines 202. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 268; [task T14/T14g](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** live field identity reused across schemas. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"schemas": ["A", "B"], "field": "same live Python field identity"}
```

**Before (illustrative):**
```json
{"internal_cache": "id-based stale reuse possible"}
```

**After (observed/current):**
```json
{"internal_cache": "lifetime-guarded for covered path"}
```

**How the result was reached:**
1. Native field identity tracking retains a live object reference rather than relying only on id(), preventing recycled object IDs from inheriting an old registration. Public impact was not demonstrated.
2. `a2ff209469f1c642fff20ebf78c3c4019db1dd5b`: source changes in [django_graphex/core/mutation.py](django_graphex/core/mutation.py), [django_graphex/core/schema_compiler.py](django_graphex/core/schema_compiler.py), [django_graphex/mutation.py](django_graphex/mutation.py), [django_graphex/types.py](django_graphex/types.py).
3. Scope check: A bounded internal live-field identity/lifetime case was corrected; public schema impact and Graphene behavior were not established.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_native_field_identity_lifetime.py](tests/core/test_native_field_identity_lifetime.py), `test_native_field_marker_expires_when_field_dies` (short source excerpt, not a reconstructed failure):
   ```python
   assert reference() is None
   ```
   - [tests/core/test_native_field_identity_lifetime.py](tests/core/test_native_field_identity_lifetime.py): `test_native_field_marker_expires_when_field_dies` (added definition); `test_live_native_field_survives_registry_slot_overwrite` (added definition); `test_current_registry_value_is_a_defensive_identity_source` (added definition); `test_stale_identity_key_cannot_admit_an_unrelated_field` (added definition); `test_modeltype_builder_tracks_its_actual_native_field` (added definition); `test_model_mutation_builder_tracks_its_actual_native_field` (added definition).


### L-M3 — An enum cache lacked synchronization in concurrent direct schema builds

**Status:** partial

**Original problem:** An enum cache lacked synchronization in concurrent direct schema builds. [original audit](auditoria-django-graphex-4.0.0.md), lines 203. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 269; [task T14/T14h](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** two threads compile same enum. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"threads": 2, "enum": "same model choices"}
```

**Before (illustrative):**
```json
{"constructions": 2}
```

**After (observed/current):**
```json
{"constructions": 1}
```

**How the result was reached:**
1. Direct GraphQLSchema enum creation is serialized around the shared cache fill, preventing concurrent same-name construction from racing. A public request race was not established.
2. `14720eab7d6662c4ce9f3ee56f1b7740133e1c08`: source changes in [django_graphex/converter.py](django_graphex/converter.py), [django_graphex/core/compiler.py](django_graphex/core/compiler.py), [django_graphex/registry.py](django_graphex/registry.py).
3. Scope check: A direct GraphQLSchema enum-cache race was corrected; public exposure was not established.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_enum_cache_concurrency.py](tests/core/test_enum_cache_concurrency.py), `test_compile_enum_shares_one_object_after_contended_miss` (short source excerpt, not a reconstructed failure):
   ```python
   assert len(constructed) == 1
   ```
   - [tests/core/test_enum_cache_concurrency.py](tests/core/test_enum_cache_concurrency.py): `test_compile_enum_shares_one_object_after_contended_miss` (added definition); `test_compile_type_shares_one_object_after_contended_miss` (added definition); `test_compile_schema_keeps_reset_and_build_in_one_transaction` (added definition); `test_native_choices_reuse_one_object_after_contended_miss` (added definition); `test_native_choices_reject_incompatible_concurrent_definition` (added definition); `test_native_choices_keep_serial_ambiguity_and_registry_isolation` (added definition).


### L-M4 — Global list-type registry creation used check-then-act without synchronization

**Status:** partial

**Original problem:** Global list-type registry creation used check-then-act without synchronization. [original audit](auditoria-django-graphex-4.0.0.md), lines 204. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 270; [task T14/T14i](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** two threads build same list type. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"threads": 2, "list_type": "same output leaf"}
```

**Before (illustrative):**
```json
{"registrations": 2}
```

**After (observed/current):**
```json
{"registrations": 1}
```

**How the result was reached:**
1. Cold list-type registration uses synchronization instead of unsafely checking then inserting global registry state. The proof is direct schema construction, not every server interleaving.
2. `13b2e6b4cdfd7489210267a5f6b5e3f35ec49ac4`: source changes in [django_graphex/registry.py](django_graphex/registry.py), [django_graphex/types.py](django_graphex/types.py).
3. Scope check: A direct GraphQLSchema list-creation race was corrected; public exposure was not established.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/core/test_registry_creation_concurrency.py](tests/core/test_registry_creation_concurrency.py), `test_global_registry_concurrent_cold_calls_share_one_instance` (short source excerpt, not a reconstructed failure):
   ```python
   assert registry_module.get_global_registry() is first_result
   ```
   - [tests/core/test_registry_creation_concurrency.py](tests/core/test_registry_creation_concurrency.py): `test_global_registry_concurrent_cold_calls_share_one_instance` (added definition); `test_global_registry_failed_construction_retries_and_reset_isolated` (added definition); `test_concurrent_list_misses_share_class_graphql_object_and_cache` (added definition); `test_explicit_list_registration_keeps_last_registration_wins` (added definition); `test_list_creation_is_scoped_to_each_model_and_registry` (added definition).


### L-S1 — SSE lacked optional heartbeat and per-account concurrent-stream controls

**Status:** partial

**Original problem:** SSE lacked optional heartbeat and per-account concurrent-stream controls; broader distributed guarantees were separate. [original audit](auditoria-django-graphex-4.0.0.md), lines 207. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 271; [task T08/R01e](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** authenticated account opens sixth SSE stream. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```http
GET /subscriptions/sse?query=subscription%20%7B...%7D
Accept: text/event-stream
```

**Before (illustrative):**
```json
{"admission": "no account cap"}
```

**After (observed/current):**
```json
{"http_status": 429, "source_started": false}
```

**How the result was reached:**
1. Optional SSE heartbeat and per-account leases default OFF. The accepted implementation uses Redis Lua for atomic grant/refusal in the single-instance witness and releases on stream teardown; partition/failover and a hard wall-clock deadline remain unproved.
2. `7ec2264c763859cd840e1475e8f4cec9a47ed8fc`: source changes in [django_graphex/settings.py](django_graphex/settings.py), [django_graphex/subscriptions/transports/_sse_lease.py](django_graphex/subscriptions/transports/_sse_lease.py), [django_graphex/subscriptions/transports/sse.py](django_graphex/subscriptions/transports/sse.py).
3. Scope check: Approved, independently opt-in SSE heartbeat and authenticated-account Redis lease cap are implemented with defaults off (15 seconds/five streams). Contract tests cover heartbeat, sixth-request HTTP 429, backend HTTP 503, cleanup and expired renewal. An explicit ten-case suite against a single Redis instance (Redis 8.10.2/redis-py 8.1.0) executes real Lua and eight processes sharing one account, with five grants and three refusals, plus public SSE and lifecycle checks. Failover and partition behavior are not proved; Redis failover is not a strict global-count guarantee.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [integration/live_redis/test_sse_live_redis.py](integration/live_redis/test_sse_live_redis.py), `test_real_lua_cross_process_cap` (short source excerpt, not a reconstructed failure):
   ```python
   assert {entry["key"] for entry in results} == {key}
   ```
   - [integration/live_redis/test_sse_live_redis.py](integration/live_redis/test_sse_live_redis.py): `test_real_lua_cross_process_cap` (added definition); `test_real_lua_ownership_expiry_and_independent_accounts` (added definition); `test_real_lua_unknown_acquire_reply_releases_committed_token` (added definition); `test_real_lua_double_cancellation_waits_for_commit_then_releases` (added definition); `test_real_lua_crashed_owner_expires_without_release` (added definition); `test_public_sse_live_cap_and_cleanup` (added definition); `test_public_sse_live_backend_unavailable_is_503_before_source` (added definition); `test_public_sse_live_source_start_failure_releases_lease` (added definition); `test_public_sse_live_normal_source_completion_releases_lease` (added definition); `test_public_sse_live_midstream_loss_is_generic_and_closes` (added definition).
   - [tests/subscriptions/test_sse_lease_lifecycle.py](tests/subscriptions/test_sse_lease_lifecycle.py): `test_expired_initial_lease_never_delivers_application_data` (added definition); `test_ready_events_still_renew_overdue_lease` (added definition); `test_repeated_cancellation_settles_admission_before_release` (added definition); `test_backend_error_after_start_closes_source_before_503` (added definition); `test_cancelled_startup_revalidation_closes_source_and_lease` (added definition); `test_consumer_delay_rechecks_before_next_source_read` (added definition); `test_overdue_ready_result_is_withheld_on_backend_error` (added definition).
   - [tests/subscriptions/test_sse_controls.py](tests/subscriptions/test_sse_controls.py): `test_idle_heartbeat_keeps_one_source_alive` (added definition); `test_heartbeat_remains_off_by_default` (added definition); `test_second_account_stream_is_rejected_before_source` (added definition); `test_backend_failure_is_pre_stream_503` (added definition); `test_sixth_stream_is_429_and_existing_five_survive` (added definition); `test_anonymous_request_does_not_access_account_lease_backend` (added definition); `test_source_start_failure_releases_reserved_slot` (added definition); `test_renewal_failure_finishes_stream_without_backend_secret` (added definition); `test_expired_lease_cannot_be_resurrected` (added definition); `test_cancelled_unknown_admission_cleans_its_token` (added definition); `test_event_heartbeat_and_natural_completion_share_one_source` (added definition); `test_healthy_lease_renews_without_heartbeat` (added definition); `test_subscribe_result_releases_unused_lease` (added definition); `test_missing_persistent_account_id_is_refused` (added definition); `test_failed_release_is_bounded_by_expiry` (added definition); `test_cancelled_backend_failure_still_propagates_cancellation` (added definition); `test_controls_ship_disabled_with_independent_values` (added definition); `test_invalid_control_settings_fail_explicitly` (added definition).


### L-S2 — connection_init could not use a token-authentication hook before WebSocket acknowledgment

**Status:** bounded-fixed

**Original problem:** connection_init could not use a token-authentication hook before WebSocket acknowledgment. [original audit](auditoria-django-graphex-4.0.0.md), lines 208. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 272; [task T08/R01d](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** connection_init token callback returns user. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"connection_init": {"token": "valid"}, "callback_user": "Alice"}
```

**Before (illustrative):**
```json
{"ack_user": "anonymous"}
```

**After (observed/current):**
```json
{"ack_user": "Alice", "schema_user": "Alice"}
```

**How the result was reached:**
1. An optional asynchronous on_connect runs before WebSocket ACK and may set the effective user or deny with close 4403. Session fallback is not used after explicit denial; no universal JWT backend was added.
2. `98956fa142bca0d6b78a7402ff626270d4295afc`: source changes in [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Scope check: An optional async on_connect callback can authenticate the connection_init payload before ACK and replace the socket user for schema and permission checks. Missing, anonymous, or invalid credentials close generically without session fallback; no hook preserves the former scope-user behavior. JWT verification, session persistence, HTTP/SSE authentication, and mid-socket refresh remain outside this fix.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_ws_on_connect.py](tests/subscriptions/test_ws_on_connect.py), `test_hook_receives_normalized_payload_and_blocks_ack` (short source excerpt, not a reconstructed failure):
   ```python
   assert seen == [(communicator.scope, payload or {})]
   ```
   - [tests/subscriptions/test_ws_on_connect.py](tests/subscriptions/test_ws_on_connect.py): `test_default_ignores_nonmapping_init_payloads` (added definition); `test_hook_receives_normalized_payload_and_blocks_ack` (added definition); `test_hook_identity_replaces_session_for_provider_and_permissions` (added definition); `test_hook_denial_has_no_session_fallback_or_secret_output` (added definition); `test_hook_rejects_nonmapping_payload_without_invocation` (added definition); `test_pending_hook_retains_protocol_errors` (added definition); `test_pending_hook_times_out_and_cancels_without_late_ack` (added definition); `test_disconnect_cancels_pending_hook` (added definition); `test_late_callback_result_cannot_replace_identity_or_ack` (added definition); `test_documented_on_connect_callback_is_typed_and_explained` (added definition).


### L-S3 — WebSocket subprotocol was accepted even if the client had not offered the required protocol

**Status:** bounded-fixed

**Original problem:** WebSocket subprotocol was accepted even if the client had not offered the required protocol. [original audit](auditoria-django-graphex-4.0.0.md), lines 209. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 273; [task T08/R01c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** client offers only wrong protocol. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"client_subprotocols": ["wrong-protocol"]}
```

**Before (illustrative):**
```json
{"accepted": true}
```

**After (observed/current):**
```json
{"accepted": false, "registry_additions": 0}
```

**How the result was reached:**
1. The WS server validates that the required subprotocol appears in the offered list before accept. Missing, empty or wrong-only offers close; the exact protocol among alternatives is accepted.
2. `ef598a7d3dca3b76974bdd0829991db895d984c1`: source changes in [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Scope check: The approved WebSocket guard rejects a missing, empty, or wrong-only subprotocol offer before acceptance; the required offer may appear among alternatives. The server logs the required protocol. Pre-accept rejection is normally wire HTTP 403, not a guaranteed browser-visible close code or GraphQL error. Broader subscription policies remain open.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_ws_subprotocol.py](tests/subscriptions/test_ws_subprotocol.py), `test_unoffered_subprotocol_is_rejected_before_accept` (short source excerpt, not a reconstructed failure):
   ```python
   assert ws.get_live_consumer(communicator.scope) is None
   ```
   - [tests/subscriptions/test_ws_subprotocol.py](tests/subscriptions/test_ws_subprotocol.py): `test_unoffered_subprotocol_is_rejected_before_accept` (added definition); `test_required_subprotocol_is_accepted_among_alternatives` (added definition).


### L-S4 — Server complete could be emitted before releasing a WebSocket operation ID, making immediate reuse appear…

**Status:** bounded-fixed

**Original problem:** Server complete could be emitted before releasing a WebSocket operation ID, making immediate reuse appear duplicate. [original audit](auditoria-django-graphex-4.0.0.md), lines 210. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 274; [task T08/R01a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** complete frame then same operation ID. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"operation_id": "op1", "frames": ["complete", "subscribe op1"]}
```

**Before (illustrative):**
```json
{"second_subscribe": "duplicate / 4409"}
```

**After (observed/current):**
```json
{"second_subscribe": "admitted after cleanup"}
```

**How the result was reached:**
1. The WS operation ID is removed from the active slot table before emitting server complete, allowing an immediate next subscribe with the same ID. Other lifecycle races remain distinct.
2. `9268da4033901e5a76daf6a3c84ac34c860dae0f`: source changes in [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Scope check: WS operation cleanup and slot release precede the server complete frame, so immediate same-ID reuse is not mistaken for a duplicate; other lifecycle cases remain.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/subscriptions/test_ws_completion_reuse.py](tests/subscriptions/test_ws_completion_reuse.py), `test_complete_waits_for_teardown_then_reuses_same_id` (short source excerpt, not a reconstructed failure):
   ```python
   assert second.source.joined_groups
   ```
   - [tests/subscriptions/test_ws_completion_reuse.py](tests/subscriptions/test_ws_completion_reuse.py): `test_complete_waits_for_teardown_then_reuses_same_id` (added definition); `test_teardown_error_keeps_existing_terminal_frame_sequence` (added definition).


### Q1 — The audit mixed an isolated graphql-core 3.3 run with the checkout's unsupported ambient 3.2.13 environment and…

**Status:** contract

**Original problem:** The audit mixed an isolated graphql-core 3.3 run with the checkout's unsupported ambient 3.2.13 environment and attributed failures to local tooling. [original audit](auditoria-django-graphex-4.0.0.md), lines 15–18, 217. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 275; [task T01/T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** ambient graphql-core 3.2.13; project requires 3.3. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"ambient result treated as supported proof"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The dependency declaration, lock, tox and CI specify graphql-core 3.3; the checkout's ambient 3.2.13 is unsupported and was not reinstalled. Environment mismatch is not a tox configuration fix.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: pyproject/uv/tox/CI require graphql-core 3.3 consistently; root 3.2.13 is stale unsupported env, not refreshed; no tox config mismatch.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/test_tox_dependency_contract.py](tests/test_tox_dependency_contract.py), `test_tox_tool_ranges_match_declared_dev_compatibility` (short source excerpt, not a reconstructed failure):
   ```python
   assert TOX_TOOL_NAMES <= seen
   ```
   - [tests/test_tox_dependency_contract.py](tests/test_tox_dependency_contract.py): `test_tox_tool_ranges_match_declared_dev_compatibility` (historical locator; not in the changed-path inventory); `test_diff_cover_has_a_deliberate_dev_range` (historical locator; not in the changed-path inventory); `test_security_gate_audits_the_locked_runtime_dependencies` (historical locator; not in the changed-path inventory); `test_security_gate_runtime_target_is_documented` (historical locator; not in the changed-path inventory); `test_ruff_range_stays_with_formatter_compatible_minor` (historical locator; not in the changed-path inventory).


### Q2 — A benchmark provenance reader globbed arbitrary JSON and could select stale/noncanonical results

**Status:** bounded-fixed

**Original problem:** A benchmark provenance reader globbed arbitrary JSON and could select stale/noncanonical results. [original audit](auditoria-django-graphex-4.0.0.md), lines 218. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 276; [task T01/T16a](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** benchmark directory contains extra JSON. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"result_dir": ["case1.json", "unrelated.json"], "canonical_expected_count": 8}
```

**Before (illustrative):**
```json
{"reader": "glob includes unrelated.json"}
```

**After (observed/current):**
```json
{"reader": "exact eight canonical names"}
```

**How the result was reached:**
1. The benchmark provenance reader selects the eight canonical JSON result names and rejects missing or malformed canonical files, rather than globbing arbitrary stale JSON. No benchmark timings were regenerated.
2. `e31333468774344e176031d1241e25c2d1642dd3`: source changes in [benchmarks/run_publish.py](benchmarks/run_publish.py).
3. Scope check: The benchmark reader selects eight canonical result files deterministically; missing or invalid results still fail, and no timing was regenerated.
4. Actual test locators, with base-to-snapshot definition provenance:
   A concrete current assertion from [tests/benchmarks/test_core33_results.py](tests/benchmarks/test_core33_results.py), `test_core33_bundle_has_exactly_eight_portable_artifacts` (short source excerpt, not a reconstructed failure):
   ```python
   assert {path.name for path in RESULTS.iterdir()} == set(FILENAMES.values())
   ```
   - [tests/benchmarks/test_canonical_provenance.py](tests/benchmarks/test_canonical_provenance.py): `test_copy_canonical_fixture_ignores_diagnostics` (added definition); `test_missing_canonical_file_still_fails_with_diagnostics` (added definition); `test_validator_ignores_unrelated_diagnostic_json` (added definition).
   - [tests/benchmarks/test_core33_results.py](tests/benchmarks/test_core33_results.py): `test_core33_bundle_has_exactly_eight_portable_artifacts` (historical locator; not in the changed-path inventory); `test_core33_artifact_matches_accepted_portable_contract` (historical locator; not in the changed-path inventory).


### Q3 — Direct-view tests owned temporary multipart/ASGI spool objects that were not closed on every exit

**Status:** bounded-fixed

**Original problem:** Direct-view tests owned temporary multipart/ASGI spool objects that were not closed on every exit. [original audit](auditoria-django-graphex-4.0.0.md), lines 219. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 277; [task T16/R09c](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** direct-view test exits on exception. The paired values below are deliberately reduced illustrations, not newly executed output:

**Concrete reduced request/setup:**
```json
{"test": "direct view", "exception": "during assertion", "temporary_file": "owned by test"}
```

**Before (illustrative):**
```json
{"file_closed": false}
```

**After (observed/current):**
```json
{"file_closed": true, "mechanism": "finally cleanup"}
```

**How the result was reached:**
1. Direct-view upload/ASGI tests now close their own temporary spool resources on success and exception paths. The observed warning was test ownership, not demonstrated production leakage.
2. The accepted outcome is recorded, but no unique causal production commit was established for this entire composite row; do not infer one from a changed test file.
   The test-resource ownership correction is test-only commit `e1f29e9430725efa2d1f240140b5ee5ab6ae4882`; it does not establish a production leak.
3. Scope check: Direct-view tests now close their own multipart temporary upload and ASGI body spool, including exception exits; no ResourceWarning was observed and no production leak is inferred.
4. Actual test locators, with base-to-snapshot definition provenance:
   - [tests/test_views_multipart_body_bound.py](tests/test_views_multipart_body_bound.py): `test_asgi_chunked_multipart_over_the_cap_is_refused` (AST-modified definition); `test_wsgi_undeclared_multipart_is_refused` (unchanged definition); `test_declared_multipart_under_the_cap_still_runs` (unchanged definition); `test_asgi_spoofed_low_content_length_is_refused` (unchanged definition); `test_wsgi_spoofed_low_content_length_never_reaches_the_view` (unchanged definition); `test_asgi_undeclared_multipart_under_the_cap_is_not_a_length_refusal` (unchanged definition); `test_undeclared_multipart_is_untouched_when_the_guard_is_off` (unchanged definition).


### Q4 — The proposed missing regression matrix repeated behavior IDs already tracked

**Status:** recommendation

**Original problem:** The proposed missing regression matrix repeated behavior IDs already tracked; it was not a distinct runtime defect. [original audit](auditoria-django-graphex-4.0.0.md), lines 221–233. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 278; [task T03–T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** audit lists more tests for C/A findings. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"interpreted as new independent defects"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The proposed regression matrix was mapped onto existing behavior IDs; no independent runtime patch follows from a coverage heading. Specific added tests are attributed in their corresponding case chapters.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: regression matrix duplicates existing IDs.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### Q5 — Historical test filenames were criticized for poor feature discoverability, not failing behavior

**Status:** recommendation

**Original problem:** Historical test filenames were criticized for poor feature discoverability, not failing behavior. [original audit](auditoria-django-graphex-4.0.0.md), lines 235. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 279; [task T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** history-named tests still run. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"name considered a defect"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. No historical test file was renamed merely to improve discoverability, because renaming can break collection references without changing behavior. Organization remains a separate review task.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: historical test naming suggestion only.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### Q6 — Large modules were proposed for splitting, with no demonstrated behavioral failure from file length alone

**Status:** recommendation

**Original problem:** Large modules were proposed for splitting, with no demonstrated behavioral failure from file length alone. [original audit](auditoria-django-graphex-4.0.0.md), lines 238. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 280; [task T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** large types.py/utils.py/views.py. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"assume split required for correctness"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Module length alone did not justify broad extraction across compatibility-sensitive call paths. No mass split was performed without a behavior-preserving scope and review proof.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: module split suggestion, no authority.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### Q7 — Repeated walkers, mutation paths and view response paths were listed as refactor candidates

**Status:** recommendation

**Original problem:** Repeated walkers, mutation paths and view response paths were listed as refactor candidates. [original audit](auditoria-django-graphex-4.0.0.md), lines 239–242. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 281; [task T02/T05/T10/T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** repeated implementation patterns. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"delete/merge as obvious dead duplication"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The repeated-walker and view/mutation candidates were tied to specific C2, A9, A1 and L-C3 repairs instead of merging all duplicates. Their remaining shared abstractions require caller analysis.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: cross-reference plan only; verify before refactor.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### Q8 — The audit listed allegedly dead factories, compiler and mutation symbols without complete caller proof

**Status:** negative-limited

**Original problem:** The audit listed allegedly dead factories, compiler and mutation symbols without complete caller proof. [original audit](auditoria-django-graphex-4.0.0.md), lines 243–248. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 282; [task T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** MUTATION_ERRORS_FLAG marked dead. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"remove without caller check"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The alleged dead MUTATION_ERRORS_FLAG still has a live GraphQLView rollback path. No symbol was deleted on a speculative reference list; other removals need call-site and compatibility proof.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: MUTATION_ERRORS_FLAG is live; other alleged dead symbols require qualified caller and compatibility review, not deletion.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### Q9 — Graphene-era names/comments were called obsolete despite possible compatibility surface

**Status:** recommendation

**Original problem:** Graphene-era names/comments were called obsolete despite possible compatibility surface. [original audit](auditoria-django-graphex-4.0.0.md), lines 249. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 283; [task T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** graphene_cls naming remains. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"assume rename is mandatory fix"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Historical Graphene-era names remain because compatibility surfaces cannot be inferred dead from naming alone. Comment cleanup was not promoted to an API-breaking rename.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: historical Graphene names/comments only.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### Q10 — Deriving GraphQL non-null from Django null=False was proposed as an opt-in SDL redesign

**Status:** decision-deferred

**Original problem:** Deriving GraphQL non-null from Django null=False was proposed as an opt-in SDL redesign. [original audit](auditoria-django-graphex-4.0.0.md), lines 250. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 284; [task T16](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** Django field null=False. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"GraphQL output still nullable"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. The SDL still does not automatically derive GraphQLNonNull from Django null=False. A broad non-null projection can change error propagation, so it remains an opt-in design decision.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: deriving non-null from null=False changes SDL.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### P1 — The release-priority action list repeated earlier findings and suggested environment/release steps without…

**Status:** recommendation

**Original problem:** The release-priority action list repeated earlier findings and suggested environment/release steps without granting authority. [original audit](auditoria-django-graphex-4.0.0.md), lines 256–265. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 285; [task T01–T17](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** priority plan repeats C1/C2/A1 etc.. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"reat each plan item as new finding"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Priority prose was cross-referenced to existing IDs but did not authorize uv sync, release/publish, default changes or another bug count. Delivery remained outside the remediation.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: duplicate priority plan, not new finding/authority.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### N1 — The audit reassuringly claimed permission caches were uniquely isolated by user, overlooking effective-signature…

**Status:** negative-limited

**Original problem:** The audit reassuringly claimed permission caches were uniquely isolated by user, overlooking effective-signature sharing. [original audit](auditoria-django-graphex-4.0.0.md), lines 269. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 286; [task T17](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** two users share effective permissions. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"audit claims never share cache entry"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Permission schema caching is keyed by effective permission signature rather than a uniquely isolated object per user. The negative universal claim is narrowed; response-cache isolation was not proved here.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: The schema cache uses an effective permission signature, not a unique user key; this is not a universal cross-user response-cache guarantee.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### N2 — The report's fail-closed permission and scoped mutation assertion was broader than its bounded checks

**Status:** negative-limited

**Original problem:** The report's fail-closed permission and scoped mutation assertion was broader than its bounded checks. [original audit](auditoria-django-graphex-4.0.0.md), lines 270. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 287; [task T17](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** anonymous/falsy permission path. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"assume all paths proven fail-closed"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Covered permission and scoped mutation tests do not establish every anonymous/falsy principal or arbitrary update/delete chain. No global fail-closed guarantee was asserted from that subset.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: anonymous/falsy permission and scoped update/delete chain not universally runtime-proved.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### N3 — One nested introspection rejection was extrapolated to a universal introspection DoS guarantee

**Status:** negative-limited

**Original problem:** One nested introspection rejection was extrapolated to a universal introspection DoS guarantee. [original audit](auditoria-django-graphex-4.0.0.md), lines 271. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 288; [task T17](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** nested introspection probe. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"assume no DoS possible"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. One nested introspection rejection came from graphql-core validation; the library's MAX_QUERY_DEPTH is a separate bound. A universal introspection DoS claim needs wider threat testing.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: Core MaxIntrospectionDepthRule rejected one bounded nested introspection query; custom MAX_QUERY_DEPTH is a different guard, and no universal DoS proof follows.
4. Actual test locators, with base-to-snapshot definition provenance:
   - [tests/test_depth_limit.py](tests/test_depth_limit.py): `test_within_limit_passes` (historical locator; not in the changed-path inventory); `test_exceeding_per_type_limit_errors` (historical locator; not in the changed-path inventory); `test_scalars_do_not_count` (historical locator; not in the changed-path inventory); `test_max_depth_zero_blocks_any_nesting` (historical locator; not in the changed-path inventory); `test_fragment_spread_does_not_bypass` (historical locator; not in the changed-path inventory); `test_inline_fragment_is_counted` (historical locator; not in the changed-path inventory); `test_most_restrictive_constraint_wins` (historical locator; not in the changed-path inventory); `test_global_default_from_setting` (historical locator; not in the changed-path inventory); `test_no_limit_configured_is_noop` (historical locator; not in the changed-path inventory); `test_object_type_stores_max_depth` (historical locator; not in the changed-path inventory); `test_list_type_stores_max_depth` (historical locator; not in the changed-path inventory); `test_serializer_type_forwards_max_depth_to_output_type` (historical locator; not in the changed-path inventory); `test_view_includes_depth_rule_with_standard_rules` (historical locator; not in the changed-path inventory); `test_each_operation_type_is_named_in_its_own_refusal` (historical locator; not in the changed-path inventory).


### N4 — The assertion that every utils cache is request-scoped ignored process-global Django class metadata for GFK types

**Status:** contract

**Original problem:** The assertion that every utils cache is request-scoped ignored process-global Django class metadata for GFK types. [original audit](auditoria-django-graphex-4.0.0.md), lines 272. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 289; [task T17](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** GFK target type lookup. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"audit says request-local cache"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. GenericForeignKey type metadata is cached at process/class scope, not per request. The all-caches-request-local statement was corrected without rewriting unrelated caches.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: The GFK field-type cache is process-global Django class metadata; saying all caches are request-scoped is inaccurate.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### N5 — A bounded regex probe cannot establish that format_graphql_error is universally safe for every input

**Status:** negative-limited

**Original problem:** A bounded regex probe cannot establish that format_graphql_error is universally safe for every input. [original audit](auditoria-django-graphex-4.0.0.md), lines 273. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 290; [task T17](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** one format_graphql_error input probe. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"assume all hostile strings safe"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. A finite format_graphql_error regex probe cannot prove safety for arbitrary strings and backtracking shapes. The exercised case is retained without global assurance.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: regex safety is bounded only; no universal conclusion.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


### N6 — A local lint/type/test result was generalized to CI and historical ignored files without preserved original…

**Status:** negative-limited

**Original problem:** A local lint/type/test result was generalized to CI and historical ignored files without preserved original preimages. [original audit](auditoria-django-graphex-4.0.0.md), lines 274. The [disposition guide](docs/audit-4.0.0.md) indexes this claim at line 291; [task T17/R09a/R09b](odd/tasks/audit-400-remediation.md) records the work boundary.

**Example context:** local strict scan after fixes. The paired values below are deliberately reduced illustrations, not newly executed output:

**Before (illustrative):**
```json
"claim CI entirely clean"
```

**After (observed/current):** No implementation was made for this claim.

**How the result was reached:**
1. Local strict lint/type/test exploration ended clean after tracked and historically ignored findings were addressed. Missing original preimages and CI runs prevent a universal historical claim.
2. No production change was accepted for this claim; the existing behavior, contradicted premise, or proposed policy is described rather than presented as a fix.
3. Scope check: The current local strict scan reports zero after correction of 23 tracked-test findings and seven ignored-profile DOC002 findings; original ignored preimages remain unknown, the ignored scripts are absent from a clean checkout, and no CI-clean verdict is proved.
4. The frozen case crosswalk gives no primary named test locator. That is a provenance gap, not proof that no tests exist.


## What was discarded, narrowed, or deliberately deferred

A discarded **premise** is not the same thing as a rejected **policy** or an untested **subcase**. No-change decisions below preserve the current contract; they must not be counted as silent fixes or automatically called false positives.

1. **Contradicted or overstated premise:** `L-E3` SITE-B publicly showed its optimizer hook ran once and returned only visible rows, so the exact alleged hook-loss path did not reproduce; other branches are unproved. `L-C8` expected `page:-1` to mean a short positive final page, but the documented contract is a fixed-size tail window. `N4` “all caches request-scoped” was inaccurate because GFK class metadata is process-global. `Q8` cannot delete `MUTATION_ERRORS_FLAG`: it has a live view path. `L-C11` named `@title`, which is not registered; `@title_case` and `@truncate` were not shown defective by that claim.
2. **Documented contract, not general bug fix:** `M-D5` distinguishes raw JSONField string input from the intentionally decoding `JSONString` scalar; `M-U4` distinguishes automatic commit-time signals from immediate manual broadcasts and absent bulk signals; `L-C6` distinguishes cache miss, hit, and cookie-bearing bypass; `L-C13` separates native naive DateTime parsing from `@date` active-zone formatting; `M-S3` explains an opt-in introspection middleware. These decisions do not imply a changed default.
3. **Unapproved incompatible policy:** No global `strict_scope` or system check (`SD6`); no all-mutation `full_clean()`/upsert semantics (`A10`); no native `ok:false` rollback/cross-DB transaction (`A1`); no universal stale-row `update_fields` (`M-D1`); no empty-Boolean identity redesign (`M-F3`); no automatic GraphQL non-null from Django `null=False` (`Q10`); no dynamic-registry lifecycle/eviction policy (`L-M1`). Each needs a separate compatibility/security decision. Declining a policy is not a finding that the original risk was imaginary.
4. **Recommendation rather than defect:** `Q4–Q7`, `Q9` and `P1` concern coverage, organization, refactoring and priority. They do not authorize renaming compatibility symbols, large-file splits, `uv sync`, release activity, or extra runtime changes.

## Additional discoveries outside the original 100-ID count

- **R09d — production output-slot side effect:** a rejected generated mutation could leave registry output visible after declaration order. The distinct bounded production correction is commit `b84d359` (full identity available in local Git); it is not merely the original `A4` registry conflict. It should be explained as a new production issue, not as proof of a global registry redesign.
- **T16g — test-fixture leak, not product defect:** the default cached schema pair leaked between isolated tests and reproduced on the audit base with seed `1823552487`. Commit `3cefed7131c6` restored the cached pair after scoped tests. This matters to proof reliability but is not a new original audit bug.
- **L-S1 F1–F3 — interim candidate versus final accepted state:** an earlier handoff was uncommitted then; source commit `7ec2264c763859cd840e1475e8f4cec9a47ed8fc` and tracking commit `1d26aa6478e2dd7e39585c349a466a34f41c1175` later included the correction in the frozen snapshot. The historical single-instance live Redis suite passed **10 tests**, exercising Lua and **eight processes** for one account (**five grants, three refusals**). Seven lifecycle test definitions represent eight pytest cases because one test is parameterized twice. The controls file has 18 definitions and the Playground added its opt-in-off default test. No HA failover/partition/global-count or hard total-deadline guarantee was established, and this report did not rerun Redis.
- **R08m Float-set F1 — field-local correction:** commit `aeb74b8` fixed an observed overflow edge in the exact Float-set path; it does not authorize global Float serialization or non-finite policy changes.
- **Default/premise corrections:** `M-S2` must acknowledge the already accepted default page size of 100; `Q1` must distinguish stale ambient graphql-core 3.2.13 from supported 3.3.0. These are corrected descriptions, not new product bugs. Harness failures and intermediate PARTIAL outcomes are preserved as proof qualifications, not inflated into library findings.

### R09d: rejected declaration must not reserve an output slot

Before: a generated mutation requested an invalid operation, but its factory had already created and registered an output type. A later valid public output for the same model could then conflict with that stale side effect. Commit `b84d359` moved output lookup/creation **after** operation validation in `django_graphex/mutation.py`; rejected declarations now leave the registry slot unused. `tests/core/test_invalid_mutation_registry_side_effect.py` records this declaration boundary. This is a production ordering defect, not a global redesign of Registry or the separate A4 conflict guard.

```json
{"request": "generate mutation with unknown operation", "before": {"error": true, "output_registered": true}, "current": {"error": true, "output_registered": false}}
```

### T16g: test fixture, not library behavior

The isolated test helper replaced the global Registry and output registry but left `_default_schema_registries` cached. On a later test, that cached pair could still point to the temporary objects; the seed `1823552487` reproduced this on the audit base. Commit `3cefed7` clears the cached pair on entering `isolated_default_pair()` and restores its exact previous object in `finally`, including exception and nested-scope paths. `tests/core/test_schema_isolation.py` covers these cases. No product-code fix or new audit bug is implied.

```json
{"setup": "two isolated tests share process", "before": {"cached_pair": "temporary prior-test pair"}, "current": {"cached_pair": "exact pre-scope pair restored"}}
```

### Follow-up F1–F3 (L-S1): three candidate-introduced lease races corrected before acceptance

F1: a lease acquired before a slow source start could expire before the first HTTP 200/body frame, yet the candidate could expose application data. The accepted path renews after source start and again before the first body read; on lost ownership it closes the source and lease, returning a pre-stream 503 or a safe terminal error after 200. `test_expired_initial_lease_never_delivers_application_data` has source-start and before-body parameters.

F2: a stream with continuously ready delivery results could skip timeout-only lease renewal and emit after expiry. The loop now checks the renewal deadline before waiting and after each wait, even when a result is already ready; a failed renewal withholds that result. `test_ready_events_still_renew_overdue_lease` and `test_overdue_ready_result_is_withheld_on_backend_error` cover the branch.

F3: repeated cancellation during an in-flight Redis/Lua acquire could release before admission committed and orphan a token. `_acquire` waits for the underlying admission result to settle before releasing its owned token; `test_repeated_cancellation_settles_admission_before_release` proves release follows commit. These are accepted candidate corrections, not missing final Redis work. Tests reside in `tests/subscriptions/test_sse_lease_lifecycle.py`; the separate ten-case real Redis proof is historical and single-instance only.

```json
{"lease": {"backend": "empty fake Redis", "capacity": 1, "admission": "paused before Lua acquire commits", "cancellations": 2}, "before": {"release_before_acquire_commit": true, "orphan_slot_possible": true}, "current": {"acquire_commits_before_release": true, "remaining_slots": 0}}
```

### R08m F1: overflowing Float-set literal is field-local

Native `GraphQLFloat` variable coercion rejected non-finite values, but its literal path could turn `1e999` into infinity. For exact `set[float]`/`typing.Set[float]` inputs, commit `aeb74b8` records surviving field aliases and checks **supplied** list members with `math.isfinite` before resolver/factory work; a supplied overflow is a field error. Omitted malformed legacy fixed defaults/factories keep their previous identity/behavior. `tests/core/test_float_set_input.py::test_literal_overflow_rejects_even_with_malformed_legacy_defaults` tests this contrast. No global Float scalar or all non-finite policy changed.

```graphql
mutation { echo(payload: {amounts: 1e999}) { result } }
```
Current result: a GraphQL field error before `echo` resolves; no finite set is silently manufactured.

## Pending work and proof limits

Fifteen principal T03–T17 work areas are still open. The primary pending/limited rows below are **not** interchangeable with bugs or work items. New public defaults, global security guarantees, cross-database semantics, distributed SSE guarantees and release decisions need human authorization. The table gives the current constrained next question, not automatic approval.

| Status | IDs and bounded reason |
|---|---|
| `partial` | `A1`, `A2`, `A10`, `A13`, `SD1`, `SD2`, `M-S2`, `M-D1`, `M-D2`, `M-D3`, `M-D4`, `M-D6`, `M-F3`, `M-H4`, `M-U1`, `M-U2`, `M-U3`, `M-U6`, `L-C12`, `L-E3`, `L-E4`, `L-M2`, `L-M3`, `L-M4`, `L-S1` |
| `decision-deferred` | `L-M1`, `Q10` |
| `negative-limited` | `Q8`, `N1`, `N2`, `N3`, `N5`, `N6` |

The selected unresolved themes are retained AST/cache bytes and aggregate memory (`A2`), native `ok:false`/cross-DB/lost-update semantics (`A1`, `M-D1`, `M-D2`), custom relation/scope behavior (`SD1`, `SD2`, `SD6`, `L-E3`), empty Boolean identities (`M-F3`), distributed SSE (`L-S1`), dynamic registries (`L-M1`), broader Float/JSON/DateTime annotation contracts (`M-D4`, `M-D6`, `M-U3`, `M-U6`, `M-D10`), and universal negative/security claims (`N1–N6`). Even where a default, test, or bounded slice changed, its parent question remains separately reviewable.

### Evidence limits that should travel with this report

- Historical run counts and coverage above belong to frozen commit `8d93483`, not to a fresh docs run or a release gate. The 10 Redis passes belong to an earlier accepted L-S1 source commit; no Redis was run while drafting this retrospective. A single-instance proof does not establish failover/partition behavior.
- The changed-test appendix is an AST comparison of base and snapshot definitions, not a collected pytest count or proof each named test passed in every historical run. Removed definitions are historical deltas, not current callable tests. The 21 index rows without a primary test locator were checked for specific accepted closeouts where possible (`L-S1`, `M-U6`); absence of a locator is not a finding of no coverage.
- The earlier evidence index contains deep source-diff narratives for `C1`, `C2`, and `A5`; this report also cross-checked ancestry and production paths for the additional case-linked implementation commits cited in individual chapters, then checked their named tests. A matching test-file co-change alone is never a claim that every original subcase was fixed. Cases without a unique causal commit say so explicitly.
- No upstream GitHub URL, external private proof file, benchmark timing, CI result, runtime API approval, PR, push, tag or publication is inferred. This companion is outside the published site. The original untracked report and existing task ledger were not edited.


## Appendix A: commit chronology

All 167 source/test-bearing commits in ancestry order from feature base to frozen snapshot; commit subjects and technical paths remain verbatim. These are historical commits, not changes made while writing this report. Co-change does not prove causation. The final docs-only closure commit is stated separately below.

| Commit | Local time (-04:00) | Subject and changed-path evidence |
|---|---|---|
| `e31333468774344e176031d1241e25c2d1642dd3` | `2026-10-13T19:18:30-04:00` | fix(benchmarks): validate only canonical results; production: none; tests: tests/benchmarks/test_canonical_provenance.py. |
| `2943f4544fe0c56064895a35b8606effe50013be` | `2026-10-13T19:50:53-04:00` | fix(validation): reject cyclic fragment graphs before expansion; production: django_graphex/_fragment_cycles.py, django_graphex/cost.py, django_graphex/validation.py; tests: tests/test_cost_edges.py, tests/test_fragment_cycles.py, tests/test_fragment_fanout.py. |
| `c57485594f83244f0dd4fcfdc71165cfb7d4da02` | `2026-10-13T20:03:58-04:00` | docs(audit): complete C3 test docstring contract; production: none; tests: tests/test_fragment_cycles.py. |
| `92b1358f31a2973abe7a817b820d54775a9067a6` | `2026-10-13T20:26:38-04:00` | fix(optimizer): bound repeated fragment planning; production: django_graphex/utils.py; tests: tests/test_optimizer_fragment_fanout.py. |
| `7bec957180edcf138d50256777a9e1bfb196f2b5` | `2026-10-13T20:45:23-04:00` | fix(optimizer): replay ordered fragment effects; production: django_graphex/utils.py; tests: tests/test_optimizer_fragment_fanout.py. |
| `bd45a6546cbb70a3e4151b087ff51110eed00706` | `2026-10-13T21:04:05-04:00` | fix(output): serialize auto-derived decimal fields; production: django_graphex/core/output_compiler.py; tests: tests/core/test_decimal_output.py. |
| `dbabfde2f1367f869c88ed22cfe91ce267ba02ca` | `2026-10-13T21:22:17-04:00` | fix(output): retain decimal primary key nullability; production: django_graphex/core/output_compiler.py; tests: tests/core/test_decimal_output.py. |
| `ca6cfb72bb388783e02bec20e4b29795b78e3abf` | `2026-10-13T21:23:37-04:00` | test(converter): register relation target locally; production: none; tests: tests/test_converter.py. |
| `8f86dc8927eb66a62dcdcf8936c40b659d6e6ead` | `2026-10-13T21:58:46-04:00` | feat(bigint)!: use decimal strings for model big integers; production: django_graphex/core/__init__.py, django_graphex/core/fields.py, django_graphex/core/input_compiler.py, django_graphex/core/output_compiler.py, django_graphex/core/scalars.py, django_graphex/filtering/native_schema.py; tests: tests/core/test_bigint.py, tests/core/test_s_roots_d_converter_native_aware.py, tests/core/test_scalars.py. |
| `12a7506a8b83c75ee211e1174dca9c3fbdf748c2` | `2026-10-13T22:36:55-04:00` | fix(bigint): preserve relation ID and choice validation; production: django_graphex/core/fields.py; tests: tests/core/test_bigint.py. |
| `d27832188f55e72d88551c16e077032d633c9875` | `2026-10-13T23:43:46-04:00` | feat(output)!: preserve decimal precision by default; production: django_graphex/core/output_compiler.py; tests: tests/core/test_decimal_output.py, tests/core/test_s_roots_d_converter_native_aware.py, tests/test_converter.py, tests/test_converter_branches.py. |
| `4cc048bb02e5258ef30e8fe86d902a0ec356ac1e` | `2026-10-14T00:17:04-04:00` | docs(scalars): describe shared decimal output scalar; production: django_graphex/core/scalars.py; tests: none. |
| `84369e41431e16a6ebe53159c2b7b6fd3401b1db` | `2026-10-14T00:32:34-04:00` | fix(views): enforce body cap before response-cache work; production: django_graphex/views.py; tests: tests/test_views_body_cap_cache.py. |
| `441899a520778e03518d81816eef0ddbd00dab8a` | `2026-10-14T01:03:57-04:00` | feat(directives)!: cap replace output before allocation; production: django_graphex/directives/string.py, django_graphex/settings.py; tests: tests/test_replace_output_limit.py. |
| `f91022e7a00deda481e63c5b316cc9db003ae1a5` | `2026-10-14T01:42:01-04:00` | fix(view): roll back atomic mutations on GraphQL errors; production: django_graphex/views.py; tests: tests/test_views_atomic_errors.py. |
| `cc67be504f595053257e237b1296ad16d202f536` | `2026-10-14T02:01:53-04:00` | fix(docs): restore core settings table rows; production: none; tests: tests/test_settings_tables_contract.py. |
| `65e99d35bd3392a640619a089307a7977627b57f` | `2026-10-14T08:58:22-04:00` | fix(registry)!: reject conflicting public model outputs; production: django_graphex/registry.py, django_graphex/types.py; tests: tests/_schema_isolation.py, tests/core/test_decimal_output.py, tests/core/test_factory.py, tests/core/test_fg2_native_schema_compiler.py, tests/core/test_fields.py, tests/core/test_filter_input_name_pascalcase.py, tests/core/test_list_output_type.py, tests/core/test_native_root_compiler.py, tests/core/test_native_schema_assembly.py, tests/core/test_output_identity_invariant.py, tests/core/test_s8c_field_descriptor_graphene_free.py, tests/core/test_s_roots_a_descriptors.py, tests/core/test_s_roots_c_ok_errors_native.py, tests/core/test_s_roots_d_converter_native_aware.py, tests/core/test_s_roots_h_native_mutation_payload.py, tests/core/test_s_roots_j_filter_input_collision.py, tests/core/test_schema_lazy_fork.py, tests/core/test_schema_scoped_registry.py, tests/core/test_subscription_native_build.py, tests/core/test_types_objecttype.py, tests/core/test_window_prefetch_native.py, tests/core/test_wu12_schema_compiler_coverage.py, tests/core/test_wu9_modeltype_mutation_execution.py, tests/core/test_wu9_mutation_execution.py, tests/subscriptions/_transport_schema.py, tests/subscriptions/test_audit_defects.py, tests/subscriptions/test_capability_parity.py, tests/test_docs_types_samples.py, tests/test_optimizer_coverage.py, tests/test_optimizer_phase_c.py, tests/test_optimizer_phase_e.py, tests/test_ordering_provenance.py, tests/test_output_registration_conflict.py, tests/test_registry.py. |
| `ff4741e6f8c7b1787933a32fb902f692b03f8b41` | `2026-10-14T09:19:34-04:00` | docs(types): clarify canonical output registration; production: django_graphex/types.py; tests: none. |
| `93edfdd1773c7eb4f5ee0058a563d6ef5c1df07b` | `2026-10-14T09:46:49-04:00` | test(registry): isolate serializer conflict fixture; production: none; tests: tests/test_serializer_type_custom_fields.py. |
| `edb82a30dae7bd96b5a56627963746d6e87b00cd` | `2026-10-14T09:53:50-04:00` | fix(types): validate public output field selectors; production: django_graphex/types.py; tests: tests/test_output_selector_validation.py. |
| `a2f329d8bdeb84499c669b01e82c28bf88d971d7` | `2026-10-14T10:29:35-04:00` | fix(output): preserve reverse accessor selectors; production: django_graphex/types.py; tests: tests/test_output_selector_validation.py. |
| `4643f9aee80fbea833e637460c2576e9327a8604` | `2026-10-14T10:29:49-04:00` | test(cost): isolate view wiring schema; production: none; tests: tests/test_query_cost.py. |
| `34b37e6f014c8c6d3308dabc1427fbd68748eac6` | `2026-10-14T12:50:13-04:00` | fix(types)!: reject incompatible generated enum collisions; production: django_graphex/converter.py, django_graphex/core/compiler.py; tests: tests/core/test_choices_enum_name_collisions.py. |
| `0b267dab424c506ed85b080b2754a496c39ee6c1` | `2026-10-14T13:10:31-04:00` | fix(types): reuse equivalent choices enums regardless of order; production: django_graphex/converter.py; tests: tests/core/test_choices_enum_name_collisions.py. |
| `c3a35a741a769cbb90bc6846062f0800b1199f9b` | `2026-10-14T13:58:10-04:00` | fix(choices)!: reject ambiguous enum member names; production: django_graphex/converter.py; tests: tests/core/test_choices_enum_member_ambiguity.py, tests/test_converter_choices.py. |
| `da31d910ea45968a823fd0a32a5fe9a4f230fa32` | `2026-10-14T14:14:13-04:00` | docs(choices): document both enum build failures; production: django_graphex/converter.py; tests: none. |
| `a96ca179b90714f39c4b69a79ebb24255aa17578` | `2026-10-14T16:10:42-04:00` | feat(mutations)!: scope generated relation ID links; production: django_graphex/nested.py, django_graphex/utils.py; tests: tests/test_destination_link_scope.py, tests/test_nested_child_permissions.py. |
| `6c100c8515d5fe75a34bce090ae6712ac9efa28a` | `2026-10-14T16:15:13-04:00` | docs(mutations): clarify scoped nested link comments; production: django_graphex/nested.py; tests: none. |
| `6275b6ee351a23f4f6c395f14c0ac587e59b8cb8` | `2026-10-14T16:42:23-04:00` | fix(nested): preserve valid destination scope querysets; production: django_graphex/nested.py; tests: tests/test_destination_link_compatibility.py. |
| `dcdd25bc3b837593eab1c8784702848d958e9451` | `2026-10-14T16:44:15-04:00` | test(nested): cover malformed scoped relation identifiers; production: none; tests: tests/test_destination_link_compatibility.py. |
| `bb592ddb7c1e90e0300ee4be8f30252b2c19d6a6` | `2026-10-14T19:06:48-04:00` | fix(nested)!: require child update host for orphan adoption; production: django_graphex/nested.py; tests: tests/test_nested_sd4_orphan_scope.py. |
| `8521c023731cae50617d605bc294e6071a483074` | `2026-10-14T19:24:58-04:00` | docs(nested): complete child-link exception contract; production: django_graphex/nested.py; tests: none. |
| `f0b3126260224c62ff1422e1e8e86ba5d8bf11bb` | `2026-10-14T20:16:22-04:00` | fix(security): redact flat GFK targets in pruned schemas; production: django_graphex/core/_flat_gfk_scope.py, django_graphex/core/output_compiler.py, django_graphex/core/permission_signature_cache.py, django_graphex/core/schema_pruner.py, django_graphex/views.py; tests: tests/test_flat_gfk_pruned_security.py. |
| `ac72aa7b9ca4b4532c26535f43e569c1cda0503e` | `2026-10-14T20:54:26-04:00` | fix(subscriptions): resolve schema providers off the event loop; production: django_graphex/subscriptions/transports/sse.py, django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_transport_cold_permissions.py. |
| `901c35bd9b754f6b21b6f61715c0f62ea0604d15` | `2026-10-14T21:39:56-04:00` | fix(subscriptions)!: isolate automatic notification failures; production: django_graphex/subscriptions/bindings.py; tests: tests/subscriptions/test_automatic_best_effort.py. |
| `c3edeb3f4082f7f3dac79bc7cd34864290ff75d2` | `2026-10-14T22:08:36-04:00` | docs(subscriptions): document propagated notification errors; production: django_graphex/subscriptions/bindings.py; tests: none. |
| `eee1a6dd2b7743763066d81f544e709c7c76d180` | `2026-10-14T22:58:41-04:00` | feat(input)!: evaluate factories per coerced object; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_input_compiler_lists_defaults.py, tests/core/test_input_factory_per_object.py. |
| `ef7f6b5ad5b9e711d36ab7d3c45694fc3c987906` | `2026-10-14T23:23:09-04:00` | fix(input): ignore factories of overwritten aliases; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_factory_per_object.py. |
| `480167af7d17354d477041f76a4a662b1814604e` | `2026-10-14T23:55:19-04:00` | fix(mutations): preserve reserved Django field names; production: django_graphex/core/backend.py, django_graphex/core/fields.py, django_graphex/core/input_compiler.py, django_graphex/core/validators.py; tests: tests/core/test_reserved_model_fields.py. |
| `9e36576513cf1e0ced46ad96a799666caa39a3f0` | `2026-10-15T00:20:43-04:00` | fix(inputs): preserve inherited hooks on reserved model fields; production: django_graphex/core/fields.py, django_graphex/core/validators.py; tests: tests/core/test_reserved_model_fields.py. |
| `0ea68ac4f120bc2bfedfde65c6e3fb7c97a7111e` | `2026-10-15T00:52:40-04:00` | fix(types)!: honor explicit interface field names; production: django_graphex/core/polymorphic_compiler.py, django_graphex/types.py; tests: tests/core/test_audit_forked_pair_and_field_names.py, tests/test_output_selector_validation.py. |
| `a64d7f58adc370ac250a4c61fc2c82e84eeb7c01` | `2026-10-15T01:11:12-04:00` | fix(types): scope explicit interface names to implementors; production: django_graphex/core/polymorphic_compiler.py, django_graphex/types.py; tests: tests/test_output_selector_validation.py. |
| `74146dd55f74108b9b3c4b5d913c2a21b36c550a` | `2026-10-15T08:23:19-04:00` | fix(mutations): redact blocked generated delete errors; production: django_graphex/mutation.py, django_graphex/types.py; tests: tests/test_generated_delete_security.py. |
| `54f68e53e1db6f8c20296e10b2f4d336a97a0880` | `2026-10-15T08:45:45-04:00` | docs(types): complete generated delete error contract; production: django_graphex/types.py; tests: none. |
| `4ec40e8403549b71531fb7d38cf884b6c90a6fbb` | `2026-10-15T09:08:47-04:00` | test: isolate reverse one-to-one classifier fixture; production: none; tests: tests/test_nested_edges.py. |
| `81f79492a3b5906687194cbf143ca483c80cfee9` | `2026-10-15T09:52:00-04:00` | feat(inputs): validate generated email fields; production: django_graphex/core/fields.py; tests: tests/core/test_email_input_validation.py. |
| `610162956ca645d85bf7e7749a19ada81aac055f` | `2026-10-15T10:12:20-04:00` | fix(inputs): validate email choice values without changing enum inputs; production: django_graphex/core/fields.py; tests: tests/core/test_email_input_validation.py. |
| `6bd37b2d9dcac7359f3f0c94fc47f65a350bac5f` | `2026-10-15T10:43:41-04:00` | fix(inputs): validate positive integer values before persistence; production: django_graphex/core/fields.py; tests: tests/core/test_positive_input_validation.py. |
| `ebe32b0a74ad388f66f8b9c66f73513ff6c28bde` | `2026-10-15T11:17:14-04:00` | fix(inputs): retain nullable positive choice enums; production: django_graphex/core/fields.py; tests: tests/core/test_positive_input_validation.py. |
| `8db3083585f44e65cbf5f7eba496f3b4e004e728` | `2026-10-15T12:02:41-04:00` | fix(mutations): redact unmapped integrity errors; production: django_graphex/mutation.py, django_graphex/nested.py, django_graphex/types.py; tests: tests/test_generated_delete_security.py, tests/test_generated_integrity_error_redaction.py. |
| `c4273e2b09624cfdd615e8f908abcb30ad2efb54` | `2026-10-15T12:56:08-04:00` | fix(filters): match explicit exact null against SQL NULL; production: django_graphex/filtering/translate.py; tests: tests/test_exact_null_filtering.py. |
| `53b3481fff2eed6eb1a0a7d5ee07cd85f8f975e8` | `2026-10-15T13:48:50-04:00` | fix(filtering): type numeric date parts as Int inputs; production: django_graphex/filtering/native_schema.py; tests: tests/test_datepart_filtering.py. |
| `342a4ab92b2797e142a325d11311495cfc5808e2` | `2026-10-15T14:38:44-04:00` | fix(filtering): match explicit AND branches across related rows; production: django_graphex/filtering/backend.py; tests: tests/test_and_many_filtering.py. |
| `4c3e4bbd0df9948c53eb3d2d4846064571934d10` | `2026-10-15T15:05:22-04:00` | fix(filtering): correlate nested to-many AND branches; production: django_graphex/filtering/backend.py; tests: tests/test_and_many_filtering.py. |
| `e18f02b8b15b7cdfaf1fad06adc545527f1f8026` | `2026-10-15T15:37:46-04:00` | fix(pagination): resume typed nested cursors; production: django_graphex/paginations/pagination.py; tests: tests/test_pagination_cursor_typed_http.py. |
| `55287677ba38739aa3885379e952b975b2640d24` | `2026-10-15T15:38:52-04:00` | test(pagination): cover typed cursor fallback branches; production: none; tests: tests/test_pagination_cursor_typed_http.py. |
| `c3a063aeaaa0e765d9b3d3dc7749168ec6f2c842` | `2026-10-15T16:17:35-04:00` | fix(pagination): reject invalid typed cursor values; production: django_graphex/paginations/pagination.py; tests: tests/test_pagination_cursor_typed_http.py. |
| `9ab95cb26b95af0fb2baae04c79108bdcbd1765f` | `2026-10-15T17:01:08-04:00` | fix(pagination): treat null page as first page; production: django_graphex/paginations/pagination.py; tests: tests/test_pagination_page_null_http.py. |
| `954a2036b53a540e4db9829b6373eb66b2570474` | `2026-10-15T17:37:56-04:00` | fix(filtering): disambiguate nested relation and primary-key lookups; production: django_graphex/filtering/translate.py; tests: tests/test_exact_null_filtering.py, tests/test_filtering_internals.py, tests/test_native_filtering.py, tests/test_relation_lookup_name_collision.py. |
| `5faeef718816e9e3fda12472f588da92ade02edf` | `2026-10-15T19:21:10-04:00` | fix(pagination): default omitted page sizes to 100; production: django_graphex/paginations/pagination.py, django_graphex/settings.py; tests: tests/core/_sdl_parity_seed.py, tests/core/test_relation_gfk_native.py, tests/core/test_relation_to_many_native.py, tests/core/test_relation_to_one_native.py, tests/test_default_page_size_http.py, tests/test_optimizer_coverage.py, tests/test_optimizer_perf.py, tests/test_optimizer_phase_c.py, tests/test_optimizer_phase_d.py, tests/test_optimizer_phase_e.py, tests/test_pagination_default_ordering.py, tests/test_query_cost.py, tests/test_query_optimization.py, tests/test_settings.py, tests/test_skip_include_directives.py, tests/test_track2_optimizer.py. |
| `7249e5e40b9a5cc225edac8dfc09b685889f9e73` | `2026-10-15T19:49:09-04:00` | docs(playground): align cursor default with app settings; production: none; tests: tests/test_playground_310_contract.py. |
| `c75ea72fb0576fb86b1dbe829d6e4b3f42c93933` | `2026-10-15T20:44:18-04:00` | fix(pagination): fail closed when negative-page count fails; production: django_graphex/paginations/pagination.py, django_graphex/paginations/utils.py; tests: tests/test_negative_page_count_error_http.py. |
| `f6e88d446f492324b5ec09f72c880c88842acb6d` | `2026-10-15T21:59:22-04:00` | fix(pagination): stabilize bounded model ties by primary key; production: django_graphex/fields.py, django_graphex/paginations/pagination.py; tests: tests/test_pagination_pk_tiebreak.py. |
| `d1a6a18c167451546f8cf8bb4c91614cbd18c492` | `2026-10-15T22:38:12-04:00` | fix(pagination): preserve effective queryset order before PK tie-break; production: django_graphex/fields.py, django_graphex/paginations/pagination.py; tests: tests/test_pagination_pk_tiebreak.py, tests/test_pagination_server_order.py. |
| `96e1f9efb0569d27a08235c84656cf6be100caf1` | `2026-10-16T00:02:16-04:00` | fix: enforce bound query cost before execution; production: django_graphex/views.py; tests: tests/test_cost_variable_http.py. |
| `bcd66860ced0d219ce5b64e618907078dd40a1fc` | `2026-10-16T00:27:03-04:00` | fix(cost): preserve cache on pre-execution mutation refusal; production: django_graphex/views.py; tests: tests/test_cost_mutation_cache.py. |
| `d9d2c40f7bb4af2fc2125f76d344c124f8a3df74` | `2026-10-16T01:10:50-04:00` | fix(cache): frame response cache request components; production: django_graphex/views.py; tests: tests/test_views_cache_key_framing.py. |
| `a401f9e25e6989ccb28571815931fc6baf624593` | `2026-10-16T02:31:11-04:00` | fix(http): classify unexpected production GraphQL errors; production: django_graphex/views.py; tests: tests/_native330_runtime_guard.py, tests/test_cost_mutation_cache.py, tests/test_generated_integrity_error_redaction.py, tests/test_http_internal_error_diagnostics.py. |
| `407060eb8f7a67373ae9a0bfaa50520457a95e4f` | `2026-10-16T02:39:31-04:00` | test(http): remove local audit runtime guard; production: none; tests: tests/_native330_runtime_guard.py, tests/test_http_internal_error_diagnostics.py. |
| `3e3af998e38dc2fe5630ee775acc5c91166c8e3f` | `2026-10-16T03:25:21-04:00` | test(security): remove checkout-bound runtime guards; production: none; tests: tests/test_generated_delete_security.py, tests/test_generated_integrity_error_redaction.py, tests/test_generated_security_test_portability.py. |
| `043811eefaec7c4662eb53672b994ec65f9ac545` | `2026-10-16T10:15:59-04:00` | fix(response): preserve zero and false during cleaning; production: django_graphex/utils.py; tests: tests/test_clean_response_http.py, tests/test_utils.py. |
| `cbfb9fb11ca45f6be45ef41e864f2f5fefa59e90` | `2026-10-16T10:34:30-04:00` | test(response): clarify cleaning regression docstrings; production: none; tests: tests/test_clean_response_http.py, tests/test_utils.py. |
| `69d326eecee9c71ffe19db64e9019812297c74a1` | `2026-10-16T11:21:55-04:00` | fix(cache): skip failed GraphQL response entries; production: django_graphex/views.py; tests: tests/test_success_response_cache.py, tests/test_views_cache_isolation.py. |
| `23c06e0b6b7d86f2b082b86a50e4a6d715a3e78e` | `2026-10-16T12:20:57-04:00` | fix(views): reject unsupported async HTTP execution; production: django_graphex/views.py; tests: tests/test_sync_async_http.py. |
| `e8d0cf9eb5e40c03d9a1b2ee8fb3a9d42e63f3e6` | `2026-10-16T12:50:39-04:00` | fix(http): close nested middleware coroutines on async refusal; production: django_graphex/views.py; tests: tests/test_sync_async_http.py. |
| `dd1cf898dd94d01e44ff7672e764ea6807cf2f7b` | `2026-10-16T13:14:28-04:00` | fix(http): preserve ignored middleware entries during async guard; production: django_graphex/views.py; tests: tests/test_sync_async_http.py. |
| `11bd843f010dce28a4a10af788d54ad058ecef5d` | `2026-10-16T13:42:31-04:00` | docs: clarify introspection middleware opt-in; production: none; tests: tests/test_introspection_docs.py. |
| `347b2ff7ac383bf791b795b6c51d9f825236ceeb` | `2026-10-16T14:25:21-04:00` | fix: preserve partial results on batch HTTP 400; production: django_graphex/views.py; tests: tests/test_batch_http_error_partial.py. |
| `9c431f68576d52d7fa263a0921d9cbb5ba7833dd` | `2026-10-16T14:55:25-04:00` | test(datepart): remove checkout-bound runtime guards; production: none; tests: tests/test_datepart_filtering.py, tests/test_datepart_test_portability.py. |
| `9fec11da77a76f697ff6365a6c0bc5ed6c33f4d7` | `2026-10-16T15:26:34-04:00` | fix: preserve view configuration validation under optimization; production: django_graphex/views.py; tests: tests/test_view_base.py. |
| `408e2aada51a39265fee6df727cdf33457d2447f` | `2026-10-16T16:01:03-04:00` | fix(views): classify fragmented introspection roots; production: django_graphex/views.py; tests: tests/test_introspection_fragments.py. |
| `bbc8e9ac28e180070b60ed254d0ca262bd9c843b` | `2026-10-16T16:03:22-04:00` | test(views): cover malformed introspection roots; production: none; tests: tests/test_introspection_fragments.py. |
| `0606b34613a5abd76d2df428da1ba8c3eb5ac625` | `2026-10-16T17:03:18-04:00` | docs(cache): clarify GET request body key hashing; production: django_graphex/views.py; tests: tests/test_views_cache_key_framing.py. |
| `0d4f3b7427360b894da40c0df91e613cb0ed5469` | `2026-10-16T17:55:26-04:00` | docs(pagination): clarify explicit None fallbacks; production: none; tests: tests/test_pagination_none_docs_contract.py. |
| `da9c3c4443dae605710b620b1d095f738d13ef53` | `2026-10-16T18:20:07-04:00` | docs(pagination): name configured startup default; production: none; tests: tests/test_pagination_none_docs_contract.py. |
| `316844e376f9585f873903a60d73eb25a39aeb58` | `2026-10-16T18:53:06-04:00` | fix(optimizer): plan merged root field nodes together; production: django_graphex/utils.py; tests: tests/test_optimizer_merged_field_nodes.py. |
| `961c018e2d089962679c65329ebdb6bff765ba26` | `2026-10-16T19:39:46-04:00` | fix(permissions): serve warm schemas during cold pruning; production: django_graphex/core/permission_signature_cache.py; tests: tests/test_permission_cache_lock_split.py. |
| `4df64c4ff7dadb0c61b82fb72324f72179af4fc0` | `2026-10-16T20:24:11-04:00` | fix(schema): isolate concurrent fork registration state; production: django_graphex/core/base.py, django_graphex/schema.py; tests: tests/core/test_schema_fork_threads.py. |
| `088b729a592bc4baae199f6ebacd15a0df129cfa` | `2026-10-16T20:34:02-04:00` | docs(tests): clarify fork regression contract; production: none; tests: tests/core/test_schema_fork_threads.py. |
| `3cefed7131c6d52f89a082a631df29ebc2228945` | `2026-10-16T21:27:54-04:00` | test(registry): restore cached default pair after isolated scopes; production: none; tests: tests/_schema_isolation.py, tests/core/test_schema_isolation.py. |
| `c8bb0dd2d7700eec80cadbab3ade0af4f3a655e8` | `2026-10-16T22:18:15-04:00` | fix(optimizer): batch GFK targets inside union fragments; production: django_graphex/utils.py; tests: tests/test_track2_optimizer.py. |
| `0c5e32065fc43799b36872ea6bc1cdaf9f007af7` | `2026-10-17T10:25:09-04:00` | fix: fail fast on model metadata enumeration errors; production: django_graphex/core/base.py, django_graphex/core/output_compiler.py, django_graphex/schema.py, django_graphex/types.py; tests: tests/core/test_metadata_enumeration_failures.py, tests/core/test_output_compiler_coverage.py. |
| `72fbcbdccecfb955ad71666b31ae7c02618803eb` | `2026-10-17T11:26:02-04:00` | fix(fields): surface source property getter errors; production: django_graphex/core/descriptors.py; tests: tests/core/test_source_property_attribute_error.py. |
| `18f4a67a947822047b5423e597d3c53d8dec0498` | `2026-10-17T11:28:31-04:00` | test(fields): keep non-property source absence nullable; production: none; tests: tests/core/test_source_property_attribute_error.py. |
| `7fb4c121dca116d9e0192e87d744f555444c1c27` | `2026-10-17T11:50:38-04:00` | fix(fields): recognize wrapped Python property failures; production: django_graphex/core/descriptors.py; tests: tests/core/test_source_property_attribute_error.py. |
| `e04394b6fcc4b4ac02e31793e7e6479fea785e9c` | `2026-10-17T13:25:40-04:00` | fix(subscriptions): log suppressed delivery close errors; production: django_graphex/subscriptions/delivery.py; tests: tests/subscriptions/test_delivery_runtimeerror_diagnostic.py. |
| `a2ff209469f1c642fff20ebf78c3c4019db1dd5b` | `2026-10-17T18:14:47-04:00` | fix(mutation): track native field identity by live instance; production: django_graphex/core/mutation.py, django_graphex/core/schema_compiler.py, django_graphex/mutation.py, django_graphex/types.py; tests: tests/core/test_native_field_identity_lifetime.py. |
| `14720eab7d6662c4ce9f3ee56f1b7740133e1c08` | `2026-10-17T19:06:10-04:00` | fix(enum): synchronize cached enum construction; production: django_graphex/converter.py, django_graphex/core/compiler.py, django_graphex/registry.py; tests: tests/core/test_enum_cache_concurrency.py. |
| `13b2e6b4cdfd7489210267a5f6b5e3f35ec49ac4` | `2026-10-17T21:52:18-04:00` | fix(registry): serialize cold registry and list creation; production: django_graphex/registry.py, django_graphex/types.py; tests: tests/core/test_registry_creation_concurrency.py. |
| `9268da4033901e5a76daf6a3c84ac34c860dae0f` | `2026-10-17T22:42:12-04:00` | fix(subscriptions): release WebSocket ID before complete; production: django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_ws_completion_reuse.py. |
| `fe545832513244bdddf2d35cea4cc845fc34cad9` | `2026-10-17T23:12:47-04:00` | fix(subscriptions): clean up groups after cancelled startup; production: django_graphex/subscriptions/source.py; tests: tests/subscriptions/test_startup_cleanup.py. |
| `514def143c42d6dad082e4590fb9edce813c90d6` | `2026-10-17T23:24:11-04:00` | fix(subscriptions): preserve retry after failed group join; production: django_graphex/subscriptions/source.py; tests: tests/subscriptions/test_startup_cleanup.py. |
| `ace6638e65f70843d123263f7ea09b7c780a595b` | `2026-10-17T23:57:16-04:00` | fix(directives): await resolver values before transformation; production: django_graphex/middleware.py; tests: tests/test_async_directive_middleware.py. |
| `031299c46e3127c080a3554f0c708b01147ad7a2` | `2026-10-18T00:16:53-04:00` | fix(directives): defer async wrapper allocation until awaited; production: django_graphex/middleware.py; tests: tests/test_async_directive_middleware.py. |
| `7a1dfe3b8406a15fc1fdd2b7221196181449e350` | `2026-10-18T00:39:45-04:00` | fix(inputs): warn on unsupported typing fallbacks; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py. |
| `34e03d39838fb6251322b32001266f9ec97cf814` | `2026-10-18T01:19:28-04:00` | docs(tests): complete tracked regression docstrings; production: none; tests: tests/core/test_metadata_enumeration_failures.py, tests/core/test_schema_fork_threads.py, tests/core/test_schema_isolation.py, tests/core/test_source_property_attribute_error.py, tests/test_optimizer_merged_field_nodes.py, tests/test_permission_cache_lock_split.py, tests/test_track2_optimizer.py. |
| `bf1163e639b680d76c4101f7524c949b7f411992` | `2026-10-18T02:03:53-04:00` | fix(subscriptions): bind automatic notifications to write alias; production: django_graphex/subscriptions/bindings.py; tests: tests/subscriptions/test_routed_on_commit.py. |
| `c408989f75d4d4f5729edd5296d93c36108f8efe` | `2026-10-18T02:33:24-04:00` | fix(nested): use parent write alias for atomic writes; production: django_graphex/nested.py; tests: tests/test_routed_nested_atomic.py. |
| `41fbeec734249c6e14c3402703e784c6cce3d490` | `2026-10-18T03:00:10-04:00` | docs(nested): qualify routed rollback contract; production: django_graphex/nested.py; tests: tests/test_routed_nested_atomic.py. |
| `6983455ea0eedb16f5a7f582604c8340bcc6a09c` | `2026-10-18T03:36:52-04:00` | fix(subscriptions): match Decimal filters against event snapshots; production: django_graphex/subscriptions/mixins.py; tests: tests/subscriptions/test_decimal_snapshot_filter.py. |
| `6df731e0d01b67997bf2fa6de457c372f4a33855` | `2026-10-18T04:06:31-04:00` | fix(subscriptions): match valid wide Decimal snapshots; production: django_graphex/subscriptions/mixins.py; tests: tests/subscriptions/test_decimal_snapshot_filter.py. |
| `e1f29e9430725efa2d1f240140b5ee5ab6ae4882` | `2026-10-18T04:44:45-04:00` | test(uploads): close direct-view request resources; production: none; tests: tests/test_view_layer_audit.py, tests/test_views_multipart_body_bound.py. |
| `73b8f4ea976b994b50b469f93665af9a36a19c61` | `2026-10-18T05:09:43-04:00` | docs: clarify current GraphEx behavior boundaries; production: none; tests: tests/test_docs_current_behavior_boundaries.py. |
| `5eb905db4dc0014c79ae4347201b36be79871f99` | `2026-10-18T05:27:31-04:00` | docs: distinguish cache misses from cookie-free hits; production: none; tests: tests/test_docs_current_behavior_boundaries.py. |
| `32f2533ba0ad97fc97cf6e5680783c4323e26aa4` | `2026-10-18T05:58:05-04:00` | docs: publish bounded 4.0.0 audit disposition; production: none; tests: tests/test_audit_400_report_contract.py. |
| `22a284875e79257a27bbff0007c7fb517a554a75` | `2026-10-18T06:31:49-04:00` | docs: clarify bounded audit claim dispositions; production: none; tests: tests/test_audit_400_report_contract.py. |
| `a5f3a8382620464105375e21f7241107dc9f69fe` | `2026-10-18T06:52:58-04:00` | docs: correct four audit examples; production: none; tests: tests/test_audit_400_report_contract.py. |
| `73a85abbad61517dc62e05bb34d22ce9464db368` | `2026-10-18T13:20:45-04:00` | fix(scope): enforce destination querysets on automatic FK reads; production: django_graphex/core/output_compiler.py, django_graphex/fields.py, django_graphex/utils.py; tests: tests/test_relation_scope_hatch.py, tests/test_sd1_relation_read_scope.py, tests/test_sd1_reverse_accessor_scope.py. |
| `603a117f67a41502f93d6551dbc5355c592b23ca` | `2026-10-18T14:26:14-04:00` | fix(filters): scope forward FK traversals to visible destinations; production: django_graphex/fields.py, django_graphex/filtering/backend.py, django_graphex/filtering/translate.py, django_graphex/types.py; tests: tests/test_sd2_forward_fk_filter_scope.py. |
| `98ee5455268077c2bd63ffe0be683a1d56917fb3` | `2026-10-18T15:56:33-04:00` | fix(filters): scope reverse FK witnesses to visible children; production: django_graphex/filtering/backend.py, django_graphex/filtering/native_schema.py, django_graphex/filtering/translate.py; tests: tests/test_sd2_reverse_fk_filter_scope.py. |
| `39dc696ba1664256e5b921003a4421133899d127` | `2026-10-18T16:53:19-04:00` | fix(filtering): scope many-to-many destination witnesses; production: django_graphex/filtering/backend.py, django_graphex/filtering/native_schema.py, django_graphex/filtering/translate.py; tests: tests/test_sd2_m2m_filter_scope.py. |
| `0f64533aff4210b77f4b4659d74fa264f46cf283` | `2026-10-18T17:31:56-04:00` | fix(filtering): scope forward one-to-one destinations; production: django_graphex/filtering/backend.py; tests: tests/test_sd2_forward_o2o_filter_scope.py. |
| `8ebfd43fce7071660795398e70f90ed0e2359054` | `2026-10-18T18:24:01-04:00` | fix(security): scope automatic one-to-one output reads; production: django_graphex/core/output_compiler.py, django_graphex/types.py, django_graphex/utils.py; tests: tests/test_sd1_o2o_output_scope.py. |
| `0ee46b94bb391bb59c599f9e88af46ce0a8f0f1b` | `2026-10-18T19:43:58-04:00` | fix(security): scope automatic many-to-many outputs and counts; production: django_graphex/converter.py, django_graphex/fields.py, django_graphex/utils.py; tests: tests/test_sd1_m2m_output_scope.py. |
| `57e0aaba2de6954f6aa1dc10b4ea690d4e16a686` | `2026-10-18T21:48:22-04:00` | fix(nested): keep instance-routed creates atomic; production: django_graphex/nested.py; tests: tests/test_routed_nested_atomic.py. |
| `33ff8786e03901ef1ca9bf0e7f34c82ab2b0a0b5` | `2026-10-19T08:48:49-04:00` | fix(subscriptions): preserve native DateTime snapshots; production: django_graphex/subscriptions/mixins.py, django_graphex/subscriptions/resolvers.py, django_graphex/subscriptions/subscription.py; tests: tests/subscriptions/test_datetime_snapshots.py. |
| `f931cb95946dc7704714097873a2a2ab2c3e06e7` | `2026-10-19T09:39:41-04:00` | docs(audit): reflect local R09b docstring cleanup; production: none; tests: tests/test_audit_400_report_contract.py. |
| `ef598a7d3dca3b76974bdd0829991db895d984c1` | `2026-10-19T10:33:34-04:00` | fix(subscriptions): reject unoffered WebSocket subprotocols; production: django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_ws_subprotocol.py, tests/test_audit_400_report_contract.py. |
| `98956fa142bca0d6b78a7402ff626270d4295afc` | `2026-10-19T11:42:16-04:00` | feat(subscriptions): add optional connection authentication hook; production: django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_ws_on_connect.py, tests/test_audit_400_report_contract.py. |
| `7ec2264c763859cd840e1475e8f4cec9a47ed8fc` | `2026-10-19T20:56:21-04:00` | feat(subscriptions): add opt-in SSE heartbeat and user limits; production: django_graphex/settings.py, django_graphex/subscriptions/transports/_sse_lease.py, django_graphex/subscriptions/transports/sse.py; tests: tests/subscriptions/test_sse_controls.py, tests/subscriptions/test_sse_lease_lifecycle.py, tests/test_audit_400_report_contract.py. |
| `1ee78e2548dcb7fc4d466a1c702f1ae9e060671d` | `2026-10-19T22:19:26-04:00` | fix(subscriptions): preserve filtered delete notifications; production: django_graphex/subscriptions/bindings.py, django_graphex/subscriptions/source.py, django_graphex/subscriptions/subscription.py; tests: tests/subscriptions/test_delete_snapshot_matching.py, tests/test_audit_400_report_contract.py. |
| `c664db3fe7d727e073de7725564a9cbe8a49e0fa` | `2026-10-19T23:28:14-04:00` | fix(subscriptions): compare finite float snapshots numerically; production: django_graphex/subscriptions/mixins.py; tests: tests/subscriptions/test_float_snapshot_filter.py. |
| `1f97d24d06309309601e029eb21766dcd1da6e67` | `2026-10-20T01:11:46-04:00` | fix(directives): preserve null values in date formatting; production: django_graphex/directives/date.py; tests: tests/test_directive_date_null.py. |
| `35199aa09a2ce3331456accb72348171cb9b98e5` | `2026-10-20T01:54:04-04:00` | fix(directives): zero omitted time components in text dates; production: django_graphex/directives/date.py; tests: tests/test_directive_date_text_time.py. |
| `dc556059c5c06e5d21bcf63388535901ffe3979a` | `2026-10-20T10:30:25-04:00` | fix(directives): localize aware dates in absolute formats; production: django_graphex/directives/date.py; tests: tests/test_directive_date_text_time.py, tests/test_directive_date_timezone.py. |
| `9faf5be77ccba11e18822b1bfd44aba66241da89` | `2026-10-20T11:42:57-04:00` | fix(directives): interpret timezone-less text in the active zone; production: django_graphex/directives/date.py; tests: tests/test_directive_date_naive_timezone.py. |
| `2ca275cd475d209024d87ae1dee7cdb2fb7e1665` | `2026-10-20T12:17:47-04:00` | fix(directives): localize adjacent numeric zero offsets; production: django_graphex/directives/date.py; tests: tests/test_directive_date_timezone.py. |
| `4b82906b44a4af22fad7502c291f9baeb29ab371` | `2026-10-20T13:21:51-04:00` | fix(directives): normalize case values without renaming schema; production: django_graphex/directives/string.py; tests: tests/test_directive_case_normalization.py, tests/test_directives_internals.py. |
| `e84090e6411e95b4a5a9b2378ee8c8d07164cb52` | `2026-10-20T14:34:08-04:00` | fix(directives): preserve numeric nulls without bypassing validation; production: django_graphex/directives/string.py; tests: tests/test_directive_numeric_null.py, tests/test_directives_internals.py. |
| `4a0760664ee6806a1fa8c07211a5501256bd65ef` | `2026-10-20T16:02:02-04:00` | fix(scalars): preserve null slots for omitted JSON variables; production: django_graphex/core/scalars.py; tests: tests/test_audit_400_report_contract.py, tests/test_json_raw_missing_list_null.py. |
| `3a7f2da0ac65e49d2fde02d403dbe95de664f143` | `2026-10-20T16:34:32-04:00` | fix(scalars): reject non-finite raw JSON inputs; production: django_graphex/core/scalars.py; tests: tests/test_json_nonfinite_input.py. |
| `03cd107e028dd096a759e95b5bbb4f98dde15c2c` | `2026-10-20T17:24:33-04:00` | fix(directives): restrict transforms to field locations; production: django_graphex/directives/base.py; tests: tests/test_audit_400_report_contract.py, tests/test_directive_field_locations.py. |
| `5b1022bcb5649016afc1ebada00b8e941e713170` | `2026-10-20T20:39:22-04:00` | fix(directives): normalize non-finite floor errors; production: django_graphex/directives/numbers.py; tests: tests/test_audit_400_report_contract.py, tests/test_floor_nonfinite_error.py. |
| `0512657622e64c731db94a699693999865c34703` | `2026-10-20T23:05:14-04:00` | fix(lookups): distinguish malformed primary key IDs; production: django_graphex/fields.py, django_graphex/types.py, django_graphex/utils.py; tests: tests/test_audit_400_report_contract.py, tests/test_invalid_id_contract.py. |
| `276841a9f9ff1796153c6ca52194f20866067373` | `2026-10-20T23:58:18-04:00` | fix(views): preserve null data for execution errors; production: django_graphex/views.py; tests: tests/test_audit_400_report_contract.py, tests/test_http_execution_error_contract.py, tests/test_http_internal_error_diagnostics.py. |
| `dfb47a0078466b96eb59d9ccba150639db08e225` | `2026-10-21T09:20:54-04:00` | fix(uploads): enforce multipart file size limits; production: django_graphex/settings.py, django_graphex/views.py; tests: tests/test_audit_400_report_contract.py, tests/test_multipart_file_size_http.py. |
| `9760b29773e3f62e9afebe7ac878779398878256` | `2026-10-21T10:20:34-04:00` | fix(settings): reject negative batch body and cache limits; production: django_graphex/settings.py; tests: tests/test_audit_400_report_contract.py, tests/test_settings_minimum_zero.py. |
| `f982bb962cd44c2994d441481b85ce69c698bd5e` | `2026-10-21T11:08:20-04:00` | docs(cache): clarify CSRF cookie cache behavior; production: none; tests: tests/test_docs_current_behavior_boundaries.py, tests/test_views_cache_cookie_bypass.py. |
| `ebeb63ab665f650551470b3db107f8c98f28e87a` | `2026-10-21T12:48:40-04:00` | fix(pagination): normalize automatic null placement; production: django_graphex/fields.py, django_graphex/paginations/pagination.py; tests: tests/test_audit_400_report_contract.py, tests/test_docs_current_behavior_boundaries.py, tests/test_pagination_null_order_parity.py. |
| `b5e48232e4615b0ae5e1d4b29ed874f55a3f859b` | `2026-10-21T15:20:01-04:00` | feat(inputs): compile string literals as automatic enums; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_literal_string_enum_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `7d0165c2df1b3e0006b5a4fd28abf55bd2d4975b` | `2026-10-21T17:00:52-04:00` | feat(inputs): validate typed integer maps as JSON; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_typed_dict_json_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `f17e96f3738a0c33dd58e76b2a8594c8c45e9285` | `2026-10-21T18:14:26-04:00` | fix(schema): render representable fixed JSON defaults; production: django_graphex/core/input_compiler.py, django_graphex/core/scalars.py; tests: tests/benchmarks/test_harness_isolation.py, tests/core/test_json_fixed_default_metadata.py, tests/subscriptions/test_transport_import_without_settings.py, tests/test_docs_mutation_contract.py. |
| `75109ef83013bf0040b25b3f2e9398b702e077cc` | `2026-10-21T18:56:00-04:00` | fix(schema): expose valid JSON list default metadata; production: django_graphex/core/input_compiler.py; tests: tests/core/test_json_fixed_default_metadata.py, tests/core/test_json_list_default_metadata.py. |
| `b84d35979cebc46bf910ee1434310f2646afca0c` | `2026-10-21T19:25:21-04:00` | fix(mutations): avoid output registration for rejected declarations; production: django_graphex/mutation.py; tests: tests/core/test_invalid_mutation_registry_side_effect.py. |
| `fc7ac7b3cc4f899c2e9a43cc91b396cca6c79130` | `2026-10-21T22:25:29-04:00` | fix(inputs): support strict JSON maps with typing Dict; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_typed_dict_json_input.py, tests/test_docs_mutation_contract.py. |
| `b4c0e71e7cede1dc406ea7eb55c0aae8b1b57c8f` | `2026-10-22T10:16:25-04:00` | feat(inputs): validate string-valued dictionaries as strict JSON; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_typed_string_dict_json_input.py, tests/test_docs_mutation_contract.py. |
| `85f8dc30a9c70fc56903d0579037e0976ecf14c2` | `2026-10-22T11:43:14-04:00` | feat(inputs): compile nested lists of supported input types; production: django_graphex/core/input_compiler.py; tests: tests/core/test_recursive_input_lists.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `384e3cd8f1e5d9ca2d3d05829ddcc973fee10f35` | `2026-10-22T13:47:31-04:00` | feat(inputs): support exact integer-set input values; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_set_int_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `22caa45c5ad70e76f52016b54f5157cf5ff4350b` | `2026-10-22T14:54:09-04:00` | feat(inputs): support typing Set integer alias; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_set_int_input.py, tests/core/test_typing_set_int_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `7b702635ae1bf47220efa9d5f5bd7fd67d3258be` | `2026-10-22T16:55:34-04:00` | feat(inputs): support exact string-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_set_int_input.py, tests/core/test_string_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `c6bff24ba46d8ed1dbd2b756f0d0022dd1823a0c` | `2026-10-23T13:57:45-04:00` | feat(inputs): support exact boolean-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_boolean_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `aeb74b884b952d94740815b387efe3cc92e81a79` | `2026-10-23T15:16:54-04:00` | feat(inputs): support finite float-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_boolean_set_input.py, tests/core/test_float_set_input.py, tests/core/test_string_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `1d0c6c23d54613ed82dbab5c5e31435055262e2b` | `2026-10-23T16:00:10-04:00` | feat(inputs): support exact UUID-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_uuid_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `ca95f9039978693562e7c26294a2c3d9e7a0e9d3` | `2026-10-23T17:15:14-04:00` | feat(inputs): support finite Decimal-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_decimal_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `deddb61527c123de52e95d239af576da70709b1c` | `2026-10-23T20:42:12-04:00` | feat(inputs): support strict Boolean-map inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_boolean_dict_json_input.py, tests/core/test_input_typing_fallback_warnings.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `d66b1752449a0441bd06d6e0167f2790ab32c907` | `2026-10-23T21:35:15-04:00` | feat(inputs): support strict IntOrString unions; production: django_graphex/core/input_compiler.py, django_graphex/core/scalars.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_int_or_string_union_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `6463eb1f894692a305e81fe0a2454260a4d61bfe` | `2026-10-23T23:09:57-04:00` | docs(audit): resolve original silent typing fallback claim; production: none; tests: tests/test_audit_400_report_contract.py. |

Final documentation-only snapshot: `8d93483d2fd654012a544ce68365baf1964056f3`, 2026-10-23 23:13:45 -04:00, `docs(audit): close original M-D10 disposition`. It is excluded from the 167 source/test-bearing entries.


## Appendix B: changed Python test files

Complete 189-path testing-area Python inventory from the frozen base-to-snapshot diff: 113 added, 76 modified. A few support paths (for example Playground schema/settings) have no test_ definitions; “file” here denotes an inventory path, not necessarily a pytest module. AST deltas are 918 added, 14 removed, 37 modified, and 1066 unchanged named definitions, not pytest-collected cases. The guide-cited 61 added/4 modified subset is not this full inventory. Names below are exact, including removed definitions that no longer exist at the snapshot.

| Path | Change | Added test definitions | AST-modified definitions | Removed definitions | Unchanged count |
|---|---:|---|---|---|---:|
| `examples/playground/blog/schema.py` [open](examples/playground/blog/schema.py) | M | — | — | — | 0 |
| `examples/playground/config/settings.py` [open](examples/playground/config/settings.py) | M | — | — | — | 0 |
| `examples/playground/tests/test_relation_scope_hatch.py` [open](examples/playground/tests/test_relation_scope_hatch.py) | M | `test_automatic_reverse_m2m_counts_visible_posts`<br>`test_the_auto_expanded_reverse_fk_is_scoped` | — | `test_the_auto_expanded_relation_beside_it_is_not_scoped` | 6 |
| `examples/playground/tests/test_shipped_defaults.py` [open](examples/playground/tests/test_shipped_defaults.py) | M | `test_optional_sse_controls_ship_off` | — | — | 7 |
| `examples/playground/tests/test_subscription_transports_e2e.py` [open](examples/playground/tests/test_subscription_transports_e2e.py) | M | — | `test_sse_subscription_delivers_post_create`<br>`test_ws_subscription_delivers_post_create` | — | 7 |
| `integration/live_redis/test_sse_live_redis.py` [open](integration/live_redis/test_sse_live_redis.py) | A | `test_public_sse_live_backend_unavailable_is_503_before_source`<br>`test_public_sse_live_cap_and_cleanup`<br>`test_public_sse_live_midstream_loss_is_generic_and_closes`<br>`test_public_sse_live_normal_source_completion_releases_lease`<br>`test_public_sse_live_source_start_failure_releases_lease`<br>`test_real_lua_crashed_owner_expires_without_release`<br>`test_real_lua_cross_process_cap`<br>`test_real_lua_double_cancellation_waits_for_commit_then_releases`<br>`test_real_lua_ownership_expiry_and_independent_accounts`<br>`test_real_lua_unknown_acquire_reply_releases_committed_token` | — | — | 0 |
| `tests/_schema_isolation.py` [open](tests/_schema_isolation.py) | M | — | — | — | 0 |
| `tests/benchmarks/test_canonical_provenance.py` [open](tests/benchmarks/test_canonical_provenance.py) | M | `test_copy_canonical_fixture_ignores_diagnostics`<br>`test_missing_canonical_file_still_fails_with_diagnostics`<br>`test_validator_ignores_unrelated_diagnostic_json` | — | — | 9 |
| `tests/benchmarks/test_harness_isolation.py` [open](tests/benchmarks/test_harness_isolation.py) | M | — | `test_graphex_mutation_sql_contract_counts_request_internal_queries` | — | 9 |
| `tests/core/_sdl_parity_seed.py` [open](tests/core/_sdl_parity_seed.py) | M | — | — | — | 0 |
| `tests/core/test_audit_forked_pair_and_field_names.py` [open](tests/core/test_audit_forked_pair_and_field_names.py) | M | `test_explicit_interface_name_is_shared_with_implementor` | — | — | 4 |
| `tests/core/test_bigint.py` [open](tests/core/test_bigint.py) | A | `test_auto_output_uses_decimal_string_bigint`<br>`test_automatic_bigint_filter_executes_orm_query`<br>`test_automatic_filter_lookups_use_bigint`<br>`test_bigint_accepts_only_string_literals`<br>`test_bigint_foreign_key_id_mutation_accepts_existing_wire_values`<br>`test_bigint_rejects_invalid_variables_before_resolver`<br>`test_explicit_bigint_primary_key_keeps_nonnull_wrapper`<br>`test_explicit_scalar_override_keeps_its_declared_contract`<br>`test_generated_input_parses_decimal_strings_to_python_int`<br>`test_generated_model_mutation_persists_exact_bigint`<br>`test_null_bigint_primary_key_propagates_nonnull_error`<br>`test_nullable_bigint_output_keeps_null`<br>`test_positive_bigint_numeric_choice_mutation_accepts_valid_enum`<br>`test_positive_bigint_validation_keeps_nonnegative_constraint`<br>`test_relation_ids_with_explicit_bigint_pk_keep_old_input_type`<br>`test_signed_minimum_and_out_of_range_output` | — | — | 0 |
| `tests/core/test_boolean_dict_json_input.py` [open](tests/core/test_boolean_dict_json_input.py) | A | `test_alias_and_permission_clone_keep_only_surviving_validator`<br>`test_boolean_map_variable_reaches_resolver`<br>`test_custom_equality_annotations_do_not_gain_boolean_map_contract`<br>`test_empty_map_and_optional_null_preserve_outer_rules`<br>`test_exact_boolean_map_uses_json_input`<br>`test_factory_omission_retains_malformed_output_but_invalid_input_stops_factory`<br>`test_field_selection_and_replacement_remove_stale_boolean_map_metadata`<br>`test_fixed_default_omission_and_explicit_same_object_have_distinct_policy`<br>`test_fixed_default_provenance_survives_permission_clone`<br>`test_legacy_dictionary_subclass_default_remains_printable`<br>`test_list_wrapped_boolean_map_keeps_existing_fallback`<br>`test_literals_accept_exact_bool_and_reject_numbers`<br>`test_malformed_fixed_nonobject_default_keeps_omission_policy`<br>`test_supplied_invalid_boolean_map_rejected_before_resolver`<br>`test_unprintable_fixed_dictionary_default_keeps_original_object`<br>`test_unrelated_dictionary_leaf_keeps_string_fallback` | — | — | 0 |
| `tests/core/test_boolean_set_input.py` [open](tests/core/test_boolean_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_metadata`<br>`test_approved_boolean_sets_have_list_introspection_without_warning`<br>`test_boolean_sets_publish_list_and_reach_resolver_as_set`<br>`test_custom_leaf_comparing_equal_to_bool_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_inline_singleton_empty_and_duplicates`<br>`test_invalid_native_boolean_literals_fail_before_resolver`<br>`test_invalid_native_boolean_variables_fail_before_resolver`<br>`test_optional_boolean_sets_keep_omission_and_null`<br>`test_other_set_leaves_and_nested_forms_keep_fallback`<br>`test_required_boolean_set_rejects_omission`<br>`test_variable_singleton_empty_and_duplicates` | — | — | 0 |
| `tests/core/test_choices_enum_member_ambiguity.py` [open](tests/core/test_choices_enum_member_ambiguity.py) | A | `test_ambiguous_members_reject_all_supported_choices_forms`<br>`test_ambiguous_members_reject_generated_input_and_filter`<br>`test_ambiguous_members_reject_public_schema_without_cache_pollution` | — | — | 0 |
| `tests/core/test_choices_enum_name_collisions.py` [open](tests/core/test_choices_enum_name_collisions.py) | A | `test_colliding_choice_descriptions_are_incompatible`<br>`test_compatible_same_name_reuses_registry_enum`<br>`test_distinct_registries_keep_colliding_names_isolated`<br>`test_filter_input_rejects_incompatible_enum`<br>`test_generated_create_input_rejects_incompatible_enum`<br>`test_incompatible_choices_collision_rejects_schema`<br>`test_reordered_compatible_choices_share_public_schema_and_inputs` | — | — | 0 |
| `tests/core/test_decimal_output.py` [open](tests/core/test_decimal_output.py) | A | `test_automatic_decimal_field_executes_as_exact_decimal`<br>`test_automatic_decimal_output_preserves_exact_text`<br>`test_automatic_decimal_primary_key_uses_decimal_nonnull`<br>`test_decimal_filter_literals_and_variables_remain_precise`<br>`test_decimal_primary_key_keeps_nonnull_and_exact_output`<br>`test_explicit_decimal_scalar_and_input_mapping_stay_precise`<br>`test_explicit_float_resolver_retains_legacy_numeric_contract`<br>`test_generated_create_mutation_returns_exact_decimal_output`<br>`test_null_decimal_primary_key_propagates_nonnull_error` | — | — | 0 |
| `tests/core/test_decimal_set_input.py` [open](tests/core/test_decimal_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_metadata`<br>`test_custom_leaf_comparing_equal_to_decimal_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_decimal_sets_publish_list_and_reach_resolver_as_set`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_inline_finite_singleton_empty_and_duplicates`<br>`test_invalid_native_variables_fail_before_resolver`<br>`test_malformed_legacy_defaults_stay_omittable_but_supplied_nonfinite_fails`<br>`test_native_finite_variables_reach_resolver_as_decimal_set`<br>`test_nonfinite_literals_fail_before_resolver`<br>`test_nonfinite_supplied_field_precedes_omitted_sibling_factory`<br>`test_nonfinite_variable_default_never_reaches_resolver`<br>`test_nonfinite_variables_fail_before_resolver`<br>`test_optional_decimal_sets_keep_omission_and_null`<br>`test_other_leaves_and_nested_forms_keep_fallback`<br>`test_pruned_clone_preserves_fixed_default_identity`<br>`test_required_decimal_set_rejects_omission` | — | — | 0 |
| `tests/core/test_email_input_validation.py` [open](tests/core/test_email_input_validation.py) | A | `test_email_syntax_preserves_optional_defaults_length_and_custom_rules`<br>`test_generated_email_choices_preserve_enum_and_validate_values`<br>`test_generated_email_input_rejects_invalid_syntax`<br>`test_nested_email_validation_rolls_back_parent_and_child`<br>`test_non_text_email_choice_reports_field_error`<br>`test_reserved_named_email_keeps_original_error_field` | — | — | 0 |
| `tests/core/test_enum_cache_concurrency.py` [open](tests/core/test_enum_cache_concurrency.py) | A | `test_compile_enum_shares_one_object_after_contended_miss`<br>`test_compile_schema_keeps_reset_and_build_in_one_transaction`<br>`test_compile_type_shares_one_object_after_contended_miss`<br>`test_native_choices_keep_serial_ambiguity_and_registry_isolation`<br>`test_native_choices_reject_incompatible_concurrent_definition`<br>`test_native_choices_reuse_one_object_after_contended_miss` | — | — | 0 |
| `tests/core/test_factory.py` [open](tests/core/test_factory.py) | M | — | — | — | 9 |
| `tests/core/test_fg2_native_schema_compiler.py` [open](tests/core/test_fg2_native_schema_compiler.py) | M | — | — | — | 6 |
| `tests/core/test_fields.py` [open](tests/core/test_fields.py) | M | — | — | — | 14 |
| `tests/core/test_filter_input_name_pascalcase.py` [open](tests/core/test_filter_input_name_pascalcase.py) | M | — | `test_filter_input_name_in_schema_type_map_is_pascalcase` | — | 1 |
| `tests/core/test_float_set_input.py` [open](tests/core/test_float_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_metadata`<br>`test_custom_leaf_comparing_equal_to_float_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_exact_float_sets_have_list_introspection_without_warning`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_float_sets_publish_list_and_reach_resolver_as_set`<br>`test_inline_numeric_singleton_empty_and_duplicates`<br>`test_invalid_native_float_literals_fail_before_resolver`<br>`test_invalid_native_float_variables_fail_before_resolver`<br>`test_literal_overflow_rejects_even_with_malformed_legacy_defaults`<br>`test_literal_overflow_rejects_through_alias_and_pruned_clone`<br>`test_native_numeric_variables_become_float_set`<br>`test_optional_float_sets_keep_omission_and_null`<br>`test_other_set_leaves_and_nested_forms_keep_fallback`<br>`test_overflowing_variable_default_never_reaches_resolver`<br>`test_required_float_set_rejects_omission` | — | — | 0 |
| `tests/core/test_input_compiler_lists_defaults.py` [open](tests/core/test_input_compiler_lists_defaults.py) | M | `test_default_factory_runs_per_coerced_object_without_sdl_default` | — | `test_default_factory_evaluated_once_and_present` | 20 |
| `tests/core/test_input_factory_per_object.py` [open](tests/core/test_input_factory_per_object.py) | A | `test_factory_failures_are_graphql_input_errors_without_private_text`<br>`test_factory_respects_variables_explicit_values_and_field_aliases`<br>`test_literal_field_overwriting_factory_alias_does_not_run_factory`<br>`test_model_derived_input_keeps_omitted_factory_field_absent`<br>`test_nested_inputs_and_inline_aliases_create_distinct_objects`<br>`test_omitted_factory_values_are_fresh_across_graphql_executions`<br>`test_overwritten_wire_alias_only_runs_effective_field_factory`<br>`test_permission_pruned_input_does_not_reinsert_hidden_factory_field`<br>`test_validated_data_factory_remains_a_model_validation_default` | — | — | 0 |
| `tests/core/test_input_typing_fallback_warnings.py` [open](tests/core/test_input_typing_fallback_warnings.py) | A | `test_public_input_mutation_warns_without_changing_wire_behavior`<br>`test_supported_annotations_do_not_gain_fallback_warnings` | — | — | 0 |
| `tests/core/test_int_or_string_union_input.py` [open](tests/core/test_int_or_string_union_input.py) | A | `test_alias_projection_and_permission_pruning`<br>`test_custom_equality_leaf_does_not_match_direct_union`<br>`test_custom_equality_outer_does_not_match_direct_union`<br>`test_direct_union_accepts_matching_literals`<br>`test_direct_union_preserves_variable_branch`<br>`test_direct_union_publishes_shared_scalar`<br>`test_direct_union_rejects_invalid_literal_before_resolver`<br>`test_direct_union_rejects_invalid_variable_before_resolver`<br>`test_factory_values_stay_fresh_and_bad_input_stops_sibling_factory`<br>`test_integer_variable_reaches_resolver_without_string_cast`<br>`test_legacy_dictionary_subclass_default_retains_old_printing`<br>`test_malformed_fixed_default_preserves_omission_and_printing`<br>`test_nullable_union_without_default_still_accepts_null`<br>`test_outer_nullable_direct_union`<br>`test_plain_string_input_is_not_split_or_cast`<br>`test_scalar_name_collision_reports_an_error`<br>`test_selected_and_replaced_fields_keep_final_wire_type`<br>`test_string_fixed_default_keeps_string_branch_in_schema`<br>`test_unapproved_wrapped_union_retains_string_fallback`<br>`test_valid_fixed_default_and_disabled_default_emission` | — | — | 0 |
| `tests/core/test_invalid_mutation_registry_side_effect.py` [open](tests/core/test_invalid_mutation_registry_side_effect.py) | A | `test_rejected_permission_host_does_not_register_user_output`<br>`test_rejected_permission_host_preserves_existing_output`<br>`test_unknown_operation_precedes_permission_error_without_output`<br>`test_valid_mutation_still_uses_one_public_output` | — | — | 0 |
| `tests/core/test_json_fixed_default_metadata.py` [open](tests/core/test_json_fixed_default_metadata.py) | A | `test_bare_json_default_roundtrips_nested_literal_and_pruned_schema`<br>`test_fixed_json_object_default_prints_and_introspects`<br>`test_ineligible_json_values_do_not_gain_metadata_or_new_validation`<br>`test_json_default_factory_is_not_frozen_in_sdl`<br>`test_mismatched_list_default_retains_prior_runtime_shape`<br>`test_non_name_json_default_keeps_runtime_without_invalid_sdl_promise`<br>`test_nullable_list_defaults_publish_metadata_and_preserve_elements`<br>`test_oversized_json_integer_default_preserves_public_runtime`<br>`test_surrogate_json_string_default_preserves_public_runtime` | — | — | 0 |
| `tests/core/test_json_list_default_metadata.py` [open](tests/core/test_json_list_default_metadata.py) | A | `test_empty_list_and_nested_pruned_default_remain_printable`<br>`test_ineligible_fixed_json_list_shapes_stay_internal`<br>`test_invalid_list_defaults_and_factory_keep_legacy_metadata`<br>`test_valid_fixed_json_list_default_prints_and_introspects` | — | — | 0 |
| `tests/core/test_list_output_type.py` [open](tests/core/test_list_output_type.py) | M | — | — | — | 5 |
| `tests/core/test_literal_string_enum_input.py` [open](tests/core/test_literal_string_enum_input.py) | A | `test_compiled_name_and_inherited_public_alias_define_enum_name`<br>`test_literal_defaults_and_factory_are_not_frozen_at_compile_time`<br>`test_member_collision_rejects_ambiguous_literals`<br>`test_public_mutation_uses_literal_enum_and_raw_resolver_value`<br>`test_wrapped_literal_alias_and_nested_input_keep_enum_values` | — | — | 0 |
| `tests/core/test_metadata_enumeration_failures.py` [open](tests/core/test_metadata_enumeration_failures.py) | A | `test_eager_field_recompile_keeps_uncaused_error_unchained`<br>`test_eager_field_recompile_retains_original_cause`<br>`test_lazy_schema_keeps_uncaused_configuration_error`<br>`test_lazy_schema_leaves_generic_type_error_untouched`<br>`test_model_derived_fields_identifies_model_and_preserves_cause`<br>`test_output_compiler_identifies_model_and_preserves_cause`<br>`test_public_schema_rejects_relation_metadata_failure` | — | — | 0 |
| `tests/core/test_native_field_identity_lifetime.py` [open](tests/core/test_native_field_identity_lifetime.py) | A | `test_current_registry_value_is_a_defensive_identity_source`<br>`test_live_native_field_survives_registry_slot_overwrite`<br>`test_model_mutation_builder_tracks_its_actual_native_field`<br>`test_modeltype_builder_tracks_its_actual_native_field`<br>`test_native_field_marker_expires_when_field_dies`<br>`test_stale_identity_key_cannot_admit_an_unrelated_field` | — | — | 0 |
| `tests/core/test_native_root_compiler.py` [open](tests/core/test_native_root_compiler.py) | M | — | — | — | 6 |
| `tests/core/test_native_schema_assembly.py` [open](tests/core/test_native_schema_assembly.py) | M | — | — | — | 14 |
| `tests/core/test_output_compiler_coverage.py` [open](tests/core/test_output_compiler_coverage.py) | M | `test_compile_output_fields_get_fields_exception_aborts_with_cause` | — | `test_compile_output_fields_get_fields_exception_fallback` | 26 |
| `tests/core/test_output_identity_invariant.py` [open](tests/core/test_output_identity_invariant.py) | M | — | — | — | 4 |
| `tests/core/test_positive_input_validation.py` [open](tests/core/test_positive_input_validation.py) | A | `test_custom_schema_preserves_nullable_positive_choice_enum`<br>`test_generated_positive_input_rejects_negative_before_sql`<br>`test_nested_positive_input_rejects_child_before_parent_persists`<br>`test_positive_choices_validate_stored_number_and_keep_enum`<br>`test_positive_field_error_preserves_earlier_sibling_write`<br>`test_positive_validator_preserves_null_and_reports_invalid_choice_value` | — | — | 0 |
| `tests/core/test_recursive_input_lists.py` [open](tests/core/test_recursive_input_lists.py) | A | `test_deep_map_alias_factory_and_permission_clone`<br>`test_deep_typed_maps_keep_strict_leaf_contract`<br>`test_deep_typed_maps_validate_when_defaults_are_not_emitted`<br>`test_ineligible_nested_json_defaults_keep_legacy_metadata`<br>`test_nested_bare_json_keeps_leaf_identity_and_single_list_parity`<br>`test_nested_integer_lists_use_recursive_graphql_wrappers`<br>`test_nested_json_fixed_default_and_factory_keep_runtime_shape`<br>`test_nested_list_nullability_and_singleton_coercion`<br>`test_nullable_nested_bare_json_fixed_defaults_remain_printable`<br>`test_supported_nested_input_and_literal_enum_leaves`<br>`test_typing_list_and_nullable_nested_map_elements`<br>`test_unsupported_nested_leaves_keep_legacy_fallback` | — | — | 0 |
| `tests/core/test_registry_creation_concurrency.py` [open](tests/core/test_registry_creation_concurrency.py) | A | `test_concurrent_list_misses_share_class_graphql_object_and_cache`<br>`test_explicit_list_registration_keeps_last_registration_wins`<br>`test_global_registry_concurrent_cold_calls_share_one_instance`<br>`test_global_registry_failed_construction_retries_and_reset_isolated`<br>`test_list_creation_is_scoped_to_each_model_and_registry` | — | — | 0 |
| `tests/core/test_relation_gfk_native.py` [open](tests/core/test_relation_gfk_native.py) | M | — | `test_choices_seed_sdl_byte_identical_and_enum_renders`<br>`test_seed_native_sdl_byte_identical_to_head_baseline` | — | 14 |
| `tests/core/test_relation_to_many_native.py` [open](tests/core/test_relation_to_many_native.py) | M | — | `test_seed_native_sdl_byte_identical_to_head_baseline` | — | 9 |
| `tests/core/test_relation_to_one_native.py` [open](tests/core/test_relation_to_one_native.py) | M | — | `test_seed_native_sdl_byte_identical_to_head_baseline` | — | 10 |
| `tests/core/test_reserved_model_fields.py` [open](tests/core/test_reserved_model_fields.py) | A | `test_existing_custom_base_config_and_dump_override_remain_active`<br>`test_generated_mutation_persists_reserved_field`<br>`test_inherited_mixed_hooks_preserve_modes_and_caller_base`<br>`test_inherited_model_config_hooks_use_original_field`<br>`test_internal_name_avoids_real_column_and_preserves_inline_validation`<br>`test_original_methods_remain_available_on_generated_class`<br>`test_reserved_default_and_partial_omission_keep_original_presence` | — | — | 0 |
| `tests/core/test_s8c_field_descriptor_graphene_free.py` [open](tests/core/test_s8c_field_descriptor_graphene_free.py) | M | — | — | — | 7 |
| `tests/core/test_s_roots_a_descriptors.py` [open](tests/core/test_s_roots_a_descriptors.py) | M | — | — | — | 12 |
| `tests/core/test_s_roots_c_ok_errors_native.py` [open](tests/core/test_s_roots_c_ok_errors_native.py) | M | — | — | — | 9 |
| `tests/core/test_s_roots_d_converter_native_aware.py` [open](tests/core/test_s_roots_d_converter_native_aware.py) | M | `test_native_scalar_sdl_preserves_approved_bigint_and_decimal` | `test_construct_fields_keeps_relation_descriptors_on_native` | `test_native_scalar_sdl_is_byte_identical_after_skip` | 7 |
| `tests/core/test_s_roots_h_native_mutation_payload.py` [open](tests/core/test_s_roots_h_native_mutation_payload.py) | M | — | — | — | 9 |
| `tests/core/test_s_roots_j_filter_input_collision.py` [open](tests/core/test_s_roots_j_filter_input_collision.py) | M | — | — | — | 4 |
| `tests/core/test_scalars.py` [open](tests/core/test_scalars.py) | M | `TestGdxScalarMap.test_has_8_custom_scalars` | `TestGdxScalarMap.test_singleton_identity`<br>`TestGdxScalarMap.test_total_size` | `TestGdxScalarMap.test_has_7_custom_scalars` | 85 |
| `tests/core/test_schema_fork_threads.py` [open](tests/core/test_schema_fork_threads.py) | A | `test_concurrent_fork_preserves_sibling_output_projections`<br>`test_fork_marker_is_nested_and_restored_after_error`<br>`test_serial_projected_list_keeps_its_node_type` | — | — | 0 |
| `tests/core/test_schema_isolation.py` [open](tests/core/test_schema_isolation.py) | A | `test_isolated_default_pair_restores_after_exception`<br>`test_isolated_default_pair_restores_each_nested_scope`<br>`test_isolated_default_pair_restores_prior_cache` | — | — | 0 |
| `tests/core/test_schema_lazy_fork.py` [open](tests/core/test_schema_lazy_fork.py) | M | — | — | — | 11 |
| `tests/core/test_schema_scoped_registry.py` [open](tests/core/test_schema_scoped_registry.py) | M | — | — | — | 8 |
| `tests/core/test_set_int_input.py` [open](tests/core/test_set_int_input.py) | A | `test_exact_set_int_prints_int_list`<br>`test_fixed_set_default_and_fresh_factory_keep_existing_lifecycle`<br>`test_graphql_singleton_coercion_yields_python_set`<br>`test_inline_set_int_values_use_the_same_boundary`<br>`test_invalid_inline_int_values_fail_before_resolver`<br>`test_invalid_variable_int_values_fail_before_resolver`<br>`test_optional_set_int_keeps_null_and_omission_defaults`<br>`test_other_set_forms_keep_legacy_fallback`<br>`test_permission_clone_keeps_only_surviving_set_conversion`<br>`test_set_field_uses_wire_alias_and_snake_resolver_name`<br>`test_set_int_variable_is_deduplicated_for_resolver` | — | — | 0 |
| `tests/core/test_source_property_attribute_error.py` [open](tests/core/test_source_property_attribute_error.py) | A | `test_absent_django_reverse_one_to_one_stays_nullable_through_property`<br>`test_custom_attribute_lookup_and_nested_required_propagation`<br>`test_explicit_resolver_precedes_source_and_method_body_error_is_unchanged`<br>`test_inherited_source_property_failure_preserves_required_propagation`<br>`test_source_absence_and_successful_dynamic_fallback_remain_nullable`<br>`test_source_property_attribute_error_surfaces_graphql_resolution_error`<br>`test_source_property_failure_keeps_safe_http_diagnostics`<br>`test_unrelated_descriptor_and_dynamic_absence_keep_legacy_null`<br>`test_wrapped_python_property_source_preserves_original_error` | — | — | 0 |
| `tests/core/test_string_set_input.py` [open](tests/core/test_string_set_input.py) | A | `test_alias_and_emitted_field_identity`<br>`test_approved_string_sets_have_list_introspection_without_warning`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_custom_string_set_leaf_comparing_equal_to_str_keeps_fallback`<br>`test_exact_string_sets_publish_list_and_reach_resolver_as_set`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_inline_singleton_empty_and_duplicates`<br>`test_invalid_native_string_literals_fail_before_resolver`<br>`test_invalid_native_string_variables_fail_before_resolver`<br>`test_native_string_values_still_become_a_python_set`<br>`test_only_exclude_include_and_replacement_remove_stale_conversion`<br>`test_optional_string_sets_keep_omission_and_null`<br>`test_permission_clone_projects_only_surviving_string_set_metadata`<br>`test_required_string_set_rejects_omission`<br>`test_unapproved_set_leaves_and_nested_forms_keep_fallback`<br>`test_variable_singleton_empty_and_duplicates` | — | — | 0 |
| `tests/core/test_subscription_native_build.py` [open](tests/core/test_subscription_native_build.py) | M | — | — | — | 5 |
| `tests/core/test_typed_dict_json_input.py` [open](tests/core/test_typed_dict_json_input.py) | A | `test_alias_nested_defaults_and_pruned_fields_use_final_input_surface`<br>`test_inline_typed_map_and_nullability_keep_graphql_coercion`<br>`test_invalid_typed_map_factory_is_rejected_before_resolver`<br>`test_invalid_typed_map_variable_is_rejected_before_resolver`<br>`test_permission_scoped_clone_keeps_only_surviving_typed_map_checks`<br>`test_production_http_preserves_deliberate_graphql_input_error`<br>`test_relation_replacement_does_not_keep_typed_map_validator`<br>`test_typed_dictionary_accepts_json_object_before_mutation`<br>`test_typing_alias_http_error_is_safe`<br>`test_typing_alias_invalid_map_stops_mutation`<br>`test_typing_alias_wrappers_defaults_and_pruned_clone`<br>`test_typing_dict_alias_uses_strict_json_public_input`<br>`test_variable_typed_maps_accept_plain_integers_and_share_json` | — | — | 0 |
| `tests/core/test_typed_string_dict_json_input.py` [open](tests/core/test_typed_string_dict_json_input.py) | A | `test_fixed_string_map_lists_render_only_valid_metadata`<br>`test_http_errors_for_invalid_string_map_are_safe`<br>`test_inline_string_maps_preserve_values_and_reject_nonstrings`<br>`test_invalid_string_map_variable_is_rejected_before_resolver`<br>`test_permission_clone_preserves_surviving_string_map_validator`<br>`test_string_map_spellings_use_strict_json_public_input`<br>`test_wrappers_defaults_factory_and_nested_inputs_keep_string_validation` | — | — | 0 |
| `tests/core/test_types_objecttype.py` [open](tests/core/test_types_objecttype.py) | M | — | — | — | 6 |
| `tests/core/test_typing_set_int_input.py` [open](tests/core/test_typing_set_int_input.py) | A | `test_invalid_typing_set_int_literal_fails_before_resolver`<br>`test_invalid_typing_set_int_variable_fails_before_resolver`<br>`test_pruned_typing_set_int_metadata_keeps_only_visible_field`<br>`test_typing_set_custom_leaf_equality_keeps_string_fallback`<br>`test_typing_set_int_alias_uses_resolver_field_name`<br>`test_typing_set_int_emits_no_fallback_warning`<br>`test_typing_set_int_fixed_and_factory_defaults_keep_lifecycle`<br>`test_typing_set_int_inline_values_use_native_coercion`<br>`test_typing_set_int_list_reaches_resolver_as_set`<br>`test_typing_set_int_optional_omission_and_null_are_unchanged`<br>`test_typing_set_int_prints_int_list`<br>`test_typing_set_int_required_field_stays_required`<br>`test_typing_set_int_variable_uses_native_list_coercion`<br>`test_unrelated_custom_scalar_equality_keeps_string_fallback` | — | — | 0 |
| `tests/core/test_uuid_set_input.py` [open](tests/core/test_uuid_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_uuid_metadata`<br>`test_custom_leaf_comparing_equal_to_uuid_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_fixed_and_factory_uuid_defaults_keep_lifecycle`<br>`test_invalid_uuid_literals_reject_before_mutation`<br>`test_invalid_uuid_variables_reject_before_mutation`<br>`test_malformed_legacy_uuid_defaults_remain_unchanged`<br>`test_native_uuid_literals_use_list_coercion`<br>`test_native_uuid_variables_reach_resolver_as_exact_uuid_set`<br>`test_optional_uuid_sets_keep_omission_and_null`<br>`test_other_set_leaves_and_nested_forms_keep_fallback`<br>`test_required_uuid_set_rejects_omission`<br>`test_uuid_sets_introspect_as_non_null_uuid_lists`<br>`test_uuid_sets_publish_list_and_reach_resolver_as_set` | — | — | 0 |
| `tests/core/test_window_prefetch_native.py` [open](tests/core/test_window_prefetch_native.py) | M | — | — | — | 7 |
| `tests/core/test_wu12_schema_compiler_coverage.py` [open](tests/core/test_wu12_schema_compiler_coverage.py) | M | — | — | — | 15 |
| `tests/core/test_wu9_modeltype_mutation_execution.py` [open](tests/core/test_wu9_modeltype_mutation_execution.py) | M | — | — | — | 5 |
| `tests/core/test_wu9_mutation_execution.py` [open](tests/core/test_wu9_mutation_execution.py) | M | — | — | — | 4 |
| `tests/subscriptions/_transport_schema.py` [open](tests/subscriptions/_transport_schema.py) | M | — | — | — | 0 |
| `tests/subscriptions/test_audit_defects.py` [open](tests/subscriptions/test_audit_defects.py) | M | — | — | — | 16 |
| `tests/subscriptions/test_automatic_best_effort.py` [open](tests/subscriptions/test_automatic_best_effort.py) | A | `test_async_automatic_failure_logs_only_metadata`<br>`test_base_exception_is_not_swallowed`<br>`test_broken_notification_transaction_still_propagates_database_error`<br>`test_database_write_error_remains_strict`<br>`test_explicit_manual_broadcast_remains_strict`<br>`test_failed_delivery_preserves_autocommit_update_and_delete`<br>`test_failed_snapshot_does_not_change_generated_mutation_result`<br>`test_logging_backend_failure_does_not_abort_save`<br>`test_missing_layer_warning_backend_failure_is_best_effort`<br>`test_rollback_discards_automatic_failures_and_snapshots`<br>`test_send_failure_keeps_committed_write_and_later_callback`<br>`test_snapshot_failure_does_not_abort_atomic_save` | — | — | 0 |
| `tests/subscriptions/test_capability_parity.py` [open](tests/subscriptions/test_capability_parity.py) | M | — | — | — | 10 |
| `tests/subscriptions/test_datetime_snapshots.py` [open](tests/subscriptions/test_datetime_snapshots.py) | A | `test_automatic_signal_keeps_original_datetime_after_object_changes`<br>`test_datetime_output_accepts_native_wire_snapshot`<br>`test_different_microseconds_do_not_deliver`<br>`test_equal_datetime_event_delivers_captured_instant`<br>`test_invalid_datetime_wire_values_do_not_pass_a_typed_filter`<br>`test_invalid_native_datetime_output_keeps_scalar_rejection`<br>`test_null_and_ordinary_string_filters_stay_unchanged`<br>`test_unfiltered_full_snapshot_preserves_microseconds_and_output` | — | — | 0 |
| `tests/subscriptions/test_decimal_snapshot_filter.py` [open](tests/subscriptions/test_decimal_snapshot_filter.py) | A | `test_decimal_snapshot_gate_preserves_non_decimal_and_fallback_filters`<br>`test_native_decimal_filter_matches_snapshot_with_different_scale`<br>`test_native_wide_decimal_filter_matches_valid_model_snapshot` | — | — | 0 |
| `tests/subscriptions/test_delete_snapshot_matching.py` [open](tests/subscriptions/test_delete_snapshot_matching.py) | A | `test_missing_or_malformed_private_delete_snapshot_fails_closed`<br>`test_private_capture_excludes_relations_containers_nonfinite_and_custom_backend`<br>`test_private_delete_equality_preserves_typed_scalar_contract`<br>`test_real_delete_uses_signal_time_projected_equality` | — | — | 0 |
| `tests/subscriptions/test_delivery_runtimeerror_diagnostic.py` [open](tests/subscriptions/test_delivery_runtimeerror_diagnostic.py) | A | `test_client_complete_logs_suppressed_delivery_runtimeerror`<br>`test_client_complete_valueerror_keeps_existing_error_frame`<br>`test_delivery_close_runtimeerror_warns_once_and_stays_idempotent` | — | — | 0 |
| `tests/subscriptions/test_float_snapshot_filter.py` [open](tests/subscriptions/test_float_snapshot_filter.py) | A | `test_float_pair_only_changes_finite_exact_equality`<br>`test_real_float_field_exact_event` | — | — | 0 |
| `tests/subscriptions/test_routed_on_commit.py` [open](tests/subscriptions/test_routed_on_commit.py) | A | `test_default_transaction_does_not_capture_secondary_autocommit`<br>`test_missing_layer_warning_follows_secondary_commit`<br>`test_routed_delete_waits_for_commit`<br>`test_routed_save_rollback_discards_notification`<br>`test_routed_save_waits_for_secondary_commit` | — | — | 0 |
| `tests/subscriptions/test_sse_controls.py` [open](tests/subscriptions/test_sse_controls.py) | A | `test_anonymous_request_does_not_access_account_lease_backend`<br>`test_backend_failure_is_pre_stream_503`<br>`test_cancelled_backend_failure_still_propagates_cancellation`<br>`test_cancelled_unknown_admission_cleans_its_token`<br>`test_controls_ship_disabled_with_independent_values`<br>`test_event_heartbeat_and_natural_completion_share_one_source`<br>`test_expired_lease_cannot_be_resurrected`<br>`test_failed_release_is_bounded_by_expiry`<br>`test_healthy_lease_renews_without_heartbeat`<br>`test_heartbeat_remains_off_by_default`<br>`test_idle_heartbeat_keeps_one_source_alive`<br>`test_invalid_control_settings_fail_explicitly`<br>`test_missing_persistent_account_id_is_refused`<br>`test_renewal_failure_finishes_stream_without_backend_secret`<br>`test_second_account_stream_is_rejected_before_source`<br>`test_sixth_stream_is_429_and_existing_five_survive`<br>`test_source_start_failure_releases_reserved_slot`<br>`test_subscribe_result_releases_unused_lease` | — | — | 0 |
| `tests/subscriptions/test_sse_lease_lifecycle.py` [open](tests/subscriptions/test_sse_lease_lifecycle.py) | A | `test_backend_error_after_start_closes_source_before_503`<br>`test_cancelled_startup_revalidation_closes_source_and_lease`<br>`test_consumer_delay_rechecks_before_next_source_read`<br>`test_expired_initial_lease_never_delivers_application_data`<br>`test_overdue_ready_result_is_withheld_on_backend_error`<br>`test_ready_events_still_renew_overdue_lease`<br>`test_repeated_cancellation_settles_admission_before_release` | — | — | 0 |
| `tests/subscriptions/test_startup_cleanup.py` [open](tests/subscriptions/test_startup_cleanup.py) | A | `test_cleanup_failure_does_not_replace_startup_failure`<br>`test_client_complete_during_real_join_discards_membership`<br>`test_disconnect_during_real_join_discards_membership`<br>`test_explicit_close_after_failed_join_stays_closed`<br>`test_failed_second_join_discards_only_its_memberships`<br>`test_failure_before_backend_join_preserves_original_error`<br>`test_same_source_retry_after_failed_join_delivers_and_cleans_up`<br>`test_sse_cancel_during_real_join_discards_membership` | — | — | 0 |
| `tests/subscriptions/test_transport_cold_permissions.py` [open](tests/subscriptions/test_transport_cold_permissions.py) | A | `test_sse_provider_resolves_cold_real_user_permissions`<br>`test_sync_providers_preserve_context_and_error_paths`<br>`test_ws_concurrent_operations_resolve_provider_once`<br>`test_ws_provider_resolves_cold_real_user_permissions`<br>`test_ws_real_auth_handshake_prunes_cold_permissions` | — | — | 0 |
| `tests/subscriptions/test_transport_import_without_settings.py` [open](tests/subscriptions/test_transport_import_without_settings.py) | M | — | — | — | 1 |
| `tests/subscriptions/test_ws_completion_reuse.py` [open](tests/subscriptions/test_ws_completion_reuse.py) | A | `test_complete_waits_for_teardown_then_reuses_same_id`<br>`test_teardown_error_keeps_existing_terminal_frame_sequence` | — | — | 0 |
| `tests/subscriptions/test_ws_on_connect.py` [open](tests/subscriptions/test_ws_on_connect.py) | A | `test_default_ignores_nonmapping_init_payloads`<br>`test_disconnect_cancels_pending_hook`<br>`test_documented_on_connect_callback_is_typed_and_explained`<br>`test_hook_denial_has_no_session_fallback_or_secret_output`<br>`test_hook_identity_replaces_session_for_provider_and_permissions`<br>`test_hook_receives_normalized_payload_and_blocks_ack`<br>`test_hook_rejects_nonmapping_payload_without_invocation`<br>`test_late_callback_result_cannot_replace_identity_or_ack`<br>`test_pending_hook_retains_protocol_errors`<br>`test_pending_hook_times_out_and_cancels_without_late_ack` | — | — | 0 |
| `tests/subscriptions/test_ws_subprotocol.py` [open](tests/subscriptions/test_ws_subprotocol.py) | A | `test_required_subprotocol_is_accepted_among_alternatives`<br>`test_unoffered_subprotocol_is_rejected_before_accept` | — | — | 0 |
| `tests/test_and_many_filtering.py` [open](tests/test_and_many_filtering.py) | A | `test_empty_boolean_operands_and_direct_many_ids`<br>`test_public_and_keeps_relation_object_same_row`<br>`test_public_deeper_and_keeps_one_outer_comment`<br>`test_public_deeper_grouping_and_missing_child_sql_null`<br>`test_public_exact_null_and_isnull_keep_absent_reverse_row`<br>`test_public_m2m_and_branches_match_distinct_rows`<br>`test_public_nested_or_not_and_multihop_correlation`<br>`test_public_paginated_count_and_variables`<br>`test_public_reverse_fk_and_branches_match_distinct_rows`<br>`test_scoped_queryset_alias_projection_and_one_sql`<br>`test_unset_boolean_children_keep_independent_branch` | — | — | 0 |
| `tests/test_async_directive_middleware.py` [open](tests/test_async_directive_middleware.py) | A | `test_http_outer_wrapper_does_not_leak_directive_coroutine`<br>`test_native_async_execution_applies_directive_after_await`<br>`test_sync_http_preserves_borrowed_future_with_directive`<br>`test_sync_http_rejects_async_resolver_with_directive`<br>`test_synchronous_directive_behavior_is_unchanged` | — | — | 0 |
| `tests/test_audit_400_report_contract.py` [open](tests/test_audit_400_report_contract.py) | A | `test_dispositions_keep_important_counterexamples_and_boundaries`<br>`test_examples_and_decision_queue_do_not_turn_boundaries_into_fixes`<br>`test_false_positive_subclaims_keep_counterexample_and_residual`<br>`test_live_redis_proof_is_separate_from_failover_decision`<br>`test_local_docstring_status_distinguishes_current_scan_from_history`<br>`test_primary_table_preserves_exact_original_order_and_status_totals`<br>`test_registry_and_factory_examples_state_the_actual_unit`<br>`test_report_bounds_direct_int_or_string_union_disposition`<br>`test_report_discloses_original_tdd_limit_without_rewriting_history`<br>`test_report_is_navigable_and_release_notes_do_not_claim_release` | — | — | 0 |
| `tests/test_batch_http_error_partial.py` [open](tests/test_batch_http_error_partial.py) | A | `test_first_http_400_has_one_error_entry_and_no_invalidation`<br>`test_later_http_400_keeps_prior_result_and_stops_batch`<br>`test_non_400_http_error_keeps_existing_request_level_envelope`<br>`test_outer_preflight_and_single_error_keep_existing_object_envelope`<br>`test_partial_response_does_not_depend_on_response_cache`<br>`test_validation_error_continues_until_later_transport_error` | — | — | 0 |
| `tests/test_clean_response_http.py` [open](tests/test_clean_response_http.py) | A | `test_clean_response_keeps_zero_false_and_nonempty_values`<br>`test_disabled_cleaning_leaves_the_full_payload_unchanged`<br>`test_selected_operation_controls_introspection_cleaning` | — | — | 0 |
| `tests/test_converter.py` [open](tests/test_converter.py) | M | — | `ConverterTest.test_convert_decimal_field`<br>`FieldConversionIntegrationTest.test_model_to_graphql_type_conversion` | — | 27 |
| `tests/test_converter_branches.py` [open](tests/test_converter_branches.py) | M | `test_decimal_field_converts_to_exact_scalar` | — | `test_decimal_field_converts_to_float` | 30 |
| `tests/test_converter_choices.py` [open](tests/test_converter_choices.py) | M | `test_grouped_colliding_labels_reject_enum_creation`<br>`test_grouped_unique_labels_keep_every_value_in_the_enum`<br>`test_naming_rejects_colliding_names`<br>`test_naming_rejects_colliding_names_across_groups` | — | `test_grouped_colliding_labels_keep_every_value_in_the_enum`<br>`test_naming_dedupes_colliding_names`<br>`test_naming_dedupes_colliding_names_across_groups` | 14 |
| `tests/test_cost_edges.py` [open](tests/test_cost_edges.py) | M | `test_cyclic_fragment_spread_raises_graphql_error` | — | `test_cyclic_fragment_spread_costed_once` | 9 |
| `tests/test_cost_mutation_cache.py` [open](tests/test_cost_mutation_cache.py) | A | `test_late_resolver_error_still_invalidates_after_non_atomic_write`<br>`test_later_refusal_preserves_earlier_executed_batch_mutation`<br>`test_refused_mutation_does_not_invalidate_warmed_query` | — | — | 0 |
| `tests/test_cost_variable_http.py` [open](tests/test_cost_variable_http.py) | A | `test_bound_skip_directive_controls_actual_cost`<br>`test_custom_scalar_and_executor_build_once_before_cost_refusal`<br>`test_high_declared_default_is_checked_when_variable_is_omitted`<br>`test_high_variable_is_rejected_before_resolver_on_validation_cache_hits`<br>`test_input_default_factories_are_not_recoerced_for_bound_cost`<br>`test_no_cost_budget_remains_a_noop`<br>`test_only_selected_operation_is_bound_checked_and_invalid_input_keeps_its_error`<br>`test_small_and_declared_default_variables_remain_accepted`<br>`test_static_fallback_still_rejects_a_small_bound_variable`<br>`test_unselected_operation_still_receives_static_validation` | — | — | 0 |
| `tests/test_datepart_filtering.py` [open](tests/test_datepart_filtering.py) | A | `test_lookup_type_boundaries_and_shared_inputs`<br>`test_numeric_date_parts_have_int_sdl_and_work_over_http` | — | — | 0 |
| `tests/test_datepart_test_portability.py` [open](tests/test_datepart_test_portability.py) | A | `test_datepart_behavior_does_not_assert_local_runtime_identity` | — | — | 0 |
| `tests/test_default_page_size_http.py` [open](tests/test_default_page_size_http.py) | A | `test_default_is_not_a_maximum_http`<br>`test_explicit_none_preserves_each_legacy_paginator_policy`<br>`test_nested_omitted_size_uses_library_default_http`<br>`test_omitted_size_uses_library_default_across_public_paginators`<br>`test_startup_global_override_and_local_size_take_precedence` | — | — | 0 |
| `tests/test_destination_link_compatibility.py` [open](tests/test_destination_link_compatibility.py) | A | `test_malformed_destination_id_uses_structured_missing_error`<br>`test_mti_parent_table_cannot_authorize_child_id`<br>`test_same_concrete_proxy_queryset_still_allows_link`<br>`test_supported_callable_destination_hooks_allow_visible_id`<br>`test_visible_id_remains_linkable_through_supported_queryset_shapes` | — | — | 0 |
| `tests/test_destination_link_scope.py` [open](tests/test_destination_link_scope.py) | A | `test_destination_hook_for_wrong_model_fails_before_write`<br>`test_existing_nested_child_update_is_not_reclassified_as_a_link`<br>`test_hidden_relation_id_has_the_same_error_as_missing`<br>`test_nested_link_is_scoped_before_parent_save`<br>`test_request_registry_not_global_registry_selects_destination_scope`<br>`test_unregistered_destination_adds_no_fk_lookup` | — | — | 0 |
| `tests/test_directive_case_normalization.py` [open](tests/test_directive_case_normalization.py) | A | `test_acronym_block_is_one_word`<br>`test_approved_boundaries_and_nonletters`<br>`test_approved_source_forms_normalize_consistently`<br>`test_each_directive_output_is_idempotent`<br>`test_none_passes_through_and_numeric_value_is_stringified`<br>`test_unapproved_character_forms_keep_legacy_converters` | — | — | 0 |
| `tests/test_directive_date_naive_timezone.py` [open](tests/test_directive_date_naive_timezone.py) | A | `test_missing_components_keep_the_parser_default_across_midnight`<br>`test_named_unknown_and_numeric_offset_text_keep_previous_paths`<br>`test_original_explicit_offset_helper_retains_its_boolean_contract`<br>`test_timezone_less_summer_text_uses_each_active_zone`<br>`test_timezone_less_text_uses_active_zone_for_absolute_and_relative_formats` | — | — | 0 |
| `tests/test_directive_date_null.py` [open](tests/test_directive_date_null.py) | A | `test_date_only_value_still_uses_existing_formatting`<br>`test_date_resolver_none_is_not_a_format_wrapper`<br>`test_invalid_non_null_value_keeps_fallback`<br>`test_nullable_date_field_stays_null`<br>`test_required_nested_date_bubbles_only_to_nullable_parent`<br>`test_required_root_date_uses_normal_non_null_error`<br>`test_valid_datetime_still_formats` | — | — | 0 |
| `tests/test_directive_date_text_time.py` [open](tests/test_directive_date_text_time.py) | A | `test_parser_zeros_microseconds_without_changing_explicit_or_nontext_values`<br>`test_text_default_preserves_active_timezone_with_use_tz_false`<br>`test_text_time_components_are_zero_in_native_graphql`<br>`test_text_time_only_keeps_current_date_across_days` | — | — | 0 |
| `tests/test_directive_date_timezone.py` [open](tests/test_directive_date_timezone.py) | A | `test_absolute_formats_localize_only_explicit_instants`<br>`test_active_zone_applies_to_aware_instants_with_use_tz_false`<br>`test_adjacent_zero_offset_relative_formats_keep_instant`<br>`test_clock_adjacent_zero_offsets_match_z_absolute_zone`<br>`test_dst_conversion_uses_each_instants_active_offset`<br>`test_explicit_offset_before_accepted_abbreviation_is_localized`<br>`test_explicit_offset_before_trailing_year_is_localized`<br>`test_invalid_offset_text_keeps_string_fallback`<br>`test_naive_text_and_typed_inputs_keep_existing_wall_clock`<br>`test_parser_accepted_adjacent_zero_spellings_are_explicit`<br>`test_public_helpers_and_other_input_kinds_are_unchanged`<br>`test_relative_formats_keep_current_path` | — | — | 0 |
| `tests/test_directive_field_locations.py` [open](tests/test_directive_field_locations.py) | A | `test_field_transform_inside_fragment_still_executes`<br>`test_field_transform_order_is_unchanged`<br>`test_guide_states_field_only_contract_with_fragment_migration`<br>`test_invalid_fragment_transform_has_http_error_wire`<br>`test_library_locations_and_builtin_metadata_are_distinct`<br>`test_raw_third_party_directive_keeps_explicit_fragment_locations`<br>`test_spec_builtins_still_control_fragment_and_field_selection`<br>`test_transform_on_fragment_is_rejected_before_resolution` | — | — | 0 |
| `tests/test_directive_numeric_null.py` [open](tests/test_directive_numeric_null.py) | A | `test_currency_custom_symbol_does_not_replace_null`<br>`test_existing_falsy_values_still_format`<br>`test_non_null_bad_value_still_reports_coercion_error`<br>`test_nullable_numeric_directive_preserves_graphql_null`<br>`test_number_cap_still_rejects_null_on_every_field_type`<br>`test_number_invalid_spec_still_rejected_for_null_formatted_field`<br>`test_number_invalid_spec_still_skipped_for_raw_numeric_type`<br>`test_numeric_and_other_nullable_types_keep_null`<br>`test_other_directive_and_default_chain_keep_their_contract`<br>`test_required_null_still_validates_number_spec`<br>`test_required_numeric_directive_bubbles_normally`<br>`test_required_root_numeric_null_bubbles_to_data` | — | — | 0 |
| `tests/test_directives_internals.py` [open](tests/test_directives_internals.py) | M | — | `DirectiveSchemaNoneTest.test_case_directives`<br>`test_number_directive_formats_value`<br>`test_snake_case_directive_resolve` | — | 35 |
| `tests/test_docs_current_behavior_boundaries.py` [open](tests/test_docs_current_behavior_boundaries.py) | A | `test_both_changelogs_scope_these_clarifications_to_documentation`<br>`test_cache_guide_explains_csrf_cookie_round_trip_and_privacy`<br>`test_cache_guide_limits_csrf_cookie_claim_to_decorated_misses`<br>`test_date_guide_states_naive_timezone_assumption_without_changing_scalar`<br>`test_mutation_guide_distinguishes_input_semantics_from_sql_updates`<br>`test_pagination_guide_states_automatic_nullable_order_boundary`<br>`test_subscription_guide_separates_signals_from_manual_broadcast` | — | — | 0 |
| `tests/test_docs_mutation_contract.py` [open](tests/test_docs_mutation_contract.py) | M | `test_docs_qualify_fixed_json_object_default_metadata`<br>`test_guide_documents_direct_int_or_string_union_migration`<br>`test_guide_documents_exact_boolean_map_json_migration`<br>`test_guide_documents_exact_boolean_set_migration`<br>`test_guide_documents_exact_finite_decimal_set_migration`<br>`test_guide_documents_exact_float_set_migration`<br>`test_guide_documents_exact_integer_set_migration`<br>`test_guide_documents_exact_string_set_migration`<br>`test_guide_documents_exact_uuid_set_migration`<br>`test_guide_documents_recursive_supported_input_lists`<br>`test_guide_documents_string_literal_enum_client_migration`<br>`test_guide_documents_typed_integer_map_json_migration`<br>`test_guide_documents_typed_string_map_json_migration` | — | — | 4 |
| `tests/test_docs_types_samples.py` [open](tests/test_docs_types_samples.py) | M | — | `test_sample_builds_behind_the_pages_own_node_type` | — | 3 |
| `tests/test_exact_null_filtering.py` [open](tests/test_exact_null_filtering.py) | A | `test_direct_relation_and_unset_lookup_boundaries`<br>`test_exact_null_field_matrix_and_json_sql_null`<br>`test_native_coercion_preserves_lookup_presence`<br>`test_nullable_choice_and_text_exact_null`<br>`test_public_exact_null_composes_without_changing_empty_nodes`<br>`test_public_literal_exact_null_is_distinct_from_omission`<br>`test_public_variable_exact_null_is_distinct_from_omission`<br>`test_to_many_null_keeps_distinct_and_nested_prefix` | — | — | 0 |
| `tests/test_filtering_internals.py` [open](tests/test_filtering_internals.py) | M | — | `test_is_pk_lookups_non_mapping_is_false` | — | 45 |
| `tests/test_flat_gfk_pruned_security.py` [open](tests/test_flat_gfk_pruned_security.py) | A | `test_explicit_prune_grants_never_widen_from_context_or_reprune`<br>`test_flat_cache_keys_unregistered_target_grants`<br>`test_flat_target_denied_by_actual_model_permission`<br>`test_flat_target_uses_registered_scope_per_request`<br>`test_http_cache_rechecks_same_users_target_grant`<br>`test_invalid_registered_scope_fails_closed`<br>`test_missing_flat_target_stays_null`<br>`test_registered_default_hook_adds_no_membership_query`<br>`test_registered_scope_preserves_join_and_slice_membership`<br>`test_unmarked_schema_keeps_projected_signature` | — | — | 0 |
| `tests/test_floor_nonfinite_error.py` [open](tests/test_floor_nonfinite_error.py) | A | `test_floor_directly_rejects_nonfinite_values`<br>`test_floor_keeps_finite_and_boolean_values`<br>`test_floor_nonnull_error_uses_standard_bubbling`<br>`test_floor_preserves_none_and_malformed_value_policy`<br>`test_floor_public_execution_returns_nullable_error`<br>`test_floor_rejects_numeric_strings_that_coerce_to_nonfinite`<br>`test_other_directives_and_floor_schema_metadata_remain_unchanged` | — | — | 0 |
| `tests/test_fragment_cycles.py` [open](tests/test_fragment_cycles.py) | A | `test_acyclic_spreads_and_missing_targets_do_not_trigger_cycle_check`<br>`test_cyclic_fanout_is_rejected_before_expensive_walks`<br>`test_default_view_rejects_cycle_without_running_resolver`<br>`test_dense_multi_entry_cycle_is_detected`<br>`test_disconnected_fragment_cycle_rejects_direct_cost_analysis`<br>`test_long_fragment_chain_uses_iterative_cycle_check` | — | — | 0 |
| `tests/test_fragment_fanout.py` [open](tests/test_fragment_fanout.py) | M | `test_cyclic_fragment_is_rejected_before_cost_expansion` | — | `test_cyclic_fragment_still_terminates_and_reports_as_before` | 4 |
| `tests/test_generated_delete_security.py` [open](tests/test_generated_delete_security.py) | A | `test_blocked_delete_preserves_sibling_rollback`<br>`test_blocked_generated_delete_hides_collector_details`<br>`test_generated_delete_keeps_success_and_not_found_contract`<br>`test_unclassified_integrity_error_uses_generic_generated_policy` | — | — | 0 |
| `tests/test_generated_integrity_error_redaction.py` [open](tests/test_generated_integrity_error_redaction.py) | A | `test_conditional_unique_violation_is_redacted`<br>`test_direct_backend_keeps_unclassified_integrity_exception`<br>`test_generated_delete_integrity_failure_is_redacted`<br>`test_generated_root_check_failure_is_redacted`<br>`test_generated_success_and_nonintegrity_error_use_http_diagnostics`<br>`test_handwritten_mutation_error_is_safe_in_production_http`<br>`test_mapped_unique_error_keeps_structured_payload`<br>`test_nested_check_failure_rolls_back_without_leaking` | — | — | 0 |
| `tests/test_generated_security_test_portability.py` [open](tests/test_generated_security_test_portability.py) | A | `test_contributor_testing_guidance_keeps_local_runtime_guards_external`<br>`test_generated_security_suites_do_not_require_a_local_graphql_checkout` | — | — | 0 |
| `tests/test_http_execution_error_contract.py` [open](tests/test_http_execution_error_contract.py) | A | `test_batch_execution_error_continues_and_validation_error_remains_scoped`<br>`test_multipart_form_uses_same_execution_envelope`<br>`test_nonnull_root_execution_error_has_null_data_in_both_views`<br>`test_null_execution_envelope_survives_cleaning_and_production_formatting`<br>`test_null_execution_errors_are_not_cached_or_replayed`<br>`test_nullable_error_and_success_keep_existing_data_and_cost`<br>`test_request_errors_stay_http_400_without_data` | — | — | 0 |
| `tests/test_http_internal_error_diagnostics.py` [open](tests/test_http_internal_error_diagnostics.py) | A | `test_custom_view_formatter_remains_an_explicit_override`<br>`test_debug_and_shared_transport_formatter_keep_existing_diagnostics`<br>`test_ids_are_unique_and_wrapped_internal_extensions_are_dropped`<br>`test_internal_failures_have_safe_http_diagnostics_and_correlated_logs`<br>`test_logger_failure_cannot_change_safe_http_response`<br>`test_nonnull_error_keeps_null_data_and_safe_message_in_every_view`<br>`test_production_error_documentation_example_matches_the_wire_contract`<br>`test_public_errors_validation_and_http_parse_errors_keep_their_contract`<br>`test_shared_formatter_is_unchanged_in_production` | — | — | 0 |
| `tests/test_introspection_docs.py` [open](tests/test_introspection_docs.py) | A | `test_introspection_setting_requires_installed_middleware`<br>`test_security_guide_installs_middleware_before_blocking_introspection` | — | — | 0 |
| `tests/test_introspection_fragments.py` [open](tests/test_introspection_fragments.py) | A | `test_ambiguous_reachable_fragment_name_fails_closed`<br>`test_http_disabled_cleaning_remains_unchanged`<br>`test_http_mixed_fragment_still_cleans_ordinary_data`<br>`test_http_named_fragment_introspection_keeps_null_and_empty_lists`<br>`test_malformed_root_selections_fail_closed`<br>`test_mixed_or_unresolved_root_fragments_fail_closed`<br>`test_reachable_root_fragments_are_introspection`<br>`test_repeated_shared_fragments_expand_once`<br>`test_selected_operation_ignores_unreachable_fragments` | — | — | 0 |
| `tests/test_invalid_id_contract.py` [open](tests/test_invalid_id_contract.py) | A | `test_custom_primary_key_prepared_once_with_generic_error`<br>`test_custom_primary_key_renamed_argument_keeps_safe_public_error`<br>`test_existing_missing_exception_boundary_in_hooks_is_preserved`<br>`test_existing_numeric_and_null_coercion_remain_orm_owned`<br>`test_get_node_rejects_malformed_integer_id`<br>`test_hidden_row_still_looks_missing`<br>`test_http_production_wire_keeps_deliberate_error`<br>`test_malformed_id_in_generated_retrieve_field`<br>`test_malformed_integer_id_has_safe_public_error`<br>`test_malformed_uuid_id_has_safe_public_error`<br>`test_non_null_field_bubbles_the_deliberate_error`<br>`test_retrieve_authorization_error_precedes_id_conversion`<br>`test_unrelated_queryset_errors_are_not_relabelled`<br>`test_uuid_missing_and_valid_ids_keep_lookup_behavior`<br>`test_valid_missing_and_char_primary_keys_keep_orm_meaning` | — | — | 0 |
| `tests/test_json_nonfinite_input.py` [open](tests/test_json_nonfinite_input.py) | A | `test_available_variable_literal_path_rejects_nonfinite`<br>`test_defaults_missing_members_and_explicit_null_keep_their_contract`<br>`test_finite_and_string_values_keep_identity_and_wire_shape`<br>`test_http_input_error_uses_graphql_error_wire`<br>`test_huge_finite_int_and_native_container_aliases_are_not_rewritten`<br>`test_literal_overflow_rejected_before_resolver`<br>`test_nested_variable_infinity_rejected_before_resolver`<br>`test_nonfinite_default_literal_rejected`<br>`test_overflow_literal_shapes_fail_before_resolver`<br>`test_raw_output_and_json_string_scalar_remain_separate`<br>`test_variable_nonfinite_values_fail_before_resolver` | — | — | 0 |
| `tests/test_json_raw_missing_list_null.py` [open](tests/test_json_raw_missing_list_null.py) | A | `test_defaulted_and_explicit_null_variables_remain_distinct`<br>`test_http_view_emits_json_null_without_undefined_sentinel`<br>`test_json_string_scalar_is_not_reinterpreted`<br>`test_nested_lists_preserve_slots_while_object_keys_stay_omitted`<br>`test_omitted_variable_keeps_null_slot_on_json_wire`<br>`test_ordinary_typed_list_and_direct_missing_argument_stay_unchanged`<br>`test_supplied_json_variable_values_keep_their_shape` | — | — | 0 |
| `tests/test_multipart_file_size_http.py` [open](tests/test_multipart_file_size_http.py) | A | `test_cache_active_multipart_cannot_bypass_file_cap`<br>`test_csrf_header_refusal_precedes_file_cap`<br>`test_every_repeated_file_is_checked`<br>`test_graphiql_success_path_still_checks_files`<br>`test_independent_total_body_cap_still_rejects_first`<br>`test_malformed_multipart_batch_keeps_400_before_file_cap`<br>`test_multiple_files_are_not_summed`<br>`test_oversized_file_prevents_mutation_resolver`<br>`test_oversized_multipart_file_is_rejected_before_resolver`<br>`test_single_file_boundary_and_uncapped_mode`<br>`test_temporary_uploaded_file_is_rejected_and_closed` | — | — | 0 |
| `tests/test_native_filtering.py` [open](tests/test_native_filtering.py) | M | — | `test_to_q_pk_lookups_on_relation`<br>`test_to_q_pk_lookups_on_to_many_relation_flag_distinct` | — | 28 |
| `tests/test_negative_page_count_error_http.py` [open](tests/test_negative_page_count_error_http.py) | A | `test_failed_count_does_not_use_length_or_iteration`<br>`test_failed_negative_page_count_is_generic_and_does_not_fetch_rows`<br>`test_list_fallback_and_unrelated_count_errors_are_unchanged`<br>`test_positive_page_does_not_attempt_count_when_not_selected` | — | — | 0 |
| `tests/test_nested_child_permissions.py` [open](tests/test_nested_child_permissions.py) | M | — | `TestNestedChildPermissions.test_forward_link_path_is_not_gated`<br>`TestNestedChildPermissions.test_m2m_link_path_is_not_gated` | — | 7 |
| `tests/test_nested_edges.py` [open](tests/test_nested_edges.py) | M | — | `test_relation_kind_reverse_one_for_reverse_o2o` | — | 7 |
| `tests/test_nested_sd4_orphan_scope.py` [open](tests/test_nested_sd4_orphan_scope.py) | A | `test_existing_orphan_requires_child_update_host`<br>`test_existing_owned_and_new_children_keep_prior_paths`<br>`test_later_orphan_denial_rolls_back_earlier_sibling_write`<br>`test_parent_create_keeps_new_child_path`<br>`test_unrelated_registry_cannot_supply_child_update_host`<br>`test_update_host_preserves_scope_and_child_permission`<br>`test_update_serving_mutation_host_admits_visible_orphan` | — | — | 0 |
| `tests/test_optimizer_coverage.py` [open](tests/test_optimizer_coverage.py) | M | — | — | — | 97 |
| `tests/test_optimizer_fragment_fanout.py` [open](tests/test_optimizer_fragment_fanout.py) | A | `test_bounded_promotion_iterator_handles_absent_and_cyclic_internal_inputs`<br>`test_interleaved_fragment_restores_last_annotation_alias_value`<br>`test_interleaved_fragment_restores_last_prefetch_annotation_plan`<br>`test_promotion_consumer_bounds_repeated_spreads_without_changing_rows`<br>`test_reused_fragment_keeps_distinct_relation_path_contexts`<br>`test_valid_repeated_fragment_graph_has_bounded_optimizer_visits` | — | — | 0 |
| `tests/test_optimizer_merged_field_nodes.py` [open](tests/test_optimizer_merged_field_nodes.py) | A | `MergedRootFieldNodesTest.test_direct_and_fragment_root_fields_share_relation_and_column_plan`<br>`MergedRootFieldNodesTest.test_second_root_node_promotes_annotated_relation` | — | — | 0 |
| `tests/test_optimizer_perf.py` [open](tests/test_optimizer_perf.py) | M | — | `OnlyNarrowingFmapCacheTest.test_only_narrowing_memoizes_get_fields` | — | 11 |
| `tests/test_optimizer_phase_c.py` [open](tests/test_optimizer_phase_c.py) | M | — | `TestBuildWindowPrefetchPreChecks.test_precheck_returns_none_when_m2m`<br>`TestBuildWindowPrefetchPreChecks.test_precheck_returns_none_when_not_one_to_many`<br>`TestC3FallbackRegressions.test_fallback_unbounded_no_window_sql`<br>`TestWalkerPaginationArgExtraction.test_g2_custom_resolver_falls_back_without_crash` | — | 50 |
| `tests/test_optimizer_phase_d.py` [open](tests/test_optimizer_phase_d.py) | M | — | — | — | 37 |
| `tests/test_optimizer_phase_e.py` [open](tests/test_optimizer_phase_e.py) | M | — | — | — | 25 |
| `tests/test_ordering_provenance.py` [open](tests/test_ordering_provenance.py) | M | `DivergentAllowlistStampTests.test_hidden_column_is_not_orderable_with_the_canonical_node` | — | `DivergentAllowlistStampTests.test_hidden_column_is_not_orderable_when_the_node_registers_late` | 7 |
| `tests/test_output_registration_conflict.py` [open](tests/test_output_registration_conflict.py) | A | `test_distinct_registries_may_publish_distinct_author_views`<br>`test_identical_class_reregistration_is_idempotent`<br>`test_input_registration_and_proxy_model_keys_remain_distinct`<br>`test_model_mutation_reuses_registered_public_output`<br>`test_non_registering_internal_view_does_not_replace_public_type`<br>`test_public_and_admin_user_schemas_bind_post_user_independently`<br>`test_registered_node_remains_list_and_filter_target`<br>`test_second_public_author_type_fails_without_shadowing_nested_author` | — | — | 0 |
| `tests/test_output_selector_validation.py` [open](tests/test_output_selector_validation.py) | A | `test_bare_string_output_selector_is_rejected`<br>`test_corrected_exclusion_hides_sensitive_user_field`<br>`test_custom_slug_key_and_empty_selector_are_valid`<br>`test_declared_custom_only_output_remains_valid`<br>`test_generic_foreign_key_and_set_selectors_remain_supported`<br>`test_non_name_selectors_fail_in_configuration`<br>`test_noninterface_declared_wire_name_keeps_existing_contract`<br>`test_one_shot_selector_is_reused_for_projection`<br>`test_reverse_accessor_and_query_name_selectors_remain_valid`<br>`test_unknown_output_selector_fails_before_registration`<br>`test_valid_model_and_declared_selectors_remain_supported` | — | — | 0 |
| `tests/test_pagination_cursor_typed_http.py` [open](tests/test_pagination_cursor_typed_http.py) | A | `TestTypedCursorHttp.test_generated_root_cursor_and_nested_relation_http`<br>`TestTypedCursorHttp.test_malformed_cursor_is_existing_graphql_error_envelope`<br>`TestTypedCursorHttp.test_tied_boundaries_match_orm_in_both_orderings`<br>`TestTypedCursorHttp.test_typed_invalid_cursor_direct_pagination_and_page_info`<br>`TestTypedCursorHttp.test_typed_invalid_cursor_value_http_error`<br>`TestTypedCursorHttp.test_unapproved_other_type_coercion_fallback_is_unchanged` | — | — | 0 |
| `tests/test_pagination_default_ordering.py` [open](tests/test_pagination_default_ordering.py) | M | `DefaultPaginatorOrderingTest.test_default_paginator_has_library_size` | — | `DefaultPaginatorOrderingTest.test_default_paginator_is_unbounded` | 24 |
| `tests/test_pagination_none_docs_contract.py` [open](tests/test_pagination_none_docs_contract.py) | A | `test_all_none_and_bounded_controls_match_existing_paginators`<br>`test_all_none_table_names_each_paginator_outcome` | — | — | 0 |
| `tests/test_pagination_null_order_parity.py` [open](tests/test_pagination_null_order_parity.py) | A | `test_explicit_orm_null_placement_remains_authoritative`<br>`test_malformed_prefix_is_not_normalized_into_a_valid_column`<br>`test_multifield_priority_and_relation_name_remain_intact`<br>`test_nested_nullable_order_matches_window_and_plain_prefetch`<br>`test_nullable_queryset_and_materialized_pages_agree` | — | — | 0 |
| `tests/test_pagination_page_null_http.py` [open](tests/test_pagination_page_null_http.py) | A | `test_direct_page_null_normalizes_both_paths`<br>`test_existing_page_boundaries_http`<br>`test_explicit_null_page_matches_omission_http`<br>`test_nested_null_page_reaches_materialized_list_without_optimizer`<br>`test_omitted_nullable_variable_keeps_default_http` | — | — | 0 |
| `tests/test_pagination_pk_tiebreak.py` [open](tests/test_pagination_pk_tiebreak.py) | A | `PkTiebreakOrderingTest.test_col_pk_expression_is_not_duplicated`<br>`PkTiebreakOrderingTest.test_explicit_descending_pk_is_not_overridden`<br>`PkTiebreakOrderingTest.test_explicit_id_inside_multiple_terms_is_not_duplicated`<br>`PkTiebreakOrderingTest.test_http_offset_pages_keep_equal_name_rows_disjoint`<br>`PkTiebreakOrderingTest.test_internal_pk_does_not_expand_client_ordering_allowlist`<br>`PkTiebreakOrderingTest.test_limit_offset_db_appends_pk_to_client_order`<br>`PkTiebreakOrderingTest.test_materialized_model_list_uses_same_tie_break`<br>`PkTiebreakOrderingTest.test_model_meta_ordering_survives_db_and_materialized_paths`<br>`PkTiebreakOrderingTest.test_natural_pk_alias_and_attname_keep_explicit_direction`<br>`PkTiebreakOrderingTest.test_natural_pk_uses_field_name_not_id`<br>`PkTiebreakOrderingTest.test_nested_hidden_pk_is_internal_not_client_ordering`<br>`PkTiebreakOrderingTest.test_no_order_uses_pk_and_page_materialized_rows_match`<br>`PkTiebreakOrderingTest.test_page_db_appends_pk_to_client_order`<br>`PkTiebreakOrderingTest.test_public_graphql_pages_cover_equal_name_rows_once`<br>`PkTiebreakOrderingTest.test_queryset_default_and_explicit_order_are_preserved`<br>`PkTiebreakOrderingTest.test_queryset_expression_order_stays_ahead_of_pk`<br>`PkTiebreakOrderingTest.test_queryset_extra_ordering_stays_ahead_of_pk`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_falls_back_for_unsupported_hook_terms`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_keeps_extra_queryset_ordering`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_keeps_hook_queryset_ordering`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_keeps_model_meta_ordering`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_row_number_uses_pk_secondary`<br>`PkTiebreakOrderingTest.test_unbounded_no_order_preserves_original_queryset_cache`<br>`PkTiebreakOrderingTest.test_unbounded_no_order_retains_meta_ordering_without_a_clone`<br>`PkTiebreakOrderingTest.test_unsupported_meta_list_ordering_keeps_pk_fallback` | — | — | 0 |
| `tests/test_pagination_server_order.py` [open](tests/test_pagination_server_order.py) | A | `test_extra_alias_and_dotted_server_terms_remain_orm_owned`<br>`test_extra_alias_nested_path_falls_back_without_losing_primary_order`<br>`test_reversed_orm_expression_and_requested_order_stay_distinct`<br>`test_server_queryset_order_precedes_ascending_pk` | — | — | 0 |
| `tests/test_permission_cache_lock_split.py` [open](tests/test_permission_cache_lock_split.py) | A | `test_clear_waits_for_build_then_removes_entry`<br>`test_cold_builds_remain_serial_and_same_key_is_shared`<br>`test_reentrant_clear_and_failed_prune_leave_cache_recoverable`<br>`test_warm_hit_completes_before_unrelated_cold_prune_is_released` | — | — | 0 |
| `tests/test_playground_310_contract.py` [open](tests/test_playground_310_contract.py) | M | `test_cursor_pagination_readme_matches_playground_settings` | — | — | 1 |
| `tests/test_query_cost.py` [open](tests/test_query_cost.py) | M | — | `CostEngineTest.test_default_multiplier_when_unbounded`<br>`CostEngineTest.test_unbounded_list_warns_once`<br>`CostViewWiringTest.test_get_query_cost_returns_payload` | — | 18 |
| `tests/test_query_optimization.py` [open](tests/test_query_optimization.py) | M | — | — | — | 14 |
| `tests/test_registry.py` [open](tests/test_registry.py) | M | — | `RegistryKeyCollisionTest.test_register_rejects_foreign_registry` | — | 11 |
| `tests/test_relation_lookup_name_collision.py` [open](tests/test_relation_lookup_name_collision.py) | A | `test_nested_lookup_name_and_direct_pk_exact` | — | — | 0 |
| `tests/test_relation_scope_hatch.py` [open](tests/test_relation_scope_hatch.py) | M | — | — | — | 8 |
| `tests/test_replace_output_limit.py` [open](tests/test_replace_output_limit.py) | A | `test_replace_exact_python_semantics`<br>`test_replace_limit_default_is_one_million`<br>`test_replace_limit_none_preserves_uncapped_behavior`<br>`test_replace_limit_rejects_noninteger_values`<br>`test_replace_limit_rejects_nonpositive_values`<br>`test_replace_nonnull_error_bubbles`<br>`test_replace_preserves_null_field`<br>`test_replace_rejects_already_oversized_noop`<br>`test_replace_rejects_expansion_before_returning_result`<br>`test_replace_rejects_without_calling_replace` | — | — | 0 |
| `tests/test_routed_nested_atomic.py` [open](tests/test_routed_nested_atomic.py) | A | `test_custom_backend_keeps_existing_create_instance_contract`<br>`test_explicit_divergent_through_router_rejects_before_any_write`<br>`test_instance_routed_create_initializes_once_and_commits_only_on_success`<br>`test_instance_routed_forward_and_m2m_writes_share_parent_boundary`<br>`test_late_failure_after_real_writes_rolls_back_chosen_alias`<br>`test_later_child_failure_rolls_back_create`<br>`test_later_child_failure_rolls_back_update`<br>`test_nested_create_succeeds_on_own_alias`<br>`test_nested_routing_contract_documents_native_instance_create_boundary`<br>`test_populated_parent_routes_entire_nested_create_to_one_alias`<br>`test_post_id_divergent_through_router_rolls_back_without_foreign_sql` | — | — | 0 |
| `tests/test_sd1_m2m_output_scope.py` [open](tests/test_sd1_m2m_output_scope.py) | A | `test_custom_through_and_reverse_accessor_scope_m2m_output`<br>`test_declared_m2m_count_only_is_scoped`<br>`test_declared_m2m_members_follow_destination_scope`<br>`test_m2m_count_precedes_nested_page_limit`<br>`test_m2m_scope_uses_current_request_and_compiled_schema`<br>`test_optimized_m2m_scope_uses_source_database_alias`<br>`test_optimized_scoped_m2m_prefetch_does_not_grow_per_parent`<br>`test_reverse_m2m_count_only_is_scoped`<br>`test_reverse_m2m_members_follow_destination_scope`<br>`test_unscoped_prefetch_cache_cannot_authorize_m2m_output` | — | — | 0 |
| `tests/test_sd1_o2o_output_scope.py` [open](tests/test_sd1_o2o_output_scope.py) | A | `test_automatic_o2o_outputs_hide_only_destinations`<br>`test_cached_o2o_values_are_not_visibility_evidence`<br>`test_default_reverse_o2o_accessor_uses_destination_scope`<br>`test_explicit_relation_resolver_is_not_reclassified_as_automatic`<br>`test_nested_o2o_outputs_scope_each_hop`<br>`test_o2o_output_hook_failure_does_not_serve_hidden_child`<br>`test_reverse_o2o_destination_scope_reaches_hidden_child_assertion` | — | — | 0 |
| `tests/test_sd1_relation_read_scope.py` [open](tests/test_sd1_relation_read_scope.py) | A | `test_automatic_fk_visibility_matches_destination_scope`<br>`test_automatic_reverse_fk_filters_before_count_and_page`<br>`test_cached_fk_fallback_applies_destination_scope`<br>`test_reverse_fk_query_costs_are_explicit`<br>`test_reverse_fk_window_pages_visible_rows_only`<br>`test_scoped_and_default_fk_query_costs_are_explicit`<br>`test_scoped_fk_prefetch_is_batched_and_aliases_share_visibility`<br>`test_scoped_reverse_fk_plain_prefetch_ignores_unscoped_cache` | — | — | 0 |
| `tests/test_sd1_reverse_accessor_scope.py` [open](tests/test_sd1_reverse_accessor_scope.py) | A | `test_hidden_reverse_child_cannot_bypass_destination_scope` | — | — | 0 |
| `tests/test_sd2_forward_fk_filter_scope.py` [open](tests/test_sd2_forward_fk_filter_scope.py) | A | `test_boolean_composition_does_not_prune_unrelated_matches`<br>`test_direct_fk_ids_and_omission_keep_source_contract`<br>`test_each_forward_fk_chain_hop_is_scoped`<br>`test_empty_forward_fk_traversal_remains_noop`<br>`test_forward_fk_filter_uses_request_destination_scope`<br>`test_incompatible_destination_hook_fails_closed`<br>`test_missing_compiled_destination_type_fails_closed`<br>`test_nullable_fk_traversal_preserves_real_null`<br>`test_nullable_forward_fk_negative_filter_keeps_real_null`<br>`test_overridden_native_backend_keeps_two_argument_seam`<br>`test_schema_and_request_isolation`<br>`test_scope_failure_is_not_unscoped_fallback` | — | — | 0 |
| `tests/test_sd2_forward_o2o_filter_scope.py` [open](tests/test_sd2_forward_o2o_filter_scope.py) | A | `test_boolean_and_empty_forward_nodes_keep_visible_sources`<br>`test_forward_and_reverse_destination_policies`<br>`test_forward_scope_errors_fail_closed`<br>`test_null_and_direct_id_controls`<br>`test_reverse_then_forward_one_to_one_scopes_each_destination` | — | — | 0 |
| `tests/test_sd2_m2m_filter_scope.py` [open](tests/test_sd2_m2m_filter_scope.py) | A | `test_custom_through_fields_scope_both_m2m_directions`<br>`test_declared_reverse_m2m_accessor_does_not_reopen_filter_path`<br>`test_direct_m2m_target_ids_respect_both_destination_hooks`<br>`test_empty_m2m_child_is_noop`<br>`test_forward_m2m_ids_use_visible_destination_universe`<br>`test_forward_m2m_requires_visible_matching_target`<br>`test_m2m_absence_and_null_match_only_visible_universe`<br>`test_m2m_boolean_grouping_uses_visible_witnesses`<br>`test_m2m_hook_exception_fails_closed`<br>`test_m2m_hook_wrong_alias_fails_closed`<br>`test_m2m_not_complements_visible_parent_matches`<br>`test_m2m_request_visibility_changes_without_cache`<br>`test_m2m_scope_keeps_one_set_based_query_per_list`<br>`test_m2m_scope_uses_active_compiled_registry`<br>`test_nested_m2m_independent_and_keeps_one_visible_outer_target`<br>`test_nested_m2m_scopes_each_hop`<br>`test_reverse_m2m_ids_use_visible_destination_universe`<br>`test_reverse_m2m_not_and_unrelated_or_preserve_parent_set`<br>`test_reverse_m2m_query_name_follows_automatic_accessor`<br>`test_reverse_m2m_requires_visible_matching_target` | — | — | 0 |
| `tests/test_sd2_reverse_fk_filter_scope.py` [open](tests/test_sd2_reverse_fk_filter_scope.py) | A | `test_declared_reverse_accessor_cannot_reopen_filter_path`<br>`test_reverse_absence_nested_forward_null`<br>`test_reverse_fk_absence_and_null_predicates`<br>`test_reverse_fk_and_retains_split_and_grouped_witnesses`<br>`test_reverse_fk_boolean_and_nested_forward_hop`<br>`test_reverse_fk_boolean_null_branch_accepts_hidden_only`<br>`test_reverse_fk_direct_child_ids_are_destination_scoped`<br>`test_reverse_fk_empty_filter_and_hook_failure`<br>`test_reverse_fk_nested_boolean_null_and_match_branches`<br>`test_reverse_fk_nested_independent_and_keeps_one_visible_child`<br>`test_reverse_fk_not_complements_matching_parent_set`<br>`test_reverse_fk_positive_requires_visible_matching_child`<br>`test_reverse_fk_resolves_default_and_named_accessors`<br>`test_reverse_fk_scope_is_one_composed_query_not_per_parent`<br>`test_reverse_fk_source_and_destination_scopes_are_distinct`<br>`test_reverse_fk_uses_active_registry_without_scope_leak`<br>`test_reverse_fk_wrong_alias_hook_fails_closed`<br>`test_reverse_fk_wrong_model_hook_fails_closed` | — | — | 0 |
| `tests/test_serializer_type_custom_fields.py` [open](tests/test_serializer_type_custom_fields.py) | M | — | `CustomFieldsConflictTest.test_warns_and_skips_when_object_type_already_registered` | — | 8 |
| `tests/test_settings.py` [open](tests/test_settings.py) | M | — | `SettingsTest.test_default_settings` | — | 7 |
| `tests/test_settings_minimum_zero.py` [open](tests/test_settings_minimum_zero.py) | A | `test_approved_boundary_values_are_retained`<br>`test_default_is_unchanged`<br>`test_existing_nonnegative_bool_and_noninteger_policy_is_unchanged`<br>`test_negative_integer_limit_fails_on_public_setting_read`<br>`test_negative_limit_is_validated_lazily` | — | — | 0 |
| `tests/test_settings_tables_contract.py` [open](tests/test_settings_tables_contract.py) | A | `test_core_settings_rows_remain_in_one_markdown_table` | — | — | 0 |
| `tests/test_skip_include_directives.py` [open](tests/test_skip_include_directives.py) | M | — | — | — | 61 |
| `tests/test_success_response_cache.py` [open](tests/test_success_response_cache.py) | A | `test_cookie_bearing_queries_bypass_response_cache`<br>`test_disabled_cache_executes_without_response_cache_io`<br>`test_legacy_failed_entry_is_ignored_and_replaced`<br>`test_malformed_legacy_entry_is_ignored`<br>`test_partial_execution_error_recovers_then_success_hits`<br>`test_validation_error_is_not_stored_or_reused` | — | — | 0 |
| `tests/test_sync_async_http.py` [open](tests/test_sync_async_http.py) | A | `test_async_middleware_is_rejected_without_running_its_body`<br>`test_async_mutation_is_rejected_with_transaction_policy`<br>`test_async_resolver_returns_json_500_and_closes_owned_coroutines`<br>`test_callable_object_middleware_remains_active`<br>`test_custom_executor_owned_coroutine_is_closed`<br>`test_executor_exception_after_async_value_closes_owned_coroutine`<br>`test_falsey_object_middleware_is_ignored_like_native`<br>`test_sync_middleware_closes_nested_owned_resolver_coroutines`<br>`test_sync_middleware_keeps_borrowed_coroutine_open` | — | — | 0 |
| `tests/test_track2_optimizer.py` [open](tests/test_track2_optimizer.py) | M | `test_gfk_union_wrapper_bucket_walk_bounds_cycles_and_excludes_foreign_types`<br>`test_gfk_union_wrapper_inline_and_named_fragments_batch_targets` | `test_gfk_union_proxy_members_no_duplicate_content_type_valueerror` | — | 16 |
| `tests/test_utils.py` [open](tests/test_utils.py) | M | `UtilsTest.test_clean_dict_retains_root_scalars_and_prunes_emptied_lists`<br>`UtilsTest.test_clean_dict_retains_zero_and_false_without_mutating_input` | — | — | 4 |
| `tests/test_view_base.py` [open](tests/test_view_base.py) | M | `test_view_constructor_does_not_use_optimized_away_validation`<br>`test_view_constructor_rejects_conflicting_modes`<br>`test_view_constructor_rejects_invalid_schema` | — | — | 20 |
| `tests/test_view_layer_audit.py` [open](tests/test_view_layer_audit.py) | M | — | `MultipartBodyGuardTest.test_multipart_upload_above_data_upload_max_memory_size_is_accepted` | — | 12 |
| `tests/test_views_atomic_errors.py` [open](tests/test_views_atomic_errors.py) | A | `test_atomic_execution_error_does_not_invalidate_rolled_back_write`<br>`test_atomic_mutations_execution_error_rolls_back_native_write`<br>`test_atomic_mutations_explicit_flag_still_rolls_back`<br>`test_atomic_requests_execution_error_rolls_back_native_write`<br>`test_atomic_requests_explicit_flag_rolls_back_without_graphql_error`<br>`test_atomic_success_commits_and_invalidates`<br>`test_batch_failed_atomic_operation_then_success_invalidates_once`<br>`test_native_ok_false_does_not_retroactively_rollback_prior_root`<br>`test_nonatomic_execution_error_keeps_durable_write_and_invalidates` | — | — | 0 |
| `tests/test_views_body_cap_cache.py` [open](tests/test_views_body_cap_cache.py) | A | `CacheActiveBodyCapTests.test_authentication_denial_precedes_body_cap`<br>`CacheActiveBodyCapTests.test_body_at_cap_still_warms_and_hits_response_cache`<br>`CacheActiveBodyCapTests.test_cache_disabled_retains_early_base_view_rejection`<br>`CacheActiveBodyCapTests.test_disabled_cap_allows_the_same_query`<br>`CacheActiveBodyCapTests.test_get_with_invalid_body_keeps_bad_request_not_body_cap`<br>`CacheActiveBodyCapTests.test_oversized_cache_active_body_is_rejected_before_parse_or_cache`<br>`CacheActiveBodyCapTests.test_spoofed_low_content_length_still_rejects_actual_body`<br>`CacheActiveBodyCapTests.test_tightened_cap_rejects_an_already_cached_query` | — | — | 0 |
| `tests/test_views_cache_cookie_bypass.py` [open](tests/test_views_cache_cookie_bypass.py) | M | `CookieCacheBypassTest.test_issued_csrf_cookie_bypasses_next_server_cache_lookup` | — | — | 4 |
| `tests/test_views_cache_isolation.py` [open](tests/test_views_cache_isolation.py) | M | `InvalidResponseCacheTest.test_empty_http_response_is_not_cached` | — | `SentinelHitCheckTest.test_empty_cached_response_is_served_without_re_executing` | 11 |
| `tests/test_views_cache_key_framing.py` [open](tests/test_views_cache_key_framing.py) | A | `test_comment_boundary_cannot_select_another_cached_operation`<br>`test_custom_fetch_cache_key_override_remains_in_dispatch`<br>`test_frame_length_counts_utf8_bytes`<br>`test_get_components_and_body_have_unambiguous_boundaries`<br>`test_get_raw_body_is_documented_and_changes_default_cache_key`<br>`test_missing_and_empty_get_parameters_remain_equivalent`<br>`test_utf8_and_framing_like_text_cannot_cross_get_components` | — | — | 0 |
| `tests/test_views_multipart_body_bound.py` [open](tests/test_views_multipart_body_bound.py) | M | — | `UndeclaredMultipartLengthTest.test_asgi_chunked_multipart_over_the_cap_is_refused` | — | 6 |
