# -*- coding: utf-8 -*-
"""AuthenticatedGraphQLView (no-DRF endpoint gate) and the graphiql_template hook."""

import json
from types import SimpleNamespace
from typing import Any

from django.http import HttpRequest
from django.test import RequestFactory, TestCase
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.permissions import AllowAny, IsAdmin
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import AuthenticatedGraphQLView, GraphQLView


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


def _post(user: Any = None) -> HttpRequest:
    """Build a POST request against the GraphQL endpoint for view tests.

    Args:
        user: When given, attached to the request as "request.user".

    Returns:
        request: A POST request carrying a fixed "{ hello }" query.
    """
    request = RequestFactory().post(
        "/graphql/", {"query": "{ hello }"}, content_type="application/json"
    )
    if user is not None:
        request.user = user
    return request


class AuthenticatedViewTest(TestCase):
    """Access-control behavior of "AuthenticatedGraphQLView".

    Covers the default permission gate and overriding it via
    "permission_classes".
    """

    def test_unauthenticated_is_forbidden(self) -> None:
        """Ship-broken contract: an anonymous-like user (is_authenticated
        False) must receive a 403 response carrying a GraphQL errors payload.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        # no request.user (anonymous-like) -> 403
        response = view(_post(user=SimpleNamespace(is_authenticated=False)))
        self.assertEqual(response.status_code, 403)
        self.assertIn("errors", json.loads(response.content))

    def test_authenticated_passes_through(self) -> None:
        """Ship-broken contract: an authenticated user must reach the schema
        and receive the resolved query data with a 200 response.
        """
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=SimpleNamespace(is_authenticated=True)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_custom_permission_classes_allow_any(self) -> None:
        """Ship-broken contract: passing the "AllowAny" permission class must
        let even an unauthenticated request through with a 200 response.
        """
        # AllowAny -> even an unauthenticated request goes through.
        view = AuthenticatedGraphQLView.as_view(
            schema=_schema, permission_classes=(AllowAny,)
        )
        response = view(_post(user=SimpleNamespace(is_authenticated=False)))
        self.assertEqual(response.status_code, 200)

    def test_custom_permission_classes_is_admin_denies_plain_user(self) -> None:
        """Ship-broken contract: the "IsAdmin" permission class must deny a
        plain authenticated, non-staff, non-superuser with a 403 response.
        """
        view = AuthenticatedGraphQLView.as_view(
            schema=_schema, permission_classes=(IsAdmin,)
        )
        plain = SimpleNamespace(
            is_authenticated=True, is_active=True, is_staff=False, is_superuser=False
        )
        response = view(_post(user=plain))
        self.assertEqual(response.status_code, 403)


class GraphiqlTemplateTest(TestCase):
    """GraphiQL HTML rendering and the "graphiql_template" override hook.

    Covers both the built-in CDN page and a project-supplied template.
    """

    def test_default_serves_cdn_page(self) -> None:
        """Ship-broken contract: with no custom template set, the view must
        serve the built-in CDN-based GraphiQL HTML page.
        """
        request = RequestFactory().get("/graphql/", HTTP_ACCEPT="text/html")
        view = GraphQLView.as_view(schema=_schema, graphiql=True)
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn(b"unpkg.com/graphiql", response.content)  # the CDN page

    def test_custom_template_overrides_cdn(self) -> None:
        """Ship-broken contract: passing "graphiql_template" must render that
        template instead of the built-in CDN page.
        """
        request = RequestFactory().get("/graphql/", HTTP_ACCEPT="text/html")
        # tests/templates/custom_graphiql.html is on the test template dirs.
        view = GraphQLView.as_view(
            schema=_schema, graphiql=True, graphiql_template="custom_graphiql.html"
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"MY CUSTOM GRAPHIQL", response.content)
        self.assertNotIn(b"unpkg.com/graphiql", response.content)  # not the CDN page


def test_explicit_subscription_path_is_honored() -> None:
    """Ship-broken contract: an explicit "subscription_path" kwarg passed to
    "BaseGraphQLView.__init__" must be honored, not silently dropped in favor
    of only reading the GRAPHENE setting.
    """
    # Regression: BaseGraphQLView.__init__ dropped an explicit subscription_path
    # (only read the GRAPHENE setting), so it never reached custom templates.
    from django_graphex.views import BaseGraphQLView

    view = BaseGraphQLView(schema=_schema, subscription_path="/ws/graphql")
    assert view.subscription_path == "/ws/graphql"
