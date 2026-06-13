"""A Django view serving a self-contained HTML subscriptions client.

Add it to your project's URLConf (like the admin) to get a browser playground for
the subscription engine, served from your own origin (so there is no CORS issue):

    from django_graphex.subscriptions import SubscriptionClientView

    urlpatterns = [
        ...,
        path("graphql/client/", SubscriptionClientView.as_view()),
    ]

The endpoints default to the page's own origin; override "ws_path" / "http_path"
if your routes differ::

    SubscriptionClientView.as_view(ws_path="/ws/graphql/", http_path="/graphql")
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from django.http import HttpRequest, HttpResponse
from django.views import View

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

    Override "ws_path" / "http_path" (as class attributes or via ``as_view``) to
    point the client at your WebSocket and GraphQL routes; they are combined with
    the request's own host in the browser.
    """

    #: WebSocket route the client connects to (combined with the page host).
    ws_path: str = "/ws/graphql/"
    #: HTTP GraphQL route the client posts subscriptions to.
    http_path: str = "/graphql"

    def get(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponse:
        """Render the client HTML with the configured endpoint paths.

        The path values are injected via ``json.dumps`` so that double quotes,
        backslashes, and other special characters are properly escaped before
        they appear inside inline JavaScript string literals.  Injecting raw
        strings would allow XSS if a path contained a double-quote or
        backslash.
        """
        # json.dumps produces a quoted JSON string literal including the
        # surrounding double-quotes, which is valid JavaScript.
        # We strip the outer quotes because the template already wraps the
        # placeholder in a string concatenation context — we inject the
        # *content* only, pre-escaped.
        ws_path_escaped = json.dumps(self.ws_path)[1:-1]
        http_path_escaped = json.dumps(self.http_path)[1:-1]
        html = (
            _template()
            .replace("__WS_PATH__", ws_path_escaped)
            .replace("__HTTP_PATH__", http_path_escaped)
        )
        return HttpResponse(html, content_type="text/html; charset=utf-8")
