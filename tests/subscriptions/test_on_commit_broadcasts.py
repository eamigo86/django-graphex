# -*- coding: utf-8 -*-
"""T-ON-COMMIT: subscription broadcasts defer until transaction commits.

Covers:
  (a) A model save inside a transaction.atomic() that ROLLS BACK emits
      zero broadcast notifications — no phantom events for non-existent rows.
  (b) A model save inside a transaction.atomic() that COMMITS still delivers
      exactly one broadcast per action group (no regression).
  (c) A save outside any explicit transaction (auto-commit) still broadcasts
      immediately (on_commit runs synchronously when no transaction is open).

Django's test runner wraps every test in a transaction (TestCase) so
on_commit callbacks never fire by default.  We use:
  - pytest-django's ``transaction=True`` marker for real commit tests.
  - Django's ``captureOnCommitCallbacks(execute=True)`` in non-transactional
    tests where we still want on_commit to run.
"""

from __future__ import annotations

import pytest
from django.db import transaction

from .schema import UserSubscription

pytestmark = [pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def _arm_binding():
    """Ensure the UserSubscription binding is wired before each test."""
    UserSubscription.get_binding()


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
