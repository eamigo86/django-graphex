"""Schema build / permission smoke tests + the subscription-client served page.

Three groups, all under the PLAYGROUND's own "config.settings":

1. Schema smoke — the playground "blog.schema" builds into a live
   graphql-core schema with the expected query/mutation/subscription roots.

2. Permission smoke — a protected field ("me") served by "GraphQLView" (with
   "AuthenticatedFieldsMiddleware" wired in "DJANGO_GRAPHEX.MIDDLEWARE") is denied
   for an anonymous request, but a public field is served.

3. Subscription client (RANK 19, LEAN) — "SubscriptionClientView" at
   "/graphql/client/" serves the self-contained HTML client with BOTH
   transports wired (graphql-transport-ws + graphql-sse) and the playground's
   own WS/HTTP endpoints injected. This is the lightest meaningful coverage of
   the browser client WITHOUT adding a headless-browser dependency; the full
   live browser round-trip is deferred to 2.1 (per the v2.0 release audit).

Run from this directory:

    cd examples/playground
    DJANGO_SETTINGS_MODULE=config.settings python -m pytest -q
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.test import Client

# --------------------------------------------------------------------------- #
# 1) Schema smoke                                                              #
# --------------------------------------------------------------------------- #


def test_playground_schema_builds() -> None:
    """Assert the playground schema compiles into a live graphql-core schema.

    Verifies the query, mutation and subscription root types exist and that the
    expected public/private query roots, all three subscriptions and the Base64
    upload mutation are mounted.
    """
    from blog.schema import schema

    gs = schema.graphql_schema
    assert gs.query_type is not None
    assert gs.mutation_type is not None
    assert gs.subscription_type is not None

    # Public + private query roots are unioned onto the query type.
    qfields = set(gs.query_type.fields)
    assert {"serverTime", "posts", "authors", "me", "myNotes"} <= qfields

    # All three subscriptions are mounted.
    sfields = set(gs.subscription_type.fields)
    assert {"postSubscription", "commentSubscription", "noteSubscription"} <= sfields

    # The Base64 upload mutation is present (lazy-thunk arg pattern compiled OK).
    mfields = set(gs.mutation_type.fields)
    assert {"postCreate", "uploadDocument", "createCategory"} <= mfields


def test_readme_nested_comments_query_validates() -> None:
    """Assert the README's flagship nested query still validates.

    "CommentModelType" is a write-only host over the same model as the
    hand-declared, cursor-paginated "CommentListType". A host that does not
    serve "list" must not take the model's container slot away from the one
    that does, or the nested "comments" list loses the "pageInfo" every README
    query selects.
    """
    from graphql import parse, validate

    from blog.schema import schema

    query = (
        "{ posts { results { id comments { results { id }"
        " pageInfo { hasNextPage } } } } }"
    )

    errors = validate(schema.graphql_schema, parse(query))

    assert errors == [], [str(error) for error in errors]


# --------------------------------------------------------------------------- #
# 2) Permission smoke — protected field requires auth (through GraphQLView)    #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_protected_field_requires_auth(client: Client) -> None:
    """Assert an anonymous request selecting the protected "me" field is denied.

    "me" is a private root field; "AuthenticatedFieldsMiddleware" (wired in
    "DJANGO_GRAPHEX.MIDDLEWARE") blocks it for an unauthenticated request. The public
    "serverTime" field in the same request still resolves to prove the gate is
    field-scoped, not request-scoped.

    Args:
        client: The Django test client issuing the unauthenticated POST.
    """
    resp = client.post(
        "/graphql/",
        data=json.dumps({"query": "{ serverTime me { id username } }"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["errors"], "the protected `me` field must produce an auth error"
    joined = " ".join(e.get("message", "") for e in body["errors"]).lower()
    assert "authenticat" in joined or "permission" in joined


@pytest.mark.django_db
def test_authenticated_request_can_read_protected_field(
    client: Client, django_user_model: type[AbstractBaseUser]
) -> None:
    """Assert a logged-in session may read the protected "me" field.

    Args:
        client: The Django test client used to log in and issue the query.
        django_user_model: The active user model, used to create the test user.
    """
    user = django_user_model.objects.create_user(
        username="alice", password="pw12345678"
    )
    assert client.login(username="alice", password="pw12345678")

    resp = client.post(
        "/graphql/",
        data=json.dumps({"query": "{ me { id username } }"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert not body.get("errors"), f"unexpected errors: {body.get('errors')}"
    assert body["data"]["me"]["username"] == "alice"
    assert str(body["data"]["me"]["id"]) == str(user.pk)


@pytest.mark.django_db
def test_public_field_served_anonymously(client: Client) -> None:
    """Assert a purely public query resolves for an anonymous request.

    Args:
        client: The Django test client issuing the unauthenticated POST.
    """
    resp = client.post(
        "/graphql/",
        data=json.dumps({"query": "{ serverTime }"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert not body.get("errors")
    assert body["data"]["serverTime"]


# --------------------------------------------------------------------------- #
# 3) Subscription client served page (RANK 19, LEAN — no browser dependency)  #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_subscription_client_page_serves_both_transports(client: Client) -> None:
    """Assert "/graphql/client/" serves the HTML client with BOTH transports wired.

    Asserts the served page is the real subscription client: it speaks
    graphql-transport-ws (the WS subprotocol + connection_init handshake) AND
    graphql-sse (an EventSource against the text/event-stream endpoint), and the
    transport-selection toggle is present. This is the lightest meaningful
    coverage of the browser client; a full headless-browser round-trip is
    intentionally deferred to 2.1 (no Playwright/Selenium dependency added).

    Args:
        client: The Django test client fetching the served client page.
    """
    resp = client.get("/graphql/client/")
    assert resp.status_code == 200
    assert resp["content-type"].startswith("text/html")

    html = resp.content.decode("utf-8")

    # WS transport (graphql-transport-ws) is wired.
    assert "graphql-transport-ws" in html
    assert "connection_init" in html
    assert "new WebSocket(" in html

    # SSE transport (graphql-sse / text/event-stream) is wired.
    assert "graphql-sse" in html
    assert "EventSource" in html
    assert "text/event-stream" in html

    # A transport selector lets the user choose WS vs SSE.
    assert "gdsx-mode" in html or "Transport" in html


@pytest.mark.django_db
def test_subscription_client_endpoints_match_playground_routes(client: Client) -> None:
    """Assert the served client injects the playground's own WS + HTTP endpoints.

    "SubscriptionClientView" replaces "__WS_PATH__" / "__HTTP_PATH__" in the
    template with its configured paths. The placeholders must be GONE (fully
    substituted) and the default playground routes (/ws/graphql/ and /graphql)
    must appear in the rendered JS so the client connects to the right endpoints.

    Args:
        client: The Django test client fetching the served client page.
    """
    resp = client.get("/graphql/client/")
    html = resp.content.decode("utf-8")

    # Placeholders are fully substituted in the served page.
    assert "__WS_PATH__" not in html
    assert "__HTTP_PATH__" not in html

    # The default playground routes are wired into the client JS.
    assert "/ws/graphql/" in html
    assert "/graphql" in html
