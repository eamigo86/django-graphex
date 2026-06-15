"""S-VIEWS (#1546): GraphQLView must accept a native ``DjangoGraphQLSchema``.

Release blocker #1546: ``views.py`` previously asserted
``isinstance(self.schema, graphene.Schema)`` in ``BaseGraphQLView.__init__``.
After S6f, ``DjangoGraphQLSchema`` is a plain class (NOT a ``graphene.Schema``
subclass), so that assert would REJECT a native schema and crash on view
construction — shipping native 2.0 broken.

The fix replaces the graphene ``isinstance`` with a duck-type check
(``hasattr(self.schema, "graphql_schema")``) that matches what the view
actually executes against (``self.schema.graphql_schema``). These tests pin
that contract:

* a native ``DjangoGraphQLSchema`` constructs the view WITHOUT raising
  (would have raised AssertionError before the fix);
* the same view executes a query end-to-end against the native schema;
* a schema-shaped object lacking ``graphql_schema`` still fails the check
  (the assert is not removed, only re-pointed).
"""

from __future__ import annotations

import json

import graphene
import pytest
from django.test import RequestFactory

from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.views import BaseGraphQLView

pytestmark = pytest.mark.native_only


class _Query(graphene.ObjectType):
    hello = graphene.String()

    def resolve_hello(root, info):  # noqa: N805
        return "world"


@pytest.mark.django_db
def test_native_schema_passes_view_schema_check():
    """A native DjangoGraphQLSchema must pass GraphQLView's schema check.

    Before #1546 this raised ``AssertionError`` in ``BaseGraphQLView.__init__``
    because the schema is not a ``graphene.Schema`` instance.
    """
    schema = DjangoGraphQLSchema(query=_Query)
    # Must NOT raise: the duck-type check accepts any schema exposing
    # ``graphql_schema`` (what the view executes against).
    view = BaseGraphQLView(schema=schema)
    assert view.schema is schema
    assert hasattr(view.schema, "graphql_schema")


@pytest.mark.django_db
def test_native_schema_view_executes_query_end_to_end():
    """The view executes a query against the native schema's graphql_schema."""
    schema = DjangoGraphQLSchema(query=_Query)
    view = BaseGraphQLView.as_view(schema=schema)
    request = RequestFactory().post(
        "/graphql/", {"query": "{ hello }"}, content_type="application/json"
    )
    response = view(request)
    assert response.status_code == 200
    assert json.loads(response.content)["data"]["hello"] == "world"


def test_schema_without_graphql_schema_attr_fails_check():
    """A schema-shaped object lacking ``graphql_schema`` still fails the check.

    Ensures the assert was RE-POINTED, not deleted: passing something that the
    view cannot execute against must error at construction time.
    """

    class _NotASchema:
        pass

    with pytest.raises(AssertionError):
        BaseGraphQLView(schema=_NotASchema())
