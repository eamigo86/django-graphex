"""DRF-style permission classes for "DjangoModelType".

A permission is checked per action ("create" / "update" / "delete" /
"retrieve" / "list"). Subclass "BasePermission" and override either
"has_permission" (applies to every action) or a single
"has_<action>_permission" method. Each method receives "(info, model,
**kwargs)"; the "info.context" is the request and "kwargs" carries "data="
for create/update.
"""

from __future__ import annotations

import inspect
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar

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
    "DjangoModelPermissions",
    "supported_kwargs",
)

#: The read-only actions (used by the *OrReadOnly variants). Subscribing is an
#: observe/read operation, so it is treated as read-only.
READ_ACTIONS = ("retrieve", "list", "subscribe")


@lru_cache(maxsize=512)
def _named_kwargs(func: Any) -> frozenset[str] | None:
    """Return the keyword names *func* names explicitly, or None for "**kwargs".

    Memoized on the plain FUNCTION, never on a bound method: permission classes
    are instantiated per check, so caching bound methods would grow without
    bound.

    Args:
        func: The plain function to introspect.

    Returns:
        The accepted keyword names, or None when the callable absorbs any
        keyword (or cannot be introspected, which is treated the same way).
    """
    try:
        parameters = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):  # pragma: no cover — exotic callables
        return None
    names = set()
    for param in parameters:
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return None
        if param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            names.add(param.name)
    return frozenset(names)


def supported_kwargs(func: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return *kwargs* narrowed to what *func* can actually accept.

    The permission plumbing grows extras over time -- "data=" first, then
    "nested_parent=" for a write arriving through a parent's nested payload --
    and forwarding one to a check that spells its arguments out raises
    "TypeError" (an HTTP 500) even when the policy GRANTS the action. Dropping
    the extra instead is fail-closed: a policy that cannot see "nested_parent"
    reads a nested write exactly as it reads a direct one.

    Args:
        func: The callable about to be invoked.
        kwargs: The keyword arguments the caller wants to pass.

    Returns:
        The subset "func" accepts (the whole mapping when it takes "**kwargs").
    """
    accepted = _named_kwargs(getattr(func, "__func__", func))
    if accepted is None:
        return kwargs
    return {name: value for name, value in kwargs.items() if name in accepted}


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

    Each per-action method narrows the extras to what the "has_permission" it
    calls can actually accept. The narrowing has to happen HERE, at the call
    that lands on the override, and not at the outer call site: the per-action
    methods take "**kwargs", so narrowing against one of them forwards
    everything and an override spelling its arguments out
    ("def has_permission(self, info, action, model, data=None)") turns a GRANT
    into a "TypeError".
    """

    def has_permission(
        self,
        info: GraphQLResolveInfo,
        action: str,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Return whether the given "action" is allowed.

        The default implementation allows every action; override it to gate all
        actions the same way.

        Args:
            info: The GraphQL resolve info carrying the request context.
            action: The CRUD action being checked (e.g. "create").
            model: The Django model class the action targets.
            **kwargs: Action-specific extras, e.g. "data=" for create/update.

        Returns:
            allowed: True when the action is permitted.
        """
        return True

    def has_create_permission(
        self,
        info: GraphQLResolveInfo,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Return the permission for the "create" action.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras, forwarded to "has_permission"
                minus any it cannot accept.

        Returns:
            allowed: True when the "create" action is permitted.
        """
        return self.has_permission(
            info, "create", model, **supported_kwargs(self.has_permission, kwargs)
        )

    def has_update_permission(
        self,
        info: GraphQLResolveInfo,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Return the permission for the "update" action.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras, forwarded to "has_permission"
                minus any it cannot accept.

        Returns:
            allowed: True when the "update" action is permitted.
        """
        return self.has_permission(
            info, "update", model, **supported_kwargs(self.has_permission, kwargs)
        )

    def has_delete_permission(
        self,
        info: GraphQLResolveInfo,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Return the permission for the "delete" action.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras, forwarded to "has_permission"
                minus any it cannot accept.

        Returns:
            allowed: True when the "delete" action is permitted.
        """
        return self.has_permission(
            info, "delete", model, **supported_kwargs(self.has_permission, kwargs)
        )

    def has_retrieve_permission(
        self,
        info: GraphQLResolveInfo,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Return the permission for the "retrieve" action.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras, forwarded to "has_permission"
                minus any it cannot accept.

        Returns:
            allowed: True when the "retrieve" action is permitted.
        """
        return self.has_permission(
            info, "retrieve", model, **supported_kwargs(self.has_permission, kwargs)
        )

    def has_list_permission(
        self,
        info: GraphQLResolveInfo,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Return the permission for the "list" action.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras, forwarded to "has_permission"
                minus any it cannot accept.

        Returns:
            allowed: True when the "list" action is permitted.
        """
        return self.has_permission(
            info, "list", model, **supported_kwargs(self.has_permission, kwargs)
        )

    def has_subscribe_permission(
        self,
        info: GraphQLResolveInfo,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Return the permission for the "subscribe" action (read-like).

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the action targets.
            **kwargs: Action-specific extras, forwarded to "has_permission"
                minus any it cannot accept.

        Returns:
            allowed: True when the "subscribe" action is permitted.
        """
        return self.has_permission(
            info, "subscribe", model, **supported_kwargs(self.has_permission, kwargs)
        )


class AllowAny(BasePermission):
    """Allow every action (explicit form of the default).

    Inherits the allow-all "BasePermission" behavior unchanged; use it to make
    the open policy explicit at a call site.
    """


class IsAuthenticated(BasePermission):
    """Require an authenticated user for every action.

    Every action, read or write, is denied unless the request carries an
    authenticated user.
    """

    def has_permission(
        self,
        info: GraphQLResolveInfo,
        action: str,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Allow only authenticated users.

        Args:
            info: The GraphQL resolve info carrying the request context.
            action: The CRUD action being checked (ignored: all actions gate
                the same way).
            model: The Django model class the action targets (ignored).
            **kwargs: Action-specific extras (ignored).

        Returns:
            allowed: True when the request user is authenticated.
        """
        return _is_authenticated(info)


class IsAdmin(BasePermission):
    """Require an active staff superuser for every action.

    Every action, read or write, is denied unless the request user is active,
    staff, and a superuser.
    """

    def has_permission(
        self,
        info: GraphQLResolveInfo,
        action: str,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Allow only admin users.

        Args:
            info: The GraphQL resolve info carrying the request context.
            action: The CRUD action being checked (ignored: all actions gate
                the same way).
            model: The Django model class the action targets (ignored).
            **kwargs: Action-specific extras (ignored).

        Returns:
            allowed: True when the request user is an active staff superuser.
        """
        return _is_admin(info)


class IsAuthenticatedOrReadOnly(BasePermission):
    """Anyone may read; only authenticated users may write.

    Read actions (see "READ_ACTIONS") are always allowed; every other action
    requires an authenticated user.
    """

    def has_permission(
        self,
        info: GraphQLResolveInfo,
        action: str,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Allow reads for anyone, writes for authenticated users.

        Args:
            info: The GraphQL resolve info carrying the request context.
            action: The CRUD action being checked; read actions (see
                "READ_ACTIONS") are always allowed.
            model: The Django model class the action targets (ignored).
            **kwargs: Action-specific extras (ignored).

        Returns:
            allowed: True for read actions, otherwise True only when the user
                is authenticated.
        """
        return True if action in READ_ACTIONS else _is_authenticated(info)


class IsAdminOrReadOnly(BasePermission):
    """Anyone may read; only admin users may write.

    Read actions (see "READ_ACTIONS") are always allowed; every other action
    requires an active staff superuser.
    """

    def has_permission(
        self,
        info: GraphQLResolveInfo,
        action: str,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Allow reads for anyone, writes for admin users.

        Args:
            info: The GraphQL resolve info carrying the request context.
            action: The CRUD action being checked; read actions (see
                "READ_ACTIONS") are always allowed.
            model: The Django model class the action targets (ignored).
            **kwargs: Action-specific extras (ignored).

        Returns:
            allowed: True for read actions, otherwise True only when the user
                is an active staff superuser.
        """
        return True if action in READ_ACTIONS else _is_admin(info)


class DjangoModelPermissions(BasePermission):
    """Map CRUD actions to Django's built-in model permissions (DRF-style).

    Each action is mapped to the Django permission codenames the user must
    hold (checked with "user.has_perms"). The mapping lives in "perms_map", a
    class variable subclasses may override to customize the required codenames
    per action.

    The default "perms_map" is composite: because a mutation payload returns
    instance data, each write action requires BOTH its write verb AND "view".
    Read/observe actions stay view-only:

        create     "{app_label}.add_{model_name}" + "{app_label}.view_{model_name}"
        update     "{app_label}.change_{model_name}" + "{app_label}.view_{model_name}"
        delete     "{app_label}.delete_{model_name}" + "{app_label}.view_{model_name}"
        retrieve   "{app_label}.view_{model_name}"
        list       "{app_label}.view_{model_name}"
        subscribe  "{app_label}.view_{model_name}"

    Override "perms_map" in a subclass to customize the required codenames (e.g.
    a write-only inbox that maps "create" to "add" alone, dropping the "view"
    requirement).

    A subscribe request that forwards the action it observes ("create" /
    "update" / "delete" / "all_actions") is gated by the UNION of the
    "subscribe" row and every write row that action maps to (see
    "subscribe_actions_map"), so a customized row is honored on both paths.

    This class is fail-closed: an unauthenticated user, a missing "model"
    context, or an unknown action is denied. Because it denies when "model" is
    None, it is intended for "DjangoModelType.permission_classes" (where a
    model is always supplied) and NOT for view-level
    "AuthenticatedGraphQLView.permission_classes" (where no model is passed).

    Superusers pass automatically: Django's "ModelBackend" grants every
    permission to an active superuser, so "has_perms" returns True.
    """

    #: Action -> tuple of "str.format" templates resolved against the model's
    #: "app_label" and "model_name". Override in a subclass to customize.
    perms_map: ClassVar[dict[str, tuple[str, ...]]] = {
        "create": ("{app_label}.add_{model_name}", "{app_label}.view_{model_name}"),
        "update": ("{app_label}.change_{model_name}", "{app_label}.view_{model_name}"),
        "delete": ("{app_label}.delete_{model_name}", "{app_label}.view_{model_name}"),
        "retrieve": ("{app_label}.view_{model_name}",),
        "list": ("{app_label}.view_{model_name}",),
        "subscribe": ("{app_label}.view_{model_name}",),
    }

    #: Subscription action-value -> the "perms_map" write rows it composes on
    #: top of the "subscribe" row. Override alongside "perms_map" to support
    #: extra action-values.
    subscribe_actions_map: ClassVar[dict[str, tuple[str, ...]]] = {
        "create": ("create",),
        "update": ("update",),
        "delete": ("delete",),
        "all_actions": ("create", "update", "delete"),
    }

    def get_required_permissions(
        self, action: str, model: type[Model]
    ) -> list[str] | None:
        """Return the permission codenames "action" requires on "model".

        Args:
            action: The CRUD action being checked (e.g. "create").
            model: The Django model class the action targets.

        Returns:
            perms: The resolved permission codenames (e.g. "['app.add_thing']"),
                or None when "action" is not present in "perms_map".
        """
        templates = self.perms_map.get(action)
        if templates is None:
            return None
        opts = model._meta
        return [
            template.format(app_label=opts.app_label, model_name=opts.model_name)
            for template in templates
        ]

    def has_permission(
        self,
        info: GraphQLResolveInfo,
        action: str,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Allow only users holding the model permissions for "action".

        Fail-closed: denies unauthenticated users, a missing "model", and
        unknown actions before consulting "user.has_perms".

        Args:
            info: The GraphQL resolve info carrying the request context.
            action: The CRUD action being checked (e.g. "create").
            model: The Django model class the action targets.
            **kwargs: Action-specific extras (ignored here).

        Returns:
            allowed: True only when an authenticated user holds every codename
                that "action" requires on "model".
        """
        if not _is_authenticated(info):
            return False
        if model is None:
            return False
        perms = self.get_required_permissions(action, model)
        if perms is None:
            return False
        return bool(_user(info).has_perms(perms))

    def has_subscribe_permission(
        self,
        info: GraphQLResolveInfo,
        model: type[Model],
        **kwargs: Any,
    ) -> bool:
        """Gate a subscribe request by its per-action COMPOSITE permissions.

        When the native subscribe entry forwards the requested action
        ("create" / "update" / "delete" / "all_actions"), the check is
        composite: the codenames of the "subscribe" row of "perms_map" PLUS
        those of every write row the action maps to via
        "subscribe_actions_map" (a payload returns instance data). With the
        default "perms_map" that is "view" plus the action's write verb,
        mirroring the P0 table; a subclass that customizes either mapping is
        honored, because every codename is resolved through
        "get_required_permissions". Without an action (a caller that never
        forwards one), it falls back to the generic view-only "subscribe"
        gate, preserving the pre-change contract.

        This is the RUNTIME half of the defense-in-depth model: even against the
        FULL schema (a bypass of the pruned action enum), a user lacking the
        action's write verb is denied here.

        The forwarded action-value arrives under the "subscription_action"
        kwarg ("authorize" reserves the positional "action" for the CRUD verb
        "subscribe"), falling back to "action" for direct callers.

        Args:
            info: The GraphQL resolve info carrying the request context.
            model: The Django model class the subscription targets.
            **kwargs: Action-specific extras; "subscription_action" (or
                "action") carries the forwarded write verb to gate against.

        Returns:
            allowed: True only when an authenticated user holds every codename
                the resolved subscribe action requires on "model"; False when
                the action is unknown or a required "perms_map" row is missing.
        """
        if not _is_authenticated(info):
            return False
        if model is None:
            return False
        action = kwargs.get("subscription_action", kwargs.get("action"))
        if action is None:
            # No action forwarded: fall back to the generic view-only gate.
            return self.has_permission(
                info,
                "subscribe",
                model,
                **supported_kwargs(self.has_permission, kwargs),
            )
        rows = self.subscribe_actions_map.get(action)
        if rows is None:
            # Unknown subscribe action -> fail-closed.
            return False
        perms: set[str] = set()
        for row in ("subscribe", *rows):
            required = self.get_required_permissions(row, model)
            if required is None:
                # A row the mapping does not cover -> fail-closed.
                return False
            perms.update(required)
        return bool(_user(info).has_perms(sorted(perms)))
