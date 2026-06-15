# -*- coding: utf-8 -*-
"""WARNING-1 close-out (verify #1522) — SSE transport branch coverage top-up.

Phase 6 verify flagged ``transports/sse.py`` at 86.92% combined branch. The
conformance suite (``test_transport_sse.py``) covers next/complete framing,
in-stream validation errors, auth deny, and serialize-once; the misses are the
PRE-200 client-error 4xx paths, the request-body parsing fallbacks, the
``TransportContext`` session branch, and the no-source complete-only stream.

Targeted sse.py branches:
  * 122-124   — ``TransportContext`` adds ``session`` to scope when present.
  * 138-143   — ``_read_request_body`` JSON-decode error → {} AND the form-POST arm.
  * 222-224   — no query → ``HttpResponseBadRequest`` (PRE-200 4xx).
  * 228-229   — a syntax error → ``HttpResponseBadRequest`` (PRE-200 4xx).
  * 232-234   — a non-subscription operation → ``HttpResponseBadRequest``.
  * 278->280  — the no-source stream with NO pre-stream result → complete-only.
  * 281       — the ``return`` after the complete frame on the no-source path.

Each test asserts a real HTTP status / frame / context value. Native-gated.
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


class _User:
    def __init__(self, *, authenticated: bool = True):
        self.is_authenticated = authenticated
        self.pk = 1 if authenticated else None


def _json_request(query, *, variables=None, operation_name=None):
    from django.test import RequestFactory

    body = {"query": query}
    if variables is not None:
        body["variables"] = variables
    if operation_name is not None:
        body["operationName"] = operation_name
    request = RequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps(body),
        content_type="application/json",
    )
    request.user = _User()
    return request


# ---------------------------------------------------------------------------
# 122-124 — TransportContext adds session to scope when present
# ---------------------------------------------------------------------------


@native_only
def test_transport_context_includes_session_when_present():
    """``TransportContext`` exposes ``.user`` and threads ``session`` into scope.

    Covers sse.py:122-124 — the ``session is not None`` arm. A request WITH a
    session puts it in scope; a request WITHOUT one leaves scope session-free.
    """
    from django.test import RequestFactory

    from django_graphex.subscriptions.transports.sse import TransportContext

    user = _User()
    sentinel_session = {"sid": "abc"}

    with_session = RequestFactory().post("/x")
    with_session.user = user
    with_session.session = sentinel_session
    ctx = TransportContext(with_session)
    assert ctx.user is user
    assert ctx.scope["user"] is user
    assert ctx.scope["session"] is sentinel_session

    # No session attr → scope carries only the user (the False arm).
    no_session = RequestFactory().post("/x")
    no_session.user = user
    if hasattr(no_session, "session"):
        del no_session.session
    ctx2 = TransportContext(no_session)
    assert "session" not in ctx2.scope


# ---------------------------------------------------------------------------
# 138-143 — request-body parsing: JSON error fallback + form POST arm
# ---------------------------------------------------------------------------


@native_only
def test_read_request_body_malformed_json_yields_empty_fields():
    """Malformed JSON in an application/json body → all fields ``None``.

    Covers sse.py:138-141 — the ``except (ValueError, UnicodeDecodeError)`` arm
    sets ``body = {}`` so query/variables/operationName all read ``None``.
    """
    from django.test import RequestFactory

    from django_graphex.subscriptions.transports.sse import _read_request_body

    request = RequestFactory().post(
        "/x", data="{not valid json", content_type="application/json"
    )
    parsed = _read_request_body(request)
    assert parsed == {"query": None, "variables": None, "operationName": None}


@native_only
def test_read_request_body_form_encoded_reads_post():
    """A form-encoded body reads ``query`` from ``request.POST``.

    Covers sse.py:142-143 — the non-JSON ``else: body = request.POST`` arm.
    """
    from django.test import RequestFactory

    from django_graphex.subscriptions.transports.sse import _read_request_body

    request = RequestFactory().post(
        "/x",
        data={"query": "subscription { post(action: CREATE) { id } }"},
    )
    parsed = _read_request_body(request)
    assert parsed["query"] == "subscription { post(action: CREATE) { id } }"
    assert parsed["variables"] is None
    assert parsed["operationName"] is None


# ---------------------------------------------------------------------------
# 222-224 — no query → PRE-200 HttpResponseBadRequest
# ---------------------------------------------------------------------------


@native_only
async def test_no_query_is_pre_200_bad_request(monkeypatch):
    """A request with NO query → HTTP 400 (PRE-200, never a stream).

    Covers sse.py:222-224 — the ``if not query`` arm.
    """
    from django.http import HttpResponseBadRequest

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    view = sse.subscription_sse_view(schema=_build_native_schema())
    response = await view(_json_request(""))
    assert isinstance(response, HttpResponseBadRequest)
    assert response.status_code == 400
    assert b"No GraphQL query" in response.content


# ---------------------------------------------------------------------------
# 228-229 — syntax error → PRE-200 HttpResponseBadRequest
# ---------------------------------------------------------------------------


@native_only
async def test_syntax_error_is_pre_200_bad_request(monkeypatch):
    """A query with a syntax error → HTTP 400 (PRE-200, never a stream).

    Covers sse.py:226-229 — the ``parse`` exception arm.
    """
    from django.http import HttpResponseBadRequest

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    view = sse.subscription_sse_view(schema=_build_native_schema())
    response = await view(_json_request("subscription {{{"))
    assert isinstance(response, HttpResponseBadRequest)
    assert response.status_code == 400
    assert b"syntax error" in response.content.lower()


# ---------------------------------------------------------------------------
# 232-234 — a non-subscription operation → PRE-200 HttpResponseBadRequest
# ---------------------------------------------------------------------------


@native_only
async def test_non_subscription_operation_is_pre_200_bad_request(monkeypatch):
    """A ``query`` operation over the SSE transport → HTTP 400 (PRE-200).

    Covers sse.py:231-234 — the ``operation != SUBSCRIPTION`` arm. Also covers the
    ``operation_ast is None`` short-circuit when no operation matches the name.
    """
    from django.http import HttpResponseBadRequest

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    view = sse.subscription_sse_view(schema=_build_native_schema())
    response = await view(_json_request("query { ok }"))
    assert isinstance(response, HttpResponseBadRequest)
    assert response.status_code == 400
    assert b"only serves subscription" in response.content


@native_only
async def test_unknown_operation_name_is_pre_200_bad_request(monkeypatch):
    """An ``operationName`` matching no operation → HTTP 400 (operation_ast None).

    Covers sse.py:232 — the ``operation_ast is None`` arm of the guard.
    """
    from django.http import HttpResponseBadRequest

    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    view = sse.subscription_sse_view(schema=_build_native_schema())
    response = await view(
        _json_request(
            "subscription Sub { post(action: CREATE) { id } }",
            operation_name="DoesNotExist",
        )
    )
    assert isinstance(response, HttpResponseBadRequest)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 278->280 + 281 — no-source stream with NO pre-stream result → complete-only
# ---------------------------------------------------------------------------


@native_only
async def test_no_source_no_pre_result_streams_complete_only(monkeypatch):
    """When neither a source NOR a pre-stream result exists → a complete-only stream.

    Covers sse.py:277-281 — the ``started_source is None`` branch with
    ``pre_stream_result is None`` (the inner ``if`` False arm) → the stream emits
    ONLY the terminal ``complete`` frame and returns. We force this by stubbing
    ``create_source_event_stream`` to return ``None`` (no source, no result).
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    async def _none_source(*args, **kwargs):
        return None  # neither an ExecutionResult nor a source

    monkeypatch.setattr(sse, "create_source_event_stream", _none_source)

    view = sse.subscription_sse_view(schema=_build_native_schema())
    query = "subscription { post(action: CREATE) { id title } }"
    response = await view(_json_request(query))
    assert response.status_code == 200

    # No started source was recorded.
    assert sse.get_started_source(response) is None

    aiter = response.streaming_content.__aiter__()
    frames = []
    for _ in range(3):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
        except StopAsyncIteration:
            break
        frames.append(
            chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        )
    # ONLY the terminal complete frame — no ``next`` frame (no pre-stream result).
    assert frames == ["event: complete\ndata: \n\n"]


@native_only
async def test_no_source_with_pre_result_streams_next_then_complete(monkeypatch):
    """A pre-stream result (no source) → a single ``next`` then ``complete``.

    Pairs with the complete-only test to pin the ``pre_stream_result is not None``
    True arm (sse.py:278-279). A validation error yields an in-stream ``next``
    frame then ``complete`` — confirming both arms of the no-source path.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    view = sse.subscription_sse_view(schema=_build_native_schema())
    # An undeclared field → a validation error → a pre-stream result, no source.
    query = "subscription { post(action: CREATE) { id nope } }"
    response = await view(_json_request(query))
    assert response.status_code == 200
    assert sse.get_started_source(response) is None

    aiter = response.streaming_content.__aiter__()
    frames = []
    for _ in range(3):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
        except StopAsyncIteration:
            break
        frames.append(
            chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        )
    joined = "".join(frames)
    assert "event: next" in joined
    assert "event: complete\ndata: \n\n" in joined
