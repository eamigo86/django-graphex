"""Tests for B1: DjangoObjectType native branch.

Under GDX_BACKEND=native, DjangoObjectType subclasses must:
- Build a GraphQLObjectType via the native compile path.
- Store compiled type on _meta.graphql_output_type.
- Attach extensions["gdx"] populated with GdxPayload.
- Pass the honest metaclass test (Phase-7 re-scope; class is NOT ModelMetaclass).

All tests run under GDX_BACKEND=native via the native_only mark.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


@pytest.mark.django_db
def test_django_object_type_native_compiles_graphql_output_type():
    """Under GDX_BACKEND=native, DjangoObjectType subclass must have
    _meta.graphql_output_type set to a GraphQLObjectType."""
    from graphql import GraphQLObjectType
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _TestCategoryType(DjangoObjectType):
        class Meta:
            model = Category

    meta = _TestCategoryType._meta
    assert hasattr(meta, "graphql_output_type"), (
        "DjangoObjectType._meta must expose graphql_output_type under native"
    )
    assert isinstance(meta.graphql_output_type, GraphQLObjectType), (
        "DjangoObjectType._meta.graphql_output_type must be a GraphQLObjectType, "
        f"got {type(meta.graphql_output_type)}"
    )


@pytest.mark.django_db
def test_django_object_type_native_extensions_gdx():
    """Under GDX_BACKEND=native, the compiled GraphQLObjectType must carry
    extensions['gdx'] = GdxPayload."""
    from django_graphex.native.bridge import GdxPayload
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _TestCategoryTypeGdx(DjangoObjectType):
        class Meta:
            model = Category

    gql_type = _TestCategoryTypeGdx._meta.graphql_output_type
    assert gql_type is not None
    ext = gql_type.extensions or {}
    assert "gdx" in ext, (
        "Compiled GraphQLObjectType must carry extensions['gdx']"
    )
    assert isinstance(ext["gdx"], GdxPayload), (
        f"extensions['gdx'] must be GdxPayload, got {type(ext['gdx'])}"
    )


@pytest.mark.django_db
def test_django_object_type_honest_metaclass():
    """Honest Phase-3 metaclass test.

    type(DjangoObjectType subclass) is NOT pydantic.ModelMetaclass in Phase 3.
    DjangoObjectType subclasses graphene's ObjectType; a class has exactly ONE
    metaclass fixed at class-definition time. While the graphene base is present,
    the metaclass is graphene's SubclassWithMeta_Meta, NOT pydantic.ModelMetaclass.

    The real Phase-3 deliverable is the compiled GraphQLObjectType + extensions["gdx"].
    Model-coupled metaclass identity (type(X) is ModelMetaclass) is RE-SCOPED
    to Phase 7 (graphene deletion). This test documents that boundary honestly.
    """
    # Phase 7 re-scope: metaclass identity swaps when graphene base is removed.
    from pydantic._internal._model_construction import ModelMetaclass
    from graphql import GraphQLObjectType
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _HonestMetaclassType(DjangoObjectType):
        class Meta:
            model = Category

    # HONEST assertion: metaclass is graphene's SubclassWithMeta_Meta, NOT ModelMetaclass
    assert type(_HonestMetaclassType) is not ModelMetaclass, (
        "In Phase 3, type(DjangoObjectType subclass) is graphene's SubclassWithMeta_Meta "
        "— NOT pydantic.ModelMetaclass. "
        "Model-coupled metaclass identity is a Phase-7 (graphene-deletion) concern."
    )

    # Phase-3 real deliverable: _meta.graphql_output_type IS a GraphQLObjectType
    assert isinstance(_HonestMetaclassType._meta.graphql_output_type, GraphQLObjectType), (
        "Phase-3 model-coupled deliverable: _meta.graphql_output_type must be a "
        "GraphQLObjectType (the native compile path must be wired)"
    )


@pytest.mark.django_db
def test_django_object_type_native_fields_include_scalars():
    """Compiled GraphQLObjectType must include scalar fields for the model."""
    from graphql import GraphQLObjectType, GraphQLNonNull, GraphQLString
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _FieldTestCategoryType(DjangoObjectType):
        class Meta:
            model = Category

    gql_type = _FieldTestCategoryType._meta.graphql_output_type
    assert isinstance(gql_type, GraphQLObjectType)
    # Category has a 'name' CharField — must appear as a field
    fields = gql_type.fields
    # Category has a 'title' CharField (not 'name' — see tests/models.py)
    assert "title" in fields, (
        f"GraphQLObjectType must have 'title' field; got {sorted(fields.keys())}"
    )


@pytest.mark.django_db
def test_django_object_type_native_meta_model():
    """_meta.model must be accessible after native compile."""
    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _MetaModelType(DjangoObjectType):
        class Meta:
            model = Category

    assert _MetaModelType._meta.model is Category
