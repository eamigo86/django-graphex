# -*- coding: utf-8 -*-
"""WU6 — subscription.py Subscription base: native compile path.

WU6 provides the native subscription compile path:

  * ``Subscription._build_native_event_type()`` — a graphql-core
    ``GraphQLObjectType`` whose every field carries a ``make_snake_resolver``
    (WU1) closure (sentinel-tagged so COND-B/``guard.py`` whitelists it) and
    which carries ``extensions['gdx']`` (the native bridge).
  * ``Subscription._build_native_spec(schema, document)`` — a fully-populated
    WU5 ``SubscriptionSpec`` wired from the class: model/stream/index_fields,
    the KEPT hooks (``authorize_subscription``/``subscription_scope``/
    ``_validate_filters``), ``group_name``/``instance_index`` = the kept
    ``_group_name``/``_instance_index``, and ``db_exists`` = the single-row
    ``.exists()`` narrowing that closes the WU4 conservative-drop gap.
  * ``Subscription._build_native_field(schema, document)`` — a DIRECT graphql-core
    ``GraphQLField(type=<event type>, subscribe=<source factory>,
    resolve=identity)`` (NOT graphene ``Subscription.Field()``); the field args
    are reduced to ``{action, id, filters}`` under native.

The native subscribe factory builds the source via WU5 ``native_subscribe`` and
is driven through WU5 ``drive_subscription`` (COND-A, no ``MapAsyncIterator``).

INDEX-ROUTING RECONCILIATION (the WU5 SUGGESTION): the kept ``_subscribe`` hook
routes index groups SCOPE-ONLY (``all(f in scope for f in index_fields)``), NOT
``merged`` (client ∪ scope). WU6 reconciles ``native_subscribe`` to SCOPE-ONLY
parity so a CLIENT-supplied index-field value never narrows the joined group —
only a server ``subscription_scope`` value does (no cross-subscriber leak via a
client-chosen value-scoped group). This test asserts that parity.

S6e UPDATE (#1452): the metaclass swap is now DONE — ``type(<a Subscription
subclass>) is pydantic ModelMetaclass`` (re-parented off graphene ``ObjectType``
onto ``native.base.ObjectType``). The base-class assertions below were inverted
from the old C-A "stays graphene" constraint to the native reality. The native
compile path (event type + ``_build_native_field`` mount seam) is UNCHANGED.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("channels")

from channels.layers import InMemoryChannelLayer  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    parse,
)

from tests.models import Author, Post  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers: build a Subscription subclass + a recording channel layer.
# ---------------------------------------------------------------------------


class _RecordingLayer(InMemoryChannelLayer):
    """An InMemoryChannelLayer recording every ``group_add`` for assertions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_add_calls: list[tuple[str, str]] = []

    async def group_add(self, group, channel):
        self.group_add_calls.append((group, channel))
        return await super().group_add(group, channel)


def _notify(group: str, data: dict, *, action: str = "create", pk=1) -> dict:
    """Build a producer-shaped ``subscription.notify`` envelope (bindings.py)."""
    return {
        "type": "subscription.notify",
        "stream": "posts",
        "group": group,
        "pk": pk,
        "payload": {"action": action, "model": "tests.post", "data": data},
    }


def _make_subscription(**meta):
    """Build a fresh ``PostSubscription`` (native base, S6e re-parent).

    ``Subscription`` is now a pydantic ``ModelMetaclass`` type (S6e); a 3-arg
    ``type(name, bases, ns)`` build must inject ``__module__``/``__qualname__``
    (and re-stamp the nested ``Meta`` qualname) or pydantic's
    ``inspect_namespace`` raises ``KeyError('__module__')`` — mirroring the
    production ``DjangoModelType.subscription_type`` builder.
    """
    from django_graphex.subscriptions import Subscription

    meta_cls = type("Meta", (), {"model": Post, "stream": "posts", **meta})
    meta_cls.__qualname__ = "PostSubscription.Meta"
    meta_cls.__module__ = __name__
    return type(
        "PostSubscription",
        (Subscription,),
        {"__module__": __name__, "__qualname__": "PostSubscription", "Meta": meta_cls},
    )


# ---------------------------------------------------------------------------
# S6e METACLASS SWAP DONE (#1452): the base is re-parented onto the native
# graphene-free ObjectType; ``type(<subclass>) is pydantic ModelMetaclass``.
# ---------------------------------------------------------------------------


def test_subscription_base_is_native_object_type():
    """The public ``Subscription`` base subclasses the native ObjectType (S6e).

    Re-parented off graphene ``ObjectType`` onto ``native.base.ObjectType`` in
    S6e. It must NO LONGER be a graphene-driven type: the metaclass swap is done
    (Phase 7 / #1452). The graphene-free proof is twofold — the base IS a
    ``native.base.ObjectType`` subclass, and its metaclass IS pydantic's
    ``ModelMetaclass`` (NOT graphene's ``SubclassWithMeta_Meta``), which a graphene
    ``ObjectType`` subclass could never satisfy.
    """
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.subscriptions import Subscription

    assert issubclass(Subscription, NativeObjectType)
    # The metaclass swap is done: a graphene ``ObjectType`` subclass has graphene's
    # ``SubclassWithMeta_Meta`` metaclass, never pydantic's ``ModelMetaclass``.
    assert type(Subscription) is ModelMetaclass


def test_subscription_subclass_is_model_metaclass():
    """``type(PostSubscription) is pydantic ModelMetaclass`` (S6e swap done).

    A class has ONE metaclass fixed at definition. After re-parenting the base
    onto the graphene-free native ``ObjectType`` (whose metaclass is pydantic's
    ``ModelMetaclass``, NOT graphene's ``SubclassWithMeta_Meta``), every concrete
    ``Subscription`` subclass's metaclass IS ``ModelMetaclass`` — the systemic
    metaclass-identity invariant (#1452).
    """
    from pydantic._internal._model_construction import ModelMetaclass

    sub = _make_subscription()
    assert type(sub) is ModelMetaclass


# ---------------------------------------------------------------------------
# bespoke GONE (WU11 lockstep cutover — subscriptions are now native-only).
# ---------------------------------------------------------------------------


def test_bespoke_transport_graphene_subscribe_path_removed():
    """The bespoke graphene ``_subscribe`` (channel_id/operation confirmation) is gone.

    WU11 retires the bespoke transport in lockstep with its tests. The
    confirmation-frame ``_subscribe`` resolver (which drove the deleted consumer
    via channel-ownership + ``subscription.register`` control messages) is
    removed. The ``SubscriptionField`` mount + the native compile path stay so a
    native schema still assembles the Subscription type.
    """
    from django_graphex.subscriptions import subscription as sub_mod

    assert not hasattr(sub_mod.Subscription, "_subscribe"), (
        "the bespoke confirmation _subscribe must be deleted in the cutover"
    )
    # The mount API + the native compile seam survive.
    assert hasattr(sub_mod.Subscription, "Field")
    assert hasattr(sub_mod.Subscription, "_build_native_field")
    assert hasattr(sub_mod, "SubscriptionField")


def test_channel_ownership_block_deleted():
    """The channel-ownership registry block is DELETED in the WU11 cutover."""
    from django_graphex.subscriptions import subscription as sub_mod

    # The ownership helpers are gone (the WS socket / HTTP request is the auth
    # boundary now — spec capability 9: the guard MUST NOT be re-introduced).
    assert not hasattr(sub_mod, "register_channel")
    assert not hasattr(sub_mod, "unregister_channel")
    assert not hasattr(sub_mod, "_validate_channel_ownership")
    assert not hasattr(sub_mod, "OperationSubscriptionEnum")

    import importlib

    # The bespoke transport modules are deleted: importing them must fail.
    for module in (
        "django_graphex.subscriptions.consumers",
        "django_graphex.subscriptions.views",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


# ---------------------------------------------------------------------------
# NATIVE compile path: direct GraphQLField (NOT graphene Field).
# ---------------------------------------------------------------------------


def test_native_event_type_carries_gdx_and_snake_resolvers():
    """The native event type carries ``extensions['gdx']`` + snake-closure resolvers.

    Every event field's resolver must carry the ``_gdx_pure_projection`` sentinel
    so COND-B (``guard.py``) whitelists it — proving the WU1 snake-closure wiring
    and the serialize-once safety-net seam (the full per-field auto-gen is WU7).
    """
    from django_graphex.subscriptions.guard import check_subscription_output_type

    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    assert isinstance(event_type, GraphQLObjectType)
    assert (event_type.extensions or {}).get("gdx") is not None

    # Every field carries the sentinel-tagged snake-closure (COND-B whitelist).
    for field_name, field in event_type.fields.items():
        assert getattr(field.resolve, "_gdx_pure_projection", False) is True, field_name

    # COND-B passes for the whole type (no live/unmarked resolver).
    check_subscription_output_type(event_type)


def test_native_field_is_direct_graphql_field_with_reduced_args():
    """``_build_native_field`` returns a DIRECT graphql-core ``GraphQLField``.

    NOT a graphene ``Field``/``SubscriptionField``. ``subscribe`` is a source
    factory; ``resolve`` is identity (the source dict IS the root); args are
    reduced to ``{action, id, filters}`` under native.
    """
    sub = _make_subscription()
    schema = _native_schema(sub)
    field = sub._build_native_field(schema, _DOC)

    # A DIRECT graphql-core ``GraphQLField`` (its class lives in the graphql-core
    # package), NOT a graphene ``Field``: graphene ``Field`` and graphql-core
    # ``GraphQLField`` are disjoint, unrelated classes, so a graphql-core instance
    # whose module is ``graphql.*`` can never be a graphene ``Field``.
    assert isinstance(field, GraphQLField)
    assert type(field).__module__.startswith("graphql")
    # Reduced args under native: action, id, filters (channel_id/operation gone).
    assert set(field.args) == {"action", "id", "filters"}
    # Identity resolve: the source dict IS the root.
    assert field.resolve(_sentinel := object(), None) is _sentinel
    assert callable(field.subscribe)


# ---------------------------------------------------------------------------
# Relation handling on the deliverable-pk seam (no registered node types needed).
#
# DESIGN RECONCILIATION (#1432 §3 vs §8): the serialize-once flat payload
# (backend.to_representation) carries FK -> pk int and M2M -> list of pks, so the
# event type renders FK -> pk scalar (ID) and M2M -> pk-list ([ID]). These are
# leaf scalars/lists derived purely from the related model's pk field — they do
# NOT require a registered related DjangoObjectType node type (the old nested-
# object / results-totalCount container did; the deliverable pk shape does not).
# So every relation field is ALWAYS PRESENT here, even with no node registration.
# The full deliverable contract is asserted in test_capability_parity.py.
# ---------------------------------------------------------------------------


def test_native_event_type_m2m_is_deliverable_pk_list():
    """An M2M wire field is a DELIVERABLE pk-list (``[ID]``), never a bare String.

    ``tests.Post`` has M2M ``tags`` / ``co_authors``. Under the deliverable-pk
    contract the M2M field is ALWAYS PRESENT (no registered related node type
    needed — the pk scalar is derived from the related model's pk field) and is a
    list of pk scalars (``[ID]``), NEVER the old ``coAuthors: String`` stand-in
    and NEVER the DB-backed ``<Model>ListType`` results/totalCount container.
    """
    from graphql import GraphQLID as _GraphQLID
    from graphql import GraphQLList as _GraphQLList
    from graphql import GraphQLObjectType as _ObjType
    from graphql import GraphQLString as _GraphQLString

    sub = _make_subscription()
    event_type = sub._build_native_event_type()

    def _unwrap(t):
        while hasattr(t, "of_type"):
            t = t.of_type
        return t

    for wire in ("tags", "coAuthors"):
        assert wire in event_type.fields, f"{wire} M2M pk-list must be present"
        m2m_type = event_type.fields[wire].type
        # [pk scalar] (auto pk -> [ID]); a leaf list, never a container/String.
        assert isinstance(m2m_type, _GraphQLList), wire
        assert m2m_type.of_type is _GraphQLID, wire
        assert not isinstance(_unwrap(m2m_type), _ObjType), wire
        assert m2m_type is not _GraphQLString, wire

    # Scalars are always present (id/title/body/views) and id is the pk.
    assert "id" in event_type.fields
    assert "title" in event_type.fields
    assert "body" in event_type.fields
    assert "views" in event_type.fields
    # The FK wire field is always present, as the deliverable pk scalar (ID).
    assert "author" in event_type.fields
    assert event_type.fields["author"].type is _GraphQLID


async def test_native_drive_query_without_selected_m2m_delivers_clean():
    """A query NOT selecting an M2M field delivers with NO coercion error.

    The producer payload carries the M2M list (``co_authors=[7, 8]``); the
    document does not select it, so it is ignored and a scalar selection delivers
    cleanly. Under the deliverable-pk contract ``author`` is a pk scalar (``ID``)
    and ``co_authors`` is a pk-list (``[ID]``) — both leaves over the flat payload,
    so neither raises a coercion error even when carried in the payload.
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.streaming import drive_subscription

    layer = InMemoryChannelLayer()
    sub = _make_subscription()
    schema = _native_schema(sub)
    spec = sub._build_native_spec(schema, _DOC_SCALARS)
    source = await sub._native_subscribe(
        layer, schema, _DOC_SCALARS, action="create", obj_id=None, filters=None,
        context=None,
    )
    delivery = drive_subscription(source, spec)

    group = source.joined_groups[0]
    flat = {"id": 1, "title": "hello", "author": 7, "co_authors": [7, 8]}
    await layer.group_send(group, _notify(group, flat))

    result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
    await delivery.aclose()

    assert isinstance(result, ExecutionResult)
    assert result.errors is None
    assert result.data == {"postEvent": {"id": "1", "title": "hello"}}


# ---------------------------------------------------------------------------
# Drive the native field end-to-end via WU5 native_subscribe/drive_subscription.
# ---------------------------------------------------------------------------


def _native_schema(sub) -> GraphQLSchema:
    """Assemble a native subscription schema mounting *sub*'s event type."""
    event_type = sub._build_native_event_type()
    subscription_type = GraphQLObjectType(
        "Subscription",
        lambda: {
            "postEvent": GraphQLField(event_type, resolve=lambda root, _info: root)
        },
    )
    query_type = GraphQLObjectType(
        "Query",
        lambda: {"ok": GraphQLField(__import__("graphql").GraphQLBoolean)},
    )
    return GraphQLSchema(query=query_type, subscription=subscription_type)


_DOC = parse("subscription { postEvent { id title author } }")
# Scalar-only selection (no relation leaf): used by the WU7 full-converter tests
# where a FK with no registered node type is a String placeholder.
_DOC_SCALARS = parse("subscription { postEvent { id title } }")


async def test_native_subscribe_returns_channel_layer_source():
    """The native subscribe factory builds a started ``ChannelLayerSource`` (WU5)."""
    from django_graphex.subscriptions.source import ChannelLayerSource

    layer = _RecordingLayer()
    sub = _make_subscription()
    schema = _native_schema(sub)
    source = await sub._native_subscribe(
        layer, schema, _DOC, action="create", obj_id=None, filters=None, context=None
    )
    try:
        assert isinstance(source, ChannelLayerSource)
        # The action picks exactly ONE group (#1420 — never hardcodes three).
        assert len(source.joined_groups) == 1
        assert len(layer.group_add_calls) == 1
    finally:
        await source.aclose()


async def test_native_drive_delivers_serialize_once_flat_dict():
    """Driving the native source yields a projected flat-dict ExecutionResult.

    The snake-closure resolvers map camelCase wire names to snake payload keys,
    so the projection delivers REAL values over the flat dict (serialize-once;
    NO DB, NO re-serialize).
    """
    from graphql import ExecutionResult

    from django_graphex.subscriptions.streaming import drive_subscription

    layer = InMemoryChannelLayer()
    sub = _make_subscription()
    schema = _native_schema(sub)
    spec = sub._build_native_spec(schema, _DOC_SCALARS)
    source = await sub._native_subscribe(
        layer, schema, _DOC_SCALARS, action="create", obj_id=None, filters=None,
        context=None,
    )
    delivery = drive_subscription(source, spec)

    group = source.joined_groups[0]
    flat = {"id": 1, "title": "hello", "author": 7}
    await layer.group_send(group, _notify(group, flat))

    result = await asyncio.wait_for(delivery.__anext__(), timeout=1.0)
    await delivery.aclose()

    assert isinstance(result, ExecutionResult)
    assert result.errors is None
    assert result.data == {"postEvent": {"id": "1", "title": "hello"}}


async def test_native_authorize_deny_short_circuits_before_group_add():
    """A denying ``authorize_subscription`` raises BEFORE any ``group_add``."""
    from graphql import GraphQLError

    layer = _RecordingLayer()

    sub = _make_subscription()

    def _deny(cls, info, **kwargs):
        raise GraphQLError("denied")

    sub.authorize_subscription = classmethod(_deny)
    schema = _native_schema(sub)

    with pytest.raises(GraphQLError, match="denied"):
        await sub._native_subscribe(
            layer, schema, _DOC, action="create", obj_id=None, filters=None,
            context=None,
        )
    # Deny fired before the source/group existed.
    assert layer.group_add_calls == []


# ---------------------------------------------------------------------------
# db_exists wired: __lookup native subscription DELIVERS verified + DROPS others.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_native_lookup_filter_delivers_verified_and_drops():
    """A ``__lookup`` native subscription DELIVERS a DB-verified event, DROPS others.

    WU6 wires ``spec.db_exists`` = ``Subscription._native_db_exists`` (the
    single-row ``.exists()`` narrowing), so a non-empty ``__lookup`` "remaining"
    filter is verified against the DB and a non-matching event is dropped —
    closing the WU4 conservative-drop gap for the native path.

    Uses ``transaction=True`` + ``database_sync_to_async`` (the repo's e2e
    pattern) so the threadpool ``.exists()`` reads committed rows (no sqlite lock).
    """
    from channels.db import database_sync_to_async

    from django_graphex.subscriptions.streaming import drive_subscription

    @database_sync_to_async
    def _seed():
        author = Author.objects.create(name="alice")
        other = Author.objects.create(name="bob")
        post = Post.objects.create(title="t", author=author)
        other_post = Post.objects.create(title="x", author=other)
        return author, other, post, other_post

    @database_sync_to_async
    def _cleanup():
        Post.objects.all().delete()
        Author.objects.all().delete()

    author, other, post, other_post = await _seed()
    try:
        layer = InMemoryChannelLayer()
        sub = _make_subscription()
        schema = _native_schema(sub)
        spec = sub._build_native_spec(schema, _DOC)
        # spec.db_exists is the REAL single-row .exists() narrowing.
        assert spec.db_exists == sub._native_db_exists
        # Filter on a forward FK lookup that the in-memory equality gate cannot
        # resolve -> needs the DB .exists() narrowing (spec.db_exists).
        source = await sub._native_subscribe(
            layer, schema, _DOC, action="create", obj_id=None,
            filters={"author__name": "alice"}, context=None,
        )
        assert source.db_verify is not None, "native_subscribe must wire db_verify"
        delivery = drive_subscription(source, spec)
        group = source.joined_groups[0]
        # Non-matching: a post whose author is NOT 'alice' -> verifier drops.
        await layer.group_send(
            group,
            _notify(group, {"id": other_post.pk, "title": "x", "author": other.pk}),
        )
        # Matching: the real post under author=alice -> verifier delivers.
        await layer.group_send(
            group, _notify(group, {"id": post.pk, "title": "t", "author": author.pk}),
        )
        result = await asyncio.wait_for(delivery.__anext__(), timeout=2.0)
        await delivery.aclose()
        assert result.data["postEvent"]["id"] == str(post.pk)
    finally:
        await _cleanup()


# ---------------------------------------------------------------------------
# INDEX-ROUTING RECONCILIATION: SCOPE-ONLY parity with the kept _subscribe hook.
# ---------------------------------------------------------------------------


async def test_index_routing_is_scope_only_not_client_filter():
    """Index routing uses SCOPE-ONLY (parity with the kept ``_subscribe`` hook).

    A CLIENT-supplied index-field value must NOT narrow the joined group — only a
    server ``subscription_scope`` value does. This is the WU5 SUGGESTION
    reconciliation: the kept hook routes on ``scope``, never on ``merged`` (client
    ∪ scope), so a client cannot pick a value-scoped group it shouldn't see.
    """
    layer = _RecordingLayer()
    sub = _make_subscription(subscription_index_fields=("author",))
    schema = _native_schema(sub)

    # Client tries to supply the index field value, but scope does NOT -> the
    # subscribe must FALL BACK to the coarse group (scope-only routing).
    source = await sub._native_subscribe(
        layer, schema, _DOC, action="create", obj_id=None,
        filters={"author": 5}, context=None,
    )
    try:
        coarse = sub._group_name("create")
        assert source.joined_groups == [coarse], (
            "client-supplied index value must NOT route to a value-scoped group"
        )
    finally:
        await source.aclose()


async def test_index_routing_uses_server_scope_value():
    """When ``subscription_scope`` supplies the index field, route value-scoped."""
    layer = _RecordingLayer()
    sub = _make_subscription(subscription_index_fields=("author",))

    def _scope(cls, info, **kwargs):
        return {"author": 5}

    sub.subscription_scope = classmethod(_scope)
    schema = _native_schema(sub)

    source = await sub._native_subscribe(
        layer, schema, _DOC, action="create", obj_id=None, filters=None, context=None
    )
    try:
        expected = sub._group_name("create", index={"author": 5})
        assert source.joined_groups == [expected]
        assert source.joined_groups != [sub._group_name("create")]
    finally:
        await source.aclose()


# ---------------------------------------------------------------------------
# No NEW graphene import on the native seam (the no-graphene gate is per-module;
# subscription.py KEEPS its existing graphene imports for the graphene path).
# ---------------------------------------------------------------------------


def test_native_field_does_not_use_graphene_field():
    """The native field builder must not return a graphene ``Field`` subclass.

    Proven graphene-free: the returned field's class is defined in the graphql-core
    package (``graphql.*``). A graphene ``Field`` lives in the ``graphene`` package
    and is an unrelated class, so a ``graphql.*`` field is provably not one.
    """
    sub = _make_subscription()
    schema = _native_schema(sub)
    field = sub._build_native_field(schema, _DOC)
    assert isinstance(field, GraphQLField)
    assert type(field).__module__.startswith("graphql")
