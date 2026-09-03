# Upgrade Guide: 2.x → 3.0

`django-graphex` 3.0 is a **security release**. The API you write is the 2.x
API — there is no port, no codemod, and no rewrite. What changed is what the
library **refuses**.

Almost every refusal closes the same hole: a schema that *said* it hid a column
and then answered questions about it anyway. If your types never did that, most
of this page will not apply to you.

> **Coming from 1.x?** Do [that upgrade](UPGRADE-2.0.md) first. This page
> assumes you are already running 2.x.

Every message quoted here was produced by running the code on 3.0.0 and
compared against the same code on 2.2.0. Where a message is quoted, it is
quoted verbatim so you can string-match it against your own console.

---

## Start here: the five-minute triage

Three of these changes **do not fail your build**. They wait for a request.
Run these greps before you deploy — they take longer to read about than to do.

```bash
# 1. A limit written as 0 to mean "off". It now raises on every request.
rg -n 'MAX_QUERY_DEPTH|MAX_QUERY_COST' --glob '*settings*'

# 2. The permission cache, whose 0 changed meaning in the OPPOSITE direction.
rg -n 'PERMISSION_SCHEMA_CACHE_MAXSIZE' --glob '*settings*'

# 3. Clients that POST anything other than application/json. They now get 403.
rg -n 'x-www-form-urlencoded|multipart/form-data' --glob '*.py' --glob '*.js' --glob '*.ts'

# 4. A subscribe gate that was never running. It runs now, and it denies.
rg -n 'async def authorize_subscription'

# 5. A view that overrides format_error with the 2.x signature.
rg -n 'def format_error'
```

If all five come back empty and your schema builds, you are done.

## At a glance

| When you find out | What | Effort |
|---|---|---|
| **Schema build** | `filter_fields` naming a column, relation or lookup the type does not publish | edit the `Meta` — the message names the entry and the fix |
| **Import** | A container projection that contradicts its node's | move it to the node |
| **Import** | `DjangoModelMutation` `Meta` typos, `permission_classes`, bad `nested_fields` | the message lists what would have worked |
| **First request** | `MAX_QUERY_DEPTH` / `MAX_QUERY_COST` set to `0` | write `None` |
| **First request** | `PERMISSION_SCHEMA_CACHE_MAXSIZE = 0` — now honoured, was ignored | write `None` |
| **Your clients** | Non-JSON POSTs get **403** | one header, or opt out |
| **Your clients** | `ordering:` by a hidden column gets refused | publish it or stop sorting by it |
| **Your clients** | The 51st subscription on one socket is refused | raise or disable the cap |
| **Your clients** | SSE streams open with a `:` comment chunk | skip comment lines |
| **Your code** | An `async def` subscribe gate starts denying | **audit, do not patch** |
| **Your codegen** | Two SDL type names can change | regenerate |

---

# Part 1 — The build stops

These are the loud ones, and they are the bulk of the release. Every message
names the offending entry, the type that owns the projection, and the remedy.

## 1.1 `filter_fields` naming a projected-away column

```python
class AuthorType(DjangoObjectType):
    class Meta:
        model = Author
        only_fields = ("id", "name")
        filter_fields = {"name": ("exact",), "bio": ("icontains",)}  # <- bio is hidden
```

```
ImproperlyConfigured: AuthorType.Meta.filter_fields entry 'bio' names 'bio',
which AuthorType does not publish -- Meta.only_fields / Meta.exclude_fields
removed it, or a declared attribute publishes the name over a different value.
A projection is a security boundary, not an output shape: a column a type hides
must not be readable, orderable or filterable through it, and one filter request
returns the hidden value exactly. Publish 'bio' on AuthorType, or drop the entry.
```

**Why it matters.** In 2.2.0 this built, and the result was a schema that lied:

```
2.2.0  AuthorType fields  : ['id', 'name']            # bio is "hidden"
2.2.0  AuthorFilterInput  : ['and', 'bio', 'name', ...]  # ...and filterable
```

A single `filter: {bio: {exact: "..."}}` returns the hidden value exactly.

**Two fixes, both verified:**

```python
# A — keep the column hidden, drop the filter:
        filter_fields = {"name": ("exact",)}

# B — keep the filter, republish the column:
        only_fields = ("id", "name")
        include_fields = ("bio",)
        filter_fields = {"name": ("exact",), "bio": ("icontains",)}
```

!!! tip "The message names two classes, and they are usually different"

    When the projection is on the **node** and `filter_fields` is on the
    **container**, the message names both:

    ```
    AuthorListType.Meta.filter_fields entry 'bio' names 'bio',
    which AuthorType does not publish -- ...
    ```

    The name before `.Meta.filter_fields` is **where the entry lives**. The name
    before `does not publish` is **where the projection lives**. Edit whichever
    one you meant.

## 1.2 `filter_fields` traversing a masked or scoped relation

A relation you publish over a resolver of your own is a **mask**: the library
cannot see what your resolver returns, so it cannot let a filter join through
it. This covers `Field(T)` + `resolve_<name>`, `Field(T, resolver=...)`, and
**both arms of the relation scoping hatch**.

```python
class AuthorType(DjangoObjectType):
    posts = DjangoFilterListField(PostType)      # the to-many hatch

    class Meta:
        model = Author
        filter_fields = {"posts__title": ("icontains",)}   # <- joins through it
```

```
ImproperlyConfigured: AuthorType.Meta.filter_fields entry 'posts__title'
traverses 'posts', which AuthorType does not publish as a relation -- ...
Publish 'posts' on AuthorType -- registering a DjangoObjectType for Post if
that is what is missing -- or drop the entry.
```

**Fix:** drop the traversing entry. The relation itself is untouched — still
selectable, still scoped by its own `get_queryset`. What goes is the ORM join
through it.

!!! warning "Read the *middle* clause of that message first"

    The refusal lists three possible causes and the last one — *"the output
    compiler dropped it because Post has no registered DjangoObjectType"* — is
    usually **not** your problem. It is a disjunction, not a diagnosis.

    If you have a `resolve_<relation>` on the type, the cause is the middle
    clause. Do not go hunting for a missing registration that is not missing.

The **relation-direct** spelling (`{"author": ("exact",)}` rather than
`{"author__name": ...}`) gets the *column* message from §1.1, not this one —
worth knowing if you are matching on the text.

## 1.3 `pk`, and lookups spelled into the key

Both of these compiled to **nothing** in 2.2.0 and were silently accepted, so a
filter you thought you had simply did not exist.

```python
filter_fields = {"pk": ("exact",)}              # the pk alias
filter_fields = {"name__icontains": ("exact",)} # lookup in the key
```

```
ImproperlyConfigured: NodeType.Meta.filter_fields entry 'pk' names 'pk', which
is not a field on Author -- its primary key is spelled 'id', and a lookup
belongs in the entry's VALUE, not in its key. The entry compiled to nothing, so
it was accepted and ignored; declare the real field name, or drop the entry.
```

```python
filter_fields = {"id": ("exact",)}          # spell the real pk field
filter_fields = {"name": ("icontains",)}    # key = path, value = lookups
```

## 1.4 A container projection that contradicts its node

This one fires at **class-definition time** — on import, before any schema is
built.

```python
class AuthorType(DjangoObjectType):
    class Meta:
        model = Author

class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author
        only_fields = ("id", "name")   # silently dropped in 2.2.0
```

```
ImproperlyConfigured: AuthorListType.Meta.only_fields cannot be honored: the
node type for Author is reused from AuthorType, which was built from its own
Meta, so the projection would be silently dropped and any field it hides would
stay exposed. Declare only_fields on AuthorType instead, or remove the option.
```

**Fix: align, do not delete.** Move the projection to the node.

!!! success "Restating the node's projection is still accepted"

    You only have to touch the container when honouring it would publish a
    **different column set** than the node already publishes. All of these
    build fine:

    ```python
    # identical only_fields on both                       -> OK
    # identical exclude_fields on both                    -> OK
    # node only_fields=("id","name") + container
    #      exclude_fields=(everything else)               -> OK, same set
    # unprojected node + container include_fields=("bio",) -> OK, no-op
    ```

    The test is on the resulting **column set**, not on the spelling.

!!! danger "The near-miss that will bite you"

    This looks like a restatement and is not:

    ```python
    class AuthorType(DjangoObjectType):
        class Meta:
            model = Author
            only_fields = ("id", "name")

    class AuthorListType(DjangoListObjectType):
        class Meta:
            model = Author
            exclude_fields = ("bio",)      # <- REFUSED
    ```

    `only_fields = ("id", "name")` also drops every **relation**.
    `exclude_fields = ("bio",)` does not. Different sets, so it is refused.

## 1.5 `DjangoModelMutation` `Meta` options that never worked

Three shapes that 2.2.0 accepted and ignored now refuse to define the class.

| You wrote | What 2.2.0 did | Message |
|---|---|---|
| `exclude_field = (...)` (typo) | left the column **writable** | `unknown Meta option(s) ['exclude_field']. Check for typos` |
| `Meta.queryset = ...` | scoped **nothing** | same unknown-option refusal |
| `permission_classes = (...)` | ran **no checks** | `permission_classes is not honored by DjangoModelMutation; this host reads it nowhere` |
| `nested_fields = {"postz": ...}` | silently skipped the key | `name no relation on Author. The names that would have worked: author_profile, coauthored_posts, posts, scalar_kinds` |

The `nested_fields` message lists every accessor that would have worked, so the
fix is a copy-paste out of the error.

!!! danger "`permission_classes` on a mutation was doing nothing"

    Deleting the attribute makes the import succeed and leaves you with **no
    permission check at all** — which is what 2.2.0 was silently doing. Move it
    to a host that runs it:

    ```python
    class AuthorWriteType(DjangoModelType):
        permission_classes = (IsStaff,)

        class Meta:
            model = Author
    ```

---

# Part 2 — Nothing fails until a request arrives

The two changes on this page most likely to reach production.

## 2.1 `MAX_QUERY_DEPTH` / `MAX_QUERY_COST` written as `0`

In 2.x, `0` silently switched the guard **off**. In 3.0 it is refused — and the
refusal fires when the setting is **read**, on the first request that reaches
validation. **The schema builds. `manage.py check` stays green.**

```python
# settings.py — HTTP 200 in 2.2.0
DJANGO_GRAPHEX = {"MAX_QUERY_DEPTH": 0}     # meant "no limit"
```

```
ImproperlyConfigured: DJANGO_GRAPHEX['MAX_QUERY_DEPTH'] = 0 is below the
minimum of 1, so it cannot mean what it says. Use None to disable the global
depth guard.
```

```python
DJANGO_GRAPHEX = {"MAX_QUERY_DEPTH": None}   # None is the ONLY off switch
```

!!! warning "The environment-variable trap"

    This is how most projects end up with a `0` without ever typing one:

    ```python
    "MAX_QUERY_DEPTH": int(os.environ.get("DEPTH", 0)),   # unset -> 0 -> raises
    "MAX_QUERY_DEPTH": int(os.environ.get("DEPTH", 0)) or None,   # fixed
    ```

## 2.2 `PERMISSION_SCHEMA_CACHE_MAXSIZE = 0` changed meaning — the other way

Same settings table, **opposite direction**. Do not assume every `0` tightened.

| Value | 2.2.0 | 3.0.0 |
|---|---|---|
| `0` | ignored — ran the 64-entry default cache | **honoured** — caches nothing, rebuilds the pruned schema on every request |
| `-1` | read as `-1`, no complaint | raises on every read |
| `None` | default | default (64) |

If you wrote `0` meaning "leave it alone", write `None`. If you genuinely want
no caching, `0` now does that — budget for a pruned schema rebuild per request
under `PERMISSION_SCOPED_SCHEMA`.

---

# Part 3 — Your clients start getting refused

## 3.1 Non-JSON POSTs now need a header (`REQUIRE_CSRF_HEADER`)

**This setting is new and ships ON.** Every POST of
`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`, or
**no `Content-Type` at all** now needs an `X-Requested-With` header. That
includes multipart file uploads and form-encoded SSE subscribes.

`application/json` is never affected.

```
403  {"errors": [{"message": "This content type requires the X-Requested-With
header. A browser can POST it cross-site without a CORS preflight, so the header
is what proves the request was not forged. Send 'X-Requested-With: XMLHttpRequest',
post 'application/json' instead, or set REQUIRE_CSRF_HEADER=False to opt out."}]}
```

```bash
# Preferred — one header, no settings change, no security loss:
curl -X POST http://host/graphql/ \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'X-Requested-With: XMLHttpRequest' \
  --data-urlencode 'query={ books { id } }'
```

```python
# Last resort. Restores 2.x exactly, and reopens the cross-site POST hole:
DJANGO_GRAPHEX = {"REQUIRE_CSRF_HEADER": False}
```

## 3.2 `ordering:` by a column the type does not publish

The projection is now a boundary on the **ordering** axis too, because ranking
rows by a hidden column recovers it one comparison at a time. All of these
answer `Invalid ordering field: '<name>'.`:

| Shape | What is refused |
|---|---|
| `only_fields` / `exclude_fields` hides the column | `ordering: "bio"` |
| The column is re-declared over a resolver (`title = CharField()` + `resolve_title`) | `ordering: "title"` — **the name is still in the SDL, so nothing warns you** |
| The type hides its own natural primary key (a slug, a code) | `ordering: "slug"` **and** `ordering: "pk"` |
| A forward FK whose **target** type hides its primary key | `ordering: "authorId"` — decided by a type one hop away |
| A relation behind the to-one scoping hatch | `ordering: "authorId"` |

For the hatch there is **no way to keep both**: either drop the declaration and
let the relation auto-expand (losing the per-request scoping), or drop the
ordering term from your documents.

!!! danger "Cursor pagination has no operator exemption"

    `LimitOffset` and `Page` paginators may still be *configured* with an
    `ordering=` naming a hidden column — that is your deployment choice, applied
    identically to every request. **`CursorGraphqlPagination` may not**, because
    `pageInfo.startCursor` is base64 of `cursor:<ordering value>\x1f<pk>` and
    therefore prints the value back.

    Two shapes fail **every request** to that field, with no client change
    involved and a schema that builds cleanly:

    ```python
    pagination = CursorGraphqlPagination(ordering="bio")   # bio is hidden
    ```
    ```
    Invalid ordering field: 'bio'.
    ```

    ```python
    # a node type whose primary key is projected away, cursor-paginated
    ```
    ```
    Cursor pagination is unavailable on a type that hides its primary key:
    every cursor carries the key as its tiebreak. Expose the primary key or
    use offset/page pagination.
    ```

## 3.3 Subscriptions are capped per socket

`MAX_SUBSCRIPTIONS_PER_CONNECTION` is new and defaults to **50**. The 51st
subscribe on one socket gets an error frame; **the socket and its running
subscriptions survive**.

```json
{"id": "op51", "type": "error", "payload": [{"message":
  "Subscription count exceeds the MAX_SUBSCRIPTIONS_PER_CONNECTION limit of 50.
   Complete an existing subscription on this connection or set
   MAX_SUBSCRIPTIONS_PER_CONNECTION=None to disable the limit."}]}
```

```python
DJANGO_GRAPHEX = {"MAX_SUBSCRIPTIONS_PER_CONNECTION": None}   # 2.x behaviour
```

Do not write `0` — see §2.1 for why a limit of zero is refused.

## 3.4 SSE streams now open with a comment chunk

An idle SSE stream sent **zero bytes** in 2.2.0 until the first broadcast, which
meant a browser's `fetch` never resolved and proxies timed the connection out.
Every stream now opens with `:\n\n` — an SSE comment, which the spec says
clients ignore.

If you hand-rolled an SSE reader that treats the first chunk as a frame, it will
see `:` first:

```python
if chunk.startswith(":"):
    continue
```

The bundled browser client had exactly this bug — it reported "Connection Error"
on a healthy stream — and it is fixed in this release.

## 3.5 Error message strings that changed

Only relevant if a client, log parser or alert rule **string-matches** message
text.

- **`Did you mean 'x'?` is stripped** from unknown-field, unknown-type,
  unknown-argument and coercion errors — but **only** on a deployment that has
  `DisableIntrospectionMiddleware` installed **and** `ALLOW_INTROSPECTION = False`.
  Guessing at schema member names rebuilds the schema an operator believes is
  hidden.
- **The depth-limit refusal names the real operation.** An over-deep mutation
  used to say `for 'query'`; it now says `for 'mutation'`. Match on
  `extensions.code == "QUERY_TOO_DEEP"` instead, which is unchanged.
- **The SSE "cannot select an operation" 400 became two messages**, neither of
  them the old one: `This request carries several operations; name the one to run
  with operationName.` and `This request names operation 'X', which this document
  does not define.`
- **A batch endpoint given non-object entries** answers `400` with
  `Batch entries should be JSON objects, but received 1.` where 2.2.0 crashed
  with a `500`. Relevant if your monitoring alerted on the 5xx, or your client
  retried on it.

---

# Part 4 — Your own code changes behaviour

## 4.1 An `async def` subscribe gate starts denying

**This is the subtlest change in the release, and there is no edit to make.**

In 2.2.0 the wrapper around `authorize_subscription` called your hook and
**discarded the coroutine**. An `async def` gate therefore never ran, and the
subscribe was **granted**. In 3.0 it is awaited, and it denies.

```python
# unchanged code — that is the whole point
class PostSub(Subscription):
    @classmethod
    async def authorize_subscription(cls, info, **kwargs):
        raise GraphQLError("staff only: subscribe denied")
```

```
2.2.0: GRANTED, group joined
3.0.0: {"type": "error", "payload": [{"message": "staff only: subscribe denied"}]}
```

**The action is an audit, not a patch:**

```bash
rg -n 'async def authorize_subscription'
```

For every hit, confirm the denial it encodes is one you actually want enforced —
because until 3.0 it was not. If a gate was written defensively and now refuses
too much, widen the gate. Do not go back to swallowing it.

## 4.2 `format_error` takes the request

`BaseGraphQLView.format_error` is now `format_error(self, error, request=None)`.
A 2.x override **500s on every request that produces a GraphQL error**:

```
TypeError: LegacyView.format_error() takes 1 positional argument but 2 were given
```

```python
class LegacyView(GraphQLView):
    def format_error(self, error, request=None):   # widen the signature
        return {"message": f"OLD:{error}"}
```

Keeping `@staticmethod` also works — you only have to widen the signature.

## 4.3 Subscriptions are measured against the depth and cost guards

Both transports now validate with the same rule tuple the HTTP view uses, so
`MAX_QUERY_DEPTH` and `MAX_QUERY_COST` see subscription documents for the first
time.

**The library's own generated subscriptions can never trip this.** Their event
payload is flat by construction — relations are rendered as IDs — so they
measure depth 1 and cost 1, and neither setting can legally go below 1.

This only affects a **hand-written** subscription with a nested payload:

```
{"type": "error", "payload": [{"message": "Query exceeds the maximum nesting
depth of 2 for 'subscription'.", "extensions": {"code": "QUERY_TOO_DEEP"}}]}
```

Raise the limit, or flatten the payload. There is no per-surface opt-out: both
transports import the same rule tuple, and setting a limit to `None` disables
that guard everywhere, HTTP included.

---

# Part 5 — SDL changes your codegen will see

Two shapes change the schema a client's generated types are built from. Both are
narrow; if neither describes your project, skip this part.

## 5.1 A nested container type can change name

If you have **both** a hand-written `DjangoListObjectType` **and** a write-only
`DjangoModelType` (`model_operations` without `"list"`) for the same model, 3.0
now serves the container you declared, and the auto-minted generic one is gone
from the type map entirely:

```
2.2.0 SDL:  AuthorType.posts : PostListGenericType
3.0.0 SDL:  AuthorType.posts : ZHandWrittenPostList
```

Nothing to change in your schema code — this is 3.0 serving what you meant. But
**regenerate your client types**, and audit any fragment written against the old
name. A persisted-query allowlist will reject documents naming it.

## 5.2 An interface field can disappear under `PERMISSION_SCOPED_SCHEMA`

A hand-mounted interface field is now gated by the **AND** of every mounted
implementor's `view_` permission. A caller holding *some but not all* of them
used to keep the field and now loses it:

```
Cannot query field 'product' on type 'Query'.
```

There is no way to keep the interface field for a partially-permitted caller.
Expose the implementors as their own gated fields and let the client select the
one it is entitled to.

---

# Part 6 — Removals

## 6.1 Four importable names are gone

```python
from django_graphex.utils import get_obj, create_obj                    # ImportError
from django_graphex.converter import assert_valid_name, convert_choice_name  # ImportError
```

```python
# get_obj(app_label, model_name, pk)
from django.apps import apps
from django_graphex.utils import get_Object_or_None      # still exported
obj = get_Object_or_None(apps.get_model(f"{app_label}.{model_name}"), pk=pk)

# create_obj(Model, **data) — plain Django, which is all it ever was
obj = Model(**data); obj.full_clean(); obj.save()

# assert_valid_name — graphql-core ships the public one
from graphql import assert_valid_name      # raises GraphQLError, not AssertionError

# convert_choice_name — NOT a drop-in replacement
from django_graphex.converter import choice_enum_name
name = choice_enum_name(value, label)
```

## 6.2 `CAMELCASE_ERRORS`

The setting had zero consumers and changed nothing. Leaving it in your settings
does not crash — you get a system-check warning:

```
?: (django_graphex.W001) Unknown DJANGO_GRAPHEX setting(s) ['CAMELCASE_ERRORS'].
   They are IGNORED, so the setting they were meant to configure keeps its default.
   HINT: 'CAMELCASE_ERRORS' has no close match — remove it.
```

Delete the key.

---

# One thing that got *less* strict

`DOCUMENT_CACHE_MAXSIZE = None` — the documented "no limit" value for every
sibling bound — made **every request** answer HTTP 400 in 2.2.0:

```
int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
```

3.0 reads `None` as unbounded and the request succeeds. No edit needed. Nobody
can have been running this in production, so it cannot break an upgrade — it is
here because the rest of this page is about settings that tightened, and this
one did the opposite.

---

# What is *not* a breaking change

Three things look like breaks in the diff and are not. If you were about to
change code because of them, don't:

- **Multipart part naming.** 2.2.0 accepted only the snake_case model attribute
  as a part name; 3.0 accepts the camelCase SDL alias **too**. Purely additive.
  A part matching no published field was ignored in both versions.
- **`MAX_REQUEST_BODY_SIZE` on multipart bodies.** 2.2.0 already answered 413
  for an oversized multipart POST, with the byte-identical message. The one
  genuinely new refusal in this area is HTTP **411** for a *chunked* multipart
  body (no `Content-Length`) while the setting is configured — 2.2.0 answered a
  confusing 400 for that shape.
- **The pagination default-ordering and pk-tiebreak rework.** Internal.

---

## If something here is wrong

Every claim on this page was reproduced on 3.0.0 and compared against 2.2.0
before it was written. If your console says something different, that is worth
an issue — a wrong upgrade instruction is worse than a missing one.

[Open an issue](https://github.com/eamigo86/django-graphex/issues) with the
message you got and the `Meta` that produced it.
