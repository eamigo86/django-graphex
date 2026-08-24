r"""graphql-transport-ws WebSocket transport adapter for the native engine.

The WebSocket transport is the SECOND (heavier) engine validator (design section
7): a Channels "AsyncJsonWebsocketConsumer" speaking the graphql-transport-ws
protocol over a SINGLE socket that multiplexes N concurrent operations. Both
transports drive the SAME serialize-once engine — the WS adapter only frames the
protocol envelopes and translates a per-id "complete" / a disconnect into the
matching "source.aclose()" teardown.

Protocol (graphql-transport-ws, primary subprotocol only; the legacy
"graphql-ws" shim is DEFERRED):

  * Handshake — "connection_init" -> "connection_ack". The "connection_init"
    IS the auth boundary: the authenticated socket carries the user in
    "self.scope['user']" (no detached per-operation token). The server waits at
    most "init_timeout" seconds ("connectionInitWaitTimeout") for the first
    "connection_init"; on timeout it closes with 4408. A SECOND
    "connection_init" closes with 4429 (Too many initialisation requests). A
    "subscribe" BEFORE the ack closes with 4401 (Unauthorized).
  * Operations — each "subscribe{id, payload:{query, variables, operationName}}"
    starts an "asyncio.Task" that runs the engine's native subscribe entry over
    its own "ChannelLayerSource", then drives WU5 "drive_subscription",
    emitting "next{id, payload}" per delivered event and a terminal
    "complete{id}" when the source ends. A subscribe-time error (validation /
    authorize-deny / parse) is delivered as "error{id, payload:[...]}". A
    duplicate "id" (one already running) closes with 4409. N operations are
    multiplexed independently over the one socket.
  * "ping" -> "pong" (keep-alive, either direction; the server answers a
    client "ping").
  * Client "complete{id}" cancels ONLY that id's task and "group_discard"s ITS
    groups (via "source.aclose()"); other ids keep streaming. The server does
    NOT echo a "complete" for a client-initiated complete (per the spec — a
    server "complete" is the stream-ended signal).
  * Disconnect cancels ALL operation tasks and "group_discard"s every joined
    group (full source teardown), so no ghost subscriber survives.
  * A malformed message closes with 4400 (Bad Request): a non-mapping payload,
    an unknown "type", an undecodable JSON body, or a non-hashable "id". The
    close runs the FULL teardown first, so no frame can leave a task or a
    joined group behind.
  * A failure DURING delivery (after the first event) is not a close: it is
    delivered as "next{id, payload:{errors}}" followed by the terminal
    "complete{id}", so the client never waits on a silently dead stream.

Per-task cleanup uses "add_done_callback" (the strawberry.channels hardening):
the operation is removed from the registry the instant its task ends — normal
completion, error, OR an abnormal cancel — so the registry never leaks a dead id.

Transport-neutral context (design section 7): the engine hooks/"execute" receive
a context exposing ".user" + a "scope" mapping, here built from "self.scope"
(the Channels scope dict — NOT an "HttpRequest"), so the authorize/scope hooks
behave identically to the SSE transport.

This module reads "graphql_api_settings.SUBSCRIPTION_CONNECTION_INIT_TIMEOUT"
(NOT "graphene_settings" — the no-graphene-import gate). It imports neither
graphene at any scope nor "channels" at module scope; "channels" is imported
lazily inside the factory so the base subscriptions package never hard-requires
the optional "[subscriptions]" extra (the consumer module is only imported when
WS is actually routed).

The protocol reference is the graphql-transport-ws PROTOCOL.md:
https://github.com/enisdenjo/graphql-ws/blob/master/PROTOCOL.md
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

from graphql import (
    ExecutionResult,
    OperationType,
    create_source_event_stream,
    parse,
    validate,
)
from graphql.utilities import get_operation_ast

from ...settings import graphql_api_settings
from ..streaming import SubscriptionSpec, build_middleware_manager, drive_subscription

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Mapping

    from graphql import DocumentNode, GraphQLSchema

    from ..source import ChannelLayerSource

__all__ = [
    "TransportContext",
    "get_live_consumer",
    "subscription_ws_consumer",
]

logger = logging.getLogger(__name__)


def _as_error(exc: BaseException) -> Any:
    """Wrap an exception as a "GraphQLError" for a "next{errors}" frame.

    Args:
        exc: The exception raised while delivering the subscription.

    Returns:
        A "GraphQLError" carrying the exception message.
    """
    from graphql import GraphQLError

    return GraphQLError(str(exc))


# graphql-transport-ws close codes.
_CODE_BAD_REQUEST = 4400
_CODE_UNAUTHORIZED = 4401
_CODE_CONNECTION_INIT_TIMEOUT = 4408
_CODE_SUBSCRIBER_ALREADY_EXISTS = 4409
_CODE_TOO_MANY_INIT_REQUESTS = 4429

# The accepted (and only) subprotocol.
_SUBPROTOCOL = "graphql-transport-ws"

# A generic denial for a subscription-less (fully-pruned) schema. Mirrors the SSE
# transport / HTTP view's generic-403 philosophy: it leaks NOTHING about which
# subscription field/type is missing, so a per-user pruned schema whose
# Subscription root is None never reveals the server's schema shape (instead of
# graphql-core's vague-but-leaky "Schema is not configured to execute
# subscription operation.").
_SUBSCRIPTION_DENIED_MESSAGE = "Subscriptions are not available."


# A scope-identity → consumer registry so callers/tests can observe the live
# consumer (its per-id operation registry + started sources). A
# WeakValueDictionary keyed by ``id(scope)`` avoids leaking consumers after the
# socket is collected; the consumer also removes itself on disconnect.
_LIVE_CONSUMERS: "WeakValueDictionary[int, Any]" = WeakValueDictionary()


def get_live_consumer(scope: "Mapping[str, Any]") -> Any:
    """Return the live consumer instance backing "scope" (or "None").

    The consumer registers itself under "id(scope)" while connected so a caller
    holding the ASGI scope (e.g. a test communicator) can introspect the live
    per-id operation registry and the started sources.

    Scope-GC caveat (audit rank 20): the registry is a "WeakValueDictionary" keyed
    by "id(scope)", so this lookup may return "None" if the consumer has been
    garbage-collected — and, more subtly, the key itself uses "id(scope)", which
    Python may RECYCLE for a different object once the original scope is collected.
    This is purely a test/introspection-utility caveat: the live subscription is
    UNAFFECTED because the running consumer keeps its OWN strong references
    (Channels holds the consumer for the lifetime of the socket; the consumer
    holds its per-id operation registry and sources). Losing the weak entry here
    only means an out-of-band observer can no longer reach the consumer through
    this helper — the subscription keeps delivering. Callers must therefore treat
    a "None" result as "not observable via this registry", not as "the
    subscription is gone".

    Args:
        scope: The Channels ASGI scope dict the connection was opened with.

    Returns:
        The connected consumer instance, or "None" when not connected (or when
        the weak entry has been collected — see the scope-GC caveat above).
    """
    return _LIVE_CONSUMERS.get(id(scope))


class TransportContext:
    """Transport-neutral context exposing ".user" + a "scope" mapping (section 7).

    Built from the Channels "scope" dict (NOT an "HttpRequest") so the engine
    hooks ("authorize"/"scope") work uniformly across SSE ("HttpRequest") and
    WS (Channels "scope"). Only ".user" and ".scope" are part of the contract
    the hooks rely on.

    Attributes:
        user: The authenticated (or anonymous) user from "scope['user']".
        scope: The Channels scope mapping (carries "user"/"session"/etc.).
        context: "self". The subscribe hooks
            ("authorize_subscription"/"subscription_scope") receive this object
            as their "info" argument, and every documented hook reads
            "info.context.user" — the SAME spelling a resolver uses, where
            "info" is a real "GraphQLResolveInfo" whose ".context" IS this
            object. The alias makes both spellings resolve to the same user.
        middleware: The connection's "DJANGO_GRAPHEX['MIDDLEWARE']" manager
            (built ONCE per operation), read by the subscribe entry and carried
            onto the delivery spec.
    """

    __slots__ = ("user", "scope", "context", "middleware")

    def __init__(self, scope: "Mapping[str, Any]") -> None:
        """Build the neutral context from a Channels "scope" mapping.

        Args:
            scope: The Channels ASGI scope mapping the connection was opened with.
        """
        self.scope = scope
        # The hooks receive this object as ``info``; ``info.context`` is how
        # every documented hook reaches the user, so it must resolve.
        self.context = self
        self.user = scope.get("user") if scope else None
        # SECURITY (2.0.1): subscriptions are served ONLY by this transport and
        # the SSE one, and neither used to build a MiddlewareManager — so every
        # configured GraphQL middleware (AuthenticatedFieldsMiddleware included)
        # was inert on subscriptions. One manager per operation, shared by the
        # subscribe entry and the per-event delivery execute.
        self.middleware = build_middleware_manager()


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
    (which ran the field's own native subscribe entry). Mirrors the SSE
    transport's "_make_spec".

    Args:
        schema: The live native "GraphQLSchema".
        document: The parsed subscription "DocumentNode".
        middleware: The connection's "MiddlewareManager" (or "None").
        variable_values: The operation's GraphQL variables (or "None") — the
            SAME ones passed to "create_source_event_stream".
        operation_name: The operation's name (or "None").

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


def subscription_ws_consumer(
    *,
    schema: "GraphQLSchema | None" = None,
    schema_provider: "Callable[[Any], GraphQLSchema] | None" = None,
    init_timeout: float | None = None,
) -> type:
    """Build the graphql-transport-ws consumer class bound to "schema".

    The returned class is a Channels "AsyncJsonWebsocketConsumer" that accepts
    the "graphql-transport-ws" subprotocol, runs the connection_init/ack auth
    handshake, multiplexes N "subscribe" operations (each driving the
    serialize-once engine over its own "ChannelLayerSource"), answers "ping"
    with "pong", and tears every source down on per-id "complete" / disconnect.

    Args:
        schema: The live native graphql-core "GraphQLSchema" the subscription
            executes against (validation, the subscribe entry, and the per-event
            delivery "execute" all use it). Backward compatible: passing a plain
            "schema=" keeps the pre-change behavior.
        schema_provider: Optional per-connection resolver
            "Callable[[user], GraphQLSchema]". When given it WINS over "schema"
            and is resolved ONCE per socket using "scope['user']" (on the first
            subscribe, then cached for the connection), so the WS connection uses
            the SAME pruned schema as HTTP for that user. When "None" the baked
            "schema" is used unchanged.
        init_timeout: Seconds to wait for the first "connection_init" before
            closing with 4408. "None" reads
            "graphql_api_settings.SUBSCRIPTION_CONNECTION_INIT_TIMEOUT"
            (default 3.0). A test may pass a tiny value to avoid waiting.

    Returns:
        A Channels consumer class (an "AsyncJsonWebsocketConsumer" subclass).

    Raises:
        ValueError: If neither "schema" nor "schema_provider" is supplied.
    """
    if schema is None and schema_provider is None:
        raise ValueError(
            "subscription_ws_consumer requires either schema= or schema_provider=."
        )

    # channels is imported lazily here so importing the base subscriptions
    # package never hard-requires the optional [subscriptions] extra; this module
    # is only imported when WS is actually routed.
    from channels.generic.websocket import AsyncJsonWebsocketConsumer

    resolved_timeout = init_timeout

    class _SubscriptionWSConsumer(AsyncJsonWebsocketConsumer):
        """graphql-transport-ws consumer multiplexing N subscriptions per socket."""

        async def connect(self) -> None:
            """Accept the socket on the graphql-transport-ws subprotocol.

            The accept advertises the negotiated subprotocol. A
            "connectionInitWaitTimeout" watchdog is armed: if no
            "connection_init" arrives in time the socket is closed with 4408.
            """
            self._acked = False
            self._operations: dict[str, asyncio.Task] = {}
            self._sources: dict[str, "ChannelLayerSource"] = {}
            self._closing = False
            # Register so callers/tests can observe the live per-id registry.
            _LIVE_CONSUMERS[id(self.scope)] = self

            await self.accept(subprotocol=_SUBPROTOCOL)

            timeout = resolved_timeout
            if timeout is None:
                timeout = graphql_api_settings.SUBSCRIPTION_CONNECTION_INIT_TIMEOUT
            self._init_timer = asyncio.ensure_future(self._init_watchdog(timeout))

        async def _init_watchdog(self, timeout: float) -> None:
            """Close with 4408 if no "connection_init" arrives within "timeout"."""
            try:
                await asyncio.sleep(timeout)
            except asyncio.CancelledError:
                return
            if not self._acked and not self._closing:
                await self._close(_CODE_CONNECTION_INIT_TIMEOUT)

        async def receive(
            self,
            text_data: str | None = None,
            bytes_data: bytes | None = None,
            **kwargs: Any,
        ) -> None:
            """Dispatch one inbound frame, closing with 4400 if it cannot be.

            This is the ONE choke point every inbound frame routes through, and
            the only place an inbound-frame failure can be contained. Channels
            does NOT invoke "disconnect()" when a message handler raises: the
            exception propagates out of the consumer and the socket dies with
            every live operation's task still running and every joined group
            still registered — a ghost subscriber per malformed frame.

            Two client inputs used to escape here: an undecodable JSON body
            (raised by "decode_json" BEFORE "receive_json" is even called) and a
            non-hashable "id" (raised by the duplicate-id registry lookup). Both
            are a Bad Request, and "_close" runs the full cancel-all +
            "group_discard" teardown before closing the socket.

            Args:
                text_data: The inbound text frame, when the client sent one.
                bytes_data: The inbound binary frame, when the client sent one.
                **kwargs: Extra dispatch kwargs forwarded to the base consumer.
            """
            try:
                await super().receive(
                    text_data=text_data, bytes_data=bytes_data, **kwargs
                )
            except Exception:  # noqa: BLE001 - a bad frame must not kill the socket
                logger.exception(
                    "Malformed graphql-transport-ws frame; closing with %s.",
                    _CODE_BAD_REQUEST,
                )
                await self._close(_CODE_BAD_REQUEST)

        async def receive_json(self, content: Any, **kwargs: Any) -> None:
            """Dispatch one decoded graphql-transport-ws message.

            A non-mapping payload or an unknown "type" closes with 4400.
            """
            if self._closing:
                return
            if not isinstance(content, dict):
                await self._close(_CODE_BAD_REQUEST)
                return

            msg_type = content.get("type")
            if msg_type == "connection_init":
                await self._on_connection_init()
            elif msg_type == "ping":
                await self._on_ping(content)
            elif msg_type == "pong":
                # A client pong (response to a server ping) needs no reply.
                return
            elif msg_type == "subscribe":
                await self._on_subscribe(content)
            elif msg_type == "complete":
                await self._on_complete(content)
            else:
                # Unknown / unsupported message type.
                await self._close(_CODE_BAD_REQUEST)

        async def _on_connection_init(self) -> None:
            """Answer the first "connection_init" with "connection_ack".

            A SECOND "connection_init" is a protocol violation -> 4429.
            """
            if self._acked:
                await self._close(_CODE_TOO_MANY_INIT_REQUESTS)
                return
            self._acked = True
            timer = getattr(self, "_init_timer", None)
            if timer is not None and not timer.done():
                timer.cancel()
            await self.send_json({"type": "connection_ack"})

        async def _on_ping(self, content: dict[str, Any]) -> None:
            """Answer a "ping" with "pong" (echoing an optional payload)."""
            pong: dict[str, Any] = {"type": "pong"}
            if content.get("payload") is not None:
                pong["payload"] = content["payload"]
            await self.send_json(pong)

        async def _on_subscribe(self, content: dict[str, Any]) -> None:
            """Start a multiplexed operation for "subscribe{id, payload}".

            A subscribe BEFORE the ack is Unauthorized (4401). A duplicate id
            (one already running) is 4409. Otherwise an "asyncio.Task" runs the
            engine for this id; "add_done_callback" removes it from the registry
            the instant the task ends (normal/error/cancel).
            """
            if not self._acked:
                await self._close(_CODE_UNAUTHORIZED)
                return

            op_id = content.get("id")
            if op_id is None:
                await self._close(_CODE_BAD_REQUEST)
                return
            if op_id in self._operations:
                await self._close(_CODE_SUBSCRIBER_ALREADY_EXISTS)
                return

            payload = content.get("payload") or {}
            task = asyncio.ensure_future(self._run_operation(op_id, payload))
            self._operations[op_id] = task
            # strawberry.channels hardening: drop the id the instant its task ends
            # (normal completion, error, OR abnormal cancel) so the registry never
            # leaks a dead operation.
            task.add_done_callback(lambda _t, _id=op_id: self._operation_done(_id, _t))

        def _operation_done(self, op_id: str, task: asyncio.Task) -> None:
            """Drop a finished operation and RETRIEVE its exception.

            Popping alone left an unretrieved task exception behind, so a
            delivery crash surfaced only as asyncio's "Task exception was never
            retrieved" warning at garbage-collection time. Reading it here logs
            it against this module instead.

            Args:
                op_id: The operation id whose task ended.
                task: The finished operation task.
            """
            self._operations.pop(op_id, None)
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "Subscription operation %r ended with an unhandled error.",
                    op_id,
                    exc_info=exc,
                )

        def _resolve_schema(self) -> "GraphQLSchema":
            """Return the schema for THIS connection (provider wins, cached once).

            When a "schema_provider" was supplied it is resolved ONCE per socket
            using "scope['user']" and cached on the instance, so every
            multiplexed operation on this connection shares the SAME pruned schema
            (matching the HTTP pruned schema for that user). Otherwise the baked
            "schema" is returned unchanged.
            """
            cached = getattr(self, "_conn_schema", None)
            if cached is not None:
                return cached
            if schema_provider is not None:
                user = self.scope.get("user") if self.scope else None
                resolved = schema_provider(user)
            else:
                resolved = schema
            self._conn_schema = resolved
            return resolved

        async def _run_operation(self, op_id: str, payload: dict[str, Any]) -> None:
            """Run one subscription operation: subscribe -> next* -> complete.

            A subscribe-time error (parse / validation / authorize-deny) is
            delivered as "error{id, payload:[...]}" (no source started). A
            started source is driven via WU5 "drive_subscription" (COND-A — NOT
            "MapAsyncIterator"): each "ExecutionResult" -> "next{id, payload}";
            when the source ends -> terminal "complete{id}". A cancel (client
            "complete" / disconnect) tears the source down in "finally".
            """
            query = payload.get("query")
            if not query:
                await self._send_error(
                    op_id, [{"message": "No GraphQL query provided."}]
                )
                return

            try:
                document = parse(query)
            except Exception as exc:  # parse error → error frame (no source)
                await self._send_error(op_id, [{"message": f"Syntax error: {exc}"}])
                return

            operation_ast = get_operation_ast(document, payload.get("operationName"))
            if (
                operation_ast is None
                or operation_ast.operation != OperationType.SUBSCRIPTION
            ):
                await self._send_error(
                    op_id,
                    [{"message": "The WS transport only serves subscriptions."}],
                )
                return

            context = TransportContext(self.scope)

            # Per-connection schema (provider wins, resolved once via scope user).
            conn_schema = self._resolve_schema()

            # Subscription-less (fully-pruned) schema short-circuit: a per-user
            # pruned schema whose Subscription root is None would make graphql-core
            # raise the vague-but-leaky "Schema is not configured to execute
            # subscription operation." Deny GENERICALLY here (mirroring the SSE
            # transport / HTTP view generic-403 philosophy) so nothing about the
            # server's schema shape leaks. No source is ever started.
            if conn_schema.subscription_type is None:
                await self._send_error(
                    op_id, [{"message": _SUBSCRIPTION_DENIED_MESSAGE}]
                )
                return

            validation_errors = validate(
                conn_schema,
                document,
                max_errors=graphql_api_settings.MAX_VALIDATION_ERRORS,
            )
            if validation_errors:
                await self._send_error(op_id, [e.formatted for e in validation_errors])
                return

            # Run the subscription field's native subscribe entry. The KEPT hooks
            # run BEFORE any group_add (authorize-deny short-circuits before the
            # source), returning the started ChannelLayerSource — or an
            # ExecutionResult when the subscribe resolver reported an error (deny).
            try:
                source_or_result = await create_source_event_stream(
                    conn_schema,
                    document,
                    context_value=context,
                    variable_values=payload.get("variables"),
                    operation_name=payload.get("operationName"),
                )
            except Exception as exc:  # authorize-deny raised before any group_add
                await self._send_error(op_id, [{"message": str(exc)}])
                return

            if isinstance(source_or_result, ExecutionResult):
                errors = source_or_result.errors or []
                await self._send_error(
                    op_id,
                    [e.formatted for e in errors]
                    or [{"message": "Subscription could not be started."}],
                )
                return

            source: "ChannelLayerSource" = source_or_result  # type: ignore[assignment]
            self._sources[op_id] = source
            spec = _make_spec(
                conn_schema,
                document,
                context.middleware,
                variable_values=payload.get("variables"),
                operation_name=payload.get("operationName"),
            )
            delivery = drive_subscription(source, spec, context)
            try:
                try:
                    async for result in delivery:
                        await self._send_next(op_id, result)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - framed, never escapes
                    # A delivery failure (e.g. an ORM error raised by a
                    # server-forced scope lookup) must NOT kill the task
                    # silently: the client would wait forever on a dead
                    # subscription with no protocol signal at all, and the
                    # exception would surface only as an asyncio warning. Frame
                    # it as ``next{errors}`` — matching the SSE transport and
                    # the spec's "errors after execution started" shape — and
                    # fall through to the terminal ``complete``.
                    logger.exception(
                        "Subscription delivery failed for operation %r.", op_id
                    )
                    await self._send_next(
                        op_id, ExecutionResult(data=None, errors=[_as_error(exc)])
                    )
                # The source ended (out-of-band close) → the terminal complete.
                # A client-initiated complete cancels this task before this point,
                # so it never reaches the server ``complete`` (per the spec).
                await self.send_json({"id": op_id, "type": "complete"})
            except asyncio.CancelledError:
                # Client complete / disconnect cancelled this operation: tear the
                # source down (group_discard ITS groups), do NOT emit complete.
                raise
            finally:
                self._sources.pop(op_id, None)
                await delivery.aclose()

        async def _on_complete(self, content: dict[str, Any]) -> None:
            """Client "complete{id}": cancel ONLY that id (discard ITS groups).

            The other operations keep streaming. The cancel propagates into the
            operation task whose "finally" runs "delivery.aclose()" ->
            "source.aclose()" -> "group_discard" for every joined group.
            """
            op_id = content.get("id")
            if op_id is None:
                return
            await self._cancel_operation(op_id)

        async def _cancel_operation(self, op_id: str) -> None:
            """Cancel a single operation task and await its teardown."""
            task = self._operations.get(op_id)
            if task is None:
                return
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                # The task's finally ran source.aclose() (group_discard); a
                # cancel/teardown error here must not break the socket.
                pass
            self._operations.pop(op_id, None)
            self._sources.pop(op_id, None)

        async def disconnect(self, code: int) -> None:
            """Disconnect: cancel ALL operation tasks + "group_discard" all.

            Every started source is torn down so no ghost subscriber survives the
            socket close. Best-effort: a teardown error never propagates out of
            "disconnect".
            """
            self._closing = True
            _LIVE_CONSUMERS.pop(id(self.scope), None)
            timer = getattr(self, "_init_timer", None)
            if timer is not None and not timer.done():
                timer.cancel()
            for op_id in list(self._operations):
                await self._cancel_operation(op_id)
            # Defensive sweep: any source whose task was already gone but whose
            # groups were not yet discarded.
            for op_id in list(self._sources):
                source = self._sources.pop(op_id, None)
                if source is not None:
                    try:
                        await source.aclose()
                    except Exception:  # noqa: BLE001 - disconnect must not raise
                        pass  # nosec B110 — best-effort source close on disconnect

        # -- protocol frame senders -----------------------------------------
        async def _send_next(self, op_id: str, result: ExecutionResult) -> None:
            """Send a "next{id, payload}" frame for one execution result."""
            payload: dict[str, Any] = {}
            if result.data is not None:
                payload["data"] = result.data
            if result.errors:
                payload["errors"] = [e.formatted for e in result.errors]
            await self.send_json({"id": op_id, "type": "next", "payload": payload})

        async def _send_error(self, op_id: str, errors: list[Any]) -> None:
            """Send an "error{id, payload:[...]}" frame (subscribe-time error)."""
            await self.send_json({"id": op_id, "type": "error", "payload": errors})

        async def _close(self, code: int) -> None:
            """Close the socket with "code", tearing every operation down FIRST.

            A server-initiated close (4400/4401/4408/4409/4429) must ACTIVELY
            tear down before delegating to "self.close()". Channels'
            "AsyncWebsocketConsumer.close()" only emits a "websocket.close"
            ASGI message — it does NOT invoke "disconnect()", so the
            cancel-all + "group_discard" teardown that lives in "disconnect"
            would NOT run until a subsequent inbound "websocket.disconnect"
            arrives (which an ASGI server/proxy may never deliver, or a stalled
            client may delay). Without active teardown, any live operation's task
            + group membership would DANGLE -> ghost subscriber + leaked task.

            So here we drain every operation (cancel its task + "aclose()" its
            source -> "group_discard" its groups, exactly as "disconnect"
            does), sweep any remaining sources defensively, and ONLY THEN close
            the socket. "source.aclose()" is idempotent and "_cancel_operation"
            pops the registries, so a later inbound "disconnect()" finds empty
            dicts -> no double-discard, no double-cancel.
            """
            if self._closing:
                return
            self._closing = True
            # Active teardown BEFORE delegating to the server: cancel every
            # operation task + group_discard its groups (mirrors disconnect).
            for op_id in list(self._operations):
                await self._cancel_operation(op_id)
            # Defensive sweep: any source whose task already ended but whose
            # groups were not yet discarded.
            for op_id in list(self._sources):
                source = self._sources.pop(op_id, None)
                if source is not None:
                    try:
                        await source.aclose()
                    except Exception:  # noqa: BLE001 - close must not raise
                        pass  # nosec B110 — best-effort source close before socket close
            await self.close(code=code)

        # -- test/introspection accessors -----------------------------------
        def operation_ids(self) -> set[str]:
            """Return the set of currently-registered operation ids."""
            return set(self._operations)

        def started_source(self, op_id: str) -> "ChannelLayerSource | None":
            """Return the started "ChannelLayerSource" for "op_id".

            "None" until the operation's subscribe entry has started its source,
            or after the operation completed / was cancelled.
            """
            return self._sources.get(op_id)

    _SubscriptionWSConsumer.__name__ = "SubscriptionWSConsumer"
    _SubscriptionWSConsumer.__qualname__ = "SubscriptionWSConsumer"
    return _SubscriptionWSConsumer
