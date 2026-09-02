"""Provide the broadcast engine bridging Django signals to Channels group_send.

This replaces the deprecated "channels-api" "ResourceBinding". A binding
connects "post_save"/"post_delete" receivers for a model and, on each change,
serializes the instance once and fans the payload out to the relevant groups.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
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
        action = "create" if created else "update"
        self._defer_snapshot(action, instance)

    def _on_delete(self, sender: Any, instance: Model, **kwargs: Any) -> None:
        self._defer_snapshot("delete", instance)

    def _defer_snapshot(self, action: str, instance: Model) -> None:
        """Capture event state without retaining the mutable model instance."""
        if get_channel_layer() is None:
            transaction.on_commit(
                lambda action=action: self._warn_missing_channel_layer(action)
            )
            return

        pk_snapshot = deepcopy(instance.pk)
        index_snapshot = deepcopy(self.subscription_cls._instance_index(instance))
        if self.subscription_cls._payload_is_full():
            data_snapshot: dict[str, Any] | None = (
                self.subscription_cls._serialize_payload(instance)
            )
        else:
            data_snapshot = None

        transaction.on_commit(
            lambda action=action,
            pk_snapshot=pk_snapshot,
            index_snapshot=index_snapshot,
            data_snapshot=data_snapshot: self._broadcast_snapshot(
                action, pk_snapshot, index_snapshot, data_snapshot
            )
        )

    def _warn_missing_channel_layer(self, action: str) -> None:
        """Log an event dropped because Channels is not configured."""
        logger.warning(
            "No channel layer configured; dropping %s notification for %s.",
            action,
            self.model_label,
        )

    # -- broadcast ----------------------------------------------------------
    def _broadcast_snapshot(
        self,
        action: str,
        pk_snapshot: Any,
        index_snapshot: dict[str, Any] | None,
        data_snapshot: dict[str, Any] | None,
    ) -> None:
        """Broadcast pre-captured state after commit without a model instance.

        Every value comes from the signal-time snapshot, so a later save or
        delete of the same Python object cannot rewrite an earlier event.

        Args:
            action: The create, update or delete action captured at signal time.
            pk_snapshot: The primary key captured at signal time.
            index_snapshot: The routing index captured at signal time.
            data_snapshot: Pre-serialized payload (non-None when
                "payload_mode='full'"), or "None" for id-only mode.
        """
        channel_layer = get_channel_layer()
        if channel_layer is None:  # pragma: no cover - misconfiguration guard
            logger.warning(
                "No channel layer configured; dropping %s notification for %s.",
                action,
                self.model_label,
            )
            return

        if data_snapshot is not None:
            data: dict[str, Any] = data_snapshot
        else:
            # Key by the model's REAL primary-key field name: the event type
            # declares the pk under that name (a "slug" pk renders "slug: String!"),
            # so a hardcoded "id" would deliver a null on a non-nullable field.
            data = {self.model._meta.pk.name: pk_snapshot}

        payload = {
            "action": action,
            "model": self.model_label,
            "data": data,
        }

        cls = self.subscription_cls
        group_names = [
            cls._group_name(action),
            cls._group_name(action, id=pk_snapshot),
        ]
        if index_snapshot:
            group_names.append(cls._group_name(action, index=index_snapshot))
            group_names.append(
                cls._group_name(action, id=pk_snapshot, index=index_snapshot)
            )

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
            # Same as "_broadcast_delete": the payload key is the model's real
            # primary-key field name, not the literal "id".
            data = {self.model._meta.pk.name: instance.pk}

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
