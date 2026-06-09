# -*- coding: utf-8 -*-
"""Native, ``Q``-based filtering: lookups, and/or/not, relations, distinct.

Exercises the ``filtering/`` package end to end against a real
``graphene.Schema`` plus unit tests for :func:`to_q`.
"""

from datetime import date

import graphene
from django.db import models
from graphene import Schema

from django_graphex import DjangoListObjectField, DjangoListObjectType
from django_graphex.filtering.translate import to_q
from django_graphex.registry import Registry

from .models import Author

R = Registry()


# A model with a choices field + ordered fields, declared inline for the suite.
class Article(models.Model):
    STATUS = (("draft", "Draft"), ("published", "Published"))
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")
    views = models.IntegerField(default=0)
    published = models.DateField(null=True)
    author = models.ForeignKey(
        Author, related_name="articles", on_delete=models.CASCADE
    )

    class Meta:
        app_label = "tests"


class ArticleListType(DjangoListObjectType):
    class Meta:
        model = Article
        registry = R
        filter_fields = {
            "title": ("exact", "icontains"),
            "status": ("exact", "in"),
            "views": ("exact", "gt", "gte", "lt", "lte", "range", "in"),
            "published": ("exact", "gt", "isnull"),
            "author__name": ("exact", "icontains"),
        }


class AuthorListType(DjangoListObjectType):
    class Meta:
        model = Author
        registry = R
        filter_fields = {
            "id": ("exact", "in"),
            "name": ("exact", "icontains"),
            "articles__title": ("icontains",),
            "articles__status": ("exact",),
        }


class Query(graphene.ObjectType):
    articles = DjangoListObjectField(ArticleListType)
    authors = DjangoListObjectField(AuthorListType)


schema = Schema(query=Query)


def _exec(query):
    result = schema.execute(query)
    assert result.errors is None, result.errors
    return result.data


def _titles(data, root="articles"):
    return sorted(r["title"] for r in data[root]["results"])


# --------------------------------------------------------------------------- #
# Per-lookup mapping                                                            #
# --------------------------------------------------------------------------- #
class _Seed:
    @classmethod
    def seed(cls):
        cls.author = Author.objects.create(name="Ada Lovelace")
        cls.other = Author.objects.create(name="Grace Hopper")
        cls.a1 = Article.objects.create(
            title="GraphQL intro",
            status="published",
            views=10,
            published=date(2020, 1, 1),
            author=cls.author,
        )
        cls.a2 = Article.objects.create(
            title="Django deep dive",
            status="draft",
            views=50,
            published=None,
            author=cls.author,
        )
        cls.a3 = Article.objects.create(
            title="GraphQL advanced",
            status="published",
            views=100,
            published=date(2021, 6, 1),
            author=cls.other,
        )


def test_exact(db):
    _Seed.seed()
    data = _exec(
        '{ articles(filter: { title: { exact: "GraphQL intro" } }) '
        "{ results { title } } }"
    )
    assert _titles(data) == ["GraphQL intro"]


def test_icontains(db):
    _Seed.seed()
    data = _exec(
        '{ articles(filter: { title: { icontains: "graphql" } }) '
        "{ results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


def test_in(db):
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { status: { in: [PUBLISHED] } }) { results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


def test_range(db):
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { views: { range: [40, 120] } }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive", "GraphQL advanced"]


def test_ordered_comparisons(db):
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { views: { gt: 10, lte: 50 } }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive"]


def test_isnull(db):
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { published: { isnull: true } }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive"]


def test_choices_field_via_enum(db):
    _Seed.seed()
    # The status field is exposed through its generated Enum.
    data = _exec(
        "{ articles(filter: { status: { exact: PUBLISHED } }) { results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


# --------------------------------------------------------------------------- #
# Logical composition                                                          #
# --------------------------------------------------------------------------- #
def test_and(db):
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { and: ["
        '  { title: { icontains: "graphql" } }'
        "  { views: { gt: 50 } }"
        "] }) { results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced"]


def test_or(db):
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { or: ["
        '  { title: { exact: "Django deep dive" } }'
        "  { views: { gte: 100 } }"
        "] }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive", "GraphQL advanced"]


def test_not(db):
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { not: { status: { exact: DRAFT } } }) "
        "{ results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


def test_nested_and_or_not(db):
    _Seed.seed()
    # published AND (views < 20 OR views >= 100), excluding the "advanced" one.
    data = _exec(
        "{ articles(filter: { "
        "  status: { exact: PUBLISHED } "
        "  or: [ { views: { lt: 20 } } { views: { gte: 100 } } ] "
        '  not: { title: { icontains: "advanced" } } '
        "}) { results { title } } }"
    )
    assert _titles(data) == ["GraphQL intro"]


# --------------------------------------------------------------------------- #
# Relations + distinct                                                          #
# --------------------------------------------------------------------------- #
def test_forward_relation_filter(db):
    _Seed.seed()
    data = _exec(
        '{ articles(filter: { author: { name: { icontains: "ada" } } }) '
        "{ results { title } } }"
    )
    assert _titles(data) == ["Django deep dive", "GraphQL intro"]


def test_reverse_to_many_relation_with_distinct(db):
    _Seed.seed()
    # Two of Ada's articles contain "GraphQL"/match the reverse filter; without
    # .distinct() the join would duplicate the author row.
    data = _exec(
        '{ authors(filter: { articles: { title: { icontains: "graphql" } } }) '
        "{ results { name } totalCount } }"
    )
    names = sorted(r["name"] for r in data["authors"]["results"])
    # Ada (1 matching article) and Grace (1 matching article); each appears once.
    assert names == ["Ada Lovelace", "Grace Hopper"]
    assert data["authors"]["totalCount"] == 2


def test_empty_filter_is_noop(db):
    _Seed.seed()
    data = _exec("{ articles(filter: {}) { totalCount } }")
    assert data["articles"]["totalCount"] == 3


# --------------------------------------------------------------------------- #
# to_q unit tests                                                              #
# --------------------------------------------------------------------------- #
def test_to_q_multiple_keys_anded():
    q, many = to_q({"views": {"gt": 1}, "status": {"exact": "x"}}, Article)
    assert not many
    assert q.children  # AND of two field leaves


def test_to_q_or_empty_contributes_nothing():
    q, _ = to_q({"or": []}, Article)
    assert q == models.Q()


def test_to_q_not_negates():
    q, _ = to_q({"not": {"views": {"exact": 1}}}, Article)
    assert q.negated or any(getattr(c, "negated", False) for c in q.children)


def test_to_q_relation_sets_distinct_for_to_many():
    q, many = to_q({"articles": {"title": {"exact": "x"}}}, Author)
    assert many is True
    assert "articles__title__exact" in str(q)


def test_to_q_range_validates_length():
    import pytest
    from graphql import GraphQLError

    with pytest.raises(GraphQLError):
        to_q({"views": {"range": [1]}}, Article)


def test_to_q_pk_lookups_on_relation():
    q, _ = to_q({"author": {"exact": 5}}, Article)
    assert "author__exact" in str(q)


# --------------------------------------------------------------------------- #
# List-form filter_fields use the default (type-derived) lookup set            #
# --------------------------------------------------------------------------- #
RL = Registry()


class ArticleListTypeListForm(DjangoListObjectType):
    class Meta:
        model = Article
        registry = RL
        # List form -> each field gets the type-derived default lookup set.
        filter_fields = ["title", "views"]


class _ListFormQuery(graphene.ObjectType):
    items = DjangoListObjectField(ArticleListTypeListForm)


_list_form_schema = Schema(query=_ListFormQuery)


def test_list_form_default_lookups_present():
    type_map = _list_form_schema.graphql_schema.type_map
    # Text field default set: exact, in, isnull, icontains, istartswith.
    title_lookups = set(type_map["ArticleTitleLookups"].fields)
    assert {"exact", "in", "isnull", "icontains", "istartswith"} <= title_lookups
    # Ordered field default set: + gt/gte/lt/lte/range.
    views_lookups = set(type_map["ArticleViewsLookups"].fields)
    assert {"exact", "in", "isnull", "gt", "gte", "lt", "lte", "range"} <= views_lookups


def test_list_form_default_lookups_filter(db):
    a = Author.objects.create(name="Z")
    Article.objects.create(title="alpha", views=1, author=a)
    Article.objects.create(title="beta", views=9, author=a)

    result = _list_form_schema.execute(
        '{ items(filter: { title: { istartswith: "al" } }) { results { title } } }'
    )
    assert result.errors is None, result.errors
    titles = [r["title"] for r in result.data["items"]["results"]]
    assert titles == ["alpha"]
