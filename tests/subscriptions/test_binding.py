# -*- coding: utf-8 -*-
"""T-BINDING: idempotent signal registration and single serialize per event.

Broadcasts are now deferred via ``transaction.on_commit`` so they only fire
after the surrounding transaction commits.  Tests that assert on the content of
broadcasts must use ``pytest.mark.django_db(transaction=True)`` so that real
commits occur and ``on_commit`` callbacks execute.
"""

from unittest import mock

import pytest

from django_graphex.subscriptions import bindings

from .schema import UserSubscription

# All tests in this module need real commits so on_commit callbacks run.
pytestmark = pytest.mark.django_db(transaction=True)


def test_save_broadcasts_to_action_and_pk_groups(
    django_user_model, captured_group_sends
):
    UserSubscription.get_binding()
    user = django_user_model.objects.create(username="alice", email="a@example.com")

    groups = {group for group, _ in captured_group_sends}
    assert groups == {"auth.user-create", "auth.user-create-{}".format(user.pk)}

    _, message = captured_group_sends[0]
    assert message["type"] == "subscription.notify"
    assert message["stream"] == "users"
    assert message["payload"]["action"] == "create"
    assert message["payload"]["model"] == "auth.user"
    assert message["payload"]["data"]["username"] == "alice"


def test_delete_broadcasts_delete_action(django_user_model, captured_group_sends):
    UserSubscription.get_binding()
    user = django_user_model.objects.create(username="carol")
    captured_group_sends.clear()

    user.delete()
    actions = {message["payload"]["action"] for _, message in captured_group_sends}
    assert actions == {"delete"}


def test_signal_registration_is_idempotent(django_user_model):
    # Build the binding twice; the dispatch_uid must keep a single receiver, so
    # the instance is serialized exactly once per save (UserSubscription is in
    # full mode).
    UserSubscription.get_binding()
    UserSubscription._binding = None  # force a second construction
    UserSubscription.get_binding()

    with mock.patch.object(
        bindings, "serialize_instance", wraps=bindings.serialize_instance
    ) as spy:
        django_user_model.objects.create(username="dave")

    assert spy.call_count == 1


def test_broadcast_without_channel_layer_is_silent(django_user_model, monkeypatch):
    monkeypatch.setattr(bindings, "get_channel_layer", lambda: None)
    binding = UserSubscription.get_binding()
    # Should not raise even though there is no layer to send to.
    binding.broadcast("create", django_user_model(username="erin", pk=999))


def test_unregister_stops_broadcasts(django_user_model, captured_group_sends):
    binding = UserSubscription.get_binding()
    binding.unregister()
    try:
        django_user_model.objects.create(username="frank")
        assert captured_group_sends == []
    finally:
        # Re-arm the binding so later tests still receive notifications.
        binding.register()
