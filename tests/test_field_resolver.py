# -*- coding: utf-8 -*-
"""Custom-resolver honoring on the list/object fields (piece A).

Also a regression for DjangoModelType: its injected ``cls.retrieve`` /
``cls.list`` (and therefore ``Meta.queryset``) must actually run.
"""

from graphql import graphql_sync

from django_graphex import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoGraphQLSchema,
    DjangoListObjectField,
    DjangoModelType,
    DjangoObjectField,
    LimitOffsetGraphqlPagination,
    ObjectType,
)
from tests.models import BasicModel
from tests.schema import User1ListType, UserType


def _sentinel(*args, **kwargs):
    return "CUSTOM"


def _func(wrapped):
    """Return the function a partial wraps (or the value itself)."""
    return getattr(wrapped, "func", wrapped)


# -- AC1 / AC2: a custom resolver is honored, else the built-in --------------- #
def test_object_field_honors_custom_resolver():
    assert _func(
        DjangoObjectField(UserType, resolver=_sentinel).wrap_resolve(None)
    ) is (_sentinel)
    assert (
        _func(DjangoObjectField(UserType).wrap_resolve(None)).__name__
        == "object_resolver"
    )


def test_list_object_field_honors_custom_resolver():
    assert (
        _func(
            DjangoListObjectField(User1ListType, resolver=_sentinel).wrap_resolve(None)
        )
        is _sentinel
    )
    assert (
        _func(DjangoListObjectField(User1ListType).wrap_resolve(None)).__name__
        == "list_resolver"
    )


def test_filter_list_field_honors_custom_resolver():
    assert (
        _func(DjangoFilterListField(UserType, resolver=_sentinel).wrap_resolve(None))
        is _sentinel
    )


def test_filter_paginate_list_field_honors_custom_resolver():
    field = DjangoFilterPaginateListField(
        UserType, pagination=LimitOffsetGraphqlPagination(), resolver=_sentinel
    )
    assert _func(field.wrap_resolve(None)) is _sentinel


# -- AC3 / AC4: DjangoModelType wiring + Meta.queryset ------------------- #
class _RestrictedBasicType(DjangoModelType):
    class Meta:
        model = BasicModel
        queryset = BasicModel.objects.filter(text__startswith="keep")
        filter_fields = {"id": ("exact",), "text": ("exact", "icontains")}


def test_serializer_type_fields_run_injected_resolvers():
    # AC3: the fields now wrap cls.list / cls.retrieve (not the built-ins).
    assert _func(_RestrictedBasicType.ListField().wrap_resolve(None)).__name__ == "list"
    assert (
        _func(_RestrictedBasicType.RetrieveField().wrap_resolve(None)).__name__
        == "retrieve"
    )


class _Query(ObjectType):
    basics = _RestrictedBasicType.ListField()


_schema = DjangoGraphQLSchema(query=_Query)


def test_meta_queryset_is_honored_in_list(db):
    # AC4: Meta.queryset restricts the list to the "keep*" subset.
    BasicModel.objects.create(text="keep-1")
    BasicModel.objects.create(text="keep-2")
    BasicModel.objects.create(text="drop-1")

    result = graphql_sync(
        _schema.graphql_schema, "{ basics { results { text } totalCount } }"
    )
    assert result.errors is None, result.errors

    data = result.data["basics"]
    assert sorted(row["text"] for row in data["results"]) == ["keep-1", "keep-2"]
    assert data["totalCount"] == 2
