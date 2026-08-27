# -*- coding: utf-8 -*-
"""Tests separating the SERVER's default ordering from CLIENT-supplied ordering.

The projection allowlist added with the read-oracle fix exists to stop a CLIENT
sorting by a column the GraphQL type hides. It was applied to the paginator's
own "ordering=" kwarg too -- the value the OPERATOR chose when constructing the
paginator -- so a list built with "ordering='-bio'" over a type that hides
"bio" answered EVERY request with "Invalid ordering field", with no client
argument involved at all.

A server-side default cannot leak anything: the operator is ordering their own
rows, and the ordering column never reaches the response. The two provenances
are pinned apart here:

  - a configured default naming a projected-away column still serves,
  - a client argument naming the same column is still rejected,
  - a client argument that merely REPEATS the default is still checked, so the
    configured value can never be used to smuggle the term past the guard.

The stamp itself is pinned too: the allowlist must describe the node type that
actually serves "results", not whichever type happened to be registered when
the container class was defined.
"""

from __future__ import annotations

import pytest
from django.test import TestCase
from graphql import GraphQLError, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.paginations.pagination import LimitOffsetGraphqlPagination
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
# Schema: a node hiding "bio", a container whose paginator DEFAULTS to it
# ---------------------------------------------------------------------------

_RPROV = Registry()


class ProvAuthorType(DjangoObjectType):
    """Author node that hides the "bio" column from the schema.

    The hidden column is what the operator's default ordering references, so
    the allowlist and the configured default disagree on purpose.
    """

    class Meta:
        """Configuration for "ProvAuthorType".

        Hides "bio" so the container's default ordering names a projected-away
        column.
        """

        model = Author
        registry = _RPROV
        exclude_fields = ("bio",)


class ProvAuthorListType(DjangoListObjectType):
    """Paginated container whose paginator orders by the hidden column.

    This is the operator's own choice, made at construction time. No client
    argument can reach it, so the projection allowlist must not apply.
    """

    class Meta:
        """Configuration for "ProvAuthorListType".

        Uses a server-side default ordering on "bio", the column the node type
        projects away.
        """

        model = Author
        registry = _RPROV
        pagination = LimitOffsetGraphqlPagination(
            default_limit=10, max_limit=20, ordering="-bio"
        )


class ProvQuery(ObjectType):
    """Root query exposing the author list with the hidden default ordering.

    One wrapped list field is enough: the container is where the paginator's
    configured ordering is applied.
    """

    authors = DjangoListObjectField(ProvAuthorListType)


prov_schema = DjangoGraphQLSchema(query=ProvQuery, registries=isolated_pair(_RPROV))


# ---------------------------------------------------------------------------
# Divergence schema: the CONTAINER is declared BEFORE the node it serves
# ---------------------------------------------------------------------------

_RDIV = Registry()


class DivPostListType(DjangoListObjectType):
    """Container declared while the registry holds NO node type for Post.

    Class definition therefore cannot see the projecting node type below: the
    registry auto-creates an unprojected stand-in, and the eager allowlist stamp
    reads that stand-in instead of the type that ends up serving "results".
    """

    class Meta:
        """Configuration for "DivPostListType".

        Declared first on purpose so the eager stamp and the "results" thunk
        resolve different node types.
        """

        model = Post
        registry = _RDIV
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class DivPostType(DjangoObjectType):
    """Post node hiding "views", registered AFTER the container above.

    Registration is last-wins, so this is the type the container's "results"
    thunk resolves -- and the type whose projection the ordering allowlist has
    to describe.
    """

    class Meta:
        """Configuration for "DivPostType".

        Hides "views" so the divergent stamp has a column to leak.
        """

        model = Post
        registry = _RDIV
        exclude_fields = ("views",)


class DivQuery(ObjectType):
    """Root query exposing the post list whose node type was declared late.

    The declaration order above is the whole point of this schema.
    """

    posts = DjangoListObjectField(DivPostListType)


div_schema = DjangoGraphQLSchema(query=DivQuery, registries=isolated_pair(_RDIV))


# ---------------------------------------------------------------------------
# Shared-paginator schemas: ONE instance mounted on two containers
# ---------------------------------------------------------------------------

#: The ordinary shape: a module-level paginator instance reused by several list
#: types. Whoever stamps it LAST would decide every other type's allowlist if
#: the stamp were not applied to a per-type copy.
_shared_paginator = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)

_RSHARE_A = Registry()


class ShareHidesBioAuthorType(DjangoObjectType):
    """Author node hiding "bio", served by the shared paginator.

    Its allowlist must exclude "bio" no matter what the other container's node
    type exposes.
    """

    class Meta:
        """Configuration for "ShareHidesBioAuthorType".

        Hides "bio" so the shared instance has a column to disagree about.
        """

        model = Author
        registry = _RSHARE_A
        exclude_fields = ("bio",)


class ShareHidesBioAuthorListType(DjangoListObjectType):
    """Container mounting the SHARED paginator over the bio-hiding node.

    Declared first, so a last-wins stamp on the shared instance would describe
    the OTHER container's node type.
    """

    class Meta:
        """Configuration for "ShareHidesBioAuthorListType".

        Mounts the module-level paginator instance rather than its own.
        """

        model = Author
        registry = _RSHARE_A
        pagination = _shared_paginator


class ShareBioQuery(ObjectType):
    """Root query exposing the bio-hiding author list.

    Feeds the half of the shared-instance test that catches a WIDENED
    allowlist.
    """

    authors = DjangoListObjectField(ShareHidesBioAuthorListType)


share_bio_schema = DjangoGraphQLSchema(
    query=ShareBioQuery, registries=isolated_pair(_RSHARE_A)
)

_RSHARE_B = Registry()


class ShareHidesNameAuthorType(DjangoObjectType):
    """Author node hiding "name" instead, served by the same paginator.

    It exposes "bio", the very column the other node type hides, which is what
    makes a shared stamp observable in both directions.
    """

    class Meta:
        """Configuration for "ShareHidesNameAuthorType".

        Hides "name" so a projection applies while "bio" stays orderable.
        """

        model = Author
        registry = _RSHARE_B
        exclude_fields = ("name",)


class ShareHidesNameAuthorListType(DjangoListObjectType):
    """Container mounting the SHARED paginator over the name-hiding node.

    Declared second, so it is the stamp that would win if the instance were
    not copied.
    """

    class Meta:
        """Configuration for "ShareHidesNameAuthorListType".

        Mounts the same module-level paginator instance.
        """

        model = Author
        registry = _RSHARE_B
        pagination = _shared_paginator


class ShareNameQuery(ObjectType):
    """Root query exposing the name-hiding author list.

    Feeds the half of the shared-instance test that catches a NARROWED
    allowlist.
    """

    authors = DjangoListObjectField(ShareHidesNameAuthorListType)


share_name_schema = DjangoGraphQLSchema(
    query=ShareNameQuery, registries=isolated_pair(_RSHARE_B)
)


@pytest.mark.django_db
class ServerDefaultOrderingTests(TestCase):
    """The operator's configured ordering is not client input.

    Pins the split: the projection gates the argument, never the fallback.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors whose hidden "bio" values order them.

        Returns:
            None.
        """
        Author.objects.create(name="alpha", bio="b")
        Author.objects.create(name="beta", bio="a")

    def test_configured_default_on_projected_away_column_still_serves(self) -> None:
        """A server-side default ordering must not be gated by the projection.

        Returns:
            None.
        """
        result = graphql_sync(
            prov_schema.graphql_schema,
            "{ authors { results { name } totalCount } }",
        )
        assert result.errors is None, [str(e) for e in result.errors or ()]
        assert result.data is not None
        assert [row["name"] for row in result.data["authors"]["results"]] == [
            "alpha",
            "beta",
        ]

    def test_client_ordering_on_projected_away_column_is_still_rejected(self) -> None:
        """The allowlist still applies to the argument a client supplies.

        Returns:
            None.
        """
        result = graphql_sync(
            prov_schema.graphql_schema,
            '{ authors { results(ordering: "bio") { name } } }',
        )
        assert result.errors is not None
        assert "Invalid ordering field: 'bio'" in str(result.errors[0])

    def test_client_repeating_the_default_is_still_rejected(self) -> None:
        """Echoing the configured default back must not bypass the allowlist.

        Returns:
            None.
        """
        result = graphql_sync(
            prov_schema.graphql_schema,
            '{ authors { results(ordering: "-bio") { name } } }',
        )
        assert result.errors is not None
        assert "Invalid ordering field: 'bio'" in str(result.errors[0])


@pytest.mark.django_db
class DivergentAllowlistStampTests(TestCase):
    """The allowlist must follow the type that actually serves "results".

    Pins the divergence the eager class-definition stamp could not see.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with two posts of differing view counts.

        Returns:
            None.
        """
        author = Author.objects.create(name="writer", bio="")
        Post.objects.create(title="low", author=author, views=1)
        Post.objects.create(title="high", author=author, views=99)

    def test_hidden_column_is_not_orderable_when_the_node_registers_late(self) -> None:
        """A late-registered projecting node type must still gate the ordering.

        Returns:
            None.
        """
        result = graphql_sync(
            div_schema.graphql_schema,
            '{ posts { results(ordering: "-views") { title } } }',
        )
        assert result.errors is not None
        assert "Invalid ordering field: 'views'" in str(result.errors[0])


@pytest.mark.django_db
class SharedPaginatorInstanceTests(TestCase):
    """One paginator instance mounted on two list types keeps two allowlists.

    The stamp is applied to a COPY per list type. Without the copy the last
    type compiled decides every other type's allowlist, which either widens one
    back to a hidden column or narrows another below its own projection. Both
    directions are asserted, so whichever container happens to stamp last the
    regression is caught.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors whose "bio" order differs from their name order.

        Returns:
            None.
        """
        Author.objects.create(name="alpha", bio="z")
        Author.objects.create(name="beta", bio="a")

    def test_the_hiding_container_still_rejects_its_own_hidden_column(self) -> None:
        """The bio-hiding list must not inherit the other list's wider allowlist.

        Returns:
            None.
        """
        result = graphql_sync(
            share_bio_schema.graphql_schema,
            '{ authors { results(ordering: "bio") { name } } }',
        )
        assert result.errors is not None, (
            "the shared paginator carried the OTHER container's allowlist, so a "
            "projected-away column became orderable"
        )
        assert "Invalid ordering field: 'bio'" in str(result.errors[0])

    def test_the_exposing_container_still_allows_that_same_column(self) -> None:
        """The name-hiding list must not inherit the other list's narrower allowlist.

        Returns:
            None.
        """
        result = graphql_sync(
            share_name_schema.graphql_schema,
            '{ authors { results(ordering: "bio") { bio } } }',
        )
        assert result.errors is None, (
            "the shared paginator carried the OTHER container's allowlist, so a "
            f"column this type exposes stopped being orderable: {result.errors}"
        )
        assert [row["bio"] for row in result.data["authors"]["results"]] == ["a", "z"]


@pytest.mark.django_db
class ServerGeneratedTiebreakTests(TestCase):
    """The paginator's OWN pk tiebreak is not client input either.

    On the prefetch-cache path a client ordering argument that normalizes to
    nothing leaves the projection allowlist in play while the paginator
    substitutes its own pk ordering for determinism. Validating a
    server-GENERATED term against a CLIENT-argument allowlist takes a nested
    list whose child type hides its pk out of service entirely.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with two posts inserted out of title order.

        Returns:
            None.
        """
        author = Author.objects.create(name="writer", bio="")
        Post.objects.create(title="b", author=author, views=1)
        Post.objects.create(title="a", author=author, views=2)

    def test_empty_client_ordering_falls_back_to_the_pk_without_raising(self) -> None:
        """An ordering argument that normalizes to nothing must not fail the page.

        Returns:
            None.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)
        # What a child type that projects its pk away stamps: "id" is absent.
        paginator.ordering_allowed_attnames = {"title"}
        rows = list(Post.objects.order_by("-pk"))

        page = paginator.paginate_queryset(rows, ordering=",")

        assert [row.title for row in page] == ["b", "a"]

    def test_a_real_client_term_outside_the_allowlist_still_raises(self) -> None:
        """Exempting the generated tiebreak must not exempt the argument itself.

        Returns:
            None.
        """
        paginator = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)
        paginator.ordering_allowed_attnames = {"title"}
        rows = list(Post.objects.all())

        with pytest.raises(GraphQLError, match="Invalid ordering field: 'views'"):
            paginator.paginate_queryset(rows, ordering="views")
