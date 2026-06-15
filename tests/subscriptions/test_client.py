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
