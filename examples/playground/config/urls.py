"""URL configuration: admin + the GraphQL endpoints (with GraphiQL).

v2.0: the legacy "SubscriptionGraphQLView" (one-shot HTTP subscribe/unsubscribe
confirmation) was removed. Queries/mutations are served by "GraphQLView";
subscriptions are served by the native SSE view (HTTP "text/event-stream") and
the native WebSocket consumer (see "config/asgi.py").
"""

import re

from blog.schema import schema
from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.urls import path, re_path
from django.views.static import serve

from django_graphex.subscriptions import SubscriptionClientView
from django_graphex.subscriptions.transports.sse import subscription_sse_view
from django_graphex.views import AuthenticatedGraphQLView, GraphQLView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Queries and mutations over HTTP + GraphiQL. Trailing slash is intentional on
    # all routes: Django's APPEND_SLASH = True redirects /graphql -> /graphql/, but
    # POST-only GraphQL clients (which do not follow redirects) must use the
    # canonical slashed URL. The slash is consistent across all routes.
    path("graphql/", GraphQLView.as_view(graphiql=True)),
    # Subscriptions over Server-Sent Events (HTTP text/event-stream). The native
    # WebSocket transport for the same schema is routed in config/asgi.py.
    # The SSE/WS transports execute against the live graphql-core schema, so pass
    # ``schema.graphql_schema`` (the GraphQLSchema), NOT the DjangoGraphQLSchema
    # wrapper — graphql-core's validate / create_source_event_stream cannot
    # consume the wrapper.
    path("graphql/stream", subscription_sse_view(schema=schema.graphql_schema)),
    # A browser client to try subscriptions live (served from this origin -> no
    # CORS). Defaults match this project's routes (/ws/graphql/ and /graphql/).
    path("graphql/client/", SubscriptionClientView.as_view()),
    # The same schema behind view-level authentication: AuthenticatedGraphQLView
    # (a subclass of GraphQLView) rejects unauthenticated requests with 403 before
    # any query runs. Override `permission_classes` to change the gate. Log in via
    # the Django admin first, then open /graphql/secure/ in the same browser.
    path("graphql/secure/", AuthenticatedGraphQLView.as_view(graphiql=True)),
]


def serve_media(request: HttpRequest, path: str) -> HttpResponse:
    """Serve one uploaded file as an inert download, never as a page.

    Uploads come from anonymous callers and "MEDIA_URL" shares an origin with
    "/admin", so an uploaded HTML or SVG file served inline would run script
    with the admin's cookies. The headers make every file a download that the
    browser neither sniffs nor renders.

    Args:
        request: The incoming HTTP request.
        path: The path of the file under "MEDIA_ROOT".

    Returns:
        response: The file response with the download-only headers added.
    """
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Content-Disposition"] = "attachment"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    return response


# Serve uploaded files (MEDIA_URL -> MEDIA_ROOT) while DEBUG is True, the same
# development-only contract as the static files in config/asgi.py. In production
# a web server or object store on a SEPARATE domain serves media, never Django.
if settings.DEBUG:
    urlpatterns.append(
        re_path(
            rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.*)$", serve_media
        )
    )
