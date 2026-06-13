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

from .mixins import serialize_instance

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
    """Send *message* to *group_name* from a synchronous Django signal context.

    Django post_save / post_delete signals fire in the ORM's synchronous call
    stack.  Two execution environments must be handled:

    * **No running loop on the current thread** (plain WSGI, Celery, management
      commands): ``async_to_sync(channel_layer.group_send)(...)`` is safe and
      is used directly.
    * **A loop IS running on the current thread** (ASGI server — Daphne,
      Uvicorn): calling ``async_to_sync`` would create a nested-loop deadlock.
      Instead, the coroutine is scheduled on the running loop via
      ``loop.create_task`` and this function returns **immediately** (fire-and-
      forget).  The loop processes the task on its next turn without any thread
      blocking.  The old executor + ``run_coroutine_threadsafe(...).result()``
      pattern blocked the loop thread waiting for a future that could never
      resolve — causing a 5-second stall and a spurious "message may be dropped"
      warning.

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
        """Idempotently connect the "post_save"/"post_delete" receivers."""
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
        """Disconnect the receivers (mainly useful for tests)."""
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
        # Same deferred-broadcast pattern as _on_save.  Note: post_delete fires
        # while the row is still present in the database within the transaction;
        # the callback runs after the DELETE commits so subscribers only see
        # notifications for rows that were actually removed.
        transaction.on_commit(lambda: self.broadcast("delete", instance))

    # -- broadcast ----------------------------------------------------------
    def broadcast(self, action: str, instance: Model) -> None:
        """Serialize once and fan out to the action and per-pk groups.

        Args:
            action: The change action, one of "create", "update" or "delete".
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
        if self.subscription_cls._should_serialize_data():
            data = serialize_instance(self.backend, instance)
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
