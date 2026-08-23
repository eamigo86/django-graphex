# -*- coding: utf-8 -*-
"""Regression — the "ordering" argument works with the DEFAULT paginator.

Every paginated list field advertises an "ordering" argument built from the
paginator's "to_graphql_fields()". With the SHIPPED defaults
("DEFAULT_PAGINATION_CLASS" = "LimitOffsetGraphqlPagination",
"DEFAULT_PAGE_SIZE" = None, "MAX_PAGE_SIZE" = None) the resolved paginator is
UNBOUNDED, and "LimitOffsetGraphqlPagination.paginate_queryset" returned the
queryset untouched from its unbounded early-return — BEFORE the ordering was
ever read. The argument was therefore present in the schema (GraphiQL
autocompleted it, clients could send it) and silently did nothing: both
"ordering: "name"" and "ordering: "-name"" came back in insertion order, and an
invalid ordering field was not even rejected.

Declaring a paginator explicitly ("pagination = LimitOffsetGraphqlPagination(
default_limit=10)") resolved a BOUNDED paginator, skipped the early-return and
ordered correctly — which is why the defect never showed up in the suite.

Pinned here, end-to-end through a compiled "DjangoGraphQLSchema" and
"graphql_sync" against a real database:

* the default (unbounded) paginator orders ascending and descending, for the
  single-term, multi-term and camelCase spellings;
* an invalid ordering field is rejected with the SAME clean
  "Invalid ordering field" error the bounded paginator already produced
  (no Django "FieldError" column leak, CWE-209);
* the explicitly-declared bounded paginator is unchanged;
* every sibling field class that mounts pagination arguments is covered:
  "DjangoListObjectField", "DjangoFilterPaginateListField" and the nested
  "DjangoNestedListObjectField" (whose rows come from the prefetch cache, i.e.
  the in-memory ordering path);
* "ordering" is advertised ONLY by the paginators that actually apply it —
  "CursorGraphqlPagination" (server-configured ordering) does not expose it.
"""

from __future__ import annotations

import json
from typing import Any

from django.test import TestCase
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import (
    DjangoFilterPaginateListField,
    DjangoListObjectField,
)
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.settings import graphql_api_settings
from django_graphex.types import DjangoListObjectType, DjangoObjectType

from ._schema_isolation import isolated_pair
from .models import DefaultOrderMember, DefaultOrderTeam

R = Registry()


class MemberType(DjangoObjectType):
    """Node type for "DefaultOrderMember", the rows being ordered.

    Backs every list field in this module, so all of them read the same two
    orderable columns ("name" and the multi-word "sort_key").
    """

    class Meta:
        """Bind the node type to "DefaultOrderMember" on the isolated registry.

        "filter_fields" is required by "DjangoFilterPaginateListField", the
        sibling field class covered further down.
        """

        model = DefaultOrderMember
        registry = R
        filter_fields = {"name": ["exact", "icontains"]}


class ExplicitMemberListType(DjangoListObjectType):
    """List container with an EXPLICIT, bounded paginator (control group).

    Declared BEFORE "DefaultMemberListType" on purpose: a list type registers
    itself as its model's canonical list type on a LAST-ONE-WINS basis, and the
    nested "team { members }" relation reuses that canonical type. Keeping the
    DEFAULT-paginator container last is what makes the nested assertions
    exercise the default paginator rather than this control group.
    """

    class Meta:
        """Bind the container to "DefaultOrderMember" with a bounded paginator.

        A concrete "default_limit" is the configuration that ALWAYS worked, so
        this container pins that the fix changes nothing for it.
        """

        model = DefaultOrderMember
        registry = R
        pagination = LimitOffsetGraphqlPagination(default_limit=10)


class DefaultMemberListType(DjangoListObjectType):
    """List container with NO "pagination", so the global default applies.

    This is the container under test: the resolved default paginator is the
    unbounded one whose "ordering" argument used to be inert.
    """

    class Meta:
        """Bind the container to "DefaultOrderMember" with no paginator.

        Omitting "pagination" is what resolves the unbounded
        "DEFAULT_PAGINATION_CLASS" instance under test.
        """

        model = DefaultOrderMember
        registry = R


class TeamType(DjangoObjectType):
    """Node type for "DefaultOrderTeam", parent of the nested member list.

    Reaching the members through a parent row is what routes the rows via the
    "prefetch_related" cache, i.e. the in-memory ordering branch.
    """

    class Meta:
        """Bind the node type to "DefaultOrderTeam" on the isolated registry.

        Its reverse "members" relation is auto-compiled into the nested list
        field whose ordering is asserted below.
        """

        model = DefaultOrderTeam
        registry = R


class TeamListType(DjangoListObjectType):
    """List container for "DefaultOrderTeam", the nested-path entry point.

    Only exists so the nested "members" list is reachable from a root field;
    its own ordering is never asserted.
    """

    class Meta:
        """Bind the container to "DefaultOrderTeam" with no paginator.

        The team list itself is incidental; it only exists to reach the nested
        "members" list through a parent row.
        """

        model = DefaultOrderTeam
        registry = R


class Query(ObjectType):
    """Root query exposing one root field per affected field class.

    "members" and "teams" are "DjangoListObjectField" (container shape),
    "flatMembers" is "DjangoFilterPaginateListField" (flat list shape), and the
    nested "DjangoNestedListObjectField" is reached through "teams".
    """

    members = DjangoListObjectField(DefaultMemberListType)
    explicit_members = DjangoListObjectField(ExplicitMemberListType)
    flat_members = DjangoFilterPaginateListField(MemberType)
    teams = DjangoListObjectField(TeamListType)


schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(R))


def _run(query: str) -> Any:
    """Execute a GraphQL document against the module schema.

    Args:
        query: The GraphQL document to execute.

    Returns:
        result: The "ExecutionResult" produced by "graphql_sync".
    """
    return graphql_sync(schema.graphql_schema, query)


def _names(query: str) -> list[str]:
    """Execute a document and collect the "name" of every returned row.

    Args:
        query: The GraphQL document to execute; it must select "name" on the
            rows under test.

    Returns:
        names: The row names in the exact order the server returned them.

    Raises:
        AssertionError: When the execution produced GraphQL errors.
    """
    result = _run(query)
    assert result.errors is None, result.errors
    payload = result.data
    rows = payload.get("members") or payload.get("explicitMembers")
    if rows is None:
        rows = payload.get("flatMembers")
        return [row["name"] for row in rows]
    return [row["name"] for row in rows["results"]]


def _ordering(value: str) -> str:
    """Render an ordering value as a GraphQL string literal.

    Args:
        value: The raw ordering value to send on the wire.

    Returns:
        literal: The JSON-quoted form, safe to inline in a document.
    """
    return json.dumps(value)


class DefaultPaginatorOrderingTest(TestCase):
    """The unbounded DEFAULT paginator must honor "ordering" on the root list.

    Covers ascending, descending, multi-term and camelCase spellings through
    "DjangoListObjectField", the field class the defect was reported on.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed three members whose insertion order is neither sort order.

        Inserting "b", "a", "c" means an unordered result is distinguishable
        from both the ascending and the descending one.
        """
        DefaultOrderMember.objects.create(name="b", sort_key=3)
        DefaultOrderMember.objects.create(name="a", sort_key=1)
        DefaultOrderMember.objects.create(name="c", sort_key=2)

    def test_default_paginator_is_unbounded(self) -> None:
        """Assert the shipped defaults really do resolve an unbounded paginator.

        If this fails the rest of this class is testing the bounded paginator
        by accident, and the regression it guards would go unnoticed.
        """
        assert graphql_api_settings.DEFAULT_PAGE_SIZE is None
        assert graphql_api_settings.MAX_PAGE_SIZE is None
        paginator = graphql_api_settings.DEFAULT_PAGINATION_CLASS()
        assert paginator.default_limit is None
        assert paginator.max_limit is None

    def test_ordering_argument_is_advertised(self) -> None:
        """Assert the default container's "results" field declares "ordering".

        If this fails the defect is gone for the wrong reason (the argument
        disappeared) and the ordering assertions below become vacuous.
        """
        results = schema.graphql_schema.query_type.fields["members"].type.fields[
            "results"
        ]
        assert "ordering" in results.args

    def test_ascending_ordering_reorders_rows(self) -> None:
        """Assert "ordering: "name"" returns rows in ascending name order.

        If this fails the advertised "ordering" argument is inert again and
        rows come back in insertion order.
        """
        query = "{ members { results(ordering: %s) { name } } }" % _ordering("name")
        assert _names(query) == ["a", "b", "c"]

    def test_descending_ordering_reorders_rows(self) -> None:
        """Assert "ordering: "-name"" returns rows in descending name order.

        If this fails the "-" direction prefix is dropped, or the argument is
        inert and both spellings return the same sequence.
        """
        query = "{ members { results(ordering: %s) { name } } }" % _ordering("-name")
        assert _names(query) == ["c", "b", "a"]

    def test_ascending_and_descending_differ(self) -> None:
        """Assert the two directions do NOT return an identical sequence.

        This is the exact shape of the reported defect: both spellings
        returning insertion order, so neither one alone proves ordering ran.
        """
        asc = _names(
            "{ members { results(ordering: %s) { name } } }" % _ordering("name")
        )
        desc = _names(
            "{ members { results(ordering: %s) { name } } }" % _ordering("-name")
        )
        assert asc == list(reversed(desc))

    def test_camelcase_ordering_reorders_rows(self) -> None:
        """Assert the camelCase wire spelling of an attname orders the rows.

        If this fails, "sortKey" is not normalized to the "sort_key" attname on
        the unbounded path even though the bounded path accepts it.
        """
        query = "{ members { results(ordering: %s) { name } } }" % _ordering("sortKey")
        assert _names(query) == ["a", "c", "b"]

    def test_camelcase_descending_ordering_reorders_rows(self) -> None:
        """Assert a descending camelCase term keeps its direction prefix.

        If this fails, "-sortKey" normalizes to an ascending term or is
        dropped entirely on the unbounded path.
        """
        query = "{ members { results(ordering: %s) { name } } }" % _ordering("-sortKey")
        assert _names(query) == ["b", "c", "a"]

    def test_multi_term_ordering_reorders_rows(self) -> None:
        """Assert a comma-separated ordering is splatted into "order_by".

        If this fails, only the first term (or none) reaches the ORM on the
        unbounded path.
        """
        query = "{ members { results(ordering: %s) { name } } }" % _ordering(
            "sortKey,-name"
        )
        assert _names(query) == ["a", "c", "b"]

    def test_invalid_ordering_field_is_rejected(self) -> None:
        """Assert an unknown ordering field raises the clean library error.

        If this fails the unbounded path swallows invalid input silently (the
        pre-fix behaviour) or leaks Django's "FieldError" column list.
        """
        query = "{ members { results(ordering: %s) { name } } }" % _ordering(
            "nonexistentField"
        )
        result = _run(query)
        assert result.errors is not None
        message = result.errors[0].message
        assert "Invalid ordering field" in message
        assert "nonexistent_field" in message

    def test_relation_spanning_ordering_is_rejected(self) -> None:
        """Assert a relation-spanning ordering term is still refused.

        If this fails the unbounded path lets an arbitrary join chain through,
        which the bounded path has always rejected.
        """
        query = "{ members { results(ordering: %s) { name } } }" % _ordering(
            "team__label"
        )
        result = _run(query)
        assert result.errors is not None
        assert "Relation-spanning ordering is not permitted" in (
            result.errors[0].message
        )

    def test_no_ordering_still_returns_every_row(self) -> None:
        """Assert omitting "ordering" still returns the whole unbounded set.

        If this fails the fix accidentally started slicing or reordering a
        request that asked for neither.
        """
        query = "{ members { results { name } } }"
        assert sorted(_names(query)) == ["a", "b", "c"]


class ExplicitPaginatorUnchangedTest(TestCase):
    """The explicitly-declared bounded paginator must behave exactly as before.

    This is the control group: it already ordered correctly, so any change in
    its behaviour would mean the fix moved more than the unbounded branch.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed three members whose insertion order is neither sort order.

        Mirrors the default-paginator fixture so both groups are comparable.
        """
        DefaultOrderMember.objects.create(name="b", sort_key=3)
        DefaultOrderMember.objects.create(name="a", sort_key=1)
        DefaultOrderMember.objects.create(name="c", sort_key=2)

    def test_explicit_ascending_ordering(self) -> None:
        """Assert the bounded paginator still orders ascending by name.

        If this fails, the shared ordering helper regressed the path that was
        already correct.
        """
        query = "{ explicitMembers { results(ordering: %s) { name } } }" % _ordering(
            "name"
        )
        assert _names(query) == ["a", "b", "c"]

    def test_explicit_descending_ordering(self) -> None:
        """Assert the bounded paginator still orders descending by name.

        If this fails, the shared ordering helper regressed the descending
        branch of the path that was already correct.
        """
        query = "{ explicitMembers { results(ordering: %s) { name } } }" % _ordering(
            "-name"
        )
        assert _names(query) == ["c", "b", "a"]

    def test_explicit_limit_offset_still_slices(self) -> None:
        """Assert ordering and slicing still compose on the bounded paginator.

        If this fails, the ordering is applied after the slice (or the slice
        was lost), so the page contents no longer match the requested order.
        """
        query = (
            "{ explicitMembers { results(ordering: %s, limit: 2, offset: 1) "
            "{ name } } }" % _ordering("name")
        )
        assert _names(query) == ["b", "c"]

    def test_explicit_invalid_ordering_still_rejected(self) -> None:
        """Assert the bounded paginator still rejects an unknown field.

        If this fails, routing the bounded path through the shared helper lost
        the pre-"order_by" allowlist check.
        """
        query = "{ explicitMembers { results(ordering: %s) { name } } }" % _ordering(
            "nonexistentField"
        )
        result = _run(query)
        assert result.errors is not None
        assert "Invalid ordering field" in result.errors[0].message


class FilterPaginateListFieldOrderingTest(TestCase):
    """ "DjangoFilterPaginateListField" resolves the default paginator too.

    It builds its own paginator instance in "__init__" from
    "DEFAULT_PAGINATION_CLASS" when none is passed, so it inherited the same
    inert-"ordering" defect through a completely different resolver.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed three members whose insertion order is neither sort order.

        Mirrors the other fixtures so the expected sequences match.
        """
        DefaultOrderMember.objects.create(name="b", sort_key=3)
        DefaultOrderMember.objects.create(name="a", sort_key=1)
        DefaultOrderMember.objects.create(name="c", sort_key=2)

    def test_flat_ascending_ordering(self) -> None:
        """Assert the flat filtered list orders ascending by name.

        If this fails, "DjangoFilterPaginateListField" still drops the
        "ordering" argument it advertises.
        """
        query = "{ flatMembers(ordering: %s) { name } }" % _ordering("name")
        assert _names(query) == ["a", "b", "c"]

    def test_flat_descending_ordering(self) -> None:
        """Assert the flat filtered list orders descending by name.

        If this fails, the descending direction is lost on the flat filtered
        list even though the container list honors it.
        """
        query = "{ flatMembers(ordering: %s) { name } }" % _ordering("-name")
        assert _names(query) == ["c", "b", "a"]

    def test_flat_ordering_composes_with_filter(self) -> None:
        """Assert ordering still applies to a filtered subset.

        If this fails, ordering and filtering are applied in an order that
        drops one of them on this field class.
        """
        query = (
            '{ flatMembers(filter: {name: {icontains: ""}}, ordering: %s) '
            "{ name } }" % _ordering("-name")
        )
        assert _names(query) == ["c", "b", "a"]

    def test_flat_invalid_ordering_is_rejected(self) -> None:
        """Assert the flat filtered list rejects an unknown ordering field.

        If this fails, this field class silently ignores invalid input that
        the container list rejects.
        """
        query = "{ flatMembers(ordering: %s) { name } }" % _ordering("nope")
        result = _run(query)
        assert result.errors is not None
        assert "Invalid ordering field" in result.errors[0].message


class NestedListFieldOrderingTest(TestCase):
    """The nested "DjangoNestedListObjectField" must honor "ordering" too.

    Its rows arrive from the parent query's "prefetch_related" cache as a plain
    Python list, so this exercises the in-memory branch of the same unbounded
    early-return.
    """

    @classmethod
    def setUpTestData(cls) -> None:
        """Seed one team with three members inserted out of sort order.

        A single parent keeps the nested assertion about ordering only, not
        about which parent a row belongs to.
        """
        team = DefaultOrderTeam.objects.create(label="t")
        DefaultOrderMember.objects.create(name="b", sort_key=3, team=team)
        DefaultOrderMember.objects.create(name="a", sort_key=1, team=team)
        DefaultOrderMember.objects.create(name="c", sort_key=2, team=team)

    def _nested_names(self, ordering: str) -> list[str]:
        """Read the nested member names for one ordering value.

        Args:
            ordering: The ordering value sent to the nested "members" field.

        Returns:
            names: The nested member names in server-returned order.

        Raises:
            AssertionError: When the execution produced GraphQL errors.
        """
        query = (
            "{ teams { results { members { results(ordering: %s) { name } } } } }"
            % _ordering(ordering)
        )
        result = _run(query)
        assert result.errors is None, result.errors
        team = result.data["teams"]["results"][0]
        return [row["name"] for row in team["members"]["results"]]

    def test_nested_ascending_ordering(self) -> None:
        """Assert the nested list orders ascending by name.

        If this fails, the nested (prefetch-cache) path still returns rows in
        insertion order despite the requested ordering.
        """
        assert self._nested_names("name") == ["a", "b", "c"]

    def test_nested_descending_ordering(self) -> None:
        """Assert the nested list orders descending by name.

        If this fails, the nested path drops the "-" direction prefix or the
        ordering argument entirely.
        """
        assert self._nested_names("-name") == ["c", "b", "a"]

    def test_nested_camelcase_ordering(self) -> None:
        """Assert the nested list normalizes a camelCase ordering term.

        If this fails, "sortKey" degrades to a missing attribute on the
        in-memory path and the sort silently becomes a no-op.
        """
        assert self._nested_names("sortKey") == ["a", "c", "b"]


class OrderingAdvertisedOnlyWhenAppliedTest(TestCase):
    """ "ordering" must be advertised only by paginators that actually apply it.

    An argument a paginator cannot honor is worse than an absent one, so this
    pins the invariant in both directions.
    """

    def test_limit_offset_advertises_ordering(self) -> None:
        """Assert the limit/offset paginator exposes "ordering".

        If this fails, clients lose an argument the paginator does apply.
        """
        assert "ordering" in LimitOffsetGraphqlPagination().to_graphql_fields()

    def test_page_advertises_ordering(self) -> None:
        """Assert the page paginator exposes "ordering".

        If this fails, clients lose an argument the paginator does apply.
        """
        assert "ordering" in PageGraphqlPagination().to_graphql_fields()

    def test_cursor_does_not_advertise_ordering(self) -> None:
        """Assert the cursor paginator exposes no "ordering" argument.

        Keyset ordering is server-configured and cannot vary per request, so
        advertising the argument would put an inert control back in the schema.
        """
        assert "ordering" not in CursorGraphqlPagination().to_graphql_fields()
