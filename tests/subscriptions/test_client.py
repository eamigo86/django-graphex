# -*- coding: utf-8 -*-
"""T-CLIENT: the SubscriptionClientView serves the HTML client."""

from django.test import RequestFactory

from django_graphex.subscriptions import SubscriptionClientView


def test_client_view_renders_default_paths():
    request = RequestFactory().get("/graphql/client/")
    response = SubscriptionClientView.as_view()(request)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    body = response.content.decode()
    assert "<!DOCTYPE html>" in body
    assert "GraphQL Subscriptions Client" in body
    # default endpoint paths are injected, placeholders are gone
    assert "/ws/graphql/" in body
    assert "/graphql" in body
    assert "__WS_PATH__" not in body and "__HTTP_PATH__" not in body


def test_client_view_custom_paths():
    request = RequestFactory().get("/anything")
    view = SubscriptionClientView.as_view(ws_path="/sock/", http_path="/api/graphql")
    body = view(request).content.decode()
    assert "/sock/" in body
    assert "/api/graphql" in body
