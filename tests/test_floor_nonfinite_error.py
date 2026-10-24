"""Public and direct regression tests for non-finite floor values."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from graphql import (
    DirectiveLocation,
    GraphQLError,
    GraphQLNonNull,
    GraphQLResolveInfo,
    GraphQLString,
    graphql_sync,
)

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.directives.numbers import (
    CeilGraphQLDirective,
    FloorGraphQLDirective,
)
from django_graphex.directives.string import (
    TitleCaseGraphQLDirective,
    TruncateGraphQLDirective,
)
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema

_MESSAGE = "@floor cannot operate on a non-finite value."
_value: object = None


class Query(ObjectType):
    """Expose a resolver value through the public schema compiler.

    The value and required fields resolve through methods that return the value selected by the test.
    """

    value = field(GraphQLString)
    required = field(GraphQLNonNull(GraphQLString))

    def resolve_value(root: object, info: GraphQLResolveInfo) -> object:
        """Return the value selected by the test.

        Args:
            root: Root value supplied by GraphQL execution.
            info: Information about the selected field.

        Returns:
            The current test value.
        """
        return _value

    def resolve_required(root: object, info: GraphQLResolveInfo) -> object:
        """Return the current value for non-null bubbling checks.

        Args:
            root: Root value supplied by GraphQL execution.
            info: Information about the selected field.

        Returns:
            The current test value.
        """
        return _value


_schema = DjangoGraphQLSchema(query=Query, directives=list(all_directives))
_middleware = [GraphQLDirectiveMiddleware()]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_floor_directly_rejects_nonfinite_values(value: float) -> None:
    """Raise the approved GraphQL error before Python's integer conversion.

    Args:
        value: A non-finite numeric value.
    """
    info = SimpleNamespace(return_type=GraphQLString)
    with pytest.raises(
        GraphQLError, match=r"^@floor cannot operate on a non-finite value\.$"
    ):
        FloorGraphQLDirective.resolve(value, {}, None, None, info)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_floor_public_execution_returns_nullable_error(value: float) -> None:
    """Expose only the approved message and a null field to GraphQL clients.

    Args:
        value: A non-finite resolver value.
    """
    global _value
    _value = value
    result = graphql_sync(
        _schema.graphql_schema, "{ value @floor }", middleware=_middleware
    )
    assert result.data == {"value": None}
    assert result.errors is not None
    assert len(result.errors) == 1
    assert result.errors[0].message == _MESSAGE
    assert result.errors[0].path == ["value"]


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "Infinity"])
def test_floor_rejects_numeric_strings_that_coerce_to_nonfinite(value: str) -> None:
    """Apply the same finite rule after the existing numeric coercion.

    Args:
        value: A numeric string representing a non-finite value.
    """
    info = SimpleNamespace(return_type=GraphQLString)
    with pytest.raises(GraphQLError) as error:
        FloorGraphQLDirective.resolve(value, {}, None, None, info)
    assert error.value.message == _MESSAGE


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4.7, "4"), (-1.2, "-2"), (-0.0, "0"), (False, "0"), (True, "1")],
)
def test_floor_keeps_finite_and_boolean_values(value: object, expected: str) -> None:
    """Preserve finite flooring, including signed zero and booleans.

    Args:
        value: A finite or boolean resolver value.
        expected: Its original floored String-field result.
    """
    global _value
    _value = value
    result = graphql_sync(
        _schema.graphql_schema, "{ value @floor }", middleware=_middleware
    )
    assert result.errors is None
    assert result.data == {"value": expected}


def test_floor_preserves_none_and_malformed_value_policy() -> None:
    """Keep null passthrough and the existing malformed-number error.

    Scenario: floor preserves none and malformed value policy.
    """
    info = SimpleNamespace(return_type=GraphQLString)
    assert FloorGraphQLDirective.resolve(None, {}, None, None, info) is None
    with pytest.raises(GraphQLError) as error:
        FloorGraphQLDirective.resolve("not-a-number", {}, None, None, info)
    assert error.value.message == (
        "@floor could not convert value 'not-a-number' to a number."
    )


def test_floor_nonnull_error_uses_standard_bubbling() -> None:
    """Let GraphQL bubble the directive error from a non-null field.

    Scenario: floor nonnull error uses standard bubbling.
    """
    global _value
    _value = math.inf
    result = graphql_sync(
        _schema.graphql_schema, "{ required @floor }", middleware=_middleware
    )
    assert result.data is None
    assert result.errors is not None
    assert len(result.errors) == 1
    assert result.errors[0].message == _MESSAGE
    assert result.errors[0].path == ["required"]


def test_other_directives_and_floor_schema_metadata_remain_unchanged() -> None:
    """Leave neighboring directive behavior and SDL-facing metadata alone.

    Scenario: other directives and floor schema metadata remain unchanged.
    """
    info = SimpleNamespace(return_type=GraphQLString)
    assert CeilGraphQLDirective.resolve(1.2, {}, None, None, info) == "2"
    assert (
        TruncateGraphQLDirective.resolve(math.inf, {"length": 10}, None, None, info)
        == "inf"
    )
    assert TitleCaseGraphQLDirective.resolve(math.inf, {}, None, None, info) == "Inf"
    floor = _schema.graphql_schema.get_directive("floor")
    assert floor is not None
    assert floor.locations == (DirectiveLocation.FIELD,)
    assert floor.args == {}
