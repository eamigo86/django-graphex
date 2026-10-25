# -*- coding: utf-8 -*-
"""Subscription operations are refused over plain HTTP.

A subscription POSTed to the HTTP view used to resolve to
"{"data": {"tick": null}}" with HTTP 200: no error and no hint that a long-lived
transport is required. The view now answers a client error naming the transports.
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
    """The root query exposing a static "hello" field.

    The "hello" field resolves to a constant string.
    """

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


class _Subscription(ObjectType):
    """The root subscription exposing a "tick" field.

    The field is never resolved over HTTP.
    """

    tick = field(GraphQLString)


_schema = DjangoGraphQLSchema(query=_Query, subscription=_Subscription)

_MESSAGE = "Subscriptions are not supported over HTTP"


class TestSubscriptionOverHttp(TestCase):
    """Drive the HTTP view with subscription operations.

    Each test posts to a view whose schema defines a subscription root.
    """

    def _post(self, body: Any, batch: bool = False) -> Any:
        """POST a JSON body to the view.

        Args:
            body: The Python object to JSON-encode.
            batch: Whether the view accepts batches.

        Returns:
            response: The view's HTTP response.
        """
        request = RequestFactory().post(
            "/graphql/", data=json.dumps(body), content_type="application/json"
        )
        return GraphQLView.as_view(schema=_schema, batch=batch)(request)

    def test_subscription_is_a_client_error(self) -> None:
        """A subscription answers HTTP 400 with a coded error.

        Contract: this ships broken if it returns HTTP 200 with null data.
        """
        response = self._post({"query": "subscription { tick }"})

        assert response.status_code == 400
        error = json.loads(response.content)["errors"][0]
        assert _MESSAGE in error["message"]
        assert error["extensions"]["code"] == "SUBSCRIPTION_NOT_SUPPORTED"

    def test_selected_operation_decides(self) -> None:
        """Only the operation selected by operationName is judged.

        Contract: this ships broken if a document that merely contains a
        subscription rejects the query operation selected next to it.
        """
        query = "query Q { hello } subscription S { tick }"
        ok = self._post({"query": query, "operationName": "Q"})
        bad = self._post({"query": query, "operationName": "S"})

        assert ok.status_code == 200
        assert json.loads(ok.content)["data"] == {"hello": "world"}
        assert bad.status_code == 400

    def test_batch_items_get_their_own_error(self) -> None:
        """Each subscription in a batch carries its own error entry.

        Contract: this ships broken if the query item is dropped or the
        subscription items answer null data.
        """
        response = self._post(
            [
                {"query": "subscription { tick }"},
                {"query": "{ hello }"},
                {"query": "subscription { tick }"},
            ],
            batch=True,
        )

        payload = json.loads(response.content)
        assert response.status_code == 400
        assert [("errors" in item) for item in payload] == [True, False, True]
        assert payload[1]["data"] == {"hello": "world"}
        assert _MESSAGE in payload[0]["errors"][0]["message"]
        assert _MESSAGE in payload[2]["errors"][0]["message"]
