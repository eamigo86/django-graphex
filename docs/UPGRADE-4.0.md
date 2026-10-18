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
