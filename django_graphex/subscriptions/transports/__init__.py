"""Transport adapters for the native serialize-once subscription engine.

Two transports drive the SAME engine (design sections 1, 7): one HTTP request /
one WebSocket connection -> "drive_subscription" over the serialize-once flat-pk
data path. The engine core ("ChannelLayerSource" group consumer, COND-A delivery
iterator, snake-closure projection) is transport-agnostic; these adapters only
frame "ExecutionResult" values for the wire and translate client disconnect into
"source.aclose()" teardown.

  * "sse" — Server-Sent Events (SHIP FIRST, the cheap engine validator).
  * "ws" — graphql-transport-ws over Channels (SHIP SECOND, the heavier
    transport: connection_init/ack auth handshake, per-id task registry, N ops
    multiplexed over one socket, close codes 4400/4401/4408/4409/4429).

No module here imports graphene; "channels" is imported lazily/guarded so the
base package never hard-requires it. The "ws" consumer module imports
"channels.generic.websocket" only inside its factory, so importing this package
never pulls channels until WS is actually routed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from graphql import DocumentNode

__all__ = ["sse", "ws"]


def is_ambiguous_operation(
    document: "DocumentNode", operation_name: str | None
) -> bool:
    """Check whether a document needs an "operationName" it was not given.

    "get_operation_ast" answers None for two unrelated cases: the named (or
    only) operation is not the kind the caller wanted, and the document holds
    several operations while the request named none. Both transports refuse on
    None, so they need this to tell the caller which one happened.

    Args:
        document: The parsed GraphQL document.
        operation_name: The operation name the request supplied, if any.

    Returns:
        "True" when the document defines more than one operation and the
        request named none of them.
    """
    from graphql import OperationDefinitionNode

    if operation_name:
        return False
    operations = [
        definition
        for definition in document.definitions
        if isinstance(definition, OperationDefinitionNode)
    ]
    return len(operations) > 1
