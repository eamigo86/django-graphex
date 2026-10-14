"""Bounded optimizer traversal of valid repeated-fragment DAGs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from graphql import build_schema, graphql_sync, parse

import django_graphex.utils as utils
from tests.models import AuditArticle, Author, Post
from tests.test_optimizer_phase_d import _AuthorTypePromo, _promo_schema


def _repeated_fragment_document(levels: int) -> tuple[Any, dict[str, Any]]:
    """Build a valid acyclic graph with two spreads at each level.

    Args:
        levels: Number of named fragment levels.

    Returns:
        The root field selection and named fragment definitions.
    """
    definitions = ["query Q { user { ...F0 } }"]
    for level in range(levels):
        selected = (
            f"...F{level + 1} ...F{level + 1}" if level + 1 < levels else "username"
        )
        definitions.append(f"fragment F{level} on User {{ {selected} }}")
    document = parse("\n".join(definitions))
    operation = document.definitions[0]
    selection = operation.selection_set.selections[0].selection_set
    fragments = {fragment.name.value: fragment for fragment in document.definitions[1:]}
    return selection, fragments


@pytest.mark.parametrize(
    "name",
    [
        "recursive_params",
        "_collect_only_fields",
        "_collect_only_fields_is_full_load",
        "_collect_prefetch_only_sets",
        "_walk_filtered_prefetches",
        "_walk_annotated_fields",
    ],
)
def test_valid_repeated_fragment_graph_has_bounded_optimizer_visits(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Visit each equivalent selection context once, not once per spread path.

    Args:
        name: Optimizer collector whose recursive entries are counted.
        monkeypatch: Replaces the collector with a counting wrapper.
    """
    selection, fragments = _repeated_fragment_document(8)
    schema = build_schema("type Query { user: User! } type User { username: String! }")
    user_type = schema.get_type("User")
    model = get_user_model()
    info = SimpleNamespace(
        fragments=fragments,
        variable_values={},
        schema=schema,
        return_type=user_type,
    )
    source_type = SimpleNamespace(_meta=SimpleNamespace(fields={}))
    calls = 0
    original = getattr(utils, name)

    def counted(*args: Any, **kwargs: Any) -> Any:
        """Count recursive entries while preserving the original result.

        Args:
            *args: Positional collector arguments.
            **kwargs: Keyword collector arguments.

        Returns:
            The original collector result.
        """
        nonlocal calls
        calls += 1
        if calls > 64:
            pytest.fail(f"{name} expanded a repeated fragment more than 64 times")
        return original(*args, **kwargs)

    monkeypatch.setattr(utils, name, counted)
    if name == "recursive_params":
        selected: list[str] = []
        prefetched: list[str] = []
        counted(
            selection, fragments, {}, selected, prefetched, current_type_name="User"
        )
        assert selected == prefetched == []
    elif name == "_collect_only_fields":
        assert counted(model, selection, fragments, current_type_name="User")
    elif name == "_collect_only_fields_is_full_load":
        assert counted(model, selection, fragments, current_type_name="User") is False
    elif name == "_collect_prefetch_only_sets":
        assert (
            counted(model, selection, fragments, gql_type=user_type, schema=schema)
            == {}
        )
    elif name == "_walk_filtered_prefetches":
        out: list[Any] = []
        seen: dict[str, Any] = {}
        counted(user_type, model, selection, "", info, out, seen)
        assert out == [] and seen == {}
    else:
        annotations: dict[str, Any] = {}
        aliases: dict[str, Any] = {}
        names: set[str] = set()
        counted(
            user_type,
            source_type,
            selection,
            info,
            annotations,
            aliases,
            names,
        )
        assert annotations == aliases == {} and names == set()


def test_reused_fragment_keeps_distinct_relation_path_contexts() -> None:
    """Retain both foreign-key paths when they share one fragment definition.

    The same fragment must be planned separately for each ORM relation prefix.
    """
    document = parse(
        "{ articles { createdBy { ...EditorBits } updatedBy { ...EditorBits } } } "
        "fragment EditorBits on Editor { name }"
    )
    selection = document.definitions[0].selection_set.selections[0].selection_set
    fragments = {"EditorBits": document.definitions[1]}
    relation_map = utils._relation_field_map(AuditArticle)
    selected: list[str] = []
    prefetched: list[str] = []

    utils.recursive_params(
        selection,
        fragments,
        relation_map,
        selected,
        prefetched,
        current_model=AuditArticle,
    )
    projected = utils._collect_only_fields(AuditArticle, selection, fragments)

    assert set(selected) == {"created_by", "updated_by"}
    assert prefetched == []
    assert {"created_by__name", "updated_by__name"} <= set(projected)


def test_bounded_promotion_iterator_handles_absent_and_cyclic_internal_inputs() -> None:
    """Keep defensive no-selection and active-cycle guards in the set walker.

    These are internal AST inputs, not valid executable GraphQL documents.
    """
    schema = build_schema("type Query { user: User! } type User { username: String! }")
    user_type = schema.get_type("User")
    document = parse(
        "{ user { ...Cycle } } fragment Cycle on User { username ...Cycle }"
    )
    selection = document.definitions[0].selection_set.selections[0].selection_set
    fragments = {"Cycle": document.definitions[1]}

    assert (
        list(
            utils._iter_unique_promotion_fields(None, user_type, schema, fragments, {})
        )
        == []
    )
    assert [
        field.name.value
        for field in utils._iter_unique_promotion_fields(
            selection, user_type, schema, fragments, {}
        )
    ] == ["username"]


@pytest.mark.django_db
def test_promotion_consumer_bounds_repeated_spreads_without_changing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build one promotion plan per context while returning the same annotation.

    Args:
        monkeypatch: Replaces the public-shaped field walker with a counter.
    """
    author = Author.objects.create(name="Ada", bio="")
    Post.objects.create(title="P", author=author)
    author_type = _AuthorTypePromo._meta.graphql_output_type.name
    definitions = ["{ allPosts { results { author { name ...F0 } } } }"]
    for level in range(8):
        selected = f"...F{level + 1} ...F{level + 1}" if level < 7 else "postCount"
        definitions.append(f"fragment F{level} on {author_type} {{ {selected} }}")
    query = "\n".join(definitions)
    visits = 0
    walker_name = (
        "_iter_unique_promotion_fields"
        if hasattr(utils, "_iter_unique_promotion_fields")
        else "_iter_promotion_fields"
    )
    original = getattr(utils, walker_name)

    def counted(*args: Any, **kwargs: Any) -> Any:
        """Count AST expansion entries without changing yielded fields.

        Args:
            *args: Positional walker arguments.
            **kwargs: Keyword walker arguments.

        Returns:
            The original field iterator.
        """
        nonlocal visits
        visits += 1
        if visits > 64:
            pytest.fail("promotion expanded a repeated fragment more than 64 times")
        return original(*args, **kwargs)

    monkeypatch.setattr(utils, walker_name, counted)
    with CaptureQueriesContext(connection) as captured:
        result = graphql_sync(_promo_schema.graphql_schema, query)
    monkeypatch.setattr(utils, walker_name, original)
    with CaptureQueriesContext(connection) as flat_captured:
        flat = graphql_sync(
            _promo_schema.graphql_schema,
            "{ allPosts { results { author { name postCount } } } }",
        )

    assert result.errors is None
    assert flat.errors is None
    assert result.data == flat.data
    assert result.data["allPosts"]["results"][0]["author"]["postCount"] == 1
    assert len(captured) == len(flat_captured) == 2
