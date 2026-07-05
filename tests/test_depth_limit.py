# -*- coding: utf-8 -*-
"""Query depth limiting ("max_depth" / MAX_QUERY_DEPTH) via DepthLimitValidationRule."""

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

from django_graphex.registry import get_global_registry
from django_graphex.types import DjangoListObjectType, DjangoModelType, DjangoObjectType
from django_graphex.validation import DepthLimitValidationRule
from django_graphex.views import GraphQLView
from tests.models import Author, UUIDItem


def _build_schema(
    node_max_depth: int | None = None, inner_max_depth: int | None = None
) -> GraphQLSchema:
    """Build a self-referential Node (optionally wrapping an Inner) for depth tests.

    Args:
        node_max_depth: When given, attaches a "max_depth" meta marker to the
            "Node" type.
        inner_max_depth: When given, attaches a "max_depth" meta marker to the
            "Inner" type.

    Returns:
        schema: The constructed GraphQLSchema with a "root" query field of
            type "Node".
    """
    inner = GraphQLObjectType(
        "Inner",
        lambda: {"name": GraphQLField(GraphQLString), "inner": GraphQLField(inner)},
    )
    if inner_max_depth is not None:
        inner.graphene_type = SimpleNamespace(
            _meta=SimpleNamespace(max_depth=inner_max_depth)
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
    if node_max_depth is not None:
        node.graphene_type = SimpleNamespace(
            _meta=SimpleNamespace(max_depth=node_max_depth)
        )

    query = GraphQLObjectType("Query", {"root": GraphQLField(node)})
    return GraphQLSchema(query=query, types=[node, inner])


def _errors(schema: GraphQLSchema, query: str) -> list[str]:
    """Validate a query string against a schema using only the depth-limit rule.

    Args:
        schema: The schema to validate against.
        query: The raw GraphQL query text to parse and validate.

    Returns:
        messages: The error messages produced by "DepthLimitValidationRule".
    """
    return [
        e.message for e in validate(schema, parse(query), [DepthLimitValidationRule])
    ]


class DepthRuleTest(TestCase):
    """Behavioral coverage of "DepthLimitValidationRule" against various query shapes.

    Exercises per-type limits, the global default, fragments, and the
    no-limit-configured no-op case.
    """

    def test_within_limit_passes(self) -> None:
        """A query nested exactly to the per-type "max_depth" must pass validation.

        If this breaks, valid queries at the configured depth limit would be
        wrongly rejected.
        """
        schema = _build_schema(node_max_depth=2)
        self.assertEqual(_errors(schema, "{ root { child { child { name } } } }"), [])

    def test_exceeding_per_type_limit_errors(self) -> None:
        """A query one level beyond the per-type "max_depth" must produce exactly one error.

        If this breaks, over-depth queries could slip past validation and
        reach execution.
        """
        schema = _build_schema(node_max_depth=2)
        errors = _errors(schema, "{ root { child { child { child { name } } } } }")
        self.assertEqual(len(errors), 1)
        self.assertIn("maximum nesting depth of 2", errors[0])

    def test_scalars_do_not_count(self) -> None:
        """Multiple scalar leaves at the same level must not add extra depth.

        If this breaks, wide-but-shallow queries could be wrongly rejected
        as if each sibling scalar added its own nesting level.
        """
        schema = _build_schema(node_max_depth=1)
        # Wide but shallow: many scalars at one level -> fine.
        self.assertEqual(_errors(schema, "{ root { name child { name } } }"), [])

    def test_max_depth_zero_blocks_any_nesting(self) -> None:
        """A "max_depth" of zero must allow the root selection but block any nested field.

        If this breaks, a max_depth of 0 could be treated as "no limit"
        instead of forbidding all nesting.
        """
        schema = _build_schema(node_max_depth=0)
        self.assertEqual(_errors(schema, "{ root { name } }"), [])
        self.assertEqual(len(_errors(schema, "{ root { child { name } } }")), 1)

    def test_fragment_spread_does_not_bypass(self) -> None:
        """Depth added through a named fragment spread must still count toward the limit.

        If this breaks, a query could bypass the depth limit entirely by
        moving deep nesting into a fragment.
        """
        schema = _build_schema(node_max_depth=2)
        query = (
            "{ root { ...F } } "
            "fragment F on Node { child { child { child { name } } } }"
        )
        self.assertEqual(len(_errors(schema, query)), 1)

    def test_inline_fragment_is_counted(self) -> None:
        """Depth added through a typed inline fragment must still count toward the limit.

        If this breaks, a query could bypass the depth limit by nesting
        fields inside an inline fragment instead of directly.
        """
        schema = _build_schema(node_max_depth=2)
        query = "{ root { ... on Node { child { child { child { name } } } } } }"
        self.assertEqual(len(_errors(schema, query)), 1)

    def test_most_restrictive_constraint_wins(self) -> None:
        """When nested types have different "max_depth" values, the stricter one must apply at its boundary.

        If this breaks, a strict inner-type limit could be overridden by a
        looser outer-type limit instead of being enforced independently.
        """
        # Outer is generous (10) but Inner is strict (1).
        schema = _build_schema(node_max_depth=10, inner_max_depth=1)
        ok = "{ root { inner { inner { name } } } }"  # 1 level below first Inner
        bad = "{ root { inner { inner { inner { name } } } } }"
        self.assertEqual(_errors(schema, ok), [])
        self.assertEqual(len(_errors(schema, bad)), 1)

    @override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
    def test_global_default_from_setting(self) -> None:
        """The global MAX_QUERY_DEPTH setting must apply when no type declares its own "max_depth".

        If this breaks, types without an explicit max_depth could bypass
        depth limiting entirely instead of falling back to the global setting.
        """
        schema = _build_schema()  # no per-type limit
        self.assertEqual(_errors(schema, "{ root { child { name } } }"), [])
        self.assertEqual(
            len(_errors(schema, "{ root { child { child { name } } } }")), 1
        )

    def test_no_limit_configured_is_noop(self) -> None:
        """With no per-type or global depth limit configured, arbitrarily deep queries must pass.

        If this breaks, the depth-limit rule could reject queries even when
        no limit was ever configured.
        """
        schema = _build_schema()  # no per-type, no global
        deep = "{ root { child { child { child { child { name } } } } } }"
        self.assertEqual(_errors(schema, deep), [])


class MaxDeepWiringTest(TestCase):
    """Coverage that a "max_depth" Meta option is stored on the "_meta" of each type flavor.

    Checks "DjangoObjectType", "DjangoListObjectType", and the
    serializer-backed "DjangoModelType" (including forwarding to its
    generated output type).
    """

    def test_object_type_stores_max_depth(self) -> None:
        """A "max_depth" Meta option on "DjangoObjectType" must be stored on "_meta".

        If this breaks, per-type depth limits declared via Meta would be
        silently dropped instead of reaching the validation rule.
        """

        class _AuthorType(DjangoObjectType):
            """Local test type carrying an explicit "max_depth" Meta option."""

            class Meta:
                """Meta options binding this type to "Author" with a depth limit."""

                model = Author
                max_depth = 3

        self.assertEqual(_AuthorType._meta.max_depth, 3)

    def test_list_type_stores_max_depth(self) -> None:
        """A "max_depth" Meta option on "DjangoListObjectType" must be stored on "_meta".

        If this breaks, list types could not declare their own depth limit
        independent of the underlying object type.
        """

        class _AuthorList(DjangoListObjectType):
            """Local test list type carrying an explicit "max_depth" Meta option."""

            class Meta:
                """Meta options binding this list type to "Author" with a depth limit."""

                model = Author
                max_depth = 4

        self.assertEqual(_AuthorList._meta.max_depth, 4)

    def test_serializer_type_forwards_max_depth_to_output_type(self) -> None:
        """A "DjangoModelType" must forward its "max_depth" to the generated output type.

        If this breaks, the depth limit declared on a serializer-backed type
        would not propagate to the object type actually used by the schema.
        """
        # Ensure a fresh output type is generated (carrying our max_depth).
        reg = get_global_registry()
        reg._types.pop((UUIDItem, None), None)
        reg._list_types.pop(UUIDItem, None)

        class _ItemType(DjangoModelType):
            """Local test serializer-backed type carrying an explicit "max_depth" option."""

            class Meta:
                """Meta options binding this type to "UUIDItem" with a depth limit."""

                model = UUIDItem
                max_depth = 2

        self.assertEqual(_ItemType._meta.max_depth, 2)
        self.assertEqual(_ItemType._meta.output_type._meta.max_depth, 2)


class ViewWiringTest(TestCase):
    """Coverage that "GraphQLView" wires the depth-limit rule into its validation rules.

    Confirms the rule is added alongside, not instead of, the standard
    GraphQL validation rules.
    """

    def test_view_includes_depth_rule_with_standard_rules(self) -> None:
        """ "GraphQLView.validation_rules" must include "DepthLimitValidationRule" alongside the standard rules.

        If this breaks, the view could either drop depth limiting entirely
        or replace the standard GraphQL validation rules instead of adding
        to them.
        """
        rules = GraphQLView.validation_rules
        self.assertIn(DepthLimitValidationRule, rules)
        # The standard rules are still present (not replaced).
        self.assertGreater(len(rules), 1)
