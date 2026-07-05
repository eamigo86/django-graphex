# -*- coding: utf-8 -*-
"""Custom-resolver honoring on the list/object fields (piece A).

Also a regression for DjangoModelType: its injected "cls.retrieve" /
"cls.list" (and therefore "Meta.queryset") must actually run.
"""

from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoObjectField,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType
from tests.models import BasicModel
from tests.schema import User1ListType, UserType


def _sentinel(*args, **kwargs):
    return "CUSTOM"


def _func(wrapped):
    """Return the function a partial wraps (or the value itself)."""
    return getattr(wrapped, "func", wrapped)


# -- AC1 / AC2: a custom resolver is honored, else the built-in --------------- #
def test_object_field_honors_custom_resolver() -> None:
    """DjangoObjectField must call a supplied resolver, or fall back otherwise.

    If this breaks, a custom resolver passed to DjangoObjectField would be
    silently ignored in favor of the built-in "object_resolver".
    """
    assert _func(
        DjangoObjectField(UserType, resolver=_sentinel).wrap_resolve(None)
    ) is (_sentinel)
    assert (
        _func(DjangoObjectField(UserType).wrap_resolve(None)).__name__
        == "object_resolver"
    )


def test_list_object_field_honors_custom_resolver() -> None:
    """DjangoListObjectField must call a supplied resolver, or fall back otherwise.

    If this breaks, a custom resolver passed to DjangoListObjectField would be
    silently ignored in favor of the built-in "list_resolver".
    """
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


def test_filter_list_field_honors_custom_resolver() -> None:
    """DjangoFilterListField must call a supplied resolver instead of the built-in.

    If this breaks, a custom resolver passed to DjangoFilterListField would be
    silently ignored.
    """
    assert (
        _func(DjangoFilterListField(UserType, resolver=_sentinel).wrap_resolve(None))
        is _sentinel
    )


def test_filter_paginate_list_field_honors_custom_resolver() -> None:
    """DjangoFilterPaginateListField must call a supplied resolver.

    If this breaks, a custom resolver passed to DjangoFilterPaginateListField
    would be silently ignored in favor of the built-in paginated resolver.
    """
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


def test_serializer_type_fields_run_injected_resolvers() -> None:
    """DjangoModelType's generated fields must wrap "cls.list" / "cls.retrieve".

    If this breaks, ListField/RetrieveField would resolve through the built-in
    resolvers instead of the injected class methods, so overrides on "list" or
    "retrieve" (and therefore Meta.queryset) would never run.
    """
    # AC3: the fields now wrap cls.list / cls.retrieve (not the built-ins).
    assert _func(_RestrictedBasicType.ListField().wrap_resolve(None)).__name__ == "list"
    assert (
        _func(_RestrictedBasicType.RetrieveField().wrap_resolve(None)).__name__
        == "retrieve"
    )


class _Query(ObjectType):
    basics = _RestrictedBasicType.ListField()


_schema = DjangoGraphQLSchema(query=_Query)


def test_meta_queryset_is_honored_in_list(db: None) -> None:
    """ "Meta.queryset" must restrict the list query to the "keep*" subset.

    If this breaks, a DjangoModelType with a restrictive "Meta.queryset" would
    leak rows outside that queryset through the generated list field.

    Args:
        db: Pytest-django fixture that grants database access for the test.
    """
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
