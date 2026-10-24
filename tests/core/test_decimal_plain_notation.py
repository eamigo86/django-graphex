"""Decimal output uses plain positional notation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from django_graphex.core.scalars import GdxDecimal


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0E-8"), "0.00000000"),
        (Decimal("5.0E-7"), "0.00000050"),
        (Decimal("1E-8"), "0.00000001"),
        (Decimal("1E+3"), "1000"),
        (Decimal("-0"), "-0"),
        (Decimal("19.99"), "19.99"),
        (Decimal("100.00"), "100.00"),
        (Decimal("NaN"), "NaN"),
        (Decimal("-Infinity"), "-Infinity"),
        (7, "7"),
    ],
)
def test_decimal_serializes_without_exponent(value: Any, expected: str) -> None:
    """Scale and sign are preserved while exponents are expanded.

    Args:
        value: The Python value handed to the scalar.
        expected: The expected wire string.
    """
    assert GdxDecimal.serialize(value) == expected
