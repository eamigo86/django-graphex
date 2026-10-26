"""Batch items run in their own savepoint and always yield one entry each."""

from __future__ import annotations

import json
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from django.db import connection
from django.test import Client, override_settings
from django.urls import path
from graphql import (
    GraphQLArgument,
    GraphQLError,
    GraphQLField,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.views import (
    MUTATION_ERRORS_FLAG,
    BaseGraphQLView,
    GraphQLView,
)
from tests.models import Author

pytestmark = pytest.mark.django_db(transaction=True)

_NAME = {"name": GraphQLArgument(GraphQLNonNull(GraphQLString))}


def _add(_root: Any, _info: Any, name: str) -> str:
    """Persist one author.

    Args:
        name: The author name.

    Returns:
        The name.
    """
    Author.objects.create(name=name)
    return name


def _fail(_root: Any, _info: Any, name: str) -> str:
    """Persist one author, then raise a GraphQL error.

    Args:
        name: The author name.

    Raises:
        GraphQLError: Always.
    """
    Author.objects.create(name=name)
    raise GraphQLError("expected failure")


def _flagged(_root: Any, info: Any, name: str) -> str:
    """Persist one author and set the request-level mutation error flag.

    Args:
        info: Resolve info carrying the request.
        name: The author name.

    Returns:
        The name.
    """
    Author.objects.create(name=name)
    setattr(info.context, MUTATION_ERRORS_FLAG, True)
    return name


def _query_fail(_root: Any, _info: Any) -> str:
    """Raise a GraphQL error from a query field.

    Raises:
        GraphQLError: Always.
    """
    raise GraphQLError("query failure")


_SCHEMA = SimpleNamespace(
    graphql_schema=GraphQLSchema(
        query=GraphQLObjectType(
            "Q",
            {
                "ping": GraphQLField(GraphQLString, resolve=lambda *_: "pong"),
                "boom": GraphQLField(
                    GraphQLNonNull(GraphQLString), resolve=_query_fail
                ),
            },
        ),
        mutation=GraphQLObjectType(
            "M",
            {
                "add": GraphQLField(GraphQLString, args=_NAME, resolve=_add),
                "fail": GraphQLField(GraphQLString, args=_NAME, resolve=_fail),
                "flagged": GraphQLField(GraphQLString, args=_NAME, resolve=_flagged),
            },
        ),
    )
)


def _post(
    body: Any,
    *,
    view_class: type[BaseGraphQLView] = GraphQLView,
    atomic_requests: bool = False,
    atomic_mutations: bool = False,
    batch: bool = True,
) -> tuple[int, Any]:
    """Send one request through the real Django handler.

    Args:
        body: The JSON body.
        view_class: The view under test.
        atomic_requests: Whether the default database sets ATOMIC_REQUESTS.
        atomic_mutations: Whether ATOMIC_MUTATIONS is on.
        batch: Whether the endpoint accepts a batch.

    Returns:
        The status code and decoded JSON payload.
    """
    urlconf = ModuleType("batch_savepoint_urls")
    urlconf.urlpatterns = [
        path("graphql/", view_class.as_view(schema=_SCHEMA, batch=batch))
    ]
    previous = connection.settings_dict.get("ATOMIC_REQUESTS", False)
    connection.settings_dict["ATOMIC_REQUESTS"] = atomic_requests
    try:
        with override_settings(
            ROOT_URLCONF=urlconf,
            DJANGO_GRAPHEX={
                "ATOMIC_MUTATIONS": atomic_mutations,
                "CACHE_ACTIVE": False,
                "MAX_BATCH_SIZE": None,
            },
        ):
            response = Client(raise_request_exception=False).post(
                "/graphql/", json.dumps(body), content_type="application/json"
            )
    finally:
        connection.settings_dict["ATOMIC_REQUESTS"] = previous
    return response.status_code, json.loads(response.content)


def _names() -> set[str]:
    """Return the persisted author names.

    Returns:
        The set of names.
    """
    return set(Author.objects.values_list("name", flat=True))


_VIEWS = pytest.mark.parametrize("view_class", [BaseGraphQLView, GraphQLView])
_ATOMIC = pytest.mark.parametrize("atomic_requests", [False, True])
_MUTATIONS = pytest.mark.parametrize("atomic_mutations", [False, True])


@_VIEWS
@_ATOMIC
@_MUTATIONS
def test_failed_query_item_does_not_poison_later_mutation(
    view_class: type[BaseGraphQLView], atomic_requests: bool, atomic_mutations: bool
) -> None:
    """A query error in one item leaves the other items' writes committed.

    Args:
        view_class: The view under test.
        atomic_requests: ATOMIC_REQUESTS on the default database.
        atomic_mutations: The ATOMIC_MUTATIONS setting.
    """
    status, payload = _post(
        [
            {"id": "w1", "query": 'mutation { add(name: "first") }'},
            {"id": "q", "query": "{ doesNotExist }"},
            {"id": "w2", "query": 'mutation { add(name: "second") }'},
            {"id": "q2", "query": "{ boom }"},
            {"id": "w3", "query": 'mutation { add(name: "third") }'},
        ],
        view_class=view_class,
        atomic_requests=atomic_requests,
        atomic_mutations=atomic_mutations,
    )

    assert status == 400
    assert [e["id"] for e in payload] == ["w1", "q", "w2", "q2", "w3"]
    assert [e["status"] for e in payload] == [200, 400, 200, 200, 200]
    assert payload[0]["data"] == {"add": "first"}
    assert payload[2]["data"] == {"add": "second"}
    assert payload[4]["data"] == {"add": "third"}
    assert "errors" not in payload[2]
    assert _names() == {"first", "second", "third"}


@_VIEWS
@_ATOMIC
def test_failing_mutation_item_is_rolled_back_alone(
    view_class: type[BaseGraphQLView], atomic_requests: bool
) -> None:
    """With ATOMIC_REQUESTS a failing item rolls back only its own writes.

    Args:
        view_class: The view under test.
        atomic_requests: ATOMIC_REQUESTS on the default database.
    """
    status, payload = _post(
        [
            {"query": 'mutation { add(name: "kept1") }'},
            {"query": 'mutation { fail(name: "lost") }'},
            {"query": 'mutation { add(name: "kept2") }'},
        ],
        view_class=view_class,
        atomic_requests=atomic_requests,
    )

    assert status == 200
    assert [bool(e.get("errors")) for e in payload] == [False, True, False]
    assert payload[2]["data"] == {"add": "kept2"}
    expected = {"kept1", "kept2"} if atomic_requests else {"kept1", "lost", "kept2"}
    assert _names() == expected


@_VIEWS
@_ATOMIC
def test_flagged_item_does_not_roll_back_later_items(
    view_class: type[BaseGraphQLView], atomic_requests: bool
) -> None:
    """The request-level mutation error flag is scoped to one batch item.

    Args:
        view_class: The view under test.
        atomic_requests: ATOMIC_REQUESTS on the default database.
    """
    _post(
        [
            {"query": 'mutation { flagged(name: "flagged") }'},
            {"query": 'mutation { add(name: "after") }'},
        ],
        view_class=view_class,
        atomic_requests=atomic_requests,
        atomic_mutations=True,
    )

    assert _names() == {"after"}


@_VIEWS
def test_single_request_keeps_request_level_rollback(
    view_class: type[BaseGraphQLView],
) -> None:
    """A non-batched request with an error still rolls back the whole request.

    Args:
        view_class: The view under test.
    """
    status, payload = _post(
        {"query": 'mutation { add(name: "one") fail(name: "two") }'},
        view_class=view_class,
        atomic_requests=True,
        batch=False,
    )

    assert status == 200
    assert payload["errors"]
    assert _names() == set()


@_VIEWS
@pytest.mark.parametrize(
    "bad_item",
    [
        {"id": "bad", "query": "{ ping }", "variables": "{not json"},
        {"id": "bad"},
        {"id": "bad", "query": "{ ping"},
        {"id": "bad", "query": "{ missing }"},
        {"id": "bad", "query": "query A { ping } query B { ping }"},
        {"id": "bad", "query": "{ ping }", "operationName": "Nope"},
    ],
)
def test_every_item_gets_exactly_one_entry_in_order(
    view_class: type[BaseGraphQLView], bad_item: dict[str, Any]
) -> None:
    """No failure kind drops, reorders or skips the entries around it.

    Args:
        view_class: The view under test.
        bad_item: A failing batch item.
    """
    items = [
        {"id": "a", "query": 'mutation { add(name: "a") }'},
        bad_item,
        {"id": "c", "query": 'mutation { add(name: "c") }'},
    ]
    status, payload = _post(items, view_class=view_class, atomic_requests=True)

    assert status == 400
    assert [e["id"] for e in payload] == ["a", "bad", "c"]
    assert [e["status"] for e in payload] == [200, 400, 200]
    assert payload[1]["errors"]
    assert _names() == {"a", "c"}


@_VIEWS
def test_batch_status_is_the_highest_entry_status(
    view_class: type[BaseGraphQLView],
) -> None:
    """The HTTP status is 200 only when every entry is 200, otherwise 400.

    Args:
        view_class: The view under test.
    """
    ok_status, ok_payload = _post(
        [{"query": "{ ping }"}, {"query": "{ ping }"}], view_class=view_class
    )
    bad_status, bad_payload = _post(
        [{"query": "{ ping }"}, {"query": "{ nope }"}], view_class=view_class
    )

    assert (ok_status, [e["status"] for e in ok_payload]) == (200, [200, 200])
    assert (bad_status, [e["status"] for e in bad_payload]) == (400, [200, 400])
