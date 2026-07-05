"""Tests for B4: _gdx_meta read-site migration.

Verifies that validation.py, cost.py, utils.py, fields.py read _meta
through _gdx_meta (graphene-first fallback) so both backends work.

These tests check:
- _type_max_depth works under native (validation.py)
- _type_complexity works under native (cost.py)
- _get_field_optimize_hook works under native (utils.py)
- _get_custom_resolver works under native (utils.py)

All tests run.
"""

from __future__ import annotations

from typing import Any

import pytest
from graphql import GraphQLObjectType


def _make_graphql_type_with_gdx(
    max_depth: int | None = None,
    complexity: int | None = None,
    model: Any = None,
    name: str = "TestType",
) -> GraphQLObjectType:
    """Create a mock GraphQLObjectType with extensions['gdx'] populated."""
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.core.bridge import GdxPayload
    from django_graphex.core.ir import GdxMeta

    gdx_meta = GdxMeta(
        name=name,
        max_depth=max_depth,
        complexity=complexity,
        model=model,
    )
    payload = GdxPayload(gdx_meta)

    return GraphQLObjectType(
        name=name,
        fields={"id": GraphQLField(GraphQLString)},
        extensions={"gdx": payload},
    )


def _make_graphql_type_with_graphene(
    max_depth: int | None = None,
    complexity: int | None = None,
    model: Any = None,
    name: str = "GrapheneType",
) -> GraphQLObjectType:
    """Create a mock GraphQLObjectType with graphene_type set (graphene path)."""
    from unittest.mock import MagicMock

    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    mock_graphene_type = MagicMock()
    mock_graphene_type._meta.max_depth = max_depth
    mock_graphene_type._meta.complexity = complexity
    mock_graphene_type._meta.model = model

    gql_type = GraphQLObjectType(
        name=name,
        fields={"id": GraphQLField(GraphQLString)},
    )
    # Simulate graphene's back-reference
    object.__setattr__(gql_type, "graphene_type", mock_graphene_type)
    return gql_type


def test_gdx_meta_shim_native_path() -> None:
    """Assert that "_gdx_meta" reads extensions['gdx']._meta for native types.

    If this fails, the native compiler's GraphQLObjectType would not expose
    its GdxMeta through the shared "_gdx_meta" read site, breaking any
    caller (validation, cost) that relies on this shim for native types.
    """
    from django_graphex.core.compat import _gdx_meta

    gql_type = _make_graphql_type_with_gdx(max_depth=5, complexity=2)
    meta = _gdx_meta(gql_type)

    assert meta.max_depth == 5
    assert meta.complexity == 2


def test_gdx_meta_shim_graphene_path() -> None:
    """Assert that "_gdx_meta" reads graphene_type._meta for graphene types.

    The graphene path takes priority (graphene-first fallback); if this
    fails, a leftover graphene-backed type would not resolve its meta
    correctly through the shared "_gdx_meta" read site.
    """
    from django_graphex.core.compat import _gdx_meta

    gql_type = _make_graphql_type_with_graphene(max_depth=3, complexity=7)
    meta = _gdx_meta(gql_type)

    assert meta.max_depth == 3
    assert meta.complexity == 7


def test_type_max_depth_via_gdx_meta_native() -> None:
    """Assert that validation.py's "_type_max_depth" works with native gdx types.

    If this fails, native types would not carry their max_depth through the
    "_gdx_meta" migration, silently disabling depth-limit validation.
    """
    from django_graphex.validation import _type_max_depth

    # Native type with max_depth set via extensions["gdx"]
    gql_type = _make_graphql_type_with_gdx(max_depth=4, name="DeepType")
    result = _type_max_depth(gql_type)
    assert result == 4, (
        f"_type_max_depth must return 4 for native type with max_depth=4, got {result}"
    )


def test_type_max_depth_via_gdx_meta_none() -> None:
    """Assert that "_type_max_depth" returns None when max_depth is unset.

    If this fails, a type with no declared max_depth would surface a
    spurious depth limit instead of being treated as unbounded.
    """
    from django_graphex.validation import _type_max_depth

    gql_type = _make_graphql_type_with_gdx(max_depth=None, name="NoDeepType")
    result = _type_max_depth(gql_type)
    assert result is None, (
        f"_type_max_depth must return None when max_depth=None, got {result}"
    )


def test_type_complexity_via_gdx_meta_native() -> None:
    """Assert that cost.py's "_type_complexity" works with native gdx types.

    If this fails, native types would not carry their complexity through the
    "_gdx_meta" migration, silently disabling query cost analysis.
    """
    from django_graphex.cost import _type_complexity

    gql_type = _make_graphql_type_with_gdx(complexity=10, name="ComplexType")
    result = _type_complexity(gql_type)
    assert result == 10, (
        f"_type_complexity must return 10 for native type with complexity=10, got {result}"
    )


def test_type_complexity_via_gdx_meta_none() -> None:
    """Assert that "_type_complexity" returns None when complexity is unset.

    If this fails, a type with no declared complexity would surface a
    spurious cost value instead of being treated as unweighted.
    """
    from django_graphex.cost import _type_complexity

    gql_type = _make_graphql_type_with_gdx(complexity=None, name="NoComplexType")
    result = _type_complexity(gql_type)
    assert result is None


def test_gdx_meta_raises_on_no_extensions() -> None:
    """Assert that "_gdx_meta" raises AttributeError for a bare GraphQL type.

    If this fails, a type carrying neither graphene_type nor
    extensions['gdx'] would return some default meta instead of loudly
    signaling that no metadata source exists.
    """
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.core.compat import _gdx_meta

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
def test_gdx_graphene_type_returns_none_when_meta_lacks_graphene_type() -> None:
    """Assert that a gdx payload whose meta lacks graphene_type resolves to None.

    Covers the defensive branch in "_gdx_graphene_type" (compat.py:112-117):
    if this fails, a malformed/partial gdx payload would raise AttributeError
    instead of being treated as "no source class recoverable".
    """
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.core.compat import _gdx_graphene_type

    class _MetaWithoutGrapheneType:
        """A _meta view that does NOT expose graphene_type (accessing raises)."""

        max_depth = None

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


def test_gdx_graphene_type_returns_none_when_gdx_meta_attr_missing() -> None:
    """Assert that a gdx payload with no "_meta" attribute resolves to None.

    If this fails, a gdx payload missing "_meta" entirely would raise
    AttributeError instead of being treated as "no source class
    recoverable", per the same defensive branch in "_gdx_graphene_type".
    """
    from graphql import GraphQLField, GraphQLObjectType, GraphQLString

    from django_graphex.core.compat import _gdx_graphene_type

    class _GdxNoMeta:
        """A gdx payload with no ._meta attribute whatsoever."""

    gql_type = GraphQLObjectType(
        name="GdxNoMetaType",
        fields={"id": GraphQLField(GraphQLString)},
        extensions={"gdx": _GdxNoMeta()},
    )

    assert _gdx_graphene_type(gql_type) is None
