# -*- coding: utf-8 -*-
"""Tests for the ordering allowlist honoring the TYPE's projection (read oracle).

Before this suite the "ordering" argument was validated against the MODEL's
concrete columns, never against the columns the GraphQL type actually exposes.
A column removed with "only_fields" / "exclude_fields" was therefore invisible
in the SDL, unselectable and unfilterable -- and still fully sortable, which
turns "ordering" into a read oracle: repeated queries that sort by the hidden
column rank the rows by it, and combined with a filter that isolates two rows
the exact value can be recovered.

The guarantee pinned here is that a projected-away column is rejected on EVERY
ordering path:

  - the queryset path ("_apply_ordering" -> "_validate_ordering_terms"),
  - the prefetch-cache / in-memory path ("_inmemory_order"),
  - the DB-side nested window path ("build_window_prefetch"), which must not
    accept a term the queryset path would reject.

The primary key follows the projection like every other column. Ordering by
"pk", by the pk's field name or by its attname works while the pk is exposed --
the ordinary surrogate-"id" case, where ranking rows by an identifier the client
already reads gives nothing away. A NATURAL key (a slug, a code, an email)
carries real data and can be hidden like anything else; while it is hidden all
three spellings are rejected, because they resolve to the same column.

Two more claims are pinned here because prose alone let the pk hole through
review:

  - The allowlist really is the mirror of the compiled output fields it says it
    is, checked against the built type map rather than re-read from "Meta".
  - "CursorGraphqlPagination" is gated on its SERVER-CONFIGURED ordering, unlike
    the other paginators, because its cursors echo the ordering value back.
"""

from __future__ import annotations

import base64

import pytest
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from graphql import GraphQLError, graphql_sync

from django_graphex._strconv import to_snake_case
from django_graphex.core import ObjectType
from django_graphex.fields import (
    DjangoFilterPaginateListField,
    DjangoNestedListObjectField,
)
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    _inmemory_order,
    _validate_ordering_terms,
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
from .models import Author, CustomPKProduct, MtiRestaurant, Post

# ---------------------------------------------------------------------------
# Root schema: a list type whose node hides "bio"
# ---------------------------------------------------------------------------

_RPROJ = Registry()


class ProjAuthorType(DjangoObjectType):
    """Author node that hides the "bio" column from the schema.

    "bio" stands in for any sensitive column a project keeps out of the SDL
    with "exclude_fields" (the documented way to hide "password" and friends).
    """

    class Meta:
        """Configuration for "ProjAuthorType".

        Hides "bio" so the ordering allowlist has a projected-away column to
        reject.
        """

        model = Author
        registry = _RPROJ
        exclude_fields = ("bio",)


class ProjAuthorListType(DjangoListObjectType):
    """Paginated container over "ProjAuthorType".

    Declares no projection of its own: the container must inherit the node
    type's, which is the shape most projects write.
    """

    class Meta:
        """Configuration for "ProjAuthorListType".

        Uses limit/offset pagination so the "ordering" argument is exposed.
        """

        model = Author
        registry = _RPROJ
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class ProjQuery(ObjectType):
    """Root query exposing the projected author list, wrapped and flat.

    The flat field paginates in its own resolver instead of going through the
    list container, so it needs its own coverage.
    """

    authors = DjangoListObjectField(ProjAuthorListType)
    flat_authors = DjangoFilterPaginateListField(
        ProjAuthorType,
        pagination=LimitOffsetGraphqlPagination(default_limit=10, max_limit=20),
    )


proj_schema = DjangoGraphQLSchema(query=ProjQuery, registries=isolated_pair(_RPROJ))


# ---------------------------------------------------------------------------
# Nested schema: a nested list type whose node hides "views"
# ---------------------------------------------------------------------------

_RNEST = Registry()


class NestPostType(DjangoObjectType):
    """Post node that hides the "views" column from the schema.

    Backs the nested window-pagination path, which validates ordering terms
    separately from the queryset path.
    """

    class Meta:
        """Configuration for "NestPostType".

        Hides "views" so the nested window path has a projected-away column.
        """

        model = Post
        registry = _RNEST
        exclude_fields = ("views",)


class NestPostListType(DjangoListObjectType):
    """Paginated container over "NestPostType".

    Mounted as the nested "posts" accessor so the DB-side window slice runs.
    """

    class Meta:
        """Configuration for "NestPostListType".

        Uses limit/offset pagination, the only paginator that supports the
        DB-side window slice.
        """

        model = Post
        registry = _RNEST
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class NestAuthorType(DjangoObjectType):
    """Author node exposing its posts as a nested paginated list.

    The nested list is what routes the query through "build_window_prefetch".
    """

    posts = DjangoNestedListObjectField(NestPostListType, accessor="posts")

    class Meta:
        """Configuration for "NestAuthorType".

        Declares no projection; only the child type hides a column.
        """

        model = Author
        registry = _RNEST


class NestAuthorListType(DjangoListObjectType):
    """Paginated container over "NestAuthorType".

    The root entry point for the nested-window tests.
    """

    class Meta:
        """Configuration for "NestAuthorListType".

        Uses limit/offset pagination so the root list is windowed too.
        """

        model = Author
        registry = _RNEST
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class NestQuery(ObjectType):
    """Root query exposing the author list with nested projected posts.

    Feeds the nested-window read-oracle tests below.
    """

    authors = DjangoListObjectField(NestAuthorListType)


nest_schema = DjangoGraphQLSchema(query=NestQuery, registries=isolated_pair(_RNEST))


# ---------------------------------------------------------------------------
# Natural-primary-key schema: the pk itself is projected away
# ---------------------------------------------------------------------------

_RPK = Registry()


class HiddenPkProductType(DjangoObjectType):
    """Product node whose NATURAL primary key ("slug") is projected away.

    A slug / code / email primary key carries real business data, so hiding it
    with "only_fields" is a projection like any other -- the pk exemption must
    not hand it back through "ordering".
    """

    class Meta:
        """Configuration for "HiddenPkProductType".

        Restricts the type to "title" so the slug primary key is projected
        away and the pk exemption has something real to leak.
        """

        model = CustomPKProduct
        registry = _RPK
        only_fields = ("title",)


class HiddenPkProductListType(DjangoListObjectType):
    """Paginated container over "HiddenPkProductType".

    Uses limit/offset pagination so the "ordering" argument is exposed.
    """

    class Meta:
        """Configuration for "HiddenPkProductListType".

        Declares no projection of its own; the node type's applies.
        """

        model = CustomPKProduct
        registry = _RPK
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class HiddenPkQuery(ObjectType):
    """Root query exposing the product list whose pk is hidden.

    Feeds the natural-primary-key oracle tests below.
    """

    products = DjangoListObjectField(HiddenPkProductListType)


hidden_pk_schema = DjangoGraphQLSchema(
    query=HiddenPkQuery, registries=isolated_pair(_RPK)
)


# ---------------------------------------------------------------------------
# Cursor schema: the server-configured ordering names a hidden column
# ---------------------------------------------------------------------------

_RCUR = Registry()


class CursorAuthorType(DjangoObjectType):
    """Author node that hides "bio" and is paged by keyset cursor.

    The cursor paginator's own "ordering=" names that hidden column, which is
    the configuration the echoed-cursor test attacks.
    """

    class Meta:
        """Configuration for "CursorAuthorType".

        Hides "bio" so the cursor's ordering value is a column the client
        cannot select.
        """

        model = Author
        registry = _RCUR
        exclude_fields = ("bio",)


class CursorAuthorListType(DjangoListObjectType):
    """Paginated container over "CursorAuthorType" using keyset cursors.

    "CursorGraphqlPagination" takes no "ordering" argument, so this ordering is
    purely server-configured -- exactly the case the server-default exemption
    claims leaks nothing.
    """

    class Meta:
        """Configuration for "CursorAuthorListType".

        Configures the cursor ordering to the hidden "bio" column.
        """

        model = Author
        registry = _RCUR
        pagination = CursorGraphqlPagination(ordering="bio")


class CursorQuery(ObjectType):
    """Root query exposing the cursor-paged author list.

    Feeds the echoed-cursor tests below.
    """

    authors = DjangoListObjectField(CursorAuthorListType)


cursor_schema = DjangoGraphQLSchema(query=CursorQuery, registries=isolated_pair(_RCUR))


# ---------------------------------------------------------------------------
# Cursor schema: the ordering column is exposed but the pk TIEBREAK is hidden
# ---------------------------------------------------------------------------

_RCURPK = Registry()


class CursorHiddenPkProductType(DjangoObjectType):
    """Product node whose NATURAL primary key is projected away.

    The cursor ordering names "title", which the type does expose, so the
    ordering allowlist has nothing to object to. The pk the paginator appends
    as its tiebreak is the hidden slug.
    """

    class Meta:
        """Configuration for "CursorHiddenPkProductType".

        Restricts the type to "title" so the slug primary key is projected
        away while the cursor's ordering column stays legitimate.
        """

        model = CustomPKProduct
        registry = _RCURPK
        only_fields = ("title",)


class CursorHiddenPkProductListType(DjangoListObjectType):
    """Keyset-paged container over a type that hides its primary key.

    Every composite cursor this container emits carries the boundary row's pk
    as its tiebreak component, so the hidden slug travels in "startCursor" and
    "endCursor" under nothing but base64.
    """

    class Meta:
        """Configuration for "CursorHiddenPkProductListType".

        Orders by the EXPOSED "title" column so the leak cannot be blamed on
        the ordering allowlist.
        """

        model = CustomPKProduct
        registry = _RCURPK
        pagination = CursorGraphqlPagination(ordering="title")


class CursorHiddenPkQuery(ObjectType):
    """Root query exposing the keyset-paged product list.

    Feeds the hidden-tiebreak tests below.
    """

    products = DjangoListObjectField(CursorHiddenPkProductListType)


cursor_hidden_pk_schema = DjangoGraphQLSchema(
    query=CursorHiddenPkQuery, registries=isolated_pair(_RCURPK)
)


# ---------------------------------------------------------------------------
# Nested window schema: the CHILD type projects its own pk away
# ---------------------------------------------------------------------------

_RWPK = Registry()


class WinPkPostType(DjangoObjectType):
    """Nested post node that projects its own primary key away.

    The DB-side window slice emits "ORDER BY <pk>" itself when no ordering is
    given, so this is the configuration the old unconditional pk exemption
    existed to protect. It is here to prove the protection is not needed.
    """

    class Meta:
        """Configuration for "WinPkPostType".

        Restricts the type to "title" so both "id" and "views" are projected
        away.
        """

        model = Post
        registry = _RWPK
        only_fields = ("title",)


class WinPkPostListType(DjangoListObjectType):
    """Paginated container over "WinPkPostType".

    Mounted as the nested accessor so the window-slice path runs.
    """

    class Meta:
        """Configuration for "WinPkPostListType".

        Uses limit/offset pagination, the only paginator the window slice
        supports.
        """

        model = Post
        registry = _RWPK
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class WinPkAuthorType(DjangoObjectType):
    """Author node exposing the pk-projecting posts as a nested list.

    Routes the query through "build_window_prefetch".
    """

    posts = DjangoNestedListObjectField(WinPkPostListType, accessor="posts")

    class Meta:
        """Configuration for "WinPkAuthorType".

        Declares no projection; only the child type hides columns.
        """

        model = Author
        registry = _RWPK


class WinPkAuthorListType(DjangoListObjectType):
    """Paginated container over "WinPkAuthorType".

    The root entry point for the nested pk-projection tests.
    """

    class Meta:
        """Configuration for "WinPkAuthorListType".

        Uses limit/offset pagination so the root list is windowed too.
        """

        model = Author
        registry = _RWPK
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class WinPkQuery(ObjectType):
    """Root query exposing authors with pk-projecting nested posts.

    Feeds the nested window pk tests below.
    """

    authors = DjangoListObjectField(WinPkAuthorListType)


win_pk_schema = DjangoGraphQLSchema(query=WinPkQuery, registries=isolated_pair(_RWPK))


# ---------------------------------------------------------------------------
# Multi-table-inheritance schema: the implicit parent link
# ---------------------------------------------------------------------------

_RMTI = Registry()


class MtiRestaurantType(DjangoObjectType):
    """Child node of a multi-table-inherited model, carrying a projection.

    A projection of ANY kind is what makes "projected_ordering_attnames" build
    a real allowlist instead of returning "None", which is what the parent-link
    divergence needs to be visible.
    """

    class Meta:
        """Configuration for "MtiRestaurantType".

        Hides "address" so a projection applies; the implicit "place_ptr"
        parent link is not named either way.
        """

        model = MtiRestaurant
        registry = _RMTI
        exclude_fields = ("address",)


class MtiRestaurantListType(DjangoListObjectType):
    """Paginated container over "MtiRestaurantType".

    Present so the node type is compiled into a schema and its SDL fields can
    be read back.
    """

    class Meta:
        """Configuration for "MtiRestaurantListType".

        Declares no projection of its own; the node type's applies.
        """

        model = MtiRestaurant
        registry = _RMTI
        pagination = LimitOffsetGraphqlPagination(default_limit=10, max_limit=20)


class MtiQuery(ObjectType):
    """Root query exposing the multi-table-inherited child node.

    Feeds the parent-link enumeration test below.
    """

    restaurants = DjangoListObjectField(MtiRestaurantListType)


mti_schema = DjangoGraphQLSchema(query=MtiQuery, registries=isolated_pair(_RMTI))


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


# ---------------------------------------------------------------------------
# The projected-away column is rejected on the queryset path
# ---------------------------------------------------------------------------


class TestProjectedColumnRejectedOnRootList(TestCase):
    """A column hidden by the node type must not be orderable.

    Covers both directions and both the presence check in the SDL and the
    runtime rejection, since the oracle needs only the ranking to work.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create three authors whose "bio" order differs from their name order.

        The mismatch is what makes a successful sort observable: if the hidden
        column were still honored, the returned name sequence would reveal it.
        """
        Author.objects.create(name="alice", bio="zzz")
        Author.objects.create(name="bob", bio="aaa")
        Author.objects.create(name="carol", bio="mmm")

    def test_hidden_column_absent_from_sdl(self) -> None:
        """Assert "bio" is not exposed on the projected author type.

        If this fails the premise is gone -- the column would be selectable
        outright and the ordering allowlist would not be the last line of
        defence.
        """
        sdl = str(proj_schema)
        assert "bio" not in sdl

    def test_ordering_by_hidden_column_is_rejected(self) -> None:
        """Assert ordering by the hidden column raises "Invalid ordering field".

        If this fails, sorting by the hidden column ranks the rows by it and
        the response leaks that ranking to a client that cannot even select
        the column.
        """
        errors = _errors(
            proj_schema,
            '{ authors { results(ordering: "bio") { name } } }',
        )
        assert errors, "ordering by a projected-away column was accepted"
        assert "Invalid ordering field: 'bio'." in errors[0]

    def test_ordering_by_hidden_column_descending_is_rejected(self) -> None:
        """Assert the descending spelling of the hidden column is rejected too.

        If this fails, the direction prefix alone would be enough to bypass
        the allowlist and recover the reverse ranking.
        """
        errors = _errors(
            proj_schema,
            '{ authors { results(ordering: "-bio") { name } } }',
        )
        assert errors, "descending ordering by a projected-away column was accepted"
        assert "Invalid ordering field: 'bio'." in errors[0]

    def test_ordering_by_exposed_column_still_works(self) -> None:
        """Assert an exposed column is still orderable.

        If this fails, the allowlist has been narrowed past the projection and
        legitimate ordering is broken.
        """
        result = graphql_sync(
            proj_schema.graphql_schema,
            '{ authors { results(ordering: "name") { name } } }',
        )
        assert result.errors is None, result.errors
        names = [row["name"] for row in result.data["authors"]["results"]]
        assert names == ["alice", "bob", "carol"]

    def test_ordering_by_a_projected_pk_still_works(self) -> None:
        """Assert a pk the type still exposes stays orderable.

        "ProjAuthorType" hides only "bio", so "id" survives its projection and
        both "id" and Django's "pk" alias must keep working -- that is the
        surrogate-key case the exemption exists for. If this fails, the
        allowlist has been narrowed past the projection.
        """
        for term in ("id", "pk"):
            result = graphql_sync(
                proj_schema.graphql_schema,
                '{ authors { results(ordering: "%s") { name } } }' % term,
            )
            assert result.errors is None, (term, result.errors)
            assert len(result.data["authors"]["results"]) == 3

    def test_flat_list_field_rejects_hidden_column(self) -> None:
        """Assert the flat paginated list field rejects the hidden column too.

        "DjangoFilterPaginateListField" paginates inside its own resolver and
        never touches the list container's paginator. If this fails, mounting
        the same projected type as a flat list reopens the oracle in full.
        """
        errors = _errors(
            proj_schema,
            '{ flatAuthors(ordering: "bio") { name } }',
        )
        assert errors, "flat list ordering by a projected-away column was accepted"
        assert "Invalid ordering field: 'bio'." in errors[0]

    def test_flat_list_field_orders_by_exposed_column(self) -> None:
        """Assert the flat paginated list field still orders by an exposed column.

        If this fails, the flat field's allowlist is narrower than the type's
        projection.
        """
        result = graphql_sync(
            proj_schema.graphql_schema,
            '{ flatAuthors(ordering: "-name") { name } }',
        )
        assert result.errors is None, result.errors
        assert [row["name"] for row in result.data["flatAuthors"]] == [
            "carol",
            "bob",
            "alice",
        ]


# ---------------------------------------------------------------------------
# The projected-away column is rejected on the nested window path
# ---------------------------------------------------------------------------


class TestProjectedColumnRejectedOnNestedWindow(TestCase):
    """A nested list must not order by a column its own node type hides.

    The DB-side window slice validates ordering terms independently of the
    queryset path, so it needs its own coverage.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with three posts whose view counts invert the titles.

        The inverted order makes a successful hidden-column sort observable
        through the exposed titles alone.
        """
        author = Author.objects.create(name="nest")
        Post.objects.create(title="a", author=author, views=30)
        Post.objects.create(title="b", author=author, views=10)
        Post.objects.create(title="c", author=author, views=20)

    def test_hidden_column_absent_from_nested_sdl(self) -> None:
        """Assert "views" is not exposed on the nested post type.

        If this fails the premise is gone and the column is selectable.
        """
        sdl = str(nest_schema)
        assert "views" not in sdl

    def test_nested_ordering_by_hidden_column_is_rejected(self) -> None:
        """Assert the nested list rejects ordering by the hidden column.

        If this fails, the window path applies the ORDER BY in SQL and returns
        the rows already sliced, so no later validation ever runs -- the
        titles come back ranked by the hidden view counts.
        """
        errors = _errors(
            nest_schema,
            """
            { authors { results {
                posts { results(ordering: "-views") { title } }
            } } }
            """,
        )
        assert errors, "nested ordering by a projected-away column was accepted"
        assert "Invalid ordering field: 'views'." in errors[0]

    def test_nested_ordering_by_exposed_column_still_works(self) -> None:
        """Assert the nested list still orders by an exposed column.

        If this fails, the window path's allowlist is narrower than the
        projection and legitimate nested ordering is broken.
        """
        result = graphql_sync(
            nest_schema.graphql_schema,
            """
            { authors { results {
                posts { results(ordering: "-title") { title } }
            } } }
            """,
        )
        assert result.errors is None, result.errors
        titles = [
            row["title"]
            for row in result.data["authors"]["results"][0]["posts"]["results"]
        ]
        assert titles == ["c", "b", "a"]


# ---------------------------------------------------------------------------
# Unit level: the allowlist parameter itself
# ---------------------------------------------------------------------------


class TestAllowedParameterUnit(TestCase):
    """The "allowed" parameter narrows both ordering validators.

    Exercised directly so the guard is pinned independently of any schema
    wiring that happens to reach it.
    """

    def test_validate_ordering_terms_honors_allowed(self) -> None:
        """Assert a concrete column outside "allowed" is rejected.

        If this fails, the model's column list is still the allowlist and the
        type's projection is decorative.

        Raises:
            GraphQLError: Expected from "_validate_ordering_terms" and
                asserted via pytest.raises.
        """
        with pytest.raises(GraphQLError, match="Invalid ordering field: 'bio'."):
            _validate_ordering_terms(Author, "bio", allowed={"name"})

    def test_validate_ordering_terms_without_allowed_is_unchanged(self) -> None:
        """Assert omitting "allowed" keeps the model-wide allowlist.

        A hand-constructed paginator carries no projection, so it must keep
        accepting every concrete column. If this fails, existing code that
        builds a paginator directly starts rejecting valid orderings.
        """
        _validate_ordering_terms(Author, "bio")

    def test_inmemory_order_honors_allowed(self) -> None:
        """Assert the in-memory path rejects a column outside "allowed".

        The prefetch-cache path never touches a queryset, so without its own
        check a nested list resolved from cache would still sort by the hidden
        column.

        Raises:
            GraphQLError: Expected from "_inmemory_order" and asserted via
                pytest.raises.
        """
        rows = [Author(name="a", bio="z"), Author(name="b", bio="a")]
        with pytest.raises(GraphQLError, match="Invalid ordering field: 'bio'."):
            _inmemory_order(rows, "bio", allowed={"name"})

    def test_inmemory_order_without_allowed_is_unchanged(self) -> None:
        """Assert omitting "allowed" leaves the in-memory path permissive.

        If this fails, every caller that has no projection to enforce would
        start raising on orderings it used to sort silently.
        """
        rows = [Author(name="a", bio="z"), Author(name="b", bio="a")]
        assert [row.name for row in _inmemory_order(rows, "bio")] == ["b", "a"]

    def test_unprojected_type_allows_every_published_column(self) -> None:
        """Assert a type that projects nothing away still publishes every column.

        The allowlist is now read off the compiled type, so an unprojected type
        gets a real set rather than "no restriction" -- the same columns, stated
        rather than assumed. If this fails, a type that asked for no projection
        lost one of its own columns.
        """
        gql_type = nest_schema.graphql_schema.type_map["NestAuthorType"]
        allowed = projected_ordering_attnames(Author, gql_type)
        assert {"id", "name", "bio", "pk"} <= allowed

    def test_inmemory_order_rejects_a_pk_outside_allowed(self) -> None:
        """Assert the in-memory path rejects "pk" when the pk is projected away.

        The prefetch-cache path had a blanket "pk" exemption of its own, so
        without this the queryset guard could be closed while a nested list
        resolved from cache still ranked the rows by the hidden pk.

        Raises:
            GraphQLError: Expected from "_inmemory_order" and asserted via
                pytest.raises.
        """
        rows = [
            CustomPKProduct(slug="z", title="a"),
            CustomPKProduct(slug="a", title="b"),
        ]
        with pytest.raises(GraphQLError, match="Invalid ordering field: 'pk'."):
            _inmemory_order(rows, "pk", allowed={"title"})

    def test_projected_attnames_drop_a_hidden_natural_pk(self) -> None:
        """Assert the allowlist omits a primary key the projection removes.

        The allowlist is the single source of truth every ordering path reads,
        so a pk it still lists is a pk every path still sorts by.
        """
        gql_type = hidden_pk_schema.graphql_schema.type_map["HiddenPkProductType"]
        assert projected_ordering_attnames(CustomPKProduct, gql_type) == {"title"}

    def test_projected_attnames_keep_an_exposed_pk_and_its_aliases(self) -> None:
        """Assert an exposed pk keeps "pk" and its field name in the allowlist.

        The SDL publishes NAMES and the ORM orders by ATTNAMES, so the "pk"
        alias and the field name have to be added back -- but only when the key
        is published. If this fails, "ordering: 'pk'" breaks on every type.
        """
        gql_type = proj_schema.graphql_schema.type_map["ProjAuthorType"]
        assert {"pk", "id"} <= projected_ordering_attnames(Author, gql_type)

    def test_the_allowlist_is_exactly_the_compiled_field_map(self) -> None:
        """Assert the allowlist is exactly the compiled SDL, keyed by attname.

        This is the whole guarantee: "orderable" and "selectable" are the same
        set. It is asserted against the built type map rather than re-derived
        from "Meta", because a claim checked only against its own source is how
        four rounds of drift survived review.
        """
        cases = (
            (proj_schema, "ProjAuthorType", Author),
            (hidden_pk_schema, "HiddenPkProductType", CustomPKProduct),
        )
        for schema, type_name, model in cases:
            gql_type = schema.graphql_schema.type_map[type_name]
            exposed = {to_snake_case(name) for name in gql_type.fields}
            expected = {
                f.attname for f in model._meta.concrete_fields if f.name in exposed
            }
            pk = model._meta.pk
            if pk.name in exposed:
                expected |= {"pk", pk.name, pk.attname}
            assert projected_ordering_attnames(model, gql_type) == expected, type_name

    # Two list types sharing ONE paginator instance is pinned in
    # ``test_ordering_allowlist_from_sdl`` (``TestSharedPaginatorAcrossContainers``),
    # where the containers really do share an instance. The version that lived
    # here read the allowlist off ``_meta.paginator`` -- an object that no longer
    # carries one, precisely because it is shared.


# ---------------------------------------------------------------------------
# A natural primary key hidden by the projection is not orderable
# ---------------------------------------------------------------------------


class TestHiddenNaturalPkRejected(TestCase):
    """A projected-away primary key must not be reachable through "ordering".

    The pk exemption exists for a surrogate key nobody minds exposing. On a
    slug / code / email primary key it hands back a real business column the
    type deliberately removed, which is the same read oracle the allowlist was
    built to close.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create three products whose slug order inverts their title order.

        The inversion is what makes a successful hidden-pk sort observable
        through the exposed titles alone.
        """
        CustomPKProduct.objects.create(slug="zzz", title="a")
        CustomPKProduct.objects.create(slug="aaa", title="b")
        CustomPKProduct.objects.create(slug="mmm", title="c")

    def test_hidden_pk_absent_from_sdl(self) -> None:
        """Assert "slug" is not exposed on the projected product type.

        If this fails the premise is gone: the pk would be selectable outright
        and the ordering allowlist would not be the last line of defence.
        """
        assert "slug" not in str(hidden_pk_schema)

    def test_ordering_by_hidden_natural_pk_is_rejected(self) -> None:
        """Assert ordering by the hidden slug primary key raises.

        If this fails, the returned title sequence IS the slug ranking, so a
        client recovers the order of a column it cannot even select.
        """
        result = graphql_sync(
            hidden_pk_schema.graphql_schema,
            '{ products { results(ordering: "slug") { title } } }',
        )
        leaked = (
            None
            if result.errors
            else [row["title"] for row in result.data["products"]["results"]]
        )
        assert result.errors, f"the hidden natural pk ranked the rows: {leaked!r}"
        assert "Invalid ordering field: 'slug'." in str(result.errors[0].message)

    def test_ordering_by_pk_alias_is_rejected_when_the_pk_is_hidden(self) -> None:
        """Assert Django's native "pk" alias is rejected when the pk is hidden.

        The alias resolves to the very same column, so exempting it while
        rejecting its real name would close nothing at all.
        """
        errors = _errors(
            hidden_pk_schema,
            '{ products { results(ordering: "pk") { title } } }',
        )
        assert errors, "the pk alias reached a projected-away natural key"
        assert "Invalid ordering field: 'pk'." in errors[0]

    def test_ordering_by_the_exposed_column_still_works(self) -> None:
        """Assert the one exposed column is still orderable.

        If this fails, the pk rule has narrowed the allowlist past the
        projection and broken legitimate ordering.
        """
        result = graphql_sync(
            hidden_pk_schema.graphql_schema,
            '{ products { results(ordering: "title") { title } } }',
        )
        assert result.errors is None, result.errors
        titles = [row["title"] for row in result.data["products"]["results"]]
        assert titles == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# The cursor paginator echoes its ordering value, so it is gated too
# ---------------------------------------------------------------------------

_CURSOR_QUERY = """
{ authors { results { name } pageInfo { endCursor startCursor } } }
"""


def _decoded(cursor: str | None) -> str | None:
    """Return the cleartext payload carried by an opaque cursor.

    Cursors are base64 of "cursor:<ordering value>\\x1f<pk>", so this is what
    ANY client can read off an echoed cursor with no privileged access.

    Args:
        cursor: The opaque cursor string, or None.

    Returns:
        The decoded payload, or None when there was no cursor.
    """
    if not cursor:
        return None
    return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")


class TestCursorOrderingHonorsProjection(TestCase):
    """A cursor paginator must not order by a column its node type hides.

    The server-default exemption is justified by the default being "never
    echoed back". "CursorGraphqlPagination" DOES echo it: "endCursor" is
    base64 of the boundary row's ordering value, so a hidden ordering column is
    read out verbatim rather than merely ranked.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two authors carrying distinctive hidden "bio" values.

        Distinctive values make the leak unambiguous in the failure message.
        """
        Author.objects.create(name="alice", bio="SECRET-A")
        Author.objects.create(name="bob", bio="SECRET-B")

    def test_hidden_column_absent_from_cursor_sdl(self) -> None:
        """Assert "bio" is not exposed on the cursor-paged author type.

        If this fails the premise is gone and the column is selectable.
        """
        assert "bio" not in str(cursor_schema)

    def test_cursor_page_info_does_not_echo_a_hidden_column(self) -> None:
        """Assert "pageInfo" refuses to build cursors over a hidden column.

        If this fails, "endCursor" decodes straight to the hidden value -- a
        direct read, not a ranking.
        """
        result = graphql_sync(cursor_schema.graphql_schema, _CURSOR_QUERY)
        leaked = (
            None
            if result.errors
            else _decoded(result.data["authors"]["pageInfo"]["endCursor"])
        )
        assert result.errors, f"endCursor echoed the hidden column: {leaked!r}"
        assert "Invalid ordering field: 'bio'." in str(result.errors[0].message)

    def test_cursor_results_do_not_rank_by_a_hidden_column(self) -> None:
        """Assert the results themselves are not ordered by the hidden column.

        "paginate_queryset" is a separate entry point from "get_page_info", so
        closing only the cursor echo would leave the ranking oracle open.
        """
        errors = _errors(cursor_schema, "{ authors { results { name } } }")
        assert errors, "the cursor results were ranked by a projected-away column"
        assert "Invalid ordering field: 'bio'." in errors[0]


# ---------------------------------------------------------------------------
# The nested window path agrees with the queryset path about the pk
# ---------------------------------------------------------------------------


class TestNestedWindowHonorsPkProjection(TestCase):
    """A nested list whose child hides its pk stays correct AND stays closed.

    The window slice applies its ORDER BY in SQL and returns rows already
    sliced, so no later guard runs; and when no ordering is supplied it emits
    the child's pk itself. Both halves need pinning: the client must not reach
    the hidden pk, and the paginator's own tiebreak must not break the field.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one author with three posts inserted out of title order.

        Insertion order is pk order, so a title sequence that differs from it
        is what would betray a hidden-pk sort.
        """
        author = Author.objects.create(name="winpk")
        Post.objects.create(title="c", author=author, views=1)
        Post.objects.create(title="a", author=author, views=2)
        Post.objects.create(title="b", author=author, views=3)

    def test_hidden_pk_absent_from_nested_sdl(self) -> None:
        """Assert the nested post type exposes nothing but "title".

        If this fails the premise is gone: the pk would be selectable outright
        and the ordering allowlist would not be the last line of defence.
        """
        gql_type = win_pk_schema.graphql_schema.type_map["WinPkPostType"]
        assert set(gql_type.fields) == {"title"}

    def test_nested_ordering_by_hidden_pk_is_rejected(self) -> None:
        """Assert the nested list rejects ordering by its projected-away pk.

        The window path declines the optimization for a term outside the
        allowlist and hands the query to the plain prefetch path, which must
        then raise rather than quietly sort by it.
        """
        result = graphql_sync(
            win_pk_schema.graphql_schema,
            """
            { authors { results {
                posts { results(ordering: "id") { title } }
            } } }
            """,
        )
        leaked = (
            None
            if result.errors
            else [
                row["title"]
                for row in result.data["authors"]["results"][0]["posts"]["results"]
            ]
        )
        assert result.errors, f"the nested hidden pk ranked the rows: {leaked!r}"
        assert "Invalid ordering field: 'id'." in str(result.errors[0].message)

    def test_nested_list_without_ordering_still_resolves(self) -> None:
        """Assert the paginator's own pk tiebreak survives the pk projection.

        This is the outage the unconditional pk exemption was defending
        against. It never materialises: the generated pk ordering carries no
        allowlist on the in-memory path, and on the window path an unusable
        tiebreak only costs the optimization, never the answer.

        The captured SQL is what turns "costs the optimization" from a claim
        into a measurement: the window slice is declined (no ROW_NUMBER) and the
        plain prefetch path serves the same three rows.
        """
        with CaptureQueriesContext(connection) as captured:
            result = graphql_sync(
                win_pk_schema.graphql_schema,
                "{ authors { results { posts { results { title } } } } }",
            )
        assert result.errors is None, result.errors
        titles = [
            row["title"]
            for row in result.data["authors"]["results"][0]["posts"]["results"]
        ]
        assert sorted(titles) == ["a", "b", "c"]
        sql = " ".join(entry["sql"].upper() for entry in captured.captured_queries)
        assert "ROW_NUMBER" not in sql


# ---------------------------------------------------------------------------
# The cursor's pk TIEBREAK follows the projection too
# ---------------------------------------------------------------------------


class TestCursorTiebreakHonorsPkProjection(TestCase):
    """A composite cursor must not print a primary key the type hides.

    The ordering allowlist gates the column the cursor RANKS by. It says
    nothing about the pk "CursorGraphqlPagination" appends as its tiebreak,
    which is serialised into the same token. With a natural key -- a slug, a
    code, an email -- that token is a direct read of a column the SDL does not
    carry, handed to the client in the response body.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two products whose slug primary keys are distinctive.

        Distinctive slugs make the leak unambiguous in the failure message.
        """
        CustomPKProduct.objects.create(slug="SECRET-SLUG-A", title="a")
        CustomPKProduct.objects.create(slug="SECRET-SLUG-B", title="b")

    def test_hidden_pk_absent_from_the_cursor_sdl(self) -> None:
        """Assert the product type exposes nothing but "title".

        If this fails the premise is gone: the slug would be selectable
        outright and the cursor would echo nothing new.
        """
        gql_type = cursor_hidden_pk_schema.graphql_schema.type_map[
            "CursorHiddenPkProductType"
        ]
        assert set(gql_type.fields) == {"title"}

    def test_page_info_cursors_do_not_carry_the_hidden_primary_key(self) -> None:
        """Assert no emitted cursor decodes to the projected-away slug.

        Reads whatever "pageInfo" hands back and decodes it the way any client
        can, so the assertion fails on the leak itself rather than on a proxy
        for it.
        """
        result = graphql_sync(
            cursor_hidden_pk_schema.graphql_schema,
            "{ products { pageInfo { startCursor endCursor } results { title } } }",
        )
        page_info = ((result.data or {}).get("products") or {}).get("pageInfo") or {}
        for key in ("startCursor", "endCursor"):
            decoded = _decoded(page_info.get(key))
            assert decoded is None or "SECRET-SLUG" not in decoded, (
                f"{key} printed the hidden primary key verbatim: {decoded!r}"
            )

    def test_the_configuration_is_refused_with_an_actionable_error(self) -> None:
        """Assert a type hiding its pk cannot be keyset-paginated at all.

        The tiebreak is what makes a keyset cursor stable and total, so it
        cannot simply be dropped; the configuration is refused instead, on
        every request and through both entry points.
        """
        for query in (
            "{ products { pageInfo { startCursor } } }",
            "{ products { results { title } } }",
        ):
            errors = _errors(cursor_hidden_pk_schema, query)
            assert errors, f"{query} was served over a hidden primary key"
            assert "primary key" in errors[0], errors[0]


# ---------------------------------------------------------------------------
# The multi-table-inheritance parent link rides on the key it points at
# ---------------------------------------------------------------------------


class TestMtiParentLinkIsInTheAllowlist(TestCase):
    """The parent link is not in the SDL, and is still orderable.

    The compiler drops the link as join plumbing while publishing the PARENT's
    "id", and the two hold the same value on every row. So the link's column
    stays orderable -- it has to, since it is what "model._meta.pk.attname"
    resolves to on an MTI child -- and it reveals nothing the type does not
    already publish.
    """

    def test_parent_link_column_is_orderable_but_not_selectable(self) -> None:
        """Assert the parent-link attname survives while the SDL drops it.

        The value is the child row's own pk, which the type also exposes as
        "id", so the divergence ranks by nothing the client cannot already
        read.
        """
        gql_type = mti_schema.graphql_schema.type_map["MtiRestaurantType"]
        allowed = projected_ordering_attnames(MtiRestaurant, gql_type)

        assert "mtiplace_ptr_id" in allowed
        assert "mtiplacePtr" not in gql_type.fields
        # The parent link IS the child's pk, so ordering by "pk" keeps working
        # and reads the same identifier the type already exposes as "id".
        assert {"pk", "id"} <= allowed
        assert "id" in gql_type.fields
