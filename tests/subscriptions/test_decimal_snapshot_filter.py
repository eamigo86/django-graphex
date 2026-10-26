"""Native subscription regressions for Decimal equality against event snapshots."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from graphql import GraphQLSchema

pytest.importorskip("channels")

from channels.layers import get_channel_layer  # noqa: E402
from django.db import models  # noqa: E402

from django_graphex.subscriptions import Subscription  # noqa: E402
from tests.models import ScalarKindsModel  # noqa: E402
from tests.subscriptions._sse import sse_frames  # noqa: E402


def _build_schema() -> GraphQLSchema:
    """Build a native schema with a generated Decimal subscription filter.

    Returns:
        The native GraphQL schema for scalar-kind events.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.schema import DjangoGraphQLSchema
    from django_graphex.types import DjangoModelType

    class ScalarType(DjangoModelType):
        class Meta:
            model = ScalarKindsModel
            stream = "decimal_snapshot_test"
            payload_mode = "full"

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        scalar = ScalarType.SubscriptionField()

    compile_all_outputs()
    return DjangoGraphQLSchema(
        query=Query, subscription=SubscriptionRoot
    ).graphql_schema


_SCHEMA = _build_schema()


class _WideDecimalModel(models.Model):
    """Unpersisted model with a valid high-precision Decimal field."""

    amount = models.DecimalField(max_digits=300, decimal_places=255)

    class Meta:
        """Keep the regression model outside migration and database setup."""

        app_label = "tests"
        managed = False


class _WideDecimalSubscription(Subscription):
    """Expose the wide model through the real native subscription path."""

    class Meta:
        """Send complete event snapshots for the high-precision model."""

        model = _WideDecimalModel
        stream = "wide_decimal_snapshot_test"
        payload_mode = "full"


def _build_wide_schema() -> GraphQLSchema:
    """Build the native public subscription for the wide Decimal model.

    Returns:
        The schema exposing a generated Decimal exact filter.
    """
    from graphql import GraphQLBoolean

    from django_graphex.core import ObjectType, field
    from django_graphex.schema import DjangoGraphQLSchema

    class Query(ObjectType):
        ok = field(GraphQLBoolean)

    class SubscriptionRoot(ObjectType):
        wide = _WideDecimalSubscription.Field()

    return DjangoGraphQLSchema(
        query=Query, subscription=SubscriptionRoot
    ).graphql_schema


_WIDE_SCHEMA = _build_wide_schema()


class _User:
    """Minimal authenticated user for the SSE transport boundary."""

    is_authenticated = True
    pk = 1


def _request(action: str = "CREATE") -> Any:
    """Create a real HTTP request with a Decimal GraphQL filter variable.

    Args:
        action: The notification action selected by the subscription.

    Returns:
        The authenticated subscription request.
    """
    from django.test import RequestFactory

    body = {
        "query": (
            f"subscription($d: Decimal!) {{ scalar(action: {action}, "
            "filter: {decimal: {exact: $d}}) { id decimal } }"
        ),
        "variables": {"d": "1.0"},
    }
    request = RequestFactory().post(
        "/subscriptions/sse", data=json.dumps(body), content_type="application/json"
    )
    request.user = _User()
    return request


def _wide_request() -> Any:
    """Create a native GraphQL request with a typed Decimal variable.

    Returns:
        The authenticated subscription request.
    """
    from django.test import RequestFactory

    body = {
        "query": (
            "subscription($d: Decimal!) { wide(action: CREATE, "
            "filter: {amount: {exact: $d}}) { id amount } }"
        ),
        "variables": {"d": "1.0"},
    }
    request = RequestFactory().post(
        "/subscriptions/sse", data=json.dumps(body), content_type="application/json"
    )
    request.user = _User()
    return request


async def _next_payload(response: Any) -> dict[str, Any]:
    """Read one delivered GraphQL result from the SSE stream.

    Args:
        response: The started SSE response.

    Returns:
        The decoded result frame.
    """
    frame = await asyncio.wait_for(sse_frames(response).__anext__(), timeout=2.0)
    decoded = frame.decode() if isinstance(frame, bytes) else frame
    line = next(line for line in decoded.splitlines() if line.startswith("data: "))
    return json.loads(line[len("data: ") :])


@pytest.mark.parametrize("action", ["CREATE", "DELETE"])
async def test_native_decimal_filter_matches_snapshot_with_different_scale(
    action: str,
) -> None:
    """Typed Decimal equality must work on full create and detached delete data.

    Args:
        action: The event action to deliver over the public subscription.
    """
    from django_graphex.subscriptions.transports import sse

    response = await sse.subscription_sse_view(schema=_SCHEMA)(_request(action))
    assert response.status_code == 200
    source = sse.get_started_source(response)
    assert source is not None
    assert isinstance(source.filters["decimal"], Decimal)
    assert source.filters["decimal"].as_tuple().exponent == -1

    group = source.joined_groups[0]
    message = {
        "type": "subscription.notify",
        "stream": "decimal_snapshot_test",
        "group": group,
        "pk": 1,
        "payload": {
            "action": action.lower(),
            "model": "tests.scalarkindsmodel",
            "data": {"id": 1, "decimal": "1.00"},
        },
    }
    try:
        await get_channel_layer().group_send(group, message)
        result = await _next_payload(response)
    finally:
        await source.aclose()

    assert result.get("errors") in (None, [])
    assert result["data"] == {"scalar": {"id": "1", "decimal": "1.00"}}


async def test_native_wide_decimal_filter_matches_valid_model_snapshot() -> None:
    """Match a valid wide model value through the public native SSE path.

    The model remains unpersisted, so delivery must use the event snapshot
    rather than retrieving any current database row.
    """
    from django_graphex.subscriptions.transports import sse

    value = Decimal("1." + "0" * 255)
    model = _WideDecimalModel(id=1, amount=value)
    field = model._meta.get_field("amount")
    assert field.clean(value, model) == value
    snapshot = _WideDecimalSubscription._serialize_payload(model)
    assert snapshot["amount"] == str(value)
    assert len(snapshot["amount"]) == 257
    assert model._state.adding

    response = await sse.subscription_sse_view(schema=_WIDE_SCHEMA)(_wide_request())
    assert response.status_code == 200
    source = sse.get_started_source(response)
    assert source is not None
    assert source.filters == {"amount": Decimal("1.0")}

    group = source.joined_groups[0]
    message = {
        "type": "subscription.notify",
        "stream": "wide_decimal_snapshot_test",
        "group": group,
        "pk": 1,
        "payload": {
            "action": "create",
            "model": "tests._widedecimalmodel",
            "data": snapshot,
        },
    }
    try:
        await get_channel_layer().group_send(group, message)
        result = await _next_payload(response)
    finally:
        await source.aclose()

    assert result.get("errors") in (None, [])
    assert result["data"] == {"wide": {"id": "1", "amount": snapshot["amount"]}}


def test_decimal_snapshot_gate_preserves_non_decimal_and_fallback_filters() -> None:
    """Keep existing string, Float, UUID and unresolved-filter behavior.

    Only typed finite Decimal mismatches gain numeric snapshot equality. This
    gate remains in memory even for a detached event with no live model row.
    """
    from django_graphex.subscriptions.mixins import split_filters

    snapshot = {
        "decimal": "1.00",
        "id": 1,
        "uuid": "12345678-1234-5678-1234-567812345678",
    }
    assert split_filters(snapshot, {"decimal": Decimal("1.0")}) == {}
    assert split_filters(snapshot, {"decimal": Decimal("2.0")}) is None
    assert split_filters(snapshot, {"decimal": "1.0"}) is None
    assert split_filters(snapshot, {"decimal": "1.00"}) == {}
    assert split_filters(snapshot, {"decimal": 1.0}) is None
    assert split_filters({"decimal": 1}, {"decimal": Decimal("1.0")}) == {}
    assert split_filters({"decimal": 1}, {"decimal": Decimal("2.0")}) is None
    assert split_filters(snapshot, {"decimal": Decimal("NaN")}) is None
    assert split_filters(snapshot, {"id": 1}) == {}
    assert split_filters(snapshot, {"uuid": UUID(snapshot["uuid"])}) == {}

    assert split_filters({"decimal": "invalid"}, {"decimal": Decimal("1")}) is None
    assert split_filters({"decimal": "NaN"}, {"decimal": Decimal("1")}) is None
    assert split_filters({"decimal": "1" * 257}, {"decimal": Decimal("1")}) is None
    assert split_filters({"decimal": "NaN"}, {"decimal": Decimal("NaN")}) == {}
    assert split_filters(snapshot, {"decimal__exact": Decimal("1")}) == {
        "decimal__exact": Decimal("1")
    }
    assert split_filters({"id": 1}, {"decimal": Decimal("1")}) == {
        "decimal": Decimal("1")
    }
