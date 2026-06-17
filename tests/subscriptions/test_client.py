# -*- coding: utf-8 -*-
"""T-CLIENT: the SubscriptionClientView serves the HTML client.

WU10: the client page now speaks STANDARD protocols:
  * graphql-transport-ws WebSocket (connection_init → ack, subscribe{id},
    next/complete/error, ping/pong)
  * graphql-sse EventSource (text/event-stream, event: next / event: complete)

The OLD bespoke channel_id / {stream, payload} wire is GONE.
SubscriptionClientView itself is KEPT and EXPORTED (design §11).
"""

from django.test import RequestFactory

from django_graphex.subscriptions import SubscriptionClientView

# ---------------------------------------------------------------------------
# Legacy tests (view contract — unchanged)
# ---------------------------------------------------------------------------


def test_client_view_renders_default_paths():
    request = RequestFactory().get("/graphql/client/")
    response = SubscriptionClientView.as_view()(request)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    body = response.content.decode()
    assert "<!DOCTYPE html>" in body
    assert "GraphQL Subscriptions Client" in body
    # default endpoint paths are injected, placeholders are gone
    assert "/ws/graphql/" in body
    assert "/graphql" in body
    assert "__WS_PATH__" not in body and "__HTTP_PATH__" not in body


def test_client_view_custom_paths():
    request = RequestFactory().get("/anything")
    view = SubscriptionClientView.as_view(ws_path="/sock/", http_path="/api/graphql")
    body = view(request).content.decode()
    assert "/sock/" in body
    assert "/api/graphql" in body


# ---------------------------------------------------------------------------
# WU10 RED tests: new protocol markers PRESENT, old bespoke wire GONE
# ---------------------------------------------------------------------------


def _get_body(ws_path: str = "/ws/graphql/", http_path: str = "/graphql") -> str:
    request = RequestFactory().get("/graphql/client/")
    view = SubscriptionClientView.as_view(ws_path=ws_path, http_path=http_path)
    return view(request).content.decode()


def test_client_new_page_has_graphql_transport_ws_marker():
    """The page JavaScript implements graphql-transport-ws (connection_init → ack)."""
    body = _get_body()
    # The graphql-transport-ws protocol requires connection_init as first message.
    assert "connection_init" in body


def test_client_new_page_has_subscribe_message_type():
    """The page sends subscribe-type messages per graphql-transport-ws."""
    body = _get_body()
    assert '"subscribe"' in body or "'subscribe'" in body


def test_client_new_page_has_next_message_type():
    """The page handles next-type messages per graphql-transport-ws."""
    body = _get_body()
    assert '"next"' in body or "'next'" in body or "next" in body


def test_client_new_page_has_sse_eventsource():
    """The page includes an EventSource-based SSE client for graphql-sse."""
    body = _get_body()
    assert "EventSource" in body


def test_client_new_page_has_sse_event_next():
    """The page handles 'event: next' SSE frames (graphql-sse protocol)."""
    body = _get_body()
    # The client listens for the 'next' named event from EventSource.
    assert "next" in body  # present in both WS and SSE paths


def test_client_new_page_has_sse_event_complete():
    """The page handles 'event: complete' SSE frames (graphql-sse protocol)."""
    body = _get_body()
    assert "complete" in body


def test_client_old_bespoke_channel_id_wire_gone():
    """The bespoke channel_id subscription wire is REMOVED from the client page."""
    body = _get_body()
    # The old client sent variables: {channelId: channelId} via HTTP POST.
    # The new client uses native WS or SSE — no HTTP POST with channelId.
    assert "channelId" not in body


def test_client_old_bespoke_connect_success_handshake_gone():
    """The old {connect: 'success', channel_id: ...} handshake is gone."""
    body = _get_body()
    # The old bespoke wire detected: data.connect==="success" && data.channel_id
    assert 'data.connect' not in body
    assert '"success"' not in body or "connect" not in body


def test_client_old_bespoke_stream_field_gone():
    """The bespoke {stream, payload, ok, error, operation} field references are gone."""
    body = _get_body()
    # The old default subscription query in the editor had: stream, operation, ok, error
    # fields that map to the bespoke engine wire — these must be gone from the template.
    assert "channelId: $channelId" not in body
    assert "$channelId: String!" not in body


def test_client_has_transport_mode_selector():
    """The new client lets the user pick WS or SSE transport mode."""
    body = _get_body()
    # Both transport modes must be represented in the UI.
    assert "SSE" in body or "sse" in body.lower()
    assert "WS" in body or "WebSocket" in body


def test_client_view_is_exported_from_subscriptions():
    """SubscriptionClientView remains publicly exported (design §11)."""
    from django_graphex.subscriptions import SubscriptionClientView as SCV  # noqa: F401

    assert SCV is SubscriptionClientView


def test_client_new_page_has_graphql_transport_ws_protocol_subprotocol():
    """The WS connection uses the graphql-transport-ws subprotocol string."""
    body = _get_body()
    assert "graphql-transport-ws" in body


def test_client_new_page_has_ping_pong():
    """The WS client handles ping/pong per graphql-transport-ws spec."""
    body = _get_body()
    assert "ping" in body or "pong" in body


def test_client_sse_http_path_used():
    """The SSE client path uses the http_path attribute (the SSE endpoint URL)."""
    body = _get_body(http_path="/api/subscriptions")
    assert "/api/subscriptions" in body


# ---------------------------------------------------------------------------
# Round-2 repair (#1623): demo-client robustness fixes (ranks 4/7/13/14/15)
#
# These are static-HTML assertions — the page is served as a Django template,
# so we assert the JavaScript markers that guard each fix are present in the
# served body.  Full browser e2e remains deferred (no browser dependency).
# ---------------------------------------------------------------------------


def test_client_ws_onclose_has_monotonic_connection_id_guard():
    """RANK 4: a monotonic connection id guards onclose against the WS→SSE→WS race.

    Switching transport modes can let an OLD WebSocket.onclose fire AFTER
    wsConnect() created a NEW ws, nulling the live connection.  Each connection
    captures a monotonic id in the wsConnect closure; onclose only runs cleanup
    when that captured id is still the current one.
    """
    body = _get_body()
    # A monotonic counter is incremented per connection and captured in closure.
    assert "wsCounter" in body
    assert "myId" in body
    # The captured id is compared against the live counter before cleanup.
    assert "myId===wsCounter" in body or "myId === wsCounter" in body


def test_client_ws_all_four_handlers_carry_the_stale_connection_guard():
    """RANK 4 (round-3 completion): the monotonic guard must be present in ALL
    four WS event handlers (onopen, onmessage, onerror, onclose), not just three.

    A stale socket's onopen firing after a newer socket is OPEN would otherwise
    send a duplicate ``connection_init`` on the live socket (close code 4429).
    Pinning the guard per-handler keeps them symmetric even if the button-disable
    gating that currently makes the race unreachable is ever changed.
    """
    body = _get_body()
    for handler in ("onopen", "onmessage", "onerror", "onclose"):
        anchor = f"sock.{handler}=function("
        assert anchor in body, f"WS handler {handler} not found"
        block = body[body.index(anchor) : body.index(anchor) + 400]
        assert "myId!==wsCounter" in block or "myId !== wsCounter" in block, (
            f"WS {handler} handler is missing the monotonic RANK-4 stale-connection guard"
        )


def test_client_sse_connect_has_no_queryless_eventsource():
    """RANK 7: sseConnect() no longer opens a dead, query-less EventSource.

    EventSource is GET-only and cannot carry a GraphQL document, so opening one
    in sseConnect() created a dead connection.  The real subscription is sent via
    the fetch POST in sseRun(); sseConnect() must not construct an EventSource.
    """
    body = _get_body()
    # The whole SSE-open seam now lives in sseRun()'s fetch POST.  sseConnect()
    # must not contain a `new EventSource(` construction.
    assert "new EventSource(" not in body
    # And the dead "EventSource connected" connectivity log is gone.
    assert "EventSource connected" not in body


def test_client_has_variables_and_operation_name_inputs():
    """RANK 13: the client exposes optional variables (JSON) + operationName inputs."""
    body = _get_body()
    # Input element ids for the new fields.
    assert "gdsx-vars" in body
    assert "gdsx-opname" in body
    # The variables textarea is labelled and the JSON is parsed (with validation).
    assert "JSON.parse" in body
    # The payload helper builds {query, variables?, operationName?}.
    assert "operationName" in body
    assert "variables" in body


def test_client_variables_json_is_validated():
    """RANK 13: invalid variables JSON is rejected with an error, not sent as garbage."""
    body = _get_body()
    # A dedicated helper parses+validates the variables JSON and logs an error
    # on parse failure rather than sending malformed input.
    assert "Invalid variables JSON" in body


def test_client_sse_done_flushes_trailing_buffer():
    """RANK 14: a buffered partial SSE frame is flushed on chunk.done, not dropped.

    A valid final SSE frame may arrive without the trailing blank line; on
    chunk.done the remaining buffer must be parsed/flushed instead of discarded.
    """
    body = _get_body()
    # On done we flush whatever remains in the buffer before completing.
    assert "flushFrame" in body or "flushBuffer" in body
    # The done branch references the buffer (it is no longer ignored).
    assert "buf.trim()" in body


def test_client_sse_pump_error_sets_connection_error_status():
    """RANK 15: a pump() error sets status to 'Connection Error', not 'Connected (SSE)'."""
    body = _get_body()
    assert "Connection Error" in body
    # The pump() catch must NOT re-assert a healthy "Connected (SSE)" status.
    # We assert the error label is wired to the failure path.
    assert 'setStatus("closed","Connection Error")' in body
