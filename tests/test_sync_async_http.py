"""Synchronous HTTP views reject owned asynchronous execution safely."""

from __future__ import annotations

import asyncio
import gc
import inspect
import json
import warnings
from types import CoroutineType, SimpleNamespace
from typing import Any

import pytest
from django.test import Client, override_settings
from django.urls import clear_url_caches, path
from graphql import (
    ExecutionResult,
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    execute,
    parse,
)
from graphql import execution as graphql_execution
from graphql.execution.middleware import MiddlewareManager

from django_graphex.permissions import AllowAny
from django_graphex.views import AuthenticatedGraphQLView, BaseGraphQLView, GraphQLView

urlpatterns: list[Any] = []
_MESSAGE = (
    "Async execution is not supported by this HTTP view. "
    "Use synchronous resolvers and middleware."
)


def _post(pathname: str, query: str) -> Any:
    """Submit one real JSON request with an independent cookie-free client.

    Args:
        pathname: Configured view URL.
        query: GraphQL document to execute.

    Returns:
        The Django HTTP response.
    """
    return Client(raise_request_exception=False).post(
        pathname, data=json.dumps({"query": query}), content_type="application/json"
    )


def _owned_coroutines(before: dict[int, Any]) -> list[Any]:
    """Capture new test and graphql-core coroutines for response-time proof.

    Args:
        before: Live coroutine references present before the request. Holding
            them prevents identity reuse while the request runs.

    Returns:
        Newly created coroutines from this test or graphql-core execution.
    """
    return [
        value
        for value in gc.get_objects()
        if type(value) is CoroutineType
        and id(value) not in before
        and (
            "test_sync_async_http.py" in value.cr_code.co_filename
            or "/graphql/execution/" in value.cr_code.co_filename
        )
    ]


@pytest.mark.parametrize("form", ["list", "standard_manager"])
@pytest.mark.parametrize("resolve_value", [False, 0, ""])
def test_falsey_object_middleware_is_ignored_like_native(
    form: str, resolve_value: Any
) -> None:
    """Keep native ignored-entry behavior for falsey resolve attributes.

    Args:
        form: Native middleware container used by the view.
        resolve_value: Falsey object attribute that native execution ignores.
    """

    class DisabledMiddleware:
        """Expose a falsey resolver attribute without a callback."""

        resolve = resolve_value

    entries: list[Any] = [DisabledMiddleware()]
    middleware: Any = entries if form == "list" else MiddlewareManager(*entries)
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "IgnoredMiddlewareQuery",
            {"value": GraphQLField(GraphQLString, resolve=lambda *_: "healthy")},
        )
    )
    native = execute(schema, parse("{ value }"), middleware=middleware)
    assert native.data == {"value": "healthy"} and not native.errors

    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=schema), middleware=middleware
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
            response = _post("/graphql/", "{ value }")
            assert response.status_code == 200
            assert response.json() == {"data": {"value": "healthy"}}
    finally:
        clear_url_caches()


@pytest.mark.parametrize("form", ["list", "standard_manager"])
def test_callable_object_middleware_remains_active(form: str) -> None:
    """Keep a valid object callback active while ignoring falsey entries.

    Args:
        form: Native middleware container used by the view.
    """

    class ActiveMiddleware:
        """Append a marker to a synchronous resolver value."""

        def resolve(self, next_: Any, root: Any, info: Any, **kwargs: Any) -> Any:
            """Delegate to the next synchronous resolver.

            Args:
                next_: Next resolver or middleware callable.
                root: GraphQL root value.
                info: GraphQL field information.
                **kwargs: GraphQL field arguments.

            Returns:
                The resolver value with an active-middleware marker.
            """
            return next_(root, info, **kwargs) + "-active"

    entries: list[Any] = [ActiveMiddleware()]
    middleware: Any = entries if form == "list" else MiddlewareManager(*entries)
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "ActiveMiddlewareQuery",
            {"value": GraphQLField(GraphQLString, resolve=lambda *_: "healthy")},
        )
    )
    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=schema), middleware=middleware
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
            response = _post("/graphql/", "{ value }")
            assert response.status_code == 200
            assert response.json() == {"data": {"value": "healthy-active"}}
    finally:
        clear_url_caches()


@pytest.mark.parametrize(
    "view_class", [BaseGraphQLView, GraphQLView, AuthenticatedGraphQLView]
)
@pytest.mark.parametrize("cache_active", [False, True])
def test_async_resolver_returns_json_500_and_closes_owned_coroutines(
    view_class: type[Any], cache_active: bool
) -> None:
    """Reject async resolver work without running it or leaking coroutines.

    Args:
        view_class: The synchronous built-in HTTP view under test.
        cache_active: Whether enhanced response caching is configured.
    """
    body_started: list[str] = []

    async def async_value(*_args: Any) -> str:
        """Record execution if this forbidden coroutine ever starts.

        Args:
            *_args: GraphQL resolver arguments.

        Returns:
            A value that synchronous HTTP must never obtain.
        """
        body_started.append("async resolver")
        return "unexpected"

    def sync_value(*_args: Any) -> str:
        """Return a known healthy synchronous value.

        Args:
            *_args: GraphQL resolver arguments.

        Returns:
            A healthy greeting.
        """
        return "healthy"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "SyncAsyncQuery",
            {
                "asyncValue": GraphQLField(GraphQLString, resolve=async_value),
                "syncValue": GraphQLField(GraphQLString, resolve=sync_value),
            },
        )
    )
    global urlpatterns
    view_options: dict[str, Any] = {"schema": SimpleNamespace(graphql_schema=schema)}
    if view_class is AuthenticatedGraphQLView:
        view_options["permission_classes"] = (AllowAny,)
    urlpatterns = [path("graphql/", view_class.as_view(**view_options))]
    captured: list[Any] = []
    try:
        with override_settings(
            ROOT_URLCONF=__name__,
            DEBUG=False,
            DEBUG_PROPAGATE_EXCEPTIONS=False,
            DJANGO_GRAPHEX={"CACHE_ACTIVE": cache_active, "CLEAN_RESPONSE": False},
        ):
            clear_url_caches()
            before = {
                id(value): value
                for value in gc.get_objects()
                if type(value) is CoroutineType
            }
            with warnings.catch_warnings(record=True) as warning_records:
                warnings.simplefilter("always", RuntimeWarning)
                response = _post("/graphql/", "{ asyncValue }")
                captured = _owned_coroutines(before)
                assert response.status_code == 500
                assert response["Content-Type"].startswith("application/json")
                assert response.json() == {"errors": [{"message": _MESSAGE}]}
                assert body_started == []
                assert captured
                assert all(
                    inspect.getcoroutinestate(value) == inspect.CORO_CLOSED
                    for value in captured
                )
                assert not [
                    item
                    for item in warning_records
                    if issubclass(item.category, RuntimeWarning)
                ]

            healthy = _post("/graphql/", "{ syncValue }")
            assert healthy.status_code == 200
            assert healthy.json()["data"] == {"syncValue": "healthy"}
    finally:
        for value in captured:
            if inspect.getcoroutinestate(value) == inspect.CORO_CREATED:
                value.close()
        clear_url_caches()


@pytest.mark.parametrize(
    "chain_kind",
    [
        "list-function",
        "list-object",
        "list-ignored",
        "manager-function",
        "manager-object",
    ],
)
@pytest.mark.parametrize("layers", [1, 2])
def test_sync_middleware_closes_nested_owned_resolver_coroutines(
    chain_kind: str, layers: int
) -> None:
    """Close every new coroutine hidden by synchronous middleware wrappers.

    Args:
        chain_kind: Native container and middleware entry shape.
        layers: Number of synchronous middleware wrappers.
    """
    created: list[Any] = []
    bodies: list[str] = []

    async def resolver(*_args: Any) -> str:
        """Record forbidden resolver execution.

        Args:
            *_args: GraphQL resolver arguments.

        Returns:
            A value that this synchronous view must not obtain.
        """
        bodies.append("resolver")
        return "unexpected"

    def middleware(next_: Any, root: Any, info: Any, **kwargs: Any) -> Any:
        """Wrap the next coroutine without starting it.

        Args:
            next_: Next callable in the middleware chain.
            root: GraphQL root value.
            info: GraphQL field information.
            **kwargs: GraphQL field arguments.

        Returns:
            A new coroutine awaiting the next callable's result.
        """
        inner = next_(root, info, **kwargs)
        created.append(inner)

        async def decorate() -> Any:
            """Record forbidden middleware execution.

            Returns:
                The next callable's eventual value.
            """
            bodies.append("middleware")
            return await inner

        outer = decorate()
        created.append(outer)
        return outer

    class ObjectMiddleware:
        """Expose the same middleware callback through an object entry."""

        def resolve(self, next_: Any, root: Any, info: Any, **kwargs: Any) -> Any:
            """Delegate to the function middleware without changing its result.

            Args:
                next_: Next resolver or middleware callable.
                root: GraphQL root value.
                info: GraphQL field information.
                **kwargs: GraphQL field arguments.

            Returns:
                The unmodified middleware result.
            """
            return middleware(next_, root, info, **kwargs)

    entry = ObjectMiddleware() if chain_kind.endswith("object") else middleware
    middleware_chain: Any = [entry] * layers
    if chain_kind == "list-ignored":
        middleware_chain.insert(0, object())
    if chain_kind.startswith("manager"):
        middleware_chain = MiddlewareManager(*middleware_chain)
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "NestedAsyncQuery",
            {"value": GraphQLField(GraphQLString, resolve=resolver)},
        )
    )
    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=schema),
                middleware=middleware_chain,
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
            response = _post("/graphql/", "{ value }")
            assert response.status_code == 500
            assert response.json() == {"errors": [{"message": _MESSAGE}]}
            assert bodies == []
            assert len(created) == 2 * layers
            assert all(
                inspect.getcoroutinestate(value) == inspect.CORO_CLOSED
                for value in created
            )
    finally:
        for value in created:
            if inspect.getcoroutinestate(value) == inspect.CORO_CREATED:
                value.close()
        clear_url_caches()


@pytest.mark.parametrize("prestarted", [False, True])
def test_sync_middleware_keeps_borrowed_coroutine_open(prestarted: bool) -> None:
    """Never close unrelated coroutine work retained by a resolver.

    Args:
        prestarted: Suspend the unrelated coroutine before the HTTP request.
    """
    bodies: list[str] = []

    async def borrowed() -> str:
        """Suspend without returning a GraphQL result.

        Returns:
            A value not obtained during synchronous HTTP execution.
        """
        bodies.append("borrowed")
        await asyncio.sleep(0)
        return "unused"

    value = borrowed()
    if prestarted:
        value.send(None)

    def resolver(*_args: Any) -> Any:
        """Return pre-existing coroutine work.

        Args:
            *_args: GraphQL resolver arguments.

        Returns:
            The unrelated coroutine.
        """
        return value

    def middleware(next_: Any, root: Any, info: Any, **kwargs: Any) -> Any:
        """Wrap a borrowed next value without claiming ownership.

        Args:
            next_: Next callable in the middleware chain.
            root: GraphQL root value.
            info: GraphQL field information.
            **kwargs: GraphQL field arguments.

        Returns:
            A new wrapper coroutine.
        """
        inner = next_(root, info, **kwargs)

        async def decorate() -> Any:
            """Await the borrowed value only if async execution occurs.

            Returns:
                The borrowed value's eventual result.
            """
            return await inner

        return decorate()

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "BorrowedAsyncQuery",
            {"value": GraphQLField(GraphQLString, resolve=resolver)},
        )
    )
    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=schema),
                middleware=[middleware],
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
            response = _post("/graphql/", "{ value }")
            assert response.status_code == 500
            assert response.json() == {"errors": [{"message": _MESSAGE}]}
            expected = inspect.CORO_SUSPENDED if prestarted else inspect.CORO_CREATED
            assert inspect.getcoroutinestate(value) == expected
            assert bodies == (["borrowed"] if prestarted else [])
    finally:
        value.close()
        clear_url_caches()


@pytest.mark.parametrize(
    "view_class", [BaseGraphQLView, GraphQLView, AuthenticatedGraphQLView]
)
def test_async_middleware_is_rejected_without_running_its_body(
    view_class: type[Any],
) -> None:
    """Reject middleware coroutines while keeping public GraphQL errors public.

    Args:
        view_class: The synchronous built-in HTTP view under test.

    Raises:
        GraphQLError: Raised by the control resolver to prove normal execution still works.
    """
    body_started: list[str] = []

    async def async_middleware(next_: Any, root: Any, info: Any, **kwargs: Any) -> Any:
        """Expose an async middleware body that must remain unstarted.

        Args:
            next_: Next resolver in the middleware chain.
            root: Resolver root value.
            info: GraphQL resolve information.
            **kwargs: GraphQL field arguments.

        Returns:
            A value that synchronous HTTP must never obtain.
        """
        body_started.append("middleware")
        return next_(root, info, **kwargs)

    def public_error(*_args: Any) -> str:
        """Raise a deliberately public GraphQL error.

        Args:
            *_args: GraphQL resolver arguments.

        Returns:
            Never returns.

        Raises:
            GraphQLError: Always, for the public-error control.
        """
        raise GraphQLError("public control")

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "MiddlewareQuery",
            {"value": GraphQLField(GraphQLString, resolve=public_error)},
        )
    )
    global urlpatterns
    view_options: dict[str, Any] = {
        "schema": SimpleNamespace(graphql_schema=schema),
        "middleware": [async_middleware],
    }
    if view_class is AuthenticatedGraphQLView:
        view_options["permission_classes"] = (AllowAny,)
    urlpatterns = [
        path(
            "graphql/",
            view_class.as_view(**view_options),
        )
    ]
    captured: list[Any] = []
    try:
        with override_settings(
            ROOT_URLCONF=__name__,
            DEBUG=False,
            DEBUG_PROPAGATE_EXCEPTIONS=False,
            DJANGO_GRAPHEX={"CACHE_ACTIVE": False},
        ):
            clear_url_caches()
            before = {
                id(value): value
                for value in gc.get_objects()
                if type(value) is CoroutineType
            }
            response = _post("/graphql/", "{ value }")
            captured = _owned_coroutines(before)
            assert response.status_code == 500
            assert response.json() == {"errors": [{"message": _MESSAGE}]}
            assert body_started == []
            assert captured
            assert all(
                inspect.getcoroutinestate(value) == inspect.CORO_CLOSED
                for value in captured
            )
    finally:
        for value in captured:
            if inspect.getcoroutinestate(value) == inspect.CORO_CREATED:
                value.close()
        clear_url_caches()


def test_custom_executor_owned_coroutine_is_closed() -> None:
    """Reject a newly created coroutine from a configured executor.

    The backend result is request-owned and must remain unstarted.
    """
    body_started: list[str] = []

    class AsyncExecutor(graphql_execution.Executor):
        """Return a new unstarted coroutine from the execution backend."""

        def execute_operation(self, *args: Any, **kwargs: Any) -> Any:
            """Create an async result without entering its body.

            Args:
                *args: Native operation arguments.
                **kwargs: Native operation options.

            Returns:
                A new awaitable execution result.
            """

            async def result() -> ExecutionResult:
                """Record forbidden execution and produce a dummy result.

                Returns:
                    An execution result that synchronous HTTP must not obtain.
                """
                body_started.append("custom executor")
                return ExecutionResult(data={"value": "unexpected"})

            return result()

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "ExecutorQuery",
            {"value": GraphQLField(GraphQLString, resolve=lambda *_: "ok")},
        )
    )
    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=schema),
                executor_class=AsyncExecutor,
            ),
        )
    ]
    captured: list[Any] = []
    try:
        with override_settings(
            ROOT_URLCONF=__name__,
            DEBUG=False,
            DEBUG_PROPAGATE_EXCEPTIONS=False,
            DJANGO_GRAPHEX={"CACHE_ACTIVE": False},
        ):
            clear_url_caches()
            before = {
                id(value): value
                for value in gc.get_objects()
                if type(value) is CoroutineType
            }
            response = _post("/graphql/", "{ value }")
            captured = _owned_coroutines(before)
            assert response.status_code == 500
            assert response.json() == {"errors": [{"message": _MESSAGE}]}
            assert body_started == []
            assert captured
            assert all(
                inspect.getcoroutinestate(value) == inspect.CORO_CLOSED
                for value in captured
            )
    finally:
        for value in captured:
            if inspect.getcoroutinestate(value) == inspect.CORO_CREATED:
                value.close()
        clear_url_caches()


def test_executor_exception_after_async_value_closes_owned_coroutine() -> None:
    """Close request-owned async work even if an executor then fails.

    This checks the exception path before a top-level awaitable can be returned.

    Raises:
        RuntimeError: Raised by the patched executor after an async value was produced.
    """
    body_started: list[str] = []
    created: list[Any] = []

    class FailingExecutor(graphql_execution.Executor):
        """Create async work and then raise from synchronous execution."""

        def execute_operation(self, *args: Any, **kwargs: Any) -> Any:
            """Raise after graphql-core's predicate observes an owned coroutine.

            Args:
                *args: Native operation arguments.
                **kwargs: Native operation options.

            Returns:
                Never returns.

            Raises:
                RuntimeError: Always after the owned coroutine is registered.
            """

            async def value() -> str:
                """Record forbidden execution if the coroutine starts.

                Returns:
                    A value that synchronous HTTP must never obtain.
                """
                body_started.append("executor value")
                return "unexpected"

            coroutine = value()
            created.append(coroutine)
            self.is_awaitable(coroutine)
            raise RuntimeError("backend failed after async value")

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "FailingExecutorQuery",
            {"value": GraphQLField(GraphQLString, resolve=lambda *_: "ok")},
        )
    )
    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(
                schema=SimpleNamespace(graphql_schema=schema),
                executor_class=FailingExecutor,
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
            with warnings.catch_warnings(record=True) as warning_records:
                warnings.simplefilter("always", RuntimeWarning)
                response = _post("/graphql/", "{ value }")
                assert response.status_code == 500
                assert response.json() == {"errors": [{"message": _MESSAGE}]}
                assert body_started == []
                assert len(created) == 1
                assert inspect.getcoroutinestate(created[0]) == inspect.CORO_CLOSED
                assert not [
                    item
                    for item in warning_records
                    if issubclass(item.category, RuntimeWarning)
                ]
    finally:
        for value in created:
            if inspect.getcoroutinestate(value) == inspect.CORO_CREATED:
                value.close()
        clear_url_caches()


@pytest.mark.django_db
@pytest.mark.parametrize("atomic", [False, True])
def test_async_mutation_is_rejected_with_transaction_policy(atomic: bool) -> None:
    """Reject unstarted mutation coroutines in both transaction modes.

    Args:
        atomic: Whether the mutation runs inside transaction.atomic.
    """
    body_started: list[str] = []

    async def mutate(*_args: Any) -> str:
        """Record any forbidden entry into the async mutation body.

        Args:
            *_args: GraphQL resolver arguments.

        Returns:
            A value that synchronous HTTP must never obtain.
        """
        body_started.append("mutation")
        return "unexpected"

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "MutationControlQuery",
            {"ok": GraphQLField(GraphQLString, resolve=lambda *_: "ok")},
        ),
        mutation=GraphQLObjectType(
            "AsyncMutation",
            {"value": GraphQLField(GraphQLString, resolve=mutate)},
        ),
    )
    global urlpatterns
    urlpatterns = [
        path(
            "graphql/",
            GraphQLView.as_view(schema=SimpleNamespace(graphql_schema=schema)),
        )
    ]
    captured: list[Any] = []
    try:
        with override_settings(
            ROOT_URLCONF=__name__,
            DEBUG=False,
            DEBUG_PROPAGATE_EXCEPTIONS=False,
            DJANGO_GRAPHEX={"ATOMIC_MUTATIONS": atomic, "CACHE_ACTIVE": False},
        ):
            clear_url_caches()
            before = {
                id(value): value
                for value in gc.get_objects()
                if type(value) is CoroutineType
            }
            with warnings.catch_warnings(record=True) as warning_records:
                warnings.simplefilter("always", RuntimeWarning)
                response = _post("/graphql/", "mutation { value }")
                captured = _owned_coroutines(before)
                assert response.status_code == 500
                assert response.json() == {"errors": [{"message": _MESSAGE}]}
                assert body_started == []
                assert captured
                assert all(
                    inspect.getcoroutinestate(value) == inspect.CORO_CLOSED
                    for value in captured
                )
                assert not [
                    item
                    for item in warning_records
                    if issubclass(item.category, RuntimeWarning)
                ]
    finally:
        for value in captured:
            if inspect.getcoroutinestate(value) == inspect.CORO_CREATED:
                value.close()
        clear_url_caches()
