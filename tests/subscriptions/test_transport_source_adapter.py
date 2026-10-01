"""Cross-version source construction for the built-in subscription transports."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from graphql import (
    ExecutionResult,
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    create_source_event_stream,
    parse,
)

from django_graphex.subscriptions.transports import _start_source_event_stream


async def test_sync_subscribe_resolver_starts_source_on_both_core_versions() -> None:
    """Use an immediately returned source without assuming it is awaitable.

    The legacy API and the Executor-based API must expose the same raw event.
    """
    context = object()
    received: list[Any] = []

    async def events() -> AsyncIterator[dict[str, str]]:
        """Yield one raw subscription event for the adapter.

        Yields:
            The raw payload emitted by the subscription resolver.
        """
        yield {"ping": "ready"}

    def subscribe(_root: Any, info: Any) -> AsyncIterator[dict[str, str]]:
        """Return the event stream synchronously and record its context.

        Args:
            _root: Root value supplied by GraphQL execution.
            info: GraphQL resolver information carrying the context.

        Returns:
            The asynchronous raw event stream.
        """
        received.append(info.context)
        return events()

    schema = GraphQLSchema(
        query=GraphQLObjectType("Query", {"noop": GraphQLField(GraphQLString)}),
        subscription=GraphQLObjectType(
            "Subscription", {"ping": GraphQLField(GraphQLString, subscribe=subscribe)}
        ),
    )
    source = await _start_source_event_stream(
        schema,
        parse("subscription { ping }"),
        context_value=context,
        variable_values=None,
        operation_name=None,
        source_factory=create_source_event_stream,
    )

    assert not isinstance(source, ExecutionResult)
    assert received == [context]
    assert await anext(source.__aiter__()) == {"ping": "ready"}


@pytest.mark.parametrize("with_errors", [False, True])
async def test_executor_build_forwards_inputs_or_returns_coercion_errors(
    monkeypatch: pytest.MonkeyPatch, *, with_errors: bool
) -> None:
    """Cover executor construction and its error-list result in the root suite.

    Args:
        monkeypatch: Fixture used to expose the new API on the 3.2 test runtime.
        with_errors: Whether construction returns variable-coercion errors.
    """
    from django_graphex.subscriptions.transports import graphql_execution

    schema: Any = object()
    document: Any = object()
    context = object()
    variables = {"value": "ready"}
    errors = [GraphQLError("invalid variable")]
    built = object()
    source_calls: list[Any] = []

    class FakeExecutor:
        """Record the request-scoped arguments used to build an executor."""

        @staticmethod
        def build(actual_schema: Any, actual_document: Any, **kwargs: Any) -> Any:
            """Return either a usable executor or coercion errors.

            Args:
                actual_schema: Schema supplied by the transport.
                actual_document: Parsed document supplied by the transport.
                **kwargs: Execution arguments supplied by the transport.

            Returns:
                The built executor marker or a list of errors.
            """
            assert actual_schema is schema
            assert actual_document is document
            assert kwargs == {
                "context_value": context,
                "raw_variable_values": variables,
                "operation_name": "Chosen",
            }
            return errors if with_errors else built

    async def events() -> AsyncIterator[str]:
        """Yield a raw source event.

        Yields:
            The event payload.
        """
        yield "ready"

    def source_factory(executor: Any) -> AsyncIterator[str]:
        """Return a source immediately for the built executor.

        Args:
            executor: Executor returned by the builder.

        Returns:
            The raw event stream.
        """
        source_calls.append(executor)
        return events()

    monkeypatch.setattr(graphql_execution, "Executor", FakeExecutor, raising=False)
    result = await _start_source_event_stream(
        schema,
        document,
        context_value=context,
        variable_values=variables,
        operation_name="Chosen",
        source_factory=source_factory,
    )
    if with_errors:
        assert isinstance(result, ExecutionResult)
        assert result.errors == errors
        assert source_calls == []
    else:
        assert not isinstance(result, ExecutionResult)
        assert source_calls == [built]
        assert await anext(result.__aiter__()) == "ready"
