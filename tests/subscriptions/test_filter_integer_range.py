"""A subscriber filter value outside the database integer range is refused."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import override_settings  # noqa: E402

from tests.models import Post  # noqa: E402
from tests.subscriptions._sse import sse_frames  # noqa: E402
from tests.subscriptions.test_audit_defects import (  # noqa: E402
    _build_native_schema,
)
from tests.subscriptions.test_wu13_sse_branch_coverage import (  # noqa: E402
    _json_request,
)
from tests.subscriptions.test_wu13_ws_branch_coverage import (  # noqa: E402
    _connect_and_ack,
    _make_communicator,
)

pytestmark = pytest.mark.django_db(transaction=True)

_BIG = "99999999999999999999"
_TRANSPORTS = pytest.mark.parametrize("transport", ("sse", "ws"))


async def _subscribe(
    monkeypatch: pytest.MonkeyPatch, transport: str, filter_input: str
) -> tuple[list[dict[str, Any]], InMemoryChannelLayer]:
    """Subscribe with a filter and report the refusal errors and the layer.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        transport: "sse" or "ws".
        filter_input: The GraphQL filter literal.

    Returns:
        The errors of the first frame (empty when the stream opened and stayed
        quiet) and the channel layer, whose groups show what was joined.
    """
    from django_graphex.subscriptions.transports import sse, ws

    query = "subscription { post(action: CREATE, filter: %s) { id } }" % filter_input
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    schema = _build_native_schema()
    if transport == "ws":
        communicator = _make_communicator(
            ws.subscription_ws_consumer(schema=schema), layer=layer
        )
        await _connect_and_ack(communicator)
        await communicator.send_json_to(
            {"id": "op", "type": "subscribe", "payload": {"query": query}}
        )
        if await communicator.receive_nothing(timeout=0.5):
            await communicator.disconnect()
            return [], layer
        frame = await communicator.receive_json_from(timeout=5)
        await communicator.disconnect()
        if frame["type"] == "error":
            return frame["payload"], layer
        return frame["payload"]["errors"], layer
    response = await sse.subscription_sse_view(schema=schema)(_json_request(query))
    source = sse.get_started_source(response)
    if source is not None:
        groups = list(source.joined_groups)
        await source.aclose()
        assert groups
        return [], layer
    async for frame in sse_frames(response):
        data = frame.decode().strip().split("\n", 1)[1]
        return json.loads(data.removeprefix("data: "))["errors"], layer
    raise AssertionError("no frame")  # pragma: no cover


@_TRANSPORTS
@pytest.mark.parametrize(
    ("filter_input", "fragment"),
    (
        (
            '{tags: {exact: "%s"}}' % _BIG,
            f"tags__exact value {_BIG} is out of range for Tag.id.",
        ),
        ('{category: {exact: "%s"}}' % _BIG, "category value"),
        ('{tags: {in: ["1", "%s"]}}' % _BIG, "tags__in value"),
        ('{id: {in: ["1", "%s"]}}' % _BIG, "id__in value"),
        ('{author: {exact: "-%s"}}' % _BIG, "out of range for Author.id."),
    ),
)
@override_settings(DEBUG=False)
async def test_out_of_range_value_is_refused_at_subscribe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    filter_input: str,
    fragment: str,
) -> None:
    """The value is refused publicly, unlogged, before any group is joined.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
        filter_input: The GraphQL filter literal.
        fragment: A fragment of the public refusal.
    """
    caplog.set_level(logging.DEBUG)

    (error,) = (await _subscribe(monkeypatch, transport, filter_input))[0]

    assert fragment in error["message"]
    assert "extensions" not in error
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@_TRANSPORTS
@pytest.mark.parametrize(
    "filter_input",
    ('{tags: {exact: "1"}}', '{category: {exact: "2"}}', '{id: {in: ["1", "2"]}}'),
)
@override_settings(DEBUG=False)
async def test_in_range_filters_still_subscribe(
    monkeypatch: pytest.MonkeyPatch, transport: str, filter_input: str
) -> None:
    """An in-range relation or id filter opens the stream and joins a group.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        transport: The transport under test.
        filter_input: The GraphQL filter literal.
    """
    errors, layer = await _subscribe(monkeypatch, transport, filter_input)

    assert errors == []


@_TRANSPORTS
@override_settings(DEBUG=False)
async def test_refused_filter_joins_no_group(
    monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    """A refused filter leaves the channel layer with no joined group.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        transport: The transport under test.
    """
    errors, layer = await _subscribe(
        monkeypatch, transport, '{tags: {exact: "%s"}}' % _BIG
    )

    assert errors
    assert not layer.groups


@_TRANSPORTS
@override_settings(DEBUG=False)
async def test_invalid_lookup_message_has_a_single_final_period(
    monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    """The ORM text already ends with a period, so it is not doubled.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        transport: The transport under test.
    """
    (error,) = (await _subscribe(monkeypatch, transport, '{author: {exact: "zz"}}'))[0]

    assert error["message"].endswith("but got 'zz'.")


def test_unbounded_and_non_integer_keys_are_not_range_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A text key, null, isnull and a missing bound never raise.

    Args:
        monkeypatch: Replaces the backend's integer range.
    """
    from django_graphex.subscriptions.streaming import _assert_integers_in_range

    _assert_integers_in_range(
        Post,
        {
            "title": _BIG,
            "title__exact": _BIG,
            "tags__isnull": True,
            "category": None,
            "tags__in": [None, 1],
            "category__nope": 1,
        },
    )
    monkeypatch.setattr(
        type(connection.ops), "integer_field_range", lambda self, t: (None, None)
    )
    _assert_integers_in_range(Post, {"tags": _BIG, "category": "-" + _BIG})
    monkeypatch.setattr(
        type(connection.ops), "integer_field_range", lambda self, t: (0, None)
    )
    _assert_integers_in_range(Post, {"tags": _BIG})
