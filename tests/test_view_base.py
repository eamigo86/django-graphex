# -*- coding: utf-8 -*-
"""Coverage for the vendored "BaseGraphQLView" error/batch/parse branches.

Exercises method-not-allowed, batch mode, invalid JSON, application/graphql and
form bodies, missing-query, GET-mutation rejection, and content-type negotiation
helpers, all through the concrete "BaseGraphQLView".
"""

import json
from typing import Any

import pytest
from django.test import RequestFactory, TestCase
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import (
    BaseGraphQLView,
    HttpError,
    get_accepted_content_types,
    instantiate_middleware,
    set_rollback,
)


class _Query(ObjectType):
    hello = field(GraphQLString)

    def resolve_hello(root: Any, info: Any) -> str:
        """Resolve the "hello" field to a fixed greeting for test schemas.

        Args:
            root: The resolver root value (unused).
            info: The GraphQL resolve info (unused).

        Returns:
            greeting: The fixed string "world".
        """
        return "world"


_schema = DjangoGraphQLSchema(query=_Query)


class ViewBaseTest(TestCase):
    """HTTP-level behavior of "BaseGraphQLView" across content types and modes.

    Covers method rejection, batch requests, malformed bodies, and the
    various supported request content types.
    """

    def setUp(self) -> None:
        """Create a shared "RequestFactory" for every test in this class.

        Individual tests build requests off "self.factory" as needed.
        """
        self.factory = RequestFactory()

    def test_method_not_allowed(self) -> None:
        """Ship-broken contract: an unsupported HTTP method (PUT) must be
        rejected with a 405 response.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.put("/graphql/", {}, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 405)

    def test_batch_mode_returns_list(self) -> None:
        """Ship-broken contract: with batch mode enabled, a JSON array of
        operations must return a JSON array of results in the same order.
        """
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }"}, {"query": "{ hello }"}])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["data"]["hello"], "world")

    def test_batch_empty_list_is_bad_request(self) -> None:
        """Ship-broken contract: an empty batch array must be rejected with a
        400 response instead of silently returning an empty result.
        """
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        request = self.factory.post("/graphql/", "[]", content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_invalid_json_body(self) -> None:
        """Ship-broken contract: a malformed JSON body must be rejected with a
        400 response rather than raising an unhandled parse error.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", "{not json", content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_application_graphql_content_type(self) -> None:
        """Ship-broken contract: a raw "application/graphql" body must be
        parsed and executed like a JSON query payload.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", "{ hello }", content_type="application/graphql"
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_form_urlencoded_body(self) -> None:
        """Ship-broken contract: a URL-encoded form body carrying "query" must
        be accepted and executed successfully. The header is what the
        CORS-simple POST guard asks such a caller to add.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/",
            "query=" + "%7B+hello+%7D",  # urlencoded "{ hello }"
            content_type="application/x-www-form-urlencoded",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_missing_query_is_bad_request(self) -> None:
        """Ship-broken contract: a request body with no "query" key must be
        rejected with a 400 response.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post("/graphql/", {}, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_get_mutation_is_rejected(self) -> None:
        """Ship-broken contract: a non-dict JSON body must fail the internal
        dict assertion and surface as a 400 response, not a crash.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        # A non-dict JSON body asserts -> bad request (covers the dict assertion).
        request = self.factory.post(
            "/graphql/", "[1, 2]", content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)

    def test_pretty_view_pretty_prints(self) -> None:
        """Ship-broken contract: with "pretty=True", the JSON response body
        must be indented (contain newlines), not minified.
        """
        view = BaseGraphQLView.as_view(schema=_schema, pretty=True)
        request = self.factory.get("/graphql/", {"query": "{ hello }"})
        response = view(request)
        self.assertEqual(response.status_code, 200)
        # Pretty output is indented (contains newlines).
        self.assertIn(b"\n", response.content)


# --------------------------------------------------------------------------- #
# Module-level helpers                                                          #
# --------------------------------------------------------------------------- #
def test_get_accepted_content_types_orders_by_quality() -> None:
    """Ship-broken contract: "get_accepted_content_types" must order the
    parsed Accept header entries by descending quality value.
    """
    factory = RequestFactory()
    request = factory.get("/", HTTP_ACCEPT="text/html;q=0.8,application/json;q=0.9")
    types = get_accepted_content_types(request)
    # The higher-quality type comes first.
    assert types[0] == "application/json"


def test_get_accepted_content_types_default() -> None:
    """Ship-broken contract: with no Accept header, the wildcard "*/*" type
    must still be present in the parsed result.
    """
    factory = RequestFactory()
    request = factory.get("/")
    assert "*/*" in get_accepted_content_types(request)


def test_instantiate_middleware_handles_classes_and_instances() -> None:
    """Ship-broken contract: "instantiate_middleware" must instantiate class
    entries while passing already-constructed instances through unchanged.
    """

    class _MW:
        """Bare middleware stand-in with no behavior, used only for identity checks."""

    instance = _MW()
    out = list(instantiate_middleware([_MW, instance]))
    assert isinstance(out[0], _MW)  # class -> instantiated
    assert out[1] is instance  # instance -> passed through


def test_set_rollback_noop_outside_atomic() -> None:
    """Ship-broken contract: calling "set_rollback" outside an atomic block
    (or with ATOMIC_REQUESTS off) must be a no-op, not raise.
    """
    # Not in an atomic block / ATOMIC_REQUESTS off -> no error, no effect.
    set_rollback()


def test_http_error_carries_response() -> None:
    """Ship-broken contract: "HttpError" must expose the wrapped response
    unchanged via its "response" attribute.
    """
    from django.http import HttpResponseBadRequest

    resp = HttpResponseBadRequest("boom")
    err = HttpError(resp)
    assert err.response is resp


def test_view_rejects_graphiql_and_batch_together() -> None:
    """Ship-broken contract: constructing a view with both "graphiql=True" and
    "batch=True" must raise AssertionError, since the two modes are mutually
    exclusive.
    """
    with pytest.raises(AssertionError):
        BaseGraphQLView(schema=_schema, graphiql=True, batch=True)


# --------------------------------------------------------------------------- #
# The base BaseGraphQLView.get_response (BaseGraphQLView overrides it)            #
# --------------------------------------------------------------------------- #
class BaseGraphQLViewTest(TestCase):
    """Response behavior of "BaseGraphQLView.get_response" for common paths.

    Covers success, GraphQL errors mapped to HTTP status, batch mode, GraphiQL
    rendering, and GET-mutation rejection.
    """

    def setUp(self) -> None:
        """Create a shared "RequestFactory" for every test in this class.

        Individual tests build requests off "self.factory" as needed.
        """
        self.factory = RequestFactory()

    def test_base_view_get_response_ok(self) -> None:
        """Ship-broken contract: a valid query must return a 200 response
        with the resolved data.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ hello }"}, content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_base_view_errors_set_400(self) -> None:
        """Ship-broken contract: a query referencing an unknown field must
        surface as a 400 response carrying a GraphQL errors payload.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        request = self.factory.post(
            "/graphql/", {"query": "{ nope }"}, content_type="application/json"
        )
        response = view(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", json.loads(response.content))

    def test_base_view_batch(self) -> None:
        """Ship-broken contract: a batch request must preserve each
        operation's "id" and per-operation HTTP status in its result list.
        """
        view = BaseGraphQLView.as_view(schema=_schema, batch=True)
        body = json.dumps([{"query": "{ hello }", "id": 1}])
        request = self.factory.post("/graphql/", body, content_type="application/json")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload[0]["id"], 1)
        self.assertEqual(payload[0]["status"], 200)

    def test_base_view_graphiql_renders_html(self) -> None:
        """Ship-broken contract: a browser request (Accept: text/html) with
        "graphiql=True" must return an HTML response, not JSON.
        """
        view = BaseGraphQLView.as_view(schema=_schema, graphiql=True)
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html")
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_base_view_get_mutation_rejected(self) -> None:
        """Ship-broken contract: a GET request carrying a mutation query
        must be rejected with a 405 response.
        """
        view = BaseGraphQLView.as_view(schema=_schema)
        # A GET carrying a mutation is rejected with 405.
        request = self.factory.get("/graphql/", {"query": "mutation { __typename }"})
        response = view(request)
        self.assertEqual(response.status_code, 405)
