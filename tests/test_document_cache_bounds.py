# -*- coding: utf-8 -*-
"""Tests for what the document caches may retain.

A verdict that depends on the caller's stack depth is not a property of the
document, and an AST is retained by token count rather than by query text.
"""

from unittest.mock import patch

from django.test import TestCase, override_settings
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


def _wide_query(fields: int) -> str:
    """Build a one-selection-set document with many one-character fields.

    Args:
        fields: How many fields the selection set holds.

    Returns:
        A query whose AST is far larger than its text.
    """
    return "{ " + "a " * fields + "}"


class TestRetainedAstBound(DocumentCacheBoundsBase):
    """The caches bound retained AST size (tokens), not only query text.



    Verifies the behavior named in the summary line.

    """

    def test_token_dense_document_is_not_retained(self) -> None:
        """A short text with too many tokens stays out of the parse cache.

        With a 1000-character bound, the per-entry token cap is 125; this
        document is 402 characters but 202 tokens.
        """
        query = _wide_query(200)
        with override_settings(
            DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAX_QUERY_LENGTH": 1000}
        ):
            self.assertLess(len(query), 1000)
            views_module.cached_parse(query)
        self.assertNotIn(query, views_module._PARSE_CACHE)

    def test_ordinary_document_is_retained(self) -> None:
        """A normal document inside both bounds is cached.

        Verifies the behavior named in the summary line.
        """
        query = "{ a }"
        with override_settings(
            DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAX_QUERY_LENGTH": 1000}
        ):
            views_module.cached_parse(query)
        self.assertIn(query, views_module._PARSE_CACHE)

    def test_total_token_budget_evicts_least_recently_used(self) -> None:
        """Retained tokens across the parse cache never exceed the budget.

        Verifies the behavior named in the summary line.
        """
        queries = [_wide_query(95 + i) for i in range(10)]
        with override_settings(
            DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAX_QUERY_LENGTH": 1000}
        ):
            for query in queries:
                views_module.cached_parse(query)
        self.assertLessEqual(views_module._PARSE_CACHE.tokens, 1000)
        self.assertNotIn(queries[0], views_module._PARSE_CACHE)
        self.assertIn(queries[-1], views_module._PARSE_CACHE)

    def test_none_removes_the_token_bound(self) -> None:
        """None keeps the documented "no bound" behavior.



        Verifies the behavior named in the summary line.

        """
        query = _wide_query(5000)
        with override_settings(
            DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAX_QUERY_LENGTH": None}
        ):
            views_module.cached_parse(query)
        self.assertIn(query, views_module._PARSE_CACHE)

    def test_validation_cache_key_does_not_retain_query_text(self) -> None:
        """The per-schema validation cache keys on a digest of the text.

        Verifies the behavior named in the summary line.
        """
        query = "{ a }"
        document = views_module.cached_parse(query)
        views_module.cached_validate(_SCHEMA, query, document, None, None)
        (sub,) = views_module._VALIDATE_CACHE.values()
        (key,) = sub
        self.assertNotIn(query, key)

    def test_token_dense_document_is_not_validated_into_the_cache(self) -> None:
        """The validation cache applies the same per-entry token bound.

        Verifies the behavior named in the summary line.
        """
        query = _wide_query(200)
        with override_settings(
            DJANGO_GRAPHEX={"DOCUMENT_CACHE_MAX_QUERY_LENGTH": 1000}
        ):
            document = views_module.cached_parse(query)
            views_module.cached_validate(_SCHEMA, query, document, None, None)
        self.assertEqual(len(views_module._VALIDATE_CACHE), 0)
