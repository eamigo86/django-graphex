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

from inspect import isawaitable
from typing import TYPE_CHECKING

from graphql import ExecutionResult
from graphql import execution as graphql_execution

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncIterable, Callable
    from typing import Any

    from graphql import DocumentNode, GraphQLSchema

__all__ = ["sse", "ws"]


async def _start_source_event_stream(
    schema: "GraphQLSchema",
    document: "DocumentNode",
    *,
    context_value: Any,
    variable_values: dict[str, Any] | None,
    operation_name: str | None,
    source_factory: "Callable[..., Any]",
) -> "AsyncIterable[Any] | ExecutionResult":
    """Start a transport source with the installed GraphQL execution API.

    Args:
        schema: Request-specific schema used for subscription execution.
        document: Parsed subscription document.
        context_value: Transport context passed to the subscribe resolver.
        variable_values: Client variables for the selected operation.
        operation_name: Name of the selected subscription operation, if any.
        source_factory: Transport-local source factory, retained for injection.

    Returns:
        The source stream or an execution result containing startup errors.

    Raises:
        TypeError: When client variables are not a dictionary.
    """
    if variable_values is not None and not isinstance(variable_values, dict):
        raise TypeError(
            "Variable values must be provided as a dictionary"
            " with variable names as keys. Perhaps look to see"
            " if an unparsed JSON string was provided."
        )

    executor_class = getattr(graphql_execution, "Executor", None)
    if executor_class is None:
        result = source_factory(
            schema,
            document,
            context_value=context_value,
            variable_values=variable_values,
            operation_name=operation_name,
        )
    else:
        executor = executor_class.build(
            schema,
            document,
            context_value=context_value,
            raw_variable_values=variable_values,
            operation_name=operation_name,
        )
        if isinstance(executor, list):
            return ExecutionResult(data=None, errors=executor)
        result = source_factory(executor)

    return await result if isawaitable(result) else result


def operation_selection_error(
    document: "DocumentNode", operation_name: str | None
) -> str | None:
    """Explain why no operation could be SELECTED from "document".

    "get_operation_ast" answers None for three unrelated reasons, and only one
    of them is "the operation is not the kind this transport serves". The other
    two are about picking an operation at all, and reporting either as an
    operation-kind problem sends the caller hunting for a query or mutation
    their document does not contain.

    Both transports call this first and fall back to their own operation-kind
    message only when it answers "None".

    Args:
        document: The parsed GraphQL document.
        operation_name: The operation name the request supplied, if any.

    Returns:
        A message naming the selection problem, or "None" when the document
        does offer an operation the request could have selected.
    """
    from graphql import OperationDefinitionNode

    operations = [
        definition
        for definition in document.definitions
        if isinstance(definition, OperationDefinitionNode)
    ]
    if operation_name:
        if any(
            operation.name and operation.name.value == operation_name
            for operation in operations
        ):
            return None
        return (
            f"This request names operation {operation_name!r}, which this "
            "document does not define."
        )
    if len(operations) > 1:
        return (
            "This request carries several operations; name the one to run "
            "with operationName."
        )
    return None
