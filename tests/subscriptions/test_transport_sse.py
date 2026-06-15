# -*- coding: utf-8 -*-
"""WU8 — SSE transport adapter (transports/sse.py).

The SSE transport is the FIRST (cheap) engine validator (design §7): an async
Django view (Django>=5.2 → clean disconnect cancellation GUARANTEED) returning a
``StreamingHttpResponse(content_type='text/event-stream')``. ONE HTTP request →
ONE subscription stream.

It drives the serialize-once native engine end-to-end:

  * auth lives in the HTTP request (``request.user`` / session) — this REPLACES
    the deleted channel-ownership guard; an authorize-deny short-circuits BEFORE
    any ``group_add`` (no stream);
  * the request's GraphQL document (query/variables/operationName) is parsed, the
    live native schema obtained, the subscription field's native subscribe entry
    run (→ ``ChannelLayerSource``), then driven via WU5 ``drive_subscription``
    supplying the live schema + parsed ``DocumentNode`` at delivery;
  * each ``ExecutionResult`` is framed ``event: next\\ndata: {json}\\n\\n``; on
    completion ``event: complete\\ndata: \\n\\n`` (the empty ``data:`` is MANDATORY
    or EventSource never fires the ``complete`` event);
  * a validation error AFTER the 200 response started goes IN-STREAM as
    ``next{errors:[...]}`` then ``complete`` — NOT an HTTP 4xx (pre-200
    parse/validate errors MAY be HTTP 4xx);
  * client disconnect / aclosing → ``source.aclose()`` → ``group_discard`` (the
    WU4 sweep releases a blocked receive + discards every joined group), so no
    ghost subscriber survives a teardown;
  * the view reads ``graphex_or_graphene_settings.MAX_VALIDATION_ERRORS`` (NOT
    ``graphene_settings`` — the no-graphene-import gate);
  * ``assertNumQueries(0)`` on the delivery path (serialize-once: the snake
    closure projects the flat pk dict, never the ORM).

All native assertions are gated behind ``GDX_BACKEND=native`` and skipped under
graphene (the bespoke transport stays UNCHANGED until WU11).
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402

from tests.models import Post  # noqa: E402

_NATIVE = os.environ.get("GDX_BACKEND", "graphene") == "native"

native_only = pytest.mark.skipif(
    not _NATIVE, reason="native SSE transport (GDX_BACKEND=native)"
)


# ---------------------------------------------------------------------------
# Helpers — node types + a native subscription schema mounting a PostModelType
# SubscriptionField, mirroring test_capability_parity's module-scope registration
# (a DjangoObjectType is identity-stable; per-test registration pollutes the
# shared output registry).
# ---------------------------------------------------------------------------

if _NATIVE:
    from django_graphex.types import DjangoObjectType as _DOT

    class _TagT(_DOT):
        class Meta:
            model = __import__("tests.models", fromlist=["Tag"]).Tag

    class _CategoryT(_DOT):
        class Meta:
            model = __import__("tests.models", fromlist=["Category"]).Category

    class _AuthorT(_DOT):
        class Meta:
            model = __import__("tests.models", fromlist=["Author"]).Author

    class _PostT(_DOT):
        class Meta:
            model = Post


def _build_native_schema():
    """Assemble a native subscription schema (PostModelType.SubscriptionField)."""
    import graphene

    from django_graphex import DjangoModelType
    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema

    class PostModelType(DjangoModelType):
        class Meta:
            model = Post
            stream = "posts"
            serialize_data = True

    class Query(graphene.ObjectType):
        ok = graphene.Boolean()

    class SubscriptionRoot(graphene.ObjectType):
        post = PostModelType.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=Query, subscription=SubscriptionRoot)
    return schema.graphql_schema


def _notify(group: str, data: dict, *, action: str = "create", pk=1) -> dict:
    """Build a producer-shaped ``subscription.notify`` envelope (bindings.py)."""
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": pk,
        "payload": {"action": action, "model": "tests.post", "data": data},
    }


class _User:
    """A minimal authenticated/anonymous user stand-in."""

    def __init__(self, *, authenticated: bool):
        self.is_authenticated = authenticated
        self.pk = 1 if authenticated else None


def _make_request(query: str, *, authenticated: bool = True, variables=None):
    """Build an async-capable HTTP request carrying a GraphQL subscription body."""
    from django.test import RequestFactory

    body = {"query": query}
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


async def _drain_frames(response, *, max_frames: int, timeout: float = 1.0):
    """Pull up to *max_frames* SSE frames from a StreamingHttpResponse.

    Returns the list of decoded frame strings collected so far. Stops early on
    the ``complete`` frame.
    """
    frames: list[str] = []
    aiter = response.streaming_content.__aiter__()
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


@native_only
async def test_sse_next_frame_then_complete_with_flat_pk_data(monkeypatch):
    """A broadcast event → an ``event: next`` frame with the serialize-once flat
    data (relations as pks per WU7); completion → ``event: complete\\ndata: \\n\\n``.
    """
    from channels.layers import get_channel_layer

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr(
        "channels.layers.get_channel_layer", lambda *a, **k: layer
    )
    # The view also imports get_channel_layer lazily; patch the source too.
    assert get_channel_layer  # referenced for clarity

    schema = _build_native_schema()
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
    aiter = response.streaming_content.__aiter__()
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


@native_only
async def test_post_200_validation_error_is_in_stream_not_http_4xx(monkeypatch):
    """A validation error AFTER the 200 stream started arrives as ``next{errors}``
    then ``complete`` — NEVER an HTTP 4xx.

    The document parses but selects an undeclared field, so validation fails. The
    transport has already committed the 200 ``text/event-stream`` response, so the
    error MUST be delivered in-stream (a 4xx is impossible once the response has
    started). EventSource only sees in-stream frames.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    schema = _build_native_schema()
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


@native_only
async def test_unauthenticated_request_is_rejected_no_stream(monkeypatch):
    """An authorize-deny (unauthenticated) request yields NO stream.

    Auth lives in the HTTP request (``request.user``) — the replacement for the
    deleted channel-ownership guard. The subscription's ``authorize`` raises for
    an anonymous user, which short-circuits BEFORE any ``group_add`` (no source,
    no group joined), and the transport surfaces the denial (no live stream).
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
            serialize_data = True

        @classmethod
        def authorize_subscription(cls, info, **kwargs):
            user = getattr(getattr(info, "context", None), "user", None)
            if user is None or not getattr(user, "is_authenticated", False):
                from graphql import GraphQLError

                raise GraphQLError("authentication required")

    import graphene

    from django_graphex.native.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema

    class Query(graphene.ObjectType):
        ok = graphene.Boolean()

    class SubscriptionRoot(graphene.ObjectType):
        post = _AuthRequiredPost.Field()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=Query, subscription=SubscriptionRoot).graphql_schema

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


@native_only
async def test_client_disconnect_acloses_source_and_discards_groups(monkeypatch):
    """Client abort → ``source.aclose()`` → every joined group discarded.

    Closing the streaming async generator (the ASGI handler does this on client
    disconnect via ``GeneratorExit``) must run the transport's ``try/finally``
    teardown: ``source.aclose()`` → ``group_discard`` for every joined group, so
    no ghost subscriber survives.
    """
    from django_graphex.subscriptions.transports import sse

    discards: list[tuple[str, str]] = []

    class _RecordingLayer(InMemoryChannelLayer):
        async def group_discard(self, group, channel):
            discards.append((group, channel))
            return await super().group_discard(group, channel)

    layer = _RecordingLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    schema = _build_native_schema()
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
    aiter = response.streaming_content.__aiter__()
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


@native_only
@pytest.mark.django_db
async def test_delivery_path_is_zero_queries(monkeypatch):
    """Delivering one event over the SSE stream issues ZERO DB queries.

    The snake-closure projects the serialize-once flat pk dict in memory; the
    transport never re-serializes nor instantiates a model, so a delivered event
    touches the ORM ZERO times.
    """
    from asgiref.sync import sync_to_async
    from django.db import connection, reset_queries

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    schema = _build_native_schema()
    view = sse.subscription_sse_view(schema=schema)
    response = await view(
        _make_request("subscription { post(action: CREATE) { id title author tags } }")
    )
    assert response.status_code == 200

    started = sse.get_started_source(response)
    group = started.joined_groups[0]
    flat = {
        "id": 1, "title": "hi", "body": "", "views": 0,
        "author": 7, "category": 9, "tags": [3], "co_authors": [7, 8],
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

    aiter = response.streaming_content.__aiter__()
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
# 5) settings: the view reads graphex_or_graphene_settings (no graphene_settings)
# ---------------------------------------------------------------------------


@native_only
def test_view_reads_max_validation_errors_via_shim(monkeypatch):
    """The SSE view reads MAX_VALIDATION_ERRORS through ``graphex_or_graphene_settings``.

    Static gate (mirrors the kept HTTP view's regression test): the module must
    reference the shim, NOT ``graphene_settings`` (the no-graphene-import gate).
    """
    from django_graphex.subscriptions.transports import sse

    assert hasattr(sse, "graphex_or_graphene_settings")
    assert not hasattr(sse, "graphene_settings")


@native_only
def test_sse_module_does_not_import_graphene():
    """``transports/sse.py`` must not import graphene (the no-graphene-import gate).

    Scans the module's AST import statements (not docstring substrings) so an
    explanatory mention of ``graphene_settings`` in the module docstring does not
    trip the gate — only a real ``import graphene`` / ``from graphene …`` or an
    import of the legacy ``graphene_settings`` symbol is forbidden.
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
    assert not any(m == "graphene" or m.startswith("graphene.") for m in imported_modules)
    assert "graphene" not in imported_names
    # The settings shim is imported; the legacy graphene_settings is NOT.
    assert "graphex_or_graphene_settings" in imported_names
    assert "graphene_settings" not in imported_names
