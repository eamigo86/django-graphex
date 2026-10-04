"""GraphQL fragment contracts for annotated select-to-prefetch promotion."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from tests.models import Author, Post
from tests.test_optimizer_phase_d import (
    _AuthorTypePromo,
    _PostListTypePromo,
    _PostTypePromo,
    _promo_schema,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "variant",
    [
        "flat",
        "inline-author",
        "named-author",
        "inline-wrapper",
        "named-wrapper",
        "aliased-author",
    ],
)
def test_annotated_author_inside_valid_fragments_matches_flat_selection(
    variant: str,
) -> None:
    """Return the related annotation through valid author and wrapper fragments.

    Args:
        variant: The GraphQL selection shape under test.
    """
    author = Author.objects.create(name="Ada", bio="")
    Post.objects.create(title="P", author=author)
    author_type = _AuthorTypePromo._meta.graphql_output_type.name
    wrapper_type = _PostListTypePromo._meta.graphql_output_type.name

    if variant == "flat":
        selected = "results { author { name postCount } }"
        definition = ""
    elif variant == "inline-author":
        selected = (
            f"results {{ author {{ ... on {author_type} {{ name postCount }} }} }}"
        )
        definition = ""
    elif variant == "named-author":
        selected = "results { author { ...AuthorCounts } }"
        definition = f"fragment AuthorCounts on {author_type} {{ name postCount }}"
    elif variant == "inline-wrapper":
        selected = (
            f"... on {wrapper_type} {{ results {{ author {{ name postCount }} }} }}"
        )
        definition = ""
    elif variant == "named-wrapper":
        selected = "...PostResults"
        definition = (
            f"fragment PostResults on {wrapper_type} "
            "{ results { author { name postCount } } }"
        )
    else:
        selected = "results { writer: author { name count: postCount } }"
        definition = ""

    query = f"{{ allPosts {{ {selected} }} }} {definition}"
    with CaptureQueriesContext(connection) as captured:
        result = graphql_sync(_promo_schema.graphql_schema, query)

    assert result.errors is None
    row = result.data["allPosts"]["results"][0]
    nested = row["writer" if variant == "aliased-author" else "author"]
    assert nested["name"] == "Ada"
    assert nested["count" if variant == "aliased-author" else "postCount"] == 1
    sql = [item["sql"] for item in captured]
    assert len(sql) == 2
    assert any("_gqx_ann_post_count" in statement for statement in sql)


@pytest.mark.django_db
@pytest.mark.parametrize("with_count", [False, True])
def test_fragment_directive_controls_annotation_fetch(with_count: bool) -> None:
    """Apply bound include variables before choosing annotation prefetch.

    Args:
        with_count: Whether the fragment's annotated field is selected.
    """
    author = Author.objects.create(name="Ada", bio="")
    Post.objects.create(title="P", author=author)
    author_type = _AuthorTypePromo._meta.graphql_output_type.name
    query = (
        "query Count($withCount: Boolean!) { allPosts { results { "
        "author { name ...AuthorCounts @include(if: $withCount) } "
        "} } } "
        f"fragment AuthorCounts on {author_type} {{ postCount }}"
    )

    with CaptureQueriesContext(connection) as captured:
        result = graphql_sync(
            _promo_schema.graphql_schema,
            query,
            variable_values={"withCount": with_count},
        )

    assert result.errors is None
    nested = result.data["allPosts"]["results"][0]["author"]
    assert nested["name"] == "Ada"
    sql = [item["sql"] for item in captured]
    if with_count:
        assert nested["postCount"] == 1
        assert len(sql) == 2
        assert any("_gqx_ann_post_count" in statement for statement in sql)
    else:
        assert "postCount" not in nested
        assert len(sql) == 1
        assert all("_gqx_ann_post_count" not in statement for statement in sql)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "variant",
    [
        "direct",
        "named-all-levels",
        "inline-all-levels",
        "untyped-inline",
        "repeated-spread",
        "count-and-data",
    ],
)
def test_fragment_layers_keep_distinct_author_aggregate_values(
    variant: str,
) -> None:
    """Keep real aggregates when wrappers, rows and relations use fragments.

    Args:
        variant: Valid selection nesting to exercise.
    """
    ada = Author.objects.create(name="Ada", bio="")
    grace = Author.objects.create(name="Grace", bio="")
    Post.objects.create(title="First", author=ada)
    Post.objects.create(title="Second", author=ada)
    Post.objects.create(title="Third", author=grace)
    author_type = _AuthorTypePromo._meta.graphql_output_type.name
    post_type = _PostTypePromo._meta.graphql_output_type.name
    wrapper_type = _PostListTypePromo._meta.graphql_output_type.name

    definition = ""
    if variant in {"direct", "count-and-data"}:
        count = "totalCount " if variant == "count-and-data" else ""
        selected = (
            f"{count}rows: results {{ title writer: author "
            "{ name tally: postCount } }"
        )
    elif variant == "named-all-levels":
        selected = "...Wrap"
        definition = (
            f"fragment Wrap on {wrapper_type} "
            "{ rows: results { ...PostBits } } "
            f"fragment PostBits on {post_type} "
            "{ title writer: author { ...Owner } } "
            f"fragment Owner on {author_type} {{ name ...Counts }} "
            f"fragment Counts on {author_type} {{ tally: postCount }}"
        )
    elif variant == "inline-all-levels":
        selected = (
            f"... on {wrapper_type} {{ rows: results {{ "
            f"... on {post_type} {{ title writer: author {{ "
            f"... on {author_type} {{ name tally: postCount }} "
            "} } } }"
        )
    elif variant == "untyped-inline":
        selected = (
            "... { rows: results { ... { title writer: author "
            "{ ... { name tally: postCount } } } } }"
        )
    else:
        selected = "rows: results { title writer: author { ...Counts ...Counts } }"
        definition = f"fragment Counts on {author_type} {{ name tally: postCount }}"

    query = f"{{ shelf: allPosts {{ {selected} }} }} {definition}"
    with CaptureQueriesContext(connection) as captured:
        result = graphql_sync(_promo_schema.graphql_schema, query)

    assert result.errors is None
    rows = result.data["shelf"]["rows"]
    assert len(rows) == 3
    assert sorted(row["title"] for row in rows) == ["First", "Second", "Third"]
    for row in rows:
        author = row["writer"]
        assert author["tally"] == (2 if author["name"] == "Ada" else 1)
    sql = [entry["sql"] for entry in captured]
    expected = 3 if variant == "count-and-data" else 2
    assert len(sql) == expected
    assert any("_gqx_ann_post_count" in statement for statement in sql)
    if variant == "count-and-data":
        assert result.data["shelf"]["totalCount"] == 3


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("include", "skip"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_nested_fragment_directives_control_real_aggregate(
    include: bool, skip: bool
) -> None:
    """Apply both bound directives before adding the related annotation.

    Args:
        include: Whether to include the named spread.
        skip: Whether to skip its untyped inline child.
    """
    ada = Author.objects.create(name="Ada", bio="")
    Post.objects.create(title="First", author=ada)
    author_type = _AuthorTypePromo._meta.graphql_output_type.name
    query = (
        "query Controls($take: Boolean!, $hide: Boolean!) { "
        "allPosts { results { author { name ...Stats @include(if: $take) } } } } "
        f"fragment Stats on {author_type} "
        "{ ... @skip(if: $hide) { postCount } }"
    )
    with CaptureQueriesContext(connection) as captured:
        result = graphql_sync(
            _promo_schema.graphql_schema,
            query,
            variable_values={"take": include, "hide": skip},
        )

    assert result.errors is None
    owner = result.data["allPosts"]["results"][0]["author"]
    assert owner["name"] == "Ada"
    selected = include and not skip
    assert owner.get("postCount") == (1 if selected else None)
    sql = [entry["sql"] for entry in captured]
    assert len(sql) == (2 if selected else 1)
    assert any("_gqx_ann_post_count" in statement for statement in sql) is selected
