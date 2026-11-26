"""The built-in GraphiQL page runs subscriptions over the WebSocket transport."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from graphql import GraphQLString

from django_graphex._script_escape import escape_for_script
from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.subscriptions import SubscriptionClientView
from django_graphex.views import GraphQLView

GRAPHQL_WS_URL = "https://unpkg.com/graphql-ws@5.16.2/umd/graphql-ws.min.js"
GRAPHQL_WS_SRI = (
    "sha384-+EVxFEOpy8LWPRQcpntm0FKN2O+BzrMNSL0G3HIgVWFmeb6xqZqjuLivrQUTXZKi"
)


class _Query(ObjectType):
    hello = field(GraphQLString)


_schema = DjangoGraphQLSchema(query=_Query)


def _page(**view_kwargs: Any) -> str:
    """Render the GraphiQL page for a view built with the given arguments.

    Args:
        **view_kwargs: Extra "GraphQLView.as_view" arguments.

    Returns:
        html: The decoded GraphiQL page body.
    """
    view = GraphQLView.as_view(schema=_schema, graphiql=True, **view_kwargs)
    request = RequestFactory().get("/graphql/", HTTP_ACCEPT="text/html,*/*")
    return view(request).content.decode()


class TestGraphiQLSubscriptions(TestCase):
    """GraphiQL page contract for subscriptions.

    The page loads graphql-ws and wires a lazy WebSocket client.
    """

    def test_graphql_ws_script_is_pinned_with_sri(self) -> None:
        """The graphql-ws tag carries the pinned URL, sha384 SRI and crossorigin.

        It must load before the inline script that calls "graphqlWs".
        """
        html = _page()
        tag = re.search(r"<script[^>]*graphql-ws@[^>]*></script>", html)
        assert tag is not None
        self.assertIn(f'src="{GRAPHQL_WS_URL}"', tag.group(0))
        self.assertIn(f'integrity="{GRAPHQL_WS_SRI}"', tag.group(0))
        self.assertIn('crossorigin="anonymous"', tag.group(0))
        self.assertLess(html.index("graphql-ws@"), html.index("graphqlWs.createClient"))

    def test_fetcher_gets_lazy_ws_client(self) -> None:
        """The fetcher keeps the HTTP URL and receives a lazy "wsClient".

        Queries and mutations therefore still go to "window.location.pathname".
        """
        html = _page()
        self.assertIn("graphqlWs.createClient", html)
        self.assertIn("lazy: true", html)
        self.assertIn(
            "GraphiQL.createFetcher({ url: window.location.pathname, wsClient })",
            html,
        )
        self.assertIn("location.host", html)
        self.assertIn("wss:", html)

    def test_default_path(self) -> None:
        """Without a view argument or setting the path is "/ws/graphql/".

        Asserts on the rendered GraphiQL page body.
        """
        self.assertIn('"/ws/graphql/"', _page())

    @override_settings(DJANGO_GRAPHEX={"SUBSCRIPTION_PATH": "/ws/from-setting/"})
    def test_path_from_setting(self) -> None:
        """The "SUBSCRIPTION_PATH" setting overrides the default.

        Asserts on the rendered GraphiQL page body.
        """
        html = _page()
        self.assertIn('"/ws/from-setting/"', html)
        self.assertNotIn("/ws/graphql/", html)

    def test_path_from_view_argument(self) -> None:
        """The view argument overrides the default.

        Asserts on the rendered GraphiQL page body.
        """
        html = _page(subscription_path="/ws/custom/")
        self.assertIn('"/ws/custom/"', html)
        self.assertNotIn("/ws/graphql/", html)

    def test_hostile_path_is_escaped(self) -> None:
        """A path with script-breaking characters cannot leave the string literal.

        Asserts on the rendered GraphiQL page body.
        """
        html = _page(subscription_path='/x</script><b>"&')
        self.assertNotIn("<b>", html)
        self.assertEqual(html.count("</script>"), 5)
        escaped = "/x\\u003c/script\\u003e\\u003cb\\u003e" + chr(92) + '"' + "\\u0026"
        self.assertIn('"' + escaped + '"', html)
        self.assertNotIn("__SUBSCRIPTION_PATH__", html)

    def test_custom_template_still_gets_subscription_path(self) -> None:
        """A custom "graphiql_template" receives "subscription_path" unchanged.

        Asserts on the rendered GraphiQL page body.
        """
        view = GraphQLView(
            schema=_schema,
            graphiql=True,
            graphiql_template="x.html",
            subscription_path="/ws/t/",
        )
        request = RequestFactory().get("/graphql/")
        with patch("django_graphex.views.render", return_value="ok") as render:
            self.assertEqual(view.render_graphiql(request), "ok")
        self.assertEqual(
            render.call_args.args[2],
            {"endpoint": "/graphql/", "subscription_path": "/ws/t/"},
        )


class TestEscapeHelper(SimpleTestCase):
    """Shared escape helper contract.

    The client view keeps delegating to the shared escape helper.
    """

    def test_client_view_escape_matches_helper(self) -> None:
        """The client view escape equals the shared helper.

        Guards the delegation in "SubscriptionClientView._escape_for_script".
        """
        self.assertEqual(
            SubscriptionClientView._escape_for_script("</a>&"),
            escape_for_script("</a>&"),
        )
