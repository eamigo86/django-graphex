"""Native, "Q"-based filtering: lookups, and/or/not, relations, distinct.

Exercises the "filtering/" package end to end against a real native
"DjangoGraphQLSchema" plus unit tests for "to_q".
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import models
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.filtering.translate import to_q
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType

from ._schema_isolation import isolated_pair
from .models import Author

R = Registry()


# A model with a choices field + ordered fields, declared inline for the suite.
class Article(models.Model):
    """Throwaway model with a choices field, ordered fields, and a forward FK to "Author".

    Declared inline so the filtering suite does not depend on shared models.
    """

    STATUS = (("draft", "Draft"), ("published", "Published"))
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS, default="draft")
    views = models.IntegerField(default=0)
    published = models.DateField(null=True)
    author = models.ForeignKey(
        Author, related_name="articles", on_delete=models.CASCADE
    )

    class Meta:
        """Register the throwaway model under the "tests" app label.

        No other options are needed for this model.
        """

        app_label = "tests"


class ArticleListType(DjangoListObjectType):
    """ "Article" list type with a broad "filter_fields" mapping, used by the filtering suite.

    Covers exact/icontains/comparison/range/isnull lookups plus a relation.
    """

    class Meta:
        """Bind the list type to "Article" with per-field lookup sets.

        Includes a reach-through lookup on "author__name".
        """

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
    """ "Author" list type with reverse-relation "filter_fields", for the distinct-join tests.

    Exercises filtering through the reverse "articles" relation.
    """

    class Meta:
        """Bind the list type to "Author" with per-field lookup sets, including reverse relations.

        "articles__title"/"articles__status" reach through the reverse FK.
        """

        model = Author
        registry = R
        filter_fields = {
            "id": ("exact", "in"),
            "name": ("exact", "icontains"),
            "articles__title": ("icontains",),
            "articles__status": ("exact",),
        }


class Query(ObjectType):
    """Root query exposing the "articles" and "authors" filterable list fields.

    The only entry point for the schema built in this module.
    """

    articles = DjangoListObjectField(ArticleListType)
    authors = DjangoListObjectField(AuthorListType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))


def _exec(query: str) -> dict[str, Any]:
    """Execute a GraphQL document against the module's filtering schema.

    Args:
        query: The GraphQL query document to execute.

    Returns:
        The execution result's "data" mapping.
    """
    result = graphql_sync(schema.graphql_schema, query)
    assert result.errors is None, result.errors
    return result.data


def _titles(data: dict[str, Any], root: str = "articles") -> list[str]:
    """Extract and sort the "title" values from a query result's results list.

    Args:
        data: The GraphQL execution result's "data" mapping.
        root: The top-level field under "data" whose "results" are read.

    Returns:
        The sorted list of "title" strings.
    """
    return sorted(r["title"] for r in data[root]["results"])


# --------------------------------------------------------------------------- #
# Per-lookup mapping                                                            #
# --------------------------------------------------------------------------- #
class _Seed:
    """Shared fixture-data builder for the filtering tests below."""

    @classmethod
    def seed(cls) -> None:
        """Create two authors and three articles spanning the filterable field values."""
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


def test_exact(db: None) -> None:
    """The "exact" lookup on "title" matches only the exactly-equal article.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        '{ articles(filter: { title: { exact: "GraphQL intro" } }) '
        "{ results { title } } }"
    )
    assert _titles(data) == ["GraphQL intro"]


def test_icontains(db: None) -> None:
    """The "icontains" lookup on "title" matches case-insensitively across multiple rows.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        '{ articles(filter: { title: { icontains: "graphql" } }) '
        "{ results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


def test_in(db: None) -> None:
    """The "in" lookup on the choices-backed "status" enum matches every listed value.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { status: { in: [PUBLISHED] } }) { results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


def test_range(db: None) -> None:
    """The "range" lookup on "views" matches rows within the inclusive bounds.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { views: { range: [40, 120] } }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive", "GraphQL advanced"]


def test_ordered_comparisons(db: None) -> None:
    """Combining "gt" and "lte" on "views" narrows to the rows within both bounds.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { views: { gt: 10, lte: 50 } }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive"]


def test_isnull(db: None) -> None:
    """The "isnull" lookup on "published" matches rows with a NULL value.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { published: { isnull: true } }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive"]


def test_choices_field_via_enum(db: None) -> None:
    """The "status" choices field is filterable through its generated GraphQL enum.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    # The status field is exposed through its generated Enum.
    data = _exec(
        "{ articles(filter: { status: { exact: PUBLISHED } }) { results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


# --------------------------------------------------------------------------- #
# Logical composition                                                          #
# --------------------------------------------------------------------------- #
def test_and(db: None) -> None:
    """An "and" filter combines its children so only rows matching every child survive.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { and: ["
        '  { title: { icontains: "graphql" } }'
        "  { views: { gt: 50 } }"
        "] }) { results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced"]


def test_or(db: None) -> None:
    """An "or" filter combines its children so rows matching any child survive.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { or: ["
        '  { title: { exact: "Django deep dive" } }'
        "  { views: { gte: 100 } }"
        "] }) { results { title } } }"
    )
    assert _titles(data) == ["Django deep dive", "GraphQL advanced"]


def test_not(db: None) -> None:
    """A "not" filter excludes rows matching its child.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        "{ articles(filter: { not: { status: { exact: DRAFT } } }) "
        "{ results { title } } }"
    )
    assert _titles(data) == ["GraphQL advanced", "GraphQL intro"]


def test_nested_and_or_not(db: None) -> None:
    """Nested "and"/"or"/"not" combine correctly into a single composite filter.

    published AND (views < 20 OR views >= 100), excluding the "advanced" one.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
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
def test_forward_relation_filter(db: None) -> None:
    """Filtering on a forward relation's field ("author.name") reaches through the join correctly.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        '{ articles(filter: { author: { name: { icontains: "ada" } } }) '
        "{ results { title } } }"
    )
    assert _titles(data) == ["Django deep dive", "GraphQL intro"]


def test_reverse_to_many_relation_with_distinct(db: None) -> None:
    """Filtering on a reverse to-many relation does not duplicate the parent row across matching children.

    Two of Ada's articles contain "GraphQL"/match the reverse filter; without
    ".distinct()" the join would duplicate the author row.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec(
        '{ authors(filter: { articles: { title: { icontains: "graphql" } } }) '
        "{ results { name } totalCount } }"
    )
    names = sorted(r["name"] for r in data["authors"]["results"])
    # Ada (1 matching article) and Grace (1 matching article); each appears once.
    assert names == ["Ada Lovelace", "Grace Hopper"]
    assert data["authors"]["totalCount"] == 2


def test_empty_filter_is_noop(db: None) -> None:
    """An empty filter object matches every row, unfiltered.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    _Seed.seed()
    data = _exec("{ articles(filter: {}) { totalCount } }")
    assert data["articles"]["totalCount"] == 3


# --------------------------------------------------------------------------- #
# to_q unit tests                                                              #
# --------------------------------------------------------------------------- #
def test_to_q_multiple_keys_anded() -> None:
    """Multiple keys in one filter node are AND-ed together by "to_q".

    This test breaks if "to_q" stops combining sibling keys with AND.
    """
    q, many = to_q({"views": {"gt": 1}, "status": {"exact": "x"}}, Article)
    assert not many
    assert q.children  # AND of two field leaves


def test_to_q_or_empty_contributes_nothing() -> None:
    """An empty "or" list contributes an empty "Q()", not an error.

    This test breaks if an empty "or" list stops degrading to a no-op "Q".
    """
    q, _ = to_q({"or": []}, Article)
    assert q == models.Q()


def test_to_q_not_negates() -> None:
    """A "not" node negates its child condition.

    This test breaks if "to_q" stops negating the "not" child, either at
    the top-level "Q" or on one of its children.
    """
    q, _ = to_q({"not": {"views": {"exact": 1}}}, Article)
    assert q.negated or any(getattr(c, "negated", False) for c in q.children)


def test_to_q_relation_sets_distinct_for_to_many() -> None:
    """Filtering through a to-many relation field reports "many=True" and builds the double-underscore lookup.

    This test breaks if "to_q" stops flagging the to-many relation traversal
    or stops building the "articles__title__exact" lookup path.
    """
    q, many = to_q({"articles": {"title": {"exact": "x"}}}, Author)
    assert many is True
    assert "articles__title__exact" in str(q)


def test_to_q_range_validates_length() -> None:
    """A "range" lookup with fewer than two bounds raises "GraphQLError".

    This test breaks if the range-length validation stops rejecting a
    malformed single-element range list.
    """
    import pytest
    from graphql import GraphQLError

    with pytest.raises(GraphQLError):
        to_q({"views": {"range": [1]}}, Article)


def test_to_q_pk_lookups_on_relation() -> None:
    """Filtering a forward relation field directly with "exact" builds the pk-based lookup.

    This test breaks if a relation field filtered without drilling into a
    sub-field stops building the "author__exact" lookup.
    """
    q, _ = to_q({"author": {"exact": 5}}, Article)
    assert "author__exact" in str(q)


# --------------------------------------------------------------------------- #
# List-form filter_fields use the default (type-derived) lookup set            #
# --------------------------------------------------------------------------- #
RL = Registry()


class ArticleListTypeListForm(DjangoListObjectType):
    """ "Article" list type using the list form of "filter_fields" (default lookup sets).

    Contrasts with "ArticleListType", which declares explicit per-field
    lookup tuples.
    """

    class Meta:
        """Bind the list type to "Article" with a bare field-name list for "filter_fields".

        Each field falls back to its type-derived default lookup set.
        """

        model = Article
        registry = RL
        # List form -> each field gets the type-derived default lookup set.
        filter_fields = ["title", "views"]


class _ListFormQuery(ObjectType):
    """Root query exposing the list-form filterable "items" field."""

    items = DjangoListObjectField(ArticleListTypeListForm)


_list_form_schema = DjangoGraphQLSchema(
    query=_ListFormQuery, registries=isolated_pair(RL)
)


def test_list_form_default_lookups_present() -> None:
    """The list-form "filter_fields" derives the default lookup set per field type.

    This test breaks if the type-derived default lookup set stops including
    the expected text-field or ordered-field lookups.
    """
    type_map = _list_form_schema.graphql_schema.type_map
    # Text field default set: exact, in, isnull, icontains, istartswith.
    title_lookups = set(type_map["ArticleTitleLookups"].fields)
    assert {"exact", "in", "isnull", "icontains", "istartswith"} <= title_lookups
    # Ordered field default set: + gt/gte/lt/lte/range.
    views_lookups = set(type_map["ArticleViewsLookups"].fields)
    assert {"exact", "in", "isnull", "gt", "gte", "lt", "lte", "range"} <= views_lookups


def test_list_form_default_lookups_filter(db: None) -> None:
    """A default-derived lookup ("istartswith") from the list-form "filter_fields" actually filters.

    Args:
        db: Pytest-django's database-access fixture; grants this test
            permission to hit the database.
    """
    a = Author.objects.create(name="Z")
    Article.objects.create(title="alpha", views=1, author=a)
    Article.objects.create(title="beta", views=9, author=a)

    result = graphql_sync(
        _list_form_schema.graphql_schema,
        '{ items(filter: { title: { istartswith: "al" } }) { results { title } } }',
    )
    assert result.errors is None, result.errors
    titles = [r["title"] for r in result.data["items"]["results"]]
    assert titles == ["alpha"]
