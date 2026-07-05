# -*- coding: utf-8 -*-
"""Native (Pydantic) subscriptions: serialize the payload without DRF."""

from __future__ import annotations

import pytest
from django.db import models

from django_graphex.core.backend import PydanticBackend
from django_graphex.subscriptions import Subscription
from tests.models import DummyModel


class SubNativeThing(DummyModel):
    """A minimal Django model used to exercise the native subscription backend.

    Carries a name and an optional note so tests can assert on serialized
    field values in the broadcast payload.
    """

    name = models.CharField(max_length=50)
    note = models.TextField(default="")


class ThingNativeSubscription(Subscription):
    """Subscription over "SubNativeThing" using the Pydantic native backend.

    Has no serializer_class, so the backend resolution falls back to the
    native Pydantic path instead of DRF.
    """

    class Meta:
        """Configuration selecting the native backend.

        No serializer_class is set, so no DRF dependency is involved.
        """

        model = SubNativeThing  # native backend; no serializer_class, no DRF
        stream = "things-native"
        payload_mode = "full"


def test_native_subscription_uses_native_backend() -> None:
    """A Subscription with no serializer_class must resolve to PydanticBackend.

    Contract: subscriptions without a DRF serializer ship broken if they fall
    back to a different backend than the native Pydantic one.
    """
    assert isinstance(ThingNativeSubscription._meta.backend, PydanticBackend)
    assert ThingNativeSubscription._meta.model is SubNativeThing


def test_no_data_projection_argument_after_cutover() -> None:
    """The post-WU11 argument set must stay reduced to action/id/filters.

    Contract: the bespoke "data" field-projection enum must not reappear even
    when payload_mode is "full", since field selection is now driven by the
    GraphQL selection set.
    """
    # The bespoke ``data`` field-projection enum is gone post-WU11: field
    # selection is the GraphQL selection set now, so the native arg set is the
    # reduced {action, id, filters} regardless of payload_mode='full'.
    args = set(ThingNativeSubscription._meta.arguments)
    assert "data" not in args
    assert args == {"action", "id", "filters"}


@pytest.mark.django_db(transaction=True)
def test_native_subscription_serializes_payload(
    captured_group_sends: list[tuple[str, dict]],
) -> None:
    """A native-backend subscription must broadcast a fully serialized payload.

    Args:
        captured_group_sends: The (group, message) pairs recorded by the
            captured_group_sends fixture for every group_send call.
    """
    # transaction=True ensures on_commit fires so the broadcast is delivered.
    ThingNativeSubscription.get_binding()
    thing = SubNativeThing.objects.create(name="Widget", note="hello")

    payloads = [message["payload"] for _, message in captured_group_sends]
    assert payloads, "no broadcast captured"
    data = payloads[0]["data"]
    assert data["name"] == "Widget"
    assert data["note"] == "hello"
    assert data["id"] == thing.pk
