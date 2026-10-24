"""Exact finite Float equality for real native subscription snapshots."""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.db import connection, models, transaction
from django.db.models.signals import post_save
from graphql import ExecutionResult, GraphQLBoolean, parse, subscribe

from django_graphex.core import ObjectType, field
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.subscriptions import Subscription
from django_graphex.subscriptions.mixins import split_filters
from tests._schema_isolation import isolated_pair
from tests.models import ScalarKindsModel


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("stored", "expected", "syntax", "delivers"),
    [
        (-0.0, 0.0, "variable", True),
        (0.0, -0.0, "variable", True),
        (-0.0, -0.0, "variable", True),
        (0.0, 0.0, "variable", True),
        (1.25, 1.25, "variable", True),
        (1.25, 1.5, "variable", False),
        (1.0, 1, "literal", True),
        (1.0, 1, "variable", True),
    ],
)
async def test_real_float_field_exact_event(
    stored: float, expected: float | int, syntax: str, delivers: bool
) -> None:
    """Deliver exactly equal FloatField events through the native signal path.

    Args:
        stored: Value saved to an actual FloatField.
        expected: GraphQL exact-filter input.
        syntax: Whether the input uses a literal or variable.
        delivers: Whether the event must reach the subscriber.
    """
    assert isinstance(ScalarKindsModel._meta.get_field("floating"), models.FloatField)
    label = f"mu3_{stored.hex()}_{float(expected).hex()}_{syntax}".replace("-", "n")
    parsed_filters: list[dict[str, Any]] = []

    class FloatSubscription(Subscription):
        """Expose the actual model's FloatField in full-payload mode."""

        class Meta:
            """Select the existing model and one isolated stream."""

            model = ScalarKindsModel
            stream = label
            payload_mode = "full"
            only_fields = ("id", "floating", "char")

        @classmethod
        def subscription_scope(cls, info: Any, **kwargs: Any) -> dict[str, Any]:
            """Observe GraphQL coercion without modifying client scope.

            Args:
                info: Native subscription context.
                **kwargs: Coerced subscription arguments.

            Returns:
                An empty server-forced filter mapping.
            """
            parsed_filters.append(kwargs["filters"])
            return {}

    class Query(ObjectType):
        """Supply the schema's required query root."""

        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        """Mount the public generated subscription field."""

        item = FloatSubscription.Field()

    schema = DjangoGraphQLSchema(
        query=Query,
        subscription=SubscriptionRoot,
        registries=isolated_pair(Registry()),
    ).graphql_schema
    binding = FloatSubscription.get_binding()
    layer = get_channel_layer()
    consumed = asyncio.Event()
    received: list[dict[str, Any]] = []
    signals: list[tuple[float, bool]] = []
    original_receive = layer.receive

    async def record_receive(channel: str) -> dict[str, Any]:
        """Observe a real backend receive without replacing its behavior.

        Args:
            channel: The joined subscriber channel.

        Returns:
            The unchanged message from the actual channel layer.
        """
        message = await original_receive(channel)
        received.append(message)
        consumed.set()
        return message

    def record_signal(sender: Any, instance: Any, **kwargs: Any) -> None:
        """Observe the saved value before transaction commit.

        Args:
            sender: The actual model class.
            instance: The actual saved instance.
            **kwargs: Django signal metadata.
        """
        signals.append((instance.floating, connection.in_atomic_block))

    layer.receive = record_receive
    post_save.connect(record_signal, sender=ScalarKindsModel, weak=False)
    stream: Any = None
    next_event: asyncio.Task[Any] | None = None
    try:
        if syntax == "literal":
            query = (
                "subscription { item(action: CREATE, filter: "
                f"{{floating: {{exact: {expected}}}}}) {{ id floating }} }}"
            )
            variables = None
        else:
            query = (
                "subscription FloatCase($value: Float!) { item(action: CREATE, "
                "filter: {floating: {exact: $value}}) { id floating } }"
            )
            variables = {"value": expected}
        opened = subscribe(schema, parse(query), variable_values=variables)
        stream = await opened if inspect.isawaitable(opened) else opened
        assert not isinstance(stream, ExecutionResult)
        assert len(parsed_filters) == 1
        assert type(parsed_filters[0]["floating"]) is float

        def save_row() -> ScalarKindsModel:
            """Commit one actual model write after the source joins.

            Returns:
                The saved instance carrying its original float sign.
            """
            with transaction.atomic():
                row = ScalarKindsModel.objects.create(char=label[:50], floating=stored)
            return row

        row = await sync_to_async(save_row, thread_sensitive=True)()
        assert signals == [(stored, True)]
        assert row.floating.hex() == stored.hex()
        next_event = asyncio.create_task(stream.__anext__())
        await asyncio.wait_for(consumed.wait(), timeout=1.0)
        assert len(received) == 1
        assert received[0]["payload"]["data"]["floating"].hex() == stored.hex()
        if delivers:
            event = await asyncio.wait_for(next_event, timeout=0.5)
            assert not event.errors
            assert event.data["item"]["floating"] == stored
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(next_event, timeout=0.25)
    finally:
        if next_event is not None and not next_event.done():
            next_event.cancel()
            await asyncio.gather(next_event, return_exceptions=True)
        if stream is not None and hasattr(stream, "aclose"):
            await stream.aclose()
        post_save.disconnect(record_signal, sender=ScalarKindsModel)
        binding.unregister()
        layer.receive = original_receive
        assert not any(layer.groups.values())
        assert not any(queue.qsize() for queue in layer.channels.values())


def test_float_pair_only_changes_finite_exact_equality() -> None:
    """Preserve all legacy and typed boundaries outside finite float pairs.

    Scenario: float pair only changes finite exact equality.
    """
    controls: list[tuple[Any, Any, bool]] = [
        (-0.0, 0.0, True),
        (0.0, -0.0, True),
        ("-0.0", "0.0", False),
        ("-0.0", 0.0, False),
        (-0.0, "0.0", False),
        (7, "7", True),
        (True, "True", True),
        (None, "None", True),
        (False, 0.0, False),
        ("1.00", Decimal("1.0"), True),
        (
            "2026-10-18T12:00:00+00:00",
            datetime.fromisoformat("2026-10-18T12:00:00+00:00"),
            True,
        ),
        (float("inf"), float("inf"), True),
        (float("inf"), float("-inf"), False),
        (1.0, float("inf"), False),
        (float("nan"), float("nan"), True),
        (float("nan"), 1.0, False),
    ]
    for snapshot, expected, matches in controls:
        assert (
            split_filters({"value": snapshot}, {"value": expected}) == {}
        ) is matches
    assert split_filters({"value": 1.0}, {"value__exact": 1.0}) == {"value__exact": 1.0}
    assert split_filters({}, {"value": 1.0}) == {"value": 1.0}
