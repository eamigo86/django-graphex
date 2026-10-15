"""Public HTTP regression tests for explicit exact-null filtering."""

from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timezone
from typing import Any

from django.db import models
from django.test import Client, override_settings
from django.urls import path
from graphql import Undefined
from graphql.utilities import coerce_input_value

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.filtering.backend import NativeFilterBackend
from django_graphex.filtering.filter_field import apply_custom_filters
from django_graphex.filtering.native_schema import build_filter_input_type
from django_graphex.filtering.translate import _is_pk_lookups, to_q
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from django_graphex.views import GraphQLView

from ._schema_isolation import isolated_pair
from .models import Author, ScalarKindsModel
from .test_native_filtering import Article, _Seed, schema

_registry = Registry()


class ExactNullChoiceRow(models.Model):
    """Test a nullable choices field and nullable ordinary text together.

    Its table exists only in the disposable pytest database.
    """

    label = models.CharField(max_length=30)
    state = models.CharField(
        max_length=8, null=True, choices=(("open", "Open"), ("closed", "Closed"))
    )
    note = models.TextField(null=True)

    class Meta:
        """Register the isolated test model in the disposable tests app.

        No production migration or table is affected.
        """

        app_label = "tests"


class _FlatArticleType(DjangoObjectType):
    """Expose the same article rows through a flat filtered list."""

    class Meta:
        """Keep the flat filter declaration local to this regression schema."""

        model = Article
        registry = _registry
        filter_fields = {
            "published": ("exact", "isnull"),
            "title": ("exact",),
        }


class _FlatQuery(ObjectType):
    """Mount the flat-list frontend beside the list-object control."""

    flat_articles = DjangoFilterListField(_FlatArticleType)


_flat_schema = DjangoGraphQLSchema(
    query=_FlatQuery, registries=isolated_pair(_registry)
)
_urlconf = types.ModuleType("t11a_exact_null_urls")
_urlconf.urlpatterns = [
    path("list/", GraphQLView.as_view(schema=schema)),
    path("flat/", GraphQLView.as_view(schema=_flat_schema)),
]
sys.modules[_urlconf.__name__] = _urlconf


def _post(path_name: str, query: str, variables: dict[str, Any] | None = None) -> Any:
    """Execute a GraphQL request through the configured Django HTTP view.

    Args:
        path_name: Either the list-object or flat-list endpoint path.
        query: GraphQL document sent in the JSON request body.
        variables: Optional variable mapping for the document.

    Returns:
        The GraphQL data mapping after successful HTTP execution.
    """
    with override_settings(ROOT_URLCONF=_urlconf.__name__):
        response = Client().post(
            f"/{path_name}/",
            data=json.dumps({"query": query, "variables": variables}),
            content_type="application/json",
        )
    payload = json.loads(response.content)
    assert response.status_code == 200, payload
    assert "errors" not in payload, payload
    return payload["data"]


def _titles(
    path_name: str, query: str, variables: dict[str, Any] | None = None
) -> list[str]:
    """Return sorted article titles from either generated list frontend.

    Args:
        path_name: Either the list-object or flat-list endpoint path.
        query: GraphQL document sent in the JSON request body.
        variables: Optional variable mapping for the document.

    Returns:
        Sorted article titles from the response.
    """
    data = _post(path_name, query, variables)
    if path_name == "list":
        rows = data["articles"]["results"]
    else:
        rows = data["flatArticles"]
    return sorted(row["title"] for row in rows)


def test_public_literal_exact_null_is_distinct_from_omission(db: None) -> None:
    """Both list frontends select NULL rows only for explicit exact-null.

    Args:
        db: Enable the disposable Django test database.
    """
    _Seed.seed()
    cases = (
        (
            "list",
            "articles",
            "results { title }",
        ),
        ("flat", "flatArticles", "title"),
    )
    for path_name, field, selection in cases:
        explicit = (
            f"{{ {field}(filter: {{ published: {{ exact: null }} }}) "
            f"{{ {selection} }} }}"
        )
        omitted = f"{{ {field}(filter: {{ published: {{}} }}) {{ {selection} }} }}"
        assert _titles(path_name, explicit) == ["Django deep dive"]
        assert _titles(path_name, omitted) == [
            "Django deep dive",
            "GraphQL advanced",
            "GraphQL intro",
        ]


def test_public_variable_exact_null_is_distinct_from_omission(db: None) -> None:
    """Coerced explicit null remains distinct from an omitted lookup key.

    Args:
        db: Enable the disposable Django test database.
    """
    _Seed.seed()
    for path_name, field, selection in (
        ("list", "articles", "results { title }"),
        ("flat", "flatArticles", "title"),
    ):
        query = (
            f"query($filter: ArticleFilterInput) "
            f"{{ {field}(filter: $filter) {{ {selection} }} }}"
        )
        assert _titles(
            path_name, query, {"filter": {"published": {"exact": None}}}
        ) == ["Django deep dive"]
        assert _titles(path_name, query, {"filter": {"published": {}}}) == [
            "Django deep dive",
            "GraphQL advanced",
            "GraphQL intro",
        ]
        assert _titles(path_name, query, {"filter": {"title": {"exact": None}}}) == []


def test_native_coercion_preserves_lookup_presence() -> None:
    """Keep omitted and explicitly null lookup keys distinct after coercion.

    This is the native input-presence boundary required by the translator.
    """
    input_type = schema.graphql_schema.type_map["ArticleFilterInput"]
    assert coerce_input_value({"published": {}}, input_type) == {"published": {}}
    assert coerce_input_value({"published": {"exact": None}}, input_type) == {
        "published": {"exact": None}
    }


def test_public_exact_null_composes_without_changing_empty_nodes(db: None) -> None:
    """Nested Boolean operators preserve their existing empty-node policy.

    Args:
        db: Enable the disposable Django test database.
    """
    _Seed.seed()
    cases = (
        (
            'and: [{ published: { exact: null } }, { title: { exact: "Django deep dive" } }]',
            ["Django deep dive"],
        ),
        (
            'or: [{ published: { exact: null } }, { title: { exact: "GraphQL intro" } }]',
            ["Django deep dive", "GraphQL intro"],
        ),
        (
            "not: { published: { exact: null } }",
            ["GraphQL advanced", "GraphQL intro"],
        ),
        ("or: []", ["Django deep dive", "GraphQL advanced", "GraphQL intro"]),
        ("not: {}", ["Django deep dive", "GraphQL advanced", "GraphQL intro"]),
        ("or: [{}, { published: { exact: null } }]", ["Django deep dive"]),
        ("published: { isnull: true }", ["Django deep dive"]),
        ("published: { isnull: false }", ["GraphQL advanced", "GraphQL intro"]),
        (
            "published: { gt: null }",
            ["Django deep dive", "GraphQL advanced", "GraphQL intro"],
        ),
        ("published: null", ["Django deep dive", "GraphQL advanced", "GraphQL intro"]),
        ("status: { exact: null }", []),
    )
    for clause, expected in cases:
        query = f"{{ articles(filter: {{ {clause} }}) {{ results {{ title }} }} }}"
        assert _titles("list", query) == expected, clause
    assert _titles("list", "{ articles(filter: null) { results { title } } }") == [
        "Django deep dive",
        "GraphQL advanced",
        "GraphQL intro",
    ]


def test_exact_null_field_matrix_and_json_sql_null(db: None) -> None:
    """One predicate selects SQL NULL across scalar, date, time, FK and JSON.

    Args:
        db: Enable the disposable Django test database.
    """
    author = Author.objects.create(name="Exact null author")
    sql_null = ScalarKindsModel.objects.create(char="sql-null", json_field=None)
    ordinary = ScalarKindsModel.objects.create(
        char="ordinary",
        date=date(2024, 1, 1),
        datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        author=author,
        json_field={"key": "value"},
    )
    json_null = ScalarKindsModel.objects.create(
        char="json-null",
        date=date(2024, 1, 2),
        datetime=datetime(2024, 1, 2, tzinfo=timezone.utc),
        author=author,
        json_field={},
    )
    ScalarKindsModel.objects.filter(pk=json_null.pk).update(
        json_field=models.Value("null")
    )
    assert list(
        ScalarKindsModel.objects.filter(json_field__exact=None).values_list(
            "pk", flat=True
        )
    ) == [json_null.pk]
    backend = NativeFilterBackend()
    filter_input = build_filter_input_type(
        ScalarKindsModel,
        {
            "date": ("exact",),
            "datetime": ("exact",),
            "author": ("exact",),
            "json_field": ("exact", "isnull"),
            "char": ("exact",),
        },
        Registry(),
    )
    assert filter_input is not None
    for field_name, wire_name in (
        ("date", "date"),
        ("datetime", "datetime"),
        ("author", "author"),
        ("json_field", "jsonField"),
    ):
        value = coerce_input_value({wire_name: {"exact": None}}, filter_input)
        assert value == {field_name: {"exact": None}}
        result = backend.apply(ScalarKindsModel.objects.all(), value)
        assert list(result.values_list("pk", flat=True)) == [sql_null.pk], field_name
    assert (
        list(
            backend.apply(
                ScalarKindsModel.objects.all(), {"char": {"exact": None}}
            ).values_list("pk", flat=True)
        )
        == []
    )
    assert list(
        backend.apply(
            ScalarKindsModel.objects.all(), {"json_field": {"isnull": True}}
        ).values_list("pk", flat=True)
    ) == [sql_null.pk]
    assert ScalarKindsModel.objects.filter(pk=ordinary.pk).exists()


def test_nullable_choice_and_text_exact_null(db: None) -> None:
    """The generated enum and ordinary text inputs accept explicit null.

    Args:
        db: Enable the disposable Django test database.
    """
    null_row = ExactNullChoiceRow.objects.create(label="null", state=None, note=None)
    ExactNullChoiceRow.objects.create(label="value", state="open", note="present")
    filter_input = build_filter_input_type(
        ExactNullChoiceRow,
        {"state": ("exact", "isnull"), "note": ("exact",)},
        Registry(),
    )
    assert filter_input is not None
    for name in ("state", "note"):
        value = coerce_input_value({name: {"exact": None}}, filter_input)
        assert value == {name: {"exact": None}}
        assert list(
            NativeFilterBackend()
            .apply(ExactNullChoiceRow.objects.all(), value)
            .values_list("pk", flat=True)
        ) == [null_row.pk]


def test_direct_relation_and_unset_lookup_boundaries(db: None) -> None:
    """Direct FK-ID null is set while other null and Undefined remain unset.

    Args:
        db: Enable the disposable Django test database.
    """
    assert _is_pk_lookups({"exact": None}) is True
    assert _is_pk_lookups({"isnull": None}) is False
    assert _is_pk_lookups({"in": None}) is False
    assert _is_pk_lookups({"exact": Undefined}) is False
    q, many = to_q({"author": {"exact": None}}, ScalarKindsModel)
    assert q == models.Q(author__pk__isnull=True)
    assert many is False
    for value in (
        {"date": {"exact": Undefined}},
        {"date": {"gt": None}},
        {"date": None},
    ):
        assert to_q(value, ScalarKindsModel)[0] == models.Q()
    calls: list[Any] = []

    def custom(queryset: Any, info: Any, value: Any) -> Any:
        """Record whether an unrelated custom filter receives null.

        Args:
            queryset: Base queryset.
            info: Unused GraphQL resolver context.
            value: Supplied custom filter value.

        Returns:
            The unchanged queryset.
        """
        calls.append(value)
        return queryset

    queryset = ScalarKindsModel.objects.all()
    assert (
        apply_custom_filters(queryset, [("custom", custom, {})], None, {"custom": None})
        is queryset
    )
    assert calls == []


def test_to_many_null_keeps_distinct_and_nested_prefix(db: None) -> None:
    """Nullable nested leaves and direct to-many IDs retain traversal behavior.

    Args:
        db: Enable the disposable Django test database.
    """
    owner = Author.objects.create(name="Has null dates")
    other = Author.objects.create(name="No articles")
    Article.objects.create(title="A", published=None, author=owner)
    Article.objects.create(title="B", published=None, author=owner)
    nested = {"articles": {"published": {"exact": None}}}
    q, many = to_q(nested, Author)
    assert q == models.Q(articles__published__isnull=True)
    assert many is True
    result = NativeFilterBackend().apply(Author.objects.all(), nested)
    # The left join also exposes NULL for an author with no related articles;
    # exact-null deliberately follows the pre-existing isnull:true predicate.
    assert set(result.values_list("pk", flat=True)) == {owner.pk, other.pk}
    assert result.count() == 2
    assert "DISTINCT" in str(result.query)
    direct_q, direct_many = to_q({"articles": {"exact": None}}, Author)
    assert direct_q == models.Q(articles__pk__isnull=True)
    assert direct_many is True
    assert list(
        NativeFilterBackend()
        .apply(Author.objects.all(), {"articles": {"exact": None}})
        .values_list("pk", flat=True)
    ) == [other.pk]
