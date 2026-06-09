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

from django_graphex import (
    CostLimitValidationRule,
    DepthLimitValidationRule,
    DjangoModelType,
)
from django_graphex.utils import not_found_error
from tests.models import Author


class NotFoundMessageTest(TestCase):
    def test_helper_format(self):
        errors = not_found_error(Author, 42)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].field, "id")
        self.assertEqual(errors[0].messages, ["Author with id 42 does not exist."])

    def test_delete_missing_object_uses_helper_message(self):
        class _AuthorType(DjangoModelType):
            class Meta:
                model = Author

        info = SimpleNamespace(context=SimpleNamespace(META={}, FILES={}))
        result = _AuthorType.delete(None, info, id=999)
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].field, "id")
        self.assertIn("does not exist", result.errors[0].messages[0])


class ErrorCodeTest(TestCase):
    def test_depth_error_carries_code(self):
        node = GraphQLObjectType(
            "Node",
            lambda: {"name": GraphQLField(GraphQLString), "child": GraphQLField(node)},
        )
        node.graphene_type = SimpleNamespace(_meta=SimpleNamespace(max_deep=1))
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
    def test_cost_error_carries_code(self):
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
    def test_missing_model_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):

            class _Broken(DjangoModelType):
                class Meta:
                    model = None
