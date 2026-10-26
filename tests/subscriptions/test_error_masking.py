"""SSE and WebSocket mask unexpected internal errors like the HTTP view."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from django.db import DatabaseError  # noqa: E402
from django.test import override_settings  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from tests.subscriptions._sse import sse_frames  # noqa: E402
from tests.subscriptions.test_wu13_sse_branch_coverage import (  # noqa: E402
    _json_request,
)
from tests.subscriptions.test_wu13_ws_branch_coverage import (  # noqa: E402
    _connect_and_ack,
    _make_communicator,
)

pytestmark = pytest.mark.django_db(transaction=True)

_SECRETS = ("hunter2", "vault", "db-host", "SELECT")


def _subscribe_raising(error: BaseException) -> Any:
    """Build a subscribe resolver that raises before any stream exists.

    Args:
        error: The exception to raise.

    Returns:
        The async subscribe resolver.
    """

    async def subscribe(_root: Any, _info: Any) -> Any:
        raise error

    return subscribe


def _resolve_raising(error: BaseException) -> Any:
    """Build an event resolver that raises.

    Args:
        error: The exception to raise.

    Returns:
        The resolver.
    """

    def resolve(_value: Any, _info: Any) -> Any:
        raise error

    return resolve


async def _one_event(_root: Any, _info: Any) -> Any:
    """Yield a single event.

    Args:
        _root: Unused root value.
        _info: Unused resolve info.

    Yields:
        One payload.
    """
    yield "x"


def _stream_raising(error: BaseException, after_event: bool = False) -> Any:
    """Build an async-generator subscribe that raises while it is iterated.

    Args:
        error: The exception to raise.
        after_event: Whether to yield one event before raising.

    Returns:
        The subscribe resolver (an async generator function).
    """

    async def subscribe(_root: Any, _info: Any) -> Any:
        if after_event:
            yield "x"
        raise error

    return subscribe


def _schema() -> GraphQLSchema:
    """Build a schema whose subscriptions fail in different ways.

    Returns:
        The schema.
    """
    string = GraphQLString
    fields = {
        "subRuntime": GraphQLField(
            string,
            subscribe=_subscribe_raising(RuntimeError("password=hunter2 at db-host")),
        ),
        "subDatabase": GraphQLField(
            string, subscribe=_subscribe_raising(DatabaseError("SELECT secret"))
        ),
        "subPublic": GraphQLField(
            string, subscribe=_subscribe_raising(GraphQLError("deliberate refusal"))
        ),
        "genRuntime": GraphQLField(
            string,
            subscribe=_stream_raising(RuntimeError("password=hunter2 at db-host")),
            resolve=lambda value, _info: value,
        ),
        "genAfterEvent": GraphQLField(
            string,
            subscribe=_stream_raising(
                RuntimeError("password=hunter2 at db-host"), True
            ),
            resolve=lambda value, _info: value,
        ),
        "genDatabase": GraphQLField(
            string,
            subscribe=_stream_raising(DatabaseError("SELECT secret FROM vault")),
            resolve=lambda value, _info: value,
        ),
        "genPublic": GraphQLField(
            string,
            subscribe=_stream_raising(GraphQLError("deliberate stream refusal")),
            resolve=lambda value, _info: value,
        ),
        "evRuntime": GraphQLField(
            string,
            subscribe=_one_event,
            resolve=_resolve_raising(RuntimeError("SELECT secret FROM vault")),
        ),
        "evDatabase": GraphQLField(
            string,
            subscribe=_one_event,
            resolve=_resolve_raising(DatabaseError("SELECT secret FROM vault")),
        ),
        "evPublic": GraphQLField(
            string,
            subscribe=_one_event,
            resolve=_resolve_raising(GraphQLError("deliberate event refusal")),
        ),
    }
    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"a": GraphQLField(string)}),
        subscription=GraphQLObjectType("Subscription", fields),
    )


async def _sse_errors(
    monkeypatch: pytest.MonkeyPatch, query: str, schema: Any = None
) -> list[dict[str, Any]]:
    """Run a subscription over SSE and return the first frame's errors.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        query: The subscription document.
        schema: The schema to serve; the failing-resolver schema by default.

    Returns:
        The errors of the first "next" frame.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    response = await sse.subscription_sse_view(schema=schema or _schema())(
        _json_request(query)
    )
    assert response.status_code == 200
    async for frame in sse_frames(response):
        event, data = frame.decode().strip().split("\n", 1)
        assert event == "event: next"
        return json.loads(data.removeprefix("data: "))["errors"]  # type: ignore[no-any-return]
    raise AssertionError("no frame")


async def _ws_errors(
    monkeypatch: pytest.MonkeyPatch, query: str, schema: Any = None
) -> list[dict[str, Any]]:
    """Run a subscription over WebSocket and return the first frame's errors.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        query: The subscription document.
        schema: The schema to serve; the failing-resolver schema by default.

    Returns:
        The errors of the first "next" or "error" frame.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    communicator = _make_communicator(
        ws.subscription_ws_consumer(schema=schema or _schema()), layer=layer
    )
    await _connect_and_ack(communicator)
    await communicator.send_json_to(
        {"id": "op", "type": "subscribe", "payload": {"query": query}}
    )
    frame = await communicator.receive_json_from(timeout=5)
    await communicator.disconnect()
    if frame["type"] == "error":
        return frame["payload"]  # type: ignore[no-any-return]
    assert frame["type"] == "next"
    return frame["payload"]["errors"]  # type: ignore[no-any-return]


def _run(transport: str) -> Any:
    """Pick the runner of a transport.

    Args:
        transport: "sse" or "ws".

    Returns:
        The coroutine function running a query on that transport.
    """
    return _sse_errors if transport == "sse" else _ws_errors


def _internal_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return the ERROR records of the internal-errors logger.

    Args:
        caplog: The log capture fixture.

    Returns:
        The matching records.
    """
    return [
        r
        for r in caplog.records
        if r.name == "django_graphex.internal_errors" and r.levelno >= logging.ERROR
    ]


_TRANSPORTS = pytest.mark.parametrize("transport", ("sse", "ws"))


@_TRANSPORTS
@pytest.mark.parametrize(
    ("query", "code", "message", "located"),
    (
        (
            "subscription { subRuntime }",
            "INTERNAL_SERVER_ERROR",
            "An internal error occurred.",
            True,
        ),
        (
            "subscription { evRuntime }",
            "INTERNAL_SERVER_ERROR",
            "An internal error occurred.",
            True,
        ),
        (
            "subscription { subDatabase }",
            "DATA_ACCESS_ERROR",
            "Unable to complete the data operation.",
            True,
        ),
        (
            "subscription { evDatabase }",
            "DATA_ACCESS_ERROR",
            "Unable to complete the data operation.",
            True,
        ),
    ),
)
@override_settings(DEBUG=False)
async def test_unexpected_errors_are_masked_and_logged_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    query: str,
    code: str,
    message: str,
    located: bool,
) -> None:
    """An unexpected exception is masked, keeps its path and logs one ERROR.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
        query: The failing subscription.
        code: The expected extensions code.
        message: The expected masked message.
        located: Whether the error carries a path.
    """
    caplog.set_level(logging.DEBUG)

    (error,) = await _run(transport)(monkeypatch, query)

    assert error["message"] == message
    assert error["extensions"]["code"] == code
    error_id = error["extensions"]["errorId"]
    assert re.fullmatch(r"[0-9a-f]{32}", error_id)
    assert ("path" in error) is located
    assert not any(secret in json.dumps(error) for secret in _SECRETS)
    (record,) = _internal_records(caplog)
    assert error_id in record.getMessage()
    assert record.exc_info is not None
    assert "HTTP" not in record.getMessage()


@_TRANSPORTS
@pytest.mark.parametrize(
    ("query", "message"),
    (
        ("subscription { subPublic }", "deliberate refusal"),
        ("subscription { evPublic }", "deliberate event refusal"),
    ),
)
@override_settings(DEBUG=False)
async def test_deliberate_graphql_errors_stay_public(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    query: str,
    message: str,
) -> None:
    """A GraphQLError a resolver raises on purpose keeps its message.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
        query: The failing subscription.
        message: The expected public message.
    """
    caplog.set_level(logging.DEBUG)

    (error,) = await _run(transport)(monkeypatch, query)

    assert error["message"] == message
    assert "errorId" not in json.dumps(error)
    assert not _internal_records(caplog)


@_TRANSPORTS
@pytest.mark.parametrize(
    ("query", "raw"),
    (
        ("subscription { subRuntime }", "password=hunter2 at db-host"),
        ("subscription { evRuntime }", "SELECT secret FROM vault"),
        ("subscription { evDatabase }", "SELECT secret FROM vault"),
    ),
)
@override_settings(DEBUG=True)
async def test_debug_keeps_the_raw_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    query: str,
    raw: str,
) -> None:
    """With DEBUG on the raw exception text is sent and nothing is logged.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
        query: The failing subscription.
        raw: The raw exception text.
    """
    caplog.set_level(logging.DEBUG)

    (error,) = await _run(transport)(monkeypatch, query)

    assert error["message"] == raw
    assert not _internal_records(caplog)


@_TRANSPORTS
@override_settings(DEBUG=False)
async def test_validation_errors_stay_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
) -> None:
    """A validation error keeps its message and is not logged as internal.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
    """
    caplog.set_level(logging.DEBUG)

    (error,) = await _run(transport)(monkeypatch, "subscription { nope }")

    assert error["message"].startswith("Cannot query field 'nope'")
    assert "extensions" not in error
    assert not _internal_records(caplog)


@override_settings(DEBUG=False)
async def test_ws_undecodable_frame_closes_without_an_error_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Any client can send garbage, so it closes 4400 without an ERROR record.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
    """
    from django_graphex.subscriptions.transports import ws

    caplog.set_level(logging.DEBUG)
    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    communicator = _make_communicator(
        ws.subscription_ws_consumer(schema=_schema()), layer=layer
    )
    await _connect_and_ack(communicator)
    await communicator.send_to(text_data="{not json")
    closed = await communicator.receive_output(timeout=5)

    assert closed["type"] == "websocket.close"
    assert closed["code"] == 4400
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@_TRANSPORTS
@pytest.mark.parametrize(
    ("filter_input", "message"),
    (
        ("{tags: {iexact: 1}}", "is not a valid database lookup on"),
        ('{title: {startswith: "a"}}', "not to include unknown field"),
        ('{title: {icontains: "a"}}', "not to include unknown field"),
        ("{id: {gt: 1}}", "not to include unknown field"),
    ),
)
@override_settings(DEBUG=False)
async def test_rejected_client_filters_stay_public_and_unlogged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    filter_input: str,
    message: str,
) -> None:
    """A subscriber filter the server refuses is client input, not a fault.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
        filter_input: The GraphQL filter literal.
        message: A fragment of the public refusal.
    """
    from tests.subscriptions.test_audit_defects import _build_native_schema

    caplog.set_level(logging.DEBUG)
    query = "subscription { post(action: CREATE, filter: %s) { id } }" % filter_input

    (error,) = await _run(transport)(monkeypatch, query, _build_native_schema())

    assert message in error["message"]
    assert "extensions" not in error
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def _sse_all_errors(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> list[dict[str, Any]]:
    """Run a subscription over SSE and collect the errors of every frame.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        query: The subscription document.

    Returns:
        The errors of all "next" frames, in order; "complete" must end the stream.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    response = await sse.subscription_sse_view(schema=_schema())(_json_request(query))
    frames = [frame async for frame in sse_frames(response)]
    assert frames[-1] == b"event: complete\ndata: \n\n"
    errors: list[dict[str, Any]] = []
    for frame in frames[:-1]:
        event, data = frame.decode().strip().split("\n", 1)
        assert event == "event: next"
        errors += json.loads(data.removeprefix("data: ")).get("errors", [])
    return errors


async def _ws_all_errors(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> list[dict[str, Any]]:
    """Run a subscription over WebSocket and collect the errors of every frame.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        query: The subscription document.

    Returns:
        The errors of all "next" frames, in order, up to the "complete" frame.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    communicator = _make_communicator(
        ws.subscription_ws_consumer(schema=_schema()), layer=layer
    )
    await _connect_and_ack(communicator)
    await communicator.send_json_to(
        {"id": "op", "type": "subscribe", "payload": {"query": query}}
    )
    errors: list[dict[str, Any]] = []
    while True:
        frame = await communicator.receive_json_from(timeout=5)
        if frame["type"] == "complete":
            break
        assert frame["type"] == "next"
        errors += frame["payload"].get("errors", [])
    await communicator.disconnect()
    return errors


@_TRANSPORTS
@pytest.mark.parametrize(
    ("query", "code"),
    (
        ("subscription { genRuntime }", "INTERNAL_SERVER_ERROR"),
        ("subscription { genAfterEvent }", "INTERNAL_SERVER_ERROR"),
        ("subscription { genDatabase }", "DATA_ACCESS_ERROR"),
    ),
)
@override_settings(DEBUG=False)
async def test_errors_raised_while_iterating_the_source_are_masked(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    query: str,
    code: str,
) -> None:
    """A source that fails mid-iteration is masked with exactly one ERROR log.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
        query: The failing subscription.
        code: The expected extensions code.
    """
    caplog.set_level(logging.DEBUG)
    run = _sse_all_errors if transport == "sse" else _ws_all_errors

    (error,) = await run(monkeypatch, query)

    assert error["extensions"]["code"] == code
    error_id = error["extensions"]["errorId"]
    assert not any(secret in json.dumps(error) for secret in _SECRETS)
    (record,) = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert record.name == "django_graphex.internal_errors"
    assert error_id in record.getMessage()
    assert record.exc_info is not None


@_TRANSPORTS
@override_settings(DEBUG=False)
async def test_deliberate_error_while_iterating_the_source_stays_public(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
) -> None:
    """A GraphQLError the source raises on purpose keeps its message.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        caplog: The log capture fixture.
        transport: The transport under test.
    """
    caplog.set_level(logging.DEBUG)
    run = _sse_all_errors if transport == "sse" else _ws_all_errors

    (error,) = await run(monkeypatch, "subscription { genPublic }")

    assert error["message"] == "deliberate stream refusal"
    assert "extensions" not in error
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@_TRANSPORTS
@override_settings(DEBUG=True)
async def test_debug_keeps_the_raw_message_of_a_source_failure(
    monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    """With DEBUG on, a mid-iteration failure keeps its raw text.

    Args:
        monkeypatch: Replaces the channel layer with an in-memory one.
        transport: The transport under test.
    """
    run = _sse_all_errors if transport == "sse" else _ws_all_errors

    (error,) = await run(monkeypatch, "subscription { genRuntime }")

    assert error["message"] == "password=hunter2 at db-host"
