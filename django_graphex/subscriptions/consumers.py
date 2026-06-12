"""Provide the WebSocket consumer preserving the two-channel wire protocol."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import FieldError

from .bindings import SubscriptionBinding
from .mixins import project_fields, split_filters
from .subscription import register_channel, unregister_channel

if TYPE_CHECKING:
    from .subscription import Subscription

logger = logging.getLogger(__name__)


class GraphqlAPIDemultiplexer(AsyncJsonWebsocketConsumer):
    """Provide the base consumer users subclass to expose their subscriptions.

    Declare the subscriptions a connection serves::

        class AppDemultiplexer(GraphqlAPIDemultiplexer):
            subscriptions = {"users": UserSubscription}

    On connect it accepts the socket, ensures the signal bindings are wired and
    sends the handshake frame {"channel_id": ..., "connect": "success"} the
    client echoes back as "channelId" when subscribing over HTTP.
    """

    #: Mapping of stream to "Subscription" subclass. Set by the subclass.
    subscriptions = {}

    async def connect(self) -> None:
        """Accept the socket, wire bindings and emit the handshake frame.

        The channel is registered in the ownership registry keyed by the
        Django session key (or, for anonymous connections, an empty string).
        The same key is expected in ``_session_key`` when the client sends
        a subscribe mutation over HTTP.
        """
        self._fields = {}
        self._filters = {}
        self._groups = set()

        # Ensure the model signal bindings are connected (idempotent).
        for subscription_cls in self._resolved_subscriptions().values():
            subscription_cls.get_binding()

        await self.accept()

        # Derive a stable per-connection ownership token from the session.
        # scope["session"] is an instance of channels' SessionStore which
        # exposes .session_key; fall back to an empty string for anonymous
        # connections without a session backend configured.
        session = self.scope.get("session")
        session_key: str = getattr(session, "session_key", None) or ""
        register_channel(self.channel_name, session_key=session_key)

        await self.send_json({"channel_id": self.channel_name, "connect": "success"})

    async def disconnect(self, code: int) -> None:
        """Best-effort removal from every group this connection joined.

        Args:
            code: The WebSocket close code.
        """
        # Remove the channel from the ownership registry so stale entries do
        # not allow reconnected channels with the same name to be claimed by
        # the wrong session.
        unregister_channel(self.channel_name)

        for group_name in list(self._groups):
            try:
                await self.channel_layer.group_discard(group_name, self.channel_name)
            except Exception:  # noqa: BLE001 - disconnect must not raise
                logger.exception(
                    "Failed to discard %s from group %s",
                    self.channel_name,
                    group_name,
                )

    # -- control messages (sent by the resolver to *this* channel) ----------
    async def subscription_register(self, event: dict[str, Any]) -> None:
        """Record the requested field projection for the event group.

        Args:
            event: The control message carrying the "group" and "fields".
        """
        group_name = event["group"]
        self._fields[group_name] = event.get("fields")
        self._filters[group_name] = event.get("filters")
        self._groups.add(group_name)

    async def subscription_deregister(self, event: dict[str, Any]) -> None:
        """Drop the projection/membership bookkeeping for a group.

        Args:
            event: The control message carrying the "group" to drop.
        """
        group_name = event["group"]
        self._fields.pop(group_name, None)
        self._filters.pop(group_name, None)
        self._groups.discard(group_name)

    # -- broadcast delivery (sent by the binding to the group) --------------
    async def subscription_notify(self, event: dict[str, Any]) -> None:
        """Project the payload to the requested fields and push to the client.

        Args:
            event: The broadcast message carrying the "stream", "group" and
                "payload".
        """
        payload = dict(event["payload"])
        group_name = event.get("group")

        filters = self._filters.get(group_name)
        if filters and not await self._matches_filters(event, payload, filters):
            return

        fields = self._fields.get(group_name)
        payload["data"] = project_fields(payload.get("data"), fields)
        await self.send_json({"stream": event.get("stream"), "payload": payload})

    async def _matches_filters(
        self, event: dict[str, Any], payload: dict[str, Any], filters: dict[str, Any]
    ) -> bool:
        """Decide whether the changed instance matches this group's filters.

        Plain-equality filters present in the payload are settled in memory; the
        rest fall back to a single-row database check. A bad lookup fails closed.

        Args:
            event: The broadcast envelope (carries the stream and instance pk).
            payload: The notification payload (carries the serialized data).
            filters: The per-subscriber filters stored for this group.

        Returns:
            "True" when the notification should be delivered.
        """
        remaining = split_filters(payload.get("data"), filters)
        if remaining is None:
            return False  # an in-memory comparison already failed
        if not remaining:
            return True  # fully matched in memory -- no database hit

        subscription_cls = self._resolved_subscriptions().get(event.get("stream"))
        pk = event.get("pk")
        if subscription_cls is None or pk is None:
            return False  # cannot verify -> fail closed (e.g. delete + DB lookup)
        model = subscription_cls._meta.model

        def _exists() -> bool:
            try:
                return model.objects.filter(pk=pk, **remaining).exists()
            except (FieldError, ValueError, TypeError):
                logger.warning(
                    "Invalid subscription filter %s for %s; dropping notification.",
                    remaining,
                    model.__name__,
                )
                return False

        return await database_sync_to_async(_exists)()

    # -- helpers ------------------------------------------------------------
    def _resolved_subscriptions(self) -> dict[str, type[Subscription]]:
        """Normalize the "subscriptions" mapping or iterable.

        "subscriptions" may be a "{stream: Subscription}" mapping or an iterable
        (set/list) of "Subscription" subclasses / "DjangoModelType" classes,
        in which case the stream is derived from each one's "Meta.stream".

        Returns:
            A mapping of stream name to "Subscription" subclass.
        """
        resolved = {}
        subscriptions = self.subscriptions or {}
        if isinstance(subscriptions, dict):
            items = list(subscriptions.items())
        else:
            items = [(None, value) for value in subscriptions]
        for stream, value in items:
            subscription_cls = self._resolve_subscription(value)
            resolved[stream or subscription_cls._meta.stream] = subscription_cls

        return resolved

    @staticmethod
    def _resolve_subscription(value: Any) -> type[Subscription]:
        """Resolve a value into its ``Subscription`` subclass.

        Accepts a ``Subscription`` subclass, a ``SubscriptionBinding``, an object
        exposing ``subscription_cls``, or a ``DjangoModelType``.

        Args:
            value: A "Subscription" subclass, a "SubscriptionBinding", an object
                exposing "subscription_cls", or a "DjangoModelType" (which
                exposes "subscription_type()").

        Returns:
            The resolved "Subscription" subclass.
        """
        if isinstance(value, SubscriptionBinding):
            return value.subscription_cls
        if hasattr(value, "subscription_cls"):
            return value.subscription_cls
        if hasattr(value, "subscription_type"):  # DjangoModelType
            return value.subscription_type()
        return value


__all__ = ["GraphqlAPIDemultiplexer"]
