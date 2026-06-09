"""URL configuration: admin + the GraphQL endpoints (with GraphiQL)."""

from django.contrib import admin
from django.urls import path

from django_graphex import AuthenticatedGraphQLView
from django_graphex.subscriptions import (
    SubscriptionClientView,
    SubscriptionGraphQLView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    # SubscriptionGraphQLView resolves the one-shot subscribe/unsubscribe
    # confirmation over HTTP; the streaming runs over the websocket (see asgi.py).
    path("graphql", SubscriptionGraphQLView.as_view(graphiql=True)),
    # A browser client to try subscriptions live (served from this origin -> no
    # CORS). Defaults match this project's routes (/ws/graphql/ and /graphql).
    path("graphql/client/", SubscriptionClientView.as_view()),
    # The same schema behind view-level authentication: AuthenticatedGraphQLView
    # (a subclass of GraphQLView) rejects unauthenticated requests with 403 before
    # any query runs. Override `permission_classes` to change the gate. Log in via
    # the Django admin first, then open /graphql/secure in the same browser.
    path(
        "graphql/secure",
        AuthenticatedGraphQLView.as_view(graphiql=True),
    ),
]
