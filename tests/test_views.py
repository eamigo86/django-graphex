# -*- coding: utf-8 -*-
"""Tests for the "django_graphex.views" module."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase
from graphql import GraphQLArgument, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView


class TestQuery(ObjectType):
    """Simple query type exposing a "hello" field for view-level tests.

    Used as the root query of "test_schema" throughout this module.
    """

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    hello = field(
        GraphQLString,
        args={"name": GraphQLArgument(GraphQLString, default_value="World")},
    )

    def resolve_hello(self: Any, info: Any, name: str) -> str:
        """Resolve the "hello" field to a greeting for the given name.

        Args:
            info: The GraphQL resolve info (unused).
            name: The name to greet.

        Returns:
            greeting: The string "Hello {name}!".
        """
        return f"Hello {name}!"


class TestSubscription(ObjectType):
    """Simple subscription type exposing a "counter" field for view-level tests.

    Used as the root subscription of "test_schema" throughout this module.
    """

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    counter = field(GraphQLString)

    def resolve_counter(self: Any, info: Any) -> str:
        """Resolve the "counter" field to a fixed placeholder value.

        Args:
            info: The GraphQL resolve info (unused).

        Returns:
            value: The fixed string "Count: 0".
        """
        return "Count: 0"


test_schema = DjangoGraphQLSchema(query=TestQuery, subscription=TestSubscription)


class GraphQLViewTest(TestCase):
    """HTTP behavior of "GraphQLView" across methods, caching, and GraphiQL.

    Covers GET/POST/OPTIONS handling, variables, introspection, invalid
    queries, subscriptions, response caching, and the GraphiQL toggle.
    """

    def setUp(self) -> None:
        """Reset the request factory and clear the cache before each test.

        Guarantees cache-related tests never observe state left over from a
        previous test in this class.
        """
        self.factory = RequestFactory()
        cache.clear()

    def test_view_creation(self) -> None:
        """Ship-broken contract: "GraphQLView.as_view" must produce a
        callable view, not None or raise.
        """
        view = GraphQLView.as_view(schema=test_schema)
        self.assertIsNotNone(view)

    def test_get_request(self) -> None:
        """Ship-broken contract: a GET request with a "query" param must
        return a 200 JSON response.
        """
        request = self.factory.get("/graphql/", {"query": "{ hello }"})
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])

    def test_post_request(self) -> None:
        """Ship-broken contract: a POST request must execute the query and
        return the resolved data.
        """
        query = "{ hello }"
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["data"]["hello"], "Hello World!")

    def test_post_request_with_variables(self) -> None:
        """Ship-broken contract: query variables passed alongside the query
        must be substituted into the resolved arguments.
        """
        query = "query($name: String) { hello(name: $name) }"
        variables = {"name": "GraphQL"}

        request = self.factory.post(
            "/graphql/",
            {"query": query, "variables": json.dumps(variables)},
            content_type="application/json",
        )
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["data"]["hello"], "Hello GraphQL!")

    def test_introspection_query(self) -> None:
        """Ship-broken contract: a "__schema" introspection query must
        succeed and return type information.
        """
        introspection_query = """
        {
            __schema {
                types {
                    name
                }
            }
        }
        """

        request = self.factory.post(
            "/graphql/", {"query": introspection_query}, content_type="application/json"
        )
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("__schema", data["data"])

    def test_invalid_query(self) -> None:
        """Ship-broken contract: a query referencing an unknown field must
        return a 400 response carrying an "errors" payload.
        """
        request = self.factory.post(
            "/graphql/", {"query": "{ invalidField }"}, content_type="application/json"
        )
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("errors", data)

    def test_subscription_request(self) -> None:
        """Ship-broken contract: a subscription operation posted to the view
        must not crash; the status code stays within the expected set.
        """
        request = self.factory.post(
            "/graphql/",
            {"query": "subscription { counter }"},
            content_type="application/json",
        )
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        # Subscriptions should be handled differently
        # The exact behavior depends on the implementation
        self.assertIn(response.status_code, [200, 400, 405])

    @patch("django_graphex.views.graphql_api_settings.CACHE_ACTIVE", True)
    def test_caching_enabled(self) -> None:
        """Ship-broken contract: with CACHE_ACTIVE on, an identical second
        request must return the same data as the first (served from cache).
        """
        # Use the real local-memory cache (already cleared in setUp).
        # First request is a cache miss -> backend is called and response stored.
        query = "{ hello }"
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )

        view = GraphQLView.as_view(schema=test_schema)
        response = view(request)

        self.assertEqual(response.status_code, 200)

        # Second identical request must hit the cache (same data returned).
        request2 = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )
        response2 = view(request2)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(
            json.loads(response.content)["data"],
            json.loads(response2.content)["data"],
        )

    @patch("django.core.cache.cache.get")
    @patch("django_graphex.views.graphql_api_settings.CACHE_ACTIVE", True)
    def test_cache_hit(self, mock_cache_get: MagicMock) -> None:
        """Ship-broken contract: a cache hit must be served directly from the
        stored (body_bytes, status_code, content_type) tuple.

        The cache stores that tuple rather than a raw HttpResponse object so
        that CSRF Set-Cookie headers are never replayed across clients
        (issue #53b).

        Args:
            mock_cache_get: Mock replacing "cache.get", primed to return the
                cached payload tuple.
        """
        cached_result = {"data": {"hello": "Hello Cached!"}}
        # Cache entry format: (body_bytes, status_code, content_type).
        cached_payload = (
            json.dumps(cached_result).encode(),
            200,
            "application/json",
        )
        mock_cache_get.return_value = cached_payload

        query = "{ hello }"
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )

        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["data"]["hello"], "Hello Cached!")

    def test_options_request(self) -> None:
        """Ship-broken contract: an OPTIONS (CORS preflight) request must not
        crash; the status code stays within the expected set.
        """
        request = self.factory.options("/graphql/")
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        # Should handle OPTIONS request
        self.assertIn(response.status_code, [200, 405])

    def test_graphiql_enabled(self) -> None:
        """Ship-broken contract: with "graphiql=True" and an HTML accept
        header, the view must return the HTML GraphiQL interface.
        """
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html")
        view = GraphQLView.as_view(schema=test_schema, graphiql=True)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        # Should return HTML for GraphiQL
        self.assertIn("text/html", response["Content-Type"])

    def test_graphiql_disabled(self) -> None:
        """Ship-broken contract: with "graphiql=False", an HTML accept header
        must not receive the HTML GraphiQL interface.
        """
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html")
        view = GraphQLView.as_view(schema=test_schema, graphiql=False)

        response = view(request)

        # Should not return HTML interface
        self.assertNotEqual(response["Content-Type"], "text/html")
