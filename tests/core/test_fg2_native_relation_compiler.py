"""Behavioral contracts for native relation projection and field resolution."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.core.exceptions import ObjectDoesNotExist
from graphql import GraphQLObjectType

from django_graphex.registry import Registry
from django_graphex.types import DjangoObjectType
from tests.models import Author, AuthorProfile, Comment, Post, Tag


@pytest.fixture(autouse=True)
def _isolate_output_registry() -> Iterator[None]:
    """Restore global output registrations after each local schema fixture.

    Yields:
        Control while one test owns its isolated model registrations.
    """
    from django_graphex.core.base import (
        _gdx_output_registry,
        get_shared_output_registry,
    )

    shared = get_shared_output_registry()
    entries = list(_gdx_output_registry)
    compiled = dict(shared._compiled)
    try:
        yield
    finally:
        _gdx_output_registry[:] = entries
        shared._compiled.clear()
        shared._compiled.update(compiled)


def _relation_registry() -> Registry:
    """Build an isolated registry containing the related node types.

    Returns:
        A fresh registry for the current relation compilation.
    """
    local_registry = Registry()

    class _AuthorNode(DjangoObjectType):
        class Meta:
            model = Author
            registry = local_registry

    class _ProfileNode(DjangoObjectType):
        class Meta:
            model = AuthorProfile
            registry = local_registry

    class _CommentNode(DjangoObjectType):
        class Meta:
            model = Comment
            registry = local_registry

    class _PostNode(DjangoObjectType):
        class Meta:
            model = Post
            registry = local_registry

    class _TagNode(DjangoObjectType):
        class Meta:
            model = Tag
            registry = local_registry

    assert all(
        local_registry.get_type_for_model(model) is not None
        for model in (Author, AuthorProfile, Comment, Post, Tag)
    )
    return local_registry


@pytest.mark.parametrize(
    ("model", "name", "container"),
    [
        (Post, "tags", "TagListType"),
        (Post, "co_authors", "AuthorListType"),
        (Post, "comments", "CommentListType"),
        (Author, "posts", "PostListType"),
        (Author, "coauthored_posts", "PostListType"),
        (Tag, "posts", "PostListType"),
    ],
)
def test_native_many_relation_projects_one_named_container(
    model: type, name: str, container: str
) -> None:
    """Project each real forward or reverse relation to its list container.

    Args:
        model: Owner model with the declared relation.
        name: Django accessor selected by the projection.
        container: Expected native GraphQL container name.
    """
    from django_graphex.types import _compile_relation_list_fields

    fields = _compile_relation_list_fields(
        DjangoObjectType, model, _relation_registry(), only_fields=[name]
    )
    expected = (
        "coAuthors"
        if name == "co_authors"
        else ("coauthoredPosts" if name == "coauthored_posts" else name)
    )
    assert set(fields) == {expected}
    assert isinstance(fields[expected].type, GraphQLObjectType)
    assert fields[expected].type.name == container
    assert {"results", "totalCount"} <= set(fields[expected].type.fields)


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (Post, "tags"),
        (Post, "co_authors"),
        (Post, "comments"),
        (Author, "posts"),
        (Author, "coauthored_posts"),
        (Tag, "posts"),
    ],
)
def test_native_many_relation_exclusion_removes_only_selected_accessor(
    model: type, name: str
) -> None:
    """Exclude one relation without hiding unrelated available containers.

    Args:
        model: Owner model with the declared relation.
        name: Django accessor excluded by the projection.
    """
    from django_graphex.types import _compile_relation_list_fields

    registry = _relation_registry()
    full = _compile_relation_list_fields(DjangoObjectType, model, registry)
    filtered = _compile_relation_list_fields(
        DjangoObjectType, model, registry, exclude_fields=[name]
    )
    expected = (
        "coAuthors"
        if name == "co_authors"
        else ("coauthoredPosts" if name == "coauthored_posts" else name)
    )
    assert expected in full
    assert set(filtered) == set(full) - {expected}


@pytest.mark.parametrize(
    ("only", "exclude", "present"),
    [
        (["author_profile"], None, True),
        (["title"], None, False),
        (None, ["author_profile"], False),
        (None, ["title"], True),
    ],
)
def test_native_reverse_o2o_projection_matches_accessor(
    only: list[str] | None, exclude: list[str] | None, present: bool
) -> None:
    """Honor the reverse one-to-one accessor projection exactly.

    Args:
        only: Allowed Django field names, if restricted.
        exclude: Omitted Django field names, if restricted.
        present: Whether the reverse field should remain visible.
    """
    from django_graphex.types import _compile_reverse_o2o_fields

    fields = _compile_reverse_o2o_fields(
        DjangoObjectType,
        Author,
        _relation_registry(),
        only_fields=only,
        exclude_fields=exclude,
    )
    assert ("authorProfile" in fields) is present
    if present:
        assert isinstance(fields["authorProfile"].type, GraphQLObjectType)


def test_native_reverse_o2o_requires_registered_target() -> None:
    """Do not expose a reverse relation to an unregistered model type.

    A schema must not create an object field without a registered target node.
    """
    from django_graphex.types import _compile_reverse_o2o_fields

    fields = _compile_reverse_o2o_fields(
        DjangoObjectType, Author, Registry(), only_fields=["author_profile"]
    )
    assert fields == {}


def test_native_reverse_o2o_resolver_handles_missing_related_row() -> None:
    """Return null for an absent reverse row without hiding real values.

    The nested fixture raises an absence exception that the resolver catches.

    Raises:
        AssertionError: If a present value disappears or absence escapes.
    """
    from django_graphex.types import _compile_reverse_o2o_fields

    fields = _compile_reverse_o2o_fields(
        DjangoObjectType,
        Author,
        _relation_registry(),
        only_fields=["author_profile"],
    )
    resolver = fields["authorProfile"].resolve
    marker = object()

    class _Missing:
        @property
        def author_profile(self) -> object:
            """Represent Django's absent reverse relation.

            Raises:
                ObjectDoesNotExist: The related row does not exist.
            """
            raise ObjectDoesNotExist("no profile")

    class _Present:
        author_profile = marker

    assert resolver({"author_profile": marker}, None) is marker
    assert resolver(_Present(), None) is marker
    assert resolver(_Missing(), None) is None
