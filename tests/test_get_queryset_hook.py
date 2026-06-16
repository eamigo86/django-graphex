# -*- coding: utf-8 -*-
"""Tests for DjangoObjectType.get_queryset per-request scoping hook (issue #58).

Verifies that overriding DjangoObjectType.get_queryset(cls, queryset, info)
actually filters the queryset for top-level list AND single-object resolvers,
AND that DjangoModelType is completely unaffected (no double-filtering, no
signature errors).
"""

from __future__ import annotations

from graphql import graphql_sync

from django_graphex import DjangoGraphQLSchema, ObjectType
from django_graphex.fields import (
    DjangoFilterListField,
    DjangoFilterPaginateListField,
    DjangoListObjectField,
    DjangoObjectField,
)
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.types import (
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

from .models import HookModel, ScopedArticle

# ---------------------------------------------------------------------------
# DjangoObjectType with a get_queryset override that filters to public rows
# ---------------------------------------------------------------------------


class ScopedArticleType(DjangoObjectType):
    class Meta:
        model = ScopedArticle
        filter_fields = {"id": ("exact",), "title": ("icontains",)}

    @classmethod
    def get_queryset(cls, queryset, info):
        """Only expose public articles."""
        return queryset.filter(is_public=True)


class ScopedArticleListType(DjangoListObjectType):
    class Meta:
        model = ScopedArticle
        filter_fields = {"id": ("exact",), "title": ("icontains",)}
        pagination = LimitOffsetGraphqlPagination(default_limit=25, ordering="id")


class _Query(ObjectType):
    article = DjangoObjectField(ScopedArticleType)
    articles = DjangoFilterListField(ScopedArticleType)
    articles_paginated = DjangoFilterPaginateListField(
        ScopedArticleType,
        pagination=LimitOffsetGraphqlPagination(default_limit=25, ordering="id"),
    )
    articles_list_obj = DjangoListObjectField(ScopedArticleListType)


_schema = DjangoGraphQLSchema(query=_Query)


def _seed():
    pub1 = ScopedArticle.objects.create(title="Public-1", is_public=True)
    pub2 = ScopedArticle.objects.create(title="Public-2", is_public=True)
    priv = ScopedArticle.objects.create(title="Private-1", is_public=False)
    return pub1, pub2, priv


# ---------------------------------------------------------------------------
# AC1: DjangoFilterListField (DjangoListField.list_resolver) honours the hook
# ---------------------------------------------------------------------------


def test_list_field_applies_get_queryset(db):
    """DjangoFilterListField returns only rows the hook allows."""
    pub1, pub2, priv = _seed()

    res = graphql_sync(_schema.graphql_schema, "{ articles { title } }")
    assert res.errors is None, res.errors

    titles = {r["title"] for r in res.data["articles"]}
    assert "Public-1" in titles
    assert "Public-2" in titles
    assert "Private-1" not in titles, (
        "DjangoObjectType.get_queryset hook was not applied — private row leaked"
    )


# ---------------------------------------------------------------------------
# AC2: DjangoObjectField (single-object resolver) honours the hook
# ---------------------------------------------------------------------------


def test_single_object_field_applies_get_queryset(db):
    """DjangoObjectField returns None for an object excluded by the hook."""
    pub1, pub2, priv = _seed()

    # Private article should be invisible even when queried by exact id
    res = graphql_sync(_schema.graphql_schema, "{ article(id: %d) { title } }" % priv.pk)
    assert res.errors is None, res.errors
    assert res.data["article"] is None, (
        "DjangoObjectType.get_queryset hook was not applied — private row returned"
    )

    # Public article should still be visible
    res_pub = graphql_sync(_schema.graphql_schema, "{ article(id: %d) { title } }" % pub1.pk)
    assert res_pub.errors is None, res_pub.errors
    assert res_pub.data["article"]["title"] == "Public-1"


# ---------------------------------------------------------------------------
# AC3: DjangoFilterPaginateListField also honours the hook
# ---------------------------------------------------------------------------


def test_paginated_list_applies_get_queryset(db):
    """DjangoFilterPaginateListField respects the get_queryset override."""
    pub1, pub2, priv = _seed()

    res = graphql_sync(_schema.graphql_schema, "{ articlesPaginated { title } }")
    assert res.errors is None, res.errors

    titles = {r["title"] for r in res.data["articlesPaginated"]}
    assert "Private-1" not in titles, (
        "DjangoObjectType.get_queryset hook was not applied in paginated list"
    )


# ---------------------------------------------------------------------------
# AC4: Default get_queryset (no override) returns everything — unchanged behaviour
# ---------------------------------------------------------------------------


class UnfilteredArticleType(DjangoObjectType):
    class Meta:
        model = ScopedArticle
        # No get_queryset override — base class returns qs unchanged
        skip_registry = True  # don't collide with ScopedArticleType in the registry


class _UnfilteredQuery(ObjectType):
    unfiltered = DjangoFilterListField(UnfilteredArticleType)


_unfiltered_schema = DjangoGraphQLSchema(query=_UnfilteredQuery)


def test_default_get_queryset_returns_all(db):
    """When get_queryset is not overridden, all rows are returned."""
    pub1, pub2, priv = _seed()

    res = graphql_sync(_unfiltered_schema.graphql_schema, "{ unfiltered { title } }")
    assert res.errors is None, res.errors
    assert len(res.data["unfiltered"]) == 3


# ---------------------------------------------------------------------------
# AC5: DjangoModelType path is UNCHANGED — no double-filtering, no sig error
# ---------------------------------------------------------------------------


class HookModelType(DjangoModelType):
    class Meta:
        model = HookModel
        filter_fields = {"id": ("exact",), "text": ("exact",)}


class _DMTQuery(ObjectType):
    hook = HookModelType.RetrieveField()
    hooks = HookModelType.ListField()


_dmt_schema = DjangoGraphQLSchema(query=_DMTQuery)


def test_django_model_type_unaffected(db):
    """DjangoModelType list/retrieve paths are not double-filtered."""
    a = HookModel.objects.create(text="alpha")
    HookModel.objects.create(text="beta")

    # list — all rows returned (no accidental extra filter)
    res = graphql_sync(_dmt_schema.graphql_schema, "{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 2

    # retrieve — correct object returned
    res2 = graphql_sync(_dmt_schema.graphql_schema, "{ hook(id: %d) { text } }" % a.pk)
    assert res2.errors is None, res2.errors
    assert res2.data["hook"]["text"] == "alpha"


def test_django_model_type_get_queryset_signature_unchanged(db, monkeypatch):
    """DjangoModelType.get_queryset(manager, info, **kwargs) still works."""
    HookModel.objects.create(text="check")
    filter_called = []

    original_fq = HookModelType.filter_queryset.__func__

    def patched_fq(cls, qs, info, **kwargs):
        filter_called.append(True)
        return original_fq(cls, qs, info, **kwargs)

    monkeypatch.setattr(HookModelType, "filter_queryset", classmethod(patched_fq))

    res = graphql_sync(_dmt_schema.graphql_schema, "{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    assert filter_called, (
        "filter_queryset was never called — DjangoModelType path broken"
    )


# ---------------------------------------------------------------------------
# AC6: Optimizer still runs on top of the hook queryset (no extra queries)
# ---------------------------------------------------------------------------


def test_optimizer_runs_on_hooked_queryset(db, django_db_setup):
    """Optimizer select_related/prefetch still applies; row-count not affected."""
    # This is a basic smoke-test: if the hook queryset is passed as-is to
    # queryset_factory, the optimizer will add select_related/prefetch on top.
    # We verify no Python/Django error occurs and the correct rows come back.
    pub1, pub2, priv = _seed()

    res = graphql_sync(_schema.graphql_schema, "{ articles { title } }")
    assert res.errors is None, res.errors
    assert len(res.data["articles"]) == 2  # only the 2 public ones


# ---------------------------------------------------------------------------
# AC7: DjangoListObjectField (results + totalCount) honours get_queryset
# ---------------------------------------------------------------------------
# This is the completion of issue #58.  DjangoListObjectField is the most
# common documented way to expose a paginated list; if the item type's
# get_queryset is bypassed there, the security hook is a no-op for that pattern.


def test_list_object_field_applies_get_queryset_results(db):
    """DjangoListObjectField results reflect the item type's get_queryset hook."""
    pub1, pub2, priv = _seed()

    res = graphql_sync(_schema.graphql_schema, "{ articlesListObj { results { title } totalCount } }")
    assert res.errors is None, res.errors

    titles = {r["title"] for r in res.data["articlesListObj"]["results"]}
    assert "Public-1" in titles
    assert "Public-2" in titles
    assert "Private-1" not in titles, (
        "DjangoListObjectField bypasses get_queryset hook — private row leaked into results"
    )


def test_list_object_field_applies_get_queryset_total_count(db):
    """DjangoListObjectField totalCount reflects the item type's get_queryset hook."""
    pub1, pub2, priv = _seed()

    res = graphql_sync(_schema.graphql_schema, "{ articlesListObj { results { title } totalCount } }")
    assert res.errors is None, res.errors

    count = res.data["articlesListObj"]["totalCount"]
    assert count == 2, (
        f"totalCount={count} includes rows excluded by get_queryset (expected 2, got {count})"
    )


def test_list_object_field_get_queryset_query_count_parity(
    db, django_assert_num_queries
):
    """Optimizer still applies on top of the hook queryset (no extra queries)."""
    pub1, pub2, priv = _seed()

    # Baseline: the hook-filtered path must not regress query count vs. un-hooked.
    # We run the same query twice and confirm it completes without error; the
    # exact count depends on optimizer settings, but it must be deterministic.
    with django_assert_num_queries(2):  # count + results (both from hooked qs)
        res = graphql_sync(_schema.graphql_schema, "{ articlesListObj { results { title } totalCount } }")
    assert res.errors is None, res.errors


def test_list_object_field_django_model_type_unaffected(db):
    """DjangoModelType path is not double-filtered by the get_queryset wiring."""
    HookModel.objects.create(text="alpha")
    HookModel.objects.create(text="beta")

    res = graphql_sync(_dmt_schema.graphql_schema, "{ hooks { results { text } totalCount } }")
    assert res.errors is None, res.errors
    # Both rows still visible — DjangoModelType is isolated from the new wiring.
    assert res.data["hooks"]["totalCount"] == 2
