# -*- coding: utf-8 -*-
"""Optimizer work budget: truncated planning never changes the data.

Past "OPTIMIZER_WORK_BUDGET" the walkers used to disagree (the plain prefetch
survived while the filtered prefetch carrying ordering, limit and offset was
dropped), so nested lists silently lost their arguments. The contract pinned
here: once the budget is spent the root field resolves exactly like
"OPTIMIZE_QUERYSET=False", and the budget is shared by the whole request.
"""

from __future__ import annotations

import json
import random
from typing import Any

import pytest
from django.test import RequestFactory, override_settings

from django_graphex import utils
from django_graphex.core import ObjectType
from django_graphex.directives import all_directives
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Author, AuthorProfile, Category, Comment, Post, Tag

R = Registry()

_HIDDEN_FIELD = {
    "Post": "title",
    "Author": "name",
    "Tag": "label",
    "Category": "title",
    "Comment": "body",
    "AuthorProfile": "bio",
}


def _hide(cls: Any, queryset: Any, info: Any) -> Any:
    """Scope every type: rows whose label starts with H are invisible.

    Args:
        cls: The output type.
        queryset: The queryset being scoped.
        info: The resolve info.

    Returns:
        queryset: The scoped queryset.
    """
    return queryset.exclude(
        **{_HIDDEN_FIELD[queryset.model.__name__] + "__startswith": "H"}
    )


class TagT(DjangoObjectType):
    """Scoped output type used by this module.

    Used by the optimizer budget consistency tests.
    """

    class Meta:
        """Type options.

        Used by the optimizer budget consistency tests.
        """

        model = Tag
        registry = R

    get_queryset = classmethod(_hide)


class CatT(DjangoObjectType):
    """Scoped output type used by this module.

    Used by the optimizer budget consistency tests.
    """

    class Meta:
        """Type options.

        Used by the optimizer budget consistency tests.
        """

        model = Category
        registry = R

    get_queryset = classmethod(_hide)


class CommentT(DjangoObjectType):
    """Scoped output type used by this module.

    Used by the optimizer budget consistency tests.
    """

    class Meta:
        """Type options.

        Used by the optimizer budget consistency tests.
        """

        model = Comment
        registry = R

    get_queryset = classmethod(_hide)


class ProfT(DjangoObjectType):
    """Scoped output type used by this module.

    Used by the optimizer budget consistency tests.
    """

    class Meta:
        """Type options.

        Used by the optimizer budget consistency tests.
        """

        model = AuthorProfile
        registry = R

    get_queryset = classmethod(_hide)


class PostT(DjangoObjectType):
    """Scoped output type used by this module.

    Used by the optimizer budget consistency tests.
    """

    class Meta:
        """Type options.

        Used by the optimizer budget consistency tests.
        """

        model = Post
        registry = R

    get_queryset = classmethod(_hide)


class AuthorT(DjangoObjectType):
    """Scoped output type used by this module.

    Used by the optimizer budget consistency tests.
    """

    class Meta:
        """Type options.

        Used by the optimizer budget consistency tests.
        """

        model = Author
        registry = R

    get_queryset = classmethod(_hide)


class Q(ObjectType):
    """Query root exposing both entry points as filter lists.

    Used by the optimizer budget consistency tests.
    """

    all_posts = DjangoFilterListField(PostT)
    authors = DjangoFilterListField(AuthorT)


SCHEMA = DjangoGraphQLSchema(
    query=Q, registries=isolated_pair(R), directives=all_directives
)


def _post(query: str) -> dict[str, Any]:
    """POST a document to the view.

    Args:
        query: The GraphQL document.

    Returns:
        body: The decoded response body.
    """
    body = json.dumps({"query": query})
    request = RequestFactory().post("/graphql/", body, content_type="application/json")
    return json.loads(GraphQLView.as_view(schema=SCHEMA)(request).content)


def _seed() -> None:
    """Create a small connected data set including hidden rows.

    Used by the optimizer budget consistency tests.
    """
    rnd = random.Random(3)
    authors = [
        Author.objects.create(name=n + str(i))
        for i, n in enumerate("a Hb c d He".split())
    ]
    for author in authors:
        AuthorProfile.objects.create(author=author, bio=rnd.choice(["x", "Hy"]))
    cats = [Category.objects.create(title=t) for t in ("c1", "Hc2", "c3")]
    tags = [Tag.objects.create(label=t) for t in ("t1", "Ht2", "t3", "t4")]
    for i in range(8):
        post = Post.objects.create(
            title=("H" if i % 4 == 1 else "p") + str(i),
            author=rnd.choice(authors),
            category=rnd.choice(cats),
        )
        post.tags.set(rnd.sample(tags, 2))
        post.co_authors.set(rnd.sample(authors, 2))
        for j in range(3):
            Comment.objects.create(post=post, body=("H" if j == 1 else "c") + f"{i}{j}")


def _oracle(query: str) -> dict[str, Any]:
    """Resolve a document without the optimizer.

    Args:
        query: The GraphQL document.

    Returns:
        body: The decoded response body.
    """
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": False}):
        return _post(query)


def _budgeted(query: str, budget: int | None) -> dict[str, Any]:
    """Resolve a document with a given optimizer work budget.

    Args:
        query: The GraphQL document.
        budget: The "OPTIMIZER_WORK_BUDGET" value.

    Returns:
        body: The decoded response body.
    """
    with override_settings(DJANGO_GRAPHEX={"OPTIMIZER_WORK_BUDGET": budget}):
        return _post(query)


NESTED = (
    "{ authors { id posts { results { id } } authorProfile { author { posts "
    "{ results%s { id } } } } } }"
)


@pytest.mark.django_db
@pytest.mark.parametrize("args", ['(ordering: "-id")', "(offset: 1)", "(limit: 2)"])
@pytest.mark.parametrize("budget", [1, 2, 3, 5, 100])
def test_truncated_nested_list_arguments_are_kept(args: str, budget: int) -> None:
    """Ordering, offset and limit of a nested list survive truncated planning.

    Args:
        args: Arguments of the nested list.
        budget: Optimizer work budget under test.
    """
    _seed()
    query = NESTED % args
    expected = _oracle(query)
    assert "errors" not in expected
    assert _budgeted(query, budget) == expected


def _fan(levels: int) -> str:
    """Fragments reaching the next level through four distinct paths.

    Args:
        levels: Number of fragment levels.

    Returns:
        fragments: The fragment definitions.
    """
    parts = []
    for i in range(levels):
        parts.append(
            f"fragment P{i} on PostT {{ author {{ ...A{i} }} "
            f"coAuthors {{ results {{ ...A{i} }} }} }}"
        )
        parts.append(
            f"fragment A{i} on AuthorT {{ posts {{ results {{ ...P{i + 1} }} }} "
            f"coauthoredPosts {{ results {{ ...P{i + 1} }} }} }}"
        )
    parts.append(f"fragment P{levels} on PostT {{ title }}")
    return "\n".join(parts)


@pytest.mark.django_db
def test_default_budget_fanout_beside_ordered_list_keeps_ordering() -> None:
    """A distinct-path fan-out past the default budget keeps list ordering.

    Used by the optimizer budget consistency tests.
    """
    author = Author.objects.create(name="a")
    AuthorProfile.objects.create(author=author, bio="x")
    for i in range(2):
        Post.objects.create(title=f"p{i}", author=author)
    query = (
        "{ authors { coauth: coauthoredPosts { results { ...P0 } } ...P0X "
        'ordered: authorProfile { author { posts { results(ordering:"-id") { id } } } } '
        "plain: posts { results { views } } } }\n"
        "fragment P0X on AuthorT { ...A0 }\n" + _fan(7)
    )
    expected = _oracle(query)
    assert "errors" not in expected
    ids = expected["data"]["authors"][0]["ordered"]["author"]["posts"]["results"]
    assert [row["id"] for row in ids] == sorted(
        (row["id"] for row in ids), reverse=True
    )
    assert _post(query) == expected


SCALARS = {
    "PostT": ["id", "title", "views"],
    "AuthorT": ["id", "name"],
    "TagT": ["label"],
    "CatT": ["title"],
    "CommentT": ["body"],
    "ProfT": ["bio"],
}
RELATIONS = {
    "PostT": [
        ("author", "AuthorT", 0),
        ("category", "CatT", 0),
        ("tags", "TagT", 1),
        ("comments", "CommentT", 1),
        ("coAuthors", "AuthorT", 1),
    ],
    "AuthorT": [
        ("posts", "PostT", 1),
        ("coauthoredPosts", "PostT", 1),
        ("authorProfile", "ProfT", 0),
    ],
    "TagT": [("posts", "PostT", 1)],
    "CatT": [("posts", "PostT", 1)],
    "CommentT": [("post", "PostT", 0)],
    "ProfT": [("author", "AuthorT", 0)],
}


def _generate(rnd: random.Random, name: str, depth: int, frags: dict[str, Any]) -> str:
    """Generate a random selection set.

    Args:
        rnd: Seeded random source.
        name: Output type name.
        depth: Remaining relation depth.
        frags: Collected fragment definitions, extended in place.

    Returns:
        selection: The selection set body.
    """
    sels = []
    for scalar in rnd.sample(SCALARS[name], rnd.randint(0, min(2, len(SCALARS[name])))):
        sels.append(("%s: " % rnd.choice("xyz") if rnd.random() < 0.1 else "") + scalar)
    if depth > 0:
        for rel, target, is_list in rnd.sample(
            RELATIONS[name], rnd.randint(0, len(RELATIONS[name]))
        ):
            inner = _generate(rnd, target, depth - 1, frags)
            if rnd.random() < 0.3:
                fragment = "F%d" % len(frags)
                frags[fragment] = (target, inner)
                inner = "..." + fragment
            args = ""
            if is_list:
                given = []
                if rnd.random() < 0.3:
                    given.append("limit: %d" % rnd.randint(1, 3))
                if rnd.random() < 0.3:
                    given.append("offset: 1")
                if rnd.random() < 0.3:
                    given.append('ordering: "-id"')
                inner = "results%s { %s }" % (
                    "(%s)" % ",".join(given) if given else "",
                    inner,
                )
            alias = "al%d: " % rnd.randint(0, 99) if rnd.random() < 0.15 else ""
            sels.append(f"{alias}{rel}{args} {{ {inner} }}")
    return " ".join(sels) or SCALARS[name][0]


@pytest.mark.django_db
def test_random_documents_match_the_unoptimized_oracle() -> None:
    """Seeded random documents resolve identically at every budget.

    Used by the optimizer budget consistency tests.
    """
    _seed()
    rnd = random.Random(11)
    checked = 0
    for _ in range(120):
        frags: dict[str, Any] = {}
        root = rnd.choice(["PostT", "AuthorT"])
        body = _generate(rnd, root, rnd.randint(2, 4), frags)
        field = "allPosts" if root == "PostT" else "authors"
        query = "{ %s { %s } }\n" % (field, body) + "\n".join(
            f"fragment {k} on {t} {{ {b} }}" for k, (t, b) in frags.items()
        )
        expected = _oracle(query)
        if "errors" in expected:
            continue
        checked += 1
        for budget in (1, 5, 20, 2000):
            assert _budgeted(query, budget) == expected, (budget, query)
    assert checked > 80


@pytest.mark.django_db
def test_budget_is_shared_by_every_root_field_of_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Twenty aliased roots plan no more than one budget in total.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    author = Author.objects.create(name="a")
    for i in range(2):
        Post.objects.create(title=f"p{i}", author=author)
    calls = {"n": 0}
    original = utils.recursive_params

    def counted(*args: Any, **kw: Any) -> Any:
        calls["n"] += 1
        return original(*args, **kw)

    monkeypatch.setattr(utils, "recursive_params", counted)
    query = (
        "{ "
        + " ".join(f"r{i}: allPosts {{ ...P0 }}" for i in range(20))
        + " }\n"
        + _fan(3)
    )
    result = _budgeted(query, 10)
    assert calls["n"] <= 15
    monkeypatch.undo()
    assert result == _oracle(query)
