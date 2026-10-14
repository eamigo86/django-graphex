"""GraphQL execution contracts for auto-derived Django DecimalField output."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
django.setup()

from django.db import models  # noqa: E402
from graphql import GraphQLFloat, GraphQLResolveInfo, graphql_sync  # noqa: E402

from django_graphex.core import ObjectType, field  # noqa: E402
from django_graphex.core.input_compiler import _native_scalar_map  # noqa: E402
from django_graphex.core.scalars import GdxDecimal  # noqa: E402
from django_graphex.schema import DjangoGraphQLSchema  # noqa: E402
from django_graphex.types import DjangoObjectType  # noqa: E402


class _DecimalOutputModel(models.Model):
    """Unmigrated model exercising decimal and ordinary float output."""

    amount = models.DecimalField(max_digits=32, decimal_places=2, null=True)
    ratio = models.FloatField(null=True)

    class Meta:
        """Attach the in-memory model to the existing test app."""

        app_label = "tests"


class _DecimalOutputType(DjangoObjectType):
    """Expose automatically compiled model fields without overrides."""

    class Meta:
        """Identify the model for native output compilation."""

        model = _DecimalOutputModel


class _AutoQuery(ObjectType):
    """Expose a model object supplied through the GraphQL request context."""

    item = field(_DecimalOutputType)

    @staticmethod
    def resolve_item(root: Any, info: GraphQLResolveInfo) -> Any:
        """Return the in-memory object without touching a database.

        Args:
            root: Unused root value.
            info: GraphQL execution context containing the object.

        Returns:
            The object supplied by the test request.
        """
        return info.context["item"]


def _explicit_decimal_resolver(root: Any, info: GraphQLResolveInfo) -> Decimal | None:
    """Return a raw Decimal through an explicitly selected Decimal scalar.

    Args:
        root: Model instance or mapping supplied by the query.
        info: Unused GraphQL execution context.

    Returns:
        The original Decimal value, including null.
    """
    return root["amount"] if isinstance(root, dict) else root.amount


class _ExplicitDecimalType(DjangoObjectType):
    """Override the model column with the existing precise Decimal scalar."""

    amount = field(GdxDecimal, resolver=_explicit_decimal_resolver)

    class Meta:
        """Identify the model for the declared output override."""

        model = _DecimalOutputModel


class _ExplicitQuery(ObjectType):
    """Expose the explicit scalar type for a compatibility control."""

    item = field(_ExplicitDecimalType)

    @staticmethod
    def resolve_item(root: Any, info: GraphQLResolveInfo) -> Any:
        """Return the in-memory object for explicit-scalar execution.

        Args:
            root: Unused root value.
            info: GraphQL execution context containing the object.

        Returns:
            The object supplied by the test request.
        """
        return info.context["item"]


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("19.99"), 19.99),
        (Decimal("-0.25"), -0.25),
        (Decimal("9007199254740993.01"), 9007199254740994.0),
        (None, None),
    ],
)
@pytest.mark.parametrize("as_mapping", [False, True])
def test_automatic_decimal_field_executes_as_existing_float(
    amount: Decimal | None, expected: float | None, as_mapping: bool
) -> None:
    """Return populated numeric values without changing the Float SDL.

    Args:
        amount: Decimal column value, or null.
        expected: Existing Float wire value, including precision loss.
        as_mapping: Resolve a mapping rather than a model instance.
    """
    schema = DjangoGraphQLSchema(query=_AutoQuery).graphql_schema
    item_type = schema.query_type.fields["item"].type
    assert item_type.fields["amount"].type is GraphQLFloat
    assert item_type.fields["ratio"].type is GraphQLFloat

    item: Any = (
        {"amount": amount, "ratio": 1.5}
        if as_mapping
        else _DecimalOutputModel(amount=amount, ratio=1.5)
    )
    result = graphql_sync(
        schema, "{ item { amount ratio } }", context_value={"item": item}
    )
    assert result.errors is None
    assert result.data == {"item": {"amount": expected, "ratio": 1.5}}


def test_explicit_decimal_scalar_and_input_mapping_stay_precise() -> None:
    """Preserve the opt-in scalar and exact input mapping.

    This control guards against changing explicit output or input contracts.
    """
    exact = Decimal("9007199254740993.01")
    schema = DjangoGraphQLSchema(query=_ExplicitQuery).graphql_schema
    item_type = schema.query_type.fields["item"].type
    assert item_type.fields["amount"].type is GdxDecimal

    result = graphql_sync(
        schema,
        "{ item { amount } }",
        context_value={"item": _DecimalOutputModel(amount=exact)},
    )
    assert result.errors is None
    assert result.data == {"item": {"amount": "9007199254740993.01"}}

    input_scalar = _native_scalar_map()[Decimal]
    assert input_scalar is GdxDecimal
    assert input_scalar.parse_value("9007199254740993.01") == exact
