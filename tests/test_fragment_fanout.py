# -*- coding: utf-8 -*-
"""Fragment fan-out hardening for "DepthLimitValidationRule" / "CostLimitValidationRule".

A document whose fragments each spread the next one twice describes a binary
tree of size 2**n with a sub-kilobyte body. Both walkers used to re-walk every
reachable path, so validation cost was exponential in the document length and
an unauthenticated request could pin a worker. These tests pin the memoized
behavior: bounded time, and unchanged depth/cost semantics.
"""

from __future__ import annotations

import time

from django.test import override_settings
from graphql import (
    GraphQLField,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    parse,
    validate,
)

from django_graphex.cost import CostLimitValidationRule, analyze_cost
from django_graphex.validation import DepthLimitValidationRule


def _schema() -> GraphQLSchema:
    """Build a self-referencing schema for fragment fan-out documents.

    Returns:
        schema: A schema exposing "Query.root" of a "Node" type that carries a
            scalar "name" and a self-referencing "child".
    """
    node = GraphQLObjectType(
        "Node",
        lambda: {
            "name": GraphQLField(GraphQLString),
            "child": GraphQLField(node),
        },
    )
    query = GraphQLObjectType("Query", {"root": GraphQLField(node)})
    return GraphQLSchema(query=query, types=[node])


def _fanout_document(levels: int) -> str:
    """Build the fan-out document: each fragment spreads the next one twice.

    Args:
        levels: The number of fan-out fragments; the described selection tree
            has 2**levels leaves.

    Returns:
        document: The raw GraphQL document text.
    """
    fragments = "\n".join(
        "fragment F{i} on Node {{ child {{ ...F{n} }} child {{ ...F{n} }} }}".format(
            i=i, n=i + 1
        )
        for i in range(levels)
    )
    return (
        "{{ root {{ ...F0 }} }}\n{fragments}\nfragment F{levels} on Node {{ name }}"
    ).format(fragments=fragments, levels=levels)


@override_settings(
    DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 100, "MAX_QUERY_COST": 10**9},
)
def test_fragment_fanout_validates_in_bounded_time() -> None:
    """A 22-level fan-out document must validate in well under a second.

    Both limits are configured far above what the document needs, so neither
    rule short-circuits on an error and both walk the whole tree. Before
    memoization this took about twelve seconds for a document of roughly one
    kilobyte. The two-second ceiling is a deliberately loose margin: the
    memoized walk runs in single-digit milliseconds, so a loaded CI runner has
    two orders of magnitude of headroom before this test turns flaky, while
    still failing hard if the exponential behavior comes back.
    """
    document = parse(_fanout_document(22))
    assert len(document.loc.source.body) < 2000  # sub-kilobyte attack surface

    start = time.perf_counter()
    errors = validate(
        _schema(),
        document,
        [DepthLimitValidationRule, CostLimitValidationRule],
    )
    elapsed = time.perf_counter() - start

    assert errors == []
    assert elapsed < 2.0, "fragment fan-out validation took {0:.2f}s".format(elapsed)


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 50, "MAX_QUERY_COST": 10**9})
def test_cyclic_fragment_still_terminates_and_reports_as_before() -> None:
    """A self-spreading fragment must still terminate and report as it did before.

    Memoization must not cache a result that was truncated by the cycle guard,
    and the cycle guard itself must still stop the recursion. Spreading the
    cyclic fragment twice exercises exactly that interaction.
    """
    query = (
        "{ root { ...F child { ...F } } } fragment F on Node { name child { ...F } }"
    )
    schema = _schema()
    errors = validate(
        schema, parse(query), [DepthLimitValidationRule, CostLimitValidationRule]
    )

    assert all(
        "nesting depth" not in e.message and "exceeds the maximum" not in e.message
        for e in errors
    )
    # own(root)=1 + [F: own(child)=1] + [child: own=1 + F: own(child)=1] -> 4.
    assert analyze_cost(schema, parse(query)).total == 4


def test_repeated_fragment_spread_counts_twice_in_cost() -> None:
    """The second spread of a fragment must still contribute its full cost.

    Memoizing a fragment's cost must reuse the computed value, never
    deduplicate the contribution away.
    """
    once = "{ root { ...F } } fragment F on Node { child { name } }"
    twice = "{ root { ...F ...F } } fragment F on Node { child { name } }"
    schema = _schema()

    # own(root)=1 + own(child)=1 -> 2; the second spread adds its own child.
    assert analyze_cost(schema, parse(once)).total == 2
    assert analyze_cost(schema, parse(twice)).total == 3


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 4})
def test_repeated_fragment_spread_still_errors_at_the_deeper_position() -> None:
    """The same fragment spread deeper must still be checked against the budget.

    The first spread sits at depth 1 and fits the budget; the second sits at
    depth 3 and blows it. A memo keyed only on the fragment name would treat
    the second spread as already proven safe and let the query through.
    """
    query = (
        "{ root { ...F child { child { ...F } } } } "
        "fragment F on Node { child { child { name } } }"
    )
    errors = [
        e.message for e in validate(_schema(), parse(query), [DepthLimitValidationRule])
    ]
    assert len(errors) == 1
    assert "maximum nesting depth of 4" in errors[0]


@override_settings(DJANGO_GRAPHEX={"MAX_QUERY_DEPTH": 2})
def test_known_depth_and_cost_values_are_unchanged() -> None:
    """Pin one known depth verdict and one known cost total against regressions.

    These are the oracle for the memoization change: the reported values must
    be byte-for-byte what the un-memoized walkers produced.
    """
    schema = _schema()
    errors = [
        e.message
        for e in validate(
            schema,
            parse("{ root { child { child { child { name } } } } }"),
            [DepthLimitValidationRule],
        )
    ]
    assert errors == ["Query exceeds the maximum nesting depth of 2 for 'query'."]

    # own(root) + own(child) + own(child) = 3; the scalar leaf is free.
    document = parse("{ root { child { child { name } } } }")
    assert analyze_cost(schema, document).total == 3
