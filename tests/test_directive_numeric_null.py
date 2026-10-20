"""Native GraphQL regressions for numeric formatting of null fields."""

from __future__ import annotations

from typing import Any

import pytest
from graphql import (
    GraphQLBoolean,
    GraphQLFloat,
    GraphQLID,
    GraphQLInt,
    GraphQLNonNull,
    GraphQLString,
    graphql_sync,
)

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema


class _Child(ObjectType):
    """Nested output with a required value for bubbling tests."""

    required_value = field(GraphQLNonNull(GraphQLString))

    def resolve_required_value(root: Any, info: Any) -> None:
        """Return null for the required field.

        Args:
            root: The parent value.
            info: GraphQL execution metadata.

        Returns:
            Null, which GraphQL must reject for this field.
        """
        return None


class _Query(ObjectType):
    """Public query root exercising numeric directives through compilation."""

    nullable_value = field(GraphQLString)
    required_value = field(GraphQLNonNull(GraphQLString))
    numeric_int = field(GraphQLInt)
    numeric_float = field(GraphQLFloat)
    boolean_value = field(GraphQLBoolean)
    id_value = field(GraphQLID)
    zero_value = field(GraphQLString)
    zero_text = field(GraphQLString)
    false_value = field(GraphQLString)
    empty_value = field(GraphQLString)
    bad_value = field(GraphQLString)
    child = field(_Child)
    sibling = field(GraphQLString)

    def resolve_nullable_value(root: Any, info: Any) -> None:
        """Return a nullable source value.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            The absent field value.
        """
        return None

    def resolve_child(root: Any, info: Any) -> dict[str, str]:
        """Return a child object for nested bubbling.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            An empty child source object.
        """
        return {}

    resolve_required_value = resolve_nullable_value
    resolve_numeric_int = resolve_nullable_value
    resolve_numeric_float = resolve_nullable_value
    resolve_boolean_value = resolve_nullable_value
    resolve_id_value = resolve_nullable_value

    def resolve_zero_value(root: Any, info: Any) -> int:
        """Return a numeric zero for unchanged falsy formatting.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A numeric zero.
        """
        return 0

    def resolve_zero_text(root: Any, info: Any) -> str:
        """Return text zero for unchanged coercion.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A string containing zero.
        """
        return "0"

    def resolve_false_value(root: Any, info: Any) -> bool:
        """Return False for unchanged falsy formatting.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            False.
        """
        return False

    def resolve_empty_value(root: Any, info: Any) -> str:
        """Return empty text for unchanged falsy formatting.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            An empty string.
        """
        return ""

    def resolve_bad_value(root: Any, info: Any) -> str:
        """Return nonnumeric text for the existing coercion error.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            Text that cannot be parsed as a number.
        """
        return "not-a-number"

    def resolve_sibling(root: Any, info: Any) -> str:
        """Return an unaffected sibling value.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A fixed sibling value.
        """
        return "kept"


_SCHEMA = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))


def _execute(query: str) -> Any:
    """Execute an operation through the public schema and directive middleware.

    Args:
        query: A native GraphQL operation.

    Returns:
        Its execution result.
    """
    return graphql_sync(
        _SCHEMA.graphql_schema,
        query,
        middleware=[GraphQLDirectiveMiddleware()],
    )


@pytest.mark.parametrize("directive", ['@number(as: ".2f")', "@currency"])
def test_nullable_numeric_directive_preserves_graphql_null(directive: str) -> None:
    """Both numeric formatters must preserve a nullable resolver's null.

    Args:
        directive: The formatter invocation to exercise.
    """
    result = _execute(f"{{ nullableValue {directive} sibling }}")
    assert result.errors is None
    assert result.data == {"nullableValue": None, "sibling": "kept"}


@pytest.mark.parametrize("directive", ['@number(as: ".2f")', "@currency"])
def test_required_numeric_directive_bubbles_normally(directive: str) -> None:
    """A required null field must bubble only to its nullable parent.

    Args:
        directive: The formatter invocation to exercise.
    """
    result = _execute(f"{{ child {{ requiredValue {directive} }} sibling }}")
    assert result.data == {"child": None, "sibling": "kept"}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["child", "requiredValue"]
    assert "Cannot return null for non-nullable field" in result.errors[0].message


@pytest.mark.parametrize("directive", ['@number(as: ".2f")', "@currency"])
def test_required_root_numeric_null_bubbles_to_data(directive: str) -> None:
    """A required root field keeps GraphQL's ordinary nullability failure.

    Args:
        directive: The formatter invocation to exercise.
    """
    result = _execute(f"{{ requiredValue {directive} }}")
    assert result.data is None
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["requiredValue"]
    assert "Cannot return null for non-nullable field" in result.errors[0].message


@pytest.mark.parametrize("directive", ['@number(as: ".2f")', "@currency"])
def test_numeric_and_other_nullable_types_keep_null(directive: str) -> None:
    """Null remains null on raw numeric and otherwise formatted types.

    Args:
        directive: The formatter invocation to exercise.
    """
    result = _execute(
        "{ numericInt "
        + directive
        + " numericFloat "
        + directive
        + " booleanValue "
        + directive
        + " idValue "
        + directive
        + " }"
    )
    assert result.errors is None
    assert result.data == {
        "numericInt": None,
        "numericFloat": None,
        "booleanValue": None,
        "idValue": None,
    }


@pytest.mark.parametrize(
    ("directive", "expected"),
    [('@number(as: ".2f")', "0.00"), ("@currency", "$0.00")],
)
def test_existing_falsy_values_still_format(directive: str, expected: str) -> None:
    """Zero, text zero, False, and empty text retain their output.

    Args:
        directive: The formatter invocation to exercise.
        expected: The previously established formatted zero.
    """
    result = _execute(
        "{ zeroValue "
        + directive
        + " zeroText "
        + directive
        + " falseValue "
        + directive
        + " emptyValue "
        + directive
        + " }"
    )
    assert result.errors is None
    assert result.data == dict.fromkeys(
        ("zeroValue", "zeroText", "falseValue", "emptyValue"), expected
    )


@pytest.mark.parametrize("field_name", ["nullableValue", "numericInt", "numericFloat"])
def test_number_cap_still_rejects_null_on_every_field_type(field_name: str) -> None:
    """The width cap precedes the type gate and null handling.

    Args:
        field_name: A nullable String, Int, or Float field.
    """
    result = _execute(f'{{ {field_name} @number(as: "1000000.2f") }}')
    assert result.data == {field_name: None}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == [field_name]
    assert "width/precision" in result.errors[0].message


def test_number_invalid_spec_still_rejected_for_null_formatted_field() -> None:
    """A null value does not bypass applicable format validation."""
    result = _execute('{ nullableValue @number(as: ".2q") }')
    assert result.data == {"nullableValue": None}
    assert result.errors is not None and len(result.errors) == 1
    assert "Invalid @number format spec" in result.errors[0].message


@pytest.mark.parametrize(
    ("spec", "message"),
    [(".2q", "Invalid @number format spec"), ("1000000.2f", "width/precision")],
)
def test_required_null_still_validates_number_spec(spec: str, message: str) -> None:
    """Invalid client arguments error before required-null completion.

    Args:
        spec: An invalid or oversized format spec.
        message: The expected validation failure fragment.
    """
    result = _execute(f'{{ requiredValue @number(as: "{spec}") }}')
    assert result.data is None
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["requiredValue"]
    assert message in result.errors[0].message


def test_currency_custom_symbol_does_not_replace_null() -> None:
    """A valid explicit currency symbol cannot turn null into zero."""
    result = _execute('{ nullableValue @currency(symbol: "€") }')
    assert result.errors is None
    assert result.data == {"nullableValue": None}


@pytest.mark.parametrize("field_name", ["numericInt", "numericFloat"])
def test_number_invalid_spec_still_skipped_for_raw_numeric_type(
    field_name: str,
) -> None:
    """The existing Int/Float type gate still skips actual formatting.

    Args:
        field_name: A raw numeric GraphQL field.
    """
    result = _execute(f'{{ {field_name} @number(as: ".2q") }}')
    assert result.errors is None
    assert result.data == {field_name: None}


@pytest.mark.parametrize("directive", ['@number(as: ".2f")', "@currency"])
def test_non_null_bad_value_still_reports_coercion_error(directive: str) -> None:
    """Nonnumeric text must keep the formatter's existing value error.

    Args:
        directive: The formatter invocation to exercise.
    """
    result = _execute(f"{{ badValue {directive} }}")
    assert result.data == {"badValue": None}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["badValue"]
    assert "could not" in result.errors[0].message


def test_other_directive_and_default_chain_keep_their_contract() -> None:
    """Numeric null does not change unrelated or explicit default behavior."""
    result = _execute(
        "{ plain: nullableValue @uppercase "
        'defaulted: nullableValue @default(to: "7") @number(as: ".2f") '
        'lateDefault: nullableValue @number(as: ".2f") @default(to: "fallback") }'
    )
    assert result.errors is None
    assert result.data == {
        "plain": None,
        "defaulted": "7.00",
        "lateDefault": "fallback",
    }
