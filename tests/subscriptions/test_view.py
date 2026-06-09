# -*- coding: utf-8 -*-
"""T-VIEW: the HTTP view returns the one-shot subscribe/unsubscribe confirmation."""

import json

from channels.layers import get_channel_layer
from django.test import RequestFactory

from django_graphex.subscriptions import SubscriptionGraphQLView

from .schema import schema

SUBSCRIBE_QUERY = """
subscription {
  userSubscription(channelId: "view-chan", action: UPDATE, operation: SUBSCRIBE, data: [USERNAME]) {
    ok
    error
    stream
    operation
    action
  }
}
"""


def _post(query):
    factory = RequestFactory()
    request = factory.post(
        "/subscriptions/",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    view = SubscriptionGraphQLView.as_view(schema=schema, graphiql=False)
    response = view(request)
    return response


def test_subscribe_over_http_returns_confirmation():
    response = _post(SUBSCRIBE_QUERY)
    assert response.status_code == 200

    payload = json.loads(response.content)
    data = payload["data"]["userSubscription"]
    assert data["ok"] is True
    assert data["error"] is None
    assert data["stream"] == "users"
    assert data["operation"] == "SUBSCRIBE"
    assert data["action"] == "UPDATE"


def test_subscribe_over_http_joins_group():
    from asgiref.sync import async_to_sync

    _post(SUBSCRIBE_QUERY)
    channel_layer = get_channel_layer()

    # The resolver first delivered a register control message to the channel.
    register = async_to_sync(channel_layer.receive)("view-chan")
    assert register["type"] == "subscription.register"
    assert register["group"] == "auth.user-update"

    # And it joined the group: a group_send now reaches the channel.
    async_to_sync(channel_layer.group_send)(
        "auth.user-update", {"type": "subscription.notify", "payload": {}}
    )
    received = async_to_sync(channel_layer.receive)("view-chan")
    assert received["type"] == "subscription.notify"


def test_regular_query_still_works_through_the_view():
    response = _post("query { hello }")
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["data"]["hello"] == "world"


def test_invalid_subscription_returns_validation_errors():
    response = _post(
        'subscription { userSubscription(channelId: "c", action: UPDATE, '
        "operation: SUBSCRIBE) { nope } }"
    )
    payload = json.loads(response.content)
    assert "errors" in payload


def test_missing_query_is_rejected():
    factory = RequestFactory()
    request = factory.post(
        "/subscriptions/", data=json.dumps({}), content_type="application/json"
    )
    view = SubscriptionGraphQLView.as_view(schema=schema, graphiql=False)
    response = view(request)
    assert response.status_code == 400


def test_unparseable_query_returns_errors():
    # A syntactically invalid query -> parse() raises in execute_graphql_request
    # -> ExecutionResult with the parse error (lines 74-75).
    response = _post("subscription { this is { broken")
    payload = json.loads(response.content)
    assert "errors" in payload


def test_subscribe_runtime_error_is_returned_as_errors(monkeypatch):
    # If driving the subscription raises, the view wraps it in errors (104-105).
    from django_graphex.subscriptions import views as views_module

    def _boom(*a, **k):
        raise RuntimeError("subscribe blew up")

    # async_to_sync(self._subscribe_once)(...) -> patch _subscribe_once to raise
    # synchronously by replacing async_to_sync with a passthrough that raises.
    monkeypatch.setattr(views_module, "async_to_sync", lambda fn: _boom)
    response = _post(SUBSCRIBE_QUERY)
    payload = json.loads(response.content)
    assert "errors" in payload
    assert any("subscribe blew up" in e["message"] for e in payload["errors"])


async def test_subscribe_once_returns_execution_result_on_subscribe_error(monkeypatch):
    """_subscribe_once forwards a subscribe-time ExecutionResult unchanged."""
    from graphql import ExecutionResult

    from django_graphex.subscriptions import views as views_module

    sentinel = ExecutionResult(data=None, errors=["boom"])
    monkeypatch.setattr(views_module, "subscribe", lambda *a, **k: sentinel)
    result = await SubscriptionGraphQLView._subscribe_once(None, None)
    assert result is sentinel


async def test_subscribe_once_handles_empty_stream(monkeypatch):
    """_subscribe_once returns an empty result when the stream yields nothing."""
    from django_graphex.subscriptions import views as views_module

    async def _empty():
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(views_module, "subscribe", lambda *a, **k: _empty())
    result = await SubscriptionGraphQLView._subscribe_once(None, None)
    assert result.data is None
    assert result.errors is None
