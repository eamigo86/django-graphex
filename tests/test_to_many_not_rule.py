"""Pin the "not inside a to-many relation object" rule against the ORM."""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from django.db.models import Exists, OuterRef, Q

from django_graphex.filtering.backend import NativeFilterBackend

from .test_and_many_filtering import AndManyComment, AndManyOwner, AndManyPost
from .test_and_many_filtering import AndManyTag as Tag


def _label(value: str) -> dict:
    """Return a tag label predicate inside a relation object.

    Args:
        value: Tag label.

    Returns:
        A relation-object fragment.
    """
    return {"label": {"exact": value}}


def _has(*labels: str) -> Exists:
    """Return an ORM test: one tag of the post carries every given label.

    Args:
        *labels: Labels that the same tag row must satisfy.

    Returns:
        An EXISTS expression over the post's tags.
    """
    rows = Tag.objects.filter(posts=OuterRef("pk"))
    for label in labels:
        rows = rows.filter(label=label)
    return Exists(rows)


def _has_any(*labels: str) -> Exists:
    """Return an ORM test: some tag of the post has one of the labels.

    Args:
        *labels: Accepted labels.

    Returns:
        An EXISTS expression over the post's tags.
    """
    return Exists(Tag.objects.filter(posts=OuterRef("pk"), label__in=labels))


@pytest.fixture
def subsets(db: None) -> None:
    """Create one post per subset of the labels x, y and z.

    Args:
        db: Pytest-Django database fixture.
    """
    owner = AndManyOwner.objects.create(name="o")
    tags = {c: Tag.objects.create(label=c, color="c") for c in "xyz"}
    for size in range(4):
        for subset in itertools.combinations("xyz", size):
            post = AndManyPost.objects.create(title="".join(subset) or "none")
            post.tags.set([tags[c] for c in subset])
            for comment_tag in subset:
                comment = AndManyComment.objects.create(
                    post=post, label=comment_tag, color="c", owner=owner
                )
                comment.tags.set([tags[c] for c in subset if c != comment_tag])


def _titles(node: dict) -> list[str]:
    """Apply a filter node through the native backend.

    Args:
        node: Filter node over the test post model.

    Returns:
        Sorted titles of the matching posts.
    """
    rows = NativeFilterBackend().apply(AndManyPost.objects.all(), node)
    return sorted(rows.values_list("title", flat=True))


def _orm(condition: Any) -> list[str]:
    """Evaluate an independent ORM condition over the subset posts.

    Args:
        condition: A Q or expression built from _has and negation.

    Returns:
        Sorted post titles.
    """
    return sorted(AndManyPost.objects.filter(condition).values_list("title", flat=True))


def _tags(node: dict) -> dict:
    """Wrap a node in the tags relation object.

    Args:
        node: Relation-object fragment.

    Returns:
        A post filter node.
    """
    return {"tags": node}


X, Y, Z = _label("x"), _label("y"), _label("z")
ALL = ["none", "x", "xy", "xyz", "xz", "y", "yz", "z"]
MATRIX = [
    ("a and[x,y]", _tags({"and": [X, Y]}), [], lambda: _has("x", "y")),
    ("b and[and[x,y]]", _tags({"and": [{"and": [X, Y]}]}), [], lambda: _has("x", "y")),
    ("c and[x,and[y]]", _tags({"and": [X, {"and": [Y]}]}), [], lambda: _has("x", "y")),
    (
        "d and[x,or[y,y]]",
        _tags({"and": [X, {"or": [Y, Y]}]}),
        [],
        lambda: _has("x", "y"),
    ),
    ("e and[x,or[y]]", _tags({"and": [X, {"or": [Y]}]}), [], lambda: _has("x", "y")),
    (
        "f and[x,not z]",
        _tags({"and": [X, {"not": Z}]}),
        ["x", "xy"],
        lambda: Q(_has("x")) & ~Q(_has("z")),
    ),
    ("g not y", _tags({"not": Y}), ["none", "x", "xz", "z"], lambda: ~Q(_has("y"))),
    (
        "h or[not y]",
        _tags({"or": [{"not": Y}]}),
        ["none", "x", "xz", "z"],
        lambda: ~Q(_has("y")),
    ),
    (
        "i or[z,not y]",
        _tags({"or": [Z, {"not": Y}]}),
        ["none", "x", "xyz", "xz", "yz", "z"],
        lambda: Q(_has("z")) | ~Q(_has("y")),
    ),
    (
        "j and[not y]",
        _tags({"and": [{"not": Y}]}),
        ["none", "x", "xz", "z"],
        lambda: ~Q(_has("y")),
    ),
    (
        "k label x + not y",
        _tags({**X, "not": Y}),
        ["x", "xz"],
        lambda: Q(_has("x")) & ~Q(_has("y")),
    ),
    (
        "l top not tags y",
        {"not": _tags(Y)},
        ["none", "x", "xz", "z"],
        lambda: ~Q(_has("y")),
    ),
    (
        "m top and[tags x, tags y]",
        {"and": [_tags(X), _tags(Y)]},
        ["xy", "xyz"],
        lambda: Q(_has("x")) & Q(_has("y")),
    ),
    (
        "n top and[tags x, tags not y]",
        {"and": [_tags(X), _tags({"not": Y})]},
        ["x", "xz"],
        lambda: Q(_has("x")) & ~Q(_has("y")),
    ),
    (
        "o not and[x,y]",
        _tags({"not": {"and": [X, Y]}}),
        ALL,
        lambda: ~Q(_has("x", "y")),
    ),
    (
        "p not or[x,y]",
        _tags({"not": {"or": [X, Y]}}),
        ["none", "z"],
        lambda: ~Q(_has_any("x", "y")),
    ),
    (
        "q top not and[tags x, tags y]",
        {"not": {"and": [_tags(X), _tags(Y)]}},
        ["none", "x", "xz", "y", "yz", "z"],
        lambda: ~(Q(_has("x")) & Q(_has("y"))),
    ),
]


@pytest.mark.parametrize(
    ("node", "expected", "condition"),
    [case[1:] for case in MATRIX],
    ids=[case[0] for case in MATRIX],
)
def test_not_inside_relation_object_matrix(
    subsets: None, node: dict, expected: list[str], condition: Any
) -> None:
    """Each of the 17 operator shapes matches the literal and the ORM answer.

    Args:
        subsets: Eight posts, one per label subset.
        node: Filter node under test.
        expected: Literal expected titles.
        condition: Independent ORM spelling of the same meaning.
    """
    assert _titles(node) == expected == _orm(condition())


@pytest.mark.parametrize(
    ("node", "condition"),
    [
        (
            _tags({"and": [X, {"or": [Z, {"not": Y}]}]}),
            lambda: Q(_has("x")) & (Q(_has("z")) | ~Q(_has("y"))),
        ),
        (_tags({"not": {"not": Y}}), lambda: Q(_has("y"))),
        (
            _tags({"not": {"and": [X, {"not": Z}]}}),
            lambda: ~(Q(_has("x")) & ~Q(_has("z"))),
        ),
        (
            {"not": _tags({"not": Y})},
            lambda: Q(_has("y")),
        ),
        (
            {"or": [_tags({"not": Y}), _tags({"and": [X, Z]})]},
            lambda: ~Q(_has("y")) | Q(_has("x", "z")),
        ),
    ],
)
def test_not_rule_composes_with_other_operators(
    subsets: None, node: dict, condition: Any
) -> None:
    """Nested not/or/and combinations follow the same parent-level rule.

    Args:
        subsets: Eight posts, one per label subset.
        node: Filter node under test.
        condition: Independent ORM spelling of the same meaning.
    """
    assert _titles(node) == _orm(condition())


def test_not_rule_applies_to_relation_inside_relation(subsets: None) -> None:
    """A comment whose own tags lack y exists for the post.

    Args:
        subsets: Eight posts with comments carrying tags.
    """
    node = {"comments": {"tags": {"not": Y}}}
    inner = Exists(Tag.objects.filter(comments=OuterRef("pk"), label="y"))
    comments = AndManyComment.objects.filter(post=OuterRef("pk")).filter(~inner)
    assert _titles(node) == _orm(Exists(comments))
    both = {"comments": {**_label("x"), "tags": {"not": Y}}}
    comments = AndManyComment.objects.filter(post=OuterRef("pk"), label="x").filter(
        ~inner
    )
    assert _titles(both) == _orm(Exists(comments))
    negated = {"not": node}
    assert _titles(negated) == _orm(
        ~Q(Exists(AndManyComment.objects.filter(post=OuterRef("pk")).filter(~inner)))
    )


def test_not_rule_keeps_flat_sql_and_other_results(subsets: None) -> None:
    """Nested ands holding a not still compile to the flat statement.

    Args:
        subsets: Eight posts, one per label subset.
    """
    branch = _tags({"not": X})
    flat = {"and": [branch] * 20}
    nested = branch
    for _ in range(19):
        nested = {"and": [nested, branch]}
    sql = [
        str(NativeFilterBackend().apply(AndManyPost.objects.all(), node).query)
        for node in (flat, nested)
    ]
    assert sql[0] == sql[1]
    assert _titles(nested) == _titles(branch) == ["none", "y", "yz", "z"]
    assert _titles({"title": {"exact": "xy"}, "not": {"title": {"exact": "x"}}}) == [
        "xy"
    ]
