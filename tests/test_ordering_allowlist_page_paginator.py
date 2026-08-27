# -*- coding: utf-8 -*-
"""The ordering projection boundary, exercised through PageGraphqlPagination.

Every other test of this boundary drives it through
"LimitOffsetGraphqlPagination". That left "PageGraphqlPagination"'s own
"_apply_ordering" call site unpinned: replacing its "allowed" argument with
"None" -- which means "allow every concrete column" -- keeps the whole suite
green, because the paginator's existing ordering tests all use a column that
does not exist on the model at all, and such a term is refused with or without
the allowlist.

What only the allowlist refuses is a column that EXISTS on the model and is
projected away by the type. That is the case this module drives, on the
paginator nobody was driving it on.
"""

from __future__ import annotations

from typing import Any

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import CharField, ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations.pagination import PageGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import Author

_RPAGE = Registry()


class PagedMaskedAuthorType(DjangoObjectType):
    """Author node that hides "bio" and republishes the name over a redaction.

    "only_fields" drops the model-derived "bio"; the declared attribute below
    puts the name back with a resolver that never reads the column, so the SDL
    advertises "bio" while every response carries a constant. Ranking rows by
    it would hand back the ordering the redaction exists to withhold.
    """

    bio = CharField()

    class Meta:
        """Bind to Author, publishing only the key and the name.

        Dropping the model-derived "bio" is what makes the declared
        attribute above the only thing publishing that name.
        """

        model = Author
        registry = _RPAGE
        only_fields = ("id", "name")

    def resolve_bio(self, info: Any) -> str:
        """Return a constant in place of the author's biography.

        Args:
            info: The GraphQL resolve info for this field.

        Returns:
            redaction: The same constant for every row.
        """
        return "[redacted]"


class PagedMaskedAuthorListType(DjangoListObjectType):
    """Paginated container over the masked node, paginated BY PAGE.

    The paginator is the whole point of this module: the identical boundary is
    already covered on the limit/offset paginator.
    """

    class Meta:
        """Bind to Author with page-number pagination and no projection.

        The node type's projection is the one under test; declaring another
        here would measure the container instead.
        """

        model = Author
        registry = _RPAGE
        pagination = PageGraphqlPagination(page_size=10)


class PagedMaskQuery(ObjectType):
    """Root query exposing the page-paginated masked author list.

    One field is enough: the paginator is what this module measures.
    """

    authors = DjangoListObjectField(PagedMaskedAuthorListType)


paged_mask_schema = DjangoGraphQLSchema(
    query=PagedMaskQuery, registries=isolated_pair(_RPAGE)
)


class PagePaginatorHonoursTheOrderingAllowlistTests(TestCase):
    """Pin the allowlist on the page paginator's own query path.

    Both directions, because a refusal alone could pass on a paginator
    that refuses every ordering term.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed authors whose "bio" order differs from their "name" order.

        By name the rows read alice, bob, carol; by bio they read bob, carol,
        alice — so a leaked ordering would be visible in the response rather
        than hidden behind a coincidence.
        """
        Author.objects.create(name="alice", bio="zzz")
        Author.objects.create(name="bob", bio="aaa")
        Author.objects.create(name="carol", bio="mmm")

    def test_ordering_by_a_projected_away_column_is_refused(self) -> None:
        """The page paginator must refuse a term its type does not publish.

        Contract: this test ships broken if "PageGraphqlPagination" stops
        passing its allowlist into "_apply_ordering" — the mutation that keeps
        every other test in the suite green.
        """
        result = graphql_sync(
            paged_mask_schema.graphql_schema,
            '{ authors { results(page: 1, ordering: "bio") { name } } }',
        )

        assert result.errors, result.data
        assert "Invalid ordering field: 'bio'." in str(result.errors[0])

    def test_a_published_column_still_orders(self) -> None:
        """The control: the boundary costs nothing on a column that IS published.

        Without this, the refusal above could pass on a paginator that refuses
        every ordering term.
        """
        result = graphql_sync(
            paged_mask_schema.graphql_schema,
            '{ authors { results(page: 1, ordering: "-name") { name } } }',
        )

        assert not result.errors, result.errors
        names = [row["name"] for row in result.data["authors"]["results"]]
        assert names == ["carol", "bob", "alice"], names
