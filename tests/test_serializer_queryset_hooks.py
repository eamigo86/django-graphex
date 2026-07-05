# -*- coding: utf-8 -*-
"""Tests for DjangoModelType.get_queryset / filter_queryset hooks (piece B)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from graphql import ExecutionResult, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoModelType

from .models import HookModel

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from pytest import MonkeyPatch


class HookType(DjangoModelType):
    """Model type under test.

    Exposes the get_queryset/filter_queryset hooks so tests can monkeypatch
    them and assert the resulting query scoping.
    """

    class Meta:
        """Configuration for "HookType".

        Declares the backing model and the fields exposed to native filtering.
        """

        model = HookModel
        filter_fields = {"id": ("exact",), "text": ("exact", "icontains")}


class _Query(ObjectType):
    """Root query exposing single and list fields for "HookType"."""

    hook = HookType.RetrieveField()
    hooks = HookType.ListField()


_schema = DjangoGraphQLSchema(query=_Query)


def _execute(query: str) -> ExecutionResult:
    """Run a query against the native schema (drop-in for "schema.execute").

    Args:
        query: The GraphQL query document to execute.

    Returns:
        result: The execution result returned by "graphql_sync".
    """
    return graphql_sync(_schema.graphql_schema, query)


def _seed() -> tuple[HookModel, HookModel, HookModel]:
    """Create three "HookModel" rows, two kept and one meant to be dropped.

    Returns:
        rows: The three created model instances in creation order.
    """
    a = HookModel.objects.create(text="keep-1")
    b = HookModel.objects.create(text="keep-2")
    c = HookModel.objects.create(text="drop-1")
    return a, b, c


# -- AC1: default hooks return everything ------------------------------------ #
def test_default_returns_all(db: None) -> None:
    """Assert the list field returns every row when no hook is overridden.

    Args:
        db: The pytest-django fixture that grants database access for the test.
    """
    _seed()
    res = _execute("{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 3


# -- AC2: get_queryset override is the base for list/retrieve ---------------- #
def test_get_queryset_override(db: None, monkeypatch: MonkeyPatch) -> None:
    """Assert an overridden "get_queryset" becomes the base for list results.

    If this fails, custom queryset scoping declared on a model type is
    silently ignored by the list field resolver.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.get_queryset" for the duration of
            the test.
    """
    _seed()

    def _gq(
        cls: type[HookType], manager: object, info: object, **kwargs: object
    ) -> QuerySet[HookModel]:
        return HookModel.objects.filter(text__startswith="keep")

    monkeypatch.setattr(HookType, "get_queryset", classmethod(_gq))

    res = _execute("{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 2
    assert sorted(r["text"] for r in res.data["hooks"]["results"]) == [
        "keep-1",
        "keep-2",
    ]


# -- AC3: filter_queryset override scopes list + retrieve -------------------- #
def test_filter_queryset_override(db: None, monkeypatch: MonkeyPatch) -> None:
    """Assert an overridden "filter_queryset" scopes both list and retrieve.

    If this fails, a row excluded by custom filtering would still be
    reachable through the single-object retrieve field.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.filter_queryset" for the duration
            of the test.
    """
    a, b, c = _seed()

    def _fq(
        cls: type[HookType], qs: QuerySet[HookModel], info: object, **kwargs: object
    ) -> QuerySet[HookModel]:
        return qs.filter(text__startswith="keep")

    monkeypatch.setattr(HookType, "filter_queryset", classmethod(_fq))

    res = _execute("{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 2

    # an excluded id retrieves as null
    excluded = _execute("{ hook(id: %d) { text } }" % c.pk)
    assert excluded.errors is None, excluded.errors
    assert excluded.data["hook"] is None

    included = _execute("{ hook(id: %d) { text } }" % a.pk)
    assert included.data["hook"]["text"] == "keep-1"


# -- AC4: perform_mutate falls back to the saved object ---------------------- #
def test_perform_mutate_fallback_when_excluded(
    db: None, monkeypatch: MonkeyPatch
) -> None:
    """Assert "perform_mutate" falls back to the saved object when excluded.

    If this fails, saving a mutation whose result is immediately filtered out
    by "filter_queryset" would surface as a failed mutation instead of
    returning the object that was actually persisted.

    Args:
        db: The pytest-django fixture that grants database access for the test.
        monkeypatch: Used to patch "HookType.filter_queryset" so it excludes
            everything.
    """
    obj = HookModel.objects.create(text="drop-1")

    def _fq(
        cls: type[HookType], qs: QuerySet[HookModel], info: object, **kwargs: object
    ) -> QuerySet[HookModel]:
        return qs.none()  # excludes everything

    monkeypatch.setattr(HookType, "filter_queryset", classmethod(_fq))

    result = HookType.perform_mutate(obj, info=None)
    assert result.ok is True
    assert getattr(result, HookType._meta.output_field_name).pk == obj.pk
