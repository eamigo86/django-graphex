"""Invalid numeric and temporal filter values are rejected with a clean error."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

import pytest
from django.test import RequestFactory
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from tests._schema_isolation import isolated_pair
from tests.models import Author, ScalarKindsModel

R = Registry()
LOOKUPS = ("exact", "in", "gt", "range")


class ScalarNode(DjangoObjectType):
    """Expose every scalar filter in an isolated registry.

    Keep this registry separate from the other filter tests.
    """

    class Meta:
        """Configure the node.

        Bind the model, registry and the filtered fields.
        """

        model = ScalarKindsModel
        registry = R
        filter_fields = {
            name: LOOKUPS
            for name in ("decimal", "floating", "integer", "big_integer", "date")
        }


class Query(ObjectType):
    """Root query exposing the filtered list.

    The list accepts the generated filter argument.
    """

    rows = DjangoFilterListField(ScalarNode)


def _run(field: str, lookup: str, value: Any) -> Any:
    """Execute one filter query with the value passed as a variable.

    Args:
        field: Model field name.
        lookup: Lookup name.
        value: Raw value (a list for in/range).

    Returns:
        The graphql-core execution result.
    """
    from django_graphex._strconv import to_camel_case

    schema = DjangoGraphQLSchema(
        query=Query, registries=isolated_pair(R)
    ).graphql_schema
    name = to_camel_case(field)
    return graphql_sync(
        schema,
        f"query{{ rows(filter: {{{name}: {{{lookup}: {json.dumps(value)}}}}}) {{ id }} }}",
        context_value=RequestFactory().post("/g/"),
    )


@pytest.fixture
def rows() -> None:
    """Create three rows to filter.

    Each row carries a distinct value for every filtered field.
    """
    author = Author.objects.create(name="a")
    for i in range(3):
        ScalarKindsModel.objects.create(
            author=author,
            char="c",
            integer=i,
            big_integer=i,
            floating=float(i),
            decimal=Decimal(i),
            date=datetime.date(2024, 1, 1 + i),
        )


BAD = [
    ("decimal", "NaN"),
    ("decimal", "sNaN"),
    ("decimal", "Infinity"),
    ("decimal", "-Infinity"),
    ("decimal", "abc"),
    ("floating", "NaN"),
    ("floating", "abc"),
    ("integer", 99999999999),
    ("integer", "abc"),
    ("big_integer", "99999999999999999999"),
    ("big_integer", "abc"),
    ("date", "2024-13-45"),
    ("date", "abc"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("field,bad", BAD)
@pytest.mark.parametrize("lookup", LOOKUPS)
def test_invalid_scalar_is_a_clean_validation_error(
    rows: None, field: str, bad: Any, lookup: str
) -> None:
    """Reject an invalid filter value before the ORM sees it.

    Args:
        rows: Fixture creating rows.
        field: Model field under test.
        bad: Invalid value for that field.
        lookup: Lookup under test.
    """
    value = [bad, bad] if lookup in ("in", "range") else bad
    result = _run(field, lookup, value)
    assert result.data is None
    assert result.errors
    assert "%(value)s" not in result.errors[0].message


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,good",
    [
        ("decimal", "1"),
        ("floating", 1.0),
        ("integer", 1),
        ("big_integer", "1"),
        ("date", "2024-01-02"),
    ],
)
@pytest.mark.parametrize("lookup,count", [("exact", 1), ("in", 1), ("gt", 1)])
def test_valid_scalar_still_filters(
    rows: None, field: str, good: Any, lookup: str, count: int
) -> None:
    """Keep valid values working for every lookup shape.

    Args:
        rows: Fixture creating rows.
        field: Model field under test.
        good: Valid value for that field.
        lookup: Lookup under test.
        count: Expected number of matching rows.
    """
    result = _run(field, lookup, [good] if lookup == "in" else good)
    assert not result.errors
    assert len(result.data["rows"]) == count


@pytest.mark.django_db
def test_valid_range_still_filters(rows: None) -> None:
    """Keep a valid Decimal range working.

    Args:
        rows: Fixture creating rows.
    """
    result = _run("decimal", "range", ["0", "1"])
    assert not result.errors
    assert len(result.data["rows"]) == 2
