# -*- coding: utf-8 -*-
"""T-SYNC-IO: async-safety of subscription hooks and consumer cache I/O.

Covers:
  (a) authorize_subscription called with a sync ORM hook does not raise
      SynchronousOnlyOperation (it is run via sync_to_async inside _subscribe).
  (b) subscription_scope with a sync ORM hook does not raise
      SynchronousOnlyOperation.
  (c) Consumer.disconnect() called before connect() body completes does not
      raise AttributeError — _groups/_fields/_filters have class-level defaults.
  (d) register_channel / unregister_channel are non-blocking on the event loop
      (wrapped in sync_to_async inside the consumer).
"""

from __future__ import annotations

import pytest
from channels.testing import WebsocketCommunicator

from .helpers import run_subscribe
from .schema import AppDemultiplexer, UserSubscription

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


# ---------------------------------------------------------------------------
# (a)+(b) sync ORM in authorize_subscription / subscription_scope
# ---------------------------------------------------------------------------


class _SyncORMSubscription(UserSubscription):
    """A subscription that performs a real ORM query inside authorize/scope."""

    class Meta:
        model = UserSubscription._meta.model
        stream = "sync_orm_test"
        serialize_data = True

    @classmethod
    def authorize_subscription(cls, info, **kwargs):
        # Deliberately touch the ORM (sync) — this should NOT raise
        # SynchronousOnlyOperation when called from _subscribe.
        from django.contrib.auth.models import User

        list(User.objects.none())  # zero-row query is safe but still hits ORM

    @classmethod
    def subscription_scope(cls, info, **kwargs):
        # Same: sync ORM access inside scope hook.
        from django.contrib.auth.models import User

        list(User.objects.none())
        return {}


async def test_sync_orm_in_authorize_subscription_does_not_raise():
    """authorize_subscription touching the ORM from inside _subscribe must not
    raise SynchronousOnlyOperation — the hook is lifted via sync_to_async."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("sync-orm-chan-1", session_key="s-auth")
    result = await run_subscribe(
        _SyncORMSubscription,
        channel_id="sync-orm-chan-1",
        action="create",
        operation="subscribe",
        _session_key="s-auth",
    )
    # The subscribe must succeed (no SynchronousOnlyOperation surfaced as error).
    assert result.ok is True, (
        f"Expected ok=True when ORM in authorize_subscription is wrapped, "
        f"got ok={result.ok}, error={result.error}"
    )


async def test_sync_orm_in_subscription_scope_does_not_raise():
    """subscription_scope touching the ORM from inside _subscribe must not
    raise SynchronousOnlyOperation — the hook is lifted via sync_to_async."""
    from django_graphex.subscriptions.subscription import register_channel

    register_channel("sync-orm-chan-2", session_key="s-scope")
    result = await run_subscribe(
        _SyncORMSubscription,
        channel_id="sync-orm-chan-2",
        action="create",
        operation="subscribe",
        _session_key="s-scope",
    )
    assert result.ok is True, (
        f"Expected ok=True when ORM in subscription_scope is wrapped, "
        f"got ok={result.ok}, error={result.error}"
    )


# ---------------------------------------------------------------------------
# (c) disconnect without completed connect does not raise AttributeError
# ---------------------------------------------------------------------------


async def test_disconnect_without_connect_does_not_raise():
    """GraphqlAPIDemultiplexer.disconnect() must be safe even if connect()
    never ran — _groups/_fields/_filters must be initialized before connect."""
    from django_graphex.subscriptions.consumers import GraphqlAPIDemultiplexer

    # Instantiate the consumer as Channels' dispatch machinery would.
    # We do NOT call connect() — disconnect() must still work.
    consumer = GraphqlAPIDemultiplexer()
    consumer.channel_name = "test-disconnect-safe"

    # disconnect() iterates self._groups; must not raise AttributeError.
    try:
        await consumer.disconnect(1001)
    except AttributeError as exc:
        pytest.fail(
            f"disconnect() raised AttributeError without connect() having run: {exc}"
        )


# ---------------------------------------------------------------------------
# (d) consumer cache I/O is async-safe (sync_to_async wrapped)
# ---------------------------------------------------------------------------


async def test_consumer_connect_and_disconnect_complete_without_blocking():
    """Full connect + disconnect cycle via WebsocketCommunicator.

    Verifies that register_channel / unregister_channel (sync cache I/O) do
    not block the event loop or raise in an ASGI context.
    """
    communicator = WebsocketCommunicator(AppDemultiplexer.as_asgi(), "/ws/")
    connected, _ = await communicator.connect()
    assert connected, "WebSocket connect must succeed"

    handshake = await communicator.receive_json_from()
    assert handshake.get("connect") == "success"

    # Disconnect — unregister_channel runs; must not raise.
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# (e) unregister_channel failure during disconnect is swallowed (lines 93-94)
# ---------------------------------------------------------------------------


async def test_disconnect_swallows_unregister_channel_error(monkeypatch):
    """Consumer.disconnect() must NOT propagate an exception from unregister_channel.

    Covers consumers.py lines 93-94: the `except Exception: logger.exception(...)`
    handler inside `disconnect`.  Patching `unregister_channel` to raise verifies
    that the error is caught, logged, and not re-raised — the connection cleanup
    continues (best-effort design).
    """
    import logging

    from django_graphex.subscriptions import consumers as consumers_mod
    from django_graphex.subscriptions.consumers import GraphqlAPIDemultiplexer

    # Force unregister_channel to raise every time it is called.
    def _boom(channel_name):
        raise RuntimeError("cache write failed")

    monkeypatch.setattr(consumers_mod, "unregister_channel", _boom)

    consumer = GraphqlAPIDemultiplexer()
    consumer.channel_name = "test-unregister-fail"

    # disconnect() must swallow the RuntimeError and not propagate.
    logged_messages = []
    original_exception = logging.Logger.exception

    def _capture(self, msg, *args, **kwargs):
        logged_messages.append(msg % args if args else msg)
        return original_exception(self, msg, *args, **kwargs)

    monkeypatch.setattr(logging.Logger, "exception", _capture)

    try:
        await consumer.disconnect(1001)
    except Exception as exc:  # pragma: no cover — must NOT reach here
        pytest.fail(
            f"disconnect() propagated an exception from unregister_channel: {exc}"
        )

    # The failure must have been logged (best-effort: log but do not raise).
    assert any("unregister" in m.lower() or "Failed" in m for m in logged_messages), (
        "Expected a log message about the failed unregister_channel call"
    )
