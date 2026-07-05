"""S-VIEWS (#1546): GraphQLView must accept a native "DjangoGraphQLSchema".

Release blocker #1546: "views.py" previously asserted
"isinstance(self.schema, graphene.Schema)" in "BaseGraphQLView.__init__".
After S6f, "DjangoGraphQLSchema" is a plain class (NOT a "graphene.Schema"
subclass), so that assert would REJECT a native schema and crash on view
construction — shipping native 2.0 broken.

The fix replaces the graphene "isinstance" with a duck-type check
("hasattr(self.schema, 'graphql_schema')") that matches what the view
actually executes against ("self.schema.graphql_schema"). These tests pin
that contract:

* a native "DjangoGraphQLSchema" constructs the view WITHOUT raising
  (would have raised AssertionError before the fix);
* the same view executes a query end-to-end against the native schema;
* a schema-shaped object lacking "graphql_schema" still fails the check
  (the assert is not removed, only re-pointed).
"""

from __future__ import annotations

import json

import pytest
from django.test import RequestFactory
from graphql import GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import BaseGraphQLView


class _Query(ObjectType):
    hello = field(GraphQLString)

    def resolve_hello(root, info):  # noqa: N805
        return "world"


@pytest.mark.django_db
def test_native_schema_passes_view_schema_check() -> None:
    """Ships broken if a native DjangoGraphQLSchema stops passing
    GraphQLView's schema check.

    Before #1546 this raised "AssertionError" in "BaseGraphQLView.__init__"
    because the schema is not a "graphene.Schema" instance.
    """
    schema = DjangoGraphQLSchema(query=_Query)
    # Must NOT raise: the duck-type check accepts any schema exposing
    # ``graphql_schema`` (what the view executes against).
    view = BaseGraphQLView(schema=schema)
    assert view.schema is schema
    assert hasattr(view.schema, "graphql_schema")


@pytest.mark.django_db
def test_native_schema_view_executes_query_end_to_end() -> None:
    """Ships broken if the view stops executing a query against the native
    schema's graphql_schema.
    """
    schema = DjangoGraphQLSchema(query=_Query)
    view = BaseGraphQLView.as_view(schema=schema)
    request = RequestFactory().post(
        "/graphql/", {"query": "{ hello }"}, content_type="application/json"
    )
    response = view(request)
    assert response.status_code == 200
    assert json.loads(response.content)["data"]["hello"] == "world"


def test_schema_without_graphql_schema_attr_fails_check() -> None:
    """Ships broken if a schema-shaped object lacking "graphql_schema" stops
    failing the check.

    Ensures the assert was re-pointed, not deleted: passing something that the
    view cannot execute against must error at construction time.
    """

    class _NotASchema:
        pass

    with pytest.raises(AssertionError):
        BaseGraphQLView(schema=_NotASchema())
