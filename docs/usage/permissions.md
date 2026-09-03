# Permissions

`DjangoModelType` supports a permission layer (modeled after DRF's API),
checked **per action** (`create` / `update` / `delete` / `retrieve` / `list`)
before each operation runs.

!!! note "DRF is *not* a dependency"

    "Modeled after DRF" refers only to the **API style** (`permission_classes`,
    `BasePermission`, `has_permission`). Django REST Framework is **not**
    required, imported, or used — there is nothing extra to install. All
    permission classes below are implemented in
    `django_graphex.permissions`.

Set `permission_classes` on the type:

```python
from django_graphex.permissions import IsAuthenticatedOrReadOnly
from django_graphex.types import DjangoModelType

class OrderType(DjangoModelType):
    permission_classes = [IsAuthenticatedOrReadOnly]

    class Meta:
        model = Order
```

With no `permission_classes` (the default) nothing is checked — every operation
runs. A denied action raises a `GraphQLError` and the operation does **not** run:

```json
{
  "errors": [{
    "message": "You do not have permission to perform this action.",
    "extensions": {"code": "PERMISSION_DENIED", "status_code": 403}
  }]
}
```

## Ready-made permissions

| Class | Allows |
|-------|--------|
| `AllowAny` | every action (explicit form of the default) |
| `IsAuthenticated` | only authenticated users |
| `IsAdmin` | only active staff superusers |
| `IsAuthenticatedOrReadOnly` | anyone may `retrieve`/`list`; authenticated users may write |
| `IsAdminOrReadOnly` | anyone may `retrieve`/`list`; admins may write |
| `DjangoModelPermissions` | users holding the matching Django model permission (see below) |

```python
from django_graphex.permissions import AllowAny, IsAuthenticated, IsAdmin, IsAuthenticatedOrReadOnly, IsAdminOrReadOnly, DjangoModelPermissions
```

Multiple classes are combined with **AND** — every class must allow the action.

## Writing a custom permission

Subclass `BasePermission` and override either `has_permission(self, info, action,
model, **kwargs)` (applies to every action) or a single `has_<action>_permission(
self, info, model, **kwargs)`. `info.context` is the request, and `kwargs` carries
`data=` for `create`/`update`. Return a **falsy** value to deny.

```python
from django_graphex.permissions import BasePermission

class IsOwnerOrReadOnly(BasePermission):
    def has_permission(self, info, action, model, **kwargs):
        if action in ("retrieve", "list"):
            return True
        return info.context.user.is_authenticated
```

!!! warning "CRUD permission hooks are synchronous"
    Define `has_permission` and `has_<action>_permission` with `def`, not
    `async def`. If a hook returns any awaitable, django-graphex closes or
    cancels it and raises `ImproperlyConfigured` **before the operation runs**.
    It never applies truthiness to a coroutine and never bridges it with
    `async_to_sync`.

    This differs intentionally from subscription hooks such as
    `authorize_subscription`, whose delivery pipeline explicitly supports both
    synchronous and asynchronous implementations.

!!! warning "Any falsy value denies — you do not have to return `False`"
    The check fails closed on `False`, `None`, `0` and `""` alike, so the
    idiomatic one-liner is safe:

    ```python
    def has_permission(self, info, action, model, **kwargs):
        user = getattr(info.context, "user", None)
        return user and user.is_staff   # -> None for an anonymous caller: DENIED
    ```

    (Fixed in 2.2.0: 2.1.0 and earlier compared the result with the `False`
    singleton, so this exact one-liner granted every action to an anonymous
    caller.)

### `nested_parent`: telling a nested write apart from a direct one

A child written through a parent's `Meta.nested_fields` runs the **child's own**
permission checks, and `kwargs` then carries `nested_parent` — the **parent
model class**. It is absent on the child's own mutation, so a policy can grant a
write only when it arrives through a parent:

```python
class OnlyViaParent(BasePermission):
    def has_create_permission(self, info, model, **kwargs):
        return kwargs.get("nested_parent") is not None
```

A model whose rows only ever make sense inside their owner (comment lines of an
order, addresses of a user) can therefore drop its own `create` root without
losing the nested surface. See
[Nested writes](mutations.md#how-nested-writes-work) for the full
contract, including which paths are gated.

!!! note "Checks with a closed signature never see it"
    Each extra is only passed to a check that can accept it, so an `authorize`
    override or a permission class that spells its arguments out
    (`def authorize(cls, info, action, data=None)`,
    `def has_permission(self, info, action, model, data=None)`) keeps working
    unchanged — it simply never receives `nested_parent`, and therefore treats a
    nested write exactly like a direct one. The narrowing happens at the call
    that lands on *your* method, so the `**kwargs` on the built-in
    `has_<action>_permission` in between does not leak the marker through.
    Accept `**kwargs` to see it.

## `DjangoModelPermissions`

`DjangoModelPermissions` maps each CRUD action to Django's built-in model
permissions (DRF-style) and checks them with `user.has_perms`. Set it on a
`DjangoModelType` like any other permission class:

```python
from django_graphex.permissions import DjangoModelPermissions
from django_graphex.types import DjangoModelType

class OrderType(DjangoModelType):
    permission_classes = [DjangoModelPermissions]

    class Meta:
        model = Order
```

The mapping is **composite**: because a mutation payload returns instance data,
each write action requires **both** its write permission **and** `view`. Read and
observe actions stay view-only:

| Action | Required permission(s) |
|--------|------------------------|
| `create` | `{app_label}.add_{model_name}` **and** `{app_label}.view_{model_name}` |
| `update` | `{app_label}.change_{model_name}` **and** `{app_label}.view_{model_name}` |
| `delete` | `{app_label}.delete_{model_name}` **and** `{app_label}.view_{model_name}` |
| `retrieve` | `{app_label}.view_{model_name}` |
| `list` | `{app_label}.view_{model_name}` |
| `subscribe` | `{app_label}.view_{model_name}` (plus the requested action's row — see below) |

> **Changed in 2.0.0** — write actions (`create` / `update` / `delete`) now also
> require the `view` permission. A user who could previously write with only the
> `add` / `change` / `delete` permission must also be granted `view`. To restore
> the old write-only behavior (e.g. a write-only inbox), override `perms_map` for
> that action with just the write verb (see below).

Notes:

- **Relations are gated by the model they point at.** `permission_classes` runs
  on the CRUD/subscribe entry points of *this* type; it does not run again on a
  nested relation resolver. Reading a related model through a relation field
  (`post { comments { results { text } } }`) is instead gated at the **schema**
  layer: with
  [`PERMISSION_SCOPED_SCHEMA`](permission-scoped-schema.md#relation-traversal-is-covered-too)
  enabled, every generated relation and nested-list field requires the target
  model's `view_{model_name}`, so a caller who cannot query `Comment` directly
  cannot reach it through `Post` either. Without that flag the schema is never
  pruned and a relation stays reachable — enable it if relation traversal must
  be permission-checked.
- **Superusers pass automatically** — Django's `ModelBackend` grants every
  permission to an active superuser.
- **Anonymous users are always denied** (the class is fail-closed).
- **Fail-closed when no model** — the check denies when it has no model context
  to map. That makes it suitable for `DjangoModelType.permission_classes` (where
  a model is always supplied) but **not** for view-level
  `AuthenticatedGraphQLView.permission_classes` (where no model is passed).

### Customizing the codenames

The mapping lives in the `perms_map` class attribute (action → tuple of format
strings resolved against the model's `app_label`/`model_name`). Override it in a
subclass to require different codenames:

```python
from django_graphex.permissions import DjangoModelPermissions

class PublishModelPermissions(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        "create": ("{app_label}.publish_{model_name}",),
    }
```

Because the default is composite, overriding an action with a single write verb
is the escape hatch for a **write-only** flow (e.g. an inbox where a user may
create records but not read them back):

```python
class WriteOnlyInbox(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        # create requires only `add` — the `view` requirement is dropped.
        "create": ("{app_label}.add_{model_name}",),
    }
```

For finer control, override `get_required_permissions(self, action, model)`,
which returns the list of codenames an action requires (or `None` for an unknown
action).

A subscribe that forwards the action it observes (`CREATE` / `UPDATE` /
`DELETE` / `ALL_ACTIONS`, see [Subscriptions](subscriptions.md)) is gated by the
**union** of the `subscribe` row and every write row that action maps to via
`subscribe_actions_map` (`"all_actions"` maps to all three). Both halves go
through `get_required_permissions`, so a customized row applies on this path as
well:

```python
class StreamModelPermissions(DjangoModelPermissions):
    perms_map = {
        **DjangoModelPermissions.perms_map,
        # subscribing needs a dedicated codename instead of plain `view`.
        "subscribe": ("{app_label}.stream_{model_name}",),
    }

# subscribe(action: CREATE) now requires:
#   {app}.stream_{model} + {app}.add_{model} + {app}.view_{model}
```

!!! tip "See the whole permission stack in action"

    `DjangoModelPermissions` is the **runtime** half of a larger model: the same
    composite table also labels the schema so `PERMISSION_SCOPED_SCHEMA` can
    serve each caller a schema pruned to their permissions. The
    [Permission-scoped schema guide](permission-scoped-schema.md) walks a Blog
    API through all three layers with worked examples.

## Customizing the check

Each CRUD operation calls `authorize(cls, info, action, **kwargs)` first, which
runs the permission checks. Override it to customize — for example, to skip checks
in local development:

```python
from django.conf import settings

class OrderType(DjangoModelType):
    permission_classes = [IsAuthenticated]

    class Meta:
        model = Order

    @classmethod
    def authorize(cls, info, action, **kwargs):
        if settings.DEBUG:
            return  # skip checks locally
        super().authorize(info, action, **kwargs)
```

!!! tip "Per-request data scoping vs. permissions"

    Permissions answer *"may this action run at all?"*. To **scope the rows** a
    user can see (row-level filtering), use
    [`filter_queryset`](types.md#custom-queryset-per-request-filtering) instead.
    That scope covers the rows a user can **write** too: `update` and `delete`
    resolve their target through the same hook, and a row outside the scope is
    reported as not found.
