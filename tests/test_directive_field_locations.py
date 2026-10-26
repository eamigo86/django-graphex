"""Public validation of transformation directive locations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.test import RequestFactory
from graphql import (
    DirectiveLocation,
    GraphQLDirective,
    GraphQLResolveInfo,
    GraphQLString,
    graphql_sync,
)
from graphql.type.directives import specified_directives

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import GraphQLView

_resolver_calls: list[str] = []


class Query(ObjectType):
    """Expose a fixed field to distinguish validation from execution.

    The text field resolves through a method that records its calls.
    """

    text = field(GraphQLString)

    def resolve_text(root: object, info: GraphQLResolveInfo) -> str:
        """Return a value and record actual resolver execution.

        Args:
            root: Root value supplied by GraphQL execution.
            info: Information about the current field.

        Returns:
            The fixed untransformed value.
        """
        _resolver_calls.append(info.field_name)
        return "hello"


_schema = DjangoGraphQLSchema(query=Query, directives=list(all_directives))
_middleware = [GraphQLDirectiveMiddleware()]


@pytest.mark.parametrize(
    ("document", "location"),
    [
        ("{ ...Words @uppercase } fragment Words on Query { text }", "fragment spread"),
        ("{ ... on Query @uppercase { text } }", "inline fragment"),
    ],
)
def test_transform_on_fragment_is_rejected_before_resolution(
    document: str, location: str
) -> None:
    """Reject a fragment-level transform rather than silently ignoring it.

    Args:
        document: Query with a transform at a fragment location.
        location: Expected invalid location in the validation error.
    """
    _resolver_calls.clear()
    result = graphql_sync(_schema.graphql_schema, document, middleware=_middleware)
    assert result.data is None
    assert result.errors is not None
    assert len(result.errors) == 1
    assert "@uppercase" in result.errors[0].message
    assert location in result.errors[0].message
    assert _resolver_calls == []


@pytest.mark.parametrize(
    "document",
    [
        "{ ...Words } fragment Words on Query { text @uppercase }",
        "{ ... on Query { text @uppercase } }",
    ],
)
def test_field_transform_inside_fragment_still_executes(document: str) -> None:
    """Keep the transform on the selected field inside either fragment kind.

    Args:
        document: A named or inline fragment containing a transformed field.
    """
    _resolver_calls.clear()
    result = graphql_sync(_schema.graphql_schema, document, middleware=_middleware)
    assert result.errors is None
    assert result.data == {"text": "HELLO"}
    assert _resolver_calls == ["text"]


def test_spec_builtins_still_control_fragment_and_field_selection() -> None:
    """Leave selection directives to the GraphQL executor.

    Scenario: spec builtins still control fragment and field selection.
    """
    _resolver_calls.clear()
    excluded = graphql_sync(
        _schema.graphql_schema,
        "{ text @skip(if: true) ...Words @include(if: false) } "
        "fragment Words on Query { text @uppercase }",
        middleware=_middleware,
    )
    assert excluded.errors is None
    assert excluded.data == {}
    assert _resolver_calls == []

    included = graphql_sync(
        _schema.graphql_schema,
        "{ ... on Query @include(if: true) { text @skip(if: false) @uppercase } }",
        middleware=_middleware,
    )
    assert included.errors is None
    assert included.data == {"text": "HELLO"}
    assert _resolver_calls == ["text"]


def test_library_locations_and_builtin_metadata_are_distinct() -> None:
    """Expose field-only library transforms without modifying spec directives.

    Scenario: library locations and builtin metadata are distinct.
    """
    library = list(all_directives[:25])
    builtins = list(all_directives[25:])
    assert len(library) == 25
    assert len({directive.name for directive in library}) == 25
    assert builtins == list(specified_directives)
    assert all(left is right for left, right in zip(builtins, specified_directives))
    assert all(
        directive.locations == (DirectiveLocation.FIELD,) for directive in library
    )
    assert all(not directive.is_repeatable for directive in library)

    result = graphql_sync(
        _schema.graphql_schema,
        "{ __schema { directives { name locations isRepeatable args { name } } } }",
    )
    assert result.errors is None
    exposed = {item["name"]: item for item in result.data["__schema"]["directives"]}
    for directive in library:
        item = exposed[directive.name]
        assert item["locations"] == ["FIELD"]
        assert item["isRepeatable"] is False
        assert {arg["name"] for arg in item["args"]} == set(directive.args)
    for directive in builtins:
        item = exposed[directive.name]
        assert item["locations"] == [location.name for location in directive.locations]
        assert item["isRepeatable"] == directive.is_repeatable
        assert {arg["name"] for arg in item["args"]} == set(directive.args)


@pytest.mark.parametrize(
    "document",
    [
        "{ ...Words @passthrough } fragment Words on Query { text }",
        "{ ... on Query @passthrough { text } }",
    ],
)
def test_raw_third_party_directive_keeps_explicit_fragment_locations(
    document: str,
) -> None:
    """Do not apply the library transform policy to a raw schema directive.

    Args:
        document: A query using the third-party directive on a fragment.
    """
    third_party = GraphQLDirective(
        name="passthrough",
        locations=[
            DirectiveLocation.FRAGMENT_SPREAD,
            DirectiveLocation.INLINE_FRAGMENT,
        ],
    )
    schema = DjangoGraphQLSchema(query=Query, directives=[*all_directives, third_party])
    _resolver_calls.clear()
    result = graphql_sync(schema.graphql_schema, document, middleware=_middleware)
    assert result.errors is None
    assert result.data == {"text": "hello"}
    assert _resolver_calls == ["text"]


def test_field_transform_order_is_unchanged() -> None:
    """Apply distinct field transforms in their written order.

    Scenario: field transform order is unchanged.
    """
    _resolver_calls.clear()
    result = graphql_sync(
        _schema.graphql_schema,
        "{ forward: text @uppercase @lowercase reverse: text @lowercase @uppercase }",
        middleware=_middleware,
    )
    assert result.errors is None
    assert result.data == {"forward": "hello", "reverse": "HELLO"}
    assert _resolver_calls == ["text", "text"]


def test_invalid_fragment_transform_has_http_error_wire() -> None:
    """Expose the standard validation error over the public HTTP view.

    Scenario: invalid fragment transform has http error wire.
    """
    _resolver_calls.clear()
    request = RequestFactory().post(
        "/graphql/",
        json.dumps(
            {"query": "{ ...Words @uppercase } fragment Words on Query { text }"}
        ),
        content_type="application/json",
    )
    response = GraphQLView.as_view(schema=_schema)(request)
    payload = json.loads(response.content)
    assert response["Content-Type"].startswith("application/json")
    assert payload.get("data") is None
    assert len(payload["errors"]) == 1
    assert "@uppercase" in payload["errors"][0]["message"]
    assert "fragment spread" in payload["errors"][0]["message"]
    assert _resolver_calls == []


def test_guide_states_field_only_contract_with_fragment_migration() -> None:
    """Keep the field-only rule and migration example together in the guide.

    Scenario: guide states field only contract with fragment migration.
    """
    guide = (Path(__file__).resolve().parents[1] / "docs/directives.md").read_text(
        encoding="utf-8"
    )
    heading = "### Transformation directive locations\n"
    assert guide.count(heading) == 1
    section = guide.split(heading, 1)[1].split("\n### ", 1)[0]
    assert "FIELD" in section
    assert "FRAGMENT_SPREAD" in section and "INLINE_FRAGMENT" in section
    assert "@skip" in section and "@include" in section
    assert "...Words @uppercase" in section
    assert "text @uppercase" in section
    assert "validation error" in section
