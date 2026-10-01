"""Preserve synchronous Django queryset completion in GraphQL HTTP views."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory, override_settings
from graphql import (
    ExecutionResult,
    GraphQLField,
    GraphQLID,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)
from graphql import execute as graphql_execute
from graphql import execution as graphql_execution

from django_graphex.views import MUTATION_ERRORS_FLAG, BaseGraphQLView


def _user_type() -> GraphQLObjectType:
    """Build the list element used by the HTTP queryset regressions.

    Returns:
        A GraphQL type exposing the user's database identifier.
    """
    return GraphQLObjectType("ThreadUser", {"id": GraphQLField(GraphQLID)})


def _request(schema: GraphQLSchema, query: str) -> tuple[Any, dict[str, Any]]:
    """Execute a real HTTP request against a graphql-core schema.

    Args:
        schema: The executable query and mutation roots.
        query: The GraphQL operation text.

    Returns:
        The response and decoded JSON body.
    """
    view = BaseGraphQLView.as_view(schema=SimpleNamespace(graphql_schema=schema))
    request = RequestFactory().post(
        "/graphql/", json.dumps({"query": query}), content_type="application/json"
    )
    response = view(request)
    return response, json.loads(response.content)


def _tracked_users(events: list[tuple[int, bool]], user_id: int) -> Any:
    """Return a lazy queryset recording its evaluation thread and transaction.

    Args:
        events: Collector for the evaluation thread and atomic-block state.
        user_id: Primary key selected by the lazy queryset.

    Returns:
        An unevaluated Django queryset.
    """
    queryset = User.objects.filter(pk=user_id)
    fetch_all = queryset._fetch_all

    def record_fetch() -> None:
        """Record the actual database-evaluation boundary."""
        events.append((threading.get_ident(), connection.in_atomic_block))
        fetch_all()

    queryset._fetch_all = record_fetch
    return queryset


@pytest.mark.django_db(transaction=True)
def test_queryset_http_query_evaluates_on_request_thread() -> None:
    """A dual-iterator queryset remains a synchronous HTTP list result.

    The database evaluation must stay on the request's thread.
    """
    user = User.objects.create(username="query_thread")
    events: list[tuple[int, bool]] = []
    user_type = _user_type()

    def resolve_users(_root: Any, _info: Any) -> Any:
        """Return the unevaluated queryset for the HTTP list field.

        Args:
            _root: Unused root value.
            _info: Unused resolver context.

        Returns:
            The tracked queryset.
        """
        return _tracked_users(events, user.pk)

    query = GraphQLObjectType(
        "Query", {"users": GraphQLField(GraphQLList(user_type), resolve=resolve_users)}
    )
    response, payload = _request(GraphQLSchema(query=query), "{ users { id } }")

    assert response.status_code == 200
    assert payload == {"data": {"users": [{"id": str(user.pk)}]}}
    assert events == [(threading.get_ident(), False)]


@pytest.mark.django_db(transaction=True)
@override_settings(DJANGO_GRAPHEX={"ATOMIC_MUTATIONS": True})
def test_queryset_mutation_evaluates_inside_atomic_request_thread() -> None:
    """A queryset response is completed before a flagged mutation rolls back.

    Evaluation must remain in the request's atomic transaction and thread.
    """
    events: list[tuple[int, bool]] = []
    user_type = _user_type()

    def resolve_rollback(_root: Any, info: Any) -> Any:
        """Create a row, then request rollback after its list is completed.

        Args:
            _root: Unused root value.
            info: Resolver context carrying the request rollback flag.

        Returns:
            The tracked queryset over the newly created row.
        """
        user = User.objects.create(username="rolled_back_user")
        setattr(info.context, MUTATION_ERRORS_FLAG, True)
        return _tracked_users(events, user.pk)

    query = GraphQLObjectType("Query", {"ping": GraphQLField(GraphQLString)})
    mutation = GraphQLObjectType(
        "Mutation",
        {
            "rollbackUsers": GraphQLField(
                GraphQLList(user_type), resolve=resolve_rollback
            )
        },
    )
    response, payload = _request(
        GraphQLSchema(query=query, mutation=mutation),
        "mutation { rollbackUsers { id } }",
    )

    assert response.status_code == 200
    assert len(payload["data"]["rollbackUsers"]) == 1
    assert events == [(threading.get_ident(), True)]
    assert not User.objects.filter(username="rolled_back_user").exists()


class AsyncOnly:
    """An async-only stream used to test predicate selection.

    It deliberately has no synchronous iterator method.
    """

    def __aiter__(self) -> AsyncOnly:
        """Return the asynchronous iterator."""
        return self

    async def __anext__(self) -> int:
        """End the stream without producing values.

        Raises:
            StopAsyncIteration: Always, as the stream is empty.
        """
        raise StopAsyncIteration


@pytest.mark.django_db
def test_capability_adapter_forwards_predicate_and_legacy_backend_alias() -> None:
    """The native executor path forwards both the predicate and backend alias.

    Forcing only the stable backend capability exercises this forwarding under
    the installed 3.2 test runner without changing the installed dependency.
    """

    class Backend:
        """A recording backend identity that the execution spy never invokes."""

    query = GraphQLObjectType("Query", {"ping": GraphQLField(GraphQLString)})
    schema = SimpleNamespace(graphql_schema=GraphQLSchema(query=query))
    request = RequestFactory().post(
        "/graphql/", json.dumps({"query": "{ ping }"}), content_type="application/json"
    )
    with (
        patch("django_graphex.views._EXECUTION_BACKEND_KEYWORD", "executor_class"),
        patch(
            "django_graphex.views.execute",
            return_value=ExecutionResult(data={"ping": None}),
        ) as execute_spy,
    ):
        response = BaseGraphQLView.as_view(
            schema=schema, execution_context_class=Backend
        )(request)

    assert response.status_code == 200
    assert json.loads(response.content) == {"data": {"ping": None}}
    options = execute_spy.call_args.kwargs
    assert options["executor_class"] is Backend
    predicate = options["is_async_iterable"]
    assert not predicate(User.objects.all())
    assert not predicate([1])
    assert predicate(AsyncOnly())


@pytest.mark.django_db
def test_backend_iterable_predicate_keeps_async_only_values() -> None:
    """The 3.3 predicate excludes dual iterables but retains async-only ones.

    GraphQL-core 3.2 must not receive the new executor option.
    """

    query = GraphQLObjectType("Query", {"ping": GraphQLField(GraphQLString)})
    with patch("django_graphex.views.execute", wraps=graphql_execute) as execute_spy:
        response, payload = _request(GraphQLSchema(query=query), "{ ping }")

    assert response.status_code == 200
    assert payload == {"data": {"ping": None}}
    options = execute_spy.call_args.kwargs
    if hasattr(graphql_execution, "Executor"):
        from graphql.pyutils import is_async_iterable

        predicate = options.get("is_async_iterable", is_async_iterable)
        assert not predicate(User.objects.all())
        assert not predicate([1])
        assert predicate(AsyncOnly())
    else:
        assert "is_async_iterable" not in options
