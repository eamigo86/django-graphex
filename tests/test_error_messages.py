# -*- coding: utf-8 -*-
"""Consistent error messages, codes and typed config errors (area 3)."""

from types import SimpleNamespace

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLInt,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)

from django_graphex.cost import CostLimitValidationRule
from django_graphex.types import DjangoModelType
from django_graphex.utils import not_found_error
from django_graphex.validation import DepthLimitValidationRule
from tests.models import Author, ErrMsgDeleteModel


class NotFoundMessageTest(TestCase):
    """Tests covering the shared "not found" error-message helper.

    Verifies both the standalone helper and the delete mutation that reuses it.
    """

    def test_helper_format(self) -> None:
        """ "not_found_error" must format a single "does not exist" GraphQLError.

        If this breaks, callers relying on "not_found_error" for a consistent
        not-found message (field "id", one error) get a malformed error list.
        """
        errors = not_found_error(Author, 42)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].field, "id")
        self.assertEqual(errors[0].messages, ["Author with id 42 does not exist."])

    def test_delete_missing_object_uses_helper_message(self) -> None:
        """The generated "delete" mutation must reuse the not-found helper message.

        If this breaks, deleting a missing object returns an inconsistent or
        unhelpful error instead of the standard "does not exist" message.
        """

        class _ErrMsgDeleteType(DjangoModelType):
            """Minimal DjangoModelType over a dedicated model for the delete test.

            Uses ErrMsgDeleteModel (relation-free, unique to this module) rather
            than a shared model: DjangoModelType always self-registers on the
            GLOBAL registry (it rejects Meta.registry), so wrapping a shared model
            here would auto-derive globally-named companion list types that
            collide with same-named types other test modules build.
            """

            class Meta:
                model = ErrMsgDeleteModel

        info = SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))
        result = _ErrMsgDeleteType.delete(None, info, id=999)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].field, "id")
        self.assertIn("does not exist", result.errors[0].messages[0])


class ErrorCodeTest(TestCase):
    """Tests asserting that validation errors carry a stable "code" extension.

    Covers both the depth-limit and cost-limit validation rules.
    """

    def test_depth_error_carries_code(self) -> None:
        """Depth-limit validation errors must carry the "QUERY_TOO_DEEP" code.

        If this breaks, clients that branch on "extensions.code" can no longer
        distinguish a depth-limit rejection from other validation failures.
        """
        node = GraphQLObjectType(
            "Node",
            lambda: {"name": GraphQLField(GraphQLString), "child": GraphQLField(node)},
        )
        node.graphene_type = SimpleNamespace(_meta=SimpleNamespace(max_depth=1))
        schema = GraphQLSchema(
            query=GraphQLObjectType("Query", {"root": GraphQLField(node)}),
            types=[node],
        )
        errors = validate(
            schema,
            parse("{ root { child { child { name } } } }"),
            [DepthLimitValidationRule],
        )
        self.assertEqual(errors[0].extensions.get("code"), "QUERY_TOO_DEEP")

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_COST": 1, "MAX_PAGE_SIZE": 100})
    def test_cost_error_carries_code(self) -> None:
        """Cost-limit validation errors must carry the "QUERY_TOO_COMPLEX" code.

        If this breaks, clients that branch on "extensions.code" can no longer
        distinguish a cost-limit rejection from other validation failures.
        """
        owner = GraphQLObjectType("Owner", {"name": GraphQLField(GraphQLString)})
        item = GraphQLObjectType("Item", {"owner": GraphQLField(owner)})
        schema = GraphQLSchema(
            query=GraphQLObjectType(
                "Query",
                {
                    "items": GraphQLField(
                        GraphQLList(item),
                        args={"limit": GraphQLArgument(GraphQLInt)},
                    )
                },
            ),
            types=[item, owner],
        )
        # cost = 1 + 50 * (owner=1) = 51 > 1
        errors = validate(
            schema,
            parse("{ items(limit: 50) { owner { name } } }"),
            [CostLimitValidationRule],
        )
        self.assertEqual(errors[0].extensions.get("code"), "QUERY_TOO_COMPLEX")


class ConfigErrorTest(TestCase):
    """Tests asserting that misconfigured DjangoModelType subclasses fail loudly.

    A missing "model" Meta option must raise ImproperlyConfigured rather than
    fail later with a confusing error.
    """

    def test_missing_model_raises_improperly_configured(self) -> None:
        """A DjangoModelType subclass without "model" in Meta must raise.

        If this breaks, a misconfigured type definition would fail later with
        an obscure error instead of a clear ImproperlyConfigured at class
        creation time.
        """
        with self.assertRaises(ImproperlyConfigured):

            class _Broken(DjangoModelType):
                """Deliberately misconfigured type used to trigger the error."""

                class Meta:
                    model = None
