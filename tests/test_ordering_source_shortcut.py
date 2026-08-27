# -*- coding: utf-8 -*-
"""Tests for the documented "source=" shortcut keeping its column orderable.

A declared class attribute wins over the model-derived field of the same name,
so the ordering guard treats a declaration carrying a RESOLVER as a mask: the
name is published, the value is whatever the callable returns, and ranking by the
raw column would leak what the response hides.

"source=" compiles to a resolver too, which made the guard refuse the one
resolver that is provably a passthrough. The cost was not theoretical: a type
declaring 'id = IDField(source="id")' projects NOTHING away, and lost its primary
key -- taking cursor pagination offline with a message asserting the type hides
the key the SDL plainly carries.

The passthrough is recognised by the COMPILED resolver, not by the declaration,
so a source naming any other attribute is still a mask. Both halves are pinned
here, end to end through the paginator that refuses a hidden key.
"""

from __future__ import annotations

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import CharField, IDField, ObjectType
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
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
from .models import Author

# ---------------------------------------------------------------------------
# The same-name shortcut over a type that projects nothing away
# ---------------------------------------------------------------------------

_RSHORTCUT = Registry()


class ShortcutAuthorType(DjangoObjectType):
    """Author node re-declaring two of its own columns through "source=".

    Every declaration names the attribute it is mounted under, which is the
    documented no-op spelling. The type projects nothing away, so anything the
    ordering guard refuses here it refused for the declaration alone.
    """

    id = IDField(source="id")
    name = CharField(source="name")

    class Meta:
        """Configuration for "ShortcutAuthorType".

        Names no projection at all, so the SDL carries every column and the
        declarations above are the only thing that could withdraw one.
        """

        model = Author
        registry = _RSHORTCUT


class ShortcutAuthorListType(DjangoListObjectType):
    """Cursor-paginated container over "ShortcutAuthorType".

    Cursor pagination is the path that refuses a type hiding its primary key,
    so it is the one that has to accept this one.
    """

    class Meta:
        """Configuration for "ShortcutAuthorListType".

        Orders by "name", one of the declared columns, so the ordering
        allowlist and the primary-key gate are both exercised.
        """

        model = Author
        registry = _RSHORTCUT
        pagination = CursorGraphqlPagination(ordering="name", page_size=2)


class ShortcutQuery(ObjectType):
    """Root query exposing the cursor-paginated shortcut author list.

    Feeds the passthrough half of the tests below.
    """

    authors = DjangoListObjectField(ShortcutAuthorListType)


shortcut_schema = DjangoGraphQLSchema(
    query=ShortcutQuery, registries=isolated_pair(_RSHORTCUT)
)


# ---------------------------------------------------------------------------
# The control: a source naming a DIFFERENT attribute is a mask like any other
# ---------------------------------------------------------------------------

_RALIAS = Registry()


class AliasedAuthorType(DjangoObjectType):
    """Author node publishing "bio" over the value of another attribute.

    "only_fields" removes the real "bio" column and the declaration republishes
    the NAME over a source reading "name", so the response carries the author's
    name while the column still holds the hidden text. Ranking by that column is
    the oracle the guard exists to close.
    """

    bio = CharField(source="name")

    class Meta:
        """Configuration for "AliasedAuthorType".

        Removes "bio" from the model-derived fields; the declaration above
        republishes the name over another attribute's value.
        """

        model = Author
        registry = _RALIAS
        only_fields = ("id", "name")


class AliasedAuthorListType(DjangoListObjectType):
    """Paginated container over "AliasedAuthorType".

    Offset pagination, because this half of the story needs the client-facing
    "ordering" argument the cursor paginator does not advertise.
    """

    class Meta:
        """Configuration for "AliasedAuthorListType".

        Declares no projection of its own; the node type's applies.
        """

        model = Author
        registry = _RALIAS
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class AliasedQuery(ObjectType):
    """Root query exposing the author list whose "bio" is an alias.

    Feeds the mask half of the tests below.
    """

    authors = DjangoListObjectField(AliasedAuthorListType)


aliased_schema = DjangoGraphQLSchema(
    query=AliasedQuery, registries=isolated_pair(_RALIAS)
)


class TestTheSameNameShortcutStaysOrderable(TestCase):
    """The passthrough shortcut costs neither the column nor the key.

    Reached through the cursor paginator, which is the path that refuses a type
    hiding its primary key and therefore the path the over-refusal took down.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create three authors so a cursor page has a boundary to encode.

        Three rows against a page size of two guarantees a non-empty
        "endCursor", which is what proves the paginator ran at all.
        """
        Author.objects.create(name="alice", bio="zzz")
        Author.objects.create(name="bob", bio="aaa")
        Author.objects.create(name="carol", bio="mmm")

    def test_the_shortcut_keeps_the_column_in_the_allowlist(self) -> None:
        """Assert the declared columns survive in the ordering allowlist.

        If this fails, declaring the documented no-op costs a type every column
        it spells out.
        """
        allowed = projected_ordering_attnames(
            Author,
            shortcut_schema.graphql_schema.type_map["ShortcutAuthorType"],
        )
        assert {"id", "name", "pk"} <= allowed

    def test_cursor_pagination_is_not_refused(self) -> None:
        """Assert the cursor page resolves instead of raising.

        The reviewer's case verbatim: the type hides nothing, so the message
        about a hidden primary key would be false as well as fatal.
        """
        result = graphql_sync(
            shortcut_schema.graphql_schema,
            "{ authors { results { name } pageInfo { endCursor } } }",
        )
        assert result.errors is None, result.errors
        assert result.data["authors"]["pageInfo"]["endCursor"]

    def test_ordering_by_a_shortcut_column_is_accepted(self) -> None:
        """Assert the declared column is still a legal ordering term.

        The container orders by "name", which is one of the declared fields, so
        a refusal here would be the same defect reached through the ordering
        allowlist rather than the primary-key gate.
        """
        result = graphql_sync(
            shortcut_schema.graphql_schema,
            "{ authors { results { name } } }",
        )
        assert result.errors is None, result.errors
        assert [row["name"] for row in result.data["authors"]["results"]] == [
            "alice",
            "bob",
        ]


class TestAnAliasingSourceIsStillAMask(TestCase):
    """A source naming another attribute publishes a name, not the column.

    The other side of the shortcut: recognising the passthrough must not widen
    into recognising every "source=".
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create three authors whose "bio" order differs from their name order.

        The mismatch is what would make a successful sort observable if the
        hidden column were still honored.
        """
        Author.objects.create(name="alice", bio="zzz")
        Author.objects.create(name="bob", bio="aaa")
        Author.objects.create(name="carol", bio="mmm")

    def test_the_aliased_name_is_in_the_sdl(self) -> None:
        """Assert the declaration republished the name the projection removed.

        If this fails the premise is gone -- there would be no name to order by
        and the mask could not be reached.
        """
        assert (
            "bio" in aliased_schema.graphql_schema.type_map["AliasedAuthorType"].fields
        )

    def test_the_aliased_column_is_not_orderable(self) -> None:
        """Assert the hidden column stays out of the allowlist.

        If this fails, a client ranks the rows by the hidden text while reading
        the author's name in the response.
        """
        allowed = projected_ordering_attnames(
            Author,
            aliased_schema.graphql_schema.type_map["AliasedAuthorType"],
        )
        assert "bio" not in allowed

    def test_ordering_by_the_aliased_name_is_refused(self) -> None:
        """Assert the refusal is reached end to end through the paginator.

        The allowlist assertion above reads one function; this one proves the
        paginator consults it before touching the queryset.
        """
        result = graphql_sync(
            aliased_schema.graphql_schema,
            '{ authors { results(ordering: "bio") { bio } } }',
        )
        messages = [str(err.message) for err in (result.errors or [])]
        assert messages, "ordering by an aliased column was accepted"
        assert "Invalid ordering field: 'bio'." in messages[0]
