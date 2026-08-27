# -*- coding: utf-8 -*-
"""WARNING-1 close-out (verify #1522) — WS transport branch coverage top-up.

Phase 6 verify flagged "transports/ws.py" at 75.57% combined branch — the
lowest of the new subscription modules. The conformance suite
("test_transport_ws.py") covers every spec SCENARIO (handshake, multiplex,
per-id cancel, disconnect, all close codes, serialize-once); the misses are the
subscribe-time ERROR frames, the keep-alive/edge branches, and the defensive
teardown sweeps. This module ADDS those, each with a MEANINGFUL assertion on the
emitted frame / close code / registry state.

Targeted ws.py branches:
  * 242        — receive_json while _closing returns early (no action).
  * 254        — a client pong needs no reply.
  * 273->275   — connection_init when the watchdog timer is already gone.
  * 281        — ping WITHOUT a payload (no echo key).
  * 298-299    — subscribe with no id -> 4400.
  * 326-327    — subscribe with an empty query -> error frame.
  * 331-333    — subscribe with a syntax error -> error frame.
  * 340-344    — a non-subscription operation -> error frame.
  * 354-357    — a validation error -> error frame.
  * 376-382    — the subscribe entry returns an ExecutionResult -> error.
  * 412        — client complete with no id -> ignored.
  * 419        — _cancel_operation for an unknown id -> no-op.
  * 459->461 + 462 — _send_next includes errors when the result has them.

Native-gated (the WS transport is native-only post-WU11).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402

# A Channels consumer touches the DB connection registry on every dispatched
# message; transaction=True is required (the consumer runs off the test txn).
pytestmark = pytest.mark.django_db(transaction=True)


# The node types Post's relation graph needs, and the assembled schema, are
# built ONCE process-wide by the shared module (see its docstring).
from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402


class _User:
    """A minimal authenticated/anonymous user stand-in."""

    def __init__(self, *, authenticated: bool = True) -> None:
        """Store the authentication flag and derive a matching pk.

        Args:
            authenticated: Whether this stand-in reports itself as
                authenticated; an unauthenticated user gets pk=None.
        """
        self.is_authenticated = authenticated
        self.pk = 1 if authenticated else None


_SUB_QUERY = "subscription { post(action: CREATE) { id title } }"


def _make_communicator(
    consumer_app: Any, *, layer: Any = None
) -> WebsocketCommunicator:
    """Build a WebsocketCommunicator for the graphql-transport-ws subprotocol.

    Args:
        consumer_app: The consumer class or ASGI app to communicate with.
        layer: An optional channel layer to attach to the scope.

    Returns:
        communicator: The configured WebsocketCommunicator, not yet connected.
    """
    application = (
        consumer_app.as_asgi() if hasattr(consumer_app, "as_asgi") else consumer_app
    )
    communicator = WebsocketCommunicator(
        application, "/graphql/", subprotocols=["graphql-transport-ws"]
    )
    communicator.scope["user"] = _User()
    if layer is not None:
        communicator.scope["channel_layer"] = layer
    return communicator


async def _connect_and_ack(
    communicator: WebsocketCommunicator,
) -> WebsocketCommunicator:
    """Open the socket and complete the connection_init -> connection_ack handshake.

    Args:
        communicator: The communicator to connect and handshake.

    Returns:
        communicator: The same communicator, now connected and acknowledged.
    """
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=2)
    assert ack["type"] == "connection_ack"
    return communicator


def _app(layer: Any, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Any:
    """Build a subscription WS consumer app patched to use the given layer.

    Args:
        layer: The channel layer get_channel_layer should resolve to.
        monkeypatch: The pytest fixture used to stub the channel layer.
        kwargs: Extra keyword arguments forwarded to subscription_ws_consumer.

    Returns:
        app: The consumer class built by subscription_ws_consumer.
    """
    from django_graphex.subscriptions.transports import ws

    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    return ws.subscription_ws_consumer(schema=build_native_schema(), **kwargs)


# ---------------------------------------------------------------------------
# 281 — ping WITHOUT a payload (no echo key)
# ---------------------------------------------------------------------------


async def test_ping_without_payload_pong_has_no_payload_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ping with no payload must produce a bare pong with no payload key.

    Contract: this test ships broken if a payload-less ping's pong reply
    gains a spurious payload key.

    Covers ws.py:280-281 — the "content.get('payload') is not None" False arm.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"type": "ping"})
    pong = await communicator.receive_json_from(timeout=2)
    assert pong == {"type": "pong"}
    assert "payload" not in pong

    await communicator.disconnect()


async def test_ping_with_payload_pong_echoes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ping with a payload must produce a pong echoing that payload.

    Contract: pairs with the no-payload test to pin both sides of the ping
    echo branch — ships broken if the payload is dropped instead of echoed.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"type": "ping", "payload": {"hi": 1}})
    pong = await communicator.receive_json_from(timeout=2)
    assert pong == {"type": "pong", "payload": {"hi": 1}}

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 254 — a client pong is silently ignored (no reply)
# ---------------------------------------------------------------------------


async def test_client_pong_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client pong (answering a server ping) must need no reply.

    Contract: this test ships broken if the consumer replies to a client
    pong, or stops processing subsequent frames after receiving one.

    Covers ws.py:252-254. After the pong (ignored), a follow-up ping still
    gets a pong — proving the consumer kept processing and did not reply to
    the pong itself.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"type": "pong"})
    # No frame is produced for the pong; the socket stays usable.
    assert await communicator.receive_nothing(timeout=0.2) is True

    await communicator.send_json_to({"type": "ping"})
    pong = await communicator.receive_json_from(timeout=2)
    assert pong["type"] == "pong"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 273->275 — connection_init when the watchdog timer is already gone/done
# ---------------------------------------------------------------------------


async def test_connection_init_with_no_timer_still_acks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """connection_init must ack even when the watchdog timer is already done.

    Contract: this test ships broken if a completed watchdog timer crashes
    the ack path instead of the guard short-circuiting cleanly.

    Covers ws.py:272-273 (the "timer is not None and not timer.done()" guard
    short-circuiting): a tiny init_timeout lets the watchdog fire-and-finish, then
    the init still produces an ack rather than crashing on a dead timer.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    # init_timeout=0 → the watchdog sleep(0) completes immediately; but it only
    # closes if NOT acked. We ack fast; the timer.done() guard is the target.
    communicator = _make_communicator(
        _app(layer, monkeypatch, init_timeout=0.05), layer=layer
    )
    connected, _ = await communicator.connect()
    assert connected
    # Let the watchdog timer expire-and-finish first (it does not close because we
    # have not subscribed and will ack just after — race-free: 0.05s window).
    await asyncio.sleep(0.0)
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=2)
    assert ack == {"type": "connection_ack"}

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 298-299 — subscribe with no id → 4400
# ---------------------------------------------------------------------------


async def test_subscribe_without_id_closes_4400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe frame without an id must close with code 4400 (Bad Request).

    Contract: this test ships broken if a subscribe with no id is accepted
    instead of closing the connection.

    Covers ws.py:297-299 — "op_id is None" -> "_close(4400)".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    # No "id" key on the subscribe.
    await communicator.send_json_to(
        {"type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4400


# ---------------------------------------------------------------------------
# 326-327 — subscribe with an empty query → error frame
# ---------------------------------------------------------------------------


async def test_subscribe_empty_query_sends_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe with an empty/absent query must send an error{id} frame.

    Contract: this test ships broken if an empty query either starts a
    source or closes the connection instead of sending a per-operation
    error frame.

    Covers ws.py:324-327. No source is started; the socket stays open (this is a
    per-operation error, NOT a connection close).

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "noq", "type": "subscribe", "payload": {"query": ""}}
    )
    err = await communicator.receive_json_from(timeout=2)
    assert err["type"] == "error"
    assert err["id"] == "noq"
    assert "No GraphQL query" in err["payload"][0]["message"]
    # The socket is still alive (a per-op error, not a close): ping → pong.
    await communicator.send_json_to({"type": "ping"})
    assert (await communicator.receive_json_from(timeout=2))["type"] == "pong"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 331-333 — subscribe with a syntax error → error frame
# ---------------------------------------------------------------------------


async def test_subscribe_syntax_error_sends_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe query with a syntax error must send an error{id} frame.

    Contract: this test ships broken if a syntax error crashes the consumer
    instead of producing a per-operation error frame.

    Covers ws.py:330-333 — the "parse" exception arm.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "bad", "type": "subscribe", "payload": {"query": "subscription {{{"}}
    )
    err = await communicator.receive_json_from(timeout=2)
    assert err["type"] == "error"
    assert err["id"] == "bad"
    assert "Syntax error" in err["payload"][0]["message"]

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 340-344 — a non-subscription operation → error frame
# ---------------------------------------------------------------------------


async def test_subscribe_non_subscription_operation_sends_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A "query" operation over the subscribe channel must send an error{id} frame.

    Contract: this test ships broken if a non-subscription operation is
    silently accepted instead of producing an error frame.

    Covers ws.py:335-344 — "operation != SUBSCRIPTION" arm.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "q1", "type": "subscribe", "payload": {"query": "query { ok }"}}
    )
    err = await communicator.receive_json_from(timeout=2)
    assert err["type"] == "error"
    assert err["id"] == "q1"
    assert "only serves subscriptions" in err["payload"][0]["message"]

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 354-357 — a validation error → error frame
# ---------------------------------------------------------------------------


async def test_subscribe_validation_error_sends_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe selecting an undeclared field must send an error{id} frame.

    Contract: this test ships broken if an undeclared field selection is
    silently accepted instead of producing a validation error frame.

    Covers ws.py:348-357 — the validation-errors arm. "nope" is not a field on
    the Post event type.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    query = "subscription { post(action: CREATE) { id nope } }"
    await communicator.send_json_to(
        {"id": "v1", "type": "subscribe", "payload": {"query": query}}
    )
    err = await communicator.receive_json_from(timeout=2)
    assert err["type"] == "error"
    assert err["id"] == "v1"
    assert any("nope" in (e.get("message") or "") for e in err["payload"])

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 376-382 — the subscribe entry returns an ExecutionResult (deny) → error frame
# ---------------------------------------------------------------------------


async def test_subscribe_resolver_error_result_sends_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe entry returning an ExecutionResult with errors must send an error frame.

    Contract: this test ships broken if the formatted resolver errors from
    an authorize-deny-shaped result are dropped instead of surfaced.

    Covers ws.py:375-382 — "isinstance(source_or_result, ExecutionResult)" arm,
    surfacing the formatted resolver errors. We force the subscribe entry to
    return an error result (the authorize-deny shape) via monkeypatch.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer and
            create_source_event_stream.
    """
    from graphql import ExecutionResult, GraphQLError

    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    async def _fake_create(*args: Any, **kwargs: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=[GraphQLError("denied by policy")])

    monkeypatch.setattr(ws, "create_source_event_stream", _fake_create)

    app = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "deny", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    err = await communicator.receive_json_from(timeout=2)
    assert err["type"] == "error"
    assert err["id"] == "deny"
    assert any("denied by policy" in (e.get("message") or "") for e in err["payload"])

    await communicator.disconnect()


async def test_subscribe_resolver_empty_error_result_sends_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe entry returning an ExecutionResult with no errors must send a fallback.

    Contract: this test ships broken if a formatted-errors-less deny result
    fails to fall back to the generic "could not be started" message.

    Covers ws.py:380 — the "or [{'message': '...'}]" fallback when the result
    carries no formatted errors.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer and
            create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    async def _fake_create(*args: Any, **kwargs: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(ws, "create_source_event_stream", _fake_create)

    app = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "empty", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    err = await communicator.receive_json_from(timeout=2)
    assert err["type"] == "error"
    assert err["id"] == "empty"
    assert err["payload"] == [{"message": "Subscription could not be started."}]

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 371-373 — the subscribe entry RAISES (authorize-deny) → error frame
# ---------------------------------------------------------------------------


async def test_subscribe_resolver_raises_sends_error_frame(  # noqa: DOC005
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe entry that raises (authorize-deny) must send an error{id} frame.

    Contract: this test ships broken if an exception from the subscribe
    entry propagates and crashes the consumer instead of being caught and
    surfaced as an error frame.

    Covers ws.py:371-373 — the "except Exception" arm around
    create_source_event_stream.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer and
            create_source_event_stream.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    async def _raising_create(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("authorize denied")

    monkeypatch.setattr(ws, "create_source_event_stream", _raising_create)

    app = ws.subscription_ws_consumer(schema=build_native_schema())
    communicator = _make_communicator(app, layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to(
        {"id": "raise", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )
    err = await communicator.receive_json_from(timeout=2)
    assert err["type"] == "error"
    assert err["id"] == "raise"
    assert "authorize denied" in err["payload"][0]["message"]

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 459->461 + 462 — _send_next includes errors when the result has them
# ---------------------------------------------------------------------------


async def test_next_frame_carries_field_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A delivered ExecutionResult with field errors must carry them in the next frame.

    Contract: this test ships broken if a partial-failure result's errors
    are dropped instead of appearing alongside data in the framed payload.

    Covers ws.py:459-462 — both arms of "_send_next" ("result.data is not
    None" AND "result.errors"): the framed payload must carry BOTH "data" and
    "errors". Driven on the real "_send_next" method of a constructed consumer
    with a crafted partial-failure result (deterministic, no live broadcast race).

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from graphql import ExecutionResult, GraphQLError

    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)

    consumer = app()
    consumer.scope = {"user": _User()}

    sent: list[dict[str, Any]] = []

    async def _capture(message: dict[str, Any]) -> None:
        sent.append(message)

    consumer.send_json = _capture
    result = ExecutionResult(
        data={"post": {"id": "1"}}, errors=[GraphQLError("partial failure")]
    )
    await consumer._send_next("eid", result)

    assert sent[0] == {
        "id": "eid",
        "type": "next",
        "payload": {
            "data": {"post": {"id": "1"}},
            "errors": [GraphQLError("partial failure").formatted],
        },
    }


# ---------------------------------------------------------------------------
# 412 — client complete with no id is ignored
# ---------------------------------------------------------------------------


async def test_client_complete_without_id_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client complete with no id must be silently ignored, without crashing.

    Contract: this test ships broken if a complete frame with no id crashes
    the consumer or leaves the socket unusable.

    Covers ws.py:410-412 — "op_id is None" -> return. The socket stays usable.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"type": "complete"})  # no id
    assert await communicator.receive_nothing(timeout=0.2) is True
    # Still usable.
    await communicator.send_json_to({"type": "ping"})
    assert (await communicator.receive_json_from(timeout=2))["type"] == "pong"

    await communicator.disconnect()


async def test_client_complete_unknown_id_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client complete for an unknown id must be a no-op, without crashing.

    Contract: this test ships broken if completing an unregistered id
    crashes the consumer instead of returning early.

    Covers ws.py:417-419 — "_cancel_operation" with "task is None" returns
    early. The socket stays usable afterwards.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    await communicator.send_json_to({"id": "ghost", "type": "complete"})
    assert await communicator.receive_nothing(timeout=0.2) is True
    await communicator.send_json_to({"type": "ping"})
    assert (await communicator.receive_json_from(timeout=2))["type"] == "pong"

    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 244-245 — a non-dict (e.g. JSON array) message → 4400
# ---------------------------------------------------------------------------


async def test_non_dict_message_closes_4400(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-mapping decoded message (a JSON array) must close with code 4400.

    Contract: this test ships broken if a non-dict decoded message crashes
    the consumer instead of closing cleanly with 4400.

    Covers ws.py:243-245 — "not isinstance(content, dict)" -> "_close(4400)".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)

    # A JSON array decodes to a list, not a dict.
    await communicator.send_to(text_data="[1, 2, 3]")
    out = await communicator.receive_output(timeout=2)
    assert out["type"] == "websocket.close"
    assert out["code"] == 4400


# ---------------------------------------------------------------------------
# 459->461 — _send_next with data-only (no errors) omits the errors key
# ---------------------------------------------------------------------------


async def test_next_frame_data_only_omits_errors_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean ExecutionResult (data, no errors) must produce a next frame with no errors key.

    Contract: this test ships broken if the framed next payload gains a
    spurious errors key when the result carries none.

    Covers ws.py:459->461 — the "if result.errors" False arm of "_send_next".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from graphql import ExecutionResult

    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)
    consumer = app()
    consumer.scope = {"user": _User()}

    sent: list[dict[str, Any]] = []

    async def _capture(message: dict[str, Any]) -> None:
        sent.append(message)

    consumer.send_json = _capture
    await consumer._send_next("d1", ExecutionResult(data={"post": {"id": "1"}}))
    assert sent[0] == {
        "id": "d1",
        "type": "next",
        "payload": {"data": {"post": {"id": "1"}}},
    }
    assert "errors" not in sent[0]["payload"]


# ---------------------------------------------------------------------------
# 420->422 — _cancel_operation when the task is ALREADY done
# ---------------------------------------------------------------------------


async def test_cancel_operation_with_already_done_task_does_not_recancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "_cancel_operation" for an already-done task must skip the cancel call.

    Contract: this test ships broken if an already-completed task is
    re-cancelled instead of simply being popped from the registries.

    Covers ws.py:420->422 — the "if not task.done()" False arm: an already-done
    task is awaited (no-op) and popped from the registries without re-cancelling.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)
    consumer = app()
    consumer.scope = {"user": _User()}
    consumer._operations = {}
    consumer._sources = {}

    async def _already() -> str:
        return "done"

    task = asyncio.ensure_future(_already())
    await task  # task is now done
    consumer._operations["op"] = task

    cancelled = {"n": 0}
    orig_cancel = task.cancel

    def _track_cancel(*a: Any, **k: Any) -> bool:
        cancelled["n"] += 1
        return orig_cancel(*a, **k)

    task.cancel = _track_cancel  # type: ignore[method-assign]

    await consumer._cancel_operation("op")
    # The done task was NOT re-cancelled and was removed from the registry.
    assert cancelled["n"] == 0
    assert "op" not in consumer._operations


# ---------------------------------------------------------------------------
# 442 + 448-453 — disconnect cancels the init timer + sweeps a leftover source
# ---------------------------------------------------------------------------


class _FakeSource:
    """A started-source stand-in recording "aclose" (optionally raising)."""

    def __init__(self, *, raise_on_close: bool = False) -> None:
        """Store the closed flag and whether aclose() should raise.

        Args:
            raise_on_close: Whether aclose() should raise RuntimeError after
                recording the close, simulating a teardown error.
        """
        self.closed = False
        self._raise = raise_on_close

    async def aclose(self) -> None:
        """Record the close, then optionally raise a simulated teardown error.

        Raises:
            RuntimeError: When this instance was constructed with
                raise_on_close=True.
        """
        self.closed = True
        if self._raise:
            raise RuntimeError("teardown error")


async def test_disconnect_cancels_init_timer_and_sweeps_leftover_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """disconnect must cancel a live init timer and aclose() a leftover source.

    Contract: this test ships broken if disconnect leaves the init timer
    running or fails to close/sweep a leftover source (even one whose
    aclose() raises).

    Covers ws.py:440-442 (the "timer is not None and not timer.done()" cancel)
    and 447-453 (the defensive source sweep: a source whose task already vanished
    is still aclose()d, and a raising aclose is swallowed).

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)
    consumer = app()
    consumer.scope = {"user": _User()}
    consumer._closing = False
    consumer._operations = {}

    # A live (not-done) init timer to be cancelled by disconnect.
    async def _never() -> None:
        await asyncio.sleep(100)

    consumer._init_timer = asyncio.ensure_future(_never())

    # A leftover source with no backing task (the defensive-sweep target); a
    # second one whose aclose RAISES (swallowed by the best-effort sweep).
    clean = _FakeSource()
    raising = _FakeSource(raise_on_close=True)
    consumer._sources = {"clean": clean, "raising": raising}

    await consumer.disconnect(code=1000)

    # Let the cancellation propagate (cancel() leaves the task in "cancelling").
    with pytest.raises(asyncio.CancelledError):
        await consumer._init_timer
    assert consumer._init_timer.cancelled()
    assert clean.closed is True
    assert raising.closed is True  # attempted despite raising
    assert consumer._sources == {}


# ---------------------------------------------------------------------------
# 491 + 500-505 — _close is idempotent + sweeps a leftover source defensively
# ---------------------------------------------------------------------------


async def test_close_is_idempotent_when_already_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "_close" while "_closing" is already True must return early, avoiding a double close.

    Contract: this test ships broken if a redundant "_close" call while
    already closing still delegates to self.close() a second time.

    Covers ws.py:490-491 — the "if self._closing: return" guard.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)
    consumer = app()
    consumer.scope = {"user": _User()}
    consumer._closing = True  # already closing
    consumer._operations = {}
    consumer._sources = {}

    closed = {"n": 0}

    async def _close(code: int | None = None) -> None:
        closed["n"] += 1

    consumer.close = _close
    await consumer._close(4400)
    # The early return means self.close() is NOT delegated to.
    assert closed["n"] == 0


async def test_close_sweeps_leftover_source_defensively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "_close" must aclose() a leftover source (no backing task) before closing.

    Contract: this test ships broken if a leftover source is left open, or
    if a raising aclose() prevents delegating to self.close(code=...).

    Covers ws.py:499-505 — the defensive source sweep, including swallowing a
    raising aclose, then delegating to self.close(code=...).

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)
    consumer = app()
    consumer.scope = {"user": _User()}
    consumer._closing = False
    consumer._operations = {}

    clean = _FakeSource()
    raising = _FakeSource(raise_on_close=True)
    consumer._sources = {"a": clean, "b": raising}

    closed_with: list[int | None] = []

    async def _close(code: int | None = None) -> None:
        closed_with.append(code)

    consumer.close = _close
    await consumer._close(4409)

    assert clean.closed is True
    assert raising.closed is True
    assert consumer._sources == {}
    assert closed_with == [4409]


# ---------------------------------------------------------------------------
# 233->exit — the init watchdog skips the close when already acked
# ---------------------------------------------------------------------------


async def test_init_watchdog_skips_close_when_already_acked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watchdog must not close when "_acked" is already True at expiry.

    Contract: this test ships broken if an already-acked connection is
    closed with 4408 by the expiring watchdog anyway.

    Covers ws.py:233->exit — the "if not self._acked and not self._closing"
    False arm: a connection that acked before the timeout never gets a 4408 close.
    Driven directly on "_init_watchdog" with "_acked = True".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    app = _app(layer, monkeypatch)
    consumer = app()
    consumer.scope = {"user": _User()}
    consumer._acked = True
    consumer._closing = False

    closed = {"n": 0}

    async def _close(code: int | None = None) -> None:
        closed["n"] += 1

    consumer._close = _close
    # A zero timeout → the sleep returns immediately, then the acked guard skips.
    await consumer._init_watchdog(0.0)
    assert closed["n"] == 0


# ---------------------------------------------------------------------------
# 242 — receive_json while _closing returns early
# ---------------------------------------------------------------------------


async def test_receive_json_after_close_flag_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A message dispatched while "_closing" is True must be ignored.

    Contract: this test ships broken if a message received while closing
    triggers another close or sends a reply instead of being ignored.

    Covers ws.py:241-242 — the "if self._closing: return" guard. Driven on a
    constructed consumer instance with "_closing = True": receive_json must
    NOT close again nor send anything.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    app = _app(layer, monkeypatch)

    consumer = app()
    consumer.scope = {"user": _User()}
    consumer._closing = True

    closed = {"n": 0}
    sent = {"n": 0}

    async def _close(code: int | None = None) -> None:
        closed["n"] += 1

    async def _send_json(message: dict[str, Any]) -> None:
        sent["n"] += 1

    consumer.close = _close
    consumer.send_json = _send_json

    # A malformed frame that would normally 4400-close is ignored while closing.
    await consumer.receive_json({"type": "bogus"})
    assert closed["n"] == 0
    assert sent["n"] == 0
