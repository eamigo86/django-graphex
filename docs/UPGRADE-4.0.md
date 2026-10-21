# Upgrading to django-graphex 4.0

## Version requirements

django-graphex 4.0.0 requires `graphql-core>=3.3.0,<3.4`. The historical
3.1.1 release requires `graphql-core>=3.2.13,<3.3`; its metadata does not
establish compatibility with the 3.3 API. Check custom integrations below
before upgrading, then select the version explicitly:

```bash
uv add "django-graphex==4.0.0"
# or
pip install "django-graphex==4.0.0"
```

The Playground installs the parent checkout in editable mode, so it tests
that source rather than an independently installed wheel.

### String Literal input values

All-string `Literal` annotations on hand-authored inputs now expose GraphQL
enums instead of `String`. For `ArticleInput.status: Literal["draft",
"published"]`, the generated `ArticleInputStatusEnum` accepts `DRAFT` and
`PUBLISHED`. Update inline operations from `status: "draft"` to
`status: DRAFT`; update JSON variables from `"status": "draft"` to
`"status": "DRAFT"`. Resolvers still receive the raw string `"draft"`.
Invalid members are rejected before resolver execution. Numeric or mixed
`Literal`, parameterized dictionaries and sets, and non-optional unions keep
their existing warning and `String` fallback; this does not add automatic
Pydantic validation.

### Nullable ordering in offset and page results

`LimitOffsetGraphqlPagination` and `PageGraphqlPagination` now place NULL last
ascending and first descending for automatic ordering by a nullable concrete
model column, including nested SQL-window pages and materialized lists. For
example, `ordering: "categoryId"` on nullable `category_id` now returns
category 1, category 2, then NULL; descending returns NULL first. On SQLite,
queryset pages previously used the opposite implicit NULL placement, so a
client that depended on that order will see a changed page boundary. Use an
explicit queryset expression such as
`F("category_id").asc(nulls_first=True)` to keep NULL first ascending.
Explicit ORM expressions and their NULL flags, custom expressions, relation
ordering, term priority, PK ties, and Cursor pagination are unchanged. The
automatic policy is not a promise about arbitrary annotations or SQL aliases.

### Negative operational limits

`MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE`, and `DOCUMENT_CACHE_MAXSIZE` now
raise `ImproperlyConfigured` when read with a negative integer. Correct a
negative configuration to a meaningful nonnegative limit, or use `None` for
the setting's existing uncapped behavior. Zero retains its distinct meaning:
no batch operations, no request-body bytes, or disabled document caches,
respectively. Defaults and positive values are unchanged. Validation occurs
when the setting is read; it is not a new startup system check or a general
type validator.

### Multipart upload size limit

If you configure `MAX_UPLOAD_SIZE`, it now limits **each received multipart
file**, including unused or unmapped parts and repeated parts under one name.
A file at the limit is accepted; a larger file receives a JSON HTTP 413 before
resolver execution. This may reject requests that previously ignored an
oversized extra part. Remove unwanted parts or raise the limit deliberately.
`None` leaves multipart files without this per-file cap, while
`MAX_REQUEST_BODY_SIZE` still controls the whole body independently.

This does not change the `Base64FileInput` requirement for a limit or its
per-call override. The multipart check occurs after Django parses the upload;
configure server-level ingress limits separately. Malformed batch requests
retain their existing HTTP 400 response before this per-file check.

### Distinguish malformed IDs from missing objects

Model-backed single-object lookups now distinguish an ID the model cannot
convert from a well-formed ID that finds no visible row. The malformed case
returns a GraphQL field error with `extensions.code` set to `INVALID_ID` and a
safe expected-format message: `Invalid ID: expected an integer.`, `Invalid ID:
expected a UUID.`, or the generic `The ID format is invalid.` for other
primary keys. The nullable field is `null` and a non-null parent follows
ordinary GraphQL error bubbling. Missing or scoped-out rows still return
`null` without an error. A text primary key such as `abc` is not rejected
merely because it is not numeric.

Clients that previously interpreted every `null` as "not found" should now
check the GraphQL `errors` array and `extensions.code`. The input value and
Django conversion details are not included in the public message. This does
not change schema fields, argument types, or valid-ID coercion.

### Move transformation directives from fragments to fields

The library's transformation directives now declare only the GraphQL `FIELD`
location. A query placing `@uppercase` or another library transform on a
fragment spread or inline fragment fails validation before resolver execution;
it no longer succeeds while silently leaving the value unchanged. Move the
directive to each selected field that should be transformed:

```graphql
# Before: invalid fragment-spread placement.
query { ...Words @uppercase }
fragment Words on Query { text }
```

```graphql
# After: valid field placement inside the same fragment.
query { ...Words }
fragment Words on Query { text @uppercase }
```

Fields inside inline fragments work the same way. Standard `@skip` and
`@include` keep their fragment and field locations and behavior. This change
does not make transformations inherit from a fragment or restrict locations
declared by third-party raw GraphQL directives.

### Handle non-finite values before applying `@floor`

`@floor` now reports a GraphQL field error for `NaN`, positive infinity, or
negative infinity, including numeric strings such as `"nan"` and `"inf"`.
Nullable fields resolve to `null` with the error path; non-null fields follow
ordinary GraphQL bubbling. Previously, Python's integer conversion error
surfaced instead. If non-finite values are possible, handle them in the
resolver before selecting `@floor`, or allow the client to handle the field
error. `None`, finite values (including negative zero), malformed-number
errors, and the behavior of `@ceil`, `@round`, `@abs`, `@truncate`, and
`@title_case` are unchanged. This is a runtime error-message policy, not a
schema or directive-location change.

### Review null values under numeric formatting directives

`@number` and `@currency` now preserve a resolver's `None` as GraphQL `null`
instead of rendering `"0.00"` or `"$0.00"` on otherwise formatted fields.
If the field is non-null, GraphQL reports the ordinary nullability error and
bubbles to the nearest nullable parent. Review clients that treated a
formatted zero as evidence of a missing value. Return an explicit zero from
the resolver when zero is intended, or use `@default` deliberately where a
fallback is appropriate. Existing format validation and width/precision caps
still apply; `Int` and `Float` fields continue to pass through raw values.

### Review case-conversion directive output values

`@camel_case`, `@snake_case`, and `@kebab_case` now recognize words separated
by spaces, underscores or hyphens, camelCase/PascalCase boundaries, and
acronym blocks. For example, `orderTotal` now yields `order_total` with
`@snake_case` and `order-total` with `@kebab_case`; previously both collapsed
to `ordertotal`. Likewise, `order_total @kebab_case` changes from
`order_-total` to `order-total`, while `HTTPServer` converts to `httpServer`,
`http_server`, or `http-server` in directive order. Review clients that compare
these formatted response values. Field and argument names in the schema,
other directives, shared conversion helpers, and handling of other
punctuation or characters are unchanged.

### Review aware values formatted with absolute @date formats

The `@date` directive now displays originally aware Python `datetime` values
and text with an explicit numeric offset or `Z` in Django's active timezone
for `default`, `iso`, `js`/`javascript`, and custom absolute formats. It
preserves the instant but may change the displayed calendar date. For example,
with `America/New_York` active, `"2026-01-01T03:30:00+02:00"` now displays
as `"2025-12-31T20:30:00"` under `@date(format: "iso")`, rather than
`"2026-01-01T03:30:00"`.
Clock-adjacent zero offsets are included: in the same active zone,
`"2026-01-10T00:30:00+00:00"` and `"2026-01-10T00:30:00+0000"` now
display as `"2026-01-09T19:30:00"`, matching the equivalent `Z` value.

If clients relied on the input offset's wall clock, review their expectations
or choose an explicit display zone in the resolver. The `iso` output still
omits offset and microseconds; it is not an offset-bearing timestamp. Explicit
offset/Z text retains its prior relative behavior. Naive Python datetimes,
Python dates, other input kinds, null handling and directive arguments remain
unchanged.

### Review timezone-less text in absolute and relative @date formats

Accepted text with no timezone information now means its **written wall
clock in Django's active timezone**, regardless of `USE_TZ`. This does not
convert an assumed UTC instant. With `TIME_ZONE="UTC"` and `Europe/Madrid`
active in July, `"2026-07-10 14:30"` gives `"14:30 +0200"` for
`@date(format: "HH:mm ZZ")`, rather than `"14:30 +0000"`. The same active-zone
interpretation applies to `"time ago"` and `"time ago 2d"`, so their relative
wording may change. Audit callers that previously relied on the default
timezone's interpretation; supply an explicit offset when the instant is
known. Named UTC/GMT text and unknown timezone names retain their existing
handling and warnings. A time-only string still takes its missing date from
the parser's current-date default, even when the active zone has crossed
midnight; no new daylight-saving gap/overlap policy was added.

### Review text values formatted with @date

The `@date` directive now fills omitted time components of accepted text
values with zeros, rather than the server's current hour, minute, second, or
microsecond. For example, a resolver returning `"2026-01-10"` with
`@date(format: "iso")` previously produced a value such as
`"2026-01-10T08:15:21"` when the server clock read 08:15:21; it now produces
`"2026-01-10T00:00:00"`. A partial value `"2026-01-10 14:30"` now produces
`"2026-01-10T14:30:00"` instead of inheriting the current seconds.

Check clients that relied on an implicit server time. Supply the intended
time explicitly in the resolver value instead. A time-only string still uses
the current date; explicit time components and null behavior are unchanged.
The aware-value timezone conversion above is a separate change. The `iso`
output format itself is unchanged and does not display offsets or microseconds.

### Review nullable fields formatted with @date

The `@date` directive now passes a resolver's `None` through as GraphQL
`null`. Previously, a nullable Date/DateTime field could expose
`"INVALID FORMAT STRING"` instead, while a String field could expose the
wrapper's text. For example, a nullable `publishedAt` queried as
`publishedAt @date(format: "YYYY-MM-DD")` now returns
`"publishedAt": null` when the resolver has no date.

If the field is declared non-null, the same resolver result now triggers the
normal GraphQL nullability error and bubbles null to the nearest nullable
parent. A non-null root field can make `data` null, so clients should check
`errors` and the field's SDL nullability. The null change does not alter SDL or
other directives; the separate text-time default change is described above.

For nested creates using the included Django backend, a database router now
receives a populated but unsaved parent instance before any related write.
It may therefore choose an alias from a supplied scalar such as `region` or
from a model default. Native parent and child saves share that alias and one
transaction; a late child failure rolls back those writes and commit callbacks.
Check routers that previously expected `instance=None` on nested create.
Direct creates without nested work and custom serializer backend create calls
retain their prior behavior. If an M2M through router explicitly selects a
different alias, native nested CREATE returns a field error before any write.
A router that chooses differently only after a generated ID triggers a second
check before linking; earlier writes on the selected alias roll back and no
foreign through write is attempted. Routers should keep the through model on
the parent's alias. Transactions across aliases and arbitrary stateful router
changes between checks and Django's link operation are not coordinated.

The built-in HTTP views now reject a schema without `graphql_schema` and the
combination `graphiql=True, batch=True` even under `python -O`. They retain
their existing `AssertionError` type and messages; only these two constructor
checks changed. The check occurs when a view instance is constructed, not
necessarily when Django evaluates `as_view()`.

Date-part behavior tests exercise the supported GraphQL-core 3.3 range without
pinning an exact patch or local checkout path. Contributors running those tests
should verify their active runtime in an external test runner; a passing local
overlay run does not by itself prove behavior under every supported install.

Batch clients should accept an HTTP 400 **array** when a valid batch reaches
an operation-level HTTP 400 request error: completed entries remain in order,
the final entry identifies the error, and later operations do not run. Earlier
successful mutations remain committed because `ATOMIC_MUTATIONS` is
per-operation, not batch-wide. Previously the same failure returned only a
request-level error object, hiding completed results. Malformed batch bodies
still return a request-level object. See [Batch endpoints](usage/views.md#batch-endpoints).

The enhanced `GraphQLView` now returns HTTP 200 with `data: null` and `errors`
when a field execution error bubbles through a non-null root field. Previously
that case returned HTTP 400 with no `data` member; `BaseGraphQLView` already
returned the execution envelope. Update clients that treated every HTTP 400 as
an execution failure or assumed HTTP 200 implies no GraphQL errors. Syntax,
validation, and variable-coercion failures still return HTTP 400 without
`data`. Errored responses remain uncached. For batches, an execution-error
entry has status 200 and retains its null data while a validation-result entry
has status 400; neither alone stops later entries. A transport-level HTTP 400
still stops the batch with completed entries. See
[production execution errors](usage/views.md#production-execution-errors).

If your deployment relies on disabled schema introspection, explicitly add
`django_graphex.security.DisableIntrospectionMiddleware` to
`DJANGO_GRAPHEX["MIDDLEWARE"]`. The default `ALLOW_INTROSPECTION=False` does not
enforce a block while the default GraphQL middleware chain is empty. See the
[security configuration](usage/security.md#disable-introspection) for a complete
example; this clarification does not install middleware automatically or change
the default setting.

When `CLEAN_RESPONSE=True`, selected introspection operations expressed with
root inline or named fragments now preserve schema `null` and empty-list
values, just like direct `__schema` and `__type` roots. Clients that previously
saw those values omitted should accept the full introspection response. Mixed
ordinary root fields are still cleaned, and the default
`CLEAN_RESPONSE=False` is unchanged. See [response cleaning](usage/security.md#ast-based-introspection-detection-clean_response).

### Review automatic OneToOne output reads

An automatically published forward or reverse OneToOne object field now
applies the destination type's `get_queryset` for the current request. A
visible parent whose linked object is hidden still appears, but that nullable
relation resolves to `null`. A genuinely absent relation remains `null`, and
the GraphQL field's nullability does not change. Review clients that previously
expanded a hidden linked user or profile, and review the destination hooks
before upgrading. Ordinary list reads batch scoped destinations; an automatic
field on a custom-returned cached parent still checks its destination. Explicit
relation resolvers and M2M output reads have separate rules. See
[automatic output relation scope](usage/types.md#relation-scope-hatch).

### Review automatic M2M output lists and counts

An automatically published declared or reverse M2M field now applies the
destination type's request-specific `get_queryset` before constructing its
`results` and `totalCount`. For a visible post linked to one visible and one
hidden tag, `tags { totalCount results { label } }` returns only the visible
tag and a count of one. A hidden-only relation returns an empty result and a
zero count; the parent remains visible. Pagination slices this visible set,
not the original links. Review clients that previously displayed hidden
members or relied on their counts. Explicit relation resolvers and
through-model access control are unchanged. See
[automatic output relation scope](usage/types.md#relation-scope-hatch).

### Review filters that traverse a forward FK

A public nested filter such as
`posts(filter: { author: { name: { exact: "Ada" } } })` now applies
`AuthorType.get_queryset` for the current request before the author can
satisfy the predicate. A post linked to a hidden author no longer matches,
even when the post itself remains visible. Each forward-FK hop in a longer
filter path is scoped. If clients previously expected hidden destinations to
match, review those filters and destination hooks.

Direct source FK-ID filters such as `author: { exact: 7 }` keep their existing
contract; a hidden target ID may still match the source row. An omitted filter
and real nullable-FK matches also keep their meanings. Forward OneToOne
and M2M filters have their own bounded rules below; custom filter bodies,
ordering, and OneToOne output reads are separate from this FK filter rule. See
[forward-FK filter scope](usage/filtering.md#forward-fk-filter-scope).

### Review filters that traverse a forward OneToOne

A declared destination-field filter such as
`profiles(filter: { user: { name: { exact: "Ada" } } })` now applies
`UserType.get_queryset` before the linked user can satisfy the predicate.
Review clients that previously selected visible profiles through hidden
users. A direct source-column `user: { exact: 7 }` filter and a genuinely
absent nullable OneToOne relation retain their prior meanings. An omitted or
empty relation filter is still a no-op. The existing reverse OneToOne filter
path already invoked its destination hook; automatic OneToOne output reads
have the separate rule above. See
[forward OneToOne filter scope](usage/filtering.md#forward-o2o-filter-scope).

### Review filters that traverse a reverse FK

Nested reverse-FK predicates now use the child type's `get_queryset` for the
current request. A hidden child can no longer make its visible parent match;
direct reverse-child ID lookups are scoped as well. `not` complements the
visible matching-child set, while separate `and` branches can use different
visible children. An absent or hidden-only child set retains the ordinary NULL
lookup behavior. Review callers that previously used hidden child fields or
IDs to select parents. An automatic reverse output accessor remains required:
an explicitly declared or permission-pruned relation still has no filter path.
See [reverse-FK filter scope](usage/filtering.md#reverse-fk-filter-scope).

### Review filters that traverse an M2M relation

Both forward and reverse M2M filter paths now apply the destination type's
request-specific `get_queryset` before a linked target can satisfy the
predicate. Hidden targets no longer make visible sources match. Direct and
nested target-ID lookups are scoped as well; unlike a direct forward-FK ID,
an M2M ID is read through the target table. An absent or hidden-only visible
target set retains ordinary relation-NULL behavior, and separate `and`
branches can still use different visible targets. Review filters that
previously selected sources through hidden tags or other M2M destinations.
Automatic M2M output reads have the separate rule above. Through-model
permissions, custom filter bodies and ordering are unchanged. See
[M2M filter scope](usage/filtering.md#m2m-filter-scope).

### Check custom integration code

1. **Execution backends:** the HTTP view accepts `executor_class=` and keeps
   `execution_context_class=` as an alias. Both names must designate the
   same class if supplied together; an explicit view argument overrides a
   subclass default. Port custom GraphQL-core 3.2 `ExecutionContext`
   subclasses to the 3.3 `Executor` API. Renaming the keyword alone is not a
   migration. A custom executor used with the synchronous view must accept
   the native async-iterable predicate that keeps a dual-iterable Django
   queryset on synchronous list completion inside the request thread.
2. **AST construction and coercion:** graphql-core 3.3 uses immutable AST
   nodes. Supply fields when constructing nodes, including inline-fragment
   `type_condition` and `selection_set`, rather than assigning afterward.
   Use a tuple for `SelectionSetNode(selections=...)`. Extensions that
   evaluate directives directly must pass 3.3's native variable-values
   object, then test valid values, defaults, and invalid-value coercion.
3. **Subscriptions:** built-in SSE and WebSocket transports prepare an
   `Executor` before opening the source stream. Custom transports must handle
   errors from `Executor.build()` and both immediate and awaitable
   `create_source_event_stream()` results. Preserve per-event authorization,
   serialization, and teardown rather than replacing the transport driver
   with a stock subscription call.
   Full-payload native DateTime snapshots now retain microseconds: exact
   DateTime filters match the captured instant, including equivalent aware
   offsets, and selected DateTime output fields serialize without an error.
   A previously dropped matching event may now arrive. Existing notifications
   already truncated to milliseconds cannot recover their original precision;
   id-only payloads, arbitrary JSON strings and custom output resolvers are
   not converted by this change. Exact finite Float pairs also now match by
   numeric equality, so a previously dropped full-payload event with snapshot
   `-0.0` and filter `0.0` (or the reverse) may arrive. This includes legacy
   direct calls to `split_filters` with two actual floats; clients that used
   signed zero to suppress delivery should use an explicit application-level
   condition. Strings, mixed types, non-finite values, and indexed group-key
   routing retain their prior behavior. See
   [subscription filters](usage/subscriptions.md#filtering-notifications).
4. **Cost and query behavior:** keep the built-in cost/depth validation and
   request-only SQL controls in your regression suite, alongside synchronous
   queryset and mutation transaction tests. The 3.3 migration does not
   promise general async-resolver support from the synchronous HTTP view.
   The built-in HTTP views now reject an awaitable execution result with HTTP
   500 and a GraphQL JSON message directing you to synchronous resolvers and
   middleware. Previously, this unsupported configuration could surface as an
   HTML 500 with a coroutine attribute error. Replace async HTTP resolvers,
   middleware and custom executor results; this change does not run or await
   them, and does not affect the subscription transports.

See [Views](usage/views.md), [Subscriptions](usage/subscriptions.md), and
[Query limits](usage/query-limits.md) for the supported interfaces. The
[current core33 comparison](why.md#current-core33-comparison) uses named
whole-stack profiles and is separate from the historical 3.1.0 results.

The new benchmark command has explicit `run` and read-only measurement
`replay` modes. `run` creates fresh private seeds and performs costly new
measurements; `replay` revalidates retained raw results before an atomic,
no-clobber eight-file install. Neither mode provides a same-user filesystem
sandbox, and neither overwrites historical results. See the
[benchmark guide](https://github.com/eamigo86/django-graphex/blob/integration/benchmarks/README.md)
for the required trusted results parent and profile-specific invocation.
