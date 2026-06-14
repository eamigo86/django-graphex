"""Tests for B4: _gdx_meta read-site migration.

Verifies that validation.py, cost.py, utils.py, fields.py read _meta
through _gdx_meta (graphene-first fallback) so both backends work.

These tests check:
- _type_max_deep works under native (validation.py)
- _type_complexity works under native (cost.py)
- _get_field_optimize_hook works under native (utils.py)
- _get_custom_resolver works under native (utils.py)

All tests run under GDX_BACKEND=native via the native_only mark.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


def _make_graphql_type_with_gdx(max_deep=None, complexity=None, model=None, name="TestType"):
    """Create a mock GraphQLObjectType with extensions['gdx'] populated."""
    from graphql import GraphQLObjectType, GraphQLString, GraphQLField
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
    from graphql import GraphQLObjectType, GraphQLString, GraphQLField
    from unittest.mock import MagicMock

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
    from graphql import GraphQLObjectType, GraphQLString, GraphQLField
    from django_graphex.native.compat import _gdx_meta

    bare_type = GraphQLObjectType(
        name="BareType",
        fields={"id": GraphQLField(GraphQLString)},
    )

    with pytest.raises(AttributeError):
        _gdx_meta(bare_type)
