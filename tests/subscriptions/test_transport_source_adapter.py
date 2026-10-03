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


def test_legacy_validation_omits_native_suggestion_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass only legacy validation options when the native flag is unavailable.

    Args:
        monkeypatch: Fixture replacing the capability and validation callable.
    """
    from django_graphex.subscriptions import transports

    schema = object()
    document = object()
    rules = object()

    def legacy_validate(
        actual_schema: Any,
        actual_document: Any,
        actual_rules: Any,
        *,
        max_errors: int,
    ) -> list[GraphQLError]:
        """Reject unsupported keywords through the legacy signature.

        Args:
            actual_schema: Schema supplied by the transport.
            actual_document: Document supplied by the transport.
            actual_rules: Validation rules supplied by the transport.
            max_errors: Error limit supplied by the transport.

        Returns:
            No validation errors for the contract probe.
        """
        assert (actual_schema, actual_document, actual_rules, max_errors) == (
            schema,
            document,
            rules,
            9,
        )
        return []

    monkeypatch.setattr(transports, "_VALIDATE_SUPPORTS_HIDE_SUGGESTIONS", False)
    monkeypatch.setattr(transports, "validate", legacy_validate)
    assert (
        transports._validate_subscription_document(
            schema, document, rules, max_errors=9, hide_suggestions=True
        )
        == []
    )


@pytest.mark.parametrize("with_errors", [False, True])
async def test_legacy_source_factory_receives_original_request_contract(
    monkeypatch: pytest.MonkeyPatch, *, with_errors: bool
) -> None:
    """Keep schema/document source construction and startup errors on 3.2.

    Args:
        monkeypatch: Fixture selecting the legacy GraphQL execution API.
        with_errors: Whether the source factory returns startup errors.
    """
    from django_graphex.subscriptions import transports

    schema = object()
    document = object()
    context = object()
    variables = {"value": "ready"}
    errors = [GraphQLError("source unavailable")]
    calls: list[tuple[Any, Any, Any, Any, Any]] = []

    async def events() -> AsyncIterator[str]:
        """Yield one raw event from a synchronously returned source.

        Yields:
            The event payload.
        """
        yield "ready"

    def legacy_source_factory(
        actual_schema: Any,
        actual_document: Any,
        *,
        context_value: Any,
        variable_values: Any,
        operation_name: Any,
    ) -> Any:
        """Require the original source-factory argument shape.

        Args:
            actual_schema: Request schema.
            actual_document: Parsed subscription document.
            context_value: Request-specific transport context.
            variable_values: Client variables.
            operation_name: Selected subscription operation.

        Returns:
            A stream or a startup error result.
        """
        calls.append(
            (
                actual_schema,
                actual_document,
                context_value,
                variable_values,
                operation_name,
            )
        )
        return ExecutionResult(errors=errors) if with_errors else events()

    monkeypatch.setattr(transports.graphql_execution, "Executor", None, raising=False)
    result = await _start_source_event_stream(
        schema,
        document,
        context_value=context,
        variable_values=variables,
        operation_name="Chosen",
        source_factory=legacy_source_factory,
        hide_suggestions=True,
    )
    assert calls == [(schema, document, context, variables, "Chosen")]
    if with_errors:
        assert isinstance(result, ExecutionResult)
        assert result.errors == errors
    else:
        assert not isinstance(result, ExecutionResult)
        assert await anext(result.__aiter__()) == "ready"


async def test_executor_without_suggestion_option_starts_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not send an unsupported hint flag to an Executor builder.

    Args:
        monkeypatch: Fixture selecting the unsupported-capability branch.
    """
    from django_graphex.subscriptions import transports

    schema = object()
    document = object()
    context = object()
    variables = {"value": "ready"}
    built = object()
    received: list[Any] = []

    class LegacyExecutor:
        """Expose a builder without a native suggestion option."""

        @staticmethod
        def build(
            actual_schema: Any,
            actual_document: Any,
            *,
            context_value: Any,
            raw_variable_values: Any,
            operation_name: Any,
        ) -> Any:
            """Require only supported options and return an executor marker.

            Args:
                actual_schema: Request schema.
                actual_document: Parsed subscription document.
                context_value: Request-specific transport context.
                raw_variable_values: Client variables.
                operation_name: Selected subscription operation.

            Returns:
                The built executor marker.
            """
            assert (actual_schema, actual_document) == (schema, document)
            assert (context_value, raw_variable_values, operation_name) == (
                context,
                variables,
                "Chosen",
            )
            return built

    def source_factory(executor: Any) -> Any:
        """Receive the built executor without rebuilding the source.

        Args:
            executor: Built executor marker.

        Returns:
            The same marker for assertion.
        """
        received.append(executor)
        return executor

    monkeypatch.setattr(
        transports.graphql_execution, "Executor", LegacyExecutor, raising=False
    )
    monkeypatch.setattr(transports, "_EXECUTOR_SUPPORTS_HIDE_SUGGESTIONS", False)
    result = await _start_source_event_stream(
        schema,
        document,
        context_value=context,
        variable_values=variables,
        operation_name="Chosen",
        source_factory=source_factory,
        hide_suggestions=True,
    )
    assert result is built
    assert received == [built]


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
    from django_graphex.subscriptions import transports
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
            expected_options = {
                "context_value": context,
                "raw_variable_values": variables,
                "operation_name": "Chosen",
            }
            if transports._EXECUTOR_SUPPORTS_HIDE_SUGGESTIONS:
                expected_options["hide_suggestions"] = False
            assert kwargs == expected_options
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


async def test_native_executor_builder_receives_private_suggestion_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward private mode to native variable coercion before source startup.

    Args:
        monkeypatch: Fixture used to exercise the native capability on 3.2.
    """
    from django_graphex.subscriptions import transports

    built = object()

    class FakeExecutor:
        """Record the options passed to the native executor constructor."""

        @staticmethod
        def build(_schema: Any, _document: Any, **kwargs: Any) -> Any:
            """Check the private flag without changing executor behavior.

            Args:
                _schema: Schema supplied by the transport.
                _document: Document supplied by the transport.
                **kwargs: Request-scoped executor options.

            Returns:
                A marker for the built executor.
            """
            assert kwargs["hide_suggestions"] is True
            return built

    def source_factory(executor: Any) -> Any:
        """Return the constructed executor as the source marker.

        Args:
            executor: Built executor passed to the source factory.

        Returns:
            The same marker for assertion.
        """
        return executor

    monkeypatch.setattr(
        transports.graphql_execution, "Executor", FakeExecutor, raising=False
    )
    monkeypatch.setattr(
        transports, "_EXECUTOR_SUPPORTS_HIDE_SUGGESTIONS", True, raising=False
    )
    result = await _start_source_event_stream(
        object(),
        object(),
        context_value=None,
        variable_values=None,
        operation_name=None,
        source_factory=source_factory,
        hide_suggestions=True,
    )
    assert result is built


def test_native_document_validation_receives_private_suggestion_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward private mode to native document validation when supported.

    Args:
        monkeypatch: Fixture used to expose the native capability on 3.2.
    """
    from django_graphex.subscriptions import transports

    schema = object()
    document = object()
    rules = object()

    def fake_validate(
        actual_schema: Any, actual_document: Any, *args: Any, **kwargs: Any
    ) -> list[Any]:
        """Assert the native validation options.

        Args:
            actual_schema: Schema supplied by the transport.
            actual_document: Document supplied by the transport.
            *args: Validation rules supplied by the transport.
            **kwargs: Native validation options.

        Returns:
            An empty error collection.
        """
        assert actual_schema is schema
        assert actual_document is document
        assert args == (rules,)
        assert kwargs == {"max_errors": 12, "hide_suggestions": True}
        return []

    monkeypatch.setattr(
        transports, "_VALIDATE_SUPPORTS_HIDE_SUGGESTIONS", True, raising=False
    )
    monkeypatch.setattr(transports, "validate", fake_validate, raising=False)
    result = transports._validate_subscription_document(
        schema, document, rules, max_errors=12, hide_suggestions=True
    )
    assert result == []
