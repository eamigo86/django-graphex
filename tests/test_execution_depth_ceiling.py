"""A document at the structural depth ceiling must execute with real data.

Python's stack cannot execute arbitrarily deep documents: graphql-core
completes each level through several nested frames. The ceiling enforced by
DepthLimitValidationRule is therefore only safe if a document right at it still
executes cleanly against cyclic data (an author whose posts point back at the
author) under the deeper stack of a real request.
"""

import json
import logging

import pytest
from django.test import RequestFactory

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType
from django_graphex.validation import _MAX_STRUCTURAL_DEPTH
from django_graphex.views import GraphQLView
from tests._schema_isolation import isolated_pair
from tests.models import Author, Post

_REGISTRY = Registry()


class _PostType(DjangoObjectType):
    """Post output type."""

    class Meta:
        """Type options."""

        model = Post
        registry = _REGISTRY


class _AuthorType(DjangoObjectType):
    """Author output type; its reverse posts relation cycles back."""

    class Meta:
        """Type options."""

        model = Author
        registry = _REGISTRY


class _PostList(DjangoListObjectType):
    """Post list wrapper used by the reverse relation."""

    class Meta:
        """Type options."""

        model = Post
        registry = _REGISTRY


class _Query(ObjectType):
    """Query root."""

    all_posts = DjangoFilterListField(_PostType)


_SCHEMA = DjangoGraphQLSchema(query=_Query, registries=isolated_pair(_REGISTRY))


def _document(max_depth: int) -> tuple[str, int]:
    """Build the deepest cyclic inline document within a depth.

    Args:
        max_depth: The largest object-nesting depth allowed.

    Returns:
        document: The query text and its actual nesting depth.
    """
    body, depth = "title", 1
    while depth + 3 <= max_depth:
        body = f"author {{ posts {{ results {{ {body} }} }} }}"
        depth += 3
    return "{ allPosts { %s } }" % body, depth


@pytest.mark.django_db
def test_document_at_the_ceiling_executes_cleanly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The deepest permitted document runs without an internal error.

    Args:
        caplog: Pytest log capture.
    """
    author = Author.objects.create(name="a")
    Post.objects.create(title="t", author=author)
    query, depth = _document(_MAX_STRUCTURAL_DEPTH)
    assert depth > _MAX_STRUCTURAL_DEPTH - 4
    request = RequestFactory().post(
        "/graphql/", json.dumps({"query": query}), content_type="application/json"
    )

    with caplog.at_level(logging.DEBUG):
        response = GraphQLView.as_view(schema=_SCHEMA)(request)

    body = json.loads(response.content)
    assert response.status_code == 200
    assert "errors" not in body
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
