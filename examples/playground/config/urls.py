"""URL configuration: admin + the GraphQL endpoints (with GraphiQL).

v2.0: the legacy ``SubscriptionGraphQLView`` (one-shot HTTP subscribe/unsubscribe
confirmation) was removed. Queries/mutations are served by ``GraphQLView``;
subscriptions are served by the native SSE view (HTTP ``text/event-stream``) and
the native WebSocket consumer (see ``config/asgi.py``).
"""

from django.contrib import admin
from django.urls import path

from django_graphex import AuthenticatedGraphQLView, GraphQLView
from django_graphex.subscriptions import SubscriptionClientView
from django_graphex.subscriptions.transports.sse import subscription_sse_view

from blog.schema import schema

urlpatterns = [
    path("admin/", admin.site.urls),
    # Queries and mutations over HTTP + GraphiQL. Trailing slash is intentional on
    # all routes: Django's APPEND_SLASH = True redirects /graphql -> /graphql/, but
    # POST-only GraphQL clients (which do not follow redirects) must use the
    # canonical slashed URL. The slash is consistent across all routes.
    path("graphql/", GraphQLView.as_view(graphiql=True)),
    # Subscriptions over Server-Sent Events (HTTP text/event-stream). The native
    # WebSocket transport for the same schema is routed in config/asgi.py.
    path("graphql/stream", subscription_sse_view(schema=schema)),
    # A browser client to try subscriptions live (served from this origin -> no
    # CORS). Defaults match this project's routes (/ws/graphql/ and /graphql/).
    path("graphql/client/", SubscriptionClientView.as_view()),
    # The same schema behind view-level authentication: AuthenticatedGraphQLView
    # (a subclass of GraphQLView) rejects unauthenticated requests with 403 before
    # any query runs. Override `permission_classes` to change the gate. Log in via
    # the Django admin first, then open /graphql/secure/ in the same browser.
    path("graphql/secure/", AuthenticatedGraphQLView.as_view(graphiql=True)),
]
