# -*- coding: utf-8 -*-
"""T-ON-COMMIT: subscription broadcasts defer until transaction commits.

Covers:
  (a) A model save inside a transaction.atomic() that ROLLS BACK emits
      zero broadcast notifications — no phantom events for non-existent rows.
  (b) A model save inside a transaction.atomic() that COMMITS still delivers
      exactly one broadcast per action group (no regression).
  (c) A save outside any explicit transaction (auto-commit) still broadcasts
      immediately (on_commit runs synchronously when no transaction is open).
  (d) A committed delete carries the real pk (non-None) in id-only mode, and
      routes to the per-pk group (regression: #69 — pk was None after on_commit
      because Django nulls instance.pk at the end of Model.delete()).
  (e) A committed delete in payload_mode="full" mode does not raise an exception
      (regression: #69 — serialize_instance hit M2M on a pk-less instance).
  (f) A committed delete on an indexed subscription emits the index-scoped delete
      group names from the detached snapshot, and every message carries the
      real (non-None) pk.
  (g) Multiple saves of the same mutable instance in one transaction preserve
      the pk, index and full payload that existed at each post_save signal.
  (h) Create-then-delete in one transaction still publishes the create event
      with the original pk instead of the pk Django clears during delete().
  (i) Snapshots queued by multiple saves are all discarded on rollback.

Django's test runner wraps every test in a transaction (TestCase) so
on_commit callbacks never fire by default. We use:
  - pytest-django's "transaction=True" marker for real commit tests.
  - Django's "captureOnCommitCallbacks(execute=True)" in non-transactional
    tests where we still want on_commit to run.
"""

from __future__ import annotations

from typing import Any, Generator

import pytest
from django.contrib.auth.models import AbstractUser
from django.db import transaction

from django_graphex.subscriptions import Subscription
from django_graphex.subscriptions.bindings import SubscriptionBinding
from tests.models import BasicModel, HookModel

from .schema import UserSubscription

pytestmark = [pytest.mark.django_db(transaction=True)]


class _IdOnlyDeleteSubscription(Subscription):
    """Minimal id-only subscription over BasicModel for delete-pk tests."""

    class Meta:
        model = BasicModel
        stream = "basic_delete_idonly"
        payload_mode = "id_only"


class _IndexedFullSaveSubscription(Subscription):
    """Full-payload subscription used to prove save snapshots are immutable."""

    class Meta:
        model = HookModel
        stream = "hookmodel_save_snapshots"
        payload_mode = "full"
        subscription_index_fields = ("text",)


@pytest.fixture(autouse=True)
def _arm_binding() -> None:
    """Ensure the UserSubscription binding is wired before each test."""
    UserSubscription.get_binding()


@pytest.fixture()
def _arm_idonly_binding() -> Generator[SubscriptionBinding, None, None]:
    """Wire the id-only delete subscription and tear it down after the test.

    Yields:
        binding: The registered SubscriptionBinding for
            _IdOnlyDeleteSubscription, unregistered again after the test.
    """
    binding = _IdOnlyDeleteSubscription.get_binding()
    binding.register()
    yield binding
    binding.unregister()


@pytest.fixture()
def _arm_indexed_full_save_binding() -> Generator[SubscriptionBinding, None, None]:
    """Wire the full-payload indexed subscription used by snapshot tests."""
    binding = _IndexedFullSaveSubscription.get_binding()
    binding.register()
    yield binding
    binding.unregister()


# ---------------------------------------------------------------------------
# (a) Rollback => zero broadcasts
# ---------------------------------------------------------------------------


def test_rolled_back_save_emits_no_broadcast(  # noqa: DOC005
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """A save that is rolled back must not produce any subscription notification.

    post_save fires inside the still-open transaction; the broadcast must be
    deferred via transaction.on_commit so that a subsequent rollback suppresses
    it entirely.

    Args:
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
    """
    from django.contrib.auth.models import User

    try:
        with transaction.atomic():
            User.objects.create(username="ghost_user", email="ghost@example.com")
            # Force a rollback by raising inside the atomic block.
            raise ValueError("forced rollback")
    except ValueError:
        pass  # expected

    assert captured_group_sends == [], (
        f"Expected 0 broadcasts after rollback, got {len(captured_group_sends)}: "
        f"{captured_group_sends}"
    )


def test_rolled_back_delete_emits_no_broadcast(  # noqa: DOC005
    db: None,
    django_user_model: type[AbstractUser],
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """A delete that is rolled back must not produce any subscription notification.

    Args:
        db: The pytest-django fixture granting database access for the test.
        django_user_model: The pytest-django fixture returning the active
            user model class.
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
    """
    user = django_user_model.objects.create(username="doomed", email="d@example.com")
    captured_group_sends.clear()  # ignore the create broadcast

    try:
        with transaction.atomic():
            user.delete()
            raise ValueError("forced rollback after delete")
    except ValueError:
        pass

    assert captured_group_sends == [], (
        f"Expected 0 broadcasts after rolled-back delete, got {len(captured_group_sends)}"
    )


# ---------------------------------------------------------------------------
# (b) Committed save => exactly one broadcast set
# ---------------------------------------------------------------------------


def test_committed_save_broadcasts_exactly_once(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """A committed save must still deliver the expected notification.

    Contract: this test ships broken (regression) if a committed save either
    drops the coarse or per-pk group broadcast, or emits extras.

    Args:
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
    """
    from django.contrib.auth.models import User

    user = User.objects.create(username="real_user", email="real@example.com")

    # We expect two groups: the coarse create group and the per-pk group.
    groups = {group for group, _ in captured_group_sends}
    assert "auth.user.users-create" in groups, (
        f"Expected auth.user.users-create group in {groups}"
    )
    assert f"auth.user.users-create-{user.pk}" in groups, (
        f"Expected per-pk group in {groups}"
    )

    # Exactly two messages (coarse + per-pk — no extras).
    assert len(captured_group_sends) == 2, (
        f"Expected exactly 2 group_sends after commit, got {len(captured_group_sends)}"
    )


# ---------------------------------------------------------------------------
# (g-i) Deferred callbacks use immutable signal-time snapshots
# ---------------------------------------------------------------------------


def test_create_then_update_preserves_each_signal_time_snapshot(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
    _arm_indexed_full_save_binding: SubscriptionBinding,
) -> None:
    """Verify create and update events retain signal-time snapshots.

    Args:
        captured_group_sends: Messages captured from the channel layer.
        _arm_indexed_full_save_binding: Registered indexed subscription fixture.
    """
    with transaction.atomic():
        instance = HookModel.objects.create(text="first")
        real_pk = instance.pk
        instance.text = "second"
        instance.save(update_fields=["text"])

    sends = [
        (group, message)
        for group, message in captured_group_sends
        if message.get("stream") == "hookmodel_save_snapshots"
    ]
    coarse_sends = [
        message
        for group, message in sends
        if group
        == _IndexedFullSaveSubscription._group_name(message["payload"]["action"])
    ]
    assert [message["payload"]["action"] for message in coarse_sends] == [
        "create",
        "update",
    ]
    coarse_messages = {
        message["payload"]["action"]: message for message in coarse_sends
    }

    assert coarse_messages["create"]["pk"] == real_pk
    assert coarse_messages["create"]["payload"]["data"]["text"] == "first"
    assert coarse_messages["update"]["pk"] == real_pk
    assert coarse_messages["update"]["payload"]["data"]["text"] == "second"

    groups = {group for group, _ in sends}
    assert (
        _IndexedFullSaveSubscription._group_name("create", index={"text": "first"})
        in groups
    )
    assert (
        _IndexedFullSaveSubscription._group_name("update", index={"text": "second"})
        in groups
    )


def test_create_then_delete_preserves_create_pk_snapshot(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
    _arm_idonly_binding: SubscriptionBinding,
) -> None:
    """Verify a deferred create retains the pk cleared by a later delete.

    Args:
        captured_group_sends: Messages captured from the channel layer.
        _arm_idonly_binding: Registered id-only subscription fixture.
    """
    with transaction.atomic():
        instance = BasicModel.objects.create(text="short-lived")
        real_pk = instance.pk
        instance.delete()

    create_messages = [
        message
        for _, message in captured_group_sends
        if message.get("stream") == "basic_delete_idonly"
        and message["payload"]["action"] == "create"
    ]

    assert create_messages
    assert all(message["pk"] == real_pk for message in create_messages)
    assert all(
        message["payload"]["data"] == {"id": real_pk} for message in create_messages
    )


def test_multiple_save_snapshots_are_discarded_on_rollback(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
    _arm_indexed_full_save_binding: SubscriptionBinding,
) -> None:
    """Verify rollback discards snapshots from repeated post-save signals.

    Args:
        captured_group_sends: Messages captured from the channel layer.
        _arm_indexed_full_save_binding: Registered indexed subscription fixture.

    Raises:
        ValueError: Intentionally raised inside the transaction to force rollback.
    """
    with pytest.raises(ValueError, match="force snapshot rollback"):
        with transaction.atomic():
            instance = HookModel.objects.create(text="first")
            instance.text = "second"
            instance.save(update_fields=["text"])
            raise ValueError("force snapshot rollback")

    sends = [
        message
        for _, message in captured_group_sends
        if message.get("stream") == "hookmodel_save_snapshots"
    ]
    assert sends == []


# ---------------------------------------------------------------------------
# (d) Committed delete — id-only mode — must carry the real pk (regression #69)
# ---------------------------------------------------------------------------


def test_committed_delete_idonly_carries_real_pk(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
    _arm_idonly_binding: SubscriptionBinding,
) -> None:
    """A committed delete in id-only mode must broadcast the real pk, not None.

    Contract: regression #69 ships broken again if the envelope pk, the
    per-pk group name, or the payload data["id"] read as None instead of the
    real primary key.

    Regression: _on_delete deferred "lambda: self.broadcast('delete', instance)".
    Django nulls instance.pk *before* the on_commit callback fires, so
    broadcast() read instance.pk=None — the envelope pk was None, the data dict
    was {"id": None}, and the per-pk group collapsed to the coarse group.

    The delete MUST happen inside an explicit atomic() block so that the
    on_commit callback fires *after* the block exits — that is the moment
    Django nulls instance.pk, making the regression observable.

    This test MUST FAIL on unpatched code.

    Args:
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
        _arm_idonly_binding: The registered SubscriptionBinding fixture for
            _IdOnlyDeleteSubscription.
    """
    instance = BasicModel.objects.create(text="to-be-deleted")
    real_pk = instance.pk
    captured_group_sends.clear()  # ignore the create broadcast

    # Filter only the stream we care about.
    def _stream_sends() -> list[tuple[str, dict[str, Any]]]:
        return [
            (g, m)
            for g, m in captured_group_sends
            if m.get("stream") == "basic_delete_idonly"
        ]

    # Wrap in atomic() so on_commit defers until after the block exits.
    # Django nulls instance.pk at the end of Model.delete(), which happens
    # before on_commit fires — this is exactly where the regression lives.
    with transaction.atomic():
        instance.delete()

    sends = _stream_sends()
    assert sends, "Expected at least one delete broadcast but got none"

    # (i) Every message envelope must carry the real pk — not None.
    for group, message in sends:
        assert message["pk"] == real_pk, (
            f"Envelope pk is {message['pk']!r} in group {group!r}; "
            f"expected {real_pk!r}.  This is the #69 regression."
        )

    # (ii) The per-pk group must be present (id-only mode uses id to build group).
    groups = {g for g, _ in sends}
    per_pk_group = _IdOnlyDeleteSubscription._group_name("delete", id=real_pk)
    assert per_pk_group in groups, (
        f"Per-pk group {per_pk_group!r} not in {groups!r}.  "
        "When pk=None the group collapses to the coarse group — that is the #69 bug."
    )

    # (iii) The data dict must carry the real id, not None.
    payloads = [m["payload"]["data"] for _, m in sends]
    for data in payloads:
        assert data.get("id") == real_pk, (
            f"Payload data['id'] is {data.get('id')!r}; expected {real_pk!r}."
        )


# ---------------------------------------------------------------------------
# (e) Committed delete — payload_mode="full" — must not raise (regression #69)
# ---------------------------------------------------------------------------


def test_committed_delete_serialize_mode_no_exception(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
    serialize_full: None,
) -> None:
    """A committed delete with payload_mode="full" must not propagate a ValueError.

    Contract: regression #69 ships broken again if a full-payload broadcast
    on a just-deleted instance raises instead of completing silently.

    Regression: broadcast() called serialize_instance on the pk-less instance,
    hitting the M2M accessor -> ValueError "needs a value for field id before
    this many-to-many relationship can be used" escaping the user's atomic() block.

    UserSubscription uses payload_mode="full" (via schema.py) and is bound by
    the autouse "_arm_binding" fixture, so User.delete() exercises that path.

    This test MUST NOT raise — if the bug is present it will raise ValueError.

    Args:
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
        serialize_full: The fixture forcing subscriptions into full-payload
            serialization mode for the duration of the test.
    """
    from django.contrib.auth.models import User

    user = User.objects.create_user(username="del_serialize", password="x")
    real_pk = user.pk
    captured_group_sends.clear()

    # Wrap in atomic() so the on_commit callback defers until after the block
    # exits — that is when Django has already nulled instance.pk, making the
    # serialize_instance call on a pk-less instance observable.
    # This must complete without raising — the regression throws ValueError here.
    with transaction.atomic():
        user.delete()

    # The broadcast must still have fired with the real pk.
    user_sends = [(g, m) for g, m in captured_group_sends if m.get("stream") == "users"]
    assert user_sends, "Expected at least one delete broadcast in 'users' stream"
    for group, message in user_sends:
        assert message["pk"] == real_pk, (
            f"Envelope pk is {message['pk']!r}; expected {real_pk!r}."
        )


# ---------------------------------------------------------------------------
# (f) Committed delete — indexed subscription — index-scoped groups appear
# ---------------------------------------------------------------------------


class _IndexedDeleteSubscription(Subscription):
    """Indexed id-only subscription over HookModel (index field: text).

    Used to exercise the snapshot fan-out branch that appends the coarse-index
    and per-pk-index group names when the subscription declares
    "subscription_index_fields".
    """

    class Meta:
        model = HookModel
        stream = "hookmodel_indexed_delete"
        payload_mode = "id_only"
        subscription_index_fields = ("text",)


@pytest.fixture()
def _arm_indexed_binding() -> Generator[SubscriptionBinding, None, None]:
    """Wire the indexed delete subscription and tear it down after the test.

    Yields:
        binding: The registered SubscriptionBinding for
            _IndexedDeleteSubscription, unregistered again after the test.
    """
    binding = _IndexedDeleteSubscription.get_binding()
    binding.register()
    yield binding
    binding.unregister()


def test_committed_delete_indexed_subscription_emits_index_scoped_groups(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
    _arm_indexed_binding: SubscriptionBinding,
) -> None:
    """A committed delete on an indexed subscription must emit index-scoped group names.

    Contract: this test ships broken if the indexed snapshot fan-out stops
    appending the coarse-index and per-pk-index group names, or if any message
    loses its real pk.

    Exercises the indexed branch in "_fan_out_snapshot" that calls:

        group_names.append(cls._group_name("delete", index=index))
        group_names.append(cls._group_name("delete", id=pk_snapshot, index=index))

    The delete is wrapped in explicit atomic() so that the on_commit callback
    fires after the block exits (same pattern as tests (d) and (e) above).
    Every message in the stream must carry the real (non-None) pk snapshot.

    Args:
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
        _arm_indexed_binding: The registered SubscriptionBinding fixture for
            _IndexedDeleteSubscription.
    """
    instance = HookModel.objects.create(text="indexed-val")
    real_pk = instance.pk
    captured_group_sends.clear()  # discard the create broadcast

    def _stream_sends() -> list[tuple[str, dict[str, Any]]]:
        return [
            (g, m)
            for g, m in captured_group_sends
            if m.get("stream") == "hookmodel_indexed_delete"
        ]

    with transaction.atomic():
        instance.delete()

    sends = _stream_sends()
    assert sends, "Expected at least one delete broadcast but got none"

    # Build expected index-scoped group names via the same helper the binding uses.
    index = _IndexedDeleteSubscription._instance_index(
        HookModel(text="indexed-val", pk=real_pk)
    )
    expected_index_group = _IndexedDeleteSubscription._group_name("delete", index=index)
    expected_index_pk_group = _IndexedDeleteSubscription._group_name(
        "delete", id=real_pk, index=index
    )

    groups = {g for g, _ in sends}

    # (i) Both index-scoped group names must be present (bindings.py:250-251).
    assert expected_index_group in groups, (
        f"Index-scoped group {expected_index_group!r} not in {groups!r}. "
        "The indexed snapshot branch was not executed."
    )
    assert expected_index_pk_group in groups, (
        f"Per-pk index-scoped group {expected_index_pk_group!r} not in {groups!r}. "
        "The indexed per-pk snapshot branch was not executed."
    )

    # (ii) Every message envelope must carry the real pk — not None.
    for group, message in sends:
        assert message["pk"] == real_pk, (
            f"Envelope pk is {message['pk']!r} in group {group!r}; "
            f"expected {real_pk!r}."
        )
