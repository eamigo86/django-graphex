"""Selected root-fragment classification and HTTP cleaning regressions."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from django.test import RequestFactory, override_settings
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString, parse
from graphql.language.ast import FragmentDefinitionNode

from django_graphex.views import GraphQLView

_SCHEMA = SimpleNamespace(
    graphql_schema=GraphQLSchema(
        query=GraphQLObjectType(
            "Query",
            {
                "greeting": GraphQLField(GraphQLString, resolve=lambda *_: "hello"),
                "missing": GraphQLField(GraphQLString, resolve=lambda *_: None),
            },
        )
    )
)


def _post(query: str, operation_name: str | None = None) -> dict[str, Any]:
    """Execute a JSON request through the enhanced HTTP view.

    Args:
        query: GraphQL document sent by the client.
        operation_name: Named operation selected from the document.

    Returns:
        The parsed HTTP response body.
    """
    body: dict[str, Any] = {"query": query}
    if operation_name is not None:
        body["operationName"] = operation_name
    request = RequestFactory().post(
        "/graphql/", json.dumps(body), content_type="application/json"
    )
    response = GraphQLView.as_view(schema=_SCHEMA)(request)
    assert response.status_code == 200
    return json.loads(response.content)


@pytest.mark.parametrize(
    "query",
    [
        '{ alias: __type(name: "Query") { description interfaces { name } } }',
        "{ ... on Query { ... on Query { __schema { queryType { name } } } } }",
        "query Intro { ...Root } fragment Root on Query { ...Inner } "
        'fragment Inner on Query { __type(name: "Query") { description } }',
        "query Intro { ...Root ... on Query { __schema { queryType { name } } } } "
        'fragment Root on Query { t: __type(name: "Query") { description } }',
    ],
)
def test_reachable_root_fragments_are_introspection(query: str) -> None:
    """Recognize only introspection fields through reachable root spreads.

    Args:
        query: A GraphQL document with direct or fragmented root selections.
    """
    assert GraphQLView._is_introspection_document(
        parse(query), "Intro" if "Intro" in query else None
    )


@pytest.mark.parametrize(
    "query",
    [
        "{ __schema { queryType { name } } ... on Query { greeting } }",
        "query { ...Root } fragment Root on Query { ...Inner } "
        'fragment Inner on Query { __type(name: "Query") { name } greeting }',
        "{ __typename __schema { queryType { name } } }",
        "query { ...Unknown }",
        "query { ...Cycle } fragment Cycle on Query { ...Cycle }",
        "query { ...A } fragment A on Query { ...B } fragment B on Query { ...A }",
    ],
)
def test_mixed_or_unresolved_root_fragments_fail_closed(query: str) -> None:
    """Do not exempt ordinary fields, missing spreads, or reachable cycles.

    Args:
        query: A GraphQL document with a non-introspection root path.
    """
    assert not GraphQLView._is_introspection_document(parse(query))


def test_selected_operation_ignores_unreachable_fragments() -> None:
    """Only the selected operation determines the exemption.

    An unrelated cyclic fragment does not affect the selected root fields.
    """
    document = parse(
        "query Intro { ...Root } query Normal { greeting } "
        'fragment Root on Query { __type(name: "Query") { description } } '
        "fragment Unused on Query { ...Unused }"
    )
    assert GraphQLView._is_introspection_document(document, "Intro")
    assert not GraphQLView._is_introspection_document(document, "Normal")
    assert not GraphQLView._is_introspection_document(document)
    assert not GraphQLView._is_introspection_document(document, "Unknown")
    assert not GraphQLView._is_introspection_document(
        parse("query Empty { ...Missing }")
    )


def test_repeated_shared_fragments_expand_once() -> None:
    """Classify a shared fragment DAG without exponential expansion.

    Each named fragment's root selections should be read at most once.
    """
    depth = 12
    fragments = [
        f"fragment F{index} on Query {{ ...F{index + 1} ...F{index + 1} }}"
        for index in range(depth)
    ]
    fragments.append('fragment F12 on Query { __type(name: "Query") { name } }')
    document = parse("query { ...F0 } " + " ".join(fragments))
    original = FragmentDefinitionNode.__getattribute__
    reads = 0

    def counted(node: FragmentDefinitionNode, name: str) -> Any:
        """Count fragment selection reads during traversal.

        Args:
            node: Fragment definition whose attribute is accessed.
            name: Attribute name.

        Returns:
            The original attribute value.
        """
        nonlocal reads
        if name == "selection_set":
            reads += 1
        return original(node, name)

    with patch.object(FragmentDefinitionNode, "__getattribute__", counted):
        assert GraphQLView._is_introspection_document(document)
    assert reads <= depth + 1


@override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
def test_http_named_fragment_introspection_keeps_null_and_empty_lists() -> None:
    """Keep null and empty-list schema values through the real HTTP view.

    Named root spreads must bypass ordinary response cleaning.
    """
    payload = _post(
        'query Intro { ...Root } fragment Root on Query { t: __type(name: "Query") '
        "{ description interfaces { name } } }"
    )
    assert payload["data"]["t"]["description"] is None
    assert payload["data"]["t"]["interfaces"] == []


@override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": True})
def test_http_mixed_fragment_still_cleans_ordinary_data() -> None:
    """Leave mixed documents on the ordinary response-cleaning path.

    A regular root field reachable in a fragment prevents exemption.
    """
    payload = _post(
        'query { ...Root } fragment Root on Query { __type(name: "Query") '
        "{ description } greeting missing }"
    )
    assert payload["data"] == {"greeting": "hello"}


@override_settings(DJANGO_GRAPHEX={"CLEAN_RESPONSE": False})
def test_http_disabled_cleaning_remains_unchanged() -> None:
    """Preserve the full ordinary payload when cleaning is disabled.

    The classifier does not change the default response policy.
    """
    payload = _post("{ greeting missing }")
    assert payload["data"] == {"greeting": "hello", "missing": None}
