"""Provide the broadcast engine bridging Django signals to Channels group_send.

This replaces the deprecated "channels-api" "ResourceBinding". A binding
connects "post_save"/"post_delete" receivers for a model and, on each change,
serializes the instance once and fans the payload out to the relevant groups.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models.signals import post_delete, post_save

if TYPE_CHECKING:  # pragma: no cover
    from django.db.models import Model

    from .subscription import Subscription

logger = logging.getLogger(__name__)

# Strong references to in-flight fire-and-forget tasks.  asyncio only keeps a
# weak reference to tasks; without this set a task can be garbage-collected
# before its done-callback fires, silently dropping the error log.
_inflight_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


def _group_send_done(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    """Done-callback for fire-and-forget group_send tasks.

    Retrieves any exception so asyncio does not emit 'Task exception was never
    retrieved', and logs it via the module logger for structured diagnostics.
    CancelledError is swallowed silently (the task was intentionally cancelled).
    """
    _inflight_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception(
            "Unhandled exception in fire-and-forget group_send task; "
            "message may have been dropped."
        )


def _safe_group_send(
    channel_layer: Any, group_name: str, message: dict[str, Any]
) -> None:
    """Send "message" to "group_name" from a synchronous Django signal context.

    Django post_save / post_delete signals fire in the ORM's synchronous call
    stack. Two execution environments must be handled:

    - No running loop on the current thread (plain WSGI, Celery, management
      commands): "async_to_sync(channel_layer.group_send)(...)" is safe and is
      used directly.
    - A loop IS running on the current thread (ASGI server — Daphne, Uvicorn):
      calling "async_to_sync" would create a nested-loop deadlock. Instead, the
      coroutine is scheduled on the running loop via "loop.create_task" and this
      function returns immediately (fire-and-forget). The loop processes the task
      on its next turn without any thread blocking. The old executor +
      "run_coroutine_threadsafe(...).result()" pattern blocked the loop thread
      waiting for a future that could never resolve — causing a 5-second stall
      and a spurious "message may be dropped" warning.

    Args:
        channel_layer: The Channels channel layer to send through.
        group_name: The group to broadcast to.
        message: The message payload.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # ASGI path: a loop is running on this thread.  Schedule the coroutine
        # as a fire-and-forget task on the already-running loop and return
        # immediately.  This avoids any blocking of the loop thread.
        task = loop.create_task(channel_layer.group_send(group_name, message))
        # Keep a strong reference so the task is not GC'd before the callback
        # fires, then attach the callback that logs any failure and releases it.
        _inflight_tasks.add(task)
        task.add_done_callback(_group_send_done)
    else:
        # WSGI / sync path: no running loop — async_to_sync is safe here.
        async_to_sync(channel_layer.group_send)(group_name, message)


class SubscriptionBinding:
    """Wire model signals for a single "Subscription" subclass.

    Registration is idempotent: receivers are connected with a stable
    "dispatch_uid" so building the same binding twice never double-fires.
    """

    def __init__(self, subscription_cls: type[Subscription]) -> None:
        """Capture the subscription's model/serializer and wire its signals.

        Args:
            subscription_cls: The "Subscription" subclass to bind signals for.
        """
        self.subscription_cls = subscription_cls
        self.model = subscription_cls._meta.model
        self.stream = subscription_cls._meta.stream
        self.backend = subscription_cls._meta.backend
        self.queryset = subscription_cls._meta.queryset
        self.register()

    @property
    def model_label(self) -> str:
        """Return the "app_label.modelname" identifier for the resolver groups.

        Returns:
            The model label matching the resolver's group names.
        """
        return self.subscription_cls.model_label()

    # -- signal registration ------------------------------------------------
    @property
    def _dispatch_uid(self) -> str:
        return f"gde-subscription-{self.model_label}-{self.stream}"

    def register(self) -> None:
        """Idempotently connect the "post_save"/"post_delete" receivers.

        Uses a stable "dispatch_uid" per model/stream so connecting the same
        binding twice never registers a second receiver (no double-fire).
        """
        post_save.connect(
            self._on_save,
            sender=self.model,
            dispatch_uid=f"{self._dispatch_uid}-save",
            weak=False,
        )
        post_delete.connect(
            self._on_delete,
            sender=self.model,
            dispatch_uid=f"{self._dispatch_uid}-delete",
            weak=False,
        )

    def unregister(self) -> None:
        """Disconnect the "post_save"/"post_delete" receivers.

        Mainly useful for tests that need to tear down the signal wiring the
        binding installed via "register".
        """
        post_save.disconnect(
            sender=self.model, dispatch_uid=f"{self._dispatch_uid}-save"
        )
        post_delete.disconnect(
            sender=self.model, dispatch_uid=f"{self._dispatch_uid}-delete"
        )

    # -- receivers ----------------------------------------------------------
    def _on_save(
        self,
        sender: Any,
        instance: Model,
        created: bool,
        **kwargs: Any,
    ) -> None:
        # Capture the action and a snapshot of the pk before deferring.
        # The instance is captured by the closure — its in-memory state is
        # consistent at signal time, and the serializer reads only already-set
        # attributes.  Deferring via on_commit guarantees the broadcast fires
        # only after the surrounding transaction commits; if the transaction
        # rolls back, the callback is discarded and subscribers receive no
        # phantom notification.  When no transaction is open, on_commit runs
        # the callback immediately (auto-commit behaviour is unchanged).
        action = "create" if created else "update"
        transaction.on_commit(lambda: self.broadcast(action, instance))

    def _on_delete(self, sender: Any, instance: Model, **kwargs: Any) -> None:
        # Snapshot the pk and (in serialize mode) the full payload *at signal
        # time*, before deferring to on_commit.  Django nulls instance.pk at the
        # end of Model.delete() — before the on_commit callback fires — so any
        # code that reads instance.pk inside the deferred lambda would see None.
        #
        # Two things happen at signal time that are correct here:
        #   * instance.pk is still set (the signal fires before the ORM clears it).
        #   * Scalar fields are still present on the in-memory instance.
        #   * M2M rows have already been cascade-deleted, so the payload
        #     serialization returns empty M2M lists — acceptable for a delete notification.
        #
        # Note: post_delete fires while the DELETE is still inside the open
        # transaction; the callback runs only after the transaction commits, so
        # subscribers never receive phantom notifications for rolled-back deletes.
        pk_snapshot = instance.pk
        if self.subscription_cls._payload_is_full():
            data_snapshot: dict[str, Any] | None = (
                self.subscription_cls._serialize_payload(instance)
            )
        else:
            data_snapshot = None

        transaction.on_commit(
            lambda: self._broadcast_delete(instance, pk_snapshot, data_snapshot)
        )

    # -- broadcast ----------------------------------------------------------
    def _broadcast_delete(
        self,
        instance: Model,
        pk_snapshot: Any,
        data_snapshot: dict[str, Any] | None,
    ) -> None:
        """Broadcast a delete notification using a pre-captured pk and payload.

        Called from the on_commit callback registered by "_on_delete". All
        pk-dependent values are derived from "pk_snapshot" (captured at signal
        time) rather than from "instance.pk", which Django sets to "None"
        during "Model.delete()" before the callback fires.

        Args:
            instance: The (now pk-less) model instance — used only for index
                field extraction via "_instance_index", which reads non-pk
                fields and is therefore safe to call with a pk-less instance.
            pk_snapshot: The primary key captured at post_delete signal time.
            data_snapshot: Pre-serialized payload (non-None when
                "payload_mode='full'"), or "None" for id-only mode.
        """
        channel_layer = get_channel_layer()
        if channel_layer is None:  # pragma: no cover - misconfiguration guard
            logger.warning(
                "No channel layer configured; dropping delete notification for %s.",
                self.model_label,
            )
            return

        if data_snapshot is not None:
            data: dict[str, Any] = data_snapshot
        else:
            data = {"id": pk_snapshot}

        payload = {
            "action": "delete",
            "model": self.model_label,
            "data": data,
        }

        cls = self.subscription_cls
        group_names = [
            cls._group_name("delete"),
            cls._group_name("delete", id=pk_snapshot),
        ]
        index = cls._instance_index(instance)
        if index:
            group_names.append(cls._group_name("delete", index=index))
            group_names.append(cls._group_name("delete", id=pk_snapshot, index=index))

        for group_name in group_names:
            message = {
                "type": "subscription.notify",
                "stream": self.stream,
                "group": group_name,
                # pk travels in the envelope so the consumer can run DB-backed
                # filters regardless of which fields the serializer exposes.
                "pk": pk_snapshot,
                "payload": payload,
            }
            _safe_group_send(channel_layer, group_name, message)

    def broadcast(self, action: str, instance: Model) -> None:
        """Serialize once and fan out to the action and per-pk groups.

        Used for "create" and "update" actions.  For "delete", use
        "_broadcast_delete" which accepts a pre-captured pk snapshot.

        Args:
            action: The change action, one of "create" or "update".
            instance: The model instance that changed.
        """
        channel_layer = get_channel_layer()
        if channel_layer is None:  # pragma: no cover - misconfiguration guard
            logger.warning(
                "No channel layer configured; dropping %s notification for %s.",
                action,
                self.model_label,
            )
            return

        # id-only (default) skips serialization entirely; full mode serializes
        # the instance once via the subscription's backend.
        if self.subscription_cls._payload_is_full():
            data = self.subscription_cls._serialize_payload(instance)
        else:
            data = {"id": instance.pk}

        payload = {
            "action": action,
            "model": self.model_label,
            "data": data,
        }

        # Always fan out to the coarse and per-pk groups (unscoped / per-object
        # subscribers). When the subscription declares index fields, also build
        # the value-scoped group names *from this instance* and send there -- the
        # names match the ones the subscribe side built from each subscriber's
        # scope, so only matching subscribers are reached (no group enumeration).
        cls = self.subscription_cls
        group_names = [
            cls._group_name(action),
            cls._group_name(action, id=instance.pk),
        ]
        index = cls._instance_index(instance)
        if index:
            group_names.append(cls._group_name(action, index=index))
            group_names.append(cls._group_name(action, id=instance.pk, index=index))

        for group_name in group_names:
            message = {
                "type": "subscription.notify",
                "stream": self.stream,
                "group": group_name,
                # pk travels in the envelope (not the client payload) so the
                # consumer can run DB-backed filters regardless of which
                # fields the serializer exposes.
                "pk": instance.pk,
                "payload": payload,
            }
            _safe_group_send(channel_layer, group_name, message)


__all__ = ["SubscriptionBinding"]
