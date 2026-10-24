"""GenericForeignKey targets honor the target output type's row scope."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext, override_settings
from graphql import GraphQLResolveInfo, graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType, DjangoUnionType
from tests._schema_isolation import isolated_pair
from tests.models import Track2Account, Track2GfkComment, Track2Invoice

_UNION_LIST = """
{ allComments { results { body target {
  __typename
  ... on ScopedAccount { label }
  ... on ScopedInvoice { note }
} } } }
"""


def _hide_secret(queryset: QuerySet, info: GraphQLResolveInfo) -> QuerySet:
    """Hide rows whose label or note starts with the secret marker.

    Args:
        queryset: Unscoped target rows.
        info: Request resolve info, unused by this fixed policy.

    Returns:
        The rows that remain visible.
    """
    if queryset.model is Track2Account:
        return queryset.exclude(label__startswith="secret")
    return queryset.exclude(note__startswith="secret")


def _schema(*, union: bool, scope_invoice: bool = False) -> DjangoGraphQLSchema:
    """Build a private schema exposing a scoped GFK target.

    Args:
        union: Whether the GFK is exposed as a typed union or the flat type.
        scope_invoice: Whether the invoice member also applies a row scope.

    Returns:
        The compiled schema with an "allComments" list root.
    """
    reg = Registry()

    class AccountType(DjangoObjectType):
        """Account member with a row scope."""

        class Meta:
            """Bind to the private registry."""

            model = Track2Account
            registry = reg
            name = "ScopedAccount"

        @classmethod
        def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
            """Hide secret accounts.

            Args:
                queryset: Unscoped rows.
                info: Request resolve info.

            Returns:
                The visible rows.
            """
            return _hide_secret(queryset, info)

    class InvoiceType(DjangoObjectType):
        """Invoice member, optionally scoped."""

        class Meta:
            """Bind to the private registry."""

            model = Track2Invoice
            registry = reg
            name = "ScopedInvoice"

        @classmethod
        def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
            """Hide secret invoices when requested.

            Args:
                queryset: Unscoped rows.
                info: Request resolve info.

            Returns:
                The visible rows.
            """
            return _hide_secret(queryset, info) if scope_invoice else queryset

    if union:

        class TargetUnion(DjangoUnionType):
            """Union over the scoped members."""

            class Meta:
                """Bind to the private registry."""

                types = (AccountType, InvoiceType)
                registry = reg
                name = "ScopedTarget"

        class CommentType(DjangoObjectType):
            """Owner exposing the typed union."""

            class Meta:
                """Bind to the private registry."""

                model = Track2GfkComment
                registry = reg
                unions = {"target": TargetUnion}

    else:

        class CommentType(DjangoObjectType):  # type: ignore[no-redef]
            """Owner exposing the flat GFK."""

            class Meta:
                """Bind to the private registry."""

                model = Track2GfkComment
                registry = reg

    class CommentListType(DjangoListObjectType):
        """List container for owners."""

        class Meta:
            """Bind to the private registry."""

            model = Track2GfkComment
            registry = reg
            pagination = LimitOffsetGraphqlPagination(
                default_limit=None, max_limit=None
            )

    class Query(ObjectType):
        """Expose the owner list."""

        all_comments = DjangoListObjectField(CommentListType)

    return DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))


def _seed(pairs: int) -> None:
    """Create visible and secret accounts and invoices with one owner each.

    Args:
        pairs: Number of visible-plus-secret rows to create per model.
    """
    acct = ContentType.objects.get_for_model(Track2Account)
    inv = ContentType.objects.get_for_model(Track2Invoice)
    for i in range(pairs):
        for prefix in ("open", "secret"):
            account = Track2Account.objects.create(label=f"{prefix}-a{i}")
            invoice = Track2Invoice.objects.create(note=f"{prefix}-i{i}")
            Track2GfkComment.objects.create(
                body=f"{prefix}-acct-{i}", target_ct=acct, target_id=account.pk
            )
            Track2GfkComment.objects.create(
                body=f"{prefix}-inv-{i}", target_ct=inv, target_id=invoice.pk
            )


def _run(schema: DjangoGraphQLSchema, query: str) -> tuple[Any, int]:
    """Execute a query and count its SQL statements.

    Args:
        schema: Schema to execute against.
        query: GraphQL document.

    Returns:
        The response data and the number of queries issued.
    """
    with CaptureQueriesContext(connection) as queries:
        result = graphql_sync(schema.graphql_schema, query)
    assert result.errors is None, result.errors
    return result.data, len(queries)


def _targets(data: Any) -> dict[str, Any]:
    """Index the list response by owner body.

    Args:
        data: Response data of the list query.

    Returns:
        Mapping of owner body to its target value.
    """
    return {row["body"]: row["target"] for row in data["allComments"]["results"]}


@pytest.mark.django_db
def test_union_member_scope_hides_account_target() -> None:
    """A union member's hook nulls a hidden target and keeps visible ones.

    Rows excluded by the member type never reach the response.
    """
    _seed(1)
    data, _ = _run(_schema(union=True), _UNION_LIST)
    targets = _targets(data)
    assert targets["secret-acct-0"] is None
    assert targets["open-acct-0"] == {
        "__typename": "ScopedAccount",
        "label": "open-a0",
    }
    # The invoice member declares the inherited no-op scope behavior.
    assert targets["secret-inv-0"] == {
        "__typename": "ScopedInvoice",
        "note": "secret-i0",
    }


@pytest.mark.django_db
def test_union_mixed_members_scope_each_member_independently() -> None:
    """Every scoped member hides its own rows within one mixed list.

    Visible and hidden rows of several members share one query.
    """
    _seed(2)
    data, _ = _run(_schema(union=True, scope_invoice=True), _UNION_LIST)
    targets = _targets(data)
    for body, target in targets.items():
        assert (target is None) == body.startswith("secret"), body


@pytest.mark.django_db
def test_union_scope_query_count_does_not_grow_with_owners() -> None:
    """Scoping is applied inside the batched prefetch, not per owner.

    Adding owners must not add queries.
    """
    schema = _schema(union=True, scope_invoice=True)
    _seed(2)
    _, small = _run(schema, _UNION_LIST)
    _seed(6)
    data, large = _run(schema, _UNION_LIST)
    assert len(data["allComments"]["results"]) == 32
    assert large == small
    for body, target in _targets(data).items():
        assert (target is None) == body.startswith("secret"), body


@pytest.mark.django_db
@override_settings(DJANGO_GRAPHEX={"OPTIMIZE_QUERYSET": False})
def test_union_scope_holds_with_optimizer_disabled() -> None:
    """The scoped prefetch also runs when queryset optimization is off.

    Hidden rows stay hidden without the optimizer.
    """
    _seed(2)
    data, _ = _run(_schema(union=True, scope_invoice=True), _UNION_LIST)
    for body, target in _targets(data).items():
        assert (target is None) == body.startswith("secret"), body


@pytest.mark.django_db
def test_union_single_owner_resolver_falls_back_to_membership_check() -> None:
    """An owner reached without a prefetch still hides the target.

    The resolver then checks the single target against the member scope.
    """
    from django_graphex.core import field

    _seed(1)
    reg = Registry()

    class AccountType(DjangoObjectType):
        """Account member hiding everything."""

        class Meta:
            """Bind to the private registry."""

            model = Track2Account
            registry = reg
            name = "SingleAccount"

        @classmethod
        def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
            """Hide all rows.

            Args:
                queryset: Unscoped rows.
                info: Request resolve info.

            Returns:
                An empty queryset.
            """
            return queryset.none()

    class InvoiceType(DjangoObjectType):
        """Unscoped second member."""

        class Meta:
            """Bind to the private registry."""

            model = Track2Invoice
            registry = reg
            name = "SingleInvoice"

    class TargetUnion(DjangoUnionType):
        """Union over both members."""

        class Meta:
            """Bind to the private registry."""

            types = (AccountType, InvoiceType)
            registry = reg
            name = "SingleTarget"

    class OwnerType(DjangoObjectType):
        """Owner with a typed union."""

        class Meta:
            """Bind to the private registry."""

            model = Track2GfkComment
            registry = reg
            name = "SingleOwner"
            unions = {"target": TargetUnion}

    class Query(ObjectType):
        """Return owners straight from the ORM."""

        hidden = field(
            OwnerType,
            resolver=lambda root, info: Track2GfkComment.objects.get(
                body="open-acct-0"
            ),
        )
        shown = field(
            OwnerType,
            resolver=lambda root, info: Track2GfkComment.objects.get(body="open-inv-0"),
        )

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))
    result = graphql_sync(
        schema.graphql_schema,
        "{ hidden { target { __typename } } shown { target { __typename } } }",
    )
    assert result.errors is None
    assert result.data == {
        "hidden": {"target": None},
        "shown": {"target": {"__typename": "SingleInvoice"}},
    }


@pytest.mark.django_db
@override_settings(DJANGO_GRAPHEX={"OPTIMIZE_ONLY_FIELDS": True})
def test_unrelated_scoped_type_keeps_union_column_narrowing() -> None:
    """A scoped type outside the union leaves the narrowed member prefetch alone.

    Only member models of a typed union decide whether its targets are scoped.
    """
    from tests.models import Track2Order

    _seed(1)
    reg = Registry()

    class AccountType(DjangoObjectType):
        """Unscoped member."""

        class Meta:
            """Bind to the private registry."""

            model = Track2Account
            registry = reg
            name = "NarrowAccount"

    class InvoiceType(DjangoObjectType):
        """Unscoped member."""

        class Meta:
            """Bind to the private registry."""

            model = Track2Invoice
            registry = reg
            name = "NarrowInvoice"

    class OrderType(DjangoObjectType):
        """Scoped type that is not a member of the union."""

        class Meta:
            """Bind to the private registry."""

            model = Track2Order
            registry = reg

        @classmethod
        def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
            """Hide every order.

            Args:
                queryset: Unscoped rows.
                info: Request resolve info.

            Returns:
                An empty queryset.
            """
            return queryset.none()

    class TargetUnion(DjangoUnionType):
        """Union over the two unscoped members."""

        class Meta:
            """Bind to the private registry."""

            types = (AccountType, InvoiceType)
            registry = reg
            name = "NarrowTarget"

    class CommentType(DjangoObjectType):
        """Owner exposing the typed union."""

        class Meta:
            """Bind to the private registry."""

            model = Track2GfkComment
            registry = reg
            unions = {"target": TargetUnion}

    class CommentListType(DjangoListObjectType):
        """List container for owners."""

        class Meta:
            """Bind to the private registry."""

            model = Track2GfkComment
            registry = reg
            pagination = LimitOffsetGraphqlPagination(
                default_limit=None, max_limit=None
            )

    class Query(ObjectType):
        """Expose the owner list."""

        all_comments = DjangoListObjectField(CommentListType)

    schema = DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))
    query = """{ allComments { results { target {
      ... on NarrowAccount { balance } ... on NarrowInvoice { amount } } } } }"""
    with CaptureQueriesContext(connection) as queries:
        result = graphql_sync(schema.graphql_schema, query)
    assert result.errors is None, result.errors
    account_sql = " ".join(
        q["sql"] for q in queries.captured_queries if "track2account" in q["sql"]
    ).lower()
    assert "balance" in account_sql
    assert "label" not in account_sql
