# -*- coding: utf-8 -*-
"""Tests for DjangoModelType.get_queryset / filter_queryset hooks (piece B)."""

import graphene

from django_graphex import DjangoModelType

from .models import HookModel


class HookType(DjangoModelType):
    class Meta:
        model = HookModel
        filter_fields = {"id": ("exact",), "text": ("exact", "icontains")}


class _Query(graphene.ObjectType):
    hook = HookType.RetrieveField()
    hooks = HookType.ListField()


_schema = graphene.Schema(query=_Query)


def _seed():
    a = HookModel.objects.create(text="keep-1")
    b = HookModel.objects.create(text="keep-2")
    c = HookModel.objects.create(text="drop-1")
    return a, b, c


# -- AC1: default hooks return everything ------------------------------------ #
def test_default_returns_all(db):
    _seed()
    res = _schema.execute("{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 3


# -- AC2: get_queryset override is the base for list/retrieve ---------------- #
def test_get_queryset_override(db, monkeypatch):
    _seed()

    def _gq(cls, manager, info, **kwargs):
        return HookModel.objects.filter(text__startswith="keep")

    monkeypatch.setattr(HookType, "get_queryset", classmethod(_gq))

    res = _schema.execute("{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 2
    assert sorted(r["text"] for r in res.data["hooks"]["results"]) == [
        "keep-1",
        "keep-2",
    ]


# -- AC3: filter_queryset override scopes list + retrieve -------------------- #
def test_filter_queryset_override(db, monkeypatch):
    a, b, c = _seed()

    def _fq(cls, qs, info, **kwargs):
        return qs.filter(text__startswith="keep")

    monkeypatch.setattr(HookType, "filter_queryset", classmethod(_fq))

    res = _schema.execute("{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 2

    # an excluded id retrieves as null
    excluded = _schema.execute("{ hook(id: %d) { text } }" % c.pk)
    assert excluded.errors is None, excluded.errors
    assert excluded.data["hook"] is None

    included = _schema.execute("{ hook(id: %d) { text } }" % a.pk)
    assert included.data["hook"]["text"] == "keep-1"


# -- AC4: perform_mutate falls back to the saved object ---------------------- #
def test_perform_mutate_fallback_when_excluded(db, monkeypatch):
    obj = HookModel.objects.create(text="drop-1")

    def _fq(cls, qs, info, **kwargs):
        return qs.none()  # excludes everything

    monkeypatch.setattr(HookType, "filter_queryset", classmethod(_fq))

    result = HookType.perform_mutate(obj, info=None)
    assert result.ok is True
    assert getattr(result, HookType._meta.output_field_name).pk == obj.pk
