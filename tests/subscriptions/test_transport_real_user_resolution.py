# -*- coding: utf-8 -*-
"""Both transports against a REAL, unresolved request/scope user.

Every other transport test hands the view a user that is already an ordinary
Python object ("request.user = _User(...)"), and the playground's end-to-end
tests use "AnonymousUser()". So the suite never exercised the shape a real
deployment always has: "AuthenticationMiddleware" assigns
"request.user = SimpleLazyObject(lambda: get_user(request))" and leaves it
UNRESOLVED. The first hook that reads it does so inside the async SSE view,
which fires the session/user query in an async context ->
"SynchronousOnlyOperation". An anonymous caller never hits it (an empty session
needs no query), which is precisely why it survived.

This module drives both transports through the REAL middleware chains
("SessionMiddleware" + "AuthenticationMiddleware" for SSE, Channels'
"AuthMiddlewareStack" for WS) instead of injecting a resolved stand-in, and
pins the same matrix on both so the two transports answer to ONE contract:

  * an authenticated caller (session cookie -> a real user row);
  * an anonymous caller (no session cookie at all);
  * a caller whose session references a DELETED user;
  * a caller with no session at all (no session/auth middleware ran);
  * an auth-gated subscription that DENIES, and one that GRANTS.

The gate is observed black-box: the channel layer's "groups" mapping is empty
for a denial and carries the joined group for a grant, so no test needs the
transports' private registries.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.middleware import AuthenticationMiddleware  # noqa: E402
from django.contrib.sessions.middleware import SessionMiddleware  # noqa: E402
from django.test import AsyncRequestFactory, Client  # noqa: E402

from tests.subscriptions._sse import sse_frames  # noqa: E402
from tests.subscriptions._transport_schema import build_auth_gated_schema  # noqa: E402

# The session and user rows must be readable from the worker thread the
# transports resolve the user in, so the writes have to be committed.
pytestmark = pytest.mark.django_db(transaction=True)


_SUB_QUERY = "subscription { post(action: CREATE) { id title } }"

_FLAT_POST = {
    "id": 1,
    "title": "hello",
    "body": "",
    "views": 0,
    "author": 7,
    "category": 9,
    "tags": [3],
    "co_authors": [7, 8],
}


def _notify(group: str) -> dict[str, Any]:
    """Build a producer-shaped "subscription.notify" envelope (bindings.py).

    Args:
        group: The channel-layer group name the message targets.

    Returns:
        message: The assembled notify message dict.
    """
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": 1,
        "payload": {"action": "create", "model": "tests.post", "data": _FLAT_POST},
    }


def _make_user(username: str) -> Any:
    """Create a real user row.

    Args:
        username: The username to create.

    Returns:
        user: The created user.
    """
    return get_user_model().objects.create_user(username=username, password="pw")


def _session_cookie(user: Any) -> str:
    """Log a user in through Django's own machinery and return the session key.

    Args:
        user: The user to open a real database-backed session for.

    Returns:
        cookie: The value a browser would send back as the session cookie.
    """
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _request(
    query: str, *, session_cookie: str | None = None, bare: bool = False
) -> Any:
    """Build an SSE request carried through the real session/auth middleware.

    The point of this helper is what it does NOT do: it never assigns
    "request.user" itself, so "AuthenticationMiddleware" installs the same
    unresolved "SimpleLazyObject" a real deployment gets.

    Args:
        query: The GraphQL subscription document to POST.
        session_cookie: The session key to present, or "None" for a caller with
            no session cookie at all (an anonymous browser).
        bare: When true no middleware runs at all, so the request carries
            neither "session" nor "user" — an endpoint mounted outside the
            session/auth chain.

    Returns:
        request: The request, middleware-processed unless "bare".
    """
    request = AsyncRequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    if bare:
        return request
    if session_cookie is not None:
        request.COOKIES[settings.SESSION_COOKIE_NAME] = session_cookie
    SessionMiddleware(lambda r: None).process_request(request)
    AuthenticationMiddleware(lambda r: None).process_request(request)
    return request


async def _drain(response: Any, *, max_frames: int = 4) -> str:
    """Pull SSE frames until the terminal one and return them joined.

    Args:
        response: The streaming response to read frames from.
        max_frames: The maximum number of frames to pull before giving up.

    Returns:
        text: Every decoded frame concatenated.
    """
    frames: list[str] = []
    aiter = sse_frames(response).__aiter__()
    for _ in range(max_frames):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
        except (StopAsyncIteration, TimeoutError):
            break
        frames.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if "event: complete" in frames[-1]:
            break
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()
    return "".join(frames)


async def _await_group(layer: InMemoryChannelLayer, *, timeout: float = 2.0) -> str:
    """Poll the channel layer until a subscribe has joined a group; return it.

    Args:
        layer: The in-memory channel layer the subscribe joins a group on.
        timeout: The maximum time in seconds to poll before failing.

    Returns:
        group: The name of the joined group.

    Raises:
        AssertionError: When no group is joined within "timeout".
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        joined = [name for name, chans in layer.groups.items() if chans]
        if joined:
            return joined[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"no group was joined within {timeout}s")


def _no_group_joined(layer: InMemoryChannelLayer) -> bool:
    """Report whether the channel layer holds no live group membership.

    Args:
        layer: The in-memory channel layer to inspect.

    Returns:
        empty: True when no group has any channel in it.
    """
    return all(not chans for chans in layer.groups.values())


@pytest.fixture
def layer(monkeypatch: pytest.MonkeyPatch) -> InMemoryChannelLayer:
    """Give the test an isolated in-memory channel layer both transports see.

    Args:
        monkeypatch: The pytest fixture used to stub the layer lookup.

    Returns:
        layer: The layer every "get_channel_layer" call resolves to.
    """
    live = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: live)
    return live


# ---------------------------------------------------------------------------
# SSE — the request user is a SimpleLazyObject the async view must resolve
# ---------------------------------------------------------------------------


async def test_sse_authenticated_caller_streams(layer: InMemoryChannelLayer) -> None:
    """An authenticated SSE caller must get a live stream, not an async-context error.

    Contract: this test ships broken if the SSE transport leaves
    "request.user" lazy for a hook to resolve inside the async view — the
    session/user lookup then runs in an async context and every authenticated
    subscription dies with "SynchronousOnlyOperation".

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from asgiref.sync import sync_to_async

    from django_graphex.subscriptions.transports import sse

    user = await sync_to_async(_make_user)("sse-live")
    cookie = await sync_to_async(_session_cookie)(user)

    view = sse.subscription_sse_view(schema=build_auth_gated_schema())
    response = await view(_request(_SUB_QUERY, session_cookie=cookie))
    assert response.status_code == 200

    started = sse.get_started_source(response)
    assert started is not None, "the granted subscribe must start a source"

    await layer.group_send(started.joined_groups[0], _notify(started.joined_groups[0]))
    frames = await _drain(response, max_frames=1)
    assert "You cannot call this from an async context" not in frames
    payload = json.loads(frames.split("data: ", 1)[1])
    assert payload["data"]["post"]["title"] == "hello"

    await started.aclose()


async def test_sse_anonymous_caller_is_denied(layer: InMemoryChannelLayer) -> None:
    """An anonymous SSE caller must be denied by the gate, joining no group.

    Contract: this test ships broken if an anonymous caller reaches a
    "group_add" or is refused with anything other than the gate's own denial.

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=build_auth_gated_schema())
    response = await view(_request(_SUB_QUERY))
    assert response.status_code == 200
    assert sse.get_started_source(response) is None

    frames = await _drain(response)
    assert "authentication required" in frames
    assert "event: complete" in frames
    assert _no_group_joined(layer)


async def test_sse_session_of_a_deleted_user_is_denied(
    layer: InMemoryChannelLayer,
) -> None:
    """A session pointing at a deleted user must be denied, not crash the stream.

    Contract: this test ships broken if the session lookup for a vanished user
    row escapes as an async-context error instead of resolving to the
    anonymous user the gate then refuses.

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from asgiref.sync import sync_to_async

    from django_graphex.subscriptions.transports import sse

    user = await sync_to_async(_make_user)("sse-ghost")
    cookie = await sync_to_async(_session_cookie)(user)
    await sync_to_async(user.delete)()

    view = sse.subscription_sse_view(schema=build_auth_gated_schema())
    response = await view(_request(_SUB_QUERY, session_cookie=cookie))

    frames = await _drain(response)
    assert "You cannot call this from an async context" not in frames
    assert "authentication required" in frames
    assert _no_group_joined(layer)


async def test_sse_request_without_any_session_is_denied(
    layer: InMemoryChannelLayer,
) -> None:
    """A request that never met the session/auth chain must be denied cleanly.

    Contract: this test ships broken if a request carrying neither "session"
    nor "user" raises instead of resolving to no user at all.

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=build_auth_gated_schema())
    response = await view(_request(_SUB_QUERY, bare=True))

    frames = await _drain(response)
    assert "authentication required" in frames
    assert _no_group_joined(layer)


async def test_sse_schema_provider_receives_a_resolved_user(
    layer: InMemoryChannelLayer,
) -> None:
    """The per-connection schema provider must be handed a RESOLVED user.

    Contract: this test ships broken if the provider is handed the lazy
    object — a provider that prunes by permission touches the user, and that
    lookup would then run in the async view's own context, escaping the view
    as a 500 (there is no in-stream framing around it).

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from asgiref.sync import sync_to_async

    from django_graphex.subscriptions.transports import sse

    user = await sync_to_async(_make_user)("sse-provider")
    cookie = await sync_to_async(_session_cookie)(user)

    seen: list[Any] = []

    def _provider(candidate: Any) -> Any:
        """Prune by permission, the way a real provider does.

        Args:
            candidate: The user the transport resolved for this connection.

        Returns:
            schema: The auth-gated schema, unpruned.
        """
        seen.append(candidate.is_authenticated)
        return build_auth_gated_schema()

    view = sse.subscription_sse_view(schema_provider=_provider)
    response = await view(_request(_SUB_QUERY, session_cookie=cookie))
    assert response.status_code == 200
    assert seen == [True]

    started = sse.get_started_source(response)
    assert started is not None
    await started.aclose()


# ---------------------------------------------------------------------------
# WS — the same matrix, so the two transports are pinned to one contract
# ---------------------------------------------------------------------------


def _communicator(
    app: Any, *, session_cookie: str | None = None, layer: Any = None
) -> WebsocketCommunicator:
    """Open a graphql-transport-ws communicator through the real auth stack.

    Args:
        app: The consumer ASGI application to wrap in "AuthMiddlewareStack".
        session_cookie: The session key to present as a cookie header, or
            "None" for a caller with no session cookie at all.
        layer: The channel layer to attach to the scope.

    Returns:
        communicator: The configured communicator, not yet connected.
    """
    headers = []
    if session_cookie is not None:
        cookie = f"{settings.SESSION_COOKIE_NAME}={session_cookie}"
        headers.append((b"cookie", cookie.encode()))
    asgi_app = app.as_asgi() if hasattr(app, "as_asgi") else app
    communicator = WebsocketCommunicator(
        AuthMiddlewareStack(asgi_app),
        "/graphql/",
        subprotocols=["graphql-transport-ws"],
        headers=headers,
    )
    if layer is not None:
        communicator.scope["channel_layer"] = layer
    return communicator


async def _ack_and_subscribe(communicator: WebsocketCommunicator) -> None:
    """Complete the handshake and send one subscribe for operation "op1".

    Args:
        communicator: The communicator to drive.
    """
    connected, _subprotocol = await communicator.connect()
    assert connected, "the WS handshake (accept) must succeed"
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=2)
    assert ack["type"] == "connection_ack"
    await communicator.send_json_to(
        {"id": "op1", "type": "subscribe", "payload": {"query": _SUB_QUERY}}
    )


async def test_ws_authenticated_caller_streams(layer: InMemoryChannelLayer) -> None:
    """An authenticated WS caller must get a live stream through the real auth stack.

    Contract: this test ships broken if a socket authenticated by Channels'
    own "AuthMiddlewareStack" fails the subscribe gate.

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from asgiref.sync import sync_to_async

    from django_graphex.subscriptions.transports import ws

    user = await sync_to_async(_make_user)("ws-live")
    cookie = await sync_to_async(_session_cookie)(user)

    app = ws.subscription_ws_consumer(schema=build_auth_gated_schema())
    communicator = _communicator(app, session_cookie=cookie, layer=layer)
    await _ack_and_subscribe(communicator)

    group = await _await_group(layer)
    await layer.group_send(group, _notify(group))

    msg = await communicator.receive_json_from(timeout=2)
    assert msg["type"] == "next", msg
    assert msg["payload"]["data"]["post"]["title"] == "hello"

    await communicator.disconnect()


async def test_ws_anonymous_caller_is_denied(layer: InMemoryChannelLayer) -> None:
    """An anonymous WS caller must be denied by the gate, joining no group.

    Contract: this test ships broken if a socket with no session cookie
    reaches a "group_add" instead of the gate's denial frame.

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from django_graphex.subscriptions.transports import ws

    app = ws.subscription_ws_consumer(schema=build_auth_gated_schema())
    communicator = _communicator(app, layer=layer)
    await _ack_and_subscribe(communicator)

    msg = await communicator.receive_json_from(timeout=2)
    assert msg["type"] == "error", msg
    assert "authentication required" in json.dumps(msg["payload"])
    assert _no_group_joined(layer)

    await communicator.disconnect()


async def test_ws_session_of_a_deleted_user_is_denied(
    layer: InMemoryChannelLayer,
) -> None:
    """A WS session pointing at a deleted user must be denied, not crash the socket.

    Contract: this test ships broken if a session whose user row is gone
    produces anything other than the gate's denial.

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from asgiref.sync import sync_to_async

    from django_graphex.subscriptions.transports import ws

    user = await sync_to_async(_make_user)("ws-ghost")
    cookie = await sync_to_async(_session_cookie)(user)
    await sync_to_async(user.delete)()

    app = ws.subscription_ws_consumer(schema=build_auth_gated_schema())
    communicator = _communicator(app, session_cookie=cookie, layer=layer)
    await _ack_and_subscribe(communicator)

    msg = await communicator.receive_json_from(timeout=2)
    assert msg["type"] == "error", msg
    assert "authentication required" in json.dumps(msg["payload"])
    assert _no_group_joined(layer)

    await communicator.disconnect()


async def test_ws_scope_without_a_user_is_denied(layer: InMemoryChannelLayer) -> None:
    """A socket opened outside the auth stack must be denied cleanly.

    Contract: this test ships broken if a scope carrying neither "user" nor
    "session" raises instead of resolving to no user at all.

    Args:
        layer: The isolated in-memory channel layer fixture.
    """
    from django_graphex.subscriptions.transports import ws

    app = ws.subscription_ws_consumer(schema=build_auth_gated_schema())
    communicator = WebsocketCommunicator(
        app.as_asgi() if hasattr(app, "as_asgi") else app,
        "/graphql/",
        subprotocols=["graphql-transport-ws"],
    )
    communicator.scope["channel_layer"] = layer
    await _ack_and_subscribe(communicator)

    msg = await communicator.receive_json_from(timeout=2)
    assert msg["type"] == "error", msg
    assert "authentication required" in json.dumps(msg["payload"])
    assert _no_group_joined(layer)

    await communicator.disconnect()
