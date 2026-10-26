"""GenericForeignKey scoped prefetch runs only the hooks of present targets."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext
from graphql import graphql_sync

from django_graphex.core import ObjectType
from django_graphex.fields import DjangoListObjectField
from django_graphex.paginations import LimitOffsetGraphqlPagination
from django_graphex.registry import Registry
from django_graphex.schema import DjangoGraphQLSchema
from django_graphex.types import DjangoListObjectType, DjangoObjectType, DjangoUnionType
from tests._schema_isolation import isolated_pair
from tests.models import Track2Account, Track2GfkComment, Track2Invoice

_FLAT = "{ allComments { results { body target { appLabel modelName id } } } }"
_UNION = """
{ allComments { results { body target {
  __typename ... on LazyAccount { label } ... on LazyInvoice { note }
} } } }
"""


def _schema(
    calls: list[str], *, union: bool, raising: str | None = None
) -> DjangoGraphQLSchema:
    """Build a schema whose account and invoice hooks record their calls.

    Args:
        calls: List the hooks append their model label to.
        union: Whether the GFK is exposed as a typed union or the flat type.
        raising: Label of the hook that raises, if any.

    Returns:
        The compiled schema with an "allComments" list root.
    """
    reg = Registry()

    account = _typed(reg, Track2Account, "acct", "LazyAccount", calls, raising)
    invoice = _typed(reg, Track2Invoice, "inv", "LazyInvoice", calls, raising)
    if union:

        class Target(DjangoUnionType):
            """Union over both scoped members."""

            class Meta:
                """Bind to the private registry."""

                types = (account, invoice)
                registry = reg
                name = "LazyTarget"

        class Owner(DjangoObjectType):
            """Owner exposing the typed union."""

            class Meta:
                """Bind to the private registry."""

                model = Track2GfkComment
                registry = reg
                unions = {"target": Target}

    else:

        class Owner(DjangoObjectType):  # type: ignore[no-redef]
            """Owner exposing the flat GFK."""

            class Meta:
                """Bind to the private registry."""

                model = Track2GfkComment
                registry = reg

    class OwnerList(DjangoListObjectType):
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

        all_comments = DjangoListObjectField(OwnerList)

    return DjangoGraphQLSchema(query=Query, registries=isolated_pair(reg))


def _typed(
    reg: Registry,
    target_model: type,
    label: str,
    type_name: str,
    calls: list[str],
    raising: str | None,
) -> type:
    """Create a registered output type whose hook records its call.

    Args:
        reg: Registry to bind to.
        target_model: Model the type exposes.
        label: Label appended to the call list.
        type_name: GraphQL type name.
        calls: List the hook appends to.
        raising: Label of the hook that raises, if any.

    Returns:
        The output type.
    """

    class Scoped(DjangoObjectType):
        """Output type with a recording hook."""

        class Meta:
            """Bind to the private registry."""

            model = target_model
            registry = reg
            name = type_name

        @classmethod
        def get_queryset(cls, queryset: QuerySet, info: Any) -> QuerySet:
            """Record the call and optionally fail.

            Args:
                queryset: Unscoped rows.
                info: Request resolve info.

            Returns:
                The rows, unchanged.
            """
            calls.append(label)
            if raising == label:
                raise PermissionError("staff only")
            return queryset

    return Scoped


def _only_account_target() -> None:
    """Create one owner that points to an account and no invoice owner."""
    account = Track2Account.objects.create(label="open")
    Track2GfkComment.objects.create(
        body="c",
        target_ct=ContentType.objects.get_for_model(Track2Account),
        target_id=account.pk,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("union", [False, True], ids=["flat", "union"])
def test_unrelated_raising_hook_is_not_called(union: bool) -> None:
    """A hook of a content type no owner points to neither runs nor fails.

    Args:
        union: Whether the GFK is a typed union or the flat type.
    """
    _only_account_target()
    calls: list[str] = []
    schema = _schema(calls, union=union, raising="inv")
    result = graphql_sync(schema.graphql_schema, _UNION if union else _FLAT)
    assert result.errors is None, result.errors
    rows = result.data["allComments"]["results"]  # type: ignore[index]
    assert rows[0]["target"] is not None
    assert "inv" not in calls
    assert calls.count("acct") >= 1


@pytest.mark.django_db
@pytest.mark.parametrize("union", [False, True], ids=["flat", "union"])
def test_present_raising_hook_fails_the_field(union: bool) -> None:
    """A hook that raises for a present target still fails the list field.

    Args:
        union: Whether the GFK is a typed union or the flat type.
    """
    _only_account_target()
    schema = _schema([], union=union, raising="acct")
    result = graphql_sync(schema.graphql_schema, _UNION if union else _FLAT)
    assert result.errors
    assert "staff only" in result.errors[0].message


@pytest.mark.django_db
def test_query_count_is_one_per_present_content_type() -> None:
    """Present targets still load with one query per content type.

    The lazy scope must not add queries over the eager one.
    """
    acct = ContentType.objects.get_for_model(Track2Account)
    inv = ContentType.objects.get_for_model(Track2Invoice)
    for i in range(4):
        a = Track2Account.objects.create(label=f"a{i}")
        n = Track2Invoice.objects.create(note=f"n{i}")
        Track2GfkComment.objects.create(body="x", target_ct=acct, target_id=a.pk)
        Track2GfkComment.objects.create(body="y", target_ct=inv, target_id=n.pk)
    schema = _schema([], union=False)
    with CaptureQueriesContext(connection) as queries:
        result = graphql_sync(schema.graphql_schema, _FLAT)
    assert result.errors is None, result.errors
    assert len(queries) <= 4
