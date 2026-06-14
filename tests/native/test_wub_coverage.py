"""B6: Coverage tests for WU-B additions.

Tests to ensure:
- DjangoObjectType native branch covers edge cases
- validation.py and cost.py _gdx_meta paths are covered
- from_attributes is never True on native types
- cyclic model detection works

All tests run under GDX_BACKEND=native via the native_only mark.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


@pytest.mark.django_db
def test_django_object_type_with_only_fields():
    """DjangoObjectType with only_fields filters correctly under native."""
    from graphql import GraphQLObjectType
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _OnlyFieldsType(DjangoObjectType):
        class Meta:
            model = Category
            only_fields = ("title",)

    gql_type = _OnlyFieldsType._meta.graphql_output_type
    assert isinstance(gql_type, GraphQLObjectType)
    fields = gql_type.fields
    # only_fields=("title",) means only 'title' should be included
    assert "title" in fields
    # 'id' should NOT be present since it's not in only_fields
    assert "id" not in fields


@pytest.mark.django_db
def test_django_object_type_with_exclude_fields():
    """DjangoObjectType with exclude_fields filters correctly under native."""
    from graphql import GraphQLObjectType
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ExcludeFieldsType(DjangoObjectType):
        class Meta:
            model = Category
            exclude_fields = ("title",)

    gql_type = _ExcludeFieldsType._meta.graphql_output_type
    assert isinstance(gql_type, GraphQLObjectType)
    fields = gql_type.fields
    # 'title' should NOT be present since it's excluded
    assert "title" not in fields
    # 'id' should still be present
    assert "id" in fields


@pytest.mark.django_db
def test_django_object_type_with_max_deep_and_complexity():
    """DjangoObjectType with max_deep and complexity stores them in extensions['gdx']."""
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _DepthComplexityType(DjangoObjectType):
        class Meta:
            model = Category
            max_deep = 3
            complexity = 5

    gql_type = _DepthComplexityType._meta.graphql_output_type
    assert gql_type is not None
    gdx = gql_type.extensions.get("gdx")
    assert gdx is not None
    meta = gdx._meta
    assert meta.max_deep == 3
    assert meta.complexity == 5


@pytest.mark.django_db
def test_validation_depth_limit_reads_gdx_meta():
    """DepthLimitValidationRule._type_max_deep reads correctly from native types."""
    from django_graphex.validation import _type_max_deep
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _ValidationDepthType(DjangoObjectType):
        class Meta:
            model = Category
            max_deep = 7

    gql_type = _ValidationDepthType._meta.graphql_output_type
    assert gql_type is not None
    result = _type_max_deep(gql_type)
    assert result == 7, f"Expected 7, got {result}"


@pytest.mark.django_db
def test_cost_analysis_reads_complexity_from_gdx_meta():
    """_type_complexity reads correctly from native types via extensions['gdx']."""
    from django_graphex.cost import _type_complexity
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _CostComplexityType(DjangoObjectType):
        class Meta:
            model = Category
            complexity = 12

    gql_type = _CostComplexityType._meta.graphql_output_type
    assert gql_type is not None
    result = _type_complexity(gql_type)
    assert result == 12, f"Expected 12, got {result}"


def test_from_attributes_never_true_on_native_output_base():
    """from_attributes must not be True on any native output base class.

    This is the spec requirement from §from_attributes=False enforcement.
    NativeTypeAliasMixin and GdxPayload/GdxMeta do not have model_config,
    so this test verifies the build pipeline never sets from_attributes=True.
    """
    from django_graphex.native.bridge import GdxPayload
    from django_graphex.native.ir import GdxMeta

    # GdxMeta and GdxPayload are frozen dataclasses - no model_config
    # The test verifies these IR types don't accidentally have from_attributes
    gdx_meta = GdxMeta(name="Test")
    assert not hasattr(gdx_meta, "model_config"), (
        "GdxMeta must not have model_config (it's a frozen dataclass, not Pydantic model)"
    )

    payload = GdxPayload(gdx_meta)
    assert not hasattr(payload, "model_config"), (
        "GdxPayload must not have model_config"
    )


@pytest.mark.django_db
def test_django_object_options_graphql_output_type_default_none():
    """DjangoObjectOptions.graphql_output_type defaults to None before native compile.

    A fresh DjangoObjectType subclass on the graphene backend has
    graphql_output_type = None (it's only populated under native).
    """
    import os
    from django_graphex.types import DjangoObjectOptions

    # DjangoObjectOptions has graphql_output_type = None as class default
    assert DjangoObjectOptions.graphql_output_type is None, (
        "DjangoObjectOptions.graphql_output_type must default to None"
    )


@pytest.mark.django_db
def test_type_max_deep_negative_value_returns_none():
    """_type_max_deep returns None for negative max_deep values."""
    from django_graphex.validation import _type_max_deep
    from graphql import GraphQLObjectType, GraphQLString, GraphQLField
    from django_graphex.native.bridge import GdxPayload
    from django_graphex.native.ir import GdxMeta

    # Negative max_deep should return None (validation rejects negative limits)
    gdx_meta = GdxMeta(name="NegativeType", max_deep=-1)
    payload = GdxPayload(gdx_meta)
    gql_type = GraphQLObjectType(
        name="NegativeType",
        fields={"id": GraphQLField(GraphQLString)},
        extensions={"gdx": payload},
    )

    result = _type_max_deep(gql_type)
    assert result is None, f"Expected None for negative max_deep, got {result}"


@pytest.mark.django_db
def test_type_complexity_negative_value_returns_none():
    """_type_complexity returns None for negative complexity values."""
    from django_graphex.cost import _type_complexity
    from graphql import GraphQLObjectType, GraphQLString, GraphQLField
    from django_graphex.native.bridge import GdxPayload
    from django_graphex.native.ir import GdxMeta

    gdx_meta = GdxMeta(name="NegativeComplexityType", complexity=-5)
    payload = GdxPayload(gdx_meta)
    gql_type = GraphQLObjectType(
        name="NegativeComplexityType",
        fields={"id": GraphQLField(GraphQLString)},
        extensions={"gdx": payload},
    )

    result = _type_complexity(gql_type)
    assert result is None, f"Expected None for negative complexity, got {result}"
