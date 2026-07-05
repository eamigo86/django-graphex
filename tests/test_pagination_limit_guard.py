# -*- coding: utf-8 -*-
"""Limit/first validation: zero and negative page sizes are clean GraphQLErrors.

Two latent bugs are pinned here:

* "_positive_int(0, strict=True)" returned "0" instead of raising, because the
  "if integer_string:" guard treats the int "0" as falsy and early-returns
  before the strict-zero check. Consequences: "limit=0" -> silent empty page;
  "first=0" -> silent fallback to the default page size.
* A negative "limit"/"first" raised a bare "ValueError()" (no message) that
  escaped the resolver as an HTTP 500, instead of the clean "GraphQLError" the
  negative-offset path already produces.

The fix makes the guard reach the strict check and surfaces both cases as a
"GraphQLError" naming the argument at every paginator entry point.
"""

from __future__ import annotations

import pytest
from django.test import TestCase
from graphql import GraphQLError

from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from django_graphex.paginations.utils import _positive_int
from tests.models import Author


# --------------------------------------------------------------------------- #
# FIX 2 — _positive_int strict-zero guard (the falsy-zero bug)                  #
# --------------------------------------------------------------------------- #
def test_positive_int_strict_zero_int_raises() -> None:
    """Assert the int 0 (not just the string "0") reaches the strict-zero check.

    If this fails, the falsy-zero guard bug regresses: "limit=0" silently
    returns an empty page instead of raising.
    """
    with pytest.raises(ValueError):
        _positive_int(0, strict=True)


def test_positive_int_zero_non_strict_returns_zero() -> None:
    """Assert non-strict 0 remains a valid passthrough value.

    If this fails, the strict-zero fix has an over-broad side effect that
    also rejects zero when strict mode is off.
    """
    assert _positive_int(0) == 0


# --------------------------------------------------------------------------- #
# FIX 3 — negative limit/first -> clean GraphQLError (not a bare ValueError)    #
# FIX 2 (entry points) — limit=0/first=0 -> clean GraphQLError                  #
# --------------------------------------------------------------------------- #
class LimitOffsetGuardDbTest(TestCase):
    """Exercise the "limit" guard on "LimitOffsetGraphqlPagination.paginate_queryset".

    Covers negative, zero and valid "limit" values against a real queryset.
    """

    def setUp(self) -> None:
        """Seed three authors so the paginator has rows to slice.

        Creates authors "a", "b" and "c" in that insertion order.
        """
        for name in ("a", "b", "c"):
            Author.objects.create(name=name)

    def test_negative_limit_raises_graphql_error(self) -> None:
        """Assert a negative "limit" raises a "GraphQLError" naming the argument.

        If this fails, a negative limit escapes as a bare ValueError instead
        of the clean, argument-named GraphQLError clients expect.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted via
                pytest.raises.
        """
        p = LimitOffsetGraphqlPagination(default_limit=5, max_limit=10)
        with pytest.raises(GraphQLError, match="limit"):
            p.paginate_queryset(Author.objects.all(), limit=-5)

    def test_zero_limit_raises_graphql_error(self) -> None:
        """Assert "limit=0" raises a "GraphQLError" instead of returning an empty page.

        If this fails, the falsy-zero guard bug regresses and a caller
        silently gets zero rows instead of a clear error.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted via
                pytest.raises.
        """
        p = LimitOffsetGraphqlPagination(default_limit=5, max_limit=10)
        with pytest.raises(GraphQLError, match="limit"):
            p.paginate_queryset(Author.objects.all(), limit=0)

    def test_valid_limit_still_works(self) -> None:
        """Assert a valid positive "limit" still slices the queryset normally.

        If this fails, the guard added for negative/zero limits has a
        regression that also breaks well-formed requests.
        """
        p = LimitOffsetGraphqlPagination(default_limit=5, max_limit=10)
        out = list(p.paginate_queryset(Author.objects.all(), limit=2))
        assert len(out) == 2


class PageGuardDbTest(TestCase):
    """Exercise the page-size guard on "PageGraphqlPagination.paginate_queryset".

    Covers negative, zero and valid page-size values against a real queryset.
    """

    def setUp(self) -> None:
        """Seed three authors so the paginator has rows to slice.

        Creates authors "a", "b" and "c" in that insertion order.
        """
        for name in ("a", "b", "c"):
            Author.objects.create(name=name)

    def test_negative_page_size_raises_graphql_error(self) -> None:
        """Assert a negative page size raises a "GraphQLError" naming the argument.

        If this fails, a negative page size escapes as a bare ValueError
        instead of the clean, argument-named GraphQLError clients expect.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted via
                pytest.raises.
        """
        p = PageGraphqlPagination(
            page_size=5, max_page_size=10, page_size_query_param="pageSize"
        )
        with pytest.raises(GraphQLError, match="page"):
            p.paginate_queryset(Author.objects.all(), page=1, pageSize=-2)

    def test_zero_page_size_raises_graphql_error(self) -> None:
        """Assert a zero page size raises a "GraphQLError" instead of an empty page.

        If this fails, the falsy-zero guard bug regresses and a caller
        silently gets zero rows instead of a clear error.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted via
                pytest.raises.
        """
        p = PageGraphqlPagination(
            page_size=5, max_page_size=10, page_size_query_param="pageSize"
        )
        with pytest.raises(GraphQLError, match="page"):
            p.paginate_queryset(Author.objects.all(), page=1, pageSize=0)

    def test_valid_page_size_still_works(self) -> None:
        """Assert a valid positive page size still slices the queryset normally.

        If this fails, the guard added for negative/zero page sizes has a
        regression that also breaks well-formed requests.
        """
        p = PageGraphqlPagination(
            page_size=5, max_page_size=10, page_size_query_param="pageSize"
        )
        out = list(p.paginate_queryset(Author.objects.all(), page=1, pageSize=2))
        assert len(out) == 2


class CursorGuardDbTest(TestCase):
    """Exercise the "first" guard on "CursorGraphqlPagination" entry points.

    Covers negative, zero and valid "first" values on both
    "paginate_queryset" and "get_page_info".
    """

    def setUp(self) -> None:
        """Seed three authors so the paginator has rows to slice.

        Creates authors "a", "b" and "c" in that insertion order.
        """
        for name in ("a", "b", "c"):
            Author.objects.create(name=name)

    def test_negative_first_raises_graphql_error(self) -> None:
        """Assert a negative "first" raises a "GraphQLError" naming the argument.

        If this fails, a negative "first" escapes as a bare ValueError
        instead of the clean, argument-named GraphQLError clients expect.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted via
                pytest.raises.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=5, max_page_size=10)
        with pytest.raises(GraphQLError, match="first"):
            p.paginate_queryset(Author.objects.all(), first=-2)

    def test_zero_first_raises_graphql_error(self) -> None:
        """Assert "first=0" raises a "GraphQLError" instead of returning an empty page.

        If this fails, the falsy-zero guard bug regresses and a caller
        silently gets a fallback page size instead of a clear error.

        Raises:
            GraphQLError: Expected from "paginate_queryset" and asserted via
                pytest.raises.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=5, max_page_size=10)
        with pytest.raises(GraphQLError, match="first"):
            p.paginate_queryset(Author.objects.all(), first=0)

    def test_negative_first_raises_graphql_error_in_page_info(self) -> None:
        """Assert a negative "first" also raises a "GraphQLError" from "get_page_info".

        If this fails, the guard is applied inconsistently across entry
        points, letting "get_page_info" accept an invalid negative "first"
        that "paginate_queryset" would reject.

        Raises:
            GraphQLError: Expected from "get_page_info" and asserted via
                pytest.raises.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=5, max_page_size=10)
        with pytest.raises(GraphQLError, match="first"):
            p.get_page_info(Author.objects.all(), first=-2)

    def test_valid_first_still_works(self) -> None:
        """Assert a valid positive "first" still slices the queryset normally.

        If this fails, the guard added for negative/zero "first" has a
        regression that also breaks well-formed requests.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=5, max_page_size=10)
        out = list(p.paginate_queryset(Author.objects.all(), first=2))
        assert len(out) == 2
