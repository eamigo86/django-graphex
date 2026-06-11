# -*- coding: utf-8 -*-
"""Tests for django_graphex.views module."""

import json
from unittest.mock import patch

import graphene
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from django_graphex.views import GraphQLView


class TestQuery(graphene.ObjectType):
    """Simple test query."""

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    hello = graphene.String(name=graphene.String(default_value="World"))

    def resolve_hello(self, info, name):
        """Resolve hello field."""
        return f"Hello {name}!"


class TestSubscription(graphene.ObjectType):
    """Simple test subscription."""

    __test__ = False  # GraphQL schema fixture, not a pytest test class

    counter = graphene.String()

    def subscribe_counter(self, info):
        """Subscribe to counter."""
        for i in range(3):
            yield {"counter": f"Count: {i}"}


test_schema = graphene.Schema(query=TestQuery, subscription=TestSubscription)


class GraphQLViewTest(TestCase):
    """Test cases for GraphQLView."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        cache.clear()

    def test_view_creation(self):
        """Test view creation."""
        view = GraphQLView.as_view(schema=test_schema)
        self.assertIsNotNone(view)

    def test_get_request(self):
        """Test GET request to GraphQL view."""
        request = self.factory.get("/graphql/", {"query": "{ hello }"})
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])

    def test_post_request(self):
        """Test POST request to GraphQL view."""
        query = "{ hello }"
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["data"]["hello"], "Hello World!")

    def test_post_request_with_variables(self):
        """Test POST request with variables."""
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

    def test_introspection_query(self):
        """Test introspection query."""
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

    def test_invalid_query(self):
        """Test invalid GraphQL query."""
        request = self.factory.post(
            "/graphql/", {"query": "{ invalidField }"}, content_type="application/json"
        )
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("errors", data)

    def test_subscription_request(self):
        """Test subscription request."""
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

    @patch("django.core.cache.cache.get")
    @patch("django.core.cache.cache.set")
    @patch("django_graphex.views.graphql_api_settings.CACHE_ACTIVE", True)
    def test_caching_enabled(self, mock_cache_set, mock_cache_get):
        """Test query caching when enabled."""
        mock_cache_get.return_value = None  # Cache miss

        query = "{ hello }"
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )

        # Create view - caching is controlled by settings
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        # Should try to get from cache
        mock_cache_get.assert_called()
        # Should set cache on cache miss
        mock_cache_set.assert_called()

    @patch("django.core.cache.cache.get")
    @patch("django_graphex.views.graphql_api_settings.CACHE_ACTIVE", True)
    def test_cache_hit(self, mock_cache_get):
        """Test cache hit scenario."""
        cached_result = {"data": {"hello": "Hello Cached!"}}
        cached_response = HttpResponse(
            json.dumps(cached_result), content_type="application/json"
        )
        mock_cache_get.return_value = cached_response

        query = "{ hello }"
        request = self.factory.post(
            "/graphql/", {"query": query}, content_type="application/json"
        )

        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["data"]["hello"], "Hello Cached!")

    def test_options_request(self):
        """Test OPTIONS request (CORS preflight)."""
        request = self.factory.options("/graphql/")
        view = GraphQLView.as_view(schema=test_schema)

        response = view(request)

        # Should handle OPTIONS request
        self.assertIn(response.status_code, [200, 405])

    def test_graphiql_enabled(self):
        """Test GraphiQL interface when enabled."""
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html")
        view = GraphQLView.as_view(schema=test_schema, graphiql=True)

        response = view(request)

        self.assertEqual(response.status_code, 200)
        # Should return HTML for GraphiQL
        self.assertIn("text/html", response["Content-Type"])

    def test_graphiql_disabled(self):
        """Test GraphiQL interface when disabled."""
        request = self.factory.get("/graphql/", HTTP_ACCEPT="text/html")
        view = GraphQLView.as_view(schema=test_schema, graphiql=False)

        response = view(request)

        # Should not return HTML interface
        self.assertNotEqual(response["Content-Type"], "text/html")
