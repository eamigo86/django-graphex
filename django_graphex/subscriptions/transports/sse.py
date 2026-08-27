r"""SSE transport adapter for the native serialize-once subscription engine.

The Server-Sent Events transport is the FIRST (cheap) engine validator (design
section 7): an async Django view (Django>=5.2 -> clean disconnect cancellation
GUARANTEED) returning a "StreamingHttpResponse(content_type='text/event-stream')".
ONE HTTP request -> ONE subscription stream.

It is intentionally THIN — roughly six lines of wire framing over the shared
driver. The engine does the work:

  * AUTH lives in the HTTP request ("request.user" / session) — the replacement
    for the deleted channel-ownership guard. A transport-neutral context exposing
    ".user" + a "scope" mapping is built from the "HttpRequest" and threaded
    into the engine (design section 7), so the hooks never assume an
    "HttpRequest".
  * The request's GraphQL document ("query"/"variables"/"operationName") is
    parsed; a parse error BEFORE the 200 response started is an HTTP 4xx. The
    document is then driven IN-STREAM (validation, subscribe, delivery), so any
    error after the 200 response started is surfaced as an in-stream
    "next{errors}" frame followed by "complete" — NEVER an HTTP 4xx (a 4xx is
    impossible once the streaming response has begun, and EventSource only sees
    in-stream frames).
  * The live native schema is the one the view was constructed with; the parsed
    request "DocumentNode" is supplied to WU5 "drive_subscription" at delivery
    (WU7 made the field's subscribe factory build the "ChannelLayerSource"
    WITHOUT needing the schema/document — only the per-event "execute" does).
  * "graphql-core" "create_source_event_stream" runs the subscription field's
    native subscribe entry (-> "ChannelLayerSource"); "drive_subscription"
    (COND-A — NOT "MapAsyncIterator") wraps it with a per-event "execute" over
    the flat serialize-once dict.
  * Each "ExecutionResult" is framed "event: next\\ndata: {json}\\n\\n"; on
    completion "event: complete\\ndata: \\n\\n" (the empty "data:" line is
    MANDATORY or an EventSource client never fires the "complete" event).
  * Client disconnect / aclosing -> the streaming generator's "finally" runs
    "source.aclose()" -> "group_discard" for every joined group (the WU4 sweep
    releases a blocked receive + discards every group), so no ghost subscriber
    survives a teardown. Django>=5.2 guarantees the disconnect cancellation that
    triggers "GeneratorExit" into the async generator. The SAME teardown is
    registered on the response ("_resource_closers"), because a response whose
    body is NEVER iterated — a client that aborts during the subscribe
    handshake — would otherwise leave its groups joined forever.
  * A failure DURING delivery is framed in-stream ("next{errors}" then
    "complete"), never allowed to escape the generator: the 200 is already
    committed, so an escaping exception would abort the connection with no
    protocol signal at all.

This module reads "graphql_api_settings.MAX_VALIDATION_ERRORS" (NOT
"graphene_settings" — the no-graphene-import gate). It imports neither graphene
nor channels at module scope; "channels" is imported lazily inside the view so
the base package never hard-requires the optional "[subscriptions]" extra.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

from asgiref.sync import async_to_sync, sync_to_async
from django.http import StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from graphql import (
    ExecutionResult,
    OperationType,
    create_source_event_stream,
    parse,
    validate,
)
from graphql.utilities import get_operation_ast

from ...security import format_graphql_error
from ...settings import graphql_api_settings
from ..streaming import SubscriptionSpec, build_middleware_manager, drive_subscription
from . import operation_selection_error

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncIterator, Callable, Mapping

    from django.http import HttpRequest
    from graphql import DocumentNode, GraphQLSchema

    from ..source import ChannelLayerSource

__all__ = ["TransportContext", "subscription_sse_view"]

logger = logging.getLogger(__name__)


def _close_source_sync(source: "ChannelLayerSource") -> None:
    """Tear a started source down from a SYNCHRONOUS response-close callback.

    Django closes a response from a worker thread
    ("await sync_to_async(response.close)()"), so "async_to_sync" is the safe
    bridge back to the loop. "aclose()" is idempotent, so this is a no-op when
    the streaming generator already ran its own teardown.

    Args:
        source: The started source whose joined groups must be discarded.
    """
    if source.is_closed:
        return
    async_to_sync(source.aclose)()


# A generic denial for a subscription-less (fully-pruned) schema. It mirrors the
# HTTP view's generic-403 philosophy (views.py ``_FORBIDDEN_MESSAGE``): it leaks
# NOTHING about which subscription field/type is missing, so a per-user pruned
# schema whose Subscription root is None never reveals the server's schema shape.
# Without it, graphql-core surfaces the vague-but-leaky "Schema is not configured
# to execute subscription operation." instead.
_SUBSCRIPTION_DENIED_MESSAGE = "Subscriptions are not available."

# Sentinel distinguishing "the body was not an object" (``None``) from "the
# body was fine but ``variables`` was not a mapping". They are different client
# errors and deserve different messages; sharing one would send the caller
# looking at their whole payload instead of one key.
_INVALID_VARIABLES: "dict[str, Any]" = {}


# A view → started-source map so callers/tests can observe the live source a
# response is streaming (and assert teardown). A WeakKeyDictionary keyed by the
# response object avoids leaking sources after the response is collected.
_STARTED_SOURCES: "WeakKeyDictionary[Any, ChannelLayerSource | None]" = (
    WeakKeyDictionary()
)


def get_started_source(response: Any) -> "ChannelLayerSource | None":
    """Return the started "ChannelLayerSource" a response is streaming.

    "None" when the subscribe was denied/errored before a source was created
    (e.g. an authorize-deny short-circuited before any "group_add"), or when the
    response is not an SSE subscription response.

    Args:
        response: The "StreamingHttpResponse" returned by the SSE view.

    Returns:
        The live source, or "None".
    """
    return _STARTED_SOURCES.get(response)


class TransportContext:
    """Transport-neutral context exposing ".user" + a "scope" mapping (section 7).

    Built from the "HttpRequest" so the engine hooks ("authorize"/"scope")
    work uniformly across SSE ("HttpRequest") and WS (Channels "scope")
    WITHOUT assuming an "HttpRequest". Only ".user" and ".scope" are part of
    the contract the hooks rely on; the underlying request is carried for callers
    that need it.

    Attributes:
        user: The authenticated (or anonymous) user from "request.user".
        scope: A mapping carrying transport scope (here: "{'user': user,
            'session': request.session}" when available).
        request: The originating "HttpRequest" (transport-specific; not part of
            the neutral contract).
        context: "self". The subscribe hooks
            ("authorize_subscription"/"subscription_scope") receive this object
            as their "info" argument, and every documented hook reads
            "info.context.user" — the SAME spelling a resolver uses, where
            "info" is a real "GraphQLResolveInfo" whose ".context" IS this
            object. The alias makes both spellings resolve to the same user.
        middleware: The connection's "DJANGO_GRAPHEX['MIDDLEWARE']" manager
            (built ONCE per request), read by the subscribe entry and carried
            onto the delivery spec.
    """

    __slots__ = ("user", "scope", "request", "context", "middleware")

    def __init__(self, request: "HttpRequest") -> None:
        """Build the neutral context from an "HttpRequest".

        Args:
            request: The originating "HttpRequest" the neutral context wraps.
        """
        self.request = request
        # The hooks receive this object as ``info``; ``info.context`` is how
        # every documented hook reaches the user, so it must resolve.
        self.context = self
        self.user = getattr(request, "user", None)
        self.scope: dict[str, Any] = {"user": self.user}
        session = getattr(request, "session", None)
        if session is not None:
            self.scope["session"] = session
        # SECURITY (2.0.1): subscriptions are served ONLY by this transport and
        # the WS one, and neither used to build a MiddlewareManager — so every
        # configured GraphQL middleware (AuthenticatedFieldsMiddleware included)
        # was inert on subscriptions. One manager per connection, shared by the
        # subscribe entry and the per-event delivery execute.
        self.middleware = build_middleware_manager()


async def _resolve_request_user(request: "HttpRequest") -> Any:
    """Resolve "request.user" in a thread, before anything reads it in the loop.

    "AuthenticationMiddleware" assigns a "SimpleLazyObject" and leaves it
    UNRESOLVED; the session/user query only runs when something first touches
    it. In a WSGI view that is harmless. Here the whole view body IS the event
    loop, so the first hook to read "info.context.user" — or a
    "schema_provider" pruning by permission — fires that query in an async
    context and dies with "SynchronousOnlyOperation". Anonymous callers never
    noticed: an empty session resolves to "AnonymousUser" without touching the
    database.

    Touching one attribute from a thread resolves the lazy object IN PLACE, so
    this is the whole fix for every later reader — the hooks, the middleware
    chain and any resolver reaching back through "context.request" all see a
    plain, already-loaded user. The WS transport needs no equivalent: Channels'
    "AuthMiddleware" awaits the lookup before the consumer runs.

    Args:
        request: The incoming HTTP request, possibly carrying a lazy user.

    Returns:
        The resolved user, or "None" when the request never met the auth
        middleware (an endpoint mounted outside the session/auth chain).
    """
    user = getattr(request, "user", None)
    if user is None:
        return None
    await sync_to_async(lambda: getattr(user, "is_authenticated", False))()
    return user


def _read_request_body(request: "HttpRequest") -> "dict[str, Any] | None":
    """Parse the GraphQL request body (JSON or form-encoded "query").

    Args:
        request: The incoming HTTP request.

    Returns:
        A mapping with "query" / "variables" / "operationName" keys, or "None"
        when the JSON body decoded to something that is not an object.
    """
    content_type = (request.content_type or "").lower()
    if "application/json" in content_type:
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError, RecursionError):
            # "RecursionError" is NOT a "ValueError": a deeply nested body blows
            # the decoder's recursion limit, and without it in this tuple the
            # error escaped the view and reached the client as a 500.
            body = {}
        if not isinstance(body, dict):
            # "[1,2,3]", '"x"' and "null" all decode cleanly and only then break
            # the mapping assumption below ("body.get" -> "AttributeError" ->
            # 500). The HTTP view already answers 400 for exactly this shape, so
            # the caller refuses it the same way instead.
            return None
    else:
        body = request.POST
    variables = body.get("variables")
    if isinstance(variables, str):
        # A form-encoded body makes EVERY value a string, and a JSON body may
        # carry variables as an encoded string too. graphql-core raises a plain
        # TypeError for anything but a mapping, and nothing downstream catches
        # it, so an undecoded string escaped the async view as a 500. The HTTP
        # view has always decoded this shape; the transport now matches it.
        try:
            variables = json.loads(variables or "{}")
        except ValueError:
            return _INVALID_VARIABLES
        if not isinstance(variables, dict):
            return _INVALID_VARIABLES
    elif variables is not None and not isinstance(variables, dict):
        return _INVALID_VARIABLES
    return {
        "query": body.get("query"),
        "variables": variables,
        "operationName": body.get("operationName"),
    }


def _frame_next(result: ExecutionResult) -> bytes:
    r"""Frame an "ExecutionResult" as an SSE "next" event.

    Args:
        result: The per-event execution result.

    Returns:
        The encoded "event: next\\ndata: {json}\\n\\n" frame.
    """
    payload: dict[str, Any] = {}
    if result.data is not None:
        payload["data"] = result.data
    if result.errors:
        payload["errors"] = [format_graphql_error(error) for error in result.errors]
    body = json.dumps(payload)
    return f"event: next\ndata: {body}\n\n".encode("utf-8")


# The terminal SSE frame. The empty ``data:`` line is MANDATORY — an EventSource
# client never fires the ``complete`` event without a data line on the frame.
_COMPLETE_FRAME: bytes = b"event: complete\ndata: \n\n"

# The frame that OPENS the response. A bare ``:`` is an SSE comment line, which
# every conforming client ignores — its only job is to be the first body chunk,
# because that is what makes an ASGI server flush the status line and headers.
_PREAMBLE_FRAME: bytes = b":\n\n"


def _make_spec(
    schema: "GraphQLSchema",
    document: "DocumentNode",
    middleware: Any = None,
    variable_values: "Mapping[str, Any] | None" = None,
    operation_name: str | None = None,
) -> SubscriptionSpec:
    """Build the minimal driver spec carrying the live schema + parsed document.

    "drive_subscription" reads ONLY the per-event "execute" inputs
    ("spec.schema", "spec.document", "spec.variable_values",
    "spec.operation_name" and "spec.middleware"); every other spec field is the
    subscribe-time concern already handled by "create_source_event_stream"
    (which ran the field's own native subscribe entry). So the transport supplies
    a spec whose sole job is to carry the live schema, the per-request selection
    set, the request's variables/operation name and the connection's middleware
    chain into the delivery "execute".

    Args:
        schema: The live native "GraphQLSchema".
        document: The parsed subscription "DocumentNode".
        middleware: The connection's "MiddlewareManager" (or "None").
        variable_values: The request's GraphQL variables (or "None") — the SAME
            ones passed to "create_source_event_stream".
        operation_name: The request's operation name (or "None").

    Returns:
        A "SubscriptionSpec" carrying every per-event "execute" input.
    """
    return SubscriptionSpec(
        model_label="",
        stream="",
        schema=schema,
        document=document,
        middleware=middleware,
        variable_values=variable_values,
        operation_name=operation_name,
    )


def subscription_sse_view(
    *,
    schema: "GraphQLSchema | None" = None,
    schema_provider: "Callable[[Any], GraphQLSchema] | None" = None,
) -> "Callable[..., Any]":
    """Build the async SSE subscription view bound to "schema" / "schema_provider".

    The returned view is an async Django view (Django>=5.2): it parses the GraphQL
    request, starts the subscription source (running the engine's authorize/scope
    hooks before any "group_add"), and returns a
    "StreamingHttpResponse(content_type='text/event-stream')" whose generator
    drives serialize-once delivery and tears the source down on disconnect.

    Args:
        schema: The live native graphql-core "GraphQLSchema" the subscription
            executes against (validation, the subscribe entry, and the per-event
            delivery "execute" all use it). Backward compatible: passing a plain
            "schema=" keeps the pre-change behavior.
        schema_provider: Optional per-connection resolver
            "Callable[[user], GraphQLSchema]". When given it WINS over "schema"
            and is resolved with "request.user" at request time, so an SSE
            connection uses the SAME pruned schema as HTTP for that user. When
            "None" the baked "schema" is used unchanged.

    Returns:
        An async view callable "async (request) -> StreamingHttpResponse".

    Raises:
        ValueError: If neither "schema" nor "schema_provider" is supplied.
    """
    if schema is None and schema_provider is None:
        raise ValueError(
            "subscription_sse_view requires either schema= or schema_provider=."
        )

    async def _view(request: "HttpRequest", *args: Any, **kwargs: Any) -> Any:
        from django.http import HttpResponseBadRequest, HttpResponseForbidden

        # Imported HERE, not at module level: "views" reaches
        # "core.permission_signature_cache", which reads "DJANGO_GRAPHEX" while it
        # is being imported. A module-level import would therefore make this
        # transport unimportable until Django settings are configured -- a
        # dependency it did not have before it started sharing the HTTP view's
        # CSRF guard and rule tuple, and one that bites any entrypoint importing
        # the view builder before it points at a settings module.
        from ...views import (
            CSRF_GUARD_MESSAGE,
            DEFAULT_VALIDATION_RULES,
            BaseGraphQLView,
            csrf_header_missing,
        )

        # Same hole as the HTTP views, same guard: this endpoint is csrf_exempt
        # and reads a form-encoded "query" straight out of "request.POST", and
        # form-encoded / multipart / text/plain are CORS-simple, so a cross-site
        # <form> submit reaches it with the victim's session cookie. Refused in
        # PLAIN TEXT, like every other pre-200 rejection below: an EventSource
        # client never parses a JSON "errors" envelope.
        if csrf_header_missing(request, BaseGraphQLView.get_content_type(request)):
            return HttpResponseForbidden(CSRF_GUARD_MESSAGE)

        # Resolve the lazy user ONCE, in a thread, before either the provider
        # below or any subscribe hook reads it from inside this async view.
        user = await _resolve_request_user(request)

        # Per-connection schema resolution: the provider (when given) wins and is
        # resolved with the request user, matching the HTTP pruned schema.
        conn_schema = schema_provider(user) if schema_provider is not None else schema

        body = _read_request_body(request)
        if body is None:
            # PRE-200: a decodable but non-object JSON body is a client error,
            # answered with the HTTP view's own message so the whole library
            # classifies the shape identically.
            return HttpResponseBadRequest(
                "The received data is not a valid JSON query."
            )
        if body is _INVALID_VARIABLES:
            # PRE-200: the HTTP view's own message, so the whole library
            # classifies this shape identically.
            return HttpResponseBadRequest("Variables are invalid JSON.")

        query = body["query"]
        if not query:
            # PRE-200: no query at all is a plain client error (HTTP 4xx).
            return HttpResponseBadRequest("No GraphQL query provided.")

        try:
            document = parse(query)
        except Exception as exc:  # PRE-200: a syntax error is an HTTP 4xx.
            return HttpResponseBadRequest(f"GraphQL syntax error: {exc}")

        operation_ast = get_operation_ast(document, body["operationName"])
        if operation_ast is None:
            # PRE-200: no operation could be SELECTED — several with no name to
            # pick one, or a name matching none. Distinct from "not a
            # subscription", which is what the fall-through below reports.
            selection_error = operation_selection_error(document, body["operationName"])
            if selection_error is not None:
                return HttpResponseBadRequest(selection_error)
        if (
            operation_ast is None
            or operation_ast.operation != OperationType.SUBSCRIPTION
        ):
            # PRE-200: this transport only serves subscriptions.
            return HttpResponseBadRequest(
                "The SSE transport only serves subscription operations."
            )

        context = TransportContext(request)

        started_source: "ChannelLayerSource | None" = None
        pre_stream_result: ExecutionResult | None = None

        # Subscription-less (fully-pruned) schema short-circuit: a per-user pruned
        # schema whose Subscription root is None would make graphql-core raise the
        # vague-but-leaky "Schema is not configured to execute subscription
        # operation." Deny GENERICALLY here (mirroring the HTTP view's generic-403
        # philosophy) so nothing about the server's schema shape leaks. Delivered
        # in-stream (the 200 stream is committed below), never a source.
        if conn_schema.subscription_type is None:
            from graphql import GraphQLError

            pre_stream_result = ExecutionResult(
                data=None,
                errors=[GraphQLError(_SUBSCRIPTION_DENIED_MESSAGE)],
            )
        else:
            # Validate the document. A validation error here is delivered IN-STREAM
            # (the 200 text/event-stream response is committed below), NOT an HTTP
            # 4xx — once the streaming response has started a 4xx is impossible and
            # an EventSource client only observes in-stream frames.
            #
            # Same rule tuple as the HTTP view: a subscription's selection set is
            # re-executed for EVERY delivered event, so an over-deep or over-costly
            # document is paid for repeatedly — the depth/cost guards matter more
            # here than on a one-shot query, not less.
            validation_errors = validate(
                conn_schema,
                document,
                DEFAULT_VALIDATION_RULES,
                max_errors=graphql_api_settings.MAX_VALIDATION_ERRORS,
            )
            if validation_errors:
                pre_stream_result = ExecutionResult(data=None, errors=validation_errors)
            else:
                # Run the subscription field's native subscribe entry. This runs
                # the KEPT hooks BEFORE any group_add (authorize-deny
                # short-circuits before the source), returning the started
                # ChannelLayerSource — or an ExecutionResult when the subscribe
                # resolver reported an error (deny).
                source_or_result = await create_source_event_stream(
                    conn_schema,
                    document,
                    context_value=context,
                    variable_values=body["variables"],
                    operation_name=body["operationName"],
                )
                if isinstance(source_or_result, ExecutionResult):
                    pre_stream_result = source_or_result
                else:
                    started_source = source_or_result  # type: ignore[assignment]

        spec = _make_spec(
            conn_schema,
            document,
            context.middleware,
            variable_values=body["variables"],
            operation_name=body["operationName"],
        )

        async def _event_stream() -> "AsyncIterator[bytes]":
            # Open the response before anything else. An ASGI server writes the
            # status line and headers with the FIRST body chunk, so a stream
            # that yields nothing until an event fires leaves the client with
            # no response at all while it idles: the browser's fetch never
            # resolves (the bundled client cannot show a connected state) and
            # an intermediary times the silent connection out. ``:`` opens an
            # SSE comment line, which every conforming client ignores.
            yield _PREAMBLE_FRAME

            # A pre-stream result (validation error / subscribe deny) is delivered
            # in-stream as a single ``next`` frame then ``complete`` — NOT a 4xx.
            if started_source is None:
                if pre_stream_result is not None:
                    yield _frame_next(pre_stream_result)
                yield _COMPLETE_FRAME
                return

            delivery = drive_subscription(started_source, spec, context)
            try:
                try:
                    async for result in delivery:
                        yield _frame_next(result)
                except Exception as exc:  # noqa: BLE001 - framed, never escapes
                    # A delivery failure (e.g. an ORM error raised by a
                    # server-forced scope lookup) must NOT escape the generator:
                    # the 200 text/event-stream response is already committed,
                    # so an escaping exception aborts the connection with no
                    # protocol signal at all. Frame it exactly like a post-200
                    # validation error — next{errors} — then complete.
                    from graphql import GraphQLError

                    logger.exception("Subscription delivery failed; closing stream.")
                    yield _frame_next(
                        ExecutionResult(data=None, errors=[GraphQLError(str(exc))])
                    )
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
        if started_source is not None:
            # The group join happens BEFORE this response is returned, while
            # teardown lives in the generator's ``finally`` — so a response that
            # is never iterated (a client that aborts during the handshake; the
            # ASGI handler closes a response whose body it never pulled) would
            # leave a ghost group member every future broadcast fans out to.
            # ``close()`` is the one callback Django guarantees for a response
            # it is finished with, iterated or not.
            response._resource_closers.append(
                partial(_close_source_sync, started_source)
            )
        # Record the live source so callers/tests can observe + assert teardown.
        _STARTED_SOURCES[response] = started_source
        return response

    # CSRF exemption mirrors ``GraphQLView`` (views.py ``as_view``): the GraphQL
    # document IS the request payload and the view auth-gates the subscription
    # itself (the KEPT authorize/scope hooks), so session-cookie CSRF adds no
    # protection to a same-origin JSON POST. Without this, a real browser/curl
    # POST (which carries no CSRF token) is rejected with 403 by
    # ``CsrfViewMiddleware`` before the view ever runs — the bundled client's
    # ``fetch`` POST sends no token, so it would never reach the stream. What
    # replaces the token for the content types a browser CAN post cross-site
    # without a preflight is the ``REQUIRE_CSRF_HEADER`` guard at the top of
    # ``_view``, shared with the HTTP views.
    return csrf_exempt(_view)
