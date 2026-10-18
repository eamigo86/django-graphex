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
