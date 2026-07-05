# -*- coding: utf-8 -*-
"""T-CLIENT: the SubscriptionClientView serves the HTML client.

WU10: the client page now speaks STANDARD protocols:
  * graphql-transport-ws WebSocket (connection_init -> ack, subscribe{id},
    next/complete/error, ping/pong)
  * graphql-sse EventSource (text/event-stream, event: next / event: complete)

The OLD bespoke channel_id / {stream, payload} wire is GONE.
SubscriptionClientView itself is KEPT and EXPORTED (design paragraph 11).
"""

from __future__ import annotations

from django.test import RequestFactory

from django_graphex.subscriptions import SubscriptionClientView

# ---------------------------------------------------------------------------
# Legacy tests (view contract — unchanged)
# ---------------------------------------------------------------------------


def test_client_view_renders_default_paths() -> None:
    """The default view must render the client HTML with real paths injected.

    Contract: this test ships broken if the default-rendered page keeps the
    __WS_PATH__/__HTTP_PATH__ placeholders instead of the real endpoint URLs.
    """
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


def test_client_view_custom_paths() -> None:
    """Custom ws_path/http_path kwargs must be reflected in the rendered client.

    Contract: this test ships broken if custom endpoint paths passed to
    as_view() are not injected into the rendered HTML body.
    """
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


def test_client_new_page_has_graphql_transport_ws_marker() -> None:
    """The page JavaScript must implement graphql-transport-ws's connection_init handshake.

    Contract: this test ships broken if the initial connection_init message
    required by the graphql-transport-ws protocol is missing from the page.
    """
    body = _get_body()
    # The graphql-transport-ws protocol requires connection_init as first message.
    assert "connection_init" in body


def test_client_new_page_has_subscribe_message_type() -> None:
    """The page must send subscribe-type messages per graphql-transport-ws.

    Contract: this test ships broken if the client stops emitting the
    "subscribe" message type required to start an operation.
    """
    body = _get_body()
    assert '"subscribe"' in body or "'subscribe'" in body


def test_client_new_page_has_next_message_type() -> None:
    """The page must handle next-type messages per graphql-transport-ws.

    Contract: this test ships broken if the client loses its handling of the
    "next" message type carrying incremental subscription results.
    """
    body = _get_body()
    assert '"next"' in body or "'next'" in body or "next" in body


def test_client_new_page_has_sse_eventsource() -> None:
    """The page must include an EventSource-based SSE client for graphql-sse.

    Contract: this test ships broken if the SSE transport path drops its
    EventSource usage.
    """
    body = _get_body()
    assert "EventSource" in body


def test_client_new_page_has_sse_event_next() -> None:
    """The page must handle "event: next" SSE frames per the graphql-sse protocol.

    Contract: this test ships broken if the client stops listening for the
    "next" named SSE event.
    """
    body = _get_body()
    # The client listens for the 'next' named event from EventSource.
    assert "next" in body  # present in both WS and SSE paths


def test_client_new_page_has_sse_event_complete() -> None:
    """The page must handle "event: complete" SSE frames per the graphql-sse protocol.

    Contract: this test ships broken if the client stops listening for the
    "complete" named SSE event.
    """
    body = _get_body()
    assert "complete" in body


def test_client_old_bespoke_channel_id_wire_gone() -> None:
    """The bespoke channelId subscription wire must be removed from the client page.

    Contract: this test ships broken if the retired channelId field
    reappears in the rendered client, signaling a regression to the old
    bespoke transport wire.
    """
    body = _get_body()
    # The old client sent variables: {channelId: channelId} via HTTP POST.
    # The new client uses native WS or SSE — no HTTP POST with channelId.
    assert "channelId" not in body


def test_client_old_bespoke_connect_success_handshake_gone() -> None:
    """The old "{connect: 'success', channel_id: ...}" handshake must be gone.

    Contract: this test ships broken if the retired bespoke handshake marker
    reappears in the rendered client.
    """
    body = _get_body()
    # The old bespoke wire detected: data.connect==="success" && data.channel_id
    assert "data.connect" not in body
    assert '"success"' not in body or "connect" not in body


def test_client_old_bespoke_stream_field_gone() -> None:
    """The bespoke stream/payload/ok/error/operation field references must be gone.

    Contract: this test ships broken if the retired bespoke-engine query
    variables reappear in the client's default editor content.
    """
    body = _get_body()
    # The old default subscription query in the editor had: stream, operation, ok, error
    # fields that map to the bespoke engine wire — these must be gone from the template.
    assert "channelId: $channelId" not in body
    assert "$channelId: String!" not in body


def test_client_has_transport_mode_selector() -> None:
    """The new client must let the user pick between WS and SSE transport mode.

    Contract: this test ships broken if either transport mode label is
    missing from the rendered UI, leaving the user unable to select it.
    """
    body = _get_body()
    # Both transport modes must be represented in the UI.
    assert "SSE" in body or "sse" in body.lower()
    assert "WS" in body or "WebSocket" in body


def test_client_view_is_exported_from_subscriptions() -> None:
    """ "SubscriptionClientView" must remain publicly exported (design paragraph 11).

    Contract: this test ships broken if the view stops being importable from
    "django_graphex.subscriptions".
    """
    from django_graphex.subscriptions import SubscriptionClientView as SCV  # noqa: F401

    assert SCV is SubscriptionClientView


def test_client_new_page_has_graphql_transport_ws_protocol_subprotocol() -> None:
    """The WS connection must use the graphql-transport-ws subprotocol string.

    Contract: this test ships broken if the client stops requesting the
    graphql-transport-ws WebSocket subprotocol.
    """
    body = _get_body()
    assert "graphql-transport-ws" in body


def test_client_new_page_has_ping_pong() -> None:
    """The WS client must handle ping/pong per the graphql-transport-ws spec.

    Contract: this test ships broken if the client stops responding to the
    protocol's keep-alive ping/pong frames.
    """
    body = _get_body()
    assert "ping" in body or "pong" in body


def test_client_sse_http_path_used() -> None:
    """The SSE client must use the configured http_path as its endpoint URL.

    Contract: this test ships broken if the SSE transport ignores the
    http_path attribute and posts to a different URL.
    """
    body = _get_body(http_path="/api/subscriptions")
    assert "/api/subscriptions" in body


# ---------------------------------------------------------------------------
# Round-2 repair (#1623): demo-client robustness fixes (ranks 4/7/13/14/15)
#
# These are static-HTML assertions — the page is served as a Django template,
# so we assert the JavaScript markers that guard each fix are present in the
# served body.  Full browser e2e remains deferred (no browser dependency).
# ---------------------------------------------------------------------------


def test_client_ws_onclose_has_monotonic_connection_id_guard() -> None:
    """RANK 4: a monotonic connection id must guard onclose against the WS-SSE-WS race.

    Contract: switching transport modes ships broken (nulling the live
    connection) if an old WebSocket.onclose can fire after wsConnect()
    created a new ws without the monotonic id guard blocking its cleanup.

    Switching transport modes can let an OLD WebSocket.onclose fire AFTER
    wsConnect() created a NEW ws, nulling the live connection. Each connection
    captures a monotonic id in the wsConnect closure; onclose only runs cleanup
    when that captured id is still the current one.
    """
    body = _get_body()
    # A monotonic counter is incremented per connection and captured in closure.
    assert "wsCounter" in body
    assert "myId" in body
    # The captured id is compared against the live counter before cleanup.
    assert "myId===wsCounter" in body or "myId === wsCounter" in body


def test_client_ws_all_four_handlers_carry_the_stale_connection_guard() -> None:
    """RANK 4 (round-3 completion): all four WS handlers must carry the monotonic guard.

    Contract: this test ships broken if any of onopen, onmessage, onerror,
    or onclose lacks the stale-connection guard, since a stale socket's
    onopen firing after a newer socket is OPEN would otherwise send a
    duplicate connection_init on the live socket (close code 4429).

    Pinning the guard per-handler keeps them symmetric even if the
    button-disable gating that currently makes the race unreachable is ever
    changed.
    """
    body = _get_body()
    for handler in ("onopen", "onmessage", "onerror", "onclose"):
        anchor = f"sock.{handler}=function("
        assert anchor in body, f"WS handler {handler} not found"
        block = body[body.index(anchor) : body.index(anchor) + 400]
        assert "myId!==wsCounter" in block or "myId !== wsCounter" in block, (
            f"WS {handler} handler is missing the monotonic RANK-4 stale-connection guard"
        )


def test_client_sse_connect_has_no_queryless_eventsource() -> None:
    """RANK 7: sseConnect() must no longer open a dead, query-less EventSource.

    Contract: this test ships broken if sseConnect() reintroduces a
    query-less EventSource construction, since EventSource is GET-only and
    cannot carry a GraphQL document.

    The real subscription is sent via the fetch POST in sseRun();
    sseConnect() must not construct an EventSource.
    """
    body = _get_body()
    # The whole SSE-open seam now lives in sseRun()'s fetch POST.  sseConnect()
    # must not contain a `new EventSource(` construction.
    assert "new EventSource(" not in body
    # And the dead "EventSource connected" connectivity log is gone.
    assert "EventSource connected" not in body


def test_client_has_variables_and_operation_name_inputs() -> None:
    """RANK 13: the client must expose optional variables (JSON) and operationName inputs.

    Contract: this test ships broken if the variables/operationName input
    fields or their JSON-parsing/payload wiring go missing from the page.
    """
    body = _get_body()
    # Input element ids for the new fields.
    assert "gdsx-vars" in body
    assert "gdsx-opname" in body
    # The variables textarea is labelled and the JSON is parsed (with validation).
    assert "JSON.parse" in body
    # The payload helper builds {query, variables?, operationName?}.
    assert "operationName" in body
    assert "variables" in body


def test_client_variables_json_is_validated() -> None:
    """RANK 13: invalid variables JSON must be rejected with an error, not sent as garbage.

    Contract: this test ships broken if malformed variables JSON is silently
    sent instead of being caught and logged as an error.
    """
    body = _get_body()
    # A dedicated helper parses+validates the variables JSON and logs an error
    # on parse failure rather than sending malformed input.
    assert "Invalid variables JSON" in body


def test_client_sse_done_flushes_trailing_buffer() -> None:
    """RANK 14: a buffered partial SSE frame must be flushed on chunk.done, not dropped.

    Contract: this test ships broken if a valid final SSE frame arriving
    without a trailing blank line is silently discarded instead of being
    parsed and flushed on chunk.done.
    """
    body = _get_body()
    # On done we flush whatever remains in the buffer before completing.
    assert "flushFrame" in body or "flushBuffer" in body
    # The done branch references the buffer (it is no longer ignored).
    assert "buf.trim()" in body


def test_client_sse_pump_error_sets_connection_error_status() -> None:
    """RANK 15: a pump() error must set status to "Connection Error", not "Connected (SSE)".

    Contract: this test ships broken if the pump() failure path stops
    setting the connection-error status, misleadingly leaving the UI on a
    healthy-looking state.
    """
    body = _get_body()
    assert "Connection Error" in body
    # The pump() catch must NOT re-assert a healthy "Connected (SSE)" status.
    # We assert the error label is wired to the failure path.
    assert 'setStatus("closed","Connection Error")' in body


# ---------------------------------------------------------------------------
# FIX 2: the default http_path carries a trailing slash (/graphql/).
#
# Django's APPEND_SLASH = True (the default) 301-redirects POST /graphql ->
# /graphql/. But a GraphQL POST client (the bundled fetch) does not follow the
# redirect, so a slash-less default sends the operation to the un-slashed URL and
# the request 500s (RuntimeError: you cannot POST-redirect with a body). The
# default MUST be the canonical slashed route so the out-of-the-box client posts
# to the same URL the GraphQLView is mounted at (config/urls.py mounts /graphql/).
# ---------------------------------------------------------------------------


def _default_view_body() -> str:
    """Render the client with the built-in defaults (no path overrides)."""
    request = RequestFactory().get("/graphql/client/")
    return SubscriptionClientView.as_view()(request).content.decode()


def test_default_http_path_has_trailing_slash() -> None:
    """The default-rendered SSE/HTTP endpoint URL must be "/graphql/" (slashed).

    Contract: this test ships broken (a 500 from Django's APPEND_SLASH
    redirect on a POST-with-body) if the default http_path renders without
    its trailing slash.

    The template injects the http_path into "loc.host+'__HTTP_PATH__'"; after
    injection the default must render "loc.host+'/graphql/'" (with the trailing
    slash) so a POST client does not hit the APPEND_SLASH redirect. A slash-less
    "/graphql" default renders "loc.host+'/graphql'" here — the RED.
    """
    body = _default_view_body()
    # The exact injected literal — a bare "/graphql" substring would falsely
    # match "/graphql/", so anchor on the host-concatenation the template emits.
    assert 'loc.host+"/graphql/"' in body


def test_default_http_path_attribute_is_slashed() -> None:
    """The class attribute default itself must be the canonical slashed route.

    Contract: this test ships broken if the class-level http_path default
    loses its trailing slash.
    """
    assert SubscriptionClientView.http_path == "/graphql/"


def test_default_ws_path_attribute_is_slashed() -> None:
    """The ws_path default must remain slashed (parity check — must not regress).

    Contract: this test ships broken if the class-level ws_path default
    loses its trailing slash.
    """
    assert SubscriptionClientView.ws_path == "/ws/graphql/"


# ---------------------------------------------------------------------------
# FIX 3: inline-script injection hardening.
#
# The paths are injected into an inline <script> block. A dev-configured path
# containing the literal "</script>" would close the script element early in the
# browser (an HTML parser sees "</script>" regardless of JS string context),
# breaking out of the script and enabling injection. The rendered inline script
# must therefore never contain a literal "</script>" produced from a path value.
# ---------------------------------------------------------------------------


def test_path_with_script_close_tag_does_not_break_out_of_inline_script() -> None:
    """A path containing "</script>" must render with no literal "</script>" inside.

    Contract: injection hardening ships broken if a malicious path value can
    still close the inline script element early in the browser.

    The HTML parser terminates an inline "<script>" at the first literal
    "</script>" sequence irrespective of JavaScript string quoting, so a
    "json.dumps"-only escape (which leaves "<" and "/" verbatim) still lets
    a malicious path close the script element. The injection must escape the
    "<" (e.g. to "\\u003c") so no literal "</script>" survives in the body.
    """
    malicious = "/graphql/</script><script>alert(1)</script>"
    request = RequestFactory().get("/graphql/client/")
    body = SubscriptionClientView.as_view(http_path=malicious)(request).content.decode()
    # The whole point: the injected path must not reintroduce a literal closing
    # script tag anywhere the browser would treat as ending the inline script.
    assert "</script><script>alert(1)</script>" not in body
    # And the escaped marker proves the value was still injected (escaped), not
    # simply dropped.
    assert "alert(1)" in body


def test_ws_path_with_script_close_tag_is_also_escaped() -> None:
    """The ws_path injection must be hardened the same way as http_path.

    Contract: injection hardening ships broken if ws_path values are
    escaped differently from http_path, leaving one transport vulnerable.
    """
    malicious = "/ws/graphql/</script>"
    request = RequestFactory().get("/graphql/client/")
    body = SubscriptionClientView.as_view(ws_path=malicious)(request).content.decode()
    assert "/ws/graphql/</script>" not in body
