"""An "or" holding relation keys uses independent witnesses, like "and"."""

from __future__ import annotations

import random
from typing import Any

import pytest
from django.db.models import Exists, OuterRef

from .test_and_many_filtering import AndManyComment, AndManyPost
from .test_and_many_filtering import AndManyTag as Tag
from .test_to_many_not_rule import _label, _orm, _tags, _titles, subsets  # noqa: F401

X, Y, Z = _label("x"), _label("y"), _label("z")


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        # The reported shape: or[x] next to a sibling tags z. Each relation
        # branch has its own witness, exactly like and[x] next to tags z.
        ({"or": [_tags(X)], **_tags(Z)}, ["xyz", "xz"]),
        ({"and": [_tags(X)], **_tags(Z)}, ["xyz", "xz"]),
        ({"or": [_tags(X), _tags(X)], **_tags(Z)}, ["xyz", "xz"]),
        ({"or": [_tags(X), _tags(Y)], **_tags(Z)}, ["xyz", "xz", "yz"]),
        ({"or": [_tags(X)], "and": [_tags(Z)]}, ["xyz", "xz"]),
        # Negation encloses the same independent test.
        (
            {"not": {"or": [_tags(X)], **_tags(Z)}},
            ["none", "x", "xy", "y", "yz", "z"],
        ),
        (
            {"not": {"and": [_tags(X)], **_tags(Z)}},
            ["none", "x", "xy", "y", "yz", "z"],
        ),
        # A negated operand next to a positive relation operand: the not is a
        # parent-level test, never a test of the row the other operand joined.
        ({"or": [_tags(X), {"not": _tags(Z)}]}, ["none", "x", "xy", "xyz", "xz", "y"]),
        # No relation next to the or: unchanged.
        ({"or": [_tags(X), _tags(Z)]}, ["x", "xy", "xyz", "xz", "yz", "z"]),
        ({"or": [_tags(X)], "title": {"icontains": "y"}}, ["xy", "xyz"]),
    ],
)
def test_or_next_to_a_relation_key_uses_separate_rows(
    subsets: None,  # noqa: F811
    node: dict,
    expected: list[str],
) -> None:
    """The or operand and the sibling relation key each get their own tag row.

    Args:
        subsets: Eight posts, one per label subset.
        node: Filter node under test.
        expected: Literal expected titles.
    """
    assert _titles(node) == expected


def test_or_in_a_relation_object_keeps_its_parent_row(
    subsets: None,  # noqa: F811
) -> None:
    """Inside one comment, or[tags x] and tags z are separate tag rows.

    Args:
        subsets: Eight posts with comments carrying tags.
    """
    node = {"comments": {"or": [_tags(X)], **_tags(Z)}}
    comments = AndManyComment.objects.filter(post=OuterRef("pk"))
    tag_x = Exists(Tag.objects.filter(comments=OuterRef("pk"), label="x"))
    tag_z = Exists(Tag.objects.filter(comments=OuterRef("pk"), label="z"))
    one_comment = comments.filter(tag_x).filter(tag_z)
    assert _titles(node) == _orm(Exists(one_comment))
    assert _titles({"comments": {"and": [_tags(X)], **_tags(Z)}}) == _titles(node)


def _post_sat(node: dict, labels: str, title: str) -> bool:
    """Evaluate a post-level node on one post, in plain Python.

    Every relation key and every and/or operand owns its own tag witness.

    Args:
        node: Post-level filter node.
        labels: The post's tag labels.
        title: The post's title.

    Returns:
        Whether the post satisfies the node.
    """
    for key, value in node.items():
        if key == "and":
            ok = all(_post_sat(child, labels, title) for child in value)
        elif key == "or":
            ok = any(_post_sat(child, labels, title) for child in value)
        elif key == "not":
            ok = not _post_sat(value, labels, title)
        elif key == "tags":
            ok = _tag_sat(value, labels)
        else:
            ok = value["icontains"] in title
        if not ok:
            return False
    return True


def _tag_sat(node: dict, labels: str) -> bool:
    """Evaluate a relation object over the post's tags, in plain Python.

    Criteria without a "not" share one tag; each "not" is a parent-level test
    (the approved rule).

    Args:
        node: Tag-level filter node.
        labels: The post's tag labels.

    Returns:
        Whether the post's tags satisfy the relation object.
    """
    terms: list[bool] = []
    row: dict[str, Any] = {}
    row_and: list[dict] = []
    for key, value in node.items():
        if key == "not":
            terms.append(not _tag_sat(value, labels))
        elif key == "and":
            for child in value:
                if _has_not(child):
                    terms.append(_tag_sat(child, labels))
                else:
                    row_and.append(child)
        elif key == "or" and any(_has_not(child) for child in value):
            terms.append(any(_tag_sat(child, labels) for child in value))
        else:
            row[key] = value
    if row_and:
        row["and"] = row_and
    if row:
        terms.append(any(_tag_row(row, label) for label in labels))
    return all(terms)


def _has_not(node: dict) -> bool:
    """Tell whether a tag-level node holds a "not" at its own level.

    Args:
        node: Tag-level filter node.

    Returns:
        Whether a not appears directly or inside and/or operands.
    """
    return any(
        key == "not" or (key in ("and", "or") and any(_has_not(c) for c in value))
        for key, value in node.items()
    )


def _tag_row(node: dict, label: str) -> bool:
    """Evaluate a not-free tag-level node on one tag.

    Args:
        node: Tag-level filter node without "not".
        label: The tag label.

    Returns:
        Whether the tag satisfies every criterion.
    """
    for key, value in node.items():
        if key == "and":
            ok = all(_tag_row(child, label) for child in value)
        elif key == "or":
            ok = any(_tag_row(child, label) for child in value)
        else:
            ok = value["exact"] == label
        if not ok:
            return False
    return True


def _gen_tag(rng: random.Random, depth: int) -> dict:
    """Generate a tag-level node.

    A "not" that encloses a relation object holding several same-row criteria
    is a separate, pre-existing gap (Django exclude() semantics), so a tag-level
    row here is a single label, an "or" of labels, or a label beside a "not".

    Args:
        rng: Seeded random source.
        depth: Remaining nesting budget.

    Returns:
        A tag-level filter node.
    """
    pick = rng.random()
    if depth > 0 and pick < 0.25:
        return {"or": [_label(rng.choice("xyz")) for _ in range(rng.randint(1, 3))]}
    if depth > 0 and pick < 0.45:
        return {"not": _gen_tag(rng, depth - 1)}
    node: dict = _label(rng.choice("xyz"))
    if depth > 0 and rng.random() < 0.2:
        node["not"] = _gen_tag(rng, depth - 1)
    return node


def _gen_post(rng: random.Random, depth: int) -> dict:
    """Generate a post-level node mixing operators and relation keys.

    Args:
        rng: Seeded random source.
        depth: Remaining nesting budget.

    Returns:
        A post-level filter node.
    """
    pick = rng.random()
    node: dict
    if depth > 0 and pick < 0.2:
        node = {"and": [_gen_post(rng, depth - 1) for _ in range(rng.randint(1, 3))]}
    elif depth > 0 and pick < 0.45:
        node = {"or": [_gen_post(rng, depth - 1) for _ in range(rng.randint(1, 3))]}
    elif depth > 0 and pick < 0.55:
        inner = _gen_post(rng, depth - 1)
        # A double negation beside a relation key is a separate, pre-existing
        # edge (the ORM merges both into one join); keep the generator off it.
        node = {"not": inner} if "not" not in inner else inner
    elif pick < 0.85:
        node = _tags(_gen_tag(rng, depth))
    else:
        node = {"title": {"icontains": rng.choice("xyz")}}
    if depth > 0 and rng.random() < 0.3:
        node.setdefault("tags", _gen_tag(rng, depth - 1))
    return node


@pytest.mark.parametrize("seed", range(40))
def test_random_filters_match_the_independent_witness_oracle(
    subsets: None,  # noqa: F811
    seed: int,
) -> None:
    """Random and/or/not/relation mixes agree with a plain-Python oracle.

    Args:
        subsets: Eight posts, one per label subset.
        seed: Random seed for the generated filters.
    """
    rng = random.Random(seed)
    posts = [
        (post.title if post.title != "none" else "", post.title)
        for post in AndManyPost.objects.all()
    ]
    for _ in range(60):
        node = _gen_post(rng, 3)
        expected = sorted(
            title or "none"
            for labels, title in posts
            if _post_sat(node, labels, labels)
        )
        assert _titles(node) == expected, repr(node)
