# -*- coding: utf-8 -*-
"""Indexed subscription groups (the optional "don't wake everyone" optimization).

The key invariant is that the subscribe side (which builds a group name from each
subscriber's ``subscription_scope``) and the broadcast side (which builds it from
the changed instance) produce the **same** name -- so notifications reach only the
matching subscribers without ever enumerating groups.
"""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.core.exceptions import FieldDoesNotExist

from django_graphex import DjangoModelType
from django_graphex.subscriptions import GraphqlAPIDemultiplexer, Subscription
from tests.models import HookModel, Post

from .helpers import run_subscribe


class _IdxSub(Subscription):
    class Meta:
        model = HookModel
        stream = "idx-unit"
        serialize_data = True
        subscription_index_fields = ("text",)


class _PostSub(Subscription):
    class Meta:
        model = Post
        stream = "idx-post"
        subscription_index_fields = ("author",)


# --------------------------------------------------------------------------- #
# Group-name construction                                                     #
# --------------------------------------------------------------------------- #
def test_index_suffix_is_sorted_and_value_sensitive():
    # Keys are sorted -> the suffix is order-independent.
    assert _IdxSub._group_name("create", index={"b": 2, "a": 1}) == _IdxSub._group_name(
        "create", index={"a": 1, "b": 2}
    )
    # Different values -> different groups.
    assert _IdxSub._group_name("create", index={"a": 1}) != _IdxSub._group_name(
        "create", index={"a": 2}
    )
    # No index -> identical to the traditional coarse group (back-compat).
    assert _IdxSub._group_name("create") == _IdxSub._group_name("create", index=None)
    assert _IdxSub._group_name("create") != _IdxSub._group_name(
        "create", index={"text": "keep"}
    )


def test_subscribe_side_and_notify_side_build_the_same_group():
    """The crux: scope-built name == instance-built name."""
    # Subscribe side: from the scope mapping {text: "keep"}.
    from_scope = _IdxSub._group_name("create", index={"text": "keep"})
    # Notify side: from a live instance via _instance_index.
    instance = HookModel(text="keep")
    from_instance = _IdxSub._group_name(
        "create", index=_IdxSub._instance_index(instance)
    )
    assert from_scope == from_instance
    # Per-object + index combine too.
    assert _IdxSub._group_name(
        "update", id=7, index={"text": "x"}
    ) == _IdxSub._group_name("update", id=7, index={"text": "x"})


def test_instance_index_reads_fk_as_id_without_a_query():
    # author_id is set directly: reading the index must NOT touch the related row.
    post = Post(title="t", author_id=7)
    assert _PostSub._instance_index(post) == {"author": 7}


def test_instance_index_is_none_without_index_fields():
    class _Plain(Subscription):
        class Meta:
            model = HookModel
            stream = "idx-plain"

    assert _Plain._instance_index(HookModel(text="x")) is None


# --------------------------------------------------------------------------- #
# Validation & plumbing                                                       #
# --------------------------------------------------------------------------- #
def test_unknown_index_field_fails_fast_at_definition():
    with pytest.raises(FieldDoesNotExist):

        class _Bad(Subscription):
            class Meta:
                model = HookModel
                stream = "idx-bad"
                subscription_index_fields = ("does_not_exist",)


def test_serializer_type_forwards_index_fields_to_generated_subscription():
    class _T(DjangoModelType):
        class Meta:
            model = HookModel
            stream = "idx-forward"
            subscription_index_fields = ("text",)

    assert _T.subscription_type()._meta.index_fields == ("text",)


def test_index_fields_default_empty_keeps_coarse_behavior():
    class _T(DjangoModelType):
        class Meta:
            model = HookModel
            stream = "idx-default"

    assert _T.subscription_type()._meta.index_fields == ()


# --------------------------------------------------------------------------- #
# End-to-end: routing actually reaches only the matching group                #
# --------------------------------------------------------------------------- #
class _IdxType(DjangoModelType):
    class Meta:
        model = HookModel
        stream = "idx-e2e"
        serialize_data = True
        subscription_index_fields = ("text",)

    @classmethod
    def subscription_scope(cls, info, **kwargs):
        return {"text": "keep"}


class _IdxDemux(GraphqlAPIDemultiplexer):
    subscriptions = {_IdxType}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_indexed_delivery_end_to_end():
    """A save routed to a different indexed group never reaches the subscriber;
    one routed to the subscriber's group does -- proving both sides agree."""
    sub_cls = _IdxType.subscription_type()
    communicator = WebsocketCommunicator(_IdxDemux.as_asgi(), "/ws/")
    try:
        connected, _ = await communicator.connect()
        assert connected
        handshake = await communicator.receive_json_from()

        # Subscriber is scoped to text="keep" -> joins "...-create:text=keep".
        await run_subscribe(
            sub_cls,
            channel_id=handshake["channel_id"],
            action="create",
            operation="subscribe",
        )

        # Routed to ":text=drop" -> the subscriber is not in that group.
        await database_sync_to_async(HookModel.objects.create)(text="drop")
        assert await communicator.receive_nothing(timeout=0.3) is True

        # Routed to ":text=keep" -> delivered (names matched by construction).
        await database_sync_to_async(HookModel.objects.create)(text="keep")
        frame = await communicator.receive_json_from()
        assert frame["payload"]["data"]["text"] == "keep"
    finally:
        await communicator.disconnect()
        # HookModel group names are model-derived and shared across streams, so
        # unregister this stream's signal binding to keep it from firing into
        # later same-model tests.
        sub_cls.get_binding().unregister()
        if "_binding" in sub_cls.__dict__:
            delattr(sub_cls, "_binding")
