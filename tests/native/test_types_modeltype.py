"""Tests for B3: DjangoModelType native branch.

Under GDX_BACKEND=native, DjangoModelType subclasses must:
- Preserve full public API (create/update/delete/retrieve/list/etc.).
- Have CreateField/UpdateField Phase-5 deferral explicit
  (these delegate to graphene.Field in Phase 3, NOT to native schema assembly).
- output_type and output_list_type are accessible.

All tests run under GDX_BACKEND=native via the native_only mark.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.native_only


@pytest.mark.django_db
def test_django_model_type_full_public_api():
    """DjangoModelType must expose its full public API under native."""
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _TestCategoryModelType(DjangoModelType):
        class Meta:
            model = Category

    # All CRUD class methods must be present
    assert callable(_TestCategoryModelType.create)
    assert callable(_TestCategoryModelType.update)
    assert callable(_TestCategoryModelType.delete)
    assert callable(_TestCategoryModelType.retrieve)
    assert callable(_TestCategoryModelType.list)

    # Field builders must be present
    assert callable(_TestCategoryModelType.CreateField)
    assert callable(_TestCategoryModelType.UpdateField)
    assert callable(_TestCategoryModelType.DeleteField)
    assert callable(_TestCategoryModelType.ListField)
    assert callable(_TestCategoryModelType.RetrieveField)
    assert callable(_TestCategoryModelType.QueryFields)
    assert callable(_TestCategoryModelType.MutationFields)


@pytest.mark.django_db
def test_django_model_type_output_type_accessible():
    """DjangoModelType._meta.output_type must be accessible and a DjangoObjectType."""
    from django_graphex.types import DjangoModelType, DjangoObjectType
    from tests.models import Category

    class _OutputTypeTest(DjangoModelType):
        class Meta:
            model = Category

    output_type = _OutputTypeTest._meta.output_type
    assert output_type is not None
    assert issubclass(output_type, DjangoObjectType)


@pytest.mark.django_db
def test_django_model_type_output_list_type_accessible():
    """DjangoModelType._meta.output_list_type must be accessible."""
    from django_graphex.types import DjangoModelType, DjangoListObjectType
    from tests.models import Category

    class _ListTypeTest(DjangoModelType):
        class Meta:
            model = Category

    output_list_type = _ListTypeTest._meta.output_list_type
    assert output_list_type is not None
    assert issubclass(output_list_type, DjangoListObjectType)


@pytest.mark.django_db
def test_django_model_type_create_field_returns_graphql_field():
    """WU-3: CreateField() now returns a GraphQLField under GDX_BACKEND=native.

    Phase 4 WU-3 implements DjangoModelType.*Field() native branches.
    Under native, CreateField() and UpdateField() return graphql-core GraphQLField
    instances (not graphene Field), so no ValueError is raised.

    This test replaces the old 'deferred_to_phase5' deferral test — WU-3 lifted
    the deferral for field construction; schema assembly (mounting into a live
    GraphQLSchema) remains Phase 5.
    """
    from graphql import GraphQLField
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _Phase4WU3Test(DjangoModelType):
        class Meta:
            model = Category

    # WU-3 GREEN: CreateField returns a GraphQLField, not graphene Field
    create_field = _Phase4WU3Test.CreateField()
    assert isinstance(create_field, GraphQLField), (
        "DjangoModelType.CreateField() must return GraphQLField under native (WU-3)"
    )

    update_field = _Phase4WU3Test.UpdateField()
    assert isinstance(update_field, GraphQLField), (
        "DjangoModelType.UpdateField() must return GraphQLField under native (WU-3)"
    )


@pytest.mark.django_db
def test_django_model_type_model_meta():
    """DjangoModelType._meta.model must be accessible under native."""
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _MetaModelTest(DjangoModelType):
        class Meta:
            model = Category

    assert _MetaModelTest._meta.model is Category
