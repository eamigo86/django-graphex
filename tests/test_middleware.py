# -*- coding: utf-8 -*-
"""Tests for django_graphex.middleware module."""

from unittest.mock import Mock

import graphene
from django.test import TestCase
from graphql import GraphQLArgument, GraphQLString

from django_graphex import all_directives
from django_graphex.directives.base import BaseExtraGraphQLDirective
from django_graphex.middleware import GraphQLDirectiveMiddleware


class PrefixGraphQLDirective(BaseExtraGraphQLDirective):
    """Prefix a string value (test directive)."""

    @staticmethod
    def get_args():
        """Get arguments for the prefix directive."""
        return {"with": GraphQLArgument(GraphQLString)}

    @staticmethod
    def resolve(value, args, directive, root, info, **kwargs):
        """Prefix strings; leave non-strings untouched."""
        if not isinstance(value, str):
            return value
        return "{}{}".format(args.get("with") or "p_", value)


# Instantiating registers the directive in the global registry under "prefix".
_prefix_directive = PrefixGraphQLDirective()
_middleware = [GraphQLDirectiveMiddleware()]


class _Query(graphene.ObjectType):
    text = graphene.String()
    number = graphene.Int()

    def resolve_text(root, info):
        return "x"

    def resolve_number(root, info):
        return 42


_schema = graphene.Schema(
    query=_Query, directives=list(all_directives) + [_prefix_directive]
)


class GraphQLDirectiveMiddlewareExecutionTest(TestCase):
    """Behavioural tests driving the middleware through real schema execution."""

    def _run(self, query, **variables):
        result = _schema.execute(
            query, middleware=_middleware, variables=variables or None
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_custom_directive_applied(self):
        self.assertEqual(self._run("{ text @prefix }")["text"], "p_x")

    def test_custom_directive_with_argument(self):
        self.assertEqual(self._run('{ text @prefix(with:"A_") }')["text"], "A_x")

    def test_directive_argument_as_variable(self):
        data = self._run("query($w:String!){ text @prefix(with:$w) }", w="V_")
        self.assertEqual(data["text"], "V_x")

    def test_multiple_directives_chain_in_order(self):
        # Directives are not repeatable in GraphQL, so chain two *different*
        # ones: @uppercase runs first ("x" -> "X"), then @prefix ("X" -> "p_X").
        self.assertEqual(self._run("{ text @uppercase @prefix }")["text"], "p_X")

    def test_mixed_with_builtin_include(self):
        # @include is handled by the executor; @prefix still applies.
        self.assertEqual(
            self._run("{ text @include(if: true) @prefix }")["text"], "p_x"
        )

    def test_non_string_value_left_untouched(self):
        self.assertEqual(self._run("{ number @prefix }")["number"], 42)

    def test_field_without_directives_is_unchanged(self):
        self.assertEqual(self._run("{ text }")["text"], "x")


class GraphQLDirectiveMiddlewareUnitTest(TestCase):
    """Structural unit tests of the middleware plumbing."""

    def setUp(self):
        self.middleware = GraphQLDirectiveMiddleware()

    def test_middleware_creation(self):
        self.assertIsInstance(self.middleware, GraphQLDirectiveMiddleware)
        self.assertTrue(hasattr(self.middleware, "resolve"))

    def test_resolve_without_directives(self):
        next_func = Mock(return_value="test_value")
        info = Mock()
        field = Mock()
        field.directives = []
        info.field_nodes = [field]

        result = self.middleware.resolve(next_func, None, info)

        self.assertEqual(result, "test_value")
        next_func.assert_called_once_with(None, info)

    def test_resolve_passes_kwargs_to_next(self):
        next_func = Mock(return_value="value")
        info = Mock()
        field = Mock()
        field.directives = []
        info.field_nodes = [field]

        result = self.middleware.resolve(next_func, None, info, custom_arg="test")

        self.assertEqual(result, "value")
        next_func.assert_called_once_with(None, info, custom_arg="test")

    def test_resolve_preserves_resolver_context(self):
        def resolver(root, info, **kwargs):
            return "root:{}".format(root)

        info = Mock()
        field = Mock()
        field.directives = []
        info.field_nodes = [field]

        result = self.middleware.resolve(resolver, "the_root", info)
        self.assertEqual(result, "root:the_root")
