"""Bounded regressions for the patched GraphQL-core 3.2 runtime."""

import json
from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    GraphQLSyntaxError,
    parse,
    validate,
)
from graphql.validation.rules import overlapping_fields_can_be_merged

from django_graphex.views import BaseGraphQLView

SCHEMA = GraphQLSchema(
    GraphQLObjectType("Query", {"hello": GraphQLField(GraphQLString)})
)


def test_skipped_comments_consume_parser_token_budget() -> None:
    """Count skipped comments toward the parser's bounded token allocation.

    A short, comment-heavy document must exceed a deliberately small limit.
    """
    query = "# comment\n" * 4 + "{ hello }"

    with pytest.raises(GraphQLSyntaxError, match="more than 5 tokens"):
        parse(query, max_tokens=5)


def test_overlapping_field_comparisons_have_a_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop validation at a small test-only field comparison budget.

    Args:
        monkeypatch: Pytest helper for lowering the upstream comparison limit.
    """
    monkeypatch.setattr(
        overlapping_fields_can_be_merged,
        "MAX_FIELD_COMPARISONS",
        2,
        raising=False,
    )

    errors = validate(SCHEMA, parse("{ hello hello hello hello }"))

    assert any("comparison" in error.message.lower() for error in errors)


@pytest.mark.parametrize(
    "query",
    [
        '{ hello(arg: "abc\\',
        '{ hello(arg: "\\u',
        '{ hello(arg: "\\u00',
    ],
)
def test_truncated_escapes_raise_syntax_errors(query: str) -> None:
    """Report malformed trailing escapes as GraphQL syntax errors.

    Args:
        query: A document ending within an escape sequence.
    """
    with pytest.raises(GraphQLSyntaxError):
        parse(query)


def test_truncated_escape_returns_json_http_400() -> None:
    """Serialize a trailing escape as an HTTP syntax error.

    The response must be JSON with status 400, not an internal error.
    """
    view = BaseGraphQLView.as_view(schema=SimpleNamespace(graphql_schema=SCHEMA))
    request = RequestFactory().post(
        "/graphql/",
        json.dumps({"query": '{ hello(arg: "\\u'}),
        content_type="application/json",
    )

    response = view(request)

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert "Syntax Error" in json.loads(response.content)["errors"][0]["message"]
