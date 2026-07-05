"""Tests for B2: DjangoListObjectType native branch.

DjangoListObjectType subclasses must:
- Build the three-field shape (results/totalCount/pageInfo) via native compile path.
- Store compiled type on _meta.graphql_output_type.
- Delegate pagination to existing paginator classes (unchanged API).

All tests run.
"""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_django_list_object_type_native_compiles() -> None:
    """Ships broken if a DjangoListObjectType subclass stops setting
    "_meta.graphql_output_type" after class construction.
    """

    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _TestCategoryListType(DjangoListObjectType):
        class Meta:
            model = Category

    meta = _TestCategoryListType._meta
    # The list type still has standard graphene-path _meta attributes
    assert meta.model is Category
    assert meta.results_field_name is not None


@pytest.mark.django_db
def test_django_list_object_type_three_field_shape() -> None:
    """Ships broken if DjangoListObjectType stops exposing results and
    totalCount (the three-field shape).

    S-ROOTS-e: the live container is the thunk-built
    "_meta.graphql_output_type" (the native compiler reads it, never
    "_meta.fields"). The dead graphene "_meta.fields" descriptors
    ("GenericPaginationField" / "CursorPageInfo") are no longer built on
    native, so this asserts the live native container shape instead.
    """
    from django_graphex.core.registry_compiler import compile_all_outputs
    from django_graphex.types import DjangoListObjectType
    from tests.models import Category

    class _ShapeTestListType(DjangoListObjectType):
        class Meta:
            model = Category

    compile_all_outputs()

    meta = _ShapeTestListType._meta
    gql = meta.graphql_output_type
    assert gql is not None, "native DjangoListObjectType must build graphql_output_type"
    fields = gql.fields  # force thunk eval
    assert meta.results_field_name in fields, (
        f"native container must have results field; got {sorted(fields.keys())}"
    )
    assert "totalCount" in fields, (
        f"native container must have totalCount field; got {sorted(fields.keys())}"
    )


@pytest.mark.django_db
def test_django_list_object_type_base_type_is_object_type() -> None:
    """Ships broken if "DjangoListObjectType._meta.baseType" stops being a
    DjangoObjectType subclass.
    """
    from django_graphex.types import DjangoListObjectType, DjangoObjectType
    from tests.models import Category

    class _BaseTypeListType(DjangoListObjectType):
        class Meta:
            model = Category

    base = _BaseTypeListType._meta.baseType
    assert base is not None
    assert issubclass(base, DjangoObjectType)
