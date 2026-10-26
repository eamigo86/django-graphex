"""The DB and in-memory cursor paths validate a boundary identically."""

from __future__ import annotations

import datetime
import math
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection, models
from graphql import GraphQLError

from django_graphex.paginations.pagination import (
    CursorGraphqlPagination,
    _sqlite_numeric_bounds,
)
from tests.models import Author, ScalarKindsModel

ENCODE = CursorGraphqlPagination.encode_cursor

VALUES = [
    "nan",
    "NaN",
    "sNaN",
    "inf",
    "-Infinity",
    "",
    "  ",
    "abc",
    "1e999",
    "-1e999",
    "1e-999",
    "1e10000",
    "1e10001",
    "1e-10001",
    "1e999999",
    "9" * 400,
    "0x10",
    "１２",
    "1_0",
    "+5",
    " 5",
    "5 ",
    "2.5",
    "2024-13-45",
    "2024-01-02",
    "2024-01-02T00:00:00",
    "2024-01-02 00:00:00",
    "2024-01-02T00:00:00+00:00",
    "2024-01-02T00:00:00+05:30",
    "2024-01-02T00:00:00.000001Z",
    "00000000-0000-0000-0000-000000000002",
    "0000000000000000000000000000000000000002",
    "true",
    "\x00",
]
FIELDS = ["integer", "floating", "decimal", "date", "datetime", "uuid_field"]
PKS = [None, "1", "zzz", "99999999999999999999"]


@pytest.fixture(params=[0, 9], ids=["pk1", "pk10"])
def rows(request: pytest.FixtureRequest) -> list[ScalarKindsModel]:
    """Create five rows with a value of every ordering type.

    The primary keys start at 1 or 10 so no outcome depends on the database pk
    sequence (a cursor pk of "1" is a real row in one run and not in the other).

    Args:
        request: Fixture request carrying the pk offset.

    Returns:
        The created rows.
    """
    author = Author.objects.create(name="a")
    return [
        ScalarKindsModel.objects.create(
            pk=1 + request.param + i,
            author=author,
            char="c",
            integer=i,
            floating=float(i),
            decimal=Decimal(i),
            uuid_field=uuid.UUID(int=i + 1),
            date=datetime.date(2024, 1, 1 + i),
            datetime=datetime.datetime(2024, 1, 1 + i, tzinfo=datetime.timezone.utc),
        )
        for i in range(5)
    ]


def _outcome(source: Any, field: str, token: str) -> str:
    """Run the cursor against one source.

    Args:
        source: A queryset or an in-memory list.
        field: Ordering field.
        token: Encoded cursor.

    Returns:
        "invalid" for a client error, otherwise the ids of the page.
    """
    paginator = CursorGraphqlPagination(ordering=field, page_size=2)
    try:
        page = list(paginator.paginate_queryset(source, first=2, cursor=token))
        paginator.get_page_info(source, first=2, cursor=token)
    except GraphQLError as exc:
        assert str(exc) == "Invalid cursor"
        return "invalid"
    return ",".join(str(row.pk) for row in page)


@pytest.mark.django_db
@pytest.mark.parametrize("field", FIELDS)
def test_cursor_validation_matrix_is_identical_on_both_paths(
    rows: list[ScalarKindsModel], field: str
) -> None:
    """Every boundary is accepted or refused the same way by the DB and memory.

    Args:
        rows: The created rows.
        field: Ordering field under test.
    """
    mismatches = []
    for value in VALUES:
        for pk in PKS:
            token = ENCODE(value, pk)
            db = _outcome(ScalarKindsModel.objects.all(), field, token)
            memory = _outcome(list(ScalarKindsModel.objects.all()), field, token)
            if db != memory:
                mismatches.append((value[:30], pk, db, memory))
    assert not mismatches


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "invalid"),
    [
        # Finite decimals are valid whatever their size; float range is not a rule.
        ("decimal", "1e999", False),
        ("decimal", "9" * 400, False),
        ("decimal", "-1e999", False),
        ("decimal", "1e10000", False),
        # Finer-than-column boundaries are valid and compared exactly; SQLite
        # can physically store finer values and representable ties (see below).
        ("decimal", "1e-999", False),
        ("decimal", "0.001", False),
        ("decimal", "2.50", False),
        ("decimal", "2.5", False),
        ("decimal", "2.5000", False),
        ("decimal", "100E-2", False),
        # Beyond ten to the 10,000th: a client error, not a database error.
        ("decimal", "1e10001", True),
        ("decimal", "1e999999", True),
        ("decimal", "NaN", True),
        ("decimal", "Infinity", True),
        ("floating", "1e999", True),
        ("floating", "nan", True),
        # USE_TZ is on: a naive boundary cannot match the aware column.
        ("datetime", "2024-01-02T00:00:00", True),
        ("datetime", "2024-01-02 00:00:00", True),
        ("datetime", "2024-01-02T00:00:00+00:00", False),
        ("datetime", "2024-01-02T00:00:00+05:30", False),
        ("date", "2024-01-02", False),
    ],
)
def test_pinned_cursor_decisions(
    rows: list[ScalarKindsModel], field: str, value: str, invalid: bool
) -> None:
    """Pin the shared rule for the cases the audit found diverging.

    Args:
        rows: The created rows.
        field: Ordering field under test.
        value: Boundary value.
        invalid: Whether both paths must answer "Invalid cursor".
    """
    token = ENCODE(value, "1")
    for source in (
        ScalarKindsModel.objects.all(),
        list(ScalarKindsModel.objects.all()),
    ):
        assert (_outcome(source, field, token) == "invalid") is invalid


@pytest.mark.django_db
@pytest.mark.parametrize("field", FIELDS)
def test_cursors_encoded_from_real_rows_always_pass(
    rows: list[ScalarKindsModel], field: str
) -> None:
    """A cursor built from a stored row is valid and agrees on both paths.

    Args:
        rows: The created rows.
        field: Ordering field under test.
    """
    ScalarKindsModel.objects.filter(pk=rows[0].pk).update(decimal=Decimal("2.50"))
    ScalarKindsModel.objects.filter(pk=rows[1].pk).update(decimal=Decimal("0.01"))
    paginator = CursorGraphqlPagination(ordering=field, page_size=2)
    for row in ScalarKindsModel.objects.all():
        token = paginator.encode_cursor(getattr(row, field), row.pk)
        db = _outcome(ScalarKindsModel.objects.all(), field, token)
        memory = _outcome(list(ScalarKindsModel.objects.all()), field, token)
        assert db == memory != "invalid"


STORED = ["-0.01", "0.00", "0.01", "1.00", "1.01", "2.99", "3.00"]


def _page(source: Any, ordering: str, token: str) -> tuple[list[int], bool, bool]:
    """Read one page and its page info from a source.

    Args:
        source: A queryset or an in-memory list.
        ordering: Ordering expression, "-" for descending.
        token: Encoded cursor.

    Returns:
        The page pks, hasNextPage and hasPreviousPage.
    """
    paginator = CursorGraphqlPagination(ordering=ordering, page_size=2)
    page = [
        row.pk for row in paginator.paginate_queryset(source, first=2, cursor=token)
    ]
    info = paginator.get_page_info(source, first=2, cursor=token)
    return page, info["has_next_page"], info["has_previous_page"]


@pytest.mark.django_db
@pytest.mark.parametrize("pk", [None, "1", "10", "99999"])
@pytest.mark.parametrize("ordering", ["decimal", "-decimal"])
@pytest.mark.parametrize(
    "boundary", ["1e-999", "-1e-999", "0.001", "-0.001", "1.005", "2.999", "0.0100001"]
)
def test_finer_decimal_boundary_pages_exactly(
    rows: list[ScalarKindsModel], boundary: str, ordering: str, pk: str | None
) -> None:
    """A boundary finer than the column pages exactly, on both paths.

    No stored value equals such a boundary, so the expected page is computed here
    from the exact decimals: strictly greater ascending, strictly less
    descending, ordered by (value, pk), whatever the cursor pk says.

    Args:
        rows: The created rows.
        boundary: The decimal boundary text.
        ordering: Ordering expression under test.
        pk: Cursor pk component.
    """
    for row, text in zip(rows, STORED, strict=False):
        ScalarKindsModel.objects.filter(pk=row.pk).update(decimal=Decimal(text))
    author = rows[0].author
    for offset, text in enumerate(STORED[len(rows) :]):
        ScalarKindsModel.objects.create(
            pk=100 + offset,
            author=author,
            char="c",
            integer=9,
            floating=9.0,
            decimal=Decimal(text),
            uuid_field=uuid.UUID(int=100 + offset),
            date=datetime.date(2025, 1, 1 + offset),
            datetime=datetime.datetime(
                2025, 1, 1 + offset, tzinfo=datetime.timezone.utc
            ),
        )
    stored = [(row.decimal, row.pk) for row in ScalarKindsModel.objects.all()]
    descending = ordering.startswith("-")
    exact = Decimal(boundary)
    after = sorted(
        (
            item
            for item in stored
            if (item[0] < exact if descending else item[0] > exact)
        ),
        reverse=descending,
    )
    expected = [item[1] for item in after[:2]]
    token = ENCODE(boundary, pk)
    db = _page(ScalarKindsModel.objects.all(), ordering, token)
    memory = _page(list(ScalarKindsModel.objects.all()), ordering, token)
    assert db == memory
    assert db[0] == expected
    assert db[1] is (len(after) > 2)


@pytest.mark.django_db
def test_computed_in_memory_decimals_page_through_every_row() -> None:
    """Python-computed decimals finer than the column are not an invalid cursor.

    The in-memory list pages through every row, whatever the column places.
    """
    author = Author.objects.create(name="a")
    items = [
        ScalarKindsModel(
            pk=1 + i,
            author=author,
            char="c",
            integer=i,
            floating=float(i),
            decimal=Decimal(i) * Decimal("1.075"),
            uuid_field=uuid.UUID(int=i + 1),
            date=datetime.date(2024, 1, 1 + i),
            datetime=datetime.datetime(2024, 1, 1 + i, tzinfo=datetime.timezone.utc),
        )
        for i in range(1, 6)
    ]
    seen: list[int] = []
    token = None
    for _ in range(10):
        paginator = CursorGraphqlPagination(ordering="decimal", page_size=2)
        seen += [
            r.pk for r in paginator.paginate_queryset(items, first=2, cursor=token)
        ]
        info = paginator.get_page_info(items, first=2, cursor=token)
        if not info["has_next_page"]:
            break
        token = info["end_cursor"]
    assert seen == [row.pk for row in items]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored", "boundary", "ordering"),
    [
        ("1.075", "1.074", "decimal"),
        ("-1.075", "-1.074", "-decimal"),
    ],
)
@pytest.mark.parametrize("pk", [None, "1"])
def test_sqlite_finer_boundary_includes_unrounded_stored_value(
    stored: str, boundary: str, ordering: str, pk: str | None
) -> None:
    """A finer SQLite value survives the corresponding exact boundary.

    Args:
        stored: Value physically stored with finer precision than the field.
        boundary: Cursor boundary before that value in ordering direction.
        ordering: Ascending or descending Decimal ordering.
        pk: Legacy or composite cursor PK component.
    """
    author = Author.objects.create(name="raw-decimal")
    ScalarKindsModel.objects.create(pk=10, author=author, decimal=Decimal(stored))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT decimal, typeof(decimal) FROM {ScalarKindsModel._meta.db_table} WHERE id = 10"
        )
        raw, storage = cursor.fetchone()
    assert storage == "real"
    assert Decimal.from_float(raw) == Decimal.from_float(float(stored))
    page, _, _ = _page(ScalarKindsModel.objects.all(), ordering, ENCODE(boundary, pk))
    assert page == [10]


@pytest.mark.django_db
@pytest.mark.parametrize("ordering", ["decimal", "-decimal"])
def test_sqlite_representable_fine_boundary_keeps_pk_tie(ordering: str) -> None:
    """An exactly representable fine boundary still advances through PK ties.

    Args:
        ordering: Ascending or descending Decimal ordering.
    """
    author = Author.objects.create(name="fine-ties")
    for pk in (10, 11, 12):
        ScalarKindsModel.objects.create(pk=pk, author=author, decimal=Decimal("0.125"))
    token = ENCODE("0.125", "11")
    page, _, _ = _page(ScalarKindsModel.objects.all(), ordering, token)
    assert page == ([12] if ordering == "decimal" else [10])
    legacy, _, _ = _page(ScalarKindsModel.objects.all(), ordering, ENCODE("0.125"))
    assert legacy == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored", "boundary", "ordering"),
    [
        (2**53 + 1, "9007199254740992.001", "decimal"),
        (2**63 - 1, "9223372036854775806.001", "decimal"),
        (-(2**63), "-9223372036854775807.001", "-decimal"),
    ],
)
def test_sqlite_finer_boundary_keeps_integer_storage(
    stored: int, boundary: str, ordering: str
) -> None:
    """Integer storage near binary64 and int64 edges is not rounded away.

    Args:
        stored: SQLite integer storage value.
        boundary: A finer cursor boundary before the stored value.
        ordering: Ascending or descending Decimal ordering.
    """
    author = Author.objects.create(name="integer-storage")
    ScalarKindsModel.objects.create(pk=10, author=author, decimal=Decimal(stored))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT typeof(decimal) FROM {ScalarKindsModel._meta.db_table} WHERE id = 10"
        )
        assert cursor.fetchone()[0] == "integer"
    paginator = CursorGraphqlPagination(ordering=ordering, page_size=2)
    queryset = paginator.paginate_queryset(
        ScalarKindsModel.objects.all(), first=2, cursor=ENCODE(boundary, "1")
    )
    assert queryset._result_cache is None
    sql, _ = queryset.query.sql_with_params()
    assert "CAST(" not in sql.upper()
    assert list(queryset.values_list("pk", flat=True)) == [10]


@pytest.mark.django_db
def test_sqlite_finer_boundary_rejects_malformed_pk() -> None:
    """Dropping an impossible equality tie does not bypass PK validation.

    The invalid PK must still become a client-facing cursor error.
    """
    paginator = CursorGraphqlPagination(ordering="decimal", page_size=2)
    with pytest.raises(GraphQLError, match="^Invalid cursor$"):
        paginator.paginate_queryset(
            ScalarKindsModel.objects.all(), first=2, cursor=ENCODE("1.074", "bad")
        )


@pytest.mark.django_db
def test_sqlite_finer_boundary_preserves_null_and_aligned_ties() -> None:
    """Finer bounds retain the NULL branch and do not change aligned ties.

    Aligned values must continue using the original Decimal-bound path.
    """
    author = Author.objects.create(name="aligned")
    ScalarKindsModel.objects.create(pk=10, author=author, decimal=Decimal("0.01"))
    ScalarKindsModel.objects.create(pk=11, author=author, decimal=Decimal("0.01"))
    source = ScalarKindsModel.objects.all()
    assert _page(source, "decimal", ENCODE("0.01", "10"))[0] == [11]
    assert _page(source, "decimal", ENCODE("0.0101", "1"))[0] == []
    assert _page(source, "-decimal", ENCODE("0.0101", "99"))[0] == [11, 10]
    bounds = CursorGraphqlPagination._validate_boundary(
        ScalarKindsModel, "decimal", "0.0101", "sqlite"
    )
    assert "decimal__isnull" in str(
        CursorGraphqlPagination._keyset_predicate(
            "decimal", False, "0.0101", "1", bounds
        )
    )


@pytest.mark.django_db(transaction=True)
def test_sqlite_finer_boundary_keeps_nullable_decimal_ordering() -> None:
    """A finer boundary includes trailing NULLs only in ascending order.

    The local nullable table exercises actual SQL filtering in both directions.
    """

    class NullableDecimalRow(models.Model):
        """Local table with a nullable two-place Decimal ordering field."""

        amount = models.DecimalField(max_digits=12, decimal_places=2, null=True)

        class Meta:
            """Attach the local table to the test application."""

            app_label = "tests"

    with connection.schema_editor() as editor:
        editor.create_model(NullableDecimalRow)
    try:
        NullableDecimalRow.objects.create(pk=10, amount=Decimal("1.075"))
        NullableDecimalRow.objects.create(pk=11, amount=None)
        assert _page(NullableDecimalRow.objects.all(), "amount", ENCODE("1.074", "1"))[
            0
        ] == [10, 11]
        assert _page(
            NullableDecimalRow.objects.all(), "-amount", ENCODE("1.076", "99")
        )[0] == [10]
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(NullableDecimalRow)


@pytest.mark.django_db
def test_sqlite_boundary_uses_queryset_database_alias(monkeypatch: Any) -> None:
    """The planner consults the selected queryset alias, not the default.

    Args:
        monkeypatch: Replaces only the vendor lookup for a planned queryset.
    """
    import django_graphex.paginations.pagination as pagination_module

    seen: list[str] = []

    class Connections:
        """Record vendor lookups without opening an additional database."""

        def __getitem__(self, alias: str) -> Any:
            """Return the simulated vendor for the requested alias.

            Args:
                alias: Database alias being planned.

            Returns:
                A minimal connection carrying its vendor.
            """
            seen.append(alias)
            return SimpleNamespace(vendor="sqlite")

    monkeypatch.setattr(pagination_module, "connections", Connections())
    paginator = CursorGraphqlPagination(ordering="decimal", page_size=2)
    planned = paginator.paginate_queryset(
        ScalarKindsModel.objects.using("cursor_replica"),
        first=2,
        cursor=ENCODE("1.074", "1"),
    )
    assert seen == ["cursor_replica"]
    assert planned._result_cache is None


def test_other_vendor_keeps_declared_scale_bounds() -> None:
    """Non-SQLite planning retains the preexisting column-scale bounds.

    This avoids changing the existing contract for other database vendors.
    """
    bounds = CursorGraphqlPagination._validate_boundary(
        ScalarKindsModel, "decimal", "1.074", "postgresql"
    )
    assert bounds == (Decimal("1.08"), Decimal("1.07"), False)


@pytest.mark.parametrize(
    ("boundary", "lower", "upper", "exact"),
    [
        ("0.125", 0.125, 0.125, True),
        ("1e-999", 0, 5e-324, False),
        ("-1e-999", -5e-324, 0, False),
        ("9007199254740992.001", 2**53, 2**53 + 1, False),
        ("9223372036854775807.001", 2**63 - 1, float(2**63), False),
        (
            "-9223372036854775808.001",
            math.nextafter(float(-(2**63)), -math.inf),
            -(2**63),
            False,
        ),
        (
            "1" + "0" * 400 + ".001",
            math.nextafter(math.inf, -math.inf),
            math.inf,
            False,
        ),
        (
            "-1" + "0" * 400 + ".001",
            -math.inf,
            math.nextafter(-math.inf, math.inf),
            False,
        ),
    ],
)
def test_sqlite_numeric_bounds_use_real_and_integer_neighbors(
    boundary: str, lower: int | float, upper: int | float, exact: bool
) -> None:
    """Bracketing uses both SQLite storage types, including int64 endpoints.

    Args:
        boundary: Exact Decimal cursor value.
        lower: Expected nearest lower representable value.
        upper: Expected nearest upper representable value.
        exact: Whether SQLite can represent the boundary itself.
    """
    got_upper, got_lower, got_exact = _sqlite_numeric_bounds(Decimal(boundary))
    assert (got_lower, got_upper, got_exact) == (lower, upper, exact)


@pytest.mark.django_db
@pytest.mark.parametrize("pk", [None, "1"])
@pytest.mark.parametrize(
    ("boundary", "ordering", "expected"),
    [
        ("1" + "0" * 400 + ".001", "decimal", []),
        ("1" + "0" * 400 + ".001", "-decimal", [11, 10]),
        ("-1" + "0" * 400 + ".001", "decimal", [10, 11]),
        ("-1" + "0" * 400 + ".001", "-decimal", []),
    ],
)
def test_sqlite_finite_finer_boundaries_beyond_float_range(
    boundary: str, ordering: str, expected: list[int], pk: str | None
) -> None:
    """Finite finer cursors outside binary64 range still paginate correctly.

    Args:
        boundary: Cursor value whose magnitude overflows a Python float.
        ordering: Ascending or descending Decimal ordering.
        expected: Primary keys after the cursor in the selected direction.
        pk: Legacy or composite cursor PK component.
    """
    author = Author.objects.create(name="large-cursor")
    for offset in (0, 1):
        ScalarKindsModel.objects.create(
            pk=10 + offset, author=author, decimal=Decimal(offset)
        )
    page, has_next, _ = _page(
        ScalarKindsModel.objects.all(), ordering, ENCODE(boundary, pk)
    )
    assert page == expected
    assert has_next is False
