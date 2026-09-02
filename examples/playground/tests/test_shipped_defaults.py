"""The security defaults this playground inherits without configuring them.

"config/settings.py" spells out the settings it changes. Two of the settings
that matter most to a reader copying this project are the ones it does NOT
spell out, because they ship ON:

1. "REQUIRE_CSRF_HEADER" (default True) — a POST of a CORS-simple content type
   ("application/x-www-form-urlencoded", "multipart/form-data", "text/plain",
   or no content type at all) is answered HTTP 403 unless it carries the
   "X-Requested-With" header. GraphiQL and any "application/json" client are
   unaffected; a multipart upload client is not, which is why the README says
   so next to the upload demo.

2. "MAX_SUBSCRIPTIONS_PER_CONNECTION" (default 50) — one WebSocket may hold
   that many concurrent operations. It is pinned in
   "test_subscription_transports_e2e.py", where the WS communicator lives.

A default is exactly the thing a project forgets it depends on, so these run
against the real views wired in "config/urls.py".

Run them from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q --no-migrations
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest

from django_graphex.settings import graphql_api_settings

if TYPE_CHECKING:
    from django.test import Client

#: The playground's simplest public query, form-encoded the way a plain HTML
#: "<form>" would send it -- which is the shape the guard exists to refuse.
_FORM_BODY = urlencode({"query": "{ serverTime }"})
_FORM_TYPE = "application/x-www-form-urlencoded"


def test_the_csrf_header_guard_ships_on() -> None:
    """Assert the playground inherits "REQUIRE_CSRF_HEADER" without setting it.

    The README documents the header requirement as a default rather than as
    playground configuration, so the claim is only true while the project
    leaves the key alone.
    """
    from django.conf import settings

    assert "REQUIRE_CSRF_HEADER" not in settings.DJANGO_GRAPHEX
    assert graphql_api_settings.REQUIRE_CSRF_HEADER is True


def test_the_subscription_cap_ships_on() -> None:
    """Assert the playground inherits "MAX_SUBSCRIPTIONS_PER_CONNECTION" at 50.

    The behaviour AT the cap is pinned in
    "test_subscription_transports_e2e.py", which lowers the value so the
    boundary is reachable in a test. That leaves nothing asserting the value a
    reader who copies "config/settings.py" actually gets, which is this.
    """
    from django.conf import settings

    assert "MAX_SUBSCRIPTIONS_PER_CONNECTION" not in settings.DJANGO_GRAPHEX
    assert graphql_api_settings.MAX_SUBSCRIPTIONS_PER_CONNECTION == 50


@pytest.mark.django_db
def test_a_form_encoded_post_without_the_header_is_refused(client: Client) -> None:
    """Assert a CORS-simple POST carrying no "X-Requested-With" is a 403.

    This is the shape a cross-site "<form>" posts: the browser sends it with no
    preflight and attaches the victim's session cookie. The refusal happens
    before the body is read, so a valid document gets no further than an
    invalid one.

    Args:
        client: The Django test client issuing the form-encoded POST.
    """
    resp = client.post(
        "/graphql/",
        data=_FORM_BODY,
        content_type=_FORM_TYPE,
    )

    assert resp.status_code == 403
    assert "X-Requested-With" in resp.content.decode()


@pytest.mark.django_db
def test_the_same_post_is_served_once_the_header_is_present(client: Client) -> None:
    """Assert adding the header is the whole fix, exactly as documented.

    The value is never inspected, so any value serves. Nothing else about the
    request changes between this test and the one above.

    Args:
        client: The Django test client issuing the form-encoded POST.
    """
    resp = client.post(
        "/graphql/",
        data=_FORM_BODY,
        content_type=_FORM_TYPE,
        headers={"x-requested-with": "XMLHttpRequest"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert not body.get("errors"), body
    assert body["data"]["serverTime"]


@pytest.mark.django_db
def test_a_json_post_never_needed_the_header(client: Client) -> None:
    """Assert the guard costs GraphiQL and every JSON client nothing.

    "application/json" is not a CORS-simple content type, so a cross-origin
    POST of it already requires a preflight the attacker page cannot pass. The
    control proves the 403 above is the content type talking, not the endpoint.

    Args:
        client: The Django test client issuing the JSON POST.
    """
    resp = client.post(
        "/graphql/", data='{"query": "{ serverTime }"}', content_type="application/json"
    )

    assert resp.status_code == 200
    assert not resp.json().get("errors")
