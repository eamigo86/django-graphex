"""End-to-end round-trip tests for the playground's subscription transports.

These are the real thing: they drive the SAME WebSocket consumer
("config.asgi" / "blog.consumers.AppWSConsumer") and the SAME SSE view
("config/urls.py" / "subscription_sse_view") the playground serves, against
the live "blog.schema". A subscriber opens a subscription, the test triggers
the corresponding change through the ORM (a genuine "Post" save fires Django's
"post_save" signal, which the subscription engine broadcasts), and the test
asserts the change is delivered as a "next" frame.

Why a real ORM save (not a hand-rolled "group_send"): it exercises the full
producer path — "post_save" -> "SubscriptionBinding.broadcast" ->
serialize-once -> "group_send" — exactly as "postCreate" does in the live
playground. The binding is wired the moment "blog.schema" is imported (its
"PostSubscription.Field()" mount calls "get_binding()"), so importing the
schema is all the setup the producer side needs.

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from blog.models import Author

pytest.importorskip("channels")

from channels.db import database_sync_to_async  # noqa: E402

from tests._documented_operations import GUIDE, README, operation_under_heading

# A Channels consumer touches the DB connection registry on every dispatched
# message, and the producer-side broadcast fires from a real transaction commit,
# so these need DB access with a real (committable) transaction.
pytestmark = pytest.mark.django_db(transaction=True)


_POST_SUB_QUERY = (
    "subscription { postSubscription(action: ALL_ACTIONS) { id title status created } }"
)


async def _sse_frames(response):
    """Iterate an SSE response's frames as text, dropping comment chunks.

    The stream opens with a bare : comment line so the ASGI server flushes
    the status line and headers before the first event. A comment is not a
    frame, so tests that read frames skip it.

    Args:
        response: The streaming response returned by the SSE view.

    Yields:
        text: Each decoded body chunk that carries an SSE event, in order.
    """
    async for chunk in response.streaming_content:
        text = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else chunk
        if not text.startswith(":"):
            yield text


@pytest.fixture(autouse=True)
def _fresh_channel_layer():
    """Reset the in-memory channel layer between tests (no group leakage).

    The playground configures a single InMemoryChannelLayer (a process-wide
    singleton returned by channels.layers.get_channel_layer()). BOTH the
    subscribe side (the consumer / SSE source) and the produce side
    (SubscriptionBinding.broadcast via post_save) resolve their layer
    through that same call, so they already share one layer — no patching needed.
    We just clear its groups/queues before each test so a prior test's
    subscriber cannot receive this test's broadcast and vice-versa.
    """
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    # InMemoryChannelLayer keeps per-group channel sets + per-channel queues. A
    # test that stops reading leaves frames queued on its channel, so flush both
    # before AND after the test: nothing may outlive the test that caused it.
    layer.groups.clear()
    layer.channels.clear()
    yield layer
    layer.groups.clear()
    layer.channels.clear()


async def _await_started_group(ws_module, communicator, op_id, *, timeout=3.0):
    """Poll until operation *op_id*'s source has joined a Channels group.

    The WS module records each connected consumer keyed by scope identity; this
    polls the live consumer's per-operation registry until the source is started
    and has joined at least one group (so a subsequent broadcast cannot race the
    subscribe).
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        consumer = ws_module.get_live_consumer(communicator.scope)
        if consumer is not None:
            source = consumer.started_source(op_id)
            if source is not None and source.joined_groups:
                return source.joined_groups[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"operation {op_id!r} never joined a group within {timeout}s")


# --------------------------------------------------------------------------- #
# WebSocket transport (graphql-transport-ws)                                   #
# --------------------------------------------------------------------------- #


async def test_ws_subscription_delivers_post_create(author: Author) -> None:
    """Exercise the WS round-trip: subscribe, create a Post, receive a "next".

    Drives the playground's own "AppWSConsumer" (the consumer mounted in
    "config/asgi.py") over the graphql-transport-ws subprotocol, waits for the
    subscribe to join its Channels group, then triggers a real ORM create.

    Args:
        author: The persisted "Author" fixture that owns the created post.
    """
    from blog.consumers import AppWSConsumer
    from blog.models import Post
    from channels.testing import WebsocketCommunicator

    communicator = WebsocketCommunicator(
        AppWSConsumer.as_asgi(),
        "/ws/graphql/",
        subprotocols=["graphql-transport-ws"],
    )

    connected, subprotocol = await communicator.connect()
    assert connected, "the WS handshake must succeed"
    assert subprotocol == "graphql-transport-ws"

    # connection_init → connection_ack.
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=3)
    assert ack["type"] == "connection_ack"

    # Subscribe to postSubscription.
    await communicator.send_json_to(
        {"id": "p1", "type": "subscribe", "payload": {"query": _POST_SUB_QUERY}}
    )

    # Wait for the subscribe task to actually join its Channels group before
    # producing, so the broadcast cannot race ahead of the subscriber.
    from django_graphex.subscriptions.transports import ws as ws_module

    await _await_started_group(ws_module, communicator, "p1", timeout=3.0)

    from channels.db import database_sync_to_async

    @database_sync_to_async
    def _create_post():
        # A real ORM create → post_save → on_commit → broadcast. Outside an
        # atomic() block (transaction=True), on_commit runs immediately.
        return Post.objects.create(
            title="Live update",
            author=author,
            status=Post.Status.PUBLISHED,
        )

    post = await _create_post()

    msg = await communicator.receive_json_from(timeout=3.0)
    assert msg["type"] == "next"
    assert msg["id"] == "p1"
    data = msg["payload"]["data"]["postSubscription"]
    assert data["title"] == "Live update"
    assert data["status"] == "PUBLISHED"
    assert datetime.fromisoformat(data["created"]) == post.created
    assert msg["payload"].get("errors") in (None, [])

    await communicator.disconnect()


@pytest.mark.parametrize(
    ("path", "heading"),
    [(README, "## Subscriptions"), (GUIDE, "## Try subscriptions live")],
    ids=["readme", "guide"],
)
async def test_documented_anonymous_subscription_receives_its_mutation(
    author: Author, path: Path, heading: str
) -> None:
    """Run the documented subscribe and HTTP mutation as anonymous clients.

    Args:
        author: The persisted author whose identifier replaces the sample id.
        path: The published Markdown file with the literal operations.
        heading: The existing section containing both operations.
    """
    from blog.consumers import AppWSConsumer
    from channels.testing import WebsocketCommunicator
    from django.test import Client
    from graphql import parse, print_ast
    from graphql.language.ast import IntValueNode

    from django_graphex.subscriptions.transports import ws as ws_module

    subscription = operation_under_heading(path, heading)
    mutation = operation_under_heading(path, heading, 1)
    assert "postSubscription" in subscription
    assert "postCreate" in mutation
    document = parse(mutation)
    post_create = document.definitions[0].selection_set.selections[0]
    payload = post_create.arguments[0].value
    fields = tuple(
        replace(field, value=IntValueNode(value=str(author.pk)))
        if field.name.value == "author"
        else field
        for field in payload.fields
    )
    mutation = print_ast(
        replace(
            document,
            definitions=(
                replace(
                    document.definitions[0],
                    selection_set=replace(
                        document.definitions[0].selection_set,
                        selections=(
                            replace(
                                post_create,
                                arguments=(
                                    replace(
                                        post_create.arguments[0],
                                        value=replace(payload, fields=fields),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    communicator = WebsocketCommunicator(
        AppWSConsumer.as_asgi(), "/ws/graphql/", subprotocols=["graphql-transport-ws"]
    )
    connected, protocol = await communicator.connect()
    assert connected and protocol == "graphql-transport-ws"
    try:
        await communicator.send_json_to({"type": "connection_init"})
        assert (await communicator.receive_json_from(timeout=3))["type"] == (
            "connection_ack"
        )
        await communicator.send_json_to(
            {
                "id": "documented",
                "type": "subscribe",
                "payload": {"query": subscription},
            }
        )
        await _await_started_group(ws_module, communicator, "documented")

        @database_sync_to_async
        def _post_documented_mutation() -> tuple[int, dict[str, object]]:
            """Submit the copied operation with a fresh anonymous HTTP client.

            Returns:
                The HTTP status and decoded GraphQL response body.
            """
            response = Client().post(
                "/graphql/",
                data=json.dumps({"query": mutation}),
                content_type="application/json",
            )
            return response.status_code, response.json()

        status, body = await _post_documented_mutation()
        assert status == 200, body
        assert body.get("errors") in (None, []), body
        assert body["data"]["postCreate"]["ok"] is True, body
        assert not await communicator.receive_nothing(timeout=0.35)
        frame = await communicator.receive_json_from(timeout=3)
        assert frame["type"] == "next", frame
        assert frame["id"] == "documented"
        assert (
            frame["payload"]["data"]["postSubscription"]["id"]
            == body["data"]["postCreate"]["post"]["id"]
        )
        assert frame["payload"].get("errors") in (None, [])
    finally:
        await communicator.disconnect()


async def test_ws_refuses_a_subscribe_past_the_shipped_cap(author: Author) -> None:
    """Assert "MAX_SUBSCRIPTIONS_PER_CONNECTION" bounds one socket's operations.

    The setting ships ON at 50 and this playground never names it, so a reader
    copying "config/settings.py" inherits the cap without reading a line about
    it. The cap is lowered to 1 here so the boundary is reachable in a test;
    what is pinned is the behaviour at the boundary, which does not depend on
    where it sits.

    The refusal is scoped to the OFFENDING operation: the socket stays open and
    the subscription already running on it keeps delivering, which is the half
    a reader has to trust before raising the cap in production.

    Args:
        author: The persisted "Author" fixture that owns the created post.
    """
    from blog.consumers import AppWSConsumer
    from blog.models import Post
    from channels.testing import WebsocketCommunicator
    from django.conf import settings
    from django.test import override_settings

    from django_graphex.subscriptions.transports import ws as ws_module

    namespace = dict(settings.DJANGO_GRAPHEX)
    namespace["MAX_SUBSCRIPTIONS_PER_CONNECTION"] = 1

    with override_settings(DJANGO_GRAPHEX=namespace):
        communicator = WebsocketCommunicator(
            AppWSConsumer.as_asgi(),
            "/ws/graphql/",
            subprotocols=["graphql-transport-ws"],
        )
        connected, _ = await communicator.connect()
        assert connected
        await communicator.send_json_to({"type": "connection_init"})
        assert (await communicator.receive_json_from(timeout=3))[
            "type"
        ] == "connection_ack"

        await communicator.send_json_to(
            {"id": "p1", "type": "subscribe", "payload": {"query": _POST_SUB_QUERY}}
        )
        await _await_started_group(ws_module, communicator, "p1", timeout=3.0)

        # The second operation is one past the cap of 1.
        await communicator.send_json_to(
            {"id": "p2", "type": "subscribe", "payload": {"query": _POST_SUB_QUERY}}
        )
        refusal = await communicator.receive_json_from(timeout=3.0)

        assert refusal["type"] == "error"
        assert refusal["id"] == "p2"
        assert "MAX_SUBSCRIPTIONS_PER_CONNECTION" in json.dumps(refusal["payload"])

        # The socket and the surviving operation are untouched by the refusal.
        from channels.db import database_sync_to_async

        @database_sync_to_async
        def _create_post():
            return Post.objects.create(
                title="Survives the cap",
                author=author,
                status=Post.Status.PUBLISHED,
            )

        await _create_post()

        delivered = await communicator.receive_json_from(timeout=3.0)
        assert delivered["type"] == "next"
        assert delivered["id"] == "p1"
        assert delivered["payload"]["data"]["postSubscription"]["title"] == (
            "Survives the cap"
        )

        await communicator.disconnect()


async def test_ws_handshake_then_ping_pong() -> None:
    """Smoke-test that the consumer completes the handshake and answers ping.

    Connects over graphql-transport-ws, performs the connection_init /
    connection_ack exchange, then asserts a "ping" frame is answered with a
    "pong".
    """
    from blog.consumers import AppWSConsumer
    from channels.testing import WebsocketCommunicator

    communicator = WebsocketCommunicator(
        AppWSConsumer.as_asgi(),
        "/ws/graphql/",
        subprotocols=["graphql-transport-ws"],
    )

    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "connection_init"})
    ack = await communicator.receive_json_from(timeout=3)
    assert ack["type"] == "connection_ack"

    await communicator.send_json_to({"type": "ping"})
    pong = await communicator.receive_json_from(timeout=3)
    assert pong["type"] == "pong"

    await communicator.disconnect()


# --------------------------------------------------------------------------- #
# SSE transport (graphql-sse / text/event-stream)                             #
# --------------------------------------------------------------------------- #


async def test_sse_subscription_delivers_post_create(author: Author) -> None:
    """Exercise the SSE round-trip: open the stream, create a Post, receive "next".

    Drives the playground's own SSE view, built exactly as "config/urls.py"
    builds it: "subscription_sse_view(schema=schema.graphql_schema)", then
    asserts the first streamed frame is the "event: next" carrying the post.

    Args:
        author: The persisted "Author" fixture that owns the created post.
    """
    from blog.models import Post
    from blog.schema import schema
    from django.test import RequestFactory

    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=schema.graphql_schema)

    factory = RequestFactory()
    request = factory.post(
        "/graphql/stream",
        data=json.dumps({"query": _POST_SUB_QUERY}),
        content_type="application/json",
    )
    # Public subscription: an anonymous user is allowed.
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()

    response = await view(request)
    assert response.status_code == 200
    assert response["content-type"].startswith("text/event-stream")

    # The subscribe joined a group; create a Post → broadcast → next frame.
    started = sse.get_started_source(response)
    assert started is not None, "the SSE subscribe must start a live source"
    assert started.joined_groups, "the SSE subscribe must join a Channels group"

    from channels.db import database_sync_to_async

    @database_sync_to_async
    def _create_post():
        return Post.objects.create(
            title="SSE live update",
            author=author,
            status=Post.Status.PUBLISHED,
        )

    post = await _create_post()

    aiter = _sse_frames(response).__aiter__()
    first = await asyncio.wait_for(aiter.__anext__(), timeout=3.0)
    assert first.startswith("event: next\n"), f"unexpected first frame: {first!r}"

    payload_line = [ln for ln in first.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(payload_line[len("data: ") :])
    data = payload["data"]["postSubscription"]
    assert data["title"] == "SSE live update"
    assert data["status"] == "PUBLISHED"
    assert datetime.fromisoformat(data["created"]) == post.created
    assert payload.get("errors") in (None, [])

    # Teardown: close the source so the generator's finally runs group_discard.
    await started.aclose()
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()


# --------------------------------------------------------------------------- #
# Public subscription scope: drafts follow PostType.get_queryset               #
# --------------------------------------------------------------------------- #


@database_sync_to_async
def _create_posts(author: Author, *statuses: str) -> list[str]:
    """Create one post per status, in order, and return their titles.

    Args:
        author: The persisted "Author" that owns the posts.
        *statuses: The "Post.Status" values to create, one post each.

    Returns:
        titles: The titles of the created posts, in creation order.
    """
    from blog.models import Post

    titles = []
    for status in statuses:
        title = f"scope-{status}"
        Post.objects.create(title=title, author=author, status=status)
        titles.append(title)
    return titles


async def _ws_first_post_title(author: Author, user: object | None) -> str:
    """Subscribe over WS, create a draft then a published post, return the first title.

    Args:
        author: The persisted "Author" that owns the posts.
        user: The authenticated user placed on the connection scope, or None
            for an anonymous socket.

    Returns:
        title: The title of the first "next" frame the subscriber received.
    """
    from blog.consumers import AppWSConsumer
    from blog.models import Post
    from channels.testing import WebsocketCommunicator

    from django_graphex.subscriptions.transports import ws as ws_module

    communicator = WebsocketCommunicator(
        AppWSConsumer.as_asgi(), "/ws/graphql/", subprotocols=["graphql-transport-ws"]
    )
    if user is not None:
        communicator.scope["user"] = user
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "connection_init"})
    assert (await communicator.receive_json_from(timeout=3))["type"] == "connection_ack"
    await communicator.send_json_to(
        {"id": "s1", "type": "subscribe", "payload": {"query": _POST_SUB_QUERY}}
    )
    await _await_started_group(ws_module, communicator, "s1", timeout=3.0)

    await _create_posts(author, Post.Status.DRAFT, Post.Status.PUBLISHED)
    frame = await communicator.receive_json_from(timeout=3.0)
    assert frame["type"] == "next", frame
    await communicator.disconnect()
    return frame["payload"]["data"]["postSubscription"]["title"]


async def _sse_first_post_title(author: Author, user: object) -> str:
    """Subscribe over SSE, create a draft then a published post, return the first title.

    Args:
        author: The persisted "Author" that owns the posts.
        user: The user placed on the request ("AnonymousUser" or a real one).

    Returns:
        title: The title of the first "event: next" frame the subscriber received.
    """
    from blog.models import Post
    from blog.schema import schema
    from django.test import RequestFactory

    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=schema.graphql_schema)
    request = RequestFactory().post(
        "/graphql/stream",
        data=json.dumps({"query": _POST_SUB_QUERY}),
        content_type="application/json",
    )
    request.user = user
    response = await view(request)
    started = sse.get_started_source(response)
    assert started is not None and started.joined_groups

    await _create_posts(author, Post.Status.DRAFT, Post.Status.PUBLISHED)
    aiter = _sse_frames(response).__aiter__()
    first = await asyncio.wait_for(aiter.__anext__(), timeout=3.0)
    payload_line = [ln for ln in first.splitlines() if ln.startswith("data: ")][0]
    title = json.loads(payload_line[len("data: ") :])["data"]["postSubscription"][
        "title"
    ]
    await started.aclose()
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()
    return title


async def test_ws_anonymous_subscriber_never_receives_a_draft(author: Author) -> None:
    """Assert an anonymous WS subscriber skips the draft and gets the published post.

    "PostType.get_queryset" hides drafts from anonymous queries; the public
    "postSubscription" must follow the same rule through "subscription_scope".

    Args:
        author: The persisted "Author" that owns the posts.
    """
    assert await _ws_first_post_title(author, None) == "scope-published"


async def test_ws_authenticated_subscriber_receives_the_draft(
    author: Author, demo_user: object
) -> None:
    """Assert a logged-in WS subscriber still sees every post, drafts included.

    Args:
        author: The persisted "Author" that owns the posts.
        demo_user: The persisted user placed on the connection scope.
    """
    assert await _ws_first_post_title(author, demo_user) == "scope-draft"


async def test_sse_anonymous_subscriber_never_receives_a_draft(author: Author) -> None:
    """Assert an anonymous SSE subscriber skips the draft and gets the published post.

    Args:
        author: The persisted "Author" that owns the posts.
    """
    from django.contrib.auth.models import AnonymousUser

    assert await _sse_first_post_title(author, AnonymousUser()) == "scope-published"


async def test_sse_authenticated_subscriber_receives_the_draft(
    author: Author, demo_user: object
) -> None:
    """Assert a logged-in SSE subscriber still sees every post, drafts included.

    Args:
        author: The persisted "Author" that owns the posts.
        demo_user: The persisted user placed on the request.
    """
    assert await _sse_first_post_title(author, demo_user) == "scope-draft"


# --------------------------------------------------------------------------- #
# Private subscription: the auth gate the README promises                      #
# --------------------------------------------------------------------------- #

_NOTE_SUB_QUERY = "subscription { noteSubscription(action: ALL_ACTIONS) { id title } }"


def _anonymous_info() -> SimpleNamespace:
    """Build the minimal resolve-info stand-in carrying an anonymous user.

    Returns:
        info: An object exposing "context.user" as an "AnonymousUser", which is
            all the subscribe hooks read.
    """
    from django.contrib.auth.models import AnonymousUser

    return SimpleNamespace(context=SimpleNamespace(user=AnonymousUser()))


@pytest.mark.django_db
def test_note_subscription_type_denies_anonymous_subscribe() -> None:
    """Assert "NoteModelType" itself denies an anonymous subscribe.

    The README documents "noteSubscription" as gated by
    "authorize_subscription". Without a gate on the TYPE, the only thing
    standing between an anonymous client and every user's notes is the
    schema-root wiring: "subscribe" counts as a read action for
    "IsAuthenticatedOrReadOnly", so copying this type into a project that
    does not mount "AuthenticatedFieldsMiddleware" leaks every note.
    """
    from blog.schema import NoteModelType
    from graphql import GraphQLError

    subscription_cls = NoteModelType.subscription_type()
    with pytest.raises(GraphQLError):
        subscription_cls.authorize_subscription(_anonymous_info(), action="all_actions")


@pytest.mark.django_db
def test_note_subscription_scope_denies_anonymous() -> None:
    """Assert the note "subscription_scope" fails closed for an anonymous user.

    Returning "None" here means NO server-forced filter, so an anonymous
    subscriber that reached this hook would receive every user's notes. The
    sibling "filter_queryset" already fails closed with "qs.none()".
    """
    from blog.schema import NoteModelType
    from graphql import GraphQLError

    subscription_cls = NoteModelType.subscription_type()
    with pytest.raises(GraphQLError):
        subscription_cls.subscription_scope(_anonymous_info(), action="all_actions")


@pytest.mark.django_db
def test_note_subscription_scope_forces_owner_for_authenticated(
    demo_user: object,
) -> None:
    """Assert an authenticated subscriber still gets the server-forced owner scope.

    Guards against the anonymous denial being bought by breaking the feature.

    Args:
        demo_user: The persisted user whose notes the scope must pin to.
    """
    from blog.schema import NoteModelType

    info = SimpleNamespace(context=SimpleNamespace(user=demo_user))
    subscription_cls = NoteModelType.subscription_type()
    assert subscription_cls.subscription_scope(info, action="all_actions") == {
        "owner": demo_user.pk
    }
    # And the subscribe itself is allowed.
    subscription_cls.authorize_subscription(info, action="all_actions")


async def test_anonymous_note_subscription_joins_no_group(demo_user: object) -> None:
    """Assert an anonymous SSE subscriber is denied before joining any group.

    End-to-end lock on the README claim: the denial reaches the client as an
    UNAUTHENTICATED error and no live source is ever started, so no notes group
    is joined.

    Args:
        demo_user: The persisted user whose private notes must never leak.
    """
    from blog.schema import schema
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory

    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=schema.graphql_schema)
    request = RequestFactory().post(
        "/graphql/stream",
        data=json.dumps({"query": _NOTE_SUB_QUERY}),
        content_type="application/json",
    )
    request.user = AnonymousUser()

    response = await view(request)
    assert sse.get_started_source(response) is None, (
        "an anonymous subscriber must never start a live notes source"
    )

    frame = await asyncio.wait_for(
        _sse_frames(response).__aiter__().__anext__(), timeout=3.0
    )
    assert "UNAUTHENTICATED" in frame, frame


@pytest.mark.asyncio
async def test_the_websocket_route_validates_the_handshake_origin() -> None:
    """Assert the routed WebSocket app refuses a foreign Origin.

    A WebSocket handshake is a plain HTTP request that carries cookies and is
    NOT subject to CORS, so a page on any other site can open one and inherit
    the visitor's session. That routes straight around REQUIRE_CSRF_HEADER,
    which this release turns on precisely to stop cross-site writes over HTTP.
    Channels ships "AllowedHostsOriginValidator" for it, and "config/asgi.py"
    wraps the router in one.

    The shipped host list is intentionally explicit, so this test exercises the
    application exactly as a reader runs it — no settings override can hide an
    unsafe wildcard default.
    """
    from channels.testing import WebsocketCommunicator
    from config.asgi import build_websocket_application
    from django.conf import settings

    # pytest-django may append a second "testserver" while setting up the DB.
    assert "*" not in settings.ALLOWED_HOSTS
    assert set(settings.ALLOWED_HOSTS) == {"127.0.0.1", "localhost", "testserver"}
    app = build_websocket_application()

    foreign = WebsocketCommunicator(app, "/ws/graphql/")
    foreign.scope["subprotocols"] = ["graphql-transport-ws"]
    foreign.scope["headers"] = [(b"origin", b"https://evil.example")]
    connected, _ = await foreign.connect()
    assert not connected, "a foreign Origin must not complete the handshake"
    await foreign.disconnect()

    for host in ("localhost", "testserver"):
        same = WebsocketCommunicator(app, "/ws/graphql/")
        same.scope["subprotocols"] = ["graphql-transport-ws"]
        same.scope["headers"] = [(b"origin", f"http://{host}".encode())]
        connected, _ = await same.connect()
        assert connected, f"the shipped host {host!r} must still connect"
        await same.disconnect()
