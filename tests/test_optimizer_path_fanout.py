# -*- coding: utf-8 -*-
"""Optimizer work budget for fragments reached through distinct relation paths.

Memoizing the optimizer walkers by selection context fixed a fragment spread
repeatedly in the SAME context. A fragment reached through DISTINCT relation
paths (author, coAuthors, posts, coauthoredPosts, ...) is a different ORM
lookup each time, so the set of lookups the document describes is itself
exponential and no memo can plan it in linear time. These tests pin the shared
per-request work budget ("OPTIMIZER_WORK_BUDGET") that bounds every walker, and
that results stay correct once planning is truncated.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pytest
from django.test import RequestFactory, override_settings

from django_graphex import utils
from django_graphex.core import ObjectType
from django_graphex.directives import all_directives
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings
from django_graphex.types import DjangoObjectType
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Author, Comment, Post, Tag

R = Registry()


class TagT(DjangoObjectType):
    """Tag output type.

    Registered in the isolated registry used by this module.
    """

    class Meta:
        """Type options.

        Registered in the isolated registry used by this module.
        """

        model = Tag
        registry = R


class CommentT(DjangoObjectType):
    """Comment output type.

    Registered in the isolated registry used by this module.
    """

    class Meta:
        """Type options.

        Registered in the isolated registry used by this module.
        """

        model = Comment
        registry = R


class PostT(DjangoObjectType):
    """Post output type.

    Registered in the isolated registry used by this module.
    """

    class Meta:
        """Type options.

        Registered in the isolated registry used by this module.
        """

        model = Post
        registry = R


class AuthorT(DjangoObjectType):
    """Author output type.

    Registered in the isolated registry used by this module.
    """

    class Meta:
        """Type options.

        Registered in the isolated registry used by this module.
        """

        model = Author
        registry = R


class Q(ObjectType):
    """Query root.

    Registered in the isolated registry used by this module.
    """

    all_posts = DjangoFilterListField(PostT)


SCHEMA = DjangoGraphQLSchema(
    query=Q, registries=isolated_pair(R), directives=all_directives
)

#: Walkers that run once per request and recurse over the selection tree.
WALKERS = (
    "recursive_params",
    "_walk_filtered_prefetches",
    "_scoped_fk_prefetches",
    "_collect_only_fields",
)


def _path_fanout(levels: int, leaf: str = "title") -> str:
    """Build a document whose fragments fan out through distinct paths.

    Args:
        levels: Number of fragment levels; every level reaches the next one
            through four different relation paths.
        leaf: Scalar selected at the deepest level.

    Returns:
        document: The GraphQL document text.
    """
    parts = ["{ allPosts { ...P0 } }"]
    for i in range(levels - 1):
        parts.append(
            f"fragment P{i} on PostT {{ author {{ ...A{i} }} "
            f"coAuthors {{ results {{ ...A{i} }} }} }}"
        )
        parts.append(
            f"fragment A{i} on AuthorT {{ posts {{ results {{ ...P{i + 1} }} }} "
            f"coauthoredPosts {{ results {{ ...P{i + 1} }} }} }}"
        )
    parts.append(f"fragment P{levels - 1} on PostT {{ {leaf} }}")
    return "\n".join(parts)


def _post(document: str) -> tuple[int, dict[str, Any]]:
    """POST a document to the view.

    Args:
        document: The GraphQL document text.

    Returns:
        result: The status code and decoded body.
    """
    body = json.dumps({"query": document})
    request = RequestFactory().post("/graphql/", body, content_type="application/json")
    response = GraphQLView.as_view(schema=SCHEMA)(request)
    return response.status_code, json.loads(response.content)


def _count_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Wrap every recursive walker with a call counter.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        calls: Live mapping of walker name to number of calls.
    """
    calls = dict.fromkeys(WALKERS, 0)
    for name in WALKERS:
        original = getattr(utils, name)

        def counted(*args: Any, _name: str = name, _orig: Any = original, **kw: Any):
            calls[_name] += 1
            return _orig(*args, **kw)

        monkeypatch.setattr(utils, name, counted)
    return calls


@pytest.mark.django_db
@override_settings(DJANGO_GRAPHEX={"OPTIMIZER_WORK_BUDGET": 200})
def test_distinct_path_fanout_work_is_bounded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Every walker stays within a small multiple of the configured budget.

    Eight levels describe 4**8 distinct lookups (about 93k walker calls before
    the budget). The assertion counts walker calls instead of seconds so it is
    deterministic on any runner.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        caplog: The pytest log capture fixture.
    """
    calls = _count_calls(monkeypatch)
    with caplog.at_level(logging.DEBUG, logger="django_graphex.utils"):
        status, body = _post(_path_fanout(8))
    assert status == 200
    assert body["data"] == {"allPosts": []}
    for name, count in calls.items():
        assert count <= 3_000, f"{name} made {count} calls"
    assert any("OPTIMIZER_WORK_BUDGET" in m for m in caplog.messages)


def test_work_budget_default_is_generous_and_documented() -> None:
    """The default budget is far above any realistic document.

    Registered in the isolated registry used by this module.
    """
    assert graphql_api_settings.OPTIMIZER_WORK_BUDGET >= 1_000


@pytest.mark.django_db
def test_distinct_path_fanout_default_budget_is_fast() -> None:
    """A ten-level distinct-path document finishes quickly with defaults.

    Before the budget this took well over twenty seconds on an empty database.
    The ceiling is a loose sanity bound; the call-count test is the strict one.
    """
    start = time.perf_counter()
    status, _ = _post(_path_fanout(10))
    assert status == 200
    assert time.perf_counter() - start < 10.0


@pytest.mark.django_db
def test_truncated_planning_keeps_results_correct() -> None:
    """Budget truncation only changes how relations load, never the data.

    Registered in the isolated registry used by this module.
    """
    first = Author.objects.create(name="Ada")
    second = Author.objects.create(name="Bob")
    one = Post.objects.create(title="one", author=first)
    one.co_authors.add(second)
    two = Post.objects.create(title="two", author=second)
    two.co_authors.add(first)
    document = _path_fanout(4)

    status, expected = _post(document)
    assert status == 200 and "errors" not in expected
    posts = expected["data"]["allPosts"]
    assert len(posts) == 2

    with override_settings(DJANGO_GRAPHEX={"OPTIMIZER_WORK_BUDGET": 3}):
        truncated_status, truncated = _post(document)
    assert truncated_status == 200
    assert truncated == expected
