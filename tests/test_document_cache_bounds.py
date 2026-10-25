# -*- coding: utf-8 -*-
"""Tests for what the document caches may retain.

A verdict that depends on the caller's stack depth is not a property of the
document, and an AST is retained by token count rather than by query text.
"""

from unittest.mock import patch

from django.test import TestCase
from graphql import GraphQLField, GraphQLObjectType, GraphQLSchema, GraphQLString

from django_graphex import views as views_module

_SCHEMA = GraphQLSchema(
    query=GraphQLObjectType("Query", {"a": GraphQLField(GraphQLString)})
)


class DocumentCacheBoundsBase(TestCase):
    """Shared setup that starts every test with empty document caches.

    Subclassed by the test classes in this module.
    """

    def setUp(self) -> None:
        """Clear both document caches.

        Runs before each test in every subclass.
        """
        views_module.clear_document_caches()


class TestStackVerdictIsNotCached(DocumentCacheBoundsBase):
    """A RecursionError verdict must not be served to a caller with a free stack.

    Covers the validation cache in "cached_validate".
    """

    def test_recursion_verdict_is_not_memoized(self) -> None:
        """A shallow caller after a deep one gets a real validation.

        The first call exhausts the stack and answers QUERY_TOO_DEEP; the
        second call, with the stack free again, must validate the document.
        """
        query = "{ a }"
        document = views_module.cached_parse(query)
        with patch.object(views_module, "validate", side_effect=[RecursionError(), []]):
            first = views_module.cached_validate(_SCHEMA, query, document, None, None)
            second = views_module.cached_validate(_SCHEMA, query, document, None, None)
        self.assertEqual(first[0].extensions["code"], "QUERY_TOO_DEEP")
        self.assertEqual(second, ())
