"""Numeric directives keep Decimal exact and BigInt integral."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.db import models
from graphql import graphql_sync
from graphql.execution import MiddlewareManager

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from tests._schema_isolation import isolated_pair


class ExactNum(models.Model):
    """Model with one nullable Decimal, BigInteger and Float column.

    Attributes:
        amt: Decimal column.
        big: BigInteger column.
        flt: Float column.
    """

    amt = models.DecimalField(max_digits=40, decimal_places=10, null=True)
    big = models.BigIntegerField(null=True)
    flt = models.FloatField(null=True)

    class Meta:
        """Test-only model options.

        Attributes:
            app_label: The label of the test app.
        """

        app_label = "tests"


_REGISTRY = Registry()


class ExactNumType(DjangoObjectType):
    """Output type exposing every ExactNum column.

    Attributes:
        Meta: Type options.
    """

    class Meta:
        """Type options.

        Attributes:
            model: The backing model.
            registry: The isolated registry.
        """

        model = ExactNum
        registry = _REGISTRY


class Query(ObjectType):
    """Query returning the context item.

    Attributes:
        item: The context item.
    """

    item = field(ExactNumType)

    @staticmethod
    def resolve_item(root: Any, info: Any) -> Any:
        """Return the instance handed in through the context.

        Args:
            root: Unused root value.
            info: Resolve info carrying the context.

        Returns:
            The context item.
        """
        return info.context["item"]


def _run(selection: str, **values: Any) -> Any:
    schema = DjangoGraphQLSchema(
        query=Query, directives=all_directives, registries=isolated_pair(_REGISTRY)
    ).graphql_schema
    return graphql_sync(
        schema,
        f"{{ item {{ {selection} }} }}",
        context_value={"item": ExactNum(**values)},
        middleware=MiddlewareManager(GraphQLDirectiveMiddleware()),
    )


_BIG = 2**40 + 7
_EDGE = 2**63 - 1
_HUGE = Decimal("12345678901234567890.123456789")

# (directive, input, expected amt, expected big, expected flt)
_CASES = [
    (
        "@round(precision: 2)",
        (Decimal("12.3456"), _BIG, 12.3456),
        "12.35",
        str(_BIG),
        12.35,
    ),
    ("@round", (Decimal("12.3456"), _BIG, 12.3456), "12", str(_BIG), 12),
    ("@round(precision: -1)", (Decimal("15"), _BIG, 15.0), "20", "1099511627780", 20),
    ("@round(precision: 2)", (Decimal("2.665"), _EDGE, 2.5), "2.66", str(_EDGE), 2.5),
    (
        "@round(precision: 4)",
        (_HUGE, _EDGE, 1.0),
        "12345678901234567890.1235",
        str(_EDGE),
        1.0,
    ),
    (
        "@round(precision: 999999)",
        (_HUGE, _EDGE, 1.0),
        "12345678901234567890.123456789",
        str(_EDGE),
        1.0,
    ),
    ("@round(precision: -999999)", (_HUGE, _EDGE, 1.0), "0", "0", 0),
    ("@floor", (Decimal("-12.3456"), -_BIG, -12.3456), "-13", str(-_BIG), -13),
    ("@floor", (_HUGE, _EDGE, 1.5), "12345678901234567890", str(_EDGE), 1),
    ("@ceil", (Decimal("12.3456"), _BIG, 12.3456), "13", str(_BIG), 13),
    ("@ceil", (_HUGE, _EDGE, 1.5), "12345678901234567891", str(_EDGE), 2),
    ("@abs", (Decimal("-12.3456"), -_BIG, -12.3456), "12.3456", str(_BIG), 12.3456),
    ("@abs", (_HUGE.copy_negate(), -_EDGE, -1.0), str(_HUGE), str(_EDGE), 1.0),
    ("@currency", (Decimal("12.3456"), _BIG, 12.3456), "12.3456", str(_BIG), 12.3456),
    (
        '@number(as: ".2f")',
        (Decimal("12.3456"), _BIG, 12.3456),
        "12.3456",
        str(_BIG),
        12.3456,
    ),
    ("@abs", (None, None, None), None, None, None),
    ("@round(precision: 2)", (None, None, None), None, None, None),
    ("@currency", (None, None, None), None, None, None),
]


@pytest.mark.parametrize(("directive", "given", "amt", "big", "flt"), _CASES)
def test_numeric_directives_across_decimal_bigint_float(
    directive: str,
    given: tuple[Any, Any, Any],
    amt: Any,
    big: Any,
    flt: Any,
) -> None:
    """Each numeric directive keeps Decimal exact and BigInt integral.

    Args:
        directive: The directive text applied to all three columns.
        given: The Decimal, BigInt and Float inputs.
        amt: Expected Decimal output.
        big: Expected BigInt output.
        flt: Expected Float output.
    """
    selection = f"amt {directive} big {directive} flt {directive}"
    if directive in ("@currency", '@number(as: ".2f")'):
        selection = f"amt {directive} big {directive}"
        flt = None
    result = _run(selection, amt=given[0], big=given[1], flt=given[2])
    assert result.errors is None, result.errors
    expected = {"amt": amt, "big": big}
    if "flt" in selection:
        expected["flt"] = flt
    assert result.data == {"item": expected}
