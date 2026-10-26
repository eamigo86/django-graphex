"""Subscription transports answer over-deep documents like the HTTP view."""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402

from tests.subscriptions._transport_schema import build_native_schema  # noqa: E402
from tests.subscriptions.test_wu13_sse_branch_coverage import (  # noqa: E402
    _json_request,
)
from tests.subscriptions.test_wu13_ws_branch_coverage import (  # noqa: E402
    _app,
    _connect_and_ack,
    _make_communicator,
)

pytestmark = pytest.mark.django_db(transaction=True)

_DEEP = (
    "subscription { post(action: CREATE) { "
    + "... { " * 800
    + "id"
    + " }" * 800
    + " } }"
)


async def test_sse_deep_document_is_a_query_too_deep_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document that exhausts the parser's stack answers QUERY_TOO_DEEP.

    Before the fix the body was the plain-text "GraphQL syntax error: maximum
    recursion depth exceeded", with raw exception text and no error code.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=build_native_schema())

    response = await view(_json_request(_DEEP))

    assert response.status_code == 400
    assert b"recursion" not in response.content.lower()
    (error,) = json.loads(response.content)["errors"]
    assert error["extensions"]["code"] == "QUERY_TOO_DEEP"


async def test_sse_non_string_query_has_no_raw_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-string query answers a generic 400 instead of the lexer's TypeError.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    view = sse.subscription_sse_view(schema=build_native_schema())

    response = await view(_json_request(123))  # type: ignore[arg-type]

    assert response.status_code == 400
    assert b"Source" not in response.content
    assert b"TypeError" not in response.content


async def _subscribe_error(
    monkeypatch: pytest.MonkeyPatch, query: Any
) -> dict[str, Any]:
    """Send one subscribe message and return the error payload entry.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
        query: The query value to send.

    Returns:
        The first error in the "error" frame.
    """
    layer = InMemoryChannelLayer()
    communicator = _make_communicator(_app(layer, monkeypatch), layer=layer)
    await _connect_and_ack(communicator)
    await communicator.send_json_to(
        {"id": "op", "type": "subscribe", "payload": {"query": query}}
    )
    frame = await communicator.receive_json_from(timeout=5)
    await communicator.disconnect()
    assert frame["type"] == "error"
    return frame["payload"][0]


async def test_ws_deep_document_is_a_query_too_deep_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document that exhausts the parser's stack sends QUERY_TOO_DEEP.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    error = await _subscribe_error(monkeypatch, _DEEP)

    assert error["extensions"]["code"] == "QUERY_TOO_DEEP"
    assert "recursion" not in error["message"].lower()


async def test_ws_non_string_query_has_no_raw_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-string query sends a generic error instead of the lexer's TypeError.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    error = await _subscribe_error(monkeypatch, 123)

    assert "Source" not in error["message"]
    assert "TypeError" not in error["message"]
