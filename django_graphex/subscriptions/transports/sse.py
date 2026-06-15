r"""SSE transport adapter for the native serialize-once subscription engine.

The Server-Sent Events transport is the FIRST (cheap) engine validator (design
§7): an async Django view (Django>=5.2 → clean disconnect cancellation
GUARANTEED) returning a ``StreamingHttpResponse(content_type='text/event-stream')``.
ONE HTTP request → ONE subscription stream.

It is intentionally THIN — roughly six lines of wire framing over the shared
driver. The engine does the work:

  * AUTH lives in the HTTP request (``request.user`` / session) — the replacement
    for the deleted channel-ownership guard. A transport-neutral context exposing
    ``.user`` + a ``scope`` mapping is built from the ``HttpRequest`` and threaded
    into the engine (design §7), so the hooks never assume an ``HttpRequest``.
  * The request's GraphQL document (``query``/``variables``/``operationName``) is
    parsed; a parse error BEFORE the 200 response started is an HTTP 4xx. The
    document is then driven IN-STREAM (validation, subscribe, delivery), so any
    error after the 200 response started is surfaced as an in-stream
    ``next{errors}`` frame followed by ``complete`` — NEVER an HTTP 4xx (a 4xx is
    impossible once the streaming response has begun, and EventSource only sees
    in-stream frames).
  * The live native schema is the one the view was constructed with; the parsed
    request ``DocumentNode`` is supplied to WU5 ``drive_subscription`` at delivery
    (WU7 made the field's subscribe factory build the ``ChannelLayerSource``
    WITHOUT needing the schema/document — only the per-event ``execute`` does).
  * ``graphql-core`` ``create_source_event_stream`` runs the subscription field's
    native subscribe entry (→ ``ChannelLayerSource``); ``drive_subscription``
    (COND-A — NOT ``MapAsyncIterator``) wraps it with a per-event ``execute`` over
    the flat serialize-once dict.
  * Each ``ExecutionResult`` is framed ``event: next\\ndata: {json}\\n\\n``; on
    completion ``event: complete\\ndata: \\n\\n`` (the empty ``data:`` line is
    MANDATORY or an EventSource client never fires the ``complete`` event).
  * Client disconnect / aclosing → the streaming generator's ``finally`` runs
    ``source.aclose()`` → ``group_discard`` for every joined group (the WU4 sweep
    releases a blocked receive + discards every group), so no ghost subscriber
    survives a teardown. Django>=5.2 guarantees the disconnect cancellation that
    triggers ``GeneratorExit`` into the async generator.

This module reads ``graphex_or_graphene_settings.MAX_VALIDATION_ERRORS`` (NOT
``graphene_settings`` — the no-graphene-import gate). It imports neither graphene
nor channels at module scope; ``channels`` is imported lazily inside the view so
the base package never hard-requires the optional ``[subscriptions]`` extra.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from django.http import StreamingHttpResponse
from graphql import (
    ExecutionResult,
    OperationType,
    create_source_event_stream,
    parse,
    validate,
)
from graphql.utilities import get_operation_ast

from ...settings import graphex_or_graphene_settings
from ..streaming import SubscriptionSpec, drive_subscription

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncIterator, Callable

    from django.http import HttpRequest
    from graphql import DocumentNode, GraphQLSchema

    from ..source import ChannelLayerSource

__all__ = ["TransportContext", "subscription_sse_view"]


# A view → started-source map so callers/tests can observe the live source a
# response is streaming (and assert teardown). A WeakKeyDictionary keyed by the
# response object avoids leaking sources after the response is collected.
_STARTED_SOURCES: "WeakKeyDictionary[Any, ChannelLayerSource | None]" = (
    WeakKeyDictionary()
)


def get_started_source(response: Any) -> "ChannelLayerSource | None":
    """Return the started :class:`ChannelLayerSource` a response is streaming.

    ``None`` when the subscribe was denied/errored before a source was created
    (e.g. an authorize-deny short-circuited before any ``group_add``), or when the
    response is not an SSE subscription response.

    Args:
        response: The ``StreamingHttpResponse`` returned by the SSE view.

    Returns:
        The live source, or ``None``.
    """
    return _STARTED_SOURCES.get(response)


class TransportContext:
    """Transport-neutral context exposing ``.user`` + a ``scope`` mapping (§7).

    Built from the ``HttpRequest`` so the engine hooks (``authorize``/``scope``)
    work uniformly across SSE (``HttpRequest``) and WS (Channels ``scope``)
    WITHOUT assuming an ``HttpRequest``. Only ``.user`` and ``.scope`` are part of
    the contract the hooks rely on; the underlying request is carried for callers
    that need it.

    Attributes:
        user: The authenticated (or anonymous) user from ``request.user``.
        scope: A mapping carrying transport scope (here: ``{"user": user,
            "session": request.session}`` when available).
        request: The originating ``HttpRequest`` (transport-specific; not part of
            the neutral contract).
    """

    __slots__ = ("user", "scope", "request")

    def __init__(self, request: "HttpRequest") -> None:
        """Build the neutral context from an ``HttpRequest``."""
        self.request = request
        self.user = getattr(request, "user", None)
        self.scope: dict[str, Any] = {"user": self.user}
        session = getattr(request, "session", None)
        if session is not None:
            self.scope["session"] = session


def _read_request_body(request: "HttpRequest") -> dict[str, Any]:
    """Parse the GraphQL request body (JSON or form-encoded ``query``).

    Args:
        request: The incoming HTTP request.

    Returns:
        A mapping with ``query`` / ``variables`` / ``operationName`` keys.
    """
    content_type = (request.content_type or "").lower()
    if "application/json" in content_type:
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            body = {}
    else:
        body = request.POST
    return {
        "query": body.get("query"),
        "variables": body.get("variables"),
        "operationName": body.get("operationName"),
    }


def _frame_next(result: ExecutionResult) -> bytes:
    r"""Frame an ``ExecutionResult`` as an SSE ``next`` event.

    Args:
        result: The per-event execution result.

    Returns:
        The encoded ``event: next\\ndata: {json}\\n\\n`` frame.
    """
    payload: dict[str, Any] = {}
    if result.data is not None:
        payload["data"] = result.data
    if result.errors:
        payload["errors"] = [error.formatted for error in result.errors]
    body = json.dumps(payload)
    return f"event: next\ndata: {body}\n\n".encode("utf-8")


# The terminal SSE frame. The empty ``data:`` line is MANDATORY — an EventSource
# client never fires the ``complete`` event without a data line on the frame.
_COMPLETE_FRAME: bytes = b"event: complete\ndata: \n\n"


def _make_spec(schema: "GraphQLSchema", document: "DocumentNode") -> SubscriptionSpec:
    """Build the minimal driver spec carrying the live schema + parsed document.

    ``drive_subscription`` reads ONLY ``spec.schema`` and ``spec.document`` (the
    per-event ``execute`` inputs); every other spec field is the subscribe-time
    concern already handled by ``create_source_event_stream`` (which ran the
    field's own native subscribe entry). So the transport supplies a spec whose
    sole job is to carry the live schema + the per-request selection set into the
    delivery ``execute``.

    Args:
        schema: The live native ``GraphQLSchema``.
        document: The parsed subscription ``DocumentNode``.

    Returns:
        A :class:`SubscriptionSpec` carrying schema + document for delivery.
    """
    return SubscriptionSpec(
        model_label="",
        stream="",
        schema=schema,
        document=document,
    )


def subscription_sse_view(*, schema: "GraphQLSchema") -> "Callable[..., Any]":
    """Build the async SSE subscription view bound to *schema*.

    The returned view is an async Django view (Django>=5.2): it parses the GraphQL
    request, starts the subscription source (running the engine's authorize/scope
    hooks before any ``group_add``), and returns a
    ``StreamingHttpResponse(content_type='text/event-stream')`` whose generator
    drives serialize-once delivery and tears the source down on disconnect.

    Args:
        schema: The live native graphql-core ``GraphQLSchema`` the subscription
            executes against (the same schema is used for validation, the
            subscribe entry, and the per-event delivery ``execute``).

    Returns:
        An async view callable ``async (request) -> StreamingHttpResponse``.
    """

    async def _view(request: "HttpRequest", *args: Any, **kwargs: Any) -> Any:
        from django.http import HttpResponseBadRequest

        body = _read_request_body(request)
        query = body["query"]
        if not query:
            # PRE-200: no query at all is a plain client error (HTTP 4xx).
            return HttpResponseBadRequest("No GraphQL query provided.")

        try:
            document = parse(query)
        except Exception as exc:  # PRE-200: a syntax error is an HTTP 4xx.
            return HttpResponseBadRequest(f"GraphQL syntax error: {exc}")

        operation_ast = get_operation_ast(document, body["operationName"])
        if operation_ast is None or operation_ast.operation != OperationType.SUBSCRIPTION:
            # PRE-200: this transport only serves subscriptions.
            return HttpResponseBadRequest(
                "The SSE transport only serves subscription operations."
            )

        context = TransportContext(request)

        # Validate the document. A validation error here is delivered IN-STREAM
        # (the 200 text/event-stream response is committed below), NOT as an HTTP
        # 4xx — once the streaming response has started a 4xx is impossible and an
        # EventSource client only observes in-stream frames.
        validation_errors = validate(
            schema,
            document,
            max_errors=graphex_or_graphene_settings.MAX_VALIDATION_ERRORS,
        )

        started_source: "ChannelLayerSource | None" = None
        pre_stream_result: ExecutionResult | None = None

        if validation_errors:
            pre_stream_result = ExecutionResult(data=None, errors=validation_errors)
        else:
            # Run the subscription field's native subscribe entry. This runs the
            # KEPT hooks BEFORE any group_add (authorize-deny short-circuits before
            # the source), returning the started ChannelLayerSource — or an
            # ExecutionResult when the subscribe resolver reported an error (deny).
            source_or_result = await create_source_event_stream(
                schema,
                document,
                context_value=context,
                variable_values=body["variables"],
                operation_name=body["operationName"],
            )
            if isinstance(source_or_result, ExecutionResult):
                pre_stream_result = source_or_result
            else:
                started_source = source_or_result  # type: ignore[assignment]

        spec = _make_spec(schema, document)

        async def _event_stream() -> "AsyncIterator[bytes]":
            # A pre-stream result (validation error / subscribe deny) is delivered
            # in-stream as a single ``next`` frame then ``complete`` — NOT a 4xx.
            if started_source is None:
                if pre_stream_result is not None:
                    yield _frame_next(pre_stream_result)
                yield _COMPLETE_FRAME
                return

            delivery = drive_subscription(started_source, spec, context)
            try:
                async for result in delivery:
                    yield _frame_next(result)
                # The source completed (out-of-band close) → terminal frame.
                yield _COMPLETE_FRAME
            finally:
                # Client disconnect / aclosing / normal completion: tear the
                # source down so every joined group is discarded (no ghost
                # subscriber). aclose() is idempotent.
                await delivery.aclose()

        response = StreamingHttpResponse(
            _event_stream(), content_type="text/event-stream"
        )
        # SSE hygiene: disable proxy buffering and client/proxy caching so frames
        # are flushed promptly.
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        # Record the live source so callers/tests can observe + assert teardown.
        _STARTED_SOURCES[response] = started_source
        return response

    return _view
