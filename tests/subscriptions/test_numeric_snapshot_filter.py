"""Numeric-aware in-memory equality between snapshots and typed filters."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from django_graphex.subscriptions.mixins import split_filters

_NAN = float("nan")
_INF = float("inf")


@pytest.mark.parametrize(
    ("snapshot", "expected", "matches"),
    [
        # int, float and Decimal compare by value, whichever type each side is.
        (1.5, Decimal("1.50"), True),
        (2.0, Decimal("2"), True),
        (2, 2.0, True),
        (2, Decimal("2.00"), True),
        (2.0, 2, True),
        (0, -0.0, True),
        (0, Decimal("-0"), True),
        (-0.0, Decimal("0"), True),
        (1.5, Decimal("1.51"), False),
        (1, 1.5, False),
        (1, Decimal("1.0000000000000000000000000001"), False),
        # Float rounding rule: an int or Decimal compared with a float is first
        # rounded to the nearest float, as a float column stores it.
        (2**53 + 1, float(2**53), True),
        (float(2**53), 2**53 + 1, True),
        (0.1, Decimal("0.1"), True),
        (10**400, Decimal(10**400), True),
        # Never numeric: bool, non-finite values and out-of-range integers.
        (True, 1.0, False),
        (True, Decimal(1), False),
        (1, True, False),
        (1, _NAN, False),
        (1, _INF, False),
        (1, Decimal("NaN"), False),
        (1, Decimal("sNaN"), False),
        (1, Decimal("Infinity"), False),
        (1.5, Decimal("NaN"), False),
        (_INF, Decimal("Infinity"), False),
        (10**400, _INF, False),
        (10**400, 1.5, False),
        (1.5, 10**400, False),
        (1.5, Decimal("1e400"), False),
    ],
)
def test_numeric_equality_matrix(snapshot: Any, expected: Any, matches: bool) -> None:
    """Exact filters compare numbers by value and drop everything else.

    Args:
        snapshot: The serialized value carried by the notification.
        expected: The typed filter value.
        matches: Whether the notification is kept without a database check.
    """
    result = split_filters({"x": snapshot}, {"x": expected})
    assert (result == {}) is matches
    assert result in ({}, None)
