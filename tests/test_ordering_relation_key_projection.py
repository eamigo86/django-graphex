# -*- coding: utf-8 -*-
"""Tests for a forward FK's column being orderable only when the KEY is published.

The ordering allowlist maps a published relation field back to the column that
relation owns: "author" in the SDL means "author_id" in the ORM. That mapping was
written as an unconditional admission -- the relation is published, therefore its
column is orderable -- justified by "the id is already readable through
'author { id }'".

That justification is a claim about the TARGET type, and nobody asked it. A node
type that publishes "author" while the author type projects its primary key away
publishes no path to that key, so ordering by "author_id" ranks the rows by a
value the schema never hands out: the same read oracle the projection closes on
every other column, reached through the one column the allowlist admitted on
faith.

"core.output_compiler.publishes_column_value" is the predicate that asks. It
follows the compiled relation field to the type it resolves to and asks that type
for the referenced key, so the answer describes the schema serving the request
rather than a rule about relations in general.
"""

from __future__ import annotations

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.paginations.pagination import (
    LimitOffsetGraphqlPagination,
    projected_ordering_attnames,
)
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
# The target type hides its key: the relation is published, the column is not
# ---------------------------------------------------------------------------

_RHIDDEN = Registry()


class KeylessAuthorType(DjangoObjectType):
    """Author node publishing its name and nothing else.

    The primary key is projected away, so no selection anywhere in the schema
    reaches an author's key -- which is what makes ordering posts by
    "author_id" a ranking by an unreadable value.
    """

    class Meta:
        """Configuration for "KeylessAuthorType".

        "only_fields" names the display column alone, so the key is gone from
        the SDL and no relation anywhere leads back to it.
        """

        model = Author
        registry = _RHIDDEN
        only_fields = ("name",)


class KeylessRefPostType(DjangoObjectType):
    """Post node publishing the relation to a key-less author type.

    Projects nothing away itself: the relation field is right there in the SDL,
    which is exactly the shape that used to admit "author_id".
    """

    class Meta:
        """Configuration for "KeylessRefPostType".

        Names the relation explicitly, so the SDL is the proof that the post
        type publishes it while the column behind it stays unreadable.
        """

        model = Post
        registry = _RHIDDEN
        only_fields = ("id", "title", "author")


class KeylessRefPostListType(DjangoListObjectType):
    """Paginated container over "KeylessRefPostType".

    Offset pagination, because the client-facing "ordering" argument is what
    carries the term under test.
    """

    class Meta:
        """Configuration for "KeylessRefPostListType".

        Declares no projection of its own; the node type's applies.
        """

        model = Post
        registry = _RHIDDEN
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class KeylessRefQuery(ObjectType):
    """Root query exposing the posts whose author type hides its key.

    Feeds the refusal half of the tests below.
    """

    posts = DjangoListObjectField(KeylessRefPostListType)


keyless_schema = DjangoGraphQLSchema(
    query=KeylessRefQuery, registries=isolated_pair(_RHIDDEN)
)


# ---------------------------------------------------------------------------
# The control: the same relation, with the key published
# ---------------------------------------------------------------------------

_RKEYED = Registry()


class KeyedAuthorType(DjangoObjectType):
    """Author node publishing its key alongside its name.

    The control for the shape above: identical in every respect except that
    "author { id }" is a real selection, so ranking by "author_id" reveals an
    order the client can already read off the rows.
    """

    class Meta:
        """Configuration for "KeyedAuthorType".

        Names "id" alongside the display column, so the key travels with every
        author the client selects.
        """

        model = Author
        registry = _RKEYED
        only_fields = ("id", "name")


class KeyedRefPostType(DjangoObjectType):
    """Post node publishing the relation to a key-publishing author type.

    Identical to the shape above but for the target type's projection, which is
    the single variable the pair isolates.
    """

    class Meta:
        """Configuration for "KeyedRefPostType".

        The same field list as the projected shape, so nothing but the author
        type's own projection can change the answer.
        """

        model = Post
        registry = _RKEYED
        only_fields = ("id", "title", "author")


class KeyedRefPostListType(DjangoListObjectType):
    """Paginated container over "KeyedRefPostType".

    Offset pagination, matching the projected shape's container exactly.
    """

    class Meta:
        """Configuration for "KeyedRefPostListType".

        Declares no projection of its own; the node type's applies.
        """

        model = Post
        registry = _RKEYED
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class KeyedRefQuery(ObjectType):
    """Root query exposing the posts whose author type publishes its key.

    Feeds the control half of the tests below.
    """

    posts = DjangoListObjectField(KeyedRefPostListType)


keyed_schema = DjangoGraphQLSchema(
    query=KeyedRefQuery, registries=isolated_pair(_RKEYED)
)


def _errors(schema: DjangoGraphQLSchema, query: str) -> list[str]:
    """Execute "query" and return its error messages.

    Args:
        schema: The compiled schema to execute against.
        query: The GraphQL document to execute.

    Returns:
        The list of error messages, empty when the query succeeded.
    """
    result = graphql_sync(schema.graphql_schema, query)
    return [str(err.message) for err in (result.errors or [])]


class TestRelationColumnFollowsTheTargetType(TestCase):
    """The FK column rides on the TARGET type publishing the key it stores.

    Both directions in one class: the projected target withdraws the column,
    the key-publishing target keeps it, and the two schemas differ in nothing
    else.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors whose key order is the reverse of their name order.

        The mismatch is what makes a successful sort observable: ordering by
        "author_id" would return the posts in creation order, ordering by the
        author name returns them the other way round.
        """
        first = Author.objects.create(name="zoe", bio="")
        second = Author.objects.create(name="adam", bio="")
        Post.objects.create(title="first", author=first)
        Post.objects.create(title="second", author=second)

    def test_the_relation_is_published(self) -> None:
        """Assert the post type still publishes the author relation.

        If this fails the premise is gone: the column would be unreachable for
        an unrelated reason and the allowlist question would never arise.
        """
        assert (
            "author"
            in keyless_schema.graphql_schema.type_map["KeylessRefPostType"].fields
        )

    def test_the_targets_key_is_not_published(self) -> None:
        """Assert the author type publishes no key field.

        The other half of the premise: with no "id" on the author type, there
        is no selection anywhere that hands the client an author's key.
        """
        assert (
            "id"
            not in keyless_schema.graphql_schema.type_map["KeylessAuthorType"].fields
        )

    def test_the_column_is_not_in_the_allowlist(self) -> None:
        """Assert "author_id" is absent from the allowlist of the projected type.

        If this fails the allowlist admits a column on the strength of the
        relation alone and every guard reading it inherits the hole.
        """
        allowed = projected_ordering_attnames(
            Post,
            keyless_schema.graphql_schema.type_map["KeylessRefPostType"],
        )
        assert "author_id" not in allowed

    def test_ordering_by_the_relation_column_is_refused(self) -> None:
        """Assert ordering by the FK column is rejected end to end.

        If this fails, a client ranks the posts by an author key the schema
        never hands out -- and with a filter isolating two rows, recovers the
        comparison exactly.
        """
        errors = _errors(
            keyless_schema,
            '{ posts { results(ordering: "authorId") { title } } }',
        )
        assert errors, "ordering by an unpublished relation key was accepted"
        assert "Invalid ordering field: 'author_id'." in errors[0]

    def test_the_published_key_keeps_the_column_orderable(self) -> None:
        """Assert the control schema still orders by the FK column.

        If this fails the fix over-refuses: an author key the client reads
        through "author { id }" is not hidden by any measure, and ordering by
        it must keep working.
        """
        result = graphql_sync(
            keyed_schema.graphql_schema,
            '{ posts { results(ordering: "-authorId") { title } } }',
        )
        assert result.errors is None, result.errors
        titles = [row["title"] for row in result.data["posts"]["results"]]
        assert titles == ["second", "first"]

    def test_the_control_allowlist_carries_the_column(self) -> None:
        """Assert the control type's allowlist carries "author_id".

        The direct reading of the case above, so a regression names the
        allowlist rather than the query.
        """
        allowed = projected_ordering_attnames(
            Post,
            keyed_schema.graphql_schema.type_map["KeyedRefPostType"],
        )
        assert "author_id" in allowed
