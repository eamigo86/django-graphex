"""Cost analysis must read page-size arguments by wire (camelCase) name too."""

from typing import Any

import pytest
from django.test import override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
)

from django_graphex._strconv import to_camel_case
from django_graphex.cost import analyze_cost
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)


def _schema(args: dict[str, Any]) -> GraphQLSchema:
    """Build a schema with one list field taking the given arguments.

    Args:
        args: Wire-named arguments of the list field.

    Returns:
        The schema.
    """
    inner = GraphQLObjectType("In", {"n": GraphQLField(GraphQLString)})
    item = GraphQLObjectType("It", {"c": GraphQLField(inner)})
    field = GraphQLField(GraphQLList(item), args=args)
    return GraphQLSchema(query=GraphQLObjectType("Q", {"items": field}))


def _total(args: dict[str, Any], wire_arg: str) -> int:
    """Cost items(<wire_arg>: 5000) against a schema with the given args.

    Args:
        args: Wire-named arguments of the list field.
        wire_arg: The argument carrying 5000.

    Returns:
        The estimated cost.
    """
    doc = parse("{ items(%s: 5000) { c { n } } }" % wire_arg)
    return analyze_cost(_schema(args), doc).total


@pytest.mark.parametrize(
    ("paginator", "wire_arg"),
    [
        (LimitOffsetGraphqlPagination(), "limit"),
        (PageGraphqlPagination(page_size_query_param="page_size"), "pageSize"),
        (PageGraphqlPagination(page_size_query_param="pageSize"), "pageSize"),
        (CursorGraphqlPagination(), "first"),
    ],
)
@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": None})
def test_paginator_page_size_argument_is_costed(paginator: Any, wire_arg: str) -> None:
    """Each paginator's size argument multiplies the cost by its value.

    Args:
        paginator: The paginator whose arguments build the field.
        wire_arg: The wire name of its page-size argument.
    """
    args = {to_camel_case(k): v for k, v in paginator.to_graphql_fields().items()}
    assert wire_arg in args
    assert _total(args, wire_arg) > 5000


@override_settings(DJANGO_GRAPHEX={"MAX_PAGE_SIZE": None})
def test_wire_name_matches_snake_case_setting() -> None:
    """A camelCase argument is costed although the setting lists snake_case.

    The wire name is snake-cased before it is compared.
    """
    assert _total({"pageSize": GraphQLArgument(GraphQLInt)}, "pageSize") > 5000


@override_settings(
    DJANGO_GRAPHEX={"MAX_PAGE_SIZE": None, "COST_PAGINATION_ARGS": ("per_page",)}
)
def test_custom_configured_name_is_costed() -> None:
    """A user-configured argument name is matched by wire name as well.

    The configured name is snake-cased before it is compared.
    """
    assert _total({"perPage": GraphQLArgument(GraphQLInt)}, "perPage") > 5000
