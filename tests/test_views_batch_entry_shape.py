# -*- coding: utf-8 -*-
"""Batch entry shape validation on the HTTP view.

A batch body is a JSON list, but nothing checked what the list CONTAINED: a
non-mapping entry reached "get_graphql_params", where "data.get(...)" raised an
"AttributeError" that escaped the "except HttpError" handler in "dispatch" and
surfaced as an HTTP 500. The docs promise HTTP 400 for a body of the wrong
shape, so a malformed entry must be rejected the same way.
"""

from __future__ import annotations

import json
from typing import Any

from django.test import RequestFactory, TestCase
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView


class _Query(ObjectType):
    """The root query exposing a single static "hello" field."""

    hello = field(GraphQLString)

    def resolve_hello(root: Any, info: Any) -> str:
        """Resolve "hello" to the constant string "world".

        Args:
            root: The parent resolver value, unused at the root query.
            info: The GraphQL resolve info for the current request.

        Returns:
            value: The literal string "world".
        """
        return "world"


_schema = DjangoGraphQLSchema(query=_Query)


class TestBatchEntryShape(TestCase):
    """A batch entry that is not a JSON object must be a 400, never a 500.

    The outer list shape was already checked; these drive what the list HOLDS,
    the gap that turned a malformed body into an unhandled "AttributeError".
    """

    def _post(self, body: Any) -> Any:
        """Send a batch body to a batch-enabled view.

        Args:
            body: The Python object to JSON-encode as the request body.

        Returns:
            response: The view's HTTP response.
        """
        request = RequestFactory().post(
            "/graphql/batch",
            data=json.dumps(body),
            content_type="application/json",
        )
        return GraphQLView.as_view(schema=_schema, batch=True)(request)

    def test_scalar_entries_return_400(self) -> None:
        """A list of bare scalars must be rejected with HTTP 400.

        Contract: this ships broken if "[1, 2, 3]" raises an "AttributeError"
        past the "HttpError" handler and yields an HTTP 500.
        """
        response = self._post([1, 2, 3])

        assert response.status_code == 400
        assert "errors" in json.loads(response.content)

    def test_nested_list_entry_returns_400(self) -> None:
        """A list entry that is itself a list must be rejected with HTTP 400.

        Contract: this ships broken if any non-mapping entry shape reaches
        "get_graphql_params" instead of the batch shape check.
        """
        response = self._post([[{"query": "{ hello }"}]])

        assert response.status_code == 400

    def test_valid_entries_still_execute(self) -> None:
        """A well-formed batch must still execute every operation.

        Contract: this ships broken if the entry-shape check rejects the
        mappings a legitimate batch is made of.
        """
        response = self._post([{"query": "{ hello }"}, {"query": "{ hello }"}])

        assert response.status_code == 200
        payload = json.loads(response.content)
        assert [entry["data"]["hello"] for entry in payload] == ["world", "world"]
