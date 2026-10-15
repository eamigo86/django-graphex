"""Public regression for explicit AND branches across multi-valued relations."""

from __future__ import annotations

import json
import sys
import types

import pytest
from django.db import connection, models
from django.db.models import F
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import path
from graphql import Undefined

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.filtering.backend import NativeFilterBackend
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair


class AndManyTag(models.Model):
    """Tag used to distinguish same-row and distinct-row M2M matches.

    Its label and color let two branches select separate rows.
    """

    label = models.CharField(max_length=20)
    color = models.CharField(max_length=20)

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        app_label = "tests"
        db_table = "t11c_and_many_tag"


class AndManyPost(models.Model):
    """Public query root with M2M tags and reverse-FK comments.

    Both relation paths begin at the same parent row.
    """

    title = models.CharField(max_length=40)
    tags = models.ManyToManyField(AndManyTag, related_name="posts")

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        app_label = "tests"
        db_table = "t11c_and_many_post"


class AndManyOwner(models.Model):
    """A to-one hop below the reverse-FK comments relation.

    It proves a nested path does not unbind its parent comment.
    """

    name = models.CharField(max_length=20)

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        app_label = "tests"
        db_table = "t11c_and_many_owner"


class AndManyComment(models.Model):
    """Reverse-FK child used to test independent AND branches.

    Two comments can satisfy different predicates for one post.
    """

    post = models.ForeignKey(
        AndManyPost, related_name="comments", on_delete=models.CASCADE
    )
    label = models.CharField(max_length=20)
    color = models.CharField(max_length=20)
    note = models.CharField(max_length=20, null=True)
    owner = models.ForeignKey(AndManyOwner, on_delete=models.CASCADE)

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        app_label = "tests"
        db_table = "t11c_and_many_comment"


registry = Registry()


class AndManyTagType(DjangoObjectType):
    """Publish the tag relation as a selectable output type.

    The filter compiler requires a published related target.
    """

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        model = AndManyTag
        registry = registry
        only_fields = ("label", "color")


class AndManyCommentType(DjangoObjectType):
    """Publish the reverse-FK target for native filter input construction.

    The projected columns include every tested child lookup.
    """

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        model = AndManyComment
        registry = registry
        only_fields = ("label", "color", "note", "owner")


class AndManyOwnerType(DjangoObjectType):
    """Publish the second hop of a multi-hop relation filter.

    Its name field is visible to the generated input.
    """

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        model = AndManyOwner
        registry = registry
        only_fields = ("name",)


class AndManyPostList(DjangoListObjectType):
    """Expose both to-many paths in the generated filter input.

    The declared paths cover direct and multi-hop predicates.
    """

    class Meta:
        """Configure the test-local model or GraphQL type.

        The declaration keeps the filter surface explicit.
        """

        model = AndManyPost
        registry = registry
        filter_fields = {
            "title": ("exact",),
            "tags__label": ("exact",),
            "tags__color": ("exact",),
            "comments__label": ("exact",),
            "comments__color": ("exact",),
            "comments__note": ("exact", "isnull"),
            "comments__owner__name": ("exact",),
        }


class AndManyQuery(ObjectType):
    """Mount the public filtered-list resolver.

    The tests exercise the shipped HTTP view and backend.
    """

    posts = DjangoListObjectField(AndManyPostList)


schema = DjangoGraphQLSchema(query=AndManyQuery, registries=isolated_pair(registry))
urlconf = types.ModuleType("t11c_and_many_urls")
urlconf.urlpatterns = [
    path(
        "graphql/",
        __import__(
            "django_graphex.views", fromlist=["GraphQLView"]
        ).GraphQLView.as_view(schema=schema),
    ),
]
sys.modules[urlconf.__name__] = urlconf


def _payload(query: str, variables: dict | None = None) -> dict:
    """Execute a public GraphQL request and return its successful JSON payload.

    Args:
        query: Complete GraphQL query document.
        variables: Optional GraphQL variables.

    Returns:
        The parsed response payload.
    """
    body = {"query": query}
    if variables is not None:
        body["variables"] = variables
    with override_settings(ROOT_URLCONF=urlconf.__name__):
        response = Client().post(
            "/graphql/", data=json.dumps(body), content_type="application/json"
        )
    payload = json.loads(response.content)
    assert response.status_code == 200, payload
    assert "errors" not in payload, payload
    return payload


def _post(query: str, variables: dict | None = None) -> list[str]:
    """Execute one public HTTP query and return sorted post titles.

    Args:
        query: Complete GraphQL query document.
        variables: Optional GraphQL variables.

    Returns:
        Sorted titles returned by the public filtered list.
    """
    payload = _payload(query, variables)
    return sorted(row["title"] for row in payload["data"]["posts"]["results"])


def _seed() -> None:
    """Create same-row, split-row, single-side, and absent-side controls.

    The same rows serve M2M and reverse-FK assertions.
    """
    owner_x = AndManyOwner.objects.create(name="owner-x")
    owner_y = AndManyOwner.objects.create(name="owner-y")
    x_red = AndManyTag.objects.create(label="x", color="red")
    y_blue = AndManyTag.objects.create(label="y", color="blue")
    x_blue = AndManyTag.objects.create(label="x", color="blue")
    split = AndManyPost.objects.create(title="split")
    split.tags.add(x_red, y_blue)
    same = AndManyPost.objects.create(title="same")
    same.tags.add(x_blue)
    only_x = AndManyPost.objects.create(title="only-x")
    only_x.tags.add(x_red)
    AndManyPost.objects.create(title="absent")

    for post, label, color, owner in (
        (split, "x", "red", owner_x),
        (split, "y", "blue", owner_y),
        (same, "x", "blue", owner_x),
        (only_x, "x", "red", owner_x),
    ):
        AndManyComment.objects.create(post=post, label=label, color=color, owner=owner)


@pytest.mark.django_db(transaction=True)
def test_public_m2m_and_branches_match_distinct_rows() -> None:
    """Two explicit tag branches may match different tags of one post.

    The split post has no tag that satisfies both labels.
    """
    _seed()
    query = (
        "{ posts(filter: { and: ["
        '{ tags: { label: { exact: "x" } } }, '
        '{ tags: { label: { exact: "y" } } }'
        "] }) { results { title } } }"
    )
    assert _post(query) == ["split"]


@pytest.mark.django_db(transaction=True)
def test_public_reverse_fk_and_branches_match_distinct_rows() -> None:
    """Two explicit reverse-FK branches may match different comments.

    The split post has separate matching child rows.
    """
    _seed()
    query = (
        "{ posts(filter: { and: ["
        '{ comments: { label: { exact: "x" } } }, '
        '{ comments: { label: { exact: "y" } } }'
        "] }) { results { title } } }"
    )
    assert _post(query) == ["split"]


@pytest.mark.django_db(transaction=True)
def test_public_and_keeps_relation_object_same_row() -> None:
    """Only explicit branches, not one relation object, permit split rows.

    The grouped form retains a single related-row witness.
    """
    _seed()
    separate_tags = (
        "{ posts(filter: { and: ["
        '{ tags: { label: { exact: "x" } } }, '
        '{ tags: { color: { exact: "blue" } } }'
        "] }) { results { title } } }"
    )
    grouped_tags = (
        '{ posts(filter: { tags: { label: { exact: "x" }, '
        'color: { exact: "blue" } } }) { results { title } } }'
    )
    grouped_comments = (
        '{ posts(filter: { comments: { label: { exact: "x" }, '
        'color: { exact: "blue" } } }) { results { title } } }'
    )
    grouped_nested_and = (
        "{ posts(filter: { tags: { and: ["
        '{ label: { exact: "x" } }, { color: { exact: "blue" } }'
        "] } }) { results { title } } }"
    )
    sibling_and_branch = (
        '{ posts(filter: { tags: { label: { exact: "x" } }, and: ['
        '{ tags: { color: { exact: "blue" } } }'
        "] }) { results { title } } }"
    )
    assert _post(separate_tags) == ["same", "split"]
    assert _post(grouped_tags) == ["same"]
    assert _post(grouped_comments) == ["same"]
    assert _post(grouped_nested_and) == ["same"]
    assert _post(sibling_and_branch) == ["same", "split"]


@pytest.mark.django_db(transaction=True)
def test_public_nested_or_not_and_multihop_correlation() -> None:
    """Nested Boolean branches stay composable without unbinding a comment.

    The owner hop must remain anchored to its comment.
    """
    _seed()
    nested_or = (
        "{ posts(filter: { or: ["
        '{ and: [{ comments: { owner: { name: { exact: "owner-x" } } } }, '
        '{ comments: { owner: { name: { exact: "owner-y" } } } }] }, '
        '{ title: { exact: "absent" } }'
        "] }) { results { title } } }"
    )
    nested_not = (
        "{ posts(filter: { not: { and: ["
        '{ comments: { label: { exact: "x" } } }, '
        '{ comments: { label: { exact: "y" } } }'
        "] } }) { results { title } } }"
    )
    grouped_multihop = (
        '{ posts(filter: { comments: { label: { exact: "x" }, '
        'owner: { name: { exact: "owner-y" } } } }) '
        "{ results { title } } }"
    )
    assert _post(nested_or) == ["absent", "split"]
    assert _post(nested_not) == ["absent", "only-x", "same"]
    assert _post(grouped_multihop) == []


@pytest.mark.django_db(transaction=True)
def test_public_exact_null_and_isnull_keep_absent_reverse_row() -> None:
    """A missing reverse child still matches SQL NULL under explicit AND.

    The existing left-join null behavior remains observable.
    """
    _seed()
    for lookup in ("exact: null", "isnull: true"):
        query = (
            "{ posts(filter: { and: ["
            "{ comments: { note: { " + lookup + " } } }, "
            '{ title: { exact: "absent" } }'
            "] }) { results { title } } }"
        )
        assert _post(query) == ["absent"]


@pytest.mark.django_db(transaction=True)
def test_empty_boolean_operands_and_direct_many_ids() -> None:
    """Existing empty operands and direct relation IDs keep their contracts.

    The new planner may not invent classical Boolean identities.
    """
    _seed()
    tag_x = AndManyTag.objects.get(label="x", color="red")
    tag_y = AndManyTag.objects.get(label="y", color="blue")
    backend = NativeFilterBackend()
    pk_branch = {
        "and": [
            {"tags": {"exact": tag_x.pk}},
            {"tags": {"exact": tag_y.pk}},
        ]
    }
    assert list(
        backend.apply(AndManyPost.objects.all(), pk_branch).values_list(
            "title", flat=True
        )
    ) == ["split"]
    empty_branch = {
        "and": [
            {"tags": {"label": {"exact": "x"}}},
            {"or": [{}, {"title": {"exact": "split"}}]},
            {"or": []},
            {"not": {}},
        ]
    }
    assert list(
        backend.apply(AndManyPost.objects.all(), empty_branch).values_list(
            "title", flat=True
        )
    ) == ["split"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("unset", [None, Undefined])
def test_unset_boolean_children_keep_independent_branch(unset: object) -> None:
    """Unset children remain no-ops beside a real independent AND.

    Args:
        unset: Null or GraphQL's omitted-value sentinel.
    """
    _seed()
    value = {
        "title": unset,
        "or": [
            unset,
            {
                "and": [
                    {"tags": {"label": {"exact": "x"}}},
                    {"tags": {"label": {"exact": "y"}}},
                ]
            },
        ],
    }
    rows = NativeFilterBackend().apply(AndManyPost.objects.all(), value)
    assert list(rows.values_list("title", flat=True)) == ["split"]


@pytest.mark.django_db(transaction=True)
def test_scoped_queryset_alias_projection_and_one_sql() -> None:
    """The backend keeps incoming scope/alias/projection and stays one query.

    The SQL expression is compiled rather than evaluated per parent.
    """
    _seed()
    base = (
        AndManyPost.objects.using("default")
        .filter(title__in=("same", "split"))
        .annotate(title_copy=F("title"))
        .values("pk", "title_copy")
    )
    value = {
        "and": [
            {"tags": {"label": {"exact": "x"}}},
            {"tags": {"color": {"exact": "blue"}}},
        ]
    }
    with CaptureQueriesContext(connection) as captured:
        rows = list(NativeFilterBackend().apply(base, value))
    assert sorted(row["title_copy"] for row in rows) == ["same", "split"]
    assert len(captured.captured_queries) == 1
    assert "EXISTS" in captured.captured_queries[0]["sql"].upper()


@pytest.mark.django_db(transaction=True)
def test_public_paginated_count_and_variables() -> None:
    """Filtered count and ordered page honor literal and variable inputs.

    Pagination runs after the corrected filter predicate.
    """
    _seed()
    query = (
        "query ($filter: AndManyPostFilterInput) {"
        " posts(filter: $filter) {"
        ' results(limit: 1, ordering: "title") { title } totalCount'
        " } }"
    )
    payload = _payload(
        query,
        {
            "filter": {
                "and": [
                    {"tags": {"label": {"exact": "x"}}},
                    {"tags": {"color": {"exact": "blue"}}},
                ]
            }
        },
    )
    posts = payload["data"]["posts"]
    assert posts["totalCount"] == 2
    assert posts["results"] == [{"title": "same"}]
