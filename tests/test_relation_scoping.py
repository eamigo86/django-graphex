# -*- coding: utf-8 -*-
"""Tests that "get_queryset" scoping survives traversal through a parent relation.

The related fast path in "DjangoFilterListField.list_resolver" used to resolve
"root.<accessor>.all()" directly, bypassing the node type's "get_queryset"
hook, so a row-level scope enforced at the top level leaked when the same type
was reached through a parent object. These tests pin the hook on BOTH paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoFilterListField
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoObjectType
from django_graphex.utils import apply_object_type_get_queryset

from .models import ScopedAuthor, ScopedPost

if TYPE_CHECKING:
    from django.db.models import QuerySet


class ScopedPostType(DjangoObjectType):
    """A "DjangoObjectType" whose "get_queryset" hook hides non-public posts.

    Mounted twice -- once at the root and once under "ScopedAuthorType" -- so the
    same scope can be asserted on both resolution paths.
    """

    class Meta:
        """Bind "ScopedPostType" to "ScopedPost" with a title filter field.

        The filter fields exist so the resolver takes its normal filtered path
        rather than a filter-free shortcut.
        """

        model = ScopedPost
        filter_fields = {"id": ("exact",), "title": ("icontains",)}

    @classmethod
    def get_queryset(cls, queryset: "QuerySet[Any]", info: Any) -> "QuerySet[Any]":
        """Restrict the queryset to titles starting with "pub".

        Args:
            queryset: The base queryset to scope.
            info: The GraphQL resolve info for the current request.

        Returns:
            The queryset narrowed to the rows this request may see.
        """
        return queryset.filter(title__startswith="pub")


class ScopedAuthorType(DjangoObjectType):
    """Parent type mounting the scoped post list under the relation accessor.

    The mounted field name matches the relation accessor ("created_posts"),
    which is exactly what sends the resolver down the related fast path.
    """

    class Meta:
        """Bind "ScopedAuthorType" to "ScopedAuthor" with an id filter field.

        Declares no "get_queryset" override, so it also serves as the unscoped
        baseline for the prefetch-preservation test.
        """

        model = ScopedAuthor
        filter_fields = {"id": ("exact",)}

    created_posts = DjangoFilterListField(ScopedPostType)


class _Query(ObjectType):
    """Root query exposing the scoped post list and its parent author list."""

    posts = DjangoFilterListField(ScopedPostType)
    authors = DjangoFilterListField(ScopedAuthorType)


_schema = DjangoGraphQLSchema(query=_Query)


def _seed() -> ScopedAuthor:
    """Create one author owning one visible and one hidden post.

    Returns:
        The author both posts belong to.
    """
    author = ScopedAuthor.objects.create(name="A")
    ScopedPost.objects.create(title="pub1", author=author)
    ScopedPost.objects.create(title="secret", author=author)
    return author


def test_top_level_list_applies_get_queryset(db: None) -> None:
    """The top-level list must expose only the rows the hook allows.

    Args:
        db: The pytest-django fixture granting database access.
    """
    _seed()

    res = graphql_sync(_schema.graphql_schema, "{ posts { title } }")

    assert res.errors is None, res.errors
    assert res.data["posts"] == [{"title": "pub1"}]


def test_nested_relation_applies_get_queryset(db: None) -> None:
    """The same list reached through a parent relation must apply the hook too.

    Args:
        db: The pytest-django fixture granting database access.
    """
    _seed()

    res = graphql_sync(_schema.graphql_schema, "{ authors { createdPosts { title } } }")

    assert res.errors is None, res.errors
    assert res.data["authors"] == [{"createdPosts": [{"title": "pub1"}]}], (
        "get_queryset hook was not applied on the related fast path -- "
        "a scoped-out row leaked through the parent relation"
    )


def test_type_without_a_scope_returns_the_very_same_queryset(db: None) -> None:
    """A type that does not override the hook must not clone the queryset.

    The related fast path relies on this: an untouched queryset keeps the
    parent's "prefetch_related" cache, so mounting the hook on that path costs
    nothing for the types that declare no scope.

    Args:
        db: The pytest-django fixture granting database access.
    """
    qs = ScopedAuthor.objects.all()

    assert apply_object_type_get_queryset(qs, ScopedAuthorType, None) is qs


def test_hook_returning_a_non_queryset_denies_instead_of_serving_rows() -> None:
    """A hook that does not return a queryset must raise, not serve unscoped rows.

    A silently skipped scope is the whole defect class, so the choke point fails
    closed instead of falling back to the unscoped queryset.
    """

    class _BrokenType:
        """A type whose scoping hook forgets to return the queryset."""

        _dgx_has_object_type_get_queryset = True

        @classmethod
        def get_queryset(cls, queryset: Any, info: Any) -> Any:
            """Return nothing, simulating a hook with a missing return.

            Args:
                queryset: The base queryset handed to the hook.
                info: The GraphQL resolve info for the current request.

            Returns:
                Always None, which cannot be honoured as a scope.
            """
            return None

    with pytest.raises(TypeError, match="must return a QuerySet"):
        apply_object_type_get_queryset(ScopedPost.objects.all(), _BrokenType, None)
