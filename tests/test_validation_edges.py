# -*- coding: utf-8 -*-
"""Remaining branch coverage for ``DepthLimitValidationRule`` (validation.py).

Covers: the non-query root with no matching root type, the unknown-field and
unresolved-type continues, the inline fragment without a type condition, and the
missing / cyclic fragment-spread guards.
"""

from types import SimpleNamespace

from django.test import override_settings
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)

from django_graphex import DepthLimitValidationRule


def _node_schema(node_max_deep=None):
    node = GraphQLObjectType(
        "Node",
        lambda: {
            "name": GraphQLField(GraphQLString),
            "child": GraphQLField(node),
        },
    )
    if node_max_deep is not None:
        node.graphene_type = SimpleNamespace(
            _meta=SimpleNamespace(max_deep=node_max_deep)
        )
    query = GraphQLObjectType("Query", {"root": GraphQLField(node)})
    return GraphQLSchema(query=query, types=[node])


def _errors(schema, query):
    return [
        e.message for e in validate(schema, parse(query), [DepthLimitValidationRule])
    ]


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 5})
def test_mutation_without_mutation_type_root_is_skipped():
    # The schema has no mutation type, so the rule's root_type is None and the
    # operation is skipped (line 101). graphql-core itself rejects the op, but
    # the depth rule must not crash.
    schema = _node_schema()
    errors = validate(schema, parse("mutation { doThing }"), [DepthLimitValidationRule])
    # No depth error contributed by our rule (it returns early).
    assert all("nesting depth" not in e.message for e in errors)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 5})
def test_unknown_field_is_skipped():
    # `bogus` is not on Node -> the walk continues past it (line 146-147).
    schema = _node_schema()
    # bogus has a selection set so it isn't a scalar leaf; the rule skips it.
    errors = _errors(schema, "{ root { bogus { name } } }")
    assert all("nesting depth" not in e for e in errors)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
def test_inline_fragment_without_type_condition_counts_no_extra_level():
    # `... { child { name } }` keeps the parent type and adds no nesting level
    # (169->176 false side).
    schema = _node_schema()
    ok = "{ root { ... { child { name } } } }"  # depth 2 -> within limit
    assert _errors(schema, ok) == []


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 5})
def test_missing_fragment_spread_is_skipped():
    # A spread of an undefined fragment is ignored (line 189-190). graphql-core
    # reports the undefined fragment, but our rule must not crash.
    schema = _node_schema()
    errors = validate(
        schema, parse("{ root { ...Ghost } }"), [DepthLimitValidationRule]
    )
    assert all("nesting depth" not in e.message for e in errors)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 50})
def test_cyclic_fragment_spread_is_guarded():
    # A fragment that spreads itself is walked once; the second encounter is
    # short-circuited by the seen-fragments guard (line 186-187). graphql-core
    # rejects the cycle, but the rule must terminate without recursing forever.
    schema = _node_schema()
    query = "{ root { ...F } } fragment F on Node { child { ...F } }"
    errors = validate(schema, parse(query), [DepthLimitValidationRule])
    # No infinite recursion; our rule contributes no depth error here.
    assert all("nesting depth" not in e.message for e in errors)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
def test_deep_error_short_circuits_remaining_siblings():
    # Once an error fires, the walk's `self._errored` guard halts further
    # recursion (line 131 + the trailing 203-204 check). A single error is
    # reported even with extra sibling selections.
    schema = _node_schema()
    query = "{ root { child { child { child { name } } child { name } } } }"
    errors = _errors(schema, query)
    assert len(errors) == 1
