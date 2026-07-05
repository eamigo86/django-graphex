# -*- coding: utf-8 -*-
"""Change 2 — the BUNDLED provider path must respect "PERMISSION_SCOPED_SCHEMA".

Once a "schema_provider" is wired on "subscription_ws_consumer" /
"subscription_sse_view", pruning happened UNCONDITIONALLY: the provider path
never read "PERMISSION_SCOPED_SCHEMA" (only "PERMISSION_SCHEMA_CACHE_MAXSIZE").
The HTTP path IS gated by the setting ("AuthenticatedGraphQLView" returns the
FULL schema when the flag is off), so the transports diverged.

One flag should rule the feature. The seam lives in the BUNDLED helper
"pruned_schema_for":

  * "PERMISSION_SCOPED_SCHEMA" False (default) -> return the FULL schema (read
    per-request / per-connection, never at import);
  * "PERMISSION_SCOPED_SCHEMA" True -> return the pruned schema;
  * an ACTIVE superuser always gets the FULL schema (invariant unchanged);
  * a CUSTOM provider callable that does NOT route through "pruned_schema_for"
    is the caller's own code — the gate does NOT touch it.

These tests drive ONLY the validation path (a labeled schema whose "post"
field is pruned for a permission-less user), so they never start a real
"ChannelLayerSource" — no channel layer is required.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import override_settings

pytest.importorskip("channels")

from graphql import (  # noqa: E402
    GraphQLArgument,
    GraphQLBoolean,
    GraphQLField,
    GraphQLInt,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
)

from django_graphex.core.permission_signature_cache import (  # noqa: E402
    pruned_schema_for,
)

# A perm the test users never hold, so the labeled ``post`` field is pruned for
# them when (and only when) PERMISSION_SCOPED_SCHEMA is True.
_VIEW_POST = "tests.view_post"
_LABEL_SET = frozenset({_VIEW_POST})

_SUB_QUERY = "subscription { post(action: CREATE) { id } }"


def _labeled(gql_field: GraphQLField, perms: frozenset[str]) -> GraphQLField:
    """Attach a "gdx_required_perms" extension to a field.

    Args:
        gql_field: The field to label.
        perms: The permission set required to see this field after pruning.

    Returns:
        gql_field: The same field instance, mutated in place.
    """
    gql_field.extensions = {
        **(gql_field.extensions or {}),
        "gdx_required_perms": perms,
    }
    return gql_field


def _full_labeled_schema() -> GraphQLSchema:
    """Build a labeled schema whose Subscription "post" field requires "_VIEW_POST".

    "prune_schema" drops the "post" field for a user lacking "_VIEW_POST",
    so with the flag ON a "subscribe { post }" fails validation ("Cannot query
    field"); with the flag OFF the field is present and validation passes.

    Returns:
        schema: The assembled labeled schema.
    """
    post_row = GraphQLObjectType("Post", {"id": GraphQLField(GraphQLInt)})
    query = GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)})
    # ``heartbeat`` is UNLABELED so it always survives pruning: this keeps the
    # Subscription root non-empty after ``post`` is pruned, so subscribing to
    # the removed ``post`` yields a precise ``Cannot query field 'post'`` error
    # (a not-found) rather than the coarse "Schema is not configured to execute
    # subscription operation" that an empty root would produce.
    subscription = GraphQLObjectType(
        "Subscription",
        {
            "heartbeat": GraphQLField(GraphQLBoolean),
            "post": _labeled(
                GraphQLField(
                    post_row,
                    args={"action": GraphQLArg()},
                ),
                _LABEL_SET,
            ),
        },
    )
    return GraphQLSchema(
        query=query,
        subscription=subscription,
        extensions={"gdx_label_set": _LABEL_SET},
    )


def GraphQLArg() -> GraphQLArgument:
    """Build the "action" argument used by the labeled schema's "post" field.

    Returns:
        argument: A GraphQLArgument typed as the CREATE/UPDATE action enum.
    """
    from graphql import GraphQLEnumType, GraphQLEnumValue

    action = GraphQLEnumType(
        "SubscriptionAction",
        {
            "CREATE": GraphQLEnumValue("CREATE"),
            "UPDATE": GraphQLEnumValue("UPDATE"),
        },
    )
    return GraphQLArgument(action)


class _User:
    """A minimal user stand-in that never holds the labeled permission."""

    def __init__(self, *, is_superuser: bool = False, is_active: bool = True) -> None:
        """Store the superuser/active flags for this stand-in user.

        Args:
            is_superuser: Whether this stand-in reports itself as superuser.
            is_active: Whether this stand-in reports itself as active.
        """
        self.is_authenticated = True
        self.is_superuser = is_superuser
        self.is_active = is_active
        self.pk = 1

    def get_all_permissions(self) -> set[str]:
        """Return an empty permission set (never holds _VIEW_POST).

        Returns:
            perms: Always an empty set.
        """
        return set()  # never holds _VIEW_POST


# ---------------------------------------------------------------------------
# Request / drain helpers (mirrors the sibling transport tests)
# ---------------------------------------------------------------------------


def _make_request(query: str, *, user: "_User") -> Any:
    """Build a POST request carrying a subscription document and a fake user.

    Args:
        query: The GraphQL subscription document to send as the request body.
        user: The stand-in user to attach as request.user.

    Returns:
        request: The constructed Django test request.
    """
    from django.test import RequestFactory

    factory = RequestFactory()
    request = factory.post(
        "/subscriptions/sse",
        data=json.dumps({"query": query}),
        content_type="application/json",
    )
    request.user = user
    return request


async def _drain(response: Any, *, max_frames: int = 3) -> str:
    """Consume up to max_frames SSE frames from a streaming response.

    Args:
        response: The streaming HTTP response to read frames from.
        max_frames: The maximum number of frames to pull before stopping.

    Returns:
        body: The concatenated decoded text of the consumed frames.
    """
    import asyncio

    frames: list[str] = []
    aiter = response.streaming_content.__aiter__()
    for _ in range(max_frames):
        try:
            chunk = await asyncio.wait_for(aiter.__anext__(), timeout=1.0)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
        text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk
        frames.append(text)
        if "event: complete" in text:
            break
    aclose = getattr(aiter, "aclose", None)
    if aclose:
        await aclose()
    return "".join(frames)


def _ws_consumer(
    scope: dict[str, Any],
    *,
    schema: GraphQLSchema | None = None,
    schema_provider: Any = None,
) -> Any:
    """Instantiate a WS consumer bound to schema/provider with a given scope.

    Args:
        scope: The ASGI-style connection scope to attach to the consumer.
        schema: An explicit schema to bind the consumer to, when not using a
            per-connection provider.
        schema_provider: A callable resolving the schema from the connected
            user, when not using a fixed schema.

    Returns:
        consumer: The instantiated consumer, pre-wired with fake internal
            state and a recording send_json stand-in.
    """
    from django_graphex.subscriptions.transports import ws

    kwargs: dict[str, Any] = {"init_timeout": 0.05}
    if schema is not None:
        kwargs["schema"] = schema
    if schema_provider is not None:
        kwargs["schema_provider"] = schema_provider
    consumer_cls = ws.subscription_ws_consumer(**kwargs)
    consumer = consumer_cls()
    consumer.scope = scope
    consumer._acked = True
    consumer._operations = {}
    consumer._sources = {}
    consumer._closing = False
    consumer._sent = []

    async def _fake_send_json(payload: dict[str, Any]) -> None:
        consumer._sent.append(payload)

    consumer.send_json = _fake_send_json  # type: ignore[assignment]
    return consumer


def _bundled_provider(full: GraphQLSchema) -> Any:
    """Return the idiom the docs tell users to wire (routes through the gate).

    Args:
        full: The unpruned schema to gate through pruned_schema_for.

    Returns:
        provider: A callable taking a user and returning the gated schema.
    """
    return lambda user: pruned_schema_for(user, full)


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": False})
async def test_sse_flag_off_bundled_provider_serves_full_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag OFF plus bundled provider must serve the full schema over SSE.

    Contract: one-flag-rules-the-feature ships broken if the previously
    pruned "post" field fails validation with the flag off.

    Args:
        monkeypatch: The pytest fixture used to stub create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import sse

    async def _stub(*a: Any, **k: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(sse, "create_source_event_stream", _stub)

    full = _full_labeled_schema()
    view = sse.subscription_sse_view(schema_provider=_bundled_provider(full))
    response = await view(_make_request(_SUB_QUERY, user=_User()))
    body = await _drain(response)
    assert "Cannot query field" not in body


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True})
async def test_sse_flag_on_bundled_provider_prunes_field() -> None:
    """Flag ON plus bundled provider must prune the "post" field over SSE.

    Contract: this test ships broken if a subscribe naming the pruned "post"
    field does not fail at validation once the flag is on.
    """
    from django_graphex.subscriptions.transports import sse

    full = _full_labeled_schema()
    view = sse.subscription_sse_view(schema_provider=_bundled_provider(full))
    response = await view(_make_request(_SUB_QUERY, user=_User()))
    body = await _drain(response)
    assert "Cannot query field" in body


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True})
async def test_sse_superuser_gets_full_schema_even_with_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active superuser must always receive the full schema, even with the flag on.

    Contract: the superuser bypass invariant ships broken if an active
    superuser's "post" field is pruned despite PERMISSION_SCOPED_SCHEMA=True.

    Args:
        monkeypatch: The pytest fixture used to stub create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import sse

    async def _stub(*a: Any, **k: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(sse, "create_source_event_stream", _stub)

    full = _full_labeled_schema()
    view = sse.subscription_sse_view(schema_provider=_bundled_provider(full))
    response = await view(_make_request(_SUB_QUERY, user=_User(is_superuser=True)))
    body = await _drain(response)
    assert "Cannot query field" not in body


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": False})
async def test_sse_custom_provider_bypasses_gate() -> None:
    """A custom provider not routing through pruned_schema_for must be honored as-is.

    Contract: the gate must not touch caller-owned provider callables — this
    test ships broken if the flag being off re-inflates a custom schema that
    the caller deliberately built without the "post" field.
    """
    from django_graphex.subscriptions.transports import sse

    custom = GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)}),
        subscription=GraphQLObjectType(
            "Subscription", {"heartbeat": GraphQLField(GraphQLString)}
        ),
    )
    view = sse.subscription_sse_view(schema_provider=lambda user: custom)
    response = await view(_make_request(_SUB_QUERY, user=_User()))
    body = await _drain(response)
    # The custom schema has no ``post`` field — the gate must NOT override it.
    assert "Cannot query field" in body


# ---------------------------------------------------------------------------
# WS
# ---------------------------------------------------------------------------


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": False})
async def test_ws_flag_off_bundled_provider_serves_full_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag OFF plus bundled provider must serve the full schema over WS.

    Contract: one-flag-rules-the-feature ships broken if "post" fails
    validation (an error frame with "Cannot query field") with the flag off.

    Args:
        monkeypatch: The pytest fixture used to stub create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import ws

    async def _stub(*a: Any, **k: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(ws, "create_source_event_stream", _stub)

    full = _full_labeled_schema()
    consumer = _ws_consumer({"user": _User()}, schema_provider=_bundled_provider(full))
    await consumer._run_operation("1", {"query": _SUB_QUERY})
    assert "Cannot query field" not in json.dumps(consumer._sent)


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True})
async def test_ws_flag_on_bundled_provider_prunes_field() -> None:
    """Flag ON plus bundled provider must prune the "post" field over WS.

    Contract: this test ships broken if subscribing to the pruned "post"
    field does not produce a "Cannot query field" error frame once the flag
    is on.
    """

    full = _full_labeled_schema()
    consumer = _ws_consumer({"user": _User()}, schema_provider=_bundled_provider(full))
    await consumer._run_operation("1", {"query": _SUB_QUERY})
    errors = [m for m in consumer._sent if m.get("type") == "error"]
    assert errors, consumer._sent
    assert "Cannot query field" in json.dumps(errors)


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": True})
async def test_ws_superuser_gets_full_schema_even_with_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active superuser must always receive the full schema over WS, flag notwithstanding.

    Contract: the superuser bypass invariant ships broken over WS if an
    active superuser's "post" field is pruned despite the flag being on.

    Args:
        monkeypatch: The pytest fixture used to stub create_source_event_stream.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.transports import ws

    async def _stub(*a: Any, **k: Any) -> ExecutionResult:
        return ExecutionResult(data=None, errors=None)

    monkeypatch.setattr(ws, "create_source_event_stream", _stub)

    full = _full_labeled_schema()
    consumer = _ws_consumer(
        {"user": _User(is_superuser=True)}, schema_provider=_bundled_provider(full)
    )
    await consumer._run_operation("1", {"query": _SUB_QUERY})
    assert "Cannot query field" not in json.dumps(consumer._sent)


@override_settings(DJANGO_GRAPHEX={"PERMISSION_SCOPED_SCHEMA": False})
async def test_ws_custom_provider_bypasses_gate() -> None:
    """A custom WS provider must be honored as-is (flag off must not re-inflate it).

    Contract: this test ships broken if the flag being off causes a custom
    provider's deliberately schema-less "post" field to reappear over WS.
    """

    custom = GraphQLSchema(
        query=GraphQLObjectType("Query", {"ok": GraphQLField(GraphQLBoolean)}),
        subscription=GraphQLObjectType(
            "Subscription", {"heartbeat": GraphQLField(GraphQLString)}
        ),
    )
    consumer = _ws_consumer({"user": _User()}, schema_provider=lambda user: custom)
    await consumer._run_operation("1", {"query": _SUB_QUERY})
    assert "Cannot query field" in json.dumps(consumer._sent)
