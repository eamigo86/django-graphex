# -*- coding: utf-8 -*-
"""The pruned container's "pageInfo" must answer for the PRUNED schema.

A permission-scoped schema is a CLONE, and "core.schema_pruner._rebuild_field"
carries "resolve" through verbatim. The results resolver is re-derived against
the pruned node type ("_rescope_paginated_resolver"), so "ordering" on
"results" already answers for the clone. "pageInfo" was not: its resolver is a
closure over the paginator the FULL schema stamped, so one container answered
two different questions about the same prune.

On "CursorGraphqlPagination" that gap is not an oracle, it is a READ. A keyset
cursor IS the ordering value: "encode_cursor" serialises the column and the
row's primary key into "startCursor" / "endCursor" under nothing but base64. A
caller denied the "author" relation -- and with it the whole author type and
the "author_id" column -- was handed that column's value, spelled out, on every
page of the list.
"""

from __future__ import annotations

import base64

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.core.perm_labels import implicit_perms_for_type
from django_graphex.core.schema_pruner import prune_schema
from django_graphex.paginations.pagination import CursorGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import (
    DjangoListObjectField,
    DjangoListObjectType,
    DjangoObjectType,
)

from ._schema_isolation import isolated_pair
from .models import Author, Post

# ---------------------------------------------------------------------------
# A cursor-paginated container ordered by the very column the prune removes
# ---------------------------------------------------------------------------

_RCUR = Registry()


class CursorPrunedAuthorType(DjangoObjectType):
    """Author node reachable only through the post node's "author" relation.

    A caller without this model's read permission loses the relation field, and
    the type falls out of the pruned schema entirely -- which is what takes the
    "author_id" column out of the post node's published set.
    """

    class Meta:
        """Configuration for "CursorPrunedAuthorType".

        Declares no projection: everything this node loses, it loses to the
        permission prune.
        """

        model = Author
        registry = _RCUR


class CursorPrunedPostType(DjangoObjectType):
    """Post node publishing the relation whose foreign key the cursor prints.

    The relation is what puts "author_id" in the node's published set, so
    removing it is what must withdraw the column from the cursor.
    """

    class Meta:
        """Configuration for "CursorPrunedPostType".

        Names the relation explicitly, so the FULL schema publishes
        "author_id" and the pruned one does not.
        """

        model = Post
        registry = _RCUR
        only_fields = ("id", "title", "author")


class CursorPrunedPostListType(DjangoListObjectType):
    """Container whose keyset cursor is built from the relation's foreign key.

    The ordering is server-configured, so no client argument is involved: the
    column reaches the response through "pageInfo" alone.
    """

    class Meta:
        """Configuration for "CursorPrunedPostListType".

        Carries the keyset paginator whose ordering allowlist the prune has
        to re-derive.
        """

        model = Post
        registry = _RCUR
        pagination = CursorGraphqlPagination(ordering="author_id", page_size=10)


class CursorPruneQuery(ObjectType):
    """Root query exposing the cursor-paginated post list.

    One container is enough: "pageInfo" is where the cursor is printed.
    """

    posts = DjangoListObjectField(CursorPrunedPostListType)


cursor_source = DjangoGraphQLSchema(
    query=CursorPruneQuery, registries=isolated_pair(_RCUR)
)

_PAGE_INFO_QUERY = "{ posts { pageInfo { startCursor endCursor } } }"


def _post_only_grant() -> frozenset[str]:
    """Return the permissions that keep "Post" and drop "Author".

    Reading the label off the compiled type instead of spelling the codename
    keeps the fixture honest if the label scheme changes.

    Returns:
        The read permissions the post node implies, and nothing else.
    """
    perms = implicit_perms_for_type(
        CursorPrunedPostType._meta.graphql_output_type,
        cursor_source.graphql_schema,
    )
    return frozenset(perms or ())


def _cursor_value(cursor: str) -> str:
    """Return the ordering value a cursor carries, in the clear.

    Args:
        cursor: The opaque "startCursor" / "endCursor" token from a response.

    Returns:
        The ordering-value component of the decoded cursor payload.
    """
    payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    return payload[len("cursor:") :].split(CursorGraphqlPagination._CURSOR_PK_SEP)[0]


class PrunedPageInfoScopeTests(TestCase):
    """One container, one answer: "pageInfo" is scoped like "results".

    Under "PERMISSION_SCOPED_SCHEMA" the schema serving the request is a
    per-caller clone, not the full schema the paginator was first stamped
    against, and every paginating field on a container has to know that.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed two posts by distinct authors so a cursor carries a real key.

        The first row's author id is kept so the decoded cursor can be
        compared against the value the pruned caller must not receive.
        """
        zeta = Author.objects.create(name="zeta", bio="")
        alpha = Author.objects.create(name="alpha", bio="")
        cls.first_author_id = zeta.pk
        Post.objects.create(title="p1", author=zeta)
        Post.objects.create(title="p2", author=alpha)

    def test_the_full_schema_prints_the_column_into_the_cursor(self) -> None:
        """The premise: the cursor IS the ordering column, in the clear.

        Without this the pruned assertion below could pass for the wrong
        reason -- a cursor that never carried the value at all.
        """
        result = graphql_sync(cursor_source.graphql_schema, _PAGE_INFO_QUERY)
        assert result.errors is None, result.errors
        start = result.data["posts"]["pageInfo"]["startCursor"]
        assert _cursor_value(start) == str(self.first_author_id)

    def test_the_pruned_schema_drops_the_relation_field(self) -> None:
        """The fixture only means anything if the prune actually removes it.

        Guards the rest of this class against silently testing an unpruned
        schema if the permission labels ever change.
        """
        pruned = prune_schema(cursor_source.graphql_schema, _post_only_grant())
        assert "author" not in pruned.type_map["CursorPrunedPostType"].fields
        assert "CursorPrunedAuthorType" not in pruned.type_map

    def test_the_pruned_page_info_refuses_the_pruned_away_column(self) -> None:
        """The reproduction: "startCursor" spelled out a denied column.

        The pruned SDL denies the relation exists, so the paginator behind
        "pageInfo" must be re-derived against the clone and refuse to page by
        it -- exactly as "results" already does.
        """
        pruned = prune_schema(cursor_source.graphql_schema, _post_only_grant())
        result = graphql_sync(pruned, _PAGE_INFO_QUERY)
        assert result.errors, result.data
        assert "Invalid ordering field: 'author_id'." in str(result.errors[0])

    def test_a_full_grant_keeps_the_page_info_working(self) -> None:
        """Re-deriving per clone must not break the caller who lost nothing.

        A caller holding both read permissions keeps the relation, so the
        cursor is still theirs to page by.
        """
        granted = _post_only_grant() | frozenset(
            implicit_perms_for_type(
                CursorPrunedAuthorType._meta.graphql_output_type,
                cursor_source.graphql_schema,
            )
            or ()
        )
        pruned = prune_schema(cursor_source.graphql_schema, granted)
        result = graphql_sync(pruned, _PAGE_INFO_QUERY)
        assert result.errors is None, result.errors
        start = result.data["posts"]["pageInfo"]["startCursor"]
        assert _cursor_value(start) == str(self.first_author_id)
