# -*- coding: utf-8 -*-
"""P3 — Per-action "authorize_subscription" (defense in depth).

The permission-scoped-schema change closes a runtime gap: the injected
"authorize_subscription" used to hardcode "authorize(info, 'subscribe')" and
DROP the requested "action", so a user permitted only "subscribe CREATE" could
still pass the runtime authorize for UPDATE / DELETE (only the pruned
enum would stop them — a single layer).

These tests pin the SECOND layer (design D6):

  * the generated subscription's "authorize_subscription" MUST forward the
    "action" kwarg to "DjangoModelType.authorize" so it reaches every
    "has_subscribe_permission(info, model, action=...)" check;
  * "DjangoModelPermissions" MUST map subscribe + action to the COMPOSITE
    per-action permissions ("view" + the write verb) from the P0 table, so a
    user lacking the action's write verb is denied at runtime even against the
    FULL schema (a bypass).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("channels")

from graphql import GraphQLError, GraphQLResolveInfo  # noqa: E402

from django_graphex.permissions import BasePermission, DjangoModelPermissions
from django_graphex.subscriptions import Subscription
from django_graphex.types import DjangoModelType
from tests.models import Post


class _User:
    """A minimal user carrying a fixed permission set for "has_perms"."""

    def __init__(self, perms: set[str], *, authenticated: bool = True) -> None:
        """Store the fixed permission set and authentication flags.

        Args:
            perms: The permission strings this user is considered to hold.
            authenticated: Whether the user reports itself as authenticated.
        """
        self._perms = set(perms)
        self.is_authenticated = authenticated
        self.is_active = True
        self.is_staff = False
        self.is_superuser = False

    def has_perms(self, perms: list[str]) -> bool:
        """Report whether every requested permission is in the held set.

        Args:
            perms: The permission strings being checked.

        Returns:
            allowed: True when perms is a subset of the held permissions.
        """
        return set(perms) <= self._perms


def _info(user: "_User") -> SimpleNamespace:
    """Build a resolve-info stand-in exposing ".context.user".

    Args:
        user: The stand-in user to attach to the fake context.

    Returns:
        info: A SimpleNamespace exposing "context.user".
    """
    return SimpleNamespace(context=SimpleNamespace(user=user))


def _subscription_cls() -> tuple[type[DjangoModelType], type[Subscription]]:
    """Return the generated "Subscription" subclass for a streaming Post type.

    Returns:
        A tuple of the DjangoModelType subclass and the Subscription
        subclass generated from it.
    """
    from django_graphex.types import DjangoModelType

    class _PostSubType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            payload_mode = "full"

    return _PostSubType, _PostSubType.subscription_type()


# ---------------------------------------------------------------------------
# 1) The injected authorize_subscription forwards ``action`` to authorize.
# ---------------------------------------------------------------------------


def test_authorize_subscription_forwards_action_to_permission_check() -> None:
    """A recording permission class must receive the requested "action".

    Contract: per-action defense in depth ships broken if the generated
    authorize_subscription drops the requested action instead of forwarding
    it through to has_subscribe_permission.
    """
    seen: dict[str, object] = {}

    class _Recorder(BasePermission):
        """A permission class that records the action and model it was called with."""

        def has_subscribe_permission(
            self, info: GraphQLResolveInfo, model: type[Any], **kwargs: Any
        ) -> bool:
            """Record the forwarded subscription action and model, then allow.

            Args:
                info: The GraphQL resolve info for the subscribe check.
                model: The Django model class being subscribed to.
                kwargs: Extra keyword arguments; only "subscription_action"
                    is inspected here.

            Returns:
                allowed: Always True; this stand-in only records inputs.
            """
            # The injected authorize_subscription forwards the subscription's
            # action-value under ``subscription_action`` (the positional CRUD
            # ``action`` is reserved for "subscribe").
            seen["action"] = kwargs.get("subscription_action")
            seen["model"] = model
            return True

    parent, sub = _subscription_cls()
    parent.permission_classes = (_Recorder,)
    try:
        # Native streaming forwards action= via kwargs (streaming.py:305).
        sub.authorize_subscription(_info(_User(set())), action="update")
    finally:
        parent.permission_classes = ()

    assert seen["action"] == "update"
    assert seen["model"] is Post


# ---------------------------------------------------------------------------
# 2) Per-action deny: lacking UPDATE => authorize denies for action=update.
# ---------------------------------------------------------------------------


def test_djangomodelpermissions_denies_missing_update_verb_at_runtime() -> None:
    """A user with only "view" (no "change") must be denied for UPDATE.

    Contract: defense in depth ships broken if, even against the FULL schema
    (a bypass of the pruned enum), authorize_subscription fails to deny a
    user lacking the "change" verb that DjangoModelPermissions now requires
    for subscribe UPDATE.
    """
    parent, sub = _subscription_cls()
    parent.permission_classes = (DjangoModelPermissions,)
    user = _User({"tests.view_post"})  # no change_post
    try:
        with pytest.raises(GraphQLError):
            sub.authorize_subscription(_info(user), action="update")
    finally:
        parent.permission_classes = ()


def test_djangomodelpermissions_denies_missing_delete_verb_at_runtime() -> None:
    """A user lacking "delete" must be denied for action=delete at runtime.

    Contract: the composite per-action permission mapping ships broken if a
    user without the delete verb is not denied when subscribing to DELETE.
    """
    parent, sub = _subscription_cls()
    parent.permission_classes = (DjangoModelPermissions,)
    user = _User({"tests.view_post"})  # no delete_post
    try:
        with pytest.raises(GraphQLError):
            sub.authorize_subscription(_info(user), action="delete")
    finally:
        parent.permission_classes = ()


# ---------------------------------------------------------------------------
# 3) Per-action allow: holding the composite verbs passes for that action.
# ---------------------------------------------------------------------------


def test_djangomodelpermissions_allows_when_composite_verbs_held() -> None:
    """A user holding "view" + "change" must pass update but stay denied for delete.

    Contract: the per-action mapping ships broken if holding the composite
    verbs for one action either fails to allow that action or incorrectly
    allows an action whose verb (delete) is still missing.
    """
    parent, sub = _subscription_cls()
    parent.permission_classes = (DjangoModelPermissions,)
    user = _User({"tests.view_post", "tests.change_post"})
    try:
        # update is permitted (view + change held) -> no raise.
        sub.authorize_subscription(_info(user), action="update")
        # delete is NOT permitted (no delete verb) -> denies.
        with pytest.raises(GraphQLError):
            sub.authorize_subscription(_info(user), action="delete")
    finally:
        parent.permission_classes = ()


def test_djangomodelpermissions_all_actions_requires_every_write_verb() -> None:
    """action=all_actions must require {view, add, change, delete} per the P0 table.

    Contract: the all_actions mapping ships broken if a user missing any one
    of the four verbs is still allowed to subscribe to all_actions.
    """
    parent, sub = _subscription_cls()
    parent.permission_classes = (DjangoModelPermissions,)
    full = {
        "tests.view_post",
        "tests.add_post",
        "tests.change_post",
        "tests.delete_post",
    }
    partial = {"tests.view_post", "tests.add_post"}  # missing change/delete
    try:
        sub.authorize_subscription(_info(_User(full)), action="all_actions")
        with pytest.raises(GraphQLError):
            sub.authorize_subscription(_info(_User(partial)), action="all_actions")
    finally:
        parent.permission_classes = ()


# ---------------------------------------------------------------------------
# 4) Backward compatibility: a subscribe WITHOUT an action still authorizes.
# ---------------------------------------------------------------------------


def test_authorize_subscription_without_action_stays_view_only() -> None:
    """When no "action" is forwarded, the check must fall back to view-only.

    Contract: backward compatibility ships broken if a user holding only
    "view" (no write verb) is denied when subscribing with no action kwarg,
    since that is the generic subscribe gate callers relied on pre-change.
    """
    parent, sub = _subscription_cls()
    parent.permission_classes = (DjangoModelPermissions,)
    user = _User({"tests.view_post"})
    try:
        sub.authorize_subscription(_info(user))  # no action kwarg -> no raise
    finally:
        parent.permission_classes = ()
