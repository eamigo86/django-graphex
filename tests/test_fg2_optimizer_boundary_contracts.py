"""Selected optimizer column and fragment boundary contracts."""

from __future__ import annotations

import pytest
from graphql import parse

from django_graphex.utils import (
    _collect_only_fields_is_full_load,
    _collect_prefetch_only_sets,
    _compute_child_only,
)
from tests.models import Author, Post
from tests.test_optimizer_phase_d import _AuthorTypePromo, _PostListTypePromo


@pytest.mark.parametrize(
    ("selected", "full_load"),
    [
        ("displayName", True),
        ("name", False),
        ("postCount", False),
    ],
)
def test_named_author_fragment_distinguishes_computed_and_stored_leaves(
    selected: str, full_load: bool
) -> None:
    """Avoid narrow row loading only for computed fragment leaves.

    Args:
        selected: The leaf selected by the named fragment.
        full_load: Whether the model requires an unrestricted row.
    """
    document = parse(
        f"{{ author {{ ...Selected }} }} fragment Selected on Author {{ {selected} }}"
    )
    selection = document.definitions[0].selection_set.selections[0].selection_set
    fragments = {"Selected": document.definitions[1]}

    assert (
        _collect_only_fields_is_full_load(
            Author,
            selection,
            fragments,
            annotated_names={"post_count"},
            current_type_name="Author",
        )
        is full_load
    )


def test_computed_leaf_and_annotation_keep_annotated_full_load_plan() -> None:
    """Retain the aggregate while avoiding an unsafe partial row load.

    A computed leaf needs its full model row, but the selected aggregate must
    still be attached to the child query.
    """
    document = parse("{ post { coAuthors { displayName postCount } } }")
    selection = (
        document.definitions[0]
        .selection_set.selections[0]
        .selection_set.selections[0]
        .selection_set
    )
    plan = _compute_child_only(
        Author,
        Post._meta.get_field("co_authors"),
        selection,
        {},
        child_gql_type=_AuthorTypePromo._meta.graphql_output_type,
        child_graphene_type=_AuthorTypePromo,
    )

    assert plan is not None
    assert plan.only_cols == []
    assert "_gqx_ann_post_count" in plan.child_annotations


def test_reverse_fk_selected_owner_column_occurs_once() -> None:
    """Preserve one FK-back key when the child also selects its owner.

    The narrowed child query needs both its selected fields and one stable
    parent-link column for Django's reverse relation matching.
    """
    document = parse("{ author { posts { title author { id } } } }")
    selection = (
        document.definitions[0]
        .selection_set.selections[0]
        .selection_set.selections[0]
        .selection_set
    )
    plan = _compute_child_only(
        Post,
        Author._meta.get_field("posts"),
        selection,
        {},
    )

    assert plan is not None
    assert plan.only_cols.count("author_id") == 1
    assert "author" in plan.child_select
    assert "author__id" in plan.only_cols
    assert "title" in plan.only_cols


def test_registered_wrapper_descends_into_promoted_relation() -> None:
    """Resolve a wrapper's row type before planning its annotated FK.

    The annotation plan belongs to the inner row relation, not to the
    transparent list wrapper itself.
    """
    document = parse("{ allPosts { results { author { name postCount } } } }")
    selection = document.definitions[0].selection_set.selections[0].selection_set
    wrapper_type = _PostListTypePromo._meta.graphql_output_type
    plans = _collect_prefetch_only_sets(
        Post,
        selection,
        {},
        gql_type=wrapper_type,
        promoted_lookups={"author"},
    )

    assert "author" in plans
    assert "_gqx_ann_post_count" in plans["author"].child_annotations
    assert "name" in plans["author"].only_cols
