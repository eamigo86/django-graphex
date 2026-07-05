"""Remaining branch coverage for "paginations/pagination.py".

Covers the in-memory (prefetch-cache) paginate paths for limit/offset, page and
cursor paginators, the page-size-None early return, the comma-ordering single
branches, cursor decode validation, and the cursor "get_page_info" /
"get_page_info_field" resolver paths (both empty and populated windows).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.test import TestCase

from django_graphex.base_types import DjangoListObjectBase
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from tests.models import Author


def _items(*values: str) -> list[SimpleNamespace]:
    """Build one throwaway namespace object per given value, under the "name" attribute.

    Args:
        *values: The values to wrap, one "SimpleNamespace(name=value)" each.

    Returns:
        A list of "SimpleNamespace" objects, in the given order.
    """
    return [SimpleNamespace(name=v) for v in values]


# --------------------------------------------------------------------------- #
# In-memory (non-queryset) paginate paths                                       #
# --------------------------------------------------------------------------- #
def test_limit_offset_inmemory_orders_and_slices() -> None:
    """Limit/offset in-memory pagination orders by "name" then slices to the default limit.

    This test breaks if ordering stops being applied before slicing.
    """
    p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10)
    out = p.paginate_queryset(_items("c", "a", "b"), ordering="name")
    assert [o.name for o in out] == ["a", "b"]


def test_limit_offset_inmemory_no_order() -> None:
    """Limit/offset in-memory pagination without an ordering slices in input order.

    This test breaks if the no-ordering branch starts sorting the input
    instead of preserving its original order.
    """
    p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10)
    out = p.paginate_queryset(_items("x", "y", "z"))
    assert [o.name for o in out] == ["x", "y"]


def test_limit_offset_unbounded_returns_input() -> None:
    """With no default and no max limit, the paginator returns the input unchanged.

    This test breaks if "_resolve_page_size" stops returning None when both
    "default_limit" and "max_limit" are None, which is what makes
    "paginate_queryset" return the original iterable as-is.
    """
    # No default and no max -> _resolve_page_size returns None -> qs returned.
    p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
    data = _items("a", "b")
    assert p.paginate_queryset(data) is data


def test_page_inmemory_orders_and_slices() -> None:
    """Page-based in-memory pagination orders by "name" then slices to page 1.

    This test breaks if ordering stops being applied before the page slice.
    """
    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    out = p.paginate_queryset(_items("c", "a", "b"), page=1, ordering="name")
    assert [o.name for o in out] == ["a", "b"]


def test_page_inmemory_no_order() -> None:
    """Page-based in-memory pagination without an ordering slices in input order.

    This test breaks if the no-ordering branch starts sorting the input
    instead of preserving its original order.
    """
    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    out = p.paginate_queryset(_items("x", "y", "z"), page=1)
    assert [o.name for o in out] == ["x", "y"]


def test_page_size_none_returns_none() -> None:
    """With no page size resolvable from any source, "paginate_queryset" returns None.

    This test breaks if the page-size-None resolution branch stops returning
    None when "page_size", "max_page_size", and the client param are all
    absent.
    """
    # No page_size, no max, no client param -> page_size resolves to None ->
    # the resolver returns None (lines 436-443).
    p = PageGraphqlPagination(page_size=None, max_page_size=None)
    assert p.paginate_queryset(_items("a", "b"), page=1) is None


def test_page_zero_raises() -> None:
    """page=0 raises "GraphQLError" via an explicit raise, not a stripped assert.

    This test breaks if the page=0 guard reverts to a bare "assert", which
    is silently stripped under "python -O" and would let an invalid page
    slip through uncaught.
    """
    # page=0 must raise GraphQLError (explicit raise, not assert — assert is
    # stripped under python -O and would silently accept page=0).
    from graphql import GraphQLError

    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    with pytest.raises(GraphQLError):
        p.paginate_queryset(_items("a", "b"), page=0)


def test_page_size_query_param_in_fields() -> None:
    """The configured "page_size_query_param" name appears in "to_graphql_fields".

    This test breaks if the custom query-param name stops being surfaced
    among the paginator's GraphQL argument fields.
    """
    p = PageGraphqlPagination(page_size=5, page_size_query_param="pageSize")
    assert "pageSize" in p.to_graphql_fields()


# --------------------------------------------------------------------------- #
# Cursor: decode validation + in-memory paginate / page info                    #
# --------------------------------------------------------------------------- #
def test_cursor_decode_rejects_bad_prefix() -> None:
    """A base64 payload with the wrong cursor prefix raises "ValueError" on decode.

    This test breaks if "decode_cursor" stops validating the cursor prefix
    before accepting the payload.
    """
    import base64

    bad = base64.urlsafe_b64encode(b"notcursor:1").decode("ascii")
    with pytest.raises(ValueError):
        CursorGraphqlPagination.decode_cursor(bad)


def test_cursor_decode_rejects_garbage() -> None:
    """A non-base64 garbage string raises "ValueError" on decode.

    This test breaks if "decode_cursor" stops raising for input that cannot
    be base64-decoded at all.
    """
    with pytest.raises(ValueError):
        CursorGraphqlPagination.decode_cursor("!!!not-base64!!!")


def test_cursor_inmemory_paginate_with_cursor() -> None:
    """Cursor-based in-memory pagination returns the rows strictly after the cursor.

    This test breaks if the in-memory cursor paginator stops excluding rows
    at or before the decoded cursor value.
    """
    p = CursorGraphqlPagination(ordering="name", page_size=10)
    items = _items("a", "b", "c", "d")
    token = CursorGraphqlPagination.encode_cursor("b")
    out = p.paginate_queryset(items, first=10, cursor=token)
    assert [o.name for o in out] == ["c", "d"]


def test_cursor_inmemory_out_of_range_cursor_returns_empty() -> None:
    """A cursor value past every row returns an empty page, matching DB keyset semantics.

    Composite keyset: a value-only cursor past every row ("zzz" > "b")
    matches the DB keyset semantics (WHERE name > "zzz" -> empty), not the
    legacy "restart from 0" behavior that silently re-served the whole list.
    This test breaks if that legacy behavior regresses.
    """
    p = CursorGraphqlPagination(ordering="name", page_size=10)
    items = _items("a", "b")
    token = CursorGraphqlPagination.encode_cursor("zzz")
    out = p.paginate_queryset(items, first=10, cursor=token)
    assert [o.name for o in out] == []


def test_cursor_inmemory_page_info_populated_window() -> None:
    """A populated in-memory cursor window reports correct hasNext/hasPrevious and boundary cursors.

    This test breaks if the page-info computation over an in-memory list
    stops matching the queryset-backed computation for the same window.
    """
    p = CursorGraphqlPagination(ordering="name", page_size=2)
    items = _items("a", "b", "c", "d")
    info = p.get_page_info(items, first=2)
    assert info["has_next_page"] is True
    assert info["has_previous_page"] is False
    assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("a")
    assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor("b")


def test_cursor_inmemory_page_info_empty_window() -> None:
    """An empty in-memory list reports the empty-page contract: all flags False, cursors None.

    This test breaks if the empty-window branch stops returning the
    canonical empty-page contract.
    """
    p = CursorGraphqlPagination(ordering="name", page_size=2)
    info = p.get_page_info([], first=2)
    assert info == {
        "has_next_page": False,
        "has_previous_page": False,
        "start_cursor": None,
        "end_cursor": None,
    }


def test_cursor_page_info_field_resolver_non_list_root_returns_none() -> None:
    """The native cursor pageInfo field resolver returns None for a non-list root value.

    S-del-backend-11: the graphene-bodied "get_page_info_field" was deleted;
    the native cursor pageInfo field is "get_native_page_info_field" (a
    graphql-core "GraphQLField" with a "resolve" callable). This test breaks
    if the resolver stops guarding against a root value that is not a
    "DjangoListObjectBase".
    """
    p = CursorGraphqlPagination(ordering="name")
    field = p.get_native_page_info_field(None)
    assert field.resolve("not-a-base", None) is None


# --------------------------------------------------------------------------- #
# Cursor get_page_info over a real queryset                                     #
# --------------------------------------------------------------------------- #
class CursorPageInfoDbTest(TestCase):
    """Coverage for "get_page_info" driven by a real Django queryset.

    Confirms the queryset-backed computation matches the in-memory one.
    """

    def setUp(self) -> None:
        """Create four throwaway authors ("a".."d") for the queryset page-info tests.

        Shared as fixture data by every test in this class.
        """
        for name in ("a", "b", "c", "d"):
            Author.objects.create(name=name)

    def test_page_info_queryset_first_page(self) -> None:
        """The first page over a real queryset reports hasNextPage and a decodable start cursor.

        This test breaks if the queryset-backed first-page computation stops
        matching the in-memory one.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        info = p.get_page_info(Author.objects.all(), first=2)
        assert info["has_next_page"] is True
        assert info["has_previous_page"] is False
        # Composite cursor: decode recovers the ordering value ('a').
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "a"

    def test_page_info_queryset_after_cursor_has_previous(self) -> None:
        """Paging past the first page's end cursor reports hasPreviousPage True.

        This test breaks if the composite (value, pk) boundary stops being
        honored when driving the second page from a real end cursor.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        # Drive the second page from the real endCursor of the first page so the
        # composite (value, pk) boundary is honoured.
        first = p.get_page_info(Author.objects.all(), first=2)
        info = p.get_page_info(
            Author.objects.all(), first=2, cursor=first["end_cursor"]
        )
        assert info["has_previous_page"] is True
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "c"

    def test_page_info_queryset_empty_result(self) -> None:
        """A cursor past the last row over a real queryset returns None boundary cursors.

        This test breaks if the empty-result branch stops returning None
        boundary cursors for a cursor past every row.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        # A cursor past the last row -> no rows -> the empty branch.
        token = CursorGraphqlPagination.encode_cursor("z")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info["start_cursor"] is None
        assert info["end_cursor"] is None

    def test_page_info_field_resolver_with_list_base(self) -> None:
        """The native pageInfo field resolver remaps snake_case keys to the camelCase wire names.

        S-del-backend-11: uses the native pageInfo field
        ("get_native_page_info_field"); its resolver remaps the snake_case
        "get_page_info" keys to the camelCase wire names the native
        CursorPageInfo type exposes. This test breaks if that remapping
        stops happening.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        field = p.get_native_page_info_field(None)
        base = DjangoListObjectBase(
            results=Author.objects.all(), count=4, results_field_name="results"
        )
        info = field.resolve(base, None, first=2)
        assert info["hasNextPage"] is True

    # ----------------------------------------------------------------------- #
    # Audit rank 22: documented cursor empty-page / boundary semantics.        #
    # These lock in the get_page_info hasNextPage / hasPreviousPage / cursor    #
    # contract at the edges (first page, last row, first row, invalid /         #
    # out-of-range cursor). Rows are a,b,c,d ordered by name, page_size=2.      #
    # ----------------------------------------------------------------------- #
    def test_page_info_first_page_no_cursor_has_no_previous(self) -> None:
        """The first page (cursor=None) has hasPreviousPage False and hasNextPage True.

        4 rows exceed page_size 2, so hasNextPage is True; the boundary
        cursors decode to the first/last value in the window. This test
        breaks if that first-page contract regresses.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        info = p.get_page_info(Author.objects.all(), first=2)
        assert info["has_previous_page"] is False
        assert info["has_next_page"] is True
        # Composite cursors: decode recovers the ordering values ('a'/'b').
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "a"
        assert CursorGraphqlPagination.decode_cursor(info["end_cursor"]) == "b"

    def test_page_info_cursor_at_last_row_has_no_next(self) -> None:
        """The second page's window [c, d] has hasNextPage False and hasPreviousPage True.

        Driven from the first page's end cursor over a,b,c,d, nothing
        follows "d" so hasNextPage is False. This test breaks if that
        boundary contract regresses.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        page1 = p.get_page_info(Author.objects.all(), first=2)
        info = p.get_page_info(
            Author.objects.all(), first=2, cursor=page1["end_cursor"]
        )
        assert info["has_next_page"] is False
        assert info["has_previous_page"] is True
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "c"
        assert CursorGraphqlPagination.decode_cursor(info["end_cursor"]) == "d"

    def test_page_info_cursor_at_first_row_has_previous(self) -> None:
        """A cursor at the first row "a" produces a window [b, c] with hasPreviousPage True.

        The composite cursor for row "a" is the endCursor of a size-1 first
        page; row "a" precedes "b" so hasPreviousPage is True and hasNextPage
        is also True. This test breaks if that boundary contract regresses.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=1)
        # The composite cursor for row 'a' is the endCursor of a size-1 first page.
        cursor_a = p.get_page_info(Author.objects.all(), first=1)["end_cursor"]
        p2 = CursorGraphqlPagination(ordering="name", page_size=2)
        info = p2.get_page_info(Author.objects.all(), first=2, cursor=cursor_a)
        assert info["has_previous_page"] is True
        assert info["has_next_page"] is True
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "b"
        assert CursorGraphqlPagination.decode_cursor(info["end_cursor"]) == "c"

    def test_page_info_cursor_at_exact_last_row_empty_page(self) -> None:
        """A cursor at the last row "d" produces the empty-page contract.

        Nothing follows "d" strictly, so all flags are False and both
        boundary cursors are None. This test breaks if that contract
        regresses.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("d")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info == {
            "has_next_page": False,
            "has_previous_page": False,
            "start_cursor": None,
            "end_cursor": None,
        }

    def test_page_info_out_of_range_cursor_empty_page(self) -> None:
        """An out-of-range cursor value past every row produces the empty-page contract, never an error.

        This test breaks if an out-of-range (but validly-encoded) cursor
        starts raising instead of returning the canonical empty-page
        contract.
        """
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("z")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info == {
            "has_next_page": False,
            "has_previous_page": False,
            "start_cursor": None,
            "end_cursor": None,
        }

    def test_page_info_invalid_cursor_raises_graphql_error(self) -> None:
        """A malformed, non-decodable cursor raises "GraphQLError('Invalid cursor')".

        Mirrors "paginate_queryset"'s tampered-cursor guard. This test
        breaks if "get_page_info" stops sharing that same guard.
        """
        from graphql import GraphQLError

        p = CursorGraphqlPagination(ordering="name", page_size=2)
        with pytest.raises(GraphQLError):
            p.get_page_info(Author.objects.all(), first=2, cursor="!!!not-base64!!!")


# --------------------------------------------------------------------------- #
# Audit rank 17: DESCENDING-order cursor boundaries on a NUMERIC field,        #
# including a cursor at value 0 and at a NEGATIVE value. Descending order uses #
# the ``lt`` lookup for "after cursor" and ``gt`` for "before cursor" (see     #
# pagination.py get_page_info), so 0 and negative boundaries must not be       #
# confused by any truthiness/`if cursor` handling. Rows balances: 2, 1, 0, -1, #
# -2 ordered by "-balance" (descending) -> window order [2, 1, 0, -1, -2].     #
# --------------------------------------------------------------------------- #
class CursorDescendingNumericPageInfoTest(TestCase):
    """Coverage for descending-order cursor boundaries on a numeric field.

    Covers zero and negative boundary values, which must not be confused by
    any truthiness-based cursor handling.
    """

    def setUp(self) -> None:
        """Create five accounts with balances 2, 1, 0, -1, -2 for the descending-order tests.

        Shared as fixture data by every test in this class.
        """
        from tests.models import Track2Account

        for balance in (2, 1, 0, -1, -2):
            Track2Account.objects.create(balance=balance)

    def _qs(self) -> Any:
        """Return a fresh queryset over every "Track2Account" row created in "setUp".

        Returns:
            The unfiltered "Track2Account" queryset.
        """
        from tests.models import Track2Account

        return Track2Account.objects.all()

    def test_descending_first_page_no_cursor(self) -> None:
        """The descending first page's window [2, 1] has hasNextPage True and hasPreviousPage False.

        Rows 0, -1, -2 still follow, so hasNextPage is True; the boundary
        cursors decode to 2 and 1. This test breaks if that contract
        regresses.
        """
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        info = p.get_page_info(self._qs(), first=2)
        assert info["has_previous_page"] is False
        assert info["has_next_page"] is True
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "2"
        assert CursorGraphqlPagination.decode_cursor(info["end_cursor"]) == "1"

    def test_descending_cursor_at_zero_value(self) -> None:
        """A cursor at the falsy-but-valid balance 0 still applies the keyset predicate correctly.

        Descending order means rows strictly less than 0 follow: window
        [-1, -2]. hasPreviousPage is True (2, 1, 0 precede) and hasNextPage
        is False (nothing after -2). This test breaks if the 0 value is
        swallowed by a falsy guard instead of being applied via the keyset
        predicate.
        """
        p1 = CursorGraphqlPagination(ordering="-balance", page_size=3)
        # First 3 descending rows are 2,1,0 -> endCursor points at the 0 row.
        cursor_zero = p1.get_page_info(self._qs(), first=3)["end_cursor"]
        assert CursorGraphqlPagination.decode_cursor(cursor_zero) == "0"
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        info = p.get_page_info(self._qs(), first=2, cursor=cursor_zero)
        assert info["has_previous_page"] is True
        assert info["has_next_page"] is False
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "-1"
        assert CursorGraphqlPagination.decode_cursor(info["end_cursor"]) == "-2"

    def test_descending_cursor_at_negative_value(self) -> None:
        """A cursor at a negative balance (-1) produces a window containing only [-2].

        Descending order means rows less than -1 follow: window [-2] only.
        hasPreviousPage is True (2, 1, 0, -1 precede) and hasNextPage is
        False (nothing after -2). This test breaks if negative boundary
        values are mishandled.
        """
        p1 = CursorGraphqlPagination(ordering="-balance", page_size=4)
        # First 4 descending rows are 2,1,0,-1 -> endCursor points at the -1 row.
        cursor_neg1 = p1.get_page_info(self._qs(), first=4)["end_cursor"]
        assert CursorGraphqlPagination.decode_cursor(cursor_neg1) == "-1"
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        info = p.get_page_info(self._qs(), first=2, cursor=cursor_neg1)
        assert info["has_previous_page"] is True
        assert info["has_next_page"] is False
        assert CursorGraphqlPagination.decode_cursor(info["start_cursor"]) == "-2"
        assert CursorGraphqlPagination.decode_cursor(info["end_cursor"]) == "-2"

    def test_descending_paginate_queryset_after_zero_cursor(self) -> None:
        """ "paginate_queryset" (not just page-info) also honors a 0 cursor in descending order.

        The rows strictly below 0 are -1, -2. This test breaks if
        "paginate_queryset" stops applying the same 0-boundary handling as
        "get_page_info".
        """
        p = CursorGraphqlPagination(ordering="-balance", page_size=10)
        token = CursorGraphqlPagination.encode_cursor(0)
        out = p.paginate_queryset(self._qs(), first=10, cursor=token)
        assert [o.balance for o in out] == [-1, -2]

    def test_descending_cursor_at_lowest_value_empty_page(self) -> None:
        """A cursor at the lowest balance (-2) in descending order produces the empty-page contract.

        Nothing follows -2 strictly, so all flags are False and both
        boundary cursors are None. This test breaks if that contract
        regresses.
        """
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        token = CursorGraphqlPagination.encode_cursor(-2)
        info = p.get_page_info(self._qs(), first=2, cursor=token)
        assert info == {
            "has_next_page": False,
            "has_previous_page": False,
            "start_cursor": None,
            "end_cursor": None,
        }
