# -*- coding: utf-8 -*-
"""Query depth limiting (`max_deep` / MAX_QUERY_DEPTH) via DepthLimitValidationRule."""

from types import SimpleNamespace

from django.test import TestCase, override_settings
from graphql import (
    GraphQLField,
    GraphQLList,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)

from django_graphex import (
    DepthLimitValidationRule,
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)
from django_graphex.registry import get_global_registry
from django_graphex.views import GraphQLView
from tests.models import Author, UUIDItem


def _build_schema(node_max_deep=None, inner_max_deep=None):
    """A self-referential Node (optionally wrapping an Inner) for depth tests."""
    inner = GraphQLObjectType(
        "Inner",
        lambda: {"name": GraphQLField(GraphQLString), "inner": GraphQLField(inner)},
    )
    if inner_max_deep is not None:
        inner.graphene_type = SimpleNamespace(
            _meta=SimpleNamespace(max_deep=inner_max_deep)
        )

    node = GraphQLObjectType(
        "Node",
        lambda: {
            "name": GraphQLField(GraphQLString),
            "child": GraphQLField(node),
            "siblings": GraphQLField(GraphQLList(node)),
            "inner": GraphQLField(inner),
        },
    )
    if node_max_deep is not None:
        node.graphene_type = SimpleNamespace(
            _meta=SimpleNamespace(max_deep=node_max_deep)
        )

    query = GraphQLObjectType("Query", {"root": GraphQLField(node)})
    return GraphQLSchema(query=query, types=[node, inner])


def _errors(schema, query):
    return [
        e.message for e in validate(schema, parse(query), [DepthLimitValidationRule])
    ]


class DepthRuleTest(TestCase):
    def test_within_limit_passes(self):
        schema = _build_schema(node_max_deep=2)
        self.assertEqual(_errors(schema, "{ root { child { child { name } } } }"), [])

    def test_exceeding_per_type_limit_errors(self):
        schema = _build_schema(node_max_deep=2)
        errors = _errors(schema, "{ root { child { child { child { name } } } } }")
        self.assertEqual(len(errors), 1)
        self.assertIn("maximum nesting depth of 2", errors[0])

    def test_scalars_do_not_count(self):
        schema = _build_schema(node_max_deep=1)
        # Wide but shallow: many scalars at one level -> fine.
        self.assertEqual(_errors(schema, "{ root { name child { name } } }"), [])

    def test_max_deep_zero_blocks_any_nesting(self):
        schema = _build_schema(node_max_deep=0)
        self.assertEqual(_errors(schema, "{ root { name } }"), [])
        self.assertEqual(len(_errors(schema, "{ root { child { name } } }")), 1)

    def test_fragment_spread_does_not_bypass(self):
        schema = _build_schema(node_max_deep=2)
        query = (
            "{ root { ...F } } "
            "fragment F on Node { child { child { child { name } } } }"
        )
        self.assertEqual(len(_errors(schema, query)), 1)

    def test_inline_fragment_is_counted(self):
        schema = _build_schema(node_max_deep=2)
        query = "{ root { ... on Node { child { child { child { name } } } } } }"
        self.assertEqual(len(_errors(schema, query)), 1)

    def test_most_restrictive_constraint_wins(self):
        # Outer is generous (10) but Inner is strict (1).
        schema = _build_schema(node_max_deep=10, inner_max_deep=1)
        ok = "{ root { inner { inner { name } } } }"  # 1 level below first Inner
        bad = "{ root { inner { inner { inner { name } } } } }"
        self.assertEqual(_errors(schema, ok), [])
        self.assertEqual(len(_errors(schema, bad)), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
    def test_global_default_from_setting(self):
        schema = _build_schema()  # no per-type limit
        self.assertEqual(_errors(schema, "{ root { child { name } } }"), [])
        self.assertEqual(
            len(_errors(schema, "{ root { child { child { name } } } }")), 1
        )

    def test_no_limit_configured_is_noop(self):
        schema = _build_schema()  # no per-type, no global
        deep = "{ root { child { child { child { child { name } } } } } }"
        self.assertEqual(_errors(schema, deep), [])


class MaxDeepWiringTest(TestCase):
    def test_object_type_stores_max_deep(self):
        class _AuthorType(DjangoObjectType):
            class Meta:
                model = Author
                max_deep = 3

        self.assertEqual(_AuthorType._meta.max_deep, 3)

    def test_list_type_stores_max_deep(self):
        class _AuthorList(DjangoListObjectType):
            class Meta:
                model = Author
                max_deep = 4

        self.assertEqual(_AuthorList._meta.max_deep, 4)

    def test_serializer_type_forwards_max_deep_to_output_type(self):
        # Ensure a fresh output type is generated (carrying our max_deep).
        reg = get_global_registry()
        reg._types.pop((UUIDItem, None), None)
        reg._list_types.pop(UUIDItem, None)

        class _ItemType(DjangoModelType):
            class Meta:
                model = UUIDItem
                max_deep = 2

        self.assertEqual(_ItemType._meta.max_deep, 2)
        self.assertEqual(_ItemType._meta.output_type._meta.max_deep, 2)


class ViewWiringTest(TestCase):
    def test_view_includes_depth_rule_with_standard_rules(self):
        rules = GraphQLView.validation_rules
        self.assertIn(DepthLimitValidationRule, rules)
        # The standard rules are still present (not replaced).
        self.assertGreater(len(rules), 1)
