"""Cache-boundary regressions for bound-cost mutation refusals."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import RequestFactory, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.views import _CACHE_MUTATION_EXECUTED_FLAG, GraphQLView
from tests.models import Author

_SETTINGS = {
    "MAX_QUERY_COST": 120,
    "MAX_PAGE_SIZE": None,
    "DEFAULT_PAGE_SIZE": 100,
    "CACHE_ACTIVE": True,
    "CACHE_TIMEOUT": 60,
}
_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "cost-mutation-cache-regression",
    }
}
_WRITE = "mutation Write($n: Int!) { write(limit: $n) { child { name } } }"


def _schema(calls: list[str]) -> SimpleNamespace:
    """Build a one-item write whose nested field makes limit affect cost."""
    child = GraphQLObjectType(
        "CostMutationChild", {"name": GraphQLField(GraphQLString)}
    )
    item = GraphQLObjectType("CostMutationItem", {"child": GraphQLField(child)})

    def status(_root: Any, _info: Any) -> str:
        calls.append("status")
        return "ok"

    def write(_root: Any, _info: Any, limit: int) -> list[dict[str, Any]]:
        calls.append("write")
        Author.objects.create(name="written")
        return [{"child": {"name": "one"}}]

    def fail(_root: Any, _info: Any) -> str:
        calls.append("fail")
        Author.objects.create(name="written before error")
        raise RuntimeError("late mutation failure")

    return SimpleNamespace(
        graphql_schema=GraphQLSchema(
            query=GraphQLObjectType(
                "CostMutationQuery",
                {"status": GraphQLField(GraphQLString, resolve=status)},
            ),
            mutation=GraphQLObjectType(
                "CostMutationRoot",
                {
                    "write": GraphQLField(
                        GraphQLList(item),
                        args={"limit": GraphQLArgument(GraphQLInt)},
                        resolve=write,
                    ),
                    "fail": GraphQLField(GraphQLString, resolve=fail),
                },
            ),
        )
    )


def _post(view: Any, payload: dict[str, Any] | list[dict[str, Any]]) -> tuple[Any, Any]:
    """Send a real JSON GraphQL request and return its body and request."""
    request = RequestFactory().post(
        "/graphql/", json.dumps(payload), content_type="application/json"
    )
    request.user = User(pk=7, username="cache-user", is_active=True)
    response = view(request)
    return json.loads(response.content), request


def _warm_query(view: Any, calls: list[str]) -> None:
    """Prove that the query has a reusable response-cache entry."""
    _post(view, {"query": "{ status }"})
    _post(view, {"query": "{ status }"})
    assert calls.count("status") == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("atomic", [False, True])
@pytest.mark.parametrize("batch", [False, True])
def test_refused_mutation_does_not_invalidate_warmed_query(
    atomic: bool, batch: bool
) -> None:
    """Reject before resolver work without changing the cache version.

    Args:
        atomic: Whether to wrap mutation execution in a transaction.
        batch: Whether the request uses the batch transport.
    """
    with override_settings(
        DJANGO_GRAPHEX={**_SETTINGS, "ATOMIC_MUTATIONS": atomic}, CACHES=_CACHE
    ):
        cache.clear()
        calls: list[str] = []
        schema = _schema(calls)
        query_view = GraphQLView.as_view(schema=schema)
        mutation_view = GraphQLView.as_view(schema=schema, batch=batch)
        _warm_query(query_view, calls)
        before = Author.objects.count()
        payload = {"query": _WRITE, "operationName": "Write", "variables": {"n": 150}}
        with patch.object(
            GraphQLView,
            "_bump_cache_version",
            autospec=True,
            side_effect=GraphQLView._bump_cache_version,
        ) as bump:
            body, request = _post(mutation_view, [payload] if batch else payload)
        result = body[0] if batch else body
        assert result["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
        assert calls.count("write") == 0
        assert Author.objects.count() == before
        assert bump.call_count == 0
        assert getattr(request, _CACHE_MUTATION_EXECUTED_FLAG) is False
        _post(query_view, {"query": "{ status }"})
        assert calls.count("status") == 1


@pytest.mark.django_db(transaction=True)
@override_settings(
    DJANGO_GRAPHEX={**_SETTINGS, "ATOMIC_MUTATIONS": False}, CACHES=_CACHE
)
def test_later_refusal_preserves_earlier_executed_batch_mutation() -> None:
    """Keep invalidation when a prior operation in the batch did write.

    The later refusal must not erase the earlier operation's marker.
    """
    cache.clear()
    calls: list[str] = []
    schema = _schema(calls)
    query_view = GraphQLView.as_view(schema=schema)
    batch_view = GraphQLView.as_view(schema=schema, batch=True)
    _warm_query(query_view, calls)
    before = Author.objects.count()
    operations = [
        {"query": _WRITE, "operationName": "Write", "variables": {"n": 1}},
        {"query": _WRITE, "operationName": "Write", "variables": {"n": 150}},
    ]
    with patch.object(
        GraphQLView,
        "_bump_cache_version",
        autospec=True,
        side_effect=GraphQLView._bump_cache_version,
    ) as bump:
        body, request = _post(batch_view, operations)
    assert body[0]["data"]["write"][0]["child"]["name"] == "one"
    assert body[1]["errors"][0]["extensions"]["code"] == "QUERY_TOO_COMPLEX"
    assert calls.count("write") == 1
    assert Author.objects.count() == before + 1
    assert getattr(request, _CACHE_MUTATION_EXECUTED_FLAG) is True
    assert bump.call_count == 1
    _post(query_view, {"query": "{ status }"})
    assert calls.count("status") == 2


@pytest.mark.django_db(transaction=True)
@override_settings(
    DJANGO_GRAPHEX={**_SETTINGS, "ATOMIC_MUTATIONS": False}, CACHES=_CACHE
)
def test_late_resolver_error_still_invalidates_after_non_atomic_write() -> None:
    """Preserve the original safety marker for a write before an error.

    A resolver failure is different from refusal before resolver execution.
    """
    cache.clear()
    calls: list[str] = []
    schema = _schema(calls)
    query_view = GraphQLView.as_view(schema=schema)
    mutation_view = GraphQLView.as_view(schema=schema)
    _warm_query(query_view, calls)
    before = Author.objects.count()
    with patch.object(
        GraphQLView,
        "_bump_cache_version",
        autospec=True,
        side_effect=GraphQLView._bump_cache_version,
    ) as bump:
        body, request = _post(mutation_view, {"query": "mutation { fail }"})
    assert body["errors"][0]["message"] == "late mutation failure"
    assert calls.count("fail") == 1
    assert Author.objects.count() == before + 1
    assert getattr(request, _CACHE_MUTATION_EXECUTED_FLAG) is True
    assert bump.call_count == 1
    _post(query_view, {"query": "{ status }"})
    assert calls.count("status") == 2
