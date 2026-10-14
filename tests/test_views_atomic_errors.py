"""Actual-client transaction and cache contracts for GraphQL execution errors."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, override_settings
from django.urls import path
from graphql import GraphQLError, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import MUTATION_ERRORS_FLAG, GraphQLView
from tests._schema_isolation import isolated_pair
from tests.test_mutations import _RMUT, TestQuery, UserMutation

pytestmark = pytest.mark.django_db(transaction=True)


class _Mutation(ObjectType):
    """Expose a native write and deterministic sibling execution outcomes."""

    user_create = UserMutation.CreateField()
    explode = field(GraphQLString)
    flagged = field(GraphQLString)

    def resolve_explode(root: Any, info: Any) -> str:
        """Raise a GraphQL execution error after an earlier sibling write.

        Args:
            root: Unused mutation root.
            info: Unused GraphQL resolve information.

        Raises:
            GraphQLError: Always, to exercise transaction rollback.
        """
        raise GraphQLError("atomic-execution-failure")

    def resolve_flagged(root: Any, info: Any) -> str:
        """Set the established request error flag without a GraphQL error.

        Args:
            root: Unused mutation root.
            info: GraphQL resolve information carrying the request context.

        Returns:
            A marker string for the response.
        """
        setattr(info.context, MUTATION_ERRORS_FLAG, True)
        return "flagged"


_SCHEMA = DjangoGraphQLSchema(
    query=TestQuery,
    mutation=_Mutation,
    registries=isolated_pair(_RMUT),
)


def _operation(username: str, sibling: str = "explode") -> str:
    """Build a native create followed by a selected sibling root field.

    Args:
        username: Isolated username for the write.
        sibling: Additional mutation root field.

    Returns:
        A mutation document selecting both root fields.
    """
    return f'''mutation {{
      userCreate(newUser: {{username: "{username}" email: "{username}@example.test"
        firstName: "T" lastName: "User" password: "testpassword123"}}) {{
        ok user {{ username }} errors {{ field messages }}
      }}
      {sibling}
    }}'''


def _post(
    query: str | list[dict[str, str]],
    *,
    atomic_mutations: bool = False,
    atomic_requests: bool = False,
    cache_active: bool = False,
    batch: bool = False,
) -> tuple[int, Any]:
    """Run the public view through Django's client and disposable test DB.

    Args:
        query: One GraphQL document or a batch of documents.
        atomic_mutations: Enable the library's inner mutation transaction.
        atomic_requests: Enable Django's actual request transaction wrapping.
        cache_active: Enable response-cache invalidation behavior.
        batch: Configure the view for a batch request.

    Returns:
        HTTP status and parsed GraphQL response payload.
    """
    urlconf = type("AtomicErrorURLConf", (), {})
    urlconf.urlpatterns = [
        path("graphql/", GraphQLView.as_view(schema=_SCHEMA, batch=batch))
    ]
    previous = connection.settings_dict.get("ATOMIC_REQUESTS", False)
    connection.settings_dict["ATOMIC_REQUESTS"] = atomic_requests
    try:
        with override_settings(
            ROOT_URLCONF=urlconf,
            DJANGO_GRAPHEX={
                "SCHEMA": None,
                "ATOMIC_MUTATIONS": atomic_mutations,
                "CACHE_ACTIVE": cache_active,
            },
        ):
            data = query if batch else {"query": query}
            response = Client().post("/graphql/", data, content_type="application/json")
    finally:
        connection.settings_dict["ATOMIC_REQUESTS"] = previous
    return response.status_code, response.json()


def test_atomic_mutations_execution_error_rolls_back_native_write() -> None:
    """An execution error rolls back the earlier native create, not its response.

    The assertion retains partial GraphQL data while checking database rollback.
    """
    username = "t05a_inner_error"
    status, payload = _post(_operation(username), atomic_mutations=True)
    assert status == 200
    assert payload["errors"][0]["message"] == "atomic-execution-failure"
    assert payload["errors"][0]["path"] == ["explode"]
    assert payload["data"]["userCreate"]["ok"] is True
    assert User.objects.filter(username=username).count() == 0


def test_atomic_requests_execution_error_rolls_back_native_write() -> None:
    """The public view marks Django's request transaction for rollback.

    The request wrapper must roll back even though the GraphQL response is valid.
    """
    username = "t05a_request_error"
    status, payload = _post(_operation(username), atomic_requests=True)
    assert status == 200
    assert payload["errors"][0]["message"] == "atomic-execution-failure"
    assert payload["data"]["userCreate"]["ok"] is True
    assert User.objects.filter(username=username).count() == 0


def test_atomic_requests_explicit_flag_rolls_back_without_graphql_error() -> None:
    """The existing flag has request-level parity without altering the payload.

    The established flag rolls back the real request transaction without an error.
    """
    username = "t05a_request_flag"
    status, payload = _post(_operation(username, "flagged"), atomic_requests=True)
    assert status == 200
    assert "errors" not in payload
    assert payload["data"]["userCreate"]["ok"] is True
    assert payload["data"]["flagged"] == "flagged"
    assert User.objects.filter(username=username).count() == 0


def test_atomic_mutations_explicit_flag_still_rolls_back() -> None:
    """The established inner-atomic flag behavior remains unchanged.

    This control preserves the pre-existing explicit-flag contract.
    """
    username = "t05a_inner_flag"
    status, payload = _post(_operation(username, "flagged"), atomic_mutations=True)
    assert status == 200
    assert "errors" not in payload
    assert User.objects.filter(username=username).count() == 0


def test_nonatomic_execution_error_keeps_durable_write_and_invalidates() -> None:
    """Without atomic protection, an earlier durable write still invalidates.

    The committed row must invalidate a cached read despite the later error.
    """
    username = "t05a_nonatomic_error"
    with patch.object(GraphQLView, "_bump_cache_version", autospec=True) as bump:
        status, payload = _post(_operation(username), cache_active=True)
    assert status == 200
    assert payload["errors"][0]["message"] == "atomic-execution-failure"
    assert User.objects.filter(username=username).count() == 1
    assert bump.call_count == 1


def test_atomic_execution_error_does_not_invalidate_rolled_back_write() -> None:
    """An inner rollback leaves cache versions unchanged.

    The cache version must not change for an inner transaction that rolls back.
    """
    username = "t05a_atomic_cache"
    with patch.object(GraphQLView, "_bump_cache_version", autospec=True) as bump:
        status, payload = _post(
            _operation(username), atomic_mutations=True, cache_active=True
        )
    assert status == 200
    assert payload["errors"][0]["message"] == "atomic-execution-failure"
    assert User.objects.filter(username=username).count() == 0
    bump.assert_not_called()


def test_atomic_success_commits_and_invalidates() -> None:
    """Successful atomic mutation work still commits and invalidates once.

    A committed inner transaction must invalidate the cache exactly once.
    """
    username = "t05a_success"
    with patch.object(GraphQLView, "_bump_cache_version", autospec=True) as bump:
        status, payload = _post(
            _operation(username, ""),
            atomic_mutations=True,
            cache_active=True,
        )
    assert status == 200
    assert payload["data"]["userCreate"]["ok"] is True
    assert User.objects.filter(username=username).count() == 1
    assert bump.call_count == 1


def test_native_ok_false_does_not_retroactively_rollback_prior_root() -> None:
    """Structured validation data does not become a GraphQL execution error.

    Native validation returns data and does not undo a prior sibling write.
    """
    username = "t05a_duplicate"
    create = _operation(username, "").removeprefix("mutation {").removesuffix("}")
    query = f"mutation {{ {create} second: {create} }}"
    status, payload = _post(query, atomic_mutations=True)
    assert status == 200
    assert "errors" not in payload
    assert payload["data"]["userCreate"]["ok"] is True
    assert payload["data"]["second"]["ok"] is False
    assert User.objects.filter(username=username).count() == 1


def test_batch_failed_atomic_operation_then_success_invalidates_once() -> None:
    """A later committed batch operation still invalidates after an earlier rollback.

    Only the later successful operation should persist and invalidate the cache.
    """
    failed = "t05a_batch_failed"
    success = "t05a_batch_success"
    documents = [
        {"query": _operation(failed)},
        {"query": _operation(success, "")},
    ]
    with patch.object(GraphQLView, "_bump_cache_version", autospec=True) as bump:
        status, payload = _post(
            documents, atomic_mutations=True, cache_active=True, batch=True
        )
    assert status == 200
    assert payload[0]["errors"][0]["message"] == "atomic-execution-failure"
    assert payload[1]["data"]["userCreate"]["ok"] is True
    assert User.objects.filter(username=failed).count() == 0
    assert User.objects.filter(username=success).count() == 1
    assert bump.call_count == 1
