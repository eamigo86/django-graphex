# Permissions

`DjangoModelType` supports a permission layer (modeled after DRF's API),
checked **per action** (`create` / `update` / `delete` / `retrieve` / `list`)
before each operation runs. These permission classes are the library's own — no
external dependency required. Set `permission_classes` on the type:

```python
from django_graphex import DjangoModelType, IsAuthenticatedOrReadOnly

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

```python
from django_graphex import (
    AllowAny, IsAuthenticated, IsAdmin,
    IsAuthenticatedOrReadOnly, IsAdminOrReadOnly,
)
```

Multiple classes are combined with **AND** — every class must allow the action.

## Writing a custom permission

Subclass `BasePermission` and override either `has_permission(self, info, action,
model, **kwargs)` (applies to every action) or a single `has_<action>_permission(
self, info, model, **kwargs)`. `info.context` is the request, and `kwargs` carries
`data=` for `create`/`update`. Return `False` to deny.

```python
from django_graphex import BasePermission

class IsOwnerOrReadOnly(BasePermission):
    def has_permission(self, info, action, model, **kwargs):
        if action in ("retrieve", "list"):
            return True
        return info.context.user.is_authenticated
```

### Example: map to Django model permissions

The downstream pattern, mapping each action to a Django `add/change/delete/view`
permission:

```python
class DjangoModelPermission(BasePermission):
    _ACTION_PERM = {
        "create": "add", "update": "change",
        "delete": "delete", "retrieve": "view", "list": "view",
    }

    def has_permission(self, info, action, model, **kwargs):
        user = info.context.user
        codename = "{}.{}_{}".format(
            model._meta.app_label,
            self._ACTION_PERM[action],
            model._meta.model_name,
        )
        return user.has_perm(codename)
```

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
