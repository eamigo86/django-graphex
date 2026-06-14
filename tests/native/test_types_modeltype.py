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
def test_django_model_type_create_update_field_deferred_to_phase5():
    """CreateField/UpdateField native schema assembly is deferred to Phase 5.

    Under GDX_BACKEND=native, calling CreateField() or UpdateField() will raise
    NotImplementedError because _meta.arguments["create"/"update"] hold
    graphql-core GraphQLArgument objects — not graphene Argument objects.
    This is the explicit Phase-5 deferral: the mutation field's native assembly
    is NOT done in Phase 3.

    This test asserts the EXPLICIT DEFERRAL: the method raises NotImplementedError
    (or ValueError from graphene's args validation). This confirms the deferred
    state is detectable, not silent.
    """
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _Phase5DeferralTest(DjangoModelType):
        class Meta:
            model = Category

    # Under native: _meta.arguments["create"] contains GraphQLArgument (not graphene.Argument).
    # graphene's Field(args=...) rejects unknown argument types → ValueError.
    # This is the explicit Phase-5 deferral: native schema assembly for mutations is
    # deferred; until Phase 5, callers must use the graphene schema build path.
    with pytest.raises((ValueError, NotImplementedError)):
        _Phase5DeferralTest.CreateField()


@pytest.mark.django_db
def test_django_model_type_model_meta():
    """DjangoModelType._meta.model must be accessible under native."""
    from django_graphex.types import DjangoModelType
    from tests.models import Category

    class _MetaModelTest(DjangoModelType):
        class Meta:
            model = Category

    assert _MetaModelTest._meta.model is Category
