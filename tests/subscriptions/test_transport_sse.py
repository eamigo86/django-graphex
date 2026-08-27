# -*- coding: utf-8 -*-
"""WU8 — SSE transport adapter (transports/sse.py).

The SSE transport is the FIRST (cheap) engine validator (design paragraph 7):
an async Django view (Django>=5.2 -> clean disconnect cancellation GUARANTEED)
returning a "StreamingHttpResponse(content_type='text/event-stream')". ONE
HTTP request -> ONE subscription stream.

It drives the serialize-once native engine end-to-end:

  * auth lives in the HTTP request ("request.user" / session) — this REPLACES
    the deleted channel-ownership guard; an authorize-deny short-circuits BEFORE
    any "group_add" (no stream);
  * the request's GraphQL document (query/variables/operationName) is parsed, the
    live native schema obtained, the subscription field's native subscribe entry
    run (-> ChannelLayerSource), then driven via WU5 "drive_subscription"
    supplying the live schema + parsed DocumentNode at delivery;
  * each ExecutionResult is framed "event: next\\ndata: {json}\\n\\n"; on
    completion "event: complete\\ndata: \\n\\n" (the empty "data:" is MANDATORY
    or EventSource never fires the "complete" event);
  * a validation error AFTER the 200 response started goes IN-STREAM as
    "next{errors:[...]}" then "complete" — NOT an HTTP 4xx (pre-200
    parse/validate errors MAY be HTTP 4xx);
  * client disconnect / aclosing -> "source.aclose()" -> "group_discard" (the
    WU4 sweep releases a blocked receive + discards every joined group), so no
    ghost subscriber survives a teardown;
  * the view reads "graphql_api_settings.MAX_VALIDATION_ERRORS" (NOT
    "graphene_settings" — the no-graphene-import gate);
  * "assertNumQueries(0)" on the delivery path (serialize-once: the snake
    closure projects the flat pk dict, never the ORM).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402

from tests.models import Post  # noqa: E402

# The node types Post's relation graph needs, and the assembled schema, are
# built ONCE process-wide by the shared module (see its docstring).
from tests.subscriptions._sse import sse_frames  # noqa: E402
from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402


def _notify(
    group: str, data: dict[str, Any], *, action: str = "create", pk: int = 1
) -> dict[str, Any]:
    """Build a producer-shaped "subscription.notify" envelope (bindings.py).

    Args:
        group: The channel-layer group name the message targets.
        data: The serialized payload data to embed in the message.
        action: The CRUD action name to embed in the payload.
        pk: The primary key to embed in the envelope.

    Returns:
        message: The assembled notify message dict.
    """
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": pk,
        "payload": {"action": action, "model": "tests.post", "data": data},
    }


class _User:
    """A minimal authenticated/anonymous user stand-in."""

    def __init__(self, *, authenticated: bool) -> None:
        """Store the authentication flag and derive a matching pk.

        Args:
            authenticated: Whether this stand-in reports itself as
                authenticated; an unauthenticated user gets pk=None.
        """
        self.is_authenticated = authenticated
        self.pk = 1 if authenticated else None


def _make_request(
    query: str, *, authenticated: bool = True, variables: dict[str, Any] | None = None
) -> Any:
    """Build an async-capable HTTP request carrying a GraphQL subscription body.

    Args:
        query: The GraphQL subscription document to send as the request body.
        authenticated: Whether the attached stand-in user is authenticated.
        variables: Optional GraphQL variables to include in the body.

    Returns:
        request: The constructed Django test request.
    """
    from django.test import RequestFactory

    body: dict[str, Any] = {"query": query}
    if variables is not None:
        body["variables"] = variables
    factory = RequestFactory()
    request = factory.post(
        "/subscriptions/sse",
        data=json.dumps(body),
        content_type="application/json",
    )
    request.user = _User(authenticated=authenticated)
    return request


async def _drain_frames(
    response: Any, *, max_frames: int, timeout: float = 1.0
) -> list[str]:
    """Pull up to "max_frames" SSE frames from a StreamingHttpResponse.

    Args:
        response: The streaming HTTP response to read frames from.
        max_frames: The maximum number of frames to pull before stopping.
        timeout: The per-frame wait timeout in seconds.

    Returns:
        frames: The decoded frame strings collected so far; stops early once
            the "complete" frame is seen.
    """
    frames: list[str] = []
    aiter = sse_frames(response).__aiter__()
    for _ in range(max_frames):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=timeout)
        except StopAsyncIteration:
            break
        text = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else chunk
        frames.append(text)
        if "event: complete" in text:
            break
    # Best-effort close of the async generator so teardown runs.
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()
    return frames


# ---------------------------------------------------------------------------
# 1) next/complete framing — serialize-once flat pk data; empty data: on complete
# ---------------------------------------------------------------------------


async def test_sse_next_frame_then_complete_with_flat_pk_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broadcast must arrive as a next frame with flat pk data, then complete.

    Contract: this test ships broken if the delivered next frame does not
    carry the serialize-once flat data (relations as pks per WU7), or if the
    terminal frame is not exactly "event: complete\\ndata: \\n\\n".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from channels.layers import get_channel_layer

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    # The view also imports get_channel_layer lazily; patch the source too.
    assert get_channel_layer  # referenced for clarity

    schema = build_native_schema()
    view = sse.subscription_sse_view(schema=schema)

    query = "subscription { post(action: CREATE) { id title author tags } }"
    request = _make_request(query)

    response = await view(request)
    assert response.status_code == 200
    assert response["content-type"].startswith("text/event-stream")

    # Drive one broadcast through the live engine.
    started = sse.get_started_source(response)
    group = started.joined_groups[0]
    flat = {
        "id": 1,
        "title": "hello",
        "body": "",
        "views": 0,
        "author": 7,
        "category": 9,
        "tags": [3],
        "co_authors": [7, 8],
    }
    await layer.group_send(group, _notify(group, flat))

    # First frame: event: next with the projected flat pk data.
    aiter = sse_frames(response).__aiter__()
    first = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
    first = first.decode() if isinstance(first, (bytes, bytearray)) else first
    assert first.startswith("event: next\n")
    assert first.endswith("\n\n")
    payload_line = [ln for ln in first.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(payload_line[len("data: ") :])
    assert payload["data"]["post"] == {
        "id": "1",
        "title": "hello",
        "author": "7",
        "tags": ["3"],
    }
    assert payload.get("errors") in (None, [])

    # Close out-of-band → the stream emits a terminal complete frame with the
    # MANDATORY empty data: line.
    await started.aclose()
    last = None
    for _ in range(3):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
        except StopAsyncIteration:
            break
        last = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        if "event: complete" in last:
            break
    assert last is not None
    assert last == "event: complete\ndata: \n\n"

    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()


# ---------------------------------------------------------------------------
# 2) in-stream validation error (post-200) → next{errors} then complete, NOT 4xx
# ---------------------------------------------------------------------------


async def test_post_200_validation_error_is_in_stream_not_http_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validation error after the 200 stream started must arrive in-stream, never as a 4xx.

    Contract: this test ships broken if a post-200 validation error is
    delivered as an HTTP 4xx instead of an in-stream next{errors} frame
    followed by complete.

    The document parses but selects an undeclared field, so validation fails. The
    transport has already committed the 200 text/event-stream response, so the
    error MUST be delivered in-stream (a 4xx is impossible once the response has
    started). EventSource only sees in-stream frames.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    schema = build_native_schema()
    view = sse.subscription_sse_view(schema=schema)

    # ``nope`` is not a field on the Post event type → a validation error.
    query = "subscription { post(action: CREATE) { id nope } }"
    request = _make_request(query)

    response = await view(request)
    # The response started 200 (the stream is committed before validation runs
    # in-stream); the validation error is delivered in-stream, not as a 4xx.
    assert response.status_code == 200
    assert response["content-type"].startswith("text/event-stream")

    frames = await _drain_frames(response, max_frames=4)
    joined = "".join(frames)
    assert "event: next" in joined
    # The error frame carries the validation error.
    next_frame = [f for f in frames if f.startswith("event: next")][0]
    data_line = [ln for ln in next_frame.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(data_line[len("data: ") :])
    assert payload["errors"], "post-200 validation error must be in-stream"
    assert any("nope" in (e.get("message") or "") for e in payload["errors"])
    # Followed by the terminal complete frame.
    assert "event: complete\ndata: \n\n" in joined


# ---------------------------------------------------------------------------
# 3) auth: an unauthenticated request to an auth-required subscription is rejected
# ---------------------------------------------------------------------------


async def test_unauthenticated_request_is_rejected_no_stream(  # noqa: DOC005
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authorize-deny (unauthenticated) request must yield no live stream.

    Contract: this test ships broken if an anonymous user's denied subscribe
    joins any channel-layer group instead of short-circuiting before
    group_add.

    Auth lives in the HTTP request ("request.user") — the replacement for the
    deleted channel-ownership guard. The subscription's authorize raises for
    an anonymous user, which short-circuits BEFORE any group_add (no source,
    no group joined), and the transport surfaces the denial (no live stream).

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions import Subscription
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    # An auth-required subscription: authorize raises for an anonymous user.
    class _AuthRequiredPost(Subscription):
        class Meta:
            model = Post
            stream = "posts"
            payload_mode = "full"

        @classmethod
        def authorize_subscription(cls, info: Any, **kwargs: Any) -> None:
            user = getattr(getattr(info, "context", None), "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                from graphql import GraphQLError

                raise GraphQLError("authentication required")

    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        post = _AuthRequiredPost.Field()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(
        query=Query, subscription=SubscriptionRoot
    ).graphql_schema

    view = sse.subscription_sse_view(schema=schema)
    query = "subscription { post(action: CREATE) { id title } }"
    request = _make_request(query, authenticated=False)

    response = await view(request)

    # No live source was started (deny short-circuited before any group_add).
    started = sse.get_started_source(response)
    assert started is None

    # The denial is surfaced: either a 200 in-stream error frame then complete, or
    # an error response. Whichever it is, NO group was ever joined.
    if response.status_code == 200:
        frames = await _drain_frames(response, max_frames=3)
        joined = "".join(frames)
        assert "authentication required" in joined or "event: complete" in joined
    else:
        assert response.status_code in (401, 403, 400)
    # Crucially: the channel layer never joined a group for a denied subscribe.
    assert layer.groups == {} or all(not chans for chans in layer.groups.values())


# ---------------------------------------------------------------------------
# 4) disconnect/teardown → source.aclose() → every joined group discarded
# ---------------------------------------------------------------------------


async def test_client_disconnect_acloses_source_and_discards_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client abort must aclose() the source and discard every joined group.

    Contract: this test ships broken if a disconnected client leaves a ghost
    subscriber behind (a joined group never discarded).

    Closing the streaming async generator (the ASGI handler does this on client
    disconnect via GeneratorExit) must run the transport's try/finally
    teardown: source.aclose() -> group_discard for every joined group, so
    no ghost subscriber survives.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    discards: list[tuple[str, str]] = []

    class _RecordingLayer(InMemoryChannelLayer):
        """An in-memory channel layer that records every group_discard call."""

        async def group_discard(self, group: str, channel: str) -> None:
            """Record the discard and delegate to the real implementation.

            Args:
                group: The group name being discarded.
                channel: The channel name being removed from the group.
            """
            discards.append((group, channel))
            return await super().group_discard(group, channel)

    layer = _RecordingLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    schema = build_native_schema()
    view = sse.subscription_sse_view(schema=schema)
    request = _make_request("subscription { post(action: CREATE) { id title } }")

    response = await view(request)
    assert response.status_code == 200

    started = sse.get_started_source(response)
    assert started is not None
    joined = set(started.joined_groups)
    assert joined  # the subscribe joined at least one group

    # Begin iterating so the generator is primed (a pull parks in receive()),
    # then simulate a client disconnect: the ASGI handler cancels the consuming
    # task and closes the async generator (GeneratorExit → the view's finally).
    aiter = sse_frames(response).__aiter__()
    pull = asyncio.ensure_future(aiter.__anext__())
    await asyncio.sleep(0)  # let the pull park in receive()
    # Cancel the in-flight pull FIRST (cannot aclose a running generator), drain
    # the cancellation, THEN aclose the generator so its finally runs teardown.
    pull.cancel()
    try:
        await pull
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()

    # The teardown discarded EVERY joined group (no ghost subscriber).
    assert started.is_closed
    discarded_groups = {g for g, _ in discards}
    assert joined <= discarded_groups, (
        f"every joined group must be discarded on disconnect; "
        f"joined={joined} discarded={discarded_groups}"
    )


# ---------------------------------------------------------------------------
# 4b) assertNumQueries(0) on the delivery path (serialize-once)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
async def test_delivery_path_is_zero_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delivering one event over the SSE stream must issue zero DB queries.

    Contract: this test ships broken if the delivery path re-serializes or
    instantiates a model instead of projecting the pre-serialized flat dict.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from asgiref.sync import sync_to_async
    from django.db import connection, reset_queries

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    schema = build_native_schema()
    view = sse.subscription_sse_view(schema=schema)
    response = await view(
        _make_request("subscription { post(action: CREATE) { id title author tags } }")
    )
    assert response.status_code == 200

    started = sse.get_started_source(response)
    group = started.joined_groups[0]
    flat = {
        "id": 1,
        "title": "hi",
        "body": "",
        "views": 0,
        "author": 7,
        "category": 9,
        "tags": [3],
        "co_authors": [7, 8],
    }
    await layer.group_send(group, _notify(group, flat))

    @sync_to_async
    def _enable_query_log():
        connection.ensure_connection()
        connection.force_debug_cursor = True
        reset_queries()

    @sync_to_async
    def _query_count():
        return len(connection.queries)

    aiter = sse_frames(response).__aiter__()
    await _enable_query_log()
    first = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
    n_queries = await _query_count()
    await started.aclose()
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()

    first = first.decode() if isinstance(first, (bytes, bytearray)) else first
    assert first.startswith("event: next\n")
    assert n_queries == 0


# ---------------------------------------------------------------------------
# 5) settings: the view reads graphql_api_settings (no graphene_settings)
# ---------------------------------------------------------------------------


def test_view_reads_max_validation_errors_via_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SSE view must read MAX_VALIDATION_ERRORS through "graphql_api_settings".

    Contract: this is a static gate (mirrors the kept HTTP view's regression
    test) — ships broken if the module stops referencing the unified reader
    or reintroduces "graphene_settings" (the no-graphene-import gate).

    Args:
        monkeypatch: Unused; kept for parity with the module's other tests.
    """
    from django_graphex.subscriptions.transports import sse

    assert hasattr(sse, "graphql_api_settings")
    assert not hasattr(sse, "graphene_settings")


def test_sse_module_does_not_import_graphene() -> None:
    """ "transports/sse.py" must not import graphene (the no-graphene-import gate).

    Contract: this test ships broken if the module gains a real graphene
    import or an import of the legacy graphene_settings symbol.

    Scans the module's AST import statements (not docstring substrings) so an
    explanatory mention of "graphene_settings" in the module docstring does not
    trip the gate — only a real "import graphene" / "from graphene ..." or an
    import of the legacy "graphene_settings" symbol is forbidden.
    """
    import ast
    import inspect

    from django_graphex.subscriptions.transports import sse

    tree = ast.parse(inspect.getsource(sse))
    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add(node.module or "")
            for alias in node.names:
                imported_names.add(alias.name)

    # No graphene import of any kind.
    assert not any(
        m == "graphene" or m.startswith("graphene.") for m in imported_modules
    )
    assert "graphene" not in imported_names
    # The unified settings reader is imported; the legacy graphene_settings is NOT.
    assert "graphql_api_settings" in imported_names
    assert "graphene_settings" not in imported_names


# ---------------------------------------------------------------------------
# 8) The stream opens on connect, not on the first event
# ---------------------------------------------------------------------------


async def test_stream_emits_a_preamble_before_any_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The response body must yield bytes before the first broadcast arrives.

    An ASGI server writes the status line and headers with the first body
    chunk. A generator that yields nothing until an event fires therefore
    leaves the client with no response at all for the whole idle period: the
    browser's fetch never resolves, so the bundled client cannot show a
    connected state, and an intermediary proxy times the silent stream out.

    Contract: this test ships broken if the first chunk of the stream is a
    frame rather than the SSE comment preamble, or if it does not arrive
    without an event being sent.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    view = sse.subscription_sse_view(schema=build_native_schema())
    query = "subscription { post(action: CREATE) { id title } }"
    response = await view(_make_request(query))
    assert response.status_code == 200

    # The RAW stream, not sse_frames: this test is the one that must see the
    # comment chunk the helper exists to hide from every other reader.
    aiter = response.streaming_content.__aiter__()
    # No group_send: nothing has happened yet on the subscription.
    first = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
    first = first.decode() if isinstance(first, (bytes, bytearray)) else first
    assert first == ":\n\n", f"expected an SSE comment preamble, got {first!r}"

    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()


async def test_a_denied_subscribe_also_opens_the_stream_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preamble must precede the in-stream denial frame too.

    A deny is delivered as next+complete inside a committed 200, so it takes
    the same path and must not be the chunk that opens the response.

    Contract: this test ships broken if a denial frame reaches the wire before
    the preamble.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    view = sse.subscription_sse_view(schema=build_native_schema())
    # An unknown field never starts a source, so the stream is pre-resulted.
    response = await view(_make_request("subscription { nope(action: CREATE) { id } }"))
    # The RAW stream, for the same reason as the test above.
    chunks: list[str] = []
    async for chunk in response.streaming_content:
        chunks.append(
            chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        )
    assert chunks[0] == ":\n\n", f"expected the preamble first, got {chunks[0]!r}"
    assert any("event: complete" in chunk for chunk in chunks)


async def test_an_ambiguous_multi_subscription_document_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document of several subscriptions must be refused for AMBIGUITY.

    "get_operation_ast" returns None both when the single operation is not a
    subscription and when the document carries several and the request named
    none. Reporting the second as the first sends the caller hunting for a
    query or mutation that is not in their document; the fix is an
    "operationName", and the refusal has to say so.

    Contract: this test ships broken if an ambiguous document is refused with
    the operation-kind message instead of naming "operationName".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=build_native_schema())

    both = (
        "subscription A { post(action: CREATE) { id } }\n"
        "subscription B { post(action: UPDATE) { id } }"
    )
    response = await view(_make_request(both))
    assert response.status_code == 400
    body = response.content.decode()
    assert "operationName" in body, body
    assert "only serves subscription" not in body, body

    # Naming one of them is what makes the same document servable.
    named = _make_request(both)
    named._body = json.dumps({"query": both, "operationName": "A"}).encode()
    ok = await view(named)
    assert ok.status_code == 200
