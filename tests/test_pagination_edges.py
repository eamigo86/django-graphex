# -*- coding: utf-8 -*-
"""Remaining branch coverage for ``paginations/pagination.py``.

Covers the in-memory (prefetch-cache) paginate paths for limit/offset, page and
cursor paginators, the page-size-None early return, the comma-ordering single
branches, cursor decode validation, and the cursor ``get_page_info`` /
``get_page_info_field`` resolver paths (both empty and populated windows).
"""

from types import SimpleNamespace

import pytest
from django.test import TestCase

from django_graphex.base_types import DjangoListObjectBase
from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    LimitOffsetGraphqlPagination,
    PageGraphqlPagination,
)
from tests.models import Author


def _items(*values):
    return [SimpleNamespace(name=v) for v in values]


# --------------------------------------------------------------------------- #
# In-memory (non-queryset) paginate paths                                       #
# --------------------------------------------------------------------------- #
def test_limit_offset_inmemory_orders_and_slices():
    p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10)
    out = p.paginate_queryset(_items("c", "a", "b"), ordering="name")
    assert [o.name for o in out] == ["a", "b"]


def test_limit_offset_inmemory_no_order():
    p = LimitOffsetGraphqlPagination(default_limit=2, max_limit=10)
    out = p.paginate_queryset(_items("x", "y", "z"))
    assert [o.name for o in out] == ["x", "y"]


def test_limit_offset_unbounded_returns_input():
    # No default and no max -> _resolve_page_size returns None -> qs returned.
    p = LimitOffsetGraphqlPagination(default_limit=None, max_limit=None)
    data = _items("a", "b")
    assert p.paginate_queryset(data) is data


def test_page_inmemory_orders_and_slices():
    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    out = p.paginate_queryset(_items("c", "a", "b"), page=1, ordering="name")
    assert [o.name for o in out] == ["a", "b"]


def test_page_inmemory_no_order():
    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    out = p.paginate_queryset(_items("x", "y", "z"), page=1)
    assert [o.name for o in out] == ["x", "y"]


def test_page_size_none_returns_none():
    # No page_size, no max, no client param -> page_size resolves to None ->
    # the resolver returns None (lines 436-443).
    p = PageGraphqlPagination(page_size=None, max_page_size=None)
    assert p.paginate_queryset(_items("a", "b"), page=1) is None


def test_page_zero_raises():
    # page=0 must raise GraphQLError (explicit raise, not assert — assert is
    # stripped under python -O and would silently accept page=0).
    from graphql import GraphQLError

    p = PageGraphqlPagination(page_size=2, max_page_size=10)
    with pytest.raises(GraphQLError):
        p.paginate_queryset(_items("a", "b"), page=0)


def test_page_size_query_param_in_fields():
    p = PageGraphqlPagination(page_size=5, page_size_query_param="pageSize")
    assert "pageSize" in p.to_graphql_fields()


# --------------------------------------------------------------------------- #
# Cursor: decode validation + in-memory paginate / page info                    #
# --------------------------------------------------------------------------- #
def test_cursor_decode_rejects_bad_prefix():
    import base64

    bad = base64.urlsafe_b64encode(b"notcursor:1").decode("ascii")
    with pytest.raises(ValueError):
        CursorGraphqlPagination.decode_cursor(bad)


def test_cursor_decode_rejects_garbage():
    with pytest.raises(ValueError):
        CursorGraphqlPagination.decode_cursor("!!!not-base64!!!")


def test_cursor_inmemory_paginate_with_cursor():
    p = CursorGraphqlPagination(ordering="name", page_size=10)
    items = _items("a", "b", "c", "d")
    token = CursorGraphqlPagination.encode_cursor("b")
    out = p.paginate_queryset(items, first=10, cursor=token)
    assert [o.name for o in out] == ["c", "d"]


def test_cursor_inmemory_start_not_found_returns_from_zero():
    p = CursorGraphqlPagination(ordering="name", page_size=10)
    items = _items("a", "b")
    # A cursor not present -> _inmemory_cursor_start returns 0.
    token = CursorGraphqlPagination.encode_cursor("zzz")
    out = p.paginate_queryset(items, first=10, cursor=token)
    assert [o.name for o in out] == ["a", "b"]


def test_cursor_inmemory_page_info_populated_window():
    p = CursorGraphqlPagination(ordering="name", page_size=2)
    items = _items("a", "b", "c", "d")
    info = p.get_page_info(items, first=2)
    assert info["has_next_page"] is True
    assert info["has_previous_page"] is False
    assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("a")
    assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor("b")


def test_cursor_inmemory_page_info_empty_window():
    p = CursorGraphqlPagination(ordering="name", page_size=2)
    info = p.get_page_info([], first=2)
    assert info == {
        "has_next_page": False,
        "has_previous_page": False,
        "start_cursor": None,
        "end_cursor": None,
    }


def test_cursor_page_info_field_resolver_non_list_root_returns_none():
    # S-del-backend-11: the graphene-bodied ``get_page_info_field`` was deleted;
    # the native cursor pageInfo field is ``get_native_page_info_field`` (a
    # graphql-core ``GraphQLField`` with a ``resolve`` callable).
    p = CursorGraphqlPagination(ordering="name")
    field = p.get_native_page_info_field(None)
    assert field.resolve("not-a-base", None) is None


# --------------------------------------------------------------------------- #
# Cursor get_page_info over a real queryset                                     #
# --------------------------------------------------------------------------- #
class CursorPageInfoDbTest(TestCase):
    def setUp(self):
        for name in ("a", "b", "c", "d"):
            Author.objects.create(name=name)

    def test_page_info_queryset_first_page(self):
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        info = p.get_page_info(Author.objects.all(), first=2)
        assert info["has_next_page"] is True
        assert info["has_previous_page"] is False
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("a")

    def test_page_info_queryset_after_cursor_has_previous(self):
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("b")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info["has_previous_page"] is True
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("c")

    def test_page_info_queryset_empty_result(self):
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        # A cursor past the last row -> no rows -> the empty branch.
        token = CursorGraphqlPagination.encode_cursor("z")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info["start_cursor"] is None
        assert info["end_cursor"] is None

    def test_page_info_field_resolver_with_list_base(self):
        # S-del-backend-11: use the native pageInfo field (``get_native_page_info_field``);
        # its resolver remaps the snake_case ``get_page_info`` keys to the camelCase
        # wire names the native CursorPageInfo type exposes.
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
    def test_page_info_first_page_no_cursor_has_no_previous(self):
        """First page (cursor=None): hasPreviousPage False, hasNextPage True
        (4 rows > page_size 2), boundary cursors are the first/last in window."""
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        info = p.get_page_info(Author.objects.all(), first=2)
        assert info["has_previous_page"] is False
        assert info["has_next_page"] is True
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("a")
        assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor("b")

    def test_page_info_cursor_at_last_row_has_no_next(self):
        """Cursor at the second-to-last row 'c' -> the window is the final row
        'd' only: hasNextPage False (nothing follows), hasPreviousPage True."""
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("c")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info["has_next_page"] is False
        assert info["has_previous_page"] is True
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("d")
        assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor("d")

    def test_page_info_cursor_at_first_row_has_previous(self):
        """Cursor at the first row 'a' -> the window is [b, c]: hasPreviousPage
        True (row 'a' is strictly before 'b'), hasNextPage True (row 'd' follows)."""
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("a")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info["has_previous_page"] is True
        assert info["has_next_page"] is True
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor("b")
        assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor("c")

    def test_page_info_cursor_at_exact_last_row_empty_page(self):
        """Cursor at the last row 'd' -> no rows strictly after it: the empty
        page contract (all flags False, both boundary cursors None)."""
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("d")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info == {
            "has_next_page": False,
            "has_previous_page": False,
            "start_cursor": None,
            "end_cursor": None,
        }

    def test_page_info_out_of_range_cursor_empty_page(self):
        """An out-of-range (valid value, past every row) cursor 'z' -> empty page
        contract (all flags False, cursors None) — never an error."""
        p = CursorGraphqlPagination(ordering="name", page_size=2)
        token = CursorGraphqlPagination.encode_cursor("z")
        info = p.get_page_info(Author.objects.all(), first=2, cursor=token)
        assert info == {
            "has_next_page": False,
            "has_previous_page": False,
            "start_cursor": None,
            "end_cursor": None,
        }

    def test_page_info_invalid_cursor_raises_graphql_error(self):
        """A malformed cursor (not decodable) -> GraphQLError('Invalid cursor'),
        mirroring paginate_queryset's tampered-cursor guard."""
        from graphql import GraphQLError

        p = CursorGraphqlPagination(ordering="name", page_size=2)
        with pytest.raises(GraphQLError):
            p.get_page_info(
                Author.objects.all(), first=2, cursor="!!!not-base64!!!"
            )


# --------------------------------------------------------------------------- #
# Audit rank 17: DESCENDING-order cursor boundaries on a NUMERIC field,        #
# including a cursor at value 0 and at a NEGATIVE value. Descending order uses #
# the ``lt`` lookup for "after cursor" and ``gt`` for "before cursor" (see     #
# pagination.py get_page_info), so 0 and negative boundaries must not be       #
# confused by any truthiness/`if cursor` handling. Rows balances: 2, 1, 0, -1, #
# -2 ordered by "-balance" (descending) -> window order [2, 1, 0, -1, -2].     #
# --------------------------------------------------------------------------- #
class CursorDescendingNumericPageInfoTest(TestCase):
    def setUp(self):
        from tests.models import Track2Account

        for balance in (2, 1, 0, -1, -2):
            Track2Account.objects.create(balance=balance)

    def _qs(self):
        from tests.models import Track2Account

        return Track2Account.objects.all()

    def test_descending_first_page_no_cursor(self):
        """Descending first page: window is [2, 1]; hasNextPage True (0,-1,-2
        follow), hasPreviousPage False; boundary cursors are 2 (highest) and 1."""
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        info = p.get_page_info(self._qs(), first=2)
        assert info["has_previous_page"] is False
        assert info["has_next_page"] is True
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor(2)
        assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor(1)

    def test_descending_cursor_at_zero_value(self):
        """Cursor AT balance 0 (a falsy-but-valid boundary). Descending -> rows
        strictly less than 0 follow: window [-1, -2]. hasPreviousPage True (2,1,0
        precede), hasNextPage False (nothing after -2). The 0 value must be
        decoded and applied via the ``balance__lt=0`` lookup, NOT swallowed by a
        falsy guard."""
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        token = CursorGraphqlPagination.encode_cursor(0)
        info = p.get_page_info(self._qs(), first=2, cursor=token)
        assert info["has_previous_page"] is True
        assert info["has_next_page"] is False
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor(-1)
        assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor(-2)

    def test_descending_cursor_at_negative_value(self):
        """Cursor AT a NEGATIVE balance (-1). Descending -> rows < -1 follow:
        window [-2] only. hasPreviousPage True (2,1,0,-1 precede), hasNextPage
        False (nothing after -2). Both boundary cursors are -2."""
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        token = CursorGraphqlPagination.encode_cursor(-1)
        info = p.get_page_info(self._qs(), first=2, cursor=token)
        assert info["has_previous_page"] is True
        assert info["has_next_page"] is False
        assert info["start_cursor"] == CursorGraphqlPagination.encode_cursor(-2)
        assert info["end_cursor"] == CursorGraphqlPagination.encode_cursor(-2)

    def test_descending_paginate_queryset_after_zero_cursor(self):
        """paginate_queryset (not just page-info) also honours the 0 cursor in
        descending order: the rows strictly below 0 are -1, -2."""
        p = CursorGraphqlPagination(ordering="-balance", page_size=10)
        token = CursorGraphqlPagination.encode_cursor(0)
        out = p.paginate_queryset(self._qs(), first=10, cursor=token)
        assert [o.balance for o in out] == [-1, -2]

    def test_descending_cursor_at_lowest_value_empty_page(self):
        """Cursor at the lowest balance (-2) in descending order -> nothing
        strictly after it: the empty-page contract (all flags False, cursors
        None)."""
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        token = CursorGraphqlPagination.encode_cursor(-2)
        info = p.get_page_info(self._qs(), first=2, cursor=token)
        assert info == {
            "has_next_page": False,
            "has_previous_page": False,
            "start_cursor": None,
            "end_cursor": None,
        }
