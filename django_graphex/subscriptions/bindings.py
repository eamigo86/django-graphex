"""Provide the broadcast engine bridging Django signals to Channels group_send.

This replaces the deprecated "channels-api" "ResourceBinding". A binding
connects "post_save"/"post_delete" receivers for a model and, on each change,
serializes the instance once and fans the payload out to the relevant groups.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_delete, post_save

from .mixins import serialize_instance

if TYPE_CHECKING:
    from django.db.models import Model

    from .subscription import Subscription

logger = logging.getLogger(__name__)


def _safe_group_send(
    channel_layer: Any, group_name: str, message: dict[str, Any]
) -> None:
    """Send *message* to *group_name* from a synchronous Django signal context.

    Django post_save / post_delete signals fire in the ORM's synchronous call
    stack.  Under a plain WSGI server there is no running event loop so the
    standard ``async_to_sync(channel_layer.group_send)(...)`` call works fine.
    Under an ASGI server (Daphne, Uvicorn) a loop IS running on the current
    thread.  Calling ``async_to_sync`` in that context creates a nested-loop
    situation that deadlocks.

    Safe pattern:
    - If no loop is running on the current thread → use ``async_to_sync``
      (the plain WSGI / Celery / management-command path).
    - If a loop IS running → schedule the coroutine on the running loop from a
      separate worker thread via ``run_coroutine_threadsafe``, which enqueues
      the coroutine safely without blocking the current thread or the loop.

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
        # ASGI path: a loop is running on this thread.  We must NOT block the
        # loop thread (future.result() on the same thread deadlocks).  Instead,
        # schedule the coroutine onto the running loop from a worker thread and
        # wait for completion there — leaving the loop thread free to process it.
        def _send_from_thread() -> None:
            future = asyncio.run_coroutine_threadsafe(
                channel_layer.group_send(group_name, message), loop
            )
            try:
                future.result(timeout=5)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "group_send to %s timed out; message may be dropped.", group_name
                )
            except Exception:  # noqa: BLE001
                logger.exception("group_send to %s raised.", group_name)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_send_from_thread).result()
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
        self.broadcast("create" if created else "update", instance)

    def _on_delete(self, sender: Any, instance: Model, **kwargs: Any) -> None:
        self.broadcast("delete", instance)

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
