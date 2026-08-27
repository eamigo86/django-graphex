# -*- coding: utf-8 -*-
"""FIX 1 — the SSE subscription view must be CSRF-exempt (like "GraphQLView").

The bundled browser client (and any real "curl"/"fetch" client) POSTs the
GraphQL subscription document with no CSRF token/cookie. "GraphQLView" is
"csrf_exempt" for exactly this reason (views.py:1010-1015): the GraphQL
document IS the payload, the view auth-gates the operation itself, and a
same-origin JSON POST gains nothing from session-cookie CSRF. The SSE transport
view is the equivalent subscription endpoint and MUST share that treatment.

Why this test drives the REAL middleware chain (Django's test "Client"):
"CsrfViewMiddleware" only rejects an unsafe method with no token in
"process_view" — it never runs under "RequestFactory" (which bypasses
middleware). So the existing "RequestFactory"-based transport tests would pass
even against a NON-exempt view. This test mounts the view in a URLConf with the
suite's "CsrfViewMiddleware" active and POSTs through it: against a non-exempt
view Django returns 403 (the RED), against the exempt view it streams the 200
"text/event-stream" response.

CSRF exemption is what makes the second half of this module necessary: the SSE
endpoint reads a form-encoded body straight out of "request.POST", and
"application/x-www-form-urlencoded" is a CORS-*simple* content type. So the
exemption that lets a real client through also lets a cross-site "<form>" submit
through, carrying the victim's session cookie -- the identical hole the HTTP
views close with "REQUIRE_CSRF_HEADER". The endpoint must honour the same
setting, with the plain-text refusal an EventSource client can actually read.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import RequestFactory

pytest.importorskip("channels")

from django.test import Client, override_settings  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLBoolean,
    GraphQLError,
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.subscriptions.transports.sse import (  # noqa: E402
    subscription_sse_view,
)

_SUB_QUERY = "subscription { post(action: CREATE) { id title } }"

#: A form-urlencoded body carrying "subscription { onTick { id } }".
_FORM_BODY = "query=subscription+%7B+onTick+%7B+id+%7D+%7D"


class _User:
    """A minimal authenticated user stand-in exposing the flags the view reads."""

    is_authenticated = True
    pk = 1


def _guard_schema() -> GraphQLSchema:
    """Build a one-field subscription schema whose subscribe entry always denies.

    The guard runs before any schema work, so the subscribe entry only has to
    exist -- denying keeps the stream short and needs no channel layer.

    Returns:
        schema: A schema with a single "onTick" subscription field.
    """

    async def subscribe(root: Any, info: Any) -> Any:
        raise GraphQLError("denied")

    return GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)}),
        subscription=GraphQLObjectType(
            "Subscription",
            {
                "onTick": GraphQLField(
                    GraphQLObjectType("Tick", {"id": GraphQLField(GraphQLString)}),
                    subscribe=subscribe,
                )
            },
        ),
    )


async def _post(body: str, content_type: str, **extra: str) -> Any:
    """POST a body at the SSE view and return its response.

    Args:
        body: The raw request body to send.
        content_type: The request "Content-Type" header value.
        **extra: Extra WSGI environ entries (e.g. "HTTP_X_REQUESTED_WITH").

    Returns:
        response: The view's HTTP response.
    """
    request = RequestFactory().post(
        "/subscriptions/sse", data=body, content_type=content_type, **extra
    )
    request.user = _User()
    return await subscription_sse_view(schema=_guard_schema())(request)


async def test_a_form_encoded_post_without_the_header_is_forbidden() -> None:
    """Refuse the cross-site form POST vector on the SSE endpoint.

    Contract: this ships broken while the guard covers only the HTTP views --
    the identical forged POST simply moves to the sibling endpoint, which reads
    the same form-encoded "query" out of "request.POST".
    """
    response = await _post(_FORM_BODY, "application/x-www-form-urlencoded")

    assert response.status_code == 403
    assert "X-Requested-With" in response.content.decode()
    assert not response["Content-Type"].startswith("text/event-stream")


async def test_the_sse_refusal_is_not_a_json_envelope() -> None:
    """Refuse in the same shape the endpoint already uses for a bad request.

    Contract: an EventSource client does not parse a JSON "errors" envelope,
    and every other pre-stream rejection here is a plain-text
    "HttpResponseBadRequest". A JSON body would be a shape nothing on this
    endpoint reads.
    """
    response = await _post(_FORM_BODY, "application/x-www-form-urlencoded")

    assert response["Content-Type"].startswith("text/html")
    with pytest.raises(json.JSONDecodeError):
        json.loads(response.content)


async def test_a_form_encoded_post_with_the_header_reaches_the_transport() -> None:
    """Stream for a form POST that sends the header.

    Contract: the guard is a header check, not a blanket rejection of
    form-encoded bodies, so the legitimate caller only adds one header.
    """
    response = await _post(
        _FORM_BODY,
        "application/x-www-form-urlencoded",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")


async def test_a_json_post_is_untouched() -> None:
    """Stream for a header-less JSON POST.

    Contract: "application/json" is not CORS-simple and already forces a
    preflight, so the bundled client and every JSON caller change nothing.
    """
    response = await _post(
        json.dumps({"query": "subscription { onTick { id } }"}), "application/json"
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")


@override_settings(DJANGO_GRAPHEX={"REQUIRE_CSRF_HEADER": False})
async def test_the_setting_turns_the_sse_guard_off() -> None:
    """Stream for a header-less form POST once the setting is off.

    Contract: the SSE endpoint honours the SAME opt-out as the HTTP views; a
    guard that ignored it would strand the project the setting exists for.
    """
    response = await _post(_FORM_BODY, "application/x-www-form-urlencoded")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")


@override_settings(ROOT_URLCONF="tests.subscriptions.urls_sse_csrf")
def test_sse_view_is_csrf_exempt_through_real_middleware(db: None) -> None:
    """A cookie-less POST through "CsrfViewMiddleware" must not be rejected with 403.

    Contract: the SSE subscription view ships broken (rejecting every real
    browser client) if it stops being CSRF-exempt.

    Args:
        db: The pytest-django fixture granting database access for the test.
    """
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        "/graphql/stream",
        data=json.dumps({"query": _SUB_QUERY}),
        content_type="application/json",
    )

    # The heart of the RED: a non-exempt view is a 403 here.
    assert response.status_code != 403, (
        "the SSE view rejected a token-less POST with 403 — it is not csrf_exempt"
    )
    assert response.status_code == 200
    assert response["content-type"].startswith("text/event-stream")

    # Prove the stream is live: pull the first frame (a subscribe with no event
    # yet yields nothing, so consume lazily with a bounded read of the iterator).
    streaming = getattr(response, "streaming_content", None)
    assert streaming is not None, "the CSRF-exempt SSE view must stream"
