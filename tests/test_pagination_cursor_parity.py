"""The DB and in-memory cursor paths validate a boundary identically."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

import pytest
from graphql import GraphQLError

from django_graphex.paginations.pagination import CursorGraphqlPagination
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
        # More fractional digits than decimal_places=2 can never match a stored
        # value: refused on both paths. Trailing zeros do not count.
        ("decimal", "1e-999", True),
        ("decimal", "0.001", True),
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
