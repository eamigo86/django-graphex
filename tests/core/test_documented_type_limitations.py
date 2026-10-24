"""Pin the documented type-mapping limitations of range and duration fields.

These mappings are known limitations (see the types and subscriptions guides),
kept as they are for 4.x. Changing one is a wire change, so these tests must be
updated deliberately together with the docs and the changelog.
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLFloat, GraphQLInt, get_named_type

from django_graphex.core.output_compiler import _RANGE_INTERNAL_TO_BOUND
from django_graphex.subscriptions import Subscription
from tests.models import ScalarKindsModel


def test_documented_limitation_range_bounds_keep_float_and_int_scalars() -> None:
    """Keep DecimalRangeField on Float bounds and BigIntegerRangeField on Int.

    Changing a bound scalar is a wire change and must be deliberate.
    """
    assert _RANGE_INTERNAL_TO_BOUND["DecimalRangeField"] is GraphQLFloat
    assert _RANGE_INTERNAL_TO_BOUND["BigIntegerRangeField"] is GraphQLInt
    assert _RANGE_INTERNAL_TO_BOUND["IntegerRangeField"] is GraphQLInt


def test_documented_limitation_subscription_duration_event_field_is_float() -> None:
    """Keep DurationField on the Float event-type field in subscriptions.

    Changing it is a wire change and must be deliberate.
    """

    class DurationSubscription(Subscription):
        """Expose the model's DurationField on the native event type."""

        class Meta:
            """Select the existing model and an isolated stream."""

            model = ScalarKindsModel
            stream = "documented_limitation_duration"
            only_fields = ("id", "duration")

    event_type: Any = DurationSubscription._build_native_event_type()
    assert get_named_type(event_type.fields["duration"].type) is GraphQLFloat
