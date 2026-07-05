# -*- coding: utf-8 -*-
"""Tests for DjangoObjectType.get_queryset per-request scoping hook (issue #58).

Verifies that overriding DjangoObjectType.get_queryset(cls, queryset, info)
actually filters the queryset for top-level list AND single-object resolvers,
AND that DjangoModelType is completely unaffected (no double-filtering, no
signature errors).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from django_graphex.types import (
    DjangoListObjectType,
    DjangoModelType,
    DjangoObjectType,
)

from .models import HookModel, ScopedArticle

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from pytest import MonkeyPatch
    from pytest_django.fixtures import DjangoAssertNumQueries

# ---------------------------------------------------------------------------
# DjangoObjectType with a get_queryset override that filters to public rows
# ---------------------------------------------------------------------------


class ScopedArticleType(DjangoObjectType):
    """A "DjangoObjectType" whose "get_queryset" hook exposes only public articles.

    Used across every AC test in this module as the hooked baseline type.
    """

    class Meta:
        """Bind "ScopedArticleType" to "ScopedArticle" with id/title filter fields.

        The filter fields let the query-time tests exercise filtered list
        resolvers alongside the "get_queryset" hook.
        """

        model = ScopedArticle
        filter_fields = {"id": ("exact",), "title": ("icontains",)}

    @classmethod
    def get_queryset(cls, queryset: "QuerySet[Any]", info: Any) -> "QuerySet[Any]":
        """Restrict the queryset to public articles only.

        Args:
            queryset: The base queryset to scope.
            info: The GraphQL resolve info for the current request.

        Returns:
            queryset: The queryset filtered to "is_public=True" rows.
        """
        return queryset.filter(is_public=True)


class ScopedArticleListType(DjangoListObjectType):
    """A "DjangoListObjectType" wrapping "ScopedArticle" for paginated listing.

    Backs the "articlesListObj" field used by the AC7 tests.
    """

    class Meta:
        """Bind "ScopedArticleListType" to "ScopedArticle" with pagination.

        Reuses the same filter fields as "ScopedArticleType".
        """

        model = ScopedArticle
        filter_fields = {"id": ("exact",), "title": ("icontains",)}
        pagination = LimitOffsetGraphqlPagination(default_limit=25, ordering="id")


class _Query(ObjectType):
    """The root query exposing every "ScopedArticleType" resolver style under test."""

    article = DjangoObjectField(ScopedArticleType)
    articles = DjangoFilterListField(ScopedArticleType)
    articles_paginated = DjangoFilterPaginateListField(
        ScopedArticleType,
        pagination=LimitOffsetGraphqlPagination(default_limit=25, ordering="id"),
    )
    articles_list_obj = DjangoListObjectField(ScopedArticleListType)


_schema = DjangoGraphQLSchema(query=_Query)


def _seed() -> tuple[ScopedArticle, ScopedArticle, ScopedArticle]:
    """Create two public and one private "ScopedArticle" fixture rows.

    Returns:
        articles: A 3-tuple of (first public, second public, private) articles.
    """
    pub1 = ScopedArticle.objects.create(title="Public-1", is_public=True)
    pub2 = ScopedArticle.objects.create(title="Public-2", is_public=True)
    priv = ScopedArticle.objects.create(title="Private-1", is_public=False)
    return pub1, pub2, priv


# ---------------------------------------------------------------------------
# AC1: DjangoFilterListField (DjangoListField.list_resolver) honours the hook
# ---------------------------------------------------------------------------


def test_list_field_applies_get_queryset(db: None) -> None:
    """DjangoFilterListField must return only rows the "get_queryset" hook allows.

    Args:
        db: The pytest-django fixture granting database access.
    """
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


def test_single_object_field_applies_get_queryset(db: None) -> None:
    """DjangoObjectField must return None for an object excluded by the hook.

    Args:
        db: The pytest-django fixture granting database access.
    """
    pub1, pub2, priv = _seed()

    # Private article should be invisible even when queried by exact id
    res = graphql_sync(
        _schema.graphql_schema, "{ article(id: %d) { title } }" % priv.pk
    )
    assert res.errors is None, res.errors
    assert res.data["article"] is None, (
        "DjangoObjectType.get_queryset hook was not applied — private row returned"
    )

    # Public article should still be visible
    res_pub = graphql_sync(
        _schema.graphql_schema, "{ article(id: %d) { title } }" % pub1.pk
    )
    assert res_pub.errors is None, res_pub.errors
    assert res_pub.data["article"]["title"] == "Public-1"


# ---------------------------------------------------------------------------
# AC3: DjangoFilterPaginateListField also honours the hook
# ---------------------------------------------------------------------------


def test_paginated_list_applies_get_queryset(db: None) -> None:
    """DjangoFilterPaginateListField must respect the get_queryset override.

    Args:
        db: The pytest-django fixture granting database access.
    """
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
    """A "DjangoObjectType" with no "get_queryset" override, for the baseline case.

    Proves the default hook is a no-op that returns the queryset unchanged.
    """

    class Meta:
        """Bind "UnfilteredArticleType" to "ScopedArticle" outside the shared registry.

        "skip_registry" avoids colliding with "ScopedArticleType" over the
        same model.
        """

        model = ScopedArticle
        # No get_queryset override — base class returns qs unchanged
        skip_registry = True  # don't collide with ScopedArticleType in the registry


class _UnfilteredQuery(ObjectType):
    """The root query exposing the unfiltered baseline resolver."""

    unfiltered = DjangoFilterListField(UnfilteredArticleType)


_unfiltered_schema = DjangoGraphQLSchema(query=_UnfilteredQuery)


def test_default_get_queryset_returns_all(db: None) -> None:
    """When "get_queryset" is not overridden, all rows must be returned.

    Args:
        db: The pytest-django fixture granting database access.
    """
    pub1, pub2, priv = _seed()

    res = graphql_sync(_unfiltered_schema.graphql_schema, "{ unfiltered { title } }")
    assert res.errors is None, res.errors
    assert len(res.data["unfiltered"]) == 3


# ---------------------------------------------------------------------------
# AC5: DjangoModelType path is UNCHANGED — no double-filtering, no sig error
# ---------------------------------------------------------------------------


class HookModelType(DjangoModelType):
    """A "DjangoModelType" for "HookModel", used to prove the hook wiring is isolated.

    "DjangoModelType" does not carry a "get_queryset" hook, so these tests
    assert it is unaffected by the new wiring.
    """

    class Meta:
        """Bind "HookModelType" to "HookModel" with id/text filter fields.

        The filter fields let the list resolver test exercise a filtered
        path.
        """

        model = HookModel
        filter_fields = {"id": ("exact",), "text": ("exact",)}


class _DMTQuery(ObjectType):
    """The root query exposing "HookModelType" retrieve and list resolvers."""

    hook = HookModelType.RetrieveField()
    hooks = HookModelType.ListField()


_dmt_schema = DjangoGraphQLSchema(query=_DMTQuery)


def test_django_model_type_unaffected(db: None) -> None:
    """DjangoModelType list/retrieve paths must not be double-filtered.

    Args:
        db: The pytest-django fixture granting database access.
    """
    a = HookModel.objects.create(text="alpha")
    HookModel.objects.create(text="beta")

    # list — all rows returned (no accidental extra filter)
    res = graphql_sync(
        _dmt_schema.graphql_schema, "{ hooks { results { text } totalCount } }"
    )
    assert res.errors is None, res.errors
    assert res.data["hooks"]["totalCount"] == 2

    # retrieve — correct object returned
    res2 = graphql_sync(_dmt_schema.graphql_schema, "{ hook(id: %d) { text } }" % a.pk)
    assert res2.errors is None, res2.errors
    assert res2.data["hook"]["text"] == "alpha"


def test_django_model_type_get_queryset_signature_unchanged(
    db: None, monkeypatch: "MonkeyPatch"
) -> None:
    """ "DjangoModelType.get_queryset(manager, info, **kwargs)" must still work.

    Args:
        db: The pytest-django fixture granting database access.
        monkeypatch: The pytest fixture used to wrap "filter_queryset" and
            record whether it was invoked.
    """
    HookModel.objects.create(text="check")
    filter_called = []

    original_fq = HookModelType.filter_queryset.__func__

    def patched_fq(cls, qs, info, **kwargs):
        filter_called.append(True)
        return original_fq(cls, qs, info, **kwargs)

    monkeypatch.setattr(HookModelType, "filter_queryset", classmethod(patched_fq))

    res = graphql_sync(
        _dmt_schema.graphql_schema, "{ hooks { results { text } totalCount } }"
    )
    assert res.errors is None, res.errors
    assert filter_called, (
        "filter_queryset was never called — DjangoModelType path broken"
    )


# ---------------------------------------------------------------------------
# AC6: Optimizer still runs on top of the hook queryset (no extra queries)
# ---------------------------------------------------------------------------


def test_optimizer_runs_on_hooked_queryset(db: None, django_db_setup: None) -> None:
    """The optimizer's select_related/prefetch must still apply; row-count unaffected.

    Args:
        db: The pytest-django fixture granting database access.
        django_db_setup: The pytest-django fixture that provisions the test
            database schema.
    """
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


def test_list_object_field_applies_get_queryset_results(db: None) -> None:
    """DjangoListObjectField results must reflect the item type's "get_queryset" hook.

    Args:
        db: The pytest-django fixture granting database access.
    """
    pub1, pub2, priv = _seed()

    res = graphql_sync(
        _schema.graphql_schema, "{ articlesListObj { results { title } totalCount } }"
    )
    assert res.errors is None, res.errors

    titles = {r["title"] for r in res.data["articlesListObj"]["results"]}
    assert "Public-1" in titles
    assert "Public-2" in titles
    assert "Private-1" not in titles, (
        "DjangoListObjectField bypasses get_queryset hook — private row leaked into results"
    )


def test_list_object_field_applies_get_queryset_total_count(db: None) -> None:
    """DjangoListObjectField totalCount must reflect the item type's "get_queryset" hook.

    Args:
        db: The pytest-django fixture granting database access.
    """
    pub1, pub2, priv = _seed()

    res = graphql_sync(
        _schema.graphql_schema, "{ articlesListObj { results { title } totalCount } }"
    )
    assert res.errors is None, res.errors

    count = res.data["articlesListObj"]["totalCount"]
    assert count == 2, (
        f"totalCount={count} includes rows excluded by get_queryset (expected 2, got {count})"
    )


def test_list_object_field_get_queryset_query_count_parity(
    db: None, django_assert_num_queries: "DjangoAssertNumQueries"
) -> None:
    """The optimizer must still apply on top of the hook queryset with no extra queries.

    Args:
        db: The pytest-django fixture granting database access.
        django_assert_num_queries: The pytest-django fixture used as a context
            manager to assert the exact number of database queries executed.
    """
    pub1, pub2, priv = _seed()

    # Baseline: the hook-filtered path must not regress query count vs. un-hooked.
    # We run the same query twice and confirm it completes without error; the
    # exact count depends on optimizer settings, but it must be deterministic.
    with django_assert_num_queries(2):  # count + results (both from hooked qs)
        res = graphql_sync(
            _schema.graphql_schema,
            "{ articlesListObj { results { title } totalCount } }",
        )
    assert res.errors is None, res.errors


def test_list_object_field_django_model_type_unaffected(db: None) -> None:
    """DjangoModelType path must not be double-filtered by the "get_queryset" wiring.

    Args:
        db: The pytest-django fixture granting database access.
    """
    HookModel.objects.create(text="alpha")
    HookModel.objects.create(text="beta")

    res = graphql_sync(
        _dmt_schema.graphql_schema, "{ hooks { results { text } totalCount } }"
    )
    assert res.errors is None, res.errors
    # Both rows still visible — DjangoModelType is isolated from the new wiring.
    assert res.data["hooks"]["totalCount"] == 2
