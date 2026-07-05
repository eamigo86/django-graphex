# -*- coding: utf-8 -*-
"""Fixtures shared by the subscription tests.

The whole subpackage is skipped automatically when the optional "channels"
dependency is not installed (the base-install CI job).
"""

from __future__ import annotations

from typing import Any, Generator

import pytest

channels = pytest.importorskip("channels")


@pytest.fixture(autouse=True)
def _fresh_channel_layer() -> Generator[None, None, None]:
    """Give every test an isolated in-memory channel layer instance.

    Resetting "channel_layers.backends" between tests prevents a stale layer
    (and its joined groups) from leaking across the transport-agnostic suites.

    Yields:
        None. Only the reset side effect before and after the test matters.
    """
    from channels.layers import channel_layers

    channel_layers.backends = {}
    yield
    channel_layers.backends = {}


@pytest.fixture
def captured_group_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, Any]]]:
    """Record every "group_send" performed by the binding.

    Args:
        monkeypatch: The pytest fixture used to patch the channel layer's
            group_send method with a recording wrapper.

    Returns:
        sends: The list that recorded (group, message) pairs are appended
            to as the test runs.
    """
    from channels.layers import get_channel_layer

    sends: list[tuple[str, dict[str, Any]]] = []
    channel_layer = get_channel_layer()
    original = channel_layer.group_send

    async def _recording_group_send(group: str, message: dict[str, Any]) -> Any:
        sends.append((group, message))
        return await original(group, message)

    monkeypatch.setattr(channel_layer, "group_send", _recording_group_send)
    return sends


@pytest.fixture
def serialize_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force subscriptions into full-serialization mode for this test.

    Patches the settings object referenced inside "subscription" so
    "_payload_is_full" sees the global default as "full".

    Args:
        monkeypatch: The pytest fixture used to patch the shared settings
            object's SUBSCRIPTION_PAYLOAD_MODE attribute.
    """
    from django_graphex.subscriptions import subscription

    monkeypatch.setattr(
        subscription.graphql_api_settings, "SUBSCRIPTION_PAYLOAD_MODE", "full"
    )
