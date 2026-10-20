"""Native GraphQL regressions for directive-only case normalization."""

from typing import Any

import pytest
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql_sync,
    specified_directives,
)
from graphql.execution import MiddlewareManager

from django_graphex.directives import all_directives
from django_graphex.middleware import GraphQLDirectiveMiddleware

_SCHEMA = GraphQLSchema(
    query=GraphQLObjectType(
        "CaseQuery",
        lambda: {
            "case_value": GraphQLField(
                GraphQLString, resolve=lambda root, info: root["value"]
            ),
            "other_value": GraphQLField(
                GraphQLString, resolve=lambda root, info: root["other"]
            ),
        },
    ),
    directives=tuple(specified_directives) + tuple(all_directives),
)
_MIDDLEWARE = MiddlewareManager(GraphQLDirectiveMiddleware())
_QUERY = """{
    camel: case_value @camel_case
    snake: case_value @snake_case
    kebab: case_value @kebab_case
    other_value
    other_upper: other_value @uppercase
}"""


def _run_case(value: Any) -> dict[str, Any]:
    """Execute all three case directives through the native GraphQL pipeline.

    Args:
        value: The resolved value of the case field.

    Returns:
        The data payload from the executed query.
    """
    result = graphql_sync(
        _SCHEMA,
        _QUERY,
        root_value={"value": value, "other": "stay"},
        middleware=_MIDDLEWARE,
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    return result.data


@pytest.mark.parametrize(
    "source",
    ["order_total", "order-total", "order total", "orderTotal", "OrderTotal"],
)
def test_approved_source_forms_normalize_consistently(source: str) -> None:
    """All approved word boundaries must yield the same directive outputs.

    Args:
        source: One approved spelling of the same two words.
    """
    assert _run_case(source) == {
        "camel": "orderTotal",
        "snake": "order_total",
        "kebab": "order-total",
        "other_value": "stay",
        "other_upper": "STAY",
    }


def test_acronym_block_is_one_word() -> None:
    """An acronym preceding a title word must retain the word boundary."""
    assert _run_case("HTTPServer") == {
        "camel": "httpServer",
        "snake": "http_server",
        "kebab": "http-server",
        "other_value": "stay",
        "other_upper": "STAY",
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  order__-- total  ", ("orderTotal", "order_total", "order-total")),
        ("v2_name", ("v2Name", "v2_name", "v2-name")),
        ("v2Name", ("v2Name", "v2_name", "v2-name")),
        ("HTTP--Server__API", ("httpServerApi", "http_server_api", "http-server-api")),
        ("", ("", "", "")),
        (" __-- ", ("", "", "")),
    ],
)
def test_approved_boundaries_and_nonletters(
    source: str, expected: tuple[str, str, str]
) -> None:
    """Approved separators collapse while digits remain in their words.

    Args:
        source: An approved input spelling.
        expected: Camel, snake, and kebab outputs in directive order.
    """
    data = _run_case(source)
    assert (data["camel"], data["snake"], data["kebab"]) == expected


@pytest.mark.parametrize("source", ["orderTotal", "HTTPServer", "v2Name"])
def test_each_directive_output_is_idempotent(source: str) -> None:
    """Each case directive must leave its own converted output unchanged.

    Args:
        source: A camel, acronym, or digit-bearing source string.
    """
    first = _run_case(source)
    for style in ("camel", "snake", "kebab"):
        assert _run_case(first[style])[style] == first[style]


def test_none_passes_through_and_numeric_value_is_stringified() -> None:
    """The existing null and Python-string-coercion mechanism remains active."""
    empty = _run_case(None)
    assert (empty["camel"], empty["snake"], empty["kebab"]) == (
        None,
        None,
        None,
    )
    numeric = _run_case(42)
    assert (numeric["camel"], numeric["snake"], numeric["kebab"]) == (
        "42",
        "42",
        "42",
    )


@pytest.mark.parametrize("source", ["order.total", "café_name", "order\ttotal"])
def test_unapproved_character_forms_keep_legacy_converters(source: str) -> None:
    """Punctuation, Unicode, and tab inputs must not gain a new policy.

    Args:
        source: An input outside the approved ASCII word/separator forms.
    """
    from django_graphex._strconv import to_camel_case, to_snake_case
    from django_graphex.utils import to_kebab_case

    data = _run_case(source)
    assert data["camel"] == to_camel_case(source)
    assert data["snake"] == to_snake_case(source.title().replace(" ", ""))
    assert data["kebab"] == to_kebab_case(source)
