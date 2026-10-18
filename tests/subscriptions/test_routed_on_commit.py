"""Keep automatic subscription notifications on the model's database alias."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.conf import settings
from django.db import connections, models, router, transaction

from django_graphex.subscriptions import Subscription
from django_graphex.subscriptions.bindings import SubscriptionBinding


class RoutedCommitModel(models.Model):
    """Own the routed SQLite write without other test models' relations.

    The unmanaged table is created only in this module's disposable alias.
    """

    text = models.CharField(max_length=100)

    class Meta:
        """Keep the fixture's table out of the default test database.

        The test module creates it explicitly on the disposable alias.
        """

        app_label = "tests"
        db_table = "tests_routed_commit"
        managed = False


class _RoutedSubscription(Subscription):
    """Bind a minimal id-only stream to a real secondary SQLite write."""

    class Meta:
        model = RoutedCommitModel
        stream = "routed_commit"
        payload_mode = "id_only"


class _RoutedModelRouter:
    """Route only test-owned model reads and writes to the disposable alias."""

    def db_for_read(self, model: type[Any], **hints: Any) -> str | None:
        """Select the secondary alias for the bound model.

        Args:
            model: The model being read.
            **hints: Django's optional routing context.

        Returns:
            The disposable alias for RoutedCommitModel, otherwise no preference.
        """
        return "routed" if model is RoutedCommitModel else None

    def db_for_write(self, model: type[Any], **hints: Any) -> str | None:
        """Select the secondary alias for the bound model.

        Args:
            model: The model being written.
            **hints: Django's optional routing context.

        Returns:
            The disposable alias for RoutedCommitModel, otherwise no preference.
        """
        return "routed" if model is RoutedCommitModel else None


@pytest.fixture(scope="module", autouse=True)
def _register_routed_alias(
    django_db_setup: None,
    django_db_blocker: Any,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Install a disposable alias before function-scoped DB access is gated.

    Args:
        django_db_setup: Initializes Django's test database first.
        django_db_blocker: Temporarily permits schema creation on this alias.
        tmp_path_factory: Creates an external disposable SQLite location.

    Yields:
        None while the secondary table is available to this module.
    """
    alias = "routed"
    assert alias not in connections.databases
    location = tmp_path_factory.mktemp("routed-db") / "routed.sqlite3"
    settings.DATABASES[alias] = {
        **settings.DATABASES["default"],
        "NAME": str(location),
    }
    connection = connections[alias]
    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            editor.create_model(RoutedCommitModel)
    try:
        yield
    finally:
        connection.close()
        del connections._connections.routed
        del settings.DATABASES[alias]


@pytest.fixture
def routed_database(
    django_db_blocker: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[SubscriptionBinding]:
    """Register the routed binding and restore only this fixture's changes.

    Args:
        django_db_blocker: Permits only this test's real database operations.
        monkeypatch: Restores the test-owned router configuration.

    Yields:
        The registered subscription binding for RoutedCommitModel.
    """
    monkeypatch.setattr(router, "routers", [_RoutedModelRouter()])
    binding = _RoutedSubscription.get_binding()
    binding.register()
    with django_db_blocker.unblock():
        try:
            yield binding
        finally:
            binding.unregister()


def _stream_messages(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Return only coarse action-group messages from the routed stream.

    Args:
        captured_group_sends: Recorded channel sends from the fixture.

    Returns:
        Routed coarse-group envelopes in delivery order.
    """
    coarse = _RoutedSubscription._group_name("create")
    return [
        message
        for group, message in captured_group_sends
        if group == coarse and message.get("stream") == "routed_commit"
    ]


def test_routed_save_waits_for_secondary_commit(
    routed_database: SubscriptionBinding,
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """A routed write emits once only after its own transaction commits.

    Args:
        routed_database: Registered binding and disposable secondary table.
        captured_group_sends: Recorded channel sends.
    """
    with transaction.atomic(using="routed"):
        instance = RoutedCommitModel.objects.create(text="secondary commit")
        assert instance._state.db == "routed"
        assert _stream_messages(captured_group_sends) == []

    messages = _stream_messages(captured_group_sends)
    assert len(messages) == 1
    assert messages[0]["pk"] == instance.pk
    assert messages[0]["payload"]["data"] == {"id": instance.pk}


def test_routed_save_rollback_discards_notification(
    routed_database: SubscriptionBinding,
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """Rollback of the routed alias discards its pending notification.

    Args:
        routed_database: Registered binding and disposable secondary table.
        captured_group_sends: Recorded channel sends.

    Raises:
        ValueError: Intentionally inside the assertion scope to roll back the
            routed transaction; it does not escape the test.
    """
    with pytest.raises(ValueError, match="routed rollback"):
        with transaction.atomic(using="routed"):
            RoutedCommitModel.objects.create(text="rolled back")
            assert _stream_messages(captured_group_sends) == []
            raise ValueError("routed rollback")

    assert _stream_messages(captured_group_sends) == []
    assert (
        not RoutedCommitModel.objects.using("routed")
        .filter(text="rolled back")
        .exists()
    )


def test_default_transaction_does_not_capture_secondary_autocommit(
    routed_database: SubscriptionBinding,
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """A default transaction cannot delay an independent routed commit.

    Args:
        routed_database: Registered binding and disposable secondary table.
        captured_group_sends: Recorded channel sends.
    """
    with transaction.atomic(using="default"):
        instance = RoutedCommitModel.objects.create(text="secondary autocommit")
        assert instance._state.db == "routed"
        assert len(_stream_messages(captured_group_sends)) == 1


def test_routed_delete_waits_for_commit(
    routed_database: SubscriptionBinding,
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """The shared delete callback also follows its secondary transaction.

    Args:
        routed_database: Registered binding and disposable secondary table.
        captured_group_sends: Recorded channel sends.
    """
    instance = RoutedCommitModel.objects.create(text="delete later")
    captured_group_sends.clear()
    with transaction.atomic(using="routed"):
        instance.delete()
        assert captured_group_sends == []
    delete_group = _RoutedSubscription._group_name("delete")
    assert sum(group == delete_group for group, _ in captured_group_sends) == 1


def test_missing_layer_warning_follows_secondary_commit(
    routed_database: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A missing-layer warning follows commit and disappears on rollback.

    Args:
        routed_database: Registered binding and disposable secondary table.
        monkeypatch: Removes the channel layer only for this test.
        caplog: Records the automatic delivery warning.

    Raises:
        ValueError: Intentionally inside the assertion scope to discard the
            first warning; it does not escape the test.
    """
    monkeypatch.setattr(
        "django_graphex.subscriptions.bindings.get_channel_layer", lambda: None
    )

    def warnings() -> list[str]:
        """Return warning messages emitted for this test's routed model.

        Returns:
            The missing-layer warning messages in emission order.
        """
        return [
            record.message
            for record in caplog.records
            if "No channel layer configured; dropping" in record.message
        ]

    with pytest.raises(ValueError, match="discard warning"):
        with transaction.atomic(using="routed"):
            RoutedCommitModel.objects.create(text="no warning after rollback")
            assert warnings() == []
            raise ValueError("discard warning")
    assert warnings() == []

    with transaction.atomic(using="routed"):
        RoutedCommitModel.objects.create(text="warn after commit")
        assert warnings() == []
    assert len(warnings()) == 1
