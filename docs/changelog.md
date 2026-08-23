# Changelog

All notable changes to this library are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

!!! info "A fresh start"

    **`django-graphex`** is a new, rewritten library — the successor to
    `graphene-django-extras`. Its history starts at **1.0.0** below. If you are
    coming from `graphene-django-extras` 1.x, the [Migration Guide](migration.md)
    explains every change with before/after examples (install `django-graphex`,
    import `django_graphex`).

## Unreleased

**Correctness pass over the 2.1.0 audit backlog.** Twelve confirmed defects from
the post-release audit, each reproduced before the fix and covered by a
regression test. No API changes.

### Fixed

- **The optimizer returned wrong rows for aliased nested lists.** Selecting the
  same relation twice under different filters made *both* aliases return the
  unfiltered set, and adding a filtered or paginated alias next to a plain one
  silently corrupted the plain one. The dedup guard counted only selections that
  emitted a prefetch, so mismatched siblings were never detected. It now records
  a row-set signature for every nested-list selection, keeps one shared prefetch
  when the signatures agree, and drops the ambiguous lookup (and its
  descendants) from `prefetch_related` so each alias resolves its own rows.
- **A nested window under a windowed parent was paginated twice**, truncating
  the inner page and reporting the page size as `totalCount`. The re-rooted
  child prefetch now carries its `to_attr`, so the page is no longer sliced a
  second time in memory.
- **`optimize_<field>` crashed on a reverse FK declared without `related_name`.**
  The accessor (`<model>_set`) was looked up in a map keyed by the relation name,
  and the bare `except` substituted the owner model, producing a prefetch that
  failed at query time. Both walk sites now resolve through the accessor-indexed
  helper and leave an unresolvable segment untouched.
- **Filtering a list by a to-many primary-key set returned duplicate parent
  rows.** The `to_many` flag was only set on the nested-relation branch, so a
  direct pk lookup never triggered `.distinct()`.
- **Grouped `choices` with a repeated label produced a broken enum.** The
  duplicate-name guard was re-created on every recursive call, so two groups
  sharing a label collapsed into one member: the enum lost a value, rows holding
  the losing value became unserialisable, and writing that member stored the
  wrong value. Colliding names are now disambiguated deterministically; enums
  without a collision are unchanged.
- **Subscriptions were broken for any model whose primary key is not named
  `id`.** The broadcast payload hardcoded the key `"id"`, so every event failed
  the non-null check on the real pk field — in the default `id_only` mode.
- **Subscriptions delivered only errors to clients using GraphQL variables.**
  The per-event execution received neither `variable_values` nor
  `operation_name`, so subscribing succeeded and every delivered event failed.
  This affected every standard client (Apollo, urql, graphql-ws) and the bundled
  browser client.
- **Every read of a populated `DurationField` returned `null` plus a field
  error**, because `timedelta` cannot coerce to `Float`. The value is now
  resolved through `total_seconds()`, and the input side accepts it back.
- **The `id` returned by a query could not be sent back to an update
  mutation.** Output emitted `ID!` (a JSON string) while the update input
  declared the raw pk type, so echoing it back raised a coercion error — the
  sibling delete mutation already used `ID!`.
- **`ordering: "+field"` returned a 500 that enumerated every column of the
  model.** The allowlist stripped every leading `-`/`+` while the term handed to
  the ORM kept them. Prefixes are now normalised before validation, so the
  validated term is the one executed; a malformed `--field` is rejected with a
  clean error instead of leaking the field list.
- **With `CACHE_ACTIVE`, a malformed request body raised an unhandled exception
  instead of returning 400.** The pre-cache preamble parsed the body outside the
  handler that turns those errors into responses.
- **A multi-operation document with `operationName` silently discarded the
  mutation** and replayed a cached success payload without executing it. The
  operation name is now honoured when classifying the request, and an
  undeterminable operation bypasses the cache.

### Documentation

- The main tutorial (`Sample Application`), the first example on the Fields
  page, the file-upload guide and several Query Recipes did not compile or
  taught a pattern that crashes at runtime. Every snippet on the affected pages
  was executed against a real schema and corrected.

## 2.1.0 — 2026-08-23

**Security release — upgrade is strongly recommended.** This release closes five
defects confirmed in 2.0.0 by a line-by-line audit of the published code (see
**Security** below), and unifies the subscription filter argument with the query
one.

**The subscription filter argument is now a real typed input object.** Queries
took `filter` as a generated `<Model>FilterInput`; subscriptions took `filters`
as a plain `String` carrying JSON — two names, two shapes, and no schema
validation or autocompletion on the subscription side. That inconsistency is why
the documented subscription filter syntax was wrong for two releases. This
release unifies them.

### Changed (BREAKING)

- **`filters` → `filter`, typed `<Model>SubscriptionFilterInput`.** The
  subscription argument is renamed to the singular query term and takes a
  generated input object with the same nested `{field: {lookup: value}}` shape
  queries use. There is **no `filters` alias** — 2.0.0 shipped one day before
  2.1.0 and the documented syntax never worked, so the exposed surface is
  minimal.

    Before (2.0.x):

    ```graphql
    subscription {
      commentSubscription(action: ALL_ACTIONS, filters: "{\"post\": 7}") {
        id
        text
      }
    }
    ```

    After (2.1.0):

    ```graphql
    subscription {
      commentSubscription(action: ALL_ACTIONS, filter: { post: { exact: 7 } }) {
        id
        text
      }
    }
    ```

    Combining lookups works the same way:
    `filter: { post: { exact: 7 }, status: { in: ["open", "urgent"] } }`.

- **The schema is now the filter boundary.** The generated input type is
  deliberately **not** the query's `<Model>FilterInput` — reusing it would
  re-expose every lookup and reopen the extraction oracle closed in this release. It
  declares exactly the subscription's projected output fields (honouring
  `Meta.only_fields` / `Meta.exclude_fields`) and exactly the four allowed
  lookups (`exact`, `iexact`, `in`, `isnull`). It is flat, so relation traversal
  is unexpressible. A banned lookup, an excluded column or a relation path is now
  a **GraphQL validation error** instead of a runtime rejection. The runtime
  check remains as defence in depth for anything reaching the engine without
  schema coercion.

  Both input types coexist in one schema; the query-side
  `<Model>FilterInput` SDL is unchanged.

### Security

*The five items below were prepared as 2.0.1; that patch was never published —
they ship here in 2.1.0.*

- **Relation traversal bypassed permission scoping.** Only generated root fields
  carried the permission label the pruner reads, so a user could read a model
  they had no `view_<model>` permission for by traversing a relation from a
  parent they *could* read (`post { comments { ... } }`). Untagged fields now
  fall back to the implicit label of their output type, and the schema label set
  is widened accordingly, so `PERMISSION_SCOPED_SCHEMA` removes those relation
  fields. See [Permission-Scoped Access](usage/permission-scoped-schema.md).
- **Subscription client filters were an extraction oracle.** The filter
  whitelist was built from the unprojected model, and only the segment before
  the first `__` was validated — so a subscriber could probe any column
  (including `password`) one comparison at a time via lookups such as
  `startswith`, and could traverse into related models. `Meta.only_fields` /
  `Meta.exclude_fields` are now honoured by the subscription backend, relation
  traversal is rejected, and client filters accept only `exact`, `iexact`, `in`
  and `isnull`. Ordered and pattern lookups (`startswith`, `icontains`, `gt`,
  `regex`, `range`, date parts) are refused — move that logic to
  `subscription_scope`. See [Subscriptions](usage/subscriptions.md).
- **`private_subscription` was not enforced on either transport.**
  `DJANGO_GRAPHEX['MIDDLEWARE']` was read only by `GraphQLView`, while
  subscriptions are served exclusively by the SSE view and the WebSocket
  consumer — so `AuthenticatedFieldsMiddleware` never ran and an anonymous
  subscriber received protected events. Both transports now build and apply the
  configured middleware chain for the subscribe and delivery paths.
- **Sub-kilobyte documents could pin a worker (DoS).** The bundled depth and
  cost validation rules re-walked each fragment once per reachable path, so a
  ~1 KB document with fan-out fragments took over ten seconds of CPU — before
  authentication, on any stock `GraphQLView`. Both rules now memoize each
  fragment's contribution; reported depth and cost values are unchanged.

### Fixed

- **`<Model>FilterInput` name collision refused to build the schema.** Filtering
  a relation by a column the related type does not itself declare (for example
  `filter_fields = {"author__email": ("exact",)}`) produced two input types with
  the same name and a hard `TypeError` at schema construction — the application
  did not start. One canonical instance per model is now cached and widened in
  place, converging regardless of build order.
- **Documented `filters` syntax could never work.** Every snippet showed
  `filters: { post: 7 }`, but the argument is a `String` carrying JSON, so the
  object literal failed input coercion. Docs and the playground now show the
  JSON-encoded form.

## 2.0.0 — 2026-06-17

**graphene removed — `django-graphex` now runs on native graphql-core + Pydantic
alone.** The legacy graphene backend is deleted; graphene is no longer a
dependency and is never imported, even on a full build with mutations,
subscriptions and pagination. See the [Upgrade Guide](UPGRADE-2.0.md) for
before/after snippets and a migration codemod (`scripts/migrate_2_0.py`).

### Changed (BREAKING)

- **graphene backend removed entirely.** The `GDX_BACKEND` environment variable
  that selected the legacy graphene path is gone; the native graphql-core path is
  the only path. graphene (and graphene-django) are no longer required and can be
  uninstalled.
- **`GRAPHENE` settings namespace → `DJANGO_GRAPHEX` (single namespace).**
  Schema/middleware settings (`SCHEMA`, `MIDDLEWARE`, `SUBSCRIPTION_PATH`, …) are
  merged into the single `DJANGO_GRAPHEX` Django-setting dict alongside this
  package's own settings (pagination, caching, query limits, …); there is no
  longer a separate schema-settings namespace, and the legacy `GRAPHENE`
  namespace is no longer consulted. The codemod `--apply` folds an existing
  `GRAPHENE` dict into `DJANGO_GRAPHEX` (no key collisions).
- **`graphene.ObjectType` schema roots → native `ObjectType`.** Import the root
  base from `django_graphex.core` (`from django_graphex.core import ObjectType`).
- **`graphene.Schema(...)` → `DjangoGraphQLSchema(...)`.** Build the schema with
  the public `django_graphex.schema.DjangoGraphQLSchema` class.
- **graphene field descriptors → native `field(...)`.** Hand-declared (non-model)
  fields use `field(GraphQLString)` / `field(GraphQLList(...))` with graphql-core
  types instead of `graphene.String()` / `graphene.Field(...)`.
- **`graphene.Argument(...)` in a Mutation `class Arguments` → `GraphQLArgument(...)`.**
  Mutation arguments are declared with native graphql-core `GraphQLArgument` (a
  bare graphql-core type is auto-wrapped) inside the `class Arguments` inner class.
  This is a **clean break**: a non-native value left in `class Arguments` now
  raises `TypeError` instead of being silently dropped.
- **`choices` fields now render as a GraphQL enum on both output and input.** A
  model field with `choices` is exposed as a real `GraphQLEnumType` on the output
  type and on filter/input types (previously a choices field could render as a
  plain `String` on the native path). This is an observable wire-format change —
  review clients that send/read choices values as raw strings.
- **Update mutations now honour an explicit `null` (GraphQL-spec-correct:
  omitted ≠ null).** Previously `update()` stripped every `None` from the input
  and treated `null` as "not provided", so a nullable field or an M2M could not
  be cleared over the wire. Now an **omitted** field is left unchanged (partial
  update), while an **explicit `null`** sets a nullable scalar/FK column to
  `NULL` and clears a top-level (`ID`-list) M2M — `tags: null` is equivalent to
  `tags: []`. A `null` on a **required** field returns a clean validation
  `errors[]` payload (`ok: false`), never a 500. **Nested** inputs
  (`Meta.nested_fields`) still treat `null` / `[]` / `{}` as a **no-op** (related
  children are never deleted). This is an observable behavior change — review
  clients that relied on `null` being silently ignored on update. Both mutation
  surfaces (`DjangoModelMutation` and `DjangoModelType`) behave identically. See
  [Mutations → Explicit-null semantics](usage/mutations.md#explicit-null-semantics-in-update-mutations).
- **Public-API renames.** Five names were renamed for clarity and consistency
  (no deprecated aliases — update call sites directly):
    - **`Meta.max_deep` → `Meta.max_depth`** on `DjangoObjectType`,
      `DjangoListObjectType`, and `DjangoModelType` (aligns with the
      `MAX_QUERY_DEPTH` setting). The unknown-option guard names the new spelling.
    - **`@filter_field(graphene_type=…)` → `@filter_field(graphql_type=…)`**
      (graphene is gone; the argument type must be a graphql-core `GraphQLType`).
    - **`DjangoUnionType` `Meta.gfk_types` → `Meta.types`**. Declaring the old
      `gfk_types` now raises `ImproperlyConfigured` with a rename hint.
    - **GFK-owner `Meta.gfk_unions` → `Meta.unions`** (the key that maps a
      `GenericForeignKey` to a typed union on a `DjangoObjectType`). Declaring the
      old `gfk_unions` now raises `ImproperlyConfigured` with a rename hint
      (`gfk_unions was renamed to unions in v2.0`).
    - **Mutation argument container `class args` → `class Arguments`** on the
      native hand-written `Mutation` base (unifies with `DjangoModelMutation` /
      `DjangoModelType`, which already used `Arguments`). A subclass that still
      declares the legacy inner `class args` (and no `Arguments`) raises
      `TypeError` with a rename hint at `Field()` build time.
    - **Subscription `Meta.serialize_data` → `Meta.payload_mode`** and the
      **`SUBSCRIPTION_SERIALIZE_DATA` setting → `SUBSCRIPTION_PAYLOAD_MODE`**. The
      boolean flag becomes a string mode: `serialize_data=True` → `payload_mode=
      "full"`, `serialize_data=False` → `payload_mode="id_only"` (the new global
      default), `None` still inherits the setting. Semantics are unchanged (id-only
      broadcasts `{"id": <pk>}`; full broadcasts a flat serialization). Declaring
      the old `Meta.serialize_data` key or the old `SUBSCRIPTION_SERIALIZE_DATA`
      setting key raises `ImproperlyConfigured` with a rename hint, and an invalid
      `payload_mode` value names both valid values.
- **`InputField` and the 12 `*InputField` twins removed — one unified `Field`.**
  The `Field` / `InputField` split is gone: the single `Field` descriptor (and 11
  typed shortcuts — `IntField`, `CharField`, `FloatField`, `BooleanField`,
  `IDField`, `DateField`, `DateTimeField`, `TimeField`, `DecimalField`,
  `UUIDField`, `JSONField`) now works in **both** an output body **and** a
  `class Arguments` body. `InputField` and every `*InputField` twin
  (`IntInputField`, `CharInputField`, …) are **removed** with no alias — port with
  a search-and-replace that drops the `Input` infix (`InputField` → `Field`,
  `IntInputField` → `IntField`, …). `resolver=` / `source=` / `args=` are
  output-only (a `TypeError` in an argument position) and `default=` is input-only
  (a `TypeError` at output compile). The raw `GraphQLArgument` idiom is unaffected.
  See [Upgrade Guide → §8](UPGRADE-2.0.md#8-inputfield-inputfield-twins-removed-one-unified-field).
- **`JSONField` now carries raw JSON on the wire (SDL scalar `JSON`).** A model
  `models.JSONField` and the `JSONField()` descriptor are transported as **raw,
  structured JSON** (SDL scalar `JSON`) across all three paths — output, mutation
  input, and filters — instead of the JSON-encoded string wire (SDL scalar
  `JSONString`) used before. Objects, lists, and scalars pass through
  structurally, and inline object / list literals are accepted directly in a
  query. **Clients that `JSON.parse()`d the old `JSONString` wire (or
  `JSON.stringify()`d it on input) must stop.** The escape hatch
  `JSONField(as_str=True)` keeps the old `JSONString` (string-encoded) wire for a
  single descriptor field. `GenericJSONField` and the `GenericScalar` SDL scalar
  name are **removed** (the raw scalar is exported as `GdxJSON`, SDL name `JSON`;
  the legacy graphene `GenericScalar` class still resolves to it for backward
  compatibility, and `GdxJSONString` stays). This is an observable SDL change.
  See [Upgrade Guide → §9](UPGRADE-2.0.md#9-jsonfield-now-carries-raw-json-on-the-wire-sdl-scalar-json).
- **Cursor pagination cursor format is now composite (`value` + `pk`).**
  `CursorGraphqlPagination` encodes the boundary row's ordering value **plus** its
  primary key as a deterministic tiebreak, so tied ordering values page correctly
  (rows are never dropped or duplicated across a boundary). Any **stored** v1 /
  beta cursor string is no longer valid and raises a clean
  `GraphQLError("Invalid cursor")` — re-fetch from the first page after upgrading.
  The `first` argument is unchanged.
  See [Upgrade Guide → §11](UPGRADE-2.0.md#11-cursor-pagination-cursor-format-changed-composite-keyset).
- **Output camelCase digit parity — `phone_1` → `phone1` (bugfix, wire-visible).**
  A field name with a trailing digit component was camelCased incorrectly on the
  **output** side (`phone_1` stayed `phone_1`), diverging from the **input** side
  (Pydantic), which already produced `phone1`. Output now routes through the same
  canonical camelCase, so `phone_1` → `phone1`, `address_2` → `address2`,
  `iso_8601_date` → `iso8601Date` — restoring output/input wire parity (and v1
  graphene parity). Fields without a digit component (`created_at` → `createdAt`)
  are unchanged. Review clients that selected the old `phone_1`-style output name.
  See [Upgrade Guide → §12](UPGRADE-2.0.md#12-output-camelcase-digit-parity-phone_1-phone1).
- **Filter input SDL name `<Model>Filterinput` → `<Model>FilterInput` (bugfix,
  wire-visible).** The generated filter input type name is now capitalized
  idiomatically (`UserFilterInput`, not `UserFilterinput`). Inline
  `filter: { ... }` usage is unaffected; update any named-variable reference
  (`$filter: UserFilterInput`) or SDL snapshot / codegen artifact that pinned the
  old spelling.
  See [Upgrade Guide → §13](UPGRADE-2.0.md#13-filter-input-sdl-name-modelfilterinput-modelfilterinput).

### Removed

- The graphene backend producer code, the `GDX_BACKEND` / dual-backend switch, and
  the graphene dependency from `pyproject.toml`.

### Added

- **Django-style field descriptor API** (`django_graphex.core`), **unified across
  positions**. One capitalized, Django-model-field-style `Field` descriptor
  declares custom (non-model) fields in **both** an `ObjectType` / `Mutation`
  payload body **and** a `class Arguments` body — direction is inferred from the
  declaration site, not the descriptor. It is sugar over the `field()` /
  `GraphQLArgument` substrate (every descriptor compiles byte-identical, no
  wire/SDL change). `Field(type, *, source=None, required=False, default=_UNSET,
  description=None, name=None, resolver=None, args=None, deprecation_reason=None)`:
  `source=` / `resolver=` / `args=` are **output-only** (a clear `TypeError` if left
  on an argument-position field) and `default=` is **input-only** (a `TypeError` at
  output compile). Ships **11 typed scalar shortcuts** usable in both positions —
  `IntField`, `CharField`, `FloatField`, `BooleanField`, `IDField`, `DateField`,
  `DateTimeField`, `TimeField`, `DecimalField`, `UUIDField`, `JSONField` — plus a
  **collision guard** that raises a loud `TypeError` naming the likely import
  mistake if a `django.db.models.Field` is used where a descriptor is expected. The
  low-level `field()` helper and the raw `GraphQLArgument` / lambda-thunk idiom stay
  public and unchanged. See
  [Declaring fields: the descriptor API](usage/types.md#declaring-fields-the-descriptor-api).
- **Ordering values accept camelCase (GraphQL-consistency).** Because every field
  *name* is exposed in camelCase on the wire, the `ordering` **value** now accepts
  camelCase too: each term is normalized to its snake_case attname (preserving the
  `-`/`+` direction prefix) at one canonical point, so `ordering: "createdAt"`
  behaves **exactly** like `ordering: "created_at"` — on the DB path, the
  in-memory (prefetch-cache) path, **and** the nested window-prefetch optimization
  (which no longer declines for a camelCase term). snake_case keeps working
  unchanged; an invalid camelCase field still raises the same
  `Invalid ordering field` `GraphQLError`, and relation-spanning terms are still
  rejected. `CursorGraphqlPagination` (server-configured ordering) is unaffected.
  This also fixes a latent bug where a camelCase ordering term **silently degraded**
  on the in-memory path (it sorted by a missing attribute — a no-op) instead of
  matching the DB path.
- **Permission-scoped schema** (`PERMISSION_SCOPED_SCHEMA` setting, default
  `False` — fully inert until enabled). `AuthenticatedGraphQLView` can serve each
  authenticated request a schema **pruned to the caller's permissions**: a field
  whose required perms the caller lacks is *absent* from validation, so selecting
  it reads as a native `Cannot query field` (a not-found, never an authorization
  error — no existence leak). Both validation and execution run against the
  pruned schema; a caller whose entire `Query` root is pruned away gets the
  endpoint's generic `403`; an active superuser always gets the full schema; the
  public `GraphQLView` is never pruned. Includes:
    - **`field(required_perms=…)`** and a **`Mutation.required_perms`** class
      attribute to label fields explicitly, on top of the automatic labels
      stamped on every generated CRUD field (`extensions["gdx_required_perms"]`);
      an unlabeled field is treated as public.
    - a **revised composite `DjangoModelPermissions.perms_map`** — because a
      write payload returns instance data, `create`/`update`/`delete` now require
      the write verb **and** `view` (read actions stay `view`-only; override
      `perms_map` to restore write-only behavior).
    - **per-action subscription authorization** — `authorize_subscription` now
      forwards the requested `action`, so subscribe permissions are enforced per
      CRUD action (defense in depth: the action's enum value is pruned at
      validation *and* denied at runtime).
    - a **per-connection `schema_provider`** on the WS/SSE subscription
      transports, so subscriptions prune to the same schema as HTTP for a user.
    - **cache-key hardening** — pruned schemas are memoized in a bounded
      in-process LRU keyed by the caller's *permission signature*
      (`perms ∩ schema label-set`, never by user id, revoke-safe;
      `PERMISSION_SCHEMA_CACHE_MAXSIZE`, benchmark-calibrated default `64`), and
      the HTTP response cache folds the signature into its key so a low-permission
      caller can never read a high-permission caller's cached response body.

  Requires a labeled `DjangoGraphQLSchema`; with the flag `False` behavior is
  byte-identical to today. See
  [Views → Permission-scoped schema](usage/views.md#permission-scoped-schema-permission_scoped_schema),
  [Security → Permission-scoped schema](usage/security.md#permission-scoped-schema-permission_scoped_schema),
  and [Settings → Security](usage/settings.md#security).
- **`API_ACCESS_GROUP` setting** (`DJANGO_GRAPHEX`). Restricts the authenticated
  endpoint (`AuthenticatedGraphQLView`) to members of a single Django auth
  `Group` (by name). `""` (default) disables the gate — zero impact. When set,
  non-members are rejected with a generic **HTTP 403** before any GraphQL
  parsing/execution (the message never leaks the group requirement), an **active
  superuser always bypasses** the gate (hardcoded invariant), and a
  missing/anonymous user is denied (fail-closed, independent of
  `permission_classes`). The public `GraphQLView` is **not** affected. See
  [Views → Endpoint-level auth](usage/views.md#restricting-the-endpoint-to-a-group-api_access_group)
  and [Settings → Security](usage/settings.md#security).
- **`DjangoModelPermissions` permission class** (`django_graphex.permissions`).
  A DRF-style permission that maps each CRUD action to Django's built-in model
  permissions (`add`/`change`/`delete`/`view`) and checks them with
  `user.has_perms`. Fail-closed (anonymous users, a missing model, and unknown
  actions are denied), superusers pass automatically, and the per-action
  codenames are customizable via the `perms_map` class attribute or by
  overriding `get_required_permissions`. Intended for
  `DjangoModelType.permission_classes`. See
  [Permissions → `DjangoModelPermissions`](usage/permissions.md#djangomodelpermissions).
- **`graphql_schema` management command** (introspection JSON / SDL export).
  Mirrors graphene-django's command of the same name (a drop-in for migrating
  users) but is built on graphql-core with no graphene import. Writes
  introspection JSON wrapped as `{"data": ...}` (matching graphene-django's
  shape) to `DJANGO_GRAPHEX["SCHEMA_OUTPUT"]` (default `schema.json`), or SDL
  when the output path ends in `.graphql` / `.gql`. Supports `--out`/`-o`
  (incl. `-` for stdout), `--indent`/`-i`, and `--schema <dotted.path>`. New
  settings `SCHEMA_OUTPUT` and `SCHEMA_INDENT` back the command's defaults. See
  [Settings → Exporting the schema](usage/settings.md#exporting-the-schema).
- **`deprecation_reason=` across the descriptor API and every Django field/mutation
  builder.** `field()`, `Field`, and all 11 typed shortcuts accept a
  `deprecation_reason=`, and so do every Django mounting builder —
  `DjangoObjectField`, `DjangoListObjectField`, `DjangoFilterListField`,
  `DjangoFilterPaginateListField`, `RetrieveField`, `QueryFields`, and the mutation
  builders (`CreateField` / `DeleteField` / `UpdateField` / `MutationFields`). When
  set, the reason is wired into the compiled field / argument so the SDL renders
  `@deprecated(reason: "…")`.
- **Pydantic `InputType` `list[...]` fields render as GraphQL lists with defaults.**
  A `list[...]`-annotated field on an `InputType` now compiles to a GraphQL list
  input (`[T]`), and a Python field default is carried into the SDL as the
  argument's default value.

### Performance

Five behavior-preserving optimizations (response shape is unchanged in all
five; SQL query counts and per-request timings improve). A reproducible
cross-library benchmark harness lives at `benchmarks/` if you want to measure
these against your own workload.

- **`totalCount` is computed lazily.** The `COUNT` query is only issued when
  the client actually selects `totalCount`, and reuses an already-materialized
  results list (`len()`) instead of a fresh query when one is available.
  Skips one `COUNT` query per request for any list operation that doesn't
  select `totalCount`.
- **Parse + validate document cache** (`DOCUMENT_CACHE_MAXSIZE` setting,
  default `128`). graphql-core's `parse()` and `validate()` are memoized in two
  bounded LRUs — a global parse cache keyed on the query string (the AST is
  immutable and schema-independent) and a per-schema validation cache keyed by
  the schema **object** (a `WeakKeyDictionary`, so a permission-pruned schema
  never shares a verdict with another schema). Shaves the re-parse/re-validate
  cost (each on the order of a fraction of a millisecond) on every repeated
  document. See
  [Settings → Document cache](usage/settings.md#document-cache-parse-validate).
- **Cached Pydantic validator build.** `build_model_schema` (the dynamically
  generated Pydantic model backing create/update validation) is now memoized
  per `(model, partial, base, exclude)` instead of rebuilt on every mutation
  call — the derived class is a pure function of that key, so rebuilding it per
  request was wasted work.
- **FK existence check moves to the mutation failure path.** A valid
  create/update mutation issues a single `INSERT`/`UPDATE` — the per-FK
  existence pre-check no longer runs on the happy path. A bad FK still returns
  the same structured `errors[]` envelope; the diagnostics that produce it now
  run only after an `IntegrityError`. Saves one `SELECT` per FK field on every
  successful mutation.
- **Nested-write savepoint opens only when nested work is present.** A
  create/update mutation with `Meta.nested_fields` no longer opens a
  `transaction.atomic()` savepoint when the request has no nested child
  payload — a plain, parent-only mutation pays no savepoint overhead.

See [Mutations → performance note](usage/mutations.md#error-handling) and
[Pagination → `totalCount` is computed lazily](usage/pagination.md#query-examples)
for the user-facing behavior these changes preserve.

### Fixed

- **Subscription transports' `schema_provider` now respects
  `PERMISSION_SCOPED_SCHEMA`.** Once a `schema_provider` was wired on
  `subscription_ws_consumer` / `subscription_sse_view`, the bundled
  `pruned_schema_for` helper pruned **unconditionally** — the provider path never
  read `PERMISSION_SCOPED_SCHEMA` even though the HTTP `AuthenticatedGraphQLView`
  is gated by it, so the transports diverged from HTTP. The bundled helper now
  reads the flag **per connection** (never at import): it returns the **full**
  schema when the flag is off (default) and the **pruned** schema when on, so one
  flag rules the feature across HTTP, SSE, and WebSocket. The active-superuser
  invariant is unchanged (always the full schema), and a **custom** provider
  callable that does not route through `pruned_schema_for` is honored as-is (the
  flag gates the bundled helper only).
- **Model-derived `JSONField` mutation inputs now store a real Python object.** A
  model-derived `JSONField` (and `HStoreField`) was rendered as a plain `String`
  on the mutation **input** type, so the submitted JSON text was assigned to the
  column verbatim — a double-encoded string instead of the parsed value. Model
  `JSONField` / `HStoreField` inputs now render as the raw `JSON` scalar (see the
  JSON-flip breaking change above) and store a dict **or** a list as a real Python
  object on both create and update — output, input, and filter paths all agree on
  the `JSON` scalar. The custom scalars are exported for reuse:
  `from django_graphex.core import GdxJSON` (also `GdxJSONString`, `GdxDate`,
  `GdxDateTime`, `GdxTime`, `GdxDecimal`, `GdxUUID`).
- **Pagination `limit` / `first` guards — zero and negative now raise a clean
  `GraphQLError`.** A `limit: 0` / `first: 0` or a negative `limit` / `first`
  previously slipped through (or produced a negative-offset slice); both now raise
  a structured `GraphQLError` (e.g. `Invalid limit: -5. Limit must be a positive
  integer.`) instead of an HTTP 500 or an empty page. Negative `offset` already
  raised.
- **`PageGraphqlPagination` supports backward (negative-page) access.** `page: -1`
  returns the **last** `page_size` rows in true `list[-N:]` order, `page: -2` the
  window before it, and an overshoot clamps to the first rows. A negative page
  costs one `COUNT` (needed to compute the count-relative offset) and opts out of
  the nested window-prefetch optimization; `page: 0` still raises a `GraphQLError`.
- **`prune_schema` forwards interface implementers (`PERMISSION_SCOPED_SCHEMA`
  polymorphic fix).** A surviving object type that implemented a surviving
  interface but was only ever returned *via* the interface used to fall out of the
  pruned schema's `type_map`, leaving `possible_types` empty and breaking
  inline-fragment queries. The pruner now forwards those implementers, so an
  interface keeps its implementers in the pruned schema exactly as in the full one.
- **SSE subscription transport hardening.** The bundled SSE view is now
  `csrf_exempt` (the event-stream endpoint no longer trips CSRF), and the SSE
  client's request path building and value escaping were corrected.
- **GenericForeignKey custom-PK resolution uses `root.pk`.** A GFK whose owner has
  a non-default primary key name is now resolved via `root.pk` (rather than a
  hard-coded `id`), so custom-PK owners resolve their GFK target correctly.
- **Inline JSON literals are accepted on `JSON` arguments.** The `JSON` scalar's
  literal parser recurses `ObjectValueNode` / `ListValueNode` (and resolves nested
  `VariableNode` references), so an inline object / list literal
  (`payload: { a: 1, tags: [1, 2] }`) is parsed into a real Python `dict` / `list`
  instead of being rejected.

## 1.3.0 — 2026-06-13

### Added

- **`@filter_field` decorator** (#26) — declare custom per-field GraphQL filter
  arguments directly on a `DjangoObjectType` or `DjangoModelType`, co-located
  with the resolver logic. The method name becomes the GraphQL argument name;
  the graphene type (default `graphene.String`) and an optional description are
  configurable. `filter_fields` continues to work for model-field lookups; custom
  logic is now exclusively via `@filter_field`. Composition order at query time:
  `get_queryset`/`filter_queryset` scoping first, then standard lookups, then
  `@filter_field` methods (declaration order). (#26)
  <small>*Erratum: this entry originally described `filter_queryset` as running
  last — the scoping hook has always run first. See
  [Filtering → Composition order](usage/filtering.md#composition-order).*</small>

- **`Base64FileInput` — opt-in base64 file uploads** (#25) —
  `Base64FileInput(graphene.InputObjectType)` with `filename` (required),
  `data` (required, base64-encoded), and `content_type` (optional, default
  `application/octet-stream`). Call `.to_uploaded_file(max_size=None)` in any
  mutation resolver to obtain a Django `SimpleUploadedFile` ready for
  `FileField.save()`. Also importable as `decode_base64_file(value, *,
  max_size=None)` for cases where you hold the raw dict.

  Two new settings enforce memory safety:

  - **`MAX_UPLOAD_SIZE`** (int bytes, required when `Base64FileInput` is used)
    — global decoded-size cap. A pre-check fires before base64 decoding to
    avoid the allocation. Per-field `max_size` overrides this. Raises
    `ImproperlyConfigured` if absent and no per-field override is given.
  - **`MAX_REQUEST_BODY_SIZE`** (int bytes, `None` = disabled) — HTTP body-size
    guard in `BaseGraphQLView.dispatch`, checked before JSON parsing. Rejects
    oversized bodies with **HTTP 413**. This is the primary memory cap (the
    base64 string is already in RAM once the body is parsed).

  Malformed base64 raises `GraphQLError` (never HTTP 500). Content-type
  validation (magic bytes) is out of scope — use `FileField` validators.
  Batch requests: `MAX_BATCH_SIZE` (op count) + `MAX_REQUEST_BODY_SIZE`
  (bytes) compose; no special upload-batch logic. Upload mutations bypass the
  response cache automatically (mutations are never cached). See
  [Mutations → File Upload Support](usage/mutations.md#file-upload-support) and
  [Settings → File uploads](usage/settings.md#file-uploads). (#25)

### Changed

- **BREAKING — minimum Django raised to 5.2** (#75) — Django 4.2, 5.0, and 5.1
  are no longer supported (all end-of-life). The supported matrix is now
  **Django 5.2 (LTS) + 6.0** × **Python 3.12–3.14**. Tooling: `pytest-asyncio`
  pinned to `>=1.0`, `ruff` constraint updated, CI uses `setup-uv` v8.

- **`filter_fields = {"field": None}` now raises `ImproperlyConfigured`** (#26) —
  The `None` sentinel (which previously applied the default lookup set and crashed
  with `TypeError`) was un-Pythonic and has been replaced by the `@filter_field`
  decorator. The error message directs users to the new API.

### Fixed

- **Docs accuracy** (#71) — Five follow-up fixes: migration guide import corrected
  (`graphene_django_extras` → `django_graphex`); fragile changelog anchor removed
  from query-optimization guide; `Meta` validation options table added to types
  docs; `!!! warning` callout added to API types reference; `BaseGraphQLView`
  views docstring reworded to match the actual tuple-store/reconstruct caching
  mechanism.

- **TTL and CSRF-replay tests now have teeth** (#72) — The TTL test previously
  read `_cache[raw_key]` (LocMemCache stores expiry in `_expire_info`, not in the
  value tuple), making the assertion vacuous. Replaced with a `cache.get()`
  presence check plus `_expire_info` TTL assertion. The CSRF-replay test's
  `if`-gated `assertNotEqual` was replaced with an unconditional
  `assertNotIn('Set-Cookie', resp2)` plus a super-call count assertion that
  verifies the cache hit.

- **Test infrastructure hardened** (#73) — Multi-backend cache fixture covering
  both `LocMemCache` and `DatabaseCache`; concurrency test for parallel mutation
  invalidation; dead `reset_global_registry` call removed; fixture deduplication.

- **Playground updated** (#74) — `PostType.get_queryset` scoping example (anonymous
  → published only, authenticated → all); safe-ordering comment on `PostListType`;
  version signal markers updated; README banner added ("Targets django-graphex
  v1.3.x") with safe-ordering table.

### New settings

| Setting | Default | Description |
|---|---|---|
| `MAX_UPLOAD_SIZE` | `None` | Global decoded-size cap for `Base64FileInput` (bytes). Required when using uploads unless a per-field `max_size` is set. |
| `MAX_REQUEST_BODY_SIZE` | `None` | HTTP body-size guard (bytes). Requests exceeding this limit are rejected with HTTP 413 before JSON parsing. |

### Behavior changes

!!! warning "Review before upgrading"

    Review each item below before upgrading.

- **Django < 5.2 is no longer supported** — Upgrade Django to ≥ 5.2 before
  upgrading `django-graphex` to 1.3.0. Projects on Django 4.2, 5.0, or 5.1 must
  stay on `django-graphex` 1.2.x. (#75)

- **`filter_fields = {"field": None}` now raises `ImproperlyConfigured`** —
  Previously this crashed with `TypeError`; the error is now explicit and
  directive. Replace `None` entries with a `@filter_field`-decorated method on
  the same type. (#26)

- **Custom filters are now declared exclusively via `@filter_field`** — Passing
  callable values through `filter_fields` is no longer supported. Use the
  `@filter_field` decorator instead; it co-locates the filter logic with the
  declaration. (#26)

- **`Base64FileInput` requires `MAX_UPLOAD_SIZE` or a per-field `max_size`** —
  Using `Base64FileInput` without either a global `MAX_UPLOAD_SIZE` setting or a
  per-field `max_size` kwarg raises `ImproperlyConfigured` at resolution time.
  (#25)

## 1.2.3 — 2026-06-13

!!! note "Hotfix"

    Corrective release only — no behavior changes beyond restoring the two
    pre-1.2.2 behaviors described below.

### Fixed

- **Subscription delete broadcasts no longer send `pk=None`** — `_on_delete`
  now snapshots the pk (and the serialized payload in `serialize_data=True`
  mode) at signal time before deferring via `transaction.on_commit`, instead
  of capturing the live instance whose pk Django nulls before the callback
  runs. Fixes misrouted per-object delete notifications in the default
  id-only mode and a `ValueError` that escaped the user's transaction in
  `serialize_data=True` mode. Regression from 1.2.2 (#63). (#69)
- **Pagination `ordering` now accepts the idiomatic `pk` / `-pk` alias** —
  The 1.2.2 ordering allowlist (#59) rejected it, breaking any paginator
  configured with `ordering="pk"` on every request. Relation-spanning (`__`)
  ordering remains rejected. Regression from 1.2.2. (#70)

## 1.2.2 — 2026-06-13

### Security

- **`DjangoObjectType.get_queryset` now actually applied on object, list, paginated,
  and list-object fields** — The hook was documented but never invoked on those field
  types, making every override a silent no-op. It is now called for
  `DjangoObjectField`, `DjangoFilterListField`, `DjangoFilterPaginateListField`, and
  `DjangoListObjectField` (results + totalCount). (#58)
- **Pagination `ordering` validated against exposed columns** — Client-supplied
  `ordering` values are now checked against the field's declared column list before
  they reach the ORM. An unknown field name can no longer trigger a `FieldError` that
  discloses the model's full field list, nor a relation-traversal `JOIN` that enables
  a DoS via index-missing foreign keys. (#59)
- **Response cache skips cookie-bearing and multipart requests** — The
  `CACHE_ACTIVE` cache no longer stores responses to requests that carry cookies or
  are `multipart/form-data`. Previously such responses could be replayed to unrelated
  clients (CSRF-cookie replay) or cause a 500 on multipart uploads. (#53)

### Fixed

- **Directives and pagination raise `GraphQLError` instead of HTTP 500 on bad client
  input** — `@base64`, `@currency`, `@floor`, `@ceil`, `@round`, `@abs`, `@center`,
  and negative-offset pagination now return a structured `GraphQLError` for invalid
  arguments rather than an unhandled exception that propagates as HTTP 500. (#50)
- **Nested-write integrity** — M2M writes with a bad primary key now return a
  structured error instead of crashing; the reverse-FK ownership guard prevents
  cross-owner row "stealing"; to-one fields that receive a list are rejected at
  input validation; `pk=0` upsert correctly routes to the update path; enum values
  inside a list input are properly unwrapped before persistence. (#62, #51)
- **Subscriptions run `authorize`/`scope` and registry I/O via `sync_to_async`** —
  Resolves `SynchronousOnlyOperation` errors that appeared when authenticated
  subscriptions called ORM-backed permission or scope logic from an async context.
  The `disconnect` handler is also now safe to call without a prior `connect`. (#61)
- **Subscription broadcasts fire on transaction commit** — Notifications are now
  deferred to `transaction.on_commit` rather than being sent at `save()` time. Rows
  inserted in a rolled-back transaction no longer emit phantom notifications to
  subscribers. (#63)
- **Enum registry keyed by model class** — The enum registry now uses the model
  class as the key, preventing collisions between apps that define a model with the
  same name. Self-referential `OneToOneField` relations are no longer silently
  dropped during schema construction. (#52)
- **`Meta`-option hygiene** — Unknown or mistyped `Meta` options (e.g.
  `filter_Filed` instead of `filter_fields`) now raise `ImproperlyConfigured`
  instead of being silently ignored. `include_fields` is honored on input and list
  types; an `id`-excluded `only_fields` no longer breaks the update mutation;
  `DjangoListObjectType.Meta.queryset` is now consumed as the base queryset. (#65)
- **Cache version counter uses `transaction.on_commit`** — The version-bump that
  invalidates a user's cache is now deferred to commit, closing the pre-commit stale
  window. Non-expiring version keys no longer resurrect after a cache flush; a cold
  key correctly heals to `1` rather than `0`. (#60)

### Performance

- **Empty window-sliced nested pages skip per-parent `COUNT`** — When a
  window-sliced nested list returns zero rows for a parent, no additional `COUNT`
  query is issued for that parent. (#64)
- **Request-scoped field-map cache threaded through filtered-prefetch descent and
  `.only()`-narrowing pass** — The per-request `_cache` dict is now correctly
  propagated through the filtered-prefetch and column-narrowing code paths,
  preventing redundant `_meta.get_fields()` calls on queries with nested filtering
  or `.only()` projections. (#57, #66)

### Packaging / Docs

- **`all_directives` static type matches runtime instances** — The type annotation
  was broadened to match the actual runtime list of directive instances returned by
  the function. (#66)
- **Install "verify" snippet works on a clean install** — `docs/installation.md`
  now uses `importlib.metadata.version('django-graphex')` (no `django.setup()`
  required) and carries an accurate Python × Django compatibility statement.
  Development Status classifier set to "5 - Production/Stable". (#67)
- **README and migration link fixes** — Migration guide URL corrected from
  `.../migration.html` to `.../migration/`; stale `#18` tracking links removed from
  `docs/usage/mutations.md`. mypy dev dependency pinned to `>=2.1,<3` to match CI;
  `daphne` upper bound `<5.0` restored in tox test environments;
  `filter_fields={"field": None}` no longer raises at schema build. (#55)

### Behavior changes

!!! warning "Review before upgrading"

    Review each item below before upgrading. Items marked **action required** need
    a one-time change in your project.

- **Subscription broadcasts now deliver on COMMIT, not at `save()` time** —
  Downstream tests that use `@pytest.mark.django_db` (non-transactional) will not
  observe broadcasts unless the test database wraps the write in a real transaction.
  **Action required for test authors**: switch to
  `@pytest.mark.django_db(transaction=True)` in any test that asserts on
  subscription notifications. (#63)
- **Response cache stores a `(body, status, content_type)` tuple, not a raw
  `HttpResponse`** — Deployments that introspect or inject into the response cache
  directly (e.g. custom cache backends that serialise the value) must account for
  the new tuple shape. Cookie-bearing and multipart requests are never cached. (#53)
- **Unknown `Meta` options now raise `ImproperlyConfigured`** — A previously
  silent typo (e.g. `filter_Filed`) will now surface at server startup rather than
  being ignored. This surfaces real bugs; review your `DjangoObjectType` and
  `DjangoListObjectType` subclasses for typos before upgrading. (#65)
- **`DjangoObjectType.get_queryset` is now actually invoked** — Any
  `get_queryset` override that was previously dormant (documented as active but
  never called on list/paginated/list-object fields) will now execute on every
  relevant query. **Action required**: review your `get_queryset` overrides to
  confirm they are safe to apply globally on those field types, then upgrade. (#58)
- **mypy dev dependency moved to `>=2.1,<3`** — Projects that pin mypy via the
  `django-graphex` dev extras should update their own mypy constraint accordingly.
  (#55)

## 1.2.1 — 2026-06-12

### Security

- **Response-cache cross-user isolation** (`CACHE_ACTIVE`) — Cache keys now
  incorporate a per-identity token (`u{pk}` for authenticated users,
  `t{header_hash}` for token-auth, `anon` for anonymous). User A's cached
  response is never served to User B. Mutation invalidation advances a
  per-user version counter instead of `cache.clear()`, so one user's cache
  miss never evicts another user's valid entries. A malformed query now returns
  HTTP 400 even when `CACHE_ACTIVE=True` (parse guard). (#27, closes #11)
- **Subscriptions hardening** — Channel ownership is validated before a
  subscriber joins any group (prevents channel hijacking). Client-supplied
  `filters` keys are now checked against declared output fields (rejects
  arbitrary ORM field probing such as `password__contains`). Broadcast signal
  handlers are ASGI-safe (no deadlock under a running event loop). Percent-encoded
  index group names prevent ambiguous separators in filter values. A new
  `SUBSCRIPTIONS_CHANNEL_GUARD` setting (default `True`) controls the ownership
  check; set to `False` only when every worker shares the `"default"` cache
  backend. The channel registry is backed by `caches["default"]` so multi-worker
  deployments with a shared cache work without configuration. (#30, closes #14)
- **`MAX_BATCH_SIZE`** (default `10`) — Batch requests with more entries than
  this limit receive HTTP 400 before any query executes, capping amplification
  attacks. `None` restores the previous unlimited behavior. (#31, closes #15)
- **GraphiQL SRI pinning** — CDN assets (react@18.3.1, react-dom@18.3.1,
  graphiql@3.7.1) are pinned with SHA-384 `integrity=` and
  `crossorigin="anonymous"` attributes. A CDN compromise or silent version bump
  can no longer inject JavaScript to GraphiQL users. (#31, closes #15)
- **`@number` format-spec cap** — Client-supplied specs with width or precision
  > 100 raise a `GraphQLError` instead of allocating gigabytes of output.
  Normal specs (`.2f`, `,.2f`, `+.1%`) are unaffected. (#32, closes #16)

### Fixed

- **UniqueConstraint validation** — `model._meta.constraints` is now iterated
  for unconditional `UniqueConstraint` entries; violations return a structured
  `ErrorType` response instead of propagating an unhandled `IntegrityError`
  HTTP 500. Deduplication prevents double messages when a field has both
  `unique=True` and a `UniqueConstraint`. Conditional and expression-based
  constraints are intentionally left to DB enforcement. MTI `parent_link`
  fields are excluded from FK constraint checks, mirroring the guard already
  present in the type converter. (#29, closes #13)
- **`@skip` / `@include` honored by cost, depth, and optimizer** — Fields
  marked `@skip(if: true)` or `@include(if: false)` are excluded from cost
  counting, depth counting, and queryset optimization (no more false-positive
  `QUERY_TOO_COMPLEX` / `QUERY_TOO_DEEP` errors; skipped subtrees are not
  over-fetched). When the directive argument is an unbound variable, the
  selection is treated as *included* (conservative fallback). (#28, closes #12)
- **Pagination** — `page=0` now raises an explicit `GraphQLError` in all
  Python execution modes (the previous `assert` was a no-op under
  `python -O`). Tampered or corrupted cursors raise a clean
  `GraphQLError("Invalid cursor")` instead of HTTP 500. The `COUNT` query in
  `PageGraphqlPagination` is now conditional — it runs only for last-page
  navigation, removing one DB round-trip from every forward-paginated request.
  (#33, closes #17)
- **`@date(format: "iso")`** — Now emits real ISO 8601 (`2023-12-01T14:30:00`)
  instead of the previous locale-dependent month abbreviation format
  (`2023-Dec-01T14:30:00`) that was unparseable by `datetime.fromisoformat`.
  (#32, closes #16)
- **`@date` time-ago DST awareness** — `_format_time_ago` now computes "now"
  using `timezone.get_current_timezone()` instead of the fixed, DST-unaware
  `time.timezone` offset. Daylight-saving transitions no longer produce
  off-by-one-hour relative timestamps. (#32, closes #16)
- **`@base64` UTF-8 support** — `.encode("ascii")` raised `UnicodeEncodeError`
  on non-ASCII input; replaced with `.encode("utf-8")` / `.decode("utf-8")`.
  (#32, closes #16)
- **Custom-pk `delete` returns the correct `id`** — `mutation.py` and
  `types.py` now resolve via `old_obj._meta.pk.attname` instead of the
  hard-coded `old_obj.id`, so models with a custom primary key name (`pk_id`,
  `uuid`, etc.) return the right identifier in the delete payload. (#34, closes #18)
- **Enum unwrap in nested writes** — `_unwrap_enums` now uses
  `isinstance(value, enum.Enum)` instead of the fragile
  `"Enum" in type(value).__name__` substring check, matching the guard in
  `native/backend.py`. A class whose name contains "Enum" but is not an actual
  enum is no longer incorrectly unwrapped. (#34, closes #18)
- **Deterministic SDL field order** — `construct_fields` now sorts fields
  unconditionally. The previous `settings.DEBUG` gate meant dev and prod SDLs
  had different field orders, breaking snapshot tests, federation registries,
  and SDL diff tools. (#35, closes #19)
- **Introspection detection by AST** — Replaces the fragile
  `startswith("\n  query IntrospectionQuery")` string check with a proper AST
  walk (`_is_introspection_document`). Any query whose top-level selections are
  exclusively `__schema` or `__type` is detected as introspection regardless of
  formatting — fixing compact inline queries and `__type` variants. (#31, closes #15)

### Performance

- **Request-scoped field-map memoization** — `_relation_field_map` and
  `_concrete_field_map` accept a per-invocation `_cache` dict threaded through
  all walker functions by `_apply_optimizations`. Each `(model, map-kind)` pair
  calls `_meta.get_fields()` at most once per optimizer run (down from 6+ for a
  typical two-model query). (#36, closes #20)
- **Selection-aware mutation re-read** — `DjangoModelType.perform_mutate`
  locates the output-field sub-node in the mutation selection set and passes it
  through `_apply_optimizations` before the DB re-read, so forward-FK relations
  present in the mutation response are pre-joined via `select_related`. (#36, closes #20)
- **Single parse with `EXPOSE_QUERY_COST`** — `execute_graphql_request` accepts
  an optional `document=` kwarg; `GraphQLView.get_response` parses once and
  threads the document to both the executor and cost checker. With
  `EXPOSE_QUERY_COST=True`, `parse()` is called exactly once per request. (#31, closes #15)
- **One fewer `COUNT` per forward page** — `PageGraphqlPagination` now runs the
  `COUNT` query only when navigating to the last page (see Fixed above). (#33, closes #17)

### Packaging

- **`py.typed` shipped** — PEP 561 marker file added; mypy/pyright now resolve
  types from the installed package without additional configuration. (#37, closes #21)
- **sdist hygiene** — `[tool.hatch.build.targets.sdist]` allowlist ensures only
  `django_graphex/`, `tests/`, `docs/`, `README.md`, `LICENSE`, and
  `pyproject.toml` are included in the source distribution; `.claude/` and
  `specs/` are provably absent from the tarball. (#37, closes #21)
- **`__version__` from `importlib.metadata`** — Single source of truth: the
  installed package version is derived at import time; a `get_version(VERSION)`
  fallback handles editable/source installs. (#37, closes #21)
- **Dependency caps** — `channels-redis>=4.2,<5.0` and `daphne>=4.0,<5.0`
  prevent accidental upgrades to as-yet-untested major versions. (#37, closes #21)
- **Metadata fixes** — `Documentation` URL corrected; PyPy classifier removed
  (untested in CI); stale `README.rst` reference removed from `MANIFEST.in`.
  (#37, closes #21)

### Documentation

- **Overhaul** — All verified doc/code drift fixed: `only_fields`/`exclude_fields`
  kwarg names, `ListField()` `AttributeError` warning, `Registry` public import
  note, `DjangoUnionType` / `DjangoInterfaceType` API reference sections,
  `CACHE_ACTIVE` default clarification. Pydantic validation docs consolidated
  to `backends.md` (single home). Nested UPDATE worked examples, mutation
  complete example with client tab, `DjangoNestedListObjectField` documented in
  `fields.md`, pagination `page_size_query_param` semantics and cursor
  single-field design noted. Directive middleware required banner relocated.
  `docs/api/utils.md` removed. (#39, closes #23)
- **New caching guide** — `docs/usage/caching.md` documents key anatomy,
  per-user isolation, mutation invalidation, malformed-query handling, and
  `cache_key_prefix` customisation. Settings page expanded with security
  semantics. (#27, closes #11)

### Behavior changes

!!! warning "Upgrade actions required"

    Review each item below before upgrading. Most require no action; the ones
    marked **action required** need a one-time change in your project.

- **`MAX_BATCH_SIZE` default is now `10`** — Batch requests longer than 10
  entries are rejected with HTTP 400. Deployments that intentionally send large
  batches must set `DJANGO_GRAPHEX["MAX_BATCH_SIZE"] = None` (unlimited) or a higher
  integer. (#31, closes #15)
- **`@date(format: "iso")` output format changed** — The old output
  (`"2023-Dec-01T14:30:00"`) was locale-dependent and unparseable; the new
  output is real ISO 8601 (`"2023-12-01T14:30:00"`). If you have clients or
  tests that match the old locale-abbreviation format, update them. (#32, closes #16)
- **Schema SDL field order is now deterministic everywhere** — Previously
  `DEBUG=True` sorted fields but `DEBUG=False` did not, causing dev/prod
  divergence. The order is now consistently alphabetical in both modes.
  **Action required**: regenerate any SDL snapshot files once after upgrading.
  (#35, closes #19)
- **Cache key format changed** — The per-identity token added for cross-user
  isolation changes the shape of every cache key. The cache will be cold after
  upgrading; no stale cross-user entries will survive. No action required beyond
  accepting a one-time warm-up cost. (#27, closes #11)
- **`page=0` now raises a `GraphQLError`** — Previously `page=0` silently
  returned an empty result set (or crashed under `python -O`). Clients that
  sent `page=0` expecting an empty page must send `page=1` instead. (#33, closes #17)
- **Subscriptions guard is fail-closed** — `SUBSCRIPTIONS_CHANNEL_GUARD=True`
  (default) requires that the HTTP subscribe request and the WebSocket connect
  reach the same worker, or that all workers share the `"default"` cache
  backend (e.g. Redis). Single-worker / single-process deployments are
  unaffected. Multi-worker deployments must configure a shared cache or set
  `SUBSCRIPTIONS_CHANNEL_GUARD=False` to disable the guard. (#30, closes #14)
- **New settings introduced**: `MAX_BATCH_SIZE` (default `10`),
  `SUBSCRIPTIONS_CHANNEL_GUARD` (default `True`). Both live under the
  `DJANGO_GRAPHEX` dict in `settings.py`. (#31, closes #15; #30, closes #14)

## 1.2.0

### Added

- **`DjangoUnionType`** — a base for a GraphQL `Union` whose members are explicit
  `DjangoObjectType`s (`Meta.gfk_types = (MemberAType, MemberBType)`). Its main
  use is exposing a `GenericForeignKey` as a **typed** union instead of the flat
  `GenericForeignKeyType`, so clients select per-member fields via inline
  fragments. A GFK owner opts in with `Meta.gfk_unions = {"<fk_name>": TheUnion}`.
  Members are explicitly enumerated — the `django_content_type` table is never
  queried to discover them. A mandatory, provided `resolve_type` maps each row to
  its registered type (raising a descriptive `TypeError` on an unregistered
  model). Declaration order is load-bearing: **members → union → owner LAST**; a
  mis-ordered declaration logs a `WARNING` and falls back to `GenericForeignKeyType`.
  See [Types — DjangoUnionType](usage/types.md#djangouniontype-typed-genericforeignkey-targets).
- **`DjangoInterfaceType`** — a base for a GraphQL `Interface` that shares field
  declarations across multiple `DjangoObjectType` implementors (via the existing
  `Meta.interfaces` kwarg). Schema-level field sharing only — no new fetch path.
  See [Types — DjangoInterfaceType](usage/types.md#djangointerfacetype-shared-fields-across-types).
- **Per-content-type column narrowing for union GFKs (Django 5.0+)** — when
  `OPTIMIZE_ONLY_FIELDS` is on, a union-typed GFK is prefetched via
  `GenericPrefetch` with **one narrowed queryset per content type**, each
  `.only()`-restricted to that member's selected columns, batched across all
  parents (no N+1). On **Django < 5.0** the optimizer degrades gracefully to a
  single bare full-load `Prefetch` — it never imports `GenericPrefetch`, never
  narrows columns, and is never slower than before. Each distinct content type
  yields exactly one queryset; two members over one shared table are collapsed
  (merged `.only()` columns). See
  [Types — per-content-type narrowing](usage/types.md#per-content-type-column-narrowing-django-50).

### Fixed

- **Inline-fragment type-condition guard.** The query optimizer no longer
  descends into an inline fragment whose `type_condition` names a *different*
  concrete type than the one being walked, preventing field mis-attribution
  against the wrong model's relation map. Inert before this release (no
  polymorphic output types were exposed) but the correctness foundation the
  union/interface routing above builds on.
- **Nested writes now expose object inputs in the GraphQL schema.** A
  `DjangoModelMutation` (or `DjangoModelType`) declaring `Meta.nested_fields`
  reused the model's generic cached input type, so its nested relations were
  exposed as `[ID!]` and a client could not create children inline — even though
  the backend supported it. The mutation now builds a distinct nested-aware input
  (e.g. `PostCreateNestedCommentsType` with `comments: [CommentCreateInput!]`)
  while a sibling generic mutation on the same model keeps its `[ID!]` input
  unchanged, regardless of declaration order.

### Documentation

- Optimizer docs brought up to date with the 1.1.0 internals: documented
  `AnnotatedField`, the `OPTIMIZE_NESTED_PAGINATION` / `OPTIMIZER_SAFE_MODE` /
  `OPTIMIZE_ANNOTATED_FIELDS` settings, GenericForeignKey prefetch, and the
  safe-mode degrade. Corrected the nested-list pagination section, which
  previously said nested lists were sliced "in memory" — by default they are now
  sliced DB-side via `ROW_NUMBER()` window functions.

## 1.1.0

### Added

- **`OPTIMIZER_SAFE_MODE`** (default `False`) — opt-in coarse fail-safe: any
  exception raised inside the queryset-optimization block degrades the whole
  resolve to the un-optimized queryset and logs a `WARNING` instead of surfacing
  a 500. Default is fail-loud. See
  [Query Optimization — OPTIMIZER_SAFE_MODE](usage/query-optimization.md#optimizer_safe_mode-fail-safe-degrade).
- **GenericForeignKey / GenericRelation prefetch** — `GenericForeignKey` targets
  are added to `prefetch_related` (the parent's content-type-id and object-id
  columns are retained so the second query resolves) and `GenericRelation`
  reverse sides are prefetched and `.only()`-narrowed (their content-type /
  object-id attnames kept). See
  [Query Optimization](usage/query-optimization.md).
- **`OPTIMIZE_NESTED_PAGINATION`** (default `True`) — DB-side
  `ROW_NUMBER() OVER (PARTITION BY fk)` window slicing for reverse-FK nested
  paginated lists (`LimitOffsetGraphqlPagination` / `PageGraphqlPagination`),
  fetching only the requested page rows per parent in a single query, with a
  filter-aware `totalCount` carried per partition. Set `False` to fall back to
  the in-memory order+slice path. See
  [Nested Lists — Performance (N+1)](usage/nested-lists.md#performance-n1).
- **`AnnotatedField`** — a public, declarative GraphQL field backed by a Django
  ORM annotation
  (e.g. `comment_count = AnnotatedField(graphene.Int, Count("comments"))`),
  injected only when the field is selected in the query; gated by
  `OPTIMIZE_ANNOTATED_FIELDS` (default `True`). Forward-FK relations whose child
  selection contains an `AnnotatedField` are auto-promoted from `select_related`
  to `prefetch_related` (annotations can't cross a SQL JOIN). See
  [Fields — AnnotatedField](usage/fields.md#annotatedfield).
- **Per-field optimize hook** (`optimize_<field>`) on parent graphene types.
  Declare an `optimize_<snake_field>(queryset, info, **kwargs)` static method on
  the parent `DjangoObjectType` to customize the child queryset for a specific
  `DjangoNestedListObjectField`. The hook is applied after the optimizer builds
  the child queryset and before Django executes it — allowing you to add
  `select_related`, annotations, ordering, or any other queryset modification
  without disabling the global optimizer.  Hook kwargs include `filter_value`
  (the filter input or `None`) and `is_window` (`True` on the window-sliced
  path, `False` on all plain paths). When no hook is declared, behavior is
  byte-identical to the pre-1.1 baseline (purely additive). See
  [Nested Lists — Per-field optimize hook](usage/nested-lists.md#per-field-optimize-hook)
  for a worked example.

### Changed

- **BREAKING — minimum Django is now 4.2.** Django 4.0 and 4.1 (both end-of-life)
  are no longer supported. Projects pinned to those versions should stay on
  `django-graphex` 1.0.x.
- **BREAKING — public classes renamed (the `Extra` prefix is dropped).**
  `ExtraGraphQLSchema` → **`DjangoGraphQLSchema`** and
  `ExtraGraphQLDirectiveMiddleware` → **`GraphQLDirectiveMiddleware`**. Update your
  imports and the `GRAPHENE["MIDDLEWARE"]` dotted path to
  `django_graphex.middleware.GraphQLDirectiveMiddleware`. `DjangoGraphQLSchema` also avoids the
  name clash with `graphql.GraphQLSchema` from graphql-core.

## 1.0.0

The first release. A GraphQL + Django toolkit built directly on `graphene`
(graphene-core) and **Pydantic v2** — **no** `graphene-django`, **no**
`djangorestframework`, **no** `django-filter`.

### Model types, mutations & the native backend
- **`DjangoModelType` / `DjangoModelMutation`** — define a Django model once and get
  query, list and create/update/delete operations. Backed by `Meta.model` and a
  native **Pydantic v2** `SerializerBackend` that validates and persists with the
  Django ORM (field types, `max_length`, `Decimal` precision, required/nullable/
  defaults, `choices` → `Enum`, FK pk types, M2M as a list of pks), and runs the
  DB-level checks Pydantic can't — **FK existence**, **uniqueness** and
  `unique_together`. Supports partial updates.
- **Custom validation** without a serializer: declare DRF-style inline
  `validate_<field>(self, value)` and an object-level `validate(self, data)` directly
  on the class, and/or pass a `Meta.pydantic_model` with validators (they compose).
- **Atomic, relation-aware nested writes** — `Meta.nested_fields = {field: Model}`
  for forward FK, reverse FK and M2M children, written in one transaction (parent or
  child failure rolls everything back) with `field.subfield` error paths.
- **Custom output fields** declared on a `DjangoModelType` are honored, including
  their `resolve_<field>` resolver methods (and `source=`), inherited/overridable
  down the MRO.

### Filtering
- **Native `and` / `or` / `not` filtering** through a single nested `filter:`
  argument (a generated `<Model>FilterInput`), built on Django's ORM lookups + `Q`
  objects. Per-field lookups, relation descent (auto `.distinct()` on to-many joins),
  plain-pk / `UUIDField` filtering (`id: { exact/in }`), and `choices` filtered via
  their `Enum`. Declared with `Meta.filter_fields` (list or dict form); the common
  base lookup set is configurable via `COMMON_FILTER_LOOKUPS`. A `FilterBackend` seam
  keeps it swappable.
- Custom filtering logic via the `get_queryset` / `filter_queryset` hooks.

### Lists, pagination & performance
- Three paginators — **`LimitOffsetGraphqlPagination`**, **`PageGraphqlPagination`**
  and **`CursorGraphqlPagination`** (keyset cursor with a non-opaque `pageInfo`).
  Pagination/ordering live on the `results(...)` subfield; lists expose the uniform
  `results` / `totalCount` shape, including **nested** related lists.
- **Automatic N+1 query optimization** — `select_related` / `prefetch_related` /
  `.only()` derived from the GraphQL selection (incl. filtered nested-list
  prefetches), tunable with `OPTIMIZE_QUERYSET` / `OPTIMIZE_ONLY_FIELDS`.
- An effective `MAX_PAGE_SIZE` ceiling applied even when no page-size arg is sent.

### Subscriptions
- Real-time GraphQL **subscriptions over Django Channels 4** (optional
  `[subscriptions]` extra) with an in-house signal → `group_send` engine; configurable
  notification payload (id-only vs full) and value-scoped "indexed" groups.

### Permissions & security
- DRF-style **permission classes** (`BasePermission`, `IsAuthenticated`, `IsAdmin`,
  `IsAuthenticatedOrReadOnly`, …) usable on types, subscriptions and views.
- **Query depth limiting** (`MAX_QUERY_DEPTH` / `Meta.max_depth`) and **query cost
  analysis** (`MAX_QUERY_COST` / `Meta.complexity`, optional `extensions.cost`).
- **Security middlewares** — `DisableIntrospectionMiddleware`,
  `AuthenticatedFieldsMiddleware` — and `ExtraGraphQLSchema` for declaring private
  fields. Every execution error carries a machine-readable `extensions.code`.

### Views
- **`GraphQLView`** (response caching + depth/cost rules + `extensions.cost`),
  **`BaseGraphQLView`** (minimal, self-contained — no `graphene-django`), and
  **`AuthenticatedGraphQLView`** (endpoint-level auth gate via the library's own
  permission classes, no DRF). GraphiQL is served from a self-contained CDN page,
  overridable with `graphiql_template` for offline / strict-CSP setups.

### Directives
- Schema directives for string/number/list/date transforms (`@title_case`,
  `@snake_case`, `@slugify`, `@truncate`, `@round`, `@abs`, `@unique`, `@date`, …;
  custom directive names are snake_case), with directive arguments as GraphQL
  variables.

### Requirements
- **Python** 3.12–3.14, **Django** 4.2–6.0 (LTS 4.2 and 5.2 recommended for production), **graphene** >=3.3,<4, **pydantic** >=2,<3.

!!! note "Django range clarification"

    The 1.0.0 release initially listed Django 4.0–6.0 in its requirements. The
    true minimum is **Django 4.2** — Django 4.0 and 4.1 are end-of-life and were
    never tested. From 1.1.0 onward the supported range is explicitly 4.2–6.0.
