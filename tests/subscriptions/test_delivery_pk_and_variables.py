# -*- coding: utf-8 -*-
"""Delivery regressions: non-"id" primary keys and parameterised subscriptions.

Two defects that make a subscription unusable in its DEFAULT configuration:

  * the "id_only" broadcast payload (the default payload mode) was hardcoded to
    the key "id", so every event for a model whose primary key is not named
    "id" delivered a null on a non-nullable event field;
  * the per-event delivery "execute" received neither "variable_values" nor
    "operation_name", so every parameterised subscription (the normal shape a
    graphql-ws / Apollo / urql client sends) got an error frame on EVERY event
    even though subscribing succeeded.

Both are driven through the REAL public surface: a compiled
"DjangoGraphQLSchema" served by the real SSE view and the real WS consumer, fed
by the real "post_save"/"post_delete" bindings.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from graphql import GraphQLSchema

pytest.importorskip("channels")

from channels.testing import WebsocketCommunicator  # noqa: E402

from tests.models import SubSlugPkItem, SubVariablesNote  # noqa: E402
from tests.subscriptions._sse import sse_frames  # noqa: E402

pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# Schemas — module scope: a DjangoModelType is identity-stable, so registering
# it per test would pollute the shared output registry.
# ---------------------------------------------------------------------------


def _build_slug_schema() -> GraphQLSchema:
    """Assemble a native schema subscribing to the slug-pk model (id-only).

    "payload_mode" is left at its default ("id_only"), which is the shipped
    default configuration and the one the defect breaks.

    Returns:
        The assembled schema exposing an "item" subscription field.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    class SlugItemType(DjangoModelType):
        class Meta:
            model = SubSlugPkItem
            stream = "sub_slug_pk_items"

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        item = SlugItemType.SubscriptionField()

    compile_all_outputs()
    return DjangoGraphQLSchema(
        query=Query, subscription=SubscriptionRoot
    ).graphql_schema


def _build_note_schema() -> GraphQLSchema:
    """Assemble a native schema subscribing to the variables-test model.

    Returns:
        The assembled schema exposing a "note" subscription field.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    class NoteType(DjangoModelType):
        class Meta:
            model = SubVariablesNote
            stream = "sub_variables_notes"
            payload_mode = "full"

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        note = NoteType.SubscriptionField()

    compile_all_outputs()
    return DjangoGraphQLSchema(
        query=Query, subscription=SubscriptionRoot
    ).graphql_schema


_SLUG_SCHEMA = _build_slug_schema()
_NOTE_SCHEMA = _build_note_schema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _User:
    """A minimal authenticated user stand-in for the transport auth boundary."""

    is_authenticated = True
    pk = 1


def _make_request(
    query: str,
    *,
    variables: dict[str, Any] | None = None,
    operation_name: str | None = None,
) -> Any:
    """Build an HTTP request carrying a GraphQL subscription body.

    Args:
        query: The GraphQL subscription document to send as the request body.
        variables: Optional GraphQL variables to include in the body.
        operation_name: Optional operation name to include in the body.

    Returns:
        The constructed Django test request with an authenticated user.
    """
    from django.test import RequestFactory

    body: dict[str, Any] = {"query": query}
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


async def _first_payload(response: Any, *, timeout: float = 3.0) -> dict[str, Any]:
    """Pull the first SSE "next" frame off "response" and decode its JSON.

    Args:
        response: The streaming HTTP response returned by the SSE view.
        timeout: The maximum time in seconds to wait for the frame.

    Returns:
        The decoded GraphQL result carried by the first frame.
    """
    aiter = sse_frames(response).__aiter__()
    chunk = await asyncio.wait_for(aiter.__anext__(), timeout=timeout)
    text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
    assert text.startswith("event: next\n"), text
    line = [ln for ln in text.splitlines() if ln.startswith("data: ")][0]
    return json.loads(line[len("data: ") :])


def _notify(group: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a producer-shaped "subscription.notify" envelope.

    Args:
        group: The channel-layer group name the message targets.
        data: The already-serialized flat payload to embed.

    Returns:
        The assembled notify message.
    """
    return {
        "type": "subscription.notify",
        "stream": "sub_variables_notes",
        "group": group,
        "pk": data.get("id"),
        "payload": {
            "action": "create",
            "model": "tests.subvariablesnote",
            "data": data,
        },
    }


# ---------------------------------------------------------------------------
# Non-"id" primary keys — the broadcast payload must be keyed by the real pk.
# ---------------------------------------------------------------------------


async def test_id_only_broadcast_delivers_non_id_primary_key() -> None:
    """A saved row with a slug primary key must deliver that slug, not a null.

    Contract: this test ships broken if the default "id_only" broadcast payload
    is keyed by the literal "id" instead of the model's real primary-key field
    name -- every event for such a model then renders as
    "{'item': None}" plus a "Cannot return null for non-nullable field" error.
    """
    from asgiref.sync import sync_to_async

    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=_SLUG_SCHEMA)
    response = await view(
        _make_request("subscription { item(action: CREATE) { slug } }")
    )
    assert response.status_code == 200

    started = sse.get_started_source(response)
    assert started is not None
    try:
        await sync_to_async(SubSlugPkItem.objects.create)(
            slug="widget-1", title="Widget"
        )
        payload = await _first_payload(response)
    finally:
        await started.aclose()

    assert payload.get("errors") in (None, [])
    assert payload["data"] == {"item": {"slug": "widget-1"}}


def test_id_only_delete_broadcast_is_keyed_by_the_real_primary_key(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """A delete notification must carry the real pk field name, not "id".

    Contract: this test ships broken if "_broadcast_delete" keys the id-only
    payload by the literal "id" -- the delete event then delivers a null on the
    non-nullable primary-key field exactly as the save path did.

    Args:
        captured_group_sends: The (group, message) pairs recorded for every
            "group_send" the binding performs.
    """
    item = SubSlugPkItem.objects.create(slug="widget-2", title="Doomed")
    captured_group_sends.clear()
    item.delete()

    deletes = [
        message
        for _group, message in captured_group_sends
        if message["payload"]["action"] == "delete"
    ]
    assert deletes, "the delete must broadcast at least one notification"
    for message in deletes:
        assert message["payload"]["data"] == {"slug": "widget-2"}


# ---------------------------------------------------------------------------
# Parameterised subscriptions — variables / operationName reach delivery.
# ---------------------------------------------------------------------------


async def test_sse_delivery_receives_the_request_variables() -> None:
    """A subscription using GraphQL variables must deliver events without errors.

    Contract: this test ships broken if the per-event delivery "execute" runs
    without "variable_values" -- every delivered event then carries
    "Variable '$a' of required type '...' was not provided.".
    """
    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=_NOTE_SCHEMA)
    query = (
        "subscription S($a: SubVariablesNoteSubscriptionAction!) "
        "{ note(action: $a) { id title } }"
    )
    response = await view(_make_request(query, variables={"a": "CREATE"}))
    assert response.status_code == 200

    started = sse.get_started_source(response)
    assert started is not None
    try:
        from channels.layers import get_channel_layer

        group = started.joined_groups[0]
        await get_channel_layer().group_send(
            group, _notify(group, {"id": 1, "title": "hello"})
        )
        payload = await _first_payload(response)
    finally:
        await started.aclose()

    assert payload.get("errors") in (None, [])
    assert payload["data"] == {"note": {"id": "1", "title": "hello"}}


async def test_sse_delivery_receives_the_request_operation_name() -> None:
    """A multi-operation document must deliver only the named operation.

    Contract: this test ships broken if the per-event delivery "execute" runs
    without "operation_name" -- graphql-core then answers every event with
    "Must provide operation name if query contains multiple operations.".
    """
    from django_graphex.subscriptions.transports import sse

    view = sse.subscription_sse_view(schema=_NOTE_SCHEMA)
    query = (
        "subscription A { note(action: CREATE) { id title } }\n"
        "subscription B { note(action: UPDATE) { id } }"
    )
    response = await view(_make_request(query, operation_name="A"))
    assert response.status_code == 200

    started = sse.get_started_source(response)
    assert started is not None
    try:
        from channels.layers import get_channel_layer

        group = started.joined_groups[0]
        await get_channel_layer().group_send(
            group, _notify(group, {"id": 2, "title": "named"})
        )
        payload = await _first_payload(response)
    finally:
        await started.aclose()

    assert payload.get("errors") in (None, [])
    assert payload["data"] == {"note": {"id": "2", "title": "named"}}


async def test_ws_delivery_receives_the_operation_variables() -> None:
    """The WS transport must forward a subscribe operation's variables to delivery.

    Contract: this test ships broken if the WS "next" frame for a parameterised
    subscription carries a "Variable ... was not provided" error instead of the
    projected event data. The SSE and WS transports build the delivery spec at
    two separate call sites, so both are pinned.
    """
    from channels.layers import get_channel_layer

    from django_graphex.subscriptions.transports import ws

    consumer = ws.subscription_ws_consumer(schema=_NOTE_SCHEMA)
    communicator = WebsocketCommunicator(
        consumer.as_asgi(), "/graphql/", subprotocols=["graphql-transport-ws"]
    )
    communicator.scope["user"] = _User()
    connected, _subprotocol = await communicator.connect()
    assert connected
    try:
        await communicator.send_json_to({"type": "connection_init"})
        assert (await communicator.receive_json_from(timeout=3))[
            "type"
        ] == "connection_ack"

        await communicator.send_json_to(
            {
                "id": "op-1",
                "type": "subscribe",
                "payload": {
                    "query": (
                        "subscription S($a: SubVariablesNoteSubscriptionAction!) "
                        "{ note(action: $a) { id title } }"
                    ),
                    "variables": {"a": "CREATE"},
                },
            }
        )

        group = ""
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            live = ws.get_live_consumer(communicator.scope)
            source = live.started_source("op-1") if live is not None else None
            if source is not None and source.joined_groups:
                group = source.joined_groups[0]
                break
            await asyncio.sleep(0.01)
        assert group, "the subscribe never joined a group"

        await get_channel_layer().group_send(
            group, _notify(group, {"id": 3, "title": "over-ws"})
        )
        frame = await communicator.receive_json_from(timeout=3)
    finally:
        await communicator.disconnect()

    assert frame["type"] == "next"
    assert frame["payload"].get("errors") in (None, [])
    assert frame["payload"]["data"] == {"note": {"id": "3", "title": "over-ws"}}
