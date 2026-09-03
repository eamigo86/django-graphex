"""core/_args.py — graphql-core arg adapter (graphene-free, v2.0).

S-del-backend-11: the graphene backend is deleted. "_unwrap_graphql_type" now
returns a graphql-core type VERBATIM and RAISES "TypeError" for any leftover
graphene type (the v2.0 CLEAN BREAK, decision #1603). "to_graphql_argument"
is a thin adapter that wraps a graphql-core type (or passes a "GraphQLArgument"
through) into a "GraphQLArgument". These tests exercise the graphql-core
(native) inputs and the loud-fail on a graphene input.

The graphene-conversion cases ("graphene.Argument(graphene.String)" to
"GraphQLArgument") were dropped with the graphene backend; the native arg
declaration API ("native_arg") is covered by "test_native_args_only.py".

Run:
    .venv/bin/python -m pytest -q tests/core/test_args.py --no-cov
"""

from __future__ import annotations

from typing import Any, Callable

import pytest


def _converter() -> Callable[..., Any]:
    from django_graphex.core._args import to_graphql_argument

    return to_graphql_argument


# ---------------------------------------------------------------------------
# graphql-core type inputs → wrapped in a GraphQLArgument
# ---------------------------------------------------------------------------


def test_bare_graphql_scalar_wraps_as_argument() -> None:
    """Assert that a bare graphql-core scalar is wrapped in a GraphQLArgument.

    If this fails, plain graphql-core scalar types passed as an argument
    declaration would not be adapted into a usable GraphQLArgument.
    """
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    result = fn(GraphQLString)
    assert isinstance(result, GraphQLArgument)
    assert result.type is GraphQLString


def test_nonnull_wrapper_preserved() -> None:
    """Assert that a graphql-core "GraphQLNonNull(GraphQLString)" is preserved.

    If this fails, non-null wrapping would be lost or altered during
    adaptation, silently relaxing a required argument to optional.
    """
    from graphql import GraphQLArgument, GraphQLNonNull, GraphQLString

    fn = _converter()
    result = fn(GraphQLNonNull(GraphQLString))
    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLNonNull)
    assert result.type.of_type is GraphQLString


def test_list_of_nonnull_string_preserved() -> None:
    """Assert that "GraphQLList(GraphQLNonNull(GraphQLString))" is preserved as-is.

    If this fails, a list-of-non-null-string argument type would be
    flattened or altered, changing the argument's declared shape.
    """
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


def test_existing_graphql_argument_passes_through_with_attrs() -> None:
    """Assert that a "GraphQLArgument" input is adapted, preserving its type.

    If this fails, passing an already-built GraphQLArgument through the
    adapter would drop or replace its inner type.
    """
    from graphql import GraphQLArgument, GraphQLID, GraphQLNonNull

    fn = _converter()
    arg = GraphQLArgument(GraphQLNonNull(GraphQLID))
    result = fn(arg)
    assert isinstance(result, GraphQLArgument)
    assert isinstance(result.type, GraphQLNonNull)
    assert result.type.of_type is GraphQLID


def test_default_value_is_preserved() -> None:
    """Assert that "default_value" on the GraphQLArgument is propagated.

    If this fails, a declared default value would be silently dropped when
    adapting an existing GraphQLArgument.
    """
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    arg = GraphQLArgument(GraphQLString, default_value="hello")
    result = fn(arg)
    assert isinstance(result, GraphQLArgument)
    assert result.default_value == "hello"


def test_description_is_preserved() -> None:
    """Assert that "description" on the GraphQLArgument is propagated.

    If this fails, an argument's description would be lost when adapting an
    existing GraphQLArgument, degrading generated schema documentation.
    """
    from graphql import GraphQLArgument, GraphQLString

    fn = _converter()
    arg = GraphQLArgument(GraphQLString, description="A test arg")
    result = fn(arg)
    assert result.description == "A test arg"


def test_out_name_snake_case_from_camel_key() -> None:
    """Assert that "out_name" becomes the snake_case form of a camelCase key.

    If this fails, a camelCase declared argument name would not resolve to
    the matching snake_case Python kwarg, breaking resolver calls.
    """
    from graphql import GraphQLString

    from django_graphex.core._args import to_graphql_argument

    result = to_graphql_argument(GraphQLString, name="firstName")
    assert result.out_name == "first_name"


def test_out_name_snake_key_unchanged() -> None:
    """Assert that "out_name" is unchanged when the key is already snake_case.

    If this fails, an already-snake_case argument name would be mangled by
    the camelCase-to-snake_case conversion instead of passing through as-is.
    """
    from graphql import GraphQLString

    from django_graphex.core._args import to_graphql_argument

    result = to_graphql_argument(GraphQLString, name="first_name")
    assert result.out_name == "first_name"


# ---------------------------------------------------------------------------
# CLEAN BREAK — a leftover graphene type raises TypeError
# ---------------------------------------------------------------------------


def test_unwrap_raises_type_error_for_unrecognised_type() -> None:
    """Assert that "_unwrap_graphql_type" raises TypeError for a foreign type.

    If this fails, the v2.0 clean break would silently accept a leftover
    graphene (or other non-graphql-core) type instead of loudly rejecting it.
    """
    from django_graphex.core._args import _unwrap_graphql_type

    class NotAGraphQLType:
        """Has no graphql-core type identity."""

    with pytest.raises(TypeError, match="Cannot convert"):
        _unwrap_graphql_type(NotAGraphQLType())


def test_unwrap_returns_graphql_core_type_verbatim() -> None:
    """Assert that a graphql-core type is returned as-is by the unwrap helper.

    If this fails, a native graphql-core type would be altered or wrapped
    instead of passing through unchanged.
    """
    from graphql import GraphQLInt

    from django_graphex.core._args import _unwrap_graphql_type

    assert _unwrap_graphql_type(GraphQLInt) is GraphQLInt
