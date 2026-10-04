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
