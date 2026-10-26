"""Native GraphQL regression coverage for nullable values formatted with @date."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from graphql import GraphQLNonNull, GraphQLString, graphql_sync

from django_graphex.core import ObjectType, field
from django_graphex.core.scalars import GdxDate, GdxDateTime
from django_graphex.directives import all_directives
from django_graphex.directives.date import DateGraphQLDirective
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema


class _Child(ObjectType):
    """Nested output exposing a required nullable-resolver date field."""

    required_date = field(GraphQLNonNull(GdxDateTime))

    def resolve_required_date(root: Any, info: Any) -> None:
        """Resolve the required date to null to exercise GraphQL bubbling.

        Args:
            root: The parent object.
            info: GraphQL execution metadata.

        Returns:
            A null value, which violates the field's declared type.
        """
        return None


class _Query(ObjectType):
    """Public query root for the date-null compatibility boundary."""

    nullable_text = field(GraphQLString)
    nullable_date = field(GdxDate)
    nullable_datetime = field(GdxDateTime)
    required_date = field(GraphQLNonNull(GdxDateTime))
    child = field(_Child)
    sibling = field(GraphQLString)
    valid_date = field(GdxDateTime)

    def resolve_nullable_text(root: Any, info: Any) -> None:
        """Return null for a string date field.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            Null for the nullable field.
        """
        return None

    resolve_nullable_date = resolve_nullable_text
    resolve_nullable_datetime = resolve_nullable_text
    resolve_required_date = resolve_nullable_text

    def resolve_child(root: Any, info: Any) -> dict[str, str]:
        """Return a nested object for bubbling verification.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A child source object.
        """
        return {}

    def resolve_sibling(root: Any, info: Any) -> str:
        """Return a sibling that should survive nested null bubbling.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A fixed unaffected value.
        """
        return "kept"

    def resolve_valid_date(root: Any, info: Any) -> datetime:
        """Return a valid aware date-time for the unchanged formatting control.

        Args:
            root: The query root.
            info: GraphQL execution metadata.

        Returns:
            A fixed aware date-time.
        """
        return datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


_SCHEMA = DjangoGraphQLSchema(query=_Query, directives=list(all_directives))


def _execute(query: str) -> Any:
    """Execute a query through the public schema and directive middleware.

    Args:
        query: A native GraphQL operation.

    Returns:
        The native execution result.
    """
    return graphql_sync(
        _SCHEMA.graphql_schema,
        query,
        middleware=[GraphQLDirectiveMiddleware()],
    )


@pytest.mark.parametrize(
    "query",
    [
        "{ nullableText @date }",
        '{ nullableText @date(format: "YYYY-MM-DD") }',
        '{ nullableDate @date(format: "YYYY-MM-DD") }',
        '{ nullableDatetime @date(format: "YYYY-MM-DD") }',
    ],
)
def test_nullable_date_field_stays_null(query: str) -> None:
    """Both default and explicit formats preserve nullable GraphQL nulls.

    Args:
        query: The string, date, or date-time field operation.
    """
    result = _execute(query)
    assert result.errors is None
    assert result.data is not None
    assert next(iter(result.data.values())) is None


def test_required_root_date_uses_normal_non_null_error() -> None:
    """A required root field bubbles to data null with a normal error path.

    Scenario: required root date uses normal non null error.
    """
    result = _execute('{ requiredDate @date(format: "YYYY-MM-DD") }')
    assert result.data is None
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["requiredDate"]
    assert "Cannot return null for non-nullable field" in result.errors[0].message


def test_required_nested_date_bubbles_only_to_nullable_parent() -> None:
    """Nested NonNull bubbling keeps an unrelated root sibling intact.

    Scenario: required nested date bubbles only to nullable parent.
    """
    result = _execute("{ child { requiredDate @date } sibling }")
    assert result.data == {"child": None, "sibling": "kept"}
    assert result.errors is not None and len(result.errors) == 1
    assert result.errors[0].path == ["child", "requiredDate"]


def test_valid_datetime_still_formats() -> None:
    """A non-null aware datetime retains the existing formatting path.

    Scenario: valid datetime still formats.
    """
    result = _execute('{ validDate @date(format: "YYYY-MM-DD") }')
    assert result.errors is None
    assert result.data == {"validDate": "2026-01-10"}


def test_invalid_non_null_value_keeps_fallback() -> None:
    """An invalid non-null value still uses the pre-existing fallback.

    Scenario: invalid non null value keeps fallback.
    """
    info = SimpleNamespace(return_type=GraphQLString)
    result = DateGraphQLDirective.resolve(object(), {}, None, None, info)
    assert result.date_str == "INVALID FORMAT STRING"


def test_date_resolver_none_is_not_a_format_wrapper() -> None:
    """The direct resolver must return None, not a serializable sentinel.

    Scenario: date resolver none is not a format wrapper.
    """
    info = SimpleNamespace(return_type=GraphQLString)
    assert DateGraphQLDirective.resolve(None, {}, None, None, info) is None


def test_date_only_value_still_uses_existing_formatting() -> None:
    """Non-null date-only values retain their prior formatting policy.

    Scenario: date only value still uses existing formatting.
    """
    info = SimpleNamespace(return_type=GdxDate)
    result = DateGraphQLDirective.resolve(
        date(2026, 1, 10), {"format": "YYYY-MM-DD"}, None, None, info
    )
    assert result.date_str == "2026-01-10"
