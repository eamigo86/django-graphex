"""Pin the documented type-mapping limitations of range and duration fields.

The declared types are kept for 4.x (changing one is a wire change), but their
values must serialize: a Decimal range bound is delivered as a float (precision
loss only) and a subscription DurationField is delivered as total seconds.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from graphql import (
    GraphQLField,
    GraphQLFloat,
    GraphQLInt,
    GraphQLObjectType,
    GraphQLSchema,
    get_named_type,
    graphql_sync,
)

from django_graphex.core.output_compiler import (
    _RANGE_INTERNAL_TO_BOUND,
    _compile_range_field,
)
from tests.models import ScalarKindsModel


def _read_range(kind: str, lower: Any, upper: Any) -> Any:
    """Execute a range field of one kind against a populated value.

    Args:
        kind: The Django internal range type name.
        lower: The lower bound handed to the resolver.
        upper: The upper bound handed to the resolver.

    Returns:
        The GraphQL execution result.
    """
    field = SimpleNamespace(name="rng", get_internal_type=lambda: kind)
    compiled = _compile_range_field(field)["rng"]
    query = GraphQLObjectType(
        "Q",
        {
            "rng": GraphQLField(
                compiled.type,
                resolve=lambda *_: SimpleNamespace(lower=lower, upper=upper),
            )
        },
    )
    return graphql_sync(GraphQLSchema(query=query), "{rng{lower upper}}")


def test_documented_limitation_range_bounds_keep_float_and_int_scalars() -> None:
    """Keep DecimalRangeField on Float bounds and BigIntegerRangeField on Int.

    Changing a bound scalar is a wire change and must be deliberate.
    """
    assert _RANGE_INTERNAL_TO_BOUND["DecimalRangeField"] is GraphQLFloat
    assert _RANGE_INTERNAL_TO_BOUND["BigIntegerRangeField"] is GraphQLInt
    assert _RANGE_INTERNAL_TO_BOUND["IntegerRangeField"] is GraphQLInt


def test_decimal_range_bounds_are_delivered_as_floats() -> None:
    """Convert finite Decimal bounds to float so the Float scalar serializes.

    Precision beyond about 15-17 digits is lost; that is the documented limit.
    """
    result = _read_range("DecimalRangeField", Decimal("1.5"), Decimal("2.25"))
    assert result.errors is None
    assert result.data == {"rng": {"lower": 1.5, "upper": 2.25}}
    open_ended = _read_range("DecimalRangeField", None, Decimal("3"))
    assert open_ended.data == {"rng": {"lower": None, "upper": 3.0}}


def test_decimal_range_non_finite_bound_keeps_the_float_error() -> None:
    """Leave a non-finite Decimal bound to the Float scalar, which rejects it.

    NaN and Infinity keep the existing error behavior.
    """
    result = _read_range("DecimalRangeField", Decimal("NaN"), Decimal("1"))
    assert result.errors


def test_bigint_range_bounds_follow_int_scalar_range() -> None:
    """Serialize 32-bit bounds and reject larger ones, as any Int field does.

    This is the documented BigIntegerRangeField limitation.
    """
    assert _read_range("BigIntegerRangeField", 1, 2**31 - 1).errors is None
    assert _read_range("BigIntegerRangeField", 1, 2**40).errors


@pytest.mark.parametrize(
    "value", [timedelta(seconds=5), timedelta(days=-1, microseconds=3), None]
)
def test_subscription_duration_event_field_is_total_seconds(
    value: timedelta | None,
) -> None:
    """Keep the Float event field and deliver the same seconds as query output.

    Args:
        value: The stored duration, or None.
    """
    pytest.importorskip("channels")
    from django_graphex.subscriptions import Subscription
    from django_graphex.subscriptions.mixins import serialize_instance

    class DurationSubscription(Subscription):
        """Expose the model's DurationField on the native event type."""

        class Meta:
            """Select the existing model and an isolated stream."""

            model = ScalarKindsModel
            stream = "documented_limitation_duration"
            only_fields = ("id", "duration")

    event_type: Any = DurationSubscription._build_native_event_type()
    assert get_named_type(event_type.fields["duration"].type) is GraphQLFloat
    payload = serialize_instance(
        DurationSubscription._meta.backend, ScalarKindsModel(id=1, duration=value)
    )
    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "Query", {"ev": GraphQLField(event_type, resolve=lambda *_: payload)}
        )
    )
    result = graphql_sync(schema, "{ev{duration}}")
    assert result.errors is None
    expected = value.total_seconds() if value is not None else None
    assert result.data == {"ev": {"duration": expected}}
