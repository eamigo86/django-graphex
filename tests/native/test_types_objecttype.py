"""Tests for B1: DjangoObjectType native branch.

DjangoObjectType subclasses must:
- Build a GraphQLObjectType via the native compile path.
- Store compiled type on _meta.graphql_output_type.
- Attach extensions["gdx"] populated with GdxPayload.
- Pass the honest metaclass test (Phase-7 re-scope; class is NOT ModelMetaclass).

All tests run.
"""
from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_django_object_type_native_compiles_graphql_output_type():
    """DjangoObjectType subclass must have
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
    """the compiled GraphQLObjectType must carry
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
    """Phase-7 S6b metaclass test (the boundary this slice crosses).

    Phase 3 documented that ``type(DjangoObjectType subclass)`` was graphene's
    ``SubclassWithMeta_Meta`` (graphene base present). S6b RE-PARENTS
    ``DjangoObjectType`` off graphene onto ``native.base.ObjectType``, whose sole
    metaclass is pydantic's ``ModelMetaclass`` (the driver runs via
    ``__init_subclass__``, NOT a custom metaclass — the #1452 invariant). So the
    Phase-3 assertion is now INVERTED: ``type(X) IS ModelMetaclass``.
    """
    # S6b re-parent: metaclass is now pydantic ModelMetaclass.
    from graphql import GraphQLObjectType
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.types import DjangoObjectType
    from tests.models import Category

    class _HonestMetaclassType(DjangoObjectType):
        class Meta:
            model = Category

    # S6b assertion: metaclass IS pydantic.ModelMetaclass (#1452 invariant holds).
    assert type(_HonestMetaclassType) is ModelMetaclass, (
        "After S6b, type(DjangoObjectType subclass) IS pydantic.ModelMetaclass "
        "(re-parented off graphene; driver runs via __init_subclass__, NOT a "
        "custom metaclass)."
    )

    # The native compile deliverable still holds: _meta.graphql_output_type IS a
    # GraphQLObjectType (the native compile path is now unconditional).
    assert isinstance(_HonestMetaclassType._meta.graphql_output_type, GraphQLObjectType), (
        "S6b deliverable: _meta.graphql_output_type must be a GraphQLObjectType "
        "(the native compile path is unconditional after re-parent)."
    )


def test_polymorphic_types_reparented_onto_native_base():
    """S6d structural invariant (restored): the POLYMORPHIC bases
    ``DjangoUnionType`` / ``DjangoInterfaceType`` are re-parented off graphene
    onto ``native.base.ObjectType``, whose sole metaclass is pydantic's
    ``ModelMetaclass`` (#1452 invariant). Mirrors the DjangoObjectType analog in
    ``test_django_object_type_honest_metaclass`` — assert the POSITIVE native
    invariant (no graphene import needed)."""
    from pydantic._internal._model_construction import ModelMetaclass

    from django_graphex.native.base import ObjectType as NativeObjectType
    from django_graphex.types import DjangoInterfaceType, DjangoUnionType

    for poly in (DjangoUnionType, DjangoInterfaceType):
        assert issubclass(poly, NativeObjectType), (
            f"{poly.__name__} must be re-parented onto native.base.ObjectType"
        )
        assert type(poly) is ModelMetaclass, (
            f"type({poly.__name__}) must be pydantic.ModelMetaclass "
            "(re-parented off graphene)."
        )


@pytest.mark.django_db
def test_django_object_type_native_fields_include_scalars():
    """Compiled GraphQLObjectType must include scalar fields for the model."""
    from graphql import GraphQLNonNull, GraphQLObjectType, GraphQLString

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
