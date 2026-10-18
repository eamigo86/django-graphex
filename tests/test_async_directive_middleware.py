"""Native async directive execution and synchronous HTTP refusal regressions."""

from __future__ import annotations

import asyncio
import gc
import inspect
import json
import warnings
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from django.test import Client, RequestFactory, override_settings
from django.urls import clear_url_caches, path
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    execute,
    parse,
)
from graphql.execution.middleware import MiddlewareManager

from django_graphex.directives import all_directives
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.views import GraphQLView

urlpatterns: list[Any] = []


def _schema(resolver: Any) -> GraphQLSchema:
    """Create a native GraphQL schema with the registered case directives.

    Args:
        resolver: Field resolver to exercise.

    Returns:
        A schema accepting the bundled directives.
    """
    return GraphQLSchema(
        query=GraphQLObjectType(
            "AsyncDirectiveQuery",
            {"value": GraphQLField(GraphQLString, resolve=resolver)},
        ),
        directives=list(all_directives),
    )


@pytest.mark.parametrize(
    ("directive", "expected"),
    [("uppercase", "HELLO"), ("lowercase", "hello")],
)
def test_native_async_execution_applies_directive_after_await(
    directive: str, expected: str
) -> None:
    """Transform the resolved string rather than stringifying its coroutine.

    Args:
        directive: Bundled case directive requested by the operation.
        expected: String expected after the directive runs.
    """
    started: list[str] = []

    async def resolve_value(_root: Any, _info: Any) -> str:
        """Return the field value once native async execution awaits it.

        Args:
            _root: GraphQL root value.
            _info: GraphQL field information.

        Returns:
            The mixed-case source string.
        """
        started.append("resolver")
        return "Hello"

    result = execute(
        _schema(resolve_value),
        parse(f"{{ value @{directive} }}"),
        middleware=[GraphQLDirectiveMiddleware()],
    )
    assert inspect.isawaitable(result)
    completed = asyncio.run(result)
    assert completed.errors is None
    assert completed.data == {"value": expected}
    assert started == ["resolver"]


@pytest.mark.parametrize("directive", ["uppercase", "lowercase"])
@pytest.mark.parametrize("manager", [False, True])
def test_sync_http_rejects_async_resolver_with_directive(
    directive: str, manager: bool
) -> None:
    """Keep the approved JSON 500 and close unstarted owned work.

    Args:
        directive: Bundled case directive requested by the HTTP operation.
        manager: Whether middleware is supplied as a native manager.
    """
    started: list[str] = []

    async def resolve_value(_root: Any, _info: Any) -> str:
        """Record whether forbidden HTTP async execution starts.

        Args:
            _root: GraphQL root value.
            _info: GraphQL field information.

        Returns:
            A value that synchronous HTTP must not obtain.
        """
        started.append("resolver")
        return "Hello"

    global urlpatterns
    entries: Any = [GraphQLDirectiveMiddleware()]
    if manager:
        entries = MiddlewareManager(*entries)
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=_schema(resolve_value)),
                middleware=entries,
            ),
        )
    ]
    try:
        with (
            override_settings(
                ROOT_URLCONF=__name__,
                DEBUG=False,
                DEBUG_PROPAGATE_EXCEPTIONS=False,
                DJANGO_GRAPHEX={"CACHE_ACTIVE": False},
            ),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always", RuntimeWarning)
            clear_url_caches()
            response = Client(raise_request_exception=False).post(
                "/graphql/",
                data=json.dumps({"query": f"{{ value @{directive} }}"}),
                content_type="application/json",
            )
            gc.collect()
            assert response.status_code == 500
            assert response["Content-Type"].startswith("application/json")
            assert response.json() == {
                "errors": [
                    {
                        "message": (
                            "Async execution is not supported by this HTTP view. "
                            "Use synchronous resolvers and middleware."
                        )
                    }
                ],
            }
            assert not [
                item for item in caught if issubclass(item.category, RuntimeWarning)
            ]
            assert started == []
    finally:
        clear_url_caches()


def test_sync_http_preserves_borrowed_future_with_directive() -> None:
    """Do not cancel an externally owned future while rejecting HTTP async work.

    The directive wrapper is owned by execution, but its input future is not.
    """
    loop = asyncio.new_event_loop()
    future: asyncio.Future[str] = loop.create_future()

    def resolve_value(_root: Any, _info: Any) -> asyncio.Future[str]:
        """Return the future owned by the caller.

        Args:
            _root: GraphQL root value.
            _info: GraphQL field information.

        Returns:
            The borrowed, pending future.
        """
        return future

    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=_schema(resolve_value)),
                middleware=[GraphQLDirectiveMiddleware()],
            ),
        )
    ]
    try:
        with override_settings(
            ROOT_URLCONF=__name__,
            DEBUG=False,
            DEBUG_PROPAGATE_EXCEPTIONS=False,
            DJANGO_GRAPHEX={"CACHE_ACTIVE": False},
        ):
            clear_url_caches()
            client = Client(raise_request_exception=False)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", RuntimeWarning)
                control = client.post(
                    "/graphql/",
                    data=json.dumps({"query": "{ value }"}),
                    content_type="application/json",
                )
                assert control.status_code == 500
                assert not future.done()
                response = client.post(
                    "/graphql/",
                    data=json.dumps({"query": "{ value @uppercase }"}),
                    content_type="application/json",
                )
                gc.collect()
                assert not [
                    item for item in caught if issubclass(item.category, RuntimeWarning)
                ]
            assert response.status_code == 500
            assert response.json() == {
                "errors": [
                    {
                        "message": (
                            "Async execution is not supported by this HTTP view. "
                            "Use synchronous resolvers and middleware."
                        )
                    }
                ]
            }
            assert not future.done()
            assert not future.cancelled()
    finally:
        clear_url_caches()
        loop.close()


def test_synchronous_directive_behavior_is_unchanged() -> None:
    """Keep the synchronous middleware path synchronous.

    A pair of directives still applies in query order to the original value.
    """

    def resolve_value(_root: Any, _info: Any) -> str:
        """Return a synchronous field value.

        Args:
            _root: GraphQL root value.
            _info: GraphQL field information.

        Returns:
            A mixed-case source string.
        """
        return "Hello"

    result = execute(
        _schema(resolve_value),
        parse("{ value @uppercase @lowercase }"),
        middleware=[GraphQLDirectiveMiddleware()],
    )
    assert not inspect.isawaitable(result)
    assert result.errors is None
    assert result.data == {"value": "hello"}


@pytest.mark.parametrize("manager", [False, True])
@pytest.mark.parametrize("borrowed_kind", ["future", "task"])
def test_http_outer_wrapper_does_not_leak_directive_coroutine(
    manager: bool, borrowed_kind: str
) -> None:
    """Reject hidden async work without creating an unowned inner coroutine.

    Args:
        manager: Whether middleware is supplied as a native manager.
        borrowed_kind: Caller-owned pending Future or Task.
    """
    loop = asyncio.new_event_loop()
    calls: list[str] = []
    retained: list[Any] = []

    async def source() -> str:
        """Record whether borrowed work was incorrectly started.

        Returns:
            The mixed-case source value.
        """
        calls.append("source-body")
        return "HeLLo"

    borrowed: Any = (
        loop.create_future()
        if borrowed_kind == "future"
        else loop.create_task(source())
    )

    def resolve_value(_root: Any, _info: Any) -> Any:
        """Return caller-owned work without transferring its ownership.

        Args:
            _root: GraphQL root value.
            _info: GraphQL field information.

        Returns:
            The pending borrowed awaitable.
        """
        calls.append("resolver")
        return borrowed

    def outer(next_: Callable[..., Any], parent: Any, info: Any, **kwargs: Any) -> Any:
        """Hide the directive result inside an unstarted outer coroutine.

        Args:
            next_: Inner middleware callback.
            parent: GraphQL root value.
            info: GraphQL field information.
            **kwargs: Resolver arguments.

        Returns:
            The unstarted outer coroutine.
        """
        calls.append("outer")
        value = next_(parent, info, **kwargs)
        retained.append(value)

        async def wrapped() -> Any:
            """Await the inner result only if native execution starts.

            Returns:
                The resolved field value.
            """
            calls.append("outer-body")
            return await value

        result = wrapped()
        retained.append(result)
        return result

    chain: Any = [GraphQLDirectiveMiddleware(), outer]
    if manager:
        chain = MiddlewareManager(*chain)
    view = GraphQLView.as_view(
        schema=SimpleNamespace(graphql_schema=_schema(resolve_value)),
        middleware=chain,
    )
    try:
        with (
            override_settings(DEBUG=False, DJANGO_GRAPHEX={"CACHE_ACTIVE": False}),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always", RuntimeWarning)
            response = view(
                RequestFactory().post(
                    "/graphql/",
                    data=json.dumps({"query": "{ value @uppercase }"}),
                    content_type="application/json",
                )
            )
            assert response.status_code == 500
            assert response["Content-Type"].startswith("application/json")
            assert set(json.loads(response.content)) == {"errors"}
            assert calls == ["outer", "resolver"]
            assert not borrowed.done() and not borrowed.cancelled()
            retained.clear()
            gc.collect()
            assert not [
                item for item in caught if issubclass(item.category, RuntimeWarning)
            ]
    finally:
        for item in retained:
            if inspect.iscoroutine(item):
                item.close()
        borrowed.cancel()
        if borrowed_kind == "task":
            loop.run_until_complete(asyncio.gather(borrowed, return_exceptions=True))
        loop.close()
