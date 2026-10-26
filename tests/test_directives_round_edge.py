"""Edge cases of the numeric directives on Decimal values.

Covers tiny magnitudes, precisions at and past the value's own scale, and
values with huge exponents (which must stay O(1)).
"""

from __future__ import annotations

import decimal
import random
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest
from graphql import GraphQLFloat, GraphQLString

from django_graphex.directives.numbers import (
    CeilGraphQLDirective,
    FloorGraphQLDirective,
    RoundGraphQLDirective,
    _round,
)

_REFERENCE = decimal.Context(
    prec=500,
    rounding=decimal.ROUND_HALF_EVEN,
    Emax=decimal.MAX_EMAX,
    Emin=decimal.MIN_EMIN,
)


def _reference(number: Decimal, precision: int) -> int | Decimal:
    """Round half to even with Decimal.quantize in an adequately sized context.

    Args:
        number: The value to round.
        precision: Decimal places; zero or below yields an integer.

    Returns:
        An int for precision zero or below, else the quantized Decimal.
    """
    target = -precision
    if number.as_tuple().exponent >= target:
        rounded = number
    else:
        rounded = number.quantize(Decimal((0, (1,), target)), context=_REFERENCE)
    return int(rounded) if precision <= 0 else rounded


@pytest.mark.parametrize(
    ("value", "precision", "expected"),
    [
        ("0.0004", 0, 0),
        ("-0.0004", 0, 0),
        ("0.0004", 2, "0.00"),
        ("-0.0004", 2, "-0.00"),
        ("0.0049", 1, "0.0"),
        ("0.0049", 0, 0),
        ("0.5", 0, 0),
        ("1.5", 0, 2),
        ("2.5", 0, 2),
        ("1E-30", 5, "0.00000"),
        ("1E-30", 0, 0),
        ("1.5E+30", -29, 15 * 10**29),
        ("0.6", 0, 1),
        ("99.95", 1, "100.0"),
    ],
)
def test_round_quantizes_to_the_requested_precision(
    value: str, precision: int, expected: object
) -> None:
    """Quantize to exactly the requested precision.

    The old clamp turned a zero or negative precision into a positive one.

    Args:
        value: Decimal text to round.
        precision: Requested decimal places.
        expected: Expected int, or the expected Decimal text.
    """
    result = _round(Decimal(value), precision)
    if isinstance(expected, str):
        assert isinstance(result, Decimal)
        assert str(result) == expected
    else:
        assert result == expected
        assert isinstance(result, int)


def test_round_matches_a_quantize_reference_on_random_values() -> None:
    """Compare against a Decimal.quantize reference on seeded random values.

    The comparison covers tiny, huge and negative values with precisions from
    -10 to 30, and the rounding never raises.
    """
    rng = random.Random(4001)
    for _ in range(4000):
        digits = rng.randint(1, 40)
        coefficient = rng.randint(0, 10**digits - 1)
        exponent = rng.randint(-45, 20)
        sign = rng.choice((0, 1))
        number = Decimal(
            (sign, tuple(int(c) for c in str(coefficient)), exponent),
        )
        precision = rng.randint(-10, 30)
        got = _round(number, precision)
        want = _reference(number, precision)
        assert got == want, (number, precision, got, want)
        assert type(got) is type(want), (number, precision)
        if isinstance(want, Decimal):
            assert got.as_tuple() == want.as_tuple(), (number, precision)


def _info(return_type: object = GraphQLFloat) -> SimpleNamespace:
    """Build the minimal resolve info the directives read.

    Args:
        return_type: The field's return type.

    Returns:
        An object exposing return_type.
    """
    return SimpleNamespace(return_type=return_type)


def _run(directive: type, value: Decimal, info: object, **args: int) -> object:
    """Run a directive's resolve with no root.

    Args:
        directive: The directive class.
        value: The field value.
        info: Resolve info stand-in.
        **args: Directive arguments.

    Returns:
        The directive result.
    """
    return directive.resolve(value, args, None, None, info)  # type: ignore[attr-defined]


@pytest.mark.parametrize("exponent", [1000, 9999, 100_000, 999_999_999])
def test_huge_exponents_are_returned_unchanged_in_constant_time(exponent: int) -> None:
    """Floor, ceil and round of an integral huge value skip the int expansion.

    Args:
        exponent: The power of ten of the tested value.
    """
    value = Decimal(f"1E+{exponent}")
    start = time.perf_counter()
    for directive, args in (
        (FloorGraphQLDirective, {}),
        (CeilGraphQLDirective, {}),
        (RoundGraphQLDirective, {}),
        (RoundGraphQLDirective, {"precision": 3}),
    ):
        result = _run(directive, value, _info(), **args)
        assert isinstance(result, Decimal)
        assert result == value
    assert time.perf_counter() - start < 0.5


def test_huge_exponent_string_field_keeps_scientific_form() -> None:
    """Keep the scientific form instead of a 100,000 digit string.

    A String field must not expand 1E+100000.
    """
    result = _run(FloorGraphQLDirective, Decimal("1E+100000"), _info(GraphQLString))
    assert result == "1E+100000"


def test_round_to_a_huge_negative_precision_is_zero() -> None:
    """Yield a plain zero when rounding far past the value's magnitude.

    A tiny value rounded to a few places keeps exactly that many places.
    """
    assert _round(Decimal("12345678901234567890.123456789"), -999_999) == 0
    assert _round(Decimal("1E-999999999"), 5) == Decimal("0.00000")


def test_floor_and_ceil_of_fractions_stay_exact() -> None:
    """Floor and ceil ordinary fractional values to exact integers.

    Negative inputs round toward the right side of zero.
    """
    assert _run(FloorGraphQLDirective, Decimal("-12.3456"), _info()) == -13
    assert _run(CeilGraphQLDirective, Decimal("12.3456"), _info()) == 13
    assert _run(CeilGraphQLDirective, Decimal("-0.5"), _info()) == 0
