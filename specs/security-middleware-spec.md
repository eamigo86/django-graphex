# SPEC — Security: introspection + field-level auth + ExtraGraphQLSchema

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** new `graphene_django_extras/security.py` and
`graphene_django_extras/schema.py`, `settings.py`, package exports, tests, docs.
**Date:** 2026-06-07
**Origin:** ported (de-coupled, bug-fixed, generalized) from two downstream
graphene middlewares. **No `ISN` prefixes / `ISN.schema` imports /
`ISNExceptionHandler` shape / `ISNGraphQLView`.** The downstream
`GraphqlSchemaMiddleware` and `_build_auth_error_extensions` are **not** ported.

---

## 1. Problem / Goals

- **G1 — Disable introspection.** Block `__schema` / `__type` unless allowed. The
  ported version is broken on v2 (`info.operation.operation == "query"` is always
  `False` — it is the `OperationType.QUERY` enum, verified), only guards
  `__schema`, crashes without `context`/`user`, and raises a bespoke exception.
- **G2 — Field-level authentication.** Require an authenticated user on the
  *private* top-level fields, raising `GraphQLError` otherwise. The ported version
  uses `user.is_anonymous()` (Django-1.11 method; a `bool` property on modern
  Django → `TypeError`), and is coupled to an app-specific private-field registry
  and error shape.
- **G3 — Ergonomic registry via `ExtraGraphQLSchema`.** Let developers declare
  what is private **next to the schema** (single source of truth, no settings
  duplication, no naming-convention magic), and have the middleware pick it up
  automatically.

### Non-Goals
- Serving a precomputed schema from a file. JWT specifics / a particular auth
  backend (we use only `request.user` / `user.is_authenticated`).

## 2. Design

### 2.1 Settings (added to `DEFAULTS`)
```python
# Security
"ALLOW_INTROSPECTION": False,            # allow __schema/__type introspection
"INTROSPECTION_ALLOW_SUPERUSER": True,   # superusers bypass the introspection block
"PROTECTED_FIELDS": (),                  # extra top-level field names requiring auth
```
(No `PROTECT_SUBSCRIPTIONS` — see §2.5.)

### 2.2 `DisableIntrospectionMiddleware`  (`security.py`)
Graphene per-resolver middleware:
```python
def resolve(self, next, root, info, **kwargs):
    if info.field_name in ("__schema", "__type") and not self._allowed(info):
        raise GraphQLError("GraphQL introspection is disabled.")
    return next(root, info, **kwargs)
```
`_allowed`: `ALLOW_INTROSPECTION` True → allow; else if
`INTROSPECTION_ALLOW_SUPERUSER` and the (guarded) `context.user.is_superuser`
→ allow; else block. Guards missing `context`/`user`. Blocks both introspection
roots; `__typename` is unaffected.

### 2.3 `AuthenticatedFieldsMiddleware`  (`security.py`)
Graphene per-resolver middleware:
```python
def resolve(self, next, root, info, **kwargs):
    if root is not None:                       # only top-level fields
        return next(root, info, **kwargs)
    if info.field_name not in self.get_protected_fields(info):
        return next(root, info, **kwargs)
    user = getattr(getattr(info, "context", None), "user", None)
    if user is None or not user.is_authenticated:   # modern Django property
        raise GraphQLError(
            "Authentication required.",
            extensions=self.get_error_extensions(info, user),
        )
    return next(root, info, **kwargs)
```

`get_protected_fields(info)` resolution:
1. Registry attached by `ExtraGraphQLSchema` →
   `getattr(info.schema, "_gde_protected_fields", None)`. If present, return it.
2. Fallback (plain `graphene.Schema`): `set(PROTECTED_FIELDS)`.

Nothing is protected unless declared (no implicit subscription protection — §2.5).

`get_error_extensions(info, user)` default → `{"code": "UNAUTHENTICATED",
"status_code": 401}`. Both methods are **override points** (subclass to source
the field set differently or enrich the error, e.g. a JWT failure reason) without
the library taking on that coupling.

Empty everything ⇒ only subscriptions are gated; with no middleware nothing is
gated (all public).

### 2.4 `ExtraGraphQLSchema`  (`schema.py`)
`graphene.Schema` subclass with three optional extra kwargs; it computes the
protected-field registry at build time and attaches it to the underlying
graphql-core schema (verified: `info.schema is schema.graphql_schema`, and a
custom attribute on it is readable from middleware; `info.field_name` is
camelCase, matching `collect_field_names`).

```python
class ExtraGraphQLSchema(graphene.Schema):
    def __init__(self, *args, private_query=None, private_mutation=None,
                 private_subscription=None, **kwargs):
        super().__init__(*args, **kwargs)
        protected = set()
        if private_query:
            protected |= collect_field_names(private_query)
        if private_mutation:
            protected |= collect_field_names(private_mutation)
        if private_subscription:
            protected |= collect_field_names(private_subscription)
        self.graphql_schema._gde_protected_fields = frozenset(protected)

        if (private_query or private_mutation or private_subscription) \
                and not _auth_middleware_configured():
            warnings.warn(
                "ExtraGraphQLSchema received private_query/private_mutation/"
                "private_subscription but AuthenticatedFieldsMiddleware is not in "
                "settings.GRAPHENE['MIDDLEWARE']; private fields will NOT be "
                "protected.",
                RuntimeWarning, stacklevel=2,
            )
```
- `_auth_middleware_configured()` best-effort scans
  `settings.GRAPHENE.get("MIDDLEWARE", [])` for `AuthenticatedFieldsMiddleware`
  (by dotted path / class). Documented limitation: middleware wired only via
  `schema.execute(middleware=…)` or the view is not detected.

### 2.5 Subscriptions
No setting, and **no implicit protection** — `private_subscription` is symmetric
with `private_query` / `private_mutation`:
- `private_subscription=<Type>` → exactly those subscription fields are protected.
  To protect **every** subscription, pass the subscription root itself
  (`private_subscription=RootSubscription`).
- A `subscription` alone (no `private_subscription`) protects nothing.
- plain `graphene.Schema` + middleware → only `PROTECTED_FIELDS` (no
  auto-subscription).

### 2.6 Helpers  (`schema.py`)
- `collect_field_names(*object_types, camelcase=True) -> frozenset`: union of each
  graphene `ObjectType._meta.fields` keys, camelCased (to match `info.field_name`
  under the default `auto_camelcase=True`).
- `DenyAllRegistry(frozenset)`: `__contains__` always returns `True` — a
  fail-closed sentinel for a subclassed `get_protected_fields` (broken-schema ⇒
  everything private), mirroring the downstream pattern.

### 2.7 Exports
`graphene_django_extras/__init__.py`: `DisableIntrospectionMiddleware`,
`AuthenticatedFieldsMiddleware`, `ExtraGraphQLSchema`, `collect_field_names`,
`DenyAllRegistry`.

### 2.8 Usage
```python
# schema.py
schema = ExtraGraphQLSchema(
    query=RootQuery,
    private_query=PrivateRootQuery,           # optional
    mutation=RootMutation,
    private_mutation=PrivateRootMutation,      # optional
    subscription=RootSubscription,
    private_subscription=RootSubscription,     # optional: protect all subscriptions
    directives=all_directives,
)

# settings.py
GRAPHENE = {
    "SCHEMA": "myapp.schema.schema",
    "MIDDLEWARE": [
        "graphene_django_extras.DisableIntrospectionMiddleware",
        "graphene_django_extras.AuthenticatedFieldsMiddleware",
        "graphene_django_extras.ExtraGraphQLDirectiveMiddleware",
    ],
}
GRAPHENE_DJANGO_EXTRAS = {"ALLOW_INTROSPECTION": False}
```

## 3. Acceptance Criteria
- **AC1** `ALLOW_INTROSPECTION=False`, anonymous/non-superuser: `__schema` and
  `__type` error; a normal field still resolves. `True`: introspection resolves.
  Missing `context`/`user` does not crash. [G1]
- **AC2** `INTROSPECTION_ALLOW_SUPERUSER=True`: superuser introspects even with
  `ALLOW_INTROSPECTION=False`; `False`: superuser blocked. [G1]
- **AC3** `ExtraGraphQLSchema(private_query=…, private_mutation=…)`: those
  top-level fields require auth (anonymous → `UNAUTHENTICATED` error, authed →
  data); public fields always resolve; nested fields (root not None) never gated.
  [G2,G3]
- **AC4** Subscriptions are symmetric: `private_subscription=<subset>` protects
  only that subset; a `subscription` alone protects nothing; a plain
  `graphene.Schema` fallback protects only `PROTECTED_FIELDS` (no
  auto-subscription). [G2]
- **AC5** `is_authenticated` read as a property (no `TypeError`). The
  `ExtraGraphQLSchema` warning fires when private_* given but the middleware is
  absent from `GRAPHENE['MIDDLEWARE']`. [G2,G3]
- **AC6** `collect_field_names` returns the camelCased field set;
  `DenyAllRegistry()` makes every field protected. All five names import from
  `graphene_django_extras`. Full suite green; base channels-free; lint +
  `mkdocs --strict` green.

## 4. Test Plan (`tests/test_security.py`)
Self-contained graphene schema(s): public + private query/mutation roots, a
nested object field, and a small subscription root. Drive `schema.execute(...,
middleware=[...], context=<obj with .user>)` using `AnonymousUser`, a real user
and a superuser.
- AC1/AC2: introspection queries under each setting/user combo (incl. a
  `context`-less execution for the guard).
- AC3: protected vs public vs nested fields, anonymous vs authenticated; assert
  the `UNAUTHENTICATED` extension.
- AC4: subscription scenarios (`private_subscription` subset, a `subscription`
  alone protecting nothing, and the plain-schema `PROTECTED_FIELDS`-only fallback)
  via the attached registry / `get_protected_fields`.
- AC5: property read (a fake user object exposing `is_authenticated` as a
  property); `warnings.catch_warnings` asserts the schema warning.
- AC6: `collect_field_names`, `DenyAllRegistry`, import smoke test.
Settings toggled by patching the live `graphql_api_settings` object the modules
reference (same approach as the subscriptions payload tests).

## 5. Documentation
New `docs/usage/security.md` (+ nav): the two middlewares, `ExtraGraphQLSchema`
with `private_query`/`private_mutation`/`private_subscription`, the subscription
convention, `collect_field_names`, `DenyAllRegistry` (fail-closed), the override
points, the settings, and the `GRAPHENE.MIDDLEWARE` wiring — with the behavior
matrix (middleware × private_* × subscriptions).

## 6. Definition of Done
1. SPEC approved.
2. `security.py` + `schema.py` + settings + exports per §2.
3. §3 ACs green via §4 tests; full suite green; base channels-free; lint +
   `mkdocs --strict` green.
4. Docs added.
5. Committed and pushed to `pre-v2`.
