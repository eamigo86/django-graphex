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


@pytest.mark.parametrize(
    "value",
    [
        Decimal("1E+999999999"),
        Decimal("-1E+100000"),
        Decimal("1E-999999999"),
        Decimal("123.45E+5000"),
    ],
)
def test_huge_exponent_keeps_scientific_notation(value: Decimal) -> None:
    """A tiny literal with a huge exponent must not expand into a huge string.

    Plain notation pads one zero per unit of exponent, so a 14-byte literal
    such as "1E+999999999" echoed by a resolver would allocate a gigabyte.
    Past the padding bound the exact scientific form is kept instead.

    Args:
        value: A Decimal whose plain form would need far too many zeros.
    """
    wire = GdxDecimal.serialize(value)
    assert len(wire) < 64
    assert Decimal(wire) == value


def test_padding_at_the_bound_still_uses_plain_notation() -> None:
    """Values within the zero-padding bound keep positional notation.

    A thousand padded zeros is far beyond any database column precision.
    """
    assert GdxDecimal.serialize(Decimal("1E+1000")) == "1" + "0" * 1000
    assert GdxDecimal.serialize(Decimal("1E-1000")) == "0." + "0" * 999 + "1"
