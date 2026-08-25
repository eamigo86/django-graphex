# -*- coding: utf-8 -*-
"""Security regressions fixed in 2.0.1 (subscription stack).

Two confirmed criticals against the published 2.0.0 subscription engine:

  * **Client filters were an oracle over undeclared columns.** The subscription
    meta silently dropped "only_fields"/"exclude_fields", so the declared output
    set was the model's FULL column list, and filter-key validation only checked
    the segment before the first "__" — so "password__startswith" and
    "groups__name__startswith" were both accepted and evaluated as ORM lookups at
    delivery time (a boolean oracle over a password hash).
  * **"private_subscription" protected nothing on the transports.**
    "DJANGO_GRAPHEX['MIDDLEWARE']" was read ONLY by "GraphQLView"; the SSE and WS
    transports never built a "MiddlewareManager", and subscriptions are served
    ONLY by those transports — so an "AnonymousUser" received events from a field
    the schema reported in "gdx_protected_fields".
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from graphql import GraphQLSchema  # noqa: E402

from django_graphex.security import AuthenticatedFieldsMiddleware  # noqa: E402
from django_graphex.subscriptions import Subscription  # noqa: E402
from tests.models import Post, SecretLedger, SecretRecord  # noqa: E402

# The WS consumer touches the DB connection registry on every dispatched message
# and the broadcast test needs a real commit for its "on_commit" callback, so the
# whole module runs against a real transactional database.
pytestmark = pytest.mark.django_db(transaction=True)


_SECRET_QUERY = "subscription { secretRecord(action: CREATE) { id title } }"

# Records every field name the marker middleware saw, proving the configured
# chain ran on BOTH the subscribe entry and the per-event delivery execute.
_MIDDLEWARE_CALLS: list[str] = []


class _MarkerMiddleware:
    """Record every resolved field name so a test can prove the chain ran."""

    def resolve(self, next_: Any, root: Any, info: Any, **kwargs: Any) -> Any:
        """Record "info.field_name" and delegate to the next resolver.

        Args:
            next_: The next resolver in the middleware chain.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the current field.
            **kwargs: Arguments forwarded to the next resolver.

        Returns:
            The result of the next resolver.
        """
        _MIDDLEWARE_CALLS.append(info.field_name)
        return next_(root, info, **kwargs)


def _auth_settings(*extra: Any) -> Any:
    """Return an "override_settings" wiring the auth middleware for subscriptions.

    Args:
        *extra: Additional middleware entries appended after the auth middleware.

    Returns:
        The configured "override_settings" context manager.
    """
    return override_settings(
        DJANGO_GRAPHEX={
            "SCHEMA": "tests.schema.schema",
            "MIDDLEWARE": [AuthenticatedFieldsMiddleware, *extra],
        }
    )


def _build_private_schema() -> GraphQLSchema:
    """Assemble a schema whose only subscription field is declared PRIVATE.

    Returns:
        The native "GraphQLSchema" exposing "secretRecord" under
        "private_subscription".
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    class SecretRecordType(DjangoModelType):
        class Meta:
            model = SecretRecord
            stream = "secret_records"
            payload_mode = "full"

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class PrivateSubscription(ObjectType):
        secret_record = SecretRecordType.SubscriptionField()

    compile_all_outputs()
    schema = DjangoGraphQLSchema(query=Query, private_subscription=PrivateSubscription)
    assert schema.graphql_schema.extensions["gdx_protected_fields"] == frozenset(
        {"secretRecord"}
    )
    return schema.graphql_schema


class _RequestUser:
    """A minimal authenticated user stand-in for the SSE transport."""

    is_authenticated = True
    pk = 1


def _make_request(query: str, *, user: Any) -> Any:
    """Build an HTTP request carrying a GraphQL subscription body.

    Args:
        query: The GraphQL subscription document sent as the request body.
        user: The user attached to the request.

    Returns:
        The constructed Django test request.
    """
    from django.test import RequestFactory

    request = RequestFactory().post(
        "/subscriptions/sse",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    request.user = user
    return request


async def _drain(response: Any, *, max_frames: int = 4) -> list[str]:
    """Pull up to "max_frames" SSE frames from a streaming response.

    Args:
        response: The streaming HTTP response to read frames from.
        max_frames: The maximum number of frames to pull before stopping.

    Returns:
        The decoded frame strings, stopping early on the "complete" frame.
    """
    frames: list[str] = []
    aiter = response.streaming_content.__aiter__()
    for _ in range(max_frames):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=2.0)
        except (StopAsyncIteration, TimeoutError):
            break
        frames.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
        if "event: complete" in frames[-1]:
            break
    aclose = getattr(aiter, "aclose", None)
    if aclose is not None:
        await aclose()
    return frames


def _notify(group: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build a producer-shaped "subscription.notify" envelope.

    Args:
        group: The channel-layer group the message targets.
        data: The serialized payload data embedded in the message.

    Returns:
        The assembled notify message dict.
    """
    return {
        "type": "subscription.notify",
        "stream": "secret_records",
        "group": group,
        "pk": data.get("id", 1),
        "payload": {"action": "create", "model": "tests.secretrecord", "data": data},
    }


# ---------------------------------------------------------------------------
# CRITICAL 3 — private_subscription must be enforced on BOTH transports.
# ---------------------------------------------------------------------------


async def test_sse_anonymous_is_denied_on_a_private_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An AnonymousUser must never join a group for a PRIVATE subscription field.

    Contract: this test ships broken if the SSE transport starts a source (or
    delivers data) for a field the schema reports in "gdx_protected_fields"
    while "AuthenticatedFieldsMiddleware" is configured.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    with _auth_settings():
        schema = _build_private_schema()
        view = sse.subscription_sse_view(schema=schema)
        response = await view(_make_request(_SECRET_QUERY, user=AnonymousUser()))

        started = sse.get_started_source(response)
        assert started is None, (
            "an anonymous subscriber joined groups on a PRIVATE subscription: "
            f"{getattr(started, 'joined_groups', None)}"
        )

        frames = await _drain(response)

    body = "".join(frames)
    assert "Authentication required." in body, body
    assert '"title"' not in body, body


async def test_ws_anonymous_is_denied_on_a_private_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The WS transport must deny an anonymous PRIVATE subscribe with an error frame.

    Contract: this test ships broken if the WS consumer starts a source for a
    protected field without an authenticated scope user.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import ws

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    with _auth_settings():
        schema = _build_private_schema()
        consumer = ws.subscription_ws_consumer(schema=schema, init_timeout=5.0)
        communicator = WebsocketCommunicator(
            consumer.as_asgi(), "/graphql/", subprotocols=["graphql-transport-ws"]
        )
        communicator.scope["user"] = AnonymousUser()
        connected, _ = await communicator.connect()
        assert connected
        await communicator.send_json_to({"type": "connection_init"})
        ack = await communicator.receive_json_from(timeout=2)
        assert ack["type"] == "connection_ack"

        await communicator.send_json_to(
            {"type": "subscribe", "id": "1", "payload": {"query": _SECRET_QUERY}}
        )
        await asyncio.sleep(0.3)
        live = ws.get_live_consumer(communicator.scope)
        started = live.started_source("1") if live is not None else None
        assert started is None, (
            "an anonymous WS subscriber joined groups on a PRIVATE subscription: "
            f"{getattr(started, 'joined_groups', None)}"
        )

        message = await communicator.receive_json_from(timeout=2)
        assert message["type"] == "error", message
        assert "Authentication required." in json.dumps(message["payload"])
        await communicator.disconnect()


async def test_authenticated_subscriber_still_receives_events_over_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An authenticated subscriber keeps receiving events with the chain wired.

    Also proves the configured middleware chain runs on the PER-EVENT delivery
    "execute": nested field names are only reachable from the delivery path.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    _MIDDLEWARE_CALLS.clear()

    with _auth_settings(_MarkerMiddleware):
        schema = _build_private_schema()
        view = sse.subscription_sse_view(schema=schema)
        response = await view(_make_request(_SECRET_QUERY, user=_RequestUser()))

        started = sse.get_started_source(response)
        assert started is not None, "an authenticated subscriber must join a group"

        group = started.joined_groups[0]
        await layer.group_send(group, _notify(group, {"id": 7, "title": "hello"}))
        frames = await _drain(response, max_frames=1)

    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["data"]["secretRecord"] == {"id": "7", "title": "hello"}
    assert "secretRecord" in _MIDDLEWARE_CALLS
    assert "title" in _MIDDLEWARE_CALLS, (
        "the configured middleware chain never ran on the per-event delivery "
        f"execute: {_MIDDLEWARE_CALLS}"
    )


# ---------------------------------------------------------------------------
# CRITICAL 2 — the projection must be honored and full filter keys validated.
# ---------------------------------------------------------------------------


class _ProjectedLedgerSubscription(Subscription):
    """A ledger subscription that projects the sensitive column out."""

    class Meta:
        """Declare the model, stream and the security projection."""

        model = SecretLedger
        stream = "secret_ledger"
        payload_mode = "full"
        exclude_fields = ("secret",)


class _PostSubscription(Subscription):
    """An unprojected post subscription (every serialized column declared)."""

    class Meta:
        """Declare the model and stream with no projection."""

        model = Post
        stream = "security_posts"
        payload_mode = "full"


def _declared(sub: type) -> set[str]:
    """Return the declared output field names carried on a subscription's spec.

    Args:
        sub: The "Subscription" subclass whose native spec is built.

    Returns:
        The spec's declared output field names.
    """
    return sub._build_native_spec(None, None).declared_output_fields


def test_exclude_fields_removes_the_column_from_the_declared_filter_set() -> None:
    """A projected-out column must not be a declared subscription output field.

    Contract: this test ships broken if "Meta.exclude_fields" is swallowed and
    the backend's unprojected column list reaches the filter-key validator.
    """
    declared = _declared(_ProjectedLedgerSubscription)
    assert "label" in declared
    assert "secret" not in declared


def test_exclude_fields_keeps_the_column_out_of_the_event_payload(
    captured_group_sends: list[tuple[str, dict[str, Any]]],
) -> None:
    """A projected-out column must never be broadcast in the event payload.

    Args:
        captured_group_sends: The (group, message) pairs recorded by the fixture.
    """
    _ProjectedLedgerSubscription.get_binding()
    SecretLedger.objects.create(label="public", secret="pbkdf2_sha256$hash")

    payloads = [
        message["payload"]["data"]
        for _group, message in captured_group_sends
        if message["stream"] == "secret_ledger"
    ]
    assert payloads, "the projected subscription broadcast nothing"
    for data in payloads:
        assert data["label"] == "public"
        assert "secret" not in data, data


def test_filter_key_on_a_projected_out_column_is_rejected() -> None:
    """A filter rooted on a projected-out column must raise at subscribe time.

    Contract: this test ships broken if the projection is honored only on the
    payload and not on the set client filter keys must root on.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    with pytest.raises(ValueError, match="not a declared output field"):
        _validate_client_filters(
            {"secret__startswith": "pbkdf2"},
            _declared(_ProjectedLedgerSubscription),
            model=SecretLedger,
        )


def test_relation_traversal_filter_keys_are_rejected() -> None:
    """A key traversing a relation into another model's columns must be rejected.

    Contract: this test ships broken if only the segment before the first "__"
    is validated — "tags__label__startswith" then reaches the ORM as a boolean
    oracle over the related model's columns even though "label" is not a field
    of the subscribed model.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = _declared(_PostSubscription)
    assert "tags" in declared, "the traversal root must itself be declared"

    with pytest.raises(ValueError, match="not a valid Django lookup"):
        _validate_client_filters(
            {"tags__label__startswith": "adm"}, declared, model=Post
        )
    with pytest.raises(ValueError, match="not a valid Django lookup"):
        _validate_client_filters({"author__name": "alice"}, declared, model=Post)


def test_equality_and_membership_lookups_stay_accepted() -> None:
    """The documented scoping feature ("filters: { post: 7 }") must keep working.

    Contract: this test ships broken if the lookup allow list also rejects the
    equality/membership forms scoping is built on — a bare field name, an
    explicit "exact"/"iexact", "in", or "isnull".
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = _declared(_PostSubscription)
    _validate_client_filters({"author": 1}, declared, model=Post)
    _validate_client_filters({"author__in": [1, 2]}, declared, model=Post)
    _validate_client_filters({"title__exact": "urgent"}, declared, model=Post)
    _validate_client_filters({"title__iexact": "urgent"}, declared, model=Post)
    _validate_client_filters({"category__isnull": True}, declared, model=Post)
    # No model on the spec (a bare driver spec): the base Field lookup registry
    # is the conservative fallback, so the allowed suffixes still resolve.
    _validate_client_filters({"title__iexact": "urgent"}, declared)


def test_declared_name_that_is_not_a_model_field_falls_back_to_base_lookups() -> None:
    """A declared name with no matching model field must not blow up the validator.

    The base "Field" lookup registry is the conservative fallback, so an allowed
    suffix passes the registry gate and a relation-style segment is still
    rejected there. Without a model to check against, that is the whole check.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = {"computed"}
    _validate_client_filters({"computed__iexact": "x"}, declared)
    with pytest.raises(ValueError, match="not a valid Django lookup"):
        _validate_client_filters({"computed__label": "x"}, declared, model=Post)


def test_a_key_the_orm_cannot_resolve_is_rejected_at_subscribe() -> None:
    """A key the ORM refuses must be rejected at subscribe, not at delivery.

    Contract: this test ships broken if the validator stops at the field's
    DECLARED lookup registry. That registry is wider than what the query
    compiler accepts: a to-many field declares "iexact" and then refuses it, and
    a declared name with no model field behind it resolves to nothing at all.
    Delivery runs ".filter(pk=..., **filters).exists()", so anything the ORM
    refuses used to raise inside the delivery loop — after the SSE 200 was
    committed, and with no frame at all on WebSocket.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = _declared(_PostSubscription)
    with pytest.raises(ValueError, match="not a valid database lookup"):
        _validate_client_filters({"tags__iexact": 1}, declared, model=Post)
    with pytest.raises(ValueError, match="not a valid database lookup"):
        _validate_client_filters({"computed__iexact": "x"}, {"computed"}, model=Post)


# ---------------------------------------------------------------------------
# CRITICAL 2 (residual) — the lookup ALLOW LIST.
#
# Honoring the projection closed the oracle only for projected-out columns. In
# the DEFAULT configuration (no "only_fields"/"exclude_fields") every serialized
# column is declared, so "password__startswith" was still accepted and delivery
# still ran it as ".filter(pk=..., **client_filters).exists()" — a boolean
# oracle over a column the subscriber cannot even select (id-only mode delivers
# "null" for it). What makes that oracle EXPLOITABLE is incremental extraction:
# ordered and pattern lookups let an attacker walk a secret prefix-by-prefix or
# binary-search it. Equality and membership do not — they force a whole-value
# guess. So the allowed suffixes are exactly {exact, iexact, in, isnull}.
# ---------------------------------------------------------------------------


class _UnprojectedLedgerSubscription(Subscription):
    """A ledger subscription with NO projection: every column stays declared."""

    class Meta:
        """Declare the model and stream with the default (absent) projection."""

        model = SecretLedger
        stream = "secret_ledger_unprojected"
        payload_mode = "full"


@pytest.mark.parametrize(
    "key",
    [
        "secret__startswith",
        "secret__istartswith",
        "secret__endswith",
        "secret__iendswith",
        "secret__contains",
        "secret__icontains",
        "secret__regex",
        "secret__iregex",
        "secret__gt",
        "secret__gte",
        "secret__lt",
        "secret__lte",
        "secret__range",
        "created__gt",
        "created__year",
        "created__year__gte",
        "created__date",
    ],
)
def test_ordered_and_pattern_lookups_are_rejected_on_declared_fields(key: str) -> None:
    """An ordered or pattern lookup must be rejected even on a DECLARED column.

    Contract: this test ships broken if the validator only checks that a suffix
    is a registered Django lookup. Every key here roots on a declared output
    field of an UNPROJECTED subscription — the default configuration — and each
    one supports incremental extraction of a value the subscriber cannot read.

    Args:
        key: The client filter key expected to be rejected.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = _declared(_UnprojectedLedgerSubscription)
    assert "secret" in declared, "the unprojected subscription must declare 'secret'"

    with pytest.raises(ValueError, match="is not an allowed lookup"):
        _validate_client_filters({key: "pbkdf2"}, declared, model=SecretLedger)


def test_the_rejection_message_names_the_lookup_and_the_allowed_ones() -> None:
    """The error must name the rejected lookup and list every allowed one.

    Contract: this test ships broken if the message stops being actionable — it
    reaches the client as an error frame and is the only feedback a legitimate
    subscriber gets about why its filter was refused.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = _declared(_UnprojectedLedgerSubscription)
    with pytest.raises(ValueError) as excinfo:
        _validate_client_filters(
            {"secret__startswith": "pbkdf2"}, declared, model=SecretLedger
        )

    message = str(excinfo.value)
    assert "startswith" in message, message
    for allowed in ("exact", "iexact", "in", "isnull"):
        assert allowed in message, message


def test_equality_and_membership_stay_accepted_on_a_declared_secret() -> None:
    """The allowed suffixes must survive on every declared column.

    Contract: this test ships broken if the allow list is tightened past
    equality/membership and breaks the documented scoping use.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = _declared(_UnprojectedLedgerSubscription)
    _validate_client_filters({"label": "public"}, declared, model=SecretLedger)
    _validate_client_filters({"label__exact": "public"}, declared, model=SecretLedger)
    _validate_client_filters({"label__iexact": "public"}, declared, model=SecretLedger)
    _validate_client_filters({"label__in": ["a", "b"]}, declared, model=SecretLedger)
    _validate_client_filters({"created__isnull": True}, declared, model=SecretLedger)


def test_the_relation_and_undeclared_rejections_survive_the_allow_list() -> None:
    """Tightening the suffixes must not weaken the two rejections already landed.

    Contract: this test ships broken if the allow-list check replaces (rather
    than joins) the declared-root and registered-lookup checks — a relation
    traversal whose last segment happens to be "in" would otherwise pass.
    """
    from django_graphex.subscriptions.streaming import _validate_client_filters

    declared = _declared(_PostSubscription)
    with pytest.raises(ValueError, match="not a declared output field"):
        _validate_client_filters({"not_a_field": 1}, declared, model=Post)
    with pytest.raises(ValueError, match="not a valid Django lookup"):
        _validate_client_filters({"tags__label__in": ["a"]}, declared, model=Post)


async def test_a_rejected_lookup_never_starts_a_stream_over_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: a rejected filter must produce an error frame and NO source.

    Contract: this test ships broken if a pattern lookup survives to
    "group_add". A joined group IS the oracle — delivery would then evaluate
    the lookup against the database and the arrival (or not) of an event would
    answer the attacker's probe.

    2.1.0 moved the rejection one step EARLIER: the argument is now the typed
    "<Model>SubscriptionFilterInput", which only declares the four allowed
    lookups, so "startswith" fails SCHEMA VALIDATION before the subscribe
    resolver runs at all. The runtime allow list ("_validate_client_filters",
    exercised directly above) stays as defence in depth for anything that
    reaches the resolver without going through schema coercion.

    Args:
        monkeypatch: The pytest fixture used to stub the channel layer.
    """
    from django_graphex.subscriptions.transports import sse

    layer = InMemoryChannelLayer()
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)

    query = (
        "subscription { secretRecord("
        'action: CREATE, filter: { title: { startswith: "a" } }'
        ") { id title } }"
    )
    with _auth_settings():
        schema = _build_private_schema()
        view = sse.subscription_sse_view(schema=schema)
        response = await view(_make_request(query, user=_RequestUser()))

        started = sse.get_started_source(response)
        assert started is None, (
            "a rejected client filter still joined groups — the oracle is open: "
            f"{getattr(started, 'joined_groups', None)}"
        )

        frames = await _drain(response)

    body = "".join(frames)
    assert "startswith" in body, body
    assert "SecretRecordTitleSubscriptionLookups" in body, body


def test_model_type_forwards_the_projection_to_its_subscription() -> None:
    """DjangoModelType "exclude_fields" must reach the generated subscription.

    Contract: this test ships broken if "types.py" builds the subscription's
    meta_attrs without forwarding "only_fields"/"exclude_fields" — the generated
    subscription then declares (and serializes) the excluded column.
    """
    from django_graphex.types import DjangoModelType

    class _ProjectedLedgerModelType(DjangoModelType):
        class Meta:
            model = SecretLedger
            stream = "secret_ledger_projected"
            payload_mode = "full"
            exclude_fields = ("secret",)

    declared = _declared(_ProjectedLedgerModelType.subscription_type())
    assert "label" in declared
    assert "secret" not in declared
