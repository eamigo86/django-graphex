"""A Django view serving a self-contained HTML subscriptions client.

Add it to your project's URLConf (like the admin) to get a browser playground for
the subscription engine, served from your own origin (so there is no CORS issue):

    from django_graphex.subscriptions import SubscriptionClientView

    urlpatterns = [
        ...,
        path("graphql/client/", SubscriptionClientView.as_view()),
    ]

The endpoints default to the page's own origin; override "ws_path" / "sse_path"
/ "http_path" if your routes differ::

    SubscriptionClientView.as_view(
        ws_path="/ws/graphql/",
        sse_path="/graphql/stream",
        http_path="/graphql/",
    )
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from django.http import HttpRequest, HttpResponse
from django.views import View

from .._script_escape import escape_for_script

__all__ = ("SubscriptionClientView",)


@lru_cache(maxsize=1)
def _template() -> str:
    """Read the packaged client HTML once."""
    return (
        resources.files("django_graphex.subscriptions")
        .joinpath("_subscription_client.html")
        .read_text(encoding="utf-8")
    )


class SubscriptionClientView(View):
    """Serve the standalone HTML WebSocket + GraphQL subscriptions client.

    Override "ws_path" / "sse_path" / "http_path" (as class attributes or via
    "as_view") to point the client at your WebSocket, SSE and GraphQL routes;
    they are combined with the request's own host in the browser.
    """

    #: WebSocket route the client connects to (combined with the page host).
    ws_path: str = "/ws/graphql/"
    #: SSE route the client streams subscriptions from (combined with the page
    #: host). This is a SEPARATE endpoint from ``http_path``: the SSE transport
    #: is its own view (``subscription_sse_view``) returning
    #: ``text/event-stream``, while ``http_path`` serves ``application/json``.
    #: Seeding both fields from ``http_path`` produced a "connected" SSE client
    #: whose stream carried a JSON body with no ``event:`` line — zero data and
    #: zero errors. The default matches the route ``examples/playground``
    #: mounts (no trailing slash: the SSE view is mounted at ``graphql/stream``).
    sse_path: str = "/graphql/stream"
    #: HTTP GraphQL route the client posts subscriptions to. Trailing slash is
    #: intentional: Django's ``APPEND_SLASH`` 301-redirects ``POST /graphql`` ->
    #: ``/graphql/``, but the bundled ``fetch`` POST client does not follow the
    #: redirect (and a POST-redirect with a body raises), so the default MUST be
    #: the canonical slashed route the ``GraphQLView`` is mounted at.
    http_path: str = "/graphql/"

    def get(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponse:
        """Render the client HTML with the configured endpoint paths.

        The path values land inside an inline "<script>" block as JavaScript
        string literals, so they are escaped for BOTH the JS-string context and
        the surrounding HTML/script context via "_escape_for_script".

        Args:
            request: The incoming HTTP GET request.
            *args: Positional route arguments (unused).
            **kwargs: Keyword route arguments (unused).

        Returns:
            The rendered client HTML as a "text/html" response.
        """
        html = (
            _template()
            .replace("__WS_PATH__", self._escape_for_script(self.ws_path))
            .replace("__SSE_PATH__", self._escape_for_script(self.sse_path))
            .replace("__HTTP_PATH__", self._escape_for_script(self.http_path))
        )
        return HttpResponse(html, content_type="text/html; charset=utf-8")

    @staticmethod
    def _escape_for_script(value: str) -> str:
        """Escape "value" for an inline "<script>" JS string literal.

        Delegates to the shared helper in "django_graphex._script_escape".

        Args:
            value: The raw path string to inject.

        Returns:
            The escaped inner content, without the surrounding quotes.
        """
        return escape_for_script(value)
