# SPEC — C: permission classes on `DjangoSerializerType`

**Status:** APPROVED — implementing in `pre-v2`.
**Scope:** new `graphene_django_extras/permissions.py`, `types.py`, package
exports, tests, docs.
**Date:** 2026-06-07
**Origin:** downstream `ISNDjangoSerializerType` permission layer +
`BaseISNPermission` classes. Piece **C** of the SerializerType work
(A, B done → C → D).

---

## 1. Problem / Goals

`DjangoSerializerType` has no authorization layer: every generated
create/update/delete/retrieve/list runs for anyone. The downstream project added
a DRF-style permission system.

**Goals**
- **G1** — `permission_classes` on a `DjangoSerializerType`, checked **per action**
  (`create` / `update` / `delete` / `retrieve` / `list`) before the operation runs.
- **G2** — A generic `BasePermission` + ready-made permission classes
  (`AllowAny`, `IsAuthenticated`, `IsAdmin`, `IsAuthenticatedOrReadOnly`,
  `IsAdminOrReadOnly`).
- **G3** — Backward compatible: no `permission_classes` ⇒ everything allowed.

### Non-Goals
- The app-specific Django-`has_perm` mapping (`app_label.action_model`) — shipped
  only as a documented example, not a built-in class.
- A "skip checks in DEBUG" setting (`CHECK_GRAPHQL_PERMISSIONS_ON_DEBUG`): the
  library checks always; the `authorize` hook is overridable for dev shortcuts.

## 2. Design

### 2.1 Permission classes (`permissions.py`)
```python
class BasePermission:
    """Allow-all base. Override `has_permission`, or a per-action method."""
    def has_permission(self, info, action, model, **kwargs):
        return True
    # per-action methods delegate to has_permission by default:
    def has_create_permission(self, info, model, **kwargs):
        return self.has_permission(info, "create", model, **kwargs)
    def has_update_permission(self, info, model, **kwargs): ...
    def has_delete_permission(self, info, model, **kwargs): ...
    def has_retrieve_permission(self, info, model, **kwargs): ...
    def has_list_permission(self, info, model, **kwargs): ...
```
Helpers + ready-mades:
```python
def _user(info): return getattr(getattr(info, "context", None), "user", None)
def _is_authenticated(info):
    u = _user(info); return bool(u and u.is_authenticated)
def _is_admin(info):
    u = _user(info); return bool(u and u.is_active and u.is_staff and u.is_superuser)

class AllowAny(BasePermission): pass

class IsAuthenticated(BasePermission):
    def has_permission(self, info, action, model, **kwargs):
        return _is_authenticated(info)

class IsAdmin(BasePermission):
    def has_permission(self, info, action, model, **kwargs):
        return _is_admin(info)

class IsAuthenticatedOrReadOnly(BasePermission):
    def has_permission(self, info, action, model, **kwargs):
        return True if action in ("retrieve", "list") else _is_authenticated(info)

class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, info, action, model, **kwargs):
        return True if action in ("retrieve", "list") else _is_admin(info)
```
`**kwargs` carries `data=` for create/update (so a permission can inspect input).

### 2.2 `DjangoSerializerType` integration (`types.py`)
```python
class DjangoSerializerType(ObjectType):
    permission_classes = ()      # plain class attribute; override per type

    @classmethod
    def get_permissions(cls):
        return [p() for p in cls.permission_classes]

    @classmethod
    def check_permissions(cls, info, action, **kwargs):
        model = cls._meta.model
        method_name = "has_{}_permission".format(action)
        for permission in cls.get_permissions():
            if getattr(permission, method_name)(info, model, **kwargs) is False:
                raise GraphQLError(
                    "You do not have permission to perform this action.",
                    extensions={"code": "PERMISSION_DENIED", "status_code": 403},
                )

    @classmethod
    def authorize(cls, info, action, **kwargs):
        """Pre-operation hook (permissions). Override for dev shortcuts, etc."""
        cls.check_permissions(info, action, **kwargs)
```
Each CRUD classmethod calls `cls.authorize(info, "<action>", data=<input or kwargs>)`
as its first statement:
- `create` → `cls.authorize(info, "create", data=data)`
- `update` → `cls.authorize(info, "update", data=data)`
- `delete` → `cls.authorize(info, "delete", data=kwargs)`
- `retrieve` → `cls.authorize(info, "retrieve")`
- `list` → `cls.authorize(info, "list")`

`permission_classes = ()` (default) ⇒ `get_permissions()` empty ⇒ no checks ⇒
unchanged behavior.

### 2.3 Exports
`permissions.py` classes are exported from `graphene_django_extras`.

## 3. Acceptance Criteria
- **AC1** No `permission_classes` ⇒ all five actions run for an anonymous user
  (unchanged). [G3]
- **AC2** `permission_classes = [IsAuthenticated]` ⇒ anonymous is denied on
  retrieve/list/create/update/delete; an authenticated user is allowed. [G1,G2]
- **AC3** `permission_classes = [IsAdminOrReadOnly]` ⇒ anonymous may retrieve/list
  but is denied create/update/delete; an admin may do all. [G1,G2]
- **AC4** A denial raises a `GraphQLError` with `extensions.code ==
  "PERMISSION_DENIED"` (surfaced in `result.errors`); the operation does not run.
- **AC5** A custom `BasePermission` subclass overriding a single
  `has_<action>_permission` is honored. [G1]
- **AC6** All permission classes import from `graphene_django_extras`. Full suite
  green; base channels-free; lint + `mkdocs --strict` green.

## 4. Test Plan (`tests/test_permissions.py`)
Reuse a `DjangoSerializerType` (the `HookModel`-based `HookType`) via a schema with
query + mutation, `monkeypatch`-ing `permission_classes` per test, and executing
with `context` carrying `AnonymousUser` / a regular user / an admin
(`is_active/is_staff/is_superuser`):
- AC1: no classes → anonymous list/retrieve/create all succeed.
- AC2: `IsAuthenticated` → anonymous denied (errors, `PERMISSION_DENIED`), authed
  allowed; check list, retrieve and create.
- AC3: `IsAdminOrReadOnly` → anonymous list ok, anonymous create denied, admin
  create ok.
- AC5: a custom class denying only `create` is honored.
- Unit: the ready-made classes return the expected booleans for fake
  anon/authed/admin `info` objects.

## 5. Documentation
New `docs/usage/permissions.md` (+ nav): `permission_classes`, the per-action
model, the ready-made classes, writing a custom `BasePermission`
(`has_permission` or per-action), the `PERMISSION_DENIED` error, and the
`authorize` override (e.g. to skip checks in local dev). Include the downstream
Django-`has_perm` mapping as the custom example. Cross-link from `types.md`.

## 6. Definition of Done
1. SPEC approved. 2. `permissions.py` + `DjangoSerializerType` integration +
exports per §2. 3. §3 ACs green via §4; full suite green; base channels-free;
lint + `mkdocs --strict` green. 4. Docs added. 5. Committed and pushed to
`pre-v2`.
