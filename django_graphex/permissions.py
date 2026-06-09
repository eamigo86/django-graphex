"""DRF-style permission classes for "DjangoModelType".

A permission is checked per action ("create" / "update" / "delete" /
"retrieve" / "list"). Subclass "BasePermission" and override either
"has_permission" (applies to every action) or a single
"has_<action>_permission" method. Each method receives "(info, model,
**kwargs)"; the "info.context" is the request and "kwargs" carries "data="
for create/update.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.db.models import Model
    from graphql import GraphQLResolveInfo

__all__ = (
    "BasePermission",
    "AllowAny",
    "IsAuthenticated",
    "IsAdmin",
    "IsAuthenticatedOrReadOnly",
    "IsAdminOrReadOnly",
)

#: The read-only actions (used by the *OrReadOnly variants). Subscribing is an
#: observe/read operation, so it is treated as read-only.
READ_ACTIONS = ("retrieve", "list", "subscribe")


def _user(info: GraphQLResolveInfo) -> Any | None:
    """Return the request user from the "info" object, or None."""
    return getattr(getattr(info, "context", None), "user", None)


def _is_authenticated(info: GraphQLResolveInfo) -> bool:
    """Return whether the request has an authenticated user."""
    user = _user(info)
    return bool(user and user.is_authenticated)


def _is_admin(info: GraphQLResolveInfo) -> bool:
    """Return whether the request user is an active staff superuser."""
    user = _user(info)
    return bool(user and user.is_active and user.is_staff and user.is_superuser)


class BasePermission:
    """Allow-all base permission.

    Override "has_permission" to gate every action the same way, or a single
    "has_<action>_permission" for finer control. Returning False denies the
    action.
    """

    def has_permission(
        self, info: GraphQLResolveInfo, action: str, model: type[Model], **kwargs
    ) -> bool:
        """Return whether the given "action" is allowed. Default: allow."""
        return True

    def has_create_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs
    ) -> bool:
        """Return the permission for the "create" action."""
        return self.has_permission(info, "create", model, **kwargs)

    def has_update_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs
    ) -> bool:
        """Return the permission for the "update" action."""
        return self.has_permission(info, "update", model, **kwargs)

    def has_delete_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs
    ) -> bool:
        """Return the permission for the "delete" action."""
        return self.has_permission(info, "delete", model, **kwargs)

    def has_retrieve_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs
    ) -> bool:
        """Return the permission for the "retrieve" action."""
        return self.has_permission(info, "retrieve", model, **kwargs)

    def has_list_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs
    ) -> bool:
        """Return the permission for the "list" action."""
        return self.has_permission(info, "list", model, **kwargs)

    def has_subscribe_permission(
        self, info: GraphQLResolveInfo, model: type[Model], **kwargs
    ) -> bool:
        """Return the permission for the "subscribe" action (read-like)."""
        return self.has_permission(info, "subscribe", model, **kwargs)


class AllowAny(BasePermission):
    """Allow every action (explicit form of the default)."""


class IsAuthenticated(BasePermission):
    """Require an authenticated user for every action."""

    def has_permission(
        self, info: GraphQLResolveInfo, action: str, model: type[Model], **kwargs
    ) -> bool:
        """Allow only authenticated users."""
        return _is_authenticated(info)


class IsAdmin(BasePermission):
    """Require an active staff superuser for every action."""

    def has_permission(
        self, info: GraphQLResolveInfo, action: str, model: type[Model], **kwargs
    ) -> bool:
        """Allow only admin users."""
        return _is_admin(info)


class IsAuthenticatedOrReadOnly(BasePermission):
    """Anyone may read; only authenticated users may write."""

    def has_permission(
        self, info: GraphQLResolveInfo, action: str, model: type[Model], **kwargs
    ) -> bool:
        """Allow reads for anyone, writes for authenticated users."""
        return True if action in READ_ACTIONS else _is_authenticated(info)


class IsAdminOrReadOnly(BasePermission):
    """Anyone may read; only admin users may write."""

    def has_permission(
        self, info: GraphQLResolveInfo, action: str, model: type[Model], **kwargs
    ) -> bool:
        """Allow reads for anyone, writes for admin users."""
        return True if action in READ_ACTIONS else _is_admin(info)
