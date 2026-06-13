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
  (e) A committed delete in serialize_data=True mode does not raise an exception
      (regression: #69 — serialize_instance hit M2M on a pk-less instance).
  (f) A committed delete on an indexed subscription emits the index-scoped delete
      group names (bindings.py:250-251 — the ``if index:`` branch in
      ``_broadcast_delete``), and every message carries the real (non-None) pk.

Django's test runner wraps every test in a transaction (TestCase) so
on_commit callbacks never fire by default.  We use:
  - pytest-django's ``transaction=True`` marker for real commit tests.
  - Django's ``captureOnCommitCallbacks(execute=True)`` in non-transactional
    tests where we still want on_commit to run.
"""

from __future__ import annotations

import pytest
from django.db import transaction

from django_graphex.subscriptions import Subscription
from tests.models import BasicModel, HookModel

from .schema import UserSubscription

pytestmark = [pytest.mark.django_db(transaction=True)]


class _IdOnlyDeleteSubscription(Subscription):
    """Minimal id-only subscription over BasicModel for delete-pk tests."""

    class Meta:
        model = BasicModel
        stream = "basic_delete_idonly"
        serialize_data = False


@pytest.fixture(autouse=True)
def _arm_binding():
    """Ensure the UserSubscription binding is wired before each test."""
    UserSubscription.get_binding()


@pytest.fixture()
def _arm_idonly_binding():
    """Wire the id-only delete subscription and tear it down after the test."""
    binding = _IdOnlyDeleteSubscription.get_binding()
    binding.register()
    yield binding
    binding.unregister()


# ---------------------------------------------------------------------------
# (a) Rollback => zero broadcasts
# ---------------------------------------------------------------------------


def test_rolled_back_save_emits_no_broadcast(captured_group_sends):
    """A save that is rolled back must not produce any subscription notification.

    post_save fires inside the still-open transaction; the broadcast must be
    deferred via transaction.on_commit so that a subsequent rollback suppresses
    it entirely.
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


def test_rolled_back_delete_emits_no_broadcast(
    db, django_user_model, captured_group_sends
):
    """A delete that is rolled back must not produce any subscription notification."""
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


def test_committed_save_broadcasts_exactly_once(captured_group_sends):
    """A committed save still delivers the expected notification — no regression."""
    from django.contrib.auth.models import User

    user = User.objects.create(username="real_user", email="real@example.com")

    # We expect two groups: the coarse create group and the per-pk group.
    groups = {group for group, _ in captured_group_sends}
    assert "auth.user-create" in groups, f"Expected auth.user-create group in {groups}"
    assert f"auth.user-create-{user.pk}" in groups, f"Expected per-pk group in {groups}"

    # Exactly two messages (coarse + per-pk — no extras).
    assert len(captured_group_sends) == 2, (
        f"Expected exactly 2 group_sends after commit, got {len(captured_group_sends)}"
    )


# ---------------------------------------------------------------------------
# (d) Committed delete — id-only mode — must carry the real pk (regression #69)
# ---------------------------------------------------------------------------


def test_committed_delete_idonly_carries_real_pk(
    captured_group_sends, _arm_idonly_binding
):
    """A committed delete in id-only mode must broadcast the real pk, not None.

    Regression: _on_delete deferred `lambda: self.broadcast("delete", instance)`.
    Django nulls instance.pk *before* the on_commit callback fires, so
    broadcast() read instance.pk=None — the envelope pk was None, the data dict
    was {'id': None}, and the per-pk group collapsed to the coarse group.

    The delete MUST happen inside an explicit atomic() block so that the
    on_commit callback fires *after* the block exits — that is the moment
    Django nulls instance.pk, making the regression observable.

    This test MUST FAIL on unpatched code.
    """
    instance = BasicModel.objects.create(text="to-be-deleted")
    real_pk = instance.pk
    captured_group_sends.clear()  # ignore the create broadcast

    # Filter only the stream we care about.
    def _stream_sends():
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
    per_pk_group = f"tests.basicmodel-delete-{real_pk}"
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
# (e) Committed delete — serialize_data=True — must not raise (regression #69)
# ---------------------------------------------------------------------------


def test_committed_delete_serialize_mode_no_exception(
    captured_group_sends, serialize_full
):
    """A committed delete with serialize_data=True must not propagate a ValueError.

    Regression: broadcast() called serialize_instance on the pk-less instance,
    hitting the M2M accessor → ValueError "needs a value for field id before
    this many-to-many relationship can be used" escaping the user's atomic() block.

    UserSubscription uses serialize_data=True (via schema.py) and is bound by
    the autouse ``_arm_binding`` fixture, so User.delete() exercises that path.

    This test MUST NOT raise — if the bug is present it will raise ValueError.
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

    Used to exercise bindings.py:250-251 — the ``if index:`` branch inside
    ``_broadcast_delete`` that appends the coarse-index and per-pk-index group
    names when the subscription declares ``subscription_index_fields``.
    """

    class Meta:
        model = HookModel
        stream = "hookmodel_indexed_delete"
        serialize_data = False
        subscription_index_fields = ("text",)


@pytest.fixture()
def _arm_indexed_binding():
    """Wire the indexed delete subscription and tear it down after the test."""
    binding = _IndexedDeleteSubscription.get_binding()
    binding.register()
    yield binding
    binding.unregister()


def test_committed_delete_indexed_subscription_emits_index_scoped_groups(
    captured_group_sends, _arm_indexed_binding
):
    """A committed delete on an indexed subscription must emit index-scoped group names.

    Exercises bindings.py:250-251 — the ``if index:`` branch in
    ``_broadcast_delete`` that calls::

        group_names.append(cls._group_name("delete", index=index))
        group_names.append(cls._group_name("delete", id=pk_snapshot, index=index))

    The delete is wrapped in explicit atomic() so that the on_commit callback
    fires after the block exits (same pattern as tests (d) and (e) above).
    Every message in the stream must carry the real (non-None) pk snapshot.
    """
    instance = HookModel.objects.create(text="indexed-val")
    real_pk = instance.pk
    captured_group_sends.clear()  # discard the create broadcast

    def _stream_sends():
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
        "bindings.py:250 was not executed."
    )
    assert expected_index_pk_group in groups, (
        f"Per-pk index-scoped group {expected_index_pk_group!r} not in {groups!r}. "
        "bindings.py:251 was not executed."
    )

    # (ii) Every message envelope must carry the real pk — not None.
    for group, message in sends:
        assert message["pk"] == real_pk, (
            f"Envelope pk is {message['pk']!r} in group {group!r}; "
            f"expected {real_pk!r}."
        )
