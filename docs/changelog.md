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

### Security

- **One WebSocket socket could open unbounded subscriptions.** The
  `graphql-transport-ws` consumer registered every accepted `subscribe` with no
  ceiling, and each live operation joins its own channel-layer group — so a
  single client turned one connection into hundreds of subscribers (500
  concurrent operations on one socket was reproduced) while the HTTP side had
  bounded its analogous surface with `MAX_BATCH_SIZE` since 1.2.1. The new
  **`MAX_SUBSCRIPTIONS_PER_CONNECTION`** setting (default `50`) caps the
  concurrent operations one socket may hold. **This rejects subscriptions that
  used to be accepted**, but only past 50 concurrent operations on a *single*
  connection; a `subscribe` past the cap is answered with the transport's own
  `error` frame naming the limit, and the socket plus every subscription
  already running on it survive untouched. A slot frees itself the moment its
  operation ends (client `complete`, stream end, or disconnect). Set
  `MAX_SUBSCRIPTIONS_PER_CONNECTION = None` to restore the previous unbounded
  behaviour. The SSE transport is unaffected: one request carries exactly one
  subscription. See
  [Subscriptions › Per-connection subscription cap](usage/subscriptions.md#per-connection-subscription-cap).
- **A cross-site form could execute mutations under the victim's session.** The
  endpoint is `csrf_exempt` and `parse_body` accepts
  `application/x-www-form-urlencoded` and `multipart/form-data`. Both are
  CORS-*simple* content types, so a `<form>` on any origin posted straight
  through with no preflight and the browser attached the victim's session
  cookie — a plain CSRF hole on every mutation. The same hole was open on the
  **SSE subscription endpoint**, which is `csrf_exempt` too and reads a
  form-encoded `query` straight out of `request.POST`. The new
  **`REQUIRE_CSRF_HEADER`** setting (default **`True`**) now demands the
  **`X-Requested-With`** header on the CORS-simple set — form-encoded,
  multipart, `text/plain`, and a body-less POST carrying no content type at all
  — and answers HTTP 403 before the body is read otherwise, on the HTTP views
  **and** on the SSE endpoint (whose refusal is a plain body, not a JSON
  envelope, because an `EventSource` client does not parse one). The header is
  not CORS-safelisted, so requiring it forces back the preflight the attacker
  page cannot pass; the value itself is never inspected. The check runs **ahead
  of every dispatch**, wrapped around the view callable, because
  `GraphQLView.dispatch` owns the whole response-cache interaction and reaches
  the shared dispatch only through `super_call`: a guard behind it is bypassed
  by a warm cache entry, has its own 403 stored and replayed to legitimate
  callers, and still lets a rejected mutation flush the caller's cache
  namespace. **`application/json` and `application/graphql` clients change
  nothing**: neither is simple, so both already required a preflight. See
  [Security › Cross-site POST protection](usage/security.md#cross-site-post-protection).

    !!! warning "This is a breaking change for two kinds of client, on by default"

        **Who breaks.** Anyone POSTing `query=` as
        `application/x-www-form-urlencoded`, and **anyone using the multipart
        file upload shipped in 2.2.0** — that feature works in the published
        release, so upload clients written against 2.2.0 do break here.

        **What they see.** HTTP 403 with
        `This content type requires the X-Requested-With header. …`, before the
        body is read. The message names the header; there is no silent failure
        and no partial execution.

        **The fix, one line.** Add the header to the request:
        `headers={"X-Requested-With": "XMLHttpRequest"}` (`requests`),
        `xhr.setRequestHeader(...)`, or the equivalent. The value is never
        inspected. Nothing else about the request changes.

        **The opt-out.** `REQUIRE_CSRF_HEADER = False` restores the previous
        behaviour wholesale. Use it only if a client genuinely cannot set a
        header **and** the endpoint is protected another way.

        **Why multipart is not exempted.** `multipart/form-data` is itself a
        CORS-simple content type, so a cross-site `<form enctype="multipart…">`
        posts to the endpoint with no preflight at all. Exempting it to spare
        the upload clients would reopen exactly the hole this closes — and
        would leave the *upload* mutations, the ones that write files, as the
        only unprotected surface.

- **Disabling introspection still leaked the schema, one guess at a time.**
  `format_error` returned graphql-core's `formatted` mapping verbatim, so the
  `Did you mean 'email'?` suggestion appended to an unknown field, type or
  argument rode out even with `DisableIntrospectionMiddleware` installed —
  probing with invented names rebuilt much of a schema the operator believed
  was hidden. The WS and SSE transports leaked it by the same route, serializing
  raw `error.formatted` of their own, so any deployment exposing subscriptions
  kept the oracle open on a `subscribe` frame or a direct POST to the SSE
  endpoint. The trailing suggestion sentence is now stripped whenever
  introspection is **actually** disabled (the middleware installed *and*
  `ALLOW_INTROSPECTION=False`), through **one shared formatter**
  (`django_graphex.security.format_graphql_error`) that the HTTP view and both
  transports call — WS covers its validation errors, its subscribe-entry
  failures and its in-stream `next{errors}` frames. The strip is keyed on the
  **rules that actually leak** — `FieldsOnCorrectTypeRule`,
  `KnownTypeNamesRule`, `KnownArgumentNames*Rule`, `ValuesOfCorrectTypeRule` /
  `coerce_input_value` and enum-value coercion — by matching the message each
  one writes ahead of its suggestion, not by matching the shape of a trailing
  `Did you mean …?` sentence. Nothing else changes: the rest of the message, the
  `locations` and the `path` all survive; `ScalarLeafsRule`'s
  `Did you mean 'field { … }'?` guidance (built from the name the *client*
  typed, not from the schema) and a resolver-raised application error that
  happens to end in a question keep every word; and with introspection allowed
  the suggestion is kept because the same names are public anyway. The strip is
  request-independent by design, so the `INTROSPECTION_ALLOW_SUPERUSER` bypass
  does not restore it — an error body reaches the response cache, where a
  per-user decision would serve one caller's body to another. See
  [Security › "Did you mean" suggestions are stripped too](usage/security.md#did-you-mean-suggestions-are-stripped-too).

### Changed

- **Subscriptions are now measured against `MAX_QUERY_DEPTH` and
  `MAX_QUERY_COST`.** Both transports validated with graphql-core's default
  rules, so the depth and cost guards never saw a subscription document — while
  [Mutations](usage/mutations.md) says they are enforced on "query, mutation,
  and subscription selection sets" and
  [Query optimization](usage/query-optimization.md) says "**all** GraphQL
  operation types". The WebSocket and SSE transports now validate with the same
  settings-driven rule tuple the HTTP view uses. **This rejects subscriptions
  that used to be accepted**: a subscription's selection set is re-executed for
  every delivered event, so an over-deep or over-costly document was paid for
  repeatedly rather than once — the guard matters more here than on a one-shot
  query, not less. A project that relied on the gap must raise
  `MAX_QUERY_DEPTH` / `MAX_QUERY_COST` far enough to cover its subscription
  documents.
- **`BaseGraphQLView.format_error` is now an instance method taking the
  request** — `format_error(self, error, request=None)`, previously
  `@staticmethod format_error(error)`. It has to be: the formatter decides
  whether to strip the schema suggestion by looking at the middleware chain, and
  the chain that actually ran comes from `get_middleware(request)`, the same
  per-request hook execution asks. A static, request-less formatter could reach
  neither, and a subclass that resolves middleware per request got a formatter
  whose verdict disagreed with the chain that ran. **Migration:** a subclass
  overriding it as `def format_error(error)` (or a caller invoking
  `MyView.format_error(err)` on the class) must become
  `def format_error(self, error, request=None)`. Calls through an instance —
  `self.format_error(err)` — are unaffected.

### Fixed

- **`totalCount` was counted whether or not the client asked for it.** A list
  served by `DjangoModelType` issued its `COUNT(*)` eagerly, so a query
  selecting only `results` paid for two round trips where the
  `DjangoListObjectField` path paid for one — while
  [Pagination](usage/pagination.md) states the count is "only issued when the
  client actually **selects** `totalCount`". The count is now deferred to first
  access, matching the sibling path and the documented behaviour. A client that
  does select it sees the same number as before, including under a filter or a
  page limit, because the deferred call still closes over the unsliced queryset.
- **A nested child was fetched and authorized twice on every write.** The
  reverse-relation and many-to-many paths resolved the child by primary key,
  ran the ownership and scope checks, and then handed the raw payload to the
  writer, which resolved the same row again and repeated the same checks — two
  lookups plus two scope queries per host, per child, growing linearly with the
  payload. The already-resolved row is now passed through. Every check still
  runs, and runs against the same row: the authorization outcome is unchanged
  for every relation kind, for a permitted and a denied caller alike.
- **A multipart part spelled the way the SDL spells it was silently dropped.**
  The merge that folds an upload into a mutation payload built its allow-list
  from each input field's snake_case model attribute, so `profilePhoto` — the
  only spelling a client can discover from the schema — matched nothing: the
  part was dropped and the mutation still answered `ok: true` with no file
  written. Both spellings are now accepted, read off the same compiled input
  field so the pair cannot disagree. The projection guard is unchanged: a part
  naming a field the input does not publish is still ignored under either name.
- **A malformed batch entry answered HTTP 500 where the docs promise 400.** A
  batch body was checked for being a non-empty list but never for what the list
  held, so an entry that was not a JSON object reached `get_graphql_params`,
  where `data.get("query")` raised an `AttributeError` that escaped the view's
  error handler: posting `[1, 2, 3]` returned a 500 while
  [Views](usage/views.md) documents a 400. Every entry is now checked alongside
  the outer list and a non-object one is rejected with the documented 400. A
  well-formed batch executes exactly as before.
- **A misconfigured write host was accepted in silence, three ways.**
  `DjangoModelMutation` never ran the unknown-`Meta`-option check its sibling
  `DjangoModelType` has run since 2.0, so `exclude_field` — a typo for
  `exclude_fields` — built a mutation whose input still carried the very column
  the declaration meant to hide, and a `Meta.queryset` was accepted while
  scoping nothing (this host scopes through `filter_queryset`).
  `permission_classes` was worse than a no-op: the plain assignment raised a raw
  Pydantic error telling you to annotate it `ClassVar`, and taking that advice
  bought a class that builds with a permission that never fires, because the
  class reads the name nowhere. And a `nested_fields` key naming no relation was
  skipped when the input surface was built and skipped again on the write path,
  yet the generated input type was still *named* after it — so `{'bookz': Book}`
  minted an `AuthorCreateNestedBookzType` carrying no nested field at all, on
  both hosts. All three now raise `ImproperlyConfigured` at class definition,
  the nested one listing the accessors that would have worked. A schema that
  builds today can therefore fail to build after upgrading — which is the point:
  each of these classes was running a configuration its author had written down
  and the library had thrown away.
- **An unknown `Meta` option that is real on a sibling class read as a typo.**
  `registry` is a supported option on `DjangoModelMutation`, but declared on a
  `DjangoModelType` it was reported with nothing but "Check for typos", sending
  you hunting for a misspelling in a word spelled correctly. The message now
  names the classes that do accept the option, read from their own signatures so
  the list cannot drift out of date.
- **…and then told you to look for the typo anyway.** The sentence naming the
  sibling class was *appended* to the typo hint rather than replacing it, so the
  user who spelled `registry` correctly still read "Check for typos" and went
  looking for a misspelling that was not there. The hint is now emitted only
  when at least one unknown name is a `Meta` option on no class at all. A real
  typo reads exactly as it did.
- **A write-only `DjangoModelType` seized the model's read container.** Every
  generated list container claims the model's canonical registry slot on a
  last-write-wins basis, and that slot is what a reverse to-many relation
  resolves through — so a host declaring
  `Meta.model_operations = ("create", "update", "delete")`, which says in as
  many words that it does not serve `list`, still displaced the
  `DjangoListObjectType` the project had declared for its reads. Attaching a
  permission to a model's write path (`permission_classes` lives on
  `DjangoModelType`, not on `DjangoModelMutation`) therefore silently rewrote
  that model's shape everywhere it appears nested, and a query selecting the
  declared container's `pageInfo` stopped validating. A host that does not serve
  `list` now hands the slot back to whoever holds it, and still fills an empty
  one so a project with a single write-only host keeps that host's own
  pagination. A host that *does* serve `list` is unchanged, and
  `_meta.output_list_type` is still populated on every host, so
  `list_object_type()` and `ListField()` are unaffected.
- **Both subscription transports stopped importing without configured Django
  settings.** Sharing the HTTP view's validation-rule tuple — and, for SSE, its
  CSRF guard — put a module-level `from ...views import ...` in each transport,
  and `views` reaches `core.permission_signature_cache`, which reads
  `DJANGO_GRAPHEX` *while it is being imported*. So
  `import django_graphex.subscriptions.transports.ws` raised
  `ImproperlyConfigured` on the import alone, breaking any ASGI entrypoint that
  reaches the consumer (directly or through a routing module) before it points
  the process at a settings module — a dependency neither transport had before.
  Both imports are deferred into the request/operation path, so the shared rule
  tuple and the shared CSRF guard are unchanged and the transports import
  settings-free again.
- **Two write-only hosts over one model resolve to the first one declared.** The
  container-slot fix above reverses the old outcome for this case: the first
  host fills the empty slot, so the second finds it taken and hands it back,
  where last-write-wins used to give the slot to the second. Neither declaration
  claims `list`, so nothing in either ranks them; first-wins is kept because it
  is the choice that does not move a model's read shape when a second write
  concern is added later, and it drops nothing — the losing container is still
  on its own `_meta`, and a write-only host's `ListField()` raises, so it can
  never reach a schema. Only a project declaring **two** write-only hosts for
  one model is affected; one host, or any host that serves `list`, is unchanged.
- **The test suite was order-dependent: some shuffles died with `Schema must
  contain uniquely named types`.** No library behaviour changed — the defect was
  test hygiene. The output registry is keyed by **model**, so when two unrelated
  test modules declared a class under the *same* GraphQL type name for the same
  model on the **global** registry, one module kept its own compiled node while
  the registry handed the other's out through the relation graph, and any schema
  reaching both died. Nine such names were reachable from a real schema
  (`_PostListType`, `_PostType`, `_PostT`, `_TagT`, `_AuthorT`, `_AuthorType`,
  `_AuthorList`, `HookType`, `ScopedDocType`); each is now module-unique. The
  four node types the six subscription-transport modules each re-declared, and
  the subscription schema each of them rebuilt on every call, now live once in
  `tests/subscriptions/_transport_schema.py`. The root cause behind two of the
  names was `tests/test_optimizer_phase_c.py` passing `{}` as `Meta.registry`:
  an empty dict is falsy, so `Meta.registry` fell back to the global registry
  and every type built there published itself process-wide. Two further modules
  now keep the throwaway types they declare only to read `_meta` off the global
  registry entirely, and the two `ScalarKindsModel` round-trip tests mount only
  the scalar field they assert instead of the whole compiled type, so neither
  drags the shared relation graph into a schema. Verified with the full suite
  under 150 distinct `--randomly-seed` values, including the seeds that used to
  fail.

### Removed

- Six internal names that nothing in the package reached, each confirmed
  callerless before deletion. None was exported through `django_graphex.__all__`
  or documented anywhere. Four of them were nonetheless importable by name —
  `utils.py` and `converter.py` declare no `__all__`, so
  `from django_graphex.utils import get_obj`, `create_obj`,
  `converter.assert_valid_name` and `converter.convert_choice_name` resolved on
  2.2.0 and raise `ImportError` here. None had a caller inside the package, and
  `create_obj` returned an error *string* rather than raising, so a project
  depending on it was already handling a value it could not distinguish from
  success. The names:
  `paginations.utils._nonzero_int` (which also still carried the zero
  passthrough its sibling `_positive_int` documents fixing — `_nonzero_int(0,
  strict=True)` returned `0` instead of raising, and it accepted negatives);
  `Registry._interface_implementors` (never written and never read —
  `get_member_models` derives implementors from `_types` on demand, so the
  second store could only go stale); `utils.get_obj` and `utils.create_obj`
  (test-only, and `get_obj`'s whole `except` chain was unreachable because
  `get_Object_or_None` already swallows those exceptions); and
  `converter.assert_valid_name` / `converter.convert_choice_name`, superseded by
  `_is_valid_name` and `choice_enum_name`.
- The `NullBooleanField` key from the two internal-type-keyed field maps
  (`core.fields.FIELD_TYPES` and the filter-schema scalar map). Django reports
  `"BooleanField"` from `get_internal_type()` for a `NullBooleanField`, so the
  key was unreachable in both — and the package's third field map had already
  dropped it, leaving the three to drift apart. A `NullBooleanField` resolves to
  a boolean exactly as before, now through one key in all three.

### Documentation

- **The example project demonstrated none of the 2.2.0 permission story, and its
  nested mutation was the exact shape those release notes call vulnerable.**
  `examples/playground` imported five permission classes to assign one, and
  neither `commentCreate` nor the nested `postWithCommentsCreate` carried any —
  so an anonymous caller created a `Post` *and* its `Comment` rows through the
  parent, in a project whose README claimed it showed "every major feature".
  Comment writes are now served by a `CommentModelType` carrying the
  `IsOwnerOrReadOnly` the module already defined, which is the same gate the
  nested write runs: the caller denied the child's own mutation is denied it
  through the parent, and the parent rolls back with the denial.
  `PERMISSION_SCOPED_SCHEMA` is switched on so `/graphql/secure/` serves each
  caller a schema pruned to their model permissions — including the nested
  `comments` input, which is stamped with the *child's* permission — and the
  README's coverage matrix now separates what the playground demonstrates from
  what it merely imports. See
  [Permission-scoped schema](usage/permission-scoped-schema.md).
- **Four pages described a codebase that had moved.** The playground schema tour
  still named a `CommentMutation` that no longer exists and still called
  `IsOwnerOrReadOnly` a pattern no type assigns; the example project's settings
  claimed subscription connections validate against a pruned schema, when both
  transports there are wired with `schema=` and pruning happens only through
  `schema_provider=`; the mutation examples still said a multipart part must be
  named after the model's snake_case attribute while the guide it links to now
  says either spelling works; and the `DjangoModelMutation` `Meta` reference
  claimed its table was the whole list while the graphene base still accepts
  `name`, `_meta`, `interfaces`, `possible_types`, `default_resolver` and
  `container`. All four now say what the code does.
- **The multipart upload pages never named the part that carries the document.**
  Both the guide and the API reference described "the part carrying the JSON
  body under whatever key your view reads", which sent readers looking for the
  `operations` / `map` envelope of the graphql-multipart-request spec — an
  envelope this library does not implement. A multipart body is read straight
  out of `request.POST`, so the parts are **`query`** and (optionally)
  **`variables`**; anything else answers `Must provide query string.` with HTTP
  400. Both pages now name them, show a working `requests.post` call, and carry
  the `X-Requested-With` requirement (the API reference had neither). See
  [Mutations › Automatic multipart uploads](usage/mutations.md#automatic-multipart-uploads).
- **Three more pages contradicted the code, and one contradicted another page.**
  The directives guide still called the spec bundle three directives in three
  places — it is five of thirty (`@skip`, `@include`, `@deprecated`,
  `@specifiedBy`, `@oneOf`), which the API reference already said; the
  pagination API reference still promised backward cursor pagination "for a
  future release" while the guide it links to says the work is **not
  scheduled**, and `CursorGraphqlPagination.__init__` takes no `last` /
  `before`; the `DjangoObjectType` `Meta` table was billed as the full set yet
  omitted `unions` and `name`, so its "every other key is rejected at startup"
  was false; and the nested-list example named a `Group.users` accessor Django
  does not create (`user_set`, compiled as `userSet`) while promising a
  `DjangoListObjectType` the example never declared. All four now say what the
  code does.
- **Two links 404'd and three snippets could not have run.** A relative link in
  the blog-schema tutorial resolved to a `permissions.md` that does not exist
  beside it, and the frontend guide reached four directories above the site root
  for `examples/playground/`. Building both tutorial schemas and validating the
  guides' queries against them also caught three snippets that fail before the
  server sees them: a nested M2M selected as `tags { name }` when a nested list
  is a container (`tags { results { name } }`), a `status` variable typed
  `String` where a field with `choices` compiles to `<app_label><Model><field>Enum`,
  and enum values sent as the model's stored `'draft'` / `'published'` instead
  of the schema's `DRAFT` / `PUBLISHED`.

## 2.2.0 — 2026-08-24

**Security release. Upgrade if you use `Meta.nested_fields`.**

Two authorization defects let a caller write child rows they were not permitted
to write, both reproduced over the wire against a real schema before being
fixed. A nested write never consulted the child's own `permission_classes`, so a
parent a caller could write was a door into a child they could not; and
`Meta.nested_fields` derived the child's input from a shared registry slot
rather than from the child's declared type, so a column hidden with
`exclude_fields` — the shape the guides teach for `is_staff` and friends —
stayed writable through the parent, and through the child's own mutation too.
`PERMISSION_SCOPED_SCHEMA` made the first one worse rather than better: it
pruned the child's own mutation and left the nested write surface untouched, so
it granted confidence it had not earned. Details in **Fixed** below.

The rest is a correctness pass over the 2.1.0 audit backlog: confirmed defects,
each reproduced before the fix and covered by a regression test.

One behaviour change worth calling out before you upgrade: declaring
`only_fields` / `exclude_fields` / `include_fields` on a type whose output type
is reused from the registry now raises `ImproperlyConfigured` at class
definition instead of dropping the option silently. A schema that builds today
can therefore fail to build after upgrading — which is the point: every schema
that stops building was silently exposing a field it was told to hide.

One rename is wire-visible: the list container a `DjangoModelType` generates is
now `<Model>ListGenericType` instead of `<Model>ListType`, which was colliding
with the name the guides give your own `DjangoListObjectType`. Field names and
shapes are unchanged; only a client document that spells the container's type
name out needs updating.

A second rename is wire-visible for the same reason: the child input a nested
field exposes is now built per nesting parent and named
`<Child><Op>In<Parent>Type` (for example `CommentCreateInPostType`) instead of
borrowing the child's own `<Child><Op>GenericType`. Field names and shapes are
unchanged apart from the fix below; only a client document that spells the
nested child input type name out needs updating.

Nested writes now run the child's own permissions, which is a behaviour change
in two directions. A nested payload that used to be accepted can now be denied —
that is the fix. And the child's checks are called with a new `nested_parent`
keyword argument, which is passed only to a check whose signature can absorb it:
an `authorize` override or a permission class that spells its arguments out
(`def authorize(cls, info, action, data=None)`) keeps working and simply never
sees the marker, treating a nested write exactly like a direct one. That holds
for a `has_permission` override too — the narrowing happens at the call that
lands on your method, not at the outer call site, so the `**kwargs` on the
built-in `has_<action>_permission` in between does not leak the marker through.
Accept `**kwargs` to see it.

Nested pk lookups resolve through `get_queryset`, which folds in `Meta.queryset`
— but only for the child hosts that **serve the write**. Which hosts those are
follows from `Meta.model_operations`, which `DjangoModelType` now takes as well
(see below): a host restricted to `model_operations = ("create",)` has no
`update` to mirror, so its scope is not applied to a nested update, and a
`DjangoModelType` declaring `model_operations = ("list", "retrieve")` is a read
host that leaves the nested write path entirely. Left undeclared, a
`DjangoModelType` still serves everything, so its `Meta.queryset` — the queryset
its own `update` and `delete` already resolve through — now gates the nested
path as well: a row outside it answers *not found*. Check any `DjangoModelType`
whose `Meta.queryset` is a display default (hiding archived or unpublished rows)
before upgrading, and declare it a read host if a parent should still be able to
update those children inline.

One configuration that used to build now raises `ImproperlyConfigured`: a host
declaring `only_fields` / `exclude_fields` / `required_perms` for a model whose
nested input has **already** been built. graphql-core caches an input object's
field map, so such a host could never reach the nested surface, and being
ignored silently is how the leak used to happen. A late host that only repeats a
declaration already contributing is accepted, since the merge is idempotent and
refusing a no-op buys nothing. Otherwise: declare every host for a model before
the first schema build.

Where a child model has more than one host, the two projection axes merge
differently, and together they can leave nothing behind. `exclude_fields` is a
prohibition and is unioned across every declared host; `only_fields` is an
allowance and is unioned across the hosts serving the operation; the prohibition
is applied last. A child whose every allowed column is excluded by a sibling host
would therefore end up with a nested input carrying no field, which graphql-core
does not accept as a legal schema — so that configuration is now refused at build
time with an `ImproperlyConfigured` naming the child, the parent and every
contributing host with both of its axes, rather than returning a schema whose
every request fails validation. Give such a child at least one column no host
forbids, or declare the read host with `model_operations = ("list", "retrieve")`.

### Added

- **`Meta.model_operations` on `DjangoModelType`.** It already existed on
  `DjangoModelMutation`; the type class now takes the same option, widened to
  the five operations it generates — `("create", "update", "delete", "list",
  "retrieve")`, which is also the default, so a project that declares nothing
  behaves exactly as it did before. An operation left out has its `*Field()`
  builder raise `AttributeError`, and `QueryFields()` / `MutationFields()`
  return only what is enabled.

    This is the opt-out for the nested-write scoping this release introduces. A
    `DjangoModelType` is a **write host** for the models a parent nests, so its
    `Meta.queryset` and its `only_fields` gate a nested write — and in the
    common read-type-plus-write-mutation split, that queryset is a plain display
    default, not a policy. Declaring
    `model_operations = ("list", "retrieve")` says so: the card stops gating the
    nested write path and stops contributing a write allowance to it, while its
    read fields work exactly as before. Declaring nothing keeps the option
    itself inert — but note that is also what leaves the card a write host, and
    therefore what makes its `Meta.queryset` gate nested writes.

### Fixed

- **A multipart upload to a `FileField` / `ImageField` could never be saved.**
  The merge that folds `request.FILES` into the input payload has been there
  since the first release, but the derived validation schema typed a file column
  as a plain string, so the uploaded file it merged came straight back as
  `{ ok: false, errors: [{ field: "attachment", messages: ["Input should be a
  valid string"] }] }` — on create and on update, on both mutation hosts, with
  no way to opt out, since the derived annotation overrides whatever a
  `Meta.pydantic_model` base declares. A file column is now typed with a marker
  that accepts exactly the two shapes it can hold: an uploaded file object, and
  the storage path string a query reads back. Every other shape is still a
  structured validation error rather than a crash at save time, and the column's
  `max_length` still constrains the string branch. Nothing moves on the wire —
  the field is `String` on input and on output, as before.

    The merge now honours the input projection, which matters precisely because
    the value validates: while a file could never be saved, a part named after a
    column the type hides with `Meta.exclude_fields` was merged and then thrown
    out by validation, so nothing landed. Making the value valid would have
    turned that same merge into a live write reaching a column the wire surface
    deliberately does not expose. Only a part naming a field the input actually
    publishes is merged; anything else is ignored, and the part must carry the
    model's snake_case attribute name rather than its camelCase alias.

    The merge is flat, so it still reaches only the model the mutation is bound
    to. A file field on a child declared in `Meta.nested_fields` remains
    unreachable, and naming a multipart part after a nested relation still
    replaces the nested payload and fails in the nested handler. That gap is
    unchanged by this fix and is now documented where the feature is described;
    for nested uploads use the base64 input.

- **`Meta.nested_fields` dropped the child's declared input projection.** The
  nested child input was never derived from the child's own type — it was
  whatever object happened to occupy the shared `(child model, operation)`
  registry slot, so the outcome depended on which class was declared first. With
  the parent declared first the slot was empty, so an **unprojected** input was
  minted straight from the Django model: every writable column landed on the
  parent's nested payload, `exclude_fields` and all. Worse, that minted input was
  registered in the shared slot, so the child's **own** mutation, declared later,
  reused it and lost its projection too — the classic
  `exclude_fields = ("is_staff", "is_superuser")` became settable through both
  the parent's nested list *and* the child's own root field, and the child's
  required back-reference `post: ID!` was silently relaxed to `post: ID` on its
  standalone surface. With the child declared first the projection survived, but
  the parent reused the child's own input, whose required back-reference foreign
  key graphql-core rejects before any resolver runs — so that order produced a
  nested field that could not be used at all. The two orders were not
  symmetric: one leaked, the other was unusable, which means every project whose
  nested writes actually worked had landed on the leaking one. Each nesting
  parent now builds its own copy of the child input, inside the parent's field
  thunk, from the hosts **declared for the child in that registry**. The two
  projection axes are merged differently, because they say different things: an
  `only_fields` is a positive allowance, so the hosts that serve the operation
  being built **union** theirs — a create-only and an update-only mutation for
  one child no longer poison each other's nested surface, and neither do a read
  card and a write mutation projecting different columns — while an
  `exclude_fields` is a prohibition — *this column is never client-writable* —
  and is unioned across **every** declared host and applied last, so a create
  host's exclusion no longer vanishes from the nested update surface and let a
  client write, on an existing row through the parent, a column the project's
  own write mutation refuses. The shared registry slot is never written, and
  only that copy relaxes the back-reference key — per parent, so a child nested
  under two parents relaxes each parent's own key and nothing else. Both
  declaration orders now produce the same, working surface. The remaining way
  that merge could have failed open is closed with it: a host declared after the
  nested input was already built raises rather than being silently dropped — the
  memo is not what freezes the surface, graphql-core's own field-map cache is,
  so no rebuild or cache clear could have recovered it.
- **A nested write never ran the child's own permissions.** `create` and
  `update` authorized the parent once and then handed the whole payload —
  children included — to the nested writer, whose only call was into the child's
  validation backend, a seam with no permission concept. A caller allowed to
  write the parent could create and update rows of a child whose own type denied
  it: `postCreate` answered `PERMISSION_DENIED` and wrote nothing, while the
  identical write smuggled inside `authorCreate`'s nested list returned
  `ok: true` and persisted the row. Under `PERMISSION_SCOPED_SCHEMA` this was
  worse than a plain gap: the pruner correctly removed the child's own
  `postCreate` root and cloned the parent's input type verbatim, so the feature
  closed the front door, left the back door open, and granted false confidence
  while doing it. Every declared host for the child model is now authorized
  before a nested create or update — all of them, so two hosts for one model
  fail closed — and the nested input field is pruned by the child's write
  permissions, whose labels now reach the schema label-set even for a child that
  has no root field of its own. Those permissions cover what the field can
  actually do rather than what the parent's verb suggests: a nested payload's
  `id` is optional on an **update** input, so omitting it creates a row, and the
  field therefore requires the child's `add` **and** `change` there — otherwise
  a caller holding `change_child` alone kept, inside the parent's update
  payload, the exact create the child's own pruned-away root refused. The
  `required_perms` of every child host that **serves** one of those verbs is
  then **unioned** onto that default, never substituted for it, so an override
  can only ever *add* a requirement: a write host declaring something stricter
  genuinely reaches the nested field — otherwise a caller who has the child's
  own roots pruned away keeps the identical write inside the parent's payload —
  while a read label is not silently read as a licence to write. Being a union
  term is not free, though: a `DjangoModelType` serves every operation unless it
  says otherwise, so a read card carrying `required_perms` also gates the nested
  field,
  and a caller lacking that label loses it even where a differently-hosted
  `childCreate` still accepts the same write. Declare such a host with
  `model_operations = ("list", "retrieve")` so its label stays on the read side.
  And an input object every field of which is pruned is
  no longer emitted unfiltered — the mutation field that takes it is pruned
  instead, so a parent whose `Meta.only_fields` names nothing but the nested
  relation loses the root rather than regaining an ungated write. A denial is
  the same `PERMISSION_DENIED` / 403 the direct mutation returns and rolls the
  whole write back. Checks receive `nested_parent`, the parent model class, so a
  child that must be writable *only* inside its parent is now expressible (under
  a permission-scoped schema that pattern needs no label of its own — the caller
  doing the nested write holds the child's write permission, and simply not
  mounting the child's own root leaves the pruner nothing to prune). The link
  paths — attaching an
  existing forward-FK or M2M row by pk — stay ungated by design: they write
  nothing on the child and offer exactly the reachability the plain
  `category: ID` surface always had.
- **A nested upsert could reach a row the child's own host hides.** The nested
  writer resolved the target row against the bare model while the top-level
  `update` / `delete` both scope theirs through `get_queryset` /
  `filter_queryset`. Naming another tenant's primary key in a nested payload
  therefore rewrote that row in place, because Django's `save()` with a primary
  key issues an `UPDATE`. Nested pk lookups now resolve through the scope of the
  child hosts that serve the write, and answer a hidden row with the same *not
  found* the child's own mutation returns — never a create at that key, never an
  update of the row the scope was hiding. The scope decision is taken **before**
  the reverse-ownership guard, which resolves the pk unscoped: a hidden row that
  happened to belong to another parent used to be answered with *does not belong
  to this &lt;Parent&gt;*, confirming its existence, while an ownerless hidden row got
  the not-found. Both now answer identically.
- **A second registry's host rewrote the first registry's nested surface.** The
  per-parent input memo and the materialization record that refuses a late host
  both live on the registry, but the host list they read from did not: it was a
  process-wide table keyed by model alone. Every nested decision reads that list
  — the projection merge, the permission stamp, the write-time row scoping and
  the write-time `authorize` loop — so a host bound to a second registry through
  `Meta.registry`, the documented multi-schema hatch, silently narrowed the
  first registry's nested payload, added its own label to it, and applied its
  `filter_queryset` to writes in a schema it has nothing to do with. Merely
  importing the other schema's module could turn every nested update in the
  first into a *not found*. The list now lives on the registry beside the two
  memos, and dies with it — but it is read as the parent's registry **unioned
  with the global one**, because `Meta.registry` is an option on
  `DjangoModelMutation` alone: a `DjangoModelType`, the only host class carrying
  `permission_classes`, can only ever register globally, so reading the parent's
  registry by itself left a parent declared with `Meta.registry` finding no
  hosts at all and the nested permission gate silent — the same front-door /
  back-door shape, reopened for multi-schema projects. A host bound to a
  non-global registry still cannot reach any other registry's parents.
- **A projected `only_fields` on a nested child stripped the pk from the update
  input.** The nested update input is what makes the documented upsert-by-id
  work, and a child write host whose `only_fields` did not happen to list the
  primary key silently removed `id` from it — so the payload the guide's worked
  example shows was rejected over the wire, and a client that dropped the
  rejected `id` got a duplicate **create** instead of an update. The same
  omission reached the host's **own** update root, whose resolver also takes the
  pk from inside the input — so `only_fields = ("headline",)` shipped an update
  mutation no client could address at all. The pk is not a projectable column on
  an update surface — it is how the row is identified — and it now survives both
  projection axes, on the nested input and on the host's own. The **create**
  input still carries no pk at all, so creates stay create-only.
- **A host's `only_fields` was silently dropped when another host had already
  registered the model's input.** The `(model, operation)` input slot holds one
  type per model, so the first host to reach it decided the wire surface for
  every later one: a `DjangoModelMutation` declaring
  `only_fields = ("headline",)` behind an already-declared display card kept
  accepting every writable column on its own root — the exact leak `only_fields`
  is documented to close — and the reverse order narrowed the card's input to
  the mutation's projection. This lot made it worse by reading the declaration
  rather than the built type when merging a nested surface, so the nested
  payload could end up wider than every mutation root in the schema. A host that
  declares a projection now gets its own input type, named after that projection
  and memoized so two hosts declaring the same one share it. Hosts that declare
  no projection keep the shared slot and are unaffected; a projected input's
  GraphQL type name gains a short `_p<hash>` suffix.
- **A child host declared after its parent had only half of it honoured.** The
  nested field's permission stamp was frozen when the parent's input class was
  defined, while the projection it must match is resolved later, inside the
  parent's field thunk. A child write host declared after the parent but before
  the schema build — the ordinary *parent app imports the child app later*
  order — therefore had its `exclude_fields` applied and its `required_perms`
  dropped, and the guard that exists to make a too-late host loud never fired,
  because the record it keys off is only written at thunk time. A caller with
  the child's own roots pruned away kept the identical write inside the parent's
  payload. The stamp is now resolved in the same thunk, from the same host list,
  as the projection. In the same pass it became operation-aware: a host's
  `required_perms` is read only for the verbs that host serves, so a delete-only
  host's label no longer removes the nested *create* field.
- **The comment defending the ungated link paths argued something untrue.** It
  claimed a linkable row *belongs to nobody, so no scope hid it either*, which
  is false whenever the child has a host with a `filter_queryset` or
  `Meta.queryset` scope. The real reason is the one the guide gives: a link
  writes nothing on the child and offers exactly the reachability the plain
  `category: ID` relation input already has, unscoped, so gating only the nested
  spelling would make two surfaces for one operation disagree. Behaviour is
  unchanged; only the reasoning is now the true one.
- **`required_perms` could not be written on a `DjangoModelType`.** The guide
  documents the plain class attribute for the mutation fields a
  `DjangoModelType` generates, and the field builder reads it — but only
  `DjangoModelMutation` declared it as a `ClassVar`, and these classes are
  Pydantic-backed, so the documented form raised `PydanticUserError` at
  class-definition time. `DjangoModelType` now declares it too, exactly as it
  already declares `permission_classes` and for the same reason. Nothing changes
  for a class that spelled the annotation out by hand.
- **A permission-scoped schema could be served for the wrong schema.** The
  pruned-schema cache keys on `id(full)` and stores a weak reference to detect
  address reuse, but a reference that had gone *dead* — the exact state an
  `id` recycle leaves behind, since the original schema must be collected before
  its address can be reused — was treated as "still valid" and the collected
  schema's pruned variant was served to the new schema. Only a reference
  resolving to the requested schema (or an entry stored without one, for a
  schema that cannot be weakly referenced) is now trusted.
- **Every validator-free type ran pydantic's deprecated `validate` on each
  write.** The inline-validator collector walked the whole MRO, so it picked up
  `pydantic.BaseModel.validate` — inherited by every host — as if it were a
  user-declared object-level hook. `Meta.pydantic_model` stopped passing through,
  a synthetic validator model was built for hosts that declared nothing, and each
  save re-validated the payload against the host type itself (a
  `PydanticDeprecatedSince20` warning per write, and a hard rejection for any
  host with required fields). The walk now stops at `BaseModel`.
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
- **`ordering` did nothing on any list that used the default paginator.** With
  the shipped defaults (no `pagination=` on the list type, no `DEFAULT_PAGE_SIZE`
  or `MAX_PAGE_SIZE`) the paginator is unbounded, and it returned the queryset
  from its unbounded early-return *before* reading `ordering` — so the argument
  was advertised in the schema, autocompleted in GraphiQL, and silently ignored:
  `ordering: "name"` and `ordering: "-name"` both returned insertion order, and
  an invalid ordering field was not even rejected. Ordering is now resolved and
  applied independently of the page-size decision, so it works on bounded and
  unbounded lists alike, across `DjangoListObjectField`,
  `DjangoFilterPaginateListField` and nested lists. Explicitly configured
  paginators are unchanged.
- **An unset variable inside a `JSON` literal aborted the whole operation.**
  `createOdd(newOdd: {payload: {a: $v, b: 1}})` sent without `$v` embedded the
  `Undefined` sentinel in the parsed value and failed with `Object of type
  UndefinedType is not JSON serializable` — so leaving an optional variable
  unset broke the request instead of omitting the key. The literal parser now
  drops such a field, exactly as graphql-core does for input-object fields. See
  [Types › `JSONField` → `JSON`](usage/types.md#jsonfield-json).
- **A `JSONString` value could not be read back by its own scalar.** A resolver
  returning a plain string (`"hello"`) put it on the wire verbatim, which is not
  valid JSON, so sending the same value back raised `JSONString cannot parse`.
  Anything that is not already valid JSON text is now `json.dumps`-encoded;
  text that already parses as JSON is still passed through unchanged. See
  [Types › `JSONField` → `JSON`](usage/types.md#jsonfield-json).
- **An input model using a Pydantic 2.10+ validated-data `default_factory`
  could not build a schema at all.** `Field(default_factory=lambda data: ...)`
  was invoked with no argument at compile time, so the type died with `<Input>
  fields cannot be resolved`. Such a factory has no compile-time value: the
  field now renders without an SDL default and Pydantic applies it per
  instance. See [Types API › `DjangoInputObjectType`](api/types.md#djangoinputobjecttype).
- **A wrapped root field made a per-schema registry pair unbuildable.** A root
  declaring `field(NativeList(SomeType))` or `field(NativeNonNull(SomeType))`
  fell through to the scalar branch of the root compiler, and that branch was
  the only one that did not carry the schema's registry pair — so the inner type
  resolved against the process-global one and the build aborted with
  `assert_schema_pair_isolation`. A bare `field(SomeType)` was unaffected, which
  is why the wrapper looked like the culprit.
- **A type implementing an interface could not be used in a second schema.** The
  per-schema copy of the type kept the interface instance compiled for the
  default schema, while a root `field(SomeInterface)` compiled a fresh one, so
  two same-named interfaces reached one schema and it failed to build with
  `Schema must contain uniquely named types`. Interfaces are now recompiled
  against the schema that owns the type.
- **`name=` was honoured on the root only.** A field declared as
  `date_ = field(GdxDate, name="date")` rendered `date` on the root and `date_`
  everywhere else — mutation payloads and nested object types camelCased the
  attribute name instead, leaking the keyword-dodging underscore onto the wire.
  See [Fields › The unified `Field`](usage/fields.md#the-unified-field).
- **A nested list ignored the `@filter_field` filters it advertised.** The
  nested `filter:` argument mounts the same `<Model>FilterInput` as the root
  list, custom filters included, but every nested path applied only the
  standard lookups — so `posts(filter: {search: "…"})` returned the unfiltered
  set (and an unfiltered `totalCount`) while the identical root query filtered
  correctly. All the nested paths — the plain prefetch, the DB-side window, its
  count subquery, and the resolver's own branches — now run both filter stages
  through one choke point. See
  [Nested Lists](usage/nested-lists.md) and
  [Filtering › Composition order](usage/filtering.md#composition-order).
- **A nested list reported a different `totalCount` on its last page.** The
  count for an empty or past-the-end window page was rebuilt from the child's
  default manager, dropping the `optimize_<field>` hook that had scoped the
  page itself: a pagination UI reading the total off the overshoot page saw the
  *unscoped* row count. The count now reuses the queryset the page was computed
  from, and the per-parent fallback re-applies the hook. See
  [Nested Lists › Per-field optimize hook](usage/nested-lists.md#per-field-optimize-hook).
- **A declared `Meta.queryset` could freeze at the first request.** The queryset
  is built once at class definition and bound as the resolver base; it was
  handed to the resolver verbatim, so with `OPTIMIZE_QUERYSET = False` (nothing
  else clones it) the first request filled its result cache and every later
  request in that process replayed it — rows created afterwards stayed invisible
  until a restart. The base queryset is now cloned per request. See
  [Types](usage/types.md) and the
  [`DjangoListObjectType` options](api/types.md).
- **With `CACHE_ACTIVE` and `ATOMIC_MUTATIONS`, the cache-invalidation bump
  fired *before* the mutation ran.** It was scheduled through
  `transaction.on_commit` from the pre-dispatch preamble, but the atomic block
  `ATOMIC_MUTATIONS` opens lives inside the execution of the mutation — so at
  scheduling time there was no open transaction and Django ran the bump
  immediately, leaving the TOCTOU window it was written to close wide open: a
  concurrent reader could cache pre-mutation data under the post-mutation
  version. The bump is now scheduled after the mutation has run. See
  [Caching › Post-commit invalidation](usage/caching.md#post-commit-invalidation-toctou-safety).
- **With `CACHE_ACTIVE`, a cached GraphiQL page was served to API clients.** The
  response-cache key ignores content negotiation, so the HTML render and the
  JSON answer for the same query shared one slot: whichever arrived first
  decided what everyone else received — a browser could warm the page and the
  next `Accept: application/json` request got `text/html` back. A request that
  would render GraphiQL now bypasses the cache entirely. See
  [Caching › Requests that bypass the cache](usage/caching.md#requests-that-bypass-the-cache).
- **A batch endpoint answered HTTP 500 for any non-JSON body.** Only an
  `application/json` body was checked for being a list; `application/graphql`,
  form-encoded and multipart bodies were iterated as-is and died with
  `AttributeError: 'str' object has no attribute 'get'`. Every batch request now
  goes through one non-list guard and gets the documented HTTP 400. See
  [Views › Batch endpoints](usage/views.md#batch-endpoints).
- **A quality value written with a space (`Accept: text/html; q=0.1`) was
  ignored**, and the entry was ranked as `q=1` — so a JSON client that
  de-prioritised HTML the perfectly legal way was served the GraphiQL page.
  Whitespace after the semicolon is now tolerated. See
  [Views › GraphiQL](usage/views.md#graphiql).
- **A nested write skipped the child type's own validation.** The nested path
  built its child validator from the child MODEL alone, so the inline
  `validate_<field>` / `validate` methods and the `Meta.pydantic_model` declared
  on that child's own `DjangoModelType` / `DjangoModelMutation` never ran: the
  exact payload the child's own mutation rejected was accepted — and written —
  through a parent's `nested_fields`. A rule expressed once, in the documented
  place, was enforced on one of the two routes to the same table. The nested
  path now reuses the child host's backend, so both routes run the same
  validator. See [Mutations](usage/mutations.md#how-nested-writes-work).
- **A malformed primary key answered with Django's internals instead of the
  error envelope.** `update` and `delete` on both `DjangoModelType` and
  `DjangoModelMutation` passed the client's `id` straight to the ORM, so
  `id: "abc"` surfaced `Field 'id' expected a number but got 'abc'.` (and a
  malformed UUID surfaced a `ValidationError`) rather than the documented
  `ok: false` / `<Model> with id <pk> does not exist.`. A value no row can hold
  matches no row, so it is now reported exactly as an absent one, at the single
  lookup helper all four resolvers share.
- **A delete input could not be declared for a model whose primary key is not
  named `id`.** `input_for = "delete"` looked the pk up under the literal key
  `"id"`, so a model on a `UUIDField`, a `SlugField` or any renamed pk raised
  `KeyError: 'id'` at class-definition time — the module simply would not
  import, with no workaround. The delete branch now reads `model._meta.pk` and
  keys the field on the real primary-key name. See
  [Types API › `DjangoInputObjectType`](api/types.md#djangoinputobjecttype).
- **An inherited `class Arguments` lost every inherited argument.** The helper
  behind the mutation argument compiler read only the class body, so factoring
  shared arguments into a base class (`class Arguments(CommonArgs)`) dropped
  them from the compiled SDL with no error at all — a required `tenant: String!`
  scope key simply disappeared. The whole MRO is now read, base classes first,
  with the most-derived declaration winning a name clash. See
  [Mutations › Custom Arguments](usage/mutations.md#custom-arguments-with-field).
- **A `@filter_field` named after a `filter_fields` key silently ate that
  field's lookups.** The custom-filter loop ran last and overwrote the compiled
  `<Model><Field>Lookups` entry, so the field became unfilterable in *both*
  shapes and the only symptom was a raw `'str' object has no attribute 'items'`
  from the query-time `Q` builder. Such a collision — including one with an
  `and` / `or` / `not` combinator — now raises `ImproperlyConfigured` when the
  filter input is built, mirroring the existing reserved-name check. See
  [Filtering › Reserved argument names](usage/filtering.md#reserved-argument-names).
- **Declaring a relation *and* a path through it dropped the nested filter.**
  `{"author": ("exact",), "author__name": ("icontains",)}` put `author` in both
  the relation and the plain-pk bucket, and the two compile loops wrote the same
  wire key, so the `AuthorFilterInput` never mounted and the declared nested
  filter vanished from the schema. The plain-pk lookups now fold onto the nested
  input under the related model's primary-key name, keeping both halves. See
  [Filtering › Filtering across relations](usage/filtering.md#filtering-across-relations).
- **An explicit nested lookup was replaced wholesale by the related type's
  own.** The canonical-shape check tested only whether the requested *path*
  existed on the related model's root declaration, then returned that root and
  discarded the requested lookups — so `PostType.filter_fields =
  {"author__name": ("icontains",)}` compiled to the root's `("exact",)` and
  `{author: {name: {icontains: "…"}}}` was rejected by validation. The
  short-circuit now requires the root's lookups to actually cover the request;
  otherwise the two are unioned, as they already were for divergent paths. See
  [Filtering › Filtering across relations](usage/filtering.md#filtering-across-relations).
- **Every string directive rendered a null field as the literal text `"None"`.**
  `@uppercase` answered `"NONE"`, `@slugify` answered `"none"`, and so on for
  the whole family, because the shared coercion helper called `str(value)`
  unconditionally — while the numeric directives already returned `null`. All of
  them now pass `null` straight through. See
  [Directives API › String Directives](api/directives.md#string-directives).
- **`@default` replaced any falsy value, not just null and the empty string.** A
  legitimate `0`, `false` or `[]` was substituted with the `to` **string** and
  then failed serialization outright (`Expected Iterable, but did not find one`,
  `Int cannot represent non-integer value`). Only `null` and `""` are
  substituted now. See
  [Directives API › `DefaultGraphQLDirective`](api/directives.md#defaultgraphqldirective).
- **`@number` and `@currency` nulled the very fields they are documented for.**
  Both always returned a formatted string, so `viewCount @number(as: ",.0f")` on
  an `Int` field and `price @currency` on a `Float` field answered `null` plus
  an opaque `Int cannot represent non-integer value: '1,234'`. On a field that
  cannot serialize a string the raw value is now returned unchanged; the
  format-spec width/precision cap still applies on every field type. See
  [Directives](directives.md#number-directives).
- **A subscription filter the schema accepted could crash the live stream.** A
  to-many field declares lookups the ORM then refuses across the join
  (`filter: { tags: { iexact: 3 } }`), so the key passed the subscribe gate and
  raised `FieldError` at delivery — escaping the SSE generator *after* the `200`
  was committed, and killing the WebSocket operation task with no frame at all.
  Client filters are now validated against the ORM itself at subscribe time, and
  a delivery-time failure on either transport is framed as `next{errors}`
  followed by `complete` instead of tearing the connection down silently. See
  [Subscriptions › Filter key validation](usage/subscriptions.md#filter-key-validation).
- **One malformed WebSocket frame leaked every live subscription on the socket.**
  A body that is not valid JSON, or a non-string operation `id`, raised out of
  the consumer, so Channels never ran `disconnect()` and every running
  operation kept its task *and* its channel-layer group. Any frame the consumer
  cannot dispatch now closes with `4400` after the full teardown.
- **An SSE response that was never iterated leaked its groups permanently.**
  The groups are joined before the response is returned, but teardown lived only
  in the streaming generator's `finally` — so a client that aborts during the
  subscribe handshake left a ghost group member every future broadcast fanned
  out to. Teardown is now registered on the response, which Django closes
  whether or not the body was read.
- **Two subscriptions on the same model cross-delivered each other's events.**
  Group names carried the model and the action but not `Meta.stream`, while the
  signal bindings registered per stream — so both fanned out into the identical
  groups and a `full`-payload subscriber received a duplicate, all-null event
  from the `id_only` one on every change. `Meta.stream` is now part of the group
  name.
- **`subscription_scope` and `authorize_subscription` were dead on both
  transports.** The subscribe hooks receive the transport context as their
  `info`, and it had no `.context` attribute — so the documented
  `info.context.user` raised `AttributeError` and the subscribe failed closed,
  with no source started. The transport contexts now expose `.context` alongside
  `.user`, so both spellings resolve. See
  [Subscriptions › Authorization and row-scoping](usage/subscriptions.md#authorization-and-row-scoping).
- **A subscription on a model with a `FileField` or `BinaryField` crashed on
  every save.** The broadcast payload is JSON-encoded, and the serializer handed
  it a raw `FieldFile` / `bytes`. File fields now serialize as their storage
  name and binary fields as base64 — matching the `String` both already render
  as on the event type.
- **The bundled subscription client pointed its SSE field at the JSON
  endpoint.** There was no `sse_path`, so the SSE input was seeded from
  `http_path`; the first-run playground POSTed a subscription to `GraphQLView`,
  got a `200 application/json` body with no `event:` line, and showed a
  connected stream with zero data and zero errors. `SubscriptionClientView` now
  has an `sse_path` (default `/graphql/stream`), and a frame the client cannot
  recognise is logged as an error instead of discarded. See
  [Subscriptions › Browser client view](usage/subscriptions.md#browser-client-view).
- **An `AnnotatedField` reached through two chained forward foreign keys
  resolved to `null`.** The select→prefetch promotion pass never recursed, so it
  only ever saw the first hop from the root: `{ comments { post { author {
  postCount } } } }` left `post__author` in `select_related`, where the
  annotation cannot ride along, and the field came back empty with no error. The
  pass now descends the whole chain carrying the dotted lookup, so the hop that
  actually owns the annotated child is the one promoted. See
  [Query Optimization › Selection-driven annotations](usage/query-optimization.md#selection-driven-annotations-annotatedfield).
- **An `... on <Interface>` fragment inside a prefetched child cost one query
  per row.** The `.only()` walkers were given the list *container*'s identity
  and no source class at all, so the guard could neither match the interface
  (only the source class carries `Meta.interfaces`) nor recognise the row type —
  every interface fragment was dropped from the projection and its columns were
  reloaded row by row. Both walkers now carry the GraphQL type through the
  `results` wrapper down to the row type. Two further walk sites read the source
  class off a `graphene_type` attribute that a natively compiled type never
  has, which silently made the same guard inert there; both now resolve it
  properly.
- **A named fragment spread on a `GenericForeignKey` union member was ignored.**
  The per-content-type bucket collector only looked at inline fragments, so a
  selection mixing `... on AccountType { balance }` with `...Money` narrowed the
  member queryset to the inline fragment's columns and fetched the rest one
  query per row. Spreads are now resolved against the document's fragments and
  merged into the same bucket. See
  [Query Optimization › Typed GenericForeignKey unions](usage/query-optimization.md#typed-genericforeignkey-unions-per-content-type-narrowing).
- **A nested list on a child with two relations back to its parent always
  resolved empty.** Every relation pointing at the parent was collected into one
  filter mapping, and a mapping is a conjunction — so a child with `created_by`
  *and* `updated_by` foreign keys (or a foreign key beside a many-to-many) was
  scoped to the rows matching both, which is nothing. Which relation is meant
  cannot be inferred, so the ambiguity now raises `ImproperlyConfigured` naming
  the relations instead of silently returning `[]`; mount such a list through
  its relation accessor. See
  [Fields › DjangoFilterPaginateListField](usage/fields.md#djangofilterpaginatelistfield).
- **A manual `prefetch_related` in `get_queryset` collided with the optimizer's
  own.** The derived lookups were appended without checking what the base
  queryset already carried, and Django rejects two lookups on the same path — so
  the documented `return queryset.prefetch_related('posts')` failed the whole
  field with `'posts' lookup was already seen with a different queryset`. A
  manual lookup the optimizer is about to re-derive is now dropped first, which
  is the "replaced" behaviour the docs already promised; manual prefetches of
  other relations are untouched. See
  [Query Optimization › Custom resolvers](usage/query-optimization.md#custom-resolvers).

### Security

- **`update` and `delete` ignored the queryset scoping that protected reads.**
  Both resolved their target row from the bare model, while `retrieve` and
  `list` went through `get_queryset` → `filter_queryset` — so the documented
  multi-tenant pattern (`qs.filter(tenant=info.context.user.tenant)`) hid
  another tenant's row from a query and still let any caller overwrite or
  delete it by primary key, returning `ok: true`. That is the worst possible
  shape: a developer verifying the scope on the read path concludes it works.
  Both write methods now resolve the row through the same scoped queryset, and
  a row outside the scope answers exactly as a missing one (`ok: false` with
  `<Model> with id <pk> does not exist.`), so the response cannot be used to
  probe which primary keys exist. See
  [Filtering › `filter_queryset`](usage/filtering.md#filter_queryset-scope-the-base-queryset).
- **A permission returning `None`, `0` or `""` was treated as *allowed*.** The
  check compared the result with the `False` singleton (`is False`), so only a
  literal `False` denied: `return user and user.is_staff` — the single most
  idiomatic way to write it — returns `None` for an anonymous caller and
  granted every action, reads and writes alike. Any falsy value now denies.
  See [Permissions › Writing a custom permission](usage/permissions.md#writing-a-custom-permission).
- **`only_fields` / `exclude_fields` were silently dropped, keeping a sensitive
  column exposed.** When a `DjangoObjectType` was already registered for the
  model, the `DjangoModelType` reused that output type and discarded its own
  projection without a word (the existing warning only fired for custom
  fields), so `exclude_fields = ("secret",)` built a schema that still served
  `secret` — defeating the control this library documents as *the* way to keep
  a column out. Declaring `only_fields` / `include_fields` / `exclude_fields`
  in that situation now raises `ImproperlyConfigured` at class definition,
  naming the option, the model and the type that registered the output type.
  This **fails the build for a schema that builds today**, deliberately: a
  warning is filterable and would leave the leak live in production, and the
  only configurations affected are the ones already leaking. Move the
  projection to the registered `DjangoObjectType`, or drop the option. See
  [Types › Custom output fields](usage/types.md#custom-output-fields).
- **`DjangoObjectType.get_node` ignored `get_queryset`.** The sibling of the
  item above on the plain-type hierarchy: it resolved its row on the bare
  manager instead of the documented scoping choke point every other row-serving
  path uses, so a caller passing a primary key straight to it got back exactly
  the rows the scope exists to hide. It now runs through `get_queryset`, and an
  excluded row is reported as missing.
- **A nested reverse `OneToOneField` child could be stolen from its owner.** The
  ownership guard on the nested-write path only tested the reverse-FK kind, so
  updating your own parent row with `{id: <yours>, profile: {id: <theirs>, ...}}`
  silently re-pointed another tenant's one-to-one child at you and returned
  `ok: true` — while the same payload on a reverse FK was correctly rejected.
  The guard now covers both reverse kinds with the identical error, so the two
  paths are indistinguishable to a client. Forward FK/O2O and M2M children are
  unaffected: those rows are not owned by the parent, so no ownership check
  applies. See [Mutations](usage/mutations.md#how-nested-writes-work).
- **Setting `root_value` silently disabled every private field.**
  `AuthenticatedFieldsMiddleware` used "the root value is not `None`" as its
  proxy for "this is a nested field", but `root_value` is a public seam (a
  `GraphQLView` kwarg, a class attribute and an overridable `get_root_value()`).
  Any view configured with one served every protected field to anonymous
  callers, and the gate was skipped on each delivered subscription event too —
  the event payload *is* the root value there. The top level is now read from
  the resolve path, which is also correct for a field reached through an inline
  fragment and for one nested inside a list element; an unreadable path is
  treated as top level, so the gate fails closed. See
  [Security](usage/security.md#field-level-authentication).
- **A deactivated superuser could still introspect the schema.** The
  `INTROSPECTION_ALLOW_SUPERUSER` bypass tested `is_superuser` alone, unlike
  every sibling superuser check in the library, so an `is_active=False` account
  kept full `__schema` access on backends that do not run Django's
  `user_can_authenticate` (token / JWT). The bypass now requires an **active**
  superuser. See [Security](usage/security.md#disable-introspection).
- **Row-level scoping leaked through a parent relation.** A
  `DjangoFilterListField` mounted on a parent type read the rows straight off
  the relation accessor, a shortcut that skipped the node type's
  `get_queryset`. A type that hid rows correctly at the top level exposed all of
  them when reached through the parent — `{ authors { createdPosts { title } } }`
  returned the rows `{ posts { title } }` withheld. The hook is now applied on
  that path too, from a single shared choke point; it also rejects a hook that
  returns a non-`QuerySet` instead of quietly serving unscoped rows. Types that
  declare no scope keep the prefetch cache and the single query; a scoped type
  costs one query per parent on that field. Auto-expanded nested lists
  (`DjangoNestedListObjectField`) remain the documented boundary. See
  [Types](usage/types.md#custom-queryset-per-request-filtering).
- **A misspelled `DJANGO_GRAPHEX` key was dropped without a signal.** An unknown
  key never reaches the reader, so the setting it was meant to configure keeps
  its default: `"MAX_PAGE_SIZ": 10` left `MAX_PAGE_SIZE` at `None` (no page-size
  cap) and `"CACHE_ACTIV": True` left the cache off, with nothing reported by
  `manage.py check`. A Django system check (`django_graphex.W001`,
  `Tags.compatibility`, registered from the app config) now compares your keys
  against the known settings and names the closest match. It is a **warning**,
  never an exception, so an app that starts today keeps starting. See
  [Settings](usage/settings.md#typos-in-the-django_graphex-dict).
- **The playground's "private" note subscription had no gate on the type.**
  `examples/playground` documented `noteSubscription` as auth-gated, but the
  only thing denying an anonymous subscriber was the schema-root wiring:
  `"subscribe"` is a READ action, so `IsAuthenticatedOrReadOnly` allowed it, and
  `subscription_scope` returned `None` — no scope, i.e. **every** user's notes —
  for a caller with no user. Copied into a project that does not mount
  `AuthenticatedFieldsMiddleware`, the type leaked the whole stream.
  `NoteModelType` now denies the anonymous `subscribe` in `authorize` (before
  any Channels group is joined) and fails closed in `subscription_scope`. See
  [Subscriptions](usage/subscriptions.md#authorization-and-row-scoping).
- **A negative page size bought budget for a sibling field, bypassing
  `MAX_QUERY_COST`.** The cost estimator used a list's page size as its
  multiplier verbatim, so `limit: -1000` multiplied that subtree by a negative
  number and *subtracted* from the operation total: a query rejected on its own
  (`requestedCost 1001` against a budget of `50`) sailed through with one extra
  aliased field whose limit was negative, and the expensive sibling executed in
  full. Page sizes are now clamped to `0` before the `MAX_PAGE_SIZE` cap, so a
  field can only ever add cost. See
  [Query limits › Query cost analysis](usage/query-limits.md#query-cost-analysis).
- **A variable default declared in the document defeated `MAX_QUERY_COST`.**
  Variables are not bound during validation, so the enforcing rule fell back to
  the operation's own `$n: Int = 1` default — a value written by the same client
  that then sends `{"n": 1000}` at execution time. The query executed, and with
  `EXPOSE_QUERY_COST` the response even reported the real
  `requestedCost` over its `maxCost`. The rule no longer reads document
  defaults: a variabled page size is costed at `MAX_PAGE_SIZE` (else
  `DEFAULT_PAGE_SIZE` / `DEFAULT_LIST_MULTIPLIER`), the same conservative
  fallback an unknown variable already used. The reporting path, which does
  receive the request's real variables, is unchanged. See
  [Query limits › Query cost analysis](usage/query-limits.md#query-cost-analysis).
- **A customized `perms_map` was ignored for subscriptions.**
  `DjangoModelPermissions.has_subscribe_permission` resolved a forwarded
  subscribe action against the library's hardcoded permission table instead of
  the class's own `perms_map`, and the generated subscription always forwards
  one. A subclass tightening the `subscribe` row (`"subscribe":
  ("{app_label}.stream_{model_name}",)`) was silently not enforced — a user
  without that codename could still subscribe — and a loosened row was silently
  denied. Both halves of the composite check now resolve through
  `get_required_permissions`, so the required codenames are the union of the
  `subscribe` row and the row the action maps to. The default mapping is
  unchanged: `view` plus the action's write verb. See
  [Permissions › Customizing the codenames](usage/permissions.md#customizing-the-codenames).
- **A per-request `validation_rules=` could be skipped entirely.** The
  validation cache keyed its verdicts on `id(rules)`, and an address is unique
  only while the object is alive: once a rules tuple built for one request was
  freed, CPython handed the same address to the next one, and the *previous*
  rule set's verdict was replayed — a stricter rule set silently never ran. The
  key is now derived from the rules themselves (their dotted names, in order).
  Views using the shipped class-attribute tuple were never affected.
- **`extensions.cost` was a schema-existence oracle.** With
  `EXPOSE_QUERY_COST`, the cost payload was computed against the FULL schema and
  attached even to a failed validation — so under
  `PERMISSION_SCOPED_SCHEMA` a caller could tell a field pruned out of their
  schema (`requestedCost: 1`) from one that does not exist (`requestedCost: 0`),
  although both answer with the same `Cannot query field` error. That undoes the
  point of the pruned schema. The cost is now computed against the schema the
  request is actually served, and is not attached to a response that carries
  errors and no data. See
  [Query limits › Query cost analysis](usage/query-limits.md#query-cost-analysis).
- **A nested forward FK or M2M payload could rewrite any row of the related
  table.** Declaring `nested_fields = {"category": Category}` was read by the
  writer as *clients may edit any row of the Category table*: naming a pk in the
  nested payload updated that row, whatever it was. The ownership guard did not
  apply (a forward or M2M target is not owned by the parent) and no scope did
  either — a shared lookup row belongs to nobody, so nothing hid it. Updating
  your own document with `{ id: <yours>, category: { id: <any pk>, name: "x" } }`
  returned `ok: true` and renamed a category every tenant reads, while the same
  payload on a reverse FK was correctly rejected. A pk the parent is **not
  already attached to** is now a **link**: the row is set on the parent (or
  `.add()`-ed) and the payload's other fields are ignored. The row the parent is
  already attached to is still updated in place, so the documented use —
  *change the category attached to this document* — is unchanged, as is
  attaching an existing row. See
  [Mutations](usage/mutations.md#how-nested-writes-work).
- **`DjangoModelMutation` had no row-scoping hook at all.** Its sibling
  `DjangoModelType` resolves `update` and `delete` through
  `get_queryset` → `filter_queryset`; the mutation host went straight to the
  bare model and had no such hook to override, so a `filter_queryset` written on
  it — spelled exactly as the documented one, with no error, no warning — was
  never called and every row stayed writable by any caller. Both hooks now exist
  on `DjangoModelMutation` with the same names and signatures, and its `update`
  and `delete` resolve through them. Authorization stays asymmetric and is now
  documented as such: `permission_classes` / `authorize` remain
  `DjangoModelType`-only. See
  [Mutations › Row scoping](usage/mutations.md#row-scoping-get_queryset-filter_queryset).
- **A multi-table-inheritance child could not be put in a schema at all.** The
  native compilers walked `model._meta.get_fields(include_parents=False)` —
  correct for an abstract base, which copies its columns onto the child, and
  wrong for multi-table inheritance, where everything inherited lives in the
  parent's table. An inherited reverse relation was therefore still listed on
  the type but had no compiled counterpart, and the schema build died with
  `RestaurantType fields cannot be resolved. Cannot convert None to a
  graphql-core type` — an error naming nothing that would let you find the
  cause. The field walk in `types.py` now goes through one helper that
  enumerates parents too, so an inherited reverse relation renders as its usual
  `<Model>ListType` container. Models that do not use multi-table inheritance
  are provably untouched (`include_parents` is a no-op for abstract and proxy
  inheritance). The output compiler walks parents too, so the inherited
  **columns** render as well — a multi-table child used to reach the schema
  without so much as an `id`, because every column it inherits (its primary key
  included) lives on the parent. The implicit `<parent>_ptr` link is hidden: the
  child now exposes each inherited column directly, so the link would only offer
  a redundant hop back to a copy of the same row. See
  [Types › Model inheritance](usage/types.md#model-inheritance).
- **`editable=False` relations were accepted in mutation input and silently
  dropped.** The scalar path already honoured `field.editable`, but the
  relation path did not, so a server-managed `ForeignKey` / `OneToOneField` /
  `ManyToManyField` (`created_by`, `tenant`, anything a custom `save()` owns)
  advertised itself as writable, returned `ok: true`, and wrote nothing. Such
  relations are now excluded from the create and update inputs. The guard is
  restricted to concrete fields on purpose: Django hardcodes `editable = False`
  on every reverse relation object, so applying it there would have deleted the
  reverse-relation injection wholesale. The validation-model layer honours
  `editable` on many-to-many too, so a non-editable `ManyToManyField` no longer
  leaks back in as a raw primary-key list.
- **A populated `BinaryField` always read as `null`.** The output compiler
  mapped it to a bare `String` with no resolver, so the `bytes` the column
  yields reached graphql-core's string serializer, which cannot represent them.
  It now resolves through the same shape the `DurationField` precedent uses, and
  delivers the column as **base64** — unconditionally, matching what the
  subscription payload encoder already sends for the same field, so a client is
  never left guessing whether it received text or base64.
- **`DjangoModelType`'s generated list container took the name the docs teach
  you to use.** The container was minted as `<Model>ListType` — the exact name
  the guides give your own `DjangoListObjectType` — so declaring both over one
  model put two different types with one name into a schema and the build
  failed with `Schema must contain uniquely named types`. It is now
  `<Model>ListGenericType`, matching the `Generic` name-space the same type
  already mints its node (`<Model>GenericType`) and inputs
  (`<Model>CreateGenericType`) into. **This is wire-visible**: update any
  client document that spells the container's type name out. Reusing a
  registered container instead was rejected — a `DjangoModelType` carries its
  own `pagination` / `results_field_name` / projection, which a container built
  from someone else's `Meta` would silently discard.
- **A `DjangoModelType` mutation could not be mixed into a forked schema.** The
  generated field stamped only `gdx_required_perms`, while the compiler keys
  its forked-schema payload re-compile off `extensions["gdx_mutation_source"]`
  — the key `DjangoModelMutation` has always stamped. Without it the field
  opted out of the re-fork and every schema built with `registries=` shared the
  payload instance pinned at class-definition time. The field now records its
  source class, so a forked schema compiles its own payload; args, resolver,
  permissions and field shape are unchanged.

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
