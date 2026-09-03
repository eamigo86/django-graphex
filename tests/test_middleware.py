# -*- coding: utf-8 -*-
"""Tests for the django_graphex.middleware module.

Covers "GraphQLDirectiveMiddleware" both behaviourally, by executing real
queries with custom directives through a live schema, and structurally, by
unit-testing the middleware's resolve plumbing in isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

from django.test import TestCase
from graphql import GraphQLArgument, GraphQLInt, GraphQLString

from django_graphex.core import ObjectType, field
from django_graphex.directives import all_directives
from django_graphex.directives.base import BaseExtraGraphQLDirective
from django_graphex.middleware import GraphQLDirectiveMiddleware
from django_graphex.schema import DjangoGraphQLSchema

if TYPE_CHECKING:
    from graphql import GraphQLResolveInfo


class PrefixGraphQLDirective(BaseExtraGraphQLDirective):
    """Prefix a string value (test directive).

    Used across this module to exercise directive argument handling, chaining
    with other directives, and non-string passthrough.
    """

    @staticmethod
    def get_args() -> dict[str, GraphQLArgument]:
        """Get arguments for the prefix directive.

        Returns:
            A mapping with a single "with" argument used as the prefix text.
        """
        return {"with": GraphQLArgument(GraphQLString)}

    @staticmethod
    def resolve(
        value: Any,
        args: dict[str, Any],
        directive: Any,
        root: Any,
        info: GraphQLResolveInfo,
        **kwargs: Any,
    ) -> Any:
        """Prefix strings; leave non-strings untouched.

        Args:
            value: The resolved field value.
            args: The coerced directive arguments.
            directive: The directive AST node.
            root: The root value passed to the resolver.
            info: The GraphQL resolve info for the field.
            **kwargs: Additional resolver keyword arguments, ignored here.

        Returns:
            The value prefixed with "with" (or "p_" by default) when it is a
            string, otherwise the value unchanged.
        """
        if not isinstance(value, str):
            return value
        return "{}{}".format(args.get("with") or "p_", value)


# Instantiating registers the directive in the global registry under "prefix".
_prefix_directive = PrefixGraphQLDirective()
_middleware = [GraphQLDirectiveMiddleware()]


class _Query(ObjectType):
    """Minimal root query exposing a string and an int field for directive tests."""

    text = field(GraphQLString)
    number = field(GraphQLInt)

    def resolve_text(root: Any, info: GraphQLResolveInfo) -> str:
        """Resolve a fixed string value used to exercise string directives.

        Args:
            root: The root value passed to the resolver, unused.
            info: The GraphQL resolve info for the field.

        Returns:
            str: The literal value "x".
        """
        return "x"

    def resolve_number(root: Any, info: GraphQLResolveInfo) -> int:
        """Resolve a fixed int value used to exercise the non-string passthrough.

        Args:
            root: The root value passed to the resolver, unused.
            info: The GraphQL resolve info for the field.

        Returns:
            int: The literal value 42.
        """
        return 42


_schema = DjangoGraphQLSchema(
    query=_Query, directives=list(all_directives) + [_prefix_directive]
)


class GraphQLDirectiveMiddlewareExecutionTest(TestCase):
    """Behavioural tests driving the middleware through real schema execution.

    Each test runs a GraphQL document against "_schema" with the directive
    middleware installed and asserts on the resulting data.
    """

    def _run(self, query: str, **variables: Any) -> dict[str, Any]:
        """Execute a query against the test schema with the directive middleware.

        Args:
            query: The GraphQL query document to execute.
            **variables: Variable values passed through to "graphql_sync".

        Returns:
            dict[str, Any]: The "data" payload of the execution result.

        Raises:
            AssertionError: If the execution result contains errors.
        """
        from graphql import graphql_sync

        result = graphql_sync(
            _schema.graphql_schema,
            query,
            middleware=_middleware,
            variable_values=variables or None,
        )
        self.assertIsNone(result.errors, result.errors)
        return result.data

    def test_custom_directive_applied(self) -> None:
        """A custom "@prefix" directive without arguments prefixes with its default.

        This test breaks if the middleware stops invoking registered
        directive resolvers for fields that declare them.
        """
        self.assertEqual(self._run("{ text @prefix }")["text"], "p_x")

    def test_custom_directive_with_argument(self) -> None:
        """The "@prefix" directive honors an explicit "with" argument.

        This test breaks if directive argument coercion stops reaching the
        directive's "resolve" implementation.
        """
        self.assertEqual(self._run('{ text @prefix(with:"A_") }')["text"], "A_x")

    def test_directive_argument_as_variable(self) -> None:
        """A directive argument supplied as a GraphQL variable is honored.

        This test breaks if variable resolution stops flowing into directive
        argument coercion before "resolve" runs.
        """
        data = self._run("query($w:String!){ text @prefix(with:$w) }", w="V_")
        self.assertEqual(data["text"], "V_x")

    def test_multiple_directives_chain_in_order(self) -> None:
        """Two different directives on one field apply in declaration order.

        This test breaks if the middleware stops chaining directive results
        (each directive's output feeding into the next) in source order.
        """
        # Directives are not repeatable in GraphQL, so chain two *different*
        # ones: @uppercase runs first ("x" -> "X"), then @prefix ("X" -> "p_X").
        self.assertEqual(self._run("{ text @uppercase @prefix }")["text"], "p_X")

    def test_mixed_with_builtin_include(self) -> None:
        """A custom directive still applies alongside the builtin "@include".

        This test breaks if custom directive handling interferes with, or is
        bypassed by, GraphQL's own executor-level directives.
        """
        # @include is handled by the executor; @prefix still applies.
        self.assertEqual(
            self._run("{ text @include(if: true) @prefix }")["text"], "p_x"
        )

    def test_non_string_value_left_untouched(self) -> None:
        """The "@prefix" directive leaves non-string values unchanged.

        This test breaks if the directive stops guarding its string-only
        transformation and starts coercing or corrupting other types.
        """
        self.assertEqual(self._run("{ number @prefix }")["number"], 42)

    def test_field_without_directives_is_unchanged(self) -> None:
        """A field with no directives resolves to its plain value.

        This test breaks if the middleware starts altering field values even
        when no directive is present on the field.
        """
        self.assertEqual(self._run("{ text }")["text"], "x")


class GraphQLDirectiveMiddlewareUnitTest(TestCase):
    """Structural unit tests of the middleware plumbing.

    Exercises "GraphQLDirectiveMiddleware.resolve" directly against mocked
    "info"/"next" collaborators, without a real schema execution.
    """

    def setUp(self) -> None:
        """Build a fresh "GraphQLDirectiveMiddleware" for each test.

        Assigned to "self.middleware" for reuse across the test methods.
        """
        self.middleware = GraphQLDirectiveMiddleware()

    def test_middleware_creation(self) -> None:
        """The middleware constructs and exposes a "resolve" method.

        This test breaks if the middleware's shape changes such that it is
        no longer usable as a graphql-core middleware entry.
        """
        self.assertIsInstance(self.middleware, GraphQLDirectiveMiddleware)
        self.assertTrue(hasattr(self.middleware, "resolve"))

    def test_resolve_without_directives(self) -> None:
        """With no directives on the field, "resolve" delegates to "next" untouched.

        This test breaks if the middleware starts mutating the resolver
        chain's return value when there is nothing to apply.
        """
        next_func = Mock(return_value="test_value")
        info = Mock()
        field = Mock()
        field.directives = []
        info.field_nodes = [field]

        result = self.middleware.resolve(next_func, None, info)

        self.assertEqual(result, "test_value")
        next_func.assert_called_once_with(None, info)

    def test_resolve_passes_kwargs_to_next(self) -> None:
        """Extra keyword arguments given to "resolve" reach the wrapped "next" call.

        This test breaks if the middleware stops forwarding resolver
        keyword arguments to the next callable in the chain.
        """
        next_func = Mock(return_value="value")
        info = Mock()
        field = Mock()
        field.directives = []
        info.field_nodes = [field]

        result = self.middleware.resolve(next_func, None, info, custom_arg="test")

        self.assertEqual(result, "value")
        next_func.assert_called_once_with(None, info, custom_arg="test")

    def test_resolve_preserves_resolver_context(self) -> None:
        """The "root" value passed to "resolve" reaches the wrapped resolver.

        This test breaks if the middleware stops forwarding "root" to the
        next callable, breaking access to resolver context.
        """

        def resolver(root: Any, info: Any, **kwargs: Any) -> str:
            """Return a string embedding the root value it was called with."""
            return "root:{}".format(root)

        info = Mock()
        field = Mock()
        field.directives = []
        info.field_nodes = [field]

        result = self.middleware.resolve(resolver, "the_root", info)
        self.assertEqual(result, "root:the_root")
