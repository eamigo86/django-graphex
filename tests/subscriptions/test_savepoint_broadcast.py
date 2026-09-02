"""Subscription coverage for the savepoint-free create path."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from channels.layers import channel_layers, get_channel_layer
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_graphex.subscriptions import Subscription
from tests.core.test_savepoint_only_when_needed import (
    PlainCategoryType,
    _create,
    _savepoint_sql,
)
from tests.models import Category

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.mark.django_db(transaction=True)
def test_plain_create_still_broadcasts(monkeypatch: MonkeyPatch) -> None:  # noqa: DOC003, E501
    """A plain autocommit create broadcasts without opening a savepoint.
    This protects the savepoint-free regression contract."""
    channel_layers.backends = {}

    class CategorySubscription(Subscription):
        class Meta:
            model = Category
            stream = "p5_categories"
            payload_mode = "id_only"

    binding = CategorySubscription.get_binding()
    binding.register()

    sends = []
    layer = get_channel_layer()
    original = layer.group_send

    async def _recording(group, message):
        sends.append((group, message))
        return await original(group, message)

    monkeypatch.setattr(layer, "group_send", _recording)

    try:
        with CaptureQueriesContext(connection) as ctx:
            result = _create(PlainCategoryType, {"title": "Broadcasted"})
        assert result.ok, getattr(result, "errors", None)
        assert _savepoint_sql(ctx.captured_queries) == []
        streams = {message.get("stream") for _, message in sends}
        assert "p5_categories" in streams
    finally:
        binding.unregister()
        channel_layers.backends = {}
