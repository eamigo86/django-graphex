# -*- coding: utf-8 -*-
"""Cookie-dependent queries are never shared by the default response cache."""

import json
from typing import Any, ClassVar
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, override_settings
from graphql import GraphQLResolveInfo, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView
from tests.cache_helpers import CACHE_ON, graphql_post, minimal_cache_schema


class _CookieQuery(ObjectType):
    """Expose a value read from the request cookie jar."""

    cart = field(GraphQLString)
    calls: ClassVar[int] = 0

    def resolve_cart(root: Any, info: GraphQLResolveInfo) -> str:  # noqa: N805
        """Return the cart cookie and count actual resolver executions."""
        _CookieQuery.calls += 1
        return info.context.COOKIES["cart"]


_cookie_schema = DjangoGraphQLSchema(query=_CookieQuery)


@override_settings(**CACHE_ON)
class CookieCacheBypassTest(TestCase):
    """The safe default bypasses response caching for cookie-bearing queries.

    This test protects the corresponding regression contract.
    """

    def setUp(self) -> None:
        """Initialize the isolated test fixture.

        This test protects the corresponding regression contract.
        """
        self.factory = RequestFactory()
        self.view = GraphQLView.as_view(schema=_cookie_schema)
        _CookieQuery.calls = 0

    def _request(self, cart: str | None = None) -> HttpRequest:
        request = graphql_post(self.factory, "{ cart }")
        if cart is not None:
            request.COOKIES["cart"] = cart
        return request

    def test_cookie_dependent_anonymous_queries_are_not_shared(self) -> None:
        """Verify cookie dependent anonymous queries are not shared.

        This test protects the corresponding regression contract.
        """
        first = self.view(self._request("alice"))
        second = self.view(self._request("bob"))

        self.assertEqual(json.loads(first.content)["data"]["cart"], "alice")
        self.assertEqual(json.loads(second.content)["data"]["cart"], "bob")
        self.assertEqual(_CookieQuery.calls, 2)

    def test_default_hook_rejects_cookie_bearing_queries(self) -> None:
        """Verify default hook rejects cookie bearing queries.

        This test protects the corresponding regression contract.
        """
        view = GraphQLView(schema=_cookie_schema)

        self.assertFalse(view.should_cache_query(self._request("alice")))

    def test_default_hook_allows_cookie_free_queries(self) -> None:
        """Verify default hook allows cookie free queries.

        This test protects the corresponding regression contract.
        """
        request = self.factory.post(
            "/graphql/",
            json.dumps({"query": "{ hello }"}),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        view = GraphQLView(schema=minimal_cache_schema)

        self.assertTrue(view.should_cache_query(request))

    def test_cookie_bearing_mutation_still_invalidates(self) -> None:
        """Verify cookie bearing mutation still invalidates.

        This test protects the corresponding regression contract.
        """
        request = graphql_post(self.factory, "mutation { doThing { ok } }")
        request.COOKIES["sessionid"] = "opaque"
        view = GraphQLView.as_view(schema=minimal_cache_schema)

        with patch.object(GraphQLView, "_bump_cache_version") as bump:
            response = view(request)

        self.assertEqual(response.status_code, 200)
        bump.assert_called_once()
