# -*- coding: utf-8 -*-
"""T-BINDING: idempotent signal registration and single serialize per event.

Broadcasts are now deferred via "transaction.on_commit" so they only fire
after the surrounding transaction commits. Tests that assert on the content of
broadcasts must use "pytest.mark.django_db(transaction=True)" so that real
commits occur and "on_commit" callbacks execute.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.contrib.auth.models import AbstractUser

from django_graphex.subscriptions import bindings
from django_graphex.subscriptions import subscription as subscription_mod

from .schema import UserSubscription

# All tests in this module need real commits so on_commit callbacks run.
pytestmark = pytest.mark.django_db(transaction=True)


def test_save_broadcasts_to_action_and_pk_groups(
    django_user_model: type[AbstractUser],
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """Saving a user must broadcast to both the action group and the pk group.

    Contract: subscribers listening on either the action-level group or the
    per-instance group ship broken if only one of the two receives the event.

    Args:
        django_user_model: The pytest-django fixture returning the active
            user model class.
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
    """
    UserSubscription.get_binding()
    user = django_user_model.objects.create(username="alice", email="a@example.com")

    groups = {group for group, _ in captured_group_sends}
    assert groups == {
        "auth.user.users-create",
        "auth.user.users-create-{}".format(user.pk),
    }

    _, message = captured_group_sends[0]
    assert message["type"] == "subscription.notify"
    assert message["stream"] == "users"
    assert message["payload"]["action"] == "create"
    assert message["payload"]["model"] == "auth.user"
    assert message["payload"]["data"]["username"] == "alice"


def test_delete_broadcasts_delete_action(
    django_user_model: type[AbstractUser],
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """Deleting a user must broadcast an event whose action is "delete".

    Args:
        django_user_model: The pytest-django fixture returning the active
            user model class.
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
    """
    UserSubscription.get_binding()
    user = django_user_model.objects.create(username="carol")
    captured_group_sends.clear()

    user.delete()
    actions = {message["payload"]["action"] for _, message in captured_group_sends}
    assert actions == {"delete"}


def test_signal_registration_is_idempotent(
    django_user_model: type[AbstractUser],
) -> None:
    """Rebuilding the binding must not register a duplicate signal receiver.

    Contract: without a stable dispatch_uid, rebuilding the binding would
    register a second receiver and serialize each saved instance twice.

    Args:
        django_user_model: The pytest-django fixture returning the active
            user model class.
    """
    # Build the binding twice; the dispatch_uid must keep a single receiver, so
    # the instance is serialized exactly once per save (UserSubscription is in
    # full mode).
    UserSubscription.get_binding()
    UserSubscription._binding = None  # force a second construction
    UserSubscription.get_binding()

    with mock.patch.object(
        subscription_mod,
        "serialize_instance",
        wraps=subscription_mod.serialize_instance,
    ) as spy:
        django_user_model.objects.create(username="dave")

    assert spy.call_count == 1


def test_broadcast_without_channel_layer_is_silent(
    django_user_model: type[AbstractUser],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Broadcasting with no channel layer configured must not raise.

    Args:
        django_user_model: The pytest-django fixture returning the active
            user model class.
        monkeypatch: The pytest fixture used to force get_channel_layer to
            return None.
    """
    monkeypatch.setattr(bindings, "get_channel_layer", lambda: None)
    binding = UserSubscription.get_binding()
    # Should not raise even though there is no layer to send to.
    binding.broadcast("create", django_user_model(username="erin", pk=999))


def test_signal_without_channel_layer_does_not_serialize(
    django_user_model: type[AbstractUser],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify dropped signals avoid serialization and ORM-query cost.

    Args:
        django_user_model: Active Django user model class.
        monkeypatch: Pytest fixture used to disable the channel layer.
    """
    monkeypatch.setattr(bindings, "get_channel_layer", lambda: None)
    UserSubscription.get_binding()

    with mock.patch.object(
        subscription_mod,
        "serialize_instance",
        wraps=subscription_mod.serialize_instance,
    ) as spy:
        django_user_model.objects.create(username="no-layer")

    assert spy.call_count == 0


def test_broadcast_compatibility_wrapper_sends_current_snapshot(
    django_user_model: type[AbstractUser],
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """Verify direct broadcast callers retain synchronous delivery.

    Args:
        django_user_model: Active Django user model class.
        captured_group_sends: Messages captured from the channel layer.
    """
    binding = UserSubscription.get_binding()
    user = django_user_model.objects.create(username="manual")
    captured_group_sends.clear()

    user.username = "manual-updated"
    binding.broadcast("update", user)

    groups = {group for group, _ in captured_group_sends}
    assert groups == {
        "auth.user.users-update",
        f"auth.user.users-update-{user.pk}",
    }
    assert all(
        message["payload"]["data"]["username"] == "manual-updated"
        for _, message in captured_group_sends
    )


def test_unregister_stops_broadcasts(
    django_user_model: type[AbstractUser],
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """Unregistering a binding must stop it from broadcasting further saves.

    Args:
        django_user_model: The pytest-django fixture returning the active
            user model class.
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
    """
    binding = UserSubscription.get_binding()
    binding.unregister()
    try:
        django_user_model.objects.create(username="frank")
        assert captured_group_sends == []
    finally:
        # Re-arm the binding so later tests still receive notifications.
        binding.register()
