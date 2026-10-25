"""COST_DIRECTIVE validation and the cost of directives on scalar lists."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from graphql import (
    GraphQLField,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    specified_directives,
)

from django_graphex.cost import analyze_cost
from django_graphex.directives import all_directives
from django_graphex.settings import graphql_api_settings

_SCHEMA = GraphQLSchema(
    query=GraphQLObjectType(
        "Query",
        {
            "tags": GraphQLField(GraphQLList(GraphQLString)),
            "text": GraphQLField(GraphQLString),
        },
    ),
    directives=[*specified_directives, *all_directives],
)


@pytest.mark.parametrize("bad", [-1, -100, "3", 1.5, True, [1], {}])
def test_cost_directive_rejects_values_that_cannot_mean_a_weight(bad: Any) -> None:
    """A negative, fractional, boolean or non-number weight is refused.

    Args:
        bad: The invalid setting value.

    Raises:
        ImproperlyConfigured: Asserted for every invalid value.
    """
    with override_settings(DJANGO_GRAPHEX={"COST_DIRECTIVE": bad}):
        with pytest.raises(ImproperlyConfigured, match="COST_DIRECTIVE"):
            graphql_api_settings.COST_DIRECTIVE  # noqa: B018


@pytest.mark.parametrize("good", [0, 1, 25])
def test_cost_directive_accepts_non_negative_integers(good: int) -> None:
    """Zero (the default) and positive integers are valid weights.

    Args:
        good: The valid setting value.
    """
    with override_settings(DJANGO_GRAPHEX={"COST_DIRECTIVE": good}):
        assert graphql_api_settings.COST_DIRECTIVE == good


@override_settings(DJANGO_GRAPHEX={"COST_DIRECTIVE": 4, "MAX_PAGE_SIZE": 10})
def test_a_directive_on_a_scalar_list_is_costed_once() -> None:
    """The directive runs once on the whole list value, so it is costed once.

    The page-size multiplier applies to lists of objects, whose selection runs
    per row; a scalar list is a single field resolution.
    """
    plain = analyze_cost(_SCHEMA, parse("{ tags }")).total
    with_directive = analyze_cost(_SCHEMA, parse("{ tags @shuffle }")).total
    assert with_directive - plain == 4
