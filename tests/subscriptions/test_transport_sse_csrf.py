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
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("channels")

from django.test import Client, override_settings  # noqa: E402

_SUB_QUERY = "subscription { post(action: CREATE) { id title } }"


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
