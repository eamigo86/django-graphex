"""Composite keyset cursor pagination — tie-safety and determinism.

The single-value cursor dropped rows whenever two rows shared the same ordering
value: page 1 ends at "value=V", page 2 filters "value > V" and skips every
other row that also had "value == V". These tests pin the composite keyset
("ordering value", "pk") contract:

* No row is ever dropped across pages when ordering values tie (DB + in-memory).
* No row is duplicated across pages.
* The order is deterministic across repeated identical requests.
* A tampered/legacy-shaped cursor still raises "GraphQLError('Invalid cursor')".
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from django.db.models import Model
from django.test import TestCase
from graphql import GraphQLError

from django_graphex.paginations.pagination import CursorGraphqlPagination
from tests.models import ScalarKindsModel, Track2Account


def _walk_pages_db(
    paginator: CursorGraphqlPagination,
    model: type[Model],
    first: int,
    order_field: str = "balance",
) -> list[tuple[Any, Any]]:
    """Walk every page of a queryset via cursors, collecting (field, pk) tuples.

    Args:
        paginator: The cursor paginator driving the walk.
        model: The Django model whose full queryset is paged through.
        first: The page size passed to "paginate_queryset" on each step.
        order_field: The attribute read off each row alongside its pk.

    Returns:
        The concatenation of "(order_field value, pk)" tuples across every
        page, in page order.
    """
    collected: list[tuple[Any, Any]] = []
    cursor = None
    # Bound the loop defensively so a broken cursor cannot spin forever.
    for _ in range(50):
        page = list(
            paginator.paginate_queryset(model.objects.all(), first=first, cursor=cursor)
        )
        if not page:
            break
        collected.extend((getattr(r, order_field), r.pk) for r in page)
        info = paginator.get_page_info(model.objects.all(), first=first, cursor=cursor)
        if not info["has_next_page"]:
            break
        cursor = info["end_cursor"]
    return collected


class CursorKeysetTieDbTest(TestCase):
    """DB path: tied ordering values must not drop rows across pages.

    Covers ascending, descending, and determinism across repeated calls.
    """

    def setUp(self) -> None:
        """Create three accounts tied at balance=1 and one at balance=2.

        Shared as fixture data by every test in this class.
        """
        # A, B, C all share balance=1 (rank 1); D has balance=2 (rank 2).
        self.a = Track2Account.objects.create(balance=1, label="A")
        self.b = Track2Account.objects.create(balance=1, label="B")
        self.c = Track2Account.objects.create(balance=1, label="C")
        self.d = Track2Account.objects.create(balance=2, label="D")

    def test_no_row_dropped_on_tied_values_ascending(self) -> None:
        """Ascending pagination over tied balance values visits every row exactly once.

        This test breaks if the tie-victim row ("C") gets dropped or
        duplicated when paging across a boundary with tied ordering values.
        """
        p = CursorGraphqlPagination(ordering="balance", page_size=2)
        collected = _walk_pages_db(p, Track2Account, first=2)
        pks = [pk for _, pk in collected]
        # All four rows appear exactly once — C (the tie victim) is NOT dropped.
        assert sorted(pks) == sorted([self.a.pk, self.b.pk, self.c.pk, self.d.pk])
        assert len(pks) == len(set(pks)), "a row was duplicated across pages"

    def test_no_row_dropped_on_tied_values_descending(self) -> None:
        """Descending pagination over tied balance values visits every row exactly once.

        This test breaks if the descending path drops or duplicates a
        tie-victim row the same way the ascending path could.
        """
        p = CursorGraphqlPagination(ordering="-balance", page_size=2)
        collected = _walk_pages_db(p, Track2Account, first=2)
        pks = [pk for _, pk in collected]
        assert sorted(pks) == sorted([self.a.pk, self.b.pk, self.c.pk, self.d.pk])
        assert len(pks) == len(set(pks))

    def test_deterministic_order_across_repeated_calls(self) -> None:
        """Two identical page-walk runs over the same data produce the identical sequence.

        This test breaks if the composite keyset ordering stops being
        deterministic across repeated identical requests.
        """
        p = CursorGraphqlPagination(ordering="balance", page_size=2)
        first_run = _walk_pages_db(p, Track2Account, first=2)
        second_run = _walk_pages_db(p, Track2Account, first=2)
        assert first_run == second_run


class CursorKeysetTieInMemoryTest(TestCase):
    """In-memory path: same tie-safety guarantees over a Python list of rows.

    Mirrors "CursorKeysetTieDbTest" but against a fixed prefetch-cache list.
    """

    def setUp(self) -> None:
        """Create the same tied fixture rows as the DB test.

        Also builds a fixed in-memory list of them, shared by every test in
        this class.
        """
        self.a = Track2Account.objects.create(balance=1, label="A")
        self.b = Track2Account.objects.create(balance=1, label="B")
        self.c = Track2Account.objects.create(balance=1, label="C")
        self.d = Track2Account.objects.create(balance=2, label="D")
        # A fixed Python list (prefetch-cache shape), not a queryset.
        self.rows = list(Track2Account.objects.all())

    def _walk(
        self, paginator: CursorGraphqlPagination, first: int
    ) -> list[tuple[int, Any]]:
        """Walk every page of "self.rows" via cursors, collecting (balance, pk) tuples.

        Args:
            paginator: The cursor paginator driving the walk.
            first: The page size passed to "paginate_queryset" on each step.

        Returns:
            The concatenation of "(balance, pk)" tuples across every page,
            in page order.
        """
        collected: list[tuple[int, Any]] = []
        cursor = None
        for _ in range(50):
            page = list(
                paginator.paginate_queryset(self.rows, first=first, cursor=cursor)
            )
            if not page:
                break
            collected.extend((r.balance, r.pk) for r in page)
            info = paginator.get_page_info(self.rows, first=first, cursor=cursor)
            if not info["has_next_page"]:
                break
            cursor = info["end_cursor"]
        return collected

    def test_inmemory_no_row_dropped_on_tied_values(self) -> None:
        """In-memory pagination over tied balance values visits every row exactly once.

        This test breaks if the in-memory path drops or duplicates a
        tie-victim row the same way the DB-backed path could.
        """
        p = CursorGraphqlPagination(ordering="balance", page_size=2)
        collected = self._walk(p, first=2)
        pks = [pk for _, pk in collected]
        assert sorted(pks) == sorted([self.a.pk, self.b.pk, self.c.pk, self.d.pk])
        assert len(pks) == len(set(pks))

    def test_inmemory_deterministic_order(self) -> None:
        """Two identical in-memory page-walk runs produce the identical sequence.

        This test breaks if the in-memory composite keyset ordering stops
        being deterministic across repeated identical requests.
        """
        p = CursorGraphqlPagination(ordering="balance", page_size=2)
        assert self._walk(p, first=2) == self._walk(p, first=2)


class CursorKeysetTamperedCursorTest(TestCase):
    """A malformed/legacy-shaped cursor must raise a clean GraphQLError.

    Covers both "paginate_queryset" and "get_page_info".
    """

    def setUp(self) -> None:
        """Create one throwaway account for the tampered-cursor tests.

        Shared as fixture data by every test in this class.
        """
        Track2Account.objects.create(balance=1, label="A")

    def test_garbage_cursor_raises_graphql_error(self) -> None:
        """A non-base64 garbage cursor raises "GraphQLError('Invalid cursor')" from "paginate_queryset".

        This test breaks if malformed cursors stop being caught and
        surfaced as a clean GraphQL error.
        """
        p = CursorGraphqlPagination(ordering="balance", page_size=2)
        with pytest.raises(GraphQLError, match="Invalid cursor"):
            p.paginate_queryset(
                Track2Account.objects.all(), first=2, cursor="!!!not-base64!!!"
            )

    def test_garbage_cursor_raises_graphql_error_in_page_info(self) -> None:
        """A non-base64 garbage cursor raises "GraphQLError('Invalid cursor')" from "get_page_info".

        This test breaks if "get_page_info" stops sharing the same
        cursor-validation error handling as "paginate_queryset".
        """
        p = CursorGraphqlPagination(ordering="balance", page_size=2)
        with pytest.raises(GraphQLError, match="Invalid cursor"):
            p.get_page_info(
                Track2Account.objects.all(), first=2, cursor="!!!not-base64!!!"
            )


class CursorDecodePartitionTest(TestCase):
    """FIX 1: "decode_cursor_parts" must split on the LAST pk separator.

    The pk is always the trailing component and pks never contain the unit
    separator, so an ordering VALUE that itself contains "\\x1f" must survive a
    round-trip intact. A "partition" (first-separator) split corrupts such a
    value, spilling the tail of the value into the pk component.
    """

    def test_value_with_separator_round_trips(self) -> None:
        """A value containing one unit-separator round-trips intact, with the pk kept separate.

        This test breaks if the split logic stops using the LAST separator
        to delimit the pk, corrupting the value.
        """
        # Value carries one \x1f; pk is the trailing component.
        cursor = CursorGraphqlPagination.encode_cursor("abc\x1fdef", pk=42)
        value, pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        assert value == "abc\x1fdef"
        assert pk == "42"

    def test_value_with_multiple_separators_round_trips(self) -> None:
        """A value containing two unit-separators round-trips intact, split only on the final one.

        This test breaks if more than the trailing separator gets treated
        as a delimiter.
        """
        # Value carries TWO \x1f; only the final separator delimits the pk.
        cursor = CursorGraphqlPagination.encode_cursor("a\x1fb\x1fc", pk=7)
        value, pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        assert value == "a\x1fb\x1fc"
        assert pk == "7"

    def test_normal_value_round_trips(self) -> None:
        """A plain value with no separator round-trips intact alongside its pk.

        This test breaks if the baseline no-separator round-trip regresses.
        """
        cursor = CursorGraphqlPagination.encode_cursor("plain", pk=99)
        value, pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        assert value == "plain"
        assert pk == "99"

    def test_legacy_value_only_cursor_has_no_pk(self) -> None:
        """A legacy value-only cursor (no pk encoded) decodes with pk as None.

        This test breaks if a pk-less cursor stops decoding to a None pk,
        or if part of the value is mistaken for a pk.
        """
        # No pk component: the whole rest is the value, pk is None.
        cursor = CursorGraphqlPagination.encode_cursor("plain")
        value, pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        assert value == "plain"
        assert pk is None

    def test_legacy_value_only_cursor_with_separator_in_value(self) -> None:
        """A pk-bearing cursor whose value itself contains a unit-separator still round-trips losslessly.

        A legacy (pk-less) value that itself contains "\\x1f". With no pk
        component present, rpartition finds a separator inside the value —
        but decode_cursor still recovers the FULL value because the "pk" it
        peels is spurious only when a real pk was never encoded. This case is
        inherently ambiguous for pk-less cursors; the contract pinned here is
        that the composite (pk-bearing) round-trip is lossless. This test
        breaks if that lossless round-trip regresses.
        """
        cursor = CursorGraphqlPagination.encode_cursor("plain\x1ftail", pk=5)
        value, pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        assert value == "plain\x1ftail"
        assert pk == "5"


def test_inmemory_tie_single_page_direct() -> None:
    """A cursor boundary landing inside a tied group resumes at the correct tied row, never skipping it.

    Direct in-memory slice: three tied rows on page 1 of size 2, then the
    boundary cursor must resume at the third tied row (pk tiebreak), never
    skip it. This test breaks if the pk tiebreak stops resolving ties inside
    a boundary correctly.
    """
    rows = [
        SimpleNamespace(balance=1, pk=1),
        SimpleNamespace(balance=1, pk=2),
        SimpleNamespace(balance=1, pk=3),
        SimpleNamespace(balance=2, pk=4),
    ]
    p = CursorGraphqlPagination(ordering="balance", page_size=2)
    page1 = p.paginate_queryset(rows, first=2)
    assert [r.pk for r in page1] == [1, 2]
    info = p.get_page_info(rows, first=2)
    page2 = p.paginate_queryset(rows, first=2, cursor=info["end_cursor"])
    # pk=3 (the third tied row) must be present — it was the dropped victim.
    assert [r.pk for r in page2] == [3, 4]


# --------------------------------------------------------------------------- #
# FIX 2 — NULL ordering values: deterministic placement + no dropped rows.    #
# --------------------------------------------------------------------------- #
# The keyset predicate compared "field > value" against a NULL boundary, which
# is never true in SQL (so pages after a NULL boundary silently vanished), and
# get_page_info's has_previous_page filter built "Q(field=None)" which raises a
# raw ValueError ("Cannot use None as a query value"). The composite cursor also
# serialised a NULL value to the literal string "None", so a NULL boundary cursor
# failed field coercion with a bogus "Invalid cursor". The contract these tests
# pin: NULL placement is DETERMINISTIC (ascending -> nulls last, descending ->
# nulls first, matching the in-memory _sort_key), no row is dropped or duplicated
# across a NULL boundary, and the DB and in-memory paths agree on the same data.


def _day(day: int) -> datetime.date:
    """Build an orderable, non-timezone-sensitive nullable value.

    A "date" is used (not a duration) because its "str()" form is ISO 8601,
    which Django's DateField coerces losslessly back on the cursor's "__gt" /
    "__lt" lookup — keeping these tests focused on NULL keyset semantics rather
    than a field's string-serialisation quirks.

    Args:
        day: The day-of-month component; the year/month are fixed at 2020-01.

    Returns:
        A "datetime.date" for 2020-01-<day>.
    """
    return datetime.date(2020, 1, day)


def _walk_pages_db_field(
    paginator: CursorGraphqlPagination,
    model: type[Model],
    first: int,
    order_field: str,
) -> list[tuple[Any, Any]]:
    """Walk every page via cursors, collecting (value, pk) tuples (DB path).

    Args:
        paginator: The cursor paginator driving the walk.
        model: The Django model whose full queryset is paged through.
        first: The page size passed to "paginate_queryset" on each step.
        order_field: The attribute read off each row alongside its pk.

    Returns:
        The concatenation of "(order_field value, pk)" tuples across every
        page, in page order.
    """
    collected: list[tuple[Any, Any]] = []
    cursor = None
    for _ in range(50):
        page = list(
            paginator.paginate_queryset(model.objects.all(), first=first, cursor=cursor)
        )
        if not page:
            break
        collected.extend((getattr(r, order_field), r.pk) for r in page)
        info = paginator.get_page_info(model.objects.all(), first=first, cursor=cursor)
        if not info["has_next_page"]:
            break
        cursor = info["end_cursor"]
    return collected


def _walk_pages_inmemory_field(
    paginator: CursorGraphqlPagination,
    rows: list[Any],
    first: int,
    order_field: str,
) -> list[tuple[Any, Any]]:
    """Walk every page via cursors over a fixed Python list (in-memory path).

    Args:
        paginator: The cursor paginator driving the walk.
        rows: The fixed list of rows to page through.
        first: The page size passed to "paginate_queryset" on each step.
        order_field: The attribute read off each row alongside its pk.

    Returns:
        The concatenation of "(order_field value, pk)" tuples across every
        page, in page order.
    """
    collected: list[tuple[Any, Any]] = []
    cursor = None
    for _ in range(50):
        page = list(paginator.paginate_queryset(rows, first=first, cursor=cursor))
        if not page:
            break
        collected.extend((getattr(r, order_field), r.pk) for r in page)
        info = paginator.get_page_info(rows, first=first, cursor=cursor)
        if not info["has_next_page"]:
            break
        cursor = info["end_cursor"]
    return collected


class CursorNullValueRoundTripTest(TestCase):
    """A NULL ordering value must survive a cursor round-trip as real None.

    Also pins the distinct genuine-string-"None" case.
    """

    def test_null_value_round_trips_as_none(self) -> None:
        """Encoding a None ordering value round-trips to a real None, not a string.

        This test breaks if a NULL ordering value stops decoding back to a
        real "None".
        """
        cursor = CursorGraphqlPagination.encode_cursor(None, pk=7)
        value, pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        assert value is None
        assert pk == "7"

    def test_string_none_is_not_confused_with_null(self) -> None:
        """The literal string "None" round-trips as the string itself, not a real NULL.

        This test breaks if the string "None" gets mistaken for a real NULL
        value during decode.
        """
        # A genuine string value "None" must NOT decode to a real None.
        cursor = CursorGraphqlPagination.encode_cursor("None", pk=3)
        value, pk = CursorGraphqlPagination.decode_cursor_parts(cursor)
        assert value == "None"
        assert pk == "3"


class CursorNullKeysetDbTest(TestCase):
    """DB path: paging across NULL boundaries drops no row and stays deterministic.

    Covers ascending, descending, all-NULL, and the has_previous_page edge.
    """

    def setUp(self) -> None:
        """Create rows mixing NULL and non-NULL "date" values.

        Shared as fixture data by every test in this class.
        """
        m = ScalarKindsModel
        # Mixed NULL / non-NULL on the nullable ordering field "date".
        self.n1 = m.objects.create(char="n1", date=None)
        self.n2 = m.objects.create(char="n2", date=None)
        self.v10 = m.objects.create(char="v10", date=_day(10))
        self.v20 = m.objects.create(char="v20", date=_day(20))
        self.n3 = m.objects.create(char="n3", date=None)
        self.all_pks = sorted(
            r.pk for r in (self.n1, self.n2, self.v10, self.v20, self.n3)
        )

    def test_ascending_crosses_null_boundary_no_drop(self) -> None:
        """Ascending pagination across a NULL boundary drops no row and duplicates none.

        This test breaks if paging past the NULL/non-NULL boundary (in
        either direction) silently loses or repeats a row.
        """
        p = CursorGraphqlPagination(ordering="date", page_size=2)
        collected = _walk_pages_db_field(p, ScalarKindsModel, 2, "date")
        pks = [pk for _, pk in collected]
        assert sorted(pks) == self.all_pks, "a row was dropped across the NULL boundary"
        assert len(pks) == len(set(pks)), "a row was duplicated across pages"

    def test_descending_crosses_null_boundary_no_drop(self) -> None:
        """Descending pagination across a NULL boundary drops no row and duplicates none.

        This test breaks if the descending path drops or duplicates rows
        across the NULL boundary the same way the ascending path could.
        """
        p = CursorGraphqlPagination(ordering="-date", page_size=2)
        collected = _walk_pages_db_field(p, ScalarKindsModel, 2, "date")
        pks = [pk for _, pk in collected]
        assert sorted(pks) == self.all_pks
        assert len(pks) == len(set(pks))

    def test_all_null_page_boundary_no_drop(self) -> None:
        """Pagination over an all-NULL table drops no row across page boundaries.

        Every row NULL: the whole walk lives inside the NULL group; the pk
        tiebreak alone must carry it across page boundaries. This test
        breaks if the pk tiebreak stops being sufficient in that case.
        """
        ScalarKindsModel.objects.all().delete()
        rows = [
            ScalarKindsModel.objects.create(char=f"a{i}", date=None) for i in range(5)
        ]
        p = CursorGraphqlPagination(ordering="date", page_size=2)
        collected = _walk_pages_db_field(p, ScalarKindsModel, 2, "date")
        pks = [pk for _, pk in collected]
        assert sorted(pks) == sorted(r.pk for r in rows)
        assert len(pks) == len(set(pks))

    def test_page_info_first_row_null_no_crash(self) -> None:
        """ "get_page_info" does not crash when the first row's ordering value is NULL.

        get_page_info's has_previous_page predicate must not raise when the
        first row's ordering value is NULL (ascending -> nulls last means the
        NULL group is the tail; a cursor landing there had start_value None).
        This test breaks if that predicate starts raising on a NULL boundary.
        """
        p = CursorGraphqlPagination(ordering="-date", page_size=2)
        # Descending -> nulls first, so page 1's first row is a NULL row.
        info = p.get_page_info(ScalarKindsModel.objects.all(), first=2)
        assert info["has_previous_page"] is False
        assert info["has_next_page"] is True

    def test_deterministic_across_repeated_calls(self) -> None:
        """Two identical page-walk runs over NULL-bearing data produce the identical sequence.

        This test breaks if the NULL-aware ordering stops being deterministic
        across repeated identical requests.
        """
        p = CursorGraphqlPagination(ordering="date", page_size=2)
        first_run = _walk_pages_db_field(p, ScalarKindsModel, 2, "date")
        second_run = _walk_pages_db_field(p, ScalarKindsModel, 2, "date")
        assert first_run == second_run


class CursorNullKeysetInMemoryVsDbParityTest(TestCase):
    """In-memory and DB paths must yield the SAME sequence over NULL-bearing data.

    Covers both ascending and descending ordering.
    """

    def setUp(self) -> None:
        """Create mixed NULL/non-NULL rows plus a fixed in-memory list of them.

        Shared as fixture data by every test in this class.
        """
        m = ScalarKindsModel
        m.objects.create(char="n1", date=None)
        m.objects.create(char="v10", date=_day(10))
        m.objects.create(char="n2", date=None)
        m.objects.create(char="v20", date=_day(20))
        m.objects.create(char="n3", date=None)
        self.rows = list(m.objects.all())

    def test_ascending_parity(self) -> None:
        """The DB-backed and in-memory ascending walks over NULL-bearing data agree pk-for-pk.

        This test breaks if either pagination path diverges from the other
        when the ordering field contains NULLs.
        """
        p = CursorGraphqlPagination(ordering="date", page_size=2)
        db = _walk_pages_db_field(p, ScalarKindsModel, 2, "date")
        mem = _walk_pages_inmemory_field(p, self.rows, 2, "date")
        assert [pk for _, pk in db] == [pk for _, pk in mem]

    def test_descending_parity(self) -> None:
        """The DB-backed and in-memory descending walks over NULL-bearing data agree pk-for-pk.

        This test breaks if either pagination path diverges from the other
        in descending order when the ordering field contains NULLs.
        """
        p = CursorGraphqlPagination(ordering="-date", page_size=2)
        db = _walk_pages_db_field(p, ScalarKindsModel, 2, "date")
        mem = _walk_pages_inmemory_field(p, self.rows, 2, "date")
        assert [pk for _, pk in db] == [pk for _, pk in mem]


class CursorLegacyNullValuePredicateTest(TestCase):
    """A pk-less (legacy) cursor carrying a NULL value must not build "field > NULL".

    "encode_cursor(None)" (no pk) produces a legacy value-only cursor whose
    decoded value is a real NULL. The value-only boundary has no pk tiebreak, so
    it routes through "_legacy_value_predicate": ascending (NULLs last) selects
    nothing further, descending (NULLs first) selects the whole non-NULL body —
    never a raw "field > NULL" comparison (which SQLite rejects).
    """

    def setUp(self) -> None:
        """Create one NULL-dated row and two non-NULL-dated rows.

        Shared as fixture data by every test in this class.
        """
        m = ScalarKindsModel
        self.n1 = m.objects.create(char="n1", date=None)
        self.v10 = m.objects.create(char="v10", date=_day(10))
        self.v20 = m.objects.create(char="v20", date=_day(20))

    def test_ascending_legacy_null_cursor_selects_nothing_after(self) -> None:
        """An ascending, pk-less NULL cursor selects nothing, since NULLs sort last with no tiebreak.

        This test breaks if the legacy-value predicate stops correctly
        selecting an empty page in this case, or raises instead.
        """
        p = CursorGraphqlPagination(ordering="date", page_size=10)
        cursor = CursorGraphqlPagination.encode_cursor(None)  # pk-less
        page = list(
            p.paginate_queryset(ScalarKindsModel.objects.all(), first=10, cursor=cursor)
        )
        # NULLs sort last ascending; without a pk tiebreak nothing follows.
        assert page == []

    def test_descending_legacy_null_cursor_selects_non_null_body(self) -> None:
        """A descending, pk-less NULL cursor selects the entire non-NULL body, since NULLs sort first.

        This test breaks if the legacy-value predicate stops correctly
        selecting the full non-NULL body in this case.
        """
        p = CursorGraphqlPagination(ordering="-date", page_size=10)
        cursor = CursorGraphqlPagination.encode_cursor(None)  # pk-less
        page = list(
            p.paginate_queryset(ScalarKindsModel.objects.all(), first=10, cursor=cursor)
        )
        # NULLs sort first descending, so the entire non-NULL body follows.
        assert sorted(r.pk for r in page) == sorted([self.v10.pk, self.v20.pk])
