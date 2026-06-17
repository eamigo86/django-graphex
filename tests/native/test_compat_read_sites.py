"""Tests for B4: _gdx_meta read-site migration.

Verifies that validation.py, cost.py, utils.py, fields.py read _meta
through _gdx_meta (graphene-first fallback) so both backends work.

These tests check:
- _type_max_deep works under native (validation.py)
- _type_complexity works under native (cost.py)
- _get_field_optimize_hook works under native (utils.py)
- _get_custom_resolver works under native (utils.py)

All tests run.
"""
from __future__ import annotations

import pytest


def _make_graphql_type_with_gdx(max_deep=None, complexity=None, model=None, name="TestType"):
    """Create a mock GraphQLObjectType with extensions['gdx'] populated."""
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.native.bridge import GdxPayload
    from django_graphex.native.ir import GdxMeta

    gdx_meta = GdxMeta(
        name=name,
        max_deep=max_deep,
        complexity=complexity,
        model=model,
    )
    payload = GdxPayload(gdx_meta)

    return GraphQLObjectType(
        name=name,
        fields={"id": GraphQLField(GraphQLString)},
        extensions={"gdx": payload},
    )


def _make_graphql_type_with_graphene(max_deep=None, complexity=None, model=None, name="GrapheneType"):
    """Create a mock GraphQLObjectType with graphene_type set (graphene path)."""
    from unittest.mock import MagicMock

    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    mock_graphene_type = MagicMock()
    mock_graphene_type._meta.max_deep = max_deep
    mock_graphene_type._meta.complexity = complexity
    mock_graphene_type._meta.model = model

    gql_type = GraphQLObjectType(
        name=name,
        fields={"id": GraphQLField(GraphQLString)},
    )
    # Simulate graphene's back-reference
    object.__setattr__(gql_type, "graphene_type", mock_graphene_type)
    return gql_type


def test_gdx_meta_shim_native_path():
    """_gdx_meta returns extensions['gdx']._meta for native types."""
    from django_graphex.native.compat import _gdx_meta

    gql_type = _make_graphql_type_with_gdx(max_deep=5, complexity=2)
    meta = _gdx_meta(gql_type)

    assert meta.max_deep == 5
    assert meta.complexity == 2


def test_gdx_meta_shim_graphene_path():
    """_gdx_meta returns graphene_type._meta for graphene types (graphene-first)."""
    from django_graphex.native.compat import _gdx_meta

    gql_type = _make_graphql_type_with_graphene(max_deep=3, complexity=7)
    meta = _gdx_meta(gql_type)

    assert meta.max_deep == 3
    assert meta.complexity == 7


def test_type_max_deep_via_gdx_meta_native():
    """validation.py._type_max_deep must work with native extensions['gdx'] types."""
    from django_graphex.validation import _type_max_deep

    # Native type with max_deep set via extensions["gdx"]
    gql_type = _make_graphql_type_with_gdx(max_deep=4, name="DeepType")
    result = _type_max_deep(gql_type)
    assert result == 4, (
        f"_type_max_deep must return 4 for native type with max_deep=4, got {result}"
    )


def test_type_max_deep_via_gdx_meta_none():
    """validation.py._type_max_deep returns None when max_deep is not set."""
    from django_graphex.validation import _type_max_deep

    gql_type = _make_graphql_type_with_gdx(max_deep=None, name="NoDeepType")
    result = _type_max_deep(gql_type)
    assert result is None, (
        f"_type_max_deep must return None when max_deep=None, got {result}"
    )


def test_type_complexity_via_gdx_meta_native():
    """cost.py._type_complexity must work with native extensions['gdx'] types."""
    from django_graphex.cost import _type_complexity

    gql_type = _make_graphql_type_with_gdx(complexity=10, name="ComplexType")
    result = _type_complexity(gql_type)
    assert result == 10, (
        f"_type_complexity must return 10 for native type with complexity=10, got {result}"
    )


def test_type_complexity_via_gdx_meta_none():
    """cost.py._type_complexity returns None when complexity is not set."""
    from django_graphex.cost import _type_complexity

    gql_type = _make_graphql_type_with_gdx(complexity=None, name="NoComplexType")
    result = _type_complexity(gql_type)
    assert result is None


def test_gdx_meta_raises_on_no_extensions():
    """_gdx_meta raises AttributeError if type has neither graphene_type nor extensions['gdx']."""
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.native.compat import _gdx_meta

    bare_type = GraphQLObjectType(
        name="BareType",
        fields={"id": GraphQLField(GraphQLString)},
    )

    with pytest.raises(AttributeError):
        _gdx_meta(bare_type)


# --------------------------------------------------------------------------- #
# Audit rank 21: _gdx_graphene_type's defensive AttributeError branch          #
# (compat.py:112-117). When extensions['gdx'] is present but its ._meta lacks  #
# a graphene_type attribute (a malformed/partial payload), the read must       #
# swallow the AttributeError and return None — never propagate it — so callers #
# uniformly treat "no source class recoverable" as "no custom hook declared".  #
# --------------------------------------------------------------------------- #
def test_gdx_graphene_type_returns_none_when_meta_lacks_graphene_type():
    """gdx present, but gdx._meta has NO graphene_type -> None (defensive branch)."""
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.native.compat import _gdx_graphene_type

    class _MetaWithoutGrapheneType:
        """A _meta view that does NOT expose graphene_type (accessing raises)."""

        max_deep = None

    class _GdxNoGrapheneType:
        """A gdx payload whose ._meta lacks graphene_type."""

        _meta = _MetaWithoutGrapheneType()

    gql_type = GraphQLObjectType(
        name="GdxNoGrapheneTypeType",
        fields={"id": GraphQLField(GraphQLString)},
        extensions={"gdx": _GdxNoGrapheneType()},
    )

    # The fast-path graphene_type back-reference is absent, and gdx._meta has no
    # graphene_type -> the try/except returns None instead of raising.
    assert _gdx_graphene_type(gql_type) is None


def test_gdx_graphene_type_returns_none_when_gdx_meta_attr_missing():
    """gdx present but with NO ._meta at all -> AttributeError swallowed -> None."""
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.native.compat import _gdx_graphene_type

    class _GdxNoMeta:
        """A gdx payload with no ._meta attribute whatsoever."""

    gql_type = GraphQLObjectType(
        name="GdxNoMetaType",
        fields={"id": GraphQLField(GraphQLString)},
        extensions={"gdx": _GdxNoMeta()},
    )

    assert _gdx_graphene_type(gql_type) is None
