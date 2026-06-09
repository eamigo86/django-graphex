# -*- coding: utf-8 -*-
"""T-PAYLOAD: configurable notification payload (id-only default vs full).

Covers the ``SUBSCRIPTION_SERIALIZE_DATA`` setting, the ``Meta.serialize_data``
override, and the conditional ``data`` argument. These use ``BasicModel`` so the
bindings never clash with the (full-mode) ``UserSubscription`` of the shared
schema.
"""

from unittest import mock

from django_graphex.subscriptions import Subscription, bindings
from tests.models import BasicModel


class BasicDefaultSubscription(Subscription):
    class Meta:
        model = BasicModel
        stream = "basic_default"  # serialize_data unset -> inherit global setting


class BasicFullSubscription(Subscription):
    class Meta:
        model = BasicModel
        stream = "basic_full"
        serialize_data = True


class BasicIdOnlySubscription(Subscription):
    class Meta:
        model = BasicModel
        stream = "basic_idonly"
        serialize_data = False


def _sends_for(captured, stream):
    return [message for _, message in captured if message["stream"] == stream]


def _broadcast_on_create(subscription_cls, captured, stream):
    """Register ``subscription_cls``, create a ``BasicModel`` and return its sends."""
    binding = subscription_cls.get_binding()
    binding.register()  # idempotent; the cached binding may have been unregistered
    try:
        instance = BasicModel.objects.create(text="payload")
    finally:
        binding.unregister()
    return instance, _sends_for(captured, stream)


# -- AC1: default is id-only, no serialization ------------------------------- #
def test_default_is_id_only_and_skips_serialization(db, captured_group_sends):
    with mock.patch.object(
        bindings, "serialize_instance", wraps=bindings.serialize_instance
    ) as spy:
        instance, sends = _broadcast_on_create(
            BasicDefaultSubscription, captured_group_sends, "basic_default"
        )

    assert spy.call_count == 0
    assert sends and sends[0]["payload"]["data"] == {"id": instance.pk}


# -- AC2: global setting switches the inheriting subscription to full -------- #
def test_global_setting_enables_full(db, captured_group_sends, serialize_full):
    with mock.patch.object(
        bindings, "serialize_instance", wraps=bindings.serialize_instance
    ) as spy:
        instance, sends = _broadcast_on_create(
            BasicDefaultSubscription, captured_group_sends, "basic_default"
        )

    assert spy.call_count == 1
    assert sends and sends[0]["payload"]["data"]["text"] == "payload"


# -- AC3: Meta override beats the global setting ----------------------------- #
def test_meta_full_overrides_global_id_only(db, captured_group_sends):
    # Global stays at the id-only default; Meta forces full.
    instance, sends = _broadcast_on_create(
        BasicFullSubscription, captured_group_sends, "basic_full"
    )
    assert sends and sends[0]["payload"]["data"]["text"] == "payload"


def test_meta_id_only_overrides_global_full(db, captured_group_sends, serialize_full):
    # Global forced to full; Meta forces id-only.
    instance, sends = _broadcast_on_create(
        BasicIdOnlySubscription, captured_group_sends, "basic_idonly"
    )
    assert sends and sends[0]["payload"]["data"] == {"id": instance.pk}


# -- AC4: the `data` argument exists only in full mode ----------------------- #
def test_data_argument_present_only_in_full_mode():
    assert "data" in BasicFullSubscription._meta.arguments
    assert "data" not in BasicIdOnlySubscription._meta.arguments
    # BasicDefaultSubscription inherits the (id-only) global default at import.
    assert "data" not in BasicDefaultSubscription._meta.arguments
