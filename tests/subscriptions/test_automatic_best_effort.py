"""Automatic model notifications must not turn a successful write into an error."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

from django_graphex.subscriptions import Subscription
from django_graphex.subscriptions.bindings import (
    SubscriptionBinding,
    _inflight_tasks,
    _safe_group_send,
)
from tests.models import HookModel
from tests.subscriptions.schema import UserSubscription
from tests.test_views_atomic_errors import _operation, _post

pytestmark = pytest.mark.django_db(transaction=True)


class _AutomaticFullSubscription(Subscription):
    """Use a distinct full-payload stream for actual ORM signal controls."""

    class Meta:
        model = HookModel
        stream = "automatic_best_effort"
        payload_mode = "full"


@pytest.fixture
def binding() -> Generator[SubscriptionBinding, None, None]:
    """Connect the subscription only for the duration of each test.

    Yields:
        The registered binding, removed after the test.
    """
    current = _AutomaticFullSubscription.get_binding()
    current.register()
    yield current
    current.unregister()


def test_snapshot_failure_does_not_abort_atomic_save(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing full-payload snapshot must not undo a valid model insert.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Replaces only the notification serializer.
        caplog: Captures metadata-only failure diagnostics.

    Raises:
        AssertionError: If snapshot failure changes persistence or logs secrets.
    """
    secret = "private-payload-should-not-be-logged"

    def fail_serialization(
        cls: type[Subscription], instance: HookModel
    ) -> dict[str, Any]:
        """Raise a notification-only error after the ORM has inserted the row.

        Args:
            cls: The subscription class receiving the method call.
            instance: The newly saved model instance.

        Raises:
            ValueError: Always, to simulate failed payload preparation.
        """
        raise ValueError(secret)

    monkeypatch.setattr(
        _AutomaticFullSubscription,
        "_serialize_payload",
        classmethod(fail_serialization),
    )

    with transaction.atomic():
        row = HookModel.objects.create(text="saved-despite-notification-failure")

    assert HookModel.objects.filter(pk=row.pk).exists()
    assert any("automatic_best_effort" in record.message for record in caplog.records)
    assert secret not in caplog.text


def test_failed_snapshot_does_not_change_generated_mutation_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public generated create mutation still returns success and saves.

    Args:
        monkeypatch: Replaces only the automatic subscription serializer.

    Raises:
        AssertionError: If the generated mutation fails or does not persist.
    """
    binding = UserSubscription.get_binding()
    binding.register()

    def fail_serialization(cls: type[Subscription], instance: User) -> dict[str, Any]:
        """Raise after the mutation's model save reaches its signal receiver.

        Args:
            cls: The subscription class receiving the method call.
            instance: The created user.

        Raises:
            ValueError: Always, as an automatic notification failure.
        """
        raise ValueError("mutation-notification-only")

    monkeypatch.setattr(
        UserSubscription, "_serialize_payload", classmethod(fail_serialization)
    )
    status, payload = _post(_operation("a6_mutation", ""), atomic_mutations=True)

    assert status == 200
    assert payload.get("errors") is None
    assert payload["data"]["userCreate"]["ok"] is True
    assert User.objects.filter(username="a6_mutation").count() == 1


def test_failed_delivery_preserves_autocommit_update_and_delete(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automatic update and delete delivery cannot alter committed rows.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Replaces the channel layer after the initial insert.

    Raises:
        AssertionError: If failed delivery prevents an update or deletion.
    """
    from django_graphex.subscriptions import bindings

    row = HookModel.objects.create(text="before")
    pk = row.pk

    class FailingLayer:
        """Fail every synchronous automatic send."""

        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            """Raise an ordinary notification-only delivery error.

            Args:
                group: Destination group.
                message: Notification envelope.

            Raises:
                RuntimeError: Always, to simulate a failed group send.
            """
            raise RuntimeError("delivery-down")

    monkeypatch.setattr(bindings, "get_channel_layer", lambda: FailingLayer())
    row.text = "after"
    row.save(update_fields=["text"])
    row.refresh_from_db()
    assert row.text == "after"

    row.delete()
    assert not HookModel.objects.filter(pk=pk).exists()


def test_explicit_manual_broadcast_remains_strict(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort signal handling must not catch explicit broadcast errors.

    Args:
        binding: The registered binding used for the explicit call.
        monkeypatch: Replaces the channel layer and payload serializer.

    Raises:
        AssertionError: If explicit delivery stops propagating failures.
    """
    from django_graphex.subscriptions import bindings

    class FailingLayer:
        """Raise from the manual group send."""

        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            """Fail a manual delivery.

            Args:
                group: Destination group.
                message: Notification envelope.

            Raises:
                RuntimeError: Always, to prove strict propagation.
            """
            raise RuntimeError("manual-delivery-failed")

    monkeypatch.setattr(bindings, "get_channel_layer", lambda: FailingLayer())
    monkeypatch.setattr(
        _AutomaticFullSubscription,
        "_serialize_payload",
        classmethod(lambda cls, instance: {"text": instance.text}),
    )
    with pytest.raises(RuntimeError, match="manual-delivery-failed"):
        binding.broadcast("update", HookModel(pk=27, text="manual"))


def test_rollback_discards_automatic_failures_and_snapshots(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rollback drops deferred callbacks without attempting delivery.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Replaces the channel layer after snapshot preparation.
        caplog: Captures unexpected automatic failure diagnostics.

    Raises:
        AssertionError: If rollback emits an event or retains the row.
    """
    from django_graphex.subscriptions import bindings

    class FailingLayer:
        """Fail if rollback incorrectly executes a deferred send."""

        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            """Reject an unexpected delivery.

            Args:
                group: Destination group.
                message: Notification envelope.

            Raises:
                RuntimeError: Always, if invoked.
            """
            raise RuntimeError("should-not-send")

    monkeypatch.setattr(bindings, "get_channel_layer", lambda: FailingLayer())
    with pytest.raises(ValueError, match="rollback requested"):
        with transaction.atomic():
            HookModel.objects.create(text="discarded")
            raise ValueError("rollback requested")

    assert not HookModel.objects.filter(text="discarded").exists()
    assert "Automatic notification dropped" not in caplog.text


def test_async_automatic_failure_logs_only_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A scheduled automatic send consumes its exception without payload logs.

    Args:
        caplog: Captures the asynchronous task's failure diagnostic.

    Raises:
        AssertionError: If the task or its logs expose notification contents.
    """
    secret = "secret-async-notification-error"

    class FailingLayer:
        """Fail after an automatic task is scheduled on the active loop."""

        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            """Raise from the scheduled task.

            Args:
                group: Destination group.
                message: Notification envelope.

            Raises:
                RuntimeError: Always, to exercise the done callback.
            """
            raise RuntimeError(secret)

    async def exercise() -> None:
        """Schedule a real event-loop task and let its callback complete."""
        _safe_group_send(
            FailingLayer(),
            "secret-group",
            {"payload": "secret-payload"},
            automatic_context=("tests.HookModel", "automatic_best_effort", "update"),
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(exercise())
    assert _inflight_tasks == set()
    assert "exception=RuntimeError" in caplog.text
    assert secret not in caplog.text
    assert "secret-group" not in caplog.text
    assert "secret-payload" not in caplog.text


def test_base_exception_is_not_swallowed(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation-like control exceptions retain their existing propagation.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Injects a BaseException at snapshot preparation.

    Raises:
        AssertionError: If the control-flow exception is swallowed.
    """

    def interrupt(cls: type[Subscription], instance: HookModel) -> dict[str, Any]:
        """Raise a control-flow exception rather than an ordinary failure.

        Args:
            cls: The subscription class receiving the method call.
            instance: The saved model instance.

        Raises:
            KeyboardInterrupt: Always, to prove it is not swallowed.
        """
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        _AutomaticFullSubscription, "_serialize_payload", classmethod(interrupt)
    )
    with pytest.raises(KeyboardInterrupt):
        HookModel.objects.create(text="interrupted")


def test_logging_backend_failure_does_not_abort_save(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure logging is also notification work, not a persistence failure.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Makes both snapshot creation and its logger fail.

    Raises:
        AssertionError: If logging failure prevents the database write.
    """
    from django_graphex.subscriptions import bindings

    def fail_serialization(
        cls: type[Subscription], instance: HookModel
    ) -> dict[str, Any]:
        """Raise while preparing an automatic payload.

        Args:
            cls: The subscription class receiving the method call.
            instance: The saved model instance.

        Raises:
            ValueError: Always, to exercise the failure logger.
        """
        raise ValueError("serializer down")

    def fail_log(*args: Any, **kwargs: Any) -> None:
        """Raise from the configured logging backend.

        Args:
            *args: The logging call arguments.
            **kwargs: The logging call keyword arguments.

        Raises:
            RuntimeError: Always, to simulate an unavailable logging backend.
        """
        raise RuntimeError("logger down")

    monkeypatch.setattr(
        _AutomaticFullSubscription,
        "_serialize_payload",
        classmethod(fail_serialization),
    )
    monkeypatch.setattr(bindings.logger, "error", fail_log)
    row = HookModel.objects.create(text="survives-logger")
    assert HookModel.objects.filter(pk=row.pk).exists()


def test_database_write_error_remains_strict(
    binding: SubscriptionBinding,
) -> None:
    """Automatic notification handling cannot turn a DB write error into success.

    Args:
        binding: The registered automatic notification binding.
    """
    row = HookModel.objects.create(text="first")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            HookModel.objects.create(pk=row.pk, text="duplicate-primary-key")
    assert HookModel.objects.get(pk=row.pk).text == "first"


def test_broken_notification_transaction_still_propagates_database_error(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An internal DB failure cannot be hidden while atomic is unusable.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Injects a database error into snapshot preparation.

    Raises:
        AssertionError: If the broken transaction incorrectly commits a row.
    """
    existing = HookModel.objects.create(text="existing")

    def fail_inside_database(
        cls: type[Subscription], instance: HookModel
    ) -> dict[str, Any]:
        """Make a real duplicate-key write while preparing a payload.

        Args:
            cls: The subscription class receiving the method call.
            instance: The saved model instance.

        Raises:
            IntegrityError: The duplicate primary key breaks the transaction.
        """
        HookModel.objects.create(pk=existing.pk, text="duplicate")
        return {}

    monkeypatch.setattr(
        _AutomaticFullSubscription,
        "_serialize_payload",
        classmethod(fail_inside_database),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            HookModel.objects.create(text="should-rollback")
    assert not HookModel.objects.filter(text="should-rollback").exists()


def test_missing_layer_warning_backend_failure_is_best_effort(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed warning handler cannot stop a later on-commit callback.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Simulates a missing layer and failed warning handler.
        caplog: Captures the fallback metadata-only error.

    Raises:
        AssertionError: If the valid insert or later callback is lost.
    """
    from django_graphex.subscriptions import bindings

    def fail_warning(*args: Any, **kwargs: Any) -> None:
        """Raise from a warning logger that cannot accept messages.

        Args:
            *args: The warning format and values.
            **kwargs: Additional logger options.

        Raises:
            RuntimeError: Always, to simulate a broken logging backend.
        """
        raise RuntimeError("private-warning-failure")

    monkeypatch.setattr(bindings, "get_channel_layer", lambda: None)
    monkeypatch.setattr(bindings.logger, "warning", fail_warning)
    later: list[str] = []
    with transaction.atomic():
        row = HookModel.objects.create(text="warn-only")
        transaction.on_commit(lambda: later.append("continued"))
    assert HookModel.objects.filter(pk=row.pk).exists()
    assert later == ["continued"]
    assert "stage=delivery" in caplog.text
    assert "private-warning-failure" not in caplog.text


def test_send_failure_keeps_committed_write_and_later_callback(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed automatic send must not interrupt later on-commit work.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Replaces only the notification channel layer.
        caplog: Captures metadata-only failure diagnostics.

    Raises:
        AssertionError: If a later callback is skipped or private data is logged.
    """
    from django_graphex.subscriptions import bindings

    secret = "private-send-error-should-not-be-logged"

    class FailingLayer:
        """Raise from a channel delivery after the database commits."""

        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            """Fail without exposing the group name or payload in diagnostics.

            Args:
                group: The destination group.
                message: The notification envelope.

            Raises:
                RuntimeError: Always, to simulate a delivery outage.
            """
            raise RuntimeError(secret)

    monkeypatch.setattr(bindings, "get_channel_layer", lambda: FailingLayer())
    later: list[str] = []

    with transaction.atomic():
        row = HookModel.objects.create(text="committed-before-send")
        transaction.on_commit(lambda: later.append("continued"))

    assert HookModel.objects.filter(pk=row.pk).exists()
    assert later == ["continued"]
    assert any("automatic_best_effort" in record.message for record in caplog.records)
    assert secret not in caplog.text


class _FirstGroupFailsLayer:
    """Record delivered groups and fail only the first send."""

    def __init__(self, secret: str) -> None:
        """Remember the failure text and start with no deliveries.

        Args:
            secret: Text placed in the raised exception message.
        """
        self.secret = secret
        self.sent: list[str] = []
        self.calls = 0

    async def group_send(self, group: str, message: dict[str, Any]) -> None:
        """Fail the first call and record the others.

        Args:
            group: Destination group.
            message: Notification envelope.

        Raises:
            RuntimeError: On the first call only.
        """
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(self.secret)
        self.sent.append(group)


def test_sync_fanout_isolates_failing_group(
    binding: SubscriptionBinding,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing first group must not stop delivery to the remaining groups.

    Args:
        binding: The registered automatic notification binding.
        monkeypatch: Installs the failing channel layer.
        caplog: Captures the diagnostic for the failed group.

    Raises:
        AssertionError: If later groups are skipped or the log lacks detail.
    """
    from django_graphex.subscriptions import bindings

    layer = _FirstGroupFailsLayer("secret-redis-detail")
    monkeypatch.setattr(bindings, "get_channel_layer", lambda: layer)
    binding._broadcast_snapshot("create", 5, {"k": "v"}, {"id": 5, "text": "x"})

    assert layer.calls == 4
    assert len(layer.sent) == 3
    assert caplog.text.count("Automatic notification dropped") == 1
    assert "stage=delivery" in caplog.text
    assert "exception=RuntimeError" in caplog.text
    assert "secret-redis-detail" not in caplog.text


def test_manual_sync_send_still_raises() -> None:
    """A manual synchronous send keeps propagating its delivery error.

    Raises:
        AssertionError: If the manual error is swallowed.
    """
    with pytest.raises(RuntimeError, match="manual-boom"):
        _safe_group_send(_FirstGroupFailsLayer("manual-boom"), "g", {"type": "t"})


def test_drop_log_names_cause_chain(caplog: pytest.LogCaptureFixture) -> None:
    """The drop log names the qualified error class and its cause.

    Args:
        caplog: Captures the drop diagnostic.

    Raises:
        AssertionError: If the chain is missing or the message leaks.
    """
    from django_graphex.subscriptions.bindings import _log_automatic_drop

    try:
        try:
            raise ConnectionError("secret-low-level")
        except ConnectionError as low:
            raise LookupError("secret-high-level") from low
    except LookupError as error:
        _log_automatic_drop("tests.HookModel", "s", "create", "delivery", error)

    assert "exception=LookupError <- ConnectionError" in caplog.text
    assert "secret" not in caplog.text
