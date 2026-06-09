# -*- coding: utf-8 -*-
"""Fixtures shared by the subscription tests.

The whole subpackage is skipped automatically when the optional ``channels``
dependency is not installed (the base-install CI job).
"""

import pytest

channels = pytest.importorskip("channels")


@pytest.fixture(autouse=True)
def _fresh_channel_layer():
    """Give every test an isolated in-memory channel layer instance."""
    from channels.layers import channel_layers

    channel_layers.backends = {}
    yield
    channel_layers.backends = {}


@pytest.fixture
def captured_group_sends(monkeypatch):
    """Record every ``group_send`` performed by the binding."""
    from channels.layers import get_channel_layer

    sends = []
    channel_layer = get_channel_layer()
    original = channel_layer.group_send

    async def _recording_group_send(group, message):
        sends.append((group, message))
        return await original(group, message)

    monkeypatch.setattr(channel_layer, "group_send", _recording_group_send)
    return sends


@pytest.fixture
def serialize_full(monkeypatch):
    """Force subscriptions into full-serialization mode for this test.

    Patches the settings object referenced inside ``subscription`` so
    ``_should_serialize_data`` sees the global default as ``True``.
    """
    from django_graphex.subscriptions import subscription

    monkeypatch.setattr(
        subscription.graphql_api_settings, "SUBSCRIPTION_SERIALIZE_DATA", True
    )
