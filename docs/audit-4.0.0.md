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
| Bounded fix | 50 | A particular demonstrated behavior was corrected and regression-tested; related subclaims may remain. |
| Partial or residual | 26 | A slice is fixed or observed, but another subcase, backend, or policy remains open. |
| Contract or premise clarification | 9 | The reported expectation differs from the documented/current contract; no blanket runtime fix is implied. |
| Recommendation | 7 | Maintainability or coverage work, not seven extra runtime bugs. |
| Limited negative check | 6 | A proposed reassuring claim has only bounded evidence or is imprecisely worded; these are not six fixes. |
| Decision deferred | 2 | A new behavior, compatibility, security, or resource policy needs explicit design approval. |

Thus **50 does not mean 50 fully closed issues**. The 26 partial rows contain
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
- Library transformation directives are valid only on fields. A transform on a
  fragment spread or inline fragment now fails GraphQL validation before a
  resolver runs, rather than validating and silently doing nothing. Put the
  transform on a selected field inside the fragment instead. Standard
  `@skip`/`@include` and raw third-party directive locations are unchanged.
  See `tests/test_directive_field_locations.py` and the
  [directive migration guide](UPGRADE-4.0.md#move-transformation-directives-from-fragments-to-fields).
- `@floor` now reports a stable GraphQL error for non-finite numeric values,
  including numeric strings, rather than exposing Python's integer conversion
  message. Nullable fields become `null` with an error path; non-null fields
  bubble normally. This does not change finite values, other directives, or
  the SDL. See `tests/test_floor_nonfinite_error.py`.
- Generated FK/M2M mutation input checks reject a **hidden destination ID**.
  Automatic forward-FK, reverse-FK and both OneToOne output directions now
  apply the destination type's hook: a hidden nullable to-one target is
  `null`, and reverse-FK results and counts omit hidden rows. Forward-FK,
  forward-OneToOne, reverse-FK and M2M filters
  now use the active request's destination hook, so hidden targets cannot make
  sources match. Automatic declared/reverse M2M output members and counts now
  use the destination hook before pagination; direct source FK/OneToOne-ID
  lookups and custom output resolvers remain separate. See
  `tests/test_destination_link_scope.py`,
  `tests/test_sd1_relation_read_scope.py`,
  `tests/test_sd2_forward_fk_filter_scope.py`,
  `tests/test_sd2_reverse_fk_filter_scope.py`,
  `tests/test_sd2_m2m_filter_scope.py`, and
  `tests/test_sd2_forward_o2o_filter_scope.py`, plus
  `tests/test_sd1_o2o_output_scope.py` and
  `tests/test_permission_relation_bypass.py`.
- For finite typed subscription filters, `Decimal("1.0")` matches an
  event-time JSON-safe snapshot of `"1.00"`, including valid high-precision
  model values. Native full-payload DateTime snapshots retain microseconds;
  exact typed DateTime filters compare the captured instant, and the native
  DateTime output field serializes it without fetching a later row. Automatic
  id-only deletes now use a separate private projected-scalar equality snapshot.
  Exact finite native Float pairs now match, including opposite signed zeros;
  non-finite and mixed-type policies remain unchanged. See
  `tests/subscriptions/test_decimal_snapshot_filter.py` and
  `tests/subscriptions/test_datetime_snapshots.py` and
  `tests/subscriptions/test_delete_snapshot_matching.py` and
  `tests/subscriptions/test_float_snapshot_filter.py`.

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
  `csrftoken`; a following request carrying that cookie bypasses the server
  response cache.
  A cookie-free **cache hit** returns before that dispatch and does **not**
  itself set `Set-Cookie`, so that client can remain eligible. Do not disable
  CSRF to seek cache hits. This is a server-side request characterization,
  not proof of browser HTTP-cache reuse. See
  `tests/test_views_cache_cookie_bypass.py` and the
  [cache guide](usage/caching.md).
- A public model JSONField receiving the string `"123"` keeps a string
  through input, DB reload, and output. The distinct `JSONString` scalar
  intentionally decodes JSON text `"123"` to integer `123`; these
  contracts must not be collapsed into “all JSON strings change type.”
- A registry keys a public output type by its Django model, not by the
  output type's spelling. `PublicAuthor` and `AdminAuthor` for the same
  `Author` model conflict in one registry even though their names differ;
  separate registries can carry distinct public schemas. A runtime input
  factory runs when a **coerced input object** omits its field: two
  independent objects receive fresh values, while two aliases referencing
  one variable share that already-coerced object. SDL introspection does
  not evaluate the factory.
- A `DjangoModelMutation` rejected for unsupported `permission_classes` or
  `model_operations` no longer reserves a model output type. The existing
  one-public-output-type rule still rejects distinct valid declarations in
  one registry; this is not general registry rollback for every class error.

### Pagination and negative checks

- Cursor retains its prior NULL last ascending / first descending behavior.
  LimitOffset and Page now use that placement for automatic ordering by a
  nullable concrete column on queryset, nested window, and materialized-list
  paths. Explicit ORM expressions/null flags, custom terms, priority and PK
  ties remain unchanged; no universal expression/backend claim follows.
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

## False-positive subclaims and corrected premises

These are corrections to **specific allegations**, not blanket declarations
that their entire audit IDs are false. Confirmed problems such as SD1 remain
problems even when a nearby assertion is contradicted.

| ID | Original allegation | Actual reason and small counterexample | Remaining limit |
|---|---|---|---|
| M-D5 | The raw JSON string input changes type on reload. | Raw model JSONField string `"123"` remains a string through input, DB reload and output; `JSONString` separately parses JSON text to integer `123`. | Other JSON scalar policy remains separate. |
| L-C8 | Negative page `-1` must equal the short positive final page. | With 23 rows and page size 10, `-1` is the final 10-row tail window, not positive page 3's three rows. | A uniform page-ordering policy remains separate. |
| L-E3 | Exact SITE-B filtered prefetch loses its child hook. | Public SQLite witness: hook ran once, only visible children returned, one batched predicate query. | Other optimizer branches and backends remain unproved. |
| N4 | Every utility cache is request-scoped. | GFK target-type lookup uses process-global Django class metadata, not a fresh request cache. | Broader cache ownership remains subject to specific inspection. |
| Q8 | Named mutation flag and other named methods are dead code. | `MUTATION_ERRORS_FLAG` is reached by a live view path, so a name-only dead-code search is insufficient. | Other alleged dead symbols remain unproved pending qualified caller and compatibility review. |
| Q1 | Project dependency declarations mismatch on graphql-core. | `pyproject.toml`, `uv.lock`, `tox.ini`, and CI agree on 3.3; ambient 3.2.13 is unsupported stale local state. | Fresh CI and environment repair were unrun; broad environment cleanliness remains unproved. |
| M-U3 | Finite Float subscription filters never match. | The blanket claim is not verified: ordinary finite fractions, integral inputs, and same-sign zeros already matched. Opposite signed zeros were a real dropped-event gap and now match when both values are actual finite floats. Decimal and DateTime have separate exact corrections. | The non-finite policy remains unproved beyond its existing fallback; mixed-type, missing-field, and indexed-routing policies are unchanged. The id-only delete correction is M-U2. |

SD1 and SD2 were **confirmed** scope boundaries, not false positives.
The approved FK/reverse-FK/OneToOne/M2M automatic output and
FK/forward-OneToOne/reverse-FK/M2M filter slices apply destination hooks
without introducing a universal strict-scope rule. Explicit output resolvers
and through-model access remain separate.

## All 100 original claims

Statuses are intentionally narrow. “Bounded-fixed” means the described slice
has accepted regression evidence, not every adjacent behavior. “Contract”
means a correction to an allegation or a documented boundary, not a new
security guarantee. “Negative-limited” means the reassuring statement needs
qualification. Each row gives a compact case, outcome or remaining limit.

| ID | Status | Finding, outcome, and limit | Small example | Evidence |
|---|---|---|---|---|
| C1 | bounded-fixed | Decimal primary keys no longer pass through Float/null conversion; distinct Decimal output and non-finite policies remain separate. | Decimal PK 9007199254740993 → exact decimal text, not rounded Float. | `tests/core/test_decimal_output.py` |
| C2 | bounded-fixed | Fragment-dependent selections now retain source order; duplicate FieldNode behavior was not changed. | Spread B then A → selection expansion follows that source order. | `tests/test_fragment_fanout.py` |
| C3 | bounded-fixed | A shared fragment cycle is rejected as GraphQLError before the cost/depth walker can recurse indefinitely. | Fragment A spreads B and B spreads A → bounded GraphQLError. | `tests/test_fragment_cycles.py` |
| A1 | partial | A GraphQL error rolls back covered default-DB sibling writes; native `ok: false`, multi-DB atomicity, and stale-row overwrites remain separate. | Sibling write then GraphQL error → covered same-DB writes roll back; ok: false differs. | `tests/test_views_atomic_errors.py` |
| A2 | partial | The POST body-size guard runs before GraphQL body parsing; retained AST/cache bytes and aggregate memory are not capped by that change. | Oversized POST body → rejected before parsing; retained cache bytes remain uncapped. | `tests/test_views_body_cap_cache.py` |
| A3 | bounded-fixed | Invalid output field selectors are rejected rather than silently bypassing the selection gate; this is not a proof about every unauthenticated request. | Unknown output selector → rejected rather than silently exposing all fields. | `tests/test_output_selector_validation.py` |
| A4 | bounded-fixed | `Registry.register` keys public outputs by Django model: a distinct output type for the same model and same registry is rejected regardless of type names; separate registries may define distinct schemas. | PublicAuthor then AdminAuthor for the same Author model in one Registry → rejected despite different names; separate registries allowed. | `tests/test_output_registration_conflict.py` |
| A5 | bounded-fixed | A cold Django user in WS/SSE receives the covered permission pruning; a fake-user control does not prove every authentication source. | Cold Django user opens SSE/WS → covered private fields remain pruned. | `tests/subscriptions/test_transport_real_user_resolution.py` |
| A6 | bounded-fixed | Automatic notification failures are best-effort rather than raising through model writes; manual broadcasts remain strict and delivery is not guaranteed. | Automatic notification failure after save → model write does not raise; manual send differs. | `tests/subscriptions/test_automatic_best_effort.py` |
| A7 | bounded-fixed | An omitted-field factory runs per coerced input object, not per selected field or alias. Explicit values skip it; schema construction and introspection do not evaluate it. | Two independent coerced input objects → two fresh factory values; two aliases using one variable share its coerced object; SDL introspection does not run the factory. | `tests/core/test_input_factory_per_object.py` |
| A8 | bounded-fixed | A BigInteger value above JavaScript's exact-number range serializes as a decimal string; relation IDs and enum behavior are separate. | BigInteger 9007199254740993 → exact decimal string rather than a rounded number. | `tests/core/test_bigint.py` |
| A9 | bounded-fixed | Generated delete errors redact underlying database detail; arbitrary DB exceptions were not given a blanket catch. | Generated delete hits a DB error → response omits underlying database detail. | `tests/test_generated_delete_security.py` |
| A10 | partial | Email input, two positive-number fields, and generated DB-error redaction have bounded fixes; a general full-clean/upsert policy remains open. | Invalid email or covered positive-number input → validation; general full_clean remains open. | `tests/core/test_positive_input_validation.py` |
| A11 | bounded-fixed | A single result is bounded by a Unicode-aware output cap; an aggregate multi-result response quota was not added. | One overlong Unicode result → capped; many individually small results are not aggregate-capped. | `tests/test_replace_output_limit.py` |
| A12 | bounded-fixed | AND across a to-many relation can match independent related rows; one relation predicate still uses same-row semantics. | AND filters matching two distinct related rows → accepted; one predicate keeps same-row meaning. | `tests/test_and_many_filtering.py` |
| A13 | partial | valid Float/Decimal/UUID continuation + invalid decoded bounds; other cursor policies open. | Valid typed Float/Decimal/UUID cursor → continued; other cursor policies remain open. | `tests/test_pagination_cursor_typed_http.py` |
| SD1 | partial | Automatic forward-FK/reverse-FK, forward/reverse OneToOne, and declared/reverse M2M outputs apply destination get_queryset. M2M results/counts exclude hidden targets before pagination; custom output resolvers and through-model access remain separate. | Visible parent points to hidden nullable to-one target → relation is null; hidden-only M2M links → empty results and count zero. | `tests/test_sd1_m2m_output_scope.py` |
| SD2 | partial | Forward-FK, forward-OneToOne, reverse-FK and M2M filters apply each traversed destination get_queryset. Reverse-FK and M2M predicates use one visible child witness; direct reverse child and M2M target IDs are scoped, while direct source FK/OneToOne IDs remain source-owned. Output scopes are separate. | Hidden author, user, comment or tag → visible source does not match; direct source ID keeps its prior meaning. | `tests/test_sd2_forward_o2o_filter_scope.py` |
| SD3 | bounded-fixed | Generated FK/M2M destination IDs are checked against the caller's visible choices; this does not make all relation reads globally scoped. | Mutation names hidden destination ID → generated FK/M2M link is rejected. | `tests/test_destination_link_scope.py` |
| SD4 | bounded-fixed | hostless nullable reverse-FK orphan adoption denied only. | Parent 10 tries to adopt parentless child 7 → covered reverse-FK assignment denied. | `tests/test_nested_sd4_orphan_scope.py` |
| SD5 | bounded-fixed | flat GFK metadata pruned on target read/scope denial; not global ACL. | GFK target fails read/scope check → flat target metadata is not returned. | `tests/test_flat_gfk_pruned_security.py` |
| SD6 | recommendation | strict_scope/system-check recommendation; public semantics need decision. | Proposed strict_scope switch → no new relation-read semantics adopted. | `docs/usage/permission-scoped-schema.md` |
| M-S1 | bounded-fixed | variable-backed cost limits; no hard memory/DB cap. | Costly operation using a variable → covered cost limit rejects it before execution. | `tests/test_cost_variable_http.py` |
| M-S2 | partial | default page size 100 already fixed; other defaults/width/depth unverified/policy, LRU not byte-cap proof. | Omitted page size → existing default 100; no new depth/byte cap inferred. | `docs/usage/query-limits.md` |
| M-S3 | contract | The guide now states the configured introspection middleware requirement; the runtime default itself did not change. | Configured introspection middleware absent → guide warns; runtime default unchanged. | `tests/test_introspection_docs.py` |
| M-S4 | bounded-fixed | Production-mode HTTP errors no longer expose the covered internal detail; this is a bounded response contract, not a blanket leak audit. | Covered production HTTP exception → public response omits internal detail. | `tests/test_http_internal_error_diagnostics.py` |
| M-S5 | bounded-fixed | GET cache-key components are length-framed so adjacent values cannot collide inside one identity partition; cross-identity policy is separate. | Cache-key parts ab+c versus a+bc → framed distinctly within one identity. | `tests/test_views_cache_key_framing.py` |
| M-S6 | contract | shortcut required_perms raises TypeError; lowercase field works; untagged public documented. | Shortcut required_perms → TypeError; lower-case field keyword works. | `tests/test_permission_keyword_boundaries.py` |
| M-D1 | partial | external current native 3.3 witness shows sequential stale backend instance overwrites separately updated bio; not a threaded/PostgreSQL race. update_fields policy deferred for auto_now/custom save behavior. | Stale model instance saves bio after separate title update → full save can overwrite title. | `docs/usage/mutations.md` |
| M-D2 | partial | The included Django backend routes a populated unsaved parent for nested CREATE and pins native nested writes to that alias; divergent M2M through routing is checked before writes and again before linking after a generated ID, rolling back local writes on later divergence. UPDATE keeps its existing alias. Custom backends, cross-DB atomicity, and changing router answers between check and link remain separate. | Explicit foreign through route → no DML; generated-ID foreign route → selected-alias writes roll back with no foreign through DML. | `tests/test_routed_nested_atomic.py` |
| M-D3 | partial | Decimal output avoids Float precision loss; SQLite reload rounding and input coercion remain separate. | Large Decimal output → exact text; SQLite reload precision is separate. | `tests/core/test_decimal_output.py` |
| M-D4 | partial | public mutation rejects NaN/±Infinity/1e1000 structurally/no save; exact 1E+999999999 untested. | NaN, Infinity or 1e1000 mutation input → no save; extreme 1E+999999999 unrun. | `docs/usage/mutations.md` |
| M-D5 | contract | Public model JSONField input string '123' stays a string through DB/output; separate JSONString intentionally decodes JSON text to integer 123. | Raw JSONField string 123 → string after reload; JSONString JSON text decodes an integer. | `tests/test_explicit_null_and_json_input.py` |
| M-D6 | partial | Missing raw JSON list variables become null in place while missing object keys stay omitted; non-finite numeric raw JSON inputs now fail before resolution. Raw output and whole-ID disposition remain separate. | `[1, $v, 3]` with no `$v` → `[1, null, 3]`; raw input `1e999` → GraphQL error. | `tests/test_json_nonfinite_input.py` |
| M-D7 | bounded-fixed | incompatible same-name choices rejected; reordered equivalent kept. | Same enum name with incompatible choices → rejected; equivalent reordering remains. | `tests/core/test_choices_enum_name_collisions.py` |
| M-D8 | bounded-fixed | reserved-name construction fixed; inherited-hook history qualified. | Model field with reserved name → covered type construction now succeeds. | `tests/core/test_reserved_model_fields.py` |
| M-D9 | bounded-fixed | interface implementor name honored; general type rename unapproved. | Named interface implementor → chosen type name appears; global renaming remains open. | `tests/test_model_type_list_type_name.py` |
| M-D10 | partial | Approved all-string Literal inputs compile to named enums/raw resolver strings; exact `dict[str, int]`/`typing.Dict[str, int]` and `dict[str, str]`/`typing.Dict[str, str]` inputs use shared JSON with strict declared-value checks before resolution; nested lists of already-supported input leaves preserve recursive nullability and GraphQL list coercion; exact `set[int]` uses `[Int!]!` and a deduplicated resolver-facing Python set; numeric/mixed Literal, other parameterized dict/set, and non-optional Union still warn and fall back to String. | String Literal member → enum/raw string; typed integer or string map → JSON object/no coercion; supported nested lists → recursive wrappers; exact integer set → GraphQLInt list/singleton coercion with no ordering; unsupported forms → warning plus String. | `tests/core/test_set_int_input.py` |
| M-F1 | bounded-fixed | nested related datepart/PK shadow fixed; SDL/null/A12 separate. | Nested related date-part/PK shadow → correct lookup retained in covered case. | `tests/test_filter_lookup_boundaries.py` |
| M-F2 | bounded-fixed | numeric Date/DateTime parts typed Int; whole-value/TimeField policy unchanged. | Date year or DateTime month filter → GraphQL Int input, not string. | `tests/test_datepart_filtering.py` |
| M-F3 | partial | exact:null/omission only; broader Boolean identities open. | exact: null versus omitted exact → distinct covered behavior; empty Boolean open. | `tests/test_exact_null_filtering.py` |
| M-F4 | bounded-fixed | explicit page:null equals omission; zero/negative unchanged. | page: null → omitted-page path; zero and negative pages keep their contracts. | `tests/test_pagination_page_null_http.py` |
| M-F5 | bounded-fixed | model-backed PK-ASC tie-break; offset/random unaffected. | Equal sort values on model rows → PK ascending tie-break stabilizes order. | `tests/test_pagination_pk_tiebreak.py` |
| M-F6 | bounded-fixed | A failed negative-page count raises a controlled `GraphQLError` instead of trying length, iteration, or a full fetch; results are null, not fallback rows. | Negative-page count fails → GraphQLError and results: null; no collection materialization. | `tests/test_negative_page_count_error_http.py` |
| M-F7 | bounded-fixed | Server `PageGraphqlPagination(page_size=None, max_page_size=None)` retains its legacy behavior; client `pageSize: null` instead resolves to the configured default, normally 100. | Server page_size=None → legacy paginator policy; client pageSize:null → configured default 100. | `tests/test_default_page_size_http.py` |
| M-H1 | bounded-fixed | batch HTTP400 prior data/error/stop; prior writes persist, no batch transaction. | Batch item 2 fails → HTTP 400 with prior item data/error, then stop; prior writes stay. | `tests/test_batch_http_error_partial.py` |
| M-H2 | bounded-fixed | sync/async misuse JSON500/cleanup; no general async support. | Sync view receives async misuse → controlled JSON 500 and cleanup. | `tests/test_sync_async_http.py` |
| M-H3 | bounded-fixed | preserve 0/False; fragment classifier separate. | Response value 0 or false → retained instead of dropped by cleaning. | `tests/test_clean_response_http.py` |
| M-H4 | partial | success-only cache fixed; finite-safety/Ruff caveats retained. | Failed response → not cached; success cache still has separate finite-safety limits. | `tests/test_success_response_cache.py` |
| M-O1 | bounded-fixed | merged-node optimizer N+1 fixed in bounded case. | Merged alias selection across rows → batched relation fetch, not one fetch per row. | `tests/test_optimizer_merged_field_nodes.py` |
| M-O2 | bounded-fixed | warm-hit lock split; no general concurrency guarantee. | Warm cache hit beside cold fill → hit need not wait for unrelated cold fill. | `tests/test_permission_cache_lock_split.py` |
| M-U1 | partial | Real-ASGI startup now cleans a group joined before cancellation returns; the same failed-Source/same-channel retry works. Distributed-backend cleanup remains best-effort. | ASGI startup cancellation after group join → cleanup; same failed Source retry succeeds. | `tests/subscriptions/test_startup_cleanup.py` |
| M-U2 | partial | Automatic delete captures loaded private projected concrete scalar values at signal time, so id-only plain equality and server scope can match after commit without widening public data. Deferred/missing/nonprojected values, id-only relations, custom backends and lookup filters remain conservative; unfiltered PK-only events still deliver. This is not a general visibility policy. | Real id-only delete with matching text scope → PK-only event; wrong tenant or lookup scope → no event. | `tests/subscriptions/test_delete_snapshot_matching.py` |
| M-U3 | partial | Finite Decimal and native DateTime exact snapshots have separate corrections. Actual finite Float pairs now use exact numeric equality, including either signed-zero direction; ordinary finite Float matches were already working. Other scalar policies remain unchanged. | Decimal 1.0 versus snapshot 1.00, DateTime .123456 versus the same instant, and real FloatField -0.0 versus exact 0.0 → match. | `tests/subscriptions/test_float_snapshot_filter.py` |
| M-U4 | contract | Automatic post-save/post-delete signals schedule commit-time sends, while bulk/update paths emit no model signals and manual binding broadcast is immediate; use a fresh post-commit instance when timing matters. | save() → after-commit send; bulk_update() → no signal; manual binding send → immediate. | `docs/usage/subscriptions.md` |
| M-U5 | bounded-fixed | Native async directive formatting waits for resolver values and preserves borrowed Future ownership; synchronous HTTP still returns its controlled JSON 500 rather than gaining async support. | Async directive resolver → awaited; borrowed Future not cancelled by formatter. | `tests/test_async_directive_middleware.py` |
| M-U6 | partial | The directive guide clarifies `@date` formatting and bounded case behavior. Null passes through with ordinary NonNull bubbling. Accepted text fills omitted time components with zeros; missing dates still use the parser's current date. Absolute formats display originally aware Python datetime and explicit-offset/Z text in the active zone, preserving the instant; clock-adjacent `+00:00`/`+0000` now match equivalent `Z`. Genuinely timezone-less text now attaches the active zone to its written wall clock for absolute and relative formats, regardless of `USE_TZ`; explicit-offset/Z relative and named/unknown-zone behavior remains. The three case directives now normalize approved word forms and acronym blocks without renaming schema fields or changing shared helpers. `@number`/`@currency` now preserve null and normal NonNull bubbling while retaining format validation and caps; wider M-U6 remains open. | Nullable @date(None) → null; NonNull @date(None) → normal GraphQL error and bubbling. Text date-only → 00:00:00; partial text time → zero missing seconds/microseconds. `orderTotal` → `order_total`/`order-total` under the snake/kebab directives; `HTTPServer` → `httpServer`/`http_server`/`http-server`. Nullable `@number(None)`/`@currency(None)` → null; NonNull fields bubble normally. Explicit-offset text may cross a calendar boundary; timezone-less text retains its written hour but relative wording may change. | `docs/directives.md` |
| M-T1 | bounded-fixed | fork-depth marker isolation; other registry races separate. | Fork in thread A → depth marker must not mutate ordinary schema B. | `tests/core/test_schema_fork_threads.py` |
| L-C1 | bounded-fixed | Malformed primary-key IDs in get_node/retrieve/DjangoObjectField now yield safe `INVALID_ID` GraphQL errors with integer, UUID or generic format hints; well-formed missing/hidden IDs remain null without errors. Valid text IDs and existing ORM coercion remain. No unrelated errors are relabeled. | Integer/UUID malformed ID → coded safe error; well-formed absent or hidden ID → null without error; text PK `abc` → valid lookup. | `tests/test_invalid_id_contract.py` |
| L-C2 | bounded-fixed | Two specific constructor validations now survive optimized Python (`-O`); no universal validation claim follows. | Two invalid constructor values under python -O → still rejected. | `tests/test_settings_boundary_values.py` |
| L-C3 | bounded-fixed | Enhanced JSON view now matches the base view for a path-bearing non-null-root execution error: HTTP 200 with `data: null` and `errors`; syntax, validation, and variable-coercion errors remain HTTP 400 without data. Auth, transport, and other media policies are separate. | Non-null root execution error → both views return HTTP 200 with `data: null`; validation error → HTTP 400 without data. | `tests/test_http_execution_error_contract.py` |
| L-C4 | bounded-fixed | Configured MAX_UPLOAD_SIZE now checks each received multipart file, including unused and repeated parts, after parsing and before resolver or successful GraphiQL rendering. A file at the cap passes; above it returns safe JSON HTTP 413. None leaves multipart without this cap. The independent whole-body limit and Base64 contract remain; malformed batches still return their existing HTTP 400. This is not ingress protection. | Cap 3 bytes: an unused 4-byte file → HTTP 413/no resolver in both views; two separate 2-byte files → pass; malformed multipart batch → HTTP 400 first. | `tests/test_multipart_file_size_http.py` |
| L-C5 | bounded-fixed | `MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE`, and `DOCUMENT_CACHE_MAXSIZE` now reject negative integers with `ImproperlyConfigured` when read, naming the setting, value, minimum zero, and remedy. Zero, `None`, positives, defaults, and existing noninteger handling retain their prior behavior. This is not eager startup validation. | Configured negative MAX_BATCH_SIZE on read → configuration error; zero remains meaningful. | `tests/test_settings_minimum_zero.py` |
| L-C6 | contract | A cache miss reaches ensure_csrf_cookie and can set csrftoken; a cache hit returns earlier without Set-Cookie. A later cookie-bearing request bypasses the any-cookie cache policy. | Cookie-free miss can set csrftoken → next cookie request bypasses; hit does not set it. | `tests/test_views_cache_cookie_bypass.py` |
| L-C7 | bounded-fixed | ambiguous enum members rejected; optional multiselect untested. | Two enum choices map to one ambiguous member → rejected. | `tests/core/test_choices_enum_member_ambiguity.py` |
| L-C8 | contract | Negative page -1 means a fixed-size tail window, not the positive final page's short remainder. | page -1 with size 10 and 23 rows → last 10, not positive page 3's last 3. | `tests/test_pagination_page_null_http.py` |
| L-C9 | bounded-fixed | Automatic nullable concrete-column order now places NULL last ascending/first descending for offset/page DB, nested window and list paths; Cursor already agreed. Explicit ORM expressions/null flags, custom terms and broader backend parity are separate. | SQLite nullable ASC → non-null rows before NULL; DESC → NULL first, including nested windows. | `tests/test_pagination_null_order_parity.py` |
| L-C10 | bounded-fixed | Library transforms now declare FIELD only; fragment-spread and inline-fragment placements fail validation before resolver execution. Fields inside fragments still transform; spec built-ins and raw third-party directive locations are unchanged. | Transform on a fragment spread → named validation error, not silent no-op. | `tests/test_directive_field_locations.py` |
| L-C11 | bounded-fixed | `@floor` now raises the approved GraphQL error for NaN and either infinity. The report's `@title` is not registered; actual `@title_case` and `@truncate` stringify non-finite values and have no demonstrated defect. Their behavior is unchanged. | `@floor("inf")` → named GraphQL field error; `@title_case(inf)` → `"Inf"`. | `tests/test_floor_nonfinite_error.py` |
| L-C12 | partial | The covered GFK union-wrapper path no longer makes an N+1 query; broader multi-table-inheritance paths remain unproved. | Covered GFK union wrapper across rows → batched; wider inheritance path unproved. | `tests/test_optimizer_phase_e.py` |
| L-C13 | contract | The guide distinguishes native DateTime scalar naive parsing from `@date`'s active-timezone interpretation, including `USE_TZ=False`; no scalar policy changed. | Naive DateTime scalar input → stays naive; naive @date value → active timezone. | `docs/directives.md` |
| L-E1 | bounded-fixed | get_fields failure surfaces model/cause; healthy path unchanged. | get_fields raises while building a type → model and cause surface. | `tests/core/test_metadata_enumeration_failures.py` |
| L-E2 | bounded-fixed | explicit source property AttributeError surfaced; legitimate null/unrelated descriptors unchanged. | Explicit source property raises AttributeError → surfaced, not treated as null. | `tests/core/test_source_property_attribute_error.py` |
| L-E3 | partial | The exact SITE-B filtered-prefetch hook-loss allegation was contradicted by a public SQLite witness: hook called once, visible rows only, one batched predicate query. Other branches/backends remain unproved. | SITE-B filtered prefetch → hook ran once and visible rows stayed filtered. | `tests/test_optimizer_phase_e.py` |
| L-E4 | partial | cancellation intentional; single-group aclose warning fixed only. | Cancelled source with one group → aclose warning handled; other cancellation paths open. | `tests/subscriptions/test_source.py` |
| L-M1 | decision-deferred | Declared input classes are intentionally registry-owned and a static three-schema reuse stayed bounded; dynamic class churn needs an ownership/lifecycle policy. | Three static schemas reuse declared input classes → bounded; dynamic churn policy open. | `tests/core/test_registry_compiler.py` |
| L-M2 | partial | A bounded internal live-field identity/lifetime case was corrected; public schema impact and Graphene behavior were not established. | Internal live field reused across schemas → covered identity/lifetime case corrected. | `tests/core/test_native_field_identity_lifetime.py` |
| L-M3 | partial | A direct GraphQLSchema enum-cache race was corrected; public exposure was not established. | Two threads request same enum compilation → one protected cache creation. | `tests/core/test_enum_cache_concurrency.py` |
| L-M4 | partial | A direct GraphQLSchema list-creation race was corrected; public exposure was not established. | Two threads request same list construction → one protected registry creation. | `tests/core/test_registry_creation_concurrency.py` |
| L-S1 | partial | Approved, independently opt-in SSE heartbeat and authenticated-account Redis lease cap are implemented with defaults off (15 seconds/five streams). Contract tests cover heartbeat, sixth-request HTTP 429, backend HTTP 503, cleanup and expired renewal. An explicit ten-case suite against a single Redis instance (Redis 8.10.2/redis-py 8.1.0) executes real Lua and eight processes sharing one account, with five grants and three refusals, plus public SSE and lifecycle checks. Failover and partition behavior are not proved; Redis failover is not a strict global-count guarantee. | Idle SSE with heartbeat enabled → comment without source restart; sixth account stream → 429 before source startup; lost lease → generic SSE error then complete. | `integration/live_redis/test_sse_live_redis.py` |
| L-S2 | bounded-fixed | An optional async on_connect callback can authenticate the connection_init payload before ACK and replace the socket user for schema and permission checks. Missing, anonymous, or invalid credentials close generically without session fallback; no hook preserves the former scope-user behavior. JWT verification, session persistence, HTTP/SSE authentication, and mid-socket refresh remain outside this fix. | Authenticated token callback → ACK and one effective user; rejected token → close 4403 without ACK or subscription. | `tests/subscriptions/test_ws_on_connect.py` |
| L-S3 | bounded-fixed | The approved WebSocket guard rejects a missing, empty, or wrong-only subprotocol offer before acceptance; the required offer may appear among alternatives. The server logs the required protocol. Pre-accept rejection is normally wire HTTP 403, not a guaranteed browser-visible close code or GraphQL error. Broader subscription policies remain open. | Real-ASGI empty/missing/wrong-only offers → rejected before registry/watchdog; exact offer among alternatives → accepted. | `tests/subscriptions/test_ws_subprotocol.py` |
| L-S4 | bounded-fixed | WS operation cleanup and slot release precede the server `complete` frame, so immediate same-ID reuse is not mistaken for a duplicate; other lifecycle cases remain. | WS operation completes then reuses same ID → slot released before complete frame. | `tests/subscriptions/test_ws_completion_reuse.py` |
| Q1 | contract | pyproject/uv/tox/CI require graphql-core 3.3 consistently; root 3.2.13 is stale unsupported env, not refreshed; no tox config mismatch. | pyproject/uv/tox/CI require core 3.3 → ambient 3.2.13 remains unsupported. | `tests/test_tox_dependency_contract.py` |
| Q2 | bounded-fixed | The benchmark reader selects eight canonical result files deterministically; missing or invalid results still fail, and no timing was regenerated. | Benchmark reader sees eight canonical files → deterministic read, no new timing run. | `tests/benchmarks/test_core33_results.py` |
| Q3 | bounded-fixed | Direct-view tests now close their own multipart temporary upload and ASGI body spool, including exception exits; no ResourceWarning was observed and no production leak is inferred. | Direct-view upload test exits through exception → its owned temp file closes. | `tests/test_views_multipart_body_bound.py` |
| Q4 | recommendation | regression matrix duplicates existing IDs. | Proposed regression matrix repeats existing claim IDs → no extra runtime fix. | `odd/tasks/audit-400-remediation.md` |
| Q5 | recommendation | historical test naming suggestion only. | Suggested test renaming → historical names retained pending review. | `odd/tasks/audit-400-remediation.md` |
| Q6 | recommendation | module split suggestion, no authority. | Suggested giant-module split → no 10k-line refactor silently performed. | `odd/tasks/audit-400-remediation.md` |
| Q7 | recommendation | cross-reference plan only; verify before refactor. | Suggested cross-reference cleanup → existing callers require review first. | `odd/tasks/audit-400-remediation.md` |
| Q8 | negative-limited | MUTATION_ERRORS_FLAG is live; other alleged dead symbols require qualified caller and compatibility review, not deletion. | Flag marked dead → MUTATION_ERRORS_FLAG has a live view path; other names unproved. | `django_graphex/views.py` |
| Q9 | recommendation | historical Graphene names/comments only. | Historical Graphene naming → no compatibility names removed on suggestion alone. | `odd/tasks/audit-400-remediation.md` |
| Q10 | decision-deferred | deriving non-null from null=False changes SDL. | null=False model field → GraphQL non-null SDL not automatically inferred. | `odd/tasks/audit-400-remediation.md` |
| P1 | recommendation | duplicate priority plan, not new finding/authority. | Duplicate priority plan → no additional defect or approval created. | `odd/tasks/audit-400-remediation.md` |
| N1 | negative-limited | The schema cache uses an effective permission signature, not a unique user key; this is not a universal cross-user response-cache guarantee. | Two users with same effective permissions → schema cache signature can match. | `odd/tasks/audit-400-remediation.md` |
| N2 | negative-limited | anonymous/falsy permission and scoped update/delete chain not universally runtime-proved. | Anonymous/falsy permissions → no universal fail-closed proof from bounded checks. | `odd/tasks/audit-400-remediation.md` |
| N3 | negative-limited | Core MaxIntrospectionDepthRule rejected one bounded nested introspection query; custom MAX_QUERY_DEPTH is a different guard, and no universal DoS proof follows. | Nested introspection query → core depth rule rejects bounded case, not all DoS. | `tests/test_depth_limit.py` |
| N4 | contract | The GFK field-type cache is process-global Django class metadata; saying all caches are request-scoped is inaccurate. | GFK target-type lookup → cached in process-global Django class metadata. | `django_graphex/utils.py` |
| N5 | negative-limited | regex safety is bounded only; no universal conclusion. | One bounded regex probe → cannot establish universal input safety. | `odd/tasks/audit-400-remediation.md` |
| N6 | negative-limited | The current local strict scan reports zero after correction of 23 tracked-test findings and seven ignored-profile DOC002 findings; original ignored preimages remain unknown, the ignored scripts are absent from a clean checkout, and no CI-clean verdict is proved. | Historical 23 tracked and seven ignored findings → current local scan zero, not CI proof. | `scripts/check_docstrings.py` |

## Decisions still required

These items are **not implemented by this audit report**. They are grouped
because approving one does not silently approve another.

1. **Security and data scope:** SD1 automatic FK/reverse-FK/OneToOne/M2M reads and SD2
   forward-FK/forward-OneToOne/reverse-FK/M2M filters have bounded destination-hook
   behavior. Explicit output resolvers, through-model access, direct source FK/OneToOne-ID policy,
   and SD6 strict-scope/system-check semantics still need separate decisions.
   The exact SITE-B L-E3 case did not reproduce,
   but other branches/backends remain unproved. Generated input destination
   IDs and hostless reverse-FK adoption have narrower accepted safeguards.
2. **Mutation semantics:** A1 native `ok: false` sibling rollback,
   cross-database writes and lost updates; M-D1 partial-save
   `update_fields`, custom `save()`, `auto_now`, and derived fields;
   R05c custom-backend nested CREATE routing; wider A10 `full_clean()` and
   upsert/uniqueness behavior all need separate compatibility decisions.
   Stable/model-routed same-alias nested rollback is not distributed
   atomicity.
3. **Subscriptions and transport:** M-U2 relation/lookup or custom-backend
   delete visibility beyond projected native scalar equality,
   R02b legacy truncated DateTime notification compatibility, M-U3 Float
   generalization, and M-U4 bulk/M2M signal policy remain distinct work.
   The single-instance live Redis validation is complete, while failover and partition behavior remain unproved
   for opt-in L-S1 controls. The optional L-S2 `connection_init` hook is
   now available, but credential verification and refresh are application
   responsibilities. Same
   failed Source retry was corrected, but backend cleanup remains best-effort.
4. **HTTP, cache, and resource limits:** A2 retained AST/cache bytes and
   aggregate memory, A11 aggregate response quota, M-S2 other defaults and
   Boolean width/depth, other resource-limit policies,
   L-C6 any-cookie privacy override and cache byte limits must not be
   inferred from existing per-result/body caps. The accepted L-C4 multipart
   cap is post-parse, not an ingress or aggregate-upload limit.
5. **Inputs, scalars, pagination, and SDL:** M-D4 extreme
   `1E+999999999` was intentionally not run without a bounded witness;
   M-D6 raw JSON output/non-JSON-native policy (the missing-list-variable and
   non-finite numeric input slices are corrected separately), M-D10 remaining
   numeric/mixed Literal and other dict/set/Union conversion, M-F3 empty Boolean identities, L-C1 malformed-ID null/error
   policy, L-C9 arbitrary-expression/backend NULL ordering, M-U6 remaining
   directive/date semantics beyond accepted bounded slices, and Q10 non-null SDL derivation all
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
- At the historical R11 snapshot, the local configured suite passed **5,627 tests**, with **7 skipped**
  and **10 warnings**. Raw branch coverage was **4,148 / 4,346 = 95.44%**;
  combined covered lines and branches were **15,546 / 15,927 = 97.61%**.
  The nonempty cumulative production diff against the initial feature-branch
  base covered **1,221 / 1,238 changed lines = 98.63%**, including branch
  coverage. These are historical R11 figures, not a final SD1 verification.
  This was a local supported-runtime run, not a clean CI matrix.
  The proof applies to the guarded finite inputs, not to every host file,
  physical index state, or power-loss mode. No package was published and no
  real PostgreSQL integration database was run.
- The current local strict scan reports zero after correction of 23 tracked
  and seven ignored DOC002 findings in local profiling files. The original ignored preimages
  remain unknown, and those scripts are absent from a clean checkout. No CI run
  or whole-CI-clean verdict follows from this current local result.
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
- The original RED demonstrated report and navigation **file absence**, but
  its test bytes are **not identical** to the eventual GREEN because a table
  helper and wording were corrected in between. A later, narrower
  **same-byte** wording RED/GREEN cycle does not retroactively repair that
  original TDD provenance. The retained proof records both paths.
