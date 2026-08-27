# -*- coding: utf-8 -*-
"""Regression tests for the post-2.1.0 subscription audit defects.

One test per reported symptom, each written from the reproduction:

  * a client filter whose lookup the schema accepts but the ORM refuses used to
    raise "FieldError" INSIDE the delivery generator, after the SSE 200 was
    committed (and, on WebSocket, killed the operation task with no frame at
    all);
  * an undecodable JSON frame and a non-hashable operation "id" raised OUT of
    the consumer, so "disconnect" never ran and every live operation leaked its
    task and its channel-layer group;
  * an SSE response that is closed without ever being iterated left its groups
    joined forever;
  * "Meta.stream" was absent from the Channels group names, so two
    subscriptions on the same model cross-delivered each other's events;
  * "subscription_scope" / "authorize_subscription" received a context with no
    ".context" attribute, so every documented hook crashed the subscribe;
  * the bundled browser client had no SSE endpoint of its own;
  * a model carrying a "FileField" / "BinaryField" crashed the broadcast
    serializer.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from graphql import GraphQLSchema

pytest.importorskip("channels")

from asgiref.sync import sync_to_async  # noqa: E402
from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402

from django_graphex.types import DjangoObjectType as _DOT  # noqa: E402
from tests.models import Post  # noqa: E402
from tests.subscriptions._sse import sse_frames  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# Helpers — node types + a native subscription schema mounting a PostModelType
# SubscriptionField (module-scope registration mirrors test_transport_sse: a
# DjangoObjectType is identity-stable, per-test registration pollutes the shared
# output registry).
# ---------------------------------------------------------------------------


class _AuditTagT(_DOT):
    class Meta:
        model = __import__("tests.models", fromlist=["Tag"]).Tag


class _AuditCategoryT(_DOT):
    class Meta:
        model = __import__("tests.models", fromlist=["Category"]).Category


class _AuditAuthorT(_DOT):
    class Meta:
        model = __import__("tests.models", fromlist=["Author"]).Author


class _AuditPostT(_DOT):
    class Meta:
        model = Post


def _build_native_schema(subscription_type: Any = None) -> GraphQLSchema:
    """Assemble a native subscription schema mounting one subscription field.

    Args:
        subscription_type: The "DjangoModelType" subclass to mount, or "None"
            to build the default "PostModelType" (stream "posts", full payload).

    Returns:
        The assembled graphql-core "GraphQLSchema" with a "post" subscription.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    if subscription_type is None:

        class PostModelType(DjangoModelType):
            class Meta:
                model = Post
                stream = "posts"
                payload_mode = "full"

        subscription_type = PostModelType

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        post = subscription_type.SubscriptionField()

    compile_all_outputs()
    return DjangoGraphQLSchema(
        query=Query, subscription=SubscriptionRoot
    ).graphql_schema


class _User:
    """A minimal authenticated user stand-in exposing "is_authenticated"/"pk"."""

    def __init__(self, *, pk: int = 1) -> None:
        """Store the stand-in primary key.

        Args:
            pk: The primary key the stand-in reports.
        """
        self.is_authenticated = True
        self.pk = pk


def _make_request(query: str) -> Any:
    """Build an async-capable HTTP request carrying a subscription document.

    Args:
        query: The GraphQL subscription document to send as the request body.

    Returns:
        The constructed Django test request with an authenticated user.
    """
    from django.test import RequestFactory

    request = RequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    request.user = _User()
    return request


def _notify(group: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a producer-shaped "subscription.notify" envelope (bindings.py).

    Args:
        group: The channel-layer group name the message targets.
        data: The serialized flat payload data to embed in the message.

    Returns:
        The assembled notify message dict.
    """
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": 1,
        "payload": {"action": "create", "model": "tests.post", "data": data},
    }


async def _read_frames(response: Any, *, limit: int = 4) -> list[str]:
    """Pull up to "limit" SSE frames from a streaming response.

    Args:
        response: The "StreamingHttpResponse" to read frames from.
        limit: The maximum number of frames to pull.

    Returns:
        The decoded frame strings, stopping early at the "complete" frame.
    """
    frames: list[str] = []
    aiter = sse_frames(response).__aiter__()
    for _ in range(limit):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=2.0)
        except StopAsyncIteration:
            break
        frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if "event: complete" in frames[-1]:
            break
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()
    return frames


async def _ws_connect(schema: GraphQLSchema) -> tuple[Any, Any, Any]:
    """Open an acknowledged graphql-transport-ws socket against "schema".

    Args:
        schema: The native schema the consumer serves.

    Returns:
        A "(ws module, communicator, live consumer)" tuple.
    """
    from django_graphex.subscriptions.transports import ws

    consumer = ws.subscription_ws_consumer(schema=schema)
    communicator = WebsocketCommunicator(
        consumer.as_asgi(), "/graphql/", subprotocols=["graphql-transport-ws"]
    )
    communicator.scope["user"] = _User()
    connected, _subprotocol = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "connection_init"})
    assert (await communicator.receive_json_from(timeout=2))["type"] == "connection_ack"
    return ws, communicator, ws.get_live_consumer(communicator.scope)


async def _await_source(consumer: Any, op_id: str) -> Any:
    """Poll until operation "op_id" has started its source; return the source.

    Args:
        consumer: The live WS consumer instance.
        op_id: The operation id whose source is awaited.

    Returns:
        The started "ChannelLayerSource".
    """
    for _ in range(100):
        source = consumer.started_source(op_id)
        if source is not None:
            return source
        await asyncio.sleep(0.02)
    raise AssertionError(f"operation {op_id!r} never started a source")


async def _failing_db_verify(_remaining: Any, _event: Any) -> bool:
    """Fail the per-event database verification hook.

    Args:
        _remaining: The unresolved lookup filters (unused).
        _event: The flat serialized event (unused).

    Returns:
        Never returns normally.

    Raises:
        RuntimeError: Always, standing in for any delivery-time failure.
    """
    raise RuntimeError("delivery blew up")


async def _explode() -> None:
    """Fail immediately, standing in for an operation task that crashed.

    Raises:
        RuntimeError: Always.
    """
    raise RuntimeError("operation blew up")


_SUB_QUERY = "subscription { post(action: CREATE) { id title } }"
_BAD_LOOKUP_QUERY = (
    "subscription { post(action: CREATE, filter: {tags: {iexact: 1}}) { id } }"
)


# ---------------------------------------------------------------------------
# 1) A client filter the ORM refuses is rejected AT SUBSCRIBE, not at delivery.
# ---------------------------------------------------------------------------


async def test_orm_rejected_client_lookup_is_refused_at_subscribe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A to-many "iexact" filter must be denied before any group is joined.

    Contract: this test ships broken if a filter key the schema declares but the
    ORM refuses reaches delivery, where "FieldError" escapes the streaming
    generator after the 200 response was committed.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=_build_native_schema())

    response = await view(_make_request(_BAD_LOOKUP_QUERY))

    assert response.status_code == 200
    assert sse.get_started_source(response) is None, (
        "an ORM-invalid client filter must short-circuit BEFORE any group_add"
    )
    frames = await _read_frames(response)
    assert frames[0].startswith("event: next\n")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert "iexact" in payload["errors"][0]["message"]
    assert frames[-1] == "event: complete\ndata: \n\n"
    assert not layer.groups


async def test_sse_delivery_exception_is_framed_in_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delivery-time exception must be framed in-stream, never escape the 200.

    Contract: this test ships broken if an exception raised while the SSE
    generator is producing frames escapes the "StreamingHttpResponse" instead of
    being delivered as "next{errors}" followed by "complete".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=_build_native_schema())

    response = await view(_make_request(_SUB_QUERY))
    source = sse.get_started_source(response)
    group = source.joined_groups[0]

    source.filters = {"tags__exact": 1}
    source.db_verify = _failing_db_verify
    await layer.group_send(group, _notify(group, {"id": 1, "title": "t"}))

    frames = await _read_frames(response)
    assert frames[0].startswith("event: next\n")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["errors"][0]["message"] == "delivery blew up"
    assert frames[-1] == "event: complete\ndata: \n\n"

    await sync_to_async(response.close)()
    assert source.is_closed


# ---------------------------------------------------------------------------
# 2) A malformed inbound frame closes with 4400 instead of leaking the socket.
# ---------------------------------------------------------------------------


async def test_undecodable_json_frame_closes_and_discards_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An undecodable text frame must close with 4400 and tear every op down.

    Contract: this test ships broken if the JSON decode error escapes the
    consumer, leaving the live operation's task registered and its channel-layer
    group joined.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    _ws, communicator, consumer = await _ws_connect(_build_native_schema())
    await communicator.send_json_to(
        {"type": "subscribe", "id": "1", "payload": {"query": _SUB_QUERY}}
    )
    source = await _await_source(consumer, "1")

    await communicator.send_to(text_data="{not json")

    close = await communicator.receive_output(timeout=2)
    assert close["type"] == "websocket.close"
    assert close["code"] == 4400
    assert consumer.operation_ids() == set()
    assert source.is_closed
    assert not any(layer.groups.get(group) for group in source.joined_groups)
    await communicator.disconnect()


async def test_unhashable_operation_id_closes_and_discards_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-hashable "id" must close with 4400 and tear every op down.

    Contract: this test ships broken if the "TypeError: unhashable type" from
    the duplicate-id registry lookup escapes the consumer, leaving the live
    operation's task registered and its channel-layer group joined.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    _ws, communicator, consumer = await _ws_connect(_build_native_schema())
    await communicator.send_json_to(
        {"type": "subscribe", "id": "1", "payload": {"query": _SUB_QUERY}}
    )
    source = await _await_source(consumer, "1")

    await communicator.send_json_to({"type": "subscribe", "id": ["x"], "payload": {}})

    close = await communicator.receive_output(timeout=2)
    assert close["type"] == "websocket.close"
    assert close["code"] == 4400
    assert consumer.operation_ids() == set()
    assert source.is_closed
    assert not any(layer.groups.get(group) for group in source.joined_groups)
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 3) A delivery exception ends the WS operation with a protocol signal.
# ---------------------------------------------------------------------------


async def test_ws_delivery_exception_sends_error_then_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delivery-time exception must yield "next{errors}" then "complete".

    Contract: this test ships broken if the operation task dies silently — no
    frame at all — leaving the client waiting forever on a dead subscription.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    _ws, communicator, consumer = await _ws_connect(_build_native_schema())
    await communicator.send_json_to(
        {"type": "subscribe", "id": "1", "payload": {"query": _SUB_QUERY}}
    )
    source = await _await_source(consumer, "1")

    source.filters = {"tags__exact": 1}
    source.db_verify = _failing_db_verify
    group = source.joined_groups[0]
    await layer.group_send(group, _notify(group, {"id": 1, "title": "t"}))

    error_frame = await communicator.receive_json_from(timeout=2)
    assert error_frame["type"] == "next"
    assert error_frame["payload"]["errors"][0]["message"] == "delivery blew up"
    complete = await communicator.receive_json_from(timeout=2)
    assert complete == {"id": "1", "type": "complete"}
    assert source.is_closed
    await communicator.disconnect()


async def test_finished_operation_task_exception_is_retrieved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed operation task must have its exception retrieved and logged.

    Contract: this test ships broken if the per-task done callback only pops the
    registry — an unretrieved task exception surfaces as asyncio's "Task
    exception was never retrieved" warning at collection time instead of a log
    line naming the operation.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    import logging

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    ws, communicator, consumer = await _ws_connect(_build_native_schema())

    task = asyncio.ensure_future(_explode())
    with pytest.raises(RuntimeError):
        await task

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    ws.logger.addHandler(handler)
    try:
        consumer._operation_done("9", task)
    finally:
        ws.logger.removeHandler(handler)

    assert "9" in records[0].getMessage()
    assert records[0].exc_info[1] is task.exception()
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# 5) An SSE response closed without being iterated must discard its groups.
# ---------------------------------------------------------------------------


async def test_sse_response_close_without_iteration_discards_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing an un-iterated SSE response must discard every joined group.

    Contract: this test ships broken if teardown lives ONLY in the streaming
    generator's "finally" — a client that aborts during the subscribe handshake
    then leaves a ghost group member every future broadcast fans out to.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=_build_native_schema())

    response = await view(_make_request(_SUB_QUERY))
    source = sse.get_started_source(response)
    assert source.joined_groups
    assert any(layer.groups.get(group) for group in source.joined_groups)

    # Django's ASGI handler closes the response from a worker thread.
    await sync_to_async(response.close)()

    assert source.is_closed
    assert not any(layer.groups.get(group) for group in source.joined_groups)


async def test_sse_response_close_is_a_no_op_after_the_stream_tore_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing a response whose source is already closed must not tear down twice.

    Contract: this test ships broken if the response-close teardown is not a
    no-op on an already-closed source — the normal path (the streaming generator
    ran its own cleanup) would then run a second discard sweep per request.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=_build_native_schema())

    response = await view(_make_request(_SUB_QUERY))
    source = sse.get_started_source(response)
    await source.aclose()

    await sync_to_async(response.close)()

    assert source.is_closed
    assert source.joined_groups == []


# ---------------------------------------------------------------------------
# 7) Meta.stream participates in the Channels group names.
# ---------------------------------------------------------------------------


def test_group_names_are_scoped_by_stream() -> None:
    """Two subscriptions on one model with different streams must not collide.

    Contract: this test ships broken if "Meta.stream" is absent from the group
    name — both bindings register (their dispatch uid DOES carry the stream) and
    both fan out into the identical groups, so a full-payload subscriber gets a
    duplicate all-null event per change.
    """
    from django_graphex.subscriptions import Subscription

    class _StreamAlphaSubscription(Subscription):
        class Meta:
            model = Post
            stream = "alpha"
            payload_mode = "full"

    class _StreamBetaSubscription(Subscription):
        class Meta:
            model = Post
            stream = "beta"
            payload_mode = "id_only"

    alpha = _StreamAlphaSubscription._group_name("create")
    beta = _StreamBetaSubscription._group_name("create")

    assert alpha != beta
    assert "alpha" in alpha
    assert "beta" in beta
    # The per-object and value-scoped variants stay distinct too.
    assert _StreamAlphaSubscription._group_name(
        "create", id=1
    ) != _StreamBetaSubscription._group_name("create", id=1)


def test_broadcast_reaches_only_its_own_stream_groups(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """One model change must not fan out into another stream's groups.

    Contract: this test ships broken if a single "Post" save sends the same
    group name for two different streams — the duplicate-delivery symptom.

    Args:
        captured_group_sends: The fixture recording every "group_send" call.
    """
    from django_graphex.subscriptions import Subscription
    from tests.models import Author

    class _FanoutAlphaSubscription(Subscription):
        class Meta:
            model = Post
            stream = "fanout-alpha"
            payload_mode = "full"

    class _FanoutBetaSubscription(Subscription):
        class Meta:
            model = Post
            stream = "fanout-beta"
            payload_mode = "id_only"

    _FanoutAlphaSubscription.get_binding()
    _FanoutBetaSubscription.get_binding()
    try:
        author = Author.objects.create(name="a")
        Post.objects.create(title="t", author=author)
    finally:
        _FanoutAlphaSubscription.get_binding().unregister()
        _FanoutBetaSubscription.get_binding().unregister()

    by_stream: dict[str, set[str]] = {}
    for group, message in captured_group_sends:
        by_stream.setdefault(message["stream"], set()).add(group)

    assert by_stream["fanout-alpha"]
    assert by_stream["fanout-beta"]
    assert not (by_stream["fanout-alpha"] & by_stream["fanout-beta"])


# ---------------------------------------------------------------------------
# P1) The subscribe hooks receive a context exposing ".context".
# ---------------------------------------------------------------------------


async def test_documented_subscription_scope_hook_works_over_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented "info.context.user" scope hook must start a source.

    Contract: this test ships broken if the transport context does not expose
    ".context" — the documented row-scoping primitive then fails closed on every
    subscribe with "'TransportContext' object has no attribute 'context'".

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse
    from django_graphex.types import DjangoModelType

    class _ScopedPostType(DjangoModelType):
        class Meta:
            model = Post
            stream = "sse-scoped-posts"
            payload_mode = "full"

        @classmethod
        def subscription_scope(
            cls, info: Any, **kwargs: Any
        ) -> "dict[str, Any] | None":
            """Scope the stream to the requesting user's own rows.

            Args:
                info: The subscribe context, used exactly as documented.
                **kwargs: The subscription arguments (unused).

            Returns:
                The server-forced filter mapping.
            """
            return {"author": info.context.user.pk}

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=_build_native_schema(_ScopedPostType))

    response = await view(_make_request(_SUB_QUERY))
    source = sse.get_started_source(response)

    assert source is not None, "the documented scope hook must not fail closed"
    assert source.filters == {"author": 1}
    await source.aclose()


async def test_documented_subscription_scope_hook_works_over_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented "info.context.user" scope hook must work on WebSocket too.

    Contract: this test ships broken if the WS transport context does not expose
    ".context" — the documented row-scoping primitive is then dead on BOTH
    transports, not just SSE.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.types import DjangoModelType

    class _WsScopedPostType(DjangoModelType):
        class Meta:
            model = Post
            stream = "ws-scoped-posts"
            payload_mode = "full"

        @classmethod
        def subscription_scope(
            cls, info: Any, **kwargs: Any
        ) -> "dict[str, Any] | None":
            """Scope the stream to the requesting user's own rows.

            Args:
                info: The subscribe context, used exactly as documented.
                **kwargs: The subscription arguments (unused).

            Returns:
                The server-forced filter mapping.
            """
            return {"author": info.context.user.pk}

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    _ws, communicator, consumer = await _ws_connect(
        _build_native_schema(_WsScopedPostType)
    )
    await communicator.send_json_to(
        {"type": "subscribe", "id": "1", "payload": {"query": _SUB_QUERY}}
    )

    source = await _await_source(consumer, "1")
    assert source.filters == {"author": 1}
    assert source.joined_groups
    await communicator.disconnect()


# ---------------------------------------------------------------------------
# P2) The bundled client has its own SSE endpoint.
# ---------------------------------------------------------------------------


def test_client_view_renders_a_dedicated_sse_path() -> None:
    """The client must seed its SSE field from "sse_path", not "http_path".

    Contract: this test ships broken if the SSE input is seeded from the HTTP
    GraphQL route — the first-run playground then POSTs a subscription to the
    JSON endpoint, gets a 200 "application/json" body with no "event:" line, and
    shows a connected stream with zero data and zero errors.
    """
    from django.test import RequestFactory

    from django_graphex.subscriptions.client import SubscriptionClientView

    assert SubscriptionClientView.sse_path == "/graphql/stream"

    view = SubscriptionClientView.as_view(
        sse_path="/custom/stream", http_path="/custom/graphql/"
    )
    body = view(RequestFactory().get("/graphql/client/")).content.decode()

    assert "__SSE_PATH__" not in body
    assert '$("gdsx-sse").value=loc.protocol+"//"+loc.host+"/custom/stream"' in body
    assert '$("gdsx-http").value=loc.protocol+"//"+loc.host+"/custom/graphql/"' in body


def test_client_logs_unrecognised_sse_event_types() -> None:
    """The client must surface an "error"/unknown SSE frame instead of dropping it.

    Contract: this test ships broken if "flushFrame" only handles "next" and
    "complete" — any other frame (including a plain JSON error body served with
    no "event:" line) is silently discarded and the user sees nothing at all.
    """
    from importlib import resources

    html = (
        resources.files("django_graphex.subscriptions")
        .joinpath("_subscription_client.html")
        .read_text(encoding="utf-8")
    )

    frame_fn = html.split("function flushFrame(frame){", 1)[1].split("\n    }", 1)[0]
    assert 'eventType==="next"' in frame_fn
    assert 'eventType==="complete"' in frame_fn
    assert "else{" in frame_fn.replace(" ", "")
    assert 'log("error"' in frame_fn


# ---------------------------------------------------------------------------
# 6) File and binary columns serialize JSON-safely.
# ---------------------------------------------------------------------------


def test_file_and_binary_columns_are_json_safe() -> None:
    """A "FileField" / "BinaryField" must serialize to a JSON-safe value.

    Contract: this test ships broken if "to_representation" hands the raw
    "FieldFile" / "bytes" to the broadcast serializer, which then raises
    "TypeError: Object of type FieldFile is not JSON serializable" on every save
    of a model carrying one of those columns.
    """
    import base64

    from django_graphex.core.backend import PydanticBackend
    from django_graphex.subscriptions.mixins import serialize_instance
    from tests.models import BinaryDoc

    doc = BinaryDoc.objects.create(
        label="x", attachment="docs/report.pdf", blob=b"\x00\xffbin"
    )
    backend = PydanticBackend(BinaryDoc)

    raw = backend.to_representation(doc)
    assert raw["attachment"] == "docs/report.pdf"
    assert raw["blob"] == base64.b64encode(b"\x00\xffbin").decode("ascii")

    payload = serialize_instance(backend, doc)
    assert payload["attachment"] == "docs/report.pdf"
    assert payload["blob"] == raw["blob"]


def test_empty_file_and_binary_columns_serialize_to_empty_values() -> None:
    """An unset "FileField" / "BinaryField" must serialize without crashing.

    Contract: this test ships broken if the JSON-safe coercion assumes a value
    is always present — a blank file name and an empty blob are the default
    state of the columns.
    """
    from django_graphex.core.backend import PydanticBackend
    from django_graphex.subscriptions.mixins import serialize_instance
    from tests.models import BinaryDoc

    doc = BinaryDoc.objects.create(label="y")
    payload = serialize_instance(PydanticBackend(BinaryDoc), doc)

    assert payload["attachment"] == ""
    assert payload["blob"] == ""
