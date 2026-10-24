# Changelog

## Unreleased

- Fix: a `Decimal` value of `NaN`, `sNaN` or an infinity is rejected as invalid
  input. In a filter (`{amt: {exact: "Infinity"}}`) it reached the ORM and came
  back as Django's raw `“%(value)s” value must be a decimal number.` with the
  whole list nulled. The `Decimal` scalar now fails with `Decimal cannot be a
  nonfinite Decimal: 'Infinity'` before execution, for every lookup (`exact`,
  `in`, `gt`, `range`) and for mutation inputs too. Float, Int, BigInt and Date
  filters already rejected their invalid values and are unchanged.

- Fix: a tampered cursor on an in-memory (prefetched or nested) list answers
  `Invalid cursor`, like the database path. A `NaN` Decimal, a non-numeric pk,
  a bad date or a naive/aware datetime mismatch raised `InvalidOperation` or
  `TypeError`, which the client saw as a masked internal error and the server
  logged at ERROR. The boundary is now converted once to the rows' type for
  every integer, float, Decimal, UUID, date, datetime and time ordering field,
  and a non-finite float or Decimal boundary is refused on both paths (the
  database path used to run the comparison with it).

- Fix: a base64 upload of exactly `MAX_UPLOAD_SIZE` bytes is accepted. The
  decoded-size pre-check ignored `=` padding and over-counted by up to two
  bytes, so the same file passed as multipart but was refused as base64. The
  limit now means the same number of bytes on both transports.

- Fix: the schema-suggestion strip in error formatting runs in linear time.
  `format_graphql_error` removed the "Did you mean ...?" sentence with a regex
  whose cost grew with the square of the message length (2.5 s for 224 KB). It
  is now a linear scan with the same results.

- Fix: the request body cap now runs before Django's CSRF check. A multipart
  POST carrying a `csrftoken` cookie was parsed (and its files spooled to disk)
  by that check before `MAX_REQUEST_BODY_SIZE` could answer 413. `dispatch` now
  checks the cap first, so an oversized body is refused unparsed whether or not
  the client holds the cookie. CSRF behavior is unchanged.

- Fix: bound the total text that directives add to one response. Only a
  per-field cap existed (`MAX_REPLACE_OUTPUT_LENGTH`), so many aliases and rows
  each under the cap could still produce hundreds of megabytes. New setting
  `MAX_DIRECTIVE_OUTPUT_TOTAL` (default 10,000,000 characters per request,
  `None` disables) charges every directive for the text it adds; once spent,
  further directive uses become field errors. New opt-in setting
  `COST_DIRECTIVE` (default `0`, so existing costs do not change) adds cost per
  custom directive use so aliases x directives counts toward `MAX_QUERY_COST`.

- Fix: cost analysis now reads the page-size argument by its wire name too.
  `COST_PAGINATION_ARGS` was compared literally, so the camelCase `pageSize`
  that the page paginator exposes was ignored and `items(pageSize: 5000)` was
  costed at the default page size. Argument names are now compared in
  snake_case form on both sides (`pageSize` matches `page_size`; a custom
  `perPage` is matched by listing `per_page` or `perPage`).

- Fix: reject enum members that GraphQL reserves. A `Literal["__x"]` input
  generated the member `__X`, so the schema built and every query failed.
  The schema build now raises an error naming the input type, field and value.
  A Django choice whose value starts with `__` no longer generates a reserved
  member name either: it falls through the usual label / `A_<value>` naming.

- Fix: adding an interface no longer changes the wire name of fields that are
  not part of it. An object type that implements an interface used the explicit
  `name=` of every declared field verbatim, while the same type without
  interfaces ignored it, so `Meta.interfaces` silently renamed unrelated
  fields. Now only a field that the interface also declares uses the explicit
  wire name; every other field keeps the naming it has without interfaces.

- Behavior change: define `not` inside a to-many relation object as "no
  related row matches the operand". A `not` used to be evaluated on the same
  related row when it sat beside a positive criterion, and its `and` operand
  was split across rows, so `tags: { not: { and: [x, y] } }` was not the
  complement of `tags: { and: [x, y] }`. Now (posts tagged with every subset of
  x, y, z): `tags: { and: [x, { not: z }] }` returns posts tagged x and not z
  (`x`, `xy`; was also `xyz`, `xz`), `tags: { label: x, not: y }` returns
  `x`, `xz` (was also `xy`, `xyz`), `tags: { or: [z, { not: y }] }` no longer
  returns `xy`, and `tags: { not: { and: [x, y] } }` returns every post. A
  `not` alone, `not: { or: ... }`, top-level `not` and every filter outside
  relation objects are unchanged.

- Compile nested `and` filters over to-many relations without nested EXISTS.
  Each level of a nested `and` re-correlated on the root table, so a chain of
  about 25 levels failed on SQLite ("Expression tree is too large") and
  surfaced as `DATA_ACCESS_ERROR`, and wide `and` lists produced several times
  more SQL than before. Operands that are only an `and` list are now flattened
  (AND is associative) and every to-many conjunct is one sibling EXISTS, so SQL
  nesting depends on relation nesting only. Results are unchanged; the
  structural query-depth ceiling still bounds literal nesting.

- Keep SSE streams open through transient lease-renewal errors. With the
  Redis-backed per-account stream cap, a single failed renewal (for example a
  two-second Redis timeout) closed the stream although the 45-second lease
  allows several renewals, so a short Redis blip closed every stream at once and
  clients reconnected into 503s. A failed renewal is now retried every five
  seconds while the last confirmed renewal is less than 40 seconds old (lease
  TTL minus a five-second safety margin); a renewal that Redis answers with "not
  owned", or errors that outlast that window, still end the stream exactly as
  before, without backend details. Streams of one process also share a single
  Redis client (connection pool) per URL instead of opening one connection per
  stream.

- Isolate each channel-layer group in automatic subscription fan-out on the
  synchronous (WSGI, Celery, management command) path. A model write sends its
  event to up to four groups; when the first `group_send` raised, the remaining
  groups never received the event, while the ASGI path already isolated each
  group. Each group now fails independently on both paths. The drop log also
  names the qualified exception class and its causes (for example
  `redis.exceptions.ConnectionError`) instead of only the bare class name; it
  still never includes exception messages, group names or event data.

- Serialize `Decimal` output in plain positional notation. Values loaded with
  `decimal_places >= 7` were emitted through `str()` as `0E-8` or `5.0E-7`; they
  now come out as `0.00000000` and `0.00000050`. Normal values are unchanged.

- Make the numeric directives work on `Decimal` and `BigInt` fields. `@round`,
  `@floor`, `@ceil` and `@abs` converted the value to `float`, so `@round` on a
  `Decimal` returned the binary expansion of the float
  (`12.3499999999999996...`) and `@abs` on a `BigInt` returned null with a
  coercion error. They now compute on the exact `Decimal` or `int` (`@round`
  rounds half to even), and `@number`/`@currency` return the raw value on these
  scalar types, as they already did on `Int` and `Float`.

- Isolate batch items from each other and answer every item. With
  `ATOMIC_REQUESTS`, any error in one item of a batched request marked the whole
  request transaction for rollback: the first item answered 200 with `ok: true`
  but nothing was persisted, and later mutations failed with "Unable to complete
  the data operation.". Each batch item now runs in its own savepoint on every
  connection that wraps the request in a transaction, so an erroring item rolls
  back only its own writes and earlier and later items commit; the request-level
  mutation error flag is also scoped to one item. A non-batched request keeps its
  request-level rollback. The batch abort rule was also inconsistent: only an
  HTTP 400 request error cut the batch short, while syntax, validation and
  `operationName` errors continued, so the response had fewer entries than the
  request. Every item now yields exactly one entry, in order, and later items
  always run; the HTTP status is the highest entry status. This replaces the
  "stop later operations" behavior introduced earlier in this release (M-H1).

- Keep custom scalar coercion failures as client errors in production. A custom
  scalar whose `parse_value`/`parse_literal` raises `ValueError`/`TypeError`
  (the graphql-core convention for invalid input) was classified as an internal
  error by the production formatter: the client got HTTP 400 with
  `INTERNAL_SERVER_ERROR` and every such request wrote an ERROR log with
  traceback. Errors raised while parsing, validating or coercing variables are
  now classified by phase as validation errors: graphql-core's message is kept
  without the raw exception text (unless `DEBUG`), there is no ERROR log, and
  errors raised during execution keep their masking and log.

- Apply the target output type's `get_queryset` to flat `GenericForeignKey`
  targets in every schema. Without `PERMISSION_SCOPED_SCHEMA` the flat
  `GenericForeignKeyType` still returned `appLabel`, `modelName` and `id` of a
  target that its registered output type hid; it now resolves to `null`, like
  the permission-pruned field already did, and the pruned and full schemas use
  one rule. The check is batched in one `GenericPrefetch` for optimized and list
  reads (query counts do not grow with the number of owners); a resolver
  without it issues one membership query per target of a type that overrides
  the hook. Targets of unregistered models, and types keeping the default
  hook, are unchanged.

- Apply a member type's `get_queryset` to typed `GenericForeignKey` union
  targets. A `Meta.unions` union returned the target of any member in full even
  when that member type's hook hid the row. A hidden target now resolves to
  `null`, like a missing one. Optimized and list reads scope the targets in one
  batched `GenericPrefetch` per request, stored under a dedicated attribute so a
  cached unscoped target is never trusted, so query counts do not grow with the
  number of owners; only the union's own member models are scoped, and a member
  with a hook loads full rows instead of the narrowed `.only()` columns. A
  resolver without that prefetch issues one membership query per target of a
  type that overrides the hook. A sliced hook, or two scoped members sharing a
  content type, resolves per row instead. Types keeping the default hook are
  unchanged.

- Require a child update host to adopt an existing reverse `OneToOneField`
  orphan by ID. Naming the ID of a child whose nullable one-to-one key is null
  in a parent update re-parented and rewrote that child with no host check and
  no scope, because the adoption guard only covered reverse `ForeignKey`. It
  now follows the same rule: a registered child `DjangoModelType` or
  `DjangoModelMutation` serving update must exist, and its scope and
  permissions apply. Children the parent already owns and new children are
  unchanged.

- Scope forward `OneToOneField` links like `ForeignKey` links. A generated
  create or update could point a one-to-one field (scalar ID or nested id-only
  payload) at a row hidden by the destination output type's `get_queryset`, and
  a nonexistent ID answered differently, so it was also an existence oracle.
  Hidden and nonexistent IDs now return the same `Invalid pk ... object does
  not exist.` relation error. The ID membership check also runs one query per
  relation instead of one per ID (200 tags cost 209 queries before), and the
  nested M2M existence and already-linked checks are batched.

- Make the depth and cost walkers iterative. `DepthLimitValidationRule` and the
  cost estimator recursed once per fragment link and per nesting level, so an
  acyclic chain of ~1000 fragments (~38 KB) raised `RecursionError` and answered
  HTTP 500. They now use an explicit stack with the same verdicts, messages and
  memoization. Documents that exceed graphql-core's own recursive parser or
  validator (about 250 nested selection sets, several hundred chained
  fragments) are answered as HTTP 400 `QUERY_TOO_DEEP` instead of 500, on the
  HTTP view and the subscription transports; resolver errors are unaffected.
  `DepthLimitValidationRule` also enforces a hard ceiling of 100 nested object
  levels even when `MAX_QUERY_DEPTH` is unset or larger: Python's stack cannot
  execute deeper documents (with data, requests fail with an internal error
  from about 130 levels), and fragments hide depth from the parser. Deeper
  documents get HTTP 400 `QUERY_TOO_DEEP` instead of an internal error.

- Bound the queryset optimizer for fragments reached through distinct relation
  paths. Memoizing by selection context only helped a fragment repeated in the
  same context; a document such as `author { ...A }` / `coAuthors { results {
  ...A } }` where each fragment reaches the next through four relations
  describes 4**n distinct `select_related`/`prefetch_related` lookups, so a
  ~1 KB anonymous request took more than 20 s of CPU on an empty database. The
  new `OPTIMIZER_WORK_BUDGET` setting (default 2000, `None` disables) caps the
  selection contexts each optimizer walker expands per request, including the
  scoped to-one walker that ran a second exponential pass. Past the cap deeper
  relations are not planned and load through the normal resolvers (results are
  identical, scoped relations stay scoped); a DEBUG record names the walker.

- Fix import-time failures of the one-public-output-type guard. A user
  `DjangoObjectType` declared after a mutation (or `DjangoModelType`, or list
  type) for the same model now replaces the generated placeholder, and the
  mutation payload resolves to the user type instead of exposing every column.
  Re-executing the same declaration (reload, re-import, notebooks, the
  benchmark harness) replaces the stale type instead of raising, and no longer
  leaves stale compile entries or duplicate input names behind. Two distinct
  user types for one model in one registry are still rejected; the error now
  suggests `skip_registry = True` or a separate `Registry`.

- Compile only direct `typing.Union[int, str]` and `int | str` input fields,
  in either member order, as a shared `IntOrString` scalar instead of `String`.
  Integer and string values retain their Python types without casts; integers
  must fit signed 32-bit range. Booleans, floats, objects and lists reject
  before mutation. Outer nullable forms, omitted fixed/factory defaults and
  aliases remain unchanged; other Union shapes and global scalars do not.
  Clients must update variable declarations and generated bindings.

- Compile exact `dict[str, bool]` and `typing.Dict[str, bool]` direct mutation
  inputs as strict `JSON` instead of `String`. Require string keys and exact
  Boolean values before resolution without changing the global JSON scalar
  or omitted fixed/factory defaults. Clients must send JSON objects, not
  encoded strings; list-wrapped and other map forms retain their fallback.

- Compile exact `set[decimal.Decimal]` and `typing.Set[decimal.Decimal]`
  mutation inputs as `[Decimal!]!` instead of `String!`. Existing native
  Decimal coercion preserves finite precision through list/singleton inputs;
  resolvers receive a deduplicated Python set without ordering guarantees.
  A field-local check rejects supplied NaN, sNaN and infinities before
  resolution and omitted sibling factories. Global Decimal and legacy
  fixed/factory-default behavior remain unchanged; other sets keep fallback.
  Clients must migrate encoded strings to native Decimal lists or singletons.

- Compile exact `set[uuid.UUID]` and `typing.Set[uuid.UUID]` mutation inputs
  as `[UUID!]!` instead of `String!`. The existing native UUID scalar accepts
  canonical, uppercase and 32-hex strings in lists or singleton form and
  rejects invalid UUIDs before resolution. Resolvers receive a deduplicated
  Python set of UUID objects without an ordering guarantee. Existing outer
  optional/default behavior remains; other set forms keep fallback. Clients
  must migrate encoded strings to UUID string arrays or singletons.

- Compile exact `set[float]` and `typing.Set[float]` mutation inputs as
  `[Float!]!` instead of `String!`. Native GraphQLFloat coerces finite numeric
  list/singleton inputs, including integers, before resolvers receive a
  deduplicated Python set without ordering guarantees. A field-local check
  rejects overflowing numeric literals before resolution while preserving
  malformed legacy defaults. Other unapproved set forms keep fallback;
  existing optional/default behavior remains. Clients must migrate
  encoded strings to numeric arrays or singletons.

- Compile exact `set[bool]` and `typing.Set[bool]` mutation inputs as
  `[Boolean!]!` instead of `String!`. Native GraphQLBoolean validation and
  list/singleton coercion apply; `false` reaches resolvers as `{False}`.
  Duplicates are removed with no ordering guarantee. Existing outer
  optional/default behavior remains; unapproved set forms retain fallback.
  Clients must migrate encoded strings to boolean arrays or singletons.

- Compile exact `set[str]` and `typing.Set[str]` mutation inputs as
  `[String!]!` instead of `String!`. Native GraphQLString validation and
  list/singleton coercion apply; resolvers receive a deduplicated Python set
  with no ordering guarantee. A singleton `"ab"` stays one member, not
  two characters. Existing outer optional/default behavior remains; other
  set forms keep their fallback. Clients must migrate encoded strings to
  string arrays or singleton strings.

- Compile exact `set[int]` and `typing.Set[int]` inputs as `[Int!]!` rather
  than `String!`.
  GraphQL applies its standard integer validation and singleton-list coercion;
  resolvers receive a deduplicated Python set with no ordering guarantee.
  Existing optional/default behavior remains, while other unapproved set forms keep
  their earlier fallback. Clients must replace encoded strings with integer
  arrays or singleton integers.

- Compile nested lists of already-supported input leaves with recursive
  GraphQL list/nullability wrappers instead of a one-level String fallback.
  GraphQL applies ordinary singleton-list coercion at each level; supported
  JSON, strict typed-map, Literal enum, and nested input leaves keep their
  existing contracts. Unsupported leaves keep the earlier fallback. Valid
  nested JSON list defaults can now render in SDL and introspection.

- Compile exact `dict[str, str]` and `typing.Dict[str, str]` input fields
  to the shared raw `JSON` scalar. Require object inputs with string keys
  and string values without conversion; invalid values fail before mutation
  resolution. Clients must replace legacy encoded String values with JSON
  objects. Other dictionary forms remain unchanged.

- Treat exact `typing.Dict[str, int]` input fields like `dict[str, int]`: shared
  JSON scalar, strict plain-integer object checks before mutation resolution,
  and the same wrapper/default behavior. Clients using the typing alias must
  replace legacy encoded String values with JSON objects. Other typing forms
  remain unchanged.

- Do not register a generated model output type for a `DjangoModelMutation`
  rejected by unsupported `permission_classes` or `model_operations`.
  This removes a test-order-dependent registry conflict without changing the
  error messages, valid CRUD declarations, or the one-public-type rule.

- Compile exact `dict[str, int]` input fields to the existing raw `JSON`
  scalar instead of `String`. Accept objects with string keys and plain
  integer values without implicit conversion; invalid values fail before
  mutation resolution. Bare `dict` and other typed-container fallbacks stay
  unchanged. Clients must replace JSON-encoded strings with objects.
  Fixed JSON defaults with GraphQL Name object keys now render in SDL and
  default-value introspection without changing runtime values. Defaults with
  non-Name keys retain runtime behavior and their metadata limitation; use
  a zero-argument factory when metadata must render. Valid fixed JSON list
  defaults now render in SDL and introspection; their outer list may be copied
  while elements stay unchanged. Malformed list defaults retain legacy behavior.
  Unpaired
  Unicode surrogates and integers beyond Python's configured
  integer-to-string limit also retain runtime defaults without new SDL metadata.

- Compile all-string hand-authored input `Literal` annotations as generated
  GraphQL enums. Inline operations and JSON variables now send enum members
  rather than raw strings; resolvers still receive the original strings.
  Numeric/mixed literals and other unsupported typing forms retain their
  warning and `String` fallback.

- Align automatic nullable-column ordering in limit/offset and page pagination
  across queryset, nested SQL-window, and materialized-list paths: NULL last
  ascending, first descending. Explicit ORM expressions, term priorities,
  primary-key ties, and Cursor pagination retain their existing behavior.

- Reject negative integer `MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE`, and
  `DOCUMENT_CACHE_MAXSIZE` values when each setting is read, using the existing
  configuration error with a minimum of zero and a remedy. Zero, `None`,
  positive values, defaults, and existing noninteger handling are unchanged;
  this does not add eager startup validation.

- Apply configured `MAX_UPLOAD_SIZE` to each received multipart file, including
  unused and repeated parts. Files over the limit now receive JSON HTTP 413
  before resolver execution; equality and `None` retain their documented
  behavior. Base64 limits and the separate whole-request body cap are unchanged.

- Return HTTP 200 with `data: null` and `errors` from the enhanced JSON view
  when a field execution error nulls a non-null root result. Syntax,
  validation, and variable-coercion failures remain HTTP 400 without data;
  errored responses are not cached. Batch transport errors and other HTTP
  policies are unchanged.

- Distinguish malformed model primary-key IDs from well-formed missing or
  scoped-out IDs in `get_node`, generated retrieve fields, and
  `DjangoObjectField`. Malformed IDs now produce a safe `INVALID_ID` GraphQL
  error with an expected-format hint; missing/hidden IDs still resolve to
  `null` without an error. Valid text IDs and existing ORM coercion remain.

- Report a stable GraphQL field error when `@floor` receives NaN or either
  infinity, including numeric strings that coerce to those values. Finite and
  null values, malformed-number errors, other directives, and schema metadata
  are unchanged.

- Declare library transformation directives on GraphQL fields only. Placing
  them on fragment spreads or inline fragments now fails validation instead
  of silently doing nothing; place transforms on fields inside fragments.
  Standard `@skip`/`@include`, raw third-party directive locations, and
  field-transform execution remain unchanged.

- Reject non-finite numbers in raw `JSON` inputs, including nested variable
  values and overflowing float literals, with a GraphQL input error before
  resolver execution. Finite values, numeric strings, missing-variable
  handling, raw `JSON` outputs, and `JSONString` remain unchanged.

- Preserve positions in raw `JSON` list literals when an optional variable is
  omitted: the missing member now resolves to `null` instead of leaking an
  unserializable sentinel. Missing object-literal keys remain omitted;
  supplied values, defaults, explicit null, and ordinary typed lists are
  unchanged. This does not change `JSONString`, top-level missing-argument
  behavior; non-finite raw input rejection is documented separately above.

- Preserve GraphQL null values through `@number` and `@currency` instead of
  formatting absent values as zero. Required fields now use normal GraphQL
  nullability errors and bubbling. Format validation, width/precision caps,
  raw numeric field passthrough, and non-null falsy value handling remain.

- Normalize output values of `@camel_case`, `@snake_case`, and `@kebab_case`
  across spaces, underscores, hyphens, camel/Pascal boundaries, and acronym
  blocks. `orderTotal` now becomes `order_total` or `order-total`, and
  `HTTPServer` becomes `httpServer`, `http_server`, or `http-server` in
  directive order. Schema names, shared converters, and other directives are
  unchanged; punctuation and other character forms retain prior handling.

- Display aware Python datetimes and text with an explicit numeric offset or
  `Z` in Django's active timezone for absolute `@date` formats, preserving
  the instant while allowing date rollover. Explicit-offset/Z text retains
  its prior relative behavior; `iso` still omits its output offset and
  microseconds. Clock-adjacent `+00:00` and `+0000` now receive the same
  absolute conversion as equivalent `Z` text.

- Interpret accepted timezone-less text passed to `@date` as its written wall
  clock in Django's active timezone for absolute and relative formats,
  regardless of `USE_TZ`. Relative wording can change. Named UTC/GMT and
  unknown timezone names, Python inputs and missing-date filling retain their
  existing behavior; no daylight-saving gap/overlap policy was added.

- Default omitted time components in accepted textual `@date` values to zero,
  including seconds and microseconds of partial times. Missing date components
  still use the current date; explicit components and null behavior are
  unchanged. The aware-value conversion above is a separate change.

- Preserve GraphQL null values through `@date`, including fields with an
  explicit format. Non-null fields now follow normal GraphQL error and null
  propagation when their resolver returns null; other directives are unchanged.

- Match exact finite native Float subscription filters against finite float
  event snapshots by numeric equality. Full-payload signed zeros now match in
  either direction, including direct legacy `split_filters` calls with two
  actual floats. Previously dropped matching events may arrive. Raw strings,
  mixed types, Boolean/null, non-finite fallback, missing fields, other
  lookups, and indexed group routing keep their existing behavior.

- Match automatic delete notifications against signal-time projected scalar
  equalities even with id-only public payloads. Server-forced scope still wins
  over conflicting client filters, and private values never become GraphQL
  output. Deferred, missing, nonprojected, id-only relation, and lookup conditions remain
  conservative; create/update and manual notification behavior is unchanged.

- Add independently opt-in SSE idle heartbeat comments (15-second setting)
  and a shared Redis-backed concurrent stream cap for authenticated accounts
  (five-stream setting). Both remain off by default. A full account receives
  HTTP 429, unavailable admission HTTP 503, and a lost midstream lease a
  generic SSE error and completion; anonymous, WebSocket, and authentication
  behavior is unchanged. Redis lease expiry and failover are documented limits.

- Add optional async `on_connect(scope, payload)` authentication to the
  subscription WebSocket consumer. An authenticated callback result replaces
  the socket user before ACK, schema resolution, and permission checks;
  malformed payloads close with `4400`, denied credentials with `4403`, and a
  stalled callback with `4408`. Without the hook, existing session identity
  and ignored initialization payloads are unchanged. Projects provide their
  own credential verifier; HTTP, SSE, and persistent sessions are unchanged.

- Reject subscription WebSocket handshakes before acceptance when the client
  does not offer the exact `graphql-transport-ws` subprotocol. Accepted clients
  may offer it among alternatives. The server logs an actionable diagnostic;
  pre-accept rejection is normally HTTP 403 on the wire, so browsers may show
  only a generic connection failure. Configure the client's subprotocol offer;
  no authentication, SSE, or HTTP behavior changed.

- Preserve microseconds in native full-payload subscription DateTime event
  snapshots. Typed exact DateTime filters now compare the captured instant,
  including equivalent aware offsets, and native DateTime event fields use the
  existing output scalar without a later row lookup. SSE and WebSocket share
  the corrected delivery path; nullable and other scalar fields, id-only
  payloads, and custom resolver contracts are unchanged. Previously dropped
  equal events can now arrive; older truncated snapshots cannot recover lost
  precision.

- Scope automatic declared and reverse M2M output lists with the destination
  type's request-specific `get_queryset`. A visible parent retains its row,
  while hidden linked targets leave `results` and the pre-pagination
  `totalCount`; an empty or hidden-only relation returns `[]` and `0`.
  Optimized reads use a scoped prefetch rather than trusting an unrelated
  relation cache. Explicit resolvers, through-model access rules, custom
  filters, and ordering are not changed.

- Apply the destination type's request-specific `get_queryset` to automatic
  forward and reverse OneToOne output reads. A visible parent keeps its row
  while a hidden linked destination resolves to `null`; genuine absent
  relations and the nullable output shape are unchanged. Scoped to-one reads
  are batched for ordinary list traversal, including when queryset optimization
  is disabled. Explicit resolvers and M2M output reads have separate rules.

- Scope nested forward OneToOne destination-field filters to the destination
  type's request-specific `get_queryset`. A visible profile cannot match a
  hidden linked user's fields; real absent OneToOne NULL matches, unrelated
  Boolean branches, and direct source-column ID lookups keep their existing
  meanings. Reverse OneToOne filters already used the destination hook.
  Automatic OneToOne output reads have the separate rule above; custom filters
  and ordering are unchanged.

- Scope forward and reverse many-to-many filters to each destination type's
  request-specific `get_queryset`. A linked hidden target no longer satisfies
  a nested field or target-ID predicate. One relation object retains one
  visible target witness, separate `and` branches may use different targets,
  and `not` complements the matching-parent set. Empty and absent-target
  predicates keep their existing meanings. M2M output reads have the separate
  rule above; through models, custom filter bodies and ordering are unchanged.

- Scope public nested forward-FK filters to the destination type's
  request-specific `get_queryset`. Hidden target rows no longer make a
  visible source row match; each hop in a forward-FK chain is checked.
  Real absent-FK NULL matches, unrelated Boolean branches, and direct source
  FK-ID predicates retain their existing meanings. This does not scope
  custom filter bodies or ordering. Forward OneToOne
  and M2M filters have separate bounded rules.

- Scope public reverse-FK filters to the child type's request-specific
  `get_queryset`. One visible child must satisfy each grouped predicate;
  separate `and` branches retain independent visible witnesses, and `not`
  complements the matching-parent set. Direct reverse-child IDs are scoped,
  unlike direct forward source FK IDs. Default and named output accessors now
  resolve declarations using their ORM query names without reopening a
  declared or pruned relation. M2M has the separate bounded rule above;
  forward OneToOne has the separate bounded rule above.

- Apply the destination type's `get_queryset` hook to automatic forward-FK
  and reverse-FK output reads. Hidden nullable FK targets now resolve to
  `null`; reverse-FK results, windows, and `totalCount` include only visible
  rows. Optimized scoped FK reads stay batched, while disabling optimization
  can add per-parent scope queries. Automatic OneToOne has the separate rule
  above; M2M outputs have their own rule, while custom resolvers and other
  joined filters remain outside this FK rule. Clients previously relying on expanded
  hidden rows should review their destination hooks before upgrading.

- Add a local, evidence-bounded disposition of the 100 original audit claims
  in [the 4.0.0 audit report](docs/audit-4.0.0.md). It separates scoped fixes,
  current contracts, recommendations, limited negative checks, and pending
  policy decisions. This is not a release or a claim that all issues are closed.

- Document current subscription, timezone, cache-cookie, partial-update and
  pagination boundaries without changing runtime behavior. The guides now
  distinguish automatic signals from manual broadcast, directive timezone
  assumptions, browser cookie cache bypass, partial-input versus SQL saves,
  and cursor versus offset/page NULL ordering.

- Close test-owned temporary multipart uploads and ASGI request-body spools
  after direct view dispatch, including exceptional exits. This changes test
  fixture ownership only; HTTP behavior and upload limits are unchanged.

- Match finite typed Decimal subscription `exact` filters by numeric value
  against the event-time JSON-safe snapshot. A filter value of `1.0` now
  matches a full-payload `"1.00"` on create and delete without a row lookup.
  Valid high-precision model values also match without an arbitrary 256-character
  cutoff. String-valued server scopes, malformed/non-finite values, other scalar
  filters, and the Decimal wire payload retain their existing behavior.
  Native DateTime snapshots have the separate lossless rule above.

- Route nested creates using one populated, unsaved parent instance with the
  included Django backend, then pin native parent and child writes to that
  selected alias in one transaction. A later child failure rolls back earlier
  same-alias writes and commit callbacks. Updates retain the existing parent's
  alias; direct non-nested creates and custom serializer backend create calls
  keep their prior contracts. A divergent M2M through route fails before the
  first write, or before linking after a generated ID while rolling back local
  writes. Cross-database transactions and routers changing answers between
  the check and link operation are not coordinated.

- Queue automatic subscription save and delete notifications on the database
  alias that performed the write. Routed secondary writes now wait for their
  own commit, disappear on rollback, and are not delayed by an unrelated
  default-database transaction. Missing-channel-layer warnings follow the
  same alias; this does not add cross-database atomicity.

- Complete Google-style docstrings in tracked regression tests for metadata
  errors, schema isolation, source properties, optimizer plans, and permission
  caching. This is a test-documentation change only; library behavior is
  unchanged. Local ignored profiling scripts are outside the clean checkout.

- Warn when unsupported hand-authored input annotations such as numeric or mixed `Literal`,
  parameterized `dict` or `set`, and non-optional `Union` fall back to GraphQL
  `String`. Existing SDL, coercion, and resolver dictionaries are unchanged;
  this does not add structured input conversion or automatic Pydantic validation.

- Apply field directives after awaiting resolver values in native asynchronous
  graphql-core execution, rather than formatting coroutine representations.
  Built-in synchronous HTTP views still reject asynchronous execution with
  their existing JSON 500 error; this does not add asynchronous HTTP support
  or change directive names, arguments, or synchronous results. Defer directive
  coroutine creation until native execution awaits it so an outer middleware
  cannot leave an unawaited inner coroutine after synchronous HTTP rejection.

- Clean up subscription group memberships when WebSocket or SSE startup is
  cancelled after a backend join but before the join call returns. Partial
  startup failures attempt the same source-owned cleanup while preserving the
  original error. Failed sources remain retryable unless explicitly closed;
  backend discard failures are logged and remain best-effort. Wire frames,
  authentication, and ordinary subscription delivery are unchanged.

- Release a WebSocket subscription's operation ID after source teardown and
  before sending its server `complete` frame, so an immediate same-ID subscribe
  is not mistaken for a concurrent duplicate. Late callbacks cannot remove a
  replacement operation; client cancellation and existing error framing are
  unchanged.

- Share one global registry instance on concurrent first access and one
  auto-generated list class per model and built-in registry on concurrent
  misses. Explicit list registration keeps its last-registration-wins rule;
  names, SDL, pagination and filter configuration are unchanged. This is not
  a general registry or schema thread-safety guarantee.

- Share one enum type for concurrent equivalent cache misses and retain the
  existing incompatible-choices error when definitions race in one registry.
  Native enum names, member order, values and serial schema output are
  unchanged; this is not a general registry thread-safety guarantee.

- Track native mutation field identity only while the field remains alive.
  This prevents a stale integer identity marker from classifying an unrelated
  raw GraphQL field internally, while retaining live fields after a later
  mutation class overwrites their model-and-operation registry slot. Mutation
  SDL and public declarations are unchanged; this does not promise general
  schema or registry reclamation.

- Diagnose a suppressed `RuntimeError` while closing a subscription delivery
  source with a server-side warning and original traceback. Close remains
  best-effort and idempotent, with no new client frame or propagation; a benign
  already-closing generator race can also produce this warning. Normal
  cooperative cancellation is unchanged.

- Report an explicit `source=` Python property's original `AttributeError`
  as a GraphQL field error when it escapes normal Python lookup, including
  getters wrapped with `functools.partial` or `functools.lru_cache`. Successful
  dynamic fallback, final dynamic absence, missing attributes, legitimate
  null values, and absent Django reverse one-to-one relations keep their
  existing behavior; required fields and production HTTP formatting are
  unchanged.

- Stop schema construction when Django model field enumeration fails instead
  of publishing a concrete-fields-only type that may omit reverse relations.
  The configuration error names the model and retains the original exception
  as its cause, including through eager and lazy GraphQL field compilation.
  Existing installations that depended on the partial-schema fallback must
  fix the underlying metadata error; healthy schema output is unchanged.

- Batch typed GenericForeignKey targets selected through valid inline or named
  fragments on the enclosing union. Member-specific column projection and
  nested relation joins now match direct member fragments, avoiding per-row
  queries without changing the schema or public API.

- Fix order-dependent registry tests by restoring the cached default schema
  pair after temporary test scopes, including nested and exceptional exits.
  This changes only test isolation; library behavior and public APIs are
  unchanged.

- Keep output registrations independent of an unrelated thread's forked schema
  build. A projected node/list type no longer degrades a later list result to
  `[String]` under that overlap; same-thread fork isolation remains intact.

- Keep a cached permission-scoped schema available while an unrelated cold
  signature is being pruned. Cold builds and cache clearing remain serialized;
  permission keys, cache bounds and public settings are unchanged.

- Plan queryset relations, annotations, filtered prefetches, and column
  projection across all field nodes merged under one root GraphQL response key.
  A relation selected only in a later root fragment no longer triggers
  per-row queries; schema and public settings remain unchanged.

- Clarify the explicit-`None` pagination documentation: when no request size,
  default, or maximum supplies a size, LimitOffset returns all rows, Page
  returns `results: null`, and Cursor uses its final 20-row fallback. Ordinary
  omitted constructor sizes still inherit the 100-row startup default; this
  corrects an ambiguous API table without changing runtime or error behavior.

- Correct the cache-key documentation: `fetch_cache_key(request)` hashes the
  raw body even on a GET request that carries one, alongside framed GET
  parameters. This is not a recommendation to send GET bodies; use query
  parameters or POST JSON. Cache-key behavior and existing entries are
  unchanged.

- Preserve `null` and empty-list schema values for selected `__schema` and
  `__type` queries whose root fields are reached through inline or named
  fragments when `CLEAN_RESPONSE=True`. Previously those fragmented
  introspection responses could be cleaned into incomplete data. Mixed ordinary
  roots still use normal cleaning; `CLEAN_RESPONSE=False`, defaults, and
  introspection authorization are unchanged.

- Keep the two public HTTP view constructor checks active under optimized
  Python (`-O`): a schema without `graphql_schema` or simultaneous GraphiQL
  and batch modes still raise their existing `AssertionError` messages when
  the view is constructed. Other assertions and validation policies are
  unchanged.

- Improve date-part test portability by removing exact runtime-version,
  checkout-path, and working-directory assertions from the behavioral test.
  A separate regression contract keeps those local proof checks external;
  this does not change date-part filtering or expand the supported version
  range.

- Preserve completed results when a valid GraphQL batch reaches an operation-
  level HTTP 400 request error. Return an HTTP 400 array ending with that
  error, stop later operations, and leave prior successful mutations committed.
  Previously the error-only object hid earlier results. Malformed batch
  bodies and non-400 transport errors keep their existing envelopes;
  `ATOMIC_MUTATIONS` remains per operation.

- Clarify that `ALLOW_INTROSPECTION=False` blocks `__schema` and `__type` only
  when `DisableIntrospectionMiddleware` is installed in GraphQL `MIDDLEWARE`.
  The default middleware chain is empty, so deployments relying on the setting
  alone should explicitly install the middleware. This is a documentation
  correction; the runtime defaults and introspection behavior are unchanged.

- Reject unsupported async resolver, middleware, and executor results on the
  synchronous built-in HTTP views with a controlled HTTP 500 GraphQL JSON
  error. Newly created, unstarted coroutines owned by execution are closed
  without running them. Previously this configuration could produce an HTML
  500 and unawaited-coroutine warnings. Use synchronous resolvers and
  middleware for HTTP; this does not add async HTTP support or change SSE and
  WebSocket subscriptions.

- Cache only HTTP 200 GraphQL data responses without errors when
  `CACHE_ACTIVE=True`. Partial-data execution errors, validation failures and
  other non-200 responses are returned normally but re-execute on the next
  request; previously stored failed entries are ignored without clearing the
  cache. A later success can be cached under the existing key. Clients or
  operators relying on cached error replay should allow fresh execution;
  successful cache hits, identity isolation, hooks, cookies and mutation
  invalidation remain unchanged.

- Preserve numeric zero and `false` in ordinary `GraphQLView` responses when
  `CLEAN_RESPONSE=True`, including nested fields and arrays. Clients that
  relied on these values being omitted will now receive them. Nulls, empty
  strings and empty containers are still removed recursively; the default
  `CLEAN_RESPONSE=False` and selected introspection responses are unchanged.

- Replace unexpected resolver-exception details on built-in HTTP views when
  `DEBUG=False` with safe `DATA_ACCESS_ERROR` or `INTERNAL_SERVER_ERROR`
  diagnostics and an opaque `errorId` correlated with restricted server logs.
  Clients must stop relying on raw exception text or custom extensions from
  these failures. Deliberate `GraphQLError`, validation errors, existing
  generated-mutation errors, `DEBUG=True`, and WebSocket/SSE formatting are
  unchanged; custom `format_error` overrides remain application-owned.

- Frame the default response-cache body and GET components before SHA-256
  hashing. Two different selected GET operations can no longer share a cache
  entry through ambiguous concatenation within one identity. Existing cached
  responses cold-miss and expire normally; the 64-hex digest shape and custom
  `fetch_cache_key(request)` override contract remain unchanged.

- Reject a selected GraphQL operation before resolution when its real,
  GraphQL-coerced request variables or defaults put it over `MAX_QUERY_COST`,
  including document-validation cache hits. A variable page size that previously
  passed the static fallback estimate may now return HTTP 400 / `QUERY_TOO_COMPLEX`.
  Conservative static validation remains: a cheap variable cannot undo an
  earlier fallback-based rejection. `MAX_PAGE_SIZE` is still optional, though
  recommended for unbounded lists; the public cost model/API is unchanged.
  A mutation refused before resolver execution does not invalidate a warmed
  response cache; an earlier executed mutation in a non-atomic batch still does.

- Make bounded model-backed LimitOffset and Page slices deterministic within ties by
  appending the primary key ascending after the existing ordering, unless the
  key is already present. This includes nested window and materialized model
  paths; explicit primary-key direction and client ordering validation remain.
  Clients relying on unspecified tie order may see rows move. Offset pages can
  still shift after concurrent inserts/deletes or random primary ordering.
  Unbounded, unconfigured LimitOffset lists retain their original queryset and
  `totalCount` cache behavior. Existing server queryset reversal and legacy
  `extra(order_by=...)` precedence remain effective ahead of the new key,
  including nested pages.

- Return a generic GraphQL error when a negative page's database `COUNT` fails,
  instead of loading the full queryset to recover the page. Clients relying on
  a successful page after a count-only failure should handle `Unable to
  calculate pagination count`; database details stay out of the response.
  Positive pages and the separate `totalCount` resolver are unchanged.

- Change the library `DEFAULT_PAGE_SIZE` from `None` to `100`. Omitted sizes on
  the global LimitOffset paginator and default-constructed Page/Cursor
  paginators now return the first 100 rows; clients must paginate for later
  rows. An explicit positive global or per-type size still wins. This is not a
  new maximum (`MAX_PAGE_SIZE` remains `None`), and explicit `None` retains each
  paginator's existing behavior, including Page's `results: null` when no
  effective size exists. Set `DEFAULT_PAGE_SIZE` before importing paginator
  classes at startup; existing instances are not hot-reloaded.

- Fix generated relation filters when a related field is named `year`,
  `month`, `day`, `range`, or `exact`: nested field lookups now reach that
  field, while direct relation `exact`/`in`/`range` lookups target the related
  primary key even when a field has the same name. Generated SDL and input
  shapes are unchanged; previously failing valid requests now return their
  matching rows.

- Treat explicit `page: null` as omitted `page` (first page 1) for page-number
  pagination on root and nested lists. This replaces the previous raw
  comparison error for null; clients relying on that error should reject null
  before sending a request. The nullable `page: Int = 1` schema, zero-page
  error, and negative-page behavior are unchanged.

- Continue in-memory cursor pages ordered by FloatField, DecimalField, or
  UUIDField using server-emitted cursors. Nested materialized lists now match
  queryset-backed lists on the next page; cursor tokens, SDL, ordering,
  and queryset behavior are unchanged.

- Report decoded cursor values that cannot convert to FloatField, DecimalField,
  or UUIDField as `GraphQLError("Invalid cursor")` for results and pageInfo on
  both queryset-backed and materialized lists. Previously, materialized lists
  exposed a raw comparison TypeError; clients matching that message should
  handle `Invalid cursor` instead. Valid server-emitted cursors, cursor bytes,
  SDL, and other scalar error policies are unchanged.

- Let separate explicit `and` filter branches over a many-to-many or reverse
  foreign-key relation match different related rows, including when nested
  beneath `or` or `not` and inside another relation object. One outer related
  row must satisfy that object's criteria; its deeper `and` branches may use
  different rows of their own relation. Queries that previously returned no
  parent may now return one;
  group criteria in one relation object to require same-row matching. Scalar,
  direct to-one, null and empty-Boolean behavior, generated SDL, and subscription
  filters are unchanged.

- Type explicitly declared numeric `DateField` and `DateTimeField` part filters
  as GraphQL `Int` so integer literals and variables reach Django. `DateField`
  supports `year`, `month`, `day`, `week_day`; `DateTimeField` also supports
  `hour`, `minute`, `second`. Clients using `$year: Date` or
  `$year: DateTime` must change to `$year: Int` and send an integer. Lookup
  exposure/defaults, full-value ISO `Date`/`DateTime` filters, `TimeField`,
  null/Boolean behavior, and subscription filters are unchanged.

- Make an explicitly supplied `exact: null` in generated query filters select
  SQL NULL rows, matching `isnull: true`; an omitted lookup still adds no
  predicate. This includes nullable relation IDs and JSON fields (SQL NULL,
  not JSON `null`). Clients using `exact: null` to mean “ignore this filter”
  must omit the lookup. Other null lookups, custom filters, empty Boolean
  operands, and the generated input schema are unchanged.

- Hide table, column, and constraint details from unclassified Django
  `IntegrityError` failures in generated create/update/delete GraphQL fields,
  including nested writes. Clients now receive the fixed top-level message
  `A database constraint prevented this operation.` instead of raw database
  text; the field remains `null`, with its GraphQL path and normal HTTP shape.
  Nested and atomic sibling rollback remain intact. Mapped unique/FK field
  errors stay structured, direct backend exceptions stay unchanged, and no
  general constraint validation or upsert is added.

- Validate supplied negative `PositiveIntegerField` and
  `PositiveSmallIntegerField` generated inputs before SQL, returning a
  structured field error without saving that mutation. Zero, positive values,
  `Int` bounds, choice Enum inputs, and omission/default behavior are unchanged.
  Because this is `ok: false` data rather than a GraphQL execution error, an
  earlier successful sibling root now commits even with `ATOMIC_MUTATIONS=True`;
  clients requiring all-or-nothing business operations must account for that
  migration. Unrelated execution errors still roll back.


- Validate supplied nonempty Django `EmailField` values with Django's email
  syntax rules in generated create/update and nested inputs. Invalid values
  now produce the existing structured field error without persistence; the
  GraphQL `String` schema for fields without choices, existing Enum SDL for
  choice-backed fields, and omission, null, empty-string, default, and
  partial-update behavior remain unchanged. Choice syntax checks use stored
  values, not display labels. This does not enable `full_clean()`
  or change other Django field validators. Clients previously sending malformed
  nonempty addresses must correct them.

- Replace Django collector details in generated delete `PROTECT`/`RESTRICT`
  failures with a generic GraphQL execution error. Both mutation frontends keep
  the existing field-null, HTTP and atomic rollback behavior; blocked deletes
  do not become `ok: false` payloads. Clients relying on the old collector
  message must migrate to the generic error and field path.

- Honor an explicit `name=` on `DjangoInterfaceType` fields and matching
  declared implementor fields. Their SDL, introspection, and queries now use
  the requested wire name; attributes without an explicit name retain
  camelCase. This changes the old accidental name (for example,
  `internalName` to `name`), so clients must update affected queries and
  generated types. No legacy alias is added.

- Preserve generated mutation create/update inputs for Django columns named
  `model_dump`, `model_validate`, or `model_config`. These previously failed
  Pydantic schema construction; their GraphQL names, validation errors, and
  persisted Django attributes now retain the original naming. Existing
  working column names and model-derived omission semantics are unchanged.
  Inherited `Meta.pydantic_model` validators and serializers for `model_config`
  continue to run without modifying the caller's base model.

- Evaluate zero-argument factories on hand-authored `InputType` fields for
  each new GraphQL-coerced input object rather than once at schema build.
  Factory values no longer appear as fixed SDL defaults; plain literal
  defaults, explicit values/null, resolver dict shape, model-derived partial
  updates, and validated-data factories keep their existing contracts. Clients
  relying on a generated SDL factory value must move to runtime input behavior.

- Make automatic model-signal subscription notifications best-effort across
  snapshot preparation and delivery. Ordinary notification errors now log
  metadata only and drop the event without failing a successful database save
  or generated mutation; later commit callbacks continue. Rollback still emits
  nothing, and explicit manual broadcasts remain strict. Applications that
  depended on automatic delivery exceptions should handle delivery explicitly;
  this does not add retries or an outbox.

- Run the documented synchronous WS/SSE subscription `schema_provider` in a
  thread-sensitive worker. Real Django users with cold permission caches can
  now use `pruned_schema_for` without synchronous ORM access on the event loop.
  Provider inputs, schema results, per-socket/per-request caching, and existing
  transport error behavior are unchanged; coroutine-returning providers are
  not a new supported contract.

- Redact the whole flat `GenericForeignKeyType` target to `null` in
  permission-pruned schemas when the actual target model's read permission is
  absent or its registered row hook excludes the row. The flat SDL, unpruned
  schemas, and typed GFK unions are unchanged. Schema-variant and HTTP response
  caches now include all grants only for schemas with the native flat fallback,
  so target permission grants and revocations do not reuse stale responses.
  Apps that relied on source-only permission for flat target metadata must
  grant target read permission and review target row scopes.

- Require a registered update-serving child write host to adopt an existing
  nullable reverse-FK orphan by ID through a generated parent update. The
  host's existing scope and permissions apply; without one the mutation
  returns a structured error and rolls back. New children, already-owned
  children, and the different-parent guard are unchanged. Applications that
  intentionally adopted hostless or read-hidden orphans must register an
  appropriate child update host and review their authorization policy.

- Check generated create/update foreign-key and many-to-many ID links against
  the request schema's destination `DjangoObjectType.get_queryset` when it is
  overridden. Hidden and nonexistent target IDs now share the ordinary
  structured invalid-pk error before persistence, including nested link
  operations whose extra attributes are ignored. Actual child writes and
  unscoped/default-hook paths retain their previous behavior and query
  cost; child-write permissions, relation reads, and ORM filter joins are
  unchanged. Apps that intentionally link read-hidden rows must migrate their
  destination scope or link workflow. Destination scopes may use callable hooks,
  duplicate-producing JOINs, ordered slices, or same-table proxies; membership
  follows the actual returned queryset window. A queryset for a different
  concrete table is rejected.

- Reject ambiguous generated `choices` enum member names with
  `ImproperlyConfigured` instead of assigning positional suffixes that could
  change literal meaning when choices are reordered. Adjust affected choices
  to generate distinct names and migrate clients using suffixed literals;
  unambiguous members and automatic enum type names are unchanged.

- Reject incompatible automatic `choices` enums that normalize to the same
  GraphQL type name in one registry with `ImproperlyConfigured` naming both
  model fields. Compatible definitions, including reordered members, still
  reuse one enum; existing noncolliding names and output, mutation-input and
  filter behavior are unchanged. Distinct registries remain isolated. Resolve
  a collision by separating schema surfaces or renaming an app, model or field.
  Such a change needs a corresponding client/schema migration; no enum-name
  override was added.

- Reject bare-string and unknown `DjangoObjectType.Meta.only_fields` or
  `exclude_fields` selectors at class definition, before registry mutation.
  Previously a typo could leave a sensitive model field published. Valid model,
  reverse-relation, private, and declared custom field names remain accepted;
  declared custom fields still compile independently of model projection.

- Reject a second distinct public `DjangoObjectType` for the same exact Django
  model and `Registry` with `ImproperlyConfigured`, rather than silently
  replacing the type used by nested relations. Re-registering the same class
  remains idempotent; separate registries, input/mutation registrations, and
  non-registering internal forks are unchanged. Existing public/admin schema
  variants over one model must use separate registries.

- Roll back default-database writes when GraphQL execution returns errors
  under `ATOMIC_MUTATIONS=True`, and mark Django `ATOMIC_REQUESTS` requests
  for rollback on those errors or the established mutation error flag.
  Rolled-back writes no longer advance the GraphQL response-cache version;
  durable non-atomic writes still invalidate it. Structured native mutation
  `ok: false` data remains distinct from a GraphQL execution error.

- Limit each `@replace` result to 1,000,000 Unicode characters by default,
  predicting Python's nonoverlapping replacement length before allocation.
  Over-limit results now produce a GraphQL field error, including when no
  replacement occurs; a result at the cap remains valid. Configure
  `MAX_REPLACE_OUTPUT_LENGTH` with a positive integer or `None` to restore
  uncapped legacy behavior. This is a per-result cap, not a query-wide quota,
  and does not change other directives or the HTTP body limit.

- Enforce the existing `MAX_REQUEST_BODY_SIZE` POST limit before the cache-active
  view parses a GraphQL document or accesses parse, validation, or response
  caches. Oversized requests keep their HTTP 413 response; the configured limit,
  default, valid/cache-hit behavior, and multipart measurement remain unchanged.

- Change auto-derived `DecimalField` output from `Float` numbers to the
  existing `Decimal` scalar's exact JSON strings, including model objects
  returned by generated mutations. `19.99` becomes `"19.99"`; large values no
  longer round through binary Float. Clients must migrate output SDL/types and
  number handling. Generated Decimal inputs and filters, explicit overrides,
  ordinary Float fields, and primary-key nullability are unchanged. An
  explicitly declared `Float` field with a Decimal-to-float resolver retains
  the former numeric output at the cost of precision. This output scalar cannot
  recover digits already rounded by a database backend.
- Map auto-derived `BigIntegerField` and `PositiveBigIntegerField` to the
  precise `BigInt` scalar in output, generated mutation inputs and automatic
  filters. Wire values are bounded decimal strings, including small values;
  model/ORM values remain Python integers. This is an approved breaking SDL and
  client-variable change; ordinary `Int`, generated `ID`, and explicit scalar
  overrides are unchanged. Relation IDs to BigInteger primary keys still accept
  string or integer values through `ID` input; numeric-choice fields keep their
  generated Enum input.

- Make the converter integration test register its User relation target in a
  test-local, allowlisted registry. The test now passes in isolation without
  weakening its relation assertion or changing production relation behavior.
- Previously restored populated auto-derived `DecimalField` output under
  graphql-core 3.3 through the existing `Float` field; the new default above
  supersedes that interim Float output without changing Decimal input parsing.
- Bound optimizer planning for valid repeated-fragment graphs to distinct
  model, type, and relation-path contexts. Existing projections, prefetches,
  annotation promotion, ordered plan/alias precedence, GraphQL results, and SQL
  query counts remain unchanged.
- Reject cyclic named-fragment graphs before cost/depth expansion. Direct
  `analyze_cost()` now raises `GraphQLError` for a cyclic document rather than
  returning a truncated cost, including cycles outside the selected operation;
  validate first or catch the error. Acyclic costs and depth verdicts are unchanged.
- Validate only the eight named canonical benchmark results and copy only those
  files into provenance-test fixtures. Ignored local diagnostic JSON no longer
  causes unrelated validation failures; missing or invalid canonical results
  still fail, with no timing or published-artifact changes.
- Make the non-paginator resolver fixture own its partial on the field instance,
  preserving bound-method identity and observing the paginator type-guard path
  across Python versions without changing production pagination behavior.
- Close SQLite connections deterministically in named comparison preflight and
  seed-identity readers, including errors. Disposable benchmark-test writers
  commit or roll back before close; historical results and timings are unchanged.

### Behavior changes

- Nested child payloads that carry an `id` no longer create a child when the
  `id` does not resolve to a visible child. A hidden `id` (outside the child's
  host or output scope) answered `<Model> with id N does not exist.` while a
  nonexistent `id` silently created a new child, so a client could probe which
  ids exist. Both now return the same error and write nothing, for reverse
  `ForeignKey`, reverse `OneToOneField` and many-to-many nested payloads
  (including models with a natural primary key). Payloads without an `id` still
  create, and children the parent already owns still update. Clients that
  relied on sending an unknown `id` together with child data to create a row
  must omit the `id`.

- Generated `update` and `delete` (`DjangoModelMutation` and `DjangoModelType`)
  now also require the target row to be visible in the model's registered
  output type: when that `DjangoObjectType` overrides `get_queryset`, a row it
  hides on reads can no longer be edited or deleted by id (`postUpdate` and
  `postDelete` returned `ok: true` for a hidden row). The host scope and the
  output scope are intersected in one query, a hidden row answers exactly like
  a nonexistent id. Nested child payloads that write fields of an existing
  child (reverse FK, reverse OneToOne, M2M, or a forward relation carrying the
  current target's id plus data) follow the same rule with the child's output
  type; an id-only re-send of a forward current target is not re-scoped.
  Types keeping the default hook add no query. Code that relied on writing rows its
  public type hides must widen that type's `get_queryset` (or register a
  broader type) for the schema that serves the write.

## 4.0.0 — 2026-10-05

Release validation now checks the exact pure-branch coverage percentage in
addition to combined and changed-line coverage. The documentation build checks
generated local links and provides the 404 page's theme skip-link target.

CI installs pinned `codecov-cli` 11.3.1 from official PyPI over verified HTTPS,
keeping the existing action, authentication and coverage gates. This replaces
the standalone-binary GPG/checksum verification with PyPI distribution trust;
`fail_ci_if_error: true` makes installation or upload errors fail the job.
Actual upload and both exact-commit Codecov checks remain required for release.

**django-graphex 4.0.0 requires `graphql-core>=3.3.0,<3.4`.** The package
and both editable project locks use this version and dependency range.
Custom 3.2 `ExecutionContext` subclasses must move to the 3.3 `Executor` API; the
legacy view keyword remains an alias with explicit-argument precedence.
Custom AST builders must construct immutable AST nodes, and subscription
transports must handle the 3.3 source stream results. Synchronous queryset
execution, directive coercion and query cost behavior retain compatibility
tests. The current official core33 SQLite comparison is in the immutable
`core33-4.0.0-bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e` series,
measured from 4.0.0 source `bf6e1ed6ccb6d3940d253c9c83b19a436f01aa4e` and installed later at
`826d5bae87ed7bbe705cf309d46a16d3ad3cdf33`. Its GraphEx/Ariadne create-comment p50 ratios are
0.57× and 0.51× for 50,000 and 100,000 comments, respectively; the
GraphEx direct-write check retains four SQL statements versus Ariadne's one.
These are three-run per-statistic medians of pinned SQLite whole stacks under
accepted background load, not paired cross-session speedups, PostgreSQL
timings or a published wheel. The earlier 4.0.0 pre-fragment, 3.1.1-source
core33 and 3.1.0 artifacts remain historical. See the
[current comparison](docs/why.md#current-core33-comparison). The dated 3.1.1 security patch and its
GraphQL-core 3.2.13 requirement remain historical facts.

SQLite generic mutations now validate only their directly saved FK rows
(including concrete inheritance parents) and updated M2M links, including
both rows of a symmetric self-relation accessed through a proxy or concrete
child, after the write, inside the rollback savepoint. This avoids
the table-wide deferred-FK scan that grew with unrelated rows, while retaining
immediate structured errors for the mutation's own invalid relations. Earlier
unrelated deferred violations remain the outer transaction's responsibility
and still prevent commit if unresolved. PostgreSQL's existing check is unchanged.
The earlier core33 results predate this change; the new 4.0.0-source series
records the scoped SQLite check without rewriting that history.

Related `AnnotatedField` selections inside applicable named or inline GraphQL
fragments now receive the same optimizer promotion as direct selections;
fragment type conditions and bound directives remain respected. Previously,
valid fragment-only related annotations could return `null` without a GraphQL
error. The current comparison above includes this correction; the earlier 4.0.0
pre-fragment series retains its original source attribution.

## 3.1.1 — 2026-10-01

This patch raises the required GraphQL-core version to 3.2.13 while staying
below 3.3. It includes upstream parser and validation denial-of-service fixes
and correct handling of truncated string escapes.
Production publication is tag-driven.

See the [full patch notes](docs/changelog.md#311--2026-10-01) and the
[security guidance](docs/usage/security.md#runtime-parser-and-validation-hardening).
The dated 3.1.0 history and its audit traceability remain in the full changelog.
