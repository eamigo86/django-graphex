"""native/_args.py — graphql-core arg adapter (graphene-free, v2.0).

S-del-backend-11: the graphene backend is deleted. ``_unwrap_graphene_type`` now
returns a graphql-core type VERBATIM and RAISES ``TypeError`` for any leftover
graphene type (the v2.0 CLEAN BREAK, decision #1603). ``graphene_arg_to_graphql_argument``
is a thin adapter that wraps a graphql-core type (or passes a ``GraphQLArgument``
through) into a ``GraphQLArgument``. These tests exercise the graphql-core
(native) inputs and the loud-fail on a graphene input.

The graphene-conversion cases (``graphene.Argument(graphene.String)`` →
``GraphQLArgument``) were dropped with the graphene backend; the native arg
declaration API (``native_arg``) is covered by ``test_native_args_only.py``.

Run:
    .venv/bin/python -m pytest -q tests/native/test_args.py
"""
from __future__ import annotations

import pytest


def _converter():
    from django_graphex.native._args import graphene_arg_to_graphql_argument

    return graphene_arg_to_graphql_argument


# ---------------------------------------------------------------------------
# graphql-core type inputs → wrapped in a GraphQLArgument
# ---------------------------------------------------------------------------


def test_bare_graphql_scalar_wraps_as_argument():
    """A bare graphql-core scalar is wrapped in a GraphQLArgument verbatim."""
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    result = fn(GraphQLString)
    assert isinstance(result, GraphQLArgument)
    assert result.type is GraphQLString


def test_nonnull_wrapper_preserved():
    """A graphql-core ``GraphQLNonNull(GraphQLString)`` is preserved."""
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    fn = _converter()
    result = fn(GraphQLNonNull(GraphQLString))
    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLNonNull)
    assert result.type.of_type is GraphQLString


def test_list_of_nonnull_string_preserved():
    """``GraphQLList(GraphQLNonNull(GraphQLString))`` is preserved as-is."""
    from graphql import (
        GraphQLArgument,
        GraphQLList,
        GraphQLNonNull,
        GraphQLString,
    )

    fn = _converter()
    result = fn(GraphQLList(GraphQLNonNull(GraphQLString)))
    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLList)
    assert isinstance(result.type.of_type, GraphQLNonNull)
    assert result.type.of_type.of_type is GraphQLString


def test_existing_graphql_argument_passes_through_with_attrs():
    """A ``GraphQLArgument`` input is adapted, preserving its inner type."""
    from graphql import GraphQLArgument, GraphQLID, GraphQLNonNull

    fn = _converter()
    arg = GraphQLArgument(GraphQLNonNull(GraphQLID))
    result = fn(arg)
    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLNonNull)
    assert result.type.of_type is GraphQLID


def test_default_value_is_preserved():
    """``default_value`` on the GraphQLArgument is propagated."""
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    arg = GraphQLArgument(GraphQLString, default_value="hello")
    result = fn(arg)
    assert isinstance(result, GraphQLArgument)
    assert result.default_value == "hello"


def test_description_is_preserved():
    """``description`` on the GraphQLArgument is propagated."""
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    arg = GraphQLArgument(GraphQLString, description="A test arg")
    result = fn(arg)
    assert result.description == "A test arg"


def test_out_name_snake_case_from_camel_key():
    """``out_name`` is the snake_case form of a camelCase declared key."""
    from graphql import GraphQLString

    from django_graphex.native._args import graphene_arg_to_graphql_argument

    result = graphene_arg_to_graphql_argument(GraphQLString, name="firstName")
    assert result.out_name == "first_name"


def test_out_name_snake_key_unchanged():
    """``out_name`` stays the same when the declared key is already snake_case."""
    from graphql import GraphQLString

    from django_graphex.native._args import graphene_arg_to_graphql_argument

    result = graphene_arg_to_graphql_argument(GraphQLString, name="first_name")
    assert result.out_name == "first_name"


# ---------------------------------------------------------------------------
# CLEAN BREAK — a leftover graphene type raises TypeError
# ---------------------------------------------------------------------------


def test_unwrap_raises_type_error_for_unrecognised_type():
    """``_unwrap_graphene_type`` raises TypeError for a non-graphql-core type."""
    from django_graphex.native._args import _unwrap_graphene_type

    class NotAGraphQLType:
        """Has no graphql-core type identity."""

    with pytest.raises(TypeError, match="Cannot convert"):
        _unwrap_graphene_type(NotAGraphQLType())


def test_unwrap_returns_graphql_core_type_verbatim():
    """A graphql-core type is returned as-is by ``_unwrap_graphene_type``."""
    from graphql import GraphQLInt

    from django_graphex.native._args import _unwrap_graphene_type

    assert _unwrap_graphene_type(GraphQLInt) is GraphQLInt
