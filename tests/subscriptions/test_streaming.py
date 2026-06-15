# -*- coding: utf-8 -*-
"""WU5 — streaming.py: SubscriptionSpec + drive_subscription + native subscribe.

Design §2 (``SubscriptionSpec`` plain ``@dataclass`` + ``drive_subscription``),
§3 (the serialize-once data path: the native subscribe entry runs the KEPT hooks
BEFORE the source — authorize -> validate_filters -> scope -> merge filters ->
compute index/groups -> ``ChannelLayerSource``; the action arg picks the join
set), §4 (COND-A: ``drive_subscription`` composes the source through the WU2
``DeliveryIterator`` running ``execute()`` PER event over the flat dict; NO
``MapAsyncIterator``; out-of-band close), §6 (snake-closure projection), §7
(transport-neutral context: ``.user`` + a scope mapping — works for both SSE
``HttpRequest`` and WS Channels scope).

This is the WU5 gate (InMemoryChannelLayer, channels 4.3.2). It proves:

  - authorize-DENY short-circuits BEFORE any ``group_add`` (no source, no group)
  - scope WINS over a conflicting client filter; effective = client ∪ scope
  - hooks run BEFORE ``ChannelLayerSource`` construction (ordering)
  - ``drive_subscription`` yields an ``ExecutionResult`` whose data is the
    projected flat dict; ``assertNumQueries(0)`` per delivered event; one
    ``execute()`` runs PER event over the SAME dict (serialize-once)
  - the delivery path contains NO ``MapAsyncIterator`` (structural assert)
  - ``db_verify`` is wired: a ``__lookup``-filtered subscription DELIVERS verified
    events and DROPS a non-matching ``__lookup`` event (the WU4 conservative-drop
    gap is closed by the wired verifier)
  - out-of-band close (``aclose``) stops promptly and ``group_discard``s (source)
"""
from __future__ import annotations

import asyncio

import pytest
from graphql import (
    GraphQLBoolean,
    GraphQLField,
    GraphQLID,
    GraphQLInt,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
)

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402

from django_graphex.subscriptions.resolvers import make_snake_resolver  # noqa: E402
from django_graphex.subscriptions.source import ChannelLayerSource  # noqa: E402
from django_graphex.subscriptions.streaming import (  # noqa: E402
    SubscriptionSpec,
    drive_subscription,
    native_subscribe,
)

# ---------------------------------------------------------------------------
# Test schema: mirrors the native wiring (subscribe=<source>, resolve=identity,
# every event field carries a sentinel snake-closure). The event type is what
# the engine projects the flat dict through.
# ---------------------------------------------------------------------------


def _build_event_schema() -> GraphQLSchema:
    """A minimal subscription schema with a snake-closure-projected event type.

    The ``demoEvent`` field's ``resolve`` is identity (root IS the flat source
    dict); each event field resolver is a sentinel-tagged snake-closure that maps
    a camelCase wire name to the snake key present in the serialized payload.
    """
    event_type = GraphQLObjectType(
        "DemoEvent",
        lambda: {
            "id": GraphQLField(GraphQLID, resolve=make_snake_resolver("id")),
            "isActive": GraphQLField(
                GraphQLBoolean, resolve=make_snake_resolver("is_active")
            ),
            "ownerId": GraphQLField(
                GraphQLInt, resolve=make_snake_resolver("owner_id")
            ),
            "name": GraphQLField(GraphQLString, resolve=make_snake_resolver("name")),
        },
    )
    subscription_type = GraphQLObjectType(
        "Subscription",
        lambda: {
            "demoEvent": GraphQLField(
                event_type,
                resolve=lambda root, _info: root,
            )
        },
    )
    # graphql-core requires a Query root type for a valid schema, even when only
    # the subscription root is exercised. A trivial one keeps validate_schema happy.
    query_type = GraphQLObjectType(
        "Query",
        lambda: {"ok": GraphQLField(GraphQLBoolean, resolve=lambda *_: True)},
    )
    return GraphQLSchema(query=query_type, subscription=subscription_type)


_DOC = parse("subscription { demoEvent { id isActive ownerId name } }")


def _notify(group: str, data: dict, *, action: str = "create", pk=1) -> dict:
    """Build a producer-shaped ``subscription.notify`` envelope (bindings.py)."""
    return {
        "type": "subscription.notify",
        "stream": "demo",
        "group": group,
        "pk": pk,
        "payload": {"action": action, "model": "app.Demo", "data": data},
    }


class _Ctx:
    """A transport-neutral context exposing ``.user`` + a scope mapping (§7).

    Both SSE (``HttpRequest``) and WS (Channels ``scope``) can satisfy this
    minimal contract: a ``user`` attribute and a ``scope`` mapping. Hooks must
    NOT assume ``HttpRequest``.
    """

    def __init__(self, user=None, scope=None):
        self.user = user
        self.scope = scope or {}


class _RecordingLayer(InMemoryChannelLayer):
    """An InMemoryChannelLayer that records every ``group_add`` for assertions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_add_calls: list[tuple[str, str]] = []

    async def group_add(self, group, channel):
        self.group_add_calls.append((group, channel))
        return await super().group_add(group, channel)


# A SubscriptionSpec used across tests. The hooks are plain (sync) callables that
# receive (context, **kwargs) — mirroring the subscription.py classmethods but
# decoupled from the graphene base so WU5 can test the engine in isolation.
def _spec(
    *,
    authorize=None,
    scope=None,
    index_fields=(),
    declared_fields=("id", "is_active", "owner_id", "name"),
    db_exists=None,
) -> SubscriptionSpec:
    """Build a SubscriptionSpec with injectable hooks for the test."""

    def _authorize(context, **kw):
        if authorize is not None:
            authorize(context, **kw)

    def _scope(context, **kw):
        return scope(context, **kw) if scope is not None else None

    return SubscriptionSpec(
        model_label="app.demo",
        stream="demo",
        schema=_build_event_schema(),
        document=_DOC,
        declared_output_fields=set(declared_fields),
        index_fields=tuple(index_fields),
        authorize=_authorize,
        scope=_scope,
        group_name=_group_name,
        instance_index=lambda inst: None,
        db_exists=db_exists,
    )


def _group_name(action, *, id=None, index=None):
    """Mirror Subscription._group_name's naming for the test.

    Uses ``safe_group_name`` so a value-scoped name carrying ``:`` / ``=`` / ``&``
    (which Channels rejects) is deterministically hashed — exactly what the real
    ``Subscription._group_name`` does, so producer and consumer names match.
    """
    from urllib.parse import quote

    from django_graphex.subscriptions.mixins import safe_group_name

    name = f"app.demo-{action}" if not id else f"app.demo-{action}-{id}"
    if index:
        suffix = "&".join(
            f"{quote(str(k), safe='')}={quote(str(index[k]), safe='')}"
            for k in sorted(index)
        )
        name = f"{name}:{suffix}"
    return safe_group_name(name)


async def _start_source(spec, layer, *, action="create", obj_id=None, filters=None,
                        context=None):
    """Run native_subscribe and return the started ChannelLayerSource."""
    return await native_subscribe(
        spec,
        layer,
        action=action,
        obj_id=obj_id,
        filters=filters,
        context=context or _Ctx(user=object()),
    )


# ---------------------------------------------------------------------------
# SubscriptionSpec is a plain @dataclass (C-A: NOT a BaseModel/ModelMetaclass)
# ---------------------------------------------------------------------------


def test_subscription_spec_is_plain_dataclass():
    """``SubscriptionSpec`` is a plain ``@dataclass`` (NOT ModelMetaclass/#1452)."""
    import dataclasses

    assert dataclasses.is_dataclass(SubscriptionSpec)
    # It must NOT be a graphene/pydantic-metaclass class — a plain dataclass's
    # metaclass is ``type`` itself.
    assert type(SubscriptionSpec) is type
    spec = _spec()
    assert spec.stream == "demo"
    assert spec.model_label == "app.demo"


# ---------------------------------------------------------------------------
# authorize-DENY short-circuits BEFORE any group_add
# ---------------------------------------------------------------------------


async def test_authorize_deny_short_circuits_before_group_add():
    """A denying ``authorize`` raises BEFORE any source/group is created.

    No ``ChannelLayerSource`` is constructed and the channel layer receives ZERO
    ``group_add`` calls (deny short-circuits before any join).
    """
    layer = _RecordingLayer()

    def _deny(context, **kw):
        raise PermissionError("denied")

    spec = _spec(authorize=_deny)

    with pytest.raises(PermissionError, match="denied"):
        await _start_source(spec, layer, action="create")

    # The deny fired BEFORE any group_add — the layer never joined a group.
    assert layer.group_add_calls == []


async def test_authorize_runs_before_source_construction(monkeypatch):
    """Hook ORDER: authorize fires BEFORE ``ChannelLayerSource`` is constructed.

    Patches ``ChannelLayerSource.__init__`` to record construction; a denying
    authorize must raise with construction NEVER recorded.
    """
    layer = _RecordingLayer()
    events: list[str] = []

    def _authorize(context, **kw):
        events.append("authorize")
        raise PermissionError("nope")

    orig_init = ChannelLayerSource.__init__

    def _spy_init(self, *a, **k):
        events.append("source_init")
        return orig_init(self, *a, **k)

    monkeypatch.setattr(ChannelLayerSource, "__init__", _spy_init)

    spec = _spec(authorize=_authorize)
    with pytest.raises(PermissionError):
        await _start_source(spec, layer)

    assert events == ["authorize"]  # source NEVER constructed after deny


# ---------------------------------------------------------------------------
# scope WINS over client filter; effective = client ∪ scope (scope precedence)
# ---------------------------------------------------------------------------


async def test_scope_wins_over_conflicting_client_filter():
    """``subscription_scope`` overrides a conflicting client filter (server wins)."""
    layer = _RecordingLayer()

    def _scope(context, **kw):
        return {"owner_id": 5}

    spec = _spec(scope=_scope)
    source = await _start_source(
        spec, layer, action="create", filters={"owner_id": 99, "name": "x"}
    )
    try:
        # Client said owner_id=99; the server scope (owner_id=5) WINS.
        assert source.filters == {"name": "x", "owner_id": 5}
    finally:
        await source.aclose()


async def test_filters_are_client_union_scope():
    """Effective filters are the union of client filters and server scope."""
    layer = _RecordingLayer()

    def _scope(context, **kw):
        return {"tenant_id": 7}

    spec = _spec(scope=_scope, declared_fields=("id", "name", "tenant_id"))
    source = await _start_source(spec, layer, filters={"name": "abc"})
    try:
        assert source.filters == {"name": "abc", "tenant_id": 7}
    finally:
        await source.aclose()


async def test_hooks_run_before_source_then_join():
    """authorize -> validate -> scope all run, THEN the source joins its group."""
    layer = _RecordingLayer()
    order: list[str] = []

    def _authorize(context, **kw):
        order.append("authorize")

    def _scope(context, **kw):
        order.append("scope")
        return {"owner_id": 1}

    spec = _spec(authorize=_authorize, scope=_scope)
    source = await _start_source(spec, layer, action="create", filters={"id": 1})
    try:
        # All hooks ran before the single group was joined.
        assert order == ["authorize", "scope"]
        assert source.joined_groups == ["app.demo-create"]
        assert len(layer.group_add_calls) == 1
    finally:
        await source.aclose()


async def test_validate_filters_rejects_undeclared_root():
    """A client filter rooting on an undeclared output field is rejected."""
    layer = _RecordingLayer()
    spec = _spec(declared_fields=("id", "name"))
    with pytest.raises(Exception):  # noqa: PT011 - GraphQLError or ValueError
        await _start_source(spec, layer, filters={"password__icontains": "x"})
    # Rejected during validation, BEFORE any group_add.
    assert layer.group_add_calls == []


# ---------------------------------------------------------------------------
# action arg picks the join set (#1420: NOT hardcoded 3)
# ---------------------------------------------------------------------------


async def test_single_action_joins_exactly_one_group_1420():
    """A single-action subscribe joins ONLY its group (the #1420 guard)."""
    layer = _RecordingLayer()
    spec = _spec()
    source = await _start_source(spec, layer, action="update")
    try:
        assert source.joined_groups == ["app.demo-update"]
    finally:
        await source.aclose()


async def test_all_actions_joins_three_groups():
    """``all_actions`` joins exactly the create/update/delete groups."""
    layer = _RecordingLayer()
    spec = _spec()
    source = await _start_source(spec, layer, action="all_actions")
    try:
        assert set(source.joined_groups) == {
            "app.demo-create",
            "app.demo-update",
            "app.demo-delete",
        }
    finally:
        await source.aclose()


# ---------------------------------------------------------------------------
# drive_subscription: flat-dict execute -> ExecutionResult; serialize-once
# ---------------------------------------------------------------------------


async def test_drive_subscription_yields_execution_result_over_flat_dict():
    """A source event -> drive yields an ``ExecutionResult`` projecting the dict.

    The snake-closure resolvers map camelCase wire names to snake payload keys, so
    a multi-word field (``isActive`` -> ``is_active``) delivers the REAL value, not
    null. ``execute()`` runs over the flat dict that IS the root.
    """
    from graphql import ExecutionResult

    layer = InMemoryChannelLayer()
    spec = _spec()
    source = await _start_source(spec, layer)
    delivery = drive_subscription(source, spec)

    flat = {"id": 1, "is_active": True, "owner_id": 5, "name": "alice"}
    await layer.group_send("app.demo-create", _notify("app.demo-create", flat))

    result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
    await delivery.aclose()

    assert isinstance(result, ExecutionResult)
    assert result.errors is None
    assert result.data == {
        "demoEvent": {
            "id": "1",
            "isActive": True,
            "ownerId": 5,
            "name": "alice",
        }
    }


async def test_execute_runs_per_event_over_same_dict():
    """``execute()`` runs ONCE PER delivered event (serialize-once data path)."""
    import django_graphex.subscriptions.streaming as streaming_mod

    calls = {"n": 0}
    real_execute = streaming_mod.execute

    def _counting(*args, **kwargs):
        calls["n"] += 1
        return real_execute(*args, **kwargs)

    layer = InMemoryChannelLayer()
    spec = _spec()
    source = await _start_source(spec, layer)
    delivery = drive_subscription(source, spec)

    # Patch the engine's execute reference after the delivery was built.
    streaming_mod.execute = _counting  # type: ignore[assignment]
    try:
        for i in range(3):
            await layer.group_send(
                "app.demo-create",
                _notify("app.demo-create", {"id": i, "is_active": True}),
            )
        for i in range(3):
            result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
            assert result.data["demoEvent"]["id"] == str(i)
    finally:
        streaming_mod.execute = real_execute  # type: ignore[assignment]
        await delivery.aclose()

    # One execute() per delivered event — no extra serialization/DB round-trips.
    assert calls["n"] == 3


@pytest.mark.django_db
def test_drive_subscription_assert_num_queries_zero_per_event(
    django_assert_num_queries,
):
    """Each delivered event's ``execute()`` hits ZERO DB queries (no ORM).

    SYNC test driving the async delivery via ``asyncio.run`` inside the assertion
    block — ``django_assert_num_queries`` calls ``ensure_connection()``
    synchronously which raises ``SynchronousOnlyOperation`` under a running loop.
    """
    layer = InMemoryChannelLayer()
    spec = _spec()

    async def _drive() -> dict:
        source = await _start_source(spec, layer)
        delivery = drive_subscription(source, spec)
        try:
            await layer.group_send(
                "app.demo-create",
                _notify("app.demo-create", {"id": 1, "is_active": False}),
            )
            result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
            return result.data
        finally:
            await delivery.aclose()

    with django_assert_num_queries(0):
        data = asyncio.run(_drive())

    assert data == {
        "demoEvent": {"id": "1", "isActive": False, "ownerId": None, "name": None}
    }


# ---------------------------------------------------------------------------
# COND-A: the delivery path contains NO MapAsyncIterator
# ---------------------------------------------------------------------------


async def test_delivery_path_is_not_map_async_iterator():
    """``drive_subscription`` composes the WU2 DeliveryIterator, NOT MapAsyncIterator."""
    from graphql.execution.map_async_iterator import MapAsyncIterator

    from django_graphex.subscriptions.delivery import DeliveryIterator

    layer = InMemoryChannelLayer()
    spec = _spec()
    source = await _start_source(spec, layer)
    delivery = drive_subscription(source, spec)
    try:
        assert isinstance(delivery, MapAsyncIterator) is False
        assert isinstance(delivery, DeliveryIterator) is True
    finally:
        await delivery.aclose()


def test_streaming_module_has_no_map_async_iterator():
    """Static guard: ``streaming.py`` must not import/use MapAsyncIterator."""
    import inspect

    from django_graphex.subscriptions import streaming

    src = inspect.getsource(streaming)
    assert "MapAsyncIterator" not in src
    assert "map_async_iterator" not in src


def test_streaming_module_has_no_graphene_import():
    """No-graphene-import gate: ``streaming.py`` must not import graphene."""
    import pathlib

    from django_graphex.subscriptions import streaming

    text = pathlib.Path(streaming.__file__).read_text(encoding="utf-8")
    assert "import graphene" not in text
    assert "from graphene" not in text


# ---------------------------------------------------------------------------
# db_verify wired: __lookup subscriptions DELIVER verified + DROP non-matching
# ---------------------------------------------------------------------------


async def test_lookup_filter_wired_db_verify_delivers_verified():
    """A ``__lookup`` filter is wired to ``source.db_verify`` -> verified delivers.

    WU4 left a conservative-drop gap: a non-empty ``__lookup`` "remaining" mapping
    dropped UNLESS a ``db_verify`` hook is wired. WU5 wires ``source.db_verify``
    (the single-row ``.exists()`` narrowing) so a verified event DELIVERS.
    """
    layer = InMemoryChannelLayer()
    seen: list[tuple[dict, dict]] = []

    def _db_exists(remaining, event, *, obj_id=None):
        # Stand-in for the single-row .exists() narrowing: match by the event's
        # carried snake key against the remaining __lookup expected value.
        seen.append((dict(remaining), dict(event)))
        return event.get("owner_tenant_id") == remaining.get("owner__tenant_id")

    spec = _spec(
        declared_fields=("id", "is_active", "owner", "name"),
        db_exists=_db_exists,
    )
    source = await _start_source(
        spec, layer, filters={"owner__tenant_id": 7}
    )
    delivery = drive_subscription(source, spec)

    # The source must have a db_verify hook wired by native_subscribe.
    assert source.db_verify is not None

    # FALSE: tenant 99 -> verifier drops.
    await layer.group_send(
        "app.demo-create",
        _notify("app.demo-create", {"id": 1, "is_active": True, "owner_tenant_id": 99}),
    )
    # TRUE: tenant 7 -> verifier delivers.
    await layer.group_send(
        "app.demo-create",
        _notify("app.demo-create", {"id": 2, "is_active": True, "owner_tenant_id": 7}),
    )

    result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
    await delivery.aclose()

    # Only the verified (tenant 7) event was delivered.
    assert result.data["demoEvent"]["id"] == "2"
    assert seen, "db_verify hook was never invoked"


async def test_lookup_filter_non_matching_dropped():
    """A non-matching ``__lookup`` event is DROPPED by the wired verifier."""
    layer = InMemoryChannelLayer()

    def _db_exists(remaining, event, *, obj_id=None):
        return event.get("owner_tenant_id") == remaining.get("owner__tenant_id")

    spec = _spec(
        declared_fields=("id", "is_active", "owner", "name"),
        db_exists=_db_exists,
    )
    source = await _start_source(spec, layer, filters={"owner__tenant_id": 7})
    delivery = drive_subscription(source, spec)

    # Send only a non-matching event (tenant 99) then a matching one so we can
    # prove the non-matching was dropped (its id never appears).
    await layer.group_send(
        "app.demo-create",
        _notify("app.demo-create", {"id": 1, "is_active": True, "owner_tenant_id": 99}),
    )
    await layer.group_send(
        "app.demo-create",
        _notify("app.demo-create", {"id": 2, "is_active": True, "owner_tenant_id": 7}),
    )

    result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
    await delivery.aclose()
    assert result.data["demoEvent"]["id"] == "2"


# ---------------------------------------------------------------------------
# out-of-band close: aclose stops promptly + group_discards (via source)
# ---------------------------------------------------------------------------


async def test_drive_subscription_aclose_stops_promptly_and_discards():
    """``drive_subscription`` aclose() releases a blocked pull PROMPTLY + discards.

    A background pull parks in the source's ``receive()``; ``aclose()`` on the
    delivery must release it (sub-500ms, not gated on the next broadcast) and the
    underlying source must ``group_discard`` every joined group (no ghost
    subscriber).
    """
    import time

    layer = InMemoryChannelLayer()
    spec = _spec()
    source = await _start_source(spec, layer, action="all_actions")
    delivery = drive_subscription(source, spec)
    channel = source.channel
    groups = list(source.joined_groups)

    pull = asyncio.ensure_future(delivery.__anext__())
    await asyncio.sleep(0.05)  # let the pull park inside receive()
    assert not pull.done()

    started = time.perf_counter()
    await delivery.aclose()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pull, timeout=5.0)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"aclose did not release promptly ({elapsed * 1000:.1f}ms)"

    # The underlying source discarded every joined group (no ghost subscribers).
    for group in groups:
        assert channel not in layer.groups.get(group, {})
    assert source.is_closed is True


async def test_drive_subscription_aclose_idempotent():
    """Calling ``drive_subscription`` aclose() twice is safe."""
    layer = InMemoryChannelLayer()
    spec = _spec()
    source = await _start_source(spec, layer)
    delivery = drive_subscription(source, spec)
    await delivery.aclose()
    await delivery.aclose()  # must not raise
    assert source.is_closed is True


# ---------------------------------------------------------------------------
# Transport-neutral context (§7): .user + scope mapping, NOT HttpRequest
# ---------------------------------------------------------------------------


async def test_context_is_transport_neutral():
    """Hooks receive a transport-neutral context (``.user`` + scope), not HttpRequest.

    The same ``native_subscribe`` works whether the context is an SSE-style
    object or a WS-style scope-bearing object — neither is an ``HttpRequest``.
    The hook reads ``context.user`` to build the scope.
    """
    layer = _RecordingLayer()
    captured: dict = {}

    def _scope(context, **kw):
        # Read from the transport-neutral context: .user + .scope mapping.
        captured["user"] = context.user
        captured["scope_keys"] = set(context.scope)
        return {"owner_id": getattr(context.user, "pk", None)}

    class _User:
        pk = 42

    spec = _spec(scope=_scope)
    ws_like_ctx = _Ctx(user=_User(), scope={"type": "websocket", "headers": []})
    source = await native_subscribe(
        spec,
        layer,
        action="create",
        obj_id=None,
        filters=None,
        context=ws_like_ctx,
    )
    try:
        assert isinstance(captured["user"], _User)
        assert "type" in captured["scope_keys"]
        assert source.filters == {"owner_id": 42}
    finally:
        await source.aclose()


# ---------------------------------------------------------------------------
# index routing: when index_fields ⊆ scope, route to a value-scoped group
# ---------------------------------------------------------------------------


async def test_index_fields_route_to_value_scoped_group():
    """When every index field is in scope, join the value-scoped group."""
    layer = _RecordingLayer()

    def _scope(context, **kw):
        return {"owner_id": 5}

    spec = _spec(scope=_scope, index_fields=("owner_id",))
    source = await _start_source(spec, layer, action="create")
    try:
        # The index suffix is appended to the coarse group name, then passed
        # through ``safe_group_name`` (the ':'/'=' chars Channels rejects are
        # hashed) — so the joined group is the SAME hashed name a producer builds.
        expected = _group_name("create", index={"owner_id": 5})
        assert source.joined_groups == [expected]
        # The value-scoped name differs from the coarse group (routing applied).
        assert source.joined_groups != ["app.demo-create"]
    finally:
        await source.aclose()


async def test_index_fields_fallback_when_not_in_scope():
    """When an index field is NOT in scope, fall back to the coarse group."""
    layer = _RecordingLayer()
    spec = _spec(index_fields=("owner_id",))  # no scope -> owner_id absent
    source = await _start_source(spec, layer, action="create")
    try:
        assert source.joined_groups == ["app.demo-create"]
    finally:
        await source.aclose()
