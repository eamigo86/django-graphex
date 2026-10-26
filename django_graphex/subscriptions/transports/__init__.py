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

from inspect import isawaitable, signature
from typing import TYPE_CHECKING

from graphql import ExecutionResult, GraphQLError, validate
from graphql import execution as graphql_execution

from ...security import mark_client_errors, mark_request_errors
from ...validation import run_validation

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import AsyncIterable, Callable
    from typing import Any

    from graphql import DocumentNode, GraphQLSchema

__all__ = ["sse", "ws"]

_VALIDATE_SUPPORTS_HIDE_SUGGESTIONS = (
    "hide_suggestions" in signature(validate).parameters
)
_NATIVE_EXECUTOR = getattr(graphql_execution, "Executor", None)
_EXECUTOR_SUPPORTS_HIDE_SUGGESTIONS = bool(
    _NATIVE_EXECUTOR
    and "hide_suggestions" in signature(_NATIVE_EXECUTOR.build).parameters
)


def _parse_subscription_document(query: Any) -> "DocumentNode":
    """Parse a subscription document the way the HTTP view does.

    Stack exhaustion becomes a GraphQLError with code "QUERY_TOO_DEEP", and any
    other non-GraphQL failure (for example a non-string query) becomes a
    generic one, so no raw exception text reaches a client.

    Args:
        query: The "query" value sent by the client.

    Returns:
        The parsed "DocumentNode".

    Raises:
        GraphQLError: When the document cannot be parsed.
    """
    # Imported here: "views" reads DJANGO_GRAPHEX while it is being imported, and
    # this package must stay importable before Django settings are configured.
    from ...views import _parse_or_depth_error

    try:
        return _parse_or_depth_error(query)
    except GraphQLError:
        raise
    except Exception as exc:
        raise GraphQLError("Invalid GraphQL query.") from exc


def _is_too_deep(error: GraphQLError) -> bool:
    """Return whether a parse error is the stack-depth client error.

    Args:
        error: The error raised by "_parse_subscription_document".

    Returns:
        True when its code is "QUERY_TOO_DEEP".
    """
    return (error.extensions or {}).get("code") == "QUERY_TOO_DEEP"


def _validate_subscription_document(
    schema: "GraphQLSchema",
    document: "DocumentNode",
    rules: Any,
    *,
    max_errors: int,
    hide_suggestions: bool,
) -> list[GraphQLError]:
    """Validate a subscription without sending unsupported options to 3.2.

    Args:
        schema: Request-specific subscription schema.
        document: Parsed subscription document.
        rules: Validation rules applied before source startup.
        max_errors: Maximum number of validation errors.
        hide_suggestions: Whether schema-derived suggestions are private.

    Returns:
        Validation errors for the request document.
    """
    options: dict[str, Any] = {"max_errors": max_errors}
    if _VALIDATE_SUPPORTS_HIDE_SUGGESTIONS:
        options["hide_suggestions"] = hide_suggestions
    return run_validation(validate, schema, document, rules, **options)


async def _start_source_event_stream(
    schema: "GraphQLSchema",
    document: "DocumentNode",
    *,
    context_value: Any,
    variable_values: dict[str, Any] | None,
    operation_name: str | None,
    source_factory: "Callable[..., Any]",
    hide_suggestions: bool = False,
) -> "AsyncIterable[Any] | ExecutionResult":
    """Start a transport source with the installed GraphQL execution API.

    Args:
        schema: Request-specific schema used for subscription execution.
        document: Parsed subscription document.
        context_value: Transport context passed to the subscribe resolver.
        variable_values: Client variables for the selected operation.
        operation_name: Name of the selected subscription operation, if any.
        source_factory: Transport-local source factory, retained for injection.
        hide_suggestions: Whether native variable errors omit schema hints.

    Returns:
        The source stream or an execution result containing startup errors, which
        include client variables that are not a dictionary.
    """
    if variable_values is not None and not isinstance(variable_values, dict):
        return ExecutionResult(
            data=None,
            errors=mark_client_errors(
                [
                    GraphQLError(
                        "Variable values must be provided as a dictionary"
                        " with variable names as keys. Perhaps look to see"
                        " if an unparsed JSON string was provided."
                    )
                ]
            ),
        )

    # "Executor" exists in every supported graphql-core (>=3.3.0, <3.4), so the
    # fallback branch is reachable only on an unsupported runtime.
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
        options: dict[str, Any] = {
            "context_value": context_value,
            "raw_variable_values": variable_values,
            "operation_name": operation_name,
        }
        if _EXECUTOR_SUPPORTS_HIDE_SUGGESTIONS:
            options["hide_suggestions"] = hide_suggestions
        try:
            executor = executor_class.build(schema, document, **options)
        except RecursionError:
            # Only variable coercion runs here, before any resolver: a bare
            # RecursionError is the client's over-deep value, answered like the
            # HTTP view. A resolver's own RecursionError is raised later, by
            # "source_factory", and stays an internal error.
            return ExecutionResult(
                data=None,
                errors=mark_client_errors(
                    [
                        GraphQLError(
                            "Variables are nested too deeply to be coerced.",
                            extensions={"code": "QUERY_TOO_DEEP"},
                        )
                    ]
                ),
            )
        if isinstance(executor, list):
            return ExecutionResult(data=None, errors=mark_client_errors(executor))
        result = source_factory(executor)

    result = await result if isawaitable(result) else result
    # Path-less errors come from before any resolver ran: client input.
    return (
        mark_request_errors(result) if isinstance(result, ExecutionResult) else result
    )


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
