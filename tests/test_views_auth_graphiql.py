# -*- coding: utf-8 -*-
"""AuthenticatedGraphQLView (no-DRF endpoint gate) and the graphiql_template hook."""

import json
from types import SimpleNamespace

from django.test import RequestFactory, TestCase
from graphql import GraphQLString

from django_graphex import AllowAny, DjangoGraphQLSchema, IsAdmin, ObjectType, field
from django_graphex.views import AuthenticatedGraphQLView, GraphQLView


class _Query(ObjectType):
    hello = field(GraphQLString)

    def resolve_hello(root, info):
        return "world"


_schema = DjangoGraphQLSchema(query=_Query)


def _post(user=None):
    request = RequestFactory().post(
        "/graphql/", {"query": "{ hello }"}, content_type="application/json"
    )
    if user is not None:
        request.user = user
    return request


class AuthenticatedViewTest(TestCase):
    def test_unauthenticated_is_forbidden(self):
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        # no request.user (anonymous-like) -> 403
        response = view(_post(user=SimpleNamespace(is_authenticated=False)))
        self.assertEqual(response.status_code, 403)
        self.assertIn("errors", json.loads(response.content))

    def test_authenticated_passes_through(self):
        view = AuthenticatedGraphQLView.as_view(schema=_schema)
        response = view(_post(user=SimpleNamespace(is_authenticated=True)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"]["hello"], "world")

    def test_custom_permission_classes_allow_any(self):
        # AllowAny -> even an unauthenticated request goes through.
        view = AuthenticatedGraphQLView.as_view(
            schema=_schema, permission_classes=(AllowAny,)
        )
        response = view(_post(user=SimpleNamespace(is_authenticated=False)))
        self.assertEqual(response.status_code, 200)

    def test_custom_permission_classes_is_admin_denies_plain_user(self):
        view = AuthenticatedGraphQLView.as_view(
            schema=_schema, permission_classes=(IsAdmin,)
        )
        plain = SimpleNamespace(
            is_authenticated=True, is_active=True, is_staff=False, is_superuser=False
        )
        response = view(_post(user=plain))
        self.assertEqual(response.status_code, 403)


class GraphiqlTemplateTest(TestCase):
    def test_default_serves_cdn_page(self):
        request = RequestFactory().get("/graphql/", HTTP_ACCEPT="text/html")
        view = GraphQLView.as_view(schema=_schema, graphiql=True)
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn(b"unpkg.com/graphiql", response.content)  # the CDN page

    def test_custom_template_overrides_cdn(self):
        request = RequestFactory().get("/graphql/", HTTP_ACCEPT="text/html")
        # tests/templates/custom_graphiql.html is on the test template dirs.
        view = GraphQLView.as_view(
            schema=_schema, graphiql=True, graphiql_template="custom_graphiql.html"
        )
        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"MY CUSTOM GRAPHIQL", response.content)
        self.assertNotIn(b"unpkg.com/graphiql", response.content)  # not the CDN page


def test_explicit_subscription_path_is_honored():
    # Regression: BaseGraphQLView.__init__ dropped an explicit subscription_path
    # (only read the GRAPHENE setting), so it never reached custom templates.
    from django_graphex.views import BaseGraphQLView

    view = BaseGraphQLView(schema=_schema, subscription_path="/ws/graphql")
    assert view.subscription_path == "/ws/graphql"
