"""Public native subscription DateTime event-snapshot regressions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.db import models
from django.db.models.signals import post_save
from django.test import RequestFactory
from graphql import GraphQLBoolean

pytest.importorskip("channels")

from django_graphex.core import ObjectType, field  # noqa: E402
from django_graphex.schema import DjangoGraphQLSchema  # noqa: E402
from django_graphex.subscriptions import Subscription  # noqa: E402
from django_graphex.subscriptions.transports import sse  # noqa: E402
from tests.subscriptions._sse import sse_frames  # noqa: E402


class TemporalEvent(models.Model):
    """Represent an event without requiring a database table.

    Instances can be serialized through the native subscription binding.
    """

    occurred = models.DateTimeField(null=True)
    label = models.CharField(max_length=32)

    class Meta:
        """Keep event snapshots independent of migrations.

        The model participates in generated GraphQL types without storage.
        """

        app_label = "tests"
        managed = False


class TemporalSubscription(Subscription):
    """Expose the standard generated full-payload subscription.

    Its DateTime field exercises the native event output and filter paths.
    """

    class Meta:
        """Configure the subscription under test.

        Full payloads carry the captured DateTime over a JSON-safe channel.
        """

        model = TemporalEvent
        stream = "r02b_datetime_snapshot"
        payload_mode = "full"


class Query(ObjectType):
    """Provide the required query root.

    The regression exercises subscription operations, not query execution.
    """

    ok = field(GraphQLBoolean)


class SubscriptionRoot(ObjectType):
    """Expose the generated native event and filter fields.

    The public field compiles the actual DateTime input and output types.
    """

    temporal = TemporalSubscription.Field()


SCHEMA = DjangoGraphQLSchema(query=Query, subscription=SubscriptionRoot).graphql_schema
BINDING = TemporalSubscription.get_binding()


class User:
    """Represent an authenticated SSE subscriber.

    The SSE transport requires an authenticated request user.
    """

    is_authenticated = True
    pk = 1


def _request(query: str, variables: dict[str, Any] | None = None) -> Any:
    """Build a native SSE request.

    Args:
        query: The subscription operation.
        variables: Optional GraphQL input values.

    Returns:
        An authenticated request.
    """
    request = RequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps({"query": query, "variables": variables or {}}),
        content_type="application/json",
    )
    request.user = User()
    return request


async def _next_payload(response: Any) -> dict[str, Any]:
    """Read one actual SSE GraphQL result.

    Args:
        response: The active streaming response.

    Returns:
        The decoded GraphQL result frame.
    """
    frame = await asyncio.wait_for(sse_frames(response).__anext__(), timeout=1.5)
    decoded = frame.decode() if isinstance(frame, bytes) else frame
    line = next(line for line in decoded.splitlines() if line.startswith("data: "))
    return json.loads(line[len("data: ") :])


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("2026-10-18T12:00:00Z", "2026-10-18T12:00:00Z"),
        ("2026-10-18T12:00:00.123000Z", "2026-10-18T12:00:00.123Z"),
        ("2026-10-18T12:00:00.123456Z", "2026-10-18T12:00:00.123456Z"),
        ("2026-10-18T12:00:00.123456Z", "2026-10-18T17:30:00.123456+05:30"),
    ],
)
async def test_equal_datetime_event_delivers_captured_instant(
    event: str, expected: str
) -> None:
    """Exact typed instants must deliver, including equivalent offsets.

    Args:
        event: Captured event DateTime.
        expected: GraphQL DateTime filter value.
    """
    query = (
        "subscription($when: DateTime) { temporal(action: CREATE, "
        "filter: {occurred: {exact: $when}}) { id occurred label } }"
    )
    response = await sse.subscription_sse_view(schema=SCHEMA)(
        _request(query, {"when": expected})
    )
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    assert source.filters["occurred"] == datetime.fromisoformat(
        event.replace("Z", "+00:00")
    )
    instance = TemporalEvent(
        id=11,
        occurred=datetime.fromisoformat(event.replace("Z", "+00:00")),
        label="kept",
    )
    try:
        BINDING.broadcast("create", instance)
        result = await _next_payload(response)
    finally:
        await source.aclose()
    assert result.get("errors") in (None, [])
    assert result["data"]["temporal"]["occurred"] == instance.occurred.isoformat()
    assert result["data"]["temporal"]["label"] == "kept"


async def test_unfiltered_full_snapshot_preserves_microseconds_and_output() -> None:
    """JSON-safe full snapshots must retain six digits and serialize DateTime.

    This independently reaches the wire-precision assertion without filtering.
    """
    response = await sse.subscription_sse_view(schema=SCHEMA)(
        _request("subscription { temporal(action: CREATE) { id occurred label } }")
    )
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    instant = datetime.fromisoformat("2026-10-18T12:00:00.123456+00:00")
    instance = TemporalEvent(id=12, occurred=instant, label="kept")
    snapshot = TemporalSubscription._serialize_payload(instance)
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert (
        datetime.fromisoformat(snapshot["occurred"].replace("Z", "+00:00")) == instant
    )
    assert snapshot["occurred"].endswith("123456+00:00")
    try:
        BINDING.broadcast("create", instance)
        result = await _next_payload(response)
    finally:
        await source.aclose()
    assert result.get("errors") in (None, [])
    assert result["data"]["temporal"]["occurred"] == instant.isoformat()


async def test_datetime_output_accepts_native_wire_snapshot() -> None:
    """The event output boundary must reconstruct its captured DateTime.

    This independently reaches the GraphQL scalar with a zero-fraction value.
    """
    response = await sse.subscription_sse_view(schema=SCHEMA)(
        _request("subscription { temporal(action: CREATE) { id occurred label } }")
    )
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    instance = TemporalEvent(
        id=14,
        occurred=datetime.fromisoformat("2026-10-18T12:00:00+00:00"),
        label="kept",
    )
    try:
        BINDING.broadcast("create", instance)
        result = await _next_payload(response)
    finally:
        await source.aclose()
    assert result.get("errors") in (None, [])
    assert result["data"]["temporal"]["occurred"] == instance.occurred.isoformat()


async def test_different_microseconds_do_not_deliver() -> None:
    """A precise DateTime filter must not admit a nearby event.

    One microsecond distinguishes the filter from the captured event.
    """
    query = (
        "subscription($when: DateTime) { temporal(action: CREATE, "
        "filter: {occurred: {exact: $when}}) { id occurred } }"
    )
    response = await sse.subscription_sse_view(schema=SCHEMA)(
        _request(query, {"when": "2026-10-18T12:00:00.123457Z"})
    )
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    instance = TemporalEvent(
        id=15,
        occurred=datetime.fromisoformat("2026-10-18T12:00:00.123456+00:00"),
        label="kept",
    )
    try:
        BINDING.broadcast("create", instance)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(sse_frames(response).__anext__(), timeout=0.2)
    finally:
        await source.aclose()


@pytest.mark.parametrize(
    ("query", "instant", "label"),
    [
        (
            "subscription { temporal(action: CREATE, filter: "
            "{occurred: {exact: null}}) { id occurred label } }",
            None,
            "kept",
        ),
        (
            "subscription { temporal(action: CREATE, filter: "
            '{label: {exact: "kept"}}) { id occurred label } }',
            None,
            "kept",
        ),
    ],
)
async def test_null_and_ordinary_string_filters_stay_unchanged(
    query: str, instant: datetime | None, label: str
) -> None:
    """The DateTime correction must not change null or string matching.

    Args:
        query: Public subscription operation.
        instant: Event DateTime or null.
        label: Event string value.
    """
    response = await sse.subscription_sse_view(schema=SCHEMA)(_request(query))
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    try:
        BINDING.broadcast("create", TemporalEvent(id=16, occurred=instant, label=label))
        result = await _next_payload(response)
    finally:
        await source.aclose()
    assert result.get("errors") in (None, [])
    assert result["data"]["temporal"] == {
        "id": "16",
        "occurred": None,
        "label": "kept",
    }


@pytest.mark.django_db(transaction=True)
async def test_automatic_signal_keeps_original_datetime_after_object_changes() -> None:
    """An automatic event must reflect its signal-time value, not later state.

    The in-memory instance is mutated only after the signal captured its data.
    """
    response = await sse.subscription_sse_view(schema=SCHEMA)(
        _request("subscription { temporal(action: CREATE) { id occurred label } }")
    )
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    instant = datetime.fromisoformat("2026-10-18T12:00:00.987654+00:00")
    instance = TemporalEvent(id=13, occurred=instant, label="before")
    try:
        await sync_to_async(post_save.send, thread_sensitive=True)(
            sender=TemporalEvent,
            instance=instance,
            created=True,
            raw=False,
            using="default",
            update_fields=None,
        )
        instance.occurred = datetime.fromisoformat("2026-10-18T12:00:01+00:00")
        instance.label = "after"
        result = await _next_payload(response)
    finally:
        await source.aclose()
    assert result.get("errors") in (None, [])
    assert result["data"]["temporal"]["occurred"] == instant.isoformat()
    assert result["data"]["temporal"]["label"] == "before"


async def test_invalid_datetime_wire_values_do_not_pass_a_typed_filter() -> None:
    """A malformed or non-string wire value must not match a typed instant.

    Only the valid event should reach the public SSE result.
    """
    query = (
        "subscription($when: DateTime) { temporal(action: CREATE, "
        "filter: {occurred: {exact: $when}}) { id occurred } }"
    )
    instant = "2026-10-18T12:00:00.123456Z"
    response = await sse.subscription_sse_view(schema=SCHEMA)(
        _request(query, {"when": instant})
    )
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    layer = get_channel_layer()
    assert layer is not None
    group = source.joined_groups[0]
    try:
        for value in (123, "not-a-datetime", instant):
            await layer.group_send(
                group,
                {
                    "type": "subscription.notify",
                    "stream": BINDING.stream,
                    "group": group,
                    "pk": 17,
                    "payload": {
                        "action": "create",
                        "model": BINDING.model_label,
                        "data": {"id": 17, "occurred": value, "label": "kept"},
                    },
                },
            )
        result = await _next_payload(response)
    finally:
        await source.aclose()
    assert result.get("errors") in (None, [])
    assert (
        result["data"]["temporal"]["occurred"]
        == datetime.fromisoformat(instant.replace("Z", "+00:00")).isoformat()
    )


async def test_invalid_native_datetime_output_keeps_scalar_rejection() -> None:
    """Malformed native wire values must retain the existing scalar error.

    The native resolver must not make the output scalar more permissive.
    """
    response = await sse.subscription_sse_view(schema=SCHEMA)(
        _request("subscription { temporal(action: CREATE) { id occurred } }")
    )
    source = sse.get_started_source(response)
    assert response.status_code == 200 and source is not None
    layer = get_channel_layer()
    assert layer is not None
    group = source.joined_groups[0]
    try:
        await layer.group_send(
            group,
            {
                "type": "subscription.notify",
                "stream": BINDING.stream,
                "group": group,
                "pk": 18,
                "payload": {
                    "action": "create",
                    "model": BINDING.model_label,
                    "data": {"id": 18, "occurred": "not-a-datetime", "label": "kept"},
                },
            },
        )
        result = await _next_payload(response)
    finally:
        await source.aclose()
    assert result["data"]["temporal"]["occurred"] is None
    assert result["errors"]
