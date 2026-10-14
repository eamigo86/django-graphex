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
from django.test import RequestFactory  # noqa: E402
from graphql import (  # noqa: E402
    GraphQLArgument,
    GraphQLField,
    GraphQLFloat,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLResolveInfo,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
)

from django_graphex._strconv import to_camel_case  # noqa: E402
from django_graphex.core import ObjectType, field  # noqa: E402
from django_graphex.core.input_compiler import _native_scalar_map  # noqa: E402
from django_graphex.core.scalars import GdxDecimal  # noqa: E402
from django_graphex.filtering.native_schema import build_filter_input_type  # noqa: E402
from django_graphex.mutation import DjangoModelMutation  # noqa: E402
from django_graphex.registry import Registry  # noqa: E402
from django_graphex.schema import DjangoGraphQLSchema  # noqa: E402
from django_graphex.types import DjangoObjectType  # noqa: E402
from tests._schema_isolation import isolated_pair  # noqa: E402


class _DecimalOutputModel(models.Model):
    """Unmigrated model exercising decimal and ordinary float output."""

    amount = models.DecimalField(max_digits=32, decimal_places=2, null=True)
    ratio = models.FloatField(null=True)

    class Meta:
        """Attach the in-memory model to the existing test app."""

        app_label = "tests"


class DecimalMutationRecord(models.Model):
    """Provide an unmigrated model for generated mutation responses.

    The model also verifies the production persistence boundary.
    """

    amount = models.DecimalField(max_digits=32, decimal_places=2, null=True)
    ratio = models.FloatField(null=True)

    class Meta:
        """Attach the decimal mutation record to the existing test app.

        This lets pytest-django create its disposable table.
        """

        app_label = "tests"


_AUTO_REGISTRY = Registry()
_EXPLICIT_DECIMAL_REGISTRY = Registry()
_EXPLICIT_FLOAT_REGISTRY = Registry()
_PRIMARY_REGISTRY = Registry()


class _DecimalOutputType(DjangoObjectType):
    """Expose automatically compiled model fields without overrides."""

    class Meta:
        """Identify the model for native output compilation."""

        model = _DecimalOutputModel
        registry = _AUTO_REGISTRY


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
        registry = _EXPLICIT_DECIMAL_REGISTRY


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


def _numeric_decimal_resolver(root: Any, info: GraphQLResolveInfo) -> float | None:
    """Convert an explicitly declared Float output with known precision loss.

    Args:
        root: Model instance or mapping supplied by the query.
        info: Unused GraphQL execution context.

    Returns:
        The rounded Float value, or null.
    """
    value = root["amount"] if isinstance(root, dict) else root.amount
    return float(value) if value is not None else None


class _ExplicitFloatType(DjangoObjectType):
    """Preserve an explicitly declared legacy numeric output field."""

    amount = field(GraphQLFloat, resolver=_numeric_decimal_resolver)

    class Meta:
        """Bind the legacy output override to the test model."""

        model = _DecimalOutputModel
        registry = _EXPLICIT_FLOAT_REGISTRY


class _ExplicitFloatQuery(ObjectType):
    """Expose the explicitly declared Float output for comparison."""

    item = field(_ExplicitFloatType)

    @staticmethod
    def resolve_item(root: Any, info: GraphQLResolveInfo) -> Any:
        """Return the model supplied in the GraphQL request context.

        Args:
            root: Unused root value.
            info: GraphQL context containing the model.

        Returns:
            The model supplied by the test request.
        """
        return info.context["item"]


class _PrimaryDecimalModel(models.Model):
    """Unmigrated model with a Decimal primary key."""

    amount = models.DecimalField(max_digits=32, decimal_places=2, primary_key=True)

    class Meta:
        """Attach the primary-key model to the existing test app."""

        app_label = "tests"


class _PrimaryDecimalType(DjangoObjectType):
    """Expose an automatically compiled Decimal primary key."""

    class Meta:
        """Identify the model for native primary-key output compilation."""

        model = _PrimaryDecimalModel
        registry = _PRIMARY_REGISTRY


class _PrimaryQuery(ObjectType):
    """Expose a primary-key model supplied by the request context."""

    item = field(_PrimaryDecimalType)

    @staticmethod
    def resolve_item(root: Any, info: GraphQLResolveInfo) -> _PrimaryDecimalModel:
        """Return the in-memory primary-key model without querying a database.

        Args:
            root: Unused root value.
            info: GraphQL execution context containing the model.

        Returns:
            The primary-key model supplied by the test request.
        """
        return info.context["item"]


@pytest.mark.parametrize("as_mapping", [False, True])
@pytest.mark.parametrize("amount", [Decimal("19.99"), Decimal("9007199254740993.01")])
def test_automatic_decimal_output_preserves_exact_text(
    amount: Decimal, as_mapping: bool
) -> None:
    """Expose the existing Decimal scalar by default without float rounding.

    Args:
        amount: The finite decimal value to serialize.
        as_mapping: Whether to resolve from a mapping rather than a model.
    """
    schema = DjangoGraphQLSchema(query=_AutoQuery).graphql_schema
    item_type = schema.query_type.fields["item"].type
    assert item_type.fields["amount"].type is GdxDecimal
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
    assert result.data == {"item": {"amount": str(amount), "ratio": 1.5}}


def test_automatic_decimal_primary_key_uses_decimal_nonnull() -> None:
    """Retain primary-key nullability while selecting exact Decimal output.

    The approved scalar change must not weaken the inherited wrapper.
    """
    schema = DjangoGraphQLSchema(query=_PrimaryQuery).graphql_schema
    item_type = schema.query_type.fields["item"].type
    amount_type = item_type.fields["amount"].type
    assert isinstance(amount_type, GraphQLNonNull)
    assert amount_type.of_type is GdxDecimal

    result = graphql_sync(
        schema,
        "{ item { amount } }",
        context_value={"item": _PrimaryDecimalModel(amount=Decimal("19.99"))},
    )
    assert result.errors is None
    assert result.data == {"item": {"amount": "19.99"}}


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("19.99"), "19.99"),
        (Decimal("-0.25"), "-0.25"),
        (Decimal("9007199254740993.01"), "9007199254740993.01"),
        (None, None),
    ],
)
@pytest.mark.parametrize("as_mapping", [False, True])
def test_automatic_decimal_field_executes_as_exact_decimal(
    amount: Decimal | None, expected: str | None, as_mapping: bool
) -> None:
    """Return exact decimal strings from model and mapping roots.

    Args:
        amount: Decimal column value, or null.
        expected: Exact Decimal wire value or null.
        as_mapping: Resolve a mapping rather than a model instance.
    """
    schema = DjangoGraphQLSchema(query=_AutoQuery).graphql_schema
    item_type = schema.query_type.fields["item"].type
    assert item_type.fields["amount"].type is GdxDecimal
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


def test_explicit_float_resolver_retains_legacy_numeric_contract() -> None:
    """Permit intentional precision loss through a declared Float resolver.

    This is the documented migration escape hatch for numeric clients.
    """
    schema = DjangoGraphQLSchema(query=_ExplicitFloatQuery).graphql_schema
    item_type = schema.query_type.fields["item"].type
    assert item_type.fields["amount"].type is GraphQLFloat
    result = graphql_sync(
        schema,
        "{ item { amount } }",
        context_value={
            "item": _DecimalOutputModel(amount=Decimal("9007199254740993.01"))
        },
    )
    assert result.errors is None
    assert result.data == {"item": {"amount": 9007199254740994.0}}


def test_decimal_filter_literals_and_variables_remain_precise() -> None:
    """Keep automatic exact-filter values as Python Decimal objects.

    Both GraphQL literals and variables preserve the original decimal text.
    """
    local_registry = Registry()

    class _FilterOutputType(DjangoObjectType):
        """Register the model used by the automatic filter."""

        class Meta:
            """Bind the test model to the filter's private registry."""

            model = _DecimalOutputModel
            registry = local_registry

    gql_filter = build_filter_input_type(
        _DecimalOutputModel, {"amount": ("exact",)}, local_registry
    )
    assert gql_filter is not None
    assert gql_filter.fields["amount"].type.fields["exact"].type is GdxDecimal
    received: list[Decimal] = []

    def resolve_filter(root: Any, info: Any, filter: Any) -> str:
        """Capture the parsed exact-filter value without running the ORM.

        Args:
            root: Unused query root.
            info: Unused GraphQL execution context.
            filter: Parsed automatic filter input.

        Returns:
            The decimal value rendered as text.
        """
        value = filter["amount"]["exact"]
        received.append(value)
        return str(value)

    schema = GraphQLSchema(
        query=GraphQLObjectType(
            "DecimalFilterQuery",
            {
                "echo": GraphQLField(
                    GraphQLString,
                    args={"filter": GraphQLArgument(gql_filter)},
                    resolve=resolve_filter,
                )
            },
        )
    )
    exact = "9007199254740993.01"
    literal = graphql_sync(
        schema, f'{{ echo(filter: {{ amount: {{ exact: "{exact}" }} }}) }}'
    )
    variable = graphql_sync(
        schema,
        f"query($filter: {gql_filter.name}) {{ echo(filter: $filter) }}",
        variable_values={"filter": {"amount": {"exact": exact}}},
    )
    assert literal.errors is None
    assert variable.errors is None
    assert literal.data == variable.data == {"echo": exact}
    assert received == [Decimal(exact), Decimal(exact)]


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["19.99", "9007199254740993.01"])
def test_generated_create_mutation_returns_exact_decimal_output(value: str) -> None:
    """Keep generated Decimal input and immediate model output precise.

    Args:
        value: Exact decimal text supplied to the generated input.
    """
    local_registry = Registry()

    class _MutationOutputType(DjangoObjectType):
        """Register the automatic model output in a private registry."""

        class Meta:
            """Bind the output type to the test model and private registry."""

            model = DecimalMutationRecord
            registry = local_registry

    class _CreateAmount(DjangoModelMutation):
        """Create a row with the production model-mutation field."""

        class Meta:
            """Bind the generated mutation to the decimal model."""

            model = DecimalMutationRecord
            registry = local_registry

    class _RootMutation(ObjectType):
        """Mount the generated create and update mutations."""

        create_amount = _CreateAmount.CreateField()
        update_amount = _CreateAmount.UpdateField()

    schema = DjangoGraphQLSchema(
        query=_AutoQuery,
        mutation=_RootMutation,
        registries=isolated_pair(local_registry),
    ).graphql_schema
    mutation_field = schema.mutation_type.fields["createAmount"]
    argument_name, argument = next(iter(mutation_field.args.items()))
    assert argument.type.of_type.fields["amount"].type is GdxDecimal
    output_name = to_camel_case(_CreateAmount._meta.output_field_name)
    assert (
        mutation_field.type.fields[output_name].type.fields["amount"].type is GdxDecimal
    )

    result = graphql_sync(
        schema,
        f"mutation($input: {argument.type}) {{ createAmount({argument_name}: $input) {{ ok {output_name} {{ amount ratio }} errors {{ field messages }} }} }}",
        variable_values={"input": {"amount": value, "ratio": 1.5}},
        context_value=RequestFactory().post(
            "/graphql/", content_type="application/json"
        ),
    )
    assert result.errors is None
    assert result.data["createAmount"]["ok"] is True, result.formatted
    assert result.data["createAmount"][output_name] == {
        "amount": value,
        "ratio": 1.5,
    }, result.formatted
    assert DecimalMutationRecord.objects.count() == 1
    if value == "19.99":
        assert DecimalMutationRecord.objects.get().amount == Decimal(value)

    update_field = schema.mutation_type.fields["updateAmount"]
    update_argument_name, update_argument = next(iter(update_field.args.items()))
    assert update_argument.type.of_type.fields["amount"].type is GdxDecimal
    updated_value = "20.01" if value == "19.99" else "9007199254740993.02"
    updated = graphql_sync(
        schema,
        f"mutation($input: {update_argument.type}) {{ updateAmount({update_argument_name}: $input) {{ ok {output_name} {{ amount ratio }} errors {{ field messages }} }} }}",
        variable_values={
            "input": {
                "id": str(DecimalMutationRecord.objects.get().pk),
                "amount": updated_value,
            }
        },
        context_value=RequestFactory().post(
            "/graphql/", content_type="application/json"
        ),
    )
    assert updated.errors is None
    assert updated.data["updateAmount"]["ok"] is True, updated.formatted
    assert updated.data["updateAmount"][output_name] == {
        "amount": updated_value,
        "ratio": 1.5,
    }, updated.formatted


def test_decimal_primary_key_keeps_nonnull_and_exact_output() -> None:
    """Preserve the inherited primary-key wrapper and exact Decimal value.

    The auto-derived field must use Decimal! and render strings.
    """
    schema = DjangoGraphQLSchema(query=_PrimaryQuery).graphql_schema
    item_type = schema.query_type.fields["item"].type
    amount_type = item_type.fields["amount"].type
    assert isinstance(amount_type, GraphQLNonNull)
    assert amount_type.of_type is GdxDecimal

    result = graphql_sync(
        schema,
        "{ item { amount } }",
        context_value={"item": _PrimaryDecimalModel(amount=Decimal("19.99"))},
    )
    assert result.errors is None
    assert result.data == {"item": {"amount": "19.99"}}


def test_null_decimal_primary_key_propagates_nonnull_error() -> None:
    """Retain the pre-C1 GraphQL error envelope for a null primary key.

    A null value must null the parent object rather than its field alone.
    """
    schema = DjangoGraphQLSchema(query=_PrimaryQuery).graphql_schema
    result = graphql_sync(
        schema,
        "{ item { amount } }",
        context_value={"item": _PrimaryDecimalModel(amount=None)},
    )
    assert result.data == {"item": None}
    assert result.errors is not None
    assert len(result.errors) == 1
    assert result.errors[0].path == ["item", "amount"]
    assert "Cannot return null for non-nullable field" in result.errors[0].message
