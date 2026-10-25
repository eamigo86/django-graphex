"""A huge negative @round precision answers in constant time and stays exact."""

from __future__ import annotations

import decimal
import time
from decimal import Decimal

import pytest

from django_graphex.directives.numbers import _round
from tests.test_directives_exact_numbers import _run

_CTX = decimal.Context(prec=2000, rounding=decimal.ROUND_HALF_EVEN)


@pytest.mark.parametrize("precision", [-(2**31), -10_000_000])
@pytest.mark.parametrize("value", [0, 1, -1, 10**3000 + 5])
def test_huge_negative_precision_on_an_int_is_fast(value: int, precision: int) -> None:
    """The query returns 0 quickly instead of building 10 ** -precision.

    Args:
        value: The BigInt column value.
        precision: The extreme negative precision.
    """
    start = time.perf_counter()
    result = _run(f"big @round(precision: {precision})", big=value)
    elapsed = time.perf_counter() - start
    assert result.errors is None
    assert result.data == {"item": {"big": "0"}}
    assert elapsed < 1.0


@pytest.mark.parametrize("k", range(1, 40))
def test_the_shortcut_never_changes_a_nonzero_result(k: int) -> None:
    """Around the cutoff, _round equals an exact half-even Decimal reference.

    Args:
        k: Power of ten used to build the probe values.
    """
    values = {5 * 10**k, 15 * 10**k, 25 * 10**k, 10**k - 1, 10**k, 10 ** (k + 1) // 2}
    for n in values | {-v for v in values}:
        for precision in (-k, -k - 1, -k - 2, -k - 3, -3 * k, -3 * k - 2):
            exact = int(
                Decimal(n).quantize(Decimal((0, (1,), -precision)), context=_CTX)
            )
            assert _round(n, precision) == exact, (n, precision)
