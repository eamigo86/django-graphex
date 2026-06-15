# -*- coding: utf-8 -*-
"""Native (Pydantic) subscriptions: serialize the payload without DRF."""

import pytest
from django.db import models

from django_graphex.native.backend import PydanticBackend
from django_graphex.subscriptions import Subscription
from tests.models import DummyModel


class SubNativeThing(DummyModel):
    name = models.CharField(max_length=50)
    note = models.TextField(default="")


class ThingNativeSubscription(Subscription):
    class Meta:
        model = SubNativeThing  # native backend; no serializer_class, no DRF
        stream = "things-native"
        serialize_data = True


def test_native_subscription_uses_native_backend():
    assert isinstance(ThingNativeSubscription._meta.backend, PydanticBackend)
    assert ThingNativeSubscription._meta.model is SubNativeThing


def test_no_data_projection_argument_after_cutover():
    # The bespoke ``data`` field-projection enum is gone post-WU11: field
    # selection is the GraphQL selection set now, so the native arg set is the
    # reduced {action, id, filters} regardless of serialize_data=True.
    args = set(ThingNativeSubscription._meta.arguments)
    assert "data" not in args
    assert args == {"action", "id", "filters"}


@pytest.mark.django_db(transaction=True)
def test_native_subscription_serializes_payload(captured_group_sends):
    # transaction=True ensures on_commit fires so the broadcast is delivered.
    ThingNativeSubscription.get_binding()
    thing = SubNativeThing.objects.create(name="Widget", note="hello")

    payloads = [message["payload"] for _, message in captured_group_sends]
    assert payloads, "no broadcast captured"
    data = payloads[0]["data"]
    assert data["name"] == "Widget"
    assert data["note"] == "hello"
    assert data["id"] == thing.pk
