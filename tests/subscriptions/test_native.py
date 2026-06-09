# -*- coding: utf-8 -*-
"""Native (Pydantic) subscriptions: serialize the payload without DRF."""

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


def test_data_argument_enum_from_model_fields():
    # serialize_data=True adds the `data` arg whose enum lists the model fields.
    assert "data" in ThingNativeSubscription._meta.arguments
    enum = ThingNativeSubscription._meta.arguments["data"].of_type
    members = {m.value for m in enum._meta.enum}
    assert {"id", "name", "note"} <= members


def test_native_subscription_serializes_payload(db, captured_group_sends):
    ThingNativeSubscription.get_binding()
    thing = SubNativeThing.objects.create(name="Widget", note="hello")

    payloads = [message["payload"] for _, message in captured_group_sends]
    assert payloads, "no broadcast captured"
    data = payloads[0]["data"]
    assert data["name"] == "Widget"
    assert data["note"] == "hello"
    assert data["id"] == thing.pk
