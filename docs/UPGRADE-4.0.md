# Preparing for GraphQL-core 3.3

## 4.0.0 release prepared

The current source checkout and its editable project locks name 4.0.0 and
require `graphql-core>=3.3.0,<3.4`. This is a local release-preparation
state: 4.0.0 is not published, and no wheel, tag, or package release is
attested here. Install and test the checkout explicitly when evaluating
it; ordinary package-manager commands may still fetch the published 3.1.1
line and its older GraphQL-core requirement. Do not infer compatibility from
an installed 3.1.1 distribution's metadata.

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
